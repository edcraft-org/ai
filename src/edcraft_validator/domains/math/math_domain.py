"""Math-domain implementation of the generic domain contract."""

from pydantic import BaseModel, ValidationError

from edcraft_validator.artifact_contracts import ValidatedTemplateArtifact
from edcraft_validator.domains.domain_support import (
    ReviewTemplateView,
    build_review_view,
    require_type,
    save_checked_evidence,
)
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
    MATH_STRUCTURE_TOOL,
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


class MathDomain:
    """Prompting, validation, and expansion for linear-equation templates."""

    name = "math"
    request_model = MathTemplateRequest
    candidate_model = MathTemplateCandidate
    validated_model = ValidatedMathTemplate
    question_model = MathQuestionInstance
    template_language = None

    def review_view(
        self, artifact: ValidatedTemplateArtifact
    ) -> ReviewTemplateView | None:
        return build_review_view(artifact, language=self.template_language)

    def generation_request(
        self, request: BaseModel
    ) -> StructuredGenerationRequest[PlannedGenerationResponse[MathProposalResponse]]:
        typed_request = require_type(request, MathTemplateRequest)
        return build_math_generation_request(typed_request)

    def build_candidate(
        self, request: BaseModel, proposal: BaseModel
    ) -> MathTemplateCandidate:
        return build_math_candidate(
            require_type(request, MathTemplateRequest),
            require_type(proposal, MathTemplateContent),
        )

    def tool_bindings(self, request, candidate, tool_name):
        """Application-owned values never come from model tool arguments."""
        bindings = {
            "candidate": require_type(candidate, MathTemplateCandidate).model_dump(
                mode="json"
            )
        }
        if tool_name == MATH_RELEVANCE_TOOL:
            bindings["author_request"] = require_type(
                request, MathTemplateRequest
            ).prompt
        if tool_name == MATH_ANSWERS_TOOL:
            bindings["required_distractors"] = require_type(
                request, MathTemplateRequest
            ).num_distractors
        return bindings

    def finalize_checked_template(
        self, candidate: BaseModel, evidence: list[ToolEvidence]
    ) -> ValidatedMathTemplate:
        """Package actual checked outputs without re-execution or repair."""
        template = require_type(candidate, MathTemplateCandidate)
        if not evidence or any(
            item.status != "passed" and item.tool not in MATH_ADVISORY_CHECK_NAMES
            for item in evidence
        ):
            raise ValueError("All selected checks must pass")
        structure = next(
            (item for item in evidence if item.tool == MATH_STRUCTURE_TOOL),
            None,
        )
        if structure is None or structure.status != "passed":
            raise ValueError("Missing passing template-structure evidence")
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
        saved_evidence = [
            save_checked_evidence(
                item, expected_sha256, advisory_names=MATH_ADVISORY_CHECK_NAMES
            )
            for item in evidence
        ]
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
        checked_evidence = [
            item
            for item in evidence
            if item.status == "passed"
            and item.tool in {MATH_ANSWERS_TOOL, MATH_STRUCTURE_TOOL}
        ]
        checked = self.finalize_checked_template(candidate, checked_evidence)
        return self.tool_bindings(request, checked.template, tool_name)

    def generate_question(
        self, validated: BaseModel, *, seed: int
    ) -> MathQuestionInstance:
        return generate_math_question(
            require_type(validated, ValidatedMathTemplate), seed
        )
