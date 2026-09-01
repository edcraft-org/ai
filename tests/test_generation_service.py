import json
from pathlib import Path

import pytest

from edcraft_validator.generation.models import GenerationRequest, QuestionDraft
from edcraft_validator.generation.service import GenerationService
from edcraft_validator.models import (
    GeneratedQuestion,
    ValidationIssue,
    ValidationReport,
)


def sample_question() -> GeneratedQuestion:
    return GeneratedQuestion.model_validate(
        {
            "code": ["def square(x):", "    return x * x"],
            "entry_function": "square",
            "inputs": {"x": 4},
            "question": "What does square(4) return?",
            "proposed_answer": 16,
            "distractors": [4, 8, 20],
        }
    )


class RecordingGenerator:
    def __init__(self) -> None:
        self.feedback: list[ValidationReport | None] = []

    def generate_draft(
        self,
        request: GenerationRequest,
        *,
        feedback: ValidationReport | None = None,
    ) -> QuestionDraft:
        self.feedback.append(feedback)
        question = sample_question()
        return QuestionDraft(
            code=question.code,
            entry_function=question.entry_function,
            inputs=question.inputs,
            question=question.question,
            distractors=question.distractors,
            distractor_reasons=["reason"] * len(question.distractors),
        )


class SequenceValidator:
    def __init__(self, reports: list[ValidationReport]) -> None:
        self.reports = reports
        self.calls = 0

    def compute_answer(self, question: GeneratedQuestion) -> ValidationReport:
        report = self.reports[self.calls]
        self.calls += 1
        return report

    def validate(self, question, *, actual_answer=None, trace_summary=None):
        return ValidationReport(status="valid", actual_answer=actual_answer)


class TwoStageGenerator:
    def __init__(
        self, distractors: list[object], reasons: list[str] | None = None
    ) -> None:
        self.distractors = distractors
        self.reasons = reasons or ["Conceptual misunderstanding"] * len(distractors)
        self.draft_calls = 0

    def generate_draft(self, request, *, feedback=None):
        self.draft_calls += 1
        return QuestionDraft(
            code="def square(x):\n    return x * x",
            entry_function="square",
            inputs={"x": 4},
            question="What does square(4) return?",
            distractors=self.distractors,
            distractor_reasons=self.reasons,
        )


class AnswerComputingValidator:
    def compute_answer(self, question):
        return ValidationReport(status="valid", actual_answer=16)

    def validate(self, question, *, actual_answer=None, trace_summary=None):
        assert question.proposed_answer == 16
        assert actual_answer == 16
        return ValidationReport(status="valid", actual_answer=actual_answer)


def valid_report() -> ValidationReport:
    return ValidationReport(status="valid", actual_answer=16)


def invalid_report() -> ValidationReport:
    return ValidationReport(
        status="invalid",
        actual_answer=16,
        issues=[
            ValidationIssue(
                code="WRONG_PROPOSED_ANSWER",
                message="The proposed answer is incorrect",
            )
        ],
    )


def execution_error_report() -> ValidationReport:
    return ValidationReport(
        status="execution_error",
        issues=[
            ValidationIssue(
                code="CONTAINER_TIMEOUT",
                message="Docker did not finish in time",
            )
        ],
    )


def request() -> GenerationRequest:
    return GenerationRequest(topic="arithmetic", difficulty="beginner")


def test_accepts_first_valid_question() -> None:
    # A valid first candidate should finish immediately with one attempt.
    generator = RecordingGenerator()
    service = GenerationService(
        generator,
        SequenceValidator([valid_report()]),
        attempt_log_path=None,
    )

    outcome = service.generate(request())

    assert outcome.status == "accepted"
    assert outcome.question is not None
    assert len(outcome.attempts) == 1
    assert generator.feedback == [None]
    assert service.metrics.snapshot()["outcomes"] == {"accepted": 1}


def test_two_stage_pipeline_uses_computed_answer() -> None:
    # The executor's answer must replace any model-proposed answer in the result.
    generator = TwoStageGenerator([4, 8, 20])
    service = GenerationService(
        generator,
        AnswerComputingValidator(),
        attempt_log_path=None,
    )

    outcome = service.generate(request())

    assert outcome.status == "accepted"
    assert outcome.question is not None
    assert outcome.question.proposed_answer == 16
    assert generator.draft_calls == 1
    assert outcome.attempts[0].distractor_reasons == ["Conceptual misunderstanding"] * 3


def test_two_stage_pipeline_rejects_wrong_distractor_count() -> None:
    # Invalid option counts should be rejected before the executor is called.
    generator = TwoStageGenerator([4, 8])
    service = GenerationService(
        generator,
        AnswerComputingValidator(),
        max_attempts=1,
        attempt_log_path=None,
    )

    outcome = service.generate(request())

    assert outcome.status == "rejected"
    assert (
        outcome.attempts[0].validation_report.issues[0].code
        == "DISTRACTOR_COUNT_MISMATCH"
    )


def test_two_stage_pipeline_rejects_wrong_reason_count() -> None:
    # Every distractor must have review metadata before execution is attempted.
    generator = TwoStageGenerator([4, 8, 20], reasons=["Only one reason"])
    validator = AnswerComputingValidator()
    service = GenerationService(
        generator, validator, max_attempts=1, attempt_log_path=None
    )

    outcome = service.generate(request())

    assert outcome.status == "rejected"
    assert outcome.attempts[0].validation_report.issues[0].code == (
        "DISTRACTOR_REASON_COUNT_MISMATCH"
    )


def test_retries_invalid_question_with_feedback() -> None:
    # Deterministic validation failures should trigger a retry with feedback.
    generator = RecordingGenerator()
    first_report = invalid_report()
    service = GenerationService(
        generator,
        SequenceValidator([first_report, valid_report()]),
        attempt_log_path=None,
    )

    outcome = service.generate(request())

    assert outcome.status == "accepted"
    assert len(outcome.attempts) == 2
    assert generator.feedback == [None, first_report]


def test_rejects_after_three_invalid_attempts() -> None:
    # The service must stop after its configured retry budget is exhausted.
    generator = RecordingGenerator()
    service = GenerationService(
        generator,
        SequenceValidator([invalid_report()] * 3),
        attempt_log_path=None,
    )

    outcome = service.generate(request())

    assert outcome.status == "rejected"
    assert outcome.question is None
    assert len(outcome.attempts) == 3
    assert service.metrics.snapshot()["outcomes"] == {"rejected": 1}


def test_does_not_regenerate_after_execution_error() -> None:
    # Infrastructure or code execution failures should stop generation immediately.
    generator = RecordingGenerator()
    validator = SequenceValidator([execution_error_report()])
    service = GenerationService(generator, validator, attempt_log_path=None)

    outcome = service.generate(request())

    assert outcome.status == "execution_error"
    assert len(outcome.attempts) == 1
    assert len(generator.feedback) == 1
    assert service.metrics.snapshot()["outcomes"] == {"execution_error": 1}


def test_logs_every_attempt_as_jsonl(tmp_path: Path) -> None:
    # Each generated attempt should be recoverable from the append-only audit log.
    log_path = tmp_path / "attempts.jsonl"
    service = GenerationService(
        RecordingGenerator(),
        SequenceValidator([invalid_report(), valid_report()]),
        attempt_log_path=log_path,
    )

    outcome = service.generate(request())

    records = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert len(records) == 2
    assert {record["run_id"] for record in records} == {outcome.run_id}
    assert records[0]["attempt"]["attempt_number"] == 1
    assert records[1]["attempt"]["validation_report"]["status"] == "valid"
    assert records[0]["telemetry"]["provider"] == "RecordingGenerator"
    assert records[0]["telemetry"]["status"] == "invalid"
    assert records[0]["telemetry"]["issue_codes"] == ["WRONG_PROPOSED_ANSWER"]
    assert records[0]["telemetry"]["generation_duration_ms"] >= 0
    assert records[0]["telemetry"]["validation_duration_ms"] >= 0


def test_rejects_invalid_attempt_limit() -> None:
    # A non-positive retry budget is invalid service configuration.
    with pytest.raises(ValueError, match="greater than zero"):
        GenerationService(
            RecordingGenerator(),
            SequenceValidator([]),
            max_attempts=0,
            attempt_log_path=None,
        )
