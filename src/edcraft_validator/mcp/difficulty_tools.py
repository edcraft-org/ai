"""Explicit advisory tools kept outside the authoritative validation catalogue."""

import os
from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from edcraft_validator.application.code_difficulty import (
    CodeDifficultyReport,
    assess_code_question_difficulty,
)
from edcraft_validator.domains.code.code_types import Difficulty
from edcraft_validator.domains.code.difficulty import CodeDifficultyQuestion
from edcraft_validator.llm.judging import JudgeProviderFactory
from edcraft_validator.llm.llm_contracts import ModelProvider, TemplateProviderSelection
from edcraft_validator.llm.provider_registry import create_model_provider


def configured_difficulty_provider() -> ModelProvider:
    """Create a fresh provider per call; configuration is controlled by the host."""
    name = os.getenv("EDCRAFT_DIFFICULTY_PROVIDER", "").strip() or "soclaas"
    if name != "soclaas":
        raise ValueError("Difficulty checks use SocLaas only")
    return create_model_provider(
        TemplateProviderSelection(
            provider=name, model=os.getenv("EDCRAFT_DIFFICULTY_MODEL") or None
        )
    )


def register_difficulty_tools(
    server: FastMCP,
    *,
    provider_factory: JudgeProviderFactory,
    judge_timeout_seconds: float,
    request_builder=None,
) -> None:
    # Model responses are not deterministic; read-only still sends question data
    # to the host-configured provider and may incur inference cost.
    @server.tool(
        name="assess_code_difficulty",
        version="2.0.0",
        tags={"quality:code"},
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
        description=(
            "Explicit advisory assessment of one complete concrete Python tracing MCQ. "
            "Sends the supplied MCQ and answer designation to a "
            "host-configured LLM judge using the versioned difficulty rubric. "
            "Requested difficulty is hidden during estimation and compared afterwards. "
            "Selects one closest level, or unable_to_assess for missing information. "
            "Makes one assessment call and reports diagnostics, usage and latency; "
            "assessed means an assessment was produced, not a correctness pass or "
            "a difficulty match. Does not execute code or verify correctness; "
            "correctness checks belong to other tools. No template-wide "
            "difficulty or learner calibration is established. May incur model cost."
        ),
    )
    async def assess_code_difficulty(
        question: CodeDifficultyQuestion,
        requested_difficulty: Annotated[
            Difficulty | None,
            Field(description="Optional authoring target, hidden from the LLM judge."),
        ] = None,
    ) -> CodeDifficultyReport:
        return await assess_code_question_difficulty(
            question,
            requested_difficulty=requested_difficulty,
            provider_factory=provider_factory,
            judge_timeout_seconds=judge_timeout_seconds,
            request_builder=request_builder,
        )
