from typing import Any

import pytest

from edcraft_validator.domains.code.templates import (
    CodeQuestionTemplate,
    SafeExpression,
    TemplateInstanceGenerator,
    TemplateValidationError,
    TemplateValidator,
    build_template_prompt,
)
from edcraft_validator.executor import ExecutionResult
from edcraft_validator.generation.models import TemplateAuthoringRequest


def template(**changes: Any) -> CodeQuestionTemplate:
    data = {
        "template_id": "arithmetic.linear_sum",
        "version": 1,
        "topic": "arithmetic",
        "difficulty": "beginner",
        "code": "def calculate(a, b, c):\n    return a + b - c",
        "entry_function": "calculate",
        "parameters": [
            {"name": "a", "values": [2, 4]},
            {"name": "b", "values": [5, 8]},
            {"name": "c", "values": [1, 3]},
        ],
        "question_template": "What does calculate({a}, {b}, {c}) return?",
        "answer_target": "return_value",
        "answer_expression": "a + b - c",
        "distractors": [
            {
                "expression": "a + b + c",
                "reason_template": "Adds c instead of subtracting it.",
            },
            {
                "expression": "a - b - c",
                "reason_template": "Subtracts both b and c from a.",
            },
            {
                "expression": "a + b",
                "reason_template": "Omits c.",
            },
        ],
        "question_type": "mcq",
    }
    data.update(changes)
    return CodeQuestionTemplate.model_validate(data)


class ArithmeticExecutor:
    def __init__(self) -> None:
        self.calls: list[dict[str, int]] = []
        self.batch_calls = 0

    def execute(
        self,
        code: str,
        entry_function: str,
        inputs: dict[str, Any],
        *,
        timeout_seconds: float,
    ) -> ExecutionResult:
        self.calls.append(inputs)
        return ExecutionResult(
            ok=True,
            answer=inputs["a"] + inputs["b"] - inputs["c"],
        )

    def execute_batch(
        self,
        code: str,
        entry_function: str,
        inputs: list[dict[str, Any]],
        *,
        timeout_seconds: float,
    ) -> list[ExecutionResult]:
        self.batch_calls += 1
        self.calls.extend(inputs)
        return [
            ExecutionResult(
                ok=True,
                answer=item["a"] + item["b"] - item["c"],
            )
            for item in inputs
        ]


def test_validates_every_case_once_then_generates_without_executor() -> None:
    executor = ArithmeticExecutor()
    approved = TemplateValidator(executor=executor).validate(template())

    assert approved.validation.cases_validated == 8
    assert executor.batch_calls == 1
    assert len(executor.calls) == 8

    first = TemplateInstanceGenerator().generate(approved, seed=42)
    second = TemplateInstanceGenerator().generate(approved, seed=42)

    assert first == second
    assert len(executor.calls) == 8
    assert first.question.proposed_answer == (
        first.parameters["a"] + first.parameters["b"] - first.parameters["c"]
    )
    assert first.question.question.startswith("What does calculate(")


def test_supports_loop_iteration_questions() -> None:
    loop_template = CodeQuestionTemplate.model_validate(
        {
            "template_id": "loops.iteration_count",
            "version": 1,
            "topic": "loops",
            "difficulty": "beginner",
            "code": (
                "def accumulate(n):\n"
                "    total = 0\n"
                "    for i in range(n):\n"
                "        total += i\n"
                "    return total"
            ),
            "entry_function": "accumulate",
            "parameters": [{"name": "n", "values": [2, 4]}],
            "question_template": (
                "How many total loop-body iterations occur when accumulate({n}) runs?"
            ),
            "answer_target": "loop_iterations",
            "answer_expression": "n",
            "distractors": [
                {"expression": "n - 1", "reason_template": "Misses one iteration."},
                {"expression": "n + 1", "reason_template": "Counts one extra."},
                {"expression": "n + 2", "reason_template": "Counts two extra."},
            ],
            "question_type": "mcq",
        }
    )

    class LoopExecutor:
        def execute_batch(self, code, entry_function, inputs, *, timeout_seconds):
            return [
                ExecutionResult(
                    ok=True,
                    answer=sum(range(item["n"])),
                    trace_summary={"loop_iterations": item["n"]},
                )
                for item in inputs
            ]

    approved = TemplateValidator(executor=LoopExecutor()).validate(loop_template)
    instance = TemplateInstanceGenerator().generate(approved, seed=3)

    assert approved.validation.cases_validated == 2
    assert instance.question.answer_target == "loop_iterations"
    assert instance.question.proposed_answer == instance.parameters["n"]


def test_loop_topic_requests_iteration_count_template() -> None:
    prompt = build_template_prompt(
        TemplateAuthoringRequest(topic="loops", difficulty="beginner")
    )

    assert "answer_target=loop_iterations" in prompt
    assert "exactly one integer parameter named n" in prompt
    assert "answer_expression to exactly `n`" in prompt


def test_rejects_a_distractor_that_is_correct_for_any_case() -> None:
    value = template().model_dump()
    value["distractors"][0]["expression"] = "a + b - c"

    with pytest.raises(TemplateValidationError, match="equals the answer"):
        TemplateValidator(executor=ArithmeticExecutor()).validate(
            CodeQuestionTemplate.model_validate(value)
        )


def test_rejects_expression_calls() -> None:
    with pytest.raises(TemplateValidationError, match="unsupported expression syntax"):
        SafeExpression("sum(a)", ("a",))


def test_refuses_to_expand_a_changed_approved_template() -> None:
    approved = TemplateValidator(executor=ArithmeticExecutor()).validate(template())
    approved.template.answer_expression = "a + b + c"

    with pytest.raises(ValueError, match="changed since validation"):
        TemplateInstanceGenerator().generate(approved, seed=1)


def test_refuses_incomplete_approval_evidence() -> None:
    approved = TemplateValidator(executor=ArithmeticExecutor()).validate(template())
    approved.validation.cases_validated = 7

    with pytest.raises(ValueError, match="complete input domain"):
        TemplateInstanceGenerator().generate(approved, seed=1)
