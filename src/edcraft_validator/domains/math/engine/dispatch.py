"""Operation dispatch for the deterministic engine; no topic families or LLMs."""

from __future__ import annotations

import time

import sympy
from pydantic import ValidationError

from edcraft_validator.domains.math.engine.context import EngineContext
from edcraft_validator.domains.math.engine.contracts import (
    CorrectnessRequest,
    CorrectnessResult,
    EngineUnknown,
    EngineUnsupported,
)
from edcraft_validator.domains.math.engine.validation import validate_request
from edcraft_validator.domains.math.ir.compile import MathCompileError


def check_in_process(request: CorrectnessRequest) -> CorrectnessResult:
    """Trusted worker/test entry point; public callers use the isolated facade."""
    started = time.perf_counter()
    try:
        request = CorrectnessRequest.model_validate(request.model_dump(mode="json"))
        validate_request(request)
        ctx = EngineContext.create(request)
        operation = request.problem.operation
        if operation == "solve":
            from edcraft_validator.domains.math.engine.solutions import check_solutions

            result = check_solutions(ctx)
        elif operation in {"matrix-multiply", "determinant", "inverse", "lu"}:
            from edcraft_validator.domains.math.engine.matrices import check_matrices

            result = check_matrices(ctx)
        else:
            from edcraft_validator.domains.math.engine.scalar import check_scalar

            result = check_scalar(ctx)
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
    return result.model_copy(
        update={
            "duration_ms": (time.perf_counter() - started) * 1000,
            "sympy_version": sympy.__version__,
        }
    )
