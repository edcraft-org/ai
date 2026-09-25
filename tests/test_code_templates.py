import ast
import json
from pathlib import Path
from typing import Any

import pytest

from edcraft_validator.application.template_workflow import TemplateApplication
from edcraft_validator.domains.code.candidate_builder import build_code_candidate
from edcraft_validator.domains.code.code_domain import CodeDomain
from edcraft_validator.domains.code.code_schemas import (
    CodeTemplateCandidate,
    CodeTemplateProposal,
    CodeTemplateRequest,
    FiniteParameter,
    TemplateValidationError,
    parse_code_template_candidate,
    parse_code_template_proposal,
)
from edcraft_validator.domains.code.code_types import CODE_DIFFICULTIES, CODE_TOPICS
from edcraft_validator.domains.code.profiles import (
    CODE_TEMPLATE_PROFILES,
    code_template_profile,
)
from edcraft_validator.domains.code.prompt_builder import build_template_prompt
from edcraft_validator.domains.code.question_generator import generate_code_question
from edcraft_validator.domains.code.safe_expressions import SafeExpression
from edcraft_validator.tools.python_execution import ExecutionResult
from edcraft_validator.tools.python_worker import execute_request
from edcraft_validator.validation.check_runner import ValidationPipeline

TEMPLATE_DIR = Path(__file__).parents[1] / "examples" / "templates"
TEMPLATE_PATHS = sorted(TEMPLATE_DIR.glob("*.json"))


def template(**changes: Any) -> CodeTemplateCandidate:
    data = {
        "template_id": "arithmetic.linear_sum",
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
    return CodeTemplateCandidate.model_validate(data)


def relaxed_profile_template(
    filename: str,
    *,
    code: str,
    answer_expression: str,
    parameter_values: list[list[Any]] | None = None,
) -> CodeTemplateCandidate:
    data = json.loads((TEMPLATE_DIR / filename).read_text())
    data["code"] = code
    data["answer_expression"] = answer_expression
    if parameter_values is not None:
        for parameter, values in zip(data["parameters"], parameter_values, strict=True):
            parameter["values"] = values

    answer_kind = code_template_profile(data["topic"], data["difficulty"]).answer_kind
    expressions = (
        ["[901]", "[902]", "[903]"]
        if answer_kind == "integer_list"
        else ["901", "902", "903"]
    )
    data["distractors"] = [
        {
            "expression": expression,
            "reason_template": "Uses an unrelated fixed result.",
        }
        for expression in expressions
    ]
    return CodeTemplateCandidate.model_validate(data)


class ArithmeticExecutor:
    def __init__(self) -> None:
        self.calls: list[dict[str, int]] = []
        self.batch_calls = 0

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
    application = TemplateApplication()
    domain = CodeDomain(execution_tool=executor)
    validated = application.validate_template(template(), domain=domain)

    assert validated.validation.cases_validated == 8
    assert validated.validation.validator_version == "code-template-validator-v3"
    assert validated.template.answer_expression is None
    assert "version" not in validated.template.model_dump()
    assert "template_sha256" not in validated.validation.model_dump()
    assert "validated_cases_sha256" not in validated.validation.model_dump()
    assert len(validated.validation.validated_cases) == 8
    assert [item.check for item in validated.validation.evidence] == [
        "template_structure",
        "expression_safety",
        "answer_domain",
        "code_execution",
        "canonical_answers",
        "distractor_consistency",
        "template_rendering",
    ]
    assert all(item.status == "passed" for item in validated.validation.evidence)
    assert validated.validation.evidence[2].assurance == "exhaustive"
    assert validated.validation.evidence[2].details == {"cases": 8}
    assert executor.batch_calls == 1
    assert len(executor.calls) == 8

    first = application.generate_question(validated, domain=domain, seed=42)
    second = application.generate_question(validated, domain=domain, seed=42)

    assert first == second
    assert len(executor.calls) == 8
    assert "template_version" not in first.model_dump()
    assert "template_sha256" not in first.model_dump()
    assert first.question.proposed_answer == (
        first.parameters["a"] + first.parameters["b"] - first.parameters["c"]
    )
    assert first.question.question.startswith("What does calculate(")


def test_supports_loop_iteration_questions() -> None:
    loop_template = CodeTemplateCandidate.model_validate(
        {
            "template_id": "loops.iteration_count",
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

    validated = TemplateApplication().validate_template(
        loop_template, domain=CodeDomain(execution_tool=LoopExecutor())
    )
    instance = generate_code_question(validated, seed=3)

    assert validated.validation.cases_validated == 2
    assert instance.question.answer_target == "loop_iterations"
    assert instance.question.proposed_answer == instance.parameters["n"]


def test_free_form_prompt_preserves_requested_topic_and_difficulty() -> None:
    prompt = build_template_prompt(
        CodeTemplateRequest(
            prompt="Create a graph traversal question using a loop",
            difficulty="beginner",
        )
    )

    assert "Create a graph traversal question using a loop" in prompt
    assert "Requested difficulty: beginner" in prompt
    assert "catalogue topic" in prompt


def test_prompt_gives_the_model_control_of_question_and_entry_function() -> None:
    prompt = build_template_prompt(
        CodeTemplateRequest(
            prompt="Create an arithmetic question", difficulty="beginner"
        )
    )

    assert "Choose the entry function" in prompt
    assert "learner-facing question template" in prompt
    assert "one supported answer_target" in prompt
    assert "exact entry_function identifier" in prompt
    assert "calculate_expression({a}, {b}, {c})" in prompt
    assert "do not replace the call" in prompt


def test_prompt_requests_only_the_needed_model_distractors() -> None:
    prompt = build_template_prompt(
        CodeTemplateRequest(
            prompt="Create an arithmetic question",
            difficulty="beginner",
            num_distractors=2,
        )
    )

    assert "at least 2 distractor candidates" in prompt


def test_two_model_distractors_are_enough_when_two_are_requested() -> None:
    canonical = template()
    payload = canonical.model_dump(
        include={
            "question_template",
            "code",
            "entry_function",
            "parameters",
            "answer_target",
            "answer_expression",
            "distractors",
        }
    )
    payload["distractors"] = payload["distractors"][:2]
    proposal = CodeTemplateProposal.model_validate(payload)

    built = build_code_candidate(
        CodeTemplateRequest(
            prompt="Create an arithmetic question",
            difficulty="beginner",
            num_distractors=2,
        ),
        proposal,
    )

    assert len(built.distractors) == 2


def test_candidate_builder_defers_missing_distractors_to_validation_fallbacks() -> None:
    canonical = template()
    payload = canonical.model_dump(
        include={
            "question_template",
            "code",
            "entry_function",
            "parameters",
            "answer_target",
            "answer_expression",
            "distractors",
        }
    )
    payload["distractors"] = payload["distractors"][:2]
    proposal = CodeTemplateProposal.model_validate(payload)

    built = build_code_candidate(
        CodeTemplateRequest(
            prompt="Create an arithmetic question",
            difficulty="beginner",
            num_distractors=3,
        ),
        proposal,
    )

    assert built.distractors == proposal.distractors
    domain = CodeDomain(execution_tool=ArithmeticExecutor())
    plan = domain.prepare_validation(
        built,
        request=CodeTemplateRequest(
            prompt="Create an arithmetic question",
            difficulty="beginner",
            num_distractors=3,
        ),
    )
    report = ValidationPipeline().validate(
        context=plan.context, checks=plan.checks, policy=plan.policy
    )
    report.raise_for_failure()
    validated = domain.finalize_template(plan.context, report)
    assert [recipe.expression for recipe in validated.template.distractors] == [
        "a + b + c",
        "a - b - c",
        "(a + b - c) + 1",
    ]


def test_prompt_offers_current_validation_check_names() -> None:
    prompt = build_template_prompt(
        CodeTemplateRequest(
            prompt="Create a conditional question", difficulty="advanced"
        )
    )

    assert "template_structure" in prompt
    assert "code_execution" in prompt
    assert "do not invent names" in prompt


def test_reason_placeholders_forbid_embedded_expressions() -> None:
    prompt = build_template_prompt(
        CodeTemplateRequest(prompt="Create a loop question", difficulty="beginner")
    )

    assert "never put expressions inside braces" in prompt


@pytest.mark.parametrize("values", [[2, 2, 4], [2, 2]])
def test_provider_template_parser_rejects_duplicate_parameter_values(
    values: list[int],
) -> None:
    payload = template().model_dump(mode="json")
    payload["parameters"][0]["values"] = values

    with pytest.raises(ValueError, match="parameter values must be unique"):
        parse_code_template_candidate(json.dumps(payload))


def test_provider_proposal_parser_rejects_duplicate_parameter_values() -> None:
    payload = template().model_dump(
        mode="json",
        include={
            "question_template",
            "code",
            "entry_function",
            "parameters",
            "answer_target",
            "answer_expression",
            "distractors",
        },
    )
    payload["parameters"][0]["values"] = [2, 2]

    with pytest.raises(ValueError, match="parameter values must be unique"):
        parse_code_template_proposal(json.dumps(payload))


def test_duplicate_validation_distinguishes_booleans_from_integers() -> None:
    payload = template().model_dump(mode="json")
    payload["parameters"][0]["values"] = [2, True]

    with pytest.raises(ValueError, match="integer values must be integers"):
        parse_code_template_candidate(json.dumps(payload))


def test_template_building_derives_stable_local_fields() -> None:
    canonical = template()
    proposal = CodeTemplateProposal.model_validate(
        canonical.model_dump(
            include={
                "question_template",
                "code",
                "entry_function",
                "parameters",
                "answer_target",
                "answer_expression",
                "distractors",
            }
        )
    )
    request = CodeTemplateRequest(
        prompt="Create an arithmetic question", difficulty="beginner"
    )

    first = build_code_candidate(request, proposal)
    second = build_code_candidate(request, proposal)

    assert first == second
    assert first.template_id.startswith("code.beginner.")
    assert first.answer_target == "return_value"
    assert first.question_type == "mcq"
    assert first.question_template == ("What does calculate({a}, {b}, {c}) return?")
    assert len(first.distractors) == 3


def test_list_template_building_preserves_model_distractors() -> None:
    canonical = CodeTemplateCandidate.model_validate_json(
        (TEMPLATE_DIR / "list_sorted.json").read_text()
    )
    proposal = CodeTemplateProposal.model_validate(
        canonical.model_dump(
            include={
                "question_template",
                "code",
                "entry_function",
                "parameters",
                "answer_target",
                "answer_expression",
                "distractors",
            }
        )
    )

    result = build_code_candidate(
        CodeTemplateRequest(prompt="Create a list question", difficulty="intermediate"),
        proposal,
    )

    assert result.distractors == proposal.distractors


def test_profile_free_validation_rejects_boolean_answers() -> None:
    value = template(
        code="def calculate(a, b, c):\n    return (a + b) > c",
        answer_expression="(a + b) > c",
    )

    with pytest.raises(TemplateValidationError) as error:
        TemplateApplication().validate_template(
            value, domain=CodeDomain(execution_tool=TrustedBatchExecutor())
        )

    assert error.value.code == "ANSWER_TYPE_UNSUPPORTED"


def test_unsupported_code_is_rejected_before_execution() -> None:
    class UnexpectedExecutor:
        called = False

        def execute_batch(self, code, entry_function, inputs, *, timeout_seconds):
            self.called = True
            raise AssertionError("unsupported code must not execute")

    executor = UnexpectedExecutor()
    value = template(code="import os\n\ndef calculate(a, b, c):\n    return a + b - c")

    with pytest.raises(TemplateValidationError) as error:
        TemplateApplication().validate_template(
            value, domain=CodeDomain(execution_tool=executor)
        )

    assert error.value.code == "UNSUPPORTED_CODE"
    assert executor.called is False
    assert [item.check for item in error.value.evidence] == ["template_structure"]


def test_inconsistent_answer_types_precede_distractor_selection() -> None:
    value = template(
        answer_expression="a if a == 2 else 'four'",
    )

    with pytest.raises(TemplateValidationError) as error:
        domain = CodeDomain(execution_tool=TrustedBatchExecutor())
        plan = domain.prepare_validation(
            value,
            request=CodeTemplateRequest(
                prompt="Create an arithmetic question",
                difficulty=value.difficulty,
                num_distractors=3,
            ),
        )
        report = ValidationPipeline().validate(
            context=plan.context, checks=plan.checks, policy=plan.policy
        )
        report.raise_for_failure()
        domain.finalize_template(plan.context, report)

    assert error.value.code == "ANSWER_TYPE_INCONSISTENT"


def test_profile_features_are_not_required_for_free_form_questions() -> None:
    value = CodeTemplateCandidate.model_validate_json(
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

    validated = TemplateApplication().validate_template(
        value, domain=CodeDomain(execution_tool=TrustedBatchExecutor())
    )

    assert validated.validation.cases_validated > 0


def test_rejects_an_unused_entry_parameter_before_execution() -> None:
    executor = ArithmeticExecutor()
    value = template(
        code="def calculate(a, b, c):\n    return a + b",
        answer_expression="a + b",
    )

    with pytest.raises(TemplateValidationError) as error:
        TemplateApplication().validate_template(
            value, domain=CodeDomain(execution_tool=executor)
        )

    assert error.value.code == "UNUSED_PARAMETER"
    assert error.value.field == "parameters"
    assert "c" in str(error.value)
    assert executor.batch_calls == 0


@pytest.mark.parametrize(
    "value",
    [
        relaxed_profile_template(
            "conditional_string.json",
            code=(
                "def route(mode):\n"
                "    if mode == 'routine':\n"
                "        return 10\n"
                "    if mode == 'priority':\n"
                "        return 20\n"
                "    return 30"
            ),
            answer_expression="1 if mode == 'routine' else 2",
            parameter_values=[["priority", "routine", "deferred"]],
        ),
        relaxed_profile_template(
            "conditional_nested.json",
            code=(
                "def classify(score, override):\n"
                "    if score >= 60:\n"
                "        if override:\n"
                "            return 'fast'\n"
                "        return 'review'\n"
                "    if override:\n"
                "        return 'manual'\n"
                "    return 'low'"
            ),
            answer_expression="2",
        ),
        relaxed_profile_template(
            "loop_iterations.json",
            code=(
                "def accumulate(n):\n"
                "    total = 0\n"
                "    for i in range(n + 1):\n"
                "        total += i\n"
                "    return total"
            ),
            answer_expression="n + 1",
        ),
        relaxed_profile_template(
            "loop_sequential.json",
            code=(
                "def accumulate(n, m):\n"
                "    total = 0\n"
                "    for i in range(n + 1):\n"
                "        total += i\n"
                "    for j in range(m * 2):\n"
                "        total += j\n"
                "    return total"
            ),
            answer_expression="n + 1 + 2 * m",
        ),
        relaxed_profile_template(
            "loop_nested.json",
            code=(
                "def accumulate(n, m):\n"
                "    total = 0\n"
                "    for i in range(n + 1):\n"
                "        for j in range(m):\n"
                "            total += i + j\n"
                "    return total"
            ),
            answer_expression="(n + 1) * (m + 1)",
        ),
        relaxed_profile_template(
            "function_helper.json",
            code=(
                "def increment(value):\n"
                "    return value + 1\n\n"
                "def double_increment(value):\n"
                "    return increment(value) + 1\n\n"
                "def calculate(value):\n"
                "    return double_increment(value)"
            ),
            answer_expression="3",
        ),
        relaxed_profile_template(
            "function_loop_helper.json",
            code=(
                "def increment(value):\n"
                "    return value + 1\n\n"
                "def calculate(n):\n"
                "    total = 0\n"
                "    for i in range(n + 1):\n"
                "        total += increment(i)\n"
                "    return total"
            ),
            answer_expression="n + 3",
        ),
        relaxed_profile_template(
            "function_nested_helpers.json",
            code=(
                "def increment(value):\n"
                "    return value + 1\n\n"
                "def transform(value):\n"
                "    return increment(value)\n\n"
                "def calculate(n):\n"
                "    total = 0\n"
                "    for i in range(n + 1):\n"
                "        total += transform(i)\n"
                "    return total"
            ),
            answer_expression="2 * n + 4",
        ),
        relaxed_profile_template(
            "list_sum.json",
            code=(
                "def total(values):\n"
                "    smallest = min(values)\n"
                "    largest = max(values)\n"
                "    return smallest + largest"
            ),
            answer_expression="min(values) + max(values)",
        ),
        relaxed_profile_template(
            "list_sorted.json",
            code=(
                "def arrange(values):\n"
                "    ordered = sorted(values)\n"
                "    return ordered + [len(values)]"
            ),
            answer_expression="sorted(values) + [len(values)]",
        ),
    ],
    ids=[
        "conditional-intermediate",
        "conditional-advanced",
        "loop-beginner",
        "loop-intermediate",
        "loop-advanced",
        "function-beginner",
        "function-intermediate",
        "function-advanced",
        "list-beginner",
        "list-intermediate",
    ],
)
def test_profiles_accept_alternative_programs_and_answer_formulas(
    value: CodeTemplateCandidate,
) -> None:
    validated = TemplateApplication().validate_template(
        value, domain=CodeDomain(execution_tool=TrustedBatchExecutor())
    )

    expected_cases = 1
    for parameter in value.parameters:
        expected_cases *= len(parameter.values)
    assert validated.validation.cases_validated == expected_cases
    instance = generate_code_question(validated, seed=11)
    assert instance.question.answer_target == value.answer_target


def test_template_building_preserves_model_authored_target_and_wording() -> None:
    canonical = CodeTemplateCandidate.model_validate_json(
        (TEMPLATE_DIR / "loop_iterations.json").read_text()
    )
    proposal = CodeTemplateProposal.model_validate(
        canonical.model_dump(
            include={
                "question_template",
                "code",
                "entry_function",
                "parameters",
                "answer_target",
                "answer_expression",
                "distractors",
            }
        )
    )

    result = build_code_candidate(
        CodeTemplateRequest(prompt="Create a loop question", difficulty="beginner"),
        proposal,
    )

    assert result.question_template == (
        "How many total loop-body iterations occur when accumulate({n}) runs?"
    )


def test_proposal_parser_rejects_locally_owned_fields() -> None:
    canonical = template().model_dump(mode="json")

    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        parse_code_template_proposal(json.dumps(canonical))


def test_profiles_remain_evaluation_fixtures_not_authoring_requirements() -> None:
    assert len(CODE_TEMPLATE_PROFILES) == 15
    assert all(
        "answer_expression" not in profile.guidance
        for profile in CODE_TEMPLATE_PROFILES.values()
    )
    assert all(
        profile.required_parameter_values is None
        for profile in CODE_TEMPLATE_PROFILES.values()
    )


def test_examples_cover_every_topic_and_difficulty() -> None:
    templates = [
        CodeTemplateCandidate.model_validate_json(path.read_text())
        for path in TEMPLATE_PATHS
    ]
    actual = {(template.topic, template.difficulty) for template in templates}
    expected = {
        (topic, difficulty) for topic in CODE_TOPICS for difficulty in CODE_DIFFICULTIES
    }

    assert len(templates) == len(expected)
    assert actual == expected


def test_capability_catalog_covers_each_profile_once() -> None:
    assert len(CODE_TEMPLATE_PROFILES) == 15
    for topic in CODE_TOPICS:
        targets = {
            code_template_profile(topic, difficulty).answer_target
            for difficulty in CODE_DIFFICULTIES
        }
        assert len(targets) == 1


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


def test_safe_expression_float_limit_has_an_explicit_boundary() -> None:
    assert SafeExpression("10_000 * 10_000 * 10.0", ()).evaluate({}) == 1_000_000_000.0

    with pytest.raises(TemplateValidationError, match="float result is non-finite"):
        SafeExpression("10_000 * 10_000 * 10.0 + 0.5", ()).evaluate({})

    with pytest.raises(TemplateValidationError, match="float result is non-finite"):
        SafeExpression("value", ("value",)).evaluate({"value": float("inf")})


@pytest.mark.parametrize("source", ["2 ** -1", "2 ** 9", "2 ** 2.0", "2 ** True"])
def test_safe_expression_rejects_invalid_exponents_before_operation(
    source: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_if_called(left: Any, right: Any) -> Any:
        raise AssertionError(f"attempted exponentiation: {left} ** {right}")

    monkeypatch.setitem(SafeExpression._binary_operators, ast.Pow, fail_if_called)

    with pytest.raises(TemplateValidationError, match="exponents must be integers"):
        SafeExpression(source, ()).evaluate({})


def test_safe_expression_rejects_large_sequence_before_allocation() -> None:
    expression = SafeExpression("label * count", ("label", "count"))

    with pytest.raises(TemplateValidationError, match="sequence result exceeds"):
        expression.evaluate({"label": "x", "count": 1_000_000_000})


def test_safe_expression_checks_list_repetition_before_operation() -> None:
    class AllocationBomb(list[Any]):
        def __mul__(self, count: int) -> list[Any]:
            raise AssertionError(f"attempted allocation with count {count}")

    expression = SafeExpression("items * count", ("items", "count"))

    with pytest.raises(TemplateValidationError, match="cumulative size limit"):
        expression.evaluate({"items": AllocationBomb([[0] * 100]), "count": 10})


def test_safe_expression_sequence_limit_has_an_explicit_boundary() -> None:
    result = SafeExpression("label * 100", ("label",)).evaluate({"label": "x"})
    assert len(result) == 100

    with pytest.raises(TemplateValidationError, match="sequence result exceeds"):
        SafeExpression("label * 101", ("label",)).evaluate({"label": "x"})


def test_safe_expression_rejects_nested_sequence_amplification() -> None:
    expression = SafeExpression("[[[0] * 10] * 10] * 10", ())

    with pytest.raises(TemplateValidationError, match="cumulative size limit"):
        expression.evaluate({})


def test_safe_expression_cumulative_size_includes_all_nested_values() -> None:
    expression = SafeExpression("items", ("items",))
    at_limit = [[0] * 100 for _ in range(9)] + [[0] * 89]
    over_limit = [*at_limit[:-1], [0] * 90]

    assert expression.evaluate({"items": at_limit}) == at_limit
    with pytest.raises(TemplateValidationError, match="cumulative size limit"):
        expression.evaluate({"items": over_limit})


def test_safe_expression_enforces_syntax_and_value_depth_limits() -> None:
    too_deep_source = "-(" * 21 + "1" + ")" * 21
    with pytest.raises(TemplateValidationError, match="too deeply nested"):
        SafeExpression(too_deep_source, ())

    expression = SafeExpression("value", ("value",))
    at_limit: Any = 0
    for _ in range(20):
        at_limit = [at_limit]

    assert expression.evaluate({"value": at_limit}) == at_limit
    with pytest.raises(TemplateValidationError, match="exceeds nesting depth"):
        expression.evaluate({"value": [at_limit]})


def test_safe_expression_normalizes_runtime_errors() -> None:
    with pytest.raises(
        TemplateValidationError, match=r"expression '1 / 0' failed.*division by zero"
    ) as error:
        SafeExpression("1 / 0", ()).evaluate({})

    assert isinstance(error.value.__cause__, ZeroDivisionError)


def test_safe_expression_rejects_string_formatting_before_allocation() -> None:
    with pytest.raises(TemplateValidationError, match="string formatting"):
        SafeExpression("'%1000000000s' % label", ("label",)).evaluate({"label": "x"})


def test_safe_expression_rejects_oversized_source_and_ast() -> None:
    with pytest.raises(TemplateValidationError, match="exceeds 500 characters"):
        SafeExpression("1" * 501, ())

    many_nodes = " + ".join("1" for _ in range(51))
    with pytest.raises(TemplateValidationError, match="exceeds 100 syntax nodes"):
        SafeExpression(many_nodes, ())


def test_rejects_a_distractor_that_is_correct_for_any_case() -> None:
    value = template().model_dump()
    value["distractors"][0]["expression"] = "a + b - c"

    with pytest.raises(TemplateValidationError, match="equals the answer") as error:
        TemplateApplication().validate_template(
            CodeTemplateCandidate.model_validate(value),
            domain=CodeDomain(execution_tool=ArithmeticExecutor()),
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
    item = CodeTemplateCandidate.model_validate(value)

    class AddTenExecutor:
        def execute_batch(self, code, entry_function, inputs, *, timeout_seconds):
            return [
                ExecutionResult(ok=True, answer=case["a"] + case["b"] + 10)
                for case in inputs
            ]

    domain = CodeDomain(execution_tool=AddTenExecutor())
    plan = domain.prepare_validation(
        item,
        request=CodeTemplateRequest(
            prompt="Create an arithmetic question",
            difficulty=item.difficulty,
            num_distractors=2,
        ),
    )
    report = ValidationPipeline().validate(
        context=plan.context, checks=plan.checks, policy=plan.policy
    )
    report.raise_for_failure()
    validated = domain.finalize_template(plan.context, report)

    assert [recipe.expression for recipe in validated.template.distractors] == [
        "a - 1",
        "2 - a",
    ]


def test_authoring_plan_evaluates_each_candidate_once_per_case(monkeypatch) -> None:
    value = template().model_dump(mode="json")
    value["distractors"] = [
        {"expression": "0", "reason_template": "Uses zero."},
        {"expression": "a + b + c", "reason_template": "Adds c."},
        {"expression": "a - b - c", "reason_template": "Subtracts b."},
    ]
    item = CodeTemplateCandidate.model_validate(value)
    parse_counts: dict[str, int] = {}
    evaluation_counts: dict[tuple[str, tuple[tuple[str, int], ...]], int] = {}
    original_init = SafeExpression.__init__
    original_evaluate = SafeExpression.evaluate

    def counting_init(self, source, names):
        parse_counts[source] = parse_counts.get(source, 0) + 1
        original_init(self, source, names)

    def counting_evaluate(self, values):
        key = (self.source, tuple(sorted(values.items())))
        evaluation_counts[key] = evaluation_counts.get(key, 0) + 1
        return original_evaluate(self, values)

    monkeypatch.setattr(SafeExpression, "__init__", counting_init)
    monkeypatch.setattr(SafeExpression, "evaluate", counting_evaluate)

    domain = CodeDomain(execution_tool=ArithmeticExecutor())
    plan = domain.prepare_validation(
        item,
        request=CodeTemplateRequest(
            prompt="Create an arithmetic question",
            difficulty=item.difficulty,
            num_distractors=2,
        ),
    )
    report = ValidationPipeline().validate(
        context=plan.context, checks=plan.checks, policy=plan.policy
    )
    report.raise_for_failure()
    domain.finalize_template(plan.context, report)

    sources = {
        item.answer_expression,
        *(candidate.expression for candidate in item.distractors),
    }
    assert parse_counts == {source: 1 for source in sources}
    assert {source for source, _ in evaluation_counts} == sources
    assert len(evaluation_counts) == len(sources) * 8
    assert set(evaluation_counts.values()) == {1}


def test_candidate_selection_recovers_from_pairwise_collisions_with_fallbacks() -> None:
    value = template().model_dump(mode="json")
    value["distractors"] = [
        {"expression": "0", "reason_template": "Uses zero."},
        {"expression": "a - 2", "reason_template": "Offsets a."},
        {
            "expression": "0 if a == 4 else b - 5",
            "reason_template": "Mixes parameter offsets.",
        },
    ]
    item = CodeTemplateCandidate.model_validate(value)

    domain = CodeDomain(execution_tool=ArithmeticExecutor())
    plan = domain.prepare_validation(
        item,
        request=CodeTemplateRequest(
            prompt="Create an arithmetic question",
            difficulty=item.difficulty,
            num_distractors=2,
        ),
    )
    report = ValidationPipeline().validate(
        context=plan.context, checks=plan.checks, policy=plan.policy
    )
    report.raise_for_failure()
    validated = domain.finalize_template(plan.context, report)

    assert [recipe.expression for recipe in validated.template.distractors] == [
        "0",
        "(a + b - c) + 1",
    ]
    selection = next(
        evidence
        for evidence in validated.validation.evidence
        if evidence.check == "distractor_selection"
    )
    assert selection.details["fallbacks_added"] == 2


def test_selection_replaces_invalid_model_distractors_with_fallbacks() -> None:
    data = template().model_dump()
    for distractor in data["distractors"]:
        distractor["expression"] = "a + b - c"
    item = CodeTemplateCandidate.model_validate(data)

    domain = CodeDomain(execution_tool=ArithmeticExecutor())
    plan = domain.prepare_validation(
        item,
        request=CodeTemplateRequest(
            prompt="Create an arithmetic question",
            difficulty=item.difficulty,
            num_distractors=3,
        ),
    )
    report = ValidationPipeline().validate(
        context=plan.context, checks=plan.checks, policy=plan.policy
    )
    report.raise_for_failure()
    validated = domain.finalize_template(plan.context, report)

    assert [recipe.expression for recipe in validated.template.distractors] == [
        "(a + b - c) + 1",
        "(a + b - c) - 1",
        "(a + b - c) + 2",
    ]


@pytest.mark.parametrize(
    ("parameter", "expected_fallbacks"),
    [
        (
            {"name": "text", "kind": "string", "values": ["ab", "xy"]},
            ["(text) + '?'", "(text) + '!'", "(text) + 'x'"],
        ),
        (
            {
                "name": "values",
                "kind": "integer_list",
                "values": [[1], [2, 3]],
            },
            ["(values) + [0]", "(values) + [1]", "(values) + [-1]"],
        ),
    ],
)
def test_fallback_distractors_cover_non_numeric_answers(
    parameter: dict[str, Any], expected_fallbacks: list[str]
) -> None:
    name = parameter["name"]
    item = CodeTemplateCandidate.model_validate(
        {
            "template_id": f"fallback.{name}",
            "difficulty": "beginner",
            "code": f"def identity({name}):\n    return {name}",
            "entry_function": "identity",
            "parameters": [parameter],
            "question_template": f"What does identity({{{name}}}) return?",
            "answer_target": "return_value",
            "answer_expression": name,
            "distractors": [
                {
                    "expression": name,
                    "reason_template": "Repeats the answer.",
                }
                for _ in range(3)
            ],
            "question_type": "mcq",
        }
    )
    domain = CodeDomain(execution_tool=TrustedBatchExecutor())
    plan = domain.prepare_validation(
        item,
        request=CodeTemplateRequest(
            prompt="Create an identity question",
            difficulty="beginner",
            num_distractors=3,
        ),
    )
    report = ValidationPipeline().validate(
        context=plan.context, checks=plan.checks, policy=plan.policy
    )
    report.raise_for_failure()
    validated = domain.finalize_template(plan.context, report)

    assert [
        recipe.expression for recipe in validated.template.distractors
    ] == expected_fallbacks


def test_rejects_non_allowlisted_expression_calls() -> None:
    with pytest.raises(TemplateValidationError, match="unsupported expression syntax"):
        SafeExpression("open(a)", ("a",))


def test_corrects_answer_and_promotes_proposal_to_distractor() -> None:
    data = template(answer_expression="a + b - c - 1").model_dump()
    data["distractors"] = [
        {
            "expression": "a + b - c",
            "reason_template": "Repeats the actual answer.",
        },
        {"expression": "a - b - c", "reason_template": "Subtracts b."},
        {"expression": "a + b", "reason_template": "Omits c."},
    ]
    item = CodeTemplateCandidate.model_validate(data)

    validated = TemplateApplication().validate_template(
        item, domain=CodeDomain(execution_tool=ArithmeticExecutor())
    )
    instance = generate_code_question(validated, seed=1)

    assert validated.template.answer_expression is None
    assert validated.validation.evidence[4].check == "canonical_answers"
    assert validated.validation.evidence[4].details == {
        "cases": 8,
        "source": "code_execution",
        "corrected_cases": 8,
        "proposal_matched": False,
    }
    assert [recipe.expression for recipe in validated.template.distractors] == [
        "a + b - c - 1",
        "a - b - c",
        "a + b",
    ]
    assert instance.question.proposed_answer == (
        instance.parameters["a"] + instance.parameters["b"] - instance.parameters["c"]
    )
    assert instance.question.proposed_answer - 1 in instance.question.distractors


def test_answer_correction_still_rejects_insufficient_valid_distractors() -> None:
    data = template(answer_expression="a + b - c - 1").model_dump()
    data["distractors"] = [
        {
            "expression": "a + b - c",
            "reason_template": "Repeats the actual answer.",
        }
        for _ in range(3)
    ]
    item = CodeTemplateCandidate.model_validate(data)

    with pytest.raises(TemplateValidationError) as error:
        TemplateApplication().validate_template(
            item, domain=CodeDomain(execution_tool=ArithmeticExecutor())
        )

    assert error.value.code == "DISTRACTOR_SELECTION_FAILED"


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
        TemplateApplication().validate_template(
            template(), domain=CodeDomain(execution_tool=FailingExecutor())
        )

    assert error.value.code == "EXECUTION_TIMEOUT"
    assert error.value.evidence[-1].check == "code_execution"
    assert error.value.evidence[-1].status == "incomplete"
    assert error.value.evidence[-1].issues[0].code == "EXECUTION_TIMEOUT"


def test_validated_template_rejects_failed_validation_evidence() -> None:
    validated = TemplateApplication().validate_template(
        template(), domain=CodeDomain(execution_tool=ArithmeticExecutor())
    )
    payload = validated.model_dump(mode="json")
    payload["validation"]["evidence"][0]["status"] = "failed"

    with pytest.raises(ValueError, match="require passing validation evidence"):
        type(validated).model_validate(payload)


def test_refuses_incomplete_validation_evidence() -> None:
    validated = TemplateApplication().validate_template(
        template(), domain=CodeDomain(execution_tool=ArithmeticExecutor())
    )
    validated.validation.cases_validated = 7

    with pytest.raises(ValueError, match="complete input domain"):
        generate_code_question(validated, seed=1)
