"""Trusted handler context; final request validation is owned by the facade."""

from __future__ import annotations

from dataclasses import dataclass

import sympy

from edcraft_validator.domains.math.engine.contracts import (
    CorrectnessRequest,
    CorrectnessResult,
    EngineUnsupported,
    Outcome,
)
from edcraft_validator.domains.math.ir.compile import build_symbols, compile_expr
from edcraft_validator.domains.math.ir.schema import Expr


@dataclass(frozen=True)
class EngineContext:
    request: CorrectnessRequest
    symbols: dict[str, sympy.Symbol]

    @classmethod
    def create(cls, request: CorrectnessRequest) -> EngineContext:
        return cls(request, build_symbols(request.problem.symbols))

    def compile(self, expr: Expr) -> sympy.Expr:
        # Inspect children before parent constructors can erase undefined terms,
        # e.g. (1/0)**0 -> 1. Symbolic holes are tracked by domain handlers.
        for child in expr.args:
            self.compile(child)
        value = compile_expr(expr, self.symbols)
        if not value.free_symbols and (value.is_finite is False or value is sympy.nan):
            raise EngineUnsupported("expression has a non-finite subexpression")
        return value

    def result(
        self, outcome: Outcome, reason: str, method: str, **details: object
    ) -> CorrectnessResult:
        return CorrectnessResult(
            outcome=outcome,
            reason=reason,
            method=method,
            details=details,
            sympy_version=sympy.__version__,
        )
