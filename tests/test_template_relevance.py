"""Authoring relevance checks, independent judging and saved evidence."""

import json

import pytest
from fastmcp import Client
from judge_helpers import TemplateJudge, candidate, proposal
from test_authoring_loop import REQUEST, SEMANTIC, STRUCTURE, Executor, Provider

from edcraft_validator.application.template_workflow import TemplateApplication
from edcraft_validator.domains.code.candidate_builder import template_sha256
from edcraft_validator.domains.code.code_domain import CodeDomain
from edcraft_validator.domains.code.code_schemas import (
    CodeTemplateCandidate,
    ValidatedCodeTemplate,
)
from edcraft_validator.domains.code.relevance import (
    TEMPLATE_RELEVANCE_TOOL,
    template_relevance_input,
)
from edcraft_validator.domains.code.template_difficulty import (
    TEMPLATE_DIFFICULTY_TOOL,
)
from edcraft_validator.llm.usage import TokenUsage
from edcraft_validator.mcp.client import FastMcpToolClient
from edcraft_validator.mcp.server import create_validation_server


class RelevanceJudge:
    provider, model = "scripted", "relevance-judge"
    threshold = 0.94

    def __init__(self, score=0.99, failure=None):
        self.value = score
        self.failure = failure
        self.texts = []
        self.last_usage = TokenUsage()
        self.closed = False

    def generation_settings(self):
        return {"reasoning": "none", "mode": "scripted"}

    def score(self, request_text, question_text):
        self.texts.append((request_text, question_text))
        self.last_usage = TokenUsage(input_tokens=20, output_tokens=1)
        if self.failure is not None:
            raise self.failure
        return self.value

    def close(self):
        self.closed = True


class NoExecution:
    def execute_batch(self, *args, **kwargs):
        pytest.fail("Template relevance must not execute Python")


def run(
    *,
    scores=(),
    estimates=(),
    relevance_failure=None,
    proposals=None,
    plan=None,
):
    relevance_judges, difficulty_judges = [], []
    pending_scores, pending_estimates = iter(scores), iter(estimates)

    def relevance_factory():
        judge = (
            RelevanceJudge(failure=relevance_failure)
            if relevance_failure is not None
            else RelevanceJudge(next(pending_scores))
        )
        relevance_judges.append(judge)
        return judge

    def difficulty_factory():
        judge = TemplateJudge(next(pending_estimates))
        difficulty_judges.append(judge)
        return judge

    author = Provider(
        proposals=proposals,
        plan=plan
        or (
            SEMANTIC,
            STRUCTURE,
            TEMPLATE_DIFFICULTY_TOOL,
            TEMPLATE_RELEVANCE_TOOL,
        ),
    )
    server = create_validation_server(
        difficulty_provider_factory=difficulty_factory,
        decision_provider_factory=relevance_factory,
        code_execution_tool=Executor(),
    )
    result = TemplateApplication(tool_client=FastMcpToolClient(server)).author_template(
        REQUEST, domain=CodeDomain(), provider=author
    )
    return result, author, difficulty_judges, relevance_judges


@pytest.mark.parametrize(
    ("score", "failure", "status", "finding"),
    [
        (0.99, None, "passed", None),
        (0.1, None, "failed", "RELEVANCE_MISMATCH"),
        (None, RuntimeError("PRIVATE MODEL ERROR"), "error", "RELEVANCE_FAILED"),
    ],
)
async def test_direct_mcp_maps_relevance_status_and_saves_evidence(
    score, failure, status, finding
):
    judge = RelevanceJudge(score=score, failure=failure)
    original = candidate()
    server = create_validation_server(
        decision_provider_factory=lambda: judge,
        code_execution_tool=NoExecution(),
    )
    async with Client(server) as client:
        result = await client.call_tool(
            TEMPLATE_RELEVANCE_TOOL,
            {
                "candidate": original.model_dump(mode="json"),
                "author_request": REQUEST.prompt,
            },
        )
    evidence = result.structured_content
    assert evidence["status"] == status
    assert evidence["tool"] == TEMPLATE_RELEVANCE_TOOL
    assert evidence["details"]["template_sha256"] == template_sha256(original)
    assert (
        evidence["details"]["relevance"]["decision"]["request_text"] == REQUEST.prompt
    )
    assert evidence["details"]["provider"] == judge.provider
    assert evidence["details"]["model"] == judge.model
    assert evidence["details"]["threshold"] == judge.threshold
    assert evidence["details"]["advisory"] is True
    if finding is None:
        assert evidence["findings"] == []
        assert evidence["details"]["score"] == score
        assert evidence["details"]["relevant"] is True
        assert evidence["details"]["usage"]["model_call_count"] == 1
    else:
        assert evidence["findings"][0]["code"] == finding
        assert evidence["details"]["retryable"] is False
    if status == "error":
        assert "PRIVATE MODEL ERROR" not in result.content[0].text


def test_template_projection_keeps_learner_task_and_omits_answer_and_reasons():
    original = candidate()
    changed = original.model_copy(
        update={
            "template_id": "different",
            "topic": "loops",
            "difficulty": "hard",
            "answer_expression": "a - b",
        },
        deep=True,
    )
    changed.distractors[0].reason_template = "Different misconception reason."
    first = template_relevance_input(original, REQUEST.prompt)
    second = template_relevance_input(changed, REQUEST.prompt)
    assert first.sha256 == second.sha256
    assert original.code in first.question_text
    assert original.question_template in first.question_text
    assert f"Answer target: {original.answer_target}\n" in first.question_text
    assert (
        "Parameter values: "
        + json.dumps({p.name: p.values for p in original.parameters})
        + "\n"
    ) in first.question_text
    for excluded in (
        "different",
        "loops",
        "hard",
        "a - b",
        "Repeats answer.",
        "Different misconception reason.",
    ):
        assert excluded not in first.question_text
    assert first.author_request == REQUEST.prompt
    changed.code += "\n# changed learner task"
    assert template_relevance_input(changed, REQUEST.prompt).sha256 != first.sha256


def test_advisory_relevance_mismatch_is_saved_and_replays_without_models(
    monkeypatch,
):
    result, author, difficulty_judges, relevance_judges = run(
        scores=[0.1], estimates=["easy"]
    )
    assert result.status == "checked" and len(result.attempts) == 1
    assert len(author.generations) == len(relevance_judges) == 1
    assert len(difficulty_judges) == 1
    assert all(len(judge.texts) == 1 for judge in relevance_judges)

    execution = next(
        item
        for item in result.attempts[0].executions
        if item.tool == TEMPLATE_RELEVANCE_TOOL
    )
    assert execution.evidence.status == "failed"
    assert execution.evidence.findings[0].code == "RELEVANCE_MISMATCH"
    assert execution.requested_arguments == {}
    assert execution.application_arguments["author_request"] == REQUEST.prompt

    saved = next(
        item
        for item in result.artifact.validation.evidence
        if item.check == TEMPLATE_RELEVANCE_TOOL
    )
    details = saved.details
    assert saved.status == "failed"
    assert details["advisory"] is True
    assert details["template_sha256"] == template_sha256(result.artifact.template)
    assert details["score"] == details["relevance"]["decision"]["score"] == 0.1
    assert details["threshold"] == details["relevance"]["decision"]["threshold"] == 0.94
    assert details["provider"] == "scripted"
    assert details["usage"]["model_call_count"] == 1
    assert result.request["prompt"] == REQUEST.prompt

    stale = [
        item.evidence.model_copy(deep=True) for item in result.attempts[0].executions
    ]
    next(item for item in stale if item.tool == TEMPLATE_RELEVANCE_TOOL).details[
        "template_sha256"
    ] = "stale"
    stale_artifact = CodeDomain().finalize_checked_template(
        CodeTemplateCandidate.model_validate(result.attempts[0].candidate), stale
    )
    stale_saved = next(
        item
        for item in stale_artifact.validation.evidence
        if item.check == TEMPLATE_RELEVANCE_TOOL
    )
    assert stale_saved.status == "incomplete"
    assert stale_saved.details["unavailable"] is True

    loaded = ValidatedCodeTemplate.model_validate_json(
        result.artifact.model_dump_json()
    )
    loaded_saved = next(
        item
        for item in loaded.validation.evidence
        if item.check == TEMPLATE_RELEVANCE_TOOL
    )
    assert loaded_saved.status == "failed"
    assert loaded_saved.details["advisory"] is True
    assert loaded_saved.details["template_sha256"] == template_sha256(loaded.template)

    def unexpected_call(*args, **kwargs):
        pytest.fail("Model-free replay must not call a model, MCP or executor")

    monkeypatch.setattr(Provider, "generate", unexpected_call)
    monkeypatch.setattr(FastMcpToolClient, "__enter__", unexpected_call)
    monkeypatch.setattr(FastMcpToolClient, "list_tools", unexpected_call)
    monkeypatch.setattr(FastMcpToolClient, "call_tool", unexpected_call)
    monkeypatch.setattr(Executor, "execute_batch", unexpected_call)
    application = TemplateApplication()
    for seed in (0, 7, 42):
        expected = application.generate_question(
            result.artifact, domain=CodeDomain(), seed=seed
        )
        assert (
            application.generate_question(loaded, domain=CodeDomain(), seed=seed)
            == expected
        )


def test_advisory_relevance_mismatch_does_not_revise_or_exhaust_attempts():
    result, author, difficulty_judges, relevance_judges = run(
        scores=[0.1], estimates=["easy"]
    )
    assert result.status == "checked" and result.artifact is not None
    assert len(result.attempts) == len(author.generations) == 1
    assert len(relevance_judges) == len(difficulty_judges) == 1
    assert result.warnings[0].code == "RELEVANCE_MISMATCH"


def test_relevance_model_error_is_unavailable_without_author_revision():
    result, author, difficulty_judges, relevance_judges = run(
        estimates=["easy"],
        relevance_failure=RuntimeError("PRIVATE MODEL ERROR"),
        plan=(
            TEMPLATE_RELEVANCE_TOOL,
            TEMPLATE_DIFFICULTY_TOOL,
            SEMANTIC,
            STRUCTURE,
        ),
    )
    assert result.status == "checked" and result.artifact is not None
    assert len(result.attempts) == len(author.generations) == 1
    assert len(relevance_judges) == 1 and len(difficulty_judges) == 1
    execution = next(
        item
        for item in result.attempts[0].executions
        if item.tool == TEMPLATE_RELEVANCE_TOOL
    )
    assert execution.evidence.status == "error"
    assert execution.evidence.findings[0].code == "RELEVANCE_FAILED"
    assert execution.evidence.details["retryable"] is False
    assert execution.evidence.details["relevance_outcome"]["unavailable"] is True
    saved = next(
        item
        for item in result.artifact.validation.evidence
        if item.check == TEMPLATE_RELEVANCE_TOOL
    )
    assert saved.status == "incomplete" and saved.details["unavailable"] is True
    assert "PRIVATE MODEL ERROR" not in result.model_dump_json()


def test_correctness_failure_skips_both_assessments_without_judge_calls():
    wrong = proposal().model_copy(update={"answer_expression": "a - b"})
    result, author, difficulty_judges, relevance_judges = run(proposals=[wrong])
    assert result.status == "needs_review" and result.artifact is None
    assert len(result.attempts) == len(author.generations) == 4
    assert difficulty_judges == relevance_judges == []
    for attempt in result.attempts:
        assert attempt.pending == [TEMPLATE_DIFFICULTY_TOOL, TEMPLATE_RELEVANCE_TOOL]
        for name in (TEMPLATE_DIFFICULTY_TOOL, TEMPLATE_RELEVANCE_TOOL):
            execution = next(item for item in attempt.executions if item.tool == name)
            assert execution.skip_reason == "Prerequisite checks did not pass"
            assert execution.evidence is None


@pytest.mark.parametrize(
    "plan",
    [
        (TEMPLATE_RELEVANCE_TOOL, TEMPLATE_DIFFICULTY_TOOL, SEMANTIC, STRUCTURE),
        (TEMPLATE_DIFFICULTY_TOOL, TEMPLATE_RELEVANCE_TOOL, SEMANTIC, STRUCTURE),
    ],
)
def test_assessments_run_independently_in_either_order(plan):
    result, _, difficulty_judges, relevance_judges = run(
        scores=[0.1], estimates=["hard"], plan=plan
    )
    assert result.status == "checked" and len(result.attempts) == 1
    assert len(relevance_judges) == len(difficulty_judges) == 1
    executions = {
        item.tool: item
        for item in result.attempts[0].executions
        if item.tool in {TEMPLATE_RELEVANCE_TOOL, TEMPLATE_DIFFICULTY_TOOL}
    }
    assert set(executions) == {TEMPLATE_RELEVANCE_TOOL, TEMPLATE_DIFFICULTY_TOOL}
    assert all(item.evidence is not None for item in executions.values())
    assert all(item.evidence.status == "failed" for item in executions.values())
    assert all(item.advisory for item in executions.values())
    candidates = [
        item.application_arguments["candidate"] for item in executions.values()
    ]
    assert candidates[0] == candidates[1]
    checked = CodeTemplateCandidate.model_validate(candidates[0])
    assert {
        item.evidence.details["template_sha256"] for item in executions.values()
    } == {template_sha256(checked)}
