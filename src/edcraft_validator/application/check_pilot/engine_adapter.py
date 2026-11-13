"""Closed conversion from pilot kernel payloads to deterministic-engine requests.

The pilot kernel contracts generate bounded problems, expected answers and
distractors.  This adapter turns those already-validated payloads into the
engine's closed ``CorrectnessRequest`` IR.  It performs no mathematics and never
falls back to the kernel verdict.

A genuine IR gap raises :class:`EngineAdapterGap`, naming the engine contract and
the exact payload field, so a refusal is reported instead of silently accepting
a malformed request.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any

from edcraft_validator.application.check_pilot.engine_registry import (
    EngineContractSpec,
    engine_contract,
)
from edcraft_validator.application.check_pilot.errors import PilotInputError
from edcraft_validator.domains.math.engine.contracts import (
    CorrectnessRequest,
    MathAnswer,
    MathProblem,
)
from edcraft_validator.domains.math.ir.schema import Expr, Relation, SymbolSpec


class EngineAdapterGap(PilotInputError):
    """A kernel payload has no faithful deterministic-engine representation."""

    def __init__(self, contract_id: str, field: str, detail: str) -> None:
        self.contract_id = contract_id
        self.field = field
        self.detail = detail
        super().__init__(f"engine contract {contract_id!r}: field {field!r} {detail}")


def _gap(contract_id: str, field: str, detail: str) -> EngineAdapterGap:
    return EngineAdapterGap(contract_id, field, detail)


def _object(value: object, contract_id: str, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _gap(contract_id, field, "must be an object")
    return value


def _list(value: object, contract_id: str, field: str) -> list[Any]:
    if not isinstance(value, list) or not value:
        raise _gap(contract_id, field, "must be a non-empty list")
    return value


def _text(value: object, contract_id: str, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise _gap(contract_id, field, "must be a non-empty exact numeric string")
    return value


def _fraction(value: object, contract_id: str, field: str) -> Fraction:
    text = _text(value, contract_id, field)
    try:
        number = Fraction(text)
    except (ValueError, ZeroDivisionError):
        raise _gap(contract_id, field, "is not a finite exact rational") from None
    return number


def _number(value: object, contract_id: str, field: str) -> Expr:
    return Expr(num=str(_fraction(value, contract_id, field)))


def _integer(value: object, contract_id: str, field: str) -> int:
    if type(value) is not int:
        raise _gap(contract_id, field, "must be an exact integer")
    return value


def _expression(value: object, contract_id: str, field: str) -> Expr:
    raw = _object(value, contract_id, field)
    try:
        return Expr.model_validate(raw)
    except ValueError as exc:
        raise _gap(
            contract_id,
            field,
            f"is not a valid math IR expression: {str(exc)[:200]}",
        ) from None


def _matrix(value: object, contract_id: str, field: str) -> list[list[Expr]]:
    rows = _list(value, contract_id, field)
    parsed: list[list[Expr]] = []
    width: int | None = None
    for row_index, row in enumerate(rows):
        row_values = _list(row, contract_id, f"{field}[{row_index}]")
        if width is None:
            width = len(row_values)
        elif len(row_values) != width:
            raise _gap(contract_id, field, "must be rectangular")
        parsed.append(
            [
                _number(entry, contract_id, f"{field}[{row_index}][{column}]")
                for column, entry in enumerate(row_values)
            ]
        )
    return parsed


def _polynomial(
    coefficients: object, contract_id: str, field: str, variable: str
) -> Expr:
    values = _list(coefficients, contract_id, field)
    terms: list[Expr] = []
    for exponent, coefficient in enumerate(values):
        number = _fraction(coefficient, contract_id, f"{field}[{exponent}]")
        if number == 0:
            continue
        factor = Expr(num=str(number))
        if exponent == 0:
            terms.append(factor)
        elif exponent == 1:
            terms.append(Expr(op="mul", args=[factor, Expr(sym=variable)]))
        else:
            terms.append(
                Expr(
                    op="mul",
                    args=[
                        factor,
                        Expr(
                            op="pow",
                            args=[Expr(sym=variable), Expr(num=str(exponent))],
                        ),
                    ],
                )
            )
    if not terms:
        return Expr(num="0")
    if len(terms) == 1:
        return terms[0]
    return Expr(op="add", args=terms)


def _linear_row(row: list[Any], contract_id: str, field: str) -> Expr:
    terms: list[Expr] = []
    for index, coefficient in enumerate(row):
        name = ("x", "y")[index]
        value = _integer(coefficient, contract_id, f"{field}[{index}]")
        if value == 0:
            continue
        terms.append(Expr(op="mul", args=[Expr(num=str(value)), Expr(sym=name)]))
    if not terms:
        return Expr(num="0")
    if len(terms) == 1:
        return terms[0]
    return Expr(op="add", args=terms)


def _scalar_problem(
    contract_id: str,
    *,
    operation: str,
    expression: Expr,
    variable: str,
    lower: Expr | None = None,
    upper: Expr | None = None,
) -> MathProblem:
    return MathProblem(
        operation=operation,  # type: ignore[arg-type]
        symbols=[SymbolSpec(name=variable)],
        expression=expression,
        variable=variable,
        lower=lower,
        upper=upper,
    )


def _antiderivative(
    spec: EngineContractSpec, problem: dict[str, Any], candidate: dict[str, Any]
) -> CorrectnessRequest:
    contract_id = spec.contract_id
    variable = _text(problem.get("variable", "x"), contract_id, "problem.variable")
    source = _polynomial(
        problem.get("coefficients"), contract_id, "problem.coefficients", variable
    )
    answer = _polynomial(
        candidate.get("coefficients"), contract_id, "candidate.coefficients", variable
    )
    for field, value in (
        ("problem.general", problem.get("general")),
        ("candidate.general", candidate.get("general")),
    ):
        if type(value) is not bool:
            raise _gap(contract_id, field, "must be a boolean")
    return CorrectnessRequest(
        problem=_scalar_problem(
            contract_id,
            operation="antiderivative",
            expression=source,
            variable=variable,
        ),
        answer=MathAnswer(kind="expression", expression=answer),
    )


def _definite_integral(
    spec: EngineContractSpec, problem: dict[str, Any], candidate: dict[str, Any]
) -> CorrectnessRequest:
    contract_id = spec.contract_id
    variable = _text(problem.get("variable", "x"), contract_id, "problem.variable")
    source = _polynomial(
        problem.get("coefficients"), contract_id, "problem.coefficients", variable
    )
    lower = _number(problem.get("lower"), contract_id, "problem.lower")
    upper = _number(problem.get("upper"), contract_id, "problem.upper")
    answer = _number(candidate.get("value"), contract_id, "candidate.value")
    return CorrectnessRequest(
        problem=_scalar_problem(
            contract_id,
            operation="definite-integral",
            expression=source,
            variable=variable,
            lower=lower,
            upper=upper,
        ),
        answer=MathAnswer(kind="expression", expression=answer),
    )


def _differentiate(
    spec: EngineContractSpec, problem: dict[str, Any], candidate: dict[str, Any]
) -> CorrectnessRequest:
    contract_id = spec.contract_id
    variable = _text(problem.get("variable", "x"), contract_id, "problem.variable")
    source = _expression(problem.get("expression"), contract_id, "problem.expression")
    answer = _expression(
        candidate.get("expression"), contract_id, "candidate.expression"
    )
    raw_symbols = _list(problem.get("symbols"), contract_id, "problem.symbols")
    symbols: list[SymbolSpec] = []
    for index, raw in enumerate(raw_symbols):
        item = _object(raw, contract_id, f"problem.symbols[{index}]")
        name = _text(item.get("name"), contract_id, f"problem.symbols[{index}].name")
        positive = item.get("positive", False)
        nonzero = item.get("nonzero", False)
        if type(positive) is not bool or type(nonzero) is not bool:
            raise _gap(
                contract_id,
                f"problem.symbols[{index}]",
                "positive and nonzero must be booleans",
            )
        symbols.append(SymbolSpec(name=name, positive=positive, nonzero=nonzero))
    if variable not in {symbol.name for symbol in symbols}:
        raise _gap(contract_id, "problem.variable", "is not a declared symbol")
    return CorrectnessRequest(
        problem=MathProblem(
            operation="differentiate",
            symbols=symbols,
            expression=source,
            variable=variable,
        ),
        answer=MathAnswer(kind="expression", expression=answer),
    )


def _equivalence(
    spec: EngineContractSpec, problem: dict[str, Any], candidate: dict[str, Any]
) -> CorrectnessRequest:
    contract_id = spec.contract_id
    source = _expression(problem.get("expression"), contract_id, "problem.expression")
    answer = _expression(
        candidate.get("expression"), contract_id, "candidate.expression"
    )
    return CorrectnessRequest(
        problem=MathProblem(
            operation=spec.operation,
            symbols=[SymbolSpec(name="x")],
            expression=source,
            variable="x",
        ),
        answer=MathAnswer(kind="expression", expression=answer),
    )


def _solve(
    spec: EngineContractSpec, problem: dict[str, Any], candidate: dict[str, Any]
) -> CorrectnessRequest:
    contract_id = spec.contract_id
    matrix = _list(problem.get("matrix"), contract_id, "problem.matrix")
    if len(matrix) != 2:
        raise _gap(contract_id, "problem.matrix", "must have exactly two rows")
    rhs = _list(problem.get("rhs"), contract_id, "problem.rhs")
    if len(rhs) != 2:
        raise _gap(contract_id, "problem.rhs", "must have exactly two entries")
    relations: list[Relation] = []
    for index, row in enumerate(matrix):
        values = _list(row, contract_id, f"problem.matrix[{index}]")
        if len(values) != 2:
            raise _gap(contract_id, f"problem.matrix[{index}]", "must have two entries")
        relations.append(
            Relation(
                kind="eq",
                lhs=_linear_row(values, contract_id, f"problem.matrix[{index}]"),
                rhs=Expr(
                    num=str(_integer(rhs[index], contract_id, f"problem.rhs[{index}]"))
                ),
            )
        )
    raw_values = _list(candidate.get("values"), contract_id, "candidate.values")
    if len(raw_values) != 2:
        raise _gap(contract_id, "candidate.values", "must have exactly two entries")
    items = [
        _number(value, contract_id, f"candidate.values[{index}]")
        for index, value in enumerate(raw_values)
    ]
    return CorrectnessRequest(
        problem=MathProblem(
            operation="solve",
            symbols=[SymbolSpec(name="x"), SymbolSpec(name="y")],
            relations=relations,
            solve_for=["x", "y"],
            domain="real",
        ),
        answer=MathAnswer(kind="tuple", items=items),
    )


def _matrix_multiply(
    spec: EngineContractSpec, problem: dict[str, Any], candidate: dict[str, Any]
) -> CorrectnessRequest:
    contract_id = spec.contract_id
    left = _matrix(problem.get("left"), contract_id, "problem.left")
    right = _matrix(problem.get("right"), contract_id, "problem.right")
    answer = _matrix(candidate.get("matrix"), contract_id, "candidate.matrix")
    return CorrectnessRequest(
        problem=MathProblem(
            operation="matrix-multiply", matrix=left, right_matrix=right
        ),
        answer=MathAnswer(kind="matrix", matrix=answer),
    )


def _determinant(
    spec: EngineContractSpec, problem: dict[str, Any], candidate: dict[str, Any]
) -> CorrectnessRequest:
    contract_id = spec.contract_id
    matrix = _matrix(problem.get("matrix"), contract_id, "problem.matrix")
    answer = _number(candidate.get("value"), contract_id, "candidate.value")
    return CorrectnessRequest(
        problem=MathProblem(operation="determinant", matrix=matrix),
        answer=MathAnswer(kind="expression", expression=answer),
    )


def _inverse(
    spec: EngineContractSpec, problem: dict[str, Any], candidate: dict[str, Any]
) -> CorrectnessRequest:
    contract_id = spec.contract_id
    matrix = _matrix(problem.get("matrix"), contract_id, "problem.matrix")
    answer = _matrix(candidate.get("matrix"), contract_id, "candidate.matrix")
    return CorrectnessRequest(
        problem=MathProblem(operation="inverse", matrix=matrix),
        answer=MathAnswer(kind="matrix", matrix=answer),
    )


def _lu(
    spec: EngineContractSpec, problem: dict[str, Any], candidate: dict[str, Any]
) -> CorrectnessRequest:
    contract_id = spec.contract_id
    matrix = _matrix(problem.get("matrix"), contract_id, "problem.matrix")
    permutation = _matrix(
        candidate.get("permutation"), contract_id, "candidate.permutation"
    )
    lower = _matrix(candidate.get("lower"), contract_id, "candidate.lower")
    upper = _matrix(candidate.get("upper"), contract_id, "candidate.upper")
    return CorrectnessRequest(
        problem=MathProblem(operation="lu", matrix=matrix),
        answer=MathAnswer(
            kind="lu",
            permutation=permutation,
            lower=lower,
            upper=upper,
        ),
    )


_BUILDERS = {
    "polynomial.antiderivative/1": _antiderivative,
    "polynomial.definite-integral/1": _definite_integral,
    "expression.differentiate/1": _differentiate,
    "polynomial.expand/1": _equivalence,
    "polynomial.factor/1": _equivalence,
    "polynomial.complete-square/1": _equivalence,
    "linear-system.unique/1": _solve,
    "matrix.multiply/1": _matrix_multiply,
    "matrix.determinant/1": _determinant,
    "matrix.inverse/1": _inverse,
    "matrix.lu/1": _lu,
}


def _spec(contract_id: object) -> EngineContractSpec:
    spec = engine_contract(contract_id)
    if spec is None:
        raise EngineAdapterGap(
            str(contract_id), "contract_id", "is not a trusted engine contract"
        )
    return spec


def to_correctness_request(
    contract_id: str,
    problem: dict[str, Any],
    candidate: dict[str, Any],
) -> CorrectnessRequest:
    """Convert one kernel-shaped problem/candidate pair into an engine request."""
    spec = _spec(contract_id)
    builder = _BUILDERS.get(spec.generator_contract_id)
    if builder is None:
        raise _gap(
            spec.contract_id,
            "generator_contract_id",
            "has no engine request mapping",
        )
    return builder(
        spec,
        _object(problem, spec.contract_id, "problem"),
        _object(candidate, spec.contract_id, "candidate"),
    )


def form_findings(
    contract_id: str,
    problem: dict[str, Any],
    candidate: dict[str, Any],
) -> list[str]:
    """Adapter-level gates for kernel answer-form rules the engine IR cannot state.

    The engine's antiderivative checker accepts any primitive and does not model
    the kernel's explicit ``general``/one-primitive marker.  The adapter keeps
    that form requirement by rejecting a mismatched marker before grading; the
    engine remains authoritative for the mathematics.
    """
    spec = _spec(contract_id)
    if spec.generator_contract_id != "polynomial.antiderivative/1":
        return []
    if not isinstance(problem, dict) or not isinstance(candidate, dict):
        return ["antiderivative problem and candidate must be objects"]
    requested = problem.get("general")
    supplied = candidate.get("general")
    if type(requested) is not bool or type(supplied) is not bool:
        return ["antiderivative general marker must be a boolean"]
    if requested != supplied:
        return [
            "antiderivative answer form does not match the requested "
            "general/one-primitive form"
        ]
    return []


__all__ = [
    "EngineAdapterGap",
    "form_findings",
    "to_correctness_request",
]
