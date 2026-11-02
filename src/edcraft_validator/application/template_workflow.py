"""Domain-agnostic template authoring, validation, and expansion."""

import copy
import json
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaError
from pydantic import BaseModel, ValidationError

from edcraft_validator.application.authoring_contracts import (
    AuthoringError,
    AuthoringFailure,
    AuthoringProgress,
    AuthoringResult,
    CheckExecution,
    GenerationAttempt,
)
from edcraft_validator.application.ports import ToolClient
from edcraft_validator.artifact_contracts import (
    TemplateAuthoringProvenance,
    ValidatedTemplateArtifact,
)
from edcraft_validator.domains.domain_contract import DomainModule
from edcraft_validator.llm.llm_contracts import (
    CheckPlanResponse,
    ModelProvider,
    PlannedGenerationResponse,
    ToolCatalogueSnapshot,
)
from edcraft_validator.llm.llm_errors import (
    GenerationError,
    GenerationSchemaError,
    GenerationTransportError,
)
from edcraft_validator.llm.tool_context import (
    constrained_check_plan,
    generation_messages,
)
from edcraft_validator.llm.usage import MeasuredProvider, summarize_usage
from edcraft_validator.mcp.catalogue import (
    ToolCatalogue,
    ToolCatalogueError,
    check_definitions,
    resolve_domain_tools,
)
from edcraft_validator.validation.check_contracts import ToolEvidence

REVISION_POLICY = "full-candidate-v1"


def _generate_author(provider, request):
    """One bounded transport retry for author calls, never for judge assessments."""
    try:
        return provider.generate(request)
    except GenerationTransportError as exc:
        status = getattr(exc.__cause__, "status_code", None)
        if status is not None and status not in {408, 409, 429} and status < 500:
            raise
        return provider.generate(request)


@dataclass
class _AuthoringJob:
    request: BaseModel | None
    domain: DomainModule
    provider: MeasuredProvider
    result: AuthoringResult
    validating: bool
    max_attempts: int
    stage: str = "configuration"
    observer: Callable[[AuthoringProgress], None] | None = None

    def generate(self, operation, *args, phase="generating", **kwargs):
        self.stage = "generation"
        self.notify(phase)
        started = time.perf_counter()
        try:
            return operation(*args, **kwargs)
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000
            self.result.generation_duration_ms += elapsed_ms

    def notify(self, phase):
        if self.observer is None:
            return
        attempt = len(self.result.attempts) + (phase in {"generating", "correcting"})
        progress = AuthoringProgress(phase=phase, attempt=attempt)
        try:
            self.observer(progress)
        except Exception:
            logging.getLogger(__name__).exception("Authoring progress observer failed")


class TemplateApplication:
    """Run the same template workflow for any registered domain."""

    def __init__(
        self,
        *,
        tool_catalogue: ToolCatalogue | None = None,
        tool_client: ToolClient | None = None,
        max_correction_attempts: int = 3,
    ) -> None:
        self.tool_catalogue = tool_catalogue
        self.tool_client = tool_client
        if (
            type(max_correction_attempts) is not int
            or not 0 <= max_correction_attempts <= 3
        ):
            raise ValueError("max_correction_attempts must be an integer from 0 to 3")
        self.max_correction_attempts = max_correction_attempts

    def create_validated_template(
        self, request, *, domain, provider, on_catalogue_resolved=None
    ):
        """Compatibility entry point: failures retain their reviewable result."""
        result = self.author_template(
            request,
            domain=domain,
            provider=provider,
            on_catalogue_resolved=on_catalogue_resolved,
        )
        if result.artifact is None:
            raise AuthoringFailure(result)
        return result.artifact

    def author_template(
        self,
        request: BaseModel,
        *,
        domain: DomainModule,
        provider: ModelProvider,
        on_catalogue_resolved: Callable[[ToolCatalogueSnapshot], None] | None = None,
        on_progress: Callable[[AuthoringProgress], None] | None = None,
    ) -> AuthoringResult:
        return self._check_template(
            request,
            domain=domain,
            provider=provider,
            on_catalogue_resolved=on_catalogue_resolved,
            on_progress=on_progress,
        )

    def validate_template(
        self,
        candidate: BaseModel,
        *,
        domain: DomainModule,
        provider: ModelProvider,
        on_catalogue_resolved=None,
        on_progress=None,
    ) -> AuthoringResult:
        """Ask the model to check an existing candidate without rewriting it."""
        candidate = domain.candidate_model.model_validate(candidate).model_copy(
            deep=True
        )
        return self._check_template(
            None,
            domain=domain,
            provider=provider,
            initial_candidate=candidate,
            on_catalogue_resolved=on_catalogue_resolved,
            on_progress=on_progress,
        )

    def _check_template(
        self,
        request,
        *,
        domain,
        provider,
        initial_candidate=None,
        on_catalogue_resolved=None,
        on_progress=None,
    ) -> AuthoringResult:
        started = time.perf_counter()
        validating = initial_candidate is not None
        request = None if validating else request.model_copy(deep=True)
        payload = (
            {"operation": "validate"} if validating else request.model_dump(mode="json")
        )
        measured = MeasuredProvider(provider)
        result = AuthoringResult(
            status="error",
            provider=provider.provider,
            model=provider.model,
            domain=domain.name,
            request=copy.deepcopy(payload),
            prompt_version="",
            revision_policy=None if validating else REVISION_POLICY,
            fixed_plan=[],
            tool_catalogue=[],
        )
        job = _AuthoringJob(
            request,
            domain,
            measured,
            result,
            validating,
            1 if validating else self.max_correction_attempts + 1,
            observer=on_progress,
        )
        try:
            result.provider_settings = copy.deepcopy(
                getattr(provider, "generation_settings", lambda: {})()
            )
            with self._tool_connection() as client:
                return self._prepare_and_run(
                    job, initial_candidate, client, on_catalogue_resolved
                )
        except Exception as exc:
            self._record_failure(result, exc, job.stage)
            return result
        finally:
            result.duration_ms = (time.perf_counter() - started) * 1000
            result.model_calls = measured.calls
            result.usage = summarize_usage(measured.calls)

    def _prepare_and_run(self, job, initial_candidate, client, observer):
        tools = resolve_domain_tools(job.domain.name, self.tool_catalogue or client)
        snapshot = ToolCatalogueSnapshot.from_definitions(tools)
        job.result.tool_catalogue = snapshot.summaries()
        if observer is not None:
            observer(snapshot)
        generation_request = (
            job.domain.validation_request(initial_candidate)
            if job.validating
            else job.domain.generation_request(job.request)
        )
        generation_request = replace(
            generation_request,
            offered_tool_names=snapshot.names,
            tool_catalogue=snapshot,
        )
        job.result.prompt_version = generation_request.prompt_version
        response = job.generate(_generate_author, job.provider, generation_request)
        self._validate_response(response, generation_request, plan_only=job.validating)
        response = response.model_copy(deep=True)
        names = tuple(check.name for check in response.checks)
        job.result.fixed_plan = list(names)
        job.result.check_plan = [
            check.model_copy(deep=True) for check in response.checks
        ]
        definitions = check_definitions(tools)
        planned_arguments = {
            check.name: json.dumps(check.arguments) for check in response.checks
        }

        for number in range(1, job.max_attempts + 1):
            job.stage = "template_building"
            candidate = (
                initial_candidate
                if job.validating
                else job.domain.build_candidate(job.request, response.proposal)
            )
            attempt = self._build_attempt(number, candidate, names)
            job.result.attempts.append(attempt)
            job.stage = "checking"
            job.notify("checking")
            self._run_checks(
                attempt,
                names,
                definitions,
                planned_arguments,
                client,
                domain=job.domain,
                request=job.request,
                candidate=candidate,
            )
            if not self._should_revise(attempt, number, job.max_attempts):
                job.stage = "finalization"
                job.notify("finalizing")
                return self._finish_attempt(job, attempt, candidate)
            response = job.generate(
                self._revise_proposal,
                generation_request,
                response,
                attempt,
                names,
                job.provider,
                author_request=job.result.request,
                remaining_revisions=job.max_attempts - number,
                phase="correcting",
            )
        raise AssertionError("Authoring loop must return within its attempt limit")

    @staticmethod
    def _should_revise(attempt, number, max_attempts):
        terminal_error = any(
            entry.evidence is not None
            and entry.evidence.status == "error"
            and entry.evidence.details.get("retryable") is False
            for entry in attempt.executions
        )
        return not attempt.passed and not terminal_error and number < max_attempts

    @staticmethod
    def _record_failure(result, exc, stage):
        result.status, result.artifact = "error", None
        result.reason = f"{type(exc).__name__}: {exc}"
        code = type(exc).__name__
        if isinstance(exc, GenerationError):
            code = exc.category
        elif isinstance(exc, ToolCatalogueError):
            code = "MCP_CATALOGUE_ERROR"
        result.failure = AuthoringError(stage=stage, code=code)

    @staticmethod
    def _build_attempt(number, candidate, plan) -> GenerationAttempt:
        """Record the exact candidate; also used by offline research runners."""
        return GenerationAttempt(
            number=number,
            candidate=candidate.model_dump(mode="json"),
            pending=list(plan),
        )

    def _tool_connection(self) -> ToolClient:
        if self.tool_client is not None:
            return self.tool_client
        from edcraft_validator.bootstrap import create_tool_client

        return create_tool_client()

    @staticmethod
    def _revise_proposal(
        generation_request,
        response,
        attempt,
        plan,
        provider,
        *,
        author_request,
        remaining_revisions,
    ):
        """Request a complete replacement proposal under the original constraints."""
        # Use the latest proposal and explicit feedback, rather than a growing
        # native-tool conversation.
        response_model = type(response.proposal)
        messages = generation_messages(generation_request) + [
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "instruction": (
                            "The current checking attempt failed. Fix each failure "
                            "reported below. "
                            "Use tool observations to address the failures. "
                            "Difficulty estimates are advisory rubric judgments, "
                            "not correctness evidence or measured learner outcomes. "
                            "Distinguish observations from requirements you supplied. "
                            "Check names and model-owned arguments are fixed. "
                            "The model_arguments below were selected in the initial "
                            "plan, not supplied by the educator. Do not change or "
                            "weaken the plan. Preserve the request's scope and "
                            "difficulty. Return one complete replacement proposal "
                            "matching the supplied schema, including every required "
                            "field even when unchanged. Prefer targeted corrections "
                            "while returning the full proposal. Keep related fields "
                            "coherent when changing them. Previously passing checks "
                            "describe the previous candidate; the application will "
                            "recheck your replacement. A check with skip_reason "
                            "was not run "
                            "and is not an observed defect. "
                            "Do not return checks; the application keeps "
                            "the original check plan."
                        ),
                        "revision_policy": REVISION_POLICY,
                        "author_request": author_request,
                        "latest_candidate": attempt.candidate,
                        "failed_attempt": attempt.number,
                        "remaining_revisions": remaining_revisions,
                        "fixed_plan": list(plan),
                        "check_plan": [
                            check.model_dump(mode="json") for check in response.checks
                        ],
                        "check_results": [
                            {
                                **execution.model_feedback(),
                                "model_arguments": execution.requested_arguments,
                            }
                            for execution in attempt.executions
                        ],
                    }
                ),
            },
        ]
        revised_proposal = _generate_author(
            provider,
            replace(
                generation_request,
                response_model=response_model,
                schema_name="template_revision",
                prompt_version=f"{generation_request.prompt_version}+{REVISION_POLICY}",
                messages=copy.deepcopy(messages),
                tool_catalogue=None,
            ),
        )
        if not isinstance(revised_proposal, response_model):
            raise GenerationSchemaError("Revision must return only the proposal")
        # Revalidate even for adapters that return an existing/constructed model.
        try:
            revised_proposal = response_model.model_validate_json(
                revised_proposal.model_dump_json()
            )
        except (ValidationError, ValueError) as exc:
            raise GenerationSchemaError(f"Invalid complete revision: {exc}") from exc
        response = response.model_copy(update={"proposal": revised_proposal})
        return response

    @staticmethod
    def _finish_attempt(job, attempt, candidate) -> AuthoringResult:
        """Return the final verdict and package a reusable artifact when possible."""
        result = job.result
        # Evidence determines the verdict; no acknowledgement inference is needed.
        if not attempt.passed:
            result.status = "needs_review"
            result.reason = (
                "Selected checks did not pass"
                if job.validating
                else "Template checking stopped without all selected checks passing"
            )
            return result

        evidence = [
            execution.evidence
            for execution in attempt.executions
            if execution.evidence is not None
        ]
        try:
            artifact = job.domain.finalize_checked_template(candidate, evidence)
        except ValueError as exc:
            result.status = "needs_review"
            result.reason = f"Selected checks passed; artifact unavailable: {exc}"
            result.failure = AuthoringError(
                stage="finalization", code="ARTIFACT_UNAVAILABLE"
            )
            return result
        if not isinstance(artifact, ValidatedTemplateArtifact):
            raise TypeError("Domain returned no shared validated artifact")

        provenance = TemplateAuthoringProvenance(
            provider=job.provider.provider,
            model=job.provider.model,
            provider_settings=result.provider_settings,
            domain=job.domain.name,
            base_prompt_version=result.prompt_version,
            generated_at=result.generated_at,
            generation_duration_ms=result.generation_duration_ms,
        )
        result.artifact = artifact.model_copy(
            update={"artifact_id": uuid.uuid4().hex, "authoring": provenance}
        )
        result.status = "checked"
        result.warnings = [
            finding
            for item in evidence
            for finding in item.findings
            if item.status == "passed"
        ]
        return result

    @staticmethod
    def _validate_response(response, request, *, plan_only=False):
        expected = CheckPlanResponse if plan_only else PlannedGenerationResponse
        if not isinstance(response, expected) or (
            plan_only and isinstance(response, PlannedGenerationResponse)
        ):
            raise GenerationSchemaError(
                "response must contain only a check plan"
                if plan_only
                else "generation must return a proposal and recommended checks"
            )
        unknown = sorted(
            {check.name for check in response.checks} - set(request.offered_tool_names)
        )
        if unknown:
            raise GenerationSchemaError(
                "model recommended checks that were not offered: " + ", ".join(unknown)
            )
        # Do not rely on the provider's wire-format support or its parser.
        wire_model = constrained_check_plan(
            type(response), request.offered_tool_names, request.check_argument_models
        )
        try:
            wire_model.model_validate_json(response.model_dump_json())
        except ValidationError as exc:
            raise GenerationSchemaError(f"Invalid check plan arguments: {exc}") from exc

    @staticmethod
    def _checked_bindings(domain, request, candidate, attempt, name):
        return domain.checked_tool_bindings(
            request,
            candidate,
            name,
            [
                execution.evidence
                for execution in attempt.executions
                if execution.evidence is not None
            ],
        )

    @staticmethod
    def _run_checks(
        attempt,
        plan,
        definitions,
        planned_arguments,
        client,
        *,
        domain,
        request,
        candidate,
    ):
        # Accept existing research callers that pass raw catalogue definitions.
        definitions = check_definitions(definitions.values())
        deferred = {name for name in plan if definitions[name].after_validation}
        ordered = [name for name in plan if name not in deferred] + [
            name for name in plan if name in deferred
        ]
        for name in ordered:
            execution = CheckExecution(
                call_id=f"attempt-{attempt.number}:{name}",
                tool=name,
                requested_arguments=json.loads(planned_arguments[name]),
            )
            attempt.executions.append(execution)
            if name in deferred and any(
                not entry.passed
                for entry in attempt.executions
                if entry.tool not in deferred
            ):
                execution.skip_reason = "Prerequisite checks did not pass"
                continue
            attempt.pending.remove(name)
            TemplateApplication._execute_check(
                execution,
                definitions[name],
                client,
                domain,
                request,
                candidate,
                attempt,
                name in deferred,
            )
        attempt.complete = not attempt.pending
        attempt.passed = attempt.complete and all(
            entry.passed for entry in attempt.executions
        )

    @staticmethod
    def _execute_check(
        execution, definition, client, domain, request, candidate, attempt, deferred
    ):
        try:
            bindings = (
                TemplateApplication._checked_bindings(
                    domain, request, candidate, attempt, execution.tool
                )
                if deferred
                else domain.tool_bindings(request, candidate, execution.tool)
            )
            arguments = execution.requested_arguments
            owned = set(arguments) & set(bindings)
            if owned:
                raise ValueError(
                    "Do not supply application-owned arguments: "
                    + ", ".join(sorted(owned))
                )
            effective = {**arguments, **copy.deepcopy(bindings)}
            execution.application_arguments = {
                key: copy.deepcopy(value)
                for key, value in bindings.items()
                if key != "candidate" or deferred
            }
            Draft202012Validator(definition.input_schema).validate(effective)
            if not isinstance(definition.output_schema, dict):
                raise ValueError("Tool has no output schema")
            raw = client.call_tool(
                execution.tool, copy.deepcopy(effective), version=definition.version
            )
            Draft202012Validator(definition.output_schema).validate(raw)
            evidence = ToolEvidence.model_validate(raw)
            if evidence.tool != execution.tool or (
                definition.version and evidence.version != definition.version
            ):
                raise ValueError("MCP evidence tool identity/version mismatch")
            execution.evidence = evidence
        except JsonSchemaError as exc:
            path = ".".join(str(part) for part in exc.absolute_path) or "arguments"
            execution.error = f"Schema validation at {path}: {exc.message}"
        except Exception as exc:
            execution.error = f"{type(exc).__name__}: {exc}"

    def generate_question(
        self, validated: ValidatedTemplateArtifact, *, domain: DomainModule, seed: int
    ) -> BaseModel:
        return domain.generate_question(validated, seed=seed)
