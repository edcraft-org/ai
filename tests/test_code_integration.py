from pathlib import Path

import pytest
from authoring_helpers import RequestPendingTools, SelectSemanticCheck

from edcraft_validator.application.template_workflow import TemplateApplication
from edcraft_validator.domains.code.code_domain import CodeDomain
from edcraft_validator.domains.code.code_schemas import (
    CodeTemplateCandidate,
    CodeTemplateProposal,
    CodeTemplateRequest,
    ValidatedCodeTemplate,
)
from edcraft_validator.domains.code.question_generator import generate_code_question
from edcraft_validator.domains.code.template_evaluator import TemplateEvaluator
from edcraft_validator.llm.llm_contracts import (
    PlannedGenerationResponse,
    RecommendedCheck,
)
from edcraft_validator.tools.python_execution import LocalPythonTool

TEMPLATE_PATHS = sorted(
    (Path(__file__).parents[1] / "examples" / "templates").glob("*.json")
)


def test_generated_code_is_bounded_by_local_python_tool() -> None:
    result = LocalPythonTool().execute_batch(
        "def slow(value):\n"
        "    for _ in range(1000000000):\n"
        "        pass\n"
        "    return value",
        "slow",
        [{"value": 1}],
        timeout_seconds=0.01,
    )[0]

    assert not result.ok
    assert result.error_code in {"EXECUTION_TIMEOUT", "TRACE_LIMIT_EXCEEDED"}


def test_generated_code_trace_limit_is_enforced() -> None:
    result = LocalPythonTool().execute_batch(
        "def expensive(value):\n"
        "    for _ in range(1000000000):\n"
        "        value += 1\n"
        "    return value",
        "expensive",
        [{"value": 1}],
        timeout_seconds=10,
    )[0]

    assert not result.ok
    assert result.error_code == "TRACE_LIMIT_EXCEEDED"


@pytest.mark.parametrize(
    "code",
    [
        (
            "def total(n):\n"
            "    if n <= 0:\n"
            "        return 0\n"
            "    return n + total(n - 1)"
        ),
        (
            "def helper(n):\n"
            "    if n <= 0:\n"
            "        return 0\n"
            "    return n + total(n - 1)\n\n"
            "def total(n):\n"
            "    if n <= 0:\n"
            "        return 0\n"
            "    return n + helper(n - 1)"
        ),
    ],
    ids=["direct", "mutual"],
)
@pytest.mark.parametrize(
    "target, expression, expected",
    [
        ("return_value", "n * (n + 1) // 2", [3, 6, 10]),
        ("function_calls", "n + 1", [3, 4, 5]),
        ("branch_executions", "n + 1", [3, 4, 5]),
    ],
)
def test_recursive_templates_are_checked_and_replayed(
    code, target, expression, expected
):
    candidate = CodeTemplateCandidate.model_validate(
        {
            "template_id": "recursive.total",
            "difficulty": "medium",
            "code": code,
            "entry_function": "total",
            "parameters": [{"name": "n", "kind": "integer", "values": [2, 3, 4]}],
            "question_template": f"What is the {target} of total({{n}})?",
            "answer_target": target,
            "answer_expression": expression,
            "distractors": [
                {
                    "expression": f"({expression}) + {offset}",
                    "reason_template": "Overcounts.",
                }
                for offset in (1, 2, 3)
            ],
            "question_type": "mcq",
        }
    )
    application = TemplateApplication()
    domain = CodeDomain()

    result = application.validate_template(
        candidate, domain=domain, provider=SelectSemanticCheck()
    )

    assert result.status == "checked", result.reason
    assert [
        case.answer for case in result.artifact.validation.validated_cases
    ] == expected
    saved = ValidatedCodeTemplate.model_validate_json(result.artifact.model_dump_json())
    for seed in (0, 42):
        preview = application.generate_question(saved, domain=domain, seed=seed)
        assert preview == application.generate_question(saved, domain=domain, seed=seed)
        assert preview.question.proposed_answer == expected[preview.parameters["n"] - 2]


def test_nonterminating_recursion_cannot_produce_a_checked_artifact() -> None:
    candidate = CodeTemplateCandidate.model_validate(
        {
            "template_id": "recursive.nonterminating",
            "difficulty": "medium",
            "code": "def total(n):\n    return total(n)",
            "entry_function": "total",
            "parameters": [{"name": "n", "kind": "integer", "values": [1, 2]}],
            "question_template": "What does total({n}) return?",
            "answer_target": "return_value",
            "answer_expression": "n",
            "distractors": [
                {"expression": f"n + {offset}", "reason_template": "Overcounts."}
                for offset in (1, 2, 3)
            ],
            "question_type": "mcq",
        }
    )

    result = TemplateApplication().validate_template(
        candidate, domain=CodeDomain(), provider=SelectSemanticCheck()
    )

    assert result.status == "needs_review"
    assert result.artifact is None
    execution = result.attempts[0].executions[0]
    assert execution.evidence.status == "failed"
    assert execution.evidence.findings[0].code == "EXECUTION_FAILED"
    assert "RecursionError" in execution.evidence.findings[0].message


@pytest.mark.parametrize("template_path", TEMPLATE_PATHS, ids=lambda path: path.stem)
def test_template_is_exhaustively_validated(template_path: Path) -> None:
    template = CodeTemplateCandidate.model_validate_json(template_path.read_text())

    application = TemplateApplication()
    domain = CodeDomain()
    result = application.validate_template(
        template, domain=domain, provider=SelectSemanticCheck()
    )
    assert result.status == "checked", result.reason
    validated = result.artifact
    reloaded = ValidatedCodeTemplate.model_validate_json(validated.model_dump_json())
    for seed in (0, 1, 42, 999):
        question = application.generate_question(reloaded, domain=domain, seed=seed)
        assert question == generate_code_question(validated, seed)
        assert question.question.answer_target == template.answer_target

    expected_cases = 1
    for parameter in template.parameters:
        expected_cases *= len(parameter.values)
    assert validated.validation.cases_validated == expected_cases


def test_model_proposal_is_built_then_validated() -> None:
    path = (
        Path(__file__).parents[1] / "examples" / "templates" / "arithmetic_linear.json"
    )
    canonical = CodeTemplateCandidate.model_validate_json(path.read_text())
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

    class StubProvider(RequestPendingTools):
        provider = "stub"
        model = "stub-model"

        def generate(self, request):
            return PlannedGenerationResponse(
                proposal=proposal,
                checks=[
                    RecommendedCheck(
                        name="code_validate_answers_and_distractors", arguments={}
                    )
                ],
            )

    validated = TemplateApplication().create_validated_template(
        CodeTemplateRequest(prompt="Create an arithmetic question", difficulty="easy"),
        domain=CodeDomain(),
        provider=StubProvider(),
    )

    assert validated.template.question_template == (
        "What does calculate({a}, {b}, {c}) return?"
    )
    expected_cases = 1
    for parameter in proposal.parameters:
        expected_cases *= len(parameter.values)
    assert validated.validation.cases_validated == expected_cases

    report = TemplateEvaluator(
        provider_factory=lambda selection: StubProvider()
    ).evaluate(
        provider="stub",
        model="stub-model",
        topics=("arithmetic",),
        difficulties=("easy",),
        repetitions=1,
    )
    assert report.summary.validated == 1
    assert report.attempts[0].validated_template is not None
