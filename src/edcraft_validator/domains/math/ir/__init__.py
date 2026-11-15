"""Typed math IR and its closed compiler."""

from edcraft_validator.domains.math.ir.compile import (
    MathCompileError,
    build_symbols,
    compile_expr,
    compile_givens,
    compile_relation,
    goal_symbols,
    parse_exact,
)
from edcraft_validator.domains.math.ir.schema import (
    AnswerRecipe,
    Distractor,
    Expr,
    Given,
    Goal,
    MathItemSpec,
    MathReconstruction,
    MathTemplateSpec,
    ParameterSpec,
    RecipeInterval,
    Relation,
    SymbolSpec,
    TextSpec,
)

__all__ = [
    "AnswerRecipe",
    "Distractor",
    "Expr",
    "Given",
    "Goal",
    "MathCompileError",
    "MathItemSpec",
    "MathReconstruction",
    "MathTemplateSpec",
    "ParameterSpec",
    "RecipeInterval",
    "Relation",
    "SymbolSpec",
    "TextSpec",
    "build_symbols",
    "compile_expr",
    "compile_givens",
    "compile_relation",
    "goal_symbols",
    "parse_exact",
]
