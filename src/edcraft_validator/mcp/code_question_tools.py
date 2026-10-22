"""Thin adapters for independent concrete Python question checks."""

from fastmcp import FastMCP

from edcraft_validator.application.code_checks import (
    check_code_question_correctness,
    check_code_question_requirements,
)
from edcraft_validator.domains.code.difficulty import CodeDifficultyQuestion
from edcraft_validator.domains.code.question_checks import (
    RequirementCheck,
    TechnicalCheck,
)
from edcraft_validator.domains.code.relevance import CodeQuestionRequest
from edcraft_validator.tools.python_execution import PythonExecutionTool


def register_code_question_tools(
    server: FastMCP,
    *,
    execution_tool: PythonExecutionTool,
    execution_timeout_seconds: float,
) -> None:
    @server.tool(
        name="check_code_question_correctness",
        version="1.0.0",
        tags={"quality:code"},
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        description=(
            "Check one complete Python tracing MCQ through bounded execution. "
            "Derives its canonical answer and checks the designated answer and "
            "distinct wrong option values. No embedding or judge calls; consumes "
            "no other assessment's evidence. Does not establish difficulty, "
            "wording clarity or relevance to an author request."
        ),
    )
    async def correctness(question: CodeDifficultyQuestion) -> TechnicalCheck:
        return await check_code_question_correctness(
            question,
            execution_tool=execution_tool,
            execution_timeout_seconds=execution_timeout_seconds,
        )

    @server.tool(
        name="check_code_question_requirements",
        version="1.0.0",
        tags={"quality:code"},
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        description=(
            "Check explicitly supplied Python syntax features in reachable "
            "functions, answer target and distractor count. No execution, "
            "embedding or judge calls; consumes no other assessment's evidence. "
            "Syntax presence does not prove concept necessity, free-text "
            "requirement coverage or answer correctness."
        ),
    )
    def requirements(
        question: CodeDifficultyQuestion, request: CodeQuestionRequest
    ) -> RequirementCheck:
        return check_code_question_requirements(question, request)
