"""Domain-neutral authoring relevance evidence from the shared classifier."""

from collections.abc import Mapping
from typing import Literal

from edcraft_validator.application.relevance import assess_relevance
from edcraft_validator.llm.decision import DecisionProviderFactory
from edcraft_validator.relevance_contracts import RelevanceInput, RelevanceReport
from edcraft_validator.validation.check_contracts import ToolEvidence, ToolFinding
from edcraft_validator.validation.check_names import (
    TEMPLATE_RELEVANCE_CHECK,
    TEMPLATE_RELEVANCE_TOOL_VERSION,
)


def build_relevance_evidence(
    report: RelevanceReport,
    *,
    tool: str,
    identity: Mapping[str, str],
) -> ToolEvidence:
    """Map one shared decision into the authoring check contract.

    ``identity`` records the exact checked subject under the key its reader
    expects. Code keeps ``template_sha256`` for historical artifacts; newer
    shared checks use ``subject_sha256``.
    """
    status: Literal["passed", "failed", "error"] = "passed"
    findings: list[ToolFinding] = []
    if report.status == "error":
        status = "error"
        findings = [
            ToolFinding(
                code=report.decision.error_code or "RELEVANCE_FAILED",
                message="Relevance assessment failed; no check retry was made.",
            )
        ]
    elif not report.decision.relevant:
        status = "failed"
        findings = [
            ToolFinding(
                code="RELEVANCE_MISMATCH",
                message=(
                    "The template may not assess the original author request; "
                    "this is advisory evidence for educator review, not a "
                    "technical failure or a revision request."
                ),
            )
        ]
    unavailable = report.status != "assessed"
    return ToolEvidence(
        tool=tool,
        version=TEMPLATE_RELEVANCE_TOOL_VERSION,
        status=status,
        findings=findings,
        details={
            "advisory": True,
            "retryable": False,
            **identity,
            "score": report.decision.score,
            "threshold": report.decision.threshold,
            "relevant": report.decision.relevant,
            "provider": report.decision.provider,
            "model": report.decision.model,
            "usage": report.decision.usage.model_dump(mode="json"),
            "relevance": report.model_dump(mode="json"),
            "relevance_outcome": {
                "status": "unavailable" if unavailable else "assessed",
                "unavailable": unavailable,
                "score": report.decision.score,
                "threshold": report.decision.threshold,
                "relevant": report.decision.relevant,
                "reason": (
                    "Relevance assessment unavailable; no check retry was made."
                    if unavailable
                    else "Advisory relevance assessment completed."
                ),
                "error_code": report.decision.error_code,
            },
        },
        duration_ms=report.duration_ms,
    )


async def assess_template_relevance(
    *,
    subject_sha256: str,
    author_request: str,
    question_text: str,
    decision_provider_factory: DecisionProviderFactory,
    relevance_timeout_seconds: float = 35,
) -> ToolEvidence:
    """Assess a domain-projected template with the shared relevance policy.

    Domains supply only the learner-facing text projection. The measurement,
    threshold and verdict stay in the shared classifier so every domain is judged
    by the same policy.
    """
    report = await assess_relevance(
        RelevanceInput(
            author_request=author_request,
            question_text=question_text,
        ),
        decision_provider_factory=decision_provider_factory,
        relevance_timeout_seconds=relevance_timeout_seconds,
    )
    return build_relevance_evidence(
        report,
        tool=TEMPLATE_RELEVANCE_CHECK,
        identity={"subject_sha256": subject_sha256},
    )
