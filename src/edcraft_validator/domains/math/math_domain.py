"""Math-domain implementation of the generic domain contract."""

from typing import Any

from pydantic import BaseModel

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
from edcraft_validator.domains.math.ir.instantiate import representative_item
from edcraft_validator.domains.math.math_schemas import (
    MathQuestionInstance,
    MathTemplateCandidate,
    MathTemplateContent,
    MathTemplateRequest,
    MathValidationSummary,
    ValidatedMathTemplate,
)
from edcraft_validator.domains.math.math_types import (
    MATH_ADVISORY_CHECK_NAMES,
    MATH_CHECKING_MODE,
    MATH_DIFFICULTY_TOOL,
    MATH_FIDELITY_TOOL,
    MATH_ITEM_SPEC_TOOL,
    MATH_OPTIONS_TOOL,
    MAX_DISTRACTORS,
    MAX_IR_VARIANTS,
    MIN_DISTRACTORS,
)
from edcraft_validator.domains.math.prompt_builder import (
    build_math_generation_request,
)
from edcraft_validator.domains.math.question_generator import generate_math_question
from edcraft_validator.domains.math.relevance import template_relevance_text
from edcraft_validator.domains.math.validation.harness import validate_template
from edcraft_validator.llm.llm_contracts import (
    PlannedGenerationResponse,
    StructuredGenerationRequest,
)
from edcraft_validator.validation.check_contracts import ToolEvidence
from edcraft_validator.validation.check_names import (
    TEMPLATE_RELEVANCE_CAPABILITY,
    TEMPLATE_RELEVANCE_CHECK,
)


class MathDomain:
    """Prompting, validation, and expansion for generic math templates."""

    name = "math"
    request_model = MathTemplateRequest
    candidate_model = MathTemplateCandidate
    validated_model = ValidatedMathTemplate
    question_model = MathQuestionInstance
    template_language = None
    capabilities = frozenset({TEMPLATE_RELEVANCE_CAPABILITY})

    def review_view(
        self, artifact: ValidatedTemplateArtifact
    ) -> ReviewTemplateView | None:
        return build_review_view(artifact, language=self.template_language)

    def generation_request(
        self, request: BaseModel
    ) -> StructuredGenerationRequest[PlannedGenerationResponse[MathTemplateContent]]:
        typed_request = require_type(request, MathTemplateRequest)
        return build_math_generation_request(typed_request)

    def build_candidate(
        self, request: BaseModel, proposal: BaseModel
    ) -> MathTemplateCandidate:
        return build_math_candidate(
            require_type(request, MathTemplateRequest),
            require_type(proposal, MathTemplateContent),
        )

    def tool_bindings(
        self, request: BaseModel, candidate: BaseModel, tool_name: str
    ) -> dict[str, Any]:
        """Application-owned values never come from model tool arguments."""
        typed_candidate = require_type(candidate, MathTemplateCandidate)
        template = typed_candidate.item
        if template is None:
            raise ValueError("generic bindings require an item template")
        if tool_name == TEMPLATE_RELEVANCE_CHECK:
            return {
                "author_request": require_type(request, MathTemplateRequest).prompt,
                "question_text": template_relevance_text(typed_candidate),
                "subject_sha256": template_sha256(typed_candidate),
            }
        if tool_name == MATH_ITEM_SPEC_TOOL:
            return {"template": template.model_dump(mode="json")}
        if tool_name == MATH_OPTIONS_TOOL:
            return {"template": template.model_dump(mode="json")}
        if tool_name == MATH_FIDELITY_TOOL:
            # Prose parse-back needs a concrete item: parameter nodes are not
            # expressions the blind reconstruction can compare.
            return {"item": representative_item(template).model_dump(mode="json")}
        if tool_name == MATH_DIFFICULTY_TOOL:
            return {"candidate": typed_candidate.model_dump(mode="json")}
        return {"candidate": typed_candidate.model_dump(mode="json")}

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
        item_spec = next(
            (item for item in evidence if item.tool == MATH_ITEM_SPEC_TOOL),
            None,
        )
        if item_spec is None or item_spec.status != "passed":
            raise ValueError("Missing passing generic item-spec evidence")
        options = next(
            (item for item in evidence if item.tool == MATH_OPTIONS_TOOL),
            None,
        )
        if options is None or options.status != "passed":
            raise ValueError("Missing passing option-check evidence")
        template_spec = template.item
        if template_spec is None:
            raise ValueError("Generic finalization requires an item template")
        distractor_count = len(template_spec.body.distractors)
        if distractor_count < MIN_DISTRACTORS:
            raise ValueError("Generic templates require at least one distractor")
        if distractor_count > MAX_DISTRACTORS:
            raise ValueError(
                f"Generic templates allow at most {MAX_DISTRACTORS} distractors"
            )
        if template_spec.body.text.mode == "prose":
            fidelity = next(
                (item for item in evidence if item.tool == MATH_FIDELITY_TOOL),
                None,
            )
            if fidelity is None or fidelity.status != "passed":
                raise ValueError("Prose items require passing text-fidelity evidence")
        report = validate_template(template_spec, max_variants=MAX_IR_VARIANTS)
        if not report.passed:
            detail = "; ".join(report.report.findings) or report.report.status
            raise ValueError(f"IR validation did not pass: {detail}")
        if report.variants_checked < 1:
            raise ValueError("IR validation checked no parameter combinations")
        expected_sha256 = template_sha256(template)
        saved_evidence = [
            save_checked_evidence(
                item, expected_sha256, advisory_names=MATH_ADVISORY_CHECK_NAMES
            )
            for item in evidence
        ]
        summary = MathValidationSummary(
            checking_mode=MATH_CHECKING_MODE,
            combinations_checked=report.variants_checked,
            max_combinations=report.variants_total,
            seed=0,
            evidence=saved_evidence,
        )
        return ValidatedMathTemplate(template=template, validation=summary)

    def checked_tool_bindings(
        self,
        request: BaseModel,
        candidate: BaseModel,
        tool_name: str,
        evidence: list[ToolEvidence],
    ) -> dict[str, Any]:
        """Assess exactly the reusable template produced by correctness checks."""
        typed = require_type(candidate, MathTemplateCandidate)
        checked_evidence = [
            item
            for item in evidence
            if item.status == "passed"
            and item.tool
            in {MATH_ITEM_SPEC_TOOL, MATH_OPTIONS_TOOL, MATH_FIDELITY_TOOL}
        ]
        checked = self.finalize_checked_template(typed, checked_evidence)
        return self.tool_bindings(request, checked.template, tool_name)

    def generate_question(
        self, validated: BaseModel, *, seed: int
    ) -> MathQuestionInstance:
        return generate_math_question(
            require_type(validated, ValidatedMathTemplate), seed
        )
