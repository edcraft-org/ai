"""Domain-agnostic template authoring, validation, and expansion."""

import copy
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import replace

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaError
from pydantic import BaseModel

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
from edcraft_validator.llm.llm_errors import GenerationError, GenerationSchemaError
from edcraft_validator.llm.tool_context import callable_tool, generation_messages
from edcraft_validator.llm.usage import MeasuredProvider, summarize_usage
from edcraft_validator.mcp.catalogue import (
    ToolCatalogue,
    ToolCatalogueError,
    resolve_domain_tools,
)
from edcraft_validator.mcp.client import FastMcpToolClient
from edcraft_validator.mcp.evidence import ToolEvidence


class TemplateApplication:
    """Run the same template workflow for any registered domain."""

    def __init__(
        self,
        *,
        tool_catalogue: ToolCatalogue | None = None,
        tool_client: FastMcpToolClient | None = None,
    ) -> None:
        self.tool_catalogue = tool_catalogue
        self.tool_client = tool_client or FastMcpToolClient()

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

        Authoring allows three total attempts with a fixed check plan.
        Validation checks an existing candidate once without rewriting it.
        Failed attempts and their evidence remain available in the result.
        """
        started = time.perf_counter()
        validating = initial_candidate is not None
        max_attempts = 1 if validating else 3
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
                    response = provider.generate(generation_request)
                finally:
                    generation_duration_ms += (
                        time.perf_counter() - generation_started
                    ) * 1000
                self._validate_response(response, snapshot.names, plan_only=validating)
                # Corrections cannot avoid checks that previously failed.
                plan = tuple(check.name for check in response.checks)
                result.fixed_plan = list(plan)
                messages = generation_messages(generation_request)
                messages.append(
                    {"role": "assistant", "content": response.model_dump_json()}
                )
                definitions = {tool["name"]: tool for tool in snapshot.definitions()}
                seen_call_ids: set[str] = set()
                for number in range(1, max_attempts + 1):
                    stage = "template_building"
                    candidate = (
                        initial_candidate
                        if validating
                        else domain.build_candidate(request, response.proposal)
                    )
                    attempt = self._build_attempt(number, candidate, plan)
                    result.attempts.append(attempt)
                    # Supply the exact candidate and request-owned arguments directly,
                    # rather than asking the model to reproduce them.
                    bindings = {
                        name: domain.tool_bindings(request, candidate, name)
                        for name in plan
                    }
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                f"Attempt {number}/{max_attempts}. "
                                "Request every planned tool exactly once in one "
                                "response: "
                                + json.dumps(plan)
                                + ". Batch the native tool calls together. "
                                "Do not revise the "
                                "proposal until all checks finish. Candidate and "
                                "request-owned "
                                "arguments are supplied by the application. "
                                "Supply required arguments from each callable schema. "
                                "Empty planning arguments do not apply to calls. "
                            ),
                        }
                    )
                    stage = "checking"
                    self._run_checks(
                        attempt,
                        plan,
                        definitions,
                        bindings,
                        messages,
                        provider,
                        client,
                        seen_call_ids,
                    )
                    if not attempt.passed and number < max_attempts:
                        stage = "generation"
                        revision_started = time.perf_counter()
                        try:
                            response, messages = self._revise_proposal(
                                generation_request, response, attempt, plan, provider
                            )
                        finally:
                            generation_duration_ms += (
                                time.perf_counter() - revision_started
                            ) * 1000
                        messages.append(
                            {"role": "assistant", "content": response.model_dump_json()}
                        )
                        continue
                    stage = "finalization"
                    return self._finish_attempt(
                        result,
                        attempt,
                        candidate,
                        domain=domain,
                        provider=provider,
                        messages=messages,
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
        raise AssertionError("Authoring loop must return within three attempts")

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
    def _revise_proposal(generation_request, response, attempt, plan, provider):
        """Request a corrected proposal while retaining the original check plan."""
        # Use the latest proposal and explicit feedback, rather than a growing
        # native-tool conversation.
        messages = generation_messages(generation_request) + [
            {"role": "assistant", "content": response.model_dump_json()},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "instruction": (
                            "The current checking attempt failed. Fix each failure "
                            "reported below. "
                            "Treat tool observations as authoritative, but "
                            "distinguish them from requirements you supplied. "
                            "Only check names are fixed; your tool arguments "
                            "can change. "
                            "The model_arguments below were supplied by you, "
                            "not by the author. Reconsider any mistaken "
                            "requirements in them. "
                            "If your tool arguments imposed unrequested "
                            "requirements, correct those arguments on the next "
                            "tool turn instead of adding irrelevant code. "
                            "Preserve the request's scope and difficulty. "
                            "Revise authored fields when they are wrong. "
                            "An unchanged proposal is allowed when only your "
                            "tool calls were wrong. Return only the "
                            "proposal fields matching the supplied schema. "
                            "Do not return checks; the application keeps "
                            "the original check plan."
                        ),
                        "fixed_plan": list(plan),
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
        revised_proposal = provider.generate(
            replace(
                generation_request,
                response_model=type(response.proposal),
                schema_name="template_revision",
                messages=copy.deepcopy(messages),
                tool_catalogue=None,
            )
        )
        if not isinstance(revised_proposal, type(response.proposal)):
            raise GenerationSchemaError("Revision must return only the proposal")
        response = response.model_copy(update={"proposal": revised_proposal})
        return response, messages

    @staticmethod
    def _finish_attempt(
        result,
        attempt,
        candidate,
        *,
        domain,
        provider,
        messages,
        validating,
        provider_settings,
        generation_duration_ms,
    ) -> AuthoringResult:
        """Return the final verdict and package a reusable artifact when possible."""
        # Deliver final evidence; model prose cannot change verdicts.
        messages.append(
            {
                "role": "user",
                "content": (
                    "Checking is finished. Acknowledge the evidence "
                    "briefly. "
                    "Do not revise the proposal or request more tools."
                ),
            }
        )
        try:
            receipt = provider.tool_turn(copy.deepcopy(messages), [])
            if receipt.calls:
                raise ValueError("Model requested tools after checking")
        except Exception as exc:
            # A failed acknowledgement cannot erase completed evidence.
            result.feedback_error = f"{type(exc).__name__}: {exc}"

        if not attempt.passed:
            result.status = "needs_review"
            result.reason = (
                "Selected checks did not pass"
                if validating
                else "Three complete attempts did not pass"
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
        return result

    @classmethod
    def _validate_response(cls, response, offered, *, plan_only=False):
        expected = CheckPlanResponse if plan_only else PlannedGenerationResponse
        if not isinstance(response, expected) or (
            plan_only and isinstance(response, PlannedGenerationResponse)
        ):
            raise GenerationSchemaError(
                "response must contain only a check plan"
                if plan_only
                else "generation must return a proposal and recommended checks"
            )
        cls._validate_recommended_checks(response, offered_tool_names=offered)

    @staticmethod
    def _run_checks(
        attempt, plan, definitions, bindings, messages, provider, client, seen_call_ids
    ):
        for _ in range(2 * len(plan) + 2):
            if not attempt.pending:
                attempt.complete = True
                attempt.passed = all(item.passed for item in attempt.executions)
                return
            callable_tools = [
                callable_tool(definitions[name], bindings[name])
                for name in attempt.pending
            ]
            turn = provider.tool_turn(copy.deepcopy(messages), callable_tools)
            if len(turn.calls) > len(plan):
                raise ValueError("Too many tool calls in one turn")
            if any(call.id in seen_call_ids for call in turn.calls) or len(
                {call.id for call in turn.calls}
            ) != len(turn.calls):
                raise ValueError("Duplicate tool call ID")
            seen_call_ids.update(call.id for call in turn.calls)
            messages.append(turn.message())
            for call in turn.calls:
                execution = CheckExecution(
                    call_id=call.id,
                    tool=call.name,
                    requested_arguments=call.arguments_json,
                )
                attempt.executions.append(execution)
                try:
                    if call.name not in attempt.pending:
                        raise ValueError("Tool is outside the pending frozen plan")
                    attempt.pending.remove(call.name)
                    definition = definitions[call.name]
                    arguments = json.loads(call.arguments_json)
                    if not isinstance(arguments, dict):
                        raise ValueError("Tool arguments must be a JSON object")
                    execution.requested_arguments = arguments
                    owned = set(arguments) & set(bindings[call.name])
                    if owned:
                        raise ValueError(
                            "Do not supply application-owned arguments: "
                            + ", ".join(sorted(owned))
                            + ". Use only the callable schema; "
                            "use {} if it has no arguments."
                        )
                    effective = {**arguments, **copy.deepcopy(bindings[call.name])}
                    execution.application_arguments = {
                        key: copy.deepcopy(value)
                        for key, value in bindings[call.name].items()
                        if key != "candidate"
                    }
                    Draft202012Validator(definition["inputSchema"]).validate(effective)
                    output_schema = definition.get("outputSchema")
                    if not isinstance(output_schema, dict):
                        raise ValueError("Tool has no output schema")
                    version = (
                        definition.get("_meta", {}).get("fastmcp", {}).get("version")
                    )
                    raw = client.call_tool(
                        call.name, copy.deepcopy(effective), version=version
                    )
                    Draft202012Validator(output_schema).validate(raw)
                    evidence = ToolEvidence.model_validate(raw)
                    if evidence.tool != call.name or (
                        version and evidence.version != version
                    ):
                        raise ValueError("MCP evidence tool identity/version mismatch")
                    execution.evidence = evidence
                except JsonSchemaError as exc:
                    path = (
                        ".".join(str(part) for part in exc.absolute_path) or "arguments"
                    )
                    execution.error = f"Schema validation at {path}: {exc.message}"
                except Exception as exc:
                    execution.error = f"{type(exc).__name__}: {exc}"
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "name": call.name,
                        "content": json.dumps(execution.model_feedback()),
                    }
                )
            if not turn.calls:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Request all remaining tools together using native "
                            "tool calls: " + json.dumps(attempt.pending)
                        ),
                    }
                )
        if not attempt.pending:
            attempt.complete = True
            attempt.passed = all(item.passed for item in attempt.executions)
            return
        raise ValueError("Tool conversation limit reached with checks still pending")

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
