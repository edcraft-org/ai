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
    CodeTemplateProposal,
    FiniteParameter,
    SafeExpression,
    TemplateInstanceGenerator,
    TemplateValidationError,
    TemplateValidator,
    build_template_prompt,
    normalize_code_template_proposal,
    parse_code_question_template,
    parse_code_template_proposal,
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
    assert approved.validation.validator_version == "code-template-validator-v1"
    assert [item.check for item in approved.validation.evidence] == [
        "template_structure",
        "expression_safety",
        "answer_domain",
        "sandboxed_execution",
        "answer_consistency",
        "distractor_consistency",
        "template_rendering",
    ]
    assert all(item.status == "passed" for item in approved.validation.evidence)
    assert approved.validation.evidence[2].assurance == "exhaustive"
    assert approved.validation.evidence[2].details == {"cases": 8}
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


def test_prompt_requests_only_the_needed_model_distractors() -> None:
    prompt = build_template_prompt(
        TemplateAuthoringRequest(
            topic="arithmetic", difficulty="beginner", num_distractors=2
        )
    )

    assert "exactly 2 distractor candidates" in prompt
    assert "will select 2" in prompt
    assert "local application adds mechanical fallback candidates" in prompt


def test_two_model_distractors_are_enough_when_two_are_requested() -> None:
    canonical = template()
    payload = canonical.model_dump(
        include={
            "code",
            "entry_function",
            "parameters",
            "answer_expression",
            "distractors",
        }
    )
    payload["distractors"] = payload["distractors"][:2]
    proposal = CodeTemplateProposal.model_validate(payload)

    normalized = normalize_code_template_proposal(
        TemplateAuthoringRequest(
            topic="arithmetic", difficulty="beginner", num_distractors=2
        ),
        proposal,
    )

    assert len(normalized.distractors) == 5


def test_prompt_serializes_the_exact_capability_contract() -> None:
    prompt = build_template_prompt(
        TemplateAuthoringRequest(topic="conditionals", difficulty="advanced")
    )

    assert '"accepted_parameter_shapes"' in prompt
    assert '"kinds": [' in prompt
    assert '"integer"' in prompt
    assert '"boolean"' in prompt
    assert '"required_code_features"' in prompt
    assert '"answer_kind": "integer"' in prompt
    assert '"nested_conditional"' in prompt
    assert "Do not add parameters" in prompt


def test_list_result_prompt_declares_the_answer_kind() -> None:
    prompt = build_template_prompt(
        TemplateAuthoringRequest(topic="lists", difficulty="intermediate")
    )

    assert '"answer_kind": "integer_list"' in prompt


def test_reason_placeholders_forbid_embedded_expressions() -> None:
    prompt = build_template_prompt(
        TemplateAuthoringRequest(topic="loops", difficulty="beginner")
    )

    assert "never put expressions such as `{n-1}` inside braces" in prompt


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


def test_proposal_normalization_derives_stable_local_fields() -> None:
    canonical = template()
    proposal = CodeTemplateProposal.model_validate(
        canonical.model_dump(
            include={
                "code",
                "entry_function",
                "parameters",
                "answer_expression",
                "distractors",
            }
        )
    )
    request = TemplateAuthoringRequest(topic="arithmetic", difficulty="beginner")

    first = normalize_code_template_proposal(request, proposal)
    second = normalize_code_template_proposal(request, proposal)

    assert first == second
    assert first.template_id.startswith("arithmetic.beginner.")
    assert first.version == 1
    assert first.answer_target == "return_value"
    assert first.question_type == "mcq"
    assert first.question_template == (
        "What value does calculate({a}, {b}, {c}) return?"
    )
    assert len(first.distractors) == 6
    assert first.distractors[-1].expression == "(a + b - c) + 3"


def test_list_proposal_normalization_adds_list_shaped_fallbacks() -> None:
    canonical = CodeQuestionTemplate.model_validate_json(
        (TEMPLATE_DIR / "list_sorted.json").read_text()
    )
    proposal = CodeTemplateProposal.model_validate(
        canonical.model_dump(
            include={
                "code",
                "entry_function",
                "parameters",
                "answer_expression",
                "distractors",
            }
        )
    )

    result = normalize_code_template_proposal(
        TemplateAuthoringRequest(topic="lists", difficulty="intermediate"), proposal
    )

    assert result.distractors[-3].expression == "(sorted(values)) + [0]"
    assert result.distractors[-1].expression == "(sorted(values)) + [2]"


def test_profile_rejects_the_wrong_answer_kind() -> None:
    value = template(
        code="def calculate(a, b, c):\n    return (a + b) > c",
        answer_expression="(a + b) > c",
    )

    with pytest.raises(TemplateValidationError) as error:
        TemplateValidator(executor=TrustedBatchExecutor()).validate(value)

    assert error.value.code == "ANSWER_KIND_MISMATCH"
    assert error.value.field == "answer_expression"
    assert error.value.inputs is not None


def test_answer_kind_error_precedes_distractor_selection() -> None:
    value = template(
        code="def calculate(a, b, c):\n    return (a + b) > c",
        answer_expression="(a + b) > c",
    )

    with pytest.raises(TemplateValidationError) as error:
        TemplateValidator(executor=TrustedBatchExecutor()).validate(
            value, num_distractors=3
        )

    assert error.value.code == "ANSWER_KIND_MISMATCH"


def test_profile_features_must_be_reachable_from_the_entry_function() -> None:
    value = CodeQuestionTemplate.model_validate_json(
        (TEMPLATE_DIR / "list_sum.json").read_text()
    ).model_copy(
        update={
            "code": (
                "def unused(values):\n"
                "    return sum(values)\n\n"
                "def total(values):\n"
                "    result = 0\n"
                "    for value in values:\n"
                "        result += value\n"
                "    return result"
            )
        }
    )

    with pytest.raises(TemplateValidationError) as error:
        TemplateValidator(executor=TrustedBatchExecutor()).validate(value)

    assert error.value.code == "PROFILE_MISMATCH"
    assert "list_aggregate" in str(error.value)


def test_rejects_an_unused_entry_parameter_before_execution() -> None:
    value = template(
        code="def calculate(a, b, c):\n    return a + b",
        answer_expression="a + b",
    )

    with pytest.raises(TemplateValidationError) as error:
        TemplateValidator(executor=ArithmeticExecutor()).validate(value)

    assert error.value.code == "UNUSED_PARAMETER"
    assert error.value.field == "parameters"
    assert "c" in str(error.value)


def test_loop_profile_enforces_its_exact_range_structure() -> None:
    value = CodeQuestionTemplate.model_validate_json(
        (TEMPLATE_DIR / "loop_iterations.json").read_text()
    ).model_copy(
        update={
            "code": (
                "def accumulate(n):\n"
                "    total = 0\n"
                "    for i in range(n + 1):\n"
                "        total += i\n"
                "    return total"
            )
        }
    )

    with pytest.raises(TemplateValidationError) as error:
        TemplateValidator(executor=TrustedBatchExecutor()).validate(value)

    assert error.value.code == "PROFILE_MISMATCH"
    assert error.value.field == "code"
    assert "range(n)" in str(error.value)


def test_function_profile_enforces_its_exact_call_count_expression() -> None:
    value = CodeQuestionTemplate.model_validate_json(
        (TEMPLATE_DIR / "function_loop_helper.json").read_text()
    ).model_copy(update={"answer_expression": "n + 3"})

    with pytest.raises(TemplateValidationError) as error:
        TemplateValidator(executor=TrustedBatchExecutor()).validate(value)

    assert error.value.code == "PROFILE_MISMATCH"
    assert error.value.field == "answer_expression"
    assert "n + 2" in str(error.value)


def test_list_profile_enforces_the_literal_beginner_operation() -> None:
    value = CodeQuestionTemplate.model_validate_json(
        (TEMPLATE_DIR / "list_sum.json").read_text()
    ).model_copy(update={"code": "def total(values):\n    return max(values)"})

    with pytest.raises(TemplateValidationError) as error:
        TemplateValidator(executor=TrustedBatchExecutor()).validate(value)

    assert error.value.code == "PROFILE_MISMATCH"
    assert error.value.field == "code"
    assert "return sum(values)" in str(error.value)


def test_conditional_profile_enforces_its_teaching_values() -> None:
    data = json.loads((TEMPLATE_DIR / "conditional_string.json").read_text())
    data["parameters"][0]["values"] = ["first", "second", "other"]
    value = CodeQuestionTemplate.model_validate(data)

    with pytest.raises(TemplateValidationError) as error:
        TemplateValidator(executor=TrustedBatchExecutor()).validate(value)

    assert error.value.code == "PROFILE_MISMATCH"
    assert error.value.field == "parameters"
    assert "express" in str(error.value)


def test_conditional_profile_enforces_sequential_comparisons() -> None:
    value = CodeQuestionTemplate.model_validate_json(
        (TEMPLATE_DIR / "conditional_string.json").read_text()
    ).model_copy(
        update={
            "code": (
                "def route(mode):\n"
                "    if mode == 'standard':\n"
                "        return 2\n"
                "    if mode == 'express':\n"
                "        return 1\n"
                "    return 3"
            )
        }
    )

    with pytest.raises(TemplateValidationError) as error:
        TemplateValidator(executor=TrustedBatchExecutor()).validate(value)

    assert error.value.code == "PROFILE_MISMATCH"
    assert error.value.field == "code"


def test_proposal_normalization_derives_target_aware_loop_wording() -> None:
    canonical = CodeQuestionTemplate.model_validate_json(
        (TEMPLATE_DIR / "loop_iterations.json").read_text()
    )
    proposal = CodeTemplateProposal.model_validate(
        canonical.model_dump(
            include={
                "code",
                "entry_function",
                "parameters",
                "answer_expression",
                "distractors",
            }
        )
    )

    result = normalize_code_template_proposal(
        TemplateAuthoringRequest(topic="loops", difficulty="beginner"), proposal
    )

    assert result.question_template == (
        "How many total loop-body iterations occur when accumulate({n}) runs?"
    )


def test_proposal_parser_rejects_locally_owned_fields() -> None:
    canonical = template().model_dump(mode="json")

    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        parse_code_template_proposal(json.dumps(canonical))


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
    assert "middle helper calls the leaf" in prompts[("functions", "advanced")]
    assert "`3 * n + 2`" in prompts[("functions", "advanced")]
    assert "body must be exactly `return sum(values)`" in prompts[("lists", "beginner")]
    assert '"required_parameter_values"' in prompts[("conditionals", "intermediate")]
    assert (
        '1 if mode == \\"express\\" else 2' in prompts[("conditionals", "intermediate")]
    )
    assert "1 if override else" in prompts[("conditionals", "advanced")]
    assert (
        "body must be exactly `return sorted(values)`"
        in prompts[("lists", "intermediate")]
    )


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


def test_safe_expression_preserves_python_short_circuit_semantics() -> None:
    assert SafeExpression("0 and (1 / 0)", ()).evaluate({}) == 0
    assert SafeExpression("'ready' or (1 / 0)", ()).evaluate({}) == "ready"


def test_safe_expression_rejects_large_integer_intermediates() -> None:
    with pytest.raises(TemplateValidationError, match="integer result exceeds"):
        SafeExpression("(10_000 ** 8) ** 2", ()).evaluate({})


def test_safe_expression_integer_limit_has_an_explicit_boundary() -> None:
    assert SafeExpression("10_000 * 10_000 * 10", ()).evaluate({}) == 1_000_000_000

    with pytest.raises(TemplateValidationError, match="integer result exceeds"):
        SafeExpression("10_000 * 10_000 * 10 + 1", ()).evaluate({})


def test_safe_expression_rejects_large_sequence_before_allocation() -> None:
    expression = SafeExpression("label * count", ("label", "count"))

    with pytest.raises(TemplateValidationError, match="sequence result exceeds"):
        expression.evaluate({"label": "x", "count": 1_000_000_000})


def test_safe_expression_sequence_limit_has_an_explicit_boundary() -> None:
    result = SafeExpression("label * 100", ("label",)).evaluate({"label": "x"})
    assert len(result) == 100

    with pytest.raises(TemplateValidationError, match="sequence result exceeds"):
        SafeExpression("label * 101", ("label",)).evaluate({"label": "x"})


def test_safe_expression_rejects_nested_sequence_amplification() -> None:
    expression = SafeExpression("[[[0] * 10] * 10] * 10", ())

    with pytest.raises(TemplateValidationError, match="cumulative size limit"):
        expression.evaluate({})


def test_safe_expression_rejects_string_formatting_before_allocation() -> None:
    with pytest.raises(TemplateValidationError, match="string formatting"):
        SafeExpression("'%1000000000s' % label", ("label",)).evaluate({"label": "x"})


def test_safe_expression_rejects_oversized_source_and_ast() -> None:
    with pytest.raises(TemplateValidationError, match="exceeds 500 characters"):
        SafeExpression("1" * 501, ())

    many_nodes = " + ".join("1" for _ in range(51))
    with pytest.raises(TemplateValidationError, match="exceeds 100 syntax nodes"):
        SafeExpression(many_nodes, ())


def test_list_topic_requests_an_integer_list_template() -> None:
    prompt = build_template_prompt(
        TemplateAuthoringRequest(topic="lists", difficulty="beginner")
    )

    assert "integer_list parameter named values" in prompt
    assert "sum(values)" in prompt


def test_rejects_a_distractor_that_is_correct_for_any_case() -> None:
    value = template().model_dump()
    value["distractors"][0]["expression"] = "a + b - c"

    with pytest.raises(TemplateValidationError, match="equals the answer") as error:
        TemplateValidator(executor=ArithmeticExecutor()).validate(
            CodeQuestionTemplate.model_validate(value)
        )

    assert error.value.code == "DISTRACTOR_EQUALS_ANSWER"
    assert error.value.field == "distractors.0"
    assert error.value.inputs is not None


def test_distractor_selection_is_not_dependent_on_greedy_candidate_order() -> None:
    value = template().model_dump(mode="json")
    value["parameters"] = [
        {"name": "a", "kind": "integer", "values": [1, 2]},
        {"name": "b", "kind": "integer", "values": [3, 4]},
    ]
    value["code"] = "def calculate(a, b):\n    return a + b + 10"
    value["question_template"] = "What does calculate({a}, {b}) return?"
    value["answer_expression"] = "a + b + 10"
    value["distractors"] = [
        {"expression": "0", "reason_template": "Uses zero."},
        {"expression": "a - 1", "reason_template": "Subtracts one."},
        {"expression": "2 - a", "reason_template": "Reverses subtraction."},
    ]
    item = CodeQuestionTemplate.model_validate(value)

    class AddTenExecutor:
        def execute_batch(self, code, entry_function, inputs, *, timeout_seconds):
            return [
                ExecutionResult(ok=True, answer=case["a"] + case["b"] + 10)
                for case in inputs
            ]

    approved = TemplateValidator(executor=AddTenExecutor()).validate(
        item, num_distractors=2
    )

    assert [recipe.expression for recipe in approved.template.distractors] == [
        "a - 1",
        "2 - a",
    ]


def test_candidate_selection_reports_when_too_few_are_globally_valid() -> None:
    data = template().model_dump()
    for distractor in data["distractors"]:
        distractor["expression"] = "a + b - c"
    item = CodeQuestionTemplate.model_validate(data)

    with pytest.raises(TemplateValidationError, match="no set of 3") as error:
        TemplateValidator(executor=ArithmeticExecutor()).validate(
            item, num_distractors=3
        )

    assert error.value.code == "DISTRACTOR_SELECTION_FAILED"
    assert error.value.field == "distractors"


def test_rejects_profile_answer_target_mismatch_before_execution() -> None:
    item = template(answer_target="loop_iterations")

    with pytest.raises(TemplateValidationError, match="requires answer_target"):
        TemplateValidator(executor=ArithmeticExecutor()).validate(item)


def test_rejects_profile_parameter_shape_mismatch_before_execution() -> None:
    data = template().model_dump()
    data["parameters"][2] = {
        "name": "c",
        "kind": "boolean",
        "values": [False, True],
    }

    with pytest.raises(TemplateValidationError, match="parameter profile requires"):
        TemplateValidator(executor=ArithmeticExecutor()).validate(
            CodeQuestionTemplate.model_validate(data)
        )


def test_rejects_missing_profile_code_feature_before_execution() -> None:
    item = template(code="def calculate(a, b, c):\n    return a")

    with pytest.raises(
        TemplateValidationError, match="missing required features"
    ) as error:
        TemplateValidator(executor=ArithmeticExecutor()).validate(item)

    payload = error.value.as_dict()
    assert {key: payload[key] for key in ("code", "message", "field", "inputs")} == {
        "code": "PROFILE_MISMATCH",
        "message": (
            "arithmetic/beginner code is missing required features: arithmetic"
        ),
        "field": "code",
        "inputs": None,
    }
    assert payload["evidence"][0]["check"] == "template_structure"
    assert payload["evidence"][0]["status"] == "failed"


def test_rejects_non_positive_profile_integer_domain_before_execution() -> None:
    path = TEMPLATE_DIR / "loop_iterations.json"
    data = json.loads(path.read_text())
    data["parameters"][0]["values"] = [0, 2]

    with pytest.raises(TemplateValidationError, match="requires positive integer"):
        TemplateValidator(executor=TrustedBatchExecutor()).validate(
            CodeQuestionTemplate.model_validate(data)
        )


def test_rejects_non_allowlisted_expression_calls() -> None:
    with pytest.raises(TemplateValidationError, match="unsupported expression syntax"):
        SafeExpression("open(a)", ("a",))


def test_answer_mismatch_reports_the_failing_inputs() -> None:
    item = template(answer_expression="a + b + c")

    with pytest.raises(
        TemplateValidationError, match="does not match the execution target"
    ) as error:
        TemplateValidator(executor=ArithmeticExecutor()).validate(item)

    assert error.value.code == "ANSWER_MISMATCH"
    assert error.value.field == "answer_expression"
    assert error.value.inputs == {"a": 2, "b": 5, "c": 1}
    assert error.value.evidence[-1].check == "answer_consistency"
    assert error.value.evidence[-1].status == "failed"
    assert error.value.evidence[-1].issues[0].code == "ANSWER_MISMATCH"
    assert error.value.evidence[-1].details["failing_inputs"] == error.value.inputs


def test_execution_failure_preserves_executor_code_in_evidence() -> None:
    class FailingExecutor:
        def execute_batch(self, code, entry_function, inputs, *, timeout_seconds):
            return [
                ExecutionResult(
                    ok=False,
                    error_code="EXECUTION_TIMEOUT",
                    error_message="Execution exceeded the time limit",
                )
                for _ in inputs
            ]

    with pytest.raises(TemplateValidationError) as error:
        TemplateValidator(executor=FailingExecutor()).validate(template())

    assert error.value.code == "EXECUTION_TIMEOUT"
    assert error.value.evidence[-1].check == "sandboxed_execution"
    assert error.value.evidence[-1].status == "failed"
    assert error.value.evidence[-1].issues[0].code == "EXECUTION_TIMEOUT"


def test_approved_template_rejects_failed_validation_evidence() -> None:
    approved = TemplateValidator(executor=ArithmeticExecutor()).validate(template())
    payload = approved.model_dump(mode="json")
    payload["validation"]["evidence"][0]["status"] = "failed"

    with pytest.raises(ValueError, match="require passing validation evidence"):
        type(approved).model_validate(payload)


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
