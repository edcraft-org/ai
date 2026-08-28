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

    def generate(
        self,
        request: GenerationRequest,
        *,
        feedback: ValidationReport | None = None,
    ) -> GeneratedQuestion:
        self.feedback.append(feedback)
        return sample_question()


class WrongDistractorCountGenerator(RecordingGenerator):
    def generate(
        self,
        request: GenerationRequest,
        *,
        feedback: ValidationReport | None = None,
    ) -> GeneratedQuestion:
        self.feedback.append(feedback)
        return sample_question().model_copy(update={"distractors": [4, 8]})


class SequenceValidator:
    def __init__(self, reports: list[ValidationReport]) -> None:
        self.reports = reports
        self.calls = 0

    def validate(self, question: GeneratedQuestion) -> ValidationReport:
        report = self.reports[self.calls]
        self.calls += 1
        return report


class TwoStageGenerator:
    def __init__(self, distractors: list[object]) -> None:
        self.distractors = distractors
        self.draft_calls = 0
        self.distractor_calls = 0

    def generate_draft(self, request, *, feedback=None):
        self.draft_calls += 1
        return QuestionDraft(
            code="def square(x):\n    return x * x",
            entry_function="square",
            inputs={"x": 4},
            question="What does square(4) return?",
        )

    def generate_distractors(self, draft, answer, num_distractors, *, feedback=None):
        self.distractor_calls += 1
        assert answer == 16
        return self.distractors[:num_distractors]

    def generate(self, request, *, feedback=None):
        raise AssertionError("two-stage generator should not use generate()")


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


def test_two_stage_pipeline_uses_computed_answer() -> None:
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
    assert generator.distractor_calls == 1


def test_retries_invalid_question_with_feedback() -> None:
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


def test_does_not_regenerate_after_execution_error() -> None:
    generator = RecordingGenerator()
    validator = SequenceValidator([execution_error_report()])
    service = GenerationService(generator, validator, attempt_log_path=None)

    outcome = service.generate(request())

    assert outcome.status == "execution_error"
    assert len(outcome.attempts) == 1
    assert len(generator.feedback) == 1


def test_rejects_candidate_with_wrong_distractor_count_before_execution() -> None:
    validator = SequenceValidator([])
    service = GenerationService(
        WrongDistractorCountGenerator(),
        validator,
        max_attempts=1,
        attempt_log_path=None,
    )

    outcome = service.generate(request())

    assert outcome.status == "rejected"
    assert validator.calls == 0
    assert (
        outcome.attempts[0].validation_report.issues[0].code
        == "DISTRACTOR_COUNT_MISMATCH"
    )


def test_logs_every_attempt_as_jsonl(tmp_path: Path) -> None:
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


def test_rejects_invalid_attempt_limit() -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        GenerationService(
            RecordingGenerator(),
            SequenceValidator([]),
            max_attempts=0,
            attempt_log_path=None,
        )
