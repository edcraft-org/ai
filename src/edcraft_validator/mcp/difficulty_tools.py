"""Shared advisory template difficulty tool.

Every domain supplies its rubric identifier and a blinded payload. The cascade
stays identical across domains, so the tool is registered once and offered to any
domain that declares the difficulty capability.
"""

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from edcraft_validator.application.template_difficulty import (
    assess_template_difficulty,
)
from edcraft_validator.domain_types import (
    MAX_DISTRACTOR_CANDIDATES,
    MIN_DISTRACTORS,
    Difficulty,
)
from edcraft_validator.llm.judge_configuration import JudgeSettings
from edcraft_validator.llm.judging import JudgeProviderFactory
from edcraft_validator.validation.check_contracts import ToolEvidence
from edcraft_validator.validation.check_names import (
    TEMPLATE_DIFFICULTY_CAPABILITY,
    TEMPLATE_DIFFICULTY_CHECK,
    TEMPLATE_DIFFICULTY_TOOL_VERSION,
)


def register_difficulty_tools(
    server: FastMCP,
    *,
    provider_factory: JudgeProviderFactory,
    judge_timeout_seconds: float,
    settings: JudgeSettings | None = None,
) -> None:
    # Model responses are not deterministic. Read-only still sends template data
    # to the host-configured provider and may incur inference cost.
    @server.tool(
        name=TEMPLATE_DIFFICULTY_CHECK,
        version=TEMPLATE_DIFFICULTY_TOOL_VERSION,
        tags={
            f"capability:{TEMPLATE_DIFFICULTY_CAPABILITY}",
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
            "Assess the difficulty of a reusable question template with the "
            "domain's registered rubric. The application supplies the rubric "
            "identifier, the blinded template payload, the distractor count, the "
            "unchanged requested level and the exact checked subject identity. Use "
            "no model-owned arguments. The configured model estimates the typical "
            "instance across the declared parameter distribution. A forced "
            "decision is accepted at token confidence >=0.70. Otherwise the same "
            "model reasons about the template using the rubric's structured shape. "
            "Difficulty mismatches are advisory. They never request author "
            "revision or block a technically checked artifact. Rubric levels are "
            "provisional conventions and reasoning confidence is not calibrated "
            "accuracy. Missing essential information and model errors are "
            "unavailable advisory evidence. Reports parameter-dependent variation. "
            "One decision and at most one reasoning call, with no check retries. "
            "Does not verify correctness or execute the template. May incur cost."
        ),
    )
    async def shared_template_difficulty(
        rubric_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9.-]*$")],
        question_payload: Annotated[str, Field(min_length=1, max_length=200_000)],
        distractor_count: Annotated[
            int, Field(ge=MIN_DISTRACTORS, le=MAX_DISTRACTOR_CANDIDATES)
        ],
        requested_difficulty: Difficulty,
        subject_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")],
    ) -> ToolEvidence:
        return await assess_template_difficulty(
            rubric_id=rubric_id,
            question_payload=question_payload,
            distractor_count=distractor_count,
            requested_difficulty=requested_difficulty,
            subject_sha256=subject_sha256,
            provider_factory=provider_factory,
            judge_timeout_seconds=judge_timeout_seconds,
            settings=settings,
        )
