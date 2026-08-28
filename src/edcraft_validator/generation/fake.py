from pathlib import Path

from edcraft_validator.generation.models import (
    GenerationRequest,
    ProgrammingTopic,
    QuestionDraft,
)
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

    def generate_draft(
        self,
        request: GenerationRequest,
        *,
        feedback: ValidationReport | None = None,
    ) -> QuestionDraft:
        _ = request.difficulty, feedback
        path = self.examples_dir / DEFAULT_EXAMPLE_FILES[request.topic]
        question = GeneratedQuestion.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        return QuestionDraft(
            code=question.code,
            entry_function=question.entry_function,
            inputs=question.inputs,
            question=question.question,
            distractors=question.distractors[: request.num_distractors],
            distractor_reasons=[
                f"Fixed example misconception {index + 1}"
                for index in range(
                    min(request.num_distractors, len(question.distractors))
                )
            ],
            question_type=question.question_type,
        )
