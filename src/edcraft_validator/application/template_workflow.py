"""Domain-agnostic template authoring, validation, and expansion."""

import copy
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import replace

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaError
from pydantic import BaseModel, ValidationError

from edcraft_validator.application.authoring_contracts import (
    AuthoringError,
    AuthoringFailure,
    AuthoringResult,
    CheckExecution,
    GenerationAttempt,
)
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
    resolve_domain_tools,
)
from edcraft_validator.mcp.client import FastMcpToolClient
from edcraft_validator.mcp.evidence import ToolEvidence

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


class TemplateApplication:
    """Run the same template workflow for any registered domain."""

    def __init__(
        self,
        *,
        tool_catalogue: ToolCatalogue | None = None,
        tool_client: FastMcpToolClient | None = None,
        max_correction_attempts: int = 3,
    ) -> None:
        self.tool_catalogue = tool_catalogue
        self.tool_client = tool_client or FastMcpToolClient()
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
    ) -> AuthoringResult:
        return self._check_template(
            request,
            domain=domain,
            provider=provider,
            on_catalogue_resolved=on_catalogue_resolved,
        )

    def validate_template(
        self,
        candidate: BaseModel,
        *,
        domain: DomainModule,
        provider: ModelProvider,
        on_catalogue_resolved=None,
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
        )

    def _check_template(
        self,
        request,
        *,
        domain,
        provider,
        initial_candidate=None,
        on_catalogue_resolved=None,
    ) -> AuthoringResult:
        """Author or validate a template using model-selected MCP checks.

        Authoring allows an initial attempt and up to three template revisions.
        Validation checks an existing candidate once without rewriting it.
        Failed attempts and their evidence remain available in the result.
        """
        started = time.perf_counter()
        validating = initial_candidate is not None
        # Caller-owned mutable requests must not change the job's author constraints.
        request = None if validating else request.model_copy(deep=True)
        max_attempts = 1 if validating else self.max_correction_attempts + 1
        request_payload = (
            {"operation": "validate"} if validating else request.model_dump(mode="json")
        )
        original_provider = provider
        provider = MeasuredProvider(provider)
        result = AuthoringResult(
            status="error",
            provider=provider.provider,
            model=provider.model,
            domain=domain.name,
            request=copy.deepcopy(request_payload),
            prompt_version="",
            revision_policy=None if validating else REVISION_POLICY,
            fixed_plan=[],
            tool_catalogue=[],
        )
        generation_duration_ms = 0
        stage = "configuration"
        try:
            provider_settings = copy.deepcopy(
                getattr(original_provider, "generation_settings", lambda: {})()
            )
            result.provider_settings = provider_settings
            with self.tool_client as client:
                tools = resolve_domain_tools(domain.name, self.tool_catalogue or client)
                snapshot = ToolCatalogueSnapshot.from_definitions(tools)
                result.tool_catalogue = snapshot.summaries()
                if on_catalogue_resolved is not None:
                    on_catalogue_resolved(snapshot)
                generation_request = replace(
                    (
                        domain.validation_request(initial_candidate)
                        if validating
                        else domain.generation_request(request)
                    ),
                    offered_tool_names=snapshot.names,
                    tool_catalogue=snapshot,
                )
                result.prompt_version = generation_request.prompt_version
                stage = "generation"
                generation_started = time.perf_counter()
                try:
                    response = _generate_author(provider, generation_request)
                finally:
                    generation_duration_ms += (
                        time.perf_counter() - generation_started
                    ) * 1000
                self._validate_response(
                    response, generation_request, plan_only=validating
                )
                response = response.model_copy(deep=True)
                # Corrections cannot avoid checks that previously failed.
                plan = tuple(check.name for check in response.checks)
                result.fixed_plan = list(plan)
                result.check_plan = [
                    check.model_copy(deep=True) for check in response.checks
                ]
                # Keep dispatch arguments private and independent of mutable model data.
                planned_arguments = {
                    check.name: json.dumps(check.arguments) for check in response.checks
                }
                definitions = {tool["name"]: tool for tool in snapshot.definitions()}
                for number in range(1, max_attempts + 1):
                    stage = "template_building"
                    candidate = (
                        initial_candidate
                        if validating
                        else domain.build_candidate(request, response.proposal)
                    )
                    attempt = self._build_attempt(number, candidate, plan)
                    result.attempts.append(attempt)
                    stage = "checking"
                    self._run_checks(
                        attempt,
                        plan,
                        definitions,
                        planned_arguments,
                        client,
                        domain=domain,
                        request=request,
                        candidate=candidate,
                    )
                    terminal_check_error = any(
                        execution.evidence is not None
                        and execution.evidence.status == "error"
                        and execution.evidence.details.get("retryable") is False
                        for execution in attempt.executions
                    )
                    if (
                        not attempt.passed
                        and not terminal_check_error
                        and number < max_attempts
                    ):
                        stage = "generation"
                        revision_started = time.perf_counter()
                        try:
                            response = self._revise_proposal(
                                generation_request,
                                response,
                                attempt,
                                plan,
                                provider,
                                author_request=request_payload,
                                remaining_revisions=max_attempts - number,
                            )
                        finally:
                            generation_duration_ms += (
                                time.perf_counter() - revision_started
                            ) * 1000
                        continue
                    stage = "finalization"
                    return self._finish_attempt(
                        result,
                        attempt,
                        candidate,
                        domain=domain,
                        provider=provider,
                        validating=validating,
                        provider_settings=provider_settings,
                        generation_duration_ms=generation_duration_ms,
                    )
        except Exception as exc:
            result.status = "error"
            result.artifact = None
            result.reason = f"{type(exc).__name__}: {exc}"
            result.failure = AuthoringError(
                stage=stage,
                code=(
                    exc.category
                    if isinstance(exc, GenerationError)
                    else "MCP_CATALOGUE_ERROR"
                    if isinstance(exc, ToolCatalogueError)
                    else type(exc).__name__
                ),
            )
            return result
        finally:
            result.duration_ms = (time.perf_counter() - started) * 1000
            result.generation_duration_ms = generation_duration_ms
            result.model_calls = provider.calls
            result.usage = summarize_usage(provider.calls)
        raise AssertionError("Authoring loop must return within its attempt limit")

    @staticmethod
    def _build_attempt(number, candidate, plan) -> GenerationAttempt:
        """Record the exact candidate that this attempt will check."""
        payload = candidate.model_dump(mode="json")
        return GenerationAttempt(
            number=number,
            candidate=payload,
            pending=list(plan),
        )

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
    def _finish_attempt(
        result,
        attempt,
        candidate,
        *,
        domain,
        provider,
        validating,
        provider_settings,
        generation_duration_ms,
    ) -> AuthoringResult:
        """Return the final verdict and package a reusable artifact when possible."""
        # Evidence determines the verdict; no acknowledgement inference is needed.
        if not attempt.passed:
            result.status = "needs_review"
            result.reason = (
                "Selected checks did not pass"
                if validating
                else "Template checking stopped without all selected checks passing"
            )
            return result

        evidence = [
            execution.evidence
            for execution in attempt.executions
            if execution.evidence is not None
        ]
        try:
            artifact = domain.finalize_checked_template(candidate, evidence)
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
            provider=provider.provider,
            model=provider.model,
            provider_settings=provider_settings,
            domain=domain.name,
            base_prompt_version=result.prompt_version,
            generated_at=result.generated_at,
            generation_duration_ms=generation_duration_ms,
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

    @classmethod
    def _validate_response(cls, response, request, *, plan_only=False):
        expected = CheckPlanResponse if plan_only else PlannedGenerationResponse
        if not isinstance(response, expected) or (
            plan_only and isinstance(response, PlannedGenerationResponse)
        ):
            raise GenerationSchemaError(
                "response must contain only a check plan"
                if plan_only
                else "generation must return a proposal and recommended checks"
            )
        cls._validate_recommended_checks(
            response, offered_tool_names=request.offered_tool_names
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
        """Execute the frozen plan once per candidate, without provider tool turns."""
        deferred = {
            name
            for name in plan
            if "stage:after-validation"
            in definitions[name].get("_meta", {}).get("fastmcp", {}).get("tags", [])
        }
        ordered = [name for name in plan if name not in deferred] + [
            name for name in plan if name in deferred
        ]
        for name in ordered:
            execution = CheckExecution(
                call_id=f"attempt-{attempt.number}:{name}",
                tool=name,
                requested_arguments=json.loads(planned_arguments[name]),
            )
            if name in deferred and any(
                not item.passed
                for item in attempt.executions
                if item.tool not in deferred
            ):
                # Keep dependent checks pending and record why they were not called.
                execution.skip_reason = "Prerequisite checks did not pass"
                attempt.executions.append(execution)
                continue
            attempt.executions.append(execution)
            attempt.pending.remove(name)
            try:
                bindings = (
                    TemplateApplication._checked_bindings(
                        domain, request, candidate, attempt, name
                    )
                    if name in deferred
                    else domain.tool_bindings(request, candidate, name)
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
                    if key != "candidate" or name in deferred
                }
                definition = definitions[name]
                Draft202012Validator(definition["inputSchema"]).validate(effective)
                output_schema = definition.get("outputSchema")
                if not isinstance(output_schema, dict):
                    raise ValueError("Tool has no output schema")
                version = definition.get("_meta", {}).get("fastmcp", {}).get("version")
                raw = client.call_tool(name, copy.deepcopy(effective), version=version)
                Draft202012Validator(output_schema).validate(raw)
                evidence = ToolEvidence.model_validate(raw)
                if evidence.tool != name or (version and evidence.version != version):
                    raise ValueError("MCP evidence tool identity/version mismatch")
                execution.evidence = evidence
            except JsonSchemaError as exc:
                path = ".".join(str(part) for part in exc.absolute_path) or "arguments"
                execution.error = f"Schema validation at {path}: {exc.message}"
            except Exception as exc:
                execution.error = f"{type(exc).__name__}: {exc}"
        attempt.complete = not attempt.pending
        attempt.passed = attempt.complete and all(
            item.passed for item in attempt.executions
        )

    @staticmethod
    def _validate_recommended_checks(
        response: PlannedGenerationResponse,
        *,
        offered_tool_names: tuple[str, ...],
    ) -> None:
        offered = set(offered_tool_names)
        unknown = sorted({check.name for check in response.checks} - offered)
        if unknown:
            raise GenerationSchemaError(
                "model recommended checks that were not offered: " + ", ".join(unknown)
            )

    def generate_question(
        self, validated: ValidatedTemplateArtifact, *, domain: DomainModule, seed: int
    ) -> BaseModel:
        return domain.generate_question(validated, seed=seed)
