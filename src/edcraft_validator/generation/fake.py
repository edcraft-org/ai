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
        self._last_question: GeneratedQuestion | None = None

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

    def generate_draft(
        self,
        request: GenerationRequest,
        *,
        feedback: ValidationReport | None = None,
    ) -> QuestionDraft:
        question = self.generate(request, feedback=feedback)
        self._last_question = question
        return QuestionDraft(
            code=question.code,
            entry_function=question.entry_function,
            inputs=question.inputs,
            question=question.question,
            question_type=question.question_type,
        )

    def generate_distractors(
        self,
        draft: QuestionDraft,
        answer: object,
        num_distractors: int,
        *,
        feedback: ValidationReport | None = None,
    ) -> list[object]:
        _ = draft, answer, feedback
        if self._last_question is None:
            raise RuntimeError("generate_draft must be called first")
        return self._last_question.distractors[:num_distractors]
