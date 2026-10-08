"""Completed check records and deterministic reuse across serialization."""

import copy

import pytest
from test_authoring_loop import REQUEST, Provider, proposal, run, wrong_answer

from edcraft_validator.application.authoring_contracts import AuthoringResult
from edcraft_validator.application.template_workflow import TemplateApplication
from edcraft_validator.domains.code.code_domain import CodeDomain
from edcraft_validator.domains.code.code_schemas import (
    CodeTemplateCandidate,
    ValidatedCodeTemplate,
)
from edcraft_validator.mcp.client import FastMcpToolClient


def test_report_owns_attempt_history_and_artifact_only_keeps_origin_metadata():
    provider = Provider([wrong_answer(), proposal()])
    result, _ = run(provider)
    artifact = result.artifact
    provenance = artifact.authoring

    assert result.request == REQUEST.model_dump(mode="json")
    assert not result.attempts[0].passed
    assert result.attempts[1].passed
    assert result.attempts[0].candidate["answer_expression"] == "a - b"
    assert result.attempts[1].candidate["answer_expression"] == "a + b"
    assert result.generation_duration_ms >= 0
    assert result.provider_settings == provenance.provider_settings
    assert provenance.provider_settings == {"mode": "scripted"}
    assert provenance.provider == provider.provider
    assert provenance.model == provider.model
    assert len(artifact.artifact_id) == 32
    assert not {"request", "proposal", "attempts", "tool_catalogue", "fixed_plan"} & (
        provenance.model_dump().keys()
    )
    # History uses the shared report schema; artifacts use their domain's schema.
    loaded = AuthoringResult.model_validate_json(result.model_dump_json())
    assert loaded.attempts == result.attempts
    assert loaded.model_dump(mode="json") == result.model_dump(mode="json")
    loaded_artifact = ValidatedCodeTemplate.model_validate_json(
        loaded.artifact.model_dump_json()
    )
    assert loaded_artifact.template == artifact.template
    assert loaded_artifact.validation == artifact.validation
    app = TemplateApplication()
    for seed in (0, 1, 42, -7):
        assert app.generate_question(
            loaded_artifact, domain=CodeDomain(), seed=seed
        ) == (app.generate_question(artifact, domain=CodeDomain(), seed=seed))


def test_saved_report_records_one_candidate_per_attempt_without_schema_copies():
    result, client = run(Provider([wrong_answer(), proposal()]))
    saved = result.model_dump(mode="json")
    assert "proposal" not in saved
    assert all(
        set(tool) == {"name", "description", "version"}
        for tool in saved["tool_catalogue"]
    )
    assert all(tool["version"] for tool in saved["tool_catalogue"])
    for attempt, dispatched in zip(
        saved["attempts"], (client.dispatches[:2], client.dispatches[2:]), strict=True
    ):
        assert "proposal" not in attempt
        assert "candidate_digest" not in attempt
        for execution, (_, arguments) in zip(
            attempt["executions"], dispatched, strict=True
        ):
            assert "effective_arguments" not in execution
            assert execution["requested_arguments"] == {}
            assert "candidate" not in execution["application_arguments"]
            assert arguments["candidate"] == attempt["candidate"]
            assert execution["evidence"] is not None
    semantic = result.attempts[-1].executions[0].evidence
    assert semantic.details["canonical_answers"]
    assert all(
        set(e.details) == {"tool_version"} for e in result.artifact.validation.evidence
    )


def test_saved_previews_replay_offline_with_the_same_artifact_and_seeds(monkeypatch):
    result, _ = run(Provider())
    artifact = result.artifact
    application = TemplateApplication()
    seeds = [0, 1, 42, -7]

    def unexpected_call(*args, **kwargs):
        pytest.fail("Preview and question reuse must not call a model or MCP")

    monkeypatch.setattr(Provider, "generate", unexpected_call)
    monkeypatch.setattr(Provider, "tool_turn", unexpected_call)
    monkeypatch.setattr(FastMcpToolClient, "__enter__", unexpected_call)
    monkeypatch.setattr(FastMcpToolClient, "list_tools", unexpected_call)
    monkeypatch.setattr(FastMcpToolClient, "call_tool", unexpected_call)
    previews = [
        application.generate_question(artifact, domain=CodeDomain(), seed=seed)
        for seed in seeds
    ]
    loaded = ValidatedCodeTemplate.model_validate_json(artifact.model_dump_json())
    assert loaded.artifact_id == artifact.artifact_id
    for preview in previews:
        assert preview.artifact_id == loaded.artifact_id
        assert (
            application.generate_question(
                loaded, domain=CodeDomain(), seed=preview.seed
            )
            == preview
        )


def test_a_fresh_check_run_receives_a_new_artifact_id():
    first, _ = run(Provider())
    second, _ = run(Provider())
    assert first.artifact.template.template_id == second.artifact.template.template_id
    assert first.artifact.artifact_id != second.artifact.artifact_id


def test_finalization_only_packages_checked_content_and_evidence(monkeypatch):
    result, _ = run(Provider())
    attempt = result.attempts[-1]
    candidate = CodeTemplateCandidate.model_validate(attempt.candidate)
    evidence = [execution.evidence for execution in attempt.executions]
    original = copy.deepcopy(candidate)
    original_evidence = copy.deepcopy(evidence)

    def unexpected_call(*args, **kwargs):
        pytest.fail("Finalization must only package the completed check outputs")

    monkeypatch.setattr(Provider, "generate", unexpected_call)
    monkeypatch.setattr(Provider, "tool_turn", unexpected_call)
    monkeypatch.setattr(FastMcpToolClient, "call_tool", unexpected_call)
    domain = CodeDomain()
    finalized = domain.finalize_checked_template(candidate, evidence)
    assert finalized == domain.finalize_checked_template(candidate, evidence)
    assert candidate == original
    assert evidence == original_evidence
    # Only the existing evidence-derived answer/recipe projection is permitted.
    excluded = {"answer_expression", "distractors"}
    assert finalized.template.model_dump(exclude=excluded) == candidate.model_dump(
        exclude=excluded
    )
    semantic = next(
        e for e in evidence if e.tool == "code_validate_answers_and_distractors"
    )
    assert finalized.template.answer_expression is None
    assert [c.model_dump() for c in finalized.validation.validated_cases] == [
        {"inputs": case["inputs"], "answer": case["answer"]}
        for case in semantic.details["canonical_answers"]
    ]
    assert [r.model_dump() for r in finalized.template.distractors] == semantic.details[
        "selected_distractors"
    ]
