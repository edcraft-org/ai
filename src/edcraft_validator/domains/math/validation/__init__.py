"""Tri-state answer primitives and the declarative item harness."""

from edcraft_validator.domains.math.validation.answers import (
    compile_answer,
    parse_answer_expr,
)
from edcraft_validator.domains.math.validation.harness import (
    HarnessReport,
    Witness,
    WitnessOutcome,
    check_answer,
    validate_item,
    validate_template,
)
from edcraft_validator.domains.math.validation.isolation import (
    DEFAULT_VALIDATION_TIMEOUT_SECONDS,
    ValidationTimeout,
    ValidationWorkerError,
    run_isolated,
)
from edcraft_validator.domains.math.validation.primitives import (
    check_primitive,
    collection_equal,
    expression_equiv,
    interval_equal,
    matrix_equal,
    numeric_equal,
    option_equivalent,
    quantity_equal,
    solution_set_equal,
    string_equal,
)
from edcraft_validator.domains.math.validation.results import (
    OptionCheck,
    PrimitiveResult,
    PrimitiveStatus,
    ValidationReport,
)

__all__ = [
    "DEFAULT_VALIDATION_TIMEOUT_SECONDS",
    "HarnessReport",
    "OptionCheck",
    "PrimitiveResult",
    "PrimitiveStatus",
    "ValidationReport",
    "ValidationTimeout",
    "ValidationWorkerError",
    "Witness",
    "WitnessOutcome",
    "check_answer",
    "check_primitive",
    "collection_equal",
    "compile_answer",
    "expression_equiv",
    "interval_equal",
    "matrix_equal",
    "numeric_equal",
    "option_equivalent",
    "parse_answer_expr",
    "quantity_equal",
    "run_isolated",
    "solution_set_equal",
    "string_equal",
    "validate_item",
    "validate_template",
]
