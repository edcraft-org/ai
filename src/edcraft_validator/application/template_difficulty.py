"""Domain-neutral template difficulty judging, policy and evidence.

Every domain supplies a blinded payload, its distractor count, the requested
level and the exact checked subject hash. The shared cascade builds the requests
from the domain's rubric record, asks for one forced decision, accepts it at
token confidence, and otherwise asks the same model to reason about the
template. Difficulty stays advisory in every domain.
"""

import math
import time
from dataclasses import replace
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, create_model, model_validator

from edcraft_validator.application.authoring_contracts import DifficultyOutcome
from edcraft_validator.application.difficulty_rubrics import (
    DifficultyRecord,
    DifficultyRubric,
    Text,
    difficulty_rubric,
)
from edcraft_validator.domain_types import (
    MAX_DISTRACTOR_CANDIDATES,
    MIN_DISTRACTORS,
    Difficulty,
)
from edcraft_validator.llm.forced_decision import (
    ClassDecision,
    JudgeProviderSession,
    run_decision,
)
from edcraft_validator.llm.judge_configuration import JudgeSettings
from edcraft_validator.llm.judging import (
    DEFAULT_JUDGE_TIMEOUT_SECONDS,
    JudgeProviderFactory,
    failed_judge,
    run_judge,
)
from edcraft_validator.llm.llm_contracts import StructuredGenerationRequest
from edcraft_validator.llm.usage import summarize_usage
from edcraft_validator.validation.check_contracts import ToolEvidence, ToolFinding
from edcraft_validator.validation.check_names import (
    TEMPLATE_DIFFICULTY_CHECK,
    TEMPLATE_DIFFICULTY_TOOL_VERSION,
)

DIFFICULTY_POLICY_VERSION = "decision-cascade-v1"
DECISION_INSTRUCTION = (
    "You are a difficulty classifier. Reply with exactly one word: "
    "easy, medium, or hard. Do not explain, reason, or prefix.\n\n"
)

DifficultyMatch = Literal["matches", "too_easy", "too_hard"]


def compare_difficulty(estimated: Difficulty, requested: Difficulty) -> DifficultyMatch:
    order = {"easy": 0, "medium": 1, "hard": 2}

    delta = order[estimated] - order[requested]
    return "matches" if delta == 0 else "too_easy" if delta < 0 else "too_hard"


class OptionExplanation(DifficultyRecord):
    reasoning: Text
    hypothesised_error: str | None
    shortcut_or_cue: str | None


def _require_reason_for_abstention(self):
    if self.estimated_difficulty is None and self.unable_to_assess_reason is None:
        raise ValueError("null estimates require an unable-to-assess reason")
    return self


@lru_cache(maxsize=32)
def _assessment_model(rubric_id: str, distractor_count: int) -> type[BaseModel]:
    rubric = difficulty_rubric(rubric_id)

    assessment = create_model(
        "TemplateDifficultyAssessment",
        __base__=DifficultyRecord,
        __validators__={
            "require_reason_for_abstention": model_validator(mode="after")(
                _require_reason_for_abstention
            )
        },
        estimated_difficulty=(Difficulty | None, ...),
        confidence=(float, Field(ge=0, le=1)),
        dimensions=(rubric.dimensions_model, ...),
        reason=(Text, ...),
        solution_reasoning=(Text, ...),
        concepts_and_dependencies=(Text, ...),
        shortcuts=(Text, ...),
        nearest_anchor=(Text, ...),
        domain_variation=(Text, ...),
        unable_to_assess_reason=(Text | None, ...),
        quality_concerns=(list[Text], ...),
    )

    evidence = create_model(
        f"EvidenceFor{distractor_count}DistractorRecipes",
        __base__=DifficultyRecord,
        **{f"D{i}": (OptionExplanation, ...) for i in range(1, distractor_count + 1)},
    )

    return create_model(
        f"TemplateDifficultyFor{distractor_count}Distractors",
        __base__=assessment,
        distractor_evidence=(evidence, ...),
    )


def template_assessment_model(
    rubric: DifficultyRubric, distractor_count: int
) -> type[BaseModel]:
    if not MIN_DISTRACTORS <= distractor_count <= MAX_DISTRACTOR_CANDIDATES:
        raise ValueError(
            f"expected {MIN_DISTRACTORS} to {MAX_DISTRACTOR_CANDIDATES} "
            "distractor recipes"
        )

    return _assessment_model(rubric.rubric_id, distractor_count)


def build_template_decision_request(
    *,
    rubric: DifficultyRubric,
    question_payload: str,
) -> StructuredGenerationRequest:
    return StructuredGenerationRequest(
        messages=[
            {
                "role": "system",
                "content": (
                    DECISION_INSTRUCTION + rubric.scope + "\n" + rubric.reference
                ),
            },
            {"role": "user", "content": question_payload},
        ],
        response_model=ClassDecision,
        prompt_version=rubric.decision_prompt_version,
        schema_name=rubric.decision_schema_name,
    )


def build_template_difficulty_request(
    *,
    rubric: DifficultyRubric,
    question_payload: str,
    distractor_count: int,
) -> StructuredGenerationRequest:
    return StructuredGenerationRequest(
        messages=[
            {
                "role": "system",
                "content": (
                    rubric.scope + rubric.reasoning_procedure + rubric.reference
                ),
            },
            {"role": "user", "content": question_payload},
        ],
        response_model=template_assessment_model(rubric, distractor_count),
        prompt_version=rubric.reasoning_prompt_version,
        schema_name=rubric.reasoning_schema_name,
    )


async def assess_template_difficulty(
    *,
    rubric_id: str,
    question_payload: str,
    distractor_count: int,
    requested_difficulty: Difficulty,
    subject_sha256: str,
    provider_factory: JudgeProviderFactory,
    judge_timeout_seconds: float = DEFAULT_JUDGE_TIMEOUT_SECONDS,
    settings: JudgeSettings | None = None,
) -> ToolEvidence:
    if not math.isfinite(judge_timeout_seconds) or judge_timeout_seconds <= 0:
        raise ValueError("judge timeout must be finite and positive")

    started = time.perf_counter()
    selected = settings if settings is not None else JudgeSettings()

    try:
        rubric = difficulty_rubric(rubric_id)
        decision_request = build_template_decision_request(
            rubric=rubric,
            question_payload=question_payload,
        )
        reasoning_request = build_template_difficulty_request(
            rubric=rubric,
            question_payload=question_payload,
            distractor_count=distractor_count,
        )
    except (OSError, ValueError):
        return _rubric_unavailable(
            rubric_id=rubric_id,
            subject_sha256=subject_sha256,
            requested_difficulty=requested_difficulty,
            started=started,
        )

    providers = JudgeProviderSession(provider_factory)
    screen = await run_decision(
        decision_request,
        labels=("easy", "medium", "hard"),
        provider_factory=providers.decision_provider,
        timeout_seconds=min(selected.decision_timeout_seconds, judge_timeout_seconds),
    )
    if _accept_decision(screen, selected):
        outcome = _policy_outcome(screen, requested_difficulty, "decision", selected)
        return _build_evidence(
            rubric=rubric,
            settings=selected,
            screen=screen,
            reasoning=None,
            outcome=outcome,
            subject_sha256=subject_sha256,
            requested_difficulty=requested_difficulty,
            started=started,
        )

    remaining = judge_timeout_seconds - (time.perf_counter() - started)
    reasoning_request = replace(
        reasoning_request, reasoning_effort=selected.reasoning_effort
    )
    judge = (
        failed_judge(reasoning_request, "JUDGE_TIMEOUT", 0)
        if remaining <= 0
        else await run_judge(
            reasoning_request,
            provider_factory=providers.reasoning_provider,
            timeout_seconds=remaining,
        )
    )

    outcome = _policy_outcome(judge, requested_difficulty, "reasoning", selected)
    return _build_evidence(
        rubric=rubric,
        settings=selected,
        screen=screen,
        reasoning=judge,
        outcome=outcome,
        subject_sha256=subject_sha256,
        requested_difficulty=requested_difficulty,
        started=started,
    )


def _rubric_unavailable(
    *,
    rubric_id: str,
    subject_sha256: str,
    requested_difficulty: Difficulty,
    started: float,
) -> ToolEvidence:
    outcome = DifficultyOutcome(
        assessment_path="decision",
        requested_difficulty=requested_difficulty,
        error_code="RUBRIC_UNAVAILABLE",
        reason="Difficulty rubric unavailable. No assessment was made.",
    )
    return ToolEvidence(
        tool=TEMPLATE_DIFFICULTY_CHECK,
        version=TEMPLATE_DIFFICULTY_TOOL_VERSION,
        status="error",
        findings=[
            ToolFinding(
                code="RUBRIC_UNAVAILABLE",
                message="Difficulty rubric unavailable. No assessment was made.",
            )
        ],
        details={
            "advisory": True,
            "retryable": False,
            "rubric_id": rubric_id,
            "subject_sha256": subject_sha256,
            "requested_difficulty": requested_difficulty,
            "difficulty_outcome": outcome.model_dump(mode="json"),
        },
        duration_ms=(time.perf_counter() - started) * 1000,
    )


def _accept_decision(screen, settings):
    return (
        screen.status == "completed"
        and screen.assessment.confidence >= settings.decision_threshold
    )


def _policy_outcome(judge, requested, path, settings):
    if judge.status == "error":
        return DifficultyOutcome(
            assessment_path=path,
            requested_difficulty=requested,
            error_code=judge.error_code,
            reason="Difficulty assessment unavailable. No check retry was made.",
        )

    assessment = judge.assessment
    is_decision = isinstance(assessment, ClassDecision)
    estimate = assessment.label if is_decision else assessment.estimated_difficulty
    if estimate is None:
        return DifficultyOutcome(
            assessment_path=path,
            requested_difficulty=requested,
            status="failed",
            error_code="DIFFICULTY_UNABLE_TO_ASSESS",
            reason=assessment.unable_to_assess_reason,
        )

    matches = compare_difficulty(estimate, requested) == "matches"
    decisive = is_decision or assessment.confidence >= settings.reasoning_threshold
    decision = "matches" if matches else "advisory_mismatch"
    return DifficultyOutcome(
        assessment_path=path,
        requested_difficulty=requested,
        estimated_difficulty=estimate,
        confidence=assessment.confidence,
        confidence_source="first_token_label_mass" if is_decision else "self_reported",
        decision=decision,
        # A decisive mismatch stays an honest advisory failure. It never gates
        # technical checking or requests an author revision.
        status="failed" if not matches and decisive else "passed",
        reason="Forced decision from first-token label probabilities."
        if is_decision
        else assessment.reason,
    )


def _findings(outcome, requested):
    if outcome.error_code:
        return [ToolFinding(code=outcome.error_code, message=outcome.reason)]

    if outcome.decision == "matches":
        return []

    return [
        ToolFinding(
            code="DIFFICULTY_MISMATCH"
            if outcome.status == "failed"
            else "DIFFICULTY_MISMATCH_LOW_CONFIDENCE",
            message=(
                f"Typical instance estimated {outcome.estimated_difficulty}. "
                f"Requested {requested}. Confidence ({outcome.confidence_source}) "
                f"{outcome.confidence:.2f}. {outcome.reason}"
            ),
            field="difficulty",
        )
    ]


def _build_evidence(
    *,
    rubric,
    settings,
    screen,
    reasoning,
    outcome,
    subject_sha256,
    requested_difficulty,
    started,
):
    judge = screen if reasoning is None else reasoning
    calls = [*screen.model_calls, *(reasoning.model_calls if reasoning else [])]

    details = {
        "advisory": True,
        "retryable": False,
        "assessment_scope": "typical_instance_uniform_eligible_combinations",
        "policy_version": DIFFICULTY_POLICY_VERSION,
        "high_confidence_threshold": settings.reasoning_threshold,
        "decision_confidence_threshold": settings.decision_threshold,
        "confidence_calibrated": False,
        "rubric_id": rubric.rubric_id,
        "subject_sha256": subject_sha256,
        "requested_difficulty": requested_difficulty,
        "rubric_version": rubric.version,
        "rubric_sha256": rubric.sha256,
        "assessment_conditions_version": rubric.assessment_conditions_version,
        "screen": screen.model_dump(mode="json"),
        "judge": judge.model_dump(mode="json"),
        "difficulty_outcome": outcome.model_dump(mode="json"),
        "usage": summarize_usage(calls).model_dump(mode="json"),
        "model_calls": [call.model_dump(mode="json") for call in calls],
    }

    if outcome.estimated_difficulty is not None:
        details["difficulty_match"] = compare_difficulty(
            outcome.estimated_difficulty, requested_difficulty
        )
    return ToolEvidence(
        tool=TEMPLATE_DIFFICULTY_CHECK,
        version=TEMPLATE_DIFFICULTY_TOOL_VERSION,
        status=outcome.status,
        findings=_findings(outcome, requested_difficulty),
        details=details,
        duration_ms=(time.perf_counter() - started) * 1000,
    )
