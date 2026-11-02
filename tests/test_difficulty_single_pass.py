"""A check assesses once without repairing or retrying the judge."""

import json

import pytest
from test_difficulty_tool import Provider, assessment, question

from edcraft_validator.application.code_difficulty import (
    CodeDifficultyReport,
    assess_code_question_difficulty,
)
from edcraft_validator.llm.llm_errors import (
    GenerationResponseError,
    GenerationTimeoutError,
    GenerationTransportError,
)


def factory_for(responses):
    pending = list(responses)
    providers = []

    def factory():
        value = Provider(pending.pop(0))
        providers.append(value)
        return value

    return factory, providers


def missing_option():
    value = assessment()
    value["option_evidence"].pop()
    return value


@pytest.mark.parametrize(
    "response,error",
    [
        (missing_option(), "JUDGE_INVALID_RESPONSE"),
        (GenerationTransportError("private"), "JUDGE_TRANSPORT"),
        (GenerationResponseError("private"), "JUDGE_INVALID_RESPONSE"),
        (GenerationTimeoutError("private"), "JUDGE_TIMEOUT"),
        (assessment() | {"concepts_and_dependencies": []}, "JUDGE_INVALID_RESPONSE"),
    ],
)
async def test_failed_check_is_not_repaired_or_retried(response, error):
    factory, providers = factory_for([response, assessment()])
    report = await assess_code_question_difficulty(
        question(), provider_factory=factory, requested_difficulty="hard"
    )
    assert report.status == "error" and report.error_code == error
    assert report.difficulty_match is None and report.judge.assessment is None
    assert len(providers) == len(providers[0].requests) == 1
    assert report.usage.model_call_count == 1
    assert report.usage == report.judge.usage
    assert "private" not in report.model_dump_json()
    assert json.loads(providers[0].requests[0].messages[-1]["content"]) == {
        "question": question().model_dump(mode="json")
    }


def test_report_has_no_check_correction_configuration_or_history():
    fields = CodeDifficultyReport.model_fields
    assert "judge_attempts" not in fields and "max_correction_attempts" not in fields


async def test_valid_label_is_not_retried_to_make_it_agree_with_requested_level():
    factory, providers = factory_for([assessment(), assessment()])
    report = await assess_code_question_difficulty(
        question(), requested_difficulty="hard", provider_factory=factory
    )
    assert report.difficulty_match == "too_easy" and len(providers) == 1


async def test_unknown_usage_from_failed_call_is_not_replaced_with_zero():
    class TimeoutProvider(Provider):
        def generate(self, request):
            self.requests.append(request)
            raise GenerationTimeoutError("private")

    provider = TimeoutProvider()
    report = await assess_code_question_difficulty(
        question(), provider_factory=lambda: provider
    )
    assert report.status == "error" and len(provider.requests) == 1
    assert report.usage.input_tokens is None and report.usage.output_tokens is None
    assert report.usage.unavailable_call_count == 1
    assert report.usage.reported_input_tokens == 0


async def test_schema_diagnostics_remain_sanitized_without_a_followup():
    malformed = assessment() | {
        "concepts_and_dependencies": [],
        "reason": "PRIVATE_VALUE",
    }
    factory, providers = factory_for([malformed, assessment()])
    report = await assess_code_question_difficulty(question(), provider_factory=factory)
    assert report.status == "error" and len(providers) == 1
    assert report.judge.validation_errors[0].location == ["concepts_and_dependencies"]
    assert "PRIVATE_VALUE" not in report.model_dump_json()
