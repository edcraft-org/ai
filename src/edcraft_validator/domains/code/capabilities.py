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
        "Use one boolean parameter in reachable conditional control flow. Keep the "
        "number of evaluated conditions small enough to trace by hand.",
        "integer",
    ),
    CodeTemplateProfile(
        "conditionals",
        "intermediate",
        "branch_executions",
        (_shape("string", names=("mode",)),),
        frozenset({"conditional", "early_return", "sequential_conditionals"}),
        "Use exactly one string parameter named mode. Include at least two reachable "
        "sequential conditionals and an early return. Choose distinct mode values "
        "that exercise different paths and numbers of evaluated conditions.",
        "integer",
    ),
    CodeTemplateProfile(
        "conditionals",
        "advanced",
        "branch_executions",
        (_shape("integer", "boolean", names=("score", "override")),),
        frozenset({"conditional", "early_return", "nested_conditional"}),
        "Use integer score and boolean override parameters in reachable control flow "
        "with both a nested conditional and an early return. Choose score values on "
        "different decision paths so the evaluated-condition count is instructive.",
        "integer",
    ),
    CodeTemplateProfile(
        "loops",
        "beginner",
        "loop_iterations",
        (_shape("integer", names=("n",)),),
        frozenset({"loop"}),
        "Use exactly one positive integer parameter named n to control reachable "
        "loop behavior. Keep every exhaustive case small enough to trace by hand.",
        "integer",
        require_positive_integers=True,
    ),
    CodeTemplateProfile(
        "loops",
        "intermediate",
        "loop_iterations",
        (_shape("integer", "integer", names=("n", "m")),),
        frozenset({"loop", "sequential_loops"}),
        "Use positive integer parameters n and m with at least two reachable "
        "sequential loops. Make both parameters affect the traced program and keep "
        "the total iteration count bounded across the finite domain.",
        "integer",
        require_positive_integers=True,
    ),
    CodeTemplateProfile(
        "loops",
        "advanced",
        "loop_iterations",
        (_shape("integer", "integer", names=("n", "m")),),
        frozenset({"loop", "nested_loop"}),
        "Use positive integer parameters n and m in reachable nested-loop behavior. "
        "Make both parameters affect the traced program and keep the total iteration "
        "count bounded across the finite domain.",
        "integer",
        require_positive_integers=True,
    ),
    CodeTemplateProfile(
        "functions",
        "beginner",
        "function_calls",
        (_shape("integer"),),
        frozenset({"helper_function"}),
        "Use one integer parameter and at least one reachable module-level helper "
        "call. Keep the call graph and total traced call count small enough to reason "
        "about directly.",
        "integer",
    ),
    CodeTemplateProfile(
        "functions",
        "intermediate",
        "function_calls",
        (_shape("integer", names=("n",)),),
        frozenset({"helper_function", "loop"}),
        "Use positive integer n in reachable loop behavior that also invokes a "
        "module-level helper. Keep the call count bounded while making its dependence "
        "on the loop behavior clear.",
        "integer",
        require_positive_integers=True,
    ),
    CodeTemplateProfile(
        "functions",
        "advanced",
        "function_calls",
        (_shape("integer", names=("n",)),),
        frozenset({"helper_function", "loop", "nested_helper"}),
        "Use positive integer n with reachable loop behavior and a multi-level "
        "module-level helper call graph in which one helper calls another. Keep the "
        "call count bounded and dependent on the loop behavior.",
        "integer",
        require_positive_integers=True,
    ),
    CodeTemplateProfile(
        "lists",
        "beginner",
        "return_value",
        (_shape("integer_list", names=("values",)),),
        frozenset({"list_aggregate"}),
        "Use exactly one integer_list parameter named values and at least one "
        "allowlisted aggregate operation such as sum, min, or max in the reachable "
        "computation. Return an integer.",
        "integer",
    ),
    CodeTemplateProfile(
        "lists",
        "intermediate",
        "return_value",
        (_shape("integer_list", names=("values",)),),
        frozenset({"list_sort"}),
        "Use exactly one integer_list parameter named values and call sorted in the "
        "reachable computation. Return an integer list whose result depends on that "
        "sorting operation.",
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


def answer_target_for_topic(topic: ProgrammingTopic) -> AnswerTarget:
    targets = {
        profile.answer_target
        for profile in CODE_TEMPLATE_PROFILES.values()
        if profile.topic == topic
    }
    if len(targets) != 1:
        raise RuntimeError(f"topic {topic!r} must have exactly one answer target")
    return targets.pop()


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
