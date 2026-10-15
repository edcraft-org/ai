"""Selection uses development only; a failed reserved gate retains the control."""

import pytest
from test_difficulty_dataset_evaluation import record

from scripts.experiment_soclaas_difficulty import (
    PROFILES,
    choose_candidate,
    macro_recall,
    promotion_decision,
)


def rated(profile, reference, estimate, split="development", error=False):
    return record(estimate, reference=reference, error=error) | {
        "profile": profile,
        "split": split,
    }


def test_candidate_selection_blinds_reserved_items_and_checks_equal_coverage():
    records = [
        rated(profile, level, level if profile == "combined" else "easy")
        for profile in PROFILES
        for level in ("easy", "medium", "hard")
    ]
    lengths = dict.fromkeys(PROFILES, 100)
    assert choose_candidate(records, lengths) == "combined"
    with pytest.raises(ValueError, match="development"):
        choose_candidate(
            records + [rated("combined", "hard", "hard", "held_out")], lengths
        )
    with pytest.raises(ValueError, match="equal"):
        choose_candidate(records[:-1], lengths)


def test_macro_recall_counts_failures_against_reference_support():
    records = [
        rated("control", "easy", "easy"),
        rated("control", "hard", "hard", error=True),
    ]
    assert macro_recall(records) == 0.5


def test_ties_prefer_shorter_prompt_without_extra_model_calls():
    records = [rated(p, "easy", "easy") for p in PROFILES]
    lengths = dict.fromkeys(PROFILES, 200) | {"runtime_rubric": 100}
    assert choose_candidate(records, lengths) == "runtime_rubric"


def test_failed_promotion_gate_does_not_select_a_different_candidate():
    records = [
        rated("control", "hard", "hard", "held_out"),
        rated("combined", "hard", "easy", "held_out"),
    ]
    assert promotion_decision(records, "combined") == "control"
    records[-1] = rated("combined", "hard", "hard", "held_out")
    assert promotion_decision(records, "combined") == "combined"
