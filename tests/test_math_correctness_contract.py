"""Registry coverage and honest build metadata."""

from __future__ import annotations

from typing import get_args

import pytest
import sympy
from pydantic import ValidationError

from edcraft_validator.domains.math.engine.contracts import (
    CorrectnessResult,
    EngineUnsupported,
    Operation,
)
from edcraft_validator.domains.math.engine.dispatch import (
    OPERATION_HANDLERS,
    dispatch_operation,
)


def test_every_operation_literal_has_one_handler():
    declared = set(get_args(Operation))
    assert set(OPERATION_HANDLERS) == declared
    assert all(callable(handler) for handler in OPERATION_HANDLERS.values())


def test_result_stamps_the_installed_sympy_version():
    result = CorrectnessResult(outcome="correct", reason="exact")
    assert result.sympy_version == sympy.__version__

    explicit = CorrectnessResult(
        outcome="correct", reason="exact", sympy_version=sympy.__version__
    )
    assert explicit.sympy_version == sympy.__version__

    with pytest.raises(ValidationError, match="does not match"):
        CorrectnessResult(outcome="correct", reason="exact", sympy_version="0.0.0")


def test_dispatch_rejects_an_unregistered_operation():
    class FakeProblem:
        operation = "not-an-operation"

    class FakeRequest:
        problem = FakeProblem()

    class FakeContext:
        request = FakeRequest()

    with pytest.raises(EngineUnsupported):
        dispatch_operation(FakeContext())  # type: ignore[arg-type]
