"""Code-domain implementation of the generic domain contract.

The domain builds a candidate from a model proposal, binds its MCP checks,
finalises the checked template, and expands it into a seeded question.
"""

from fastmcp import FastMCP
from pydantic import BaseModel

from edcraft_validator.artifact_contracts import ValidatedTemplateArtifact
from edcraft_validator.domains.code.candidate_builder import (
    build_code_candidate,
    template_sha256,
)
from edcraft_validator.domains.code.code_schemas import (
    CodeQuestionInstance,
    CodeTemplateCandidate,
    CodeTemplateContent,
    CodeTemplateRequest,
    DistractorRecipe,
    TemplateValidationSummary,
    ValidatedCodeTemplate,
)
from edcraft_validator.domains.code.code_types import MIN_DISTRACTORS
from edcraft_validator.domains.code.prompt_builder import (
    build_code_generation_request,
)
from edcraft_validator.domains.code.proposal_response import CodeProposalResponse
from edcraft_validator.domains.code.question_generator import generate_code_question
from edcraft_validator.domains.code.relevance import template_relevance_text
from edcraft_validator.domains.domain_support import (
    ReviewTemplateView,
    build_review_view,
    require_checked,
    require_type,
    save_checked_evidence,
)
from edcraft_validator.llm.llm_contracts import (
    PlannedGenerationResponse,
    StructuredGenerationRequest,
)
from edcraft_validator.mcp.code_tools import register_code_validation_tools
from edcraft_validator.mcp.difficulty_tools import register_difficulty_tools
from edcraft_validator.mcp.tool_dependencies import ToolDependencies
from edcraft_validator.validation.check_contracts import ToolEvidence
from edcraft_validator.validation.check_names import (
    TEMPLATE_RELEVANCE_CAPABILITY,
    TEMPLATE_RELEVANCE_CHECK,
)
from edcraft_validator.validation.validation_contracts import ValidationEvidence

SEMANTIC_CHECK = "code_validate_answers_and_distractors"


class CodeDomain:
    """Prompting, validation, and expansion for code templates."""

    name = "code"
    request_model = CodeTemplateRequest
    candidate_model = CodeTemplateCandidate
    validated_model = ValidatedCodeTemplate
    question_model = CodeQuestionInstance
    template_language = "python"
    capabilities = frozenset({TEMPLATE_RELEVANCE_CAPABILITY})

    def register_tools(self, server: FastMCP, dependencies: ToolDependencies) -> None:
        """Register the code domain's authoritative and advisory tools."""
        register_code_validation_tools(
            server,
            execution_tool=dependencies.execution_tool,
            timeout_seconds=dependencies.code_execution_timeout_seconds,
            property_settings=dependencies.property_settings,
        )
        register_difficulty_tools(
            server,
            provider_factory=dependencies.difficulty_provider_factory,
            judge_timeout_seconds=dependencies.difficulty_judge_timeout_seconds,
            settings=dependencies.judge_settings,
        )

    def review_view(
        self, artifact: ValidatedTemplateArtifact
    ) -> ReviewTemplateView | None:
        return build_review_view(artifact, language=self.template_language)

    def generation_request(
        self, request: BaseModel
    ) -> StructuredGenerationRequest[PlannedGenerationResponse[CodeProposalResponse]]:
        typed_request = require_type(request, CodeTemplateRequest)
        return build_code_generation_request(typed_request)

    def build_candidate(
        self, request: BaseModel, proposal: BaseModel
    ) -> CodeTemplateCandidate:
        return build_code_candidate(
            require_type(request, CodeTemplateRequest),
            require_type(proposal, CodeTemplateContent),
        )

    def tool_bindings(self, request, candidate, tool_name):
        """Application-owned values never come from model tool arguments."""
        typed_candidate = require_type(candidate, CodeTemplateCandidate)
        if tool_name == TEMPLATE_RELEVANCE_CHECK:
            return {
                "author_request": require_type(request, CodeTemplateRequest).prompt,
                "question_text": template_relevance_text(typed_candidate),
                "subject_sha256": template_sha256(typed_candidate),
            }

        bindings = {"candidate": typed_candidate.model_dump(mode="json")}
        if tool_name == SEMANTIC_CHECK:
            bindings["required_distractors"] = require_type(
                request, CodeTemplateRequest
            ).num_distractors
        return bindings

    def distractor_count(self, candidate: BaseModel) -> int:
        return len(require_type(candidate, CodeTemplateCandidate).distractors)

    def required_checks(self, candidate: BaseModel) -> frozenset[str]:
        """Only this check yields the execution-derived answers a template needs."""
        return frozenset({SEMANTIC_CHECK})

    def finalize_checked_template(
        self,
        candidate: BaseModel,
        evidence: list[ToolEvidence],
        *,
        advisory_checks: frozenset[str],
    ) -> ValidatedCodeTemplate:
        """Package actual MCP outputs without re-execution or answer repair."""
        template = require_type(candidate, CodeTemplateCandidate)
        require_checked(
            evidence,
            required=self.required_checks(template),
            advisory_checks=advisory_checks,
        )

        semantic = next(item for item in evidence if item.tool == SEMANTIC_CHECK)
        reusable = _reusable_checked_template(template, semantic)
        saved_evidence = [
            save_checked_evidence(
                item, template_sha256(reusable), advisory_checks=advisory_checks
            )
            for item in evidence
        ]

        return ValidatedCodeTemplate(
            template=reusable,
            validation=_validation_summary(semantic, saved_evidence),
        )

    def checked_tool_bindings(self, request, candidate, tool_name, evidence):
        """Assess exactly the reusable template produced by correctness checks."""
        semantic = [
            item
            for item in evidence
            if item.tool == SEMANTIC_CHECK and item.status == "passed"
        ]

        checked = self.finalize_checked_template(
            candidate, semantic, advisory_checks=frozenset()
        )
        return self.tool_bindings(request, checked.template, tool_name)

    def generate_question(
        self, validated: BaseModel, *, seed: int
    ) -> CodeQuestionInstance:
        return generate_code_question(
            require_type(validated, ValidatedCodeTemplate), seed
        )


def _reusable_checked_template(
    template: CodeTemplateCandidate,
    semantic: ToolEvidence,
) -> CodeTemplateCandidate:
    """Keep only the distractors the semantic check actually accepted."""
    selected = [
        DistractorRecipe.model_validate(item)
        for item in semantic.details["selected_distractors"]
    ]
    if len(selected) < MIN_DISTRACTORS or any(
        recipe not in template.distractors for recipe in selected
    ):
        raise ValueError("Selected distractors are not checked proposal recipes")

    reusable = template.model_copy(
        update={
            "distractors": selected,
        },
        deep=True,
    )
    return CodeTemplateCandidate.model_validate(reusable.model_dump())


def _validation_summary(
    semantic: ToolEvidence,
    saved_evidence: list[ValidationEvidence],
) -> TemplateValidationSummary:
    """Copy the execution coverage onto the saved template."""
    return TemplateValidationSummary.model_validate(
        {
            **{
                key: semantic.details[key]
                for key in (
                    "checking_mode",
                    "examples_checked",
                    "execution_calls",
                    "max_examples",
                    "max_execution_calls",
                    "timeout_seconds",
                    "seed",
                )
            },
            "evidence": saved_evidence,
        }
    )
