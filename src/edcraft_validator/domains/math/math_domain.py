"""Math-domain implementation of the generic domain contract."""

from pydantic import BaseModel, ValidationError

from edcraft_validator.domains.math.candidate_builder import (
    build_math_candidate,
    template_sha256,
)
from edcraft_validator.domains.math.math_schemas import (
    MathDistractorRecipe,
    MathQuestionInstance,
    MathTemplateCandidate,
    MathTemplateContent,
    MathTemplateRequest,
    MathValidationSummary,
    ValidatedMathTemplate,
)
from edcraft_validator.domains.math.math_types import (
    MATH_ADVISORY_CHECK_NAMES,
    MATH_ANSWERS_TOOL,
    MATH_RELEVANCE_TOOL,
    MIN_DISTRACTORS,
)
from edcraft_validator.domains.math.prompt_builder import (
    build_math_generation_request,
)
from edcraft_validator.domains.math.proposal_response import MathProposalResponse
from edcraft_validator.domains.math.question_generator import generate_math_question
from edcraft_validator.llm.llm_contracts import (
    PlannedGenerationResponse,
    StructuredGenerationRequest,
)
from edcraft_validator.validation.check_contracts import ToolEvidence
from edcraft_validator.validation.validation_contracts import ValidationEvidence


class MathDomain:
    """Prompting, validation, and expansion for linear-equation templates."""

    name = "math"
    request_model = MathTemplateRequest
    candidate_model = MathTemplateCandidate
    validated_model = ValidatedMathTemplate
    question_model = MathQuestionInstance

    def generation_request(
        self, request: BaseModel
    ) -> StructuredGenerationRequest[PlannedGenerationResponse[MathProposalResponse]]:
        typed_request = _require_type(request, MathTemplateRequest)
        return build_math_generation_request(typed_request)

    def build_candidate(
        self, request: BaseModel, proposal: BaseModel
    ) -> MathTemplateCandidate:
        return build_math_candidate(
            _require_type(request, MathTemplateRequest),
            _require_type(proposal, MathTemplateContent),
        )

    def tool_bindings(self, request, candidate, tool_name):
        """Application-owned values never come from model tool arguments."""
        bindings = {
            "candidate": _require_type(candidate, MathTemplateCandidate).model_dump(
                mode="json"
            )
        }
        if tool_name == MATH_RELEVANCE_TOOL:
            bindings["author_request"] = _require_type(
                request, MathTemplateRequest
            ).prompt
        if tool_name == MATH_ANSWERS_TOOL:
            bindings["required_distractors"] = _require_type(
                request, MathTemplateRequest
            ).num_distractors
        return bindings

    def finalize_checked_template(
        self, candidate: BaseModel, evidence: list[ToolEvidence]
    ) -> ValidatedMathTemplate:
        """Package actual checked outputs without re-execution or repair."""
        template = _require_type(candidate, MathTemplateCandidate)
        if not evidence or any(
            item.status != "passed" and item.tool not in MATH_ADVISORY_CHECK_NAMES
            for item in evidence
        ):
            raise ValueError("All selected checks must pass")
        semantic = next(
            (item for item in evidence if item.tool == MATH_ANSWERS_TOOL),
            None,
        )
        if semantic is None or semantic.status != "passed":
            raise ValueError("Missing exhaustive exact-answer and distractor evidence")
        selected_payload = semantic.details.get("selected_distractors")
        if not isinstance(selected_payload, list):
            raise ValueError("Checked distractor selection is missing")
        try:
            selected = [
                MathDistractorRecipe.model_validate(item) for item in selected_payload
            ]
        except ValidationError as exc:
            raise ValueError("Checked distractor selection is malformed") from exc
        if len(selected) < MIN_DISTRACTORS:
            raise ValueError("No checked distractor recipes were selected")
        if any(recipe not in template.distractors for recipe in selected):
            raise ValueError("Selected distractors are not checked proposal recipes")
        reusable = template.model_copy(
            update={"distractors": selected},
            deep=True,
        )
        reusable = MathTemplateCandidate.model_validate(reusable.model_dump())
        expected_sha256 = template_sha256(reusable)
        saved_evidence = [_saved_evidence(item, expected_sha256) for item in evidence]
        try:
            summary = MathValidationSummary.model_validate(
                {
                    "checking_mode": semantic.details["checking_mode"],
                    "combinations_checked": semantic.details["combinations_checked"],
                    "max_combinations": semantic.details["max_combinations"],
                    "seed": semantic.details["seed"],
                    "evidence": saved_evidence,
                }
            )
        except (KeyError, ValidationError) as exc:
            raise ValueError(
                "Checked answer evidence is missing its bound-domain summary"
            ) from exc
        return ValidatedMathTemplate(
            template=reusable,
            validation=summary,
        )

    def checked_tool_bindings(self, request, candidate, tool_name, evidence):
        """Assess exactly the reusable template produced by correctness checks."""
        semantic = [
            item
            for item in evidence
            if item.tool == MATH_ANSWERS_TOOL and item.status == "passed"
        ]
        checked = self.finalize_checked_template(candidate, semantic)
        return self.tool_bindings(request, checked.template, tool_name)

    def generate_question(
        self, validated: BaseModel, *, seed: int
    ) -> MathQuestionInstance:
        return generate_math_question(
            _require_type(validated, ValidatedMathTemplate), seed
        )


def _saved_evidence(item: ToolEvidence, expected_sha256: str) -> ValidationEvidence:
    """Keep technical passes and advisory verdicts distinct in saved evidence."""
    if item.tool not in MATH_ADVISORY_CHECK_NAMES:
        return ValidationEvidence(
            check=item.tool,
            status="passed",
            duration_ms=item.duration_ms,
            issues=[finding.model_dump() for finding in item.findings],
            details={"tool_version": item.version},
        )
    details = {"tool_version": item.version, **item.details}
    recorded_sha256 = item.details.get("template_sha256")
    if recorded_sha256 is None:
        details.update(
            unavailable=True,
            unavailable_reason="Assessment evidence is missing its template identity",
        )
        status = "incomplete"
    elif recorded_sha256 != expected_sha256:
        details.update(
            unavailable=True,
            unavailable_reason="Assessment evidence belongs to a different template",
        )
        status = "incomplete"
    elif item.status == "failed":
        status = "failed"
    elif item.status == "error":
        details.update(
            unavailable=True,
            unavailable_reason="Advisory assessment did not return a verdict",
        )
        status = "incomplete"
    else:
        status = "passed"
    return ValidationEvidence(
        check=item.tool,
        status=status,
        duration_ms=item.duration_ms,
        issues=[finding.model_dump() for finding in item.findings],
        details=details,
    )


def _require_type[ModelT: BaseModel](value: BaseModel, model: type[ModelT]) -> ModelT:
    if not isinstance(value, model):
        raise TypeError(f"math domain requires {model.__name__}")
    return value
