"""Reusable, exhaustively validated templates for Python questions."""

from .authoring import (
    CODE_TEMPLATE_PROMPT_VERSION,
    CODE_TEMPLATE_SYSTEM_PROMPT,
    build_code_template,
    build_template_prompt,
    parse_code_question_template,
    parse_code_template_proposal,
)
from .expressions import SafeExpression
from .generation import generate_template_instance, render_template
from .models import (
    ApprovedCodeQuestionTemplate,
    CodeQuestionTemplate,
    CodeTemplateProposal,
    DistractorRecipe,
    FiniteParameter,
    ParameterValue,
    TemplateQuestionInstance,
    TemplateValidationError,
    TemplateValidationSummary,
    ValidatedTemplateCase,
)
from .validation import CODE_TEMPLATE_VALIDATOR_VERSION, TemplateValidator

__all__ = [
    "ApprovedCodeQuestionTemplate",
    "CODE_TEMPLATE_PROMPT_VERSION",
    "CODE_TEMPLATE_SYSTEM_PROMPT",
    "CODE_TEMPLATE_VALIDATOR_VERSION",
    "CodeQuestionTemplate",
    "CodeTemplateProposal",
    "DistractorRecipe",
    "FiniteParameter",
    "ParameterValue",
    "SafeExpression",
    "TemplateQuestionInstance",
    "TemplateValidationError",
    "TemplateValidationSummary",
    "TemplateValidator",
    "ValidatedTemplateCase",
    "build_template_prompt",
    "build_code_template",
    "generate_template_instance",
    "parse_code_question_template",
    "parse_code_template_proposal",
    "render_template",
]
