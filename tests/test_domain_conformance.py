"""Domain conformance checklist applied to every registered question domain.

Each test names one rule a new domain must satisfy. The fixture table below
supplies a valid request, candidate, and passing tool evidence per domain so
the rules can be checked without repeating the authoring workflow.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache, partial
from pathlib import Path
from typing import Any

import pytest
from fastmcp import FastMCP
from math_helpers import ir_candidate, quadratic_ir_template

from edcraft_validator.application.difficulty_rubrics import difficulty_rubric
from edcraft_validator.domains.code.code_schemas import (
    CodeTemplateCandidate,
    CodeTemplateRequest,
)
from edcraft_validator.domains.domain_registry import available_domains, create_domain
from edcraft_validator.domains.math.math_schemas import MathTemplateRequest
from edcraft_validator.llm.judge_configuration import (
    JudgeSettings,
    configured_judge_provider,
)
from edcraft_validator.llm.judging import DEFAULT_JUDGE_TIMEOUT_SECONDS
from edcraft_validator.mcp.catalogue import resolve_domain_tools
from edcraft_validator.mcp.client import FastMcpToolClient
from edcraft_validator.mcp.server import create_validation_server
from edcraft_validator.mcp.tool_dependencies import ToolDependencies
from edcraft_validator.tools.python_execution import ExecutionResult
from edcraft_validator.validation.check_contracts import ToolEvidence, ToolFinding
from edcraft_validator.validation.check_names import (
    TEMPLATE_DIFFICULTY_CAPABILITY,
    TEMPLATE_DIFFICULTY_CHECK,
    TEMPLATE_RELEVANCE_CAPABILITY,
    TEMPLATE_RELEVANCE_CHECK,
)
from edcraft_validator.validation.property_summary import PropertyCheckSummary

EXAMPLES = Path(__file__).resolve().parents[1] / "examples/templates"

PROPERTY_FIELDS = (
    "checking_mode",
    "examples_checked",
    "execution_calls",
    "max_examples",
    "max_execution_calls",
    "timeout_seconds",
    "seed",
    "whole_domain",
    "declared_domain_size",
)


class _ArithmeticExecutor:
    """Evaluate the arithmetic fixture without launching an isolated worker."""

    def execute_batch(self, code, entry_function, inputs, *, timeout_seconds):
        return [
            ExecutionResult(ok=True, answer=item["a"] + item["b"] - item["c"])
            for item in inputs
        ]


@dataclass(frozen=True)
class DomainCase:
    """Fixtures that give a domain a valid request, candidate, and evidence."""

    request: Callable[[], Any]
    candidate: Callable[[], Any]
    required_evidence: Callable[[], list[ToolEvidence]]
    distractors: Callable[[Any], list[Any]]


@cache
def _validation_server() -> FastMCP:
    return create_validation_server(code_execution_tool=_ArithmeticExecutor())


@cache
def _cached_passing_evidence(domain_name: str) -> tuple[ToolEvidence, ...]:
    """Run the domain's required checks once through the real MCP server."""
    case = _case(domain_name)
    domain = create_domain(domain_name)
    request, candidate = case.request(), case.candidate()
    with FastMcpToolClient(_validation_server()) as client:
        return tuple(
            ToolEvidence.model_validate(
                client.call_tool(name, domain.tool_bindings(request, candidate, name))
            )
            for name in sorted(domain.required_checks(candidate))
        )


def _passing_evidence(domain_name: str) -> list[ToolEvidence]:
    return list(_cached_passing_evidence(domain_name))


def _code_request() -> CodeTemplateRequest:
    return CodeTemplateRequest(
        prompt="Create an arithmetic question.", difficulty="easy"
    )


def _code_candidate() -> CodeTemplateCandidate:
    return CodeTemplateCandidate.model_validate_json(
        (EXAMPLES / "arithmetic_linear.json").read_text()
    )


def _math_request() -> MathTemplateRequest:
    return MathTemplateRequest(
        prompt="Author a generic mathematics multiple-choice template.",
        difficulty="easy",
        num_distractors=3,
    )


def _math_candidate():
    return ir_candidate(quadratic_ir_template())


def _code_evidence() -> list[ToolEvidence]:
    return _passing_evidence("code")


def _math_evidence() -> list[ToolEvidence]:
    return _passing_evidence("math")


DOMAIN_CASES: dict[str, DomainCase] = {
    "code": DomainCase(
        request=_code_request,
        candidate=_code_candidate,
        required_evidence=_code_evidence,
        distractors=lambda candidate: candidate.distractors,
    ),
    "math": DomainCase(
        request=_math_request,
        candidate=_math_candidate,
        required_evidence=_math_evidence,
        distractors=lambda candidate: candidate.item.body.distractors,
    ),
}


def _case(domain_name: str) -> DomainCase:
    try:
        return DOMAIN_CASES[domain_name]
    except KeyError:
        pytest.fail(
            f"No conformance case for the registered domain {domain_name!r}. "
            "Add its request, candidate and evidence to DOMAIN_CASES."
        )


def _tool_dependencies() -> ToolDependencies:
    settings = JudgeSettings()
    provider_factory = partial(configured_judge_provider, settings)
    return ToolDependencies(
        execution_tool=_ArithmeticExecutor(),
        code_execution_timeout_seconds=2.0,
        property_settings=None,
        difficulty_provider_factory=provider_factory,
        difficulty_judge_timeout_seconds=DEFAULT_JUDGE_TIMEOUT_SECONDS,
        judge_settings=settings,
        fidelity_provider_factory=provider_factory,
        fidelity_timeout_seconds=60.0,
    )


def _finalized_artifact(domain_name: str):
    case = _case(domain_name)
    return create_domain(domain_name).finalize_checked_template(
        case.candidate(),
        case.required_evidence(),
        advisory_checks=frozenset(),
    )


@pytest.mark.parametrize("domain_name", available_domains())
async def test_register_tools_registers_a_domain_tagged_tool(domain_name) -> None:
    server = FastMCP(name=f"{domain_name} conformance")

    create_domain(domain_name).register_tools(server, _tool_dependencies())

    tools = await server.list_tools()
    assert any(f"domain:{domain_name}" in set(tool.tags or ()) for tool in tools)


@pytest.mark.parametrize("domain_name", available_domains())
def test_resolve_domain_tools_offers_every_required_check(domain_name) -> None:
    case = _case(domain_name)
    domain = create_domain(domain_name)
    required = domain.required_checks(case.candidate())
    assert required

    with FastMcpToolClient(_validation_server()) as client:
        offered = {
            tool["name"]
            for tool in resolve_domain_tools(
                domain.name, client, capabilities=domain.capabilities
            )
        }

    assert required <= offered


@pytest.mark.parametrize("domain_name", available_domains())
def test_tool_bindings_are_json_serialisable_for_required_checks(domain_name) -> None:
    case = _case(domain_name)
    domain = create_domain(domain_name)
    request, candidate = case.request(), case.candidate()

    for name in sorted(domain.required_checks(candidate)):
        bindings = domain.tool_bindings(request, candidate, name)
        assert isinstance(bindings, dict)
        json.dumps(bindings)


@pytest.mark.parametrize("domain_name", available_domains())
def test_finalize_accepts_passing_evidence_for_required_checks(domain_name) -> None:
    artifact = _finalized_artifact(domain_name)

    assert artifact.artifact_id is None
    assert artifact.validation.evidence


@pytest.mark.parametrize("domain_name", available_domains())
def test_finalize_rejects_a_missing_required_check(domain_name) -> None:
    case = _case(domain_name)
    domain = create_domain(domain_name)
    evidence = case.required_evidence()

    for missing in sorted(domain.required_checks(case.candidate())):
        remaining = [item for item in evidence if item.tool != missing]
        with pytest.raises(ValueError):
            domain.finalize_checked_template(
                case.candidate(), remaining, advisory_checks=frozenset()
            )


@pytest.mark.parametrize("domain_name", available_domains())
def test_finalize_rejects_a_failed_required_check(domain_name) -> None:
    case = _case(domain_name)
    domain = create_domain(domain_name)
    failed_tool = min(domain.required_checks(case.candidate()))
    evidence = [
        item.model_copy(
            update={
                "status": "failed",
                "findings": [
                    ToolFinding(
                        code="CONFORMANCE_FAILURE",
                        message="Synthetic required-check failure",
                    )
                ],
            }
        )
        if item.tool == failed_tool
        else item
        for item in case.required_evidence()
    ]

    with pytest.raises(ValueError):
        domain.finalize_checked_template(
            case.candidate(), evidence, advisory_checks=frozenset()
        )


@pytest.mark.parametrize("domain_name", available_domains())
def test_finalized_validation_uses_the_shared_property_summary(domain_name) -> None:
    case = _case(domain_name)
    summary = _finalized_artifact(domain_name).validation

    assert isinstance(summary, PropertyCheckSummary)
    assert set(PROPERTY_FIELDS) <= set(type(summary).model_fields)
    assert summary.checking_mode == "property_based"
    assert summary.examples_checked >= 1
    assert summary.execution_calls >= summary.examples_checked
    assert summary.max_execution_calls >= summary.execution_calls
    assert summary.timeout_seconds > 0
    assert isinstance(summary.whole_domain, bool)
    assert summary.declared_domain_size is not None
    assert summary.declared_domain_size >= 1
    assert isinstance(summary.seed, int)

    passed = {item.check for item in summary.evidence if item.status == "passed"}
    assert create_domain(domain_name).required_checks(case.candidate()) <= passed


@pytest.mark.parametrize("domain_name", available_domains())
def test_generate_question_is_deterministic_without_external_calls(
    domain_name, monkeypatch
) -> None:
    artifact = _finalized_artifact(domain_name)
    domain = create_domain(domain_name)
    for seed in (0, 7):
        expected = domain.generate_question(artifact, seed=seed)
        assert expected == domain.generate_question(artifact, seed=seed)

    def unexpected_call(*args, **kwargs):
        pytest.fail("Question generation must not call MCP or a model provider")

    monkeypatch.setattr(FastMcpToolClient, "__enter__", unexpected_call)
    monkeypatch.setattr(FastMcpToolClient, "list_tools", unexpected_call)
    monkeypatch.setattr(FastMcpToolClient, "call_tool", unexpected_call)
    monkeypatch.setattr(
        "edcraft_validator.bootstrap.create_tool_client", unexpected_call
    )
    monkeypatch.setattr(
        "edcraft_validator.llm.judge_configuration.configured_judge_provider",
        unexpected_call,
    )
    monkeypatch.setattr(
        "edcraft_validator.llm.decision.ConfiguredDecisionProvider", unexpected_call
    )
    monkeypatch.setattr(
        "edcraft_validator.mcp.server.create_validation_server", unexpected_call
    )

    assert domain.generate_question(artifact, seed=7) == expected


@pytest.mark.parametrize("domain_name", available_domains())
def test_distractor_count_matches_the_candidate_distractors(domain_name) -> None:
    case = _case(domain_name)
    candidate = case.candidate()
    expected = len(case.distractors(candidate))

    assert expected >= 1
    assert create_domain(domain_name).distractor_count(candidate) == expected


@pytest.mark.parametrize("domain_name", available_domains())
def test_domain_uses_the_shared_advisory_capabilities(domain_name) -> None:
    """Difficulty and relevance are shared checks, so a domain only supplies data."""
    case = _case(domain_name)
    domain = create_domain(domain_name)
    request, candidate = case.request(), case.candidate()

    assert {
        TEMPLATE_DIFFICULTY_CAPABILITY,
        TEMPLATE_RELEVANCE_CAPABILITY,
    } <= domain.capabilities

    for name in (TEMPLATE_DIFFICULTY_CHECK, TEMPLATE_RELEVANCE_CHECK):
        json.dumps(domain.tool_bindings(request, candidate, name))

    difficulty = domain.tool_bindings(request, candidate, TEMPLATE_DIFFICULTY_CHECK)
    rubric = difficulty_rubric(difficulty["rubric_id"])
    assert rubric.rubric_id == difficulty["rubric_id"]
    assert rubric.dimensions_model.model_fields


@pytest.mark.parametrize("domain_name", available_domains())
def test_failed_advisory_evidence_never_blocks_finalization(domain_name) -> None:
    """Advisory checks are never required, so their failure stays advisory."""
    case = _case(domain_name)
    domain = create_domain(domain_name)
    request, candidate = case.request(), case.candidate()

    assert {
        TEMPLATE_DIFFICULTY_CHECK,
        TEMPLATE_RELEVANCE_CHECK,
    }.isdisjoint(domain.required_checks(candidate))

    bindings = domain.tool_bindings(request, candidate, TEMPLATE_DIFFICULTY_CHECK)
    failed = ToolEvidence(
        tool=TEMPLATE_DIFFICULTY_CHECK,
        version="conformance",
        status="failed",
        findings=[
            ToolFinding(
                code="ADVISORY_MISMATCH",
                message="Synthetic advisory mismatch",
            )
        ],
        details={"subject_sha256": bindings["subject_sha256"]},
    )

    artifact = domain.finalize_checked_template(
        candidate,
        [*case.required_evidence(), failed],
        advisory_checks=frozenset({TEMPLATE_DIFFICULTY_CHECK}),
    )

    saved = next(
        item
        for item in artifact.validation.evidence
        if item.check == TEMPLATE_DIFFICULTY_CHECK
    )
    assert saved.status == "failed"
    assert saved.details["advisory"] is True
