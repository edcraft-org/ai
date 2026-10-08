"""Direct checking-operation helpers; workflow integration tests use actual MCP."""

from edcraft_validator.domains.code.code_domain import CodeDomain
from edcraft_validator.mcp.code_tools import (
    CODE_TOOL_VERSION,
    validate_answers_and_distractors,
)
from edcraft_validator.mcp.evidence import ToolEvidence


def validate_code(candidate, *, execution_tool, num_distractors=3):
    details = validate_answers_and_distractors(
        candidate, num_distractors, execution_tool=execution_tool, timeout_seconds=2
    )
    return CodeDomain().finalize_checked_template(
        candidate,
        [
            ToolEvidence(
                tool="code_validate_answers_and_distractors",
                version=CODE_TOOL_VERSION,
                status="passed",
                details=details,
            )
        ],
    )
