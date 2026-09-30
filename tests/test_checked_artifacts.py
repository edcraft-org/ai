"""Completed check records and deterministic reuse across serialization."""

import copy
import json

import pytest
from test_authoring_loop import REQUEST, Provider, proposal, run, wrong_answer

from edcraft_validator.application.template_workflow import TemplateApplication
from edcraft_validator.domains.code.code_domain import CodeDomain
from edcraft_validator.domains.code.code_schemas import (
    CodeTemplateCandidate,
    ValidatedCodeTemplate,
)
from edcraft_validator.mcp.client import FastMcpToolClient


def test_completed_artifact_retains_final_proposal_and_full_check_record():
    provider = Provider([wrong_answer(), proposal()])
    result, _ = run(provider)
    artifact = result.artifact
    provenance = artifact.authoring

    assert provenance.request == REQUEST.model_dump(mode="json")
    assert provenance.proposal == result.proposal == result.attempts[-1].proposal
    assert provenance.fixed_plan == result.fixed_plan
    assert provenance.tool_catalogue == result.tool_catalogue
    assert provenance.attempts == [a.model_dump(mode="json") for a in result.attempts]
    assert not provenance.attempts[0]["passed"]
    assert provenance.attempts[1]["passed"]
    assert provenance.provider_settings == {"mode": "scripted"}
    assert provenance.provider == provider.provider
    assert provenance.model == provider.model
    assert {"proposal", "checks"} <= set(provenance.response_schema["properties"])
    assert any(REQUEST.prompt in m["content"] for m in provenance.generation_messages)
    assert any(
        "code_validate_answers_and_distractors" in m["content"]
        for m in provenance.generation_messages
    )
    assert artifact.artifact_id.startswith("sha256:")
    assert artifact.generator_version == "code-question-v1"


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
    assert loaded.with_authoring(loaded.authoring).artifact_id == artifact.artifact_id
    for preview in previews:
        assert preview.artifact_id == loaded.artifact_id
        assert (
            application.generate_question(
                loaded, domain=CodeDomain(), seed=preview.seed
            )
            == preview
        )


@pytest.mark.parametrize(
    "field",
    ["proposal", "fixed_plan", "tool_catalogue", "provider_settings", "attempts"],
)
def test_new_check_record_gets_a_different_identity(field):
    result, _ = run(Provider())
    artifact = result.artifact
    record = artifact.authoring.model_dump(mode="python")
    if field == "proposal":
        record[field]["question_template"] += " Explain your answer."
    elif field == "fixed_plan":
        record[field] = list(reversed(record[field]))
    elif field == "tool_catalogue":
        record[field][0]["description"] += " Updated tool."
    elif field == "provider_settings":
        record[field]["mode"] = "another-setting"
    else:
        record[field][0]["executions"][0]["evidence"]["version"] = "new-version"
    updated = artifact.with_authoring(type(artifact.authoring).model_validate(record))
    assert updated.artifact_id != artifact.artifact_id


def test_identity_includes_finalized_generation_content():
    result, _ = run(Provider())
    artifact = result.artifact
    updated = artifact.model_copy(deep=True)
    updated.validation.validated_cases[0].answer = 999
    assert updated.with_authoring(updated.authoring).artifact_id != artifact.artifact_id


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


def test_previous_provenance_schema_requires_fresh_checks():
    from pydantic import ValidationError

    result, _ = run(Provider())
    payload = json.loads(result.artifact.model_dump_json())
    del payload["authoring"]["provider_settings"]
    with pytest.raises(ValidationError, match="provider_settings"):
        ValidatedCodeTemplate.model_validate_json(json.dumps(payload))
