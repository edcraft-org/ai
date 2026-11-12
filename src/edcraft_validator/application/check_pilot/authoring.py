"""Check-author and template-author orchestration with bounded repairs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from edcraft_validator.application.check_pilot.errors import PilotError
from edcraft_validator.application.check_pilot.models import (
    CHECK_SCHEMA_VERSION,
    RECIPE_OPERATION_SET,
    SUPPORTED_SCOPE,
    CheckAuthorProposal,
    CheckRecipeDefinition,
    CheckRecord,
    CheckRef,
    PilotQualificationSettings,
    PilotTemplateDefinition,
    PilotTemplateRecord,
    PolynomialFamily,
    Qualification,
    TemplateAuthorProposal,
    TemplateStatus,
)
from edcraft_validator.application.check_pilot.operations import (
    RecipeCompileError,
    compile_recipe,
)
from edcraft_validator.application.check_pilot.prompts import (
    CHECK_PROMPT_VERSION,
    TEMPLATE_PROMPT_VERSION,
    build_check_generation_request,
    build_template_generation_request,
)
from edcraft_validator.application.check_pilot.qualification import (
    qualification_seed,
    qualify_recipe,
    qualify_template,
)
from edcraft_validator.application.check_pilot.storage import (
    NULL_TEMPLATE_SHA256,
    PilotStore,
    check_content_sha256,
    template_definition_sha256,
)
from edcraft_validator.llm.llm_contracts import ModelProvider

MAX_CHECK_REPAIRS = 2
_SAFE_PROVIDER_ERROR = (
    "The authoring model could not produce a usable structured response."
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


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _request_sha256(prompt: str) -> str:
    return hashlib.sha256(prompt.encode()).hexdigest()


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
        status="failed",
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
        },
    )


def _check_provenance(
    provider: ModelProvider,
    *,
    prompt: str,
    repair_attempts: int,
    seed: int,
) -> dict[str, Any]:
    return {
        "role": "check-author",
        "provider": str(provider.provider),
        "model": str(provider.model),
        "prompt_version": CHECK_PROMPT_VERSION,
        "provider_settings": _safe_settings(provider),
        "request_sha256": _request_sha256(prompt),
        "request_length": len(prompt),
        "repair_attempts": repair_attempts,
        "qualification_seed": seed,
        "contract": CHECK_SCHEMA_VERSION,
    }


def _make_check(
    proposal: CheckAuthorProposal,
    *,
    provider: ModelProvider,
    prompt: str,
    repair_attempts: int,
    seed: int,
    qualification: Qualification,
) -> CheckRecord:
    assert proposal.recipe is not None and proposal.title and proposal.description
    scope = SUPPORTED_SCOPE.model_dump(mode="json")
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
        ),
        created_at=_now(),
    )


def find_applicable_check(store: PilotStore, owner_id: str) -> CheckRecord | None:
    expected_scope = SUPPORTED_SCOPE.model_dump(mode="json")
    for record in reversed(store.list_checks(owner_id)):
        if (
            record.scope == expected_scope
            and record.definition.get("operation_set") == RECIPE_OPERATION_SET
            and record.qualification.status == "passed"
        ):
            return record
    return None


def author_check(
    store: PilotStore,
    owner_id: str,
    *,
    prompt: str,
    provider: ModelProvider,
    settings: PilotQualificationSettings,
) -> CheckAuthoringOutcome:
    feedback: dict[str, Any] | None = None
    last_qualification: Qualification | None = None
    for attempt in range(MAX_CHECK_REPAIRS + 1):
        try:
            proposal = provider.generate(
                build_check_generation_request(prompt, feedback=feedback)
            )
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
            compiled = compile_recipe(recipe)
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

        seed = qualification_seed(compiled.sha256, RECIPE_OPERATION_SET)
        last_qualification = qualify_recipe(recipe, seed=seed, settings=settings)
        if last_qualification.status == "passed":
            check = _make_check(
                proposal,
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
    repair_attempts: int = 0,
) -> dict[str, Any]:
    return {
        "role": "template-author",
        "provider": str(provider.provider),
        "model": str(provider.model),
        "prompt_version": TEMPLATE_PROMPT_VERSION,
        "provider_settings": _safe_settings(provider),
        "request_sha256": _request_sha256(prompt),
        "request_length": len(prompt),
        "template_sha256": template_digest,
        "check_sha256": check_sha256,
        "qualification_seed": seed,
        "repair_attempts": repair_attempts,
    }


def _template_id(prompt: str, template_digest: str, check_sha256: str) -> str:
    identity = hashlib.sha256(
        f"{prompt}\0{template_digest}\0{check_sha256}\0{uuid4().hex}".encode()
    ).hexdigest()
    return f"tpl_{identity[:24]}"


def _record_failure(
    *,
    prompt: str,
    status: TemplateStatus,
    findings: list[str],
    check: CheckRecord | None,
    check_qualification: Qualification | None,
    provenance: dict[str, Any],
    reused_check: bool,
) -> PilotTemplateRecord:
    check_sha = check.check_ref.sha256 if check is not None else "0" * 64
    return PilotTemplateRecord(
        template_id=_template_id(prompt, NULL_TEMPLATE_SHA256, check_sha),
        template_sha256=NULL_TEMPLATE_SHA256,
        prompt=prompt,
        status=status,
        approval="unreviewed",
        reused_check=reused_check,
        check=check,
        template=None,
        qualification=None,
        findings=[finding[:1000] for finding in findings[:20]],
        created_at=_now(),
        scope=SUPPORTED_SCOPE.model_dump(mode="json"),
        provenance=provenance,
        check_qualification=check_qualification,
    )


def author_template_flow(
    store: PilotStore,
    owner_id: str,
    *,
    prompt: str,
    provider: ModelProvider,
    num_distractors: int,
    settings: PilotQualificationSettings,
) -> PilotTemplateRecord:
    check = find_applicable_check(store, owner_id)
    reused_check = check is not None
    check_qualification = check.qualification if check is not None else None
    if check is None:
        outcome = author_check(
            store,
            owner_id,
            prompt=prompt,
            provider=provider,
            settings=settings,
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
                    "role": "check-author",
                    "provider": str(provider.provider),
                    "model": str(provider.model),
                    "prompt_version": CHECK_PROMPT_VERSION,
                },
                reused_check=False,
            )
            return store.save_template(owner_id, record)

    try:
        proposal = provider.generate(
            build_template_generation_request(
                prompt, check=check, num_distractors=num_distractors
            )
        )
    except Exception:
        record = _record_failure(
            prompt=prompt,
            status="error",
            findings=[_SAFE_PROVIDER_ERROR],
            check=check,
            check_qualification=check_qualification,
            provenance={
                "role": "template-author",
                "provider": str(provider.provider),
                "model": str(provider.model),
                "prompt_version": TEMPLATE_PROMPT_VERSION,
            },
            reused_check=reused_check,
        )
        return store.save_template(owner_id, record)
    if not isinstance(proposal, TemplateAuthorProposal):
        record = _record_failure(
            prompt=prompt,
            status="error",
            findings=[_SAFE_PROVIDER_ERROR],
            check=check,
            check_qualification=check_qualification,
            provenance={
                "role": "template-author",
                "provider": str(provider.provider),
                "model": str(provider.model),
                "prompt_version": TEMPLATE_PROMPT_VERSION,
            },
            reused_check=reused_check,
        )
        return store.save_template(owner_id, record)
    if not proposal.supported:
        development = (proposal.development_needed or "").strip()[:1000]
        record = _record_failure(
            prompt=prompt,
            status="needs_review",
            findings=[f"Development needed: {development}"],
            check=check,
            check_qualification=check_qualification,
            provenance=_template_provenance(
                provider,
                prompt=prompt,
                template_digest=NULL_TEMPLATE_SHA256,
                check_sha256=check.check_ref.sha256,
                seed=0,
            ),
            reused_check=reused_check,
        )
        return store.save_template(owner_id, record)

    try:
        family = PolynomialFamily.model_validate(
            {
                **(proposal.family.model_dump(mode="json") if proposal.family else {}),
                "num_distractors": num_distractors,
            }
        )
        definition = PilotTemplateDefinition(
            scope=SUPPORTED_SCOPE,
            family=family,
        )
    except ValidationError:
        record = _record_failure(
            prompt=prompt,
            status="needs_review",
            findings=[
                "Development needed: the declared coefficient domains are outside "
                "the supported bounded polynomial family."
            ],
            check=check,
            check_qualification=check_qualification,
            provenance=_template_provenance(
                provider,
                prompt=prompt,
                template_digest=NULL_TEMPLATE_SHA256,
                check_sha256=check.check_ref.sha256,
                seed=0,
            ),
            reused_check=reused_check,
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
            ),
            reused_check=reused_check,
        )
        return store.save_template(owner_id, record)

    qualification = qualify_template(
        recipe,
        family,
        seed=seed,
        settings=settings,
    )
    if qualification.status == "passed":
        status: TemplateStatus = "ready"
        findings: list[str] = []
    elif qualification.status == "error":
        status = "error"
        findings = [_SAFE_WORKER_ERROR, *_public_check_findings(qualification)]
    else:
        status = "needs_review"
        findings = _public_check_findings(qualification) or [
            f"template qualification {qualification.status}"
        ]
    record = PilotTemplateRecord(
        template_id=_template_id(prompt, template_digest, check.check_ref.sha256),
        template_sha256=template_digest,
        prompt=prompt,
        status=status,
        approval="unreviewed",
        reused_check=reused_check,
        check=check,
        template=definition.model_dump(mode="json"),
        qualification=qualification,
        findings=[finding[:1000] for finding in findings[:20]],
        created_at=_now(),
        scope=SUPPORTED_SCOPE.model_dump(mode="json"),
        provenance=_template_provenance(
            provider,
            prompt=prompt,
            template_digest=template_digest,
            check_sha256=check.check_ref.sha256,
            seed=seed,
        ),
        check_qualification=check_qualification,
    )
    return store.save_template(owner_id, record)


__all__ = [
    "CheckAuthoringOutcome",
    "MAX_CHECK_REPAIRS",
    "author_check",
    "author_template_flow",
    "find_applicable_check",
    "sanitize_counterexample",
]
