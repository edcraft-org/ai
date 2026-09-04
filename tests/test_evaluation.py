import json

from edcraft_validator.application import TemplateEvaluator
from edcraft_validator.domains.code.templates import (
    CodeTemplateProposal,
    TemplateValidator,
)
from edcraft_validator.executor import ExecutionResult
from edcraft_validator.generation.base import GenerationError
from edcraft_validator.generation.models import TemplatePromptMetadata


def proposal(*, code: str = "def add(a, b):\n    return a + b") -> CodeTemplateProposal:
    return CodeTemplateProposal.model_validate(
        {
            "code": code,
            "entry_function": "add",
            "parameters": [
                {"name": "a", "kind": "integer", "values": [1, 2]},
                {"name": "b", "kind": "integer", "values": [3, 4]},
            ],
            "answer_expression": "a + b",
            "distractors": [
                {"expression": "a + b", "reason_template": "Repeats answer."},
                {"expression": "a - b", "reason_template": "Subtracts."},
                {"expression": "a + b + 1", "reason_template": "Adds one."},
                {"expression": "a + b - 1", "reason_template": "Subtracts one."},
                {"expression": "a + b + 2", "reason_template": "Adds two."},
            ],
        }
    )


class SumExecutor:
    def execute_batch(self, code, entry_function, inputs, *, timeout_seconds):
        return [
            ExecutionResult(ok=True, answer=item["a"] + item["b"]) for item in inputs
        ]


class StubGenerator:
    provider = "stub"
    model = "stub-model"

    def __init__(self, result: CodeTemplateProposal) -> None:
        self.result = result

    def prompt_metadata(self, request):
        return TemplatePromptMetadata(version="test-v1", sha256="c" * 64)

    def generate_proposal(self, request):
        return self.result


def test_evaluation_records_outputs_failures_and_grouped_metrics(tmp_path) -> None:
    proposals = iter([proposal(), proposal(code="def add(a, b):\n    return a")])
    evaluator = TemplateEvaluator(
        generator_factory=lambda selection: StubGenerator(next(proposals)),
        validator_factory=lambda: TemplateValidator(executor=SumExecutor()),
    )

    report = evaluator.evaluate(
        provider="stub",
        model="stub-model",
        topics=("arithmetic",),
        difficulties=("beginner",),
        repetitions=2,
    )

    assert [attempt.status for attempt in report.attempts] == ["approved", "failed"]
    assert report.attempts[0].approved_template is not None
    assert report.attempts[1].failure_stage == "validation"
    assert report.attempts[1].failure_code == "PROFILE_MISMATCH"
    assert report.attempts[1].validation_evidence[-1].status == "failed"
    assert report.attempts[1].validation_evidence[-1].check == "template_structure"
    assert report.summary.attempts == 2
    assert report.summary.approved == 1
    assert report.summary.pass_rate == 0.5
    assert report.summary.failure_counts == {"PROFILE_MISMATCH": 1}
    assert report.summary.groups[0].model == "stub-model"

    output = tmp_path / "evaluation.jsonl"
    report.write_jsonl(output)
    records = [json.loads(line) for line in output.read_text().splitlines()]
    assert len(records) == 2
    assert records[0]["approved_template"]["authoring"]["model"] == "stub-model"
    assert records[1]["failure_code"] == "PROFILE_MISMATCH"
    assert records[1]["validation_evidence"][-1]["issues"][0]["code"] == (
        "PROFILE_MISMATCH"
    )


def test_evaluation_notifies_after_each_completed_attempt() -> None:
    observed = []
    evaluator = TemplateEvaluator(
        generator_factory=lambda selection: StubGenerator(proposal()),
        validator_factory=lambda: TemplateValidator(executor=SumExecutor()),
    )

    report = evaluator.evaluate(
        provider="stub",
        model="stub-model",
        topics=("arithmetic",),
        difficulties=("beginner",),
        repetitions=2,
        on_attempt=observed.append,
    )

    assert observed == report.attempts
    assert [attempt.attempt for attempt in observed] == [1, 2]


def test_evaluation_classifies_provider_setup_failure() -> None:
    def unavailable(selection):
        raise GenerationError("provider is not configured")

    report = TemplateEvaluator(generator_factory=unavailable).evaluate(
        provider="missing",
        model=None,
        topics=("arithmetic",),
        difficulties=("beginner",),
        repetitions=1,
    )

    attempt = report.attempts[0]
    assert attempt.status == "failed"
    assert attempt.failure_stage == "configuration"
    assert attempt.failure_code == "generation_error"
