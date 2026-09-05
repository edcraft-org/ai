"""Supported code-question capabilities and authoring profiles."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Literal, get_args

from edcraft_validator.models import AnswerTarget

ProgrammingTopic = Literal[
    "arithmetic",
    "conditionals",
    "loops",
    "functions",
    "lists",
]
Difficulty = Literal["beginner", "intermediate", "advanced"]
ParameterKind = Literal["integer", "boolean", "string", "integer_list"]
AnswerKind = Literal["number", "integer", "integer_list"]
CodeFeature = Literal[
    "arithmetic",
    "conditional",
    "early_return",
    "helper_function",
    "list_aggregate",
    "list_index",
    "list_sort",
    "loop",
    "nested_conditional",
    "nested_helper",
    "nested_loop",
    "sequential_conditionals",
    "sequential_loops",
]

CODE_TOPICS: tuple[ProgrammingTopic, ...] = get_args(ProgrammingTopic)
CODE_DIFFICULTIES: tuple[Difficulty, ...] = get_args(Difficulty)


@dataclass(frozen=True)
class ParameterShape:
    """One accepted ordered parameter shape for a profile."""

    kinds: tuple[ParameterKind, ...]
    names: tuple[str, ...] | None = None


@dataclass(frozen=True)
class CodeTemplateProfile:
    """Machine-readable contract for one advertised code capability."""

    topic: ProgrammingTopic
    difficulty: Difficulty
    answer_target: AnswerTarget
    parameter_shapes: tuple[ParameterShape, ...]
    required_features: frozenset[CodeFeature]
    guidance: str
    answer_kind: AnswerKind
    require_positive_integers: bool = False
    required_parameter_values: tuple[tuple[object, ...], ...] | None = None


def _shape(
    *kinds: ParameterKind, names: tuple[str, ...] | None = None
) -> ParameterShape:
    return ParameterShape(kinds=kinds, names=names)


_PROFILES = (
    CodeTemplateProfile(
        "arithmetic",
        "beginner",
        "return_value",
        (
            _shape("integer", "integer", names=("a", "b")),
            _shape("integer", "integer", "integer", names=("a", "b", "c")),
        ),
        frozenset({"arithmetic"}),
        "Use two or three integer parameters named a, b, and optionally c, in that "
        "order, with one short arithmetic expression. Give each parameter two to "
        "four distinct values. Do not create a parameter for the operator.",
        "number",
    ),
    CodeTemplateProfile(
        "arithmetic",
        "intermediate",
        "return_value",
        (_shape("integer", "integer", "boolean"),),
        frozenset({"arithmetic", "conditional"}),
        "Combine two integer parameters and one boolean parameter with one "
        "conditional adjustment.",
        "number",
    ),
    CodeTemplateProfile(
        "arithmetic",
        "advanced",
        "return_value",
        (_shape("integer_list", "string"),),
        frozenset({"arithmetic", "conditional", "list_aggregate"}),
        "Use exactly an integer_list and a string mode. Call an allowlisted aggregate "
        "such as sum in code; the aggregate must not be a third parameter.",
        "number",
    ),
    CodeTemplateProfile(
        "conditionals",
        "beginner",
        "branch_executions",
        (_shape("boolean"),),
        frozenset({"conditional"}),
        "Use one boolean parameter and a short nested or early-return branch.",
        "integer",
    ),
    CodeTemplateProfile(
        "conditionals",
        "intermediate",
        "branch_executions",
        (_shape("string", names=("mode",)),),
        frozenset({"conditional", "early_return", "sequential_conditionals"}),
        "Use exactly one string parameter named mode with values `express`, "
        "`standard`, and `economy`. Test express first and return early, then test "
        "standard and return early. answer_expression must be exactly "
        '`1 if mode == "express" else 2`.',
        "integer",
        required_parameter_values=(("express", "standard", "economy"),),
    ),
    CodeTemplateProfile(
        "conditionals",
        "advanced",
        "branch_executions",
        (_shape("integer", "boolean", names=("score", "override")),),
        frozenset({"conditional", "early_return", "nested_conditional"}),
        "Use integer score and boolean override parameters. First test override and "
        "return early. Then test score >= 50, with a nested score >= 80 test. "
        "answer_expression must be exactly `1 if override else (3 if score >= 50 "
        "else 2)`.",
        "integer",
    ),
    CodeTemplateProfile(
        "loops",
        "beginner",
        "loop_iterations",
        (_shape("integer", names=("n",)),),
        frozenset({"loop"}),
        "Use exactly one integer parameter named n with positive values from 2 "
        "through 6, exactly one `for i in range(n)` loop, and answer_expression "
        "exactly `n`.",
        "integer",
        require_positive_integers=True,
    ),
    CodeTemplateProfile(
        "loops",
        "intermediate",
        "loop_iterations",
        (_shape("integer", "integer", names=("n", "m")),),
        frozenset({"loop", "sequential_loops"}),
        "Use positive integer parameters n and m with two sequential range loops; "
        "the total loop_iterations expression should be `n + m`.",
        "integer",
        require_positive_integers=True,
    ),
    CodeTemplateProfile(
        "loops",
        "advanced",
        "loop_iterations",
        (_shape("integer", "integer", names=("n", "m")),),
        frozenset({"loop", "nested_loop"}),
        "Use positive integer parameters n and m with one nested range loop; the "
        "total loop_iterations expression should be `n + n * m`.",
        "integer",
        require_positive_integers=True,
    ),
    CodeTemplateProfile(
        "functions",
        "beginner",
        "function_calls",
        (_shape("integer"),),
        frozenset({"helper_function"}),
        "Define exactly one module-level helper and call it once from the entry "
        "function. Make no other calls. answer_expression must be exactly `2` for "
        "the entry call plus the helper call.",
        "integer",
    ),
    CodeTemplateProfile(
        "functions",
        "intermediate",
        "function_calls",
        (_shape("integer", names=("n",)),),
        frozenset({"helper_function", "loop"}),
        "Define exactly one module-level helper. The entry function must call "
        "range(n) once and call the helper exactly once per loop iteration. Make no "
        "other calls. answer_expression must be exactly `n + 2` for the entry, "
        "range, and n helper calls.",
        "integer",
        require_positive_integers=True,
    ),
    CodeTemplateProfile(
        "functions",
        "advanced",
        "function_calls",
        (_shape("integer", names=("n",)),),
        frozenset({"helper_function", "loop", "nested_helper"}),
        "Define exactly two module-level helpers: a middle helper calls the leaf "
        "helper exactly twice, and the entry calls range(n) once and the middle "
        "helper once per iteration. Make no other calls and do not define a function "
        "inside another function. answer_expression must be exactly `3 * n + 2` for "
        "the entry, range, n middle, and 2*n leaf calls.",
        "integer",
        require_positive_integers=True,
    ),
    CodeTemplateProfile(
        "lists",
        "beginner",
        "return_value",
        (_shape("integer_list", names=("values",)),),
        frozenset({"list_aggregate"}),
        "Use exactly one integer_list parameter named values. The entry-function "
        "body must be exactly `return sum(values)`, and answer_expression must be "
        "exactly `sum(values)`.",
        "integer",
    ),
    CodeTemplateProfile(
        "lists",
        "intermediate",
        "return_value",
        (_shape("integer_list", names=("values",)),),
        frozenset({"list_sort"}),
        "Use exactly one integer_list parameter named values. The entry-function "
        "body must be exactly `return sorted(values)`, and answer_expression must be "
        "exactly `sorted(values)`.",
        "integer_list",
    ),
    CodeTemplateProfile(
        "lists",
        "advanced",
        "return_value",
        (_shape("integer_list", names=("values",)),),
        frozenset({"arithmetic", "list_index"}),
        "Use one integer_list parameter named values and combine indexing with an "
        "aggregate or arithmetic expression.",
        "integer",
    ),
)

CODE_TEMPLATE_PROFILES = {
    (profile.topic, profile.difficulty): profile for profile in _PROFILES
}

if set(CODE_TEMPLATE_PROFILES) != {
    (topic, difficulty) for topic in CODE_TOPICS for difficulty in CODE_DIFFICULTIES
}:
    raise RuntimeError("code template profiles must cover every topic and difficulty")


def code_template_profile(
    topic: ProgrammingTopic, difficulty: Difficulty
) -> CodeTemplateProfile:
    return CODE_TEMPLATE_PROFILES[(topic, difficulty)]


def extract_code_features(code: str, entry_function: str) -> frozenset[CodeFeature]:
    """Extract the structural features used by code capability profiles."""
    tree = ast.parse(code)
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    all_functions = {
        node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)
    }
    reachable_names = _reachable_function_names(all_functions, entry_function)
    functions = [
        function for name, function in all_functions.items() if name in reachable_names
    ]
    helper_names = reachable_names - {entry_function}
    nodes = [node for function in functions for node in ast.walk(function)]
    features: set[CodeFeature] = set()

    if helper_names:
        features.add("helper_function")
    if any(isinstance(node, ast.BinOp) for node in nodes):
        features.add("arithmetic")
    if any(isinstance(node, ast.If) for node in nodes):
        features.add("conditional")
    if any(isinstance(node, ast.For) for node in nodes):
        features.add("loop")
    if any(isinstance(node, ast.Subscript) for node in nodes):
        features.add("list_index")

    calls = [node for node in nodes if isinstance(node, ast.Call)]
    called_names = {node.func.id for node in calls if isinstance(node.func, ast.Name)}
    if called_names & {"all", "any", "max", "min", "sum"}:
        features.add("list_aggregate")
    if "sorted" in called_names:
        features.add("list_sort")

    if_nodes = [node for node in ast.walk(tree) if isinstance(node, ast.If)]
    if any(_has_ancestor(node, ast.If, parents) for node in if_nodes):
        features.add("nested_conditional")
    if any(
        isinstance(node, ast.Return) and _has_ancestor(node, ast.If, parents)
        for node in nodes
    ):
        features.add("early_return")
    if _has_sequential_nodes(functions, ast.If, parents):
        features.add("sequential_conditionals")

    for_nodes = [node for node in ast.walk(tree) if isinstance(node, ast.For)]
    if any(_has_ancestor(node, ast.For, parents) for node in for_nodes):
        features.add("nested_loop")
    if _has_sequential_nodes(functions, ast.For, parents):
        features.add("sequential_loops")

    if any(
        isinstance(node.func, ast.Name)
        and node.func.id in helper_names
        and (_nearest_function(node, parents) or "") in helper_names
        for node in calls
    ):
        features.add("nested_helper")
    return frozenset(features)


def profile_semantic_violation(
    profile: CodeTemplateProfile,
    code: str,
    entry_function: str,
    answer_expression: str,
) -> tuple[str, str] | None:
    """Return the first exact profile-contract violation, if any."""
    tree = ast.parse(code)
    functions = {
        node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)
    }
    entry = functions.get(entry_function)
    if entry is None:
        return "code", "entry function is not defined"
    key = (profile.topic, profile.difficulty)

    expected_expressions = {
        ("conditionals", "advanced"): ("1 if override else (3 if score >= 50 else 2)"),
        ("conditionals", "intermediate"): '1 if mode == "express" else 2',
        ("loops", "beginner"): "n",
        ("loops", "intermediate"): "n + m",
        ("loops", "advanced"): "n + n * m",
        ("functions", "beginner"): "2",
        ("functions", "intermediate"): "n + 2",
        ("functions", "advanced"): "3 * n + 2",
        ("lists", "beginner"): "sum(values)",
        ("lists", "intermediate"): "sorted(values)",
    }
    expected_expression = expected_expressions.get(key)
    if expected_expression is not None and not _same_expression(
        answer_expression, expected_expression
    ):
        return (
            "answer_expression",
            f"{profile.topic}/{profile.difficulty} requires answer_expression "
            f"equivalent to `{expected_expression}`",
        )

    if key == ("conditionals", "intermediate"):
        error = _intermediate_conditional_error(entry)
    elif profile.topic == "loops":
        error = _loop_profile_error(entry, profile.difficulty)
    elif profile.topic == "functions":
        error = _function_profile_error(functions, entry, profile.difficulty)
    elif key == ("lists", "beginner"):
        error = _single_return_call_error(entry, "sum", "values")
    elif key == ("lists", "intermediate"):
        error = _single_return_call_error(entry, "sorted", "values")
    else:
        error = None
    return ("code", error) if error is not None else None


def _intermediate_conditional_error(entry: ast.FunctionDef) -> str | None:
    if len(entry.body) != 3:
        return "conditionals/intermediate requires two sequential ifs and one return"
    first, second, final = entry.body
    if not (
        isinstance(first, ast.If)
        and isinstance(second, ast.If)
        and isinstance(final, ast.Return)
        and _string_equality(first.test, "mode", "express")
        and _string_equality(second.test, "mode", "standard")
        and len(first.body) == 1
        and isinstance(first.body[0], ast.Return)
        and not first.orelse
        and len(second.body) == 1
        and isinstance(second.body[0], ast.Return)
        and not second.orelse
    ):
        return (
            'conditionals/intermediate requires sequential `mode == "express"` '
            'and `mode == "standard"` early-return conditions'
        )
    return None


def _string_equality(node: ast.AST, name: str, value: str) -> bool:
    return (
        isinstance(node, ast.Compare)
        and isinstance(node.left, ast.Name)
        and node.left.id == name
        and len(node.ops) == 1
        and isinstance(node.ops[0], ast.Eq)
        and len(node.comparators) == 1
        and isinstance(node.comparators[0], ast.Constant)
        and node.comparators[0].value == value
    )


def _same_expression(actual: str, expected: str) -> bool:
    try:
        actual_node = ast.parse(actual, mode="eval").body
        expected_node = ast.parse(expected, mode="eval").body
    except SyntaxError:
        return False
    return ast.dump(actual_node, include_attributes=False) == ast.dump(
        expected_node, include_attributes=False
    )


def _loop_profile_error(entry: ast.FunctionDef, difficulty: Difficulty) -> str | None:
    loops = [node for node in ast.walk(entry) if isinstance(node, ast.For)]
    if difficulty == "beginner":
        if len(loops) != 1 or _range_argument(loops[0]) != "n":
            return "loops/beginner requires exactly one `for ... in range(n)` loop"
        return None

    if len(loops) != 2:
        return f"loops/{difficulty} requires exactly two range loops"
    outer, second = loops
    if difficulty == "intermediate":
        top_level = [
            statement for statement in entry.body if isinstance(statement, ast.For)
        ]
        if (
            len(top_level) != 2
            or _range_argument(top_level[0]) != "n"
            or _range_argument(top_level[1]) != "m"
        ):
            return (
                "loops/intermediate requires sequential `range(n)` and `range(m)` loops"
            )
        return None

    nested = [statement for statement in outer.body if isinstance(statement, ast.For)]
    if (
        _range_argument(outer) != "n"
        or len(nested) != 1
        or nested[0] is not second
        or _range_argument(second) != "m"
    ):
        return "loops/advanced requires a `range(m)` loop nested in `range(n)`"
    return None


def _function_profile_error(
    functions: dict[str, ast.FunctionDef],
    entry: ast.FunctionDef,
    difficulty: Difficulty,
) -> str | None:
    helpers = {name: node for name, node in functions.items() if node is not entry}
    expected_helpers = 2 if difficulty == "advanced" else 1
    if len(helpers) != expected_helpers:
        return f"functions/{difficulty} requires exactly {expected_helpers} helper(s)"

    entry_calls = _direct_call_names(entry)
    if difficulty == "beginner":
        helper = next(iter(helpers))
        if entry_calls != [helper] or _direct_call_names(helpers[helper]):
            return "functions/beginner requires exactly one entry-to-helper call"
        return None

    helper_calls_in_loops = [
        node.func.id
        for loop in ast.walk(entry)
        if isinstance(loop, ast.For)
        for node in ast.walk(loop)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in helpers
    ]
    if entry_calls.count("range") != 1 or len(helper_calls_in_loops) != 1:
        return (
            f"functions/{difficulty} requires one range call and one helper call "
            "inside the loop"
        )

    middle_name = helper_calls_in_loops[0]
    if difficulty == "intermediate":
        if entry_calls != ["range", middle_name] or _direct_call_names(
            helpers[middle_name]
        ):
            return "functions/intermediate contains calls outside its required pattern"
        return None

    leaf_names = set(helpers) - {middle_name}
    leaf_name = next(iter(leaf_names))
    if (
        entry_calls != ["range", middle_name]
        or _direct_call_names(helpers[middle_name]) != [leaf_name, leaf_name]
        or _direct_call_names(helpers[leaf_name])
    ):
        return (
            "functions/advanced requires the middle helper to call the leaf exactly "
            "twice and no other calls"
        )
    return None


def _direct_call_names(function: ast.FunctionDef) -> list[str]:
    return [
        node.func.id
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]


def _range_argument(loop: ast.For) -> str | None:
    iterator = loop.iter
    if (
        isinstance(iterator, ast.Call)
        and isinstance(iterator.func, ast.Name)
        and iterator.func.id == "range"
        and len(iterator.args) == 1
        and not iterator.keywords
        and isinstance(iterator.args[0], ast.Name)
    ):
        return iterator.args[0].id
    return None


def _single_return_call_error(
    entry: ast.FunctionDef, function_name: str, parameter_name: str
) -> str | None:
    requirement = (
        "entry-function body must be exactly "
        f"`return {function_name}({parameter_name})`"
    )
    if len(entry.body) != 1 or not isinstance(entry.body[0], ast.Return):
        return requirement
    value = entry.body[0].value
    if not (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id == function_name
        and len(value.args) == 1
        and isinstance(value.args[0], ast.Name)
        and value.args[0].id == parameter_name
        and not value.keywords
    ):
        return requirement
    return None


def _reachable_function_names(
    functions: dict[str, ast.FunctionDef], entry_function: str
) -> set[str]:
    reachable: set[str] = set()
    pending = [entry_function]
    while pending:
        name = pending.pop()
        if name in reachable or name not in functions:
            continue
        reachable.add(name)
        called = {
            node.func.id
            for node in ast.walk(functions[name])
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        pending.extend(called - reachable)
    return reachable


def _has_ancestor(
    node: ast.AST, kind: type[ast.AST], parents: dict[ast.AST, ast.AST]
) -> bool:
    current = parents.get(node)
    while current is not None:
        if isinstance(current, kind):
            return True
        current = parents.get(current)
    return False


def _nearest_function(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str | None:
    current = parents.get(node)
    while current is not None:
        if isinstance(current, ast.FunctionDef):
            return current.name
        current = parents.get(current)
    return None


def _has_sequential_nodes(
    functions: list[ast.FunctionDef],
    kind: type[ast.If] | type[ast.For],
    parents: dict[ast.AST, ast.AST],
) -> bool:
    for function in functions:
        top_level = [
            node
            for node in ast.walk(function)
            if isinstance(node, kind)
            and _nearest_function(node, parents) == function.name
            and not _has_ancestor(node, kind, parents)
        ]
        if len(top_level) >= 2:
            return True
    return False
