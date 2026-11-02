"""Code-domain implementation of the generic domain contract."""

from pydantic import BaseModel

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
from edcraft_validator.domains.code.prompt_builder import (
    build_code_generation_request,
)
from edcraft_validator.domains.code.proposal_response import CodeProposalResponse
from edcraft_validator.domains.code.question_generator import generate_code_question
from edcraft_validator.domains.code.relevance import TEMPLATE_RELEVANCE_TOOL
from edcraft_validator.domains.code.template_difficulty import (
    TEMPLATE_DIFFICULTY_TOOL,
)
from edcraft_validator.llm.llm_contracts import (
    PlannedGenerationResponse,
    StructuredGenerationRequest,
)
from edcraft_validator.validation.check_contracts import ToolEvidence
from edcraft_validator.validation.validation_contracts import ValidationEvidence


class CodeDomain:
    """Prompting, validation, and expansion for code templates."""

    name = "code"
    request_model = CodeTemplateRequest
    validated_model = ValidatedCodeTemplate

    def generation_request(
        self, request: BaseModel
    ) -> StructuredGenerationRequest[PlannedGenerationResponse[CodeProposalResponse]]:
        typed_request = _require_type(request, CodeTemplateRequest)
        return build_code_generation_request(typed_request)

    def build_candidate(
        self, request: BaseModel, proposal: BaseModel
    ) -> CodeTemplateCandidate:
        return build_code_candidate(
            _require_type(request, CodeTemplateRequest),
            _require_type(proposal, CodeTemplateContent),
        )

    def tool_bindings(self, request, candidate, tool_name):
        """Application-owned values never come from model tool arguments."""
        bindings = {
            "candidate": _require_type(candidate, CodeTemplateCandidate).model_dump(
                mode="json"
            )
        }
        if tool_name == TEMPLATE_RELEVANCE_TOOL:
            bindings["author_request"] = _require_type(
                request, CodeTemplateRequest
            ).prompt
        if tool_name == "code_validate_answers_and_distractors":
            bindings["required_distractors"] = _require_type(
                request, CodeTemplateRequest
            ).num_distractors
        return bindings

    def finalize_checked_template(
        self, candidate: BaseModel, evidence: list[ToolEvidence]
    ) -> ValidatedCodeTemplate:
        """Package actual MCP outputs without re-execution or answer repair."""
        template = _require_type(candidate, CodeTemplateCandidate)
        if not evidence or any(item.status != "passed" for item in evidence):
            raise ValueError("All selected checks must pass")
        semantic = next(
            (
                item
                for item in evidence
                if item.tool == "code_validate_answers_and_distractors"
            ),
            None,
        )
        if semantic is None:
            raise ValueError(
                "Missing execution-derived canonical answers and distractors"
            )
        saved_evidence = [
            ValidationEvidence(
                check=item.tool,
                status="passed",
                duration_ms=item.duration_ms,
                issues=[finding.model_dump() for finding in item.findings],
                details={
                    "tool_version": item.version,
                    **(
                        item.details
                        if item.tool
                        in {TEMPLATE_DIFFICULTY_TOOL, TEMPLATE_RELEVANCE_TOOL}
                        else {}
                    ),
                },
            )
            for item in evidence
        ]
        summary = TemplateValidationSummary.model_validate(
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
        selected = [
            DistractorRecipe.model_validate(item)
            for item in semantic.details["selected_distractors"]
        ]
        if len(selected) < 2 or any(
            recipe not in template.distractors for recipe in selected
        ):
            raise ValueError("Selected distractors are not checked proposal recipes")
        reusable = template.model_copy(
            update={
                "distractors": selected,
            },
            deep=True,
        )
        reusable = CodeTemplateCandidate.model_validate(reusable.model_dump())
        for item in evidence:
            if item.tool in {TEMPLATE_DIFFICULTY_TOOL, TEMPLATE_RELEVANCE_TOOL} and (
                item.details.get("template_sha256") != template_sha256(reusable)
            ):
                raise ValueError("Assessment evidence belongs to a different template")
        return ValidatedCodeTemplate(
            template=reusable,
            validation=summary,
        )

    def checked_tool_bindings(self, request, candidate, tool_name, evidence):
        """Assess exactly the reusable template produced by correctness checks."""
        semantic = [
            item
            for item in evidence
            if item.tool == "code_validate_answers_and_distractors"
            and item.status == "passed"
        ]
        checked = self.finalize_checked_template(candidate, semantic)
        return self.tool_bindings(request, checked.template, tool_name)

    def generate_question(
        self, validated: BaseModel, *, seed: int
    ) -> CodeQuestionInstance:
        return generate_code_question(
            _require_type(validated, ValidatedCodeTemplate), seed
        )


def _require_type[ModelT: BaseModel](value: BaseModel, model: type[ModelT]) -> ModelT:
    if not isinstance(value, model):
        raise TypeError(f"code domain requires {model.__name__}")
    return value
