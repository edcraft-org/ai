"""Fixed jobs retain failures, explicit denominators, and replayable output files."""

import json

import pytest
from test_authoring_loop import (
    SEMANTIC,
    STRUCTURE,
    Executor,
    Provider,
    RecordingClient,
    run,
    wrong_answer,
)
from test_tool_catalogue import RecordingCatalogue

from edcraft_validator.application.authoring_contracts import (
    AuthoringError,
    AuthoringResult,
    CheckExecution,
    GenerationAttempt,
)
from edcraft_validator.application.template_workflow import TemplateApplication
from edcraft_validator.llm.llm_errors import GenerationError
from edcraft_validator.validation.check_contracts import ToolEvidence
from scripts import evaluate_authoring_loop as evaluation


def record(result):
    return {
        "status": result.status,
        "authoring_result": result.model_dump(mode="json"),
        "duration_ms": result.duration_ms,
    }


def test_summary_separates_jobs_attempts_corrections_and_missing_usage():
    success, _ = run(Provider())
    corrected, _ = run(Provider([wrong_answer(), Provider().proposals[0]]))
    failed, _ = run(Provider([wrong_answer()]))
    summary = evaluation.summarize_records(
        [record(success), record(corrected), record(failed)], 5
    )
    assert summary["checked"] == 2
    assert summary["needs_review"] == 1
    assert summary["unresolved"] == 2
    assert summary["first_attempt_success_rate"] == 1 / 5
    assert summary["checked_rate"] == 2 / 5
    assert summary["correction_eligible_jobs"] == 2
    assert summary["corrected_jobs"] == 1
    assert summary["correction_success_rate"] == 0.5
    assert summary["attempts_per_job"] == [1, 2, 4]
    assert summary["failure_counts"] == {"PROPOSED_ANSWER_MISMATCH": 1}
    assert summary["check_finding_counts"] == {"PROPOSED_ANSWER_MISMATCH": 5}
    assert summary["usage"]["input_tokens"] is None
    assert summary["mean_input_tokens_per_recorded_job"] is None
    assert evaluation.summarize_records([], 5)["correction_success_rate"] is None


def test_blocked_checks_fold_into_the_root_structural_failure():
    def execution(tool, code, *, status="error", blocking=None):
        return CheckExecution(
            call_id=tool,
            tool=tool,
            requested_arguments={},
            evidence=ToolEvidence(
                tool=tool,
                version="1",
                status=status,
                findings=[{"code": code, "message": code}],
                details={} if blocking is None else {"blocking_code": blocking},
            ),
        )

    result = AuthoringResult(
        status="needs_review",
        provider="test",
        model="test",
        domain="code",
        request={},
        prompt_version="",
        fixed_plan=[],
        tool_catalogue=[],
        failure=AuthoringError(stage="checking", code="TEMPLATE_CHECKS_FAILED"),
        attempts=[
            GenerationAttempt(
                number=1,
                candidate={},
                pending=[],
                complete=True,
                passed=False,
                executions=[
                    execution(
                        "code_verify_template_structure",
                        "UNSUPPORTED_CODE",
                        status="failed",
                    ),
                    execution(
                        "code_validate_answers_and_distractors",
                        "ANSWERS_NOT_EVALUATED",
                        blocking="UNSUPPORTED_CODE",
                    ),
                    execution(
                        "code_require_features",
                        "FEATURES_NOT_EVALUATED",
                        blocking="UNSUPPORTED_CODE",
                    ),
                ],
            )
        ],
    )
    summary = evaluation.summarize_records([record(result)], 1)
    assert summary["failure_counts"] == {"UNSUPPORTED_CODE": 1}
    assert not any(
        code.endswith("_NOT_EVALUATED") for code in summary["failure_counts"]
    )


def test_five_job_run_retains_provider_setup_failure_and_replays_saved_templates(
    monkeypatch, tmp_path
):
    calls = []

    def create(selection):
        calls.append(selection)
        if len(calls) == 2:
            raise GenerationError("not configured")
        return Provider()

    monkeypatch.setattr(evaluation, "create_model_provider", create)
    monkeypatch.setattr(
        evaluation,
        "TemplateApplication",
        lambda: TemplateApplication(tool_client=RecordingClient(Executor())),
    )
    monkeypatch.setattr(
        evaluation,
        "source_revision",
        lambda: {
            "git_revision": "test",
            "working_tree_dirty": True,
        },
    )
    output = tmp_path / "baseline.jsonl"
    monkeypatch.setattr(
        "sys.argv",
        [
            "evaluate",
            "--provider",
            "openai",
            "--model",
            "test",
            "--jobs",
            "5",
            "--output",
            str(output),
        ],
    )
    assert evaluation.main() == 1
    records = [json.loads(line) for line in output.read_text().splitlines()]
    assert len(records) == len(calls) == 5
    assert records[1]["failure"] == {
        "stage": "configuration",
        "code": "generation_error",
    }
    assert records[1]["status"] == "error"
    assert [r["request"]["difficulty"] for r in records] == [
        "easy",
        "easy",
        "medium",
        "medium",
        "hard",
    ]
    summary = json.loads(output.with_suffix(".summary.json").read_text())
    assert summary["checked"] == summary["replay_passed_jobs"] == 4
    assert summary["error"] == 1
    assert summary["unresolved"] == 0
    assert summary["failure_counts"] == {"configuration:generation_error": 1}
    for item in records:
        if item["status"] == "checked":
            previews = json.loads(
                (output.with_suffix("") / item["preview_file"]).read_text()
            )
            assert [preview["seed"] for preview in previews] == [0, 1, 42]
            assert (output.with_suffix("") / item["catalogue_file"]).exists()


def test_initial_failure_has_a_summary_without_checking_attempts():
    class Failure(Provider):
        def generate(self, request):
            raise GenerationError("invalid response")

    result, _ = run(Failure())
    summary = evaluation.summarize_records([record(result)], 1)
    assert summary["error"] == 1
    assert summary["attempts_per_job"] == [0]
    assert summary["usage"]["model_call_count"] == 1
    assert summary["failure_counts"] == {"generation:generation_error": 1}


@pytest.mark.parametrize("arguments", [{"unexpected": True}, "{invalid"])
def test_initial_plan_argument_errors_are_categorized_without_check_findings(arguments):
    result, _ = run(Provider(plan=(SEMANTIC,), plan_arguments={SEMANTIC: arguments}))
    summary = evaluation.summarize_records([record(result)], 1)
    assert result.status == "error"
    assert summary["failure_counts"] == {f"generation:{result.failure.code}": 1}
    assert summary["check_finding_counts"] == {}


def test_terminal_tool_error_preserves_other_check_failure_categories():
    class UnavailableStructure(RecordingClient):
        def call_tool(self, name, arguments, *, version=None):
            if name == STRUCTURE:
                raise TimeoutError("MCP tool unavailable")
            return super().call_tool(name, arguments, version=version)

    result, _ = run(Provider([wrong_answer()]), UnavailableStructure(Executor()))
    summary = evaluation.summarize_records([record(result)], 1)
    assert result.status == "needs_review"
    assert summary["failure_counts"] == {
        "PROPOSED_ANSWER_MISMATCH": 1,
        "TOOL_CALL_ERROR": 1,
    }


@pytest.mark.parametrize("failure", ["resolution", "writing"])
def test_rerun_does_not_attach_catalogue_from_previous_job(
    monkeypatch, tmp_path, failure
):
    output = tmp_path / "baseline.jsonl"
    monkeypatch.setattr(
        "sys.argv", ["evaluate", "--jobs", "1", "--output", str(output)]
    )
    monkeypatch.setattr(
        evaluation, "create_model_provider", lambda selection: Provider()
    )
    monkeypatch.setattr(
        evaluation,
        "TemplateApplication",
        lambda: TemplateApplication(tool_client=RecordingClient(Executor())),
    )
    assert evaluation.main() == 0
    original = json.loads(output.read_text())
    catalogue = output.with_suffix("") / original["catalogue_file"]
    saved_catalogue = catalogue.read_bytes()

    if failure == "resolution":
        monkeypatch.setattr(
            evaluation,
            "TemplateApplication",
            lambda: TemplateApplication(
                tool_catalogue=RecordingCatalogue([]),
                tool_client=RecordingClient(Executor()),
            ),
        )
    else:
        write_json = evaluation.write_json

        def fail_catalogue_write(path, value):
            if path == catalogue:
                raise OSError("Cannot write catalogue")
            write_json(path, value)

        monkeypatch.setattr(evaluation, "write_json", fail_catalogue_write)

    assert evaluation.main() == 1
    failed = json.loads(output.read_text())
    assert failed["status"] == "error"
    assert "catalogue_file" not in failed
    assert catalogue.read_bytes() == saved_catalogue
    assert failed["authoring_result"]["attempts"] == []


@pytest.mark.parametrize("fails", [False, True], ids=["success", "failure"])
def test_each_job_closes_owned_provider_on_success_and_failure(
    monkeypatch, tmp_path, fails
):
    closed = []

    class ClosingProvider(Provider):
        def close(self):
            closed.append(self)

    class FailingProvider(ClosingProvider):
        def generate(self, request):
            raise GenerationError("not configured")

    monkeypatch.setattr(
        evaluation,
        "create_model_provider",
        lambda selection: FailingProvider() if fails else ClosingProvider(),
    )
    monkeypatch.setattr(
        evaluation,
        "TemplateApplication",
        lambda: TemplateApplication(tool_client=RecordingClient(Executor())),
    )
    monkeypatch.setattr(
        evaluation,
        "source_revision",
        lambda: {"git_revision": "test", "working_tree_dirty": True},
    )
    output = tmp_path / "baseline.jsonl"
    monkeypatch.setattr(
        "sys.argv",
        ["evaluate", "--provider", "openai", "--jobs", "1", "--output", str(output)],
    )

    assert evaluation.main() == (1 if fails else 0)
    assert len(closed) == 1


def test_nonpositive_job_count_stops_before_model_creation(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "sys.argv",
        ["evaluate", "--jobs", "0", "--output", str(tmp_path / "result.jsonl")],
    )
    with pytest.raises(SystemExit):
        evaluation.main()
