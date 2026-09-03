"""Repeatable real-provider evaluation for code-template authoring."""

from __future__ import annotations

import statistics
import time
from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from edcraft_validator.domains.code.application import QuestionTemplateApplication
from edcraft_validator.domains.code.capabilities import Difficulty, ProgrammingTopic
from edcraft_validator.domains.code.templates import (
    ApprovedCodeQuestionTemplate,
    TemplateValidationError,
    TemplateValidator,
)
from edcraft_validator.generation.base import GenerationError, QuestionTemplateGenerator
from edcraft_validator.generation.models import (
    TemplateAuthoringRequest,
    TemplateProviderSelection,
)
from edcraft_validator.generation.registry import create_template_generator

GeneratorFactory = Callable[[TemplateProviderSelection], QuestionTemplateGenerator]
ValidatorFactory = Callable[[], TemplateValidator]
AttemptObserver = Callable[["TemplateEvaluationAttempt"], None]


class TemplateEvaluationAttempt(BaseModel):
    """One complete provider → normalization → validation attempt."""

    model_config = ConfigDict(extra="forbid", strict=True)

    attempt: int = Field(ge=1)
    provider: str
    model: str
    request: TemplateAuthoringRequest
    status: Literal["approved", "failed"]
    prompt_version: str | None = None
    prompt_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    generation_duration_ms: float | None = Field(default=None, ge=0)
    validation_duration_ms: float | None = Field(default=None, ge=0)
    total_duration_ms: float = Field(ge=0)
    failure_stage: (
        Literal[
            "configuration", "generation", "normalization", "validation", "unexpected"
        ]
        | None
    ) = None
    failure_code: str | None = None
    error: str | None = None
    approved_template: ApprovedCodeQuestionTemplate | None = None


class TemplateEvaluationGroup(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    provider: str
    model: str
    topic: ProgrammingTopic
    difficulty: Difficulty
    attempts: int = Field(ge=1)
    approved: int = Field(ge=0)
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
    approved: int = Field(ge=0)
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
        generator_factory: GeneratorFactory = create_template_generator,
        validator_factory: ValidatorFactory = TemplateValidator,
    ) -> None:
        self.generator_factory = generator_factory
        self.validator_factory = validator_factory

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
                request = TemplateAuthoringRequest(
                    topic=topic,
                    difficulty=difficulty,
                    num_distractors=num_distractors,
                )
                for _ in range(repetitions):
                    attempt_number += 1
                    attempt = self._evaluate_once(
                        attempt_number,
                        TemplateProviderSelection(provider=provider, model=model),
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
        request: TemplateAuthoringRequest,
    ) -> TemplateEvaluationAttempt:
        started = time.perf_counter()
        generator: QuestionTemplateGenerator | None = None
        prompt_version = None
        prompt_sha256 = None
        resolved_model = selection.model or "<provider-default>"
        try:
            generator = self.generator_factory(selection)
            resolved_model = generator.model
            prompt = generator.prompt_metadata(request)
            prompt_version = prompt.version
            prompt_sha256 = prompt.sha256
            application = QuestionTemplateApplication(
                generator_factory=lambda _: generator,
                validator_factory=self.validator_factory,
            )
            approved = application.author(
                request,
                provider=selection.provider,
                model=selection.model,
            )
        except Exception as exc:
            stage, code = _classify_failure(exc, generator is not None)
            return TemplateEvaluationAttempt(
                attempt=attempt_number,
                provider=selection.provider,
                model=resolved_model,
                request=request,
                status="failed",
                prompt_version=prompt_version,
                prompt_sha256=prompt_sha256,
                total_duration_ms=(time.perf_counter() - started) * 1000,
                failure_stage=stage,
                failure_code=code,
                error=str(exc),
            )

        provenance = approved.authoring
        if provenance is None:
            raise RuntimeError("authored template did not include provenance")
        return TemplateEvaluationAttempt(
            attempt=attempt_number,
            provider=provenance.provider,
            model=provenance.model,
            request=request,
            status="approved",
            prompt_version=provenance.prompt.version,
            prompt_sha256=provenance.prompt.sha256,
            generation_duration_ms=provenance.generation_duration_ms,
            validation_duration_ms=provenance.validation_duration_ms,
            total_duration_ms=(time.perf_counter() - started) * 1000,
            approved_template=approved,
        )


def _classify_failure(
    error: Exception, generator_created: bool
) -> tuple[
    Literal["configuration", "generation", "normalization", "validation", "unexpected"],
    str,
]:
    if isinstance(error, GenerationError):
        stage = "generation" if generator_created else "configuration"
        return stage, error.category
    if isinstance(error, TemplateValidationError):
        return "validation", error.code
    if isinstance(error, ValidationError):
        return "normalization", "SCHEMA_VALIDATION"
    if isinstance(error, ValueError):
        return "normalization", "NORMALIZATION_ERROR"
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
            attempt.request.topic,
            attempt.request.difficulty,
        )
        grouped.setdefault(key, []).append(attempt)

    groups = [_summarize_group(key, values) for key, values in sorted(grouped.items())]
    approved = sum(attempt.status == "approved" for attempt in attempts)
    failures = Counter(
        attempt.failure_code for attempt in attempts if attempt.failure_code is not None
    )
    return TemplateEvaluationSummary(
        attempts=len(attempts),
        approved=approved,
        failed=len(attempts) - approved,
        pass_rate=approved / len(attempts),
        failure_counts=dict(sorted(failures.items())),
        groups=groups,
    )


def _summarize_group(
    key: tuple[str, str, ProgrammingTopic, Difficulty],
    attempts: list[TemplateEvaluationAttempt],
) -> TemplateEvaluationGroup:
    provider, model, topic, difficulty = key
    approved = sum(attempt.status == "approved" for attempt in attempts)
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
        approved=approved,
        failed=len(attempts) - approved,
        pass_rate=approved / len(attempts),
        failure_counts=dict(sorted(failures.items())),
        mean_total_duration_ms=statistics.fmean(durations),
        median_total_duration_ms=statistics.median(durations),
        min_total_duration_ms=min(durations),
        max_total_duration_ms=max(durations),
    )
