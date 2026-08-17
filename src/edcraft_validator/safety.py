import ast
from dataclasses import dataclass, field


@dataclass
class SafetyResult:
    errors: list[str] = field(default_factory=list)

    @property
    def is_safe(self) -> bool:
        return not self.errors


class SafetyChecker(ast.NodeVisitor):
    """Conservative syntax gate, not a complete security sandbox."""

    _blocked_nodes = (
        ast.AsyncFor,
        ast.AsyncFunctionDef,
        ast.AsyncWith,
        ast.Attribute,
        ast.Await,
        ast.ClassDef,
        ast.Delete,
        ast.DictComp,
        ast.GeneratorExp,
        ast.Global,
        ast.Import,
        ast.ImportFrom,
        ast.Lambda,
        ast.ListComp,
        ast.Nonlocal,
        ast.Raise,
        ast.SetComp,
        ast.Try,
        ast.While,
        ast.With,
        ast.Yield,
        ast.YieldFrom,
    )
    _safe_builtins = {
        "abs",
        "all",
        "any",
        "bool",
        "enumerate",
        "float",
        "int",
        "len",
        "list",
        "max",
        "min",
        "range",
        "reversed",
        "round",
        "sorted",
        "str",
        "sum",
        "tuple",
        "zip",
    }
    _blocked_names = {
        "breakpoint",
        "compile",
        "eval",
        "exec",
        "getattr",
        "globals",
        "help",
        "input",
        "locals",
        "memoryview",
        "open",
        "setattr",
        "type",
        "vars",
        "__import__",
    }

    def __init__(self, entry_function: str) -> None:
        self.entry_function = entry_function
        self.errors: list[str] = []
        self._defined_functions: set[str] = set()
        self._current_function: str | None = None

    def check(self, code: str) -> SafetyResult:
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            return SafetyResult([f"Syntax error at line {exc.lineno}: {exc.msg}"])

        self._defined_functions = {
            node.name for node in tree.body if isinstance(node, ast.FunctionDef)
        }
        if self.entry_function not in self._defined_functions:
            self.errors.append(
                f"Entry function '{self.entry_function}' is not defined at module level"
            )

        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.Assign, ast.AnnAssign)):
                self.errors.append(
                    f"Top-level {type(node).__name__} is not allowed "
                    f"(line {node.lineno})"
                )

        self.visit(tree)
        return SafetyResult(self.errors)

    def generic_visit(self, node: ast.AST) -> None:
        if isinstance(node, self._blocked_nodes):
            self.errors.append(
                f"{type(node).__name__} is not supported (line {node.lineno})"
            )
            return
        super().generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node.decorator_list:
            self.errors.append(f"Decorators are not allowed (line {node.lineno})")
        previous = self._current_function
        self._current_function = node.name
        self.generic_visit(node)
        self._current_function = previous

    def visit_Name(self, node: ast.Name) -> None:
        if node.id.startswith("__") or node.id in self._blocked_names:
            self.errors.append(f"Name '{node.id}' is not allowed (line {node.lineno})")

    def visit_Call(self, node: ast.Call) -> None:
        if not isinstance(node.func, ast.Name):
            self.errors.append(
                f"Only direct function calls are allowed (line {node.lineno})"
            )
        else:
            called = node.func.id
            allowed = self._safe_builtins | self._defined_functions
            if called not in allowed:
                self.errors.append(
                    f"Call to '{called}' is not allowed (line {node.lineno})"
                )
            if called == self._current_function:
                self.errors.append(f"Recursion is not allowed (line {node.lineno})")
        self.generic_visit(node)


def check_code_safety(code: str, entry_function: str) -> SafetyResult:
    return SafetyChecker(entry_function).check(code)
