"""Checks for the static structure and rendering of code templates."""

import ast

from edcraft_validator.domains.code.checks.validation_context import (
    CodeValidationContext,
)
from edcraft_validator.domains.code.code_schemas import (
    CodeTemplateCandidate,
    TemplateValidationError,
)
from edcraft_validator.domains.code.text_rendering import render_template
from edcraft_validator.tools.python_analysis import analyze_python_subset
from edcraft_validator.validation.validation_contracts import CheckResult


def check_structure(context: CodeValidationContext) -> CheckResult:
    """Validate code, profile, parameters, and the question template."""
    _validate_structure(context.template, context.names)
    if context.num_distractors is not None and not 2 <= context.num_distractors <= 3:
        raise ValueError("num_distractors must be 2 or 3")
    return CheckResult()


def check_rendering(context: CodeValidationContext) -> CheckResult:
    """Render every learner-facing template for every input case."""
    for inputs in context.inputs_cases:
        render_template(context.template.question_template, inputs, require_all=True)
        for recipe in context.template.distractors:
            render_template(recipe.reason_template, inputs)
    return CheckResult()


def _validate_structure(
    template: CodeTemplateCandidate, names: tuple[str, ...]
) -> None:
    analysis = analyze_python_subset(template.code, template.entry_function)
    if not analysis.is_valid:
        raise TemplateValidationError(
            "; ".join(analysis.errors),
            code="UNSUPPORTED_CODE",
            field="code",
        )
    arguments = _entry_function_arguments(template.code, template.entry_function)
    if arguments != names:
        raise TemplateValidationError(
            "entry function arguments must exactly match parameter order: "
            f"expected {names}, received {arguments}",
            code="ENTRY_FUNCTION_MISMATCH",
            field="entry_function",
        )
    unused = _unused_entry_parameters(template.code, template.entry_function, arguments)
    if unused:
        raise TemplateValidationError(
            "entry function parameters must affect learner-facing behavior; "
            f"unused parameters: {', '.join(unused)}",
            code="UNUSED_PARAMETER",
            field="parameters",
        )
    if template.entry_function not in template.question_template:
        raise TemplateValidationError(
            "question_template must name the entry function",
            code="QUESTION_TEMPLATE_INVALID",
            field="question_template",
        )
    render_template(
        template.question_template,
        {name: 0 for name in names},
        require_all=True,
    )


def _entry_function_arguments(code: str, entry_function: str) -> tuple[str, ...]:
    tree = ast.parse(code)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == entry_function:
            if (
                node.args.posonlyargs
                or node.args.kwonlyargs
                or node.args.vararg
                or node.args.kwarg
                or node.args.defaults
                or node.args.kw_defaults
            ):
                raise TemplateValidationError(
                    "entry function must use plain positional arguments "
                    "without defaults"
                )
            return tuple(argument.arg for argument in node.args.args)
    raise TemplateValidationError("entry function is not defined")


def _unused_entry_parameters(
    code: str, entry_function: str, parameters: tuple[str, ...]
) -> tuple[str, ...]:
    tree = ast.parse(code)
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    loaded: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Name) or not isinstance(node.ctx, ast.Load):
            continue
        current = parents.get(node)
        while current is not None and not isinstance(current, ast.FunctionDef):
            current = parents.get(current)
        if isinstance(current, ast.FunctionDef) and current.name == entry_function:
            loaded.add(node.id)
    return tuple(parameter for parameter in parameters if parameter not in loaded)
