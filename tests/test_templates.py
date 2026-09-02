import json
from pathlib import Path
from typing import Any

import pytest

from edcraft_validator._worker import execute_request
from edcraft_validator.domains.code.capabilities import (
    CODE_DIFFICULTIES,
    CODE_TEMPLATE_PROFILES,
    CODE_TOPICS,
    code_template_profile,
)
from edcraft_validator.domains.code.templates import (
    CodeQuestionTemplate,
    FiniteParameter,
    SafeExpression,
    TemplateInstanceGenerator,
    TemplateValidationError,
    TemplateValidator,
    build_template_prompt,
    parse_code_question_template,
)
from edcraft_validator.executor import ExecutionResult
from edcraft_validator.generation.models import TemplateAuthoringRequest

TEMPLATE_DIR = Path(__file__).parents[1] / "examples" / "templates"
TEMPLATE_PATHS = sorted(TEMPLATE_DIR.glob("*.json"))


def template(**changes: Any) -> CodeQuestionTemplate:
    data = {
        "template_id": "arithmetic.linear_sum",
        "version": 1,
        "topic": "arithmetic",
        "difficulty": "beginner",
        "code": "def calculate(a, b, c):\n    return a + b - c",
        "entry_function": "calculate",
        "parameters": [
            {"name": "a", "kind": "integer", "values": [2, 4]},
            {"name": "b", "kind": "integer", "values": [5, 8]},
            {"name": "c", "kind": "integer", "values": [1, 3]},
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


class TrustedBatchExecutor:
    """Exercise fixed repository templates through the real tracer in-process."""

    def execute_batch(self, code, entry_function, inputs, *, timeout_seconds):
        results = []
        for item in inputs:
            response = execute_request(
                {
                    "code": code,
                    "entry_function": entry_function,
                    "inputs": item,
                    "timeout_seconds": timeout_seconds,
                }
            )
            results.append(
                ExecutionResult(
                    ok=response["ok"],
                    answer=response.get("answer"),
                    trace_summary=response.get("trace_summary"),
                    error_code=response.get("error_code"),
                    error_message=response.get("error_message"),
                )
            )
        return results


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
            "parameters": [{"name": "n", "kind": "integer", "values": [2, 4]}],
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
    assert "answer_expression exactly `n`" in prompt


def test_beginner_arithmetic_prompt_forbids_operator_parameter() -> None:
    prompt = build_template_prompt(
        TemplateAuthoringRequest(topic="arithmetic", difficulty="beginner")
    )

    assert "two or three integer parameters named a, b, and optionally c" in prompt
    assert "Do not create a parameter for the operator" in prompt


def test_provider_template_parser_removes_duplicate_parameter_values() -> None:
    payload = template().model_dump(mode="json")
    payload["parameters"][0]["values"] = [2, 2, 4]

    parsed = parse_code_question_template(json.dumps(payload))

    assert parsed.parameters[0].values == [2, 4]


def test_provider_template_parser_does_not_invent_missing_domain_values() -> None:
    payload = template().model_dump(mode="json")
    payload["parameters"][0]["values"] = [2, 2]

    with pytest.raises(ValueError, match="at least 2 items"):
        parse_code_question_template(json.dumps(payload))


def test_every_topic_and_difficulty_has_distinct_authoring_guidance() -> None:
    prompts = {
        (topic, difficulty): build_template_prompt(
            TemplateAuthoringRequest(topic=topic, difficulty=difficulty)
        )
        for topic in CODE_TOPICS
        for difficulty in CODE_DIFFICULTIES
    }

    assert len(set(prompts.values())) == 15
    assert "two sequential range loops" in prompts[("loops", "intermediate")]
    assert "one nested range loop" in prompts[("loops", "advanced")]
    assert "nested helpers" in prompts[("functions", "advanced")]


def test_examples_cover_every_topic_and_difficulty() -> None:
    templates = [
        CodeQuestionTemplate.model_validate_json(path.read_text())
        for path in TEMPLATE_PATHS
    ]
    actual = {(template.topic, template.difficulty) for template in templates}
    expected = {
        (topic, difficulty) for topic in CODE_TOPICS for difficulty in CODE_DIFFICULTIES
    }

    assert len(templates) == len(expected)
    assert actual == expected


def test_example_templates_match_their_capability_profiles() -> None:
    for path in TEMPLATE_PATHS:
        item = CodeQuestionTemplate.model_validate_json(path.read_text())
        profile = code_template_profile(item.topic, item.difficulty)
        actual_kinds = tuple(parameter.kind for parameter in item.parameters)
        actual_names = tuple(parameter.name for parameter in item.parameters)

        assert item.answer_target == profile.answer_target
        assert any(
            actual_kinds == shape.kinds
            and (shape.names is None or actual_names == shape.names)
            for shape in profile.parameter_shapes
        ), item.template_id
        if profile.require_positive_integers:
            assert all(
                value > 0
                for parameter in item.parameters
                if parameter.kind == "integer"
                for value in parameter.values
            ), item.template_id


def test_capability_catalog_covers_each_profile_once() -> None:
    assert len(CODE_TEMPLATE_PROFILES) == 15
    for topic in CODE_TOPICS:
        targets = {
            code_template_profile(topic, difficulty).answer_target
            for difficulty in CODE_DIFFICULTIES
        }
        assert len(targets) == 1


@pytest.mark.parametrize("path", TEMPLATE_PATHS, ids=lambda path: path.stem)
def test_every_example_template_validates_with_the_real_tracer(path: Path) -> None:
    raw_template = CodeQuestionTemplate.model_validate_json(path.read_text())

    approved = TemplateValidator(executor=TrustedBatchExecutor()).validate(raw_template)
    instance = TemplateInstanceGenerator().generate(approved, seed=11)

    expected_cases = 1
    for parameter in raw_template.parameters:
        expected_cases *= len(parameter.values)
    assert approved.validation.cases_validated == expected_cases
    assert instance.question.answer_target == raw_template.answer_target


@pytest.mark.parametrize(
    ("kind", "values"),
    [
        ("integer", [False, True]),
        ("boolean", [0, 1]),
        ("string", ["valid", ""]),
        ("integer_list", [[1, 2], [1, True]]),
    ],
)
def test_parameter_kind_rejects_mismatched_values(kind: str, values: list[Any]) -> None:
    with pytest.raises(ValueError):
        FiniteParameter.model_validate(
            {"name": "value", "kind": kind, "values": values}
        )


def test_safe_expression_supports_validated_collection_operations() -> None:
    values = {"items": [3, 1, 2], "label": "ready", "enabled": True}

    assert SafeExpression("sum(items)", tuple(values)).evaluate(values) == 6
    assert SafeExpression("items[1]", tuple(values)).evaluate(values) == 1
    assert SafeExpression("sorted(items)", tuple(values)).evaluate(values) == [1, 2, 3]
    assert (
        SafeExpression(
            'len(items) if enabled and label == "ready" else 0', tuple(values)
        ).evaluate(values)
        == 3
    )


def test_list_topic_requests_an_integer_list_template() -> None:
    prompt = build_template_prompt(
        TemplateAuthoringRequest(topic="lists", difficulty="beginner")
    )

    assert "integer_list parameter named values" in prompt
    assert "sum(values)" in prompt


def test_rejects_a_distractor_that_is_correct_for_any_case() -> None:
    value = template().model_dump()
    value["distractors"][0]["expression"] = "a + b - c"

    with pytest.raises(TemplateValidationError, match="equals the answer"):
        TemplateValidator(executor=ArithmeticExecutor()).validate(
            CodeQuestionTemplate.model_validate(value)
        )


def test_rejects_non_allowlisted_expression_calls() -> None:
    with pytest.raises(TemplateValidationError, match="unsupported expression syntax"):
        SafeExpression("open(a)", ("a",))


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
