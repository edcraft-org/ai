"""Domain-agnostic authoring loop that turns a model proposal into a checked template.

The application builds a candidate, runs the frozen check plan through MCP, asks
the author for full revisions and records the finalised artifact. Approved
templates then expand into seeded questions without further model calls.
"""

import copy
import json
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal

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
    ModelProvider,
    PlannedGenerationResponse,
    RecommendedCheck,
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
from edcraft_validator.validation.check_contracts import ToolEvidence, ToolFinding

REVISION_POLICY = "full-candidate-v1"
# Reported like a check so the author model can revise, but owned by the
# application: it compares the candidate with the request and calls no tool.
DISTRACTOR_COUNT_CHECK = "application_distractor_count"
DISTRACTOR_COUNT_VERSION = "1.0.0"
# Mirrors the phase literal declared on AuthoringProgress.
ProgressPhase = Literal[
    "generating",
    "checking",
    "assessing",
    "correcting",
    "finalizing",
]


def _has_technical_check_error(attempt) -> bool:
    """Distinguish tool/protocol failures from genuine finding failures."""
    return any(
        not execution.advisory
        and (
            execution.error is not None
            or (execution.evidence is not None and execution.evidence.status == "error")
        )
        for execution in attempt.executions
    )


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
    request: BaseModel
    domain: DomainModule
    provider: MeasuredProvider
    result: AuthoringResult
    max_attempts: int
    stage: str = "configuration"
    observer: Callable[[AuthoringProgress], None] | None = None
    current_phase: str | None = None
    phase_started_at: datetime | None = None

    def generate(self, operation, *args, phase="generating", **kwargs):
        self.stage = "generation"
        self.notify(phase)

        started = time.perf_counter()
        try:
            return operation(*args, **kwargs)
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000
            self.result.generation_duration_ms += elapsed_ms

    def notify(
        self,
        phase: ProgressPhase,
        *,
        checks_total: int | None = None,
        checks_done: int | None = None,
        current_check: str | None = None,
    ) -> None:
        if self.observer is None:
            return

        if phase != self.current_phase:
            self.current_phase = phase
            self.phase_started_at = datetime.now(UTC)

        attempt = len(self.result.attempts) + (phase in {"generating", "correcting"})
        progress = AuthoringProgress(
            phase=phase,
            attempt=attempt,
            max_attempts=self.max_attempts,
            checks_total=checks_total,
            checks_done=checks_done,
            current_check=current_check,
            phase_started_at=self.phase_started_at,
        )
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
        started = time.perf_counter()
        request = request.model_copy(deep=True)
        measured = MeasuredProvider(provider)
        result = self._initial_result(provider, domain, request)

        job = _AuthoringJob(
            request,
            domain,
            measured,
            result,
            self.max_correction_attempts + 1,
            observer=on_progress,
        )

        try:
            result.provider_settings = copy.deepcopy(
                getattr(provider, "generation_settings", lambda: {})()
            )
            with self._tool_connection() as client:
                return self._prepare_and_run(job, client, on_catalogue_resolved)
        except Exception as exc:
            self._record_failure(result, exc, job.stage)
            return result
        finally:
            result.duration_ms = (time.perf_counter() - started) * 1000
            result.model_calls = measured.calls
            result.usage = summarize_usage(measured.calls)

    @staticmethod
    def _initial_result(provider, domain, request) -> AuthoringResult:
        """Create the reviewable result record before any model call."""
        return AuthoringResult(
            status="error",
            provider=provider.provider,
            model=provider.model,
            domain=domain.name,
            request=copy.deepcopy(request.model_dump(mode="json")),
            prompt_version="",
            revision_policy=REVISION_POLICY,
            fixed_plan=[],
            tool_catalogue=[],
        )

    def _generate_proposal(self, job, generation_request):
        """Generate one schema-validated proposal from the author provider."""
        response = job.generate(_generate_author, job.provider, generation_request)
        self._validate_response(response, generation_request)
        return response

    def _resolve_tools(self, job, client, observer):
        """Resolve the domain's tools, publish their catalogue and notify."""
        capabilities = getattr(job.domain, "capabilities", None)
        if capabilities is None:
            raise ValueError(f"domain {job.domain.name!r} must declare capabilities")

        tools = resolve_domain_tools(
            job.domain.name,
            self.tool_catalogue or client,
            capabilities=capabilities,
        )
        snapshot = ToolCatalogueSnapshot.from_definitions(tools)
        job.result.tool_catalogue = snapshot.summaries()
        if observer is not None:
            observer(snapshot)
        return tools, snapshot

    @staticmethod
    def _bound_generation_request(job, snapshot):
        """Build the domain request with the offered catalogue attached."""
        generation_request = job.domain.generation_request(job.request)
        generation_request = replace(
            generation_request,
            offered_tool_names=snapshot.names,
            tool_catalogue=snapshot,
        )
        job.result.prompt_version = generation_request.prompt_version
        return generation_request

    def _prepare_job(self, job, client, observer):
        """Resolve the tools and produce the first proposal for this job."""
        tools, snapshot = self._resolve_tools(job, client, observer)
        generation_request = self._bound_generation_request(job, snapshot)
        response = self._generate_proposal(job, generation_request)
        response = response.model_copy(deep=True)
        return generation_request, response, check_definitions(tools)

    def _prepare_and_run(self, job, client, observer):
        generation_request, response, definitions = self._prepare_job(
            job, client, observer
        )

        for number in range(1, job.max_attempts + 1):
            job.stage = "template_building"
            candidate, response, names, planned_arguments = self._build_and_plan(
                job, response, definitions
            )

            attempt = self._build_attempt(number, candidate, names)
            job.result.attempts.append(attempt)
            job.stage = "checking"
            job.notify(
                "checking",
                checks_total=sum(
                    1 for name in names if not definitions[name].after_validation
                ),
                checks_done=0,
                current_check=DISTRACTOR_COUNT_CHECK,
            )
            self._check_distractor_count(attempt, job, candidate)
            self._run_checks(
                attempt,
                names,
                definitions,
                planned_arguments,
                client,
                domain=job.domain,
                request=job.request,
                candidate=candidate,
                job=job,
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

    def _build_and_plan(self, job, response, definitions):
        """Build one candidate and record the fixed plan its checks came from."""
        candidate = job.domain.build_candidate(job.request, response.proposal)
        response = self._with_required_checks(
            response, job.domain.required_checks(candidate), definitions
        )
        names = tuple(check.name for check in response.checks)
        job.result.fixed_plan = list(names)
        job.result.check_plan = [
            check.model_copy(deep=True) for check in response.checks
        ]
        planned_arguments = {
            check.name: json.dumps(check.arguments) for check in response.checks
        }
        return candidate, response, names, planned_arguments

    @staticmethod
    def _with_required_checks(response, required, definitions):
        """Add the checks the domain requires that the model did not select.

        The model still chooses the optional checks. The plan only ever grows,
        so a revision that needs a further check gets it.
        """
        selected = {check.name for check in response.checks}
        missing = sorted(required - selected)
        unavailable = [name for name in missing if name not in definitions]
        if unavailable:
            raise ToolCatalogueError(
                "domain requires checks the catalogue does not offer: "
                + ", ".join(unavailable)
            )

        if not missing:
            return response

        added = [RecommendedCheck(name=name, arguments={}) for name in missing]
        return response.model_copy(update={"checks": [*response.checks, *added]})

    @staticmethod
    def _check_distractor_count(attempt, job, candidate):
        """Record a failed check when the candidate offers too few distractors."""
        requested = getattr(job.request, "num_distractors", None)
        if requested is None:
            return

        offered = job.domain.distractor_count(candidate)
        if offered >= requested:
            return

        attempt.executions.append(
            CheckExecution(
                call_id=f"attempt-{attempt.number}:{DISTRACTOR_COUNT_CHECK}",
                tool=DISTRACTOR_COUNT_CHECK,
                requested_arguments={},
                evidence=ToolEvidence(
                    tool=DISTRACTOR_COUNT_CHECK,
                    version=DISTRACTOR_COUNT_VERSION,
                    status="failed",
                    findings=[
                        ToolFinding(
                            code="TOO_FEW_DISTRACTORS",
                            message=(
                                f"The request needs {requested} distractors but "
                                f"the template offers {offered}."
                            ),
                            field="distractors",
                        )
                    ],
                    details={"requested": requested, "offered": offered},
                ),
            )
        )

    @staticmethod
    def _should_revise(attempt, number, max_attempts):
        terminal_error = any(
            not entry.advisory
            and entry.evidence is not None
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
    def _revision_messages(
        generation_request,
        response,
        attempt,
        plan,
        *,
        author_request,
        remaining_revisions,
    ):
        """Build the revision conversation from the latest candidate and feedback."""
        return generation_messages(generation_request) + [
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "instruction": (
                            "A required technical check failed. Fix each technical "
                            "failure reported below. "
                            "Use tool observations to address the failures. "
                            "Difficulty and relevance assessments are advisory "
                            "rubric judgments, not correctness evidence or revision "
                            "requirements; do not change a field only because an "
                            "advisory verdict differs. "
                            "Distinguish observations from requirements you supplied. "
                            "Check names and model-owned arguments are fixed; the "
                            "application may add checks your replacement requires. "
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
                            "Do not return checks; the application owns "
                            "the check plan."
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

    @staticmethod
    def _request_revision(provider, generation_request, response_model, messages):
        """Ask the author for a full replacement under the frozen constraints."""
        return _generate_author(
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

    @staticmethod
    def _validated_revision(revised_proposal, response_model):
        """Confirm the revision carries only a complete proposal."""
        if not isinstance(revised_proposal, response_model):
            raise GenerationSchemaError("Revision must return only the proposal")
        # Revalidate even for adapters that return an existing/constructed model.
        try:
            return response_model.model_validate_json(
                revised_proposal.model_dump_json()
            )
        except (ValidationError, ValueError) as exc:
            raise GenerationSchemaError(f"Invalid complete revision: {exc}") from exc

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
        messages = TemplateApplication._revision_messages(
            generation_request,
            response,
            attempt,
            plan,
            author_request=author_request,
            remaining_revisions=remaining_revisions,
        )
        revised_proposal = TemplateApplication._request_revision(
            provider, generation_request, response_model, messages
        )
        revised_proposal = TemplateApplication._validated_revision(
            revised_proposal, response_model
        )
        return response.model_copy(update={"proposal": revised_proposal})

    @staticmethod
    def _record_unpassed(job, attempt) -> AuthoringResult:
        """Record the reviewable verdict for an attempt that did not pass."""
        result = job.result
        result.status = "needs_review"
        result.reason = "Template checking stopped without all selected checks passing"
        if result.failure is None:
            if _has_technical_check_error(attempt):
                result.failure = AuthoringError(stage="checking", code="CHECK_ERROR")
                result.reason = (
                    "A technical check could not complete, so the template "
                    "could not be fully checked"
                )
            else:
                result.failure = AuthoringError(
                    stage="checking", code="TEMPLATE_CHECKS_FAILED"
                )
        return result

    @staticmethod
    def _packaged_artifact(job, candidate, evidence, advisory_checks):
        """Finalise, identify and attribute the checked artifact."""
        try:
            artifact = job.domain.finalize_checked_template(
                candidate, evidence, advisory_checks=advisory_checks
            )
        except ValueError as exc:
            job.result.status = "needs_review"
            job.result.reason = f"Selected checks passed; artifact unavailable: {exc}"
            job.result.failure = AuthoringError(
                stage="finalization", code="ARTIFACT_UNAVAILABLE"
            )
            return None

        if not isinstance(artifact, ValidatedTemplateArtifact):
            raise TypeError("Domain returned no shared validated artifact")

        provenance = TemplateAuthoringProvenance(
            provider=job.provider.provider,
            model=job.provider.model,
            provider_settings=job.result.provider_settings,
            domain=job.domain.name,
            base_prompt_version=job.result.prompt_version,
            generated_at=job.result.generated_at,
            generation_duration_ms=job.result.generation_duration_ms,
        )
        return artifact.model_copy(
            update={"artifact_id": uuid.uuid4().hex, "authoring": provenance}
        )

    @staticmethod
    def _collect_warnings(evidence, attempt):
        """Retain passed findings and report advisory assessments that did not run."""
        warnings = [
            finding
            for item in evidence
            for finding in item.findings
            if item.status == "passed" or item.details.get("advisory") is True
        ]
        warnings.extend(
            ToolFinding(
                code="ADVISORY_ASSESSMENT_UNAVAILABLE",
                message=(
                    f"{execution.tool} advisory assessment was unavailable; "
                    "the technically checked artifact was retained."
                ),
            )
            for execution in attempt.executions
            if execution.advisory and execution.evidence is None
        )
        return warnings

    @staticmethod
    def _finish_attempt(job, attempt, candidate) -> AuthoringResult:
        """Return the final verdict and package a reusable artifact when possible."""
        result = job.result
        # Evidence determines the verdict. No acknowledgement inference is needed.
        if not attempt.passed:
            return TemplateApplication._record_unpassed(job, attempt)

        evidence = [
            execution.evidence
            for execution in attempt.executions
            if execution.evidence is not None
        ]
        advisory_checks = frozenset(
            execution.tool for execution in attempt.executions if execution.advisory
        )

        artifact = TemplateApplication._packaged_artifact(
            job, candidate, evidence, advisory_checks
        )
        if artifact is None:
            return result

        result.artifact = artifact
        result.status = "checked"
        result.warnings = TemplateApplication._collect_warnings(evidence, attempt)
        return result

    @staticmethod
    def _validate_response(response, request):
        if not isinstance(response, PlannedGenerationResponse):
            raise GenerationSchemaError(
                "generation must return a proposal and recommended checks"
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
    def _ordered_checks(plan, deferred):
        """Run deferred checks after the technical checks they depend on."""
        return [name for name in plan if name not in deferred] + [
            name for name in plan if name in deferred
        ]

    @staticmethod
    def _start_check(attempt, name, definitions, planned_arguments):
        """Record a check execution with its fixed arguments before it runs."""
        execution = CheckExecution(
            call_id=f"attempt-{attempt.number}:{name}",
            tool=name,
            advisory=definitions[name].advisory,
            requested_arguments=json.loads(planned_arguments[name]),
        )
        attempt.executions.append(execution)
        return execution

    @staticmethod
    def _prerequisite_failed(attempt, deferred):
        """Report whether an earlier technical check has already failed."""
        return any(
            not entry.passed and not entry.advisory
            for entry in attempt.executions
            if entry.tool not in deferred
        )

    @staticmethod
    def _record_check_outcome(attempt):
        """Set completion and the technical verdict for the attempt."""
        attempt.complete = not attempt.pending
        # Advisory assessments are retained as evidence but never gate the
        # technical artifact or request revisions.
        attempt.passed = attempt.complete and all(
            entry.passed for entry in attempt.executions if not entry.advisory
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
        job: _AuthoringJob | None = None,
    ):
        # Accept existing research callers that pass raw catalogue definitions.
        definitions = check_definitions(definitions.values())
        deferred = {name for name in plan if definitions[name].after_validation}
        totals = {
            "checking": sum(1 for name in plan if name not in deferred),
            "assessing": sum(1 for name in plan if name in deferred),
        }
        done = {"checking": 0, "assessing": 0}

        for name in TemplateApplication._ordered_checks(plan, deferred):
            phase: ProgressPhase = "assessing" if name in deferred else "checking"
            if job is not None:
                job.notify(
                    phase,
                    checks_total=totals[phase],
                    checks_done=done[phase],
                    current_check=name,
                )
            execution = TemplateApplication._start_check(
                attempt, name, definitions, planned_arguments
            )
            if name in deferred and TemplateApplication._prerequisite_failed(
                attempt, deferred
            ):
                execution.skip_reason = "Prerequisite checks did not pass"
            else:
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
            done[phase] += 1
            if job is not None:
                job.notify(phase, checks_total=totals[phase], checks_done=done[phase])

        TemplateApplication._record_check_outcome(attempt)

    @staticmethod
    def _reject_owned_arguments(arguments, bindings):
        """Refuse model arguments that the application supplies itself."""
        owned = set(arguments) & set(bindings)
        if owned:
            raise ValueError(
                "Do not supply application-owned arguments: " + ", ".join(sorted(owned))
            )

    @staticmethod
    def _call_check_tool(execution, definition, client, effective):
        """Validate the call, run the MCP tool and validate its response."""
        Draft202012Validator(definition.input_schema).validate(effective)
        if not isinstance(definition.output_schema, dict):
            raise ValueError("Tool has no output schema")

        raw = client.call_tool(
            execution.tool, copy.deepcopy(effective), version=definition.version
        )
        Draft202012Validator(definition.output_schema).validate(raw)
        return raw

    @staticmethod
    def _matching_evidence(raw, execution, definition):
        """Decode the evidence and confirm it belongs to the called tool."""
        evidence = ToolEvidence.model_validate(raw)
        if evidence.tool != execution.tool or (
            definition.version and evidence.version != definition.version
        ):
            raise ValueError("MCP evidence tool identity/version mismatch")
        return evidence

    @staticmethod
    def _apply_advisory_policy(evidence, definition):
        """Let the application decide whether evidence is advisory."""
        details = dict(evidence.details)
        if definition.advisory:
            details["advisory"] = True
        else:
            details.pop("advisory", None)
        if details != evidence.details:
            evidence = evidence.model_copy(update={"details": details})
        return evidence

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
            TemplateApplication._reject_owned_arguments(arguments, bindings)

            effective = {**arguments, **copy.deepcopy(bindings)}
            execution.application_arguments = {
                key: copy.deepcopy(value)
                for key, value in bindings.items()
                if key != "candidate" or deferred
            }

            raw = TemplateApplication._call_check_tool(
                execution, definition, client, effective
            )
            evidence = TemplateApplication._matching_evidence(
                raw, execution, definition
            )
            execution.evidence = TemplateApplication._apply_advisory_policy(
                evidence, definition
            )
        except JsonSchemaError as exc:
            path = ".".join(str(part) for part in exc.absolute_path) or "arguments"
            execution.error = f"Schema validation at {path}: {exc.message}"
        except Exception as exc:
            execution.error = f"{type(exc).__name__}: {exc}"

    def generate_question(
        self, validated: ValidatedTemplateArtifact, *, domain: DomainModule, seed: int
    ) -> BaseModel:
        return domain.generate_question(validated, seed=seed)
