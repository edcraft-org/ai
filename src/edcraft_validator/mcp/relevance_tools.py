"""Expose the shared relevance checks."""

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from edcraft_validator.application.relevance import assess_relevance
from edcraft_validator.application.template_relevance import assess_template_relevance
from edcraft_validator.llm.decision import DecisionProviderFactory
from edcraft_validator.relevance_contracts import RelevanceInput, RelevanceReport
from edcraft_validator.validation.check_contracts import ToolEvidence
from edcraft_validator.validation.check_names import (
    TEMPLATE_RELEVANCE_CAPABILITY,
    TEMPLATE_RELEVANCE_CHECK,
    TEMPLATE_RELEVANCE_TOOL_VERSION,
)


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
        name=TEMPLATE_RELEVANCE_CHECK,
        version=TEMPLATE_RELEVANCE_TOOL_VERSION,
        tags={
            f"capability:{TEMPLATE_RELEVANCE_CAPABILITY}",
            "stage:after-validation",
            "policy:advisory",
        },
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
        description=(
            "Check whether a reusable question template tests the original author "
            "request. The application supplies the unchanged request, the "
            "domain-rendered learner-facing text and the exact checked template "
            "identity; use no model-owned arguments. The measurement is the shared "
            "semantic relevance classifier, so every domain is judged by the same "
            "policy and threshold. A negative decision is advisory evidence for "
            "educator review and never blocks a technically checked artifact. "
            "Errors are reported as unavailable advisory evidence. Inputs are sent "
            "to the configured model endpoint and may incur cost."
        ),
    )
    async def shared_template_relevance(
        author_request: Annotated[str, Field(min_length=1, max_length=4000)],
        question_text: Annotated[str, Field(min_length=1, max_length=200_000)],
        subject_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")],
    ) -> ToolEvidence:
        return await assess_template_relevance(
            subject_sha256=subject_sha256,
            author_request=author_request,
            question_text=question_text,
            decision_provider_factory=decision_provider_factory,
            relevance_timeout_seconds=relevance_timeout_seconds,
        )
