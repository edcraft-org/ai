"""Declarative operation dispatch for the deterministic engine.

Adding an operation is one handler plus one registry entry: nothing in this
module branches on operation names (the LU convention metadata is the only
per-operation detail, and it lives next to the registry).
"""

from __future__ import annotations

import time
from collections.abc import Callable

import sympy
from pydantic import ValidationError

from edcraft_validator.domains.math.engine.context import EngineContext
from edcraft_validator.domains.math.engine.contracts import (
    CorrectnessRequest,
    CorrectnessResult,
    EngineUnknown,
    EngineUnsupported,
)
from edcraft_validator.domains.math.engine.matrices import check_matrices
from edcraft_validator.domains.math.engine.scalar import check_scalar
from edcraft_validator.domains.math.engine.solutions import check_solutions
from edcraft_validator.domains.math.engine.validation import validate_request
from edcraft_validator.domains.math.ir.compile import MathCompileError

Handler = Callable[[EngineContext], CorrectnessResult]

# The single source of truth mapping every ``Operation`` literal to a handler.
OPERATION_HANDLERS: dict[str, Handler] = {
    "evaluate": check_scalar,
    "simplify": check_scalar,
    "expand": check_scalar,
    "factor": check_scalar,
    "complete-square": check_scalar,
    "differentiate": check_scalar,
    "antiderivative": check_scalar,
    "definite-integral": check_scalar,
    "solve": check_solutions,
    "matrix-multiply": check_matrices,
    "determinant": check_matrices,
    "inverse": check_matrices,
    "lu": check_matrices,
}

# LU answers are checked against ``P * A = L * U`` (see the engine docs).  The
# convention is recorded on every LU result so callers never have to infer it.
LU_CONVENTION = "P * A = L * U"


def dispatch_operation(ctx: EngineContext) -> CorrectnessResult:
    """Run the registered handler for this request's operation."""
    operation = ctx.request.problem.operation
    handler = OPERATION_HANDLERS.get(operation)
    if handler is None:
        raise EngineUnsupported(f"no handler is registered for {operation!r}")
    return handler(ctx)


def _with_convention(operation: str, result: CorrectnessResult) -> CorrectnessResult:
    if operation != "lu":
        return result
    return result.model_copy(
        update={"details": {**result.details, "lu_convention": LU_CONVENTION}}
    )


def check_in_process(request: CorrectnessRequest) -> CorrectnessResult:
    """Trusted worker/test entry point; public callers use the isolated facade."""
    started = time.perf_counter()
    try:
        request = CorrectnessRequest.model_validate(request.model_dump(mode="json"))
        validate_request(request)
        ctx = EngineContext.create(request)
        result = dispatch_operation(ctx)
    except EngineUnsupported as exc:
        result = CorrectnessResult(outcome="unsupported", reason=str(exc))
    except EngineUnknown as exc:
        result = CorrectnessResult(outcome="unknown", reason=str(exc))
    except NotImplementedError:
        result = CorrectnessResult(
            outcome="unsupported",
            reason="symbolic algorithm does not support this input",
        )
    except (
        ValidationError,
        MathCompileError,
        ValueError,
        TypeError,
        KeyError,
        ZeroDivisionError,
    ) as exc:
        result = CorrectnessResult(
            outcome="error", reason=f"invalid mathematical input: {str(exc)[:500]}"
        )
    except Exception as exc:  # worker owns a deterministic failure outcome
        result = CorrectnessResult(
            outcome="error", reason=f"symbolic calculation failed: {type(exc).__name__}"
        )
    return _with_convention(request.problem.operation, result).model_copy(
        update={
            "duration_ms": (time.perf_counter() - started) * 1000,
            "sympy_version": sympy.__version__,
        }
    )
