"""Shared text relevance and independently callable Python checks."""

import ast
import asyncio
import importlib.util
import json
import threading
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from edcraft_validator.application.code_checks import (
    check_code_question_correctness,
    check_code_question_requirements,
)
from edcraft_validator.application.relevance import assess_relevance
from edcraft_validator.domains.code.relevance import (
    CodeQuestionRequest,
    relevance_input,
)
from edcraft_validator.mcp.server import create_validation_server
from edcraft_validator.relevance_contracts import RelevanceInput, RelevanceReport
from tests.test_code_relevance import Embeddings, Executor
from tests.test_difficulty_tool import question


async def test_shared_service_preserves_non_python_text():
    embeddings = Embeddings()
    request = RelevanceInput(
        author_request="Create a question about triangle angles.",
        question_text="Two angles are 50 and 60 degrees. Find the third angle.",
    )
    report = await assess_relevance(
        request, embedding_provider_factory=lambda: embeddings
    )
    assert report.status == "assessed" and report.advisory
    assert report.input_sha256 == request.sha256
    assert embeddings.texts == [request.author_request, request.question_text]
    assert report.similarity.dimensions == 2
    assert not {"technical", "requirements", "judge", "difficulty"} & set(
        report.model_dump()
    )


def test_python_adapter_preserves_content_and_excludes_only_answer_designation():
    item = question()
    request = CodeQuestionRequest(
        prompt="Trace arithmetic.", num_distractors=3, required_features=["arithmetic"]
    )
    representation = relevance_input(item, request)
    assert json.loads(representation.author_request) == request.model_dump(mode="json")
    assert json.loads(representation.question_text) == item.model_dump(
        mode="json", exclude={"correct_option"}
    )
    assert "correct_option" not in representation.question_text
    changed_key = item.model_copy(update={"correct_option": "A"})
    assert relevance_input(changed_key, request).sha256 == representation.sha256
    assert changed_key.sha256 != item.sha256
    item.options[0].value = 999
    assert relevance_input(item, request).sha256 != representation.sha256


def test_whitespace_normalization_preserves_input_identity():
    first = RelevanceInput(
        author_request=" \r\nrequest\r", question_text="question\r\n"
    )
    second = RelevanceInput(author_request="request", question_text="question")
    assert first.sha256 == second.sha256
    assert first.author_request == "request" and first.question_text == "question"


@pytest.mark.parametrize(
    "change",
    [
        {"author_request": "\r\n "},
        {"question_text": "\t "},
        {"question_text": 1},
        {"author_request": "x" * 200_001},
        {"difficulty_report": {}},
        {"correctness_report": {}},
    ],
)
async def test_invalid_shared_input_fails_before_provider_creation(change):
    def forbidden():
        pytest.fail("Invalid inputs must not construct a provider")

    with pytest.raises(ValueError):
        invalid = RelevanceInput.model_validate(
            {"author_request": "request", "question_text": "question"} | change
        )
        await assess_relevance(invalid, embedding_provider_factory=forbidden)


async def test_service_revalidates_mutated_typed_input_before_provider_creation():
    def forbidden():
        pytest.fail("Mutated invalid text must not construct a provider")

    request = RelevanceInput(author_request="request", question_text="question")
    request.question_text = " "
    with pytest.raises(ValueError):
        await assess_relevance(request, embedding_provider_factory=forbidden)


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
async def test_invalid_shared_timeout_fails_before_provider_creation(timeout):
    def forbidden():
        pytest.fail("Invalid timeout must not construct a provider")

    with pytest.raises(ValueError, match="finite and positive"):
        await assess_relevance(
            RelevanceInput(author_request="request", question_text="question"),
            embedding_provider_factory=forbidden,
            embedding_timeout_seconds=timeout,
        )


async def test_shared_report_cannot_acquire_another_checks_evidence():
    report = await assess_relevance(
        RelevanceInput(author_request="request", question_text="question"),
        embedding_provider_factory=Embeddings,
    )
    for field in ("technical", "requirements", "difficulty_report", "judge"):
        with pytest.raises(ValueError, match="extra_forbidden"):
            RelevanceReport.model_validate_json(
                json.dumps(report.model_dump(mode="json") | {field: {}})
            )


async def test_caller_mutation_cannot_change_in_flight_identity_or_representation():
    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    class Delayed(Embeddings):
        def embed(self, texts):
            started.set()
            try:
                assert release.wait(5)
                return super().embed(texts)
            finally:
                finished.set()

    request = RelevanceInput(
        author_request="request",
        question_text="original",
    )
    identity = request.sha256
    task = asyncio.create_task(
        assess_relevance(request, embedding_provider_factory=Delayed)
    )
    try:
        assert await asyncio.to_thread(started.wait, 2)
        request.question_text = "changed"
        release.set()
        report = await task
    finally:
        release.set()
        assert await asyncio.to_thread(finished.wait, 2)
        await task
    assert report.input_sha256 == identity
    assert report.similarity.question_text == "original"


async def test_each_mcp_check_runs_without_calling_the_other_services():
    def forbidden():
        pytest.fail("Python checks must not construct any model provider")

    executor = Executor()
    server = create_validation_server(
        difficulty_provider_factory=forbidden,
        embedding_provider_factory=forbidden,
        code_execution_tool=executor,
    )
    item = question().model_copy(update={"correct_option": "A"})
    async with Client(server) as client:
        technical = await client.call_tool(
            "check_code_question_correctness",
            {"question": item.model_dump(mode="json")},
        )
        assert technical.structured_content["status"] == "failed"
        assert technical.structured_content["question_sha256"] == item.sha256
        assert executor.calls == 1
        requirements = await client.call_tool(
            "check_code_question_requirements",
            {
                "question": item.model_dump(mode="json"),
                "request": {"prompt": "Use a loop.", "required_features": ["loop"]},
            },
        )
        assert requirements.structured_content["status"] == "missing"
        assert requirements.structured_content["question_sha256"] == item.sha256
        assert executor.calls == 1
        for name in (
            "check_code_question_correctness",
            "check_code_question_requirements",
        ):
            definition = next(t for t in await client.list_tools() if t.name == name)
            assert (
                "domain:code"
                not in definition.model_dump(by_alias=True)["_meta"]["fastmcp"]["tags"]
            )
            assert not {"similarity", "relevance", "judge"} & set(
                definition.output_schema["properties"]
            )


async def test_shared_mcp_works_even_when_python_execution_is_unavailable():
    class ForbiddenExecutor:
        def execute_batch(self, *args, **kwargs):
            pytest.fail("Shared relevance must not execute Python")

    server = create_validation_server(
        code_execution_tool=ForbiddenExecutor(), embedding_provider_factory=Embeddings
    )
    async with Client(server) as client:
        result = await client.call_tool(
            "assess_relevance",
            {
                "request": {
                    "author_request": "Ask about addition",
                    "question_text": "2 + 3?",
                }
            },
        )
        assert result.structured_content["status"] == "assessed"
        for extra in ("question", "difficulty_report", "technical", "requirements"):
            with pytest.raises(ToolError):
                await client.call_tool(
                    "assess_relevance",
                    {
                        "request": {"author_request": "a", "question_text": "b"},
                        extra: {},
                    },
                )


async def test_standalone_correctness_error_is_explicit_and_requirements_still_work():
    class BrokenExecutor:
        def execute_batch(self, *args, **kwargs):
            raise RuntimeError("PRIVATE EXECUTION DETAIL")

    item = question()
    result = await check_code_question_correctness(
        item, execution_tool=BrokenExecutor()
    )
    assert result.status == "error" and result.findings == ["TECHNICAL_CHECK_ERROR"]
    assert result.question_sha256 == item.sha256
    assert "PRIVATE" not in result.model_dump_json()
    requirements = check_code_question_requirements(
        item, CodeQuestionRequest(prompt="Arithmetic", required_features=["arithmetic"])
    )
    assert requirements.status == "satisfied"


@pytest.mark.parametrize(
    "module",
    [
        "edcraft_validator.application.relevance",
        "edcraft_validator.relevance_contracts",
        "edcraft_validator.domains.code.question_checks",
        "edcraft_validator.domains.code.relevance",
        "edcraft_validator.domains.code.features",
    ],
)
def test_shared_services_and_domain_checks_do_not_depend_on_mcp(module):
    tree = ast.parse(Path(importlib.util.find_spec(module).origin).read_text())
    imports = [
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    ] + [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    ]
    assert not any("mcp" in name for name in imports)
    if module in {
        "edcraft_validator.application.relevance",
        "edcraft_validator.relevance_contracts",
    }:
        assert not any("edcraft_validator.domains" in name for name in imports)
