"""Quality remains advisory even for similar, malformed or incorrect questions."""

import asyncio
import json
import threading
from types import SimpleNamespace

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from edcraft_validator.application.code_difficulty import (
    assess_code_question_difficulty,
)
from edcraft_validator.application.code_quality import (
    assess_code_question_quality,
    check_concrete_correctness,
    check_requirements,
)
from edcraft_validator.domains.code.quality import (
    QualityRequest,
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
from tests.test_difficulty_tool import Provider, assessment, question


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

    def execute_batch(self, *args, **kwargs):
        return [self.result]


async def assess(*, item=None, request=None, embeddings=None, **kwargs):
    return await assess_code_question_quality(
        item or question(),
        request or QualityRequest(prompt="Trace arithmetic."),
        embedding_provider_factory=lambda: embeddings or Embeddings(),
        execution_tool=Executor(),
        **kwargs,
    )


async def test_full_content_and_absent_quality_are_explicit():
    embeddings = Embeddings()
    report = await assess(embeddings=embeddings)
    data = json.loads(report.model_dump_json())
    assert report.status == "assessed" and report.advisory
    assert report.technical.status == "passed"
    assert report.similarity.similarity == 1
    assert report.similarity.usage.input_tokens == 40
    assert report.similarity.duration_ms > 0
    assert report.difficulty_quality.status == "not_supplied"
    assert report.difficulty_quality.quality_concerns is None
    assert "judge" not in data and "relevance" not in data
    assert "quality_score" not in data
    embedded = json.loads(embeddings.texts[1])
    assert embedded == question().model_dump(mode="json", exclude={"correct_option"})
    assert embeddings.texts == [
        report.similarity.request_text,
        report.similarity.question_text,
    ]


async def test_reuses_existing_difficulty_once_and_snapshots_its_evidence():
    provider = Provider()
    previous = await assess_code_question_difficulty(
        question(), provider_factory=lambda: provider
    )
    report = await assess(difficulty_report=previous)
    assert len(provider.requests) == 1
    assert report.difficulty_quality.status == "reused"
    assert (
        report.difficulty_quality.quality_concerns
        == previous.judge.assessment.quality_concerns
    )
    assert report.difficulty_quality.report == previous
    saved = report.model_dump_json()
    previous.judge.assessment.quality_concerns.append("Caller changed its copy")
    assert report.model_dump_json() == saved
    assert report.difficulty_quality.report.usage.input_tokens == 123


async def test_stale_difficulty_evidence_is_rejected_before_embedding():
    previous = await assess_code_question_difficulty(
        question(), provider_factory=Provider
    )
    embeddings = Embeddings()
    changed = question().model_copy(update={"question": "Changed wording"})
    with pytest.raises(ValueError, match="exact supplied question"):
        await assess(item=changed, embeddings=embeddings, difficulty_report=previous)
    assert embeddings.texts is None


async def test_incomplete_option_evidence_is_not_reused():
    previous = await assess_code_question_difficulty(
        question(), provider_factory=Provider
    )
    previous.judge.assessment.option_evidence.pop()
    with pytest.raises(ValueError, match="cover the supplied options"):
        await assess(difficulty_report=previous)


async def test_perfect_similarity_and_reused_opinions_do_not_override_failures():
    item = question().model_copy(update={"correct_option": "A"})
    request = QualityRequest(
        prompt="Trace nested loops.",
        required_features=["nested_loop"],
        answer_target="loop_iterations",
        num_distractors=2,
    )
    provider = Provider()
    previous = await assess_code_question_difficulty(
        item, provider_factory=lambda: provider
    )
    previous.judge.assessment.quality_concerns = []
    report = await assess(item=item, request=request, difficulty_report=previous)
    assert report.difficulty_quality.status == "reused"
    assert len(provider.requests) == 1
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
    assert report.similarity.similarity == 1


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
        QualityRequest(prompt="Use nested loops.", required_features=["nested_loop"]),
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
async def test_bad_embeddings_keep_quality_and_technical_results(vectors):
    report = await assess(embeddings=Embeddings(vectors))
    assert report.status == "error"
    assert report.similarity.error_code == "EMBEDDING_FAILED"
    assert report.similarity.similarity is None
    assert report.difficulty_quality.status == "not_supplied"
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


async def test_failed_difficulty_evidence_is_retained_without_reassessment():
    provider = Provider(RuntimeError("PRIVATE REMOTE ERROR"))
    previous = await assess_code_question_difficulty(
        question(), provider_factory=lambda: provider
    )
    report = await assess(difficulty_report=previous)
    assert len(provider.requests) == 1
    assert report.status == "assessed"
    assert report.difficulty_quality.status == "unavailable"
    assert report.difficulty_quality.quality_concerns is None
    assert report.difficulty_quality.report.error_code == "JUDGE_INTERNAL_ERROR"
    assert report.difficulty_quality.report.usage.input_tokens == 123
    assert "PRIVATE REMOTE ERROR" not in report.model_dump_json()


async def test_configuration_errors_are_explicit_and_do_not_leak_secrets():
    def broken():
        raise ValueError("PRIVATE TOKEN")

    report = await assess_code_question_quality(
        question(),
        QualityRequest(prompt="Arithmetic"),
        embedding_provider_factory=broken,
        execution_tool=Executor(),
    )
    assert report.status == "error"
    assert report.technical.status == "passed"
    assert report.similarity.error_code == "EMBEDDING_CONFIGURATION_ERROR"
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


async def test_three_options_reuse_only_the_three_existing_judgments():
    item = question()
    item.options.pop()
    response = assessment()
    response["option_evidence"].pop()
    provider = Provider(response)
    previous = await assess_code_question_difficulty(
        item, provider_factory=lambda: provider
    )
    result = await assess(item=item, difficulty_report=previous)
    assert len(provider.requests) == 1 and result.status == "assessed"
    assert len(result.difficulty_quality.report.judge.assessment.option_evidence) == 3


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
        pytest.fail("Quality assessment must not construct a difficulty judge")

    previous = await assess_code_question_difficulty(
        question(), provider_factory=Provider
    )
    server = create_validation_server(
        difficulty_provider_factory=forbidden,
        embedding_provider_factory=Embeddings,
        code_execution_tool=Executor(),
    )
    async with Client(server) as client:
        tool = next(
            t for t in await client.list_tools() if t.name == "assess_code_quality"
        )
        assert tool.model_dump(by_alias=True)["_meta"]["fastmcp"]["tags"] == [
            "quality:code"
        ]
        result = await client.call_tool(
            "assess_code_quality",
            {
                "question": question().model_dump(mode="json"),
                "request": {"prompt": "Arithmetic"},
            },
        )
        assert result.structured_content["technical"]["status"] == "passed"
        assert result.structured_content["version"] == "2.0.0"
        assert (
            result.structured_content["difficulty_quality"]["status"] == "not_supplied"
        )
        assert "judge" not in result.structured_content
        reused = await client.call_tool(
            "assess_code_quality",
            {
                "question": question().model_dump(mode="json"),
                "request": {"prompt": "Arithmetic"},
                "difficulty_report": previous.model_dump(mode="json"),
            },
        )
        assert reused.structured_content["difficulty_quality"]["status"] == "reused"
        assert reused.structured_content["difficulty_quality"]["quality_concerns"]
        malformed = previous.model_dump(mode="json")
        malformed["usage"]["model_call_count"] = "1"
        with pytest.raises(ToolError, match="int_type"):
            await client.call_tool(
                "assess_code_quality",
                {
                    "question": question().model_dump(mode="json"),
                    "request": {"prompt": "Arithmetic"},
                    "difficulty_report": malformed,
                },
            )
        with pytest.raises(ToolError):
            await client.call_tool(
                "assess_code_quality",
                {
                    "question": question().model_dump(mode="json"),
                    "request": {"prompt": "", "required_features": ["invented"]},
                },
            )


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
