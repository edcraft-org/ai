"""Shared relevance measurement with no domain, correctness or judge dependency."""

import time

from edcraft_validator.llm.decision import (
    DecisionProviderFactory,
    measure_relevance,
)
from edcraft_validator.relevance_contracts import RelevanceInput, RelevanceReport


async def assess_relevance(
    request: RelevanceInput,
    *,
    decision_provider_factory: DecisionProviderFactory,
    relevance_timeout_seconds: float = 35,
) -> RelevanceReport:
    request = RelevanceInput.model_validate(request.model_dump())
    started = time.perf_counter()
    decision = await measure_relevance(
        request.author_request,
        request.question_text,
        provider_factory=decision_provider_factory,
        timeout_seconds=relevance_timeout_seconds,
    )
    return RelevanceReport(
        status="assessed" if decision.status == "assessed" else "error",
        input_sha256=request.sha256,
        decision=decision,
        duration_ms=(time.perf_counter() - started) * 1000,
    )
