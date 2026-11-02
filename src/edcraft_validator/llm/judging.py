"""Run a domain-owned structured judge request, retaining failures and usage."""

import asyncio
import hashlib
import json
import math
import time
from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from edcraft_validator.llm.llm_contracts import (
    ModelProvider,
    StructuredGenerationRequest,
)
from edcraft_validator.llm.llm_errors import GenerationError
from edcraft_validator.llm.usage import (
    MeasuredProvider,
    ModelCallRecord,
    ModelUsageSummary,
    close_provider,
    summarize_usage,
)

DEFAULT_JUDGE_TIMEOUT_SECONDS = 310.0

JudgeProviderFactory = Callable[[], ModelProvider]


class JudgeValidationFinding(BaseModel):
    location: list[str | int]
    code: str
    message: str


class JudgeRun[AssessmentT: BaseModel](BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["completed", "error"]
    provider: str | None = None
    model: str | None = None
    provider_settings: dict[str, Any] = Field(default_factory=dict)
    prompt_version: str
    request_sha256: str
    timeout_seconds: float
    assessment: AssessmentT | None = None
    error_code: str | None = None
    validation_errors: list[JudgeValidationFinding] = Field(default_factory=list)
    model_calls: list[ModelCallRecord] = Field(default_factory=list)
    usage: ModelUsageSummary = Field(default_factory=ModelUsageSummary)
    duration_ms: float = 0


async def run_judge[AssessmentT: BaseModel](
    request: StructuredGenerationRequest[AssessmentT],
    *,
    provider_factory: JudgeProviderFactory,
    timeout_seconds: float = DEFAULT_JUDGE_TIMEOUT_SECONDS,
) -> JudgeRun[AssessmentT]:
    """One application call; no repair retries or replacement judgments.

    A deadline stops waiting, not the synchronous provider thread. Late results
    are ignored. Token usage on that path is unknown; transport timeouts/retries
    still belong to the configured provider.
    """
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("judge timeout must be finite and positive")
    started = time.perf_counter()
    report = _new_run(request, timeout_seconds)
    measured = None
    provider = None
    try:
        provider = provider_factory()
        report.provider, report.model = provider.provider, provider.model
        report.provider_settings = provider.generation_settings()
        if request.reasoning_effort is not None:
            report.provider_settings["reasoning_effort"] = request.reasoning_effort
        measured = MeasuredProvider(provider)
    except Exception:
        report.error_code = "JUDGE_CONFIGURATION_ERROR"
        report.duration_ms = (time.perf_counter() - started) * 1000
        close_provider(provider)
        return report
    call_started = time.perf_counter()
    try:
        async with asyncio.timeout(timeout_seconds):
            assessment = await asyncio.to_thread(_execute_judge, measured, request)
        report.assessment = request.response_model.model_validate_json(
            assessment.model_dump_json()
        )
        report.status = "completed"
    except TimeoutError:
        report.error_code = "JUDGE_TIMEOUT"
        report.model_calls = [
            ModelCallRecord(
                operation="judging",
                duration_ms=(time.perf_counter() - call_started) * 1000,
                error="timeout",
                usage_unavailable_reason="Judge deadline expired; usage is unknown",
            )
        ]
    except GenerationError as exc:
        report.error_code = f"JUDGE_{exc.category.upper()}"
        if isinstance(exc.__cause__, ValidationError):
            report.validation_errors = validation_findings(exc.__cause__)
    except ValidationError as exc:
        report.error_code = "JUDGE_INVALID_RESPONSE"
        report.validation_errors = validation_findings(exc)
    except (AttributeError, TypeError, ValueError):
        report.error_code = "JUDGE_INVALID_RESPONSE"
    except Exception:
        report.error_code = "JUDGE_INTERNAL_ERROR"
    if not report.model_calls:
        report.model_calls = [call.model_copy(deep=True) for call in measured.calls]
    if report.status == "error" and report.model_calls:
        report.model_calls[-1].error = report.error_code
    report.usage = summarize_usage(report.model_calls)
    report.duration_ms = (time.perf_counter() - started) * 1000
    return report


def failed_judge(request, code, timeout_seconds):
    report = _new_run(request, timeout_seconds)
    report.error_code = code
    return report


def _new_run(request, timeout_seconds):
    return JudgeRun[request.response_model](
        status="error",
        prompt_version=request.prompt_version,
        timeout_seconds=timeout_seconds,
        request_sha256=hashlib.sha256(
            json.dumps(
                {
                    "messages": request.messages,
                    "schema": request.response_model.model_json_schema(),
                    "schema_name": request.schema_name,
                    "prompt_version": request.prompt_version,
                    "reasoning_effort": request.reasoning_effort,
                },
                sort_keys=True,
                allow_nan=False,
            ).encode()
        ).hexdigest(),
    )


def validation_findings(error: ValidationError) -> list[JudgeValidationFinding]:
    # Keep field locations and validation reasons, excluding response values,
    # exception context and URLs. Provider credentials never enter this schema.
    return [
        JudgeValidationFinding(
            location=list(item["loc"]), code=item["type"], message=item["msg"]
        )
        for item in error.errors(
            include_input=False, include_context=False, include_url=False
        )
    ]


def _execute_judge(measured, request):
    # Ownership stays in the worker, including after the caller's deadline.
    try:
        return measured.judge(request)
    finally:
        close_provider(measured.delegate)
