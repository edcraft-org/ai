from pathlib import Path

from edcraft_validator.application import QuestionGenerationApplication
from edcraft_validator.generation.models import GenerationRequest, QuestionDraft
from edcraft_validator.models import ValidationReport


class StubGenerator:
    provider = "stub"
    model = "stub-model"

    def generate_draft(self, request, *, feedback=None):
        return QuestionDraft(
            code="def square(x):\n    return x * x",
            entry_function="square",
            inputs={"x": 4},
            question="What does square(4) return?",
            distractors=[4, 8, 20],
            distractor_reasons=["reason"] * 3,
        )


class StubValidator:
    def compute_answer(self, question):
        return ValidationReport(status="valid", actual_answer=16)

    def validate(self, question, *, actual_answer=None, trace_summary=None):
        return ValidationReport(status="valid", actual_answer=actual_answer)


def test_application_service_owns_generation_wiring() -> None:
    calls: list[tuple[str, object]] = []

    def generator_factory(provider, *, examples_dir):
        calls.append((provider, examples_dir))
        return StubGenerator()

    application = QuestionGenerationApplication(
        generator_factory=generator_factory,
        validator_factory=StubValidator,
    )

    outcome = application.generate(
        GenerationRequest(topic="arithmetic", difficulty="beginner"),
        provider="stub",
        attempt_log_path=None,
    )

    assert outcome.status == "accepted"
    assert outcome.question is not None
    assert outcome.question.proposed_answer == 16
    assert calls == [("stub", Path("examples"))]
