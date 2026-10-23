"""Expose the shared relevance service without adding domain checks."""

from fastmcp import FastMCP

from edcraft_validator.application.relevance import assess_relevance
from edcraft_validator.llm.decision import DecisionProviderFactory
from edcraft_validator.relevance_contracts import RelevanceInput, RelevanceReport


def register_relevance_tools(
    server: FastMCP,
    *,
    decision_provider_factory: DecisionProviderFactory,
    relevance_timeout_seconds: float,
) -> None:
    @server.tool(
        name="assess_relevance",
        version="2.0.0",
        tags={"capability:relevance"},
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
        description=(
            "Assess semantic alignment between an original author request and a "
            "complete textual question, using local Qwen3-Reranker-0.6B. Supply "
            "all learner-facing text. Returns an advisory yes/no decision, raw "
            "yes/no score and pilot-derived threshold. The score is not a "
            "calibrated probability. No embedding API, text generation, code "
            "execution or difficulty judge is used. Consumes no other assessment "
            "reports. Errors have no relevance decision. Model files must already "
            "be downloaded; relevance inputs remain local. Pilot chemistry "
            "results do not establish accuracy in every domain."
        ),
    )
    async def relevance(request: RelevanceInput) -> RelevanceReport:
        return await assess_relevance(
            request,
            decision_provider_factory=decision_provider_factory,
            relevance_timeout_seconds=relevance_timeout_seconds,
        )
