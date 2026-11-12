"""FastMCP server exposing technical checks and separate advisory assessments."""

import math
from functools import partial

from fastmcp import FastMCP

from edcraft_validator.llm.decision import (
    ConfiguredDecisionProvider,
    DecisionProviderFactory,
)
from edcraft_validator.llm.judge_configuration import (
    JudgeSettings,
    configured_judge_provider,
    load_judge_settings,
)
from edcraft_validator.llm.judging import (
    DEFAULT_JUDGE_TIMEOUT_SECONDS,
    JudgeProviderFactory,
)
from edcraft_validator.mcp.check_pilot_tools import register_check_pilot_tools
from edcraft_validator.mcp.code_checks.property_checks import PropertyCheckSettings
from edcraft_validator.mcp.code_question_tools import register_code_question_tools
from edcraft_validator.mcp.code_tools import register_code_validation_tools
from edcraft_validator.mcp.difficulty_tools import register_difficulty_tools
from edcraft_validator.mcp.math_tools import register_math_tools
from edcraft_validator.mcp.relevance_tools import register_relevance_tools
from edcraft_validator.tools.python_execution import (
    LocalPythonTool,
    PythonExecutionTool,
)


def create_validation_server(
    *,
    code_execution_tool: PythonExecutionTool | None = None,
    code_execution_timeout_seconds: float = 2.0,
    difficulty_provider_factory: JudgeProviderFactory | None = None,
    difficulty_judge_timeout_seconds: float = DEFAULT_JUDGE_TIMEOUT_SECONDS,
    decision_provider_factory: DecisionProviderFactory | None = None,
    relevance_timeout_seconds: float = 35.0,
    fidelity_judge_timeout_seconds: float = 60.0,
    template_property_settings: PropertyCheckSettings | None = None,
    judge_settings: JudgeSettings | None = None,
) -> FastMCP:
    """Build the centralized server with injectable code-domain dependencies."""
    for timeout in (
        code_execution_timeout_seconds,
        difficulty_judge_timeout_seconds,
        relevance_timeout_seconds,
        fidelity_judge_timeout_seconds,
    ):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("tool timeouts must be finite and positive")
    server = FastMCP(
        name="EdCraft Validation Tools",
        strict_input_validation=True,
        mask_error_details=True,
    )
    selected = judge_settings if judge_settings is not None else load_judge_settings()
    execution_tool = code_execution_tool or LocalPythonTool()
    register_code_validation_tools(
        server,
        execution_tool=execution_tool,
        timeout_seconds=code_execution_timeout_seconds,
        property_settings=template_property_settings,
    )
    register_difficulty_tools(
        server,
        provider_factory=difficulty_provider_factory
        or partial(configured_judge_provider, selected),
        judge_timeout_seconds=difficulty_judge_timeout_seconds,
        settings=selected,
    )
    register_code_question_tools(
        server,
        execution_tool=execution_tool,
        execution_timeout_seconds=code_execution_timeout_seconds,
    )
    register_math_tools(
        server,
        fidelity_provider_factory=partial(configured_judge_provider, selected),
        fidelity_timeout_seconds=fidelity_judge_timeout_seconds,
    )
    register_check_pilot_tools(server)
    register_relevance_tools(
        server,
        decision_provider_factory=decision_provider_factory
        or partial(ConfiguredDecisionProvider, selected),
        relevance_timeout_seconds=relevance_timeout_seconds,
    )
    return server
