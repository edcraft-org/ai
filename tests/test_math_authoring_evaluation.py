"""Math authoring evaluation through the script with fake providers only."""

import json

from math_helpers import (
    MathTemplateJudge,
    ir_num,
    ir_param,
    ir_proposal,
    ir_template,
    quadratic_ir_template,
)
from test_authoring_loop import Executor, Provider, RecordingClient

from edcraft_validator.application.template_workflow import TemplateApplication
from edcraft_validator.domains.math.ir.schema import (
    AnswerRecipe,
    Distractor,
    Given,
    Goal,
    MathItemSpec,
    ParameterSpec,
    SymbolSpec,
    TextSpec,
)
from edcraft_validator.llm.llm_contracts import PlannedGenerationResponse
from edcraft_validator.llm.usage import TokenUsage
from edcraft_validator.mcp.client import FastMcpToolClient
from edcraft_validator.mcp.server import create_validation_server
from scripts import evaluate_authoring_loop as evaluation

MATH_CHECKS = (
    "math_verify_item_spec",
    "math_validate_options",
    "assess_template_difficulty",
    "assess_template_relevance",
)


def unsupported_eigenvalues_proposal():
    matrix = [
        [ir_param("a"), ir_num(1), ir_num(0)],
        [ir_num(0), ir_num(2), ir_num(0)],
        [ir_num(0), ir_num(0), ir_num(3)],
    ]
    body = MathItemSpec(
        topic="university.eigenvalues",
        symbols=[SymbolSpec(name="z", kind="given", domain="integer")],
        givens=[Given(id="z_domain", kind="domain", symbol="z", domain="integer")],
        goal=Goal(kind="eigenvalues", matrix=matrix),
        answer_recipe=AnswerRecipe(
            kind="matrix",
            matrix=[
                [ir_param("a"), ir_num(2), ir_num(3)],
                [ir_num(0), ir_num(0), ir_num(0)],
                [ir_num(0), ir_num(0), ir_num(0)],
            ],
        ),
        distractors=[
            Distractor(value=ir_num(value), misconception=f"MISCONCEPTION_{value}")
            for value in (1, 2, 3)
        ],
        text=TextSpec(mode="symbolic", template="Find the eigenvalues of {matrix}."),
    )
    return ir_proposal(
        ir_template(
            "university.eigenvalues",
            [ParameterSpec(name="a", values=["1", "2"])],
            body,
        )
    )


class MathAuthor:
    provider = "scripted"
    model = "scripted-math"

    def __init__(self, proposals):
        self.proposals = proposals
        self.calls = 0
        self.closed = False

    def generation_settings(self):
        return {"mode": "scripted", "max_retries": 0}

    def generate(self, request):
        self.calls += 1
        self.last_usage = TokenUsage(input_tokens=11, output_tokens=7)
        if request.schema_name == "template_revision":
            return self.proposals[-1].model_copy(deep=True)
        return PlannedGenerationResponse(
            proposal=self.proposals[0],
            checks=[{"name": name, "arguments": {}} for name in MATH_CHECKS],
        )

    def close(self):
        self.closed = True


class ScoringDecisions:
    provider = "fake"
    model = "decision-test"
    threshold = 0.9

    def generation_settings(self):
        return {"reasoning": "none", "mode": "scripted"}

    def score(self, request_text, question_text):
        self.last_usage = TokenUsage(input_tokens=20, output_tokens=1)
        return 0.1 if "prove" in request_text.lower() else 0.99


def _install_math_application(monkeypatch):
    def application():
        server = create_validation_server(
            difficulty_provider_factory=MathTemplateJudge,
            decision_provider_factory=ScoringDecisions,
        )
        return TemplateApplication(tool_client=FastMcpToolClient(server))

    monkeypatch.setattr(evaluation, "TemplateApplication", application)
    monkeypatch.setattr(
        evaluation,
        "source_revision",
        lambda: {"git_revision": "test-revision", "working_tree_dirty": True},
    )


def _run_math(monkeypatch, tmp_path, *, case_set, provider, name):
    _install_math_application(monkeypatch)
    monkeypatch.setattr(evaluation, "create_model_provider", lambda selection: provider)
    output = tmp_path / name
    monkeypatch.setattr(
        "sys.argv",
        [
            "evaluate",
            "--domain",
            "math",
            "--provider",
            "scripted",
            "--model",
            "scripted-math",
            "--set",
            case_set,
            "--jobs",
            "1",
            "--output",
            str(output),
        ],
    )
    assert evaluation.main() == 0
    return output


def _records(output):
    return [json.loads(line) for line in output.read_text().splitlines()]


def test_math_natural_prompt_records_assessments_coverage_and_replay(
    monkeypatch, tmp_path
):
    provider = MathAuthor([ir_proposal(quadratic_ir_template())])
    output = _run_math(
        monkeypatch,
        tmp_path,
        case_set="natural",
        provider=provider,
        name="math-natural.jsonl",
    )

    record = _records(output)[0]
    assert record["domain"] == "math"
    assert record["case_set"] == "natural"
    assert record["status"] == record["outcome"] == "checked"
    assert record["checked"] is True
    assert record["needs_review"] is False
    assert record["failed"] is False
    assert record["unresolved"] is False
    assert record["attempts_used"] == 1
    assert record["failed_check_codes_by_attempt"] == [{"attempt": 1, "codes": []}]
    assert record["difficulty"]["requested"] == "easy"
    assert record["difficulty"]["estimated"] == "easy"
    assert record["difficulty"]["decision"] == "matches"
    assert record["difficulty"]["assessment_path"] == "decision"
    assert record["relevance"]["score"] == 0.99
    assert record["relevance"]["threshold"] == 0.9
    assert record["relevance"]["decision"] == "relevant"
    assert record["examples_checked"] >= 1
    assert record["declared_domain_size"] >= 1
    assert record["author_tokens"]["input_tokens"] == 11
    assert record["judge_tokens"]["input_tokens"] is not None
    assert record["duration_ms"] >= 0
    assert record["replay_passed"] is True
    assert provider.calls == 1

    previews = json.loads((output.with_suffix("") / record["preview_file"]).read_text())
    assert [preview["seed"] for preview in previews] == [0, 1, 42]

    summary = json.loads(output.with_suffix(".summary.json").read_text())
    assert summary["outcomes"]["checked"] == 1
    assert summary["by_set"]["natural"]["checked"] == 1
    assert summary["checked_rate"] == 1
    assert summary["first_attempt_success_rate"] == 1
    assert summary["revisions"]["total"] == 0
    assert summary["difficulty_agreement"] == {"easy": {"easy": 1}}
    assert summary["latency_ms"]["median"] is not None
    assert summary["token_totals"]["author"]["input_tokens"] == 11
    assert summary["token_totals"]["judge"]["model_call_count"] == 2

    manifest = json.loads(output.with_suffix(".manifest.json").read_text())
    assert manifest["domain"] == "math"
    assert manifest["validator_revision"] == "test-revision"
    assert manifest["provider"] == "scripted"
    assert manifest["resolved_model"] == "scripted-math"
    assert manifest["provider_settings"]["max_retries"] == 0
    assert any("math-template-v10" in item for item in manifest["prompt_versions"])
    assert manifest["rubric_versions"][0]["version"] == "math-ir-v0.1"
    assert manifest["cases"][0]["set"] == "natural"


def test_math_unsupported_prompt_records_revision_and_relevance_flag(
    monkeypatch, tmp_path
):
    valid = ir_proposal(quadratic_ir_template())
    provider = MathAuthor([unsupported_eigenvalues_proposal(), valid])
    output = _run_math(
        monkeypatch,
        tmp_path,
        case_set="unsupported",
        provider=provider,
        name="math-unsupported.jsonl",
    )

    record = _records(output)[0]
    assert record["case_set"] == "unsupported"
    assert record["status"] == record["outcome"] == "checked"
    assert record["attempts_used"] == 2
    assert provider.calls == 2
    assert "IR_VALIDATION_FAILED" in record["failed_check_codes_by_attempt"][0]["codes"]
    assert record["failed_check_codes_by_attempt"][1]["codes"] == [
        "DIFFICULTY_MISMATCH",
        "RELEVANCE_MISMATCH",
    ]
    assert record["difficulty"]["requested"] == "hard"
    assert record["difficulty"]["estimated"] == "easy"
    assert record["difficulty"]["decision"] == "advisory_mismatch"
    assert record["relevance"]["score"] == 0.1
    assert record["relevance"]["threshold"] == 0.9
    assert record["relevance"]["decision"] == "not_relevant"
    assert record["replay_passed"] is True

    summary = json.loads(output.with_suffix(".summary.json").read_text())
    assert summary["outcomes"]["checked"] == 1
    assert summary["by_set"]["unsupported"]["checked"] == 1
    assert summary["revisions"] == {"histogram": {"1": 1}, "total": 1}
    assert "IR_VALIDATION_FAILED" in summary["failure_taxonomy"]
    assert summary["difficulty_agreement"] == {"hard": {"easy": 1}}
    assert summary["relevance_flags_on_unsupported"]["counts"] == {"not_relevant": 1}
    assert summary["relevance_flags_on_unsupported"]["jobs"][0]["score"] == 0.1

    manifest = json.loads(output.with_suffix(".manifest.json").read_text())
    assert manifest["case_set"] == "unsupported"
    assert manifest["cases"][0]["set"] == "unsupported"
    assert manifest["rubric_versions"][0]["version"] == "math-ir-v0.1"


def test_code_domain_remains_the_default_with_existing_cases(monkeypatch, tmp_path):
    _install_math_application(monkeypatch)
    monkeypatch.setattr(
        evaluation, "create_model_provider", lambda selection: Provider()
    )
    monkeypatch.setattr(
        evaluation,
        "TemplateApplication",
        lambda: TemplateApplication(tool_client=RecordingClient(Executor())),
    )
    output = tmp_path / "code-default.jsonl"
    monkeypatch.setattr(
        "sys.argv",
        ["evaluate", "--jobs", "1", "--output", str(output)],
    )

    assert evaluation.main() == 0

    record = _records(output)[0]
    assert record["domain"] == "code"
    assert record["case_set"] == "natural"
    assert record["case_id"] == "addition"
    assert record["request"]["difficulty"] == "easy"
    assert record["status"] == record["outcome"] == "checked"
    assert record["attempts_used"] == 1

    manifest = json.loads(output.with_suffix(".manifest.json").read_text())
    assert manifest["domain"] == "code"
    assert manifest["cases_version"] == "authoring-baseline-v1"
    assert manifest["validator_revision"] == "test-revision"
