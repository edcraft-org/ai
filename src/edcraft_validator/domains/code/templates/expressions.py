"""Restricted expression language used by code-question templates."""

from __future__ import annotations

import ast
import math
import operator
from typing import Any

from .models import (
    MAX_LIST_LENGTH,
    MAX_STRING_LENGTH,
    ParameterValue,
    TemplateValidationError,
)

MAX_EXPRESSION_LENGTH = 500
MAX_EXPRESSION_NODES = 100
MAX_EXPRESSION_INTEGER_ABS = 1_000_000_000
MAX_EXPRESSION_FLOAT_ABS = 1_000_000_000.0
MAX_EXPRESSION_SEQUENCE_LENGTH = 100
MAX_EXPRESSION_VALUE_SIZE = 1_000
MAX_EXPRESSION_VALUE_DEPTH = 20


class SafeExpression:
    """Evaluate the small arithmetic expression language used by templates."""

    _binary_operators = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
    }
    _unary_operators = {
        ast.UAdd: operator.pos,
        ast.USub: operator.neg,
        ast.Not: operator.not_,
    }
    _comparison_operators = {
        ast.Eq: operator.eq,
        ast.NotEq: operator.ne,
        ast.Lt: operator.lt,
        ast.LtE: operator.le,
        ast.Gt: operator.gt,
        ast.GtE: operator.ge,
        ast.In: lambda item, container: operator.contains(container, item),
        ast.NotIn: lambda item, container: not operator.contains(container, item),
    }
    _safe_functions = {
        "all": all,
        "any": any,
        "len": len,
        "max": max,
        "min": min,
        "sorted": sorted,
        "sum": sum,
    }

    def __init__(self, source: str, names: tuple[str, ...]) -> None:
        self.source = source
        self.names = frozenset(names)
        if len(source) > MAX_EXPRESSION_LENGTH:
            raise TemplateValidationError(
                f"template expression exceeds {MAX_EXPRESSION_LENGTH} characters"
            )
        try:
            self.expression = ast.parse(source, mode="eval").body
        except SyntaxError as exc:
            raise TemplateValidationError(
                f"invalid template expression {source!r}: {exc.msg}"
            ) from exc
        if sum(1 for _ in ast.walk(self.expression)) > MAX_EXPRESSION_NODES:
            raise TemplateValidationError(
                f"template expression exceeds {MAX_EXPRESSION_NODES} syntax nodes"
            )
        self._validate(self.expression, depth=0)

    def evaluate(self, values: dict[str, ParameterValue]) -> Any:
        try:
            return self._bounded(self._evaluate(self.expression, values))
        except (
            ArithmeticError,
            IndexError,
            OverflowError,
            TypeError,
            ValueError,
        ) as exc:
            raise TemplateValidationError(
                f"expression {self.source!r} failed for {values}: {exc}"
            ) from exc

    def _validate(self, node: ast.AST, *, depth: int) -> None:
        if depth > 20:
            raise TemplateValidationError("template expression is too deeply nested")
        if isinstance(node, ast.Constant):
            if type(node.value) not in {int, float, bool, str}:
                raise TemplateValidationError(
                    "template expressions support only JSON scalar constants"
                )
            if isinstance(node.value, (int, float)) and abs(node.value) > 10_000:
                raise TemplateValidationError("expression constant is too large")
            if isinstance(node.value, str) and (
                len(node.value) > MAX_STRING_LENGTH or not node.value.isprintable()
            ):
                raise TemplateValidationError("expression string constant is invalid")
            return
        if isinstance(node, ast.Name):
            if node.id not in self.names:
                raise TemplateValidationError(
                    f"expression uses unknown parameter {node.id!r}"
                )
            return
        if isinstance(node, ast.BinOp) and type(node.op) in self._binary_operators:
            self._validate(node.left, depth=depth + 1)
            self._validate(node.right, depth=depth + 1)
            return
        if isinstance(node, ast.UnaryOp) and type(node.op) in self._unary_operators:
            self._validate(node.operand, depth=depth + 1)
            return
        if isinstance(node, ast.IfExp):
            self._validate(node.test, depth=depth + 1)
            self._validate(node.body, depth=depth + 1)
            self._validate(node.orelse, depth=depth + 1)
            return
        if isinstance(node, ast.Compare) and all(
            type(item) in self._comparison_operators for item in node.ops
        ):
            self._validate(node.left, depth=depth + 1)
            for comparator in node.comparators:
                self._validate(comparator, depth=depth + 1)
            return
        if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            for value in node.values:
                self._validate(value, depth=depth + 1)
            return
        if isinstance(node, ast.List):
            if len(node.elts) > MAX_LIST_LENGTH:
                raise TemplateValidationError("expression list is too long")
            for element in node.elts:
                self._validate(element, depth=depth + 1)
            return
        if isinstance(node, ast.Subscript) and not isinstance(node.slice, ast.Slice):
            self._validate(node.value, depth=depth + 1)
            self._validate(node.slice, depth=depth + 1)
            return
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in self._safe_functions
            and len(node.args) == 1
            and not node.keywords
        ):
            self._validate(node.args[0], depth=depth + 1)
            return
        raise TemplateValidationError(
            f"unsupported expression syntax: {type(node).__name__}"
        )

    def _evaluate(self, node: ast.AST, values: dict[str, ParameterValue]) -> Any:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return values[node.id]
        if isinstance(node, ast.BinOp):
            left = self._bounded(self._evaluate(node.left, values))
            right = self._bounded(self._evaluate(node.right, values))
            if isinstance(node.op, ast.Pow) and (
                type(right) is not int or not 0 <= right <= 8
            ):
                raise TemplateValidationError("exponents must be integers from 0 to 8")
            if isinstance(node.op, ast.Mod) and isinstance(left, str):
                raise TemplateValidationError(
                    "string formatting is not supported in template expressions"
                )
            if isinstance(node.op, ast.Mult):
                self._check_sequence_repetition(left, right)
            return self._bounded(self._binary_operators[type(node.op)](left, right))
        if isinstance(node, ast.UnaryOp):
            return self._bounded(
                self._unary_operators[type(node.op)](
                    self._bounded(self._evaluate(node.operand, values))
                )
            )
        if isinstance(node, ast.IfExp):
            test = self._bounded(self._evaluate(node.test, values))
            branch = node.body if test else node.orelse
            return self._evaluate(branch, values)
        if isinstance(node, ast.Compare):
            left = self._bounded(self._evaluate(node.left, values))
            for operation, comparator in zip(node.ops, node.comparators, strict=True):
                right = self._bounded(self._evaluate(comparator, values))
                if not self._comparison_operators[type(operation)](left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.BoolOp):
            result = self._bounded(self._evaluate(node.values[0], values))
            for value in node.values[1:]:
                if isinstance(node.op, ast.And) and not result:
                    return result
                if isinstance(node.op, ast.Or) and result:
                    return result
                result = self._bounded(self._evaluate(value, values))
            return result
        if isinstance(node, ast.List):
            return self._bounded(
                [
                    self._bounded(self._evaluate(element, values))
                    for element in node.elts
                ]
            )
        if isinstance(node, ast.Subscript):
            value = self._bounded(self._evaluate(node.value, values))
            index = self._bounded(self._evaluate(node.slice, values))
            return value[index]
        if isinstance(node, ast.Call):
            argument = self._bounded(self._evaluate(node.args[0], values))
            return self._bounded(self._safe_functions[node.func.id](argument))
        raise AssertionError(f"unvalidated expression node: {type(node).__name__}")

    @classmethod
    def _check_sequence_repetition(cls, left: Any, right: Any) -> None:
        sequence: str | list[Any] | None = None
        count: int | None = None
        if isinstance(left, (str, list)) and type(right) is int:
            sequence, count = left, right
        elif type(left) is int and isinstance(right, (str, list)):
            sequence, count = right, left
        if sequence is None or count is None:
            return
        repetitions = max(count, 0)
        resulting_length = len(sequence) * repetitions
        if resulting_length > MAX_EXPRESSION_SEQUENCE_LENGTH:
            raise TemplateValidationError(
                "expression sequence result exceeds "
                f"{MAX_EXPRESSION_SEQUENCE_LENGTH} items"
            )
        if isinstance(sequence, list):
            payload_size = cls._bounded_value_size(sequence) - 1
            if 1 + payload_size * repetitions > MAX_EXPRESSION_VALUE_SIZE:
                raise TemplateValidationError(
                    "expression value exceeds cumulative size limit of "
                    f"{MAX_EXPRESSION_VALUE_SIZE}"
                )

    @classmethod
    def _bounded(cls, value: Any) -> Any:
        cls._bounded_value_size(value)
        return value

    @classmethod
    def _bounded_value_size(
        cls,
        value: Any,
        *,
        depth: int = 0,
        remaining_size: int = MAX_EXPRESSION_VALUE_SIZE,
    ) -> int:
        if depth > MAX_EXPRESSION_VALUE_DEPTH:
            raise TemplateValidationError(
                f"expression value exceeds nesting depth {MAX_EXPRESSION_VALUE_DEPTH}"
            )
        if type(value) is bool:
            size = 1
        elif type(value) is int:
            if abs(value) > MAX_EXPRESSION_INTEGER_ABS:
                raise TemplateValidationError(
                    f"expression integer result exceeds {MAX_EXPRESSION_INTEGER_ABS}"
                )
            size = 1
        elif type(value) is float:
            if not math.isfinite(value) or abs(value) > MAX_EXPRESSION_FLOAT_ABS:
                raise TemplateValidationError(
                    "expression float result is non-finite or exceeds "
                    f"{MAX_EXPRESSION_FLOAT_ABS:g}"
                )
            size = 1
        elif isinstance(value, str):
            if len(value) > MAX_EXPRESSION_SEQUENCE_LENGTH:
                raise TemplateValidationError(
                    "expression sequence result exceeds "
                    f"{MAX_EXPRESSION_SEQUENCE_LENGTH} items"
                )
            size = 1 + len(value)
        elif isinstance(value, list):
            if len(value) > MAX_EXPRESSION_SEQUENCE_LENGTH:
                raise TemplateValidationError(
                    "expression sequence result exceeds "
                    f"{MAX_EXPRESSION_SEQUENCE_LENGTH} items"
                )
            size = 1
            cls._ensure_value_size(size, remaining_size)
            for item in value:
                size += cls._bounded_value_size(
                    item,
                    depth=depth + 1,
                    remaining_size=remaining_size - size,
                )
        else:
            raise TemplateValidationError(
                f"expression produced unsupported value type {type(value).__name__}"
            )
        cls._ensure_value_size(size, remaining_size)
        return size

    @staticmethod
    def _ensure_value_size(size: int, limit: int) -> None:
        if size > limit:
            raise TemplateValidationError(
                "expression value exceeds cumulative size limit of "
                f"{MAX_EXPRESSION_VALUE_SIZE}"
            )
