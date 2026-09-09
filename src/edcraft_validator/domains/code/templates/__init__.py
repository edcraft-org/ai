"""Reusable, exhaustively validated templates for Python questions."""

from .authoring import (
    CODE_TEMPLATE_PROMPT_VERSION,
    CODE_TEMPLATE_SYSTEM_PROMPT,
    build_code_candidate,
    build_template_prompt,
    parse_code_template_candidate,
    parse_code_template_proposal,
)
from .expressions import SafeExpression
from .generation import generate_code_question, render_template
from .models import (
    CodeQuestionInstance,
    CodeTemplateCandidate,
    CodeTemplateProposal,
    DistractorRecipe,
    FiniteParameter,
    ParameterValue,
    TemplateValidationError,
    TemplateValidationSummary,
    ValidatedCodeTemplate,
    ValidatedTemplateCase,
)
from .validation import CODE_TEMPLATE_VALIDATOR_VERSION, TemplateValidator

__all__ = [
    "ValidatedCodeTemplate",
    "CODE_TEMPLATE_PROMPT_VERSION",
    "CODE_TEMPLATE_SYSTEM_PROMPT",
    "CODE_TEMPLATE_VALIDATOR_VERSION",
    "CodeTemplateCandidate",
    "CodeTemplateProposal",
    "DistractorRecipe",
    "FiniteParameter",
    "ParameterValue",
    "SafeExpression",
    "CodeQuestionInstance",
    "TemplateValidationError",
    "TemplateValidationSummary",
    "TemplateValidator",
    "ValidatedTemplateCase",
    "build_template_prompt",
    "build_code_candidate",
    "generate_code_question",
    "parse_code_template_candidate",
    "parse_code_template_proposal",
    "render_template",
]
