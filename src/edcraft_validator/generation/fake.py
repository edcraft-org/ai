from pathlib import Path

from edcraft_validator.generation.models import GenerationRequest, ProgrammingTopic
from edcraft_validator.models import GeneratedQuestion, ValidationReport

DEFAULT_EXAMPLE_FILES: dict[ProgrammingTopic, str] = {
    "arithmetic": "valid_square.json",
    "conditionals": "valid_delivery_fee.json",
    "loops": "valid_accumulated_bonus.json",
    "functions": "valid_weighted_total.json",
    "lists": "valid_summary.json",
}


class FakeQuestionGenerator:
    """Load deterministic examples while the real AI provider is not connected."""

    def __init__(self, examples_dir: Path) -> None:
        self.examples_dir = examples_dir

    def generate(
        self,
        request: GenerationRequest,
        *,
        feedback: ValidationReport | None = None,
    ) -> GeneratedQuestion:
        # Difficulty and feedback become meaningful when an AI provider is added.
        _ = request.difficulty, feedback
        path = self.examples_dir / DEFAULT_EXAMPLE_FILES[request.topic]
        question = GeneratedQuestion.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        return question.model_copy(
            update={"distractors": question.distractors[: request.num_distractors]}
        )

