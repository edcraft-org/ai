"""Exhaustive approval pipeline for finite code-question templates."""

from __future__ import annotations

import ast
import copy
import itertools
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from edcraft_validator.comparison import equivalent, same_value_shape
from edcraft_validator.domains.code.capabilities import (
    code_template_profile,
    extract_code_features,
)
from edcraft_validator.executor import DockerExecutor, ExecutionBackend, ExecutionResult
from edcraft_validator.models import AnswerTarget, ValidationIssue
from edcraft_validator.safety import check_code_safety
from edcraft_validator.validation.contracts import (
    AssuranceLevel,
    ValidationEvidence,
)

from .expressions import SafeExpression
from .generation import render_template, template_sha256
from .models import (
    ApprovedCodeQuestionTemplate,
    CodeQuestionTemplate,
    DistractorRecipe,
    ParameterValue,
    TemplateValidationError,
    TemplateValidationSummary,
    ValidatedTemplateCase,
    validated_cases_sha256,
)

CODE_TEMPLATE_VALIDATOR_VERSION = "code-template-validator-v2"
_T = TypeVar("_T")


@dataclass
class _DistractorCandidate:
    index: int
    expression: SafeExpression | None = None
    values: list[Any] | None = None
    rejection: str | None = None


class TemplateValidator:
    """Approve a finite template only after checking every possible instance."""

    def __init__(
        self,
        *,
        executor: ExecutionBackend | None = None,
        timeout_seconds: float = 2.0,
    ) -> None:
        self.executor = executor or DockerExecutor()
        self.timeout_seconds = timeout_seconds

    def validate(
        self, template: CodeQuestionTemplate, *, num_distractors: int | None = None
    ) -> ApprovedCodeQuestionTemplate:
        evidence: list[ValidationEvidence] = []
        original_distractor_count = len(template.distractors)
        names = tuple(parameter.name for parameter in template.parameters)
        value_domains = [parameter.values for parameter in template.parameters]
        inputs_cases = [
            dict(zip(names, values, strict=True))
            for values in itertools.product(*value_domains)
        ]
        case_details = {"cases": len(inputs_cases)}

        self._record_check(
            evidence,
            check="template_structure",
            assurance="bounded",
            details={"topic": template.topic, "difficulty": template.difficulty},
            operation=lambda: self._validate_structure(template, names),
        )
        if num_distractors is not None and not 2 <= num_distractors <= 3:
            raise ValueError("num_distractors must be 2 or 3")
        proposed_answer, candidates = self._record_check(
            evidence,
            check="expression_safety",
            assurance="bounded",
            details={"distractors": len(template.distractors)},
            operation=lambda: self._parse_expressions(
                template,
                names,
                allow_candidate_rejections=num_distractors is not None,
            ),
        )
        proposed_answers = self._record_check(
            evidence,
            check="answer_domain",
            assurance="exhaustive",
            details=case_details,
            operation=lambda: self._evaluate_answers(
                template, proposed_answer, inputs_cases
            ),
        )
        executions = self._record_check(
            evidence,
            check="sandboxed_execution",
            assurance="exhaustive",
            details={**case_details, "executor": type(self.executor).__name__},
            operation=lambda: self._execute_successfully(template, inputs_cases),
        )
        answer_details = {**case_details, "source": "sandboxed_execution"}
        canonical_answers, corrected_cases = self._record_check(
            evidence,
            check="canonical_answers",
            assurance="exhaustive",
            details=answer_details,
            operation=lambda: self._resolve_canonical_answers(
                template,
                inputs_cases,
                executions,
                proposed_answers,
                answer_details,
            ),
        )
        if corrected_cases:
            template, candidates = self._promote_proposed_answer_to_distractor(
                template,
                proposed_answer,
                proposed_answers,
                candidates,
            )
        selected_count = num_distractors
        if selected_count is None and corrected_cases:
            selected_count = original_distractor_count
        if selected_count is not None:
            template, candidates = self._record_check(
                evidence,
                check="distractor_selection",
                assurance="exhaustive",
                details={**case_details, "selected": selected_count},
                operation=lambda: self._select_distractors(
                    template,
                    inputs_cases,
                    canonical_answers,
                    candidates,
                    num_distractors=selected_count,
                ),
            )
        self._record_check(
            evidence,
            check="distractor_consistency",
            assurance="exhaustive",
            details={**case_details, "distractors": len(candidates)},
            operation=lambda: self._validate_all_distractors(
                inputs_cases, canonical_answers, candidates
            ),
        )
        self._record_check(
            evidence,
            check="template_rendering",
            assurance="exhaustive",
            details=case_details,
            operation=lambda: self._validate_rendering(template, inputs_cases),
        )

        validated_cases = [
            ValidatedTemplateCase(inputs=inputs, answer=answer)
            for inputs, answer in zip(inputs_cases, canonical_answers, strict=True)
        ]
        approved_template = template.model_copy(
            update={"answer_expression": None}, deep=True
        )
        return ApprovedCodeQuestionTemplate(
            template=approved_template,
            validation=TemplateValidationSummary(
                validator_version=CODE_TEMPLATE_VALIDATOR_VERSION,
                cases_validated=len(inputs_cases),
                template_sha256=template_sha256(approved_template),
                validated_cases=validated_cases,
                validated_cases_sha256=validated_cases_sha256(validated_cases),
                evidence=evidence,
            ),
        )

    @staticmethod
    def _record_check(
        evidence: list[ValidationEvidence],
        *,
        check: str,
        assurance: AssuranceLevel,
        details: dict[str, Any],
        operation: Callable[[], _T],
    ) -> _T:
        started = time.perf_counter()
        try:
            result = operation()
        except TemplateValidationError as exc:
            failed_details = copy.deepcopy(details)
            if exc.inputs is not None:
                failed_details["failing_inputs"] = copy.deepcopy(exc.inputs)
            evidence.append(
                ValidationEvidence(
                    check=check,
                    status="failed",
                    assurance=assurance,
                    issues=[
                        ValidationIssue(
                            code=exc.code,
                            message=str(exc),
                            field=exc.field,
                        )
                    ],
                    details=failed_details,
                    duration_ms=(time.perf_counter() - started) * 1000,
                )
            )
            exc.evidence = copy.deepcopy(evidence)
            raise
        evidence.append(
            ValidationEvidence(
                check=check,
                status="passed",
                assurance=assurance,
                details=copy.deepcopy(details),
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        )
        return result

    @staticmethod
    def _parse_expressions(
        template: CodeQuestionTemplate,
        names: tuple[str, ...],
        *,
        allow_candidate_rejections: bool,
    ) -> tuple[SafeExpression, list[_DistractorCandidate]]:
        if template.answer_expression is None:
            raise TemplateValidationError(
                "unapproved templates require an answer_expression",
                code="ANSWER_EXPRESSION_MISSING",
                field="answer_expression",
            )
        answer = SafeExpression(template.answer_expression, names)
        candidates: list[_DistractorCandidate] = []
        for index, recipe in enumerate(template.distractors):
            try:
                expression = SafeExpression(recipe.expression, names)
            except TemplateValidationError as exc:
                if not allow_candidate_rejections:
                    raise
                candidates.append(_DistractorCandidate(index=index, rejection=str(exc)))
            else:
                candidates.append(
                    _DistractorCandidate(index=index, expression=expression)
                )
        return answer, candidates

    @classmethod
    def _evaluate_answers(
        cls,
        template: CodeQuestionTemplate,
        answer: SafeExpression,
        inputs_cases: list[dict[str, ParameterValue]],
    ) -> list[Any]:
        expected_answers = []
        for inputs in inputs_cases:
            expected_answer = answer.evaluate(inputs)
            _require_json_value(expected_answer, "answer")
            cls._validate_answer_kind(template, inputs, expected_answer)
            expected_answers.append(expected_answer)
        return expected_answers

    def _execute_successfully(
        self,
        template: CodeQuestionTemplate,
        inputs_cases: list[dict[str, ParameterValue]],
    ) -> list[ExecutionResult]:
        executions = self._execute_all(template, inputs_cases)
        for inputs, execution in zip(inputs_cases, executions, strict=True):
            if execution.ok:
                continue
            detail = execution.error_message or execution.error_code or "unknown"
            raise TemplateValidationError(
                f"template execution failed for inputs {inputs}: {detail}",
                code=execution.error_code or "EXECUTION_FAILED",
                field="code",
                inputs=inputs,
            )
        return executions

    @classmethod
    def _resolve_canonical_answers(
        cls,
        template: CodeQuestionTemplate,
        inputs_cases: list[dict[str, ParameterValue]],
        executions: list[ExecutionResult],
        proposed_answers: list[Any],
        details: dict[str, Any],
    ) -> tuple[list[Any], int]:
        canonical_answers = []
        corrected_cases = 0
        for inputs, execution, proposed_answer in zip(
            inputs_cases, executions, proposed_answers, strict=True
        ):
            actual_answer = _execution_answer(execution, template.answer_target)
            _require_json_value(actual_answer, "executor answer")
            cls._validate_answer_kind(template, inputs, actual_answer)
            canonical_answers.append(copy.deepcopy(actual_answer))
            if not equivalent(actual_answer, proposed_answer):
                corrected_cases += 1
        details["corrected_cases"] = corrected_cases
        details["proposal_matched"] = corrected_cases == 0
        return canonical_answers, corrected_cases

    @staticmethod
    def _promote_proposed_answer_to_distractor(
        template: CodeQuestionTemplate,
        proposed_answer: SafeExpression,
        proposed_values: list[Any],
        candidates: list[_DistractorCandidate],
    ) -> tuple[CodeQuestionTemplate, list[_DistractorCandidate]]:
        if template.answer_expression is None:
            raise AssertionError("proposed answer expression is missing")

        recipes = list(template.distractors)
        existing_index = next(
            (
                index
                for index, recipe in enumerate(recipes)
                if recipe.expression == template.answer_expression
            ),
            None,
        )
        if existing_index is None:
            promoted_recipe = DistractorRecipe(
                expression=template.answer_expression,
                reason_template=(
                    "Uses the original predicted answer instead of the execution "
                    "result."
                ),
            )
            promoted_candidate = _DistractorCandidate(
                index=0,
                expression=proposed_answer,
                values=copy.deepcopy(proposed_values),
            )
        else:
            promoted_recipe = recipes.pop(existing_index)
            candidates.pop(existing_index)
            promoted_candidate = _DistractorCandidate(
                index=0,
                expression=proposed_answer,
                values=copy.deepcopy(proposed_values),
            )

        recipes.insert(0, promoted_recipe)
        candidates.insert(0, promoted_candidate)
        for index, candidate in enumerate(candidates):
            candidate.index = index
        return (
            template.model_copy(update={"distractors": recipes}, deep=True),
            candidates,
        )

    @classmethod
    def _validate_all_distractors(
        cls,
        inputs_cases: list[dict[str, ParameterValue]],
        expected_answers: list[Any],
        candidates: list[_DistractorCandidate],
    ) -> None:
        for candidate in candidates:
            if candidate.values is not None:
                continue
            if candidate.expression is None:
                raise AssertionError("validated distractor is missing its expression")
            candidate.values = [
                candidate.expression.evaluate(inputs) for inputs in inputs_cases
            ]
        for case_index, (inputs, expected_answer) in enumerate(
            zip(inputs_cases, expected_answers, strict=True)
        ):
            generated = [
                candidate.values[case_index]
                for candidate in candidates
                if candidate.values is not None
            ]
            if len(generated) != len(candidates):
                raise AssertionError("validated distractor is missing computed values")
            cls._validate_distractors(inputs, expected_answer, generated)

    @staticmethod
    def _validate_rendering(
        template: CodeQuestionTemplate,
        inputs_cases: list[dict[str, ParameterValue]],
    ) -> None:
        for inputs in inputs_cases:
            render_template(template.question_template, inputs, require_all=True)
            for recipe in template.distractors:
                render_template(recipe.reason_template, inputs)

    @classmethod
    def _select_distractors(
        cls,
        template: CodeQuestionTemplate,
        inputs_cases: list[dict[str, ParameterValue]],
        expected_answers: list[Any],
        candidates: list[_DistractorCandidate],
        *,
        num_distractors: int,
    ) -> tuple[CodeQuestionTemplate, list[_DistractorCandidate]]:
        cls._precompute_candidate_vectors(
            template, inputs_cases, expected_answers, candidates
        )
        failures: list[str] = []

        for candidate_indexes in itertools.combinations(
            range(len(template.distractors)), num_distractors
        ):
            selected = [candidates[index] for index in candidate_indexes]
            rejection = next(
                (candidate.rejection for candidate in selected if candidate.rejection),
                None,
            )
            if rejection is None:
                rejection = cls._find_candidate_collision(selected, inputs_cases)
            if rejection is not None:
                rendered_indexes = ",".join(str(index) for index in candidate_indexes)
                failures.append(f"candidates {rendered_indexes}: {rejection}")
                continue
            recipes = [template.distractors[index] for index in candidate_indexes]
            selected_template = template.model_copy(
                update={"distractors": recipes}, deep=True
            )
            return selected_template, selected

        detail = "; ".join(failures[:3]) or "not enough candidates"
        raise TemplateValidationError(
            f"no set of {num_distractors} distractors is globally valid: {detail}",
            code="DISTRACTOR_SELECTION_FAILED",
            field="distractors",
        )

    @classmethod
    def _precompute_candidate_vectors(
        cls,
        template: CodeQuestionTemplate,
        inputs_cases: list[dict[str, ParameterValue]],
        expected_answers: list[Any],
        candidates: list[_DistractorCandidate],
    ) -> None:
        for candidate in candidates:
            if candidate.rejection is not None:
                candidate.rejection = (
                    f"candidate {candidate.index}: {candidate.rejection}"
                )
                continue
            if candidate.expression is None:
                raise AssertionError("distractor candidate is missing its expression")
            values = candidate.values or []
            try:
                if candidate.values is None:
                    values = [
                        candidate.expression.evaluate(inputs) for inputs in inputs_cases
                    ]
                for inputs, expected_answer, value in zip(
                    inputs_cases, expected_answers, values, strict=True
                ):
                    cls._validate_distractor_value(
                        inputs, expected_answer, value, candidate.index
                    )
                    render_template(
                        template.distractors[candidate.index].reason_template, inputs
                    )
            except (
                TemplateValidationError,
                ArithmeticError,
                TypeError,
                ValueError,
            ) as exc:
                candidate.rejection = f"candidate {candidate.index}: {exc}"
            else:
                candidate.values = values

    @staticmethod
    def _find_candidate_collision(
        candidates: list[_DistractorCandidate],
        inputs_cases: list[dict[str, ParameterValue]],
    ) -> str | None:
        for first, second in itertools.combinations(candidates, 2):
            if first.values is None or second.values is None:
                raise AssertionError("valid distractor candidate is missing its values")
            for inputs, first_value, second_value in zip(
                inputs_cases, first.values, second.values, strict=True
            ):
                if equivalent(first_value, second_value):
                    return (
                        f"candidate {second.index} duplicates candidate {first.index} "
                        f"for inputs {inputs}"
                    )
        return None

    def _execute_all(
        self,
        template: CodeQuestionTemplate,
        inputs: list[dict[str, ParameterValue]],
    ) -> list[ExecutionResult]:
        execute_batch = getattr(self.executor, "execute_batch", None)
        if callable(execute_batch):
            results = execute_batch(
                template.code,
                template.entry_function,
                inputs,
                timeout_seconds=self.timeout_seconds,
            )
        else:
            results = [
                self.executor.execute(
                    template.code,
                    template.entry_function,
                    item,
                    timeout_seconds=self.timeout_seconds,
                )
                for item in inputs
            ]
        if len(results) != len(inputs):
            raise TemplateValidationError(
                "executor returned the wrong number of batch results",
                code="EXECUTOR_PROTOCOL_ERROR",
                field="code",
            )
        return results

    @staticmethod
    def _validate_structure(
        template: CodeQuestionTemplate, names: tuple[str, ...]
    ) -> None:
        safety = check_code_safety(template.code, template.entry_function)
        if not safety.is_safe:
            raise TemplateValidationError(
                "; ".join(safety.errors), code="UNSAFE_CODE", field="code"
            )
        TemplateValidator._validate_profile(template)
        arguments = _entry_function_arguments(template.code, template.entry_function)
        if arguments != names:
            raise TemplateValidationError(
                "entry function arguments must exactly match parameter order: "
                f"expected {names}, received {arguments}",
                code="ENTRY_FUNCTION_MISMATCH",
                field="entry_function",
            )
        unused = _unused_entry_parameters(
            template.code, template.entry_function, arguments
        )
        if unused:
            raise TemplateValidationError(
                "entry function parameters must affect learner-facing behavior; "
                f"unused parameters: {', '.join(unused)}",
                code="UNUSED_PARAMETER",
                field="parameters",
            )
        if template.entry_function not in template.question_template:
            raise TemplateValidationError(
                "question_template must name the entry function",
                code="QUESTION_TEMPLATE_INVALID",
                field="question_template",
            )
        render_template(
            template.question_template,
            {name: 0 for name in names},
            require_all=True,
        )

    @staticmethod
    def _validate_profile(template: CodeQuestionTemplate) -> None:
        profile = code_template_profile(template.topic, template.difficulty)
        if template.answer_target != profile.answer_target:
            raise TemplateValidationError(
                f"{template.topic}/{template.difficulty} requires answer_target="
                f"{profile.answer_target}",
                code="PROFILE_MISMATCH",
                field="answer_target",
            )

        actual_kinds = tuple(parameter.kind for parameter in template.parameters)
        actual_names = tuple(parameter.name for parameter in template.parameters)
        if not any(
            actual_kinds == shape.kinds
            and (shape.names is None or actual_names == shape.names)
            for shape in profile.parameter_shapes
        ):
            expected = " or ".join(
                repr(shape.names or shape.kinds) for shape in profile.parameter_shapes
            )
            raise TemplateValidationError(
                f"{template.topic}/{template.difficulty} parameter profile requires "
                f"{expected}; received {actual_names} with kinds {actual_kinds}",
                code="PROFILE_MISMATCH",
                field="parameters",
            )

        if profile.require_positive_integers and any(
            value <= 0
            for parameter in template.parameters
            if parameter.kind == "integer"
            for value in parameter.values
        ):
            raise TemplateValidationError(
                f"{template.topic}/{template.difficulty} requires positive integer "
                "parameter values",
                code="PROFILE_MISMATCH",
                field="parameters",
            )

        if profile.required_parameter_values is not None:
            actual_values = tuple(
                tuple(parameter.values) for parameter in template.parameters
            )
            if actual_values != profile.required_parameter_values:
                raise TemplateValidationError(
                    f"{template.topic}/{template.difficulty} requires parameter "
                    f"values {profile.required_parameter_values}; received "
                    f"{actual_values}",
                    code="PROFILE_MISMATCH",
                    field="parameters",
                )

        actual_features = extract_code_features(template.code, template.entry_function)
        missing = profile.required_features - actual_features
        if missing:
            raise TemplateValidationError(
                f"{template.topic}/{template.difficulty} code is missing required "
                f"features: {', '.join(sorted(missing))}",
                code="PROFILE_MISMATCH",
                field="code",
            )

    @staticmethod
    def _validate_answer_kind(
        template: CodeQuestionTemplate,
        inputs: dict[str, ParameterValue],
        answer: Any,
    ) -> None:
        answer_kind = code_template_profile(
            template.topic, template.difficulty
        ).answer_kind
        valid = {
            "number": type(answer) in {int, float},
            "integer": type(answer) is int,
            "integer_list": type(answer) is list
            and all(type(item) is int for item in answer),
        }[answer_kind]
        if not valid:
            raise TemplateValidationError(
                f"{template.topic}/{template.difficulty} requires answer kind "
                f"{answer_kind}; received {type(answer).__name__} for inputs {inputs}",
                code="ANSWER_KIND_MISMATCH",
                field="answer_expression",
                inputs=inputs,
            )

    @staticmethod
    def _validate_distractors(
        inputs: dict[str, ParameterValue], answer: Any, distractors: list[Any]
    ) -> None:
        for index, distractor in enumerate(distractors):
            TemplateValidator._validate_distractor_value(
                inputs, answer, distractor, index
            )
            if any(
                equivalent(distractor, previous) for previous in distractors[:index]
            ):
                raise TemplateValidationError(
                    f"distractor {index} is duplicated for inputs {inputs}",
                    code="DISTRACTOR_DUPLICATE",
                    field=f"distractors.{index}",
                    inputs=inputs,
                )

    @staticmethod
    def _validate_distractor_value(
        inputs: dict[str, ParameterValue],
        answer: Any,
        distractor: Any,
        index: int,
    ) -> None:
        _require_json_value(distractor, f"distractor {index}")
        if not same_value_shape(distractor, answer):
            raise TemplateValidationError(
                f"distractor {index} has the wrong type for inputs {inputs}",
                code="DISTRACTOR_TYPE_MISMATCH",
                field=f"distractors.{index}",
                inputs=inputs,
            )
        if equivalent(distractor, answer):
            raise TemplateValidationError(
                f"distractor {index} equals the answer for inputs {inputs}",
                code="DISTRACTOR_EQUALS_ANSWER",
                field=f"distractors.{index}",
                inputs=inputs,
            )


def _execution_answer(execution: ExecutionResult, target: AnswerTarget) -> Any:
    if target == "return_value":
        return execution.answer
    summary = execution.trace_summary
    if not isinstance(summary, dict) or target not in summary:
        raise TemplateValidationError(
            f"execution did not provide answer target {target!r}"
        )
    return summary[target]


def _entry_function_arguments(code: str, entry_function: str) -> tuple[str, ...]:
    tree = ast.parse(code)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == entry_function:
            if (
                node.args.posonlyargs
                or node.args.kwonlyargs
                or node.args.vararg
                or node.args.kwarg
                or node.args.defaults
                or node.args.kw_defaults
            ):
                raise TemplateValidationError(
                    "entry function must use plain positional arguments "
                    "without defaults"
                )
            return tuple(argument.arg for argument in node.args.args)
    raise TemplateValidationError("entry function is not defined")


def _unused_entry_parameters(
    code: str, entry_function: str, parameters: tuple[str, ...]
) -> tuple[str, ...]:
    tree = ast.parse(code)
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    loaded: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Name) or not isinstance(node.ctx, ast.Load):
            continue
        current = parents.get(node)
        while current is not None and not isinstance(current, ast.FunctionDef):
            current = parents.get(current)
        if isinstance(current, ast.FunctionDef) and current.name == entry_function:
            loaded.add(node.id)
    return tuple(parameter for parameter in parameters if parameter not in loaded)


def _require_json_value(value: Any, label: str) -> None:
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise TemplateValidationError(f"{label} is not a finite JSON value") from exc
