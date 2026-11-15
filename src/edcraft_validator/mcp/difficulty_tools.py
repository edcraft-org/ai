"""Explicit advisory tools kept outside the authoritative validation catalogue."""

from fastmcp import FastMCP

from edcraft_validator.domains.code.code_schemas import CodeTemplateCandidate
from edcraft_validator.domains.code.difficulty_assessment import (
    assess_template_difficulty,
)
from edcraft_validator.llm.judge_configuration import JudgeSettings
from edcraft_validator.llm.judging import JudgeProviderFactory
from edcraft_validator.validation.check_contracts import ToolEvidence


def register_difficulty_tools(
    server: FastMCP,
    *,
    provider_factory: JudgeProviderFactory,
    judge_timeout_seconds: float,
    settings: JudgeSettings | None = None,
) -> None:
    # Model responses are not deterministic; read-only still sends question data
    # to the host-configured provider and may incur inference cost.
    @server.tool(
        name="code_assess_template_difficulty",
        version="1.2.0",
        tags={
            "domain:code",
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
            "Assess the difficulty of a reusable Python tracing MCQ template. "
            "Select this check when authoring or validating a template with a target "
            "difficulty. The configured model estimates the typical instance across "
            "effective domain: uniform eligible combinations when supplied, "
            "otherwise independent uniform parameter values, "
            "using code, question pattern, answer target and distractor recipes. "
            "The declared level is hidden from the judge and compared afterwards. "
            "A forced decision is accepted at token confidence >=0.70; otherwise "
            "the same model reasons about the template. Difficulty mismatches are "
            "advisory: they never request author revision or block a technically "
            "checked artifact. Inspect status, difficulty_match and decision; "
            "reasoning confidence 0.80 or higher remains provisional, not "
            "calibrated accuracy. Missing essential information and model errors "
            "are unavailable advisory evidence. Reports parameter-dependent "
            "variation. "
            "One decision and at most one reasoning call; no check retries. "
            "Does not execute code "
            "or verify correctness; use separate correctness tools. May incur cost."
        ),
    )
    async def code_assess_template_difficulty(
        candidate: CodeTemplateCandidate,
    ) -> ToolEvidence:
        return await assess_template_difficulty(
            candidate,
            provider_factory=provider_factory,
            judge_timeout_seconds=judge_timeout_seconds,
            settings=settings,
        )
