import asyncio
import threading
from pathlib import Path
from textwrap import indent

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from edcraft_validator.domains.code.code_schemas import CodeTemplateCandidate
from edcraft_validator.mcp import code_tools
from edcraft_validator.mcp.code_tools import CODE_TOOL_VERSION
from edcraft_validator.mcp.server import create_validation_server
from edcraft_validator.tools.python_execution import ExecutionResult


def candidate() -> CodeTemplateCandidate:
    return CodeTemplateCandidate.model_validate_json(
        Path("examples/templates/arithmetic_linear.json").read_text()
    )


class ArithmeticExecutor:
    def __init__(self) -> None:
        self.calls = 0

    def execute_batch(self, code, entry_function, inputs, *, timeout_seconds):
        self.calls += 1
        return [
            ExecutionResult(ok=True, answer=item["a"] + item["b"] - item["c"])
            for item in inputs
        ]


async def call_tool(server, name: str, arguments: dict) -> dict:
    async with Client(server) as client:
        result = await client.call_tool(name, arguments)
    assert not result.is_error
    assert result.structured_content is not None
    return result.structured_content


async def test_catalogue_exposes_authoritative_names_descriptions_and_schemas():
    async with Client(create_validation_server()) as client:
        tools = await client.list_tools()

    assert [tool.name for tool in tools] == [
        "code_verify_template_structure",
        "code_validate_answers_and_distractors",
        "code_require_features",
    ]
    for tool in tools:
        assert tool.description
        assert tool.input_schema["additionalProperties"] is False
        assert tool.output_schema["properties"]["status"]["enum"] == [
            "passed",
            "failed",
            "error",
        ]
        assert tool.output_schema["properties"]["version"]["minLength"] == 1
    executable = next(
        tool for tool in tools if tool.name == "code_validate_answers_and_distractors"
    )
    assert "supported Python subset" in executable.description
    assert "bounded trace" in executable.description
    assert "resource-limit termination produces error evidence" in (
        executable.description
    )


async def test_structure_and_feature_tools_are_independently_callable():
    template = candidate()
    server = create_validation_server(execution_tool=ArithmeticExecutor())

    structure = await call_tool(
        server,
        "code_verify_template_structure",
        {"candidate": template.model_dump(mode="json")},
    )
    features = await call_tool(
        server,
        "code_require_features",
        {
            "candidate": template.model_dump(mode="json"),
            "required": ["arithmetic"],
        },
    )

    assert structure["status"] == "passed"
    assert structure["assurance"] == "bounded"
    assert structure["version"] == CODE_TOOL_VERSION
    assert structure["details"]["cases"] == 8
    assert features["status"] == "passed"
    assert features["details"] == {
        "required": ["arithmetic"],
        "observed": ["arithmetic"],
    }


async def test_missing_required_feature_is_a_validation_failure():
    result = await call_tool(
        create_validation_server(),
        "code_require_features",
        {
            "candidate": candidate().model_dump(mode="json"),
            "required": ["loop"],
        },
    )

    assert result["status"] == "failed"
    assert result["findings"][0]["code"] == "REQUIRED_FEATURE_MISSING"
    assert result["details"]["missing"] == ["loop"]


@pytest.mark.parametrize(
    "placement, expected_status",
    [
        ("uncalled_global", "failed"),
        ("uncalled_local", "failed"),
        ("called_only_by_uncalled_local", "failed"),
        ("called_global", "passed"),
    ],
)
async def test_required_nested_features_must_be_in_reachable_functions(
    placement, expected_status
):
    helper = (
        "def helper(n):\n"
        "    for i in range(n):\n"
        "        for j in range(n):\n"
        "            pass\n"
        "    if n:\n"
        "        if n > 1:\n"
        "            return 1\n"
        "    return 0\n"
    )
    programs = {
        "uncalled_global": (
            "def calculate(a, b, c):\n    return a + b - c\n\n" + helper
        ),
        "uncalled_local": (
            "def calculate(a, b, c):\n"
            + indent(helper, "    ")
            + "    return a + b - c\n"
        ),
        "called_only_by_uncalled_local": (
            "def calculate(a, b, c):\n"
            "    def unused():\n"
            "        return helper(a)\n"
            "    return a + b - c\n\n" + helper
        ),
        "called_global": (
            "def calculate(a, b, c):\n    return a + b - c + helper(a)\n\n" + helper
        ),
    }
    template = candidate().model_copy(update={"code": programs[placement]})

    result = await call_tool(
        create_validation_server(),
        "code_require_features",
        {
            "candidate": template.model_dump(mode="json"),
            "required": ["nested_loop", "nested_conditional"],
        },
    )

    assert result["status"] == expected_status
    if expected_status == "failed":
        assert result["findings"][0]["code"] == "REQUIRED_FEATURE_MISSING"
        assert result["details"]["missing"] == ["nested_conditional", "nested_loop"]
        assert result["details"]["observed"] == ["arithmetic"]
    else:
        assert {"loop", "nested_loop", "conditional", "nested_conditional"} <= set(
            result["details"]["observed"]
        )


@pytest.mark.parametrize(
    "tool_name, arguments",
    [
        ("code_verify_template_structure", {}),
        ("code_require_features", {"required": ["arithmetic"]}),
        ("code_validate_answers_and_distractors", {"required_distractors": 3}),
    ],
)
async def test_mcp_deadline_returns_error_without_waiting_for_synchronous_work(
    monkeypatch, tool_name, arguments
):
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def block():
        started.set()
        try:
            release.wait(timeout=10)
        finally:
            finished.set()

    class SlowExecutor(ArithmeticExecutor):
        def execute_batch(self, code, entry_function, inputs, *, timeout_seconds):
            block()
            return super().execute_batch(
                code, entry_function, inputs, timeout_seconds=timeout_seconds
            )

    if tool_name != "code_validate_answers_and_distractors":
        original_check = code_tools.check_structure

        def slow_structure(context):
            block()
            return original_check(context)

        monkeypatch.setattr(code_tools, "check_structure", slow_structure)
        monkeypatch.setattr(code_tools, "STATIC_TOOL_TIMEOUT_SECONDS", 0.1)

    server = create_validation_server(
        execution_tool=SlowExecutor(), timeout_seconds=0.001
    )
    try:
        result = await asyncio.wait_for(
            call_tool(
                server,
                tool_name,
                {"candidate": candidate().model_dump(mode="json"), **arguments},
            ),
            timeout=5,
        )
        assert started.is_set()
        assert not finished.is_set()
        assert result["status"] == "error"
        assert result["findings"][0]["code"] == "CHECK_TIMEOUT"
        assert result["details"] == {}
    finally:
        # Python cannot kill threads. Release the fake work even if the test fails.
        release.set()
        if started.is_set():
            assert await asyncio.to_thread(finished.wait, 2)


async def test_semantic_tool_executes_once_and_returns_canonical_results():
    executor = ArithmeticExecutor()
    template = candidate()
    original = template.model_copy(deep=True)

    result = await call_tool(
        create_validation_server(execution_tool=executor),
        "code_validate_answers_and_distractors",
        {
            "candidate": template.model_dump(mode="json"),
            "required_distractors": 3,
        },
    )

    assert result["status"] == "passed"
    assert result["assurance"] == "exhaustive"
    assert executor.calls == 1
    assert template == original
    assert [item["answer"] for item in result["details"]["canonical_answers"]] == [
        6,
        4,
        9,
        7,
        8,
        6,
        11,
        9,
    ]
    assert len(result["details"]["selected_distractors"]) == 3


async def test_wrong_proposed_answer_fails_before_distractor_validation():
    executor = ArithmeticExecutor()
    template = candidate().model_copy(update={"answer_expression": "a + b + c"})

    result = await call_tool(
        create_validation_server(execution_tool=executor),
        "code_validate_answers_and_distractors",
        {
            "candidate": template.model_dump(mode="json"),
            "required_distractors": 3,
        },
    )

    assert result["status"] == "failed"
    assert result["findings"][0]["code"] == "PROPOSED_ANSWER_MISMATCH"
    assert result["details"]["cases"] == 8
    assert len(result["details"]["mismatches"]) == 8
    assert executor.calls == 1


async def test_insufficient_model_distractors_fails_without_fallbacks():
    executor = ArithmeticExecutor()
    template = candidate()
    invalid = template.distractors[0].model_copy(
        update={"expression": template.answer_expression}
    )
    template = template.model_copy(
        update={"distractors": [invalid, *template.distractors[1:]]}, deep=True
    )

    result = await call_tool(
        create_validation_server(execution_tool=executor),
        "code_validate_answers_and_distractors",
        {
            "candidate": template.model_dump(mode="json"),
            "required_distractors": 3,
        },
    )

    assert result["status"] == "failed"
    assert result["findings"][0]["code"] == "DISTRACTOR_SELECTION_FAILED"
    assert executor.calls == 1


@pytest.mark.parametrize(
    "error_code",
    [
        "EXECUTION_TIMEOUT",
        "RESOURCE_LIMIT_EXCEEDED",
        "TRACE_LIMIT_EXCEEDED",
        "TOOL_FAILURE",
        "INVALID_TOOL_OUTPUT",
    ],
)
async def test_execution_infrastructure_failures_return_error_evidence(error_code):
    class FailingExecutor:
        def execute_batch(self, code, entry_function, inputs, *, timeout_seconds):
            return [ExecutionResult(ok=False, error_code=error_code) for _ in inputs]

    result = await call_tool(
        create_validation_server(execution_tool=FailingExecutor()),
        "code_validate_answers_and_distractors",
        {
            "candidate": candidate().model_dump(mode="json"),
            "required_distractors": 3,
        },
    )

    assert result["status"] == "error"
    assert result["findings"][0]["code"] == error_code


async def test_candidate_runtime_failure_is_a_validation_failure():
    class RuntimeFailureExecutor:
        def execute_batch(self, code, entry_function, inputs, *, timeout_seconds):
            return [
                ExecutionResult(
                    ok=False,
                    error_code="EXECUTION_FAILED",
                    error_message="ZeroDivisionError: division by zero",
                )
                for _ in inputs
            ]

    result = await call_tool(
        create_validation_server(execution_tool=RuntimeFailureExecutor()),
        "code_validate_answers_and_distractors",
        {
            "candidate": candidate().model_dump(mode="json"),
            "required_distractors": 3,
        },
    )

    assert result["status"] == "failed"
    assert result["findings"][0]["code"] == "EXECUTION_FAILED"


async def test_unexpected_execution_failure_is_masked_as_error_evidence():
    class BrokenExecutor:
        def execute_batch(self, code, entry_function, inputs, *, timeout_seconds):
            raise RuntimeError("secret internal detail")

    result = await call_tool(
        create_validation_server(execution_tool=BrokenExecutor()),
        "code_validate_answers_and_distractors",
        {
            "candidate": candidate().model_dump(mode="json"),
            "required_distractors": 3,
        },
    )

    assert result["status"] == "error"
    assert result["findings"] == [
        {
            "code": "TOOL_EXECUTION_ERROR",
            "message": "Validation tool failed with RuntimeError",
            "severity": "error",
            "field": None,
        }
    ]


async def test_invalid_arguments_and_unknown_tools_are_protocol_errors():
    async with Client(create_validation_server()) as client:
        with pytest.raises(ToolError, match="less_than_equal"):
            await client.call_tool(
                "code_validate_answers_and_distractors",
                {
                    "candidate": candidate().model_dump(mode="json"),
                    "required_distractors": 4,
                },
            )
        with pytest.raises(ToolError, match="Unknown tool"):
            await client.call_tool("code_tool_that_is_not_available", {})
