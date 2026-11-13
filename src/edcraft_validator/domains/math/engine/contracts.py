"""Closed inputs and honest outcomes for deterministic mathematics checking."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from edcraft_validator.domains.math.ir.schema import Expr, Relation, SymbolSpec

Operation = Literal[
    "evaluate",
    "simplify",
    "expand",
    "factor",
    "complete-square",
    "differentiate",
    "antiderivative",
    "definite-integral",
    "solve",
    "matrix-multiply",
    "determinant",
    "inverse",
    "lu",
]
Outcome = Literal["correct", "incorrect", "unknown", "unsupported", "timeout", "error"]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class MathProblem(Record):
    operation: Operation
    symbols: list[SymbolSpec] = Field(default_factory=list, max_length=8)
    expression: Expr | None = None
    variable: str | None = None
    order: int = Field(default=1, ge=1, le=8)
    relations: list[Relation] = Field(default_factory=list, max_length=16)
    solve_for: list[str] = Field(default_factory=list, max_length=8)
    domain: Literal["real", "integer", "rational"] = "real"
    matrix: list[list[Expr]] | None = None
    right_matrix: list[list[Expr]] | None = None
    lower: Expr | None = None
    upper: Expr | None = None

    @model_validator(mode="after")
    def validate_problem(self) -> MathProblem:
        names = [s.name for s in self.symbols]
        if len(names) != len(set(names)):
            raise ValueError("symbol names must be unique")
        if self.variable is not None and self.variable not in names:
            raise ValueError("variable must be a declared symbol")
        if len(self.solve_for) != len(set(self.solve_for)) or any(
            n not in names for n in self.solve_for
        ):
            raise ValueError("solve_for must contain unique declared symbols")
        if self.operation == "solve":
            if not self.relations or not self.solve_for:
                raise ValueError("solve requires relations and solve_for")
        elif self.operation in {"matrix-multiply", "determinant", "inverse", "lu"}:
            if self.matrix is None:
                raise ValueError("matrix operation requires matrix")
            if self.operation == "matrix-multiply" and self.right_matrix is None:
                raise ValueError("matrix multiplication requires right_matrix")
        elif self.expression is None:
            raise ValueError("expression operation requires expression")
        if (
            self.operation in {"differentiate", "antiderivative", "definite-integral"}
            and self.variable is None
        ):
            raise ValueError("calculus operation requires variable")
        if self.operation == "definite-integral" and (
            self.lower is None or self.upper is None
        ):
            raise ValueError("definite integral requires lower and upper endpoints")
        return self


class AnswerInterval(Record):
    lower: Expr | None = None
    upper: Expr | None = None
    lower_open: bool = True
    upper_open: bool = True


class MathAnswer(Record):
    kind: Literal["expression", "set", "tuple", "matrix", "lu"] = "expression"
    expression: Expr | None = None
    items: list[Expr] = Field(default_factory=list, max_length=64)
    intervals: list[AnswerInterval] = Field(default_factory=list, max_length=32)
    matrix: list[list[Expr]] | None = None
    permutation: list[list[Expr]] | None = None
    lower: list[list[Expr]] | None = None
    upper: list[list[Expr]] | None = None

    @model_validator(mode="after")
    def validate_answer(self) -> MathAnswer:
        fields = {
            name
            for name in (
                "expression",
                "items",
                "intervals",
                "matrix",
                "permutation",
                "lower",
                "upper",
            )
            if (value := getattr(self, name)) is not None and value != []
        }
        permitted = {
            "expression": {"expression"},
            "set": {"items", "intervals"},
            "tuple": {"items"},
            "matrix": {"matrix"},
            "lu": {"permutation", "lower", "upper"},
        }[self.kind]
        if fields - permitted:
            raise ValueError("answer contains fields for another answer kind")
        if self.kind == "expression" and self.expression is None:
            raise ValueError("expression answer requires expression")
        if self.kind == "matrix" and self.matrix is None:
            raise ValueError("matrix answer requires matrix")
        if self.kind == "lu" and any(
            v is None for v in (self.permutation, self.lower, self.upper)
        ):
            raise ValueError("LU answer requires permutation, lower and upper matrices")
        return self


class CorrectnessRequest(Record):
    problem: MathProblem
    answer: MathAnswer


class CorrectnessResult(Record):
    outcome: Outcome
    reason: str
    method: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    duration_ms: float = Field(default=0, ge=0)
    engine_version: str = "math-correctness/1"
    sympy_version: str = ""


class EngineUnsupported(ValueError):
    """A well-formed request is outside supported mathematics or resource scope."""


class EngineUnknown(ValueError):
    """The requested mathematical conclusion could not be determined."""
