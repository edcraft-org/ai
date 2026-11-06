"""Python-owned requirements and complete learner-facing relevance rendering."""

import json

from pydantic import Field

from edcraft_validator.domains.code.code_schemas import CodeTemplateCandidate
from edcraft_validator.domains.code.code_types import (
    MAX_CONCRETE_DISTRACTORS,
    MIN_CONCRETE_DISTRACTORS,
    AnswerTarget,
    CodeFeature,
)
from edcraft_validator.domains.code.difficulty import (
    CodeDifficultyQuestion,
    Record,
    Text,
)
from edcraft_validator.relevance_contracts import RelevanceInput


class CodeQuestionRequest(Record):
    """Requirements for one concrete question, not a reusable template.

    Concrete questions use the fixed A-D option schema, so their distractor
    count is bounded to 2-3 (three or four choices). Template authoring has
    its own request model and the wider 1-10 distractor range.
    """

    prompt: Text = Field(max_length=4000)
    required_features: list[CodeFeature] = Field(default_factory=list, max_length=13)
    answer_target: AnswerTarget | None = None
    num_distractors: int | None = Field(
        default=None, ge=MIN_CONCRETE_DISTRACTORS, le=MAX_CONCRETE_DISTRACTORS
    )
    learner_prerequisites: list[Text] = Field(default_factory=list, max_length=20)


def rendered_question(question: CodeDifficultyQuestion) -> str:
    """Preserve learner-facing content while withholding the answer designation."""
    return json.dumps(
        question.model_dump(mode="json", exclude={"correct_option"}),
        sort_keys=True,
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    )


def relevance_input(
    question: CodeDifficultyQuestion, request: CodeQuestionRequest
) -> RelevanceInput:
    return RelevanceInput(
        author_request=json.dumps(
            request.model_dump(mode="json"), sort_keys=True, indent=2
        ),
        question_text=rendered_question(question),
    )


TEMPLATE_RELEVANCE_TOOL = "code_assess_template_relevance"


def template_relevance_input(
    candidate: CodeTemplateCandidate, author_request: str
) -> RelevanceInput:
    """Compare the actual learner task with the request, without answer or hints."""
    return RelevanceInput(
        author_request=author_request,
        question_text=(
            "Python multiple-choice question template\n\n"
            f"Python code:\n{candidate.code}\n\n"
            f"Question: {candidate.question_template}\n"
            f"Answer target: {candidate.answer_target}\n"
            f"Parameter values: "
            f"{json.dumps({p.name: p.values for p in candidate.parameters})}\n"
            "Each generated question substitutes one allowed value "
            "for every placeholder.\n"
        ),
    )
