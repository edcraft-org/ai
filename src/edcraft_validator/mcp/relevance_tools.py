"""Expose shared relevance and the code-template authoring adapter."""

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from edcraft_validator.application.code_relevance import assess_code_template_relevance
from edcraft_validator.application.relevance import assess_relevance
from edcraft_validator.application.template_relevance import (
    assess_template_relevance as build_template_relevance_evidence,
)
from edcraft_validator.domains.code.code_schemas import CodeTemplateCandidate
from edcraft_validator.domains.code.relevance import TEMPLATE_RELEVANCE_TOOL
from edcraft_validator.llm.decision import DecisionProviderFactory
from edcraft_validator.relevance_contracts import RelevanceInput, RelevanceReport
from edcraft_validator.validation.check_contracts import ToolEvidence
from edcraft_validator.validation.check_names import (
    TEMPLATE_RELEVANCE_CAPABILITY,
    TEMPLATE_RELEVANCE_CHECK,
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
        version="1.0.0",
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
        return await build_template_relevance_evidence(
            subject_sha256=subject_sha256,
            author_request=author_request,
            question_text=question_text,
            decision_provider_factory=decision_provider_factory,
            relevance_timeout_seconds=relevance_timeout_seconds,
        )

    @server.tool(
        name=TEMPLATE_RELEVANCE_TOOL,
        version="1.0.0",
        tags={
            "domain:code",
            "quality:code",
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
            "Check whether the reusable Python MCQ template tests the original "
            "author request. The application supplies both the exact checked "
            "candidate and the unchanged author request; use no model-owned "
            "arguments. Select this check for authoring. Uses the "
            "configured judge model with reasoning disabled and the configured "
            "relevance threshold. An irrelevant decision is advisory evidence: it "
            "never requests revision or blocks a technically checked artifact. "
            "Errors never pass and are reported as unavailable advisory evidence. "
            "Assesses the code, question "
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
