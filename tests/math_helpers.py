"""Shared valid math-domain fixtures for unit and workflow tests."""

from edcraft_validator.domains.math.candidate_builder import build_math_candidate
from edcraft_validator.domains.math.math_schemas import (
    MathTemplateRequest,
    MathValidationSummary,
)


def checked_summary(report, evidence):
    """Build a saved math summary from a harness report's sampled coverage."""
    payload = report.model_dump(exclude={"report"}) | {"evidence": evidence}
    return MathValidationSummary.model_validate(payload)


# --- Generic IR template fixtures -------------------------------------------
#
# These fixtures exercise the generic authoring path. They are deliberately
# small finite families so tests can enumerate every combination deterministically.


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
        Relation,
        SymbolSpec,
        TextSpec,
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
    )
    return ir_template(
        "school.quadratic",
        [
            ParameterSpec(name="p", values=["2", "3"]),
            ParameterSpec(name="q", values=["-7", "-5"]),
        ],
        body,
    )


def linear_ir_template():
    from edcraft_validator.domains.math.ir.schema import (
        AnswerRecipe,
        Distractor,
        Given,
        Goal,
        MathItemSpec,
        ParameterSpec,
        Relation,
        SymbolSpec,
        TextSpec,
    )

    body = MathItemSpec(
        topic="school.linear",
        symbols=[SymbolSpec(name="x", domain="real")],
        givens=[
            Given(
                id="equation",
                relation=Relation(
                    kind="eq",
                    lhs=ir_add(ir_mul(ir_param("a"), ir_sym("x")), ir_param("b")),
                    rhs=ir_param("c"),
                ),
            )
        ],
        goal=Goal(kind="solve", symbol="x", domain="real"),
        answer_recipe=AnswerRecipe(
            kind="set",
            items=[ir_div(ir_sub(ir_param("c"), ir_param("b")), ir_param("a"))],
        ),
        distractors=[
            Distractor(
                value=ir_div(ir_sub(ir_param("b"), ir_param("c")), ir_param("a")),
                misconception="SIGN_ERROR",
                reason="Negates the numerator",
            ),
            Distractor(
                value=ir_sub(ir_param("c"), ir_param("b")),
                misconception="NO_DIVISION",
                reason="Omits dividing by a",
            ),
            Distractor(
                value=ir_div(ir_add(ir_param("c"), ir_param("b")), ir_param("a")),
                misconception="ADD_NOT_SUBTRACT",
                reason="Adds b instead of subtracting",
            ),
        ],
        text=TextSpec(mode="symbolic", template="Solve {equation} for x."),
    )
    return ir_template(
        "school.linear",
        [
            ParameterSpec(name="a", values=["2", "3", "5"]),
            ParameterSpec(name="b", values=["1", "4"]),
            ParameterSpec(name="c", values=["7", "10"]),
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
        Relation,
        SymbolSpec,
        TextSpec,
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
        SymbolSpec,
        TextSpec,
    )

    # The engine grades only exact real exponents, so the fixture fixes the
    # exponents and varies only the coefficients.
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
        SymbolSpec,
        TextSpec,
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
        SymbolSpec,
        TextSpec,
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
    )
    return ir_template(
        "school.percentage",
        [
            ParameterSpec(name="percent", values=["10", "20"]),
            ParameterSpec(name="whole", values=["50", "80"]),
        ],
        body,
    )


def arithmetic_ir_template():
    from edcraft_validator.domains.math.ir.schema import (
        AnswerRecipe,
        Distractor,
        Given,
        Goal,
        MathItemSpec,
        ParameterSpec,
        SymbolSpec,
        TextSpec,
    )

    body = MathItemSpec(
        topic="school.two_digit_addition",
        symbols=[
            SymbolSpec(name="a", kind="given", domain="integer", integer=True),
            SymbolSpec(name="b", kind="given", domain="integer", integer=True),
        ],
        givens=[
            Given(id="a_domain", kind="domain", symbol="a", domain="integer"),
            Given(id="b_domain", kind="domain", symbol="b", domain="integer"),
        ],
        goal=Goal(kind="evaluate", expr=ir_add(ir_param("a"), ir_param("b"))),
        answer_recipe=AnswerRecipe(
            kind="numeric",
            items=[ir_add(ir_param("a"), ir_param("b"))],
        ),
        distractors=[
            Distractor(
                value=ir_add(ir_param("a"), ir_param("b"), ir_num(1)),
                misconception="OFF_BY_ONE",
                reason="Adds one extra unit",
            ),
            Distractor(
                value=ir_sub(ir_add(ir_param("a"), ir_param("b")), ir_num(1)),
                misconception="OFF_BY_ONE",
                reason="Loses one unit",
            ),
            Distractor(
                value=ir_add(ir_param("a"), ir_param("b"), ir_num(10)),
                misconception="PLACE_VALUE_ERROR",
                reason="Misaligns the tens column",
            ),
        ],
        text=TextSpec(mode="symbolic", template="What is {expr}?"),
    )
    return ir_template(
        "school.two_digit_addition",
        [
            ParameterSpec(name="a", values=["12", "23"]),
            ParameterSpec(name="b", values=["14", "18"]),
        ],
        body,
    )


def factor_ir_template(*, factored_answer=True):
    """Factor x^2 + (p+q)x + pq; the answer is factored or left expanded."""
    from edcraft_validator.domains.math.ir.schema import (
        AnswerRecipe,
        Distractor,
        Given,
        Goal,
        MathItemSpec,
        ParameterSpec,
        SymbolSpec,
        TextSpec,
    )

    x, p, q = ir_sym("x"), ir_param("p"), ir_param("q")
    expanded = ir_add(ir_pow(x, ir_num(2)), ir_mul(ir_add(p, q), x), ir_mul(p, q))

    def product(left, right):
        return ir_mul(left, right)

    answer = product(ir_add(x, p), ir_add(x, q)) if factored_answer else expanded

    body = MathItemSpec(
        topic="school.factor",
        symbols=[SymbolSpec(name="x", domain="real")],
        givens=[Given(id="g1", kind="domain", symbol="x", domain="real")],
        goal=Goal(kind="factor", expr=expanded),
        answer_recipe=AnswerRecipe(kind="expression", items=[answer]),
        distractors=[
            Distractor(
                value=product(ir_sub(x, p), ir_sub(x, q)), misconception="SIGNS"
            ),
            Distractor(
                value=product(ir_add(x, p), ir_sub(x, q)), misconception="ONE_SIGN"
            ),
            Distractor(
                value=product(ir_sub(x, p), ir_add(x, q)), misconception="OTHER_SIGN"
            ),
        ],
        text=TextSpec(mode="symbolic", template="Factor {expr}."),
    )
    return ir_template(
        "school.factor",
        [
            ParameterSpec(name="p", values=["2", "3"]),
            ParameterSpec(name="q", values=["5", "7"]),
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


class MathTemplateJudge:
    """Decision-capable fake judge, so the shared cascade stays model-free."""

    provider, model = "scripted", "math-template-judge"

    def generation_settings(self):
        return {"sampling": "scripted", "max_retries": 0}

    def decide(self, messages, labels):
        from edcraft_validator.llm.forced_decision import ClassDecision
        from edcraft_validator.llm.usage import TokenUsage

        self.last_usage = TokenUsage(input_tokens=10, output_tokens=1)
        return ClassDecision(
            label="easy",
            confidence=1.0,
            distribution={"easy": 1.0, "medium": 0.0, "hard": 0.0},
            served_model="served",
        )

    def generate(self, request):
        raise AssertionError("a confident decision must not request reasoning")
