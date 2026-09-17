"""Build code template candidates and append fallback distractors."""

from __future__ import annotations

import hashlib
import json

from edcraft_validator.domains.code.code_schemas import (
    CodeTemplateCandidate,
    CodeTemplateProposal,
    CodeTemplateRequest,
    DistractorRecipe,
    TemplateValidationError,
)
from edcraft_validator.domains.code.code_types import AnswerTarget
from edcraft_validator.domains.code.profiles import code_template_profile


def build_code_candidate(
    request: CodeTemplateRequest, proposal: CodeTemplateProposal
) -> CodeTemplateCandidate:
    """Build the canonical code template from a model proposal."""
    if len(proposal.distractors) < request.num_distractors:
        raise TemplateValidationError(
            f"expected at least {request.num_distractors} distractor candidates, "
            f"received {len(proposal.distractors)}",
            code="DISTRACTOR_COUNT_INVALID",
            field="distractors",
        )
    profile = code_template_profile(request.topic, request.difficulty)
    identity_payload = json.dumps(
        {
            "request": request.model_dump(mode="json"),
            "proposal": proposal.model_dump(mode="json"),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    digest = hashlib.sha256(identity_payload).hexdigest()[:12]
    return CodeTemplateCandidate(
        template_id=f"{request.topic}.{request.difficulty}.{digest}",
        topic=request.topic,
        difficulty=request.difficulty,
        code=proposal.code,
        entry_function=proposal.entry_function,
        parameters=proposal.parameters,
        question_template=_question_template(
            profile.answer_target,
            proposal.entry_function,
            tuple(parameter.name for parameter in proposal.parameters),
        ),
        answer_target=profile.answer_target,
        answer_expression=proposal.answer_expression,
        distractors=_with_deterministic_fallbacks(
            proposal.distractors,
            answer_expression=proposal.answer_expression,
            answer_kind=profile.answer_kind,
        ),
        question_type="mcq",
    )


def _with_deterministic_fallbacks(
    model_candidates: list[DistractorRecipe],
    *,
    answer_expression: str,
    answer_kind: str,
) -> list[DistractorRecipe]:
    if answer_kind == "integer_list":
        fallback_expressions = [
            f"({answer_expression}) + [{offset}]" for offset in range(3)
        ]
        reason = "Appends an extra value to the result list."
    else:
        fallback_expressions = [
            f"({answer_expression}) + {offset}" for offset in range(1, 4)
        ]
        reason = "Applies an off-by-one-style adjustment to the correct result."

    result = list(model_candidates)
    existing = {candidate.expression for candidate in result}
    for expression in fallback_expressions:
        if expression not in existing:
            result.append(
                DistractorRecipe(expression=expression, reason_template=reason)
            )
            existing.add(expression)
    return result


def _question_template(
    target: AnswerTarget, entry_function: str, parameter_names: tuple[str, ...]
) -> str:
    arguments = ", ".join(f"{{{name}}}" for name in parameter_names)
    invocation = f"{entry_function}({arguments})"
    wording = {
        "return_value": f"What value does {invocation} return?",
        "loop_iterations": (
            f"How many total loop-body iterations occur when {invocation} runs?"
        ),
        "loop_executions": (
            f"How many loop statements are encountered when {invocation} runs?"
        ),
        "branch_executions": (
            f"How many if conditions are evaluated when {invocation} runs?"
        ),
        "function_calls": (
            f"How many traced function calls occur when {invocation} runs, including "
            "the entry function and safe built-ins?"
        ),
    }
    return wording[target]
