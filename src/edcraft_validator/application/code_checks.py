"""Independently callable Python question checks with bounded execution."""

import asyncio
import math

from edcraft_validator.domains.code.difficulty import CodeDifficultyQuestion
from edcraft_validator.domains.code.question_checks import (
    RequirementCheck,
    TechnicalCheck,
    check_concrete_correctness,
    check_requirements,
)
from edcraft_validator.domains.code.relevance import CodeQuestionRequest
from edcraft_validator.tools.python_execution import (
    LocalPythonTool,
    PythonExecutionTool,
)


async def check_code_question_correctness(
    question: CodeDifficultyQuestion,
    *,
    execution_tool: PythonExecutionTool | None = None,
    execution_timeout_seconds: float = 2,
) -> TechnicalCheck:
    if not math.isfinite(execution_timeout_seconds) or execution_timeout_seconds <= 0:
        raise ValueError("execution timeout must be finite and positive")
    question = CodeDifficultyQuestion.model_validate_json(question.model_dump_json())
    try:
        async with asyncio.timeout(execution_timeout_seconds + 2):
            return await asyncio.to_thread(
                check_concrete_correctness,
                question,
                execution_tool or LocalPythonTool(),
                execution_timeout_seconds,
            )
    except TimeoutError:
        finding = "EXECUTION_TIMEOUT"
    except Exception:
        finding = "TECHNICAL_CHECK_ERROR"
    return TechnicalCheck(question_sha256=question.sha256, findings=[finding])


def check_code_question_requirements(
    question: CodeDifficultyQuestion, request: CodeQuestionRequest
) -> RequirementCheck:
    question = CodeDifficultyQuestion.model_validate_json(question.model_dump_json())
    request = CodeQuestionRequest.model_validate_json(request.model_dump_json())
    return check_requirements(question, request)
