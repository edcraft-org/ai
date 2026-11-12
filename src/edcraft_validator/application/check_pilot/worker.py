"""JSON-only isolated worker for pilot qualification and recipe execution."""

from __future__ import annotations

import json
import platform
import random
import sys
import time
from dataclasses import dataclass, field
from typing import Any

import hypothesis
from hypothesis import HealthCheck, Phase, example, given, seed, settings
from hypothesis import strategies as st

from edcraft_validator.application.check_pilot.batch_generation import (
    generate_batch as build_generation_batch,
)
from edcraft_validator.application.check_pilot.contracts import (
    scope_from_recipe_operation_set,
    trusted_contract_scope,
)
from edcraft_validator.application.check_pilot.models import (
    MAX_RECIPE_CASES,
    SUPPORTED_SCOPE,
    CheckRecipeDefinition,
    CheckRef,
    ContractScope,
    PilotQualificationSettings,
    PilotTemplateDefinition,
    PolynomialFamily,
    PolynomialRelation,
    PolynomialScope,
    Qualification,
    QualificationPhase,
    QualificationStatus,
    RealSolutionSet,
    RelationKind,
    SolveFamily,
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
    build_solve_instance,
    guard_instance,
    guard_solve_instance,
)
from edcraft_validator.application.check_pilot.seeds import coefficient_seed
from edcraft_validator.application.check_pilot.solution_sets import (
    SolutionSetError,
    render_relation,
    render_solution_set,
    solution_set_model,
    solution_set_mutations,
    solve_relation_independently,
)
from edcraft_validator.application.check_pilot.versions import static_versions


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
    accepted: set[tuple[object, ...]] = field(default_factory=set)

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
        **static_versions(),
        "hypothesis": hypothesis.__version__,
        "python": platform.python_version(),
    }


def _qualification(
    *,
    status: QualificationStatus,
    config: PilotQualificationSettings,
    seed_value: int,
    phase: QualificationPhase = "sampling",
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
        phase=phase,
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
    definition: Any,
    config: PilotQualificationSettings,
    seed_value: int,
    scope: PolynomialScope | ContractScope | None = None,
) -> Qualification | None:
    try:
        compile_recipe(
            CheckRecipeDefinition.model_validate(definition),
            scope=scope or SUPPORTED_SCOPE,
        )
    except RecipeCompileError as exc:
        findings = []
        for finding in exc.findings:
            if exc.unknown_capability:
                findings.append(f"Development needed: {finding}")
            else:
                findings.append(f"recipe did not compile: {finding}")
        return _qualification(
            status="error",
            phase="compilation",
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
        rng = random.Random(coefficient_seed(seed_value, coefficients, salt=salt))
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


def _scope_from_payload(
    payload: dict[str, Any], definition: CheckRecipeDefinition
) -> PolynomialScope | ContractScope:
    raw = payload.get("scope")
    if isinstance(raw, dict):
        if "contract_id" in raw:
            return trusted_contract_scope(ContractScope.model_validate(raw))
        return PolynomialScope.model_validate(raw)
    return scope_from_recipe_operation_set(definition.operation_set)


def _solve_relation_strategy(
    scope: ContractScope,
) -> st.SearchStrategy[PolynomialRelation]:
    relations: list[RelationKind] = []
    for item in scope.relations:
        if item != "none":
            relations.append(item)
    if not relations:
        relations = ["eq"]
    bound = scope.max_abs_coefficient

    def for_degree(
        relation: RelationKind, degree: int
    ) -> st.SearchStrategy[PolynomialRelation]:
        return st.lists(
            st.integers(min_value=-bound, max_value=bound),
            min_size=degree + 1,
            max_size=degree + 1,
        ).map(
            lambda values: PolynomialRelation(
                relation=relation,
                coefficients=[
                    *values[:-1],
                    values[-1] if values[-1] != 0 else 1,
                ],
            )
        )

    return st.sampled_from(relations).flatmap(
        lambda relation: st.integers(min_value=0, max_value=scope.max_degree).flatmap(
            lambda degree: for_degree(relation, degree)
        )
    )


def _solve_boundary_relations(scope: ContractScope) -> list[PolynomialRelation]:
    relations: list[RelationKind] = []
    for item in scope.relations:
        if item != "none":
            relations.append(item)
    desired: list[tuple[RelationKind, list[int]]] = []
    for relation in relations:
        if relation == "eq":
            desired.extend(
                [
                    (relation, [-4, 0, 1]),
                    (relation, [1, -2, 1]),
                    (relation, [1, 0, 1]),
                    (relation, [2, -4]),
                    (relation, [0, 0, 0]),
                    (relation, [3]),
                ]
            )
        else:
            desired.extend(
                [
                    (relation, [-4, 0, 1]),
                    (relation, [1, -2, 1]),
                    (relation, [1, 0, 1]),
                    (relation, [-1, 0, 1]),
                    (relation, [2, -4]),
                    (relation, [0, 0, 0]),
                    (relation, [1]),
                ]
            )
    items: list[PolynomialRelation] = []
    seen: set[str] = set()
    for relation, coefficients in desired:
        model = PolynomialRelation(relation=relation, coefficients=coefficients)
        key = json.dumps(model.model_dump(mode="json"), sort_keys=True)
        if key not in seen:
            seen.add(key)
            items.append(model)
    return items


def _run_solve_recipe_property(
    *,
    compiled: CompiledRecipe,
    scope: ContractScope,
    state: _RunState,
    seed_value: int,
    max_examples: int,
    salt: int,
    expose_counterexample: bool,
    include_boundaries: bool,
) -> tuple[dict[str, Any] | None, Qualification | None]:
    def check_case(relation: PolynomialRelation) -> None:
        state.reserve()
        key = (relation.relation, tuple(relation.coefficients))
        if key in state.accepted:
            return
        coefficients = tuple(relation.coefficients)
        try:
            expected = solve_relation_independently(relation.relation, coefficients)
        except SolutionSetError as exc:
            raise _CaseFailure(
                {
                    "reason": f"independent oracle rejected the relation: {exc}",
                    "problem": render_relation(relation.relation, coefficients),
                }
            ) from None
        state.reserve()
        correct = solution_set_model(expected)
        result = execute_recipe(compiled, relation, correct)
        if not result.verdict:
            raise _CaseFailure(
                {
                    "reason": "correct complete solution set rejected",
                    "problem": result.problem,
                    "expected": result.expected,
                    "candidate": result.candidate,
                }
            )
        rng = random.Random(coefficient_seed(seed_value, coefficients, salt=salt))
        wrongs = solution_set_mutations(
            relation.relation, coefficients, expected, 3, rng=rng
        )
        if len(wrongs) < 2:
            raise _CaseFailure(
                {
                    "reason": "could not build distinct wrong solution sets",
                    "problem": render_relation(relation.relation, coefficients),
                }
            )
        for wrong in wrongs:
            state.reserve()
            wrong_model = solution_set_model(wrong)
            result = execute_recipe(compiled, relation, wrong_model)
            if result.verdict:
                raise _CaseFailure(
                    {
                        "reason": "wrong solution set accepted",
                        "problem": result.problem,
                        "expected": result.expected,
                        "candidate": render_solution_set(wrong)[:200],
                    }
                )
        state.accepted.add(key)

    @seed(seed_value)
    @settings(
        max_examples=max_examples,
        deadline=None,
        database=None,
        report_multiple_bugs=False,
        phases=(Phase.explicit, Phase.generate, Phase.shrink),
        suppress_health_check=[HealthCheck.too_slow],
    )
    @given(relation=_solve_relation_strategy(scope))
    def wrapped(relation: PolynomialRelation) -> None:
        check_case(relation)

    if include_boundaries:
        for relation in reversed(_solve_boundary_relations(scope)):
            wrapped = example(relation=relation)(wrapped)
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
    definition = CheckRecipeDefinition.model_validate(payload.get("definition"))
    scope = _scope_from_payload(payload, definition)
    failure = _compile_failure(definition, config, seed_value, scope)
    if failure is not None:
        return failure
    compiled = compile_recipe(definition, scope=scope)
    state = _RunState(config)
    solve_property = isinstance(scope, ContractScope) and scope.operation == "solve"
    if solve_property:
        assert isinstance(scope, ContractScope)
        _, outcome = _run_solve_recipe_property(
            compiled=compiled,
            scope=scope,
            state=state,
            seed_value=seed_value,
            max_examples=config.max_examples,
            salt=0,
            expose_counterexample=True,
            include_boundaries=True,
        )
    else:
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
    if solve_property:
        assert isinstance(scope, ContractScope)
        _, held_out = _run_solve_recipe_property(
            compiled=compiled,
            scope=scope,
            state=state,
            seed_value=seed_value + 7919,
            max_examples=max(4, config.max_examples // 2),
            salt=104_729,
            expose_counterexample=False,
            include_boundaries=False,
        )
    else:
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


def _family_strategy(
    family: PolynomialFamily | SolveFamily,
) -> st.SearchStrategy[dict[str, int]]:
    return st.fixed_dictionaries(
        {
            f"a{domain.exponent}": st.sampled_from(domain.values)
            for domain in family.coefficients
        }
    )


def _family_boundaries(
    family: PolynomialFamily | SolveFamily,
) -> list[dict[str, int]]:
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


def _solve_template_qualification(
    *,
    compiled: CompiledRecipe,
    family: SolveFamily,
    config: PilotQualificationSettings,
    seed_value: int,
) -> Qualification:
    state = _RunState(config)

    def check_case(assignment: dict[str, int]) -> None:
        state.reserve()
        coefficients = tuple(
            assignment[f"a{domain.exponent}"] for domain in family.coefficients
        )
        key = (family.relation, coefficients)
        if key in state.accepted:
            return
        try:
            instance = build_solve_instance(family, coefficients, seed=seed_value)
        except QuestionBuildError as exc:
            raise _CaseFailure(
                {
                    "reason": f"renderer rejected the assignment: {exc}",
                    "assignment": assignment,
                }
            ) from None
        guard_findings = guard_solve_instance(
            instance, num_distractors=family.num_distractors
        )
        if guard_findings:
            raise _CaseFailure(
                {
                    "reason": guard_findings[0],
                    "assignment": assignment,
                    "expected": instance.answer,
                    "choices": list(instance.choices),
                }
            )
        state.reserve()
        result = execute_recipe(
            compiled, instance.relation, solution_set_model(instance.expected)
        )
        if not result.verdict:
            raise _CaseFailure(
                {
                    "reason": "pinned recipe rejected the correct solution set",
                    "assignment": assignment,
                    "expected": result.expected,
                    "candidate": instance.answer,
                }
            )
        for distractor in instance.distractors:
            state.reserve()
            candidate = solution_set_model(distractor)
            result = execute_recipe(compiled, instance.relation, candidate)
            if result.verdict:
                raise _CaseFailure(
                    {
                        "reason": "pinned recipe accepted a wrong solution set",
                        "assignment": assignment,
                        "expected": result.expected,
                        "candidate": render_solution_set(distractor)[:200],
                    }
                )
        state.accepted.add(key)

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


def qualify_template_payload(payload: dict[str, Any]) -> Qualification:
    config = PilotQualificationSettings.model_validate(payload.get("settings", {}))
    seed_value = int(payload.get("seed", 0))
    if seed_value < 0:
        seed_value = 0
    definition = CheckRecipeDefinition.model_validate(payload.get("definition"))
    template_data = payload.get("template")
    if isinstance(template_data, dict):
        template = PilotTemplateDefinition.model_validate(template_data)
        scope: PolynomialScope | ContractScope = template.scope
        failure = _compile_failure(definition, config, seed_value, scope)
        if failure is not None:
            return failure
        compiled = compile_recipe(definition, scope=scope)
        if template.solve_family is not None:
            return _solve_template_qualification(
                compiled=compiled,
                family=template.solve_family,
                config=config,
                seed_value=seed_value,
            )
        family = template.family
        assert family is not None
    else:
        scope = _scope_from_payload(payload, definition)
        failure = _compile_failure(definition, config, seed_value, scope)
        if failure is not None:
            return failure
        compiled = compile_recipe(definition, scope=scope)
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


def _deserialize_problem(value: Any) -> Polynomial | PolynomialRelation:
    if isinstance(value, str):
        return parse_polynomial(value)
    if isinstance(value, dict):
        kind = value.get("kind")
        if kind == "polynomial":
            return parse_polynomial(value.get("text", ""))
        if kind == "relation":
            return PolynomialRelation.model_validate(value.get("relation"))
        if "relation" in value and "coefficients" in value:
            return PolynomialRelation.model_validate(value)
    raise ValueError("recipe problem must be a polynomial or relation payload")


def _deserialize_candidate(value: Any) -> Polynomial | RealSolutionSet:
    if isinstance(value, str):
        return parse_polynomial(value)
    if isinstance(value, dict):
        kind = value.get("kind")
        if kind == "polynomial":
            return parse_polynomial(value.get("text", ""))
        if kind == "solution_set":
            return RealSolutionSet.model_validate(value.get("solution_set"))
        if "components" in value:
            return RealSolutionSet.model_validate(value)
    raise ValueError("recipe candidate must be a polynomial or solution-set payload")


def execute_recipe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    definition = CheckRecipeDefinition.model_validate(payload["definition"])
    scope = _scope_from_payload(payload, definition)
    compiled = compile_recipe(definition, scope=scope)
    problem = _deserialize_problem(payload["problem"])
    candidate = _deserialize_candidate(payload["candidate"])
    result = execute_recipe(compiled, problem, candidate)
    return {"result": result.model_dump(mode="json")}


def execute_recipe_cases_payload(payload: dict[str, Any]) -> dict[str, Any]:
    cases = payload.get("cases", [])
    if not isinstance(cases, list) or len(cases) > MAX_RECIPE_CASES:
        raise ValueError(f"recipe cases must be a list of at most {MAX_RECIPE_CASES}")
    definition = CheckRecipeDefinition.model_validate(payload["definition"])
    scope = _scope_from_payload(payload, definition)
    compiled = compile_recipe(definition, scope=scope)
    results = []
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("each recipe case must be an object")
        problem = _deserialize_problem(case["problem"])
        candidate = _deserialize_candidate(case["candidate"])
        results.append(
            execute_recipe(compiled, problem, candidate).model_dump(mode="json")
        )
    return {"results": results}


def generate_batch_payload(payload: dict[str, Any]) -> dict[str, Any]:
    template_id = payload.get("template_id")
    seed = payload.get("seed")
    quantity = payload.get("quantity")
    if not isinstance(template_id, str) or not template_id:
        raise ValueError("generation requires a template id")
    if type(seed) is not int or type(quantity) is not int:
        raise ValueError("generation seed and quantity must be integers")
    batch = build_generation_batch(
        template_id=template_id,
        seed=seed,
        quantity=quantity,
        definition=CheckRecipeDefinition.model_validate(payload.get("definition")),
        template=PilotTemplateDefinition.model_validate(payload.get("template")),
        check_ref=CheckRef.model_validate(payload.get("check_ref")),
    )
    return {"batch": batch.model_dump(mode="json")}


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
    if operation == "generate_batch":
        return generate_batch_payload(payload)
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
