"""Property-only checking, bounded search and recipe-based unseen generation."""

import json
import time
from pathlib import Path

import pytest
from code_validation_helpers import validate_code
from test_code_templates import ArithmeticExecutor, template

from edcraft_validator.domains.code.code_schemas import ValidatedCodeTemplate
from edcraft_validator.domains.code.question_generator import generate_code_question
from edcraft_validator.mcp.code_checks.property_checks import PropertyCheckSettings
from edcraft_validator.mcp.code_tools import validate_answers_and_distractors
from edcraft_validator.validation.validation_contracts import ValidationFailure


def large_candidate():
    value = template()
    for index, p in enumerate(value.parameters):
        p.values = list(range(2 + index, 34 + index))
    return value


def test_large_domain_is_sampled_and_unseen_inputs_generate_without_execution():
    candidate = large_candidate()
    executor = ArithmeticExecutor()
    checked = validate_code(candidate, execution_tool=executor)
    counts = checked.validation
    assert counts.checking_mode == "property_based"
    assert 1 <= counts.examples_checked <= counts.max_examples + 5
    assert counts.execution_calls == len(executor.calls) == counts.examples_checked
    assert counts.examples_checked < 32**3
    assert "validated_cases" not in counts.model_dump()
    assert checked.template.answer_expression == candidate.answer_expression
    reloaded = ValidatedCodeTemplate.model_validate_json(checked.model_dump_json())
    sampled = {json.dumps(x, sort_keys=True) for x in executor.calls}
    before = len(executor.calls)
    drafts = [generate_code_question(reloaded, n) for n in range(20)]
    assert any(json.dumps(q.parameters, sort_keys=True) not in sampled for q in drafts)
    assert len(executor.calls) == before
    for q in drafts:
        assert q == generate_code_question(checked, q.seed)
        assert q.requires_manual_review
        assert (
            q.question.proposed_answer
            == q.parameters["a"] + q.parameters["b"] - q.parameters["c"]
        )
        assert len(set(q.question.distractors)) == 3
        assert q.question.proposed_answer not in q.question.distractors


def test_budget_stops_actual_execution_including_replays():
    executor = ArithmeticExecutor()
    with pytest.raises(ValidationFailure) as exc:
        validate_answers_and_distractors(
            large_candidate(),
            3,
            execution_tool=executor,
            timeout_seconds=2,
            property_settings=PropertyCheckSettings(max_execution_calls=2),
        )
    assert exc.value.code == "PROPERTY_CHECK_BUDGET_EXCEEDED"
    assert exc.value.context["execution_calls"] == len(executor.calls) == 2


def test_wall_budget_returns_error_instead_of_passing_partial_samples():
    class Slow(ArithmeticExecutor):
        def execute_batch(self, *args, **kwargs):
            time.sleep(0.02)
            return super().execute_batch(*args, **kwargs)

    with pytest.raises(ValidationFailure) as exc:
        validate_answers_and_distractors(
            large_candidate(),
            3,
            execution_tool=Slow(),
            timeout_seconds=2,
            property_settings=PropertyCheckSettings(timeout_seconds=0.01),
        )
    assert exc.value.code == "PROPERTY_CHECK_BUDGET_EXCEEDED"


def test_failing_generated_input_shrinks_and_replays():
    candidate = template(
        code="def f(a, b, c):\n    return a + b - c",
        entry_function="f",
        question_template="What does f({a}, {b}, {c}) return?",
        answer_expression="a + b - c if a < 5 or a > 8 else a + b - c + 1",
    )
    candidate.parameters[0].values = list(range(10))
    seen = []
    for _ in range(2):
        with pytest.raises(ValidationFailure) as exc:
            validate_answers_and_distractors(
                candidate,
                3,
                execution_tool=ArithmeticExecutor(),
                timeout_seconds=2,
            )
        assert exc.value.code == "PROPOSED_ANSWER_MISMATCH"
        seen.append(exc.value.context["failing_inputs"])
        assert exc.value.context["execution_calls"] <= 128
    assert seen[0] == seen[1]
    assert seen[0]["a"] == 5


def test_no_template_cartesian_enumerator_or_legacy_fields_remain():
    root = Path("src/edcraft_validator")
    for name in [
        "domains/code/question_generator.py",
        "domains/code/code_domain.py",
        "mcp/code_checks/validation_context.py",
    ]:
        text = (root / name).read_text()
        assert "itertools.product" not in text and "eligible_inputs" not in text
    checked = validate_code(template(), execution_tool=ArithmeticExecutor())
    raw = checked.model_dump()
    raw["validation"]["validated_cases"] = []
    with pytest.raises(ValueError):
        ValidatedCodeTemplate.model_validate(raw)


def test_sampling_rejects_a_collision_instead_of_an_excluded_input_pool():
    candidate = template()
    candidate.distractors[0].expression = candidate.answer_expression
    with pytest.raises(ValidationFailure) as exc:
        validate_code(candidate, execution_tool=ArithmeticExecutor())
    assert exc.value.code == "DISTRACTOR_SELECTION_FAILED"
    assert exc.value.context["distractor_diagnostics"]


def test_generation_stops_when_all_recipe_attempts_collide():
    checked = validate_code(template(), execution_tool=ArithmeticExecutor())
    checked.template.distractors[0].expression = checked.template.answer_expression
    with pytest.raises(ValidationFailure) as exc:
        generate_code_question(checked, 1)
    assert exc.value.code == "GENERATION_ATTEMPTS_EXHAUSTED"


@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan")])
def test_invalid_sample_limits_are_rejected(value):
    with pytest.raises(ValueError):
        PropertyCheckSettings(max_examples=value)


def test_existing_author_prompt_limit_is_unchanged():
    from edcraft_validator.domains.code.code_schemas import CodeTemplateRequest

    with pytest.raises(ValueError):
        CodeTemplateRequest(prompt="x" * 4001, difficulty="easy")


def test_finalization_keeps_evidence_uniqueness_validation():
    from edcraft_validator.domains.code.code_domain import CodeDomain
    from edcraft_validator.mcp.evidence import ToolEvidence

    candidate = template()
    details = validate_answers_and_distractors(
        candidate, 3, execution_tool=ArithmeticExecutor(), timeout_seconds=2
    )
    evidence = ToolEvidence(
        tool="code_validate_answers_and_distractors",
        version="2.0.0",
        status="passed",
        details=details,
    )
    with pytest.raises(ValueError, match="unique"):
        CodeDomain().finalize_checked_template(candidate, [evidence, evidence])
