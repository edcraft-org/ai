"""Code prompt construction and canonical template building."""

from __future__ import annotations

import hashlib
import json

from edcraft_validator.domains.code.capabilities import code_template_profile
from edcraft_validator.domains.code.models import CodeTemplateAuthoringRequest
from edcraft_validator.models import AnswerTarget

from .models import (
    CodeQuestionTemplate,
    CodeTemplateProposal,
    DistractorRecipe,
    TemplateValidationError,
)

CODE_TEMPLATE_PROMPT_VERSION = "code-template-v8"


def parse_code_question_template(content: str) -> CodeQuestionTemplate:
    """Parse template JSON with strict local schema validation."""
    payload = json.loads(content)
    return CodeQuestionTemplate.model_validate(payload)


def parse_code_template_proposal(content: str) -> CodeTemplateProposal:
    """Parse a provider proposal with strict local schema validation."""
    payload = json.loads(content)
    return CodeTemplateProposal.model_validate(payload)


def build_code_template(
    request: CodeTemplateAuthoringRequest, proposal: CodeTemplateProposal
) -> CodeQuestionTemplate:
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
    return CodeQuestionTemplate(
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


def build_template_prompt(request: CodeTemplateAuthoringRequest) -> str:
    profile = code_template_profile(request.topic, request.difficulty)
    candidate_count = request.num_distractors
    shapes = [
        {
            "kinds": list(shape.kinds),
            "names": list(shape.names) if shape.names is not None else None,
        }
        for shape in profile.parameter_shapes
    ]
    contract = json.dumps(
        {
            "topic": profile.topic,
            "difficulty": profile.difficulty,
            "answer_target": profile.answer_target,
            "answer_kind": profile.answer_kind,
            "accepted_parameter_shapes": shapes,
            "required_code_features": sorted(profile.required_features),
            "positive_integer_values_required": profile.require_positive_integers,
            "required_parameter_values": profile.required_parameter_values,
            "authoring_requirements": profile.guidance,
        },
        indent=2,
        sort_keys=True,
    )
    prompt = (
        "Follow this exact capability contract. Choose exactly one accepted parameter "
        "shape. A null names value means choose valid names but preserve the exact "
        "number, order, and kinds. Do not add parameters.\n"
        f"{contract}\n"
        f"Use answer_target={profile.answer_target}. "
        f"Create exactly {candidate_count} distractor candidates; the local validator "
        f"will select {request.num_distractors}. Every candidate should model a real "
        "misconception and should differ from the answer and other candidates for the "
        "complete Cartesian product. The local application adds mechanical fallback "
        "candidates; do not add generic answer-plus-constant fallbacks yourself. In "
        "reason_template, use only plain placeholders such as "
        "`{n}`; never put expressions such as `{n-1}` inside braces. "
        "Keep the complete Cartesian product valid."
    )
    return prompt


CODE_TEMPLATE_SYSTEM_PROMPT = """\
Generate the judgment-bearing fields for one reusable Python execution-trace MCQ
template, not one concrete question. The local application derives identity, topic,
difficulty, answer target, question wording, version, and question type.

The proposal must use a finite Cartesian product of typed finite parameter values so
the local application can exhaustively validate every possible question once.

Rules:
- `code` is the learner-facing Python program that the question asks about. It must
  directly perform the selected topic's computation or control flow. Never write a
  question generator, template generator, metadata dictionary, schema, or code that
  stores answer/distractor expressions as strings. Keep code, answer_expression, and
  distractor candidates as separate schema fields.
- Define one module-level entry function whose positional arguments exactly match the
  parameter names and order. Use every parameter in executed learner-facing behavior.
  Helper functions are allowed. The code must work for every parameter combination.
- Use only expressions, assignments, if statements, and for loops. Do not use imports,
  attributes, classes, decorators, recursion, comprehensions, while loops, lambdas,
  exceptions, file access, networking, input, eval, or exec.
- Every parameter declares a kind and two to four distinct finite values. Supported
  kinds are integer (-100 through 100), boolean, string (non-empty short printable
  text), and
  integer_list (at most eight integers from -100 through 100). Use JSON booleans.
- The user prompt states the selected answer target. answer_expression must calculate
  that target using parameter names,
  numeric constants, arithmetic, comparisons, boolean operators, or a conditional
  expression. String constants, list literals, indexing, and the one-argument functions
  len, sum, min, max, sorted, all, and any are also supported. Do not use methods or
  other function calls.
- Each distractor candidate must represent a specific misconception. The local
  validator selects candidates that are unique, type-compatible, and different from
  the answer for every parameter combination. The local application adds mechanical
  fallback candidates after the provider response.
- reason_template explains its misconception and may use only a bare parameter
  placeholder such as `{n}`. Do not place arithmetic or any other expression inside
  braces.
- Return only the proposal schema fields and no markdown. Do not add locally derived
  fields.
"""
