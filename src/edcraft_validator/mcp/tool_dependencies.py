"""Resolved dependencies that domain tool registration consumes."""

from dataclasses import dataclass

from edcraft_validator.llm.judge_configuration import JudgeSettings
from edcraft_validator.llm.judging import JudgeProviderFactory
from edcraft_validator.tools.python_execution import PythonExecutionTool
from edcraft_validator.validation.property_checks import PropertyCheckSettings


@dataclass(frozen=True)
class ToolDependencies:
    """Settings and services resolved once by the server for every domain."""

    execution_tool: PythonExecutionTool
    code_execution_timeout_seconds: float
    property_settings: PropertyCheckSettings | None
    difficulty_provider_factory: JudgeProviderFactory
    difficulty_judge_timeout_seconds: float
    judge_settings: JudgeSettings
    fidelity_provider_factory: JudgeProviderFactory
    fidelity_timeout_seconds: float
