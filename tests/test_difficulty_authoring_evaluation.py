"""Report correction gains separately from primary matches and failed revisions."""

import copy

from test_difficulty_authoring import question, revised_question, run

from edcraft_validator.llm.llm_errors import GenerationResponseError
from scripts.evaluate_difficulty_authoring import summarize_records


async def test_summary_retains_failed_corrections_and_uncertain_primary_matches():
    matched, _, _ = await run([question().model_dump()], ["easy"], requested="easy")
    corrected, _, _ = await run(
        [question().model_dump(), revised_question()], ["easy", "medium"]
    )
    failed, _, _ = await run(
        [question().model_dump(), GenerationResponseError("bad revision")], ["easy"]
    )
    uncertain = copy.deepcopy(corrected.model_dump(mode="json"))
    uncertain["status"] = "uncertain"
    last = uncertain["attempts"][-1]["tool_output"]
    last["difficulty_match"] = "uncertain"
    last["judge"]["assessment"]["alternative_levels"] = ["easy"]
    last["judge"]["assessment"]["uncertainty_reason"] = "Adjacent boundary."
    records = [r.model_dump(mode="json") for r in (matched, corrected, failed)]
    records.append(uncertain)
    for record in records:
        record["provider"] = "scripted"
    summary = summarize_records(records)["scripted"]
    assert summary["jobs"] == 4
    assert summary["initial_confirmed_matches"] == 1
    assert summary["initial_primary_matches"] == 1
    assert summary["correction_attempts"] == 3
    assert summary["changed_questions"] == 2
    assert summary["corrections_resolved_to_confirmed_match"] == 1
    assert summary["final_primary_matches"] == 3
    assert summary["final_confirmed_matches"] == 2
    assert summary["final_uncertain"] == 1
    assert summary["final_errors"] == 1
    assert summary["usage"]["model_call_count"] == 13
