"""Recognize the Python syntax features referenced by code profiles."""

from __future__ import annotations

import ast

from edcraft_validator.domains.code.code_types import CodeFeature


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
