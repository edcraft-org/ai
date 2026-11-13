"""Trusted exact matrix check kernel for the reusable-check pilot.

Four developer-authored contracts share one bounded rational-matrix surface:

* ``matrix.multiply/1``
* ``matrix.determinant/1``
* ``matrix.inverse/1``
* ``matrix.lu/1``

All inputs are closed 1..3 dimensional exact rational matrices. Determinant,
inverse and LU require a 2x2 or 3x3 square matrix. No model-authored code is
executed and no SymPy algorithmic result is trusted. The expected-answer
oracle uses explicit Laplace/determinant and adjugate arithmetic, while the
checker independently verifies products, Bareiss determinants, and the exact
``P * A = L * U`` LU convention with structural checks.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any, Literal

from hypothesis import strategies as st
from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationError,
    field_validator,
    model_validator,
)

MAX_ROWS = 3
MAX_COLUMNS = 3
MIN_SQUARE_SIZE = 2
MAX_SQUARE_SIZE = 3
MAX_ENTRY_ABS = 1_000
MAX_ENTRY_DENOMINATOR = 100
MAX_ANSWER_ABS = 10**40
MAX_ANSWER_DENOMINATOR = 10**40
MAX_RATIONAL_TEXT = 200

MULTIPLY_CONTRACT = "matrix.multiply/1"
DETERMINANT_CONTRACT = "matrix.determinant/1"
INVERSE_CONTRACT = "matrix.inverse/1"
LU_CONTRACT = "matrix.lu/1"

CONTRACT_SPECS: list[dict[str, str]] = [
    {
        "contract_id": MULTIPLY_CONTRACT,
        "title": "Multiply bounded exact rational matrices",
        "summary": (
            "Multiply matrices with at most 3 rows and columns and exactly "
            "matching inner dimensions using exact rational arithmetic."
        ),
        "kind": "matrix_multiply",
    },
    {
        "contract_id": DETERMINANT_CONTRACT,
        "title": "Determinant of a bounded exact 2x2 or 3x3 matrix",
        "summary": (
            "Evaluate a 2x2 or 3x3 exact rational determinant, including zero "
            "determinants, with an independent exact checker."
        ),
        "kind": "matrix_determinant",
    },
    {
        "contract_id": INVERSE_CONTRACT,
        "title": "Inverse of a bounded nonsingular exact matrix",
        "summary": (
            "Find the exact inverse of a nonsingular 2x2 or 3x3 rational "
            "matrix. Singular problems and singular candidate inverses fail."
        ),
        "kind": "matrix_inverse",
    },
    {
        "contract_id": LU_CONTRACT,
        "title": "LU factorisation of a bounded exact matrix",
        "summary": (
            "Return P, L and U for the fixed convention P*A = L*U with P a "
            "permutation, L unit lower triangular and U upper triangular; "
            "product-only answers are rejected."
        ),
        "kind": "matrix_lu",
    },
]
_SPEC_INDEX = {spec["contract_id"]: spec for spec in CONTRACT_SPECS}


class _ClosedModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, allow_inf_nan=False
    )


def _parse_rational(
    text: object,
    *,
    label: str,
    max_abs: int = MAX_ENTRY_ABS,
    max_denominator: int = MAX_ENTRY_DENOMINATOR,
) -> Fraction:
    if not isinstance(text, str):
        raise ValueError(f"{label} must be an exact rational string")
    if not text or len(text) > MAX_RATIONAL_TEXT:
        raise ValueError(f"{label} is empty or too long")
    if text != text.strip():
        raise ValueError(f"{label} must not contain surrounding whitespace")
    try:
        value = Fraction(text)
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError(f"{label} is not an exact finite rational") from exc
    if value.denominator > max_denominator:
        raise ValueError(f"{label} denominator is out of bounds")
    if abs(value.numerator) > max_abs:
        raise ValueError(f"{label} is out of bounds")
    return value


def _canonical_matrix(
    value: object,
    *,
    label: str,
    min_rows: int,
    max_rows: int,
    min_columns: int,
    max_columns: int,
    max_abs: int = MAX_ENTRY_ABS,
    max_denominator: int = MAX_ENTRY_DENOMINATOR,
) -> list[list[str]]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list of rows")
    if not min_rows <= len(value) <= max_rows:
        raise ValueError(f"{label} row count is out of bounds")
    rows: list[list[str]] = []
    for row_index, row in enumerate(value):
        if not isinstance(row, list):
            raise ValueError(f"{label}[{row_index}] must be a list")
        if not min_columns <= len(row) <= max_columns:
            raise ValueError(f"{label}[{row_index}] column count is out of bounds")
        rows.append(
            [
                str(
                    _parse_rational(
                        entry,
                        label=f"{label}[{row_index}][{column_index}]",
                        max_abs=max_abs,
                        max_denominator=max_denominator,
                    )
                )
                for column_index, entry in enumerate(row)
            ]
        )
    if len({len(row) for row in rows}) != 1:
        raise ValueError(f"{label} must be rectangular")
    return rows


def _rectangular_validator(
    label: str,
    *,
    min_rows: int = 1,
    max_rows: int = MAX_ROWS,
    min_columns: int = 1,
    max_columns: int = MAX_COLUMNS,
) -> Any:
    def validate(value: object) -> list[list[str]]:
        return _canonical_matrix(
            value,
            label=label,
            min_rows=min_rows,
            max_rows=max_rows,
            min_columns=min_columns,
            max_columns=max_columns,
        )

    return validate


def _square_validator(label: str) -> Any:
    def validate(value: object) -> list[list[str]]:
        matrix = _canonical_matrix(
            value,
            label=label,
            min_rows=MIN_SQUARE_SIZE,
            max_rows=MAX_SQUARE_SIZE,
            min_columns=MIN_SQUARE_SIZE,
            max_columns=MAX_SQUARE_SIZE,
        )
        if len(matrix) != len(matrix[0]):
            raise ValueError(f"{label} must be square")
        return matrix

    return validate


class MatrixMultiplyProblem(_ClosedModel):
    kind: Literal["matrix_multiply"] = "matrix_multiply"
    left: list[list[str]]
    right: list[list[str]]

    @field_validator("left", mode="before")
    @classmethod
    def _left(cls, value: object) -> list[list[str]]:
        return _rectangular_validator("left")(value)

    @field_validator("right", mode="before")
    @classmethod
    def _right(cls, value: object) -> list[list[str]]:
        return _rectangular_validator("right")(value)

    @model_validator(mode="after")
    def _matching_inner_dimensions(self) -> MatrixMultiplyProblem:
        if len(self.left[0]) != len(self.right):
            raise ValueError("left columns must equal right rows")
        return self


class MatrixDeterminantProblem(_ClosedModel):
    kind: Literal["matrix_determinant"] = "matrix_determinant"
    matrix: list[list[str]]

    @field_validator("matrix", mode="before")
    @classmethod
    def _matrix(cls, value: object) -> list[list[str]]:
        return _square_validator("matrix")(value)


class MatrixInverseProblem(_ClosedModel):
    kind: Literal["matrix_inverse"] = "matrix_inverse"
    matrix: list[list[str]]

    @field_validator("matrix", mode="before")
    @classmethod
    def _matrix(cls, value: object) -> list[list[str]]:
        return _square_validator("matrix")(value)


class MatrixLUProblem(_ClosedModel):
    kind: Literal["matrix_lu"] = "matrix_lu"
    matrix: list[list[str]]

    @field_validator("matrix", mode="before")
    @classmethod
    def _matrix(cls, value: object) -> list[list[str]]:
        return _square_validator("matrix")(value)


class MatrixMultiplyAnswer(_ClosedModel):
    kind: Literal["matrix_multiply_answer"] = "matrix_multiply_answer"
    matrix: list[list[str]]

    @field_validator("matrix", mode="before")
    @classmethod
    def _matrix(cls, value: object) -> list[list[str]]:
        return _canonical_matrix(
            value,
            label="matrix",
            min_rows=1,
            max_rows=MAX_ROWS,
            min_columns=1,
            max_columns=MAX_COLUMNS,
            max_abs=MAX_ANSWER_ABS,
            max_denominator=MAX_ANSWER_DENOMINATOR,
        )


class MatrixDeterminantAnswer(_ClosedModel):
    kind: Literal["matrix_determinant_answer"] = "matrix_determinant_answer"
    value: str

    @field_validator("value", mode="before")
    @classmethod
    def _value(cls, value: object) -> str:
        return str(
            _parse_rational(
                value,
                label="value",
                max_abs=MAX_ANSWER_ABS,
                max_denominator=MAX_ANSWER_DENOMINATOR,
            )
        )


class MatrixInverseAnswer(_ClosedModel):
    kind: Literal["matrix_inverse_answer"] = "matrix_inverse_answer"
    matrix: list[list[str]]

    @field_validator("matrix", mode="before")
    @classmethod
    def _matrix(cls, value: object) -> list[list[str]]:
        return _canonical_matrix(
            value,
            label="matrix",
            min_rows=MIN_SQUARE_SIZE,
            max_rows=MAX_SQUARE_SIZE,
            min_columns=MIN_SQUARE_SIZE,
            max_columns=MAX_SQUARE_SIZE,
            max_abs=MAX_ANSWER_ABS,
            max_denominator=MAX_ANSWER_DENOMINATOR,
        )


class MatrixLUAnswer(_ClosedModel):
    kind: Literal["matrix_lu_answer"] = "matrix_lu_answer"
    permutation: list[list[str]]
    lower: list[list[str]]
    upper: list[list[str]]

    @field_validator("permutation", "lower", "upper", mode="before")
    @classmethod
    def _matrix(cls, value: object) -> list[list[str]]:
        return _canonical_matrix(
            value,
            label="lu matrix",
            min_rows=MIN_SQUARE_SIZE,
            max_rows=MAX_SQUARE_SIZE,
            min_columns=MIN_SQUARE_SIZE,
            max_columns=MAX_SQUARE_SIZE,
            max_abs=MAX_ANSWER_ABS,
            max_denominator=MAX_ANSWER_DENOMINATOR,
        )


PROBLEM_TYPES: tuple[type[BaseModel], ...] = (
    MatrixMultiplyProblem,
    MatrixDeterminantProblem,
    MatrixInverseProblem,
    MatrixLUProblem,
)
_PROBLEM_MODELS: dict[str, type[BaseModel]] = {
    MULTIPLY_CONTRACT: MatrixMultiplyProblem,
    DETERMINANT_CONTRACT: MatrixDeterminantProblem,
    INVERSE_CONTRACT: MatrixInverseProblem,
    LU_CONTRACT: MatrixLUProblem,
}
_ANSWER_MODELS: dict[str, type[BaseModel]] = {
    MULTIPLY_CONTRACT: MatrixMultiplyAnswer,
    DETERMINANT_CONTRACT: MatrixDeterminantAnswer,
    INVERSE_CONTRACT: MatrixInverseAnswer,
    LU_CONTRACT: MatrixLUAnswer,
}


def _descriptor(contract_id: object) -> dict[str, str]:
    if not isinstance(contract_id, str):
        raise ValueError("contract id must be a string")
    try:
        return _SPEC_INDEX[contract_id]
    except KeyError as exc:
        raise ValueError(f"unknown matrix contract {contract_id!r}") from exc


def _fractions(matrix: list[list[str]]) -> list[list[Fraction]]:
    return [[Fraction(entry) for entry in row] for row in matrix]


def _strings(matrix: list[list[Fraction]]) -> list[list[str]]:
    return [[str(entry) for entry in row] for row in matrix]


def _identity(size: int) -> list[list[Fraction]]:
    return [
        [Fraction(1 if row == column else 0) for column in range(size)]
        for row in range(size)
    ]


def _matrix_multiply(
    left: list[list[Fraction]], right: list[list[Fraction]]
) -> list[list[Fraction]]:
    """Expected-answer product: row-major triple loop."""
    rows = len(left)
    columns = len(right[0])
    inner = len(right)
    result = [[Fraction(0) for _ in range(columns)] for _ in range(rows)]
    for row in range(rows):
        for column in range(columns):
            total = Fraction(0)
            for index in range(inner):
                total += left[row][index] * right[index][column]
            result[row][column] = total
    return result


def _sympy_multiply(
    left: list[list[Fraction]], right: list[list[Fraction]]
) -> list[list[Fraction]]:
    """Checker product through SymPy exact matrices, independent of the oracle."""
    import sympy

    left_matrix = sympy.Matrix(
        [
            [sympy.Rational(value.numerator, value.denominator) for value in row]
            for row in left
        ]
    )
    right_matrix = sympy.Matrix(
        [
            [sympy.Rational(value.numerator, value.denominator) for value in row]
            for row in right
        ]
    )
    product = left_matrix * right_matrix
    return [
        [
            Fraction(int(product[row, column].p), int(product[row, column].q))
            for column in range(product.cols)
        ]
        for row in range(product.rows)
    ]


def _determinant_laplace(matrix: list[list[Fraction]]) -> Fraction:
    """Independent expected determinant: explicit cofactor expansion."""
    size = len(matrix)
    if size == 1:
        return matrix[0][0]
    if size == 2:
        return matrix[0][0] * matrix[1][1] - matrix[0][1] * matrix[1][0]
    total = Fraction(0)
    for column in range(size):
        minor = [
            [row[index] for index in range(size) if index != column]
            for row in matrix[1:]
        ]
        total += (-1) ** column * matrix[0][column] * _determinant_laplace(minor)
    return total


def _determinant_bareiss(matrix: list[list[Fraction]]) -> Fraction:
    """Checker determinant: fraction-free Bareiss elimination."""
    size = len(matrix)
    if size == 1:
        return matrix[0][0]
    work = [row[:] for row in matrix]
    sign = Fraction(1)
    previous = Fraction(1)
    for pivot in range(size - 1):
        if work[pivot][pivot] == 0:
            swap = next(
                (row for row in range(pivot + 1, size) if work[row][pivot] != 0),
                None,
            )
            if swap is None:
                return Fraction(0)
            work[pivot], work[swap] = work[swap], work[pivot]
            sign = -sign
        for row in range(pivot + 1, size):
            for column in range(pivot + 1, size):
                work[row][column] = (
                    work[row][column] * work[pivot][pivot]
                    - work[row][pivot] * work[pivot][column]
                ) / previous
        previous = work[pivot][pivot]
        for row in range(pivot + 1, size):
            work[row][pivot] = Fraction(0)
    return sign * work[size - 1][size - 1]


def _cofactor(matrix: list[list[Fraction]], row: int, column: int) -> Fraction:
    size = len(matrix)
    minor = [
        [matrix[r][c] for c in range(size) if c != column]
        for r in range(size)
        if r != row
    ]
    return (-1) ** (row + column) * _determinant_laplace(minor)


def _inverse_adjugate(matrix: list[list[Fraction]]) -> list[list[Fraction]]:
    determinant = _determinant_laplace(matrix)
    if determinant == 0:
        raise ValueError("matrix is singular")
    size = len(matrix)
    return [
        [_cofactor(matrix, column, row) / determinant for column in range(size)]
        for row in range(size)
    ]


def _lu_decompose(
    matrix: list[list[Fraction]],
) -> tuple[list[list[Fraction]], list[list[Fraction]], list[list[Fraction]]]:
    """Gaussian elimination with deterministic partial pivoting.

    The convention is ``P * A = L * U``. Ties choose the first candidate row.
    A fully zero pivot column needs no elimination, so the algorithm can also
    factor singular matrices.
    """
    size = len(matrix)
    upper = [row[:] for row in matrix]
    permutation = _identity(size)
    lower = _identity(size)
    for column in range(size):
        pivot = max(
            range(column, size),
            key=lambda row: abs(upper[row][column]),
        )
        if upper[pivot][column] == 0:
            continue
        if pivot != column:
            upper[column], upper[pivot] = upper[pivot], upper[column]
            permutation[column], permutation[pivot] = (
                permutation[pivot],
                permutation[column],
            )
            lower[column][:column], lower[pivot][:column] = (
                lower[pivot][:column],
                lower[column][:column],
            )
        for row in range(column + 1, size):
            factor = upper[row][column] / upper[column][column]
            lower[row][column] = factor
            for index in range(column, size):
                upper[row][index] -= factor * upper[column][index]
    return permutation, lower, upper


def _validate_semantics(contract_id: str, parsed: BaseModel) -> None:
    if contract_id == INVERSE_CONTRACT:
        assert isinstance(parsed, MatrixInverseProblem)
        if _determinant_laplace(_fractions(parsed.matrix)) == 0:
            raise ValueError("inverse requires a nonsingular matrix")


def validate_problem(contract_id: str, problem: dict[str, Any]) -> dict[str, Any]:
    descriptor = _descriptor(contract_id)
    if not isinstance(problem, dict):
        raise ValueError("a problem must be a JSON-compatible object")
    if problem.get("kind") != descriptor["kind"]:
        raise ValueError(
            f"problem kind must be {descriptor['kind']!r} for {contract_id}"
        )
    try:
        parsed = _PROBLEM_MODELS[contract_id].model_validate(problem)
    except ValidationError as exc:
        raise ValueError(f"invalid problem: {exc}") from exc
    _validate_semantics(contract_id, parsed)
    return parsed.model_dump(mode="json")


def problem_extent(contract_id: str, problem: dict[str, Any]) -> dict[str, int | bool]:
    """Describe exact entry budgets and the actual matrix dimensions."""
    validated = validate_problem(contract_id, problem)
    matrices = [
        validated[key] for key in ("matrix", "left", "right") if key in validated
    ]
    dimensions = [size for matrix in matrices for size in (len(matrix), len(matrix[0]))]
    entries = [
        Fraction(value) for matrix in matrices for row in matrix for value in row
    ]
    bound = max(max(abs(value.numerator), value.denominator) for value in entries)
    return {
        "min_degree": 0,
        "max_degree": 0,
        "max_abs_coefficient": max(1, bound),
        "min_dimension": min(dimensions),
        "max_dimension": max(dimensions),
        "requires_general": False,
    }


def expected_answer(contract_id: str, problem: dict[str, Any]) -> dict[str, Any]:
    validated = validate_problem(contract_id, problem)
    if contract_id == MULTIPLY_CONTRACT:
        multiply_problem = MatrixMultiplyProblem.model_validate(validated)
        product = _matrix_multiply(
            _fractions(multiply_problem.left),
            _fractions(multiply_problem.right),
        )
        return {
            "kind": "matrix_multiply_answer",
            "matrix": _strings(product),
        }
    if contract_id == DETERMINANT_CONTRACT:
        determinant_problem = MatrixDeterminantProblem.model_validate(validated)
        determinant = _determinant_laplace(_fractions(determinant_problem.matrix))
        return {
            "kind": "matrix_determinant_answer",
            "value": str(determinant),
        }
    if contract_id == INVERSE_CONTRACT:
        inverse_problem = MatrixInverseProblem.model_validate(validated)
        inverse = _inverse_adjugate(_fractions(inverse_problem.matrix))
        return {
            "kind": "matrix_inverse_answer",
            "matrix": _strings(inverse),
        }
    if contract_id == LU_CONTRACT:
        lu_problem = MatrixLUProblem.model_validate(validated)
        permutation, lower, upper = _lu_decompose(_fractions(lu_problem.matrix))
        return {
            "kind": "matrix_lu_answer",
            "permutation": _strings(permutation),
            "lower": _strings(lower),
            "upper": _strings(upper),
        }
    raise ValueError(f"unknown matrix contract {contract_id!r}")


def _answer(contract_id: str, candidate: object) -> BaseModel:
    if not isinstance(candidate, dict):
        raise ValueError("a candidate answer must be a JSON-compatible object")
    try:
        return _ANSWER_MODELS[contract_id].model_validate(candidate)
    except ValidationError as exc:
        raise ValueError(f"invalid candidate answer: {exc}") from exc


def _is_permutation(matrix: list[list[Fraction]]) -> bool:
    size = len(matrix)
    for row in matrix:
        if len(row) != size:
            return False
        if any(value not in {0, 1} for value in row):
            return False
        if sum(row) != 1:
            return False
    for column in range(size):
        if sum(matrix[row][column] for row in range(size)) != 1:
            return False
    return True


def _is_unit_lower(matrix: list[list[Fraction]]) -> bool:
    size = len(matrix)
    for row in range(size):
        for column in range(size):
            if row == column and matrix[row][column] != 1:
                return False
            if column > row and matrix[row][column] != 0:
                return False
    return True


def _is_upper(matrix: list[list[Fraction]]) -> bool:
    size = len(matrix)
    return all(matrix[row][column] == 0 for row in range(size) for column in range(row))


def _matrices_equal(left: list[list[Fraction]], right: list[list[Fraction]]) -> bool:
    return (
        len(left) == len(right)
        and all(len(a) == len(b) for a, b in zip(left, right, strict=True))
        and all(
            a == b
            for left_row, right_row in zip(left, right, strict=True)
            for a, b in zip(left_row, right_row, strict=True)
        )
    )


def _check_shape(matrix: list[list[str]], rows: int, columns: int) -> bool:
    return len(matrix) == rows and all(len(row) == columns for row in matrix)


def check_answer(
    contract_id: str, problem: dict[str, Any], candidate: dict[str, Any]
) -> bool:
    _descriptor(contract_id)
    validated = validate_problem(contract_id, problem)
    parsed_answer = _answer(contract_id, candidate)
    if contract_id == MULTIPLY_CONTRACT:
        assert isinstance(parsed_answer, MatrixMultiplyAnswer)
        multiply_problem = MatrixMultiplyProblem.model_validate(validated)
        left = _fractions(multiply_problem.left)
        right = _fractions(multiply_problem.right)
        rows = len(left)
        columns = len(right[0])
        if not _check_shape(parsed_answer.matrix, rows, columns):
            return False
        expected = _sympy_multiply(left, right)
        return _matrices_equal(expected, _fractions(parsed_answer.matrix))
    if contract_id == DETERMINANT_CONTRACT:
        assert isinstance(parsed_answer, MatrixDeterminantAnswer)
        determinant_problem = MatrixDeterminantProblem.model_validate(validated)
        actual = Fraction(parsed_answer.value)
        return actual == _determinant_bareiss(_fractions(determinant_problem.matrix))
    if contract_id == INVERSE_CONTRACT:
        assert isinstance(parsed_answer, MatrixInverseAnswer)
        inverse_problem = MatrixInverseProblem.model_validate(validated)
        source = _fractions(inverse_problem.matrix)
        size = len(source)
        if not _check_shape(parsed_answer.matrix, size, size):
            return False
        inverse = _fractions(parsed_answer.matrix)
        identity = _identity(size)
        return _matrices_equal(
            _sympy_multiply(source, inverse), identity
        ) and _matrices_equal(_sympy_multiply(inverse, source), identity)
    if contract_id == LU_CONTRACT:
        assert isinstance(parsed_answer, MatrixLUAnswer)
        lu_problem = MatrixLUProblem.model_validate(validated)
        source = _fractions(lu_problem.matrix)
        size = len(source)
        for matrix in (
            parsed_answer.permutation,
            parsed_answer.lower,
            parsed_answer.upper,
        ):
            if not _check_shape(matrix, size, size):
                return False
        permutation = _fractions(parsed_answer.permutation)
        lower = _fractions(parsed_answer.lower)
        upper = _fractions(parsed_answer.upper)
        if not _is_permutation(permutation):
            return False
        if not _is_unit_lower(lower):
            return False
        if not _is_upper(upper):
            return False
        return _matrices_equal(
            _sympy_multiply(permutation, source),
            _sympy_multiply(lower, upper),
        )
    raise ValueError(f"unknown matrix contract {contract_id!r}")


def _render_matrix(matrix: list[list[str]]) -> str:
    return "[" + ", ".join("[" + ", ".join(row) + "]" for row in matrix) + "]"


def render_problem(contract_id: str, problem: dict[str, Any]) -> str:
    validated = validate_problem(contract_id, problem)
    if contract_id == MULTIPLY_CONTRACT:
        multiply_problem = MatrixMultiplyProblem.model_validate(validated)
        return (
            f"Multiply the matrix {_render_matrix(multiply_problem.left)} by "
            f"{_render_matrix(multiply_problem.right)}."
        )
    if contract_id == DETERMINANT_CONTRACT:
        determinant_problem = MatrixDeterminantProblem.model_validate(validated)
        return f"Find the determinant of {_render_matrix(determinant_problem.matrix)}."
    if contract_id == INVERSE_CONTRACT:
        inverse_problem = MatrixInverseProblem.model_validate(validated)
        return (
            f"Find the inverse of the matrix {_render_matrix(inverse_problem.matrix)}."
        )
    lu_problem = MatrixLUProblem.model_validate(validated)
    return (
        f"Factor the matrix {_render_matrix(lu_problem.matrix)} as P*A = L*U, "
        "where P is a permutation, L is unit lower triangular and U is upper "
        "triangular."
    )


def render_answer(contract_id: str, candidate: dict[str, Any]) -> str:
    parsed = _answer(contract_id, candidate)
    if contract_id == DETERMINANT_CONTRACT:
        assert isinstance(parsed, MatrixDeterminantAnswer)
        return parsed.value
    if contract_id == LU_CONTRACT:
        assert isinstance(parsed, MatrixLUAnswer)
        return (
            f"P = {_render_matrix(parsed.permutation)}, "
            f"L = {_render_matrix(parsed.lower)}, "
            f"U = {_render_matrix(parsed.upper)}"
        )
    assert isinstance(parsed, (MatrixMultiplyAnswer, MatrixInverseAnswer))
    return _render_matrix(parsed.matrix)


def _unique_wrong(
    contract_id: str, problem: dict[str, Any], variants: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Deduplicate independently-constructed wrong answers.

    Wrongness is established by construction (entry/scalar perturbation or a
    structural LU violation), never by asking the checker that qualification
    is testing.
    """
    _ = (contract_id, problem)
    accepted: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in variants:
        marker = repr(candidate)
        if marker in seen:
            continue
        seen.add(marker)
        accepted.append(candidate)
    return accepted


def _mutate_matrix(matrix: list[list[str]], delta: int) -> list[list[str]]:
    changed = [list(row) for row in matrix]
    changed[0][0] = str(Fraction(changed[0][0]) + delta)
    return changed


def wrong_answers(
    contract_id: str, problem: dict[str, Any], answer: dict[str, Any]
) -> list[dict[str, Any]]:
    validated = validate_problem(contract_id, problem)
    expected = expected_answer(contract_id, validated)
    _answer(contract_id, answer)
    if contract_id in {MULTIPLY_CONTRACT, INVERSE_CONTRACT}:
        variants = [
            {
                "kind": expected["kind"],
                "matrix": _mutate_matrix(expected["matrix"], delta),
            }
            for delta in (1, -1, 2, -2, 3)
        ]
        return _unique_wrong(contract_id, validated, variants)
    if contract_id == DETERMINANT_CONTRACT:
        value = Fraction(expected["value"])
        variants = [
            {"kind": expected["kind"], "value": str(value + delta)}
            for delta in (1, -1, 2, -2, 3)
        ]
        return _unique_wrong(contract_id, validated, variants)
    scaled_lower = [
        [str(Fraction(entry) * 2) for entry in row] for row in expected["lower"]
    ]
    scaled_upper = [
        [str(Fraction(entry) / 2) for entry in row] for row in expected["upper"]
    ]
    not_unit_lower = [list(row) for row in expected["lower"]]
    not_unit_lower[0][0] = "2"
    not_upper = [list(row) for row in expected["upper"]]
    not_upper[1][0] = "1"
    bad_permutation = [list(row) for row in expected["permutation"]]
    bad_permutation[0] = [str(0) for _ in bad_permutation[0]]
    mutated_upper = [list(row) for row in expected["upper"]]
    mutated_upper[0][0] = str(Fraction(mutated_upper[0][0]) + 1)
    variants = [
        {
            "kind": expected["kind"],
            "permutation": expected["permutation"],
            "lower": scaled_lower,
            "upper": scaled_upper,
        },
        {
            "kind": expected["kind"],
            "permutation": expected["permutation"],
            "lower": not_unit_lower,
            "upper": expected["upper"],
        },
        {
            "kind": expected["kind"],
            "permutation": expected["permutation"],
            "lower": expected["lower"],
            "upper": not_upper,
        },
        {
            "kind": expected["kind"],
            "permutation": bad_permutation,
            "lower": expected["lower"],
            "upper": expected["upper"],
        },
        {
            "kind": expected["kind"],
            "permutation": expected["permutation"],
            "lower": expected["lower"],
            "upper": mutated_upper,
        },
    ]
    return _unique_wrong(contract_id, validated, variants)


def _entry_strategy() -> st.SearchStrategy[str]:
    return st.fractions(min_value=-5, max_value=5, max_denominator=3).map(str)


@st.composite
def _matrix_strategy(draw: st.DrawFn, rows: int, columns: int) -> list[list[str]]:
    return [[draw(_entry_strategy()) for _ in range(columns)] for _ in range(rows)]


@st.composite
def _multiply_strategy(draw: st.DrawFn) -> dict[str, Any]:
    rows = draw(st.integers(min_value=1, max_value=MAX_ROWS))
    inner = draw(st.integers(min_value=1, max_value=MAX_COLUMNS))
    columns = draw(st.integers(min_value=1, max_value=MAX_COLUMNS))
    return {
        "kind": "matrix_multiply",
        "left": draw(_matrix_strategy(rows, inner)),
        "right": draw(_matrix_strategy(inner, columns)),
    }


@st.composite
def _square_strategy(draw: st.DrawFn, *, nonsingular: bool) -> dict[str, Any]:
    size = draw(st.integers(min_value=MIN_SQUARE_SIZE, max_value=MAX_SQUARE_SIZE))
    matrix = draw(_matrix_strategy(size, size))
    if nonsingular and _determinant_laplace(_fractions(matrix)) == 0:
        # Deterministically restore nonsingularity by shifting the whole
        # diagonal; the candidate stays inside the same input bounds.
        original = _fractions(matrix)
        offset = 1
        while offset <= 10:
            candidate = [row[:] for row in original]
            for index in range(size):
                candidate[index][index] += offset
            if _determinant_laplace(candidate) != 0:
                matrix = _strings(candidate)
                break
            offset += 1
        else:
            matrix = _strings(_identity(size))
    return {"kind": "matrix_inverse", "matrix": matrix}


@st.composite
def _determinant_strategy(draw: st.DrawFn) -> dict[str, Any]:
    problem = draw(_square_strategy(nonsingular=False))
    return {"kind": "matrix_determinant", "matrix": problem["matrix"]}


@st.composite
def _inverse_strategy(draw: st.DrawFn) -> dict[str, Any]:
    return draw(_square_strategy(nonsingular=True))


@st.composite
def _lu_strategy(draw: st.DrawFn) -> dict[str, Any]:
    problem = draw(_square_strategy(nonsingular=False))
    return {"kind": "matrix_lu", "matrix": problem["matrix"]}


def problem_strategy(contract_id: str) -> st.SearchStrategy[dict[str, Any]]:
    _descriptor(contract_id)
    if contract_id == MULTIPLY_CONTRACT:
        return _multiply_strategy()
    if contract_id == DETERMINANT_CONTRACT:
        return _determinant_strategy()
    if contract_id == INVERSE_CONTRACT:
        return _inverse_strategy()
    return _lu_strategy()


def boundary_problems(contract_id: str) -> list[dict[str, Any]]:
    _descriptor(contract_id)
    if contract_id == MULTIPLY_CONTRACT:
        return [
            {
                "kind": "matrix_multiply",
                "left": [["1", "0"], ["0", "1"]],
                "right": [["2", "-1"], ["3", "4"]],
            },
            {
                "kind": "matrix_multiply",
                "left": [["1", "2", "3"], ["4", "5", "6"]],
                "right": [["1", "0"], ["0", "1"], ["1", "1"]],
            },
            {
                "kind": "matrix_multiply",
                "left": [["1/2", "2/3"], ["-1", "0"]],
                "right": [["3", "1/4"], ["2", "5/6"]],
            },
            {
                "kind": "matrix_multiply",
                "left": [["7"]],
                "right": [["1/3"]],
            },
        ]
    if contract_id == DETERMINANT_CONTRACT:
        return [
            {
                "kind": "matrix_determinant",
                "matrix": [["1", "2"], ["3", "4"]],
            },
            {
                "kind": "matrix_determinant",
                "matrix": [["1", "2"], ["2", "4"]],
            },
            {
                "kind": "matrix_determinant",
                "matrix": [
                    ["2", "-1", "3"],
                    ["0", "4", "1"],
                    ["5", "2", "-2"],
                ],
            },
            {
                "kind": "matrix_determinant",
                "matrix": [
                    ["1/2", "2/3", "0"],
                    ["0", "-1", "5/4"],
                    ["3", "0", "7"],
                ],
            },
        ]
    if contract_id == INVERSE_CONTRACT:
        return [
            {
                "kind": "matrix_inverse",
                "matrix": [["1", "0"], ["0", "1"]],
            },
            {
                "kind": "matrix_inverse",
                "matrix": [["4", "7"], ["2", "6"]],
            },
            {
                "kind": "matrix_inverse",
                "matrix": [
                    ["1", "2", "3"],
                    ["0", "1", "4"],
                    ["5", "6", "0"],
                ],
            },
            {
                "kind": "matrix_inverse",
                "matrix": [["1/2", "1/3"], ["-1", "2"]],
            },
        ]
    return [
        {
            "kind": "matrix_lu",
            "matrix": [["1", "0"], ["0", "1"]],
        },
        {
            "kind": "matrix_lu",
            "matrix": [["2", "3"], ["0", "4"]],
        },
        {
            "kind": "matrix_lu",
            "matrix": [["0", "2", "1"], ["1", "1", "0"], ["2", "0", "1"]],
        },
        {
            "kind": "matrix_lu",
            "matrix": [["1", "1"], ["1", "1"]],
        },
        {
            "kind": "matrix_lu",
            "matrix": [
                ["1/2", "2", "0"],
                ["0", "3", "-1"],
                ["4", "0", "5"],
            ],
        },
    ]


__all__ = [
    "CONTRACT_SPECS",
    "DETERMINANT_CONTRACT",
    "INVERSE_CONTRACT",
    "LU_CONTRACT",
    "MULTIPLY_CONTRACT",
    "PROBLEM_TYPES",
    "boundary_problems",
    "check_answer",
    "expected_answer",
    "problem_extent",
    "problem_strategy",
    "render_answer",
    "render_problem",
    "validate_problem",
    "wrong_answers",
]
