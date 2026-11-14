"""Error paths of the isolated math validation tools."""

from __future__ import annotations

import pytest

from edcraft_validator.domains.math.ir.schema import (
    Distractor,
    Expr,
    Given,
    Goal,
    MathItemSpec,
    Relation,
    SymbolSpec,
    TextSpec,
)
from edcraft_validator.domains.math.validation.isolation import (
    ValidationTimeout,
    ValidationWorkerError,
)
from edcraft_validator.mcp import math_tools
from edcraft_validator.mcp.math_tools import MathSpecRequest, verify_item_spec


def item() -> MathItemSpec:
    return MathItemSpec(
        topic="school.linear_equation",
        symbols=[SymbolSpec(name="x", domain="real")],
        givens=[
            Given(
                id="equation",
                relation=Relation(kind="eq", lhs=Expr(sym="x"), rhs=Expr(num="2")),
            )
        ],
        goal=Goal(kind="solve", symbol="x"),
        text=TextSpec(mode="symbolic", template="Solve x = 2."),
    )


def request() -> MathSpecRequest:
    return MathSpecRequest(item=item())


def test_timeout_is_reported_as_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def timeout(*args: object, **kwargs: object) -> dict:
        raise ValidationTimeout("math validation exceeded 1s")

    monkeypatch.setattr(math_tools, "run_isolated", timeout)

    evidence = verify_item_spec(request())

    assert evidence.status == "error"
    assert [finding.code for finding in evidence.findings] == ["VALIDATION_TIMEOUT"]


def test_worker_failure_is_reported_as_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failure(*args: object, **kwargs: object) -> dict:
        raise ValidationWorkerError("worker exited with 1")

    monkeypatch.setattr(math_tools, "run_isolated", failure)

    evidence = verify_item_spec(request())

    assert evidence.status == "error"
    assert [finding.code for finding in evidence.findings] == [
        "VALIDATION_WORKER_ERROR"
    ]


def test_non_object_report_is_malformed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(math_tools, "run_isolated", lambda *a, **k: {"report": []})

    evidence = verify_item_spec(request())

    assert evidence.status == "error"
    assert [finding.code for finding in evidence.findings] == [
        "VALIDATION_RESPONSE_MALFORMED"
    ]


def test_unknown_worker_status_routes_to_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        math_tools,
        "run_isolated",
        lambda *a, **k: {
            "report": {"report": {"status": "surprising", "findings": []}}
        },
    )

    evidence = verify_item_spec(request())

    assert evidence.status == "failed"
    assert evidence.details["ir_status"] == "inconclusive"
    assert evidence.details["routes_to_review"] is True
    assert [finding.code for finding in evidence.findings] == [
        "IR_VALIDATION_INCONCLUSIVE"
    ]


def test_engine_and_form_checks_reach_tool_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checks = [
        {"check": "engine_correctness", "status": "passed", "reason": ""},
        {"check": "form", "status": "passed", "reason": ""},
    ]
    monkeypatch.setattr(
        math_tools,
        "run_isolated",
        lambda *a, **k: {
            "report": {
                "report": {"status": "passed", "findings": [], "checks": checks}
            },
            "variants_checked": 1,
            "variants_total": 1,
        },
    )

    evidence = verify_item_spec(request())

    assert evidence.status == "passed"
    assert [check["check"] for check in evidence.details["checks"]] == [
        "engine_correctness",
        "form",
    ]


def test_option_findings_do_not_hide_the_answer_finding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        math_tools,
        "run_isolated",
        lambda *a, **k: {
            "report": {
                "report": {
                    "status": "failed",
                    "findings": ["engine_correctness: the engine returned 'incorrect'"],
                    "options": [
                        {
                            "index": 0,
                            "value": "4",
                            "result": {"status": "failed", "reason": "duplicate"},
                        }
                    ],
                }
            }
        },
    )
    from edcraft_validator.mcp.math_tools import MathOptionsRequest, validate_options

    option_item = item().model_copy(
        update={"distractors": [Distractor(value=Expr(num="4"), misconception="copy")]}
    )
    evidence = validate_options(MathOptionsRequest(item=option_item))

    assert evidence.status == "failed"
    assert evidence.details["findings"] == [
        "engine_correctness: the engine returned 'incorrect'",
        "option 0: duplicate",
    ]
