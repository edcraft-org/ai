"""Structured planning, catalogue reuse, and bounded check/template authoring."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import ValidationError

from edcraft_validator.application.check_pilot.catalogue import (
    find_applicable_check,
    qualified_check_descriptors,
    resolve_plan,
)
from edcraft_validator.application.check_pilot.contracts import (
    Contract,
    Goal,
    plan_covers_template_findings,
    scope_applicability_findings,
    template_goal,
)
from edcraft_validator.application.check_pilot.errors import PilotError
from edcraft_validator.application.check_pilot.kernel_registry import (
    KernelContractSpec,
)
from edcraft_validator.application.check_pilot.models import (
    CHECK_SCHEMA_VERSION,
    RENDERER_VERSION,
    SOLVE_RENDERER_VERSION,
    STRUCTURED_RENDERER_VERSION,
    TEMPLATE_SCHEMA_VERSION_V2,
    TEMPLATE_SCHEMA_VERSION_V3,
    ApprovalStatus,
    CheckAuthorProposal,
    CheckPlanProposal,
    CheckRecipeDefinition,
    CheckRecord,
    CheckRef,
    CheckSelection,
    KernelGoal,
    PilotQualificationSettings,
    PilotTemplateDefinition,
    PilotTemplateRecord,
    PolynomialFamily,
    Qualification,
    SolveFamily,
    StructuredProblemFamily,
    TemplateAuthorProposal,
    TemplateStatus,
)
from edcraft_validator.application.check_pilot.operations import (
    RecipeCompileError,
    compile_recipe,
)
from edcraft_validator.application.check_pilot.prompts import (
    CHECK_PROMPT_VERSION,
    PLANNER_PROMPT_VERSION,
    TEMPLATE_PROMPT_VERSION,
    build_check_generation_request,
    build_plan_generation_request,
    build_template_generation_request,
)
from edcraft_validator.application.check_pilot.qualification import (
    qualification_seed,
    qualify_recipe,
    qualify_structured_template,
)
from edcraft_validator.application.check_pilot.storage import (
    NULL_TEMPLATE_SHA256,
    PilotStore,
    check_content_sha256,
    template_definition_sha256,
)
from edcraft_validator.llm.llm_contracts import ModelProvider
from edcraft_validator.llm.llm_errors import GenerationSchemaError

MAX_CHECK_REPAIRS = 2
MAX_PLAN_REPAIRS = 2
MAX_TEMPLATE_REPAIRS = 2
_SAFE_PROVIDER_ERROR = (
    "The authoring model could not produce a usable structured response."
)
_SAFE_SCHEMA_ERROR = (
    "The authoring model could not produce a schema-valid structured response "
    "after bounded repair attempts."
)
_SAFE_WORKER_ERROR = "Qualification failed safely; no check was stored."
_SAFE_STORAGE_ERROR = "The qualified result could not be stored safely."
_COUNTEREXAMPLE_KEYS = {
    "reason",
    "problem",
    "coefficients",
    "expected",
    "candidate",
    "assignment",
    "choices",
}


@dataclass(frozen=True, slots=True)
class CheckAuthoringOutcome:
    check: CheckRecord | None
    qualification: Qualification | None
    status: TemplateStatus
    findings: list[str]


@dataclass(frozen=True, slots=True)
class PlanOutcome:
    proposal: CheckPlanProposal | None
    contract: Contract | None
    goal: Goal | None
    check: CheckRecord | None
    status: TemplateStatus
    findings: list[str]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _request_sha256(prompt: str) -> str:
    return hashlib.sha256(prompt.encode()).hexdigest()


def _schema_error_feedback(stage: str) -> dict[str, Any]:
    """Bounded, application-authored repair hint for one schema rejection.

    Provider error text and raw model output stay out of the next prompt so a
    failed structured response cannot leak untrusted data or held-out cases.
    """
    return {
        "stage": stage,
        "findings": ["the previous response did not match the closed schema"],
        "guidance": (
            "Return only advertised fields. Declare each recipe step with one "
            "registered operation and exactly that operation's argument names. "
            "Input and step arguments use a name and a null value; literal "
            "arguments use a null name and a non-null value."
        ),
    }


def _author_provenance(
    role: Literal["check-planner", "check-author", "template-author"],
    provider: ModelProvider,
    prompt_version: str,
) -> dict[str, Any]:
    return {
        "role": role,
        "provider": str(provider.provider),
        "model": str(provider.model),
        "prompt_version": prompt_version,
    }


def _safe_settings(provider: ModelProvider) -> dict[str, Any]:
    try:
        settings = provider.generation_settings()
        if not isinstance(settings, dict):
            return {}
        return json.loads(json.dumps(settings, allow_nan=False))
    except (TypeError, ValueError, AttributeError):
        return {}


def _truncate(value: Any, limit: int = 200) -> Any:
    if isinstance(value, str):
        return value[:limit]
    return value


def sanitize_counterexample(
    counterexample: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Bound model feedback and drop worker-only bookkeeping keys."""
    if not isinstance(counterexample, dict):
        return None
    sanitized: dict[str, Any] = {}
    for key, value in counterexample.items():
        if key not in _COUNTEREXAMPLE_KEYS:
            continue
        if isinstance(value, list):
            sanitized[key] = [_truncate(item) for item in value[:6]]
        elif isinstance(value, dict):
            sanitized[key] = {
                str(name)[:32]: _truncate(item)
                for name, item in list(value.items())[:6]
            }
        else:
            sanitized[key] = _truncate(value)
    return sanitized or None


def _public_check_findings(qualification: Qualification) -> list[str]:
    findings: list[str] = []
    for finding in qualification.findings[:4]:
        if "held-out" in finding.lower():
            finding = "independent evaluation did not confirm the recipe"
        findings.append(finding[:600])
    return findings


def _compile_failure_qualification(
    settings: PilotQualificationSettings, findings: list[str]
) -> Qualification:
    return Qualification(
        status="error",
        phase="compilation",
        accepted_cases=0,
        execution_calls=0,
        seed=0,
        max_examples=settings.max_examples,
        max_execution_calls=settings.max_execution_calls,
        timeout_seconds=settings.timeout_seconds,
        counterexample=None,
        findings=findings,
        versions={
            "check_pilot": "1",
            "recipe_compiler": "1",
            "polynomial_oracle": "coefficient-arithmetic/1",
            "solution_oracle": "discriminant-sign/1",
        },
    )


def _check_provenance(
    provider: ModelProvider,
    *,
    prompt: str,
    repair_attempts: int,
    seed: int,
    contract: Contract,
) -> dict[str, Any]:
    return {
        **_author_provenance("check-author", provider, CHECK_PROMPT_VERSION),
        "provider_settings": _safe_settings(provider),
        "request_sha256": _request_sha256(prompt),
        "request_length": len(prompt),
        "repair_attempts": repair_attempts,
        "qualification_seed": seed,
        "contract": CHECK_SCHEMA_VERSION,
        "contract_id": contract.contract_id,
        "operation_set": contract.operation_set,
    }


def _make_check(
    proposal: CheckAuthorProposal,
    *,
    contract: Contract,
    provider: ModelProvider,
    prompt: str,
    repair_attempts: int,
    seed: int,
    qualification: Qualification,
) -> CheckRecord:
    assert proposal.recipe is not None and proposal.title and proposal.description
    scope = contract.scope().model_dump(mode="json")
    definition = proposal.recipe.model_dump(mode="json")
    digest = check_content_sha256(
        title=proposal.title,
        description=proposal.description,
        scope=scope,
        definition=definition,
    )
    return CheckRecord(
        check_ref=CheckRef(
            check_id=f"chk_{digest[:24]}",
            version="1",
            sha256=digest,
        ),
        title=proposal.title,
        description=proposal.description,
        scope=scope,
        definition=definition,
        qualification=qualification,
        provenance=_check_provenance(
            provider,
            prompt=prompt,
            repair_attempts=repair_attempts,
            seed=seed,
            contract=contract,
        ),
        created_at=_now(),
    )


def _plan_with_repairs(
    store: PilotStore,
    owner_id: str,
    *,
    prompt: str,
    provider: ModelProvider,
) -> PlanOutcome:
    feedback: dict[str, Any] | None = None
    checks = qualified_check_descriptors(store.list_checks(owner_id))
    last: PlanOutcome | None = None
    for attempt in range(MAX_PLAN_REPAIRS + 1):
        try:
            proposal = provider.generate(
                build_plan_generation_request(
                    prompt,
                    checks=checks,
                    feedback=feedback,
                )
            )
        except GenerationSchemaError:
            if attempt >= MAX_PLAN_REPAIRS:
                return PlanOutcome(
                    proposal=None,
                    contract=None,
                    goal=None,
                    check=None,
                    status="error",
                    findings=[_SAFE_SCHEMA_ERROR],
                )
            feedback = _schema_error_feedback("plan")
            continue
        except Exception:
            return PlanOutcome(
                proposal=None,
                contract=None,
                goal=None,
                check=None,
                status="error",
                findings=[_SAFE_PROVIDER_ERROR],
            )
        if not isinstance(proposal, CheckPlanProposal):
            return PlanOutcome(
                proposal=None,
                contract=None,
                goal=None,
                check=None,
                status="error",
                findings=[_SAFE_PROVIDER_ERROR],
            )
        resolution = resolve_plan(store, owner_id, proposal)
        last = PlanOutcome(
            proposal=proposal,
            contract=resolution.contract,
            goal=resolution.goal,
            check=resolution.check,
            status="ready" if resolution.supported else "needs_review",
            findings=resolution.findings,
        )
        if resolution.supported:
            return last
        if not proposal.supported or attempt >= MAX_PLAN_REPAIRS:
            return last
        feedback = {
            "stage": "plan",
            "findings": resolution.findings[:4],
            "contract_id": proposal.contract_id,
            "goal": (
                proposal.goal.model_dump(mode="json")
                if proposal.goal is not None
                else None
            ),
        }
    raise AssertionError("bounded plan repair loop must return")


def author_check(
    store: PilotStore,
    owner_id: str,
    *,
    prompt: str,
    provider: ModelProvider,
    settings: PilotQualificationSettings,
    contract: Contract,
    goal: Goal,
) -> CheckAuthoringOutcome:
    feedback: dict[str, Any] | None = None
    last_qualification: Qualification | None = None
    scope = contract.scope()
    for attempt in range(MAX_CHECK_REPAIRS + 1):
        try:
            proposal = provider.generate(
                build_check_generation_request(
                    prompt,
                    contract=contract,
                    goal=goal,
                    feedback=feedback,
                )
            )
        except GenerationSchemaError:
            if attempt >= MAX_CHECK_REPAIRS:
                return CheckAuthoringOutcome(
                    check=None,
                    qualification=last_qualification,
                    status="error",
                    findings=[_SAFE_SCHEMA_ERROR],
                )
            feedback = _schema_error_feedback("check")
            continue
        except Exception:
            return CheckAuthoringOutcome(
                check=None,
                qualification=last_qualification,
                status="error",
                findings=[_SAFE_PROVIDER_ERROR],
            )
        if not isinstance(proposal, CheckAuthorProposal):
            return CheckAuthoringOutcome(
                check=None,
                qualification=last_qualification,
                status="error",
                findings=[_SAFE_PROVIDER_ERROR],
            )
        if not proposal.supported:
            development = (proposal.development_needed or "").strip()[:1000]
            return CheckAuthoringOutcome(
                check=None,
                qualification=None,
                status="needs_review",
                findings=[f"Development needed: {development}"],
            )

        try:
            recipe = proposal.recipe
            assert recipe is not None
            compiled = compile_recipe(recipe, scope=scope)
        except RecipeCompileError as exc:
            findings = [
                (
                    f"Development needed: {finding}"
                    if exc.unknown_capability
                    else f"recipe did not compile: {finding}"
                )
                for finding in exc.findings[:4]
            ]
            last_qualification = _compile_failure_qualification(settings, findings)
            if attempt >= MAX_CHECK_REPAIRS:
                return CheckAuthoringOutcome(
                    check=None,
                    qualification=last_qualification,
                    status="needs_review",
                    findings=findings,
                )
            feedback = {
                "stage": "compile",
                "findings": findings,
                "counterexample": None,
            }
            continue

        seed = qualification_seed(compiled.sha256, contract.operation_set)
        last_qualification = qualify_recipe(
            recipe,
            seed=seed,
            settings=settings,
            scope=scope,
        )
        if last_qualification.status == "passed":
            check = _make_check(
                proposal,
                contract=contract,
                provider=provider,
                prompt=prompt,
                repair_attempts=attempt,
                seed=seed,
                qualification=last_qualification,
            )
            try:
                store.save_check(owner_id, check)
            except PilotError:
                return CheckAuthoringOutcome(
                    check=None,
                    qualification=last_qualification,
                    status="error",
                    findings=[_SAFE_STORAGE_ERROR],
                )
            return CheckAuthoringOutcome(
                check=check,
                qualification=last_qualification,
                status="ready",
                findings=[],
            )

        findings = [
            f"check qualification {last_qualification.status}",
            *_public_check_findings(last_qualification),
        ]
        if last_qualification.status == "error":
            return CheckAuthoringOutcome(
                check=None,
                qualification=last_qualification,
                status="error",
                findings=[_SAFE_WORKER_ERROR, *findings],
            )
        if attempt >= MAX_CHECK_REPAIRS:
            return CheckAuthoringOutcome(
                check=None,
                qualification=last_qualification,
                status="needs_review",
                findings=findings,
            )
        feedback = {
            "stage": "qualification",
            "status": last_qualification.status,
            "findings": _public_check_findings(last_qualification),
            "counterexample": sanitize_counterexample(
                last_qualification.counterexample
            ),
        }
    raise AssertionError("bounded repair loop must return")


def _template_provenance(
    provider: ModelProvider,
    *,
    prompt: str,
    template_digest: str,
    check_sha256: str,
    seed: int,
    contract: Contract,
    source: Literal["saved", "authored"],
    repair_attempts: int = 0,
) -> dict[str, Any]:
    return {
        **_author_provenance("template-author", provider, TEMPLATE_PROMPT_VERSION),
        "provider_settings": _safe_settings(provider),
        "request_sha256": _request_sha256(prompt),
        "request_length": len(prompt),
        "template_sha256": template_digest,
        "check_sha256": check_sha256,
        "qualification_seed": seed,
        "repair_attempts": repair_attempts,
        "contract_id": contract.contract_id,
        "selection_source": source,
    }


def _template_id(prompt: str, template_digest: str, check_sha256: str) -> str:
    identity = hashlib.sha256(
        f"{prompt}\0{template_digest}\0{check_sha256}\0{uuid4().hex}".encode()
    ).hexdigest()
    return f"tpl_{identity[:24]}"


def _failure_approval(
    *, status: TemplateStatus, qualification: Qualification | None
) -> ApprovalStatus:
    """Decide whether saved failure evidence is final or retryable.

    A failed or inconclusive check/template qualification is deterministic
    evidence against the draft, so the record is marked ``rejected`` while its
    status and findings stay for inspection. Provider, schema, worker, timeout
    and unsupported-plan failures stay ``unreviewed`` so a retry can succeed.
    """
    if status == "error":
        return "unreviewed"
    if qualification is not None and qualification.status in {
        "failed",
        "inconclusive",
    }:
        return "rejected"
    return "unreviewed"


def _record_failure(
    *,
    prompt: str,
    status: TemplateStatus,
    findings: list[str],
    check: CheckRecord | None,
    check_qualification: Qualification | None,
    provenance: dict[str, Any],
    reused_check: bool,
    scope: dict[str, Any] | None,
    selection: CheckSelection | None,
) -> PilotTemplateRecord:
    check_sha = check.check_ref.sha256 if check is not None else "0" * 64
    return PilotTemplateRecord(
        template_id=_template_id(prompt, NULL_TEMPLATE_SHA256, check_sha),
        template_sha256=NULL_TEMPLATE_SHA256,
        prompt=prompt,
        status=status,
        approval=_failure_approval(status=status, qualification=check_qualification),
        reused_check=reused_check,
        check=check,
        template=None,
        qualification=None,
        findings=[finding[:1000] for finding in findings[:20]],
        created_at=_now(),
        scope=scope,
        provenance=provenance,
        check_qualification=check_qualification,
        selection=selection,
    )


def _validation_findings(exc: ValidationError) -> list[str]:
    findings: list[str] = []
    for error in exc.errors()[:4]:
        location = ".".join(str(part) for part in error.get("loc", ()))
        message = str(error.get("msg", "invalid value"))
        findings.append(f"{location}: {message}" if location else message)
    return findings or ["the structured family is invalid"]


def _template_definition_from_proposal(
    proposal: TemplateAuthorProposal,
    *,
    contract: Contract,
    goal: Goal,
    num_distractors: int,
) -> tuple[PilotTemplateDefinition | None, list[str]]:
    if proposal.contract_id != contract.contract_id:
        return None, ["the template proposal must preserve the selected contract id"]
    if isinstance(contract, KernelContractSpec):
        if not isinstance(goal, KernelGoal):
            return None, ["a kernel contract requires a kernel plan goal"]
        if (
            proposal.structured_family is None
            or proposal.family is not None
            or proposal.solve_family is not None
        ):
            return None, [
                "a kernel contract requires exactly one structured problem family"
            ]
        try:
            structured_family = StructuredProblemFamily.model_validate(
                {
                    **proposal.structured_family.model_dump(mode="json"),
                    "num_distractors": num_distractors,
                }
            )
        except ValidationError as exc:
            return None, _validation_findings(exc)
        definition = PilotTemplateDefinition(
            schema_version=TEMPLATE_SCHEMA_VERSION_V3,
            renderer_version=STRUCTURED_RENDERER_VERSION,
            scope=contract.scope(),
            contract_id=contract.contract_id,
            structured_family=structured_family,
            goal=goal,
        )
    elif contract.operation == "differentiate":
        if proposal.family is None or proposal.solve_family is not None:
            return None, [
                "a differentiation contract requires exactly one polynomial family"
            ]
        try:
            family = PolynomialFamily.model_validate(
                {
                    **proposal.family.model_dump(mode="json"),
                    "num_distractors": num_distractors,
                }
            )
        except ValidationError as exc:
            return None, _validation_findings(exc)
        definition = PilotTemplateDefinition(
            schema_version=TEMPLATE_SCHEMA_VERSION_V2,
            renderer_version=RENDERER_VERSION,
            scope=contract.scope(),
            contract_id=contract.contract_id,
            family=family,
        )
    else:
        if proposal.solve_family is None or proposal.family is not None:
            return None, [
                "a solve contract requires exactly one structured solve family"
            ]
        try:
            solve_family = SolveFamily.model_validate(
                {
                    **proposal.solve_family.model_dump(mode="json"),
                    "num_distractors": num_distractors,
                }
            )
        except ValidationError as exc:
            return None, _validation_findings(exc)
        definition = PilotTemplateDefinition(
            schema_version=TEMPLATE_SCHEMA_VERSION_V2,
            renderer_version=SOLVE_RENDERER_VERSION,
            scope=contract.scope(),
            contract_id=contract.contract_id,
            solve_family=solve_family,
        )
    findings = plan_covers_template_findings(goal, template_goal(definition))
    return (definition if not findings else None), findings


def _author_template_proposal(
    *,
    prompt: str,
    provider: ModelProvider,
    check: CheckRecord,
    contract: Contract,
    goal: Goal,
    num_distractors: int,
) -> tuple[
    PilotTemplateDefinition | None,
    TemplateAuthorProposal | None,
    TemplateStatus,
    list[str],
]:
    feedback: dict[str, Any] | None = None
    last_proposal: TemplateAuthorProposal | None = None
    for attempt in range(MAX_TEMPLATE_REPAIRS + 1):
        try:
            proposal = provider.generate(
                build_template_generation_request(
                    prompt,
                    check=check,
                    contract=contract,
                    goal=goal,
                    num_distractors=num_distractors,
                    feedback=feedback,
                )
            )
        except GenerationSchemaError:
            if attempt >= MAX_TEMPLATE_REPAIRS:
                return None, last_proposal, "error", [_SAFE_SCHEMA_ERROR]
            feedback = _schema_error_feedback("template")
            continue
        except Exception:
            return None, last_proposal, "error", [_SAFE_PROVIDER_ERROR]
        if not isinstance(proposal, TemplateAuthorProposal):
            return None, last_proposal, "error", [_SAFE_PROVIDER_ERROR]
        last_proposal = proposal
        if not proposal.supported:
            development = (proposal.development_needed or "").strip()[:1000]
            return (
                None,
                proposal,
                "needs_review",
                [f"Development needed: {development}"],
            )
        definition, findings = _template_definition_from_proposal(
            proposal,
            contract=contract,
            goal=goal,
            num_distractors=num_distractors,
        )
        if definition is not None:
            return definition, proposal, "ready", []
        if attempt >= MAX_TEMPLATE_REPAIRS:
            return None, proposal, "needs_review", findings
        feedback = {
            "stage": "template",
            "findings": findings[:4],
            "contract_id": contract.contract_id,
            "goal": goal.model_dump(mode="json"),
        }
    raise AssertionError("bounded template repair loop must return")


def author_template_flow(
    store: PilotStore,
    owner_id: str,
    *,
    prompt: str,
    provider: ModelProvider,
    num_distractors: int,
    settings: PilotQualificationSettings,
) -> PilotTemplateRecord:
    plan = _plan_with_repairs(
        store,
        owner_id,
        prompt=prompt,
        provider=provider,
    )
    if plan.status != "ready" or plan.contract is None or plan.goal is None:
        scope = (
            plan.contract.scope().model_dump(mode="json")
            if plan.contract is not None
            else None
        )
        record = _record_failure(
            prompt=prompt,
            status=plan.status,
            findings=plan.findings,
            check=None,
            check_qualification=None,
            provenance={
                **_author_provenance("check-planner", provider, PLANNER_PROMPT_VERSION),
                "provider_settings": _safe_settings(provider),
                "request_sha256": _request_sha256(prompt),
                "request_length": len(prompt),
                "contract_id": (
                    plan.proposal.contract_id if plan.proposal is not None else None
                ),
            },
            reused_check=False,
            scope=scope,
            selection=None,
        )
        return store.save_template(owner_id, record)

    contract = plan.contract
    goal = plan.goal
    reason = plan.proposal.reason if plan.proposal is not None else ""
    check = plan.check
    reused_check = check is not None
    check_qualification = check.qualification if check is not None else None
    if check is None:
        outcome = author_check(
            store,
            owner_id,
            prompt=prompt,
            provider=provider,
            settings=settings,
            contract=contract,
            goal=goal,
        )
        check = outcome.check
        check_qualification = outcome.qualification
        if check is None:
            record = _record_failure(
                prompt=prompt,
                status=outcome.status,
                findings=outcome.findings,
                check=None,
                check_qualification=outcome.qualification,
                provenance={
                    **_author_provenance(
                        "check-author", provider, CHECK_PROMPT_VERSION
                    ),
                    "provider_settings": _safe_settings(provider),
                    "request_sha256": _request_sha256(prompt),
                    "request_length": len(prompt),
                    "contract_id": contract.contract_id,
                },
                reused_check=False,
                scope=contract.scope().model_dump(mode="json"),
                selection=None,
            )
            return store.save_template(owner_id, record)

    selection = CheckSelection(
        contract_id=contract.contract_id,
        reason=reason or "trusted contract selected by the application",
        source="saved" if reused_check else "authored",
        check_ref=check.check_ref,
    )
    definition, proposal, template_status, template_findings = (
        _author_template_proposal(
            prompt=prompt,
            provider=provider,
            check=check,
            contract=contract,
            goal=goal,
            num_distractors=num_distractors,
        )
    )
    if definition is None:
        record = _record_failure(
            prompt=prompt,
            status=template_status,
            findings=template_findings,
            check=check,
            check_qualification=check_qualification,
            provenance=_template_provenance(
                provider,
                prompt=prompt,
                template_digest=NULL_TEMPLATE_SHA256,
                check_sha256=check.check_ref.sha256,
                seed=0,
                contract=contract,
                source=selection.source,
            ),
            reused_check=reused_check,
            scope=contract.scope().model_dump(mode="json"),
            selection=selection,
        )
        return store.save_template(owner_id, record)

    actual = template_goal(definition)
    findings = scope_applicability_findings(check.scope, actual)
    if findings:
        record = _record_failure(
            prompt=prompt,
            status="needs_review",
            findings=findings,
            check=check,
            check_qualification=check_qualification,
            provenance=_template_provenance(
                provider,
                prompt=prompt,
                template_digest=NULL_TEMPLATE_SHA256,
                check_sha256=check.check_ref.sha256,
                seed=0,
                contract=contract,
                source=selection.source,
            ),
            reused_check=reused_check,
            scope=definition.scope.model_dump(mode="json", exclude_none=True),
            selection=selection,
        )
        return store.save_template(owner_id, record)

    template_digest = template_definition_sha256(definition)
    seed = qualification_seed(template_digest, check.check_ref.sha256)
    try:
        recipe = CheckRecipeDefinition.model_validate(check.definition)
    except ValidationError:
        record = _record_failure(
            prompt=prompt,
            status="error",
            findings=[_SAFE_STORAGE_ERROR],
            check=check,
            check_qualification=check_qualification,
            provenance=_template_provenance(
                provider,
                prompt=prompt,
                template_digest=template_digest,
                check_sha256=check.check_ref.sha256,
                seed=seed,
                contract=contract,
                source=selection.source,
            ),
            reused_check=reused_check,
            scope=definition.scope.model_dump(mode="json", exclude_none=True),
            selection=selection,
        )
        return store.save_template(owner_id, record)

    qualification = qualify_structured_template(
        recipe,
        definition,
        seed=seed,
        settings=settings,
    )
    if qualification.status == "passed":
        status: TemplateStatus = "ready"
        status_findings: list[str] = []
    elif qualification.status == "error":
        status = "error"
        status_findings = [
            _SAFE_WORKER_ERROR,
            *_public_check_findings(qualification),
        ]
    else:
        status = "needs_review"
        status_findings = _public_check_findings(qualification) or [
            f"template qualification {qualification.status}"
        ]
    record = PilotTemplateRecord(
        template_id=_template_id(prompt, template_digest, check.check_ref.sha256),
        template_sha256=template_digest,
        prompt=prompt,
        status=status,
        approval=_failure_approval(status=status, qualification=qualification),
        reused_check=reused_check,
        check=check,
        template=definition.model_dump(mode="json", exclude_none=True),
        qualification=qualification,
        findings=[finding[:1000] for finding in status_findings[:20]],
        created_at=_now(),
        scope=definition.scope.model_dump(mode="json", exclude_none=True),
        provenance=_template_provenance(
            provider,
            prompt=prompt,
            template_digest=template_digest,
            check_sha256=check.check_ref.sha256,
            seed=seed,
            contract=contract,
            source=selection.source,
            repair_attempts=0,
        ),
        check_qualification=check_qualification,
        selection=selection,
    )
    return store.save_template(owner_id, record)


__all__ = [
    "CheckAuthoringOutcome",
    "MAX_CHECK_REPAIRS",
    "MAX_PLAN_REPAIRS",
    "MAX_TEMPLATE_REPAIRS",
    "PlanOutcome",
    "author_check",
    "author_template_flow",
    "find_applicable_check",
    "sanitize_counterexample",
]
