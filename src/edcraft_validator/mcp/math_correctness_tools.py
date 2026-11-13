"""MCP transport for deterministic mathematics; no reusable recipe authoring."""

from fastmcp import FastMCP

from edcraft_validator.application.math_correctness import (
    check_math_correctness,
    correctness_evidence,
)
from edcraft_validator.application.math_correctness_sampling import (
    qualify_math_template,
)
from edcraft_validator.domains.math.engine.contracts import CorrectnessRequest
from edcraft_validator.domains.math.engine.sampling import (
    CorrectnessTemplate,
    SamplingSettings,
)
from edcraft_validator.validation.check_contracts import (
    ToolEvidence,
    ToolFinding,
    ToolStatus,
)


def register_math_correctness_tools(server: FastMCP) -> None:
    @server.tool(
        name="math_check_correctness",
        tags={"quality:math"},
        version="1.0.0",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        description=(
            "Check one structured mathematics answer with exact symbolic computation. "
            "Supports expressions, calculus, solution sets and matrices within limits. "
            "Unknown, unsupported and timeout never count as incorrect answers. "
            "Assesses correctness; makes no LLM calls."
        ),
    )
    def math_check_correctness(request: CorrectnessRequest) -> ToolEvidence:
        return correctness_evidence(check_math_correctness(request))

    @server.tool(
        name="math_qualify_correctness_template",
        version="1.0.0",
        tags={"quality:math"},
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        description=(
            "Qualify a mathematics template with bounded, seeded "
            "property-based samples. No enumeration or LLM calls. "
            "Reports counts and shrunk counterexamples for sampled cases only."
        ),
    )
    def math_qualify_correctness_template(
        template: CorrectnessTemplate,
        settings: SamplingSettings | None = None,
    ) -> ToolEvidence:
        report = qualify_math_template(template, settings=settings)
        outcome = report["status"]
        status: ToolStatus = (
            "passed"
            if outcome == "passed"
            else "failed"
            if outcome == "failed"
            else "error"
        )
        return ToolEvidence(
            tool="math_qualify_correctness_template",
            version="1.0.0",
            status=status,
            findings=[]
            if status == "passed"
            else [
                ToolFinding(
                    code="MATH_QUALIFICATION_" + outcome.upper(),
                    message=str(
                        report.get(
                            "reason",
                            "Sampled qualification did not pass; inspect the details.",
                        )
                    ),
                )
            ],
            details=report,
            duration_ms=report.get("duration_ms", 0),
        )
