"""Build the frozen mathematics difficulty reference set.

The script constructs each template in code, runs the production maths checks,
renders the seed-0 instance with the production generator and writes the dataset
plus a human review sheet. It never overwrites owner ratings that are already
filled in.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from edcraft_validator.domains.math.fidelity import math_fidelity_plugin
from edcraft_validator.domains.math.ir.schema import (
    AnswerRecipe,
    Distractor,
    Expr,
    Given,
    Goal,
    MathItemSpec,
    MathTemplateSpec,
    ParameterSpec,
    Relation,
    SymbolSpec,
    TextSpec,
)
from edcraft_validator.domains.math.math_schemas import (
    MathTemplateCandidate,
    ValidatedMathTemplate,
)
from edcraft_validator.domains.math.math_types import FORM_SENSITIVE_GOALS
from edcraft_validator.domains.math.question_generator import generate_math_question
from edcraft_validator.domains.math.validation.harness import validate_template
from edcraft_validator.validation.validation_contracts import ValidationEvidence

ROOT = Path(__file__).resolve().parents[1]
DATASET_DIR = ROOT / "reference_sets" / "math_templates"
DATASET_PATH = DATASET_DIR / "dataset.json"
REVIEW_PATH = DATASET_DIR / "review-sheet.md"
RUBRIC_VERSION = "math-ir-v0.1"
ASSESSMENT_CONDITIONS = (
    "Untimed paper practice without calculator, computer algebra system or AI "
    "assistant, with the relevant mathematical prerequisites understood. Difficulty is "
    "assessed on the typical concrete expansion of the declared parameter family."
)


def num(value: int | str) -> Expr:
    return Expr(num=str(value))


def sym(name: str) -> Expr:
    return Expr(sym=name)


def param(name: str) -> Expr:
    return Expr(param=name)


def add(*args: Expr) -> Expr:
    return Expr(op="add", args=list(args))


def mul(*args: Expr) -> Expr:
    return Expr(op="mul", args=list(args))


def sub(left: Expr, right: Expr) -> Expr:
    return Expr(op="sub", args=[left, right])


def div(left: Expr, right: Expr) -> Expr:
    return Expr(op="div", args=[left, right])


def pow_(left: Expr, right: Expr) -> Expr:
    return Expr(op="pow", args=[left, right])


def sqrt(value: Expr) -> Expr:
    return Expr(op="sqrt", args=[value])


def exp(value: Expr) -> Expr:
    return Expr(op="exp", args=[value])


def sin(value: Expr) -> Expr:
    return Expr(op="sin", args=[value])


def cos(value: Expr) -> Expr:
    return Expr(op="cos", args=[value])


def log(value: Expr) -> Expr:
    return Expr(op="log", args=[value])


def abs_(value: Expr) -> Expr:
    return Expr(op="abs", args=[value])


def neg(value: Expr) -> Expr:
    return mul(num(-1), value)


def domain_givens(*names: str) -> list[Given]:
    return [
        Given(id=f"domain_{name}", kind="domain", symbol=name, domain="real")
        for name in names
    ]


def prose(text: str) -> TextSpec:
    """Build a prose spec and anchor every literal number in the template."""
    anchors: dict[str, tuple[int, int]] = {}
    import re

    placeholder = re.compile(r"\{[^{}]*\}")
    literal = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")
    spans = [(m.start(), m.end()) for m in placeholder.finditer(text)]
    for match in literal.finditer(text):
        if any(start <= match.start() < end for start, end in spans):
            continue
        key = match.group(0)
        if key in anchors:
            raise ValueError(f"prose text repeats the numeric literal {key!r}")
        anchors[key] = (match.start(), match.end())
    return TextSpec(mode="prose", template=text, anchors=anchors)


def symbolic(text: str) -> TextSpec:
    return TextSpec(mode="symbolic", template=text)


@dataclass(frozen=True)
class Item:
    family: str
    number: int
    goal_kind: str
    split: str
    level: str
    dimensions: dict[str, str]
    reason: str
    template: MathTemplateSpec

    @property
    def question_id(self) -> str:
        return f"{self.family}-{self.number:02d}"


def item(
    *,
    family: str,
    number: int,
    goal_kind: str,
    split: str,
    level: str,
    template: MathTemplateSpec,
    dimensions: dict[str, str],
    reason: str,
) -> Item:
    return Item(
        family=family,
        number=number,
        goal_kind=goal_kind,
        split=split,
        level=level,
        dimensions=dimensions,
        reason=reason,
        template=template,
    )


def template(topic: str, parameters: list[ParameterSpec], body: MathItemSpec):
    return MathTemplateSpec(topic=topic, parameters=parameters, body=body)


def body(
    *,
    topic: str,
    symbols: list[SymbolSpec],
    givens: list[Given],
    goal: Goal,
    recipe: AnswerRecipe,
    distractors: list[Distractor],
    text: TextSpec,
) -> MathItemSpec:
    return MathItemSpec(
        topic=topic,
        symbols=symbols,
        givens=givens,
        goal=goal,
        answer_recipe=recipe,
        distractors=distractors,
        text=text,
    )


def x_symbol() -> SymbolSpec:
    return SymbolSpec(name="x", domain="real")


def y_symbol() -> SymbolSpec:
    return SymbolSpec(name="y", domain="real")


def answer_expression(expr: Expr) -> AnswerRecipe:
    return AnswerRecipe(kind="expression", items=[expr])


def answer_numeric(expr: Expr) -> AnswerRecipe:
    return AnswerRecipe(kind="numeric", items=[expr])


def answer_set(*items: Expr) -> AnswerRecipe:
    return AnswerRecipe(kind="set", items=list(items))


def answer_tuple(*items: Expr) -> AnswerRecipe:
    return AnswerRecipe(kind="tuple", items=list(items))


def distractor(value: Expr, misconception: str, reason: str) -> Distractor:
    return Distractor(value=value, misconception=misconception, reason=reason)


def distractor_set(items: list[Expr], misconception: str, reason: str) -> Distractor:
    return Distractor(items=items, misconception=misconception, reason=reason)


def distractor_tuple(
    components: list[Expr], misconception: str, reason: str
) -> Distractor:
    return Distractor(components=components, misconception=misconception, reason=reason)


def arithmetic_items() -> list[Item]:
    family = "arithmetic-evaluate"
    topic = "school.arithmetic"
    split = "development"

    easy = template(
        topic,
        [
            ParameterSpec(name="a", values=["12", "23"]),
            ParameterSpec(name="b", values=["14", "18"]),
        ],
        body(
            topic=topic,
            symbols=[SymbolSpec(name="x", kind="given", domain="real")],
            givens=domain_givens("x"),
            goal=Goal(kind="evaluate", expr=add(param("a"), param("b"))),
            recipe=answer_numeric(add(param("a"), param("b"))),
            distractors=[
                distractor(
                    add(param("a"), param("b"), num(1)),
                    "OFF_BY_ONE",
                    "Adds one extra unit",
                ),
                distractor(
                    sub(add(param("a"), param("b")), num(1)),
                    "OFF_BY_ONE",
                    "Loses one unit",
                ),
                distractor(
                    add(param("a"), param("b"), num(10)),
                    "PLACE_VALUE",
                    "Misaligns the tens column",
                ),
            ],
            text=symbolic("What is {expr}?"),
        ),
    )

    medium = template(
        topic,
        [
            ParameterSpec(name="a", values=["2", "3"]),
            ParameterSpec(name="b", values=["4", "5"]),
            ParameterSpec(name="c", values=["1", "2"]),
        ],
        body(
            topic=topic,
            symbols=[SymbolSpec(name="x", kind="given", domain="real")],
            givens=domain_givens("x"),
            goal=Goal(
                kind="evaluate", expr=add(mul(param("a"), param("b")), param("c"))
            ),
            recipe=answer_numeric(add(mul(param("a"), param("b")), param("c"))),
            distractors=[
                distractor(
                    mul(param("a"), add(param("b"), param("c"))),
                    "IGNORES_PRECEDENCE",
                    "Adds before multiplying",
                ),
                distractor(
                    mul(param("a"), param("b")),
                    "DROPS_TERM",
                    "Drops the added constant",
                ),
                distractor(
                    sub(mul(param("a"), param("b")), param("c")),
                    "SUBTRACTS_TERM",
                    "Subtracts the constant instead of adding",
                ),
            ],
            text=symbolic("What is {expr}?"),
        ),
    )

    hard = template(
        topic,
        [
            ParameterSpec(name="a", values=["1", "3"]),
            ParameterSpec(name="b", values=["2", "4"]),
            ParameterSpec(name="c", values=["1", "2"]),
            ParameterSpec(name="d", values=["3", "4"]),
        ],
        body(
            topic=topic,
            symbols=[SymbolSpec(name="x", kind="given", domain="real")],
            givens=domain_givens("x"),
            goal=Goal(
                kind="evaluate",
                expr=add(div(param("a"), param("b")), div(param("c"), param("d"))),
            ),
            recipe=answer_numeric(
                add(div(param("a"), param("b")), div(param("c"), param("d")))
            ),
            distractors=[
                distractor(
                    div(add(param("a"), param("c")), add(param("b"), param("d"))),
                    "ADDS_ACROSS",
                    "Adds numerators and denominators",
                ),
                distractor(
                    div(add(param("a"), param("c")), mul(param("b"), param("d"))),
                    "COMMON_DENOMINATOR_ONLY",
                    "Uses a common denominator but adds wrongly",
                ),
                distractor(
                    add(div(param("a"), param("b")), div(param("d"), param("c"))),
                    "RECIPROCAL",
                    "Reciprocates the second fraction",
                ),
            ],
            text=symbolic("What is {expr}?"),
        ),
    )

    return [
        item(
            family=family,
            number=1,
            goal_kind="evaluate",
            split=split,
            level="easy",
            template=easy,
            dimensions={
                "procedure_length": "low",
                "operation_type": "low",
                "conceptual_demand": "low",
                "answer_discrimination": "low",
            },
            reason="Nearest anchor is the easy linear equation. The procedure is one "
            "addition, the operation family is basic arithmetic and every distractor "
            "fails a quick magnitude or place-value check, so the structural demand "
            "stays low.",
        ),
        item(
            family=family,
            number=2,
            goal_kind="evaluate",
            split=split,
            level="medium",
            template=medium,
            dimensions={
                "procedure_length": "moderate",
                "operation_type": "low",
                "conceptual_demand": "moderate",
                "answer_discrimination": "moderate",
            },
            reason="Nearest anchor is the easy linear equation, extended by one "
            "precedence decision. The learner must multiply before adding, and the "
            "distractor that adds first needs the order-of-operations rule to "
            "eliminate, which makes the sequence rather than the number size the "
            "deciding feature.",
        ),
        item(
            family=family,
            number=3,
            goal_kind="evaluate",
            split=split,
            level="hard",
            template=hard,
            dimensions={
                "procedure_length": "high",
                "operation_type": "moderate",
                "conceptual_demand": "high",
                "answer_discrimination": "high",
            },
            reason="Nearest anchor is the medium quadratic expansion, because the work "
            "turns on combining rational terms. The learner must form a common "
            "denominator and then add numerators, and the plausible options each break "
            "a different fraction rule rather than differing by magnitude.",
        ),
    ]


def percentage_items() -> list[Item]:
    family = "percentage-change"
    topic = "school.percentage"
    split = "development"

    easy = template(
        topic,
        [
            ParameterSpec(name="percent", values=["10", "20"]),
            ParameterSpec(name="whole", values=["50", "80"]),
        ],
        body(
            topic=topic,
            symbols=[SymbolSpec(name="x", kind="given", domain="real")],
            givens=domain_givens("x"),
            goal=Goal(
                kind="evaluate",
                expr=div(mul(param("percent"), param("whole")), num(100)),
            ),
            recipe=answer_numeric(div(mul(param("percent"), param("whole")), num(100))),
            distractors=[
                distractor(
                    mul(param("percent"), param("whole")),
                    "MISSING_DIVISION",
                    "Forgets to divide by 100",
                ),
                distractor(
                    add(param("whole"), param("percent")),
                    "ADDED_INSTEAD",
                    "Adds the percentage to the whole",
                ),
                distractor(
                    sub(param("whole"), param("percent")),
                    "SUBTRACTED_INSTEAD",
                    "Subtracts the percentage from the whole",
                ),
            ],
            text=symbolic("Find {percent}% of {whole}."),
        ),
    )

    medium = template(
        topic,
        [ParameterSpec(name="percent", values=["20", "40", "60"])],
        body(
            topic=topic,
            symbols=[SymbolSpec(name="x", kind="given", domain="real")],
            givens=domain_givens("x"),
            goal=Goal(
                kind="evaluate", expr=div(mul(param("percent"), num(500)), num(100))
            ),
            recipe=answer_numeric(div(mul(param("percent"), num(500)), num(100))),
            distractors=[
                distractor(
                    sub(num(500), param("percent")),
                    "SUBTRACTS_PERCENT",
                    "Treats the percentage as a quantity",
                ),
                distractor(
                    mul(param("percent"), num(500)),
                    "MISSING_DIVISION",
                    "Forgets to divide by 100",
                ),
                distractor(
                    add(num(500), param("percent")),
                    "ADDS_PERCENT",
                    "Adds the percentage to the volume",
                ),
            ],
            text=prose(
                "A 500 ml bottle is {percent}% full. How many millilitres does it "
                "contain?"
            ),
        ),
    )

    hard = template(
        topic,
        [
            ParameterSpec(name="percent", values=["10", "20"]),
            ParameterSpec(name="sale", values=["45", "72"]),
        ],
        body(
            topic=topic,
            symbols=[SymbolSpec(name="x", kind="given", domain="real")],
            givens=domain_givens("x"),
            goal=Goal(
                kind="evaluate",
                expr=div(mul(param("sale"), num(100)), sub(num(100), param("percent"))),
            ),
            recipe=answer_numeric(
                div(mul(param("sale"), num(100)), sub(num(100), param("percent")))
            ),
            distractors=[
                distractor(
                    div(mul(param("sale"), num(100)), add(num(100), param("percent"))),
                    "SIGN_ERROR",
                    "Adds the discount in the denominator",
                ),
                distractor(
                    div(mul(param("sale"), param("percent")), num(100)),
                    "REPORTS_DISCOUNT",
                    "Reports the discount amount",
                ),
                distractor(
                    div(mul(param("sale"), sub(num(100), param("percent"))), num(100)),
                    "REAPPLIES_DISCOUNT",
                    "Applies the discount a second time",
                ),
            ],
            text=prose(
                "After a {percent}% discount a jacket costs {sale} pounds. What was "
                "the price before the discount?"
            ),
        ),
    )

    return [
        item(
            family=family,
            number=1,
            goal_kind="evaluate",
            split=split,
            level="easy",
            template=easy,
            dimensions={
                "procedure_length": "low",
                "operation_type": "low",
                "conceptual_demand": "low",
                "answer_discrimination": "low",
            },
            reason="Nearest anchor is the easy linear equation. The procedure is one "
            "multiplication followed by a standard division by 100, and the wrong "
            "options are removed by a magnitude cue or by noticing that a percentage "
            "of a whole must be smaller than the whole.",
        ),
        item(
            family=family,
            number=2,
            goal_kind="evaluate",
            split=split,
            level="medium",
            template=medium,
            dimensions={
                "procedure_length": "moderate",
                "operation_type": "low",
                "conceptual_demand": "moderate",
                "answer_discrimination": "moderate",
            },
            reason="Nearest anchor is the easy linear equation, with one added "
            "modelling step. The learner has to read the volume as the whole and the "
            "percentage as a rate, then multiply and divide, so the connection between "
            "the prose quantity and the operation decides the level rather than the "
            "size of 500.",
        ),
        item(
            family=family,
            number=3,
            goal_kind="evaluate",
            split=split,
            level="hard",
            template=hard,
            dimensions={
                "procedure_length": "high",
                "operation_type": "moderate",
                "conceptual_demand": "high",
                "answer_discrimination": "high",
            },
            reason="Nearest anchor is the medium quadratic expansion, because the "
            "solution reverses a percentage change rather than applying one. The "
            "learner must identify the sale price as the reduced amount and divide by "
            "the remaining fraction, and each plausible option uses a different wrong "
            "inverse, so a full setup is needed to choose.",
        ),
    ]


def powers_roots_items() -> list[Item]:
    family = "powers-roots"
    topic = "school.powers"
    split = "development"

    easy = template(
        topic,
        [
            ParameterSpec(name="a", values=["3", "5"]),
            ParameterSpec(name="b", values=["4", "7"]),
        ],
        body(
            topic=topic,
            symbols=[SymbolSpec(name="x", kind="given", domain="real")],
            givens=domain_givens("x"),
            goal=Goal(kind="evaluate", expr=add(pow_(param("a"), num(2)), param("b"))),
            recipe=answer_numeric(add(pow_(param("a"), num(2)), param("b"))),
            distractors=[
                distractor(
                    add(mul(param("a"), num(2)), param("b")),
                    "MULTIPLIES_BY_TWO",
                    "Doubles the base instead of squaring",
                ),
                distractor(
                    pow_(param("a"), num(2)), "DROPS_TERM", "Drops the added constant"
                ),
                distractor(
                    add(param("a"), param("b")),
                    "ADDS_BASE",
                    "Adds the base before squaring",
                ),
            ],
            text=symbolic("Evaluate {expr}."),
        ),
    )

    medium = template(
        topic,
        [
            ParameterSpec(name="a", values=["3", "6"]),
            ParameterSpec(name="b", values=["4", "8"]),
        ],
        body(
            topic=topic,
            symbols=[SymbolSpec(name="x", kind="given", domain="real")],
            givens=domain_givens("x"),
            goal=Goal(
                kind="evaluate",
                expr=sqrt(add(pow_(param("a"), num(2)), pow_(param("b"), num(2)))),
            ),
            recipe=answer_numeric(
                sqrt(add(pow_(param("a"), num(2)), pow_(param("b"), num(2))))
            ),
            distractors=[
                distractor(
                    add(param("a"), param("b")), "ADDS_LEGS", "Adds the two legs"
                ),
                distractor(
                    mul(param("a"), param("b")),
                    "MULTIPLIES_LEGS",
                    "Multiplies the two legs",
                ),
                distractor(
                    div(add(param("a"), param("b")), num(2)),
                    "AVERAGES_LEGS",
                    "Averages the two legs",
                ),
            ],
            text=prose(
                "A right triangle has legs {a} and {b}. How long is the hypotenuse?"
            ),
        ),
    )

    hard = template(
        topic,
        [ParameterSpec(name="a", values=["16", "25"])],
        body(
            topic=topic,
            symbols=[SymbolSpec(name="x", kind="given", domain="real")],
            givens=domain_givens("x"),
            goal=Goal(kind="evaluate", expr=pow_(param("a"), num("3/2"))),
            recipe=answer_numeric(pow_(param("a"), num("3/2"))),
            distractors=[
                distractor(
                    div(pow_(param("a"), num(3)), num(2)),
                    "DIVIDES_AFTER_POWER",
                    "Cubes then halves",
                ),
                distractor(
                    pow_(param("a"), num(2)),
                    "WRONG_EXPONENT",
                    "Squares instead of using three halves",
                ),
                distractor(
                    sqrt(param("a")), "STOPS_AT_ROOT", "Takes only the square root"
                ),
            ],
            text=symbolic("Evaluate {expr}."),
        ),
    )

    return [
        item(
            family=family,
            number=1,
            goal_kind="evaluate",
            split=split,
            level="easy",
            template=easy,
            dimensions={
                "procedure_length": "low",
                "operation_type": "low",
                "conceptual_demand": "low",
                "answer_discrimination": "low",
            },
            reason="Nearest anchor is the easy linear equation. The procedure applies "
            "one power and one addition, and the options separate immediately once the "
            "square is evaluated, so the demand is routine recall and arithmetic.",
        ),
        item(
            family=family,
            number=2,
            goal_kind="evaluate",
            split=split,
            level="medium",
            template=medium,
            dimensions={
                "procedure_length": "moderate",
                "operation_type": "moderate",
                "conceptual_demand": "moderate",
                "answer_discrimination": "moderate",
            },
            reason="Nearest anchor is the easy linear equation, with a geometric "
            "connection added. The learner must recognise the hypotenuse relation, "
            "square both legs, add and take the root, and the distractors are "
            "eliminated by the one specific rule that the hypotenuse is the root of a "
            "sum of squares.",
        ),
        item(
            family=family,
            number=3,
            goal_kind="evaluate",
            split=split,
            level="hard",
            template=hard,
            dimensions={
                "procedure_length": "moderate",
                "operation_type": "moderate",
                "conceptual_demand": "high",
                "answer_discrimination": "high",
            },
            reason="Nearest anchor is the medium quadratic expansion, because a "
            "fractional exponent must be read as a power and a root. The work is short "
            "in steps but requires choosing the right decomposition, and each option "
            "comes from a different misreading of three halves, so several rules are "
            "needed to settle the answer.",
        ),
    ]


def proportion_items() -> list[Item]:
    family = "proportion-problem"
    topic = "school.proportion"
    split = "development"

    easy = template(
        topic,
        [ParameterSpec(name="eggs", values=["2", "3"])],
        body(
            topic=topic,
            symbols=[SymbolSpec(name="x", kind="given", domain="real")],
            givens=domain_givens("x"),
            goal=Goal(kind="evaluate", expr=mul(param("eggs"), num(3))),
            recipe=answer_numeric(mul(param("eggs"), num(3))),
            distractors=[
                distractor(add(param("eggs"), num(1)), "ADDS_ONE", "Adds one egg"),
                distractor(
                    mul(param("eggs"), num(36)),
                    "MULTIPLIES_BY_TOTAL",
                    "Multiplies by the pancake total",
                ),
                distractor(
                    mul(param("eggs"), num(2)), "WRONG_SCALE", "Uses a scale of two"
                ),
            ],
            text=prose(
                "A recipe uses {eggs} eggs for every 12 pancakes. How many eggs are "
                "needed for 36 pancakes?"
            ),
        ),
    )

    medium = template(
        topic,
        [ParameterSpec(name="hours", values=["2", "3", "4"])],
        body(
            topic=topic,
            symbols=[SymbolSpec(name="x", kind="given", domain="real")],
            givens=domain_givens("x"),
            goal=Goal(kind="evaluate", expr=div(mul(num(60), num(5)), param("hours"))),
            recipe=answer_numeric(div(mul(num(60), num(5)), param("hours"))),
            distractors=[
                distractor(
                    mul(num(60), param("hours")),
                    "MULTIPLIES_HOURS",
                    "Multiplies by the given hours",
                ),
                distractor(
                    add(num(60), num(5)),
                    "ADDS_QUANTITIES",
                    "Adds the distance and the time",
                ),
                distractor(
                    mul(mul(num(60), num(5)), param("hours")),
                    "COMPOUNDS_RATE",
                    "Multiplies by the hours twice",
                ),
            ],
            text=prose(
                "A car travels 60 miles in {hours} hours. How far does it travel in 5 "
                "hours at the same speed?"
            ),
        ),
    )

    hard = template(
        topic,
        [ParameterSpec(name="minutes", values=["120", "240"])],
        body(
            topic=topic,
            symbols=[SymbolSpec(name="x", kind="given", domain="real")],
            givens=domain_givens("x"),
            goal=Goal(
                kind="evaluate",
                expr=div(num(240), add(div(num(240), param("minutes")), num(3))),
            ),
            recipe=answer_numeric(
                div(num(240), add(div(num(240), param("minutes")), num(3)))
            ),
            distractors=[
                distractor(
                    add(param("minutes"), num(80)),
                    "ADDS_TIMES",
                    "Adds the two filling times",
                ),
                distractor(
                    div(add(param("minutes"), num(80)), num(2)),
                    "AVERAGES_TIMES",
                    "Averages the two filling times",
                ),
                distractor(
                    div(param("minutes"), num(2)),
                    "HALVES_TIME",
                    "Halves the slower tap's time",
                ),
            ],
            text=prose(
                "A tap fills a 240 litre tank in {minutes} minutes. A second tap fills "
                "it in 80 minutes. How long do both taps take together?"
            ),
        ),
    )

    return [
        item(
            family=family,
            number=1,
            goal_kind="evaluate",
            split=split,
            level="easy",
            template=easy,
            dimensions={
                "procedure_length": "low",
                "operation_type": "low",
                "conceptual_demand": "low",
                "answer_discrimination": "low",
            },
            reason="Nearest anchor is the easy linear equation. The scale factor is a "
            "single comparison between the two pancake totals, and the distractors are "
            "rejected by a quick check on whether the answer should be a multiple of "
            "the given number of eggs.",
        ),
        item(
            family=family,
            number=2,
            goal_kind="evaluate",
            split=split,
            level="medium",
            template=medium,
            dimensions={
                "procedure_length": "moderate",
                "operation_type": "moderate",
                "conceptual_demand": "moderate",
                "answer_discrimination": "moderate",
            },
            reason="Nearest anchor is the easy linear equation, extended by a "
            "unit-rate step. The learner must first find the distance per hour and "
            "then scale it to the new time, and the options are eliminated by the "
            "specific rule that distance grows with time at a fixed speed.",
        ),
        item(
            family=family,
            number=3,
            goal_kind="evaluate",
            split=split,
            level="hard",
            template=hard,
            dimensions={
                "procedure_length": "high",
                "operation_type": "moderate",
                "conceptual_demand": "high",
                "answer_discrimination": "high",
            },
            reason="Nearest anchor is the medium quadratic expansion, because the "
            "problem combines two rates instead of scaling one. The learner must add "
            "the filling rates and invert the total, and the plausible options come "
            "from adding, averaging or halving times, so a full rate model is needed "
            "to choose.",
        ),
    ]


def function_evaluation_items() -> list[Item]:
    family = "function-evaluation"
    topic = "school.function"
    split = "development"

    easy = template(
        topic,
        [ParameterSpec(name="a", values=["4", "5"])],
        body(
            topic=topic,
            symbols=[SymbolSpec(name="x", kind="given", domain="real")],
            givens=domain_givens("x"),
            goal=Goal(kind="evaluate", expr=add(mul(num(2), param("a")), num(3))),
            recipe=answer_numeric(add(mul(num(2), param("a")), num(3))),
            distractors=[
                distractor(
                    sub(mul(num(2), param("a")), num(3)),
                    "SIGN_ERROR",
                    "Subtracts the constant",
                ),
                distractor(
                    add(param("a"), num(3)), "DROPS_FACTOR", "Omits the coefficient two"
                ),
                distractor(
                    add(mul(num(2), param("a")), num(5)),
                    "WRONG_CONSTANT",
                    "Adds five instead of three",
                ),
            ],
            text=prose("If f(x) = 2x + 3, find f({a})."),
        ),
    )

    medium = template(
        topic,
        [ParameterSpec(name="a", values=["2", "4"])],
        body(
            topic=topic,
            symbols=[SymbolSpec(name="x", kind="given", domain="real")],
            givens=domain_givens("x"),
            goal=Goal(
                kind="evaluate",
                expr=add(pow_(param("a"), num(2)), mul(num(-3), param("a")), num(1)),
            ),
            recipe=answer_numeric(
                add(pow_(param("a"), num(2)), mul(num(-3), param("a")), num(1))
            ),
            distractors=[
                distractor(
                    add(pow_(param("a"), num(2)), mul(num(3), param("a")), num(1)),
                    "SIGN_ERROR",
                    "Adds the linear term",
                ),
                distractor(
                    sub(pow_(param("a"), num(2)), mul(num(3), param("a"))),
                    "DROPS_CONSTANT",
                    "Drops the constant",
                ),
                distractor(
                    add(pow_(param("a"), num(2)), num(1)),
                    "DROPS_LINEAR",
                    "Drops the linear term",
                ),
            ],
            text=prose("If f(x) = x^2 - 3x + 1, find f({a})."),
        ),
    )

    hard = template(
        topic,
        [
            ParameterSpec(name="a", values=["1", "2"]),
            ParameterSpec(name="b", values=["4", "5"]),
        ],
        body(
            topic=topic,
            symbols=[SymbolSpec(name="x", kind="given", domain="real")],
            givens=domain_givens("x"),
            goal=Goal(
                kind="evaluate",
                expr=div(
                    sub(pow_(param("b"), num(2)), pow_(param("a"), num(2))),
                    sub(param("b"), param("a")),
                ),
            ),
            recipe=answer_numeric(add(param("a"), param("b"))),
            distractors=[
                distractor(
                    sub(param("b"), param("a")),
                    "SIGN_ERROR",
                    "Subtracts instead of adding",
                ),
                distractor(
                    mul(param("a"), param("b")),
                    "MULTIPLIES",
                    "Multiplies the two values",
                ),
                distractor(
                    sub(pow_(param("b"), num(2)), pow_(param("a"), num(2))),
                    "NO_CANCELLATION",
                    "Leaves the difference of squares",
                ),
            ],
            text=prose(
                "Evaluate (x squared minus {a} squared) divided by (x minus {a}) when "
                "x = {b}."
            ),
        ),
    )

    return [
        item(
            family=family,
            number=1,
            goal_kind="evaluate",
            split=split,
            level="easy",
            template=easy,
            dimensions={
                "procedure_length": "low",
                "operation_type": "low",
                "conceptual_demand": "low",
                "answer_discrimination": "low",
            },
            reason="Nearest anchor is the easy linear equation. Substituting one value "
            "into a linear rule is a single routine step, and the wrong options are "
            "removed by checking one coefficient or the constant.",
        ),
        item(
            family=family,
            number=2,
            goal_kind="evaluate",
            split=split,
            level="medium",
            template=medium,
            dimensions={
                "procedure_length": "moderate",
                "operation_type": "moderate",
                "conceptual_demand": "moderate",
                "answer_discrimination": "moderate",
            },
            reason="Nearest anchor is the easy linear equation, extended by a "
            "quadratic substitution. The learner must square the input and keep the "
            "signs of both terms, and each option breaks one specific substitution "
            "rule, so the connection rather than the value decides.",
        ),
        item(
            family=family,
            number=3,
            goal_kind="evaluate",
            split=split,
            level="hard",
            template=hard,
            dimensions={
                "procedure_length": "moderate",
                "operation_type": "moderate",
                "conceptual_demand": "high",
                "answer_discrimination": "high",
            },
            reason="Nearest anchor is the hard product derivative, because the item "
            "hides a cancellation that must be recognised before substitution. The "
            "learner has to see the difference of squares, simplify the rule and then "
            "evaluate, and the plausible options come from skipping the cancellation "
            "or mishandling the signs.",
        ),
    ]


def linear_equation_items() -> list[Item]:
    family = "linear-equation"
    topic = "school.linear"
    split = "development"

    easy = template(
        topic,
        [
            ParameterSpec(name="a", values=["2", "3"]),
            ParameterSpec(name="b", values=["6", "12"]),
        ],
        body(
            topic=topic,
            symbols=[x_symbol()],
            givens=[
                Given(
                    id="equation",
                    relation=Relation(
                        kind="eq", lhs=mul(param("a"), sym("x")), rhs=param("b")
                    ),
                )
            ],
            goal=Goal(kind="solve", symbol="x", domain="real"),
            recipe=answer_set(div(param("b"), param("a"))),
            distractors=[
                distractor_set(
                    [mul(param("b"), param("a"))],
                    "MULTIPLIES",
                    "Multiplies instead of dividing",
                ),
                distractor_set(
                    [div(neg(param("b")), param("a"))],
                    "SIGN_ERROR",
                    "Negates the solution",
                ),
                distractor_set(
                    [sub(param("b"), param("a"))],
                    "SUBTRACTS",
                    "Subtracts the coefficient",
                ),
            ],
            text=symbolic("Solve {equation}."),
        ),
    )

    medium = template(
        topic,
        [
            ParameterSpec(name="a", values=["2", "3"]),
            ParameterSpec(name="b", values=["1", "2"]),
            ParameterSpec(name="c", values=["7", "11"]),
        ],
        body(
            topic=topic,
            symbols=[x_symbol()],
            givens=[
                Given(
                    id="equation",
                    relation=Relation(
                        kind="eq",
                        lhs=add(mul(param("a"), sym("x")), param("b")),
                        rhs=param("c"),
                    ),
                )
            ],
            goal=Goal(kind="solve", symbol="x", domain="real"),
            recipe=answer_set(div(sub(param("c"), param("b")), param("a"))),
            distractors=[
                distractor_set(
                    [div(sub(param("b"), param("c")), param("a"))],
                    "SIGN_ERROR",
                    "Negates the numerator",
                ),
                distractor_set(
                    [sub(param("c"), param("b"))],
                    "NO_DIVISION",
                    "Omits dividing by the coefficient",
                ),
                distractor_set(
                    [div(add(param("c"), param("b")), param("a"))],
                    "ADDS_CONSTANT",
                    "Adds the constant instead of subtracting",
                ),
            ],
            text=symbolic("Solve {equation} for x."),
        ),
    )

    hard = template(
        topic,
        [
            ParameterSpec(name="a", values=["3", "4"]),
            ParameterSpec(name="c", values=["1", "2"]),
            ParameterSpec(name="b", values=["1", "2"]),
            ParameterSpec(name="d", values=["5", "7"]),
        ],
        body(
            topic=topic,
            symbols=[x_symbol()],
            givens=[
                Given(
                    id="equation",
                    relation=Relation(
                        kind="eq",
                        lhs=mul(param("a"), add(sym("x"), param("b"))),
                        rhs=mul(param("c"), add(sym("x"), param("d"))),
                    ),
                )
            ],
            goal=Goal(kind="solve", symbol="x", domain="real"),
            recipe=answer_set(
                div(
                    sub(mul(param("c"), param("d")), mul(param("a"), param("b"))),
                    sub(param("a"), param("c")),
                )
            ),
            distractors=[
                distractor_set(
                    [
                        div(
                            sub(
                                mul(param("a"), param("b")), mul(param("c"), param("d"))
                            ),
                            sub(param("a"), param("c")),
                        )
                    ],
                    "SIGN_ERROR",
                    "Negates the numerator",
                ),
                distractor_set(
                    [
                        div(
                            sub(
                                mul(param("c"), param("d")), mul(param("a"), param("b"))
                            ),
                            add(param("a"), param("c")),
                        )
                    ],
                    "DENOMINATOR_SIGN",
                    "Adds the coefficients instead of subtracting",
                ),
                distractor_set(
                    [
                        div(
                            add(
                                mul(param("c"), param("d")), mul(param("a"), param("b"))
                            ),
                            sub(param("a"), param("c")),
                        )
                    ],
                    "NUMERATOR_SIGN",
                    "Adds the products instead of subtracting",
                ),
            ],
            text=symbolic("Solve {equation} for x."),
        ),
    )

    return [
        item(
            family=family,
            number=1,
            goal_kind="solve",
            split=split,
            level="easy",
            template=easy,
            dimensions={
                "procedure_length": "low",
                "operation_type": "low",
                "conceptual_demand": "low",
                "answer_discrimination": "low",
            },
            reason="This is the closest item to the easy linear equation anchor. One "
            "division isolates the unknown, and multiplying instead of dividing or "
            "negating the result fails a direct substitution check.",
        ),
        item(
            family=family,
            number=2,
            goal_kind="solve",
            split=split,
            level="medium",
            template=medium,
            dimensions={
                "procedure_length": "moderate",
                "operation_type": "moderate",
                "conceptual_demand": "moderate",
                "answer_discrimination": "moderate",
            },
            reason="Nearest anchor is the easy linear equation, extended by a two-step "
            "rearrangement. The learner must subtract the constant and then divide, "
            "and each option is eliminated by one specific inverse-operation rule, so "
            "the sequence and not the coefficient size sets the level.",
        ),
        item(
            family=family,
            number=3,
            goal_kind="solve",
            split=split,
            level="hard",
            template=hard,
            dimensions={
                "procedure_length": "high",
                "operation_type": "moderate",
                "conceptual_demand": "high",
                "answer_discrimination": "high",
            },
            reason="Nearest anchor is the medium quadratic expansion, because both "
            "sides need distributing before the unknown can be collected. The learner "
            "must expand two brackets, move all variable terms to one side and divide, "
            "and the similarly shaped options require the full rearrangement rather "
            "than a single sign check.",
        ),
    ]


def quadratic_equation_items() -> list[Item]:
    family = "quadratic-equation"
    topic = "school.quadratic"
    split = "development"

    easy = template(
        topic,
        [ParameterSpec(name="a", values=["4", "9"])],
        body(
            topic=topic,
            symbols=[x_symbol()],
            givens=[
                Given(
                    id="equation",
                    relation=Relation(
                        kind="eq", lhs=pow_(sym("x"), num(2)), rhs=param("a")
                    ),
                )
            ],
            goal=Goal(kind="solve", symbol="x", domain="real"),
            recipe=answer_set(sqrt(param("a")), neg(sqrt(param("a")))),
            distractors=[
                distractor_set(
                    [param("a")], "FORGETS_ROOT", "Reports the squared value"
                ),
                distractor_set(
                    [sqrt(param("a"))], "ONE_ROOT", "Keeps only the positive root"
                ),
                distractor_set([neg(param("a"))], "SIGNS", "Negates the squared value"),
            ],
            text=symbolic("Solve {equation} for x."),
        ),
    )

    medium = template(
        topic,
        [
            ParameterSpec(name="p", values=["2", "3"]),
            ParameterSpec(name="q", values=["4", "5"]),
        ],
        body(
            topic=topic,
            symbols=[x_symbol()],
            givens=[
                Given(
                    id="equation",
                    relation=Relation(
                        kind="eq",
                        lhs=add(
                            pow_(sym("x"), num(2)),
                            mul(neg(add(param("p"), param("q"))), sym("x")),
                            mul(param("p"), param("q")),
                        ),
                        rhs=num(0),
                    ),
                )
            ],
            goal=Goal(kind="solve", symbol="x", domain="real"),
            recipe=answer_set(param("p"), param("q")),
            distractors=[
                distractor_set(
                    [neg(param("p")), neg(param("q"))], "SIGN_ERROR", "Flips both roots"
                ),
                distractor_set(
                    [add(param("p"), param("q"))],
                    "SUM_AS_ROOT",
                    "Reports the sum of the roots",
                ),
                distractor_set(
                    [mul(param("p"), param("q"))],
                    "PRODUCT_AS_ROOT",
                    "Reports the product of the roots",
                ),
            ],
            text=symbolic("Solve {equation} for x."),
        ),
    )

    hard = template(
        topic,
        [
            ParameterSpec(name="a", values=["2", "3"]),
            ParameterSpec(name="r", values=["1", "2"]),
            ParameterSpec(name="s", values=["3", "4"]),
        ],
        body(
            topic=topic,
            symbols=[x_symbol()],
            givens=[
                Given(
                    id="equation",
                    relation=Relation(
                        kind="eq",
                        lhs=add(
                            mul(param("a"), pow_(sym("x"), num(2))),
                            mul(
                                neg(mul(param("a"), add(param("r"), param("s")))),
                                sym("x"),
                            ),
                            mul(param("a"), param("r"), param("s")),
                        ),
                        rhs=num(0),
                    ),
                )
            ],
            goal=Goal(kind="solve", symbol="x", domain="real"),
            recipe=answer_set(param("r"), param("s")),
            distractors=[
                distractor_set(
                    [neg(param("r")), neg(param("s"))], "SIGN_ERROR", "Flips both roots"
                ),
                distractor_set(
                    [add(param("r"), param("s"))],
                    "SUM_AS_ROOT",
                    "Reports the sum of the roots",
                ),
                distractor_set(
                    [mul(param("r"), param("s"))],
                    "PRODUCT_AS_ROOT",
                    "Reports the product of the roots",
                ),
            ],
            text=symbolic("Solve {equation} for x."),
        ),
    )

    return [
        item(
            family=family,
            number=1,
            goal_kind="solve",
            split=split,
            level="easy",
            template=easy,
            dimensions={
                "procedure_length": "low",
                "operation_type": "moderate",
                "conceptual_demand": "moderate",
                "answer_discrimination": "moderate",
            },
            reason="Nearest anchor is the easy linear equation, with the one "
            "connection that a square has two roots. Taking the root is routine, but "
            "the learner must remember both signs, and the options are separated by "
            "whether they keep one root, no root or the wrong sign.",
        ),
        item(
            family=family,
            number=2,
            goal_kind="solve",
            split=split,
            level="medium",
            template=medium,
            dimensions={
                "procedure_length": "moderate",
                "operation_type": "moderate",
                "conceptual_demand": "moderate",
                "answer_discrimination": "moderate",
            },
            reason="Nearest anchor is the medium quadratic expansion, run in reverse. "
            "Recognising that the constant and coefficient come from a factor pair is "
            "the one connection, and the distractors copy the sum and product rules "
            "that learners often confuse with the roots.",
        ),
        item(
            family=family,
            number=3,
            goal_kind="solve",
            split=split,
            level="hard",
            template=hard,
            dimensions={
                "procedure_length": "high",
                "operation_type": "high",
                "conceptual_demand": "high",
                "answer_discrimination": "high",
            },
            reason="Nearest anchor is the hard product derivative, because a non-monic "
            "quadratic needs a method choice between factorising and the formula. The "
            "leading coefficient makes the factor pair harder to recover, and the "
            "plausible options look like legitimate root patterns, so a full solution "
            "is needed to choose.",
        ),
    ]


def linear_system_items() -> list[Item]:
    family = "linear-system"
    topic = "school.linear_system"
    split = "held_out"

    first = template(
        topic,
        [
            ParameterSpec(name="p", values=["2", "3"]),
            ParameterSpec(name="q", values=["-1", "1"]),
        ],
        body(
            topic=topic,
            symbols=[x_symbol(), y_symbol()],
            givens=[
                Given(
                    id="eq1",
                    relation=Relation(
                        kind="eq",
                        lhs=add(sym("x"), sym("y")),
                        rhs=add(param("p"), param("q")),
                    ),
                ),
                Given(
                    id="eq2",
                    relation=Relation(
                        kind="eq",
                        lhs=sub(sym("x"), sym("y")),
                        rhs=sub(param("p"), param("q")),
                    ),
                ),
            ],
            goal=Goal(kind="solve", symbols=["x", "y"], domain="real"),
            recipe=answer_tuple(param("p"), param("q")),
            distractors=[
                distractor_tuple(
                    [param("q"), param("p")], "SWAPPED", "Swaps the two unknowns"
                ),
                distractor_tuple(
                    [param("p"), neg(param("q"))], "SIGN_ERROR", "Flips the sign of y"
                ),
                distractor_tuple(
                    [add(param("p"), param("q")), num(0)],
                    "SUM_ERROR",
                    "Adds the right-hand sides",
                ),
            ],
            text=symbolic("Solve the system {equations}."),
        ),
    )

    second = template(
        topic,
        [
            ParameterSpec(name="p", values=["1", "2"]),
            ParameterSpec(name="q", values=["-2", "-1"]),
        ],
        body(
            topic=topic,
            symbols=[x_symbol(), y_symbol()],
            givens=[
                Given(
                    id="eq1",
                    relation=Relation(
                        kind="eq",
                        lhs=add(mul(num(2), sym("x")), sym("y")),
                        rhs=add(mul(num(2), param("p")), param("q")),
                    ),
                ),
                Given(
                    id="eq2",
                    relation=Relation(
                        kind="eq",
                        lhs=add(sym("x"), mul(num(3), sym("y"))),
                        rhs=add(param("p"), mul(num(3), param("q"))),
                    ),
                ),
            ],
            goal=Goal(kind="solve", symbols=["x", "y"], domain="real"),
            recipe=answer_tuple(param("p"), param("q")),
            distractors=[
                distractor_tuple(
                    [param("p"), neg(param("q"))], "SIGN_ERROR", "Flips the sign of y"
                ),
                distractor_tuple([param("q"), param("p")], "SWAPPED", "Swaps x and y"),
                distractor_tuple(
                    [add(param("p"), param("q")), num(0)],
                    "SUM_ERROR",
                    "Adds the right-hand sides",
                ),
            ],
            text=symbolic("Solve the system {equations}."),
        ),
    )

    third = template(
        topic,
        [
            ParameterSpec(name="p", values=["1", "2"]),
            ParameterSpec(name="q", values=["3", "4"]),
            ParameterSpec(name="r", values=["-1", "1"]),
        ],
        body(
            topic=topic,
            symbols=[x_symbol(), y_symbol(), SymbolSpec(name="z", domain="real")],
            givens=[
                Given(
                    id="eq1",
                    relation=Relation(
                        kind="eq",
                        lhs=add(sym("x"), sym("y"), sym("z")),
                        rhs=add(param("p"), param("q"), param("r")),
                    ),
                ),
                Given(
                    id="eq2",
                    relation=Relation(
                        kind="eq",
                        lhs=sub(sym("x"), sym("y")),
                        rhs=sub(param("p"), param("q")),
                    ),
                ),
                Given(
                    id="eq3",
                    relation=Relation(
                        kind="eq",
                        lhs=add(sym("y"), sym("z")),
                        rhs=add(param("q"), param("r")),
                    ),
                ),
            ],
            goal=Goal(kind="solve", symbols=["x", "y", "z"], domain="real"),
            recipe=answer_tuple(param("p"), param("q"), param("r")),
            distractors=[
                distractor_tuple(
                    [neg(param("p")), param("q"), param("r")],
                    "SIGN_ERROR",
                    "Flips the first unknown",
                ),
                distractor_tuple(
                    [param("q"), param("p"), param("r")],
                    "SWAPPED",
                    "Swaps the first two unknowns",
                ),
                distractor_tuple(
                    [add(param("p"), param("q"), param("r")), num(0), num(0)],
                    "SUM_ERROR",
                    "Adds the right-hand sides into one coordinate",
                ),
            ],
            text=symbolic("Solve the system {equations}."),
        ),
    )

    dimensions_medium = {
        "procedure_length": "moderate",
        "operation_type": "high",
        "conceptual_demand": "moderate",
        "answer_discrimination": "moderate",
    }
    dimensions_hard = {
        "procedure_length": "high",
        "operation_type": "high",
        "conceptual_demand": "high",
        "answer_discrimination": "high",
    }

    return [
        item(
            family=family,
            number=1,
            goal_kind="solve",
            split=split,
            level="medium",
            template=first,
            dimensions=dimensions_medium,
            reason="Nearest anchor is the easy linear equation, repeated for two "
            "unknowns. Adding and subtracting the equations isolates the variables in "
            "a short routine, and the options are rejected by one substitution rule or "
            "by noticing that the coordinate order is wrong.",
        ),
        item(
            family=family,
            number=2,
            goal_kind="solve",
            split=split,
            level="medium",
            template=second,
            dimensions=dimensions_medium,
            reason="Nearest anchor is the easy linear equation, extended to an "
            "elimination system. The learner must choose a multiplier, eliminate one "
            "unknown and back-substitute, so a specific elimination rule eliminates "
            "each option even though every step is standard.",
        ),
        item(
            family=family,
            number=3,
            goal_kind="solve",
            split=split,
            level="hard",
            template=third,
            dimensions=dimensions_hard,
            reason="Nearest anchor is the hard product derivative, because three "
            "coupled equations require coordinating several eliminations. The solver "
            "has to choose which variable to remove first and keep three coordinates "
            "consistent, and the plausible options are wrong in ways that only a full "
            "back-substitution exposes.",
        ),
    ]


def simplify_expression_items() -> list[Item]:
    family = "simplify-expression"
    topic = "school.simplify"
    split = "development"

    easy = template(
        topic,
        [
            ParameterSpec(name="a", values=["2", "3"]),
            ParameterSpec(name="b", values=["4", "5"]),
        ],
        body(
            topic=topic,
            symbols=[x_symbol()],
            givens=domain_givens("x"),
            goal=Goal(
                kind="simplify",
                expr=sub(
                    mul(add(sym("x"), param("a")), add(sym("x"), param("b"))),
                    pow_(sym("x"), num(2)),
                ),
            ),
            recipe=answer_expression(
                add(
                    mul(add(param("a"), param("b")), sym("x")),
                    mul(param("a"), param("b")),
                )
            ),
            distractors=[
                distractor(
                    mul(add(param("a"), param("b")), sym("x")),
                    "DROPS_CONSTANT",
                    "Drops the constant term",
                ),
                distractor(
                    mul(param("a"), param("b")), "DROPS_LINEAR", "Drops the linear term"
                ),
                distractor(
                    sub(
                        mul(add(param("a"), param("b")), sym("x")),
                        mul(param("a"), param("b")),
                    ),
                    "SIGN_ERROR",
                    "Negates the constant term",
                ),
            ],
            text=symbolic("Simplify {expr}."),
        ),
    )

    medium = template(
        topic,
        [ParameterSpec(name="a", values=["2", "3"])],
        body(
            topic=topic,
            symbols=[x_symbol()],
            givens=domain_givens("x"),
            goal=Goal(
                kind="simplify",
                expr=sub(
                    pow_(add(sym("x"), param("a")), num(2)),
                    pow_(sub(sym("x"), param("a")), num(2)),
                ),
            ),
            recipe=answer_expression(mul(num(4), param("a"), sym("x"))),
            distractors=[
                distractor(
                    num(0), "CANCELS_SQUARES", "Cancels the two squares completely"
                ),
                distractor(
                    mul(num(2), param("a"), sym("x")),
                    "HALVES_CROSS_TERM",
                    "Keeps only one cross term",
                ),
                distractor(
                    mul(num(4), pow_(param("a"), num(2))),
                    "DROPS_VARIABLE",
                    "Keeps the constant square only",
                ),
            ],
            text=symbolic("Simplify {expr}."),
        ),
    )

    hard = template(
        topic,
        [ParameterSpec(name="a", values=["2", "3"])],
        body(
            topic=topic,
            symbols=[x_symbol()],
            givens=domain_givens("x"),
            goal=Goal(
                kind="simplify",
                expr=div(
                    sub(pow_(sym("x"), num(2)), pow_(param("a"), num(2))),
                    sub(sym("x"), param("a")),
                ),
            ),
            recipe=answer_expression(add(sym("x"), param("a"))),
            distractors=[
                distractor(
                    sub(sym("x"), param("a")), "SIGN_ERROR", "Subtracts the constant"
                ),
                distractor(
                    add(pow_(sym("x"), num(2)), param("a")),
                    "NO_CANCELLATION",
                    "Leaves the squared term",
                ),
                distractor(
                    mul(param("a"), sym("x")), "MULTIPLIES", "Multiplies the terms"
                ),
            ],
            text=symbolic("Simplify {expr}."),
        ),
    )

    return [
        item(
            family=family,
            number=1,
            goal_kind="simplify",
            split=split,
            level="easy",
            template=easy,
            dimensions={
                "procedure_length": "low",
                "operation_type": "low",
                "conceptual_demand": "low",
                "answer_discrimination": "low",
            },
            reason="Nearest anchor is the easy linear equation. Expanding one product "
            "and cancelling the matching square is a short routine, and the options "
            "are separated by whether the linear term and the constant were both kept.",
        ),
        item(
            family=family,
            number=2,
            goal_kind="simplify",
            split=split,
            level="medium",
            template=medium,
            dimensions={
                "procedure_length": "moderate",
                "operation_type": "moderate",
                "conceptual_demand": "moderate",
                "answer_discrimination": "moderate",
            },
            reason="Nearest anchor is the medium quadratic expansion, applied twice. "
            "The learner must expand two squares and subtract one from the other, so "
            "the cross terms combine while the square terms cancel. Each option drops "
            "a cross term or the variable, so the subtraction rule is the specific "
            "discriminator.",
        ),
        item(
            family=family,
            number=3,
            goal_kind="simplify",
            split=split,
            level="hard",
            template=hard,
            dimensions={
                "procedure_length": "moderate",
                "operation_type": "moderate",
                "conceptual_demand": "high",
                "answer_discrimination": "high",
            },
            reason="Nearest anchor is the hard product derivative, because the "
            "simplification depends on spotting a difference of squares before "
            "cancelling. The domain hole at the excluded value adds a reason to "
            "justify the cancellation, and the plausible options look like the "
            "original factors rather than the reduced expression.",
        ),
    ]


def algebraic_fraction_items() -> list[Item]:
    family = "algebraic-fraction"
    topic = "school.algebraic_fraction"
    split = "development"

    easy = template(
        topic,
        [ParameterSpec(name="b", values=["2", "3"])],
        body(
            topic=topic,
            symbols=[x_symbol(), y_symbol()],
            givens=domain_givens("x", "y"),
            goal=Goal(
                kind="simplify",
                expr=div(
                    add(pow_(sym("x"), num(2)), mul(param("b"), sym("x"), sym("y"))),
                    sym("x"),
                ),
            ),
            recipe=answer_expression(add(sym("x"), mul(param("b"), sym("y")))),
            distractors=[
                distractor(
                    add(sym("x"), param("b")),
                    "DROPS_VARIABLE",
                    "Cancels the x but drops the y factor",
                ),
                distractor(
                    mul(sym("x"), sym("y")),
                    "MULTIPLIES",
                    "Multiplies the remaining terms",
                ),
                distractor(
                    sub(sym("x"), mul(param("b"), sym("y"))),
                    "SIGN_ERROR",
                    "Subtracts the second term",
                ),
            ],
            text=symbolic("Simplify {expr}."),
        ),
    )

    medium = template(
        topic,
        [ParameterSpec(name="a", values=["2", "3"])],
        body(
            topic=topic,
            symbols=[x_symbol()],
            givens=domain_givens("x"),
            goal=Goal(
                kind="simplify",
                expr=div(
                    add(pow_(sym("x"), num(2)), mul(param("a"), sym("x"))), sym("x")
                ),
            ),
            recipe=answer_expression(add(sym("x"), param("a"))),
            distractors=[
                distractor(sym("x"), "DROPS_TERM", "Drops the constant term"),
                distractor(
                    add(sym("x"), pow_(param("a"), num(2))),
                    "SQUARES_CONSTANT",
                    "Squares the constant",
                ),
                distractor(
                    mul(param("a"), sym("x")),
                    "KEEPS_PRODUCT",
                    "Leaves the product instead of the sum",
                ),
            ],
            text=symbolic("Simplify {expr}."),
        ),
    )

    hard = template(
        topic,
        [
            ParameterSpec(name="a", values=["1", "2"]),
            ParameterSpec(name="b", values=["3", "4"]),
        ],
        body(
            topic=topic,
            symbols=[x_symbol()],
            givens=domain_givens("x"),
            goal=Goal(
                kind="simplify",
                expr=div(
                    sub(pow_(sym("x"), num(2)), pow_(param("a"), num(2))),
                    add(
                        pow_(sym("x"), num(2)),
                        mul(neg(add(param("a"), param("b"))), sym("x")),
                        mul(param("a"), param("b")),
                    ),
                ),
            ),
            recipe=answer_expression(
                div(add(sym("x"), param("a")), sub(sym("x"), param("b")))
            ),
            distractors=[
                distractor(
                    div(sub(sym("x"), param("a")), sub(sym("x"), param("b"))),
                    "SIGN_ERROR",
                    "Keeps the wrong numerator factor",
                ),
                distractor(
                    div(add(sym("x"), param("a")), add(sym("x"), param("b"))),
                    "DENOMINATOR_SIGN",
                    "Keeps the wrong denominator factor",
                ),
                distractor(
                    div(sub(sym("x"), param("a")), add(sym("x"), param("b"))),
                    "BOTH_SIGNS",
                    "Flips both remaining signs",
                ),
            ],
            text=symbolic("Simplify {expr}."),
        ),
    )

    return [
        item(
            family=family,
            number=1,
            goal_kind="simplify",
            split=split,
            level="easy",
            template=easy,
            dimensions={
                "procedure_length": "low",
                "operation_type": "low",
                "conceptual_demand": "low",
                "answer_discrimination": "low",
            },
            reason="Nearest anchor is the easy linear equation. Removing a common "
            "factor is one routine step, and the options are rejected by checking "
            "whether the division was applied to every term.",
        ),
        item(
            family=family,
            number=2,
            goal_kind="simplify",
            split=split,
            level="medium",
            template=medium,
            dimensions={
                "procedure_length": "moderate",
                "operation_type": "moderate",
                "conceptual_demand": "moderate",
                "answer_discrimination": "moderate",
            },
            reason="Nearest anchor is the easy linear equation, extended by factoring "
            "the numerator. The learner must divide both terms by the common factor, "
            "and each option mishandles one term, so one specific factorisation rule "
            "separates the choices.",
        ),
        item(
            family=family,
            number=3,
            goal_kind="simplify",
            split=split,
            level="hard",
            template=hard,
            dimensions={
                "procedure_length": "high",
                "operation_type": "high",
                "conceptual_demand": "high",
                "answer_discrimination": "high",
            },
            reason="Nearest anchor is the hard product derivative, because both "
            "numerator and denominator must be factorised before anything cancels. The "
            "two sign patterns across the factors make the remaining choices genuinely "
            "similar, so the full factorisation and cancellation is needed.",
        ),
    ]


def exponent_law_items() -> list[Item]:
    family = "exponent-laws"
    topic = "school.exponents"
    split = "held_out"

    easy = template(
        topic,
        [ParameterSpec(name="a", values=["2", "3"])],
        body(
            topic=topic,
            symbols=[x_symbol()],
            givens=domain_givens("x"),
            goal=Goal(
                kind="evaluate",
                expr=mul(pow_(param("a"), num(3)), pow_(param("a"), num(4))),
            ),
            recipe=answer_numeric(pow_(param("a"), num(7))),
            distractors=[
                distractor(
                    pow_(param("a"), num(12)),
                    "MULTIPLIES_EXPONENTS",
                    "Multiplies the exponents",
                ),
                distractor(
                    pow_(param("a"), num(1)),
                    "SUBTRACTS_EXPONENTS",
                    "Subtracts the exponents",
                ),
                distractor(
                    pow_(param("a"), num(8)), "OFF_BY_ONE", "Adds one extra power"
                ),
            ],
            text=symbolic("Evaluate {expr}."),
        ),
    )

    medium = template(
        topic,
        [ParameterSpec(name="a", values=["2", "3"])],
        body(
            topic=topic,
            symbols=[x_symbol()],
            givens=domain_givens("x"),
            goal=Goal(
                kind="evaluate",
                expr=div(
                    mul(pow_(pow_(param("a"), num(2)), num(3))),
                    pow_(param("a"), num(4)),
                ),
            ),
            recipe=answer_numeric(pow_(param("a"), num(2))),
            distractors=[
                distractor(
                    pow_(param("a"), num(6)),
                    "FORGETS_DIVISION",
                    "Keeps the multiplied exponent",
                ),
                distractor(
                    pow_(param("a"), num(10)),
                    "ADDS_EXPONENTS",
                    "Adds instead of subtracting",
                ),
                distractor(
                    div(num(1), pow_(param("a"), num(2))),
                    "SIGN_ERROR",
                    "Subtracts in the wrong order",
                ),
            ],
            text=symbolic("Evaluate {expr}."),
        ),
    )

    hard = template(
        topic,
        [
            ParameterSpec(name="a", values=["2", "3"]),
            ParameterSpec(name="b", values=["2", "3"]),
        ],
        body(
            topic=topic,
            symbols=[x_symbol(), y_symbol()],
            givens=domain_givens("x", "y"),
            goal=Goal(
                kind="evaluate",
                expr=div(
                    pow_(
                        mul(pow_(param("a"), num(2)), pow_(param("b"), num(3))), num(2)
                    ),
                    mul(pow_(param("a"), num(3)), pow_(param("b"), num(4))),
                ),
            ),
            recipe=answer_numeric(mul(param("a"), pow_(param("b"), num(2)))),
            distractors=[
                distractor(
                    mul(pow_(param("a"), num(4)), pow_(param("b"), num(2))),
                    "FORGETS_A_DIVISION",
                    "Fails to subtract the a exponent",
                ),
                distractor(
                    pow_(param("b"), num(2)),
                    "CANCELS_A",
                    "Cancels the a factor completely",
                ),
                distractor(
                    mul(param("a"), pow_(param("b"), num(4))),
                    "FORGETS_B_DIVISION",
                    "Fails to subtract the b exponent",
                ),
            ],
            text=symbolic("Evaluate {expr}."),
        ),
    )

    medium_dimensions = {
        "procedure_length": "moderate",
        "operation_type": "moderate",
        "conceptual_demand": "moderate",
        "answer_discrimination": "moderate",
    }
    hard_dimensions = {
        "procedure_length": "high",
        "operation_type": "moderate",
        "conceptual_demand": "high",
        "answer_discrimination": "high",
    }

    return [
        item(
            family=family,
            number=1,
            goal_kind="evaluate",
            split=split,
            level="easy",
            template=easy,
            dimensions={
                "procedure_length": "low",
                "operation_type": "low",
                "conceptual_demand": "low",
                "answer_discrimination": "low",
            },
            reason="Nearest anchor is the easy linear equation. The item applies one "
            "exponent law to a product, and the options are separated by a quick check "
            "that powers with the same base add their exponents.",
        ),
        item(
            family=family,
            number=2,
            goal_kind="evaluate",
            split=split,
            level="medium",
            template=medium,
            dimensions=medium_dimensions,
            reason="Nearest anchor is the medium quadratic expansion, because two "
            "exponent laws are chained. The learner must multiply the inner exponents "
            "and then subtract the denominator exponent, and each option omits one of "
            "those two operations.",
        ),
        item(
            family=family,
            number=3,
            goal_kind="evaluate",
            split=split,
            level="hard",
            template=hard,
            dimensions=hard_dimensions,
            reason="Nearest anchor is the hard product derivative, because the "
            "expression has two bases and two nested laws. Both exponents must be "
            "tracked independently through the power and the quotient, and the options "
            "each leave one base or one subtraction uncorrected.",
        ),
    ]


def factor_quadratic_items() -> list[Item]:
    family = "factor-quadratic"
    topic = "school.factor"
    split = "development"

    easy = template(
        topic,
        [
            ParameterSpec(name="p", values=["1", "2"]),
            ParameterSpec(name="q", values=["2", "3"]),
        ],
        body(
            topic=topic,
            symbols=[x_symbol()],
            givens=domain_givens("x"),
            goal=Goal(
                kind="factor",
                expr=add(
                    pow_(sym("x"), num(2)),
                    mul(add(param("p"), param("q")), sym("x")),
                    mul(param("p"), param("q")),
                ),
            ),
            recipe=answer_expression(
                mul(add(sym("x"), param("p")), add(sym("x"), param("q")))
            ),
            distractors=[
                distractor(
                    mul(sub(sym("x"), param("p")), sub(sym("x"), param("q"))),
                    "SIGN_ERROR",
                    "Flips both signs inside the brackets",
                ),
                distractor(
                    mul(add(sym("x"), param("p")), sub(sym("x"), param("q"))),
                    "ONE_SIGN",
                    "Flips one sign inside the brackets",
                ),
                distractor(
                    mul(
                        add(sym("x"), mul(param("p"), param("q"))),
                        add(sym("x"), add(param("p"), param("q"))),
                    ),
                    "CONFUSES_SUM_AND_PRODUCT",
                    "Uses the product and the sum of the constants",
                ),
            ],
            text=symbolic("Factor {expr}."),
        ),
    )

    medium = template(
        topic,
        [ParameterSpec(name="a", values=["2", "3"])],
        body(
            topic=topic,
            symbols=[x_symbol()],
            givens=domain_givens("x"),
            goal=Goal(
                kind="factor",
                expr=sub(pow_(sym("x"), num(2)), pow_(param("a"), num(2))),
            ),
            recipe=answer_expression(
                mul(sub(sym("x"), param("a")), add(sym("x"), param("a")))
            ),
            distractors=[
                distractor(
                    pow_(sub(sym("x"), param("a")), num(2)),
                    "REPEATS_ROOT",
                    "Repeats one factor",
                ),
                distractor(
                    pow_(add(sym("x"), param("a")), num(2)),
                    "SIGN_ERROR",
                    "Uses the wrong sign twice",
                ),
                distractor(
                    mul(
                        sub(sym("x"), param("a")),
                        add(sym("x"), add(param("a"), num(1))),
                    ),
                    "OFF_BY_ONE",
                    "Adds one to the constant",
                ),
            ],
            text=symbolic("Factor {expr}."),
        ),
    )

    hard = template(
        topic,
        [
            ParameterSpec(name="m", values=["2", "3"]),
            ParameterSpec(name="p", values=["5", "7"]),
            ParameterSpec(name="q", values=["3", "4"]),
        ],
        body(
            topic=topic,
            symbols=[x_symbol()],
            givens=domain_givens("x"),
            goal=Goal(
                kind="factor",
                expr=add(
                    mul(param("m"), pow_(sym("x"), num(2))),
                    mul(add(mul(param("m"), param("q")), param("p")), sym("x")),
                    mul(param("p"), param("q")),
                ),
            ),
            recipe=answer_expression(
                mul(
                    add(mul(param("m"), sym("x")), param("p")),
                    add(sym("x"), param("q")),
                )
            ),
            distractors=[
                distractor(
                    mul(
                        sub(mul(param("m"), sym("x")), param("p")),
                        sub(sym("x"), param("q")),
                    ),
                    "SIGN_ERROR",
                    "Flips both signs",
                ),
                distractor(
                    mul(
                        param("m"), add(sym("x"), param("p")), add(sym("x"), param("q"))
                    ),
                    "DOUBLE_COEFFICIENT",
                    "Applies the leading coefficient to the whole product",
                ),
                distractor(
                    mul(add(sym("x"), param("p")), add(sym("x"), param("q"))),
                    "MISSING_COEFFICIENT",
                    "Drops the leading coefficient",
                ),
            ],
            text=symbolic("Factor {expr}."),
        ),
    )

    return [
        item(
            family=family,
            number=1,
            goal_kind="factor",
            split=split,
            level="easy",
            template=easy,
            dimensions={
                "procedure_length": "low",
                "operation_type": "moderate",
                "conceptual_demand": "low",
                "answer_discrimination": "low",
            },
            reason="Nearest anchor is the medium quadratic expansion, read in reverse. "
            "Finding two constants with the stated sum and product is one routine "
            "search, and the options are separated by checking the signs in the two "
            "brackets.",
        ),
        item(
            family=family,
            number=2,
            goal_kind="factor",
            split=split,
            level="medium",
            template=medium,
            dimensions={
                "procedure_length": "moderate",
                "operation_type": "moderate",
                "conceptual_demand": "moderate",
                "answer_discrimination": "moderate",
            },
            reason="Nearest anchor is the medium quadratic expansion, run in reverse. "
            "Recognising the difference of squares is the one connection, and the "
            "distractors differ by repeating a factor or by using the wrong sign "
            "pattern.",
        ),
        item(
            family=family,
            number=3,
            goal_kind="factor",
            split=split,
            level="hard",
            template=hard,
            dimensions={
                "procedure_length": "high",
                "operation_type": "high",
                "conceptual_demand": "high",
                "answer_discrimination": "high",
            },
            reason="Nearest anchor is the hard product derivative, because a non-monic "
            "quadratic needs a search over factor pairs and a check of the cross term. "
            "The plausible options flip the signs, double the leading coefficient or "
            "drop it, so the full factorisation must be recovered.",
        ),
    ]


def factor_special_items() -> list[Item]:
    family = "factor-special"
    topic = "school.factor_special"
    split = "held_out"

    easy = template(
        topic,
        [ParameterSpec(name="a", values=["2", "3"])],
        body(
            topic=topic,
            symbols=[x_symbol()],
            givens=domain_givens("x"),
            goal=Goal(
                kind="factor",
                expr=add(
                    pow_(sym("x"), num(2)),
                    mul(num(2), param("a"), sym("x")),
                    pow_(param("a"), num(2)),
                ),
            ),
            recipe=answer_expression(pow_(add(sym("x"), param("a")), num(2))),
            distractors=[
                distractor(
                    pow_(sub(sym("x"), param("a")), num(2)),
                    "SIGN_ERROR",
                    "Uses the wrong sign",
                ),
                distractor(
                    mul(add(sym("x"), param("a")), sub(sym("x"), param("a"))),
                    "DIFFERENCE_OF_SQUARES",
                    "Treats it as a difference of squares",
                ),
                distractor(
                    pow_(add(sym("x"), mul(num(2), param("a"))), num(2)),
                    "DOUBLES_CONSTANT",
                    "Doubles the constant",
                ),
            ],
            text=symbolic("Factor {expr}."),
        ),
    )

    medium = template(
        topic,
        [ParameterSpec(name="a", values=["1", "2"])],
        body(
            topic=topic,
            symbols=[x_symbol()],
            givens=domain_givens("x"),
            goal=Goal(
                kind="factor",
                expr=sub(pow_(sym("x"), num(3)), pow_(param("a"), num(3))),
            ),
            recipe=answer_expression(
                mul(
                    sub(sym("x"), param("a")),
                    add(
                        pow_(sym("x"), num(2)),
                        mul(param("a"), sym("x")),
                        pow_(param("a"), num(2)),
                    ),
                )
            ),
            distractors=[
                distractor(
                    mul(
                        add(sym("x"), param("a")),
                        add(
                            pow_(sym("x"), num(2)),
                            mul(neg(param("a")), sym("x")),
                            pow_(param("a"), num(2)),
                        ),
                    ),
                    "SUM_OF_CUBES",
                    "Uses the sum-of-cubes pattern",
                ),
                distractor(
                    pow_(sub(sym("x"), param("a")), num(3)),
                    "CUBES_BINOMIAL",
                    "Cubes the binomial",
                ),
                distractor(
                    mul(
                        sub(sym("x"), param("a")),
                        add(pow_(sym("x"), num(2)), pow_(param("a"), num(2))),
                    ),
                    "MISSING_CROSS_TERM",
                    "Drops the cross term",
                ),
            ],
            text=symbolic("Factor {expr}."),
        ),
    )

    hard = template(
        topic,
        [
            ParameterSpec(name="a", values=["1", "2"]),
            ParameterSpec(name="b", values=["3", "4"]),
        ],
        body(
            topic=topic,
            symbols=[x_symbol()],
            givens=domain_givens("x"),
            goal=Goal(
                kind="factor",
                expr=add(
                    pow_(sym("x"), num(3)),
                    mul(param("a"), pow_(sym("x"), num(2))),
                    mul(param("b"), sym("x")),
                    mul(param("a"), param("b")),
                ),
            ),
            recipe=answer_expression(
                mul(add(sym("x"), param("a")), add(pow_(sym("x"), num(2)), param("b")))
            ),
            distractors=[
                distractor(
                    mul(
                        sub(sym("x"), param("a")),
                        add(pow_(sym("x"), num(2)), param("b")),
                    ),
                    "SIGN_ERROR",
                    "Flips the linear factor",
                ),
                distractor(
                    mul(
                        add(sym("x"), param("b")),
                        add(pow_(sym("x"), num(2)), param("a")),
                    ),
                    "SWAPPED_CONSTANTS",
                    "Swaps the constants between the factors",
                ),
                distractor(
                    mul(add(sym("x"), param("a")), add(sym("x"), param("b"))),
                    "MISSING_DEGREE",
                    "Factors as two linear terms",
                ),
            ],
            text=symbolic("Factor {expr}."),
        ),
    )

    return [
        item(
            family=family,
            number=1,
            goal_kind="factor",
            split=split,
            level="easy",
            template=easy,
            dimensions={
                "procedure_length": "low",
                "operation_type": "moderate",
                "conceptual_demand": "moderate",
                "answer_discrimination": "moderate",
            },
            reason="Nearest anchor is the medium quadratic expansion, read as a "
            "perfect square. The learner must notice that the middle term is twice the "
            "product, and the options differ by the sign or by confusing the pattern "
            "with a difference of squares.",
        ),
        item(
            family=family,
            number=2,
            goal_kind="factor",
            split=split,
            level="medium",
            template=medium,
            dimensions={
                "procedure_length": "moderate",
                "operation_type": "moderate",
                "conceptual_demand": "moderate",
                "answer_discrimination": "moderate",
            },
            reason="Nearest anchor is the medium quadratic expansion, extended to a "
            "cubic identity. The learner must recall the difference-of-cubes pattern "
            "and keep the quadratic factor irreducible, while the distractors swap in "
            "the sum pattern or drop the cross term.",
        ),
        item(
            family=family,
            number=3,
            goal_kind="factor",
            split=split,
            level="hard",
            template=hard,
            dimensions={
                "procedure_length": "high",
                "operation_type": "high",
                "conceptual_demand": "high",
                "answer_discrimination": "high",
            },
            reason="Nearest anchor is the hard product derivative, because grouping "
            "requires choosing a split of the cubic terms before a common bracket "
            "appears. The options are all factored forms with plausible sign or degree "
            "errors, so the learner has to reconstruct the grouping rather than test "
            "one rule.",
        ),
    ]


def expand_binomial_items() -> list[Item]:
    family = "expand-binomial"
    topic = "school.expand"
    split = "development"

    easy = template(
        topic,
        [
            ParameterSpec(name="a", values=["2", "3"]),
            ParameterSpec(name="b", values=["1", "2"]),
        ],
        body(
            topic=topic,
            symbols=[x_symbol()],
            givens=domain_givens("x"),
            goal=Goal(
                kind="expand",
                expr=mul(add(sym("x"), param("a")), add(sym("x"), param("b"))),
            ),
            recipe=answer_expression(
                add(
                    pow_(sym("x"), num(2)),
                    mul(add(param("a"), param("b")), sym("x")),
                    mul(param("a"), param("b")),
                )
            ),
            distractors=[
                distractor(
                    add(pow_(sym("x"), num(2)), mul(param("a"), param("b"))),
                    "MISSING_CROSS_TERM",
                    "Drops the linear term",
                ),
                distractor(
                    add(
                        pow_(sym("x"), num(2)),
                        mul(neg(add(param("a"), param("b"))), sym("x")),
                        mul(param("a"), param("b")),
                    ),
                    "SIGN_ERROR",
                    "Negates the linear term",
                ),
                distractor(
                    sub(
                        add(
                            pow_(sym("x"), num(2)),
                            mul(add(param("a"), param("b")), sym("x")),
                        ),
                        mul(param("a"), param("b")),
                    ),
                    "CONSTANT_SIGN",
                    "Negates the constant term",
                ),
            ],
            text=symbolic("Expand {expr}."),
        ),
    )

    medium = template(
        topic,
        [
            ParameterSpec(name="a", values=["2", "3"]),
            ParameterSpec(name="b", values=["1", "4"]),
        ],
        body(
            topic=topic,
            symbols=[x_symbol()],
            givens=domain_givens("x"),
            goal=Goal(
                kind="expand",
                expr=mul(add(sym("x"), param("a")), sub(sym("x"), param("b"))),
            ),
            recipe=answer_expression(
                add(
                    pow_(sym("x"), num(2)),
                    mul(sub(param("a"), param("b")), sym("x")),
                    mul(neg(param("a")), param("b")),
                )
            ),
            distractors=[
                distractor(
                    add(
                        pow_(sym("x"), num(2)),
                        mul(add(param("a"), param("b")), sym("x")),
                        mul(param("a"), param("b")),
                    ),
                    "SIGN_ERROR",
                    "Ignores the subtracted constant in the second bracket",
                ),
                distractor(
                    add(
                        pow_(sym("x"), num(2)),
                        mul(sub(param("a"), param("b")), sym("x")),
                        mul(param("a"), param("b")),
                    ),
                    "CONSTANT_SIGN",
                    "Gives the constant term the wrong sign",
                ),
                distractor(
                    sub(
                        pow_(sym("x"), num(2)),
                        add(
                            mul(sub(param("a"), param("b")), sym("x")),
                            mul(param("a"), param("b")),
                        ),
                    ),
                    "LINEAR_SIGN",
                    "Negates both the linear and the constant term",
                ),
            ],
            text=symbolic("Expand {expr}."),
        ),
    )

    hard = template(
        topic,
        [ParameterSpec(name="a", values=["2", "3"])],
        body(
            topic=topic,
            symbols=[x_symbol()],
            givens=domain_givens("x"),
            goal=Goal(kind="expand", expr=pow_(add(sym("x"), param("a")), num(3))),
            recipe=answer_expression(
                add(
                    pow_(sym("x"), num(3)),
                    mul(num(3), param("a"), pow_(sym("x"), num(2))),
                    mul(num(3), pow_(param("a"), num(2)), sym("x")),
                    pow_(param("a"), num(3)),
                )
            ),
            distractors=[
                distractor(
                    add(pow_(sym("x"), num(3)), pow_(param("a"), num(3))),
                    "MISSING_CROSS_TERMS",
                    "Drops both middle terms",
                ),
                distractor(
                    sub(
                        add(
                            pow_(sym("x"), num(3)),
                            mul(num(3), param("a"), pow_(sym("x"), num(2))),
                            mul(num(3), pow_(param("a"), num(2)), sym("x")),
                        ),
                        pow_(param("a"), num(3)),
                    ),
                    "CONSTANT_SIGN",
                    "Negates the constant term",
                ),
                distractor(
                    add(
                        pow_(sym("x"), num(3)),
                        mul(param("a"), pow_(sym("x"), num(2))),
                        mul(pow_(param("a"), num(2)), sym("x")),
                        pow_(param("a"), num(3)),
                    ),
                    "LINEAR_COEFFICIENTS",
                    "Uses the coefficients from a square",
                ),
            ],
            text=symbolic("Expand {expr}."),
        ),
    )

    return [
        item(
            family=family,
            number=1,
            goal_kind="expand",
            split=split,
            level="easy",
            template=easy,
            dimensions={
                "procedure_length": "low",
                "operation_type": "low",
                "conceptual_demand": "low",
                "answer_discrimination": "low",
            },
            reason="Nearest anchor is the easy linear equation. Multiplying two "
            "binomials is one routine expansion, and the options are separated by "
            "checking the cross term and the sign of the constant.",
        ),
        item(
            family=family,
            number=2,
            goal_kind="expand",
            split=split,
            level="medium",
            template=medium,
            dimensions={
                "procedure_length": "moderate",
                "operation_type": "moderate",
                "conceptual_demand": "low",
                "answer_discrimination": "moderate",
            },
            reason="This is the worked medium quadratic expansion anchor, with one "
            "subtracted constant. Four products are collected into three terms, and "
            "each option needs the sign and cross-term rules checked, so the sequence "
            "is moderate even though the distributive rule itself is routine.",
        ),
        item(
            family=family,
            number=3,
            goal_kind="expand",
            split=split,
            level="hard",
            template=hard,
            dimensions={
                "procedure_length": "high",
                "operation_type": "moderate",
                "conceptual_demand": "moderate",
                "answer_discrimination": "high",
            },
            reason="Nearest anchor is the hard product derivative, because a cubed "
            "binomial multiplies three factors and collects several like terms. The "
            "binomial coefficients must be tracked through the expansion, and the "
            "plausible options drop a cross term or copy the coefficients from a "
            "square.",
        ),
    ]


def expand_special_items() -> list[Item]:
    family = "expand-special"
    topic = "school.expand_special"
    split = "held_out"

    easy = template(
        topic,
        [ParameterSpec(name="a", values=["2", "3"])],
        body(
            topic=topic,
            symbols=[x_symbol()],
            givens=domain_givens("x"),
            goal=Goal(kind="expand", expr=pow_(add(sym("x"), param("a")), num(2))),
            recipe=answer_expression(
                add(
                    pow_(sym("x"), num(2)),
                    mul(num(2), param("a"), sym("x")),
                    pow_(param("a"), num(2)),
                )
            ),
            distractors=[
                distractor(
                    add(pow_(sym("x"), num(2)), pow_(param("a"), num(2))),
                    "MISSING_CROSS_TERM",
                    "Drops the middle term",
                ),
                distractor(
                    add(
                        pow_(sym("x"), num(2)),
                        mul(param("a"), sym("x")),
                        pow_(param("a"), num(2)),
                    ),
                    "HALVES_CROSS_TERM",
                    "Uses one cross term instead of two",
                ),
                distractor(
                    sub(
                        add(pow_(sym("x"), num(2)), mul(num(2), param("a"), sym("x"))),
                        pow_(param("a"), num(2)),
                    ),
                    "CONSTANT_SIGN",
                    "Negates the constant term",
                ),
            ],
            text=symbolic("Expand {expr}."),
        ),
    )

    medium = template(
        topic,
        [ParameterSpec(name="a", values=["2", "3"])],
        body(
            topic=topic,
            symbols=[x_symbol()],
            givens=domain_givens("x"),
            goal=Goal(
                kind="expand",
                expr=mul(add(sym("x"), param("a")), sub(sym("x"), param("a"))),
            ),
            recipe=answer_expression(
                sub(pow_(sym("x"), num(2)), pow_(param("a"), num(2)))
            ),
            distractors=[
                distractor(
                    add(pow_(sym("x"), num(2)), pow_(param("a"), num(2))),
                    "SIGN_ERROR",
                    "Adds the squared constant",
                ),
                distractor(
                    add(
                        pow_(sym("x"), num(2)),
                        mul(neg(mul(num(2), param("a"))), sym("x")),
                        pow_(param("a"), num(2)),
                    ),
                    "KEEPS_CROSS_TERM",
                    "Keeps the cross term",
                ),
                distractor(
                    sub(
                        add(
                            pow_(sym("x"), num(2)),
                            mul(neg(mul(num(2), param("a"))), sym("x")),
                        ),
                        pow_(param("a"), num("2")),
                    ),
                    "BOTH_SIGNS",
                    "Keeps the cross term and negates the constant",
                ),
            ],
            text=symbolic("Expand {expr}."),
        ),
    )

    hard = template(
        topic,
        [
            ParameterSpec(name="a", values=["2", "3"]),
            ParameterSpec(name="b", values=["1", "2"]),
        ],
        body(
            topic=topic,
            symbols=[x_symbol()],
            givens=domain_givens("x"),
            goal=Goal(
                kind="expand",
                expr=pow_(add(mul(param("a"), sym("x")), param("b")), num(2)),
            ),
            recipe=answer_expression(
                add(
                    mul(pow_(param("a"), num(2)), pow_(sym("x"), num(2))),
                    mul(num(2), param("a"), param("b"), sym("x")),
                    pow_(param("b"), num(2)),
                )
            ),
            distractors=[
                distractor(
                    add(
                        mul(param("a"), pow_(sym("x"), num(2))),
                        mul(num(2), param("a"), param("b"), sym("x")),
                        pow_(param("b"), num(2)),
                    ),
                    "UNSQUARED_COEFFICIENT",
                    "Fails to square the leading coefficient",
                ),
                distractor(
                    add(
                        mul(pow_(param("a"), num(2)), pow_(sym("x"), num(2))),
                        pow_(param("b"), num("2")),
                    ),
                    "MISSING_CROSS_TERM",
                    "Drops the cross term",
                ),
                distractor(
                    add(
                        mul(pow_(param("a"), num(2)), pow_(sym("x"), num(2))),
                        mul(param("a"), param("b"), sym("x")),
                        pow_(param("b"), num(2)),
                    ),
                    "HALVES_CROSS_TERM",
                    "Uses one cross term instead of two",
                ),
            ],
            text=symbolic("Expand {expr}."),
        ),
    )

    return [
        item(
            family=family,
            number=1,
            goal_kind="expand",
            split=split,
            level="easy",
            template=easy,
            dimensions={
                "procedure_length": "low",
                "operation_type": "moderate",
                "conceptual_demand": "low",
                "answer_discrimination": "low",
            },
            reason="Nearest anchor is the medium quadratic expansion, with one "
            "repeated factor. Squaring a binomial is a short standard procedure, and "
            "the options are separated by whether the learner kept the two cross terms "
            "and the positive constant.",
        ),
        item(
            family=family,
            number=2,
            goal_kind="expand",
            split=split,
            level="medium",
            template=medium,
            dimensions={
                "procedure_length": "moderate",
                "operation_type": "moderate",
                "conceptual_demand": "moderate",
                "answer_discrimination": "moderate",
            },
            reason="Nearest anchor is the medium quadratic expansion, using the "
            "conjugate pair. The learner must see that the cross terms cancel, and the "
            "distractors keep a cross term or add the squared constant, so the sign "
            "rule is the specific discriminator.",
        ),
        item(
            family=family,
            number=3,
            goal_kind="expand",
            split=split,
            level="hard",
            template=hard,
            dimensions={
                "procedure_length": "moderate",
                "operation_type": "moderate",
                "conceptual_demand": "moderate",
                "answer_discrimination": "high",
            },
            reason="Nearest anchor is the hard product derivative, because the leading "
            "coefficient and the constant both need squaring inside the binomial "
            "expansion. The structure is short but the coefficient errors are "
            "plausible, and separating the options needs every term of the identity "
            "checked.",
        ),
    ]


def derivative_polynomial_items() -> list[Item]:
    family = "derivative-polynomial"
    topic = "university.derivative_polynomial"
    split = "development"

    easy = template(
        topic,
        [ParameterSpec(name="a", values=["2", "3"])],
        body(
            topic=topic,
            symbols=[x_symbol()],
            givens=domain_givens("x"),
            goal=Goal(
                kind="derivative",
                symbol="x",
                expr=mul(param("a"), pow_(sym("x"), num(2))),
                order=1,
            ),
            recipe=answer_expression(mul(num(2), param("a"), sym("x"))),
            distractors=[
                distractor(
                    mul(param("a"), sym("x")),
                    "DROPS_COEFFICIENT",
                    "Drops the power-rule coefficient",
                ),
                distractor(
                    mul(num(2), param("a"), pow_(sym("x"), num(2))),
                    "KEEPS_EXPONENT",
                    "Keeps the original exponent",
                ),
                distractor(
                    mul(param("a"), pow_(sym("x"), num(2))),
                    "NO_CHANGE",
                    "Returns the original expression",
                ),
            ],
            text=symbolic("Differentiate {expr} with respect to x."),
        ),
    )

    medium = template(
        topic,
        [
            ParameterSpec(name="a", values=["2", "3"]),
            ParameterSpec(name="b", values=["-2", "1"]),
            ParameterSpec(name="c", values=["1", "2"]),
        ],
        body(
            topic=topic,
            symbols=[x_symbol()],
            givens=domain_givens("x"),
            goal=Goal(
                kind="derivative",
                symbol="x",
                expr=add(
                    mul(param("a"), pow_(sym("x"), num(3))),
                    mul(param("b"), pow_(sym("x"), num(2))),
                    param("c"),
                ),
                order=1,
            ),
            recipe=answer_expression(
                add(
                    mul(num(3), param("a"), pow_(sym("x"), num(2))),
                    mul(num(2), param("b"), sym("x")),
                )
            ),
            distractors=[
                distractor(
                    add(
                        mul(num(3), param("a"), pow_(sym("x"), num(3))),
                        mul(num(2), param("b"), pow_(sym("x"), num(2))),
                    ),
                    "KEEPS_EXPONENTS",
                    "Keeps the original exponents",
                ),
                distractor(
                    add(
                        mul(param("a"), pow_(sym("x"), num(2))),
                        mul(param("b"), sym("x")),
                    ),
                    "DROPS_COEFFICIENTS",
                    "Drops the power-rule coefficients",
                ),
                distractor(
                    sub(
                        mul(num(3), param("a"), pow_(sym("x"), num(2))),
                        mul(num(2), param("b"), sym("x")),
                    ),
                    "SIGN_ERROR",
                    "Flips the sign of the linear term",
                ),
            ],
            text=symbolic("Differentiate {expr} with respect to x."),
        ),
    )

    hard = template(
        topic,
        [
            ParameterSpec(name="a", values=["2", "3"]),
            ParameterSpec(name="b", values=["-1", "1"]),
            ParameterSpec(name="c", values=["1", "2"]),
        ],
        body(
            topic=topic,
            symbols=[x_symbol()],
            givens=domain_givens("x"),
            goal=Goal(
                kind="derivative",
                symbol="x",
                expr=add(
                    mul(param("a"), pow_(sym("x"), num(4))),
                    mul(param("b"), pow_(sym("x"), num(3))),
                    mul(param("c"), sym("x")),
                ),
                order=2,
            ),
            recipe=answer_expression(
                add(
                    mul(num(12), param("a"), pow_(sym("x"), num(2))),
                    mul(num(6), param("b"), sym("x")),
                )
            ),
            distractors=[
                distractor(
                    add(
                        mul(num(4), param("a"), pow_(sym("x"), num(3))),
                        mul(num(3), param("b"), pow_(sym("x"), num(2))),
                        param("c"),
                    ),
                    "FIRST_DERIVATIVE",
                    "Stops after one differentiation",
                ),
                distractor(
                    add(
                        mul(num(12), param("a"), pow_(sym("x"), num(3))),
                        mul(num(6), param("b"), pow_(sym("x"), num(2))),
                    ),
                    "KEEPS_EXPONENTS",
                    "Keeps the first-derivative exponents",
                ),
                distractor(
                    sub(
                        mul(num(12), param("a"), pow_(sym("x"), num(2))),
                        mul(num(6), param("b"), sym("x")),
                    ),
                    "SIGN_ERROR",
                    "Flips the sign of the linear term",
                ),
            ],
            text=symbolic("Find the second derivative of {expr} with respect to x."),
        ),
    )

    return [
        item(
            family=family,
            number=1,
            goal_kind="derivative",
            split=split,
            level="easy",
            template=easy,
            dimensions={
                "procedure_length": "low",
                "operation_type": "moderate",
                "conceptual_demand": "low",
                "answer_discrimination": "low",
            },
            reason="Nearest anchor is the easy linear equation, with one power-rule "
            "step in place of an inverse operation. The coefficient is multiplied by "
            "the exponent and the power drops by one, and the options fail a direct "
            "check of one of those two moves.",
        ),
        item(
            family=family,
            number=2,
            goal_kind="derivative",
            split=split,
            level="medium",
            template=medium,
            dimensions={
                "procedure_length": "moderate",
                "operation_type": "moderate",
                "conceptual_demand": "low",
                "answer_discrimination": "moderate",
            },
            reason="Nearest anchor is the easy linear equation, repeated across three "
            "terms. The learner applies the power rule term by term and drops the "
            "constant, and the options are eliminated by checking the exponent and "
            "coefficient pattern once.",
        ),
        item(
            family=family,
            number=3,
            goal_kind="derivative",
            split=split,
            level="hard",
            template=hard,
            dimensions={
                "procedure_length": "high",
                "operation_type": "moderate",
                "conceptual_demand": "moderate",
                "answer_discrimination": "high",
            },
            reason="Nearest anchor is the hard product derivative, because the item "
            "asks for a second derivative and so repeats the whole power-rule chain. "
            "The plausible options stop after one differentiation or keep the "
            "intermediate exponents, so the full repeated procedure is needed.",
        ),
    ]


def derivative_rules_items() -> list[Item]:
    family = "derivative-rules"
    topic = "university.derivative_rules"
    split = "held_out"

    easy = template(
        topic,
        [ParameterSpec(name="a", values=["2", "3"])],
        body(
            topic=topic,
            symbols=[x_symbol()],
            givens=domain_givens("x"),
            goal=Goal(
                kind="derivative",
                symbol="x",
                expr=mul(param("a"), sin(sym("x"))),
                order=1,
            ),
            recipe=answer_expression(mul(param("a"), cos(sym("x")))),
            distractors=[
                distractor(
                    mul(param("a"), sin(sym("x"))),
                    "NO_CHANGE",
                    "Returns the original function",
                ),
                distractor(
                    neg(mul(param("a"), sin(sym("x")))),
                    "SIGN_ERROR",
                    "Negates the sine term",
                ),
                distractor(
                    cos(sym("x")), "DROPS_COEFFICIENT", "Drops the constant multiple"
                ),
            ],
            text=symbolic("Differentiate {expr} with respect to x."),
        ),
    )

    medium = template(
        topic,
        [ParameterSpec(name="a", values=["2", "3"])],
        body(
            topic=topic,
            symbols=[x_symbol()],
            givens=domain_givens("x"),
            goal=Goal(
                kind="derivative",
                symbol="x",
                expr=sin(mul(param("a"), sym("x"))),
                order=1,
            ),
            recipe=answer_expression(mul(param("a"), cos(mul(param("a"), sym("x"))))),
            distractors=[
                distractor(
                    cos(mul(param("a"), sym("x"))),
                    "FORGETS_CHAIN",
                    "Omits the inner derivative",
                ),
                distractor(
                    neg(mul(param("a"), sin(mul(param("a"), sym("x"))))),
                    "WRONG_FUNCTION",
                    "Differentiates sine as negative sine",
                ),
                distractor(
                    mul(param("a"), sin(mul(param("a"), sym("x")))),
                    "NO_CHANGE",
                    "Returns the original function",
                ),
            ],
            text=symbolic("Differentiate {expr} with respect to x."),
        ),
    )

    hard = template(
        topic,
        [ParameterSpec(name="a", values=["2", "3"])],
        body(
            topic=topic,
            symbols=[x_symbol()],
            givens=domain_givens("x"),
            goal=Goal(
                kind="derivative",
                symbol="x",
                expr=mul(param("a"), pow_(sym("x"), num(2)), sin(sym("x"))),
                order=1,
            ),
            recipe=answer_expression(
                mul(
                    param("a"),
                    add(
                        mul(num(2), sym("x"), sin(sym("x"))),
                        mul(pow_(sym("x"), num(2)), cos(sym("x"))),
                    ),
                )
            ),
            distractors=[
                distractor(
                    mul(param("a"), num(2), sym("x"), cos(sym("x"))),
                    "DERIVATIVE_PRODUCT",
                    "Multiplies the two derivatives",
                ),
                distractor(
                    mul(param("a"), pow_(sym("x"), num(2)), cos(sym("x"))),
                    "DROPS_FIRST_TERM",
                    "Differentiates only the sine",
                ),
                distractor(
                    mul(
                        param("a"),
                        sub(
                            mul(num(2), sym("x"), sin(sym("x"))),
                            mul(pow_(sym("x"), num(2)), cos(sym("x"))),
                        ),
                    ),
                    "SIGN_ERROR",
                    "Subtracts the second product term",
                ),
            ],
            text=symbolic("Differentiate {expr} with respect to x."),
        ),
    )

    return [
        item(
            family=family,
            number=1,
            goal_kind="derivative",
            split=split,
            level="easy",
            template=easy,
            dimensions={
                "procedure_length": "low",
                "operation_type": "moderate",
                "conceptual_demand": "low",
                "answer_discrimination": "low",
            },
            reason="Nearest anchor is the easy linear equation, with a recalled "
            "trigonometric derivative. The constant multiple stays in place and sine "
            "becomes cosine, and the options are separated by direct recall of that "
            "one fact.",
        ),
        item(
            family=family,
            number=2,
            goal_kind="derivative",
            split=split,
            level="medium",
            template=medium,
            dimensions={
                "procedure_length": "moderate",
                "operation_type": "high",
                "conceptual_demand": "moderate",
                "answer_discrimination": "moderate",
            },
            reason="Nearest anchor is the hard product derivative, reduced to a single "
            "composition. The learner must recognise the inner linear function and "
            "multiply by its derivative, and the option without that factor is removed "
            "by the chain rule alone.",
        ),
        item(
            family=family,
            number=3,
            goal_kind="derivative",
            split=split,
            level="hard",
            template=hard,
            dimensions={
                "procedure_length": "high",
                "operation_type": "high",
                "conceptual_demand": "high",
                "answer_discrimination": "high",
            },
            reason="This is the worked hard product derivative anchor. The product "
            "rule couples the polynomial and trigonometric families, and each option "
            "uses a different wrong combination of the two derivatives, so the learner "
            "needs the rule and both term checks.",
        ),
    ]


def integral_polynomial_items() -> list[Item]:
    family = "integral-polynomial"
    topic = "university.integral_polynomial"
    split = "development"

    easy = template(
        topic,
        [ParameterSpec(name="a", values=["2", "3"])],
        body(
            topic=topic,
            symbols=[x_symbol()],
            givens=domain_givens("x"),
            goal=Goal(kind="integral", symbol="x", expr=param("a"), order=1),
            recipe=answer_expression(mul(param("a"), sym("x"))),
            distractors=[
                distractor(
                    param("a"),
                    "DROPS_VARIABLE",
                    "Leaves the constant without the variable",
                ),
                distractor(
                    div(mul(param("a"), pow_(sym("x"), num(2))), num(2)),
                    "USES_POWER_RULE",
                    "Applies the power rule to a constant",
                ),
                distractor(
                    mul(num(2), param("a"), sym("x")),
                    "DOUBLES_CONSTANT",
                    "Doubles the constant coefficient",
                ),
            ],
            text=symbolic("Find the antiderivative of {expr} with respect to x."),
        ),
    )

    medium = template(
        topic,
        [ParameterSpec(name="a", values=["2", "3"])],
        body(
            topic=topic,
            symbols=[x_symbol()],
            givens=domain_givens("x"),
            goal=Goal(
                kind="integral",
                symbol="x",
                expr=mul(param("a"), pow_(sym("x"), num(2))),
                order=1,
            ),
            recipe=answer_expression(
                div(mul(param("a"), pow_(sym("x"), num(3))), num(3))
            ),
            distractors=[
                distractor(
                    div(mul(param("a"), pow_(sym("x"), num(2))), num(2)),
                    "KEEPS_EXPONENT",
                    "Fails to raise the exponent",
                ),
                distractor(
                    mul(param("a"), pow_(sym("x"), num(3))),
                    "MISSING_DIVISION",
                    "Fails to divide by the new exponent",
                ),
                distractor(
                    div(mul(param("a"), pow_(sym("x"), num(3))), num(2)),
                    "WRONG_DIVISOR",
                    "Divides by the old exponent",
                ),
            ],
            text=symbolic("Find the antiderivative of {expr} with respect to x."),
        ),
    )

    hard = template(
        topic,
        [
            ParameterSpec(name="a", values=["2", "3"]),
            ParameterSpec(name="b", values=["1", "2"]),
        ],
        body(
            topic=topic,
            symbols=[x_symbol()],
            givens=domain_givens("x"),
            goal=Goal(
                kind="integral",
                symbol="x",
                expr=pow_(add(mul(param("a"), sym("x")), param("b")), num(2)),
                order=1,
            ),
            recipe=answer_expression(
                div(
                    pow_(add(mul(param("a"), sym("x")), param("b")), num(3)),
                    mul(num(3), param("a")),
                )
            ),
            distractors=[
                distractor(
                    div(
                        pow_(add(mul(param("a"), sym("x")), param("b")), num(3)), num(3)
                    ),
                    "FORGETS_INNER_FACTOR",
                    "Omits the inner derivative factor",
                ),
                distractor(
                    div(
                        mul(
                            param("a"),
                            pow_(add(mul(param("a"), sym("x")), param("b")), num(3)),
                        ),
                        num(3),
                    ),
                    "MULTIPLIES_INNER",
                    "Multiplies by the inner coefficient",
                ),
                distractor(
                    div(
                        pow_(add(mul(param("a"), sym("x")), param("b")), num(2)), num(2)
                    ),
                    "INTEGRATES_OUTER_ONLY",
                    "Raises only the outer power",
                ),
            ],
            text=symbolic("Find the antiderivative of {expr} with respect to x."),
        ),
    )

    return [
        item(
            family=family,
            number=1,
            goal_kind="integral",
            split=split,
            level="easy",
            template=easy,
            dimensions={
                "procedure_length": "low",
                "operation_type": "moderate",
                "conceptual_demand": "low",
                "answer_discrimination": "low",
            },
            reason="Nearest anchor is the easy linear equation, with the one recall "
            "step that a constant integrates to a linear term. The options are "
            "separated by checking whether the variable appears and whether the power "
            "rule was misapplied.",
        ),
        item(
            family=family,
            number=2,
            goal_kind="integral",
            split=split,
            level="medium",
            template=medium,
            dimensions={
                "procedure_length": "moderate",
                "operation_type": "moderate",
                "conceptual_demand": "moderate",
                "answer_discrimination": "moderate",
            },
            reason="Nearest anchor is the easy linear equation, extended by the "
            "reverse power rule. The learner must raise the exponent and divide by the "
            "new one, and each option omits one of those two linked moves.",
        ),
        item(
            family=family,
            number=3,
            goal_kind="integral",
            split=split,
            level="hard",
            template=hard,
            dimensions={
                "procedure_length": "high",
                "operation_type": "high",
                "conceptual_demand": "high",
                "answer_discrimination": "high",
            },
            reason="Nearest anchor is the hard product derivative, because the "
            "integrand is a composed square and the reverse chain rule must be "
            "recognised. The inner coefficient has to appear as a divisor, and the "
            "plausible options fail in different places in that substitution, so a "
            "full check by differentiation is needed.",
        ),
    ]


def integral_standard_items() -> list[Item]:
    family = "integral-standard"
    topic = "university.integral_standard"
    split = "held_out"

    easy = template(
        topic,
        [ParameterSpec(name="a", values=["2", "3"])],
        body(
            topic=topic,
            symbols=[x_symbol()],
            givens=domain_givens("x"),
            goal=Goal(
                kind="integral",
                symbol="x",
                expr=mul(param("a"), cos(sym("x"))),
                order=1,
            ),
            recipe=answer_expression(mul(param("a"), sin(sym("x")))),
            distractors=[
                distractor(
                    neg(mul(param("a"), sin(sym("x")))),
                    "SIGN_ERROR",
                    "Negates the sine term",
                ),
                distractor(
                    mul(param("a"), cos(sym("x"))), "NO_CHANGE", "Returns the integrand"
                ),
                distractor(
                    neg(mul(param("a"), cos(sym("x")))),
                    "WRONG_FUNCTION",
                    "Negates the cosine",
                ),
            ],
            text=symbolic("Find the antiderivative of {expr} with respect to x."),
        ),
    )

    medium = template(
        topic,
        [ParameterSpec(name="a", values=["2", "3"])],
        body(
            topic=topic,
            symbols=[x_symbol()],
            givens=domain_givens("x"),
            goal=Goal(
                kind="integral", symbol="x", expr=div(param("a"), sym("x")), order=1
            ),
            recipe=answer_expression(mul(param("a"), log(abs_(sym("x"))))),
            distractors=[
                distractor(
                    mul(param("a"), log(sym("x"))),
                    "MISSING_ABSOLUTE",
                    "Uses a logarithm without the absolute value",
                ),
                distractor(
                    div(param("a"), pow_(sym("x"), num(2))),
                    "POWER_RULE",
                    "Applies the power rule to a reciprocal",
                ),
                distractor(
                    neg(div(param("a"), pow_(sym("x"), num(2)))),
                    "SIGN_ERROR",
                    "Negates the reciprocal square",
                ),
            ],
            text=symbolic("Find the antiderivative of {expr} with respect to x."),
        ),
    )

    hard = template(
        topic,
        [
            ParameterSpec(name="a", values=["2", "3"]),
            ParameterSpec(name="b", values=["2", "3"]),
        ],
        body(
            topic=topic,
            symbols=[x_symbol()],
            givens=domain_givens("x"),
            goal=Goal(
                kind="integral",
                symbol="x",
                expr=mul(param("a"), exp(mul(param("b"), sym("x")))),
                order=1,
            ),
            recipe=answer_expression(
                div(mul(param("a"), exp(mul(param("b"), sym("x")))), param("b"))
            ),
            distractors=[
                distractor(
                    mul(param("a"), exp(mul(param("b"), sym("x")))),
                    "FORGETS_INNER_FACTOR",
                    "Omits the inner coefficient divisor",
                ),
                distractor(
                    mul(param("a"), param("b"), exp(mul(param("b"), sym("x")))),
                    "MULTIPLIES_INNER",
                    "Multiplies by the inner coefficient",
                ),
                distractor(
                    div(mul(param("a"), exp(sym("x"))), param("b")),
                    "WRONG_EXPONENT",
                    "Drops the inner coefficient from the exponent",
                ),
            ],
            text=symbolic("Find the antiderivative of {expr} with respect to x."),
        ),
    )

    medium_dimensions = {
        "procedure_length": "moderate",
        "operation_type": "moderate",
        "conceptual_demand": "moderate",
        "answer_discrimination": "moderate",
    }
    hard_dimensions = {
        "procedure_length": "high",
        "operation_type": "high",
        "conceptual_demand": "high",
        "answer_discrimination": "high",
    }

    return [
        item(
            family=family,
            number=1,
            goal_kind="integral",
            split=split,
            level="easy",
            template=easy,
            dimensions={
                "procedure_length": "low",
                "operation_type": "moderate",
                "conceptual_demand": "low",
                "answer_discrimination": "low",
            },
            reason="Nearest anchor is the easy linear equation, using a recalled "
            "trigonometric antiderivative. The constant multiple is unchanged and "
            "cosine integrates to sine, so the options are separated by one recall "
            "fact and a sign check.",
        ),
        item(
            family=family,
            number=2,
            goal_kind="integral",
            split=split,
            level="medium",
            template=medium,
            dimensions=medium_dimensions,
            reason="Nearest anchor is the easy linear equation, with a standard "
            "reciprocal integral. The learner must recall the logarithm and its "
            "absolute value, and the option without the absolute value is removed by "
            "the domain rule rather than by size.",
        ),
        item(
            family=family,
            number=3,
            goal_kind="integral",
            split=split,
            level="hard",
            template=hard,
            dimensions=hard_dimensions,
            reason="Nearest anchor is the hard product derivative, because the "
            "exponential has a linear inner function. The reverse chain rule requires "
            "dividing by the inner coefficient, and the plausible options fail in the "
            "exponent or the factor, so differentiation of each option is needed to "
            "decide.",
        ),
    ]


def determinant_items() -> list[Item]:
    family = "determinant-matrix"
    topic = "university.determinant"
    split = "development"

    easy = template(
        topic,
        [
            ParameterSpec(name="a", values=["2", "3"]),
            ParameterSpec(name="b", values=["1", "2"]),
            ParameterSpec(name="c", values=["1", "2"]),
            ParameterSpec(name="d", values=["3", "4"]),
        ],
        body(
            topic=topic,
            symbols=[SymbolSpec(name="m", kind="given", domain="integer")],
            givens=domain_givens("m"),
            goal=Goal(
                kind="determinant",
                matrix=[[param("a"), param("b")], [param("c"), param("d")]],
            ),
            recipe=answer_numeric(
                sub(mul(param("a"), param("d")), mul(param("b"), param("c")))
            ),
            distractors=[
                distractor(
                    add(mul(param("a"), param("d")), mul(param("b"), param("c"))),
                    "SIGN_ERROR",
                    "Adds the cross term instead of subtracting",
                ),
                distractor(
                    sub(mul(param("a"), param("b")), mul(param("c"), param("d"))),
                    "MINOR_SWAP",
                    "Swaps the diagonal pairings",
                ),
                distractor(
                    mul(param("a"), param("d")),
                    "MISSING_MINOR",
                    "Keeps only the main diagonal product",
                ),
            ],
            text=symbolic("Find the determinant of {matrix}."),
        ),
    )

    medium = template(
        topic,
        [
            ParameterSpec(name="a", values=["2", "3"]),
            ParameterSpec(name="d", values=["2", "3"]),
            ParameterSpec(name="e", values=["1", "2"]),
            ParameterSpec(name="f", values=["1", "2"]),
            ParameterSpec(name="g", values=["4", "5"]),
        ],
        body(
            topic=topic,
            symbols=[SymbolSpec(name="m", kind="given", domain="integer")],
            givens=domain_givens("m"),
            goal=Goal(
                kind="determinant",
                matrix=[
                    [param("a"), num(1), num(2)],
                    [num(0), param("d"), param("e")],
                    [num(0), param("f"), param("g")],
                ],
            ),
            recipe=answer_numeric(
                mul(
                    param("a"),
                    sub(mul(param("d"), param("g")), mul(param("e"), param("f"))),
                )
            ),
            distractors=[
                distractor(
                    mul(
                        param("a"),
                        add(mul(param("d"), param("g")), mul(param("e"), param("f"))),
                    ),
                    "SIGN_ERROR",
                    "Adds the minor instead of subtracting",
                ),
                distractor(
                    sub(mul(param("d"), param("g")), mul(param("e"), param("f"))),
                    "MISSING_LEADING_FACTOR",
                    "Drops the leading entry factor",
                ),
                distractor(
                    mul(param("a"), param("d"), param("g")),
                    "MISSING_MINOR",
                    "Keeps only the main diagonal product",
                ),
            ],
            text=symbolic("Find the determinant of {matrix}."),
        ),
    )

    hard = template(
        topic,
        [
            ParameterSpec(name="a", values=["1", "2"]),
            ParameterSpec(name="b", values=["1", "2"]),
            ParameterSpec(name="c", values=["2", "3"]),
            ParameterSpec(name="d", values=["2", "3"]),
        ],
        body(
            topic=topic,
            symbols=[SymbolSpec(name="m", kind="given", domain="integer")],
            givens=domain_givens("m"),
            goal=Goal(
                kind="determinant",
                matrix=[
                    [param("a"), param("b"), num(1)],
                    [param("c"), param("d"), num(2)],
                    [num(1), num(3), num(4)],
                ],
            ),
            recipe=answer_numeric(
                add(
                    mul(param("a"), sub(mul(num(4), param("d")), num(6))),
                    mul(neg(param("b")), sub(mul(num(4), param("c")), num(2))),
                    sub(mul(num(3), param("c")), param("d")),
                )
            ),
            distractors=[
                distractor(
                    add(
                        mul(param("a"), sub(mul(num(4), param("d")), num(6))),
                        mul(param("b"), sub(mul(num(4), param("c")), num(2))),
                        sub(mul(num(3), param("c")), param("d")),
                    ),
                    "COFACTOR_SIGN",
                    "Uses the wrong sign for the second cofactor",
                ),
                distractor(
                    sub(
                        add(
                            mul(param("a"), sub(mul(num(4), param("d")), num(6))),
                            mul(param("b"), sub(mul(num(4), param("c")), num(2))),
                        ),
                        sub(mul(num(3), param("c")), param("d")),
                    ),
                    "THIRD_SIGN",
                    "Uses the wrong sign for the third cofactor",
                ),
                distractor(
                    mul(param("a"), param("d"), num(4)),
                    "MAIN_DIAGONAL",
                    "Multiplies the main diagonal only",
                ),
            ],
            text=symbolic("Find the determinant of {matrix}."),
        ),
    )

    return [
        item(
            family=family,
            number=1,
            goal_kind="determinant",
            split=split,
            level="easy",
            template=easy,
            dimensions={
                "procedure_length": "low",
                "operation_type": "moderate",
                "conceptual_demand": "low",
                "answer_discrimination": "low",
            },
            reason="Nearest anchor is the easy linear equation, with the two-by-two "
            "determinant as one recalled formula. The options are separated by "
            "checking the subtraction and the pairing of the entries, which is a "
            "single rule.",
        ),
        item(
            family=family,
            number=2,
            goal_kind="determinant",
            split=split,
            level="medium",
            template=medium,
            dimensions={
                "procedure_length": "moderate",
                "operation_type": "high",
                "conceptual_demand": "moderate",
                "answer_discrimination": "moderate",
            },
            reason="Nearest anchor is the medium quadratic expansion, because a "
            "three-by-three determinant is reduced by expansion along the zero column. "
            "The learner must form the remaining two-by-two minor and multiply by the "
            "leading entry, and one cofactor rule eliminates each option.",
        ),
        item(
            family=family,
            number=3,
            goal_kind="determinant",
            split=split,
            level="hard",
            template=hard,
            dimensions={
                "procedure_length": "high",
                "operation_type": "high",
                "conceptual_demand": "high",
                "answer_discrimination": "high",
            },
            reason="Nearest anchor is the hard product derivative, because a general "
            "three-by-three determinant needs three cofactors with alternating signs. "
            "Each plausible option flips a different cofactor or keeps only the "
            "diagonal, so the full expansion is needed to decide.",
        ),
    ]


def all_items() -> list[Item]:
    builders = (
        arithmetic_items,
        percentage_items,
        powers_roots_items,
        proportion_items,
        function_evaluation_items,
        linear_equation_items,
        quadratic_equation_items,
        linear_system_items,
        simplify_expression_items,
        algebraic_fraction_items,
        exponent_law_items,
        factor_quadratic_items,
        factor_special_items,
        expand_binomial_items,
        expand_special_items,
        derivative_polynomial_items,
        derivative_rules_items,
        integral_polynomial_items,
        integral_standard_items,
        determinant_items,
    )
    items: list[Item] = []
    for builder in builders:
        items.extend(builder())
    return items


def candidate_for(item: Item) -> MathTemplateCandidate:
    return MathTemplateCandidate(
        template_id=f"math.reference.{item.question_id}",
        difficulty=item.level,
        item=item.template,
    )


def check_template(item: Item) -> list[str]:
    failures: list[str] = []
    template = item.template
    correctness = validate_template(template, aspect="correctness")
    if correctness.report.status != "passed":
        failures.append("correctness: " + "; ".join(correctness.report.findings))
    if template.body.goal.kind in FORM_SENSITIVE_GOALS:
        form = validate_template(template, aspect="form")
        if form.report.status != "passed":
            failures.append("form: " + "; ".join(form.report.findings))
    if template.body.text.mode == "prose":
        verdict = math_fidelity_plugin().check_anchors(
            template.body, template.body.text.template
        )
        if verdict.status != "passed":
            failures.append("anchors: " + "; ".join(verdict.reasons))
    return failures


def validated_item(item: Item, report: Any) -> ValidatedMathTemplate:
    payload = report.model_dump(exclude={"report"}) | {
        "evidence": [ValidationEvidence(check="math_verify_item_spec", status="passed")]
    }
    from edcraft_validator.domains.math.math_schemas import MathValidationSummary

    return ValidatedMathTemplate(
        artifact_id=f"math-reference-{item.question_id}",
        template=candidate_for(item),
        validation=MathValidationSummary.model_validate(payload),
    )


def seed_zero_instance(item: Item) -> dict[str, Any]:
    report = validate_template(item.template, aspect="correctness")
    if report.report.status != "passed":
        raise ValueError(
            f"{item.question_id} failed correctness: {report.report.findings}"
        )
    instance = generate_math_question(validated_item(item, report), 0)
    return {
        "question": instance.question,
        "options": [
            {"id": letter, "value": choice}
            for letter, choice in zip("ABCD", instance.choices, strict=True)
        ],
        "correct_option": "ABCD"[instance.correct_index],
    }


def load_owner_fields() -> dict[str, dict[str, Any]]:
    if not DATASET_PATH.exists():
        return {}
    previous = json.loads(DATASET_PATH.read_text())
    return {
        entry["question_id"]: {
            "owner_difficulty": entry.get("owner_difficulty"),
            "owner_dimensions": entry.get("owner_dimensions"),
            "owner_notes": entry.get("owner_notes"),
        }
        for entry in previous.get("questions", [])
    }


def build_dataset(items: list[Item]) -> dict[str, Any]:
    owners = load_owner_fields()
    questions = []
    for entry in items:
        owner = owners.get(entry.question_id, {})
        questions.append(
            {
                "question_id": entry.question_id,
                "family": entry.family,
                "goal_kind": entry.goal_kind,
                "split": entry.split,
                "template": entry.template.model_dump(mode="json"),
                "instance": seed_zero_instance(entry),
                "proposed_difficulty": entry.level,
                "proposed_dimensions": entry.dimensions,
                "proposed_reason": entry.reason,
                "owner_difficulty": owner.get("owner_difficulty"),
                "owner_dimensions": owner.get("owner_dimensions"),
                "owner_notes": owner.get("owner_notes"),
            }
        )
    return {
        "dataset_id": "math-template-difficulty-2026-11-16-math-ir-v0.1",
        "rubric_version": RUBRIC_VERSION,
        "assessment_conditions": ASSESSMENT_CONDITIONS,
        "review_metadata": {
            "status": "proposed, awaiting owner review",
            "reviewer_count": 1,
            "reviewer": "project owner",
            "independent_second_rater": False,
            "note": (
                "Proposed ratings are AI drafted. They become reference labels only "
                "after the project owner reviews and fills the owner fields."
            ),
        },
        "questions": questions,
    }


def render_review_sheet(dataset: dict[str, Any]) -> str:
    lines = [
        "# Mathematics difficulty review sheet",
        "",
        "Rubric version: `math-ir-v0.1`.",
        "",
        "Proposed ratings are AI drafted and become reference labels only after",
        "owner review. For each item, read the question and options first, then",
        "compare your own rating with the proposal below it.",
        "",
    ]
    for entry in dataset["questions"]:
        lines.extend(
            [
                f"## {entry['question_id']}",
                "",
                f"Family: `{entry['family']}`  ",
                f"Goal kind: `{entry['goal_kind']}`  ",
                f"Split: `{entry['split']}`",
                "",
                f"**Question.** {entry['instance']['question']}",
                "",
            ]
        )
        for option in entry["instance"]["options"]:
            marker = (
                " (correct)"
                if option["id"] == entry["instance"]["correct_option"]
                else ""
            )
            lines.append(f"- {option['id']}. {option['value']}{marker}")
        lines.extend(
            [
                "",
                f"Correct option: **{entry['instance']['correct_option']}**",
                "",
                f"Proposed level: **{entry['proposed_difficulty']}**  ",
                "Proposed dimensions: "
                + ", ".join(
                    f"{name}={value}"
                    for name, value in entry["proposed_dimensions"].items()
                ),
                "",
                f"Proposed reason: {entry['proposed_reason']}",
                "",
                "Your level:",
                "",
                "Your dimensions:",
                "",
                "Notes:",
                "",
                "---",
                "",
            ]
        )
    return "\n".join(lines)


def main() -> None:
    items = all_items()
    failures: list[str] = []
    for entry in items:
        problems = check_template(entry)
        if problems:
            failures.append(f"{entry.question_id}: " + " | ".join(problems))
    if failures:
        raise SystemExit("template checks failed:\n" + "\n".join(failures))

    dataset = build_dataset(items)
    DATASET_DIR.mkdir(parents=True, exist_ok=True)
    DATASET_PATH.write_text(json.dumps(dataset, indent=2) + "\n")
    REVIEW_PATH.write_text(render_review_sheet(dataset))
    print(f"wrote {len(dataset['questions'])} questions to {DATASET_PATH}")
    print(f"wrote review sheet to {REVIEW_PATH}")


if __name__ == "__main__":
    main()
