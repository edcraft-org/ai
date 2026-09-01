"""Reusable, exhaustively validated templates for Python questions."""

from __future__ import annotations

import ast
import hashlib
import itertools
import json
import operator
from string import Formatter
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from edcraft_validator.comparison import equivalent, same_value_shape
from edcraft_validator.executor import DockerExecutor, ExecutionBackend, ExecutionResult
from edcraft_validator.generation.models import (
    Difficulty,
    ProgrammingTopic,
    TemplateAuthoringRequest,
)
from edcraft_validator.models import AnswerTarget, GeneratedQuestion
from edcraft_validator.safety import check_code_safety

MAX_TEMPLATE_CASES = 64


class IntegerParameter(BaseModel):
    """A finite parameter domain that can be validated exhaustively."""

    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    values: list[int] = Field(min_length=2, max_length=4)

    @field_validator("values")
    @classmethod
    def validate_values(cls, values: list[int]) -> list[int]:
        if len(values) != len(set(values)):
            raise ValueError("parameter values must be unique")
        if any(abs(value) > 100 for value in values):
            raise ValueError("parameter values must be between -100 and 100")
        return values


class DistractorRecipe(BaseModel):
    """A deterministic misconception applied to concrete parameter values."""

    model_config = ConfigDict(extra="forbid", strict=True)

    expression: str = Field(min_length=1)
    reason_template: str = Field(min_length=1)


class CodeQuestionTemplate(BaseModel):
    """Provider-neutral template contract for the first code-domain version."""

    model_config = ConfigDict(extra="forbid", strict=True)

    template_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    version: int = Field(ge=1)
    topic: ProgrammingTopic
    difficulty: Difficulty
    code: str = Field(min_length=1)
    entry_function: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    parameters: list[IntegerParameter] = Field(min_length=1, max_length=3)
    question_template: str = Field(min_length=1)
    answer_target: AnswerTarget
    answer_expression: str = Field(min_length=1)
    distractors: list[DistractorRecipe] = Field(min_length=2, max_length=3)
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

    cases_validated: int = Field(ge=1)
    template_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ApprovedCodeQuestionTemplate(BaseModel):
    """A template plus evidence that its complete finite domain was checked."""

    model_config = ConfigDict(extra="forbid", strict=True)

    template: CodeQuestionTemplate
    validation: TemplateValidationSummary


class TemplateQuestionInstance(BaseModel):
    """A reproducible question expanded from an approved template."""

    model_config = ConfigDict(extra="forbid", strict=True)

    template_id: str
    template_version: int
    template_sha256: str
    seed: int
    parameters: dict[str, int]
    question: GeneratedQuestion


class TemplateValidationError(ValueError):
    """Raised when any possible instance fails template approval."""


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

    def validate(self, template: CodeQuestionTemplate) -> ApprovedCodeQuestionTemplate:
        names = tuple(parameter.name for parameter in template.parameters)
        self._validate_structure(template, names)
        answer = SafeExpression(template.answer_expression, names)
        distractors = [
            SafeExpression(recipe.expression, names) for recipe in template.distractors
        ]

        value_domains = [parameter.values for parameter in template.parameters]
        inputs_cases = [
            dict(zip(names, values, strict=True))
            for values in itertools.product(*value_domains)
        ]
        executions = self._execute_all(template, inputs_cases)
        for inputs, execution in zip(inputs_cases, executions, strict=True):
            expected_answer = answer.evaluate(inputs)
            _require_json_value(expected_answer, "answer")
            if not execution.ok:
                detail = execution.error_message or execution.error_code or "unknown"
                raise TemplateValidationError(
                    f"template execution failed for inputs {inputs}: {detail}"
                )
            actual_answer = _execution_answer(execution, template.answer_target)
            if not equivalent(actual_answer, expected_answer):
                raise TemplateValidationError(
                    "answer_expression does not match the execution target for "
                    f"inputs {inputs}: expression={expected_answer!r}, "
                    f"execution={actual_answer!r}"
                )

            generated_distractors = [item.evaluate(inputs) for item in distractors]
            self._validate_distractors(inputs, expected_answer, generated_distractors)
            render_template(template.question_template, inputs, require_all=True)
            for recipe in template.distractors:
                render_template(recipe.reason_template, inputs)

        return ApprovedCodeQuestionTemplate(
            template=template,
            validation=TemplateValidationSummary(
                cases_validated=len(inputs_cases),
                template_sha256=template_sha256(template),
            ),
        )

    def _execute_all(
        self,
        template: CodeQuestionTemplate,
        inputs: list[dict[str, int]],
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
                "executor returned the wrong number of batch results"
            )
        return results

    @staticmethod
    def _validate_structure(
        template: CodeQuestionTemplate, names: tuple[str, ...]
    ) -> None:
        safety = check_code_safety(template.code, template.entry_function)
        if not safety.is_safe:
            raise TemplateValidationError("; ".join(safety.errors))
        arguments = _entry_function_arguments(template.code, template.entry_function)
        if arguments != names:
            raise TemplateValidationError(
                "entry function arguments must exactly match parameter order: "
                f"expected {names}, received {arguments}"
            )
        if template.entry_function not in template.question_template:
            raise TemplateValidationError(
                "question_template must name the entry function"
            )
        render_template(
            template.question_template,
            {name: 0 for name in names},
            require_all=True,
        )

    @staticmethod
    def _validate_distractors(
        inputs: dict[str, int], answer: Any, distractors: list[Any]
    ) -> None:
        for index, distractor in enumerate(distractors):
            _require_json_value(distractor, f"distractor {index}")
            if not same_value_shape(distractor, answer):
                raise TemplateValidationError(
                    f"distractor {index} has the wrong type for inputs {inputs}"
                )
            if equivalent(distractor, answer):
                raise TemplateValidationError(
                    f"distractor {index} equals the answer for inputs {inputs}"
                )
            if any(
                equivalent(distractor, previous) for previous in distractors[:index]
            ):
                raise TemplateValidationError(
                    f"distractor {index} is duplicated for inputs {inputs}"
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
            parameter.name: _seeded_choice(
                parameter.values, digest, seed, parameter.name
            )
            for parameter in template.parameters
        }
        names = tuple(inputs)
        answer = SafeExpression(template.answer_expression, names).evaluate(inputs)
        distractors = [
            SafeExpression(recipe.expression, names).evaluate(inputs)
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
    }

    def __init__(self, source: str, names: tuple[str, ...]) -> None:
        self.source = source
        self.names = frozenset(names)
        try:
            self.expression = ast.parse(source, mode="eval").body
        except SyntaxError as exc:
            raise TemplateValidationError(
                f"invalid template expression {source!r}: {exc.msg}"
            ) from exc
        self._validate(self.expression, depth=0)

    def evaluate(self, values: dict[str, int]) -> Any:
        try:
            return self._evaluate(self.expression, values)
        except (ArithmeticError, OverflowError) as exc:
            raise TemplateValidationError(
                f"expression {self.source!r} failed for {values}: {exc}"
            ) from exc

    def _validate(self, node: ast.AST, *, depth: int) -> None:
        if depth > 20:
            raise TemplateValidationError("template expression is too deeply nested")
        if isinstance(node, ast.Constant):
            if type(node.value) not in {int, float, bool}:
                raise TemplateValidationError(
                    "template expressions support only numeric and boolean constants"
                )
            if isinstance(node.value, (int, float)) and abs(node.value) > 10_000:
                raise TemplateValidationError("expression constant is too large")
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
        raise TemplateValidationError(
            f"unsupported expression syntax: {type(node).__name__}"
        )

    def _evaluate(self, node: ast.AST, values: dict[str, int]) -> Any:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return values[node.id]
        if isinstance(node, ast.BinOp):
            left = self._evaluate(node.left, values)
            right = self._evaluate(node.right, values)
            if isinstance(node.op, ast.Pow) and (
                type(right) is not int or not 0 <= right <= 8
            ):
                raise TemplateValidationError("exponents must be integers from 0 to 8")
            return self._binary_operators[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp):
            return self._unary_operators[type(node.op)](
                self._evaluate(node.operand, values)
            )
        if isinstance(node, ast.IfExp):
            branch = node.body if self._evaluate(node.test, values) else node.orelse
            return self._evaluate(branch, values)
        if isinstance(node, ast.Compare):
            left = self._evaluate(node.left, values)
            for operation, comparator in zip(node.ops, node.comparators, strict=True):
                right = self._evaluate(comparator, values)
                if not self._comparison_operators[type(operation)](left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.BoolOp):
            evaluated = [self._evaluate(value, values) for value in node.values]
            return all(evaluated) if isinstance(node.op, ast.And) else any(evaluated)
        raise AssertionError(f"unvalidated expression node: {type(node).__name__}")


def build_template_prompt(request: TemplateAuthoringRequest) -> str:
    target = answer_target_for_topic(request.topic)
    parameter_guidance = (
        "Use exactly one integer parameter named n."
        if request.topic == "loops"
        else "Use two or three integer parameters with two or three values each."
    )
    prompt = (
        f"Topic: {request.topic}\n"
        f"Difficulty: {request.difficulty}\n"
        f"Use answer_target={target}. "
        f"Create exactly {request.num_distractors} distractor recipes. "
        f"{parameter_guidance} "
        "Keep the complete Cartesian product valid."
    )
    if request.topic == "loops":
        prompt += (
            " Give n two or three distinct positive values from 2 through 6. Use "
            "exactly one for loop written as `for i in range(n)`. Set "
            "answer_expression to exactly `n`. Suitable distinct distractor "
            "expressions include `n - 1`, `n + 1`, and `n + 2`."
        )
    return prompt


def answer_target_for_topic(topic: ProgrammingTopic) -> AnswerTarget:
    """Choose the initial trace question supported for each programming topic."""
    return {
        "arithmetic": "return_value",
        "conditionals": "branch_executions",
        "loops": "loop_iterations",
        "functions": "function_calls",
        "lists": "return_value",
    }[topic]


CODE_TEMPLATE_SYSTEM_PROMPT = """\
Generate one reusable Python execution-trace MCQ template, not one concrete question.
The template must use a finite Cartesian product of integer parameter values so the
local application can exhaustively validate every possible question once.

Rules:
- Define one module-level entry function whose positional arguments exactly match the
  parameter names and order. The code must work for every parameter combination.
- Use only expressions, assignments, if statements, and for loops. Do not use imports,
  attributes, classes, decorators, recursion, comprehensions, while loops, lambdas,
  exceptions, file access, networking, input, eval, or exec.
- Each parameter must contain two or three distinct integer values between -100 and 100.
- question_template must name the entry function and contain exactly one simple
  {parameter_name} placeholder for every parameter.
- answer_target selects what the question asks: return_value is the entry function's
  return value; loop_iterations is the total number of loop-body iterations across all
  loops; loop_executions is the number of loop statements encountered; branch_executions
  is the number of evaluated if conditions; and function_calls is all traced calls,
  including the entry function and safe built-ins. Phrase the question unambiguously.
- answer_expression must calculate the selected answer_target using parameter names,
  numeric constants, arithmetic, comparisons, boolean operators, or a conditional
  expression. Do not use function calls.
- Each distractor expression must represent a specific misconception and must be unique,
  type-compatible, and different from the answer for every parameter combination.
- reason_template explains its misconception and may use simple parameter placeholders.
- Return only the schema fields and no markdown.
"""


def render_template(
    source: str, values: dict[str, int], *, require_all: bool = False
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


def _require_json_value(value: Any, label: str) -> None:
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise TemplateValidationError(f"{label} is not a finite JSON value") from exc


def _seeded_choice(values: list[int], digest: str, seed: int, name: str) -> int:
    payload = f"{digest}:{seed}:{name}".encode()
    index = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % len(values)
    return values[index]


def _case_count(template: CodeQuestionTemplate) -> int:
    combinations = 1
    for parameter in template.parameters:
        combinations *= len(parameter.values)
    return combinations
