"""Reference ratings stay hidden; failures remain in evaluation denominators."""

import json

import pytest
from fastmcp import Client
from test_difficulty_tool import ForbiddenExecutor, Provider, assessment, question

from edcraft_validator.mcp.server import create_validation_server
from scripts import evaluate_difficulty_dataset as evaluation


def item():
    return question().model_dump(mode="json") | {
        "question_id": "one",
        "difficulty": "hard",
        "difficulty_reason": "SECRET_REASON",
        "solution": "SECRET_SOLUTION",
        "topic": "arithmetic",
        "split": "held_out",
        "dimensions": dict.fromkeys(evaluation.DIMENSIONS, "high"),
    }


def record(estimate, *, reference="easy", alternatives=(), error=False):
    value = assessment() | {
        "estimated_difficulty": estimate,
        "alternative_levels": list(alternatives),
    }
    return {
        "provider": "test",
        "family_id": "family",
        "reference": {
            "difficulty": reference,
            "dimensions": dict.fromkeys(evaluation.DIMENSIONS, "low"),
        },
        "tool_output": {
            "status": "error" if error else "assessed",
            "error_code": "JUDGE_SCHEMA" if error else None,
            "judge": {"assessment": value},
        },
    }


async def test_live_path_blinds_reference_and_does_not_execute(tmp_path):
    provider = Provider()
    server = create_validation_server(
        difficulty_provider_factory=lambda: provider,
        code_execution_tool=ForbiddenExecutor(),
    )
    async with Client(server) as client:
        result = await evaluation.evaluate_item(client, "test", item(), tmp_path, 5)
    assert result["tool_output"]["status"] == "assessed"
    assert result["tool_output"]["requested_difficulty"] is None
    assert len(provider.requests) == 1
    prompt = json.dumps(provider.requests[0].messages)
    assert "SECRET_REASON" not in prompt and "SECRET_SOLUTION" not in prompt
    assert json.loads(provider.requests[0].messages[-1]["content"])[
        "question"
    ] == question().model_dump(mode="json")
    assert json.loads((tmp_path / "test-one.json").read_text()) == result


def test_primary_agreement_separates_hedging_missing_and_errors():
    records = [
        record("easy", alternatives=["medium"]),
        record("medium"),
        record(None),
        record("easy", error=True),
        record("hard"),
    ]
    summary = evaluation.summarize(records)
    assert summary["primary_agreement_all_items"] == {
        "count": 1,
        "denominator": 5,
        "rate": 0.2,
    }
    assert summary["primary_agreement_jointly_labelled"]["denominator"] == 3
    assert summary["uncertain_comparisons"] == 2
    assert summary["confirmed_reference_matches"]["count"] == 0
    assert summary["failures"] == {"JUDGE_SCHEMA": 1}
    assert summary["unknown_estimates"] == 1
    assert summary["severe_disagreements"] == 1
    assert summary["dimensions"]["changing_state"]["denominator"] == 4


def test_ordinal_alpha_known_cases_and_missing_categories():
    assert evaluation.ordinal_alpha([]) is None
    assert evaluation.ordinal_alpha([("easy", "easy")]) is None
    assert evaluation.ordinal_alpha([("easy", "easy"), ("hard", "hard")]) == 1
    assert evaluation.ordinal_alpha([("easy", "hard"), ("hard", "easy")]) == -0.5
    assert evaluation.ordinal_alpha(
        [("easy", "easy"), ("easy", "medium"), ("hard", "hard")]
    ) == pytest.approx(7 / 9)


def test_bootstrap_resamples_whole_families_and_is_reproducible():
    records = [record("easy"), record("hard")]
    assert "unavailable_reason" in evaluation.bootstrap_intervals(records)
    records[1]["family_id"] = "other"
    first = evaluation.bootstrap_intervals(records, replicates=100)
    assert first == evaluation.bootstrap_intervals(records, replicates=100)
    assert first["families"] == 2
    assert first["intervals"]["primary_agreement_all_items"]["lower"] == 0
    assert first["intervals"]["primary_agreement_all_items"]["upper"] == 1


async def test_protocol_failure_is_saved_without_retry(tmp_path):
    class ClientFailure:
        calls = 0

        async def call_tool(self, *args, **kwargs):
            self.calls += 1
            raise RuntimeError("secret endpoint details")

    client = ClientFailure()
    result = await evaluation.evaluate_item(client, "test", item(), tmp_path, 5)
    assert client.calls == 1
    assert result["error_code"] == "MCP_RuntimeError"
    assert "secret endpoint details" not in json.dumps(result)
    assert evaluation.summarize([result])["primary_agreement_all_items"]["rate"] == 0
