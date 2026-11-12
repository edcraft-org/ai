"""JSON-only isolated worker for pilot qualification and recipe execution."""

from __future__ import annotations

import json
import platform
import random
import sys
import time
from dataclasses import dataclass, field
from importlib.metadata import version as package_version
from typing import Any

import hypothesis
from hypothesis import HealthCheck, Phase, example, given, seed, settings
from hypothesis import strategies as st

from edcraft_validator.application.check_pilot.models import (
    MAX_RECIPE_CASES,
    RENDERER_VERSION,
    CheckRecipeDefinition,
    PilotQualificationSettings,
    PolynomialFamily,
    Qualification,
    QualificationStatus,
)
from edcraft_validator.application.check_pilot.operations import (
    CompiledRecipe,
    RecipeCompileError,
    compile_recipe,
    execute_recipe,
)
from edcraft_validator.application.check_pilot.polynomial import (
    Polynomial,
    alternate_polynomial_forms,
    derivative_via_coefficients,
    parse_polynomial,
    render_polynomial,
    semantic_mutations,
)
from edcraft_validator.application.check_pilot.question import (
    QuestionBuildError,
    build_instance,
    guard_instance,
)


class _BudgetExceeded(BaseException):
    """Stop Hypothesis immediately, including during shrinking."""


class _CaseFailure(Exception):
    def __init__(self, counterexample: dict[str, Any]) -> None:
        super().__init__(counterexample.get("reason", "case failed"))
        self.counterexample = counterexample


@dataclass
class _RunState:
    config: PilotQualificationSettings
    started: float = field(default_factory=time.perf_counter)
    execution_calls: int = 0
    accepted: set[tuple[int, ...]] = field(default_factory=set)

    @property
    def deadline(self) -> float:
        # Leave a short margin so the worker can report before the hard kill.
        return max(0.5, self.config.timeout_seconds - 1.0)

    def reserve(self) -> None:
        if time.perf_counter() - self.started >= self.deadline:
            raise _BudgetExceeded()
        if self.execution_calls >= self.config.max_execution_calls:
            raise _BudgetExceeded()
        self.execution_calls += 1


def _versions() -> dict[str, str]:
    return {
        "check_pilot": "1",
        "differentiation": "sympy",
        "sympy": package_version("sympy"),
        "oracle": "coefficient-arithmetic/1",
        "polynomial_oracle": "coefficient-arithmetic/1",
        "recipe_compiler": "1",
        "renderer": RENDERER_VERSION,
        "question_builder": RENDERER_VERSION,
        "hypothesis": hypothesis.__version__,
        "python": platform.python_version(),
    }


def _qualification(
    *,
    status: QualificationStatus,
    config: PilotQualificationSettings,
    seed_value: int,
    state: _RunState | None = None,
    findings: list[str] | None = None,
    counterexample: dict[str, Any] | None = None,
    accepted_cases: int | None = None,
) -> Qualification:
    if accepted_cases is not None:
        accepted = accepted_cases
    else:
        accepted = len(state.accepted) if state is not None else 0
    return Qualification(
        status=status,
        accepted_cases=accepted,
        execution_calls=state.execution_calls if state else 0,
        seed=seed_value,
        max_examples=config.max_examples,
        max_execution_calls=config.max_execution_calls,
        timeout_seconds=config.timeout_seconds,
        counterexample=counterexample,
        findings=findings or [],
        versions=_versions(),
    )


def _compile_failure(
    definition: Any, config: PilotQualificationSettings, seed_value: int
) -> Qualification | None:
    try:
        compile_recipe(CheckRecipeDefinition.model_validate(definition))
    except RecipeCompileError as exc:
        findings = []
        for finding in exc.findings:
            if exc.unknown_capability:
                findings.append(f"Development needed: {finding}")
            else:
                findings.append(f"recipe did not compile: {finding}")
        return _qualification(
            status="failed",
            config=config,
            seed_value=seed_value,
            findings=findings or ["recipe did not compile"],
        )
    return None


def _polynomial_strategy() -> st.SearchStrategy[Polynomial]:
    return st.integers(min_value=0, max_value=5).flatmap(
        lambda degree: st.lists(
            st.integers(min_value=-20, max_value=20),
            min_size=degree + 1,
            max_size=degree + 1,
        ).map(Polynomial.from_coefficients)
    )


def _boundary_polynomials() -> list[Polynomial]:
    values = [
        [0],
        [1],
        [-1],
        [0, 1],
        [0, -1],
        [5, -2],
        [-20, 0, 20],
        [1, -2, 0, 3],
        [0, 0, 0, 0, 0, 1],
        [1, 1, 1, 1, 1, 1],
        [-1, -1, -1, -1, -1, -1],
    ]
    return [Polynomial.from_coefficients(value) for value in values]


def _case_seed(seed_value: int, coefficients: tuple[int, ...], salt: int) -> int:
    value = (seed_value + salt) & 0x7FFF_FFFF
    for coefficient in coefficients:
        value = (value * 131 + coefficient + 10_007) & 0xFFFF_FFFF_FFFF_FFFF
    return value


def _run_recipe_property(
    *,
    compiled: CompiledRecipe,
    state: _RunState,
    seed_value: int,
    max_examples: int,
    salt: int,
    expose_counterexample: bool,
    include_boundaries: bool,
) -> tuple[dict[str, Any] | None, Qualification | None]:
    def check_case(polynomial: Polynomial) -> None:
        state.reserve()
        coefficients = tuple(polynomial.coefficients)
        if coefficients in state.accepted:
            return
        expected = derivative_via_coefficients(polynomial)
        correct_forms = alternate_polynomial_forms(expected)
        rng = random.Random(_case_seed(seed_value, coefficients, salt))
        wrongs = semantic_mutations(expected, 3, rng=rng)
        if len(wrongs) < 2:
            raise _CaseFailure(
                {
                    "reason": "could not build distinct semantic mutations",
                    "problem": render_polynomial(polynomial),
                    "coefficients": list(coefficients),
                }
            )
        for form in correct_forms:
            state.reserve()
            try:
                candidate = parse_polynomial(form)
            except ValueError as exc:
                raise _CaseFailure(
                    {
                        "reason": f"alternate correct form did not parse: {exc}",
                        "problem": render_polynomial(polynomial),
                        "coefficients": list(coefficients),
                        "expected": render_polynomial(expected),
                        "candidate": form[:200],
                    }
                ) from None
            result = execute_recipe(compiled, polynomial, candidate)
            if not result.verdict:
                raise _CaseFailure(
                    {
                        "reason": "correct answer rejected",
                        "problem": result.problem,
                        "coefficients": list(coefficients),
                        "expected": result.expected,
                        "candidate": form[:200],
                    }
                )
        for wrong in wrongs:
            if wrong == expected:
                raise _CaseFailure(
                    {
                        "reason": "mutation did not differ from the expected value",
                        "problem": render_polynomial(polynomial),
                        "coefficients": list(coefficients),
                    }
                )
            state.reserve()
            result = execute_recipe(compiled, polynomial, wrong)
            if result.verdict:
                raise _CaseFailure(
                    {
                        "reason": "wrong answer accepted",
                        "problem": result.problem,
                        "coefficients": list(coefficients),
                        "expected": result.expected,
                        "candidate": render_polynomial(wrong)[:200],
                    }
                )
        state.accepted.add(coefficients)

    @seed(seed_value)
    @settings(
        max_examples=max_examples,
        deadline=None,
        database=None,
        report_multiple_bugs=False,
        phases=(Phase.explicit, Phase.generate, Phase.shrink),
        suppress_health_check=[HealthCheck.too_slow],
    )
    @given(polynomial=_polynomial_strategy())
    def wrapped(polynomial: Polynomial) -> None:
        check_case(polynomial)

    if include_boundaries:
        for polynomial in reversed(_boundary_polynomials()):
            wrapped = example(polynomial=polynomial)(wrapped)
    try:
        wrapped()
    except _BudgetExceeded:
        return None, _qualification(
            status="inconclusive",
            config=state.config,
            seed_value=seed_value,
            state=state,
            findings=["qualification budget was exhausted before a verdict"],
        )
    except _CaseFailure as exc:
        counterexample = exc.counterexample if expose_counterexample else None
        finding = (
            "held-out evaluation did not confirm the recipe"
            if not expose_counterexample
            else f"counterexample: {exc.counterexample.get('reason', 'case failed')}"
        )
        return counterexample or {"withheld": True}, _qualification(
            status="failed",
            config=state.config,
            seed_value=seed_value,
            state=state,
            findings=[finding],
            counterexample=counterexample,
        )
    return None, None


def qualify_recipe_payload(payload: dict[str, Any]) -> Qualification:
    config = PilotQualificationSettings.model_validate(payload.get("settings", {}))
    seed_value = int(payload.get("seed", 0))
    if seed_value < 0:
        seed_value = 0
    definition = payload.get("definition")
    failure = _compile_failure(definition, config, seed_value)
    if failure is not None:
        return failure
    compiled = compile_recipe(CheckRecipeDefinition.model_validate(definition))
    state = _RunState(config)
    _, outcome = _run_recipe_property(
        compiled=compiled,
        state=state,
        seed_value=seed_value,
        max_examples=config.max_examples,
        salt=0,
        expose_counterexample=True,
        include_boundaries=True,
    )
    if outcome is not None:
        return outcome
    _, held_out = _run_recipe_property(
        compiled=compiled,
        state=state,
        seed_value=seed_value + 7919,
        max_examples=max(4, config.max_examples // 2),
        salt=104_729,
        expose_counterexample=False,
        include_boundaries=False,
    )
    if held_out is not None:
        return held_out
    if len(state.accepted) < 2:
        return _qualification(
            status="inconclusive",
            config=config,
            seed_value=seed_value,
            state=state,
            findings=["not enough sampled cases were accepted for qualification"],
        )
    return _qualification(
        status="passed",
        config=config,
        seed_value=seed_value,
        state=state,
        findings=["No counterexample found in sampled cases"],
    )


def _family_strategy(family: PolynomialFamily) -> st.SearchStrategy[dict[str, int]]:
    return st.fixed_dictionaries(
        {
            f"a{domain.exponent}": st.sampled_from(domain.values)
            for domain in family.coefficients
        }
    )


def _family_boundaries(family: PolynomialFamily) -> list[dict[str, int]]:
    base = {f"a{domain.exponent}": domain.values[0] for domain in family.coefficients}
    last = {f"a{domain.exponent}": domain.values[-1] for domain in family.coefficients}
    examples = [base, last]
    for domain in family.coefficients:
        for value in (min(domain.values), max(domain.values)):
            changed = dict(base)
            changed[f"a{domain.exponent}"] = value
            examples.append(changed)
    unique: dict[str, dict[str, int]] = {}
    for item in examples:
        unique[json.dumps(item, sort_keys=True)] = item
    return list(unique.values())


def qualify_template_payload(payload: dict[str, Any]) -> Qualification:
    config = PilotQualificationSettings.model_validate(payload.get("settings", {}))
    seed_value = int(payload.get("seed", 0))
    if seed_value < 0:
        seed_value = 0
    definition = payload.get("definition")
    failure = _compile_failure(definition, config, seed_value)
    if failure is not None:
        return failure
    compiled = compile_recipe(CheckRecipeDefinition.model_validate(definition))
    family = PolynomialFamily.model_validate(payload["family"])
    state = _RunState(config)

    def check_case(assignment: dict[str, int]) -> None:
        state.reserve()
        coefficients = tuple(
            assignment[f"a{domain.exponent}"] for domain in family.coefficients
        )
        if coefficients in state.accepted:
            return
        try:
            instance = build_instance(family, coefficients, seed=seed_value)
        except QuestionBuildError as exc:
            raise _CaseFailure(
                {
                    "reason": f"renderer rejected the assignment: {exc}",
                    "assignment": assignment,
                }
            ) from None
        guard_findings = guard_instance(
            instance, num_distractors=family.num_distractors
        )
        if guard_findings:
            raise _CaseFailure(
                {
                    "reason": guard_findings[0],
                    "assignment": assignment,
                    "expected": render_polynomial(instance.expected),
                    "choices": list(instance.choices),
                }
            )
        state.reserve()
        result = execute_recipe(compiled, instance.problem, instance.expected)
        if not result.verdict:
            raise _CaseFailure(
                {
                    "reason": "pinned recipe rejected the correct answer",
                    "assignment": assignment,
                    "expected": result.expected,
                    "candidate": render_polynomial(instance.expected),
                }
            )
        for text in instance.distractors:
            state.reserve()
            candidate = parse_polynomial(text)
            result = execute_recipe(compiled, instance.problem, candidate)
            if result.verdict:
                raise _CaseFailure(
                    {
                        "reason": "pinned recipe accepted a distractor",
                        "assignment": assignment,
                        "expected": result.expected,
                        "candidate": text[:200],
                    }
                )
        state.accepted.add(coefficients)

    @seed(seed_value)
    @settings(
        max_examples=config.max_examples,
        deadline=None,
        database=None,
        report_multiple_bugs=False,
        phases=(Phase.explicit, Phase.generate, Phase.shrink),
        suppress_health_check=[HealthCheck.too_slow],
    )
    @given(assignment=_family_strategy(family))
    def wrapped(assignment: dict[str, int]) -> None:
        check_case(assignment)

    for assignment in reversed(_family_boundaries(family)):
        wrapped = example(assignment=assignment)(wrapped)
    try:
        wrapped()
    except _BudgetExceeded:
        return _qualification(
            status="inconclusive",
            config=config,
            seed_value=seed_value,
            state=state,
            findings=["template qualification budget was exhausted before a verdict"],
        )
    except _CaseFailure as exc:
        return _qualification(
            status="failed",
            config=config,
            seed_value=seed_value,
            state=state,
            findings=[f"counterexample: {exc.counterexample.get('reason', 'failed')}"],
            counterexample=exc.counterexample,
        )
    if len(state.accepted) < 2:
        return _qualification(
            status="inconclusive",
            config=config,
            seed_value=seed_value,
            state=state,
            findings=["not enough sampled family assignments were accepted"],
        )
    return _qualification(
        status="passed",
        config=config,
        seed_value=seed_value,
        state=state,
        findings=["No counterexample found in sampled cases"],
    )


def execute_recipe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    definition = CheckRecipeDefinition.model_validate(payload["definition"])
    compiled = compile_recipe(definition)
    problem = parse_polynomial(payload["problem"])
    candidate = parse_polynomial(payload["candidate"])
    result = execute_recipe(compiled, problem, candidate)
    return {"result": result.model_dump(mode="json")}


def execute_recipe_cases_payload(payload: dict[str, Any]) -> dict[str, Any]:
    cases = payload.get("cases", [])
    if not isinstance(cases, list) or len(cases) > MAX_RECIPE_CASES:
        raise ValueError(f"recipe cases must be a list of at most {MAX_RECIPE_CASES}")
    definition = CheckRecipeDefinition.model_validate(payload["definition"])
    compiled = compile_recipe(definition)
    results = []
    for case in cases:
        problem = parse_polynomial(case["problem"])
        candidate = parse_polynomial(case["candidate"])
        results.append(
            execute_recipe(compiled, problem, candidate).model_dump(mode="json")
        )
    return {"results": results}


def _run(payload: dict[str, Any]) -> dict[str, Any]:
    operation = payload.get("operation")
    if operation == "qualify_recipe":
        qualification = qualify_recipe_payload(payload)
        return {"qualification": qualification.model_dump(mode="json")}
    if operation == "qualify_template":
        return {
            "qualification": qualify_template_payload(payload).model_dump(mode="json")
        }
    if operation == "execute_recipe":
        return execute_recipe_payload(payload)
    if operation == "execute_recipe_cases":
        return execute_recipe_cases_payload(payload)
    raise ValueError(f"unknown pilot operation {operation!r}")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        response = _run(payload)
    except Exception as exc:  # noqa: BLE001 - the boundary reports all failures
        json.dump(
            {
                "error": {
                    "type": type(exc).__name__,
                    "message": str(exc)[:1000],
                }
            },
            sys.stdout,
        )
        return 0
    json.dump(response, sys.stdout, allow_nan=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
