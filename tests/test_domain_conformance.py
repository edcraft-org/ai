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

from edcraft_validator.domains.code.code_schemas import (
    CodeTemplateCandidate,
    CodeTemplateRequest,
)
from edcraft_validator.domains.domain_registry import available_domains, create_domain
from edcraft_validator.domains.math.math_schemas import MathTemplateRequest
from edcraft_validator.llm.judge_configuration import (
    configured_judge_provider,
    load_judge_settings,
)
from edcraft_validator.llm.judging import DEFAULT_JUDGE_TIMEOUT_SECONDS
from edcraft_validator.mcp.catalogue import resolve_domain_tools
from edcraft_validator.mcp.client import FastMcpToolClient
from edcraft_validator.mcp.server import create_validation_server
from edcraft_validator.mcp.tool_dependencies import ToolDependencies
from edcraft_validator.tools.python_execution import ExecutionResult
from edcraft_validator.validation.check_contracts import ToolEvidence, ToolFinding
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
    case = DOMAIN_CASES[domain_name]
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


def _tool_dependencies() -> ToolDependencies:
    settings = load_judge_settings()
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
    case = DOMAIN_CASES[domain_name]
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
    case = DOMAIN_CASES[domain_name]
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
    case = DOMAIN_CASES[domain_name]
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
    case = DOMAIN_CASES[domain_name]
    domain = create_domain(domain_name)
    missing = min(domain.required_checks(case.candidate()))
    remaining = [item for item in case.required_evidence() if item.tool != missing]

    with pytest.raises(ValueError):
        domain.finalize_checked_template(
            case.candidate(), remaining, advisory_checks=frozenset()
        )


@pytest.mark.parametrize("domain_name", available_domains())
def test_finalize_rejects_a_failed_required_check(domain_name) -> None:
    case = DOMAIN_CASES[domain_name]
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
    case = DOMAIN_CASES[domain_name]
    summary = _finalized_artifact(domain_name).validation

    assert isinstance(summary, PropertyCheckSummary)
    assert set(PROPERTY_FIELDS) <= set(type(summary).model_fields)
    assert summary.checking_mode == "property_based"
    assert summary.examples_checked >= 1
    assert summary.execution_calls >= summary.examples_checked
    assert summary.max_execution_calls >= summary.execution_calls
    assert summary.timeout_seconds > 0
    assert isinstance(summary.whole_domain, bool)
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
    case = DOMAIN_CASES[domain_name]
    candidate = case.candidate()
    expected = len(case.distractors(candidate))

    assert expected >= 1
    assert create_domain(domain_name).distractor_count(candidate) == expected
