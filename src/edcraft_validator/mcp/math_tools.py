"""Exact structure and answer checks plus advisory math assessments."""

from __future__ import annotations

import time
from itertools import product
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field, ValidationError

from edcraft_validator.application.authoring_contracts import (
    DifficultyOutcome,
    RelevanceOutcome,
)
from edcraft_validator.domains.math.candidate_builder import template_sha256
from edcraft_validator.domains.math.math_schemas import (
    MathTemplateCandidate,
    template_fields,
)
from edcraft_validator.domains.math.math_types import (
    MATH_ANSWERS_TOOL,
    MATH_DIFFICULTY_TOOL,
    MATH_PARAMETER_NAMES,
    MATH_RELEVANCE_TOOL,
    MATH_STRUCTURE_TOOL,
    MATH_TOOL_VERSION,
    MAX_DISTRACTORS,
    MIN_DISTRACTORS,
)
from edcraft_validator.domains.math.safe_linear import (
    evaluate_expression,
    validate_expression,
)
from edcraft_validator.validation.check_contracts import ToolEvidence, ToolFinding

_RELEVANCE_THRESHOLD = 0.2
_RELEVANCE_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "about",
        "create",
        "for",
        "from",
        "generate",
        "in",
        "of",
        "on",
        "question",
        "the",
        "to",
        "with",
    }
)

CandidateArgument = Annotated[
    MathTemplateCandidate,
    Field(
        description=(
            "Complete linear-equation template candidate to check. The tool treats "
            "it as untrusted input and does not modify the supplied object."
        )
    ),
]


class MathToolFailure(ValueError):
    """A validation failure with an actionable finding code."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "TEMPLATE_INVALID",
        field: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.field = field
        self.context = context or {}


def register_math_tools(server: FastMCP) -> None:
    """Register the math-domain validation and advisory catalogue."""

    @server.tool(
        name=MATH_STRUCTURE_TOOL,
        version=MATH_TOOL_VERSION,
        tags={"domain:math"},
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        description=(
            "Establish that a linear-equation template uses the supported "
            "a, b, c parameters, well-formed equation and question placeholders, "
            "bounded integer values, at least one distractor, and only the allowed "
            "arithmetic expression subset. The check is static and does not "
            "compute answers or establish that distractors are wrong."
        ),
    )
    async def math_verify_template_structure(
        candidate: CandidateArgument,
    ) -> ToolEvidence:
        return _run_tool(
            MATH_STRUCTURE_TOOL,
            lambda: verify_template_structure(candidate),
        )

    @server.tool(
        name=MATH_ANSWERS_TOOL,
        version=MATH_TOOL_VERSION,
        tags={"domain:math"},
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        description=(
            "Exhaustively enumerate the bounded a, b, c parameter domain and "
            "compute exact rational answers for the answer recipe. Require every "
            "answer to be well-defined, every selected distractor to differ from "
            "the answer, and all selected distractors to be pairwise distinct for "
            "every declared combination. Returns the checked distractor recipes "
            "in details.selected_distractors. This is bounded-domain evidence, not "
            "proof for undeclared coefficient values; generated drafts still "
            "require manual review."
        ),
    )
    async def math_validate_answers_and_distractors(
        candidate: CandidateArgument,
        required_distractors: Annotated[
            int,
            Field(
                ge=MIN_DISTRACTORS,
                le=MAX_DISTRACTORS,
                description="Number of checked learner-facing distractors required.",
            ),
        ],
    ) -> ToolEvidence:
        return _run_tool(
            MATH_ANSWERS_TOOL,
            lambda: validate_answers_and_distractors(candidate, required_distractors),
        )

    @server.tool(
        name=MATH_DIFFICULTY_TOOL,
        version=MATH_TOOL_VERSION,
        tags={
            "domain:math",
            "quality:math",
            "stage:after-validation",
            "policy:advisory",
        },
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        description=(
            "Provide a provisional heuristic difficulty assessment for a checked "
            "linear-equation template. Uses coefficient magnitude, sign variety, "
            "parameter-domain size, and distractor count. The estimate is advisory "
            "and uncalibrated; a mismatch never blocks a technically checked "
            "template or requests author revision. No model call is made."
        ),
    )
    async def math_assess_template_difficulty(
        candidate: CandidateArgument,
    ) -> ToolEvidence:
        return assess_template_difficulty(candidate)

    @server.tool(
        name=MATH_RELEVANCE_TOOL,
        version=MATH_TOOL_VERSION,
        tags={
            "domain:math",
            "quality:math",
            "stage:after-validation",
            "policy:advisory",
        },
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        description=(
            "Compare a checked linear-equation template with the original author "
            "request using a conservative keyword-overlap heuristic. The "
            "application supplies the unchanged request. A low overlap is advisory "
            "evidence for educator review and never blocks a technically checked "
            "template. No model call, embedding, or external I/O is used."
        ),
    )
    async def math_assess_template_relevance(
        candidate: CandidateArgument,
        author_request: Annotated[str, Field(min_length=1, max_length=4000)],
    ) -> ToolEvidence:
        return assess_template_relevance(candidate, author_request)


def _run_tool(name: str, operation) -> ToolEvidence:
    started = time.perf_counter()
    try:
        details = operation()
    except MathToolFailure as exc:
        return ToolEvidence(
            tool=name,
            version=MATH_TOOL_VERSION,
            status="failed",
            findings=[ToolFinding(code=exc.code, message=str(exc), field=exc.field)],
            details=exc.context,
            duration_ms=_elapsed_ms(started),
        )
    except ValidationError as exc:
        return ToolEvidence(
            tool=name,
            version=MATH_TOOL_VERSION,
            status="failed",
            findings=[
                ToolFinding(
                    code="TEMPLATE_INVALID",
                    message=f"Candidate does not match the math template schema: {exc}",
                )
            ],
            duration_ms=_elapsed_ms(started),
        )
    except Exception as exc:
        return ToolEvidence(
            tool=name,
            version=MATH_TOOL_VERSION,
            status="error",
            findings=[
                ToolFinding(
                    code="TOOL_EXECUTION_ERROR",
                    message=f"Validation tool failed with {type(exc).__name__}",
                )
            ],
            duration_ms=_elapsed_ms(started),
        )
    return ToolEvidence(
        tool=name,
        version=MATH_TOOL_VERSION,
        status="passed",
        details=details,
        duration_ms=_elapsed_ms(started),
    )


def verify_template_structure(
    candidate: MathTemplateCandidate,
) -> dict[str, Any]:
    """Check placeholders, bounds, and the allowlisted expression subset."""
    candidate = _revalidate(candidate)
    try:
        validate_expression(candidate.answer_expression)
    except ValueError as exc:
        raise MathToolFailure(
            f"Answer expression is unsupported: {exc}",
            code="EXPRESSION_UNSUPPORTED",
            field="answer_expression",
        ) from exc
    for index, recipe in enumerate(candidate.distractors):
        try:
            validate_expression(recipe.expression)
        except ValueError as exc:
            raise MathToolFailure(
                f"Distractor expression is unsupported: {exc}",
                code="EXPRESSION_UNSUPPORTED",
                field=f"distractors.{index}.expression",
            ) from exc
        try:
            unknown = template_fields(recipe.reason_template) - set(
                MATH_PARAMETER_NAMES
            )
        except ValueError as exc:
            raise MathToolFailure(
                f"Distractor reason template is invalid: {exc}",
                code="REASON_TEMPLATE_INVALID",
                field=f"distractors.{index}.reason_template",
            ) from exc
        if unknown:
            raise MathToolFailure(
                "Distractor reason uses unsupported placeholders: "
                + ", ".join(sorted(unknown)),
                code="REASON_PLACEHOLDER_UNSUPPORTED",
                field=f"distractors.{index}.reason_template",
            )
    coefficient_a = next(
        parameter for parameter in candidate.parameters if parameter.name == "a"
    )
    if 0 in coefficient_a.values:
        raise MathToolFailure(
            "Parameter a must never be zero",
            code="NONZERO_COEFFICIENT_REQUIRED",
            field="parameters.a",
        )
    combinations = _parameter_combinations(candidate)
    return {
        "parameters": len(candidate.parameters),
        "combinations": len(combinations),
        "distractors": len(candidate.distractors),
        "expressions_checked": 1 + len(candidate.distractors),
    }


def validate_answers_and_distractors(
    candidate: MathTemplateCandidate, required_distractors: int
) -> dict[str, Any]:
    """Check exact answers and distractors over the complete bounded domain."""
    candidate = _revalidate(candidate)
    if not MIN_DISTRACTORS <= required_distractors <= MAX_DISTRACTORS:
        raise MathToolFailure(
            "Required distractor count is outside the supported range",
            code="DISTRACTOR_COUNT_INVALID",
            field="required_distractors",
        )
    if len(candidate.distractors) < required_distractors:
        raise MathToolFailure(
            "The template supplies fewer distractor recipes than required",
            code="INSUFFICIENT_DISTRACTORS",
            field="distractors",
            context={
                "available": len(candidate.distractors),
                "required": required_distractors,
            },
        )
    combinations = _parameter_combinations(candidate)
    selected = candidate.distractors[:required_distractors]
    for values in combinations:
        if values["a"] == 0:
            raise MathToolFailure(
                "Parameter a must never be zero",
                code="NONZERO_COEFFICIENT_REQUIRED",
                field="parameters.a",
                context={"failing_parameters": values},
            )
        try:
            answer = evaluate_expression(candidate.answer_expression, values)
        except ValueError as exc:
            raise MathToolFailure(
                f"Answer recipe is not well-defined: {exc}",
                code="ANSWER_UNDEFINED",
                field="answer_expression",
                context={"failing_parameters": values},
            ) from exc
        seen: set[Any] = set()
        for index, recipe in enumerate(selected):
            try:
                distractor = evaluate_expression(recipe.expression, values)
            except ValueError as exc:
                raise MathToolFailure(
                    f"Distractor recipe is not well-defined: {exc}",
                    code="DISTRACTOR_UNDEFINED",
                    field=f"distractors.{index}.expression",
                    context={"failing_parameters": values},
                ) from exc
            if distractor == answer:
                raise MathToolFailure(
                    "A distractor coincides with the answer for a declared "
                    "parameter combination",
                    code="DISTRACTOR_MATCHES_ANSWER",
                    field=f"distractors.{index}.expression",
                    context={
                        "failing_parameters": values,
                        "distractor_index": index,
                    },
                )
            if distractor in seen:
                raise MathToolFailure(
                    "Two selected distractors coincide for a declared parameter "
                    "combination",
                    code="DISTRACTOR_COLLISION",
                    field=f"distractors.{index}.expression",
                    context={
                        "failing_parameters": values,
                        "distractor_index": index,
                    },
                )
            seen.add(distractor)
    return {
        "checking_mode": "exhaustive_domain",
        "combinations_checked": len(combinations),
        "max_combinations": len(combinations),
        "seed": 0,
        "selected_distractors": [recipe.model_dump(mode="json") for recipe in selected],
    }


def assess_template_difficulty(
    candidate: MathTemplateCandidate,
) -> ToolEvidence:
    """Return a deterministic provisional difficulty estimate."""
    started = time.perf_counter()
    candidate = _revalidate(candidate)
    estimate = _estimate_difficulty(candidate)
    matches = estimate == candidate.difficulty
    outcome = DifficultyOutcome(
        assessment_path="reasoning",
        requested_difficulty=candidate.difficulty,
        estimated_difficulty=estimate,
        confidence=0.55,
        confidence_source="self_reported",
        decision="matches" if matches else "advisory_mismatch",
        status="passed" if matches else "failed",
        reason=(
            "Provisional heuristic estimate from coefficient magnitude, sign "
            "variety, parameter-domain size, and distractor count; not calibrated."
        ),
    )
    findings = (
        []
        if matches
        else [
            ToolFinding(
                code="DIFFICULTY_MISMATCH",
                message=(
                    f"Heuristic estimate is {estimate}; requested "
                    f"{candidate.difficulty}. Advisory only."
                ),
                field="difficulty",
            )
        ]
    )
    details = {
        "advisory": True,
        "provisional": True,
        "calibrated": False,
        "template_sha256": template_sha256(candidate),
        "requested_difficulty": candidate.difficulty,
        "difficulty_outcome": outcome.model_dump(mode="json"),
        **outcome.model_dump(
            mode="json",
            include={
                "assessment_path",
                "requested_difficulty",
                "estimated_difficulty",
                "confidence",
                "confidence_source",
                "decision",
            },
        ),
    }
    return ToolEvidence(
        tool=MATH_DIFFICULTY_TOOL,
        version=MATH_TOOL_VERSION,
        status=outcome.status,
        findings=findings,
        details=details,
        duration_ms=_elapsed_ms(started),
    )


def assess_template_relevance(
    candidate: MathTemplateCandidate, author_request: str
) -> ToolEvidence:
    """Return a conservative keyword-overlap relevance verdict."""
    started = time.perf_counter()
    candidate = _revalidate(candidate)
    request_tokens = _tokens(author_request)
    template_tokens = _tokens(
        "linear equation solve for x "
        f"{candidate.equation_template} {candidate.question_template}"
    )
    if not request_tokens:
        outcome = RelevanceOutcome(
            status="unavailable",
            unavailable=True,
            relevant=None,
            reason="Author request has no informative keywords.",
            error_code="RELEVANCE_NO_KEYWORDS",
        )
        return ToolEvidence(
            tool=MATH_RELEVANCE_TOOL,
            version=MATH_TOOL_VERSION,
            status="error",
            findings=[
                ToolFinding(
                    code="RELEVANCE_NO_KEYWORDS",
                    message="Author request has no informative keywords.",
                )
            ],
            details={
                "advisory": True,
                "template_sha256": template_sha256(candidate),
                "relevance_outcome": outcome.model_dump(mode="json"),
            },
            duration_ms=_elapsed_ms(started),
        )
    overlap = len(request_tokens & template_tokens)
    score = overlap / len(request_tokens)
    relevant = score >= _RELEVANCE_THRESHOLD
    outcome = RelevanceOutcome(
        status="assessed",
        unavailable=False,
        score=round(score, 4),
        threshold=_RELEVANCE_THRESHOLD,
        relevant=relevant,
        reason=(
            "Conservative keyword overlap between the original request and the "
            "equation template; advisory and uncalibrated."
        ),
        error_code=None,
    )
    return ToolEvidence(
        tool=MATH_RELEVANCE_TOOL,
        version=MATH_TOOL_VERSION,
        status="passed" if relevant else "failed",
        findings=[]
        if relevant
        else [
            ToolFinding(
                code="RELEVANCE_MISMATCH",
                message=(
                    "The template may not assess the original author request; "
                    "this is advisory evidence, not a technical failure."
                ),
            )
        ],
        details={
            "advisory": True,
            "template_sha256": template_sha256(candidate),
            "score": outcome.score,
            "threshold": outcome.threshold,
            "relevant": relevant,
            "relevance_outcome": outcome.model_dump(mode="json"),
        },
        duration_ms=_elapsed_ms(started),
    )


def _revalidate(candidate: MathTemplateCandidate) -> MathTemplateCandidate:
    try:
        return MathTemplateCandidate.model_validate(candidate.model_dump())
    except ValidationError as exc:
        raise MathToolFailure(
            f"Candidate does not match the math template schema: {exc}",
            code="TEMPLATE_INVALID",
        ) from exc


def _parameter_combinations(
    candidate: MathTemplateCandidate,
) -> list[dict[str, int]]:
    names = tuple(parameter.name for parameter in candidate.parameters)
    return [
        dict(zip(names, values, strict=True))
        for values in product(*(parameter.values for parameter in candidate.parameters))
    ]


def _estimate_difficulty(candidate: MathTemplateCandidate) -> str:
    parameters = {
        parameter.name: parameter.values for parameter in candidate.parameters
    }
    score = 0
    if max(abs(value) for value in parameters["a"]) > 1:
        score += 1
    if any(value < 0 for values in parameters.values() for value in values):
        score += 1
    if max(abs(value) for values in parameters.values() for value in values) >= 10:
        score += 1
    combination_count = len(_parameter_combinations(candidate))
    if combination_count >= 60:
        score += 1
    if len(candidate.distractors) >= 4:
        score += 1
    if score <= 1:
        return "easy"
    if score <= 3:
        return "medium"
    return "hard"


def _tokens(text: str) -> set[str]:
    token = []
    tokens: set[str] = set()
    for character in text.lower():
        if character.isalnum():
            token.append(character)
        elif token:
            word = "".join(token)
            token = []
            if word not in _RELEVANCE_STOPWORDS:
                tokens.add(word)
    if token:
        word = "".join(token)
        if word not in _RELEVANCE_STOPWORDS:
            tokens.add(word)
    return tokens


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000
