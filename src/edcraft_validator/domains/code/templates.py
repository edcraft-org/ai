"""Reusable, exhaustively validated templates for Python questions."""

from __future__ import annotations

import ast
import copy
import hashlib
import itertools
import json
import math
import operator
import time
from collections.abc import Callable
from string import Formatter
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from edcraft_validator.comparison import equivalent, same_value_shape
from edcraft_validator.domains.code.capabilities import (
    Difficulty,
    ProgrammingTopic,
    code_template_profile,
    extract_code_features,
    profile_semantic_violation,
)
from edcraft_validator.executor import DockerExecutor, ExecutionBackend, ExecutionResult
from edcraft_validator.generation.models import (
    TemplateAuthoringProvenance,
    TemplateAuthoringRequest,
)
from edcraft_validator.models import AnswerTarget, GeneratedQuestion, ValidationIssue
from edcraft_validator.safety import check_code_safety
from edcraft_validator.validation.contracts import (
    AssuranceLevel,
    ValidationEvidence,
)

MAX_TEMPLATE_CASES = 64
MAX_STRING_LENGTH = 40
MAX_LIST_LENGTH = 8
MAX_EXPRESSION_LENGTH = 500
MAX_EXPRESSION_NODES = 100
MAX_EXPRESSION_INTEGER_ABS = 1_000_000_000
MAX_EXPRESSION_FLOAT_ABS = 1_000_000_000.0
MAX_EXPRESSION_SEQUENCE_LENGTH = 100
MAX_EXPRESSION_VALUE_SIZE = 1_000
MAX_EXPRESSION_VALUE_DEPTH = 20
CODE_TEMPLATE_PROMPT_VERSION = "code-template-v8"
CODE_TEMPLATE_VALIDATOR_VERSION = "code-template-validator-v1"
ParameterValue = int | bool | str | list[int]
_T = TypeVar("_T")


class FiniteParameter(BaseModel):
    """A finite parameter domain that can be validated exhaustively."""

    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    kind: Literal["integer", "boolean", "string", "integer_list"]
    values: list[ParameterValue] = Field(min_length=2, max_length=4)

    @model_validator(mode="after")
    def validate_values(self) -> FiniteParameter:
        encoded = [
            json.dumps(value, sort_keys=True, separators=(",", ":"))
            for value in self.values
        ]
        if len(encoded) != len(set(encoded)):
            raise ValueError("parameter values must be unique")
        validators = {
            "integer": self._validate_integer,
            "boolean": self._validate_boolean,
            "string": self._validate_string,
            "integer_list": self._validate_integer_list,
        }
        for value in self.values:
            validators[self.kind](value)
        return self

    @staticmethod
    def _validate_integer(value: ParameterValue) -> None:
        if type(value) is not int or abs(value) > 100:
            raise ValueError("integer values must be integers from -100 to 100")

    @staticmethod
    def _validate_boolean(value: ParameterValue) -> None:
        if type(value) is not bool:
            raise ValueError("boolean values must be true or false")

    @staticmethod
    def _validate_string(value: ParameterValue) -> None:
        if (
            type(value) is not str
            or not value
            or len(value) > MAX_STRING_LENGTH
            or not value.isprintable()
        ):
            raise ValueError(
                f"string values must be 1 to {MAX_STRING_LENGTH} printable characters"
            )

    @staticmethod
    def _validate_integer_list(value: ParameterValue) -> None:
        if type(value) is not list or len(value) > MAX_LIST_LENGTH:
            raise ValueError(
                f"integer-list values must contain at most {MAX_LIST_LENGTH} items"
            )
        if any(type(item) is not int or abs(item) > 100 for item in value):
            raise ValueError("integer-list items must be integers from -100 to 100")


class DistractorRecipe(BaseModel):
    """A deterministic misconception applied to concrete parameter values."""

    model_config = ConfigDict(extra="forbid", strict=True)

    expression: str = Field(min_length=1)
    reason_template: str = Field(min_length=1)


class CodeTemplateProposal(BaseModel):
    """Model-authored fields that require generative judgment."""

    model_config = ConfigDict(extra="forbid", strict=True)

    code: str = Field(min_length=1)
    entry_function: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    parameters: list[FiniteParameter] = Field(min_length=1, max_length=3)
    answer_expression: str = Field(min_length=1)
    distractors: list[DistractorRecipe] = Field(min_length=2, max_length=5)

    @field_validator("code", "answer_expression")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @model_validator(mode="after")
    def validate_parameter_domain(self) -> CodeTemplateProposal:
        names = [parameter.name for parameter in self.parameters]
        if len(names) != len(set(names)):
            raise ValueError("parameter names must be unique")
        combinations = math.prod(len(parameter.values) for parameter in self.parameters)
        if combinations > MAX_TEMPLATE_CASES:
            raise ValueError(
                f"template has {combinations} cases; maximum is {MAX_TEMPLATE_CASES}"
            )
        return self


class CodeQuestionTemplate(BaseModel):
    """Provider-neutral template contract for the first code-domain version."""

    model_config = ConfigDict(extra="forbid", strict=True)

    template_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    version: int = Field(ge=1)
    topic: ProgrammingTopic
    difficulty: Difficulty
    code: str = Field(min_length=1)
    entry_function: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    parameters: list[FiniteParameter] = Field(min_length=1, max_length=3)
    question_template: str = Field(min_length=1)
    answer_target: AnswerTarget
    answer_expression: str = Field(min_length=1)
    distractors: list[DistractorRecipe] = Field(min_length=2, max_length=8)
    question_type: Literal["mcq"]

    @field_validator("code", "question_template", "answer_expression")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @model_validator(mode="after")
    def validate_parameter_domain(self) -> CodeQuestionTemplate:
        names = [parameter.name for parameter in self.parameters]
        if len(names) != len(set(names)):
            raise ValueError("parameter names must be unique")
        combinations = _case_count(self)
        if combinations > MAX_TEMPLATE_CASES:
            raise ValueError(
                f"template has {combinations} cases; maximum is {MAX_TEMPLATE_CASES}"
            )
        return self


class TemplateValidationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    validator_version: str = Field(min_length=1)
    cases_validated: int = Field(ge=1)
    template_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence: list[ValidationEvidence] = Field(min_length=1)

    @model_validator(mode="after")
    def require_successful_unique_evidence(self) -> TemplateValidationSummary:
        checks = [item.check for item in self.evidence]
        if len(checks) != len(set(checks)):
            raise ValueError("validation evidence checks must be unique")
        if any(item.status != "passed" for item in self.evidence):
            raise ValueError("approved templates require passing validation evidence")
        return self


class ApprovedCodeQuestionTemplate(BaseModel):
    """A template plus evidence that its complete finite domain was checked."""

    model_config = ConfigDict(extra="forbid", strict=True)

    template: CodeQuestionTemplate
    validation: TemplateValidationSummary
    authoring: TemplateAuthoringProvenance | None = None


class TemplateQuestionInstance(BaseModel):
    """A reproducible question expanded from an approved template."""

    model_config = ConfigDict(extra="forbid", strict=True)

    template_id: str
    template_version: int
    template_sha256: str
    seed: int
    parameters: dict[str, ParameterValue]
    question: GeneratedQuestion


class TemplateValidationError(ValueError):
    """Raised when any possible instance fails template approval."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "TEMPLATE_INVALID",
        field: str | None = None,
        inputs: dict[str, ParameterValue] | None = None,
        evidence: list[ValidationEvidence] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.field = field
        self.inputs = copy.deepcopy(inputs)
        self.evidence = copy.deepcopy(evidence or [])

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "field": self.field,
            "inputs": self.inputs,
            "evidence": [item.model_dump(mode="json") for item in self.evidence],
        }


def parse_code_question_template(content: str) -> CodeQuestionTemplate:
    """Parse template JSON with strict local schema validation."""
    payload = json.loads(content)
    return CodeQuestionTemplate.model_validate(payload)


def parse_code_template_proposal(content: str) -> CodeTemplateProposal:
    """Parse a provider proposal with strict local schema validation."""
    payload = json.loads(content)
    return CodeTemplateProposal.model_validate(payload)


def normalize_code_template_proposal(
    request: TemplateAuthoringRequest, proposal: CodeTemplateProposal
) -> CodeQuestionTemplate:
    """Derive non-judgment fields locally and produce the canonical template."""
    if len(proposal.distractors) < request.num_distractors:
        raise TemplateValidationError(
            f"expected at least {request.num_distractors} distractor candidates, "
            f"received {len(proposal.distractors)}",
            code="DISTRACTOR_COUNT_INVALID",
            field="distractors",
        )
    profile = code_template_profile(request.topic, request.difficulty)
    identity_payload = json.dumps(
        {
            "request": request.model_dump(mode="json"),
            "proposal": proposal.model_dump(mode="json"),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    digest = hashlib.sha256(identity_payload).hexdigest()[:12]
    return CodeQuestionTemplate(
        template_id=f"{request.topic}.{request.difficulty}.{digest}",
        version=1,
        topic=request.topic,
        difficulty=request.difficulty,
        code=proposal.code,
        entry_function=proposal.entry_function,
        parameters=proposal.parameters,
        question_template=_question_template(
            profile.answer_target,
            proposal.entry_function,
            tuple(parameter.name for parameter in proposal.parameters),
        ),
        answer_target=profile.answer_target,
        answer_expression=proposal.answer_expression,
        distractors=_with_deterministic_fallbacks(
            proposal.distractors,
            answer_expression=proposal.answer_expression,
            answer_kind=profile.answer_kind,
        ),
        question_type="mcq",
    )


def _with_deterministic_fallbacks(
    model_candidates: list[DistractorRecipe],
    *,
    answer_expression: str,
    answer_kind: str,
) -> list[DistractorRecipe]:
    if answer_kind == "integer_list":
        fallback_expressions = [
            f"({answer_expression}) + [{offset}]" for offset in range(3)
        ]
        reason = "Appends an extra value to the result list."
    else:
        fallback_expressions = [
            f"({answer_expression}) + {offset}" for offset in range(1, 4)
        ]
        reason = "Applies an off-by-one-style adjustment to the correct result."

    result = list(model_candidates)
    existing = {candidate.expression for candidate in result}
    for expression in fallback_expressions:
        if expression not in existing:
            result.append(
                DistractorRecipe(expression=expression, reason_template=reason)
            )
            existing.add(expression)
    return result


def _question_template(
    target: AnswerTarget, entry_function: str, parameter_names: tuple[str, ...]
) -> str:
    arguments = ", ".join(f"{{{name}}}" for name in parameter_names)
    invocation = f"{entry_function}({arguments})"
    wording = {
        "return_value": f"What value does {invocation} return?",
        "loop_iterations": (
            f"How many total loop-body iterations occur when {invocation} runs?"
        ),
        "loop_executions": (
            f"How many loop statements are encountered when {invocation} runs?"
        ),
        "branch_executions": (
            f"How many if conditions are evaluated when {invocation} runs?"
        ),
        "function_calls": (
            f"How many traced function calls occur when {invocation} runs, including "
            "the entry function and safe built-ins?"
        ),
    }
    return wording[target]


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
        if num_distractors is not None:
            if not 2 <= num_distractors <= 3:
                raise ValueError("num_distractors must be 2 or 3")
            template = self._record_check(
                evidence,
                check="distractor_selection",
                assurance="exhaustive",
                details={**case_details, "selected": num_distractors},
                operation=lambda: self._select_distractors(
                    template, names, num_distractors=num_distractors
                ),
            )
        answer, distractors = self._record_check(
            evidence,
            check="expression_safety",
            assurance="bounded",
            details={"distractors": len(template.distractors)},
            operation=lambda: (
                SafeExpression(template.answer_expression, names),
                [
                    SafeExpression(recipe.expression, names)
                    for recipe in template.distractors
                ],
            ),
        )
        expected_answers = self._record_check(
            evidence,
            check="answer_domain",
            assurance="exhaustive",
            details=case_details,
            operation=lambda: self._evaluate_answers(template, answer, inputs_cases),
        )
        executions = self._record_check(
            evidence,
            check="sandboxed_execution",
            assurance="exhaustive",
            details={**case_details, "executor": type(self.executor).__name__},
            operation=lambda: self._execute_successfully(template, inputs_cases),
        )
        self._record_check(
            evidence,
            check="answer_consistency",
            assurance="exhaustive",
            details=case_details,
            operation=lambda: self._validate_answers(
                template, inputs_cases, executions, expected_answers
            ),
        )
        self._record_check(
            evidence,
            check="distractor_consistency",
            assurance="exhaustive",
            details={**case_details, "distractors": len(distractors)},
            operation=lambda: self._validate_all_distractors(
                inputs_cases, expected_answers, distractors
            ),
        )
        self._record_check(
            evidence,
            check="template_rendering",
            assurance="exhaustive",
            details=case_details,
            operation=lambda: self._validate_rendering(template, inputs_cases),
        )

        return ApprovedCodeQuestionTemplate(
            template=template,
            validation=TemplateValidationSummary(
                validator_version=CODE_TEMPLATE_VALIDATOR_VERSION,
                cases_validated=len(inputs_cases),
                template_sha256=template_sha256(template),
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

    @staticmethod
    def _validate_answers(
        template: CodeQuestionTemplate,
        inputs_cases: list[dict[str, ParameterValue]],
        executions: list[ExecutionResult],
        expected_answers: list[Any],
    ) -> None:
        for inputs, execution, expected_answer in zip(
            inputs_cases, executions, expected_answers, strict=True
        ):
            actual_answer = _execution_answer(execution, template.answer_target)
            if equivalent(actual_answer, expected_answer):
                continue
            raise TemplateValidationError(
                "answer_expression does not match the execution target for "
                f"inputs {inputs}: expression={expected_answer!r}, "
                f"execution={actual_answer!r}",
                code="ANSWER_MISMATCH",
                field="answer_expression",
                inputs=inputs,
            )

    @classmethod
    def _validate_all_distractors(
        cls,
        inputs_cases: list[dict[str, ParameterValue]],
        expected_answers: list[Any],
        distractors: list[SafeExpression],
    ) -> None:
        for inputs, expected_answer in zip(inputs_cases, expected_answers, strict=True):
            generated = [item.evaluate(inputs) for item in distractors]
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
        names: tuple[str, ...],
        *,
        num_distractors: int,
    ) -> CodeQuestionTemplate:
        answer = SafeExpression(template.answer_expression, names)
        value_domains = [parameter.values for parameter in template.parameters]
        inputs_cases = [
            dict(zip(names, values, strict=True))
            for values in itertools.product(*value_domains)
        ]
        expected_answers = [answer.evaluate(inputs) for inputs in inputs_cases]
        for inputs, expected_answer in zip(inputs_cases, expected_answers, strict=True):
            cls._validate_answer_kind(template, inputs, expected_answer)
        failures: list[str] = []

        for candidate_indexes in itertools.combinations(
            range(len(template.distractors)), num_distractors
        ):
            recipes = [template.distractors[index] for index in candidate_indexes]
            try:
                expressions = [
                    SafeExpression(recipe.expression, names) for recipe in recipes
                ]
                for inputs, expected_answer in zip(
                    inputs_cases, expected_answers, strict=True
                ):
                    candidate_values = [
                        expression.evaluate(inputs) for expression in expressions
                    ]
                    cls._validate_distractors(
                        inputs,
                        expected_answer,
                        candidate_values,
                    )
                    for recipe in recipes:
                        render_template(recipe.reason_template, inputs)
            except (
                TemplateValidationError,
                ArithmeticError,
                TypeError,
                ValueError,
            ) as exc:
                rendered_indexes = ",".join(str(index) for index in candidate_indexes)
                failures.append(f"candidates {rendered_indexes}: {exc}")
                continue
            return template.model_copy(update={"distractors": recipes}, deep=True)

        detail = "; ".join(failures[:3]) or "not enough candidates"
        raise TemplateValidationError(
            f"no set of {num_distractors} distractors is globally valid: {detail}",
            code="DISTRACTOR_SELECTION_FAILED",
            field="distractors",
        )

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

        semantic_violation = profile_semantic_violation(
            profile,
            template.code,
            template.entry_function,
            template.answer_expression,
        )
        if semantic_violation is not None:
            field, message = semantic_violation
            raise TemplateValidationError(
                message,
                code="PROFILE_MISMATCH",
                field=field,
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
            if any(
                equivalent(distractor, previous) for previous in distractors[:index]
            ):
                raise TemplateValidationError(
                    f"distractor {index} is duplicated for inputs {inputs}",
                    code="DISTRACTOR_DUPLICATE",
                    field=f"distractors.{index}",
                    inputs=inputs,
                )


class TemplateInstanceGenerator:
    """Expand approved templates without AI calls or per-instance validation."""

    provider = "template"
    model = None

    def generate(
        self, approved: ApprovedCodeQuestionTemplate, *, seed: int
    ) -> TemplateQuestionInstance:
        template = approved.template
        digest = template_sha256(template)
        if digest != approved.validation.template_sha256:
            raise ValueError("approved template content has changed since validation")
        if approved.validation.cases_validated != _case_count(template):
            raise ValueError(
                "approved template does not cover its complete input domain"
            )

        inputs = {
            parameter.name: copy.deepcopy(
                _seeded_choice(parameter.values, digest, seed, parameter.name)
            )
            for parameter in template.parameters
        }
        names = tuple(inputs)
        answer = SafeExpression(template.answer_expression, names).evaluate(inputs)
        distractors = [
            SafeExpression(recipe.expression, names).evaluate(inputs)
            for recipe in template.distractors
        ]
        distractor_reasons = [
            render_template(recipe.reason_template, inputs)
            for recipe in template.distractors
        ]
        question = GeneratedQuestion(
            code=template.code,
            entry_function=template.entry_function,
            inputs=inputs,
            question=render_template(
                template.question_template, inputs, require_all=True
            ),
            proposed_answer=answer,
            distractors=distractors,
            distractor_reasons=distractor_reasons,
            answer_target=template.answer_target,
            question_type=template.question_type,
        )
        return TemplateQuestionInstance(
            template_id=template.template_id,
            template_version=template.version,
            template_sha256=digest,
            seed=seed,
            parameters=inputs,
            question=question,
        )


class SafeExpression:
    """Evaluate the small arithmetic expression language used by templates."""

    _binary_operators = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
    }
    _unary_operators = {
        ast.UAdd: operator.pos,
        ast.USub: operator.neg,
        ast.Not: operator.not_,
    }
    _comparison_operators = {
        ast.Eq: operator.eq,
        ast.NotEq: operator.ne,
        ast.Lt: operator.lt,
        ast.LtE: operator.le,
        ast.Gt: operator.gt,
        ast.GtE: operator.ge,
        ast.In: lambda item, container: operator.contains(container, item),
        ast.NotIn: lambda item, container: not operator.contains(container, item),
    }
    _safe_functions = {
        "all": all,
        "any": any,
        "len": len,
        "max": max,
        "min": min,
        "sorted": sorted,
        "sum": sum,
    }

    def __init__(self, source: str, names: tuple[str, ...]) -> None:
        self.source = source
        self.names = frozenset(names)
        if len(source) > MAX_EXPRESSION_LENGTH:
            raise TemplateValidationError(
                f"template expression exceeds {MAX_EXPRESSION_LENGTH} characters"
            )
        try:
            self.expression = ast.parse(source, mode="eval").body
        except SyntaxError as exc:
            raise TemplateValidationError(
                f"invalid template expression {source!r}: {exc.msg}"
            ) from exc
        if sum(1 for _ in ast.walk(self.expression)) > MAX_EXPRESSION_NODES:
            raise TemplateValidationError(
                f"template expression exceeds {MAX_EXPRESSION_NODES} syntax nodes"
            )
        self._validate(self.expression, depth=0)

    def evaluate(self, values: dict[str, ParameterValue]) -> Any:
        try:
            return self._bounded(self._evaluate(self.expression, values))
        except (
            ArithmeticError,
            IndexError,
            OverflowError,
            TypeError,
            ValueError,
        ) as exc:
            raise TemplateValidationError(
                f"expression {self.source!r} failed for {values}: {exc}"
            ) from exc

    def _validate(self, node: ast.AST, *, depth: int) -> None:
        if depth > 20:
            raise TemplateValidationError("template expression is too deeply nested")
        if isinstance(node, ast.Constant):
            if type(node.value) not in {int, float, bool, str}:
                raise TemplateValidationError(
                    "template expressions support only JSON scalar constants"
                )
            if isinstance(node.value, (int, float)) and abs(node.value) > 10_000:
                raise TemplateValidationError("expression constant is too large")
            if isinstance(node.value, str) and (
                len(node.value) > MAX_STRING_LENGTH or not node.value.isprintable()
            ):
                raise TemplateValidationError("expression string constant is invalid")
            return
        if isinstance(node, ast.Name):
            if node.id not in self.names:
                raise TemplateValidationError(
                    f"expression uses unknown parameter {node.id!r}"
                )
            return
        if isinstance(node, ast.BinOp) and type(node.op) in self._binary_operators:
            self._validate(node.left, depth=depth + 1)
            self._validate(node.right, depth=depth + 1)
            return
        if isinstance(node, ast.UnaryOp) and type(node.op) in self._unary_operators:
            self._validate(node.operand, depth=depth + 1)
            return
        if isinstance(node, ast.IfExp):
            self._validate(node.test, depth=depth + 1)
            self._validate(node.body, depth=depth + 1)
            self._validate(node.orelse, depth=depth + 1)
            return
        if isinstance(node, ast.Compare) and all(
            type(item) in self._comparison_operators for item in node.ops
        ):
            self._validate(node.left, depth=depth + 1)
            for comparator in node.comparators:
                self._validate(comparator, depth=depth + 1)
            return
        if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            for value in node.values:
                self._validate(value, depth=depth + 1)
            return
        if isinstance(node, ast.List):
            if len(node.elts) > MAX_LIST_LENGTH:
                raise TemplateValidationError("expression list is too long")
            for element in node.elts:
                self._validate(element, depth=depth + 1)
            return
        if isinstance(node, ast.Subscript) and not isinstance(node.slice, ast.Slice):
            self._validate(node.value, depth=depth + 1)
            self._validate(node.slice, depth=depth + 1)
            return
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in self._safe_functions
            and len(node.args) == 1
            and not node.keywords
        ):
            self._validate(node.args[0], depth=depth + 1)
            return
        raise TemplateValidationError(
            f"unsupported expression syntax: {type(node).__name__}"
        )

    def _evaluate(self, node: ast.AST, values: dict[str, ParameterValue]) -> Any:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return values[node.id]
        if isinstance(node, ast.BinOp):
            left = self._bounded(self._evaluate(node.left, values))
            right = self._bounded(self._evaluate(node.right, values))
            if isinstance(node.op, ast.Pow) and (
                type(right) is not int or not 0 <= right <= 8
            ):
                raise TemplateValidationError("exponents must be integers from 0 to 8")
            if isinstance(node.op, ast.Mod) and isinstance(left, str):
                raise TemplateValidationError(
                    "string formatting is not supported in template expressions"
                )
            if isinstance(node.op, ast.Mult):
                self._check_sequence_repetition(left, right)
            return self._bounded(self._binary_operators[type(node.op)](left, right))
        if isinstance(node, ast.UnaryOp):
            return self._bounded(
                self._unary_operators[type(node.op)](
                    self._bounded(self._evaluate(node.operand, values))
                )
            )
        if isinstance(node, ast.IfExp):
            test = self._bounded(self._evaluate(node.test, values))
            branch = node.body if test else node.orelse
            return self._evaluate(branch, values)
        if isinstance(node, ast.Compare):
            left = self._bounded(self._evaluate(node.left, values))
            for operation, comparator in zip(node.ops, node.comparators, strict=True):
                right = self._bounded(self._evaluate(comparator, values))
                if not self._comparison_operators[type(operation)](left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.BoolOp):
            result = self._bounded(self._evaluate(node.values[0], values))
            for value in node.values[1:]:
                if isinstance(node.op, ast.And) and not result:
                    return result
                if isinstance(node.op, ast.Or) and result:
                    return result
                result = self._bounded(self._evaluate(value, values))
            return result
        if isinstance(node, ast.List):
            return self._bounded(
                [
                    self._bounded(self._evaluate(element, values))
                    for element in node.elts
                ]
            )
        if isinstance(node, ast.Subscript):
            value = self._bounded(self._evaluate(node.value, values))
            index = self._bounded(self._evaluate(node.slice, values))
            return value[index]
        if isinstance(node, ast.Call):
            argument = self._bounded(self._evaluate(node.args[0], values))
            return self._bounded(self._safe_functions[node.func.id](argument))
        raise AssertionError(f"unvalidated expression node: {type(node).__name__}")

    @classmethod
    def _check_sequence_repetition(cls, left: Any, right: Any) -> None:
        sequence: str | list[Any] | None = None
        count: int | None = None
        if isinstance(left, (str, list)) and type(right) is int:
            sequence, count = left, right
        elif type(left) is int and isinstance(right, (str, list)):
            sequence, count = right, left
        if sequence is None or count is None:
            return
        repetitions = max(count, 0)
        resulting_length = len(sequence) * repetitions
        if resulting_length > MAX_EXPRESSION_SEQUENCE_LENGTH:
            raise TemplateValidationError(
                "expression sequence result exceeds "
                f"{MAX_EXPRESSION_SEQUENCE_LENGTH} items"
            )
        if isinstance(sequence, list):
            payload_size = sum(cls._value_size(item) for item in sequence)
            if 1 + payload_size * repetitions > MAX_EXPRESSION_VALUE_SIZE:
                raise TemplateValidationError(
                    "expression value exceeds cumulative size limit of "
                    f"{MAX_EXPRESSION_VALUE_SIZE}"
                )

    @classmethod
    def _bounded(cls, value: Any) -> Any:
        remaining = [MAX_EXPRESSION_VALUE_SIZE]
        cls._validate_bounded_value(value, remaining=remaining, depth=0)
        return value

    @classmethod
    def _validate_bounded_value(
        cls, value: Any, *, remaining: list[int], depth: int
    ) -> None:
        if depth > MAX_EXPRESSION_VALUE_DEPTH:
            raise TemplateValidationError(
                f"expression value exceeds nesting depth {MAX_EXPRESSION_VALUE_DEPTH}"
            )
        if type(value) is bool:
            cls._spend_value_budget(remaining, 1)
            return
        if type(value) is int:
            if abs(value) > MAX_EXPRESSION_INTEGER_ABS:
                raise TemplateValidationError(
                    f"expression integer result exceeds {MAX_EXPRESSION_INTEGER_ABS}"
                )
            cls._spend_value_budget(remaining, 1)
            return
        if type(value) is float:
            if not math.isfinite(value) or abs(value) > MAX_EXPRESSION_FLOAT_ABS:
                raise TemplateValidationError(
                    "expression float result is non-finite or exceeds "
                    f"{MAX_EXPRESSION_FLOAT_ABS:g}"
                )
            cls._spend_value_budget(remaining, 1)
            return
        if isinstance(value, (str, list)):
            if len(value) > MAX_EXPRESSION_SEQUENCE_LENGTH:
                raise TemplateValidationError(
                    "expression sequence result exceeds "
                    f"{MAX_EXPRESSION_SEQUENCE_LENGTH} items"
                )
            cls._spend_value_budget(
                remaining, 1 + len(value) if isinstance(value, str) else 1
            )
            if isinstance(value, list):
                for item in value:
                    cls._validate_bounded_value(
                        item, remaining=remaining, depth=depth + 1
                    )
            return
        raise TemplateValidationError(
            f"expression produced unsupported value type {type(value).__name__}"
        )

    @staticmethod
    def _spend_value_budget(remaining: list[int], amount: int) -> None:
        remaining[0] -= amount
        if remaining[0] < 0:
            raise TemplateValidationError(
                "expression value exceeds cumulative size limit of "
                f"{MAX_EXPRESSION_VALUE_SIZE}"
            )

    @classmethod
    def _value_size(cls, value: Any) -> int:
        if isinstance(value, str):
            return 1 + len(value)
        if isinstance(value, list):
            return 1 + sum(cls._value_size(item) for item in value)
        return 1


def build_template_prompt(request: TemplateAuthoringRequest) -> str:
    profile = code_template_profile(request.topic, request.difficulty)
    candidate_count = request.num_distractors
    shapes = [
        {
            "kinds": list(shape.kinds),
            "names": list(shape.names) if shape.names is not None else None,
        }
        for shape in profile.parameter_shapes
    ]
    contract = json.dumps(
        {
            "topic": profile.topic,
            "difficulty": profile.difficulty,
            "answer_target": profile.answer_target,
            "answer_kind": profile.answer_kind,
            "accepted_parameter_shapes": shapes,
            "required_code_features": sorted(profile.required_features),
            "positive_integer_values_required": profile.require_positive_integers,
            "required_parameter_values": profile.required_parameter_values,
            "authoring_requirements": profile.guidance,
        },
        indent=2,
        sort_keys=True,
    )
    prompt = (
        "Follow this exact capability contract. Choose exactly one accepted parameter "
        "shape. A null names value means choose valid names but preserve the exact "
        "number, order, and kinds. Do not add parameters.\n"
        f"{contract}\n"
        f"Use answer_target={profile.answer_target}. "
        f"Create exactly {candidate_count} distractor candidates; the local validator "
        f"will select {request.num_distractors}. Every candidate should model a real "
        "misconception and should differ from the answer and other candidates for the "
        "complete Cartesian product. The local application adds mechanical fallback "
        "candidates; do not add generic answer-plus-constant fallbacks yourself. In "
        "reason_template, use only plain placeholders such as "
        "`{n}`; never put expressions such as `{n-1}` inside braces. "
        "Keep the complete Cartesian product valid."
    )
    return prompt


CODE_TEMPLATE_SYSTEM_PROMPT = """\
Generate the judgment-bearing fields for one reusable Python execution-trace MCQ
template, not one concrete question. The local application derives identity, topic,
difficulty, answer target, question wording, version, and question type.

The proposal must use a finite Cartesian product of typed finite parameter values so
the local application can exhaustively validate every possible question once.

Rules:
- `code` is the learner-facing Python program that the question asks about. It must
  directly perform the selected topic's computation or control flow. Never write a
  question generator, template generator, metadata dictionary, schema, or code that
  stores answer/distractor expressions as strings. Keep code, answer_expression, and
  distractor candidates as separate schema fields.
- Define one module-level entry function whose positional arguments exactly match the
  parameter names and order. Use every parameter in executed learner-facing behavior.
  Helper functions are allowed. The code must work for every parameter combination.
- Use only expressions, assignments, if statements, and for loops. Do not use imports,
  attributes, classes, decorators, recursion, comprehensions, while loops, lambdas,
  exceptions, file access, networking, input, eval, or exec.
- Every parameter declares a kind and two to four distinct finite values. Supported
  kinds are integer (-100 through 100), boolean, string (non-empty short printable
  text), and
  integer_list (at most eight integers from -100 through 100). Use JSON booleans.
- The user prompt states the selected answer target. answer_expression must calculate
  that target using parameter names,
  numeric constants, arithmetic, comparisons, boolean operators, or a conditional
  expression. String constants, list literals, indexing, and the one-argument functions
  len, sum, min, max, sorted, all, and any are also supported. Do not use methods or
  other function calls.
- Each distractor candidate must represent a specific misconception. The local
  validator selects candidates that are unique, type-compatible, and different from
  the answer for every parameter combination. The local application adds mechanical
  fallback candidates after the provider response.
- reason_template explains its misconception and may use only a bare parameter
  placeholder such as `{n}`. Do not place arithmetic or any other expression inside
  braces.
- Return only the proposal schema fields and no markdown. Do not add locally derived
  fields.
"""


def render_template(
    source: str, values: dict[str, ParameterValue], *, require_all: bool = False
) -> str:
    fields: set[str] = set()
    try:
        parsed = list(Formatter().parse(source))
    except ValueError as exc:
        raise TemplateValidationError(f"invalid text template: {exc}") from exc
    for _, field_name, format_spec, conversion in parsed:
        if field_name is None:
            continue
        if field_name not in values:
            raise TemplateValidationError(
                f"text template uses unknown parameter {field_name!r}"
            )
        if format_spec or conversion:
            raise TemplateValidationError(
                "text templates do not support conversions or format specifications"
            )
        fields.add(field_name)
    if require_all and fields != set(values):
        raise TemplateValidationError(
            "question_template placeholders must exactly match the parameters"
        )
    rendered = source.format_map(values)
    if not rendered.strip():
        raise TemplateValidationError("rendered text must not be blank")
    return rendered


def template_sha256(template: CodeQuestionTemplate) -> str:
    payload = json.dumps(
        template.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


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


def _seeded_choice(
    values: list[ParameterValue], digest: str, seed: int, name: str
) -> ParameterValue:
    payload = f"{digest}:{seed}:{name}".encode()
    index = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % len(values)
    return values[index]


def _case_count(template: CodeQuestionTemplate) -> int:
    combinations = 1
    for parameter in template.parameters:
        combinations *= len(parameter.values)
    return combinations
