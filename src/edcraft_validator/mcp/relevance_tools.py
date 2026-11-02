"""Expose shared relevance and its code-template authoring adapter."""

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from edcraft_validator.application.code_relevance import assess_code_template_relevance
from edcraft_validator.application.relevance import assess_relevance
from edcraft_validator.domains.code.code_schemas import CodeTemplateCandidate
from edcraft_validator.domains.code.relevance import TEMPLATE_RELEVANCE_TOOL
from edcraft_validator.llm.decision import DecisionProviderFactory
from edcraft_validator.relevance_contracts import RelevanceInput, RelevanceReport
from edcraft_validator.validation.check_contracts import ToolEvidence


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
            "openWorldHint": True,
        },
        description=(
            "Assess semantic alignment between an original author request and a "
            "complete textual question, using the host-configured judge model "
            "with reasoning disabled. Supply "
            "all learner-facing text. Returns an advisory yes/no decision, raw "
            "yes/no score and pilot-derived threshold. The score is not a "
            "calibrated probability. No embedding API, code "
            "execution or difficulty judge is used. Consumes no other assessment "
            "reports. Errors have no relevance decision. Inputs are sent to the "
            "configured "
            "model endpoint and may incur cost. Pilot chemistry "
            "results do not establish accuracy in every domain."
        ),
    )
    async def relevance(request: RelevanceInput) -> RelevanceReport:
        return await assess_relevance(
            request,
            decision_provider_factory=decision_provider_factory,
            relevance_timeout_seconds=relevance_timeout_seconds,
        )

    @server.tool(
        name=TEMPLATE_RELEVANCE_TOOL,
        version="1.0.0",
        tags={"domain:code", "quality:code", "stage:after-validation"},
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
        description=(
            "Check whether the reusable Python MCQ template tests the original "
            "author request. The application supplies both the exact checked "
            "candidate and the unchanged author request; use no model-owned "
            "arguments. Select this check for authoring. Uses the "
            "configured judge model with reasoning disabled and the configured "
            "relevance threshold. An irrelevant decision fails the check and "
            "requests revision. Errors never pass. Assesses the code, question "
            "pattern, answer target and finite parameter domain; does not execute "
            "code or consume correctness/difficulty reports. Reuses the text "
            "relevance classifier; template accuracy is not established by the "
            "concrete-question pilot. May incur model cost."
        ),
    )
    async def template_relevance(
        candidate: CodeTemplateCandidate,
        author_request: Annotated[str, Field(min_length=1, max_length=4000)],
    ) -> ToolEvidence:
        return await assess_code_template_relevance(
            candidate,
            author_request,
            decision_provider_factory=decision_provider_factory,
            relevance_timeout_seconds=relevance_timeout_seconds,
        )
