"""Shared valid math-domain fixtures for unit and workflow tests."""

from edcraft_validator.domains.math.candidate_builder import build_math_candidate
from edcraft_validator.domains.math.math_schemas import MathTemplateRequest

# --- Generic IR template fixtures -------------------------------------------
#
# These fixtures exercise the generic authoring path. They are deliberately
# small finite families so the harness can sweep every combination.


def ir_num(value: int | str):
    from edcraft_validator.domains.math.ir.schema import Expr

    return Expr(num=str(value))


def ir_sym(name: str):
    from edcraft_validator.domains.math.ir.schema import Expr

    return Expr(sym=name)


def ir_param(name: str):
    from edcraft_validator.domains.math.ir.schema import Expr

    return Expr(param=name)


def ir_add(*args):
    from edcraft_validator.domains.math.ir.schema import Expr

    return Expr(op="add", args=list(args))


def ir_mul(*args):
    from edcraft_validator.domains.math.ir.schema import Expr

    return Expr(op="mul", args=list(args))


def ir_sub(left, right):
    from edcraft_validator.domains.math.ir.schema import Expr

    return Expr(op="sub", args=[left, right])


def ir_div(left, right):
    from edcraft_validator.domains.math.ir.schema import Expr

    return Expr(op="div", args=[left, right])


def ir_pow(left, right):
    from edcraft_validator.domains.math.ir.schema import Expr

    return Expr(op="pow", args=[left, right])


def ir_template(topic, parameters, body):
    from edcraft_validator.domains.math.ir.schema import MathTemplateSpec

    return MathTemplateSpec(topic=topic, parameters=parameters, body=body)


def quadratic_ir_template():
    from edcraft_validator.domains.math.ir.schema import (
        AnswerRecipe,
        Distractor,
        Given,
        Goal,
        MathItemSpec,
        ParameterSpec,
        PrimitiveSpec,
        Relation,
        SymbolSpec,
        TextSpec,
        ValidationSpec,
    )

    body = MathItemSpec(
        topic="school.quadratic",
        symbols=[SymbolSpec(name="x", domain="real")],
        givens=[
            Given(
                id="equation",
                relation=Relation(
                    kind="eq",
                    lhs=ir_add(
                        ir_pow(ir_sym("x"), ir_num(2)),
                        ir_mul(
                            ir_sub(ir_num(0), ir_add(ir_param("p"), ir_param("q"))),
                            ir_sym("x"),
                        ),
                        ir_mul(ir_param("p"), ir_param("q")),
                    ),
                    rhs=ir_num(0),
                ),
            )
        ],
        goal=Goal(kind="solve", symbol="x", domain="real"),
        answer_recipe=AnswerRecipe(kind="set", items=[ir_param("p"), ir_param("q")]),
        distractors=[
            Distractor(
                value=ir_sub(ir_num(0), ir_param("p")),
                misconception="SIGN_ERROR",
                reason="Flips the sign of one root",
            ),
            Distractor(
                value=ir_add(ir_param("p"), ir_param("q")),
                misconception="SUM_AS_ROOT",
                reason="Reports the sum of the roots as a root",
            ),
            Distractor(
                value=ir_mul(ir_param("p"), ir_param("q")),
                misconception="PRODUCT_AS_ROOT",
                reason="Reports the product of the roots as a root",
            ),
        ],
        text=TextSpec(mode="symbolic", template="Solve {equation}."),
        validation=ValidationSpec(primitives=[PrimitiveSpec(type="solution_set")]),
    )
    return ir_template(
        "school.quadratic",
        [
            ParameterSpec(name="p", values=["2", "3"]),
            ParameterSpec(name="q", values=["-7", "-5"]),
        ],
        body,
    )


def linear_system_ir_template():
    from edcraft_validator.domains.math.ir.schema import (
        AnswerRecipe,
        Distractor,
        Given,
        Goal,
        MathItemSpec,
        ParameterSpec,
        PrimitiveSpec,
        Relation,
        SymbolSpec,
        TextSpec,
        ValidationSpec,
    )

    body = MathItemSpec(
        topic="school.linear_system",
        symbols=[
            SymbolSpec(name="x", domain="real"),
            SymbolSpec(name="y", domain="real"),
        ],
        givens=[
            Given(
                id="eq1",
                relation=Relation(
                    kind="eq",
                    lhs=ir_add(ir_mul(ir_num(2), ir_sym("x")), ir_sym("y")),
                    rhs=ir_add(ir_mul(ir_num(2), ir_param("p")), ir_param("q")),
                ),
            ),
            Given(
                id="eq2",
                relation=Relation(
                    kind="eq",
                    lhs=ir_add(ir_sym("x"), ir_mul(ir_num(3), ir_sym("y"))),
                    rhs=ir_add(ir_param("p"), ir_mul(ir_num(3), ir_param("q"))),
                ),
            ),
        ],
        goal=Goal(kind="solve", symbols=["x", "y"], domain="real"),
        answer_recipe=AnswerRecipe(kind="tuple", items=[ir_param("p"), ir_param("q")]),
        distractors=[
            Distractor(
                components=[ir_param("p"), ir_sub(ir_num(0), ir_param("q"))],
                misconception="SIGN_ERROR",
                reason="Flips the sign of y",
            ),
            Distractor(
                components=[ir_param("q"), ir_param("p")],
                misconception="SWAPPED",
                reason="Swaps x and y",
            ),
            Distractor(
                components=[ir_add(ir_param("p"), ir_param("q")), ir_num(0)],
                misconception="SUM_ERROR",
                reason="Adds the right-hand sides instead of solving",
            ),
        ],
        text=TextSpec(mode="symbolic", template="Solve the system {equations}."),
        validation=ValidationSpec(primitives=[PrimitiveSpec(type="solution_set")]),
    )
    return ir_template(
        "school.linear_system",
        [
            ParameterSpec(name="p", values=["1", "2"]),
            ParameterSpec(name="q", values=["-2", "-1"]),
        ],
        body,
    )


def derivative_ir_template():
    from edcraft_validator.domains.math.ir.schema import (
        AnswerRecipe,
        Distractor,
        Given,
        Goal,
        MathItemSpec,
        ParameterSpec,
        PrimitiveSpec,
        SymbolSpec,
        TextSpec,
        ValidationSpec,
    )

    # The engine refuses power nodes whose exponent is not a bounded literal,
    # so the fixture fixes the exponents and varies only the coefficients.
    expression = ir_add(
        ir_mul(ir_param("a"), ir_pow(ir_sym("x"), ir_num(3))),
        ir_mul(ir_param("b"), ir_pow(ir_sym("x"), ir_num(2))),
        ir_num(1),
    )
    derivative_expr = ir_add(
        ir_mul(ir_num(3), ir_param("a"), ir_pow(ir_sym("x"), ir_num(2))),
        ir_mul(ir_num(2), ir_param("b"), ir_sym("x")),
    )
    body = MathItemSpec(
        topic="university.derivative",
        symbols=[SymbolSpec(name="x", domain="real")],
        givens=[Given(id="domain_x", kind="domain", symbol="x", domain="real")],
        goal=Goal(kind="derivative", symbol="x", expr=expression, order=1),
        answer_recipe=AnswerRecipe(kind="expression", items=[derivative_expr]),
        distractors=[
            Distractor(
                value=ir_add(
                    ir_mul(ir_num(3), ir_param("a"), ir_pow(ir_sym("x"), ir_num(3))),
                    ir_mul(ir_num(2), ir_param("b"), ir_pow(ir_sym("x"), ir_num(2))),
                ),
                misconception="POWER_NOT_DECREMENTED",
                reason="Keeps the original exponents",
            ),
            Distractor(
                value=ir_add(
                    ir_mul(ir_param("a"), ir_pow(ir_sym("x"), ir_num(2))),
                    ir_mul(ir_param("b"), ir_sym("x")),
                ),
                misconception="DROPPED_COEFFICIENTS",
                reason="Drops the power-rule coefficients",
            ),
            Distractor(
                value=ir_sub(
                    ir_mul(ir_num(3), ir_param("a"), ir_pow(ir_sym("x"), ir_num(2))),
                    ir_mul(ir_num(2), ir_param("b"), ir_sym("x")),
                ),
                misconception="SIGN_ERROR",
                reason="Flips the sign of the linear term",
            ),
        ],
        text=TextSpec(
            mode="symbolic", template="Differentiate {expr} with respect to x."
        ),
        validation=ValidationSpec(primitives=[PrimitiveSpec(type="expression_equiv")]),
    )
    return ir_template(
        "university.derivative",
        [
            ParameterSpec(name="a", values=["2", "3"]),
            ParameterSpec(name="b", values=["-2", "1"]),
        ],
        body,
    )


def determinant_ir_template():
    from edcraft_validator.domains.math.ir.schema import (
        AnswerRecipe,
        Distractor,
        Given,
        Goal,
        MathItemSpec,
        ParameterSpec,
        PrimitiveSpec,
        SymbolSpec,
        TextSpec,
        ValidationSpec,
    )

    body = MathItemSpec(
        topic="university.determinant",
        symbols=[SymbolSpec(name="m", kind="given", domain="integer")],
        givens=[Given(id="entries", kind="domain", symbol="m", domain="integer")],
        goal=Goal(
            kind="determinant",
            matrix=[
                [ir_param("a"), ir_param("b")],
                [ir_param("c"), ir_param("d")],
            ],
        ),
        answer_recipe=AnswerRecipe(
            kind="numeric",
            items=[
                ir_sub(
                    ir_mul(ir_param("a"), ir_param("d")),
                    ir_mul(ir_param("b"), ir_param("c")),
                )
            ],
        ),
        distractors=[
            Distractor(
                value=ir_add(
                    ir_mul(ir_param("a"), ir_param("d")),
                    ir_mul(ir_param("b"), ir_param("c")),
                ),
                misconception="SIGN_ERROR",
                reason="Adds the cross term instead of subtracting",
            ),
            Distractor(
                value=ir_sub(
                    ir_mul(ir_param("a"), ir_param("b")),
                    ir_mul(ir_param("c"), ir_param("d")),
                ),
                misconception="MINOR_SWAP",
                reason="Swaps the diagonal pairings",
            ),
            Distractor(
                value=ir_mul(ir_param("a"), ir_param("d")),
                misconception="MISSING_MINOR",
                reason="Keeps only the main diagonal product",
            ),
        ],
        text=TextSpec(mode="symbolic", template="Find the determinant of {matrix}."),
        validation=ValidationSpec(primitives=[PrimitiveSpec(type="numeric")]),
    )
    return ir_template(
        "university.determinant",
        [
            ParameterSpec(name="a", values=["2", "3"]),
            ParameterSpec(name="b", values=["1", "2"]),
            ParameterSpec(name="c", values=["1", "2"]),
            ParameterSpec(name="d", values=["3", "4"]),
        ],
        body,
    )


def percentage_ir_template():
    from edcraft_validator.domains.math.ir.schema import (
        AnswerRecipe,
        Distractor,
        Given,
        Goal,
        MathItemSpec,
        ParameterSpec,
        PrimitiveSpec,
        SymbolSpec,
        TextSpec,
        ValidationSpec,
    )

    body = MathItemSpec(
        topic="school.percentage",
        symbols=[SymbolSpec(name="amount", kind="given", domain="rational")],
        givens=[
            Given(id="domain_amount", kind="domain", symbol="amount", domain="rational")
        ],
        goal=Goal(
            kind="evaluate",
            expr=ir_div(ir_mul(ir_param("percent"), ir_param("whole")), ir_num(100)),
        ),
        answer_recipe=AnswerRecipe(
            kind="numeric",
            items=[ir_div(ir_mul(ir_param("percent"), ir_param("whole")), ir_num(100))],
        ),
        distractors=[
            Distractor(
                value=ir_mul(ir_param("percent"), ir_param("whole")),
                misconception="MISSING_DIVISION",
                reason="Forgets to divide by 100",
            ),
            Distractor(
                value=ir_add(ir_param("whole"), ir_param("percent")),
                misconception="ADDED_INSTEAD",
                reason="Adds the percentage to the whole",
            ),
            Distractor(
                value=ir_sub(ir_param("whole"), ir_param("percent")),
                misconception="SUBTRACTED_INSTEAD",
                reason="Subtracts the percentage from the whole",
            ),
        ],
        text=TextSpec(mode="symbolic", template="Find {percent}% of {whole}."),
        validation=ValidationSpec(primitives=[PrimitiveSpec(type="numeric")]),
    )
    return ir_template(
        "school.percentage",
        [
            ParameterSpec(name="percent", values=["10", "20"]),
            ParameterSpec(name="whole", values=["50", "80"]),
        ],
        body,
    )


def ir_proposal(template):
    from edcraft_validator.domains.math.math_schemas import MathTemplateContent

    return MathTemplateContent(item=template)


def ir_candidate(template, *, difficulty="easy"):
    request = MathTemplateRequest(
        prompt="Author a generic mathematics multiple-choice template.",
        difficulty=difficulty,
        num_distractors=3,
    )
    return build_math_candidate(request, ir_proposal(template))
