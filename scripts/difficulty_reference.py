"""Verify the provisional set and prepare blinded human reviews; no model calls."""

import argparse
import ast
import copy
import hashlib
import json
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

from edcraft_validator.domains.code.code_types import AnswerTarget, Difficulty
from edcraft_validator.domains.code.difficulty_matching import compare_difficulty
from edcraft_validator.tools.python_analysis import PythonSubsetAnalyzer
from edcraft_validator.tools.python_execution import LocalPythonTool
from edcraft_validator.value_comparison import equivalent, same_value_shape

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SET = ROOT / "reference_sets/python_tracing_v2"
REVIEW_SCHEMA = "human-difficulty-review-v2"
ASSISTED_REVIEW_SCHEMA = "human-difficulty-review-v3-assisted"
LEGACY_REVIEW_SCHEMA = "human-difficulty-review-v1"
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


def check_external_sources(directory: Path, questions: list, entries: list) -> None:
    external = [e for e in entries if e["provenance"]["kind"] == "cruxeval_adaptation"]
    if not external:
        return
    source_path = directory / "sources/cruxeval-selected.jsonl"
    source_bytes = source_path.read_bytes()
    records = [json.loads(line) for line in source_bytes.decode().splitlines()]
    by_id = {record["id"]: record for record in records}
    ids = [e["provenance"]["source_id"] for e in external]
    if (
        len(by_id) != len(records)
        or len(set(ids)) != len(ids)
        or set(ids) != set(by_id)
    ):
        raise ValueError("external sources must retain distinct original records")
    catalog = read_json(directory / "sources/provenance.json")
    license_bytes = (directory / "sources/CRUXEval-LICENSE").read_bytes()
    if hashlib.sha256(license_bytes).hexdigest() != catalog["license_sha256"]:
        raise ValueError("external source license changed")
    by_question = {q.question_id: q for q in questions}
    for entry in external:
        provenance = entry["provenance"]
        original = by_id[provenance["source_id"]]
        if (
            provenance["source_sha256"] != hashlib.sha256(source_bytes).hexdigest()
            or provenance["source_record_sha256"] != digest(original)
            or provenance["source_revision"] != catalog["revision"]
            or provenance["license"] != "MIT"
            or by_question[entry["question_id"]].code != original["code"]
        ):
            raise ValueError("external code or source provenance changed")


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
    family_counts = Counter()
    for question in questions:
        entry = next(e for e in entries if e["question_id"] == question.question_id)
        family, split = entry["family_id"], entry["split"]
        family_counts[family] += 1
        if split not in {"development", "held_out"}:
            raise ValueError("unknown split")
        if entry["requested_difficulty"] not in {"easy", "medium", "hard"}:
            raise ValueError("unknown requested level")
        if family_splits.setdefault(family, split) != split:
            raise ValueError("family leaks across splits")
        fingerprint = code_family_fingerprint(question.code)
        if code_families.setdefault(fingerprint, family) != family:
            raise ValueError("normalised code clone assigned to multiple families")
        if manifest.get("one_question_per_family") and family_counts[family] > 1:
            raise ValueError("primary collection permits one question per family")
        if set(entry["distractor_hypotheses"]) != set("ABCD") - {
            question.correct_option
        }:
            raise ValueError("distractor provenance missing")
    rubric_hash = hashlib.sha256((ROOT / "docs/difficulty-rubric.md").read_bytes())
    if rubric_hash.hexdigest() != manifest["rubric_sha256"]:
        raise ValueError("rubric changed; version and review the set again")
    check_external_sources(directory, questions, entries)
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
        "review_schema_version": REVIEW_SCHEMA,
        "reviewer_id": reviewer,
        "reviewer_kind": "human",
        "review_date": datetime.now(ZoneInfo("Asia/Singapore")).date().isoformat(),
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
                "rating_reason": "",
                "dimensions": {dimension: {"rating": None} for dimension in DIMENSIONS},
                "quality_concerns": "",
            }
            for q in packet["questions"]
        ],
    }


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
    # Retain detailed v1 human records without requiring these fields in v2.
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


class HumanReview(Record):
    review_schema_version: Literal[
        "human-difficulty-review-v1",
        "human-difficulty-review-v2",
        "human-difficulty-review-v3-assisted",
    ] = LEGACY_REVIEW_SCHEMA
    reviewer_id: str = Field(min_length=1)
    reviewer_kind: Literal["human"]
    review_date: str
    independent_blinded_review: bool
    assisted_review_confirmed: bool = False
    recommendations_sha256: str | None = None
    packet_sha256: str
    rubric_version: str
    rubric_sha256: str
    assessment_conditions_version: str
    ratings: list[Rating]

    @model_validator(mode="after")
    def valid_date(self):
        if date.fromisoformat(self.review_date).isoformat() != self.review_date:
            raise ValueError("review date must be YYYY-MM-DD")
        for rating in self.ratings:
            if rating.status != "reviewed":
                continue
            if any(d.rating is None for d in rating.dimensions.values()):
                raise ValueError(
                    "choose all four dimension ratings; unknown is allowed"
                )
            if self.review_schema_version == ASSISTED_REVIEW_SCHEMA:
                if rating.human_decision == "pending":
                    raise ValueError(
                        "assisted ratings need explicit human confirmation"
                    )
                if rating.human_decision in {"corrected", "uncertain"} and not (
                    rating.rating_reason.strip()
                ):
                    raise ValueError(
                        "corrections or abstentions need a short human note"
                    )
                if rating.human_decision == "uncertain" and not (
                    rating.estimated_difficulty is None or rating.confidence == "low"
                ):
                    raise ValueError(
                        "uncertain human decisions must abstain or use low confidence"
                    )
                continue
            if self.review_schema_version == REVIEW_SCHEMA:
                if not rating.rating_reason.strip():
                    raise ValueError("reviewed ratings need a short human reason")
                # One brief note covers rationale and any uncertainty; no walkthrough.
                continue
            reasons = [
                rating.solution_reasoning,
                rating.concepts_and_dependencies,
                rating.shortcuts,
                rating.nearest_anchor,
                *(dimension.reason for dimension in rating.dimensions.values()),
                *rating.option_evidence.values(),
            ]
            if set(rating.option_evidence) != set("ABCD") or any(
                not reason.strip() for reason in reasons
            ):
                raise ValueError("legacy reviewed ratings need full evidence")
            if (
                rating.estimated_difficulty is None
                or rating.confidence == "low"
                or rating.alternative_levels
                or any(d.rating == "unknown" for d in rating.dimensions.values())
            ) and not rating.uncertainty_reason.strip():
                raise ValueError("uncertain legacy reviews need an uncertainty reason")
        return self


def match_decision(rating: Rating, requested: Difficulty) -> str | None:
    if rating.status == "pending":
        return None
    return compare_difficulty(
        rating.estimated_difficulty,
        requested,
        rating.confidence,
        rating.alternative_levels,
    )


def load_recommendations(
    directory: Path, questions: list[Question], manifest: dict
) -> dict:
    """Load fixed AI proposals; these cannot count as human ratings by themselves."""
    data = read_json(directory / "ai-recommendations.json")
    if data["assessor_kind"] != "AI":
        raise ValueError("recommendations must disclose their AI origin")
    for field in (
        "set_version",
        "rubric_version",
        "rubric_sha256",
        "assessment_conditions_version",
    ):
        if data[field] != manifest[field]:
            raise ValueError("stale recommendation context")
    records = {record["question_id"]: record for record in data["records"]}
    if len(records) != len(data["records"]) or set(records) != {
        q.question_id for q in questions
    }:
        raise ValueError("recommendations must contain every question exactly once")
    for question in questions:
        record = records[question.question_id]
        if record["question_sha256"] != digest(question.model_dump()):
            raise ValueError("question changed since AI recommendation")
        rating = Rating.model_validate(
            {
                **{k: v for k, v in record.items() if k != "question_id"},
                "review_id": question.question_id,
                "status": "pending",
            }
        )
        if (
            rating.estimated_difficulty is None
            or any(
                d.rating is None or not d.reason.strip()
                for d in rating.dimensions.values()
            )
            or not rating.rating_reason.strip()
            or set(rating.option_evidence) != set("ABCD")
        ):
            raise ValueError("AI recommendations need proposed levels and evidence")
    return data


def assisted_review(packet: dict, reviewer: str, recommendations: dict) -> dict:
    review = blank_review(packet, reviewer)
    review.update(
        review_schema_version=ASSISTED_REVIEW_SCHEMA,
        recommendations_sha256=digest(recommendations),
        independent_blinded_review=False,
        assisted_review_confirmed=False,
    )
    by_hash = {r["question_sha256"]: r for r in recommendations["records"]}
    for rating in review["ratings"]:
        proposed = by_hash[rating["question_sha256"]]
        for field in ("estimated_difficulty", "confidence", "alternative_levels"):
            rating[field] = (
                proposed[field].copy()
                if isinstance(proposed[field], list)
                else proposed[field]
            )
        rating["dimensions"] = {
            key: {"rating": dimension["rating"]}
            for key, dimension in proposed["dimensions"].items()
        }
        rating["human_decision"] = "pending"
        # AI prose remains in its own recommendation, never a human-authored note.
    return review


def same_judgment(rating: Rating, proposed: dict) -> bool:
    return (
        rating.estimated_difficulty == proposed["estimated_difficulty"]
        and rating.confidence == proposed["confidence"]
        and set(rating.alternative_levels) == set(proposed["alternative_levels"])
        and all(
            rating.dimensions[key].rating == proposed["dimensions"][key]["rating"]
            for key in DIMENSIONS
        )
    )


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
    reviewed = [r for r in review.ratings if r.status == "reviewed"]
    if review.review_schema_version == ASSISTED_REVIEW_SCHEMA:
        data = load_recommendations(directory, questions, manifest)
        if review.recommendations_sha256 != digest(data):
            raise ValueError("AI recommendations changed since human verification")
        if review.independent_blinded_review:
            raise ValueError(
                "AI-assisted approvals cannot be independent blind ratings"
            )
        if reviewed and not review.assisted_review_confirmed:
            raise ValueError("confirm AI-assisted human review")
        proposed = {r["question_sha256"]: r for r in data["records"]}
        for rating in reviewed:
            original = proposed.get(rating.question_sha256)
            if original is None:
                raise ValueError("question changed since AI recommendation")
            same = same_judgment(rating, original)
            if rating.human_decision == "approved" and not same:
                raise ValueError("changed ratings must be recorded as corrections")
            if rating.human_decision == "corrected" and same:
                raise ValueError("a correction must change a proposed judgment")
    else:
        if (
            review.recommendations_sha256
            or review.assisted_review_confirmed
            or any(r.human_decision != "pending" for r in review.ratings)
        ):
            raise ValueError("assisted provenance cannot be relabelled independent")
        if reviewed and not review.independent_blinded_review:
            raise ValueError("reviewer must attest independent blinded human review")
    for blinded in packet["questions"]:
        if by_id[blinded["review_id"]].question_sha256 != blinded["question_sha256"]:
            raise ValueError("question changed since review")
    return review, packet, questions, manifest


def carry_forward_review(
    source_directory: Path, source_data: dict, destination_directory: Path
) -> tuple[dict, dict]:
    """Reuse explicit assisted decisions only for unchanged questions AND proposals.

    Keep the original review intact. Opaque IDs may change with packet ordering;
    the audit maps them by the full question hash, never by their display number.
    """
    source, source_packet, old_questions, old_manifest = validate_review(
        source_directory, source_data
    )
    if source.review_schema_version != ASSISTED_REVIEW_SCHEMA:
        raise ValueError("carry-forward requires an explicitly assisted source review")
    questions, manifest = load_set(destination_directory)
    for field in ("rubric_version", "rubric_sha256", "assessment_conditions_version"):
        if old_manifest[field] != manifest[field]:
            raise ValueError("review context changed; fresh human review required")
    proposals = load_recommendations(destination_directory, questions, manifest)
    old_proposals = load_recommendations(source_directory, old_questions, old_manifest)
    for field in ("assessor", "assessor_kind", "source_context"):
        if old_proposals[field] != proposals[field]:
            raise ValueError("recommendation context changed; fresh review required")
    packet = make_packet(destination_directory, questions, manifest)
    review = assisted_review(packet, source.reviewer_id, proposals)
    # Transfer is not a new human review event; retain the actual review date.
    review["review_date"] = source.review_date
    originals = {r["question_sha256"]: r for r in source_data["ratings"]}
    old_ai = {r["question_sha256"]: r for r in old_proposals["records"]}
    new_ai = {r["question_sha256"]: r for r in proposals["records"]}
    carried = []
    for index, rating in enumerate(review["ratings"]):
        item_hash = rating["question_sha256"]
        original = originals.get(item_hash)
        if (
            original is None
            or original["status"] != "reviewed"
            or old_ai.get(item_hash) != new_ai[item_hash]
        ):
            continue
        retained = copy.deepcopy(original)
        retained["review_id"] = rating["review_id"]
        review["ratings"][index] = retained
        carried.append(
            {
                "question_sha256": item_hash,
                "source_review_id": original["review_id"],
                "destination_review_id": rating["review_id"],
                "original_rating_sha256": digest(original),
                "carried_rating_sha256": digest(retained),
            }
        )
    review["assisted_review_confirmed"] = bool(carried)
    validate_review(destination_directory, review)
    return review, {
        "source_set_version": source_packet["set_version"],
        "source_review_sha256": digest(source_data),
        "source_review_date": source.review_date,
        "destination_set_version": packet["set_version"],
        "initial_destination_review_sha256": digest(review),
        "policy": "Unchanged full questions and exact AI proposals only; original "
        "human notes and corrections retained. New items remain pending.",
        "carried_count": len(carried),
        "pending_count": len(review["ratings"]) - len(carried),
        "mappings": carried,
    }


def compare_review(directory: Path, review_data: dict) -> dict:
    review, packet, questions, manifest = validate_review(directory, review_data)
    if any(r.status == "pending" for r in review.ratings):
        raise ValueError("finish and freeze all human ratings before comparison")
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
                "human_decision": rating.human_decision,
                "difficulty_match": match_decision(
                    rating, entry["requested_difficulty"]
                ),
            }
        )
    return {
        "review_sha256": digest(review_data),
        "packet_sha256": packet["packet_sha256"],
        "reviewer_id": review.reviewer_id,
        "reference_type": (
            "ai_assisted_single_human_reviewer"
            if review.review_schema_version == ASSISTED_REVIEW_SCHEMA
            else "single_human_reviewer"
        ),
        "independent_reference": review.review_schema_version != ASSISTED_REVIEW_SCHEMA,
        "recommendations_sha256": review.recommendations_sha256,
        "human_decisions": dict(Counter(r.human_decision for r in review.ratings)),
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
    export.add_argument("--assisted", action="store_true")
    export.add_argument("--output", type=Path, required=True)
    carry = commands.add_parser("carry-review")
    carry.add_argument("--source-set", type=Path, required=True)
    carry.add_argument("review", type=Path)
    carry.add_argument("--output", type=Path, required=True)
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
    elif args.command == "carry-review":
        saved = args.output / "review.json"
        if saved.exists():
            raise ValueError("destination review already exists; preserve it first")
        review, audit = carry_forward_review(
            args.source_set, read_json(args.review), args.set
        )
        write_json(saved, review)
        write_json(args.output / "carry-forward.json", audit)
        print(f"Carried {audit['carried_count']}; pending: {audit['pending_count']}")
    elif args.command == "prepare-review":
        packet = make_packet(args.set, questions, manifest)
        recommendations = (
            load_recommendations(args.set, questions, manifest)
            if args.assisted
            else None
        )
        review = (
            assisted_review(packet, args.reviewer, recommendations)
            if recommendations
            else blank_review(packet, args.reviewer)
        )
        # Do not replace a saved review record when regenerating its presentation.
        saved_path = args.output / "review.json"
        if saved_path.exists():
            saved = read_json(saved_path)
            if saved.get("review_schema_version") == review["review_schema_version"]:
                validate_review(args.set, saved)
                review = saved
            else:
                archive = args.output / f"review.archive-{digest(saved)[:12]}.json"
                if not archive.exists():
                    write_json(archive, saved)
        write_json(args.output / "packet.json", packet)
        write_json(args.output / "review.json", review)
        template = (ROOT / "scripts/reference_review.html").read_text()
        payload = json.dumps(
            {
                "packet": packet,
                "review": review,
                "rubric_text": (ROOT / "docs/difficulty-rubric.md").read_text(),
                "recommendations": (
                    {
                        record["question_sha256"]: {
                            key: value
                            for key, value in record.items()
                            if key != "question_id"
                        }
                        for record in recommendations["records"]
                    }
                    if recommendations
                    else None
                ),
                "recommendation_context": recommendations["source_context"]
                if recommendations
                else None,
                "carry_forward": (
                    read_json(args.output / "carry-forward.json")
                    if (args.output / "carry-forward.json").exists()
                    else None
                ),
            }
        ).replace("<", "\\u003c")
        (args.output / "review.html").write_text(
            template.replace("__PAYLOAD__", payload)
        )
        kind = "AI-assisted" if args.assisted else "independent"
        print(f"Prepared {kind} review: {args.output / 'review.html'}")
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
