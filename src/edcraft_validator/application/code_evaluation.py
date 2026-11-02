"""Repeatable real-provider evaluation for code-template authoring."""

from __future__ import annotations

import statistics
import time
from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_serializer,
    model_validator,
)

from edcraft_validator.application.authoring_contracts import (
    AuthoringFailure,
    AuthoringResult,
    FailureStage,
)
from edcraft_validator.application.template_workflow import TemplateApplication
from edcraft_validator.domains.code.code_domain import CodeDomain
from edcraft_validator.domains.code.code_schemas import (
    CodeTemplateRequest,
    TemplateValidationError,
    ValidatedCodeTemplate,
)
from edcraft_validator.domains.code.code_types import Difficulty, ProgrammingTopic
from edcraft_validator.domains.code.profiles import code_template_profile
from edcraft_validator.domains.code.prompt_builder import build_code_generation_request
from edcraft_validator.llm.llm_contracts import (
    ModelProvider,
    TemplateProviderSelection,
    ToolCatalogueSnapshot,
)
from edcraft_validator.llm.llm_errors import GenerationError
from edcraft_validator.llm.provider_registry import create_model_provider
from edcraft_validator.mcp.catalogue import ToolCatalogueError
from edcraft_validator.mcp.client import FastMcpToolClient
from edcraft_validator.mcp.server import create_validation_server
from edcraft_validator.tools.python_execution import PythonExecutionTool
from edcraft_validator.validation.validation_contracts import (
    ValidationEvidence,
    ValidationIssue,
)

ProviderFactory = Callable[[TemplateProviderSelection], ModelProvider]
AttemptObserver = Callable[["TemplateEvaluationAttempt"], None]


class TemplateEvaluationAttempt(BaseModel):
    """One complete provider → template building → validation attempt."""

    model_config = ConfigDict(extra="forbid", strict=True)

    attempt: int = Field(ge=1)
    provider: str
    model: str
    topic: ProgrammingTopic
    request: CodeTemplateRequest
    status: Literal["validated", "failed"]
    prompt_version: str | None = None
    generation_duration_ms: float | None = Field(default=None, ge=0)
    total_duration_ms: float = Field(ge=0)
    failure_stage: FailureStage | None = None
    failure_code: str | None = None
    error: str | None = None
    tool_catalogue: list[dict[str, Any]] = Field(default_factory=list)
    validation_evidence: list[ValidationEvidence] = Field(default_factory=list)
    validated_template: ValidatedCodeTemplate | None = None
    authoring_result: AuthoringResult | None = None

    @model_validator(mode="after")
    def restore_report_views(self):
        """Derive Python convenience fields from the one saved authoring report."""
        result = self.authoring_result
        if result is None:
            return self
        self.tool_catalogue = result.tool_catalogue
        if result.artifact is not None:
            self.validated_template = ValidatedCodeTemplate.model_validate_json(
                result.artifact.model_dump_json()
            )
            self.validation_evidence = self.validated_template.validation.evidence
        else:
            self.validation_evidence = [
                ValidationEvidence(
                    check=item.tool,
                    status="incomplete" if item.status == "error" else item.status,
                    issues=[
                        ValidationIssue(**finding.model_dump())
                        for finding in item.findings
                    ],
                    details=item.details,
                    duration_ms=item.duration_ms,
                )
                for attempt in result.attempts
                for execution in attempt.executions
                if (item := execution.evidence) is not None
            ]
        return self

    @model_serializer(mode="wrap")
    def serialize_report_once(self, handler):
        """Keep convenience fields in memory without duplicating saved content."""
        payload = handler(self)
        if payload.get("authoring_result") is not None:
            for key in ("validated_template", "tool_catalogue", "validation_evidence"):
                payload.pop(key, None)
        return payload


class TemplateEvaluationGroup(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    provider: str
    model: str
    topic: ProgrammingTopic
    difficulty: Difficulty
    attempts: int = Field(ge=1)
    validated: int = Field(ge=0)
    failed: int = Field(ge=0)
    pass_rate: float = Field(ge=0, le=1)
    failure_counts: dict[str, int]
    mean_total_duration_ms: float = Field(ge=0)
    median_total_duration_ms: float = Field(ge=0)
    min_total_duration_ms: float = Field(ge=0)
    max_total_duration_ms: float = Field(ge=0)


class TemplateEvaluationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    attempts: int = Field(ge=1)
    validated: int = Field(ge=0)
    failed: int = Field(ge=0)
    pass_rate: float = Field(ge=0, le=1)
    failure_counts: dict[str, int]
    groups: list[TemplateEvaluationGroup]


class TemplateEvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    attempts: list[TemplateEvaluationAttempt] = Field(min_length=1)
    summary: TemplateEvaluationSummary

    def write_jsonl(self, output: Path) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        rendered = "\n".join(item.model_dump_json() for item in self.attempts)
        output.write_text(rendered + "\n")


class TemplateEvaluator:
    """Evaluate the same application workflow used by a future frontend."""

    def __init__(
        self,
        *,
        provider_factory: ProviderFactory = create_model_provider,
        execution_tool: PythonExecutionTool | None = None,
        timeout_seconds: float = 2.0,
    ) -> None:
        self.provider_factory = provider_factory
        self.tool_client = FastMcpToolClient(
            create_validation_server(
                code_execution_tool=execution_tool,
                code_execution_timeout_seconds=timeout_seconds,
            )
        )
        self.domain = CodeDomain()

    def evaluate(
        self,
        *,
        provider: str,
        model: str | None,
        topics: Sequence[ProgrammingTopic],
        difficulties: Sequence[Difficulty],
        repetitions: int,
        num_distractors: int = 3,
        on_attempt: AttemptObserver | None = None,
    ) -> TemplateEvaluationReport:
        if repetitions < 1:
            raise ValueError("repetitions must be at least 1")
        if not topics:
            raise ValueError("at least one topic is required")
        if not difficulties:
            raise ValueError("at least one difficulty is required")
        attempts: list[TemplateEvaluationAttempt] = []
        attempt_number = 0
        for topic in topics:
            for difficulty in difficulties:
                profile = code_template_profile(topic, difficulty)
                request = CodeTemplateRequest(
                    prompt=(f"Create a Python MCQ about {topic}. {profile.guidance}"),
                    difficulty=difficulty,
                    num_distractors=num_distractors,
                )
                for _ in range(repetitions):
                    attempt_number += 1
                    attempt = self._evaluate_once(
                        attempt_number,
                        TemplateProviderSelection(provider=provider, model=model),
                        topic,
                        request,
                    )
                    attempts.append(attempt)
                    if on_attempt is not None:
                        on_attempt(attempt)
        return TemplateEvaluationReport(
            attempts=attempts,
            summary=_summarize(attempts),
        )

    def _evaluate_once(
        self,
        attempt_number: int,
        selection: TemplateProviderSelection,
        topic: ProgrammingTopic,
        request: CodeTemplateRequest,
    ) -> TemplateEvaluationAttempt:
        started = time.perf_counter()
        model_provider: ModelProvider | None = None
        prompt_version = None
        resolved_model = selection.model or "<provider-default>"
        catalogue_snapshot: ToolCatalogueSnapshot | None = None

        def record_catalogue(snapshot: ToolCatalogueSnapshot) -> None:
            nonlocal catalogue_snapshot
            catalogue_snapshot = snapshot

        try:
            model_provider = self.provider_factory(selection)
            resolved_model = model_provider.model
            generation_request = build_code_generation_request(request)
            prompt_version = generation_request.prompt_version
            application = TemplateApplication(tool_client=self.tool_client)
            result = application.author_template(
                request,
                domain=self.domain,
                provider=model_provider,
                on_catalogue_resolved=record_catalogue,
            )
            if result.artifact is None:
                raise AuthoringFailure(result)
            validated = result.artifact
        except AuthoringFailure as exc:
            result = exc.result
            stage, code = _terminal_failure(result)
            return TemplateEvaluationAttempt(
                attempt=attempt_number,
                provider=selection.provider,
                model=resolved_model,
                topic=topic,
                request=request,
                status="failed",
                prompt_version=prompt_version,
                generation_duration_ms=result.generation_duration_ms,
                total_duration_ms=(time.perf_counter() - started) * 1000,
                failure_stage=stage,
                failure_code=code,
                error=result.reason,
                authoring_result=result,
            )
        except Exception as exc:
            stage, code = _classify_failure(exc, model_provider is not None)
            return TemplateEvaluationAttempt(
                attempt=attempt_number,
                provider=selection.provider,
                model=resolved_model,
                topic=topic,
                request=request,
                status="failed",
                prompt_version=prompt_version,
                total_duration_ms=(time.perf_counter() - started) * 1000,
                failure_stage=stage,
                failure_code=code,
                error=str(exc),
                tool_catalogue=(
                    catalogue_snapshot.summaries() if catalogue_snapshot else []
                ),
                validation_evidence=(
                    exc.evidence if isinstance(exc, TemplateValidationError) else []
                ),
            )

        provenance = validated.authoring
        if provenance is None:
            raise RuntimeError("authored template did not include provenance")
        return TemplateEvaluationAttempt(
            attempt=attempt_number,
            provider=provenance.provider,
            model=provenance.model,
            topic=topic,
            request=request,
            status="validated",
            prompt_version=provenance.base_prompt_version,
            generation_duration_ms=provenance.generation_duration_ms,
            total_duration_ms=(time.perf_counter() - started) * 1000,
            authoring_result=result,
        )


def _terminal_failure(result: AuthoringResult) -> tuple[FailureStage, str]:
    if result.failure is not None:
        return result.failure.stage, result.failure.code
    if result.attempts:
        for execution in result.attempts[-1].executions:
            if execution.passed:
                continue
            if execution.evidence is not None and execution.evidence.findings:
                stage = (
                    "checking" if execution.evidence.status == "error" else "validation"
                )
                return stage, execution.evidence.findings[0].code
            return "checking", "TOOL_CALL_ERROR"
    return "validation", result.status


def _classify_failure(
    error: Exception, generator_created: bool
) -> tuple[FailureStage, str]:
    if isinstance(error, ToolCatalogueError):
        return "configuration", "MCP_CATALOGUE_ERROR"
    if isinstance(error, GenerationError):
        stage = "generation" if generator_created else "configuration"
        return stage, error.category
    if isinstance(error, TemplateValidationError):
        return "validation", error.code
    if isinstance(error, ValidationError):
        return "template_building", "SCHEMA_VALIDATION"
    if isinstance(error, ValueError):
        return "template_building", "TEMPLATE_BUILDING_ERROR"
    return "unexpected", type(error).__name__


def _summarize(
    attempts: list[TemplateEvaluationAttempt],
) -> TemplateEvaluationSummary:
    grouped: dict[
        tuple[str, str, ProgrammingTopic, Difficulty],
        list[TemplateEvaluationAttempt],
    ] = {}
    for attempt in attempts:
        key = (
            attempt.provider,
            attempt.model,
            attempt.topic,
            attempt.request.difficulty,
        )
        grouped.setdefault(key, []).append(attempt)

    groups = [_summarize_group(key, values) for key, values in sorted(grouped.items())]
    validated = sum(attempt.status == "validated" for attempt in attempts)
    failures = Counter(
        attempt.failure_code for attempt in attempts if attempt.failure_code is not None
    )
    return TemplateEvaluationSummary(
        attempts=len(attempts),
        validated=validated,
        failed=len(attempts) - validated,
        pass_rate=validated / len(attempts),
        failure_counts=dict(sorted(failures.items())),
        groups=groups,
    )


def _summarize_group(
    key: tuple[str, str, ProgrammingTopic, Difficulty],
    attempts: list[TemplateEvaluationAttempt],
) -> TemplateEvaluationGroup:
    provider, model, topic, difficulty = key
    validated = sum(attempt.status == "validated" for attempt in attempts)
    durations = [attempt.total_duration_ms for attempt in attempts]
    failures = Counter(
        attempt.failure_code for attempt in attempts if attempt.failure_code is not None
    )
    return TemplateEvaluationGroup(
        provider=provider,
        model=model,
        topic=topic,
        difficulty=difficulty,
        attempts=len(attempts),
        validated=validated,
        failed=len(attempts) - validated,
        pass_rate=validated / len(attempts),
        failure_counts=dict(sorted(failures.items())),
        mean_total_duration_ms=statistics.fmean(durations),
        median_total_duration_ms=statistics.median(durations),
        min_total_duration_ms=min(durations),
        max_total_duration_ms=max(durations),
    )
