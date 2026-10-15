"""Read and verify the frozen Python tracing evaluation dataset; never relabel it."""

import argparse
import ast
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from edcraft_validator.domains.code.code_types import (
    AnswerTarget,
    Difficulty,
    ProgrammingTopic,
)
from edcraft_validator.tools.python_analysis import PythonSubsetAnalyzer
from edcraft_validator.tools.python_execution import LocalPythonTool
from edcraft_validator.value_comparison import equivalent, same_value_shape

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SET = ROOT / "reference_sets/python_tracing"
DEFAULT_DATASET = DEFAULT_SET / "dataset.json"
DIMENSIONS = (
    "execution_burden",
    "changing_state",
    "conceptual_interaction",
    "answer_discrimination",
)
FROZEN_DATASET_SHA256 = (
    "15526570cb3b60ca8eb7ebfca02bbbd12f81788dc4fd7fa3a46ac1b899df2fe7"
)
CRUXEVAL_LICENSE_SHA256 = (
    "055ca9e3fa33562173156e02e2350ceff4089deab480b368a849b6bc04f09719"
)
CRUXEVAL_REVISION = "190faf16d175b5847b0af05d937872b1fb395942"


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def code_family_fingerprint(code: str) -> str:
    """Catch formatting, identifier and literal-only clones, not semantic equivalence.

    Built-in names and operators remain significant. This deliberately conservative
    screen needs a separate curator check for different implementations of one idea.
    """
    tree = ast.parse(code)
    bound = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            bound.add(node.name)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            bound.add(node.id)
    names = {}

    def normalise(name):
        if name not in bound:
            return name
        return names.setdefault(name, f"identifier_{len(names)}")

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            node.name = normalise(node.name)
        elif isinstance(node, ast.arg):
            node.arg = normalise(node.arg)
        elif isinstance(node, ast.Name):
            node.id = normalise(node.id)
        elif isinstance(node, ast.Constant):
            node.value = f"literal_{type(node.value).__name__}"
    return digest(ast.dump(tree, include_attributes=False))


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Option(Record):
    id: Literal["A", "B", "C", "D"]
    value: int | float | str | list[int]


class Question(Record):
    question_id: str = Field(min_length=1)
    code: str = Field(min_length=1)
    entry_function: str = Field(min_length=1)
    inputs: dict[str, int | bool | str | list[int]]
    seed: int | None
    question: str = Field(min_length=1)
    answer_target: AnswerTarget
    options: list[Option] = Field(min_length=4, max_length=4)
    correct_option: Literal["A", "B", "C", "D"]

    @model_validator(mode="after")
    def valid_options(self):
        if [option.id for option in self.options] != list("ABCD"):
            raise ValueError("options must be ordered A, B, C, D")
        for index, option in enumerate(self.options):
            for other in self.options[index + 1 :]:
                if equivalent(option.value, other.value):
                    raise ValueError("options collide")
            if not same_value_shape(option.value, self.options[0].value):
                raise ValueError("option types differ")
        return self


class Dimension(Record):
    rating: Literal["low", "moderate", "high", "unknown"] | None
    reason: str = ""


class Rating(Record):
    review_id: str
    question_sha256: str
    status: Literal["pending", "reviewed"]
    estimated_difficulty: Difficulty | None
    confidence: Literal["low", "medium", "high"]
    alternative_levels: list[Difficulty]
    uncertainty_reason: str
    rating_reason: str = ""
    solution_reasoning: str = ""
    concepts_and_dependencies: str = ""
    shortcuts: str = ""
    dimensions: dict[str, Dimension]
    option_evidence: dict[str, str] = Field(default_factory=dict)
    nearest_anchor: str = ""
    quality_concerns: str
    human_decision: Literal["pending", "approved", "corrected", "uncertain"] = "pending"

    @model_validator(mode="after")
    def complete_review(self):
        if set(self.dimensions) != set(DIMENSIONS):
            raise ValueError("all four dimensions are required")
        if self.option_evidence and set(self.option_evidence) != set("ABCD"):
            raise ValueError("evidence for all four options is required")
        if len(set(self.alternative_levels)) != len(self.alternative_levels):
            raise ValueError("duplicate alternatives")
        return self


def match_decision(rating: Rating, requested: Difficulty) -> str | None:
    if rating.status == "pending":
        return None
    if rating.estimated_difficulty is None or rating.confidence == "low":
        return "uncertain"
    order = {"easy": 0, "medium": 1, "hard": 2}

    def compare(level):
        delta = order[level] - order[requested]
        return "matches" if delta == 0 else "too_easy" if delta < 0 else "too_hard"

    decision = compare(rating.estimated_difficulty)
    if any(compare(level) != decision for level in rating.alternative_levels):
        return "uncertain"
    return decision


class ReviewNotes(Record):
    confidence: Literal["low", "medium", "high"]
    alternative_levels: list[Difficulty]
    human_decision: Literal["approved", "corrected"]
    human_note: str
    quality_concerns: str


class FrozenDimensions(Record):
    model_config = ConfigDict(frozen=True)

    execution_burden: Literal["low", "moderate", "high", "unknown"]
    changing_state: Literal["low", "moderate", "high", "unknown"]
    conceptual_interaction: Literal["low", "moderate", "high", "unknown"]
    answer_discrimination: Literal["low", "moderate", "high", "unknown"]


class FrozenQuestion(Question):
    model_config = ConfigDict(frozen=True)

    review_id: str
    topic: ProgrammingTopic
    family_id: str
    split: Literal["development", "held_out"]
    difficulty: Difficulty
    dimensions: FrozenDimensions
    difficulty_reason: str = Field(min_length=1)
    reason_source: Literal["human_correction", "AI_proposal_approved_by_human"]
    solution: str = Field(min_length=1)
    provenance: dict[str, Any]
    review_notes: ReviewNotes
    verified_answer: int | float | str | list[int]
    trace_summary: dict[str, str | int]

    @model_validator(mode="after")
    def complete_reference(self):
        answer = next(o.value for o in self.options if o.id == self.correct_option)
        if not equivalent(answer, self.verified_answer):
            raise ValueError("verified answer does not match the correct option")
        if self.answer_target != "return_value" and not equivalent(
            self.trace_summary.get(self.answer_target), answer
        ):
            raise ValueError("trace evidence does not support the count target")
        return self


class FrozenDataset(Record):
    model_config = ConfigDict(frozen=True)

    dataset_id: Literal["python-tracing-evaluation-2026-10-15"]
    frozen: Literal[True]
    frozen_date: Literal["2026-10-15"]
    rubric_version: str
    rubric_sha256: str
    assessment_conditions_version: str
    assessment_conditions: str
    reference_type: Literal["ai_assisted_single_human_reviewer"]
    reviewer_id: str
    review_date: str
    approved_revision: str
    approved_review_sha256: str
    label_policy: str
    questions: list[FrozenQuestion] = Field(min_length=30, max_length=30)


def load_dataset(path: Path = DEFAULT_DATASET) -> FrozenDataset:
    """Reject changes to approved questions, labels, dimensions, topics or splits."""
    raw = read_json(path)
    dataset = FrozenDataset.model_validate(raw)
    ids = [q.question_id for q in dataset.questions]
    review_ids = [q.review_id for q in dataset.questions]
    if len(set(ids)) != 30 or set(review_ids) != {f"Q{i:02}" for i in range(1, 31)}:
        raise ValueError("duplicate or missing question identifiers")
    families = set()
    fingerprints = set()
    for item in dataset.questions:
        if item.family_id in families:
            raise ValueError("one question per family; family reuse or split leakage")
        families.add(item.family_id)
        fingerprint = code_family_fingerprint(item.code)
        if fingerprint in fingerprints:
            raise ValueError("normalised code clone in evaluation dataset")
        fingerprints.add(fingerprint)
        source = item.provenance
        if source.get("code_sha256") != hashlib.sha256(item.code.encode()).hexdigest():
            raise ValueError("source code changed")
        if source["kind"] == "cruxeval_adaptation" and (
            source.get("license") != "MIT"
            or source.get("source_revision") != CRUXEVAL_REVISION
            or not source.get("source_record_sha256")
        ):
            raise ValueError("CRUXEval source provenance changed")
    if hashlib.sha256((path.parent / "CRUXEval-LICENSE").read_bytes()).hexdigest() != (
        CRUXEVAL_LICENSE_SHA256
    ):
        raise ValueError("CRUXEval license changed")
    if hashlib.sha256(
        (ROOT / "docs/difficulty-rubric.md").read_bytes()
    ).hexdigest() != (dataset.rubric_sha256):
        raise ValueError("rubric changed from the frozen assessment conditions")
    if digest(raw) != FROZEN_DATASET_SHA256:
        raise ValueError("frozen dataset changed; restore the approved snapshot")
    return dataset


def question_for_judge(item: FrozenQuestion) -> dict:
    """Return the complete MCQ without reference labels, reviewer notes or sources."""
    return item.model_dump(include=set(Question.model_fields) - {"question_id", "seed"})


def verify_questions(questions: list[Question]) -> list[dict]:
    records = []
    tool = LocalPythonTool()
    for question in questions:
        analysis = PythonSubsetAnalyzer(question.entry_function).check(question.code)
        if not analysis.is_valid:
            raise ValueError(f"{question.question_id}: {analysis.errors}")
        execution = tool.execute_batch(
            question.code,
            question.entry_function,
            [question.inputs],
            timeout_seconds=2,
        )[0]
        if not execution.ok:
            raise ValueError(f"{question.question_id}: {execution.error_message}")
        summary = execution.trace_summary
        answer = (
            execution.answer
            if question.answer_target == "return_value"
            else (summary or {}).get(question.answer_target)
        )
        option = next(o for o in question.options if o.id == question.correct_option)
        if not equivalent(answer, option.value):
            raise ValueError(
                f"{question.question_id}: answer {answer!r} "
                f"differs from {option.value!r}"
            )
        records.append(
            {
                "question_id": question.question_id,
                "question_sha256": digest(question.model_dump()),
                "verified_answer": answer,
                "correct_option": question.correct_option,
                "trace_summary": summary,
                "subset_valid": True,
                "options_distinct": True,
            }
        )
    return records


def verify_dataset(path: Path = DEFAULT_DATASET) -> dict:
    dataset = load_dataset(path)
    before = path.read_bytes()
    records = verify_questions(dataset.questions)
    for item, record in zip(dataset.questions, records, strict=True):
        if record["trace_summary"] != item.trace_summary:
            raise ValueError(f"{item.question_id}: execution trace changed")
    if path.read_bytes() != before:
        raise ValueError("dataset changed during verification")
    return {
        "dataset_id": dataset.dataset_id,
        "frozen": True,
        "sha256": FROZEN_DATASET_SHA256,
        "verified": len(records),
        "difficulty": dict(Counter(q.difficulty for q in dataset.questions)),
        "topics": dict(Counter(q.topic for q in dataset.questions)),
        "splits": dict(Counter(q.split for q in dataset.questions)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("command", choices=["verify"])
    args = parser.parse_args()
    print(json.dumps(verify_dataset(args.dataset), indent=2))


if __name__ == "__main__":
    main()
