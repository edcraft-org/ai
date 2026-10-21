"""A measured embedding baseline with exact comparison text and no pass cutoff."""

import asyncio
import math
import os
import time
from collections.abc import Callable
from typing import Literal, Protocol

from openai import APITimeoutError, OpenAI
from pydantic import BaseModel, ConfigDict, Field

from edcraft_validator.llm.usage import TokenUsage


class EmbeddingProvider(Protocol):
    provider: str
    model: str
    model_version: str
    last_usage: TokenUsage

    def embed(self, texts: list[str]) -> list[list[float]]: ...


EmbeddingProviderFactory = Callable[[], EmbeddingProvider]


class OpenAIEmbeddingProvider:
    provider = "openai"

    def __init__(self, *, client=None, model: str | None = None):
        self.model = model or os.getenv(
            "EDCRAFT_EMBEDDING_MODEL", "text-embedding-3-small"
        )
        # The endpoint exposes a model ID, not an immutable weight revision.
        self.model_version = "provider model ID; immutable revision unavailable"
        self.client = client or OpenAI(
            api_key=os.environ["OPENAI_API_KEY"],
            base_url=os.getenv("OPENAI_BASE_URL") or None,
            timeout=30,
            max_retries=0,
        )
        self.last_usage = TokenUsage()

    def embed(self, texts):
        self.last_usage = TokenUsage()
        response = self.client.embeddings.create(
            model=self.model, input=texts, encoding_format="float"
        )
        self.last_usage = TokenUsage.from_counts(
            getattr(getattr(response, "usage", None), "prompt_tokens", None), 0
        )
        if response.model != self.model:
            raise ValueError("embedding response model differs from requested model")
        rows = sorted(response.data, key=lambda item: item.index)
        if [row.index for row in rows] != list(range(len(texts))):
            raise ValueError("embedding response indices do not match the inputs")
        return [row.embedding for row in rows]


class SimilarityReport(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    status: Literal["measured", "error"] = "error"
    provider: str | None = None
    model: str | None = None
    model_version: str | None = None
    preprocessing: Literal["lf-strip-v1"] = "lf-strip-v1"
    metric: Literal["cosine"] = "cosine"
    request_text: str
    question_text: str
    similarity: float | None = Field(default=None, ge=-1, le=1)
    dimensions: int | None = None
    timeout_seconds: float
    usage: TokenUsage = Field(default_factory=TokenUsage)
    error_code: str | None = None
    duration_ms: float = 0


def cosine_similarity(vectors: list[list[float]]) -> float:
    if len(vectors) != 2 or not vectors[0] or len(vectors[0]) != len(vectors[1]):
        raise ValueError("expected two nonempty equal-sized vectors")
    normalized = []
    for vector in vectors:
        if any(type(x) not in {int, float} or not math.isfinite(x) for x in vector):
            raise ValueError("embedding vectors must contain finite numbers")
        scale = max(abs(x) for x in vector)
        if scale == 0:
            raise ValueError("zero embedding vector")
        scaled = [x / scale for x in vector]
        norm = math.hypot(*scaled)
        normalized.append([x / norm for x in scaled])
    value = math.fsum(a * b for a, b in zip(*normalized, strict=True))
    return max(-1.0, min(1.0, value))


async def measure_similarity(
    request_text: str,
    question_text: str,
    *,
    provider_factory: EmbeddingProviderFactory,
    timeout_seconds: float = 35,
) -> SimilarityReport:
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("embedding timeout must be finite and positive")
    started = time.perf_counter()
    report = SimilarityReport(
        request_text=request_text.replace("\r\n", "\n").replace("\r", "\n").strip(),
        question_text=question_text.replace("\r\n", "\n").replace("\r", "\n").strip(),
        timeout_seconds=timeout_seconds,
    )
    try:
        provider = provider_factory()
        report.provider, report.model = provider.provider, provider.model
        report.model_version = provider.model_version
    except Exception:
        report.error_code = "EMBEDDING_CONFIGURATION_ERROR"
    else:
        try:
            async with asyncio.timeout(timeout_seconds):
                vectors = await asyncio.to_thread(
                    provider.embed, [report.request_text, report.question_text]
                )
            usage = getattr(provider, "last_usage", None)
            if isinstance(usage, TokenUsage):
                report.usage = usage.model_copy(deep=True)
            report.similarity = cosine_similarity(vectors)
            report.dimensions = len(vectors[0])
            report.status = "measured"
        except (TimeoutError, APITimeoutError):
            # Snapshot only: a late thread cannot change the returned usage.
            report.error_code = "EMBEDDING_TIMEOUT"
        except Exception:
            report.error_code = "EMBEDDING_FAILED"
            usage = getattr(provider, "last_usage", None)
            if isinstance(usage, TokenUsage):
                report.usage = usage.model_copy(deep=True)
    report.duration_ms = (time.perf_counter() - started) * 1000
    return report
