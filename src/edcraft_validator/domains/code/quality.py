"""Request and learner-facing content for lightweight relevance assessment."""

import json

from pydantic import Field

from edcraft_validator.domains.code.code_types import AnswerTarget, CodeFeature
from edcraft_validator.domains.code.difficulty import (
    CodeDifficultyQuestion,
    Record,
    Text,
)


class QualityRequest(Record):
    prompt: Text = Field(max_length=4000)
    required_features: list[CodeFeature] = Field(default_factory=list, max_length=13)
    answer_target: AnswerTarget | None = None
    num_distractors: int | None = Field(default=None, ge=2, le=3)
    learner_prerequisites: list[Text] = Field(default_factory=list, max_length=20)


def rendered_question(question: CodeDifficultyQuestion) -> str:
    """Preserve all learner-facing fields, withholding the answer designation."""
    return json.dumps(
        question.model_dump(mode="json", exclude={"correct_option"}),
        sort_keys=True,
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    )
