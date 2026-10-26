import json
from pathlib import Path

from edcraft_validator.domains.code.code_schemas import CodeTemplateCandidate
from edcraft_validator.mcp.code_checks.validation_context import (
    CodeValidationContext,
)


def test_context_uses_axis_boundaries_without_mutating_candidate():
    path = Path("examples/templates/arithmetic_linear.json")
    candidate = CodeTemplateCandidate.model_validate(json.loads(path.read_text()))
    original = candidate.model_dump()
    context = CodeValidationContext(candidate)
    assert len(context.inputs_cases) == 5
    assert all(tuple(case) == context.names for case in context.inputs_cases)
    context.template.distractors.clear()
    assert candidate.model_dump() == original
