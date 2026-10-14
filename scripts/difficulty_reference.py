"""Verify the provisional set and prepare blinded human reviews; no model calls."""

import argparse
import hashlib
import json
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from edcraft_validator.domains.code.code_types import AnswerTarget, Difficulty
from edcraft_validator.tools.python_analysis import PythonSubsetAnalyzer
from edcraft_validator.tools.python_execution import LocalPythonTool
from edcraft_validator.value_comparison import equivalent, same_value_shape

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SET = ROOT / "reference_sets/python_tracing_v1"
DIMENSIONS = (
    "execution_burden",
    "changing_state",
    "conceptual_interaction",
    "answer_discrimination",
)


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


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


def load_set(directory: Path) -> tuple[list[Question], dict]:
    data = read_json(directory / "questions.json")
    manifest = read_json(directory / "manifest.json")
    if data["set_version"] != manifest["set_version"]:
        raise ValueError("set versions differ")
    questions = [Question.model_validate(value) for value in data["questions"]]
    ids = [question.question_id for question in questions]
    entries = manifest["items"]
    if len(set(ids)) != len(ids) or len({e["question_id"] for e in entries}) != len(
        entries
    ):
        raise ValueError("duplicate question IDs")
    if set(ids) != {entry["question_id"] for entry in entries}:
        raise ValueError("manifest and questions differ")
    family_splits = {}
    code_families = {}
    for question in questions:
        entry = next(e for e in entries if e["question_id"] == question.question_id)
        family, split = entry["family_id"], entry["split"]
        if split not in {"development", "held_out"}:
            raise ValueError("unknown split")
        if entry["requested_difficulty"] not in {"easy", "medium", "hard"}:
            raise ValueError("unknown requested level")
        if family_splits.setdefault(family, split) != split:
            raise ValueError("family leaks across splits")
        # Identical code cannot be assigned to different declared families.
        if code_families.setdefault(question.code, family) != family:
            raise ValueError("identical code assigned to multiple families")
        if set(entry["distractor_hypotheses"]) != set("ABCD") - {
            question.correct_option
        }:
            raise ValueError("distractor provenance missing")
    rubric_hash = hashlib.sha256((ROOT / "docs/difficulty-rubric.md").read_bytes())
    if rubric_hash.hexdigest() != manifest["rubric_sha256"]:
        raise ValueError("rubric changed; version and review the set again")
    return questions, manifest


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


def checked_evidence(
    directory: Path, questions: list[Question], manifest: dict
) -> dict:
    evidence = read_json(directory / "technical-evidence.json")
    if evidence["questions_sha256"] != digest(read_json(directory / "questions.json")):
        raise ValueError("stale question evidence; rerun verify --write-evidence")
    if evidence["manifest_sha256"] != digest(manifest):
        raise ValueError("stale manifest evidence; rerun verify --write-evidence")
    if [record["question_sha256"] for record in evidence["records"]] != [
        digest(question.model_dump()) for question in questions
    ]:
        raise ValueError("stale or incomplete technical evidence")
    for question, record in zip(questions, evidence["records"], strict=True):
        correct = next(o for o in question.options if o.id == question.correct_option)
        if (
            record["question_id"] != question.question_id
            or record["correct_option"] != question.correct_option
            or record["subset_valid"] is not True
            or record["options_distinct"] is not True
            or not equivalent(record["verified_answer"], correct.value)
        ):
            raise ValueError("invalid technical evidence")
        if question.answer_target != "return_value" and not equivalent(
            record["trace_summary"].get(question.answer_target), correct.value
        ):
            raise ValueError("count evidence does not support the target")
    return evidence


def make_packet(directory: Path, questions: list[Question], manifest: dict) -> dict:
    evidence = checked_evidence(directory, questions, manifest)
    records = {record["question_id"]: record for record in evidence["records"]}
    # Opaque IDs and a hash-based order conceal family/topic/source clues in IDs.
    ordered = sorted(questions, key=lambda q: digest(q.question_id))
    blinded = []
    for index, question in enumerate(ordered, 1):
        value = question.model_dump(exclude={"question_id", "seed"})
        record = records[question.question_id]
        blinded.append(
            {
                "review_id": f"Q{index:02}",
                **value,
                "question_sha256": record["question_sha256"],
                "verified_answer": record["verified_answer"],
                "trace_summary": record["trace_summary"],
            }
        )
    packet = {
        "set_version": manifest["set_version"],
        "protocol_version": manifest["protocol_version"],
        "rubric_version": manifest["rubric_version"],
        "rubric_sha256": manifest["rubric_sha256"],
        "assessment_conditions_version": manifest["assessment_conditions_version"],
        "conditions": "Manual tracing with scratch paper; untimed; no execution, "
        "calculator or AI assistance. Semantics are assumed understood. "
        "Verified answers/traces are reviewer evidence, not learner-facing material.",
        "questions": blinded,
    }
    return {**packet, "packet_sha256": digest(packet)}


def blank_review(packet: dict, reviewer: str) -> dict:
    return {
        "reviewer_id": reviewer,
        "reviewer_kind": "human",
        "review_date": datetime.now(UTC).date().isoformat(),
        "independent_blinded_review": False,
        "packet_sha256": packet["packet_sha256"],
        "rubric_version": packet["rubric_version"],
        "rubric_sha256": packet["rubric_sha256"],
        "assessment_conditions_version": packet["assessment_conditions_version"],
        "ratings": [
            {
                "review_id": q["review_id"],
                "question_sha256": q["question_sha256"],
                "status": "pending",
                "estimated_difficulty": None,
                "confidence": "low",
                "alternative_levels": [],
                "uncertainty_reason": "",
                "solution_reasoning": "",
                "concepts_and_dependencies": "",
                "shortcuts": "",
                "dimensions": {
                    dimension: {"rating": "unknown", "reason": ""}
                    for dimension in DIMENSIONS
                },
                "option_evidence": {option["id"]: "" for option in q["options"]},
                "nearest_anchor": "",
                "quality_concerns": "",
            }
            for q in packet["questions"]
        ],
    }


class Dimension(Record):
    rating: Literal["low", "moderate", "high", "unknown"]
    reason: str


class Rating(Record):
    review_id: str
    question_sha256: str
    status: Literal["pending", "reviewed"]
    estimated_difficulty: Difficulty | None
    confidence: Literal["low", "medium", "high"]
    alternative_levels: list[Difficulty]
    uncertainty_reason: str
    solution_reasoning: str
    concepts_and_dependencies: str
    shortcuts: str
    dimensions: dict[str, Dimension]
    option_evidence: dict[str, str]
    nearest_anchor: str
    quality_concerns: str

    @model_validator(mode="after")
    def complete_review(self):
        if set(self.dimensions) != set(DIMENSIONS):
            raise ValueError("all four dimensions are required")
        if set(self.option_evidence) != set("ABCD"):
            raise ValueError("evidence for all four options is required")
        if len(set(self.alternative_levels)) != len(self.alternative_levels):
            raise ValueError("duplicate alternatives")
        if self.status == "reviewed":
            reasons = [
                self.solution_reasoning,
                self.concepts_and_dependencies,
                self.shortcuts,
                self.nearest_anchor,
                *(dimension.reason for dimension in self.dimensions.values()),
                *self.option_evidence.values(),
            ]
            if any(not reason.strip() for reason in reasons):
                raise ValueError("reviewed ratings need reasons, including shortcuts")
            if (
                self.estimated_difficulty is None
                or self.confidence == "low"
                or self.alternative_levels
                or any(d.rating == "unknown" for d in self.dimensions.values())
            ) and not self.uncertainty_reason.strip():
                raise ValueError("uncertain reviews need an uncertainty reason")
        return self


class HumanReview(Record):
    reviewer_id: str = Field(min_length=1)
    reviewer_kind: Literal["human"]
    review_date: str
    independent_blinded_review: bool
    packet_sha256: str
    rubric_version: str
    rubric_sha256: str
    assessment_conditions_version: str
    ratings: list[Rating]

    @model_validator(mode="after")
    def valid_date(self):
        if date.fromisoformat(self.review_date).isoformat() != self.review_date:
            raise ValueError("review date must be YYYY-MM-DD")
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


def validate_review(directory: Path, review_data: dict) -> tuple:
    """Check original ratings without revealing requested labels."""
    questions, manifest = load_set(directory)
    packet = make_packet(directory, questions, manifest)
    review = HumanReview.model_validate(review_data)
    for field in (
        "packet_sha256",
        "rubric_version",
        "rubric_sha256",
        "assessment_conditions_version",
    ):
        if getattr(review, field) != packet[field]:
            raise ValueError(f"stale review {field}")
    by_id = {rating.review_id: rating for rating in review.ratings}
    if len(by_id) != len(review.ratings) or set(by_id) != {
        question["review_id"] for question in packet["questions"]
    }:
        raise ValueError("review must retain all items exactly once, including pending")
    if any(r.status == "reviewed" for r in review.ratings) and not (
        review.independent_blinded_review
    ):
        raise ValueError("reviewer must attest independent blinded human review")
    for blinded in packet["questions"]:
        if by_id[blinded["review_id"]].question_sha256 != blinded["question_sha256"]:
            raise ValueError("question changed since review")
    return review, packet, questions, manifest


def compare_review(directory: Path, review_data: dict) -> dict:
    review, packet, questions, manifest = validate_review(directory, review_data)
    if any(r.status == "pending" for r in review.ratings):
        raise ValueError("finish and freeze all independent ratings before comparison")
    by_id = {rating.review_id: rating for rating in review.ratings}
    entries = {entry["question_id"]: entry for entry in manifest["items"]}
    ordered = sorted(questions, key=lambda q: digest(q.question_id))
    comparisons = []
    for question, blinded in zip(ordered, packet["questions"], strict=True):
        rating = by_id[blinded["review_id"]]
        if rating.question_sha256 != blinded["question_sha256"]:
            raise ValueError("question changed since review")
        entry = entries[question.question_id]
        comparisons.append(
            {
                "question_id": question.question_id,
                "review_id": rating.review_id,
                "family_id": entry["family_id"],
                "split": entry["split"],
                "requested_difficulty": entry["requested_difficulty"],
                "estimated_difficulty": rating.estimated_difficulty,
                "status": rating.status,
                "difficulty_match": match_decision(
                    rating, entry["requested_difficulty"]
                ),
            }
        )
    return {
        "review_sha256": digest(review.model_dump()),
        "packet_sha256": packet["packet_sha256"],
        "reviewer_id": review.reviewer_id,
        "reference_type": "single_human_reviewer",
        "human_human_agreement": None,
        "observed_learner_performance": None,
        "reviewed_count": sum(r.status == "reviewed" for r in review.ratings),
        "pending_count": sum(r.status == "pending" for r in review.ratings),
        "comparisons": comparisons,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set", type=Path, default=DEFAULT_SET)
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--write-evidence", action="store_true")
    export = commands.add_parser("prepare-review")
    export.add_argument("--reviewer", required=True)
    export.add_argument("--output", type=Path, required=True)
    validate = commands.add_parser("validate-review")
    validate.add_argument("review", type=Path)
    compare = commands.add_parser("compare-review")
    compare.add_argument("review", type=Path)
    compare.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    questions, manifest = load_set(args.set)
    if args.command == "verify":
        records = verify_questions(questions)
        if args.write_evidence:
            write_json(
                args.set / "technical-evidence.json",
                {
                    "evidence_version": "python-tracing-technical-v1",
                    "questions_sha256": digest(read_json(args.set / "questions.json")),
                    "manifest_sha256": digest(manifest),
                    "executor": "LocalPythonTool / StepTracer",
                    "step_tracer_revision": "ab7e22ef18b776a9cbd5260bef4b4eeacc17db11",
                    "timeout_seconds_per_case": 2,
                    "records": records,
                },
            )
        else:
            evidence = checked_evidence(args.set, questions, manifest)
            if records != evidence["records"]:
                raise ValueError("execution evidence differs from recorded results")
        print(
            json.dumps(
                {
                    "verified": len(records),
                    "families": len({e["family_id"] for e in manifest["items"]}),
                    "splits": dict(Counter(e["split"] for e in manifest["items"])),
                    "topics": dict(Counter(e["topic"] for e in manifest["items"])),
                    "human_ratings": "pending; not supplied by technical checks",
                },
                indent=2,
            )
        )
    elif args.command == "prepare-review":
        packet = make_packet(args.set, questions, manifest)
        review = blank_review(packet, args.reviewer)
        write_json(args.output / "packet.json", packet)
        write_json(args.output / "review.json", review)
        template = (ROOT / "scripts/reference_review.html").read_text()
        payload = json.dumps(
            {
                "packet": packet,
                "review": review,
                "rubric_text": (ROOT / "docs/difficulty-rubric.md").read_text(),
            }
        ).replace("<", "\\u003c")
        (args.output / "review.html").write_text(
            template.replace("__PAYLOAD__", payload)
        )
        print(f"Prepared blinded review: {args.output / 'review.html'}")
    elif args.command == "validate-review":
        review, _, _, _ = validate_review(args.set, read_json(args.review))
        print(
            json.dumps(
                {
                    "reviewer_id": review.reviewer_id,
                    "reviewed_count": sum(
                        r.status == "reviewed" for r in review.ratings
                    ),
                    "pending_count": sum(r.status == "pending" for r in review.ratings),
                    "requested_levels": "hidden until all ratings are frozen",
                },
                indent=2,
            )
        )
    else:
        report = compare_review(args.set, read_json(args.review))
        write_json(args.output, report)
        print(
            f"Reviewed: {report['reviewed_count']}; pending: {report['pending_count']}"
        )


if __name__ == "__main__":
    main()
