"""Public-engine outcomes, resource limits and MCP integration."""

import pytest
from fastmcp import Client

from edcraft_validator.application.math_correctness import check_math_correctness
from edcraft_validator.domains.math.engine.contracts import CorrectnessRequest
from edcraft_validator.mcp.server import create_validation_server


def derivative_request(coefficient="3"):
    return {
        "problem": {
            "operation": "differentiate",
            "symbols": [{"name": "x"}],
            "variable": "x",
            "expression": {"op": "pow", "args": [{"sym": "x"}, {"num": "3"}]},
        },
        "answer": {
            "expression": {
                "op": "mul",
                "args": [
                    {"num": coefficient},
                    {"op": "pow", "args": [{"sym": "x"}, {"num": "2"}]},
                ],
            }
        },
    }


def test_public_check_is_exact_and_isolated():
    correct = check_math_correctness(derivative_request())
    wrong = check_math_correctness(derivative_request("4"))
    assert correct.outcome == "correct"
    assert wrong.outcome == "incorrect"
    assert correct.sympy_version
    assert correct.engine_version == "math-correctness/1"
    assert correct.duration_ms > 0


def test_unknown_operation_and_unknown_symbols_fail_safely():
    request = derivative_request()
    request["problem"]["operation"] = "execute_python"
    assert check_math_correctness(request).outcome == "error"
    request = derivative_request()
    request["answer"] = {"expression": {"sym": "undeclared"}}
    assert check_math_correctness(request).outcome == "error"


def test_model_construct_does_not_bypass_revalidation():
    request = CorrectnessRequest.model_construct(
        problem={"operation": "exec"}, answer={}
    )
    assert check_math_correctness(request).outcome == "error"


@pytest.mark.parametrize("literal", ["1e999999999", "1" * 130, "nan"])
def test_oversized_literals_fail_before_computation(literal):
    request = derivative_request(literal)
    assert check_math_correctness(request).outcome == "unsupported"


def test_unsupported_operator_does_not_execute():
    request = derivative_request()
    request["answer"]["expression"] = {"op": "__import__", "args": []}
    assert check_math_correctness(request).outcome == "unsupported"


def test_hard_deadline_returns_timeout():
    result = check_math_correctness(derivative_request(), timeout_seconds=0.000001)
    assert result.outcome == "timeout"


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf"), True])
def test_invalid_deadline_is_rejected(timeout):
    with pytest.raises(ValueError):
        check_math_correctness(derivative_request(), timeout_seconds=timeout)


async def test_mcp_exposes_one_deterministic_correctness_check():
    async with Client(create_validation_server()) as client:
        result = await client.call_tool(
            "math_check_correctness", {"request": derivative_request()}
        )
        tools = await client.list_tools()
    assert not result.is_error
    evidence = result.structured_content
    assert evidence["status"] == "passed"
    assert evidence["details"]["outcome"] == "correct"
    tool = next(t for t in tools if t.name == "math_check_correctness")
    assert not tool.annotations.open_world_hint
    assert tool.annotations.idempotent_hint


def test_request_json_roundtrip_preserves_answer_kind():
    request = CorrectnessRequest.model_validate(derivative_request())
    assert CorrectnessRequest.model_validate(request.model_dump(mode="json")) == request


def test_nested_literal_powers_are_bounded_before_evaluation():
    request = derivative_request()
    huge = {"num": "2"}
    for _ in range(12):
        huge = {"op": "pow", "args": [huge, {"num": "12"}]}
    request["answer"] = {"expression": huge}
    assert check_math_correctness(request).outcome == "unsupported"
