"""Correction summaries retain exhausted retries and missing-information outcomes."""

from test_difficulty_authoring import question, revised_question, run

from edcraft_validator.llm.llm_errors import GenerationResponseError
from scripts.evaluate_difficulty_authoring import summarize_records


async def test_summary_counts_three_corrections_and_does_not_hide_failed_revisions():
    matched, _, _ = await run([question().model_dump()], ["easy"], requested="easy")
    corrected, _, _ = await run(
        [question().model_dump(), revised_question()], ["easy", "medium"]
    )
    failed, _, _ = await run(
        [
            question().model_dump(),
            *[GenerationResponseError("bad revision") for _ in range(3)],
        ],
        ["easy"],
    )
    unable, _, _ = await run(
        [question().model_dump(), *[revised_question() for _ in range(3)]], [None] * 4
    )
    records = [
        r.model_dump(mode="json") | {"provider": "scripted"}
        for r in (matched, corrected, failed, unable)
    ]
    summary = summarize_records(records)["scripted"]
    assert summary["jobs"] == 4
    assert (
        summary["initial_confirmed_matches"] == summary["initial_primary_matches"] == 1
    )
    assert summary["jobs_with_corrections"] == 3
    assert summary["correction_attempts"] == 7
    assert summary["changed_questions"] == 2
    assert summary["corrections_resolved_to_confirmed_match"] == 1
    assert summary["final_primary_matches"] == summary["final_confirmed_matches"] == 2
    assert summary["final_unable_to_assess"] == 1
    assert summary["final_errors"] == 1
    assert summary["usage"]["model_call_count"] == 19
