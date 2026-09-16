"""Checks for the static structure and rendering of code templates."""

import ast

from edcraft_validator.domains.code.capabilities import (
    code_template_profile,
    extract_code_features,
)
from edcraft_validator.tools.python_analysis import analyze_python_subset
from edcraft_validator.validation.contracts import CheckResult

from .context import CodeValidationContext
from .generation import render_template
from .models import CodeTemplateCandidate, TemplateValidationError


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
    _validate_profile(template)
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


def _validate_profile(template: CodeTemplateCandidate) -> None:
    profile = code_template_profile(template.topic, template.difficulty)
    if template.answer_target != profile.answer_target:
        raise TemplateValidationError(
            f"{template.topic}/{template.difficulty} requires answer_target="
            f"{profile.answer_target}",
            code="PROFILE_MISMATCH",
            field="answer_target",
        )

    actual_kinds = tuple(parameter.kind for parameter in template.parameters)
    actual_names = tuple(parameter.name for parameter in template.parameters)
    if not any(
        actual_kinds == shape.kinds
        and (shape.names is None or actual_names == shape.names)
        for shape in profile.parameter_shapes
    ):
        expected = " or ".join(
            repr(shape.names or shape.kinds) for shape in profile.parameter_shapes
        )
        raise TemplateValidationError(
            f"{template.topic}/{template.difficulty} parameter profile requires "
            f"{expected}; received {actual_names} with kinds {actual_kinds}",
            code="PROFILE_MISMATCH",
            field="parameters",
        )

    if profile.require_positive_integers and any(
        value <= 0
        for parameter in template.parameters
        if parameter.kind == "integer"
        for value in parameter.values
    ):
        raise TemplateValidationError(
            f"{template.topic}/{template.difficulty} requires positive integer "
            "parameter values",
            code="PROFILE_MISMATCH",
            field="parameters",
        )

    if profile.required_parameter_values is not None:
        actual_values = tuple(
            tuple(parameter.values) for parameter in template.parameters
        )
        if actual_values != profile.required_parameter_values:
            raise TemplateValidationError(
                f"{template.topic}/{template.difficulty} requires parameter "
                f"values {profile.required_parameter_values}; received {actual_values}",
                code="PROFILE_MISMATCH",
                field="parameters",
            )

    actual_features = extract_code_features(template.code, template.entry_function)
    missing = profile.required_features - actual_features
    if missing:
        raise TemplateValidationError(
            f"{template.topic}/{template.difficulty} code is missing required "
            f"features: {', '.join(sorted(missing))}",
            code="PROFILE_MISMATCH",
            field="code",
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
