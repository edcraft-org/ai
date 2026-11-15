"""Math-domain implementation of the generic domain contract.

The domain builds a candidate from a model proposal, binds its MCP checks,
finalises the checked template, and expands it into a seeded question.
"""

from typing import Any

from fastmcp import FastMCP
from pydantic import BaseModel

from edcraft_validator.artifact_contracts import ValidatedTemplateArtifact
from edcraft_validator.domains.domain_support import (
    ReviewTemplateView,
    build_review_view,
    require_checked,
    require_type,
    save_checked_evidence,
)
from edcraft_validator.domains.math.candidate_builder import (
    build_math_candidate,
    template_sha256,
)
from edcraft_validator.domains.math.ir.instantiate import representative_item
from edcraft_validator.domains.math.ir.schema import MathTemplateSpec
from edcraft_validator.domains.math.math_schemas import (
    MathQuestionInstance,
    MathTemplateCandidate,
    MathTemplateContent,
    MathTemplateRequest,
    MathValidationSummary,
    ValidatedMathTemplate,
)
from edcraft_validator.domains.math.math_types import (
    FORM_SENSITIVE_GOALS,
    MATH_CHECKING_MODE,
    MATH_FIDELITY_TOOL,
    MATH_FORM_TOOL,
    MATH_ITEM_SPEC_TOOL,
    MATH_OPTIONS_TOOL,
    MAX_DISTRACTORS,
    MIN_DISTRACTORS,
)
from edcraft_validator.domains.math.prompt_builder import (
    build_math_generation_request,
)
from edcraft_validator.domains.math.question_generator import generate_math_question
from edcraft_validator.domains.math.relevance import template_relevance_text
from edcraft_validator.llm.llm_contracts import (
    PlannedGenerationResponse,
    StructuredGenerationRequest,
)
from edcraft_validator.mcp.math_tools import register_math_tools
from edcraft_validator.mcp.tool_dependencies import ToolDependencies
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

    def register_tools(self, server: FastMCP, dependencies: ToolDependencies) -> None:
        """Register the math domain's authoritative and advisory tools."""
        register_math_tools(
            server,
            fidelity_provider_factory=dependencies.fidelity_provider_factory,
            fidelity_timeout_seconds=dependencies.fidelity_timeout_seconds,
        )

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
        if tool_name in {MATH_ITEM_SPEC_TOOL, MATH_OPTIONS_TOOL, MATH_FORM_TOOL}:
            return {"template": template.model_dump(mode="json")}
        if tool_name == MATH_FIDELITY_TOOL:
            # Blind parse-back needs concrete text, so one representative
            # combination is substituted. Anchors are spans of the authored
            # text, so the item keeps that text and the substituted reading
            # is passed separately.
            concrete = representative_item(template)
            authored = concrete.model_copy(update={"text": template.body.text})
            return {
                "item": authored.model_dump(mode="json"),
                "text": concrete.text.template,
            }
        return {"candidate": typed_candidate.model_dump(mode="json")}

    def distractor_count(self, candidate: BaseModel) -> int:
        template = require_type(candidate, MathTemplateCandidate).item
        return 0 if template is None else len(template.body.distractors)

    def required_checks(self, candidate: BaseModel) -> frozenset[str]:
        """Correctness and options always; fidelity and form only when needed."""
        template = require_type(candidate, MathTemplateCandidate).item
        required = {MATH_ITEM_SPEC_TOOL, MATH_OPTIONS_TOOL}
        if template is not None:
            if template.body.text.mode == "prose":
                required.add(MATH_FIDELITY_TOOL)
            if template.body.goal.kind in FORM_SENSITIVE_GOALS:
                required.add(MATH_FORM_TOOL)
        return frozenset(required)

    def finalize_checked_template(
        self,
        candidate: BaseModel,
        evidence: list[ToolEvidence],
        *,
        advisory_checks: frozenset[str],
    ) -> ValidatedMathTemplate:
        """Package the isolated checks' evidence without running them again."""
        template = require_type(candidate, MathTemplateCandidate)
        template_spec = template.item
        if template_spec is None:
            raise ValueError("Generic finalization requires an item template")

        require_checked(
            evidence,
            required=self.required_checks(template),
            advisory_checks=advisory_checks,
        )
        _require_distractor_count(template_spec)

        item_spec = _item_spec_evidence(evidence)
        combinations_checked = _checked_combinations(item_spec)
        saved_evidence = [
            save_checked_evidence(
                item, template_sha256(template), advisory_checks=advisory_checks
            )
            for item in evidence
        ]

        summary = MathValidationSummary(
            checking_mode=MATH_CHECKING_MODE,
            combinations_checked=combinations_checked,
            max_combinations=item_spec.details.get("variants_total", 0),
            seed=item_spec.details.get("seed", 0),
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
        """Checking never rewrites a math template, so the candidate is bound."""
        return self.tool_bindings(request, candidate, tool_name)

    def generate_question(
        self, validated: BaseModel, *, seed: int
    ) -> MathQuestionInstance:
        return generate_math_question(
            require_type(validated, ValidatedMathTemplate), seed
        )


def _require_distractor_count(template: MathTemplateSpec) -> None:
    """Keep the option count within the range the artifact format allows."""
    count = len(template.body.distractors)
    if count < MIN_DISTRACTORS:
        raise ValueError("Generic templates require at least one distractor")
    if count > MAX_DISTRACTORS:
        raise ValueError(
            f"Generic templates allow at most {MAX_DISTRACTORS} distractors"
        )


def _item_spec_evidence(evidence: list[ToolEvidence]) -> ToolEvidence:
    return next(item for item in evidence if item.tool == MATH_ITEM_SPEC_TOOL)


def _checked_combinations(item_spec: ToolEvidence) -> int:
    """Refuse a pass that sampled no parameter combinations."""
    combinations_checked = item_spec.details.get("variants_checked", 0)
    if combinations_checked < 1:
        raise ValueError("IR validation checked no parameter combinations")
    return combinations_checked
