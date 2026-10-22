"""Expose the shared relevance service without adding domain checks."""

from fastmcp import FastMCP

from edcraft_validator.application.relevance import assess_relevance
from edcraft_validator.llm.embeddings import EmbeddingProviderFactory
from edcraft_validator.relevance_contracts import RelevanceInput, RelevanceReport


def register_relevance_tools(
    server: FastMCP,
    *,
    embedding_provider_factory: EmbeddingProviderFactory,
    embedding_timeout_seconds: float,
) -> None:
    @server.tool(
        name="assess_relevance",
        version="1.0.0",
        tags={"capability:relevance"},
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
        description=(
            "Domain-independent embedding relatedness between an original author "
            "request and a complete textual question representation. Supply all "
            "learner-facing question text. Makes one batched embedding request, no "
            "generative judge call, no code execution and no requirement checks. "
            "Consumes no correctness or difficulty evidence. Records exact text, "
            "input identity, model, dimensions, usage and latency. Assessed means "
            "measurement completed, never a relevance or quality pass. No pass "
            "threshold or calibrated accuracy is established for any domain. "
            "Sends the supplied texts to the configured provider and may incur cost."
        ),
    )
    async def relevance(request: RelevanceInput) -> RelevanceReport:
        return await assess_relevance(
            request,
            embedding_provider_factory=embedding_provider_factory,
            embedding_timeout_seconds=embedding_timeout_seconds,
        )
