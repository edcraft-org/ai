"""Python-owned requirements and complete learner-facing relevance rendering."""

import json

from pydantic import Field

from edcraft_validator.domains.code.code_types import AnswerTarget, CodeFeature
from edcraft_validator.domains.code.difficulty import (
    CodeDifficultyQuestion,
    Record,
    Text,
)
from edcraft_validator.relevance_contracts import RelevanceInput

CODE_RELEVANCE_RENDERING_VERSION = "code-question-json-v1"


class CodeQuestionRequest(Record):
    prompt: Text = Field(max_length=4000)
    required_features: list[CodeFeature] = Field(default_factory=list, max_length=13)
    answer_target: AnswerTarget | None = None
    num_distractors: int | None = Field(default=None, ge=2, le=3)
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
    question = CodeDifficultyQuestion.model_validate_json(question.model_dump_json())
    request = CodeQuestionRequest.model_validate_json(request.model_dump_json())
    return RelevanceInput(
        author_request=json.dumps(
            request.model_dump(mode="json"), sort_keys=True, indent=2
        ),
        question_text=rendered_question(question),
        rendering_version=CODE_RELEVANCE_RENDERING_VERSION,
    )
