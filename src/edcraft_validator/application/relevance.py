"""Shared relevance measurement with no domain, correctness or judge dependency."""

import time

from edcraft_validator.llm.embeddings import (
    EmbeddingProviderFactory,
    measure_similarity,
)
from edcraft_validator.relevance_contracts import RelevanceInput, RelevanceReport


async def assess_relevance(
    request: RelevanceInput,
    *,
    embedding_provider_factory: EmbeddingProviderFactory,
    embedding_timeout_seconds: float = 35,
) -> RelevanceReport:
    request = RelevanceInput.model_validate(request.model_dump())
    started = time.perf_counter()
    similarity = await measure_similarity(
        request.author_request,
        request.question_text,
        provider_factory=embedding_provider_factory,
        timeout_seconds=embedding_timeout_seconds,
    )
    return RelevanceReport(
        status="assessed" if similarity.status == "measured" else "error",
        input_sha256=request.sha256,
        similarity=similarity,
        duration_ms=(time.perf_counter() - started) * 1000,
    )
