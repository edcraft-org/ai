"""Code-owned contracts, rubric and prompt for provisional concrete-MCQ judging."""

import hashlib
import json
import re
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from edcraft_validator.domains.code.code_types import AnswerTarget, Difficulty
from edcraft_validator.llm.llm_contracts import StructuredGenerationRequest

DIFFICULTY_PROMPT_VERSION = "code-difficulty-v6-runtime-exact-options"
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
OptionID = Literal["A", "B", "C", "D"]
AnswerValue = int | float | bool | str | list[int]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class DifficultyOption(Record):
    id: OptionID
    value: AnswerValue


class CodeQuestionContent(Record):
    """Fields shared by MCP questions and closed-schema authoring responses."""

    code: str = Field(min_length=1, max_length=20_000)
    entry_function: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    question: Text = Field(max_length=8_000)
    answer_target: AnswerTarget
    options: list[DifficultyOption] = Field(min_length=3, max_length=4)
    correct_option: OptionID

    @model_validator(mode="after")
    def check_option_identifiers(self):
        if [o.id for o in self.options] != list("ABCD"[: len(self.options)]):
            raise ValueError("options must be ordered A, B, C[, D]")
        if self.correct_option not in {o.id for o in self.options}:
            raise ValueError("correct_option must identify a supplied option")
        return self


class CodeDifficultyQuestion(CodeQuestionContent):
    """Exactly the learner-facing MCQ plus its designated answer, without labels."""

    inputs: dict[str, int | bool | str | list[int]]

    @property
    def sha256(self) -> str:
        return hashlib.sha256(
            json.dumps(
                self.model_dump(),
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
        ).hexdigest()


class NamedQuestionInput(Record):
    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    value: int | bool | str | list[int]


class CodeQuestionDraft(CodeQuestionContent):
    """Named input entries keep the author response schema closed for OpenAI."""

    inputs: list[NamedQuestionInput]

    @model_validator(mode="after")
    def unique_input_names(self):
        names = [item.name for item in self.inputs]
        if len(names) != len(set(names)):
            raise ValueError("input names must be unique")
        return self

    def to_question(self) -> CodeDifficultyQuestion:
        value = self.model_dump()
        value["inputs"] = {item.name: item.value for item in self.inputs}
        return CodeDifficultyQuestion.model_validate(value)


class DimensionAssessment(Record):
    rating: Literal["low", "moderate", "high", "unknown"]
    reason: Text


class DifficultyDimensions(Record):
    execution_burden: DimensionAssessment
    changing_state: DimensionAssessment
    conceptual_interaction: DimensionAssessment
    answer_discrimination: DimensionAssessment


class OptionAssessment(Record):
    option_id: OptionID
    reasoning: Text
    hypothesised_error: str | None
    shortcut_or_cue: str | None


class DifficultyAssessment(Record):
    estimated_difficulty: Difficulty | None
    dimensions: DifficultyDimensions
    reason: Text
    solution_reasoning: Text
    concepts_and_dependencies: Text
    shortcuts: Text
    nearest_anchor: Text
    option_evidence: list[OptionAssessment] = Field(min_length=3, max_length=4)
    unable_to_assess_reason: Text | None = Field(
        description=(
            "Required when essential question information is missing and the "
            "estimate is null. Borderline difficulty is not missing information: "
            "choose the closest easy/medium/hard anchor. Otherwise use null."
        )
    )
    quality_concerns: list[Text]

    @model_validator(mode="after")
    def validate_assessment(self):
        ids = [o.option_id for o in self.option_evidence]
        if len(ids) != len(set(ids)):
            raise ValueError("option evidence must not repeat an option")
        if self.estimated_difficulty is None and self.unable_to_assess_reason is None:
            raise ValueError("null estimates require an unable-to-assess reason")
        return self


@dataclass(frozen=True)
class CodeDifficultyRubric:
    text: str
    version: str
    assessment_conditions_version: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()


def load_code_difficulty_rubric() -> CodeDifficultyRubric:
    """The wheel bundles the same document used for source-tree review records."""
    resource = files("edcraft_validator.domains.code").joinpath("difficulty-rubric.md")
    if resource.is_file():
        text = resource.read_bytes().decode("utf-8")
    else:
        text = (
            (Path(__file__).resolve().parents[4] / "docs/difficulty-rubric.md")
            .read_bytes()
            .decode("utf-8")
        )
    version = re.search(r"^Rubric version: `([^`]+)`", text, re.MULTILINE)
    conditions = re.search(
        r"^Assessment conditions version: `([^`]+)`", text, re.MULTILINE
    )
    if version is None or conditions is None:
        raise ValueError("rubric must declare versions")
    return CodeDifficultyRubric(text, version[1], conditions[1])


def build_difficulty_request(
    question: CodeDifficultyQuestion,
    rubric: CodeDifficultyRubric,
) -> StructuredGenerationRequest:
    from edcraft_validator.domains.code.difficulty_request import build_judge_request

    return build_judge_request(question, rubric)
