from pathlib import Path

import pytest

from edcraft_validator.executor import ExecutionResult
from edcraft_validator.generation.fake import FakeQuestionGenerator
from edcraft_validator.generation.models import GenerationRequest
from edcraft_validator.generation.service import GenerationService
from edcraft_validator.validator import QuestionValidator

EXAMPLES_DIR = Path(__file__).parents[1] / "examples"


@pytest.mark.parametrize(
    ("topic", "entry_function"),
    [
        ("arithmetic", "square"),
        ("conditionals", "delivery_fee"),
        ("loops", "accumulated_bonus"),
        ("functions", "weighted_total"),
        ("lists", "summarize"),
    ],
)
def test_selects_example_for_topic(topic: str, entry_function: str) -> None:
    request = GenerationRequest.model_validate(
        {"topic": topic, "difficulty": "intermediate"}
    )

    draft = FakeQuestionGenerator(EXAMPLES_DIR).generate_draft(request)

    assert draft.entry_function == entry_function
    assert len(draft.distractors) == 3
    assert len(draft.distractor_reasons) == 3


def test_uses_requested_distractor_count() -> None:
    request = GenerationRequest(
        topic="arithmetic",
        difficulty="beginner",
        num_distractors=2,
    )

    draft = FakeQuestionGenerator(EXAMPLES_DIR).generate_draft(request)

    assert len(draft.distractors) == 2
    assert len(draft.distractor_reasons) == 2


def test_missing_example_is_reported() -> None:
    request = GenerationRequest(topic="arithmetic", difficulty="beginner")
    with pytest.raises(FileNotFoundError):
        FakeQuestionGenerator(Path("missing-examples")).generate_draft(request)


class FixedExampleExecutor:
    def execute(self, code, entry_function, inputs, *, timeout_seconds):
        return ExecutionResult(ok=True, answer=41)


def test_fake_draft_passes_through_authoritative_answer_flow() -> None:
    request = GenerationRequest(
        topic="loops", difficulty="intermediate", num_distractors=3
    )
    service = GenerationService(
        FakeQuestionGenerator(EXAMPLES_DIR),
        QuestionValidator(executor=FixedExampleExecutor()),
        attempt_log_path=None,
    )

    outcome = service.generate(request)

    assert outcome.status == "accepted"
    assert outcome.question is not None
    assert outcome.question.proposed_answer == 41
    assert not hasattr(outcome.question, "distractor_reasons")
    assert len(outcome.attempts[0].distractor_reasons) == 3
