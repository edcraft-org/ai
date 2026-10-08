import json

from authoring_helpers import RequestPendingTools

from edcraft_validator.domains.code.code_schemas import CodeTemplateProposal
from edcraft_validator.domains.code.template_evaluator import (
    TemplateEvaluationReport,
    TemplateEvaluator,
)
from edcraft_validator.llm.llm_contracts import (
    PlannedGenerationResponse,
    RecommendedCheck,
)
from edcraft_validator.llm.llm_errors import GenerationError
from edcraft_validator.tools.python_execution import ExecutionResult


def proposal(*, code: str = "def add(a, b):\n    return a + b") -> CodeTemplateProposal:
    return CodeTemplateProposal.model_validate(
        {
            "question_template": "What does add({a}, {b}) return?",
            "code": code,
            "entry_function": "add",
            "parameters": [
                {"name": "a", "kind": "integer", "values": [1, 2]},
                {"name": "b", "kind": "integer", "values": [3, 4]},
            ],
            "answer_target": "return_value",
            "answer_expression": "a + b",
            "distractors": [
                {"expression": "a + b", "reason_template": "Repeats answer."},
                {"expression": "a - b", "reason_template": "Subtracts."},
                {"expression": "a + b + 1", "reason_template": "Adds one."},
                {"expression": "a + b - 1", "reason_template": "Subtracts one."},
                {"expression": "a + b + 2", "reason_template": "Adds two."},
            ],
        }
    )


class SumExecutor:
    def execute_batch(self, code, entry_function, inputs, *, timeout_seconds):
        return [
            ExecutionResult(ok=True, answer=item["a"] + item["b"]) for item in inputs
        ]


class StubProvider(RequestPendingTools):
    provider = "stub"
    model = "stub-model"

    def __init__(self, result: CodeTemplateProposal) -> None:
        self.result = result

    def generate(self, request):
        if not issubclass(request.response_model, PlannedGenerationResponse):
            return request.response_model.model_validate(self.result.model_dump())
        return PlannedGenerationResponse(
            proposal=self.result,
            checks=[
                RecommendedCheck(
                    name="code_validate_answers_and_distractors", arguments={}
                )
            ],
        )


def test_evaluation_records_outputs_failures_and_grouped_metrics(tmp_path) -> None:
    proposals = iter([proposal(), proposal(code="def add(a, b):\n    return a")])
    evaluator = TemplateEvaluator(
        provider_factory=lambda selection: StubProvider(next(proposals)),
        execution_tool=SumExecutor(),
    )

    report = evaluator.evaluate(
        provider="stub",
        model="stub-model",
        topics=("arithmetic",),
        difficulties=("easy",),
        repetitions=2,
    )

    assert [attempt.status for attempt in report.attempts] == ["validated", "failed"]
    assert report.attempts[0].validated_template is not None
    assert report.attempts[1].failure_stage == "validation"
    assert report.attempts[1].failure_code == "UNUSED_PARAMETER"
    assert report.attempts[1].validation_evidence[-1].status == "failed"
    assert (
        report.attempts[1].validation_evidence[-1].check
        == "code_validate_answers_and_distractors"
    )
    assert [tool["name"] for tool in report.attempts[1].tool_catalogue] == [
        "code_require_features",
        "code_validate_answers_and_distractors",
        "code_verify_template_structure",
    ]
    assert report.summary.attempts == 2
    assert report.summary.validated == 1
    assert report.summary.pass_rate == 0.5
    assert report.summary.failure_counts == {"UNUSED_PARAMETER": 1}
    assert report.summary.groups[0].model == "stub-model"

    output = tmp_path / "evaluation.jsonl"
    report.write_jsonl(output)
    records = [json.loads(line) for line in output.read_text().splitlines()]
    assert len(records) == 2
    assert (
        records[0]["authoring_result"]["artifact"]["authoring"]["model"] == "stub-model"
    )
    assert records[1]["failure_code"] == "UNUSED_PARAMETER"
    assert (
        records[1]["authoring_result"]["tool_catalogue"]
        == report.attempts[1].tool_catalogue
    )
    assert records[1]["authoring_result"]["attempts"][-1]["executions"][-1]["evidence"][
        "findings"
    ][0]["code"] == ("UNUSED_PARAMETER")
    for record in records:
        assert (
            not {"validated_template", "tool_catalogue", "validation_evidence"}
            & record.keys()
        )
    # Saved evaluation records still expose the same Python convenience fields.
    loaded = TemplateEvaluationReport.model_validate_json(report.model_dump_json())
    assert loaded.model_dump(mode="json") == report.model_dump(mode="json")
    assert (
        loaded.attempts[0].validated_template == report.attempts[0].validated_template
    )
    assert loaded.attempts[1].tool_catalogue == report.attempts[1].tool_catalogue
    assert (
        loaded.attempts[1].validation_evidence == report.attempts[1].validation_evidence
    )
    # Explicitly requesting a convenience field still works without the report.
    selected = report.attempts[0].model_dump(
        mode="json", include={"validated_template"}
    )
    assert selected["validated_template"] == records[0]["authoring_result"]["artifact"]


def test_evaluation_notifies_before_starting_the_next_attempt() -> None:
    observed = []
    events = []

    class RecordingProvider(StubProvider):
        def generate(self, request):
            events.append("generate")
            return super().generate(request)

    def record(attempt):
        events.append(f"completed:{attempt.attempt}")
        observed.append(attempt)

    evaluator = TemplateEvaluator(
        provider_factory=lambda selection: RecordingProvider(proposal()),
        execution_tool=SumExecutor(),
    )
    report = evaluator.evaluate(
        provider="stub",
        model="stub-model",
        topics=("arithmetic",),
        difficulties=("easy",),
        repetitions=2,
        on_attempt=record,
    )
    assert observed == report.attempts
    assert events == ["generate", "completed:1", "generate", "completed:2"]


def test_evaluation_classifies_provider_setup_failure() -> None:
    def unavailable(selection):
        raise GenerationError("provider is not configured")

    report = TemplateEvaluator(provider_factory=unavailable).evaluate(
        provider="missing",
        model=None,
        topics=("arithmetic",),
        difficulties=("easy",),
        repetitions=1,
    )

    attempt = report.attempts[0]
    assert attempt.status == "failed"
    assert attempt.failure_stage == "configuration"
    assert attempt.failure_code == "generation_error"
    assert attempt.tool_catalogue == []


def test_evaluation_retains_catalogue_when_model_generation_fails() -> None:
    class FailingProvider:
        provider = "stub"
        model = "stub-model"

        def generate(self, request):
            raise GenerationError("generation failed")

    report = TemplateEvaluator(
        provider_factory=lambda selection: FailingProvider()
    ).evaluate(
        provider="stub",
        model="stub-model",
        topics=("arithmetic",),
        difficulties=("easy",),
        repetitions=1,
    )

    attempt = report.attempts[0]
    assert attempt.failure_stage == "generation"
    assert [tool["name"] for tool in attempt.tool_catalogue] == [
        "code_require_features",
        "code_validate_answers_and_distractors",
        "code_verify_template_structure",
    ]


def test_successful_evaluation_keeps_failed_attempt_evidence_in_the_report():
    class CorrectingProvider(StubProvider):
        def generate(self, request):
            if issubclass(request.response_model, PlannedGenerationResponse):
                wrong = proposal().model_copy(update={"answer_expression": "a - b"})
                return PlannedGenerationResponse(
                    proposal=wrong,
                    checks=[
                        {
                            "name": "code_validate_answers_and_distractors",
                            "arguments": {},
                        }
                    ],
                )
            return request.response_model.model_validate(proposal().model_dump())

    report = TemplateEvaluator(
        provider_factory=lambda selection: CorrectingProvider(proposal()),
        execution_tool=SumExecutor(),
    ).evaluate(
        provider="stub",
        model="stub-model",
        topics=("arithmetic",),
        difficulties=("easy",),
        repetitions=1,
    )
    attempt = report.attempts[0]
    assert attempt.status == "validated"
    history = attempt.authoring_result.attempts
    assert len(history) == 2
    assert not history[0].passed and history[1].passed
    assert (
        history[0].executions[0].evidence.findings[0].code == "PROPOSED_ANSWER_MISMATCH"
    )
    assert "attempts" not in attempt.validated_template.authoring.model_dump()


def test_evaluation_attributes_failure_to_the_final_attempt():
    class ChangingFailures(StubProvider):
        def generate(self, request):
            if issubclass(request.response_model, PlannedGenerationResponse):
                wrong = proposal().model_copy(update={"answer_expression": "a - b"})
                return PlannedGenerationResponse(
                    proposal=wrong,
                    checks=[
                        {
                            "name": "code_validate_answers_and_distractors",
                            "arguments": {},
                        }
                    ],
                )
            payload = proposal().model_dump()
            payload["distractors"] = [
                {"expression": "a + b", "reason_template": "Repeats answer."}
            ] * 3
            return request.response_model.model_validate(payload)

    report = TemplateEvaluator(
        provider_factory=lambda selection: ChangingFailures(proposal()),
        execution_tool=SumExecutor(),
    ).evaluate(
        provider="stub",
        model="stub-model",
        topics=("arithmetic",),
        difficulties=("easy",),
        repetitions=1,
    )
    attempt = report.attempts[0]
    assert attempt.failure_stage == "validation"
    assert attempt.failure_code == "DISTRACTOR_SELECTION_FAILED"
    assert report.summary.failure_counts == {"DISTRACTOR_SELECTION_FAILED": 1}
    history = attempt.authoring_result.attempts
    assert len(history) == 3
    assert (
        history[0].executions[0].evidence.findings[0].code == "PROPOSED_ANSWER_MISMATCH"
    )
    assert (
        history[-1].executions[0].evidence.findings[0].code
        == "DISTRACTOR_SELECTION_FAILED"
    )


def test_evaluation_distinguishes_revision_transport_errors_from_check_failures():
    from edcraft_validator.llm.llm_errors import GenerationTransportError

    class InterruptedCorrection(StubProvider):
        def generate(self, request):
            if issubclass(request.response_model, PlannedGenerationResponse):
                wrong = proposal().model_copy(update={"answer_expression": "a - b"})
                return PlannedGenerationResponse(
                    proposal=wrong,
                    checks=[
                        {
                            "name": "code_validate_answers_and_distractors",
                            "arguments": {},
                        }
                    ],
                )
            raise GenerationTransportError("Connection failed during correction")

    report = TemplateEvaluator(
        provider_factory=lambda selection: InterruptedCorrection(proposal()),
        execution_tool=SumExecutor(),
    ).evaluate(
        provider="stub",
        model="stub-model",
        topics=("arithmetic",),
        difficulties=("easy",),
        repetitions=1,
    )
    attempt = report.attempts[0]
    assert attempt.failure_stage == "generation"
    assert attempt.failure_code == "transport"
    assert report.summary.failure_counts == {"transport": 1}
    assert attempt.authoring_result.status == "error"
    assert (
        attempt.authoring_result.attempts[0].executions[0].evidence.findings[0].code
        == "PROPOSED_ANSWER_MISMATCH"
    )
