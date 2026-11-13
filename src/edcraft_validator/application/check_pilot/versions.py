"""Static version metadata shared by qualification evidence paths."""

from __future__ import annotations

from importlib.metadata import version as package_version

from edcraft_validator.application.check_pilot.models import (
    RENDERER_VERSION,
    SOLVE_RENDERER_VERSION,
)


def static_versions() -> dict[str, str]:
    """Return the canonical static evidence versions."""
    return {
        "check_pilot": "1",
        "differentiation": "sympy",
        "sympy": package_version("sympy"),
        "oracle": "coefficient-arithmetic/1",
        "polynomial_oracle": "coefficient-arithmetic/1",
        "solution_oracle": "discriminant-sign/1",
        "recipe_compiler": "1",
        "renderer": RENDERER_VERSION,
        "solve_renderer": SOLVE_RENDERER_VERSION,
        "question_builder": RENDERER_VERSION,
        "solve_question_builder": SOLVE_RENDERER_VERSION,
    }


__all__ = ["static_versions"]
