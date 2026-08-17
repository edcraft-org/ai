import json
from pathlib import Path

import pytest

from edcraft_validator._worker import execute_request
from edcraft_validator.executor import ExecutionResult
from edcraft_validator.models import GeneratedQuestion
from edcraft_validator.validator import QuestionValidator

EXAMPLES_DIR = Path(__file__).parents[1] / "examples"
# Automatically include every example that is documented as valid.
EXAMPLE_FILES = sorted(EXAMPLES_DIR.glob("valid_*.json"))


class TrustedWorkerExecutor:
    """Run only the fixed repository examples without requiring Docker."""

    def execute(
        self,
        code: str,
        entry_function: str,
        inputs: dict[str, object],
        *,
        timeout_seconds: float,
    ) -> ExecutionResult:
        response = execute_request(
            {"code": code, "entry_function": entry_function, "inputs": inputs}
        )
        return ExecutionResult(
            ok=response["ok"],
            answer=response.get("answer"),
            trace_summary=response.get("trace_summary"),
            error_code=response.get("error_code"),
            error_message=response.get("error_message"),
        )


def example_validator() -> QuestionValidator:
    return QuestionValidator(executor=TrustedWorkerExecutor())


@pytest.mark.parametrize("example_path", EXAMPLE_FILES, ids=lambda path: path.stem)
def test_valid_examples_pass_end_to_end(example_path: Path) -> None:
    # Load each file through the same strict schema used for future AI output.
    raw_question = json.loads(example_path.read_text(encoding="utf-8"))
    question = GeneratedQuestion.model_validate(raw_question)

    # Exercise safety checking, traced execution, and answer validation together.
    report = example_validator().validate(question)

    assert report.status == "valid", report.model_dump_json(indent=2)
    assert report.trace_summary is not None
    assert report.trace_summary.function_calls >= 1


def test_control_flow_example_produces_trace_evidence() -> None:
    path = EXAMPLES_DIR / "valid_accumulated_bonus.json"
    question = GeneratedQuestion.model_validate_json(path.read_text(encoding="utf-8"))

    report = example_validator().validate(question)

    # The four input scores produce four iterations and four threshold checks.
    assert report.trace_summary is not None
    assert report.trace_summary.loop_executions == 1
    assert report.trace_summary.branch_executions == 4


def test_helper_function_calls_are_traced() -> None:
    path = EXAMPLES_DIR / "valid_weighted_total.json"
    question = GeneratedQuestion.model_validate_json(path.read_text(encoding="utf-8"))

    report = example_validator().validate(question)

    # This includes the entry call, three helper calls, and safe built-in calls.
    assert report.trace_summary is not None
    assert report.trace_summary.function_calls >= 6
