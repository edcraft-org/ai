"""Domain-agnostic template authoring, validation, and expansion."""

import copy
import hashlib
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaError
from pydantic import BaseModel

from edcraft_validator.application.authoring_contracts import (
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
from edcraft_validator.llm.llm_errors import GenerationSchemaError
from edcraft_validator.llm.tool_context import callable_tool, generation_messages
from edcraft_validator.mcp.catalogue import (
    ToolCatalogue,
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
        validating = initial_candidate is not None
        max_attempts = 1 if validating else 3
        request_payload = (
            {"candidate": initial_candidate.model_dump(mode="json")}
            if validating
            else request.model_dump(mode="json")
        )
        with self.tool_client as client:
            tools = resolve_domain_tools(domain.name, self.tool_catalogue or client)
            snapshot = ToolCatalogueSnapshot.from_definitions(tools)
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
            started = time.perf_counter()
            response = provider.generate(generation_request)
            generation_duration_ms = (time.perf_counter() - started) * 1000
            self._validate_response(response, snapshot.names, plan_only=validating)
            provider_settings = copy.deepcopy(provider.generation_settings())
            # Keep the initial check plan across revisions so a correction cannot
            # avoid a check that previously failed.
            plan = tuple(check.name for check in response.checks)
            result = AuthoringResult(
                status="error",
                provider=provider.provider,
                model=provider.model,
                request=copy.deepcopy(request_payload),
                prompt_version=generation_request.prompt_version,
                proposal=(
                    initial_candidate.model_dump(mode="json")
                    if validating
                    else response.proposal.model_dump(mode="json")
                ),
                fixed_plan=list(plan),
                tool_catalogue=snapshot.definitions(),
            )
            messages = generation_messages(generation_request)
            messages.append(
                {"role": "assistant", "content": response.model_dump_json()}
            )
            definitions = {tool["name"]: tool for tool in snapshot.definitions()}
            seen_call_ids: set[str] = set()
            try:
                for number in range(1, max_attempts + 1):
                    candidate = (
                        initial_candidate
                        if validating
                        else domain.build_candidate(request, response.proposal)
                    )
                    attempt = self._build_attempt(
                        number, candidate, result.proposal, plan
                    )
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
                                "Request each planned tool once: "
                                + json.dumps(plan)
                                + ". Use native tool calls. Do not revise the "
                                "proposal until all checks finish. Candidate and "
                                "request-owned "
                                "arguments are supplied by the application. "
                                "Supply required arguments from each callable schema. "
                                "Empty planning arguments do not apply to calls. "
                            ),
                        }
                    )
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
                        response, messages, revision_duration_ms = (
                            self._revise_proposal(
                                generation_request, response, attempt, plan, provider
                            )
                        )
                        generation_duration_ms += revision_duration_ms
                        result.proposal = response.proposal.model_dump(mode="json")
                        messages.append(
                            {"role": "assistant", "content": response.model_dump_json()}
                        )
                        continue
                    return self._finish_attempt(
                        result,
                        attempt,
                        candidate,
                        domain=domain,
                        provider=provider,
                        messages=messages,
                        validating=validating,
                        provider_settings=provider_settings,
                        snapshot=snapshot,
                        generation_duration_ms=generation_duration_ms,
                    )
            except Exception as exc:
                result.reason = f"{type(exc).__name__}: {exc}"
                return result
            finally:
                result.duration_ms = (time.perf_counter() - started) * 1000
        raise AssertionError("Authoring loop must return within three attempts")

    @staticmethod
    def _build_attempt(number, candidate, proposal, plan) -> GenerationAttempt:
        """Record the exact candidate that this attempt will check."""
        payload = candidate.model_dump(mode="json")
        digest = hashlib.sha256(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
        ).hexdigest()
        return GenerationAttempt(
            number=number,
            proposal=copy.deepcopy(proposal),
            candidate=payload,
            candidate_digest=digest,
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
                            "The current proposal failed. Fix each failure "
                            "reported below. "
                            "Treat results as authoritative. "
                            "Revise any authored fields needed to fix "
                            "the failures; preserve the author request. "
                            "Do not repeat "
                            "the failed proposal. Return only the revised "
                            "proposal fields matching the supplied schema. "
                            "Do not return checks; the application keeps "
                            "the original check plan."
                        ),
                        "fixed_plan": list(plan),
                        "check_results": [
                            execution.model_feedback()
                            for execution in attempt.executions
                        ],
                    }
                ),
            },
        ]
        generation_started = time.perf_counter()
        revised_proposal = provider.generate(
            replace(
                generation_request,
                response_model=type(response.proposal),
                schema_name="template_revision",
                messages=copy.deepcopy(messages),
                tool_catalogue=None,
            )
        )
        duration_ms = (time.perf_counter() - generation_started) * 1000
        if not isinstance(revised_proposal, type(response.proposal)):
            raise GenerationSchemaError("Revision must return only the proposal")
        response = response.model_copy(update={"proposal": revised_proposal})
        return response, messages, duration_ms

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
        snapshot,
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
            return result
        if not isinstance(artifact, ValidatedTemplateArtifact):
            raise TypeError("Domain returned no shared validated artifact")

        provenance = TemplateAuthoringProvenance(
            provider=provider.provider,
            model=provider.model,
            provider_settings=provider_settings,
            domain=domain.name,
            base_prompt_version=result.prompt_version,
            request=copy.deepcopy(result.request),
            proposal=copy.deepcopy(result.proposal),
            fixed_plan=list(result.fixed_plan),
            tool_catalogue=snapshot.definitions(),
            attempts=[item.model_dump(mode="json") for item in result.attempts],
            generated_at=datetime.now(UTC),
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
                    candidate_digest=attempt.candidate_digest,
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
                    owned = set(arguments) & set(bindings[call.name])
                    if owned:
                        raise ValueError(
                            "Do not supply application-owned arguments: "
                            + ", ".join(sorted(owned))
                            + ". Use only the callable schema; "
                            "use {} if it has no arguments."
                        )
                    effective = {**arguments, **copy.deepcopy(bindings[call.name])}
                    execution.effective_arguments = effective
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
                            "Request the remaining tools using native tool calls: "
                            + json.dumps(attempt.pending)
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
