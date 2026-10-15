"""Bounded diagnostics repair output errors without revealing difficulty targets."""

import json

import pytest
from fastmcp import Client
from test_difficulty_authoring import run
from test_difficulty_tool import ForbiddenExecutor, Provider, assessment, question

from edcraft_validator.application.code_difficulty import (
    assess_code_question_difficulty,
)
from edcraft_validator.llm.llm_errors import (
    GenerationResponseError,
    GenerationTimeoutError,
    GenerationTransportError,
)
from edcraft_validator.mcp.server import create_validation_server
from scripts.evaluate_difficulty_dataset import all_summaries, evaluate_item


def factory_for(responses):
    pending = list(responses)
    providers = []

    def factory():
        value = Provider(pending.pop(0))
        providers.append(value)
        return value

    return factory, providers


async def test_three_failed_outputs_then_success_preserves_all_calls_and_blinding():
    wrong_options = assessment()
    wrong_options["option_evidence"].pop()
    factory, providers = factory_for(
        [
            wrong_options,
            GenerationTransportError("SENSITIVE_ERROR_CONTENT"),
            GenerationResponseError("SENSITIVE_ERROR_CONTENT"),
            assessment(),
        ]
    )
    original = question().model_dump(mode="json")
    report = await assess_code_question_difficulty(
        question(), provider_factory=factory, requested_difficulty="hard"
    )
    assert report.status == "assessed" and report.difficulty_match == "too_easy"
    assert len(report.judge_attempts) == len(providers) == 4
    assert [r.error_code for r in report.judge_attempts] == [
        "JUDGE_OPTION_EVIDENCE_MISMATCH",
        "JUDGE_TRANSPORT",
        "JUDGE_INVALID_RESPONSE",
        None,
    ]
    assert report.judge == report.judge_attempts[-1]
    assert report.usage.model_call_count == 4 and report.usage.input_tokens == 492
    assert report.error_code is None and report.question_sha256 == question().sha256
    for provider in providers:
        request = provider.requests[0]
        assert json.loads(request.messages[1]["content"]) == {"question": original}
        for message in request.messages[1:]:
            payload = json.loads(message["content"])
            assert "requested_difficulty" not in payload and "reference" not in payload
    assert "option_ids_mismatch" in providers[1].requests[0].messages[-1]["content"]
    assert "SENSITIVE_ERROR_CONTENT" not in report.model_dump_json()
    assert "SENSITIVE_ERROR_CONTENT" not in json.dumps(
        providers[-1].requests[0].messages
    )


async def test_all_four_failures_remain_errors_without_a_fabricated_label():
    factory, providers = factory_for(
        [GenerationResponseError("private") for _ in range(4)]
    )
    report = await assess_code_question_difficulty(question(), provider_factory=factory)
    assert report.status == "error" and report.error_code == "JUDGE_INVALID_RESPONSE"
    assert len(providers) == len(report.judge_attempts) == 4
    assert report.difficulty_match is None and report.judge.assessment is None
    assert report.usage.model_call_count == 4


async def test_valid_label_is_never_retried_to_make_it_agree_with_requested_level():
    factory, providers = factory_for([assessment()])
    report = await assess_code_question_difficulty(
        question(), requested_difficulty="hard", provider_factory=factory
    )
    assert report.difficulty_match == "too_easy" and len(providers) == 1


async def test_unknown_usage_from_failed_calls_is_not_replaced_with_zero():
    class TimeoutProvider(Provider):
        def generate(self, request):
            raise GenerationTimeoutError("private")

    calls = []

    def factory():
        provider = TimeoutProvider() if len(calls) < 3 else Provider()
        calls.append(provider)
        return provider

    report = await assess_code_question_difficulty(question(), provider_factory=factory)
    assert report.status == "assessed" and len(calls) == 4
    assert report.usage.input_tokens is None and report.usage.output_tokens is None
    assert report.usage.unavailable_call_count == 3
    assert report.usage.reported_input_tokens == 123


async def test_question_revision_can_match_on_the_third_correction():
    report, author, judges = await run(
        [question().model_dump() for _ in range(4)], ["easy", "easy", "easy", "medium"]
    )
    assert report.status == "matches" and report.error_code is None
    assert len(report.attempts) == len(author.requests) == len(judges) == 4


async def test_schema_diagnostics_are_sent_to_repair_without_response_values():
    malformed = assessment() | {
        "concepts_and_dependencies": [],
        "reason": "PRIVATE_VALUE",
    }
    factory, providers = factory_for([malformed, assessment()])
    report = await assess_code_question_difficulty(question(), provider_factory=factory)
    assert report.status == "assessed" and len(providers) == 2
    feedback = json.loads(providers[1].requests[0].messages[-1]["content"])
    assert feedback["validation_findings"][0]["location"] == [
        "concepts_and_dependencies"
    ]
    assert "PRIVATE_VALUE" not in report.model_dump_json()
    assert "PRIVATE_VALUE" not in json.dumps(providers[1].requests[0].messages)


@pytest.mark.parametrize("limit", [-1, 4, True, 1.5])
async def test_invalid_repair_budget_is_rejected_before_provider_calls(limit):
    factory, providers = factory_for([])
    with pytest.raises(ValueError):
        await assess_code_question_difficulty(
            question(), provider_factory=factory, max_correction_attempts=limit
        )
    assert providers == []


async def test_generation_recovers_on_third_correction_with_unchanged_brief_target():
    report, author, judges = await run(
        [
            *[GenerationResponseError("private") for _ in range(3)],
            question().model_dump(),
        ],
        ["easy"],
        requested="easy",
    )
    assert report.status == "matches" and report.error_code is None
    assert len(report.attempts) == len(author.requests) == 4 and len(judges) == 1
    assert [a.operation for a in report.attempts] == [
        "generation",
        "correction",
        "correction",
        "correction",
    ]
    first = json.loads(author.requests[0].messages[1]["content"])
    for request in author.requests[1:]:
        payload = json.loads(request.messages[1]["content"])
        assert payload["brief"] == first["brief"]
        assert payload["requested_difficulty"] == first["requested_difficulty"]
        assert payload["generation_feedback"]["error_code"] == "AUTHOR_INVALID_RESPONSE"
    assert "private" not in report.model_dump_json()


async def test_dataset_reports_first_pass_and_repaired_accuracy_separately(tmp_path):
    malformed = assessment() | {"concepts_and_dependencies": []}
    correct = assessment() | {"estimated_difficulty": "hard"}
    factory, providers = factory_for([malformed, correct])
    item = question().model_dump(mode="json") | {
        "question_id": "fixed",
        "difficulty": "hard",
        "topic": "arithmetic",
        "split": "development",
        "dimensions": {k: "low" for k in correct["dimensions"]},
    }
    server = create_validation_server(
        difficulty_provider_factory=factory, code_execution_tool=ForbiddenExecutor()
    )
    async with Client(server) as client:
        record = await evaluate_item(client, "test", item, tmp_path, 5)
    result = all_summaries([record])["providers"]["test"]["all"]
    assert result["primary_agreement_all_items"]["rate"] == 1
    assert result["first_pass"]["primary_agreement_all_items"]["rate"] == 0
    assert result["corrective_calls"] == result["recovered_to_label"] == 1
    assert len(providers) == 2
    assert "reference" not in providers[-1].requests[0].messages[-1]["content"]
