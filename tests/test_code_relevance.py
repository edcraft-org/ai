"""Quality remains advisory even for similar, malformed or incorrect questions."""

import asyncio
import json
import threading
from types import SimpleNamespace

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from edcraft_validator.application.code_relevance import (
    CodeRelevanceReview,
    review_code_question_relevance,
)
from edcraft_validator.domains.code.question_checks import (
    check_concrete_correctness,
    check_requirements,
)
from edcraft_validator.domains.code.relevance import (
    CodeQuestionRequest,
    relevance_input,
    rendered_question,
)
from edcraft_validator.llm.embeddings import (
    OpenAIEmbeddingProvider,
    cosine_similarity,
    measure_similarity,
)
from edcraft_validator.llm.usage import TokenUsage
from edcraft_validator.mcp.server import create_validation_server
from edcraft_validator.tools.python_execution import ExecutionResult
from tests.test_difficulty_tool import Provider, question


class Embeddings:
    provider, model, model_version = "fake", "embed-test", "fixed-v1"

    def __init__(self, vectors=None):
        self.vectors = vectors if vectors is not None else [[1.0, 0.0], [1.0, 0.0]]
        self.last_usage = TokenUsage(input_tokens=40, output_tokens=0)
        self.texts = None

    def embed(self, texts):
        self.texts = texts
        if isinstance(self.vectors, Exception):
            raise self.vectors
        return self.vectors


class Executor:
    def __init__(self, result=None):
        self.result = result or ExecutionResult(ok=True, answer=10)
        self.calls = 0

    def execute_batch(self, *args, **kwargs):
        self.calls += 1
        return [self.result]


async def assess(*, item=None, request=None, embeddings=None, **kwargs):
    return await review_code_question_relevance(
        item or question(),
        request or CodeQuestionRequest(prompt="Trace arithmetic."),
        embedding_provider_factory=lambda: embeddings or Embeddings(),
        execution_tool=Executor(),
        **kwargs,
    )


async def test_full_content_and_independent_evidence_are_explicit():
    embeddings = Embeddings()
    report = await assess(embeddings=embeddings)
    data = json.loads(report.model_dump_json())
    assert report.status == "assessed" and report.advisory
    assert report.technical.status == "passed"
    assert report.relevance.similarity.similarity == 1
    assert report.relevance.similarity.usage.input_tokens == 40
    assert report.relevance.similarity.duration_ms > 0
    assert data["version"] == "4.0.0"
    assert "difficulty_quality" not in data and "quality_concerns" not in data
    assert "judge" not in data and "relevance" in data
    assert "quality_score" not in data
    embedded = json.loads(embeddings.texts[1])
    assert embedded == question().model_dump(mode="json", exclude={"correct_option"})
    assert embeddings.texts == [
        report.relevance.similarity.request_text,
        report.relevance.similarity.question_text,
    ]


async def test_application_rejects_difficulty_report_input_without_embedding():
    embeddings = Embeddings()
    with pytest.raises(TypeError, match="difficulty_report"):
        await assess(embeddings=embeddings, difficulty_report={"status": "error"})
    assert embeddings.texts is None


async def test_report_rejects_attached_difficulty_evidence():
    report = await assess()
    data = report.model_dump(mode="json")
    data["difficulty_quality"] = {"status": "reused", "quality_concerns": []}
    with pytest.raises(ValueError, match="extra_forbidden"):
        CodeRelevanceReview.model_validate_json(json.dumps(data))


async def test_perfect_similarity_does_not_override_failures():
    item = question().model_copy(update={"correct_option": "A"})
    request = CodeQuestionRequest(
        prompt="Trace nested loops.",
        required_features=["nested_loop"],
        answer_target="loop_iterations",
        num_distractors=2,
    )
    report = await assess(item=item, request=request)
    assert report.status == "assessed"
    assert report.technical.status == "failed"
    assert report.technical.findings == [
        "CANONICAL_ANSWER_MISMATCH",
        "DISTRACTOR_EQUALS_ANSWER:C",
    ]
    assert report.requirements.status == "missing"
    assert set(report.requirements.findings) == {
        "MISSING_FEATURE:nested_loop",
        "ANSWER_TARGET_MISMATCH",
        "DISTRACTOR_COUNT_MISMATCH",
    }
    assert report.relevance.similarity.similarity == 1


def test_keyword_and_unreachable_helper_cannot_satisfy_syntax_requirement():
    item = question().model_copy(
        update={
            "code": question().code
            + (
                "# nested loops\ndef unused(n):\n"
                "    for i in range(n):\n        for j in range(n):\n            pass\n"
            )
        }
    )
    result = check_requirements(
        item,
        CodeQuestionRequest(
            prompt="Use nested loops.", required_features=["nested_loop"]
        ),
    )
    assert result.status == "missing"
    assert "nested_loop" not in result.observed_features


@pytest.mark.parametrize(
    "change,finding",
    [
        ({"correct_option": "A"}, "CANONICAL_ANSWER_MISMATCH"),
        ({"code": "import os\ndef f(x): return x"}, "UNSUPPORTED_CODE"),
        ({"code": "not python!"}, "UNSUPPORTED_CODE"),
    ],
)
def test_correctness_and_supported_subset_are_hard_requirements(change, finding):
    result = check_concrete_correctness(
        question().model_copy(update=change), Executor(), 1
    )
    assert result.status == "failed" and finding in result.findings


def test_distinct_options_and_missing_trace_evidence_never_pass():
    item = question()
    item.options[1].value = item.options[0].value
    result = check_concrete_correctness(item, Executor(), 1)
    assert result.status == "failed" and "DUPLICATE_OPTION:B" in result.findings
    item.answer_target = "loop_iterations"
    result = check_concrete_correctness(item, Executor(), 1)
    assert result.status == "error" and result.findings == ["ANSWER_TARGET_UNAVAILABLE"]
    result = check_concrete_correctness(
        question(),
        Executor(ExecutionResult(ok=False, error_code="EXECUTION_TIMEOUT")),
        1,
    )
    assert result.status == "error"


@pytest.mark.parametrize(
    "target",
    ["loop_iterations", "loop_executions", "function_calls", "branch_executions"],
)
def test_counts_use_trace_summary_instead_of_return_value(target):
    item = question().model_copy(update={"answer_target": target})
    result = check_concrete_correctness(
        item,
        Executor(ExecutionResult(ok=True, answer=999, trace_summary={target: 10})),
        1,
    )
    assert result.status == "passed" and result.canonical_answer == 10


@pytest.mark.parametrize(
    "vectors",
    [
        [],
        [[1]],
        [[1], [1, 2]],
        [[0], [1]],
        [[float("nan")], [1]],
        [[float("inf")], [1]],
        [[True], [1]],
    ],
)
async def test_bad_embeddings_keep_technical_results(vectors):
    report = await assess(embeddings=Embeddings(vectors))
    assert report.status == "error"
    assert report.relevance.similarity.error_code == "EMBEDDING_FAILED"
    assert report.relevance.similarity.similarity is None
    assert report.technical.status == "passed"


@pytest.mark.parametrize(
    "vectors,expected",
    [
        ([[1, 0], [0, 1]], 0),
        ([[1], [-1]], -1),
        ([[1e308, 1e308], [1e308, 1e308]], 1),
    ],
)
def test_cosine_range_and_numerical_stability(vectors, expected):
    assert cosine_similarity(vectors) == pytest.approx(expected)


@pytest.mark.parametrize("difficulty_error", [False, True])
async def test_mcp_difficulty_success_or_failure_cannot_affect_relevance(
    difficulty_error,
):
    provider = Provider(
        RuntimeError("PRIVATE REMOTE ERROR") if difficulty_error else None
    )
    executor = Executor()
    server = create_validation_server(
        difficulty_provider_factory=lambda: provider,
        embedding_provider_factory=Embeddings,
        code_execution_tool=executor,
    )
    async with Client(server) as client:
        difficulty = await client.call_tool(
            "assess_code_difficulty", {"question": question().model_dump(mode="json")}
        )
        relevance = await client.call_tool(
            "assess_relevance",
            {
                "request": relevance_input(
                    question(), CodeQuestionRequest(prompt="Arithmetic")
                ).model_dump(mode="json"),
            },
        )
    assert len(provider.requests) == 1
    assert difficulty.structured_content["status"] == (
        "error" if difficulty_error else "assessed"
    )
    if not difficulty_error:
        assert difficulty.structured_content["judge"]["assessment"]["quality_concerns"]
    data = relevance.structured_content
    assert data["status"] == "assessed" and executor.calls == 0
    assert data["similarity"]["usage"]["input_tokens"] == 40
    assert "difficulty_quality" not in data and "judge" not in data
    assert "PRIVATE REMOTE ERROR" not in json.dumps(data)


async def test_configuration_errors_are_explicit_and_do_not_leak_secrets():
    def broken():
        raise ValueError("PRIVATE TOKEN")

    report = await review_code_question_relevance(
        question(),
        CodeQuestionRequest(prompt="Arithmetic"),
        embedding_provider_factory=broken,
        execution_tool=Executor(),
    )
    assert report.status == "error"
    assert report.technical.status == "passed"
    assert report.relevance.similarity.error_code == "EMBEDDING_CONFIGURATION_ERROR"
    assert "PRIVATE TOKEN" not in report.model_dump_json()


async def test_embedding_deadline_returns_immutable_usage_snapshot():
    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    class Slow(Embeddings):
        def embed(self, texts):
            started.set()
            try:
                release.wait(5)
                return super().embed(texts)
            finally:
                finished.set()

    try:
        result = await measure_similarity(
            "\r\nRequest\r", "Question\r\n", provider_factory=Slow, timeout_seconds=0.1
        )
        assert started.is_set() and not finished.is_set()
        assert result.error_code == "EMBEDDING_TIMEOUT"
        assert result.usage.input_tokens is None
        assert result.request_text == "Request" and result.question_text == "Question"
        snapshot = result.model_dump_json()
    finally:
        release.set()
        assert await asyncio.to_thread(finished.wait, 2)
    assert result.model_dump_json() == snapshot


async def test_missing_embedding_usage_stays_unknown_without_losing_similarity():
    class Unmetered(Embeddings):
        def embed(self, texts):
            result = super().embed(texts)
            del self.last_usage
            return result

    result = await measure_similarity("request", "question", provider_factory=Unmetered)
    assert result.status == "measured" and result.similarity == 1
    assert result.usage.input_tokens is None


async def test_three_options_are_assessed_without_difficulty_evidence():
    item = question()
    item.options.pop()
    result = await assess(item=item)
    assert result.status == "assessed" and result.technical.status == "passed"
    assert len(json.loads(result.relevance.similarity.question_text)["options"]) == 3


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
async def test_invalid_deadlines_fail_before_provider_calls(timeout):
    embeddings = Embeddings()
    with pytest.raises(ValueError, match="finite and positive"):
        await assess(embeddings=embeddings, embedding_timeout_seconds=timeout)
    assert embeddings.texts is None
    with pytest.raises(ValueError, match="finite and positive"):
        create_validation_server(embedding_timeout_seconds=timeout)


def test_embedding_adapter_orders_indices_and_preserves_usage_on_bad_response():
    response = SimpleNamespace(
        model="embed-test",
        usage=SimpleNamespace(prompt_tokens=44),
        data=[
            SimpleNamespace(index=1, embedding=[0, 1]),
            SimpleNamespace(index=0, embedding=[1, 0]),
        ],
    )
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return response

    provider = OpenAIEmbeddingProvider(
        model="embed-test",
        client=SimpleNamespace(embeddings=SimpleNamespace(create=create)),
    )
    assert provider.embed(["request", "question"]) == [[1, 0], [0, 1]]
    assert provider.last_usage.input_tokens == 44
    assert calls[0]["input"] == ["request", "question"]
    response.data[1].index = 1
    with pytest.raises(ValueError, match="indices"):
        provider.embed(["request", "question"])
    assert provider.last_usage.input_tokens == 44


async def test_mcp_tool_has_full_evidence_and_is_not_an_authoring_check():
    def forbidden():
        pytest.fail("Relevance assessment must not construct a difficulty judge")

    embeddings, executor = Embeddings(), Executor()
    server = create_validation_server(
        difficulty_provider_factory=forbidden,
        embedding_provider_factory=lambda: embeddings,
        code_execution_tool=executor,
    )
    async with Client(server) as client:
        tool = next(
            t for t in await client.list_tools() if t.name == "assess_relevance"
        )
        assert tool.model_dump(by_alias=True)["_meta"]["fastmcp"]["tags"] == [
            "capability:relevance"
        ]
        assert set(tool.input_schema["properties"]) == {"request"}
        assert "difficulty_quality" not in tool.output_schema["properties"]
        payload = relevance_input(
            question(), CodeQuestionRequest(prompt="Arithmetic")
        ).model_dump(mode="json")
        result = await client.call_tool("assess_relevance", {"request": payload})
        assert result.structured_content["status"] == "assessed"
        assert result.structured_content["version"] == "1.0.0"
        assert "technical" not in result.structured_content
        assert executor.calls == 0
        assert "difficulty_quality" not in result.structured_content
        assert "judge" not in result.structured_content
        embeddings.texts = None
        executions = executor.calls
        with pytest.raises(ToolError):
            await client.call_tool(
                "assess_relevance",
                {
                    "request": payload,
                    "difficulty_report": {"status": "error"},
                },
            )
        assert embeddings.texts is None and executor.calls == executions
        with pytest.raises(ToolError):
            await client.call_tool(
                "assess_relevance",
                {
                    "request": {**payload, "author_request": " "},
                },
            )
        with pytest.raises(ToolError, match="Unknown tool"):
            await client.call_tool("assess_code_quality", {})
        assert embeddings.texts is None and executor.calls == 0


def test_rendering_preserves_all_learner_content_and_omits_the_designation():
    item = question()
    item.options.pop()
    content = json.loads(rendered_question(item))
    assert content["code"] == item.code
    assert len(content["options"]) == 3
    assert "correct_option" not in content


def test_default_and_override_embedding_models(monkeypatch):
    monkeypatch.delenv("EDCRAFT_EMBEDDING_MODEL", raising=False)
    assert OpenAIEmbeddingProvider(client=object()).model == "text-embedding-3-large"
    monkeypatch.setenv("EDCRAFT_EMBEDDING_MODEL", "text-embedding-3-small")
    assert OpenAIEmbeddingProvider(client=object()).model == "text-embedding-3-small"
