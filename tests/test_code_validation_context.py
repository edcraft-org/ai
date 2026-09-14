import json
from pathlib import Path

from edcraft_validator.domains.code.templates.context import CodeValidationContext
from edcraft_validator.domains.code.templates.models import CodeTemplateCandidate


def test_context_enumerates_cases_without_mutating_candidate():
    path = Path("examples/templates/arithmetic_linear.json")
    candidate = CodeTemplateCandidate.model_validate(json.loads(path.read_text()))
    original = candidate.model_dump()
    context = CodeValidationContext(candidate)
    assert len(context.inputs_cases) == 8
    assert all(tuple(case) == context.names for case in context.inputs_cases)
    context.template.distractors.clear()
    assert candidate.model_dump() == original
    assert context.original_distractor_count == len(candidate.distractors)
