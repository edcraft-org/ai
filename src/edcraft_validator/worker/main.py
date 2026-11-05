"""Entrypoint for one flag-gated Nomad AI authoring allocation."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import logging
import os
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from edcraft_validator.application.authoring_api import (
    AuthoringJobCommand,
    AuthoringJobRecord,
    run_authoring_job_sync,
)
from edcraft_validator.application.authoring_contracts import (
    AuthoringProgress,
    AuthoringResult,
)
from edcraft_validator.application.template_workflow import TemplateApplication
from edcraft_validator.worker.client import (
    SecretRedactionFilter,
    WorkerClient,
    sanitize_error_message,
)
from edcraft_validator.worker.providers import (
    ProviderPlan,
    WorkerPlan,
    build_model_tool_client,
    build_provider,
)

logger = logging.getLogger(__name__)

REQUIRED_ENVIRONMENT = (
    "EDCRAFT_CONTEXT_URL",
    "EDCRAFT_PROGRESS_URL",
    "EDCRAFT_CALLBACK_URL",
    "EDCRAFT_ERROR_URL",
    "EDCRAFT_LIBRARY_REVISION",
    "EDCRAFT_JOB_ID",
)

ERROR_CODE = "AUTHORING_FAILED"


class WorkerConfigurationError(RuntimeError):
    """The allocation cannot start because its environment is incomplete."""


class WorkerContextError(RuntimeError):
    """The backend context cannot be turned into a job."""


@dataclass(frozen=True)
class WorkerEnvironment:
    context_url: str
    progress_url: str
    callback_url: str
    error_url: str
    library_revision: str
    job_id: str
    params: AuthoringJobCommand | None


@dataclass(frozen=True)
class PreparedJob:
    command: AuthoringJobCommand
    plan: WorkerPlan


class WorkerContext(BaseModel):
    """The subset of the context response the worker relies on."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    job_id: UUID | None = None
    library_revision: str = Field(min_length=1)
    timeout_seconds: float | None = Field(default=None, gt=0)
    command: dict[str, Any] | None = None
    plan: WorkerPlan


def _decode_params(raw: str | None) -> AuthoringJobCommand | None:
    if not raw or not raw.strip():
        return None
    encoded = raw.strip()
    padded = encoded + "=" * (-len(encoded) % 4)
    try:
        try:
            decoded = base64.b64decode(padded, validate=True)
        except binascii.Error:
            decoded = base64.urlsafe_b64decode(padded)
        payload = json.loads(decoded)
        return AuthoringJobCommand.model_validate(payload)
    except (ValueError, TypeError, binascii.Error) as exc:
        raise WorkerConfigurationError(
            "EDCRAFT_PARAMS_B64 is not a valid authoring command"
        ) from exc


def load_environment(environ: Mapping[str, str]) -> WorkerEnvironment:
    """Read and validate the allocation's environment before any network call."""
    values = {name: (environ.get(name) or "").strip() for name in REQUIRED_ENVIRONMENT}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise WorkerConfigurationError(
            "Missing required environment: " + ", ".join(missing)
        )
    try:
        UUID(values["EDCRAFT_JOB_ID"])
    except ValueError as exc:
        raise WorkerConfigurationError("EDCRAFT_JOB_ID must be a UUID") from exc
    return WorkerEnvironment(
        context_url=values["EDCRAFT_CONTEXT_URL"],
        progress_url=values["EDCRAFT_PROGRESS_URL"],
        callback_url=values["EDCRAFT_CALLBACK_URL"],
        error_url=values["EDCRAFT_ERROR_URL"],
        library_revision=values["EDCRAFT_LIBRARY_REVISION"],
        job_id=values["EDCRAFT_JOB_ID"],
        params=_decode_params(environ.get("EDCRAFT_PARAMS_B64")),
    )


def prepare_job(
    payload: Mapping[str, Any],
    *,
    params: AuthoringJobCommand | None,
    library_revision: str,
    job_id: str,
) -> PreparedJob:
    """Validate the revision and reconstruct the command plus role plan."""
    try:
        context = WorkerContext.model_validate(payload)
    except ValidationError as exc:
        raise WorkerContextError(
            "Context payload is not a valid worker context"
        ) from exc
    if context.library_revision != library_revision:
        raise WorkerContextError(
            "Worker library revision does not match the job context"
        )
    if context.job_id is not None and str(context.job_id) != job_id:
        raise WorkerContextError("Context job id does not match this worker")
    command_payload = context.command
    if command_payload is None:
        if params is None:
            raise WorkerContextError("Context does not include a job command")
        command_payload = params.model_dump(mode="json")
    try:
        command = AuthoringJobCommand.model_validate(command_payload)
    except ValidationError as exc:
        raise WorkerContextError(
            "Context command is not a valid authoring command"
        ) from exc
    if str(command.job_id) != job_id:
        raise WorkerContextError("Command job id does not match this worker")
    if params is not None and params != command:
        raise WorkerContextError("Encoded parameters do not match the job context")
    return PreparedJob(command=command, plan=context.plan)


def execute_job(
    command: AuthoringJobCommand,
    plan: WorkerPlan,
    *,
    on_progress: Callable[[AuthoringProgress], None] | None,
    runner: Callable[..., AuthoringJobRecord] = run_authoring_job_sync,
    tool_client_factory: Callable[..., Any] = build_model_tool_client,
    provider_factory: Callable[[ProviderPlan], Any] = build_provider,
) -> AuthoringJobRecord:
    """Run the pinned validator with job-scoped providers and tools."""
    tool_client = tool_client_factory(
        difficulty=plan.difficulty,
        relevance=plan.relevance,
    )

    def application_factory() -> TemplateApplication:
        return TemplateApplication(tool_client=tool_client)

    author_plan = plan.author

    def author_provider_factory(_selection: Any) -> Any:
        return provider_factory(author_plan)

    return runner(
        command,
        application_factory=application_factory,
        provider_factory=author_provider_factory,
        on_progress=on_progress,
    )


def _worker_token_from_url(url: str) -> str | None:
    parts = urlparse(url).path.split("/")
    if "worker" in parts:
        index = parts.index("worker")
        if index + 1 < len(parts) and parts[index + 1]:
            return parts[index + 1]
    return None


def _secrets_from_urls(settings: WorkerEnvironment) -> tuple[str, ...]:
    tokens = {
        _worker_token_from_url(url)
        for url in (
            settings.context_url,
            settings.progress_url,
            settings.callback_url,
            settings.error_url,
        )
    }
    return tuple(token for token in tokens if token)


def _context_secrets(payload: Mapping[str, Any]) -> tuple[str, ...]:
    plan = payload.get("plan")
    if not isinstance(plan, dict):
        return ()
    secrets: list[str] = []
    for role in plan.values():
        if not isinstance(role, dict):
            continue
        api_key = role.get("api_key")
        if isinstance(api_key, str) and api_key:
            secrets.append(api_key)
    return tuple(secrets)


def _install_redaction(redaction: SecretRedactionFilter) -> None:
    logger.addFilter(redaction)
    for handler in logging.getLogger().handlers:
        handler.addFilter(redaction)


def _configure_logging(level_name: str | None) -> None:
    level = getattr(logging, (level_name or "INFO").upper(), logging.INFO)
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
    logging.getLogger().setLevel(level)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def _report_fatal(
    client: WorkerClient,
    redaction: SecretRedactionFilter,
    *,
    job_id: str,
    phase: str,
    message: str,
    exc: BaseException | None = None,
) -> None:
    detail = (
        sanitize_error_message(exc, redaction.secrets) if exc is not None else message
    )
    logger.error(
        "job_id=%s phase=%s status=failed error=%s",
        job_id,
        phase,
        detail,
    )
    client.post_error(ERROR_CODE, detail, job_id=job_id)


def _argument_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        prog="python -m edcraft_validator.worker",
        description=(
            "Run one AI authoring job supplied by the backend over authenticated "
            "HTTP. Configuration comes from EDCRAFT_* environment variables."
        ),
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    runner: Callable[..., AuthoringJobRecord] | None = None,
    tool_client_factory: Callable[..., Any] | None = None,
    provider_factory: Callable[[ProviderPlan], Any] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Run one allocation and return a process exit code."""
    _argument_parser().parse_args([] if argv is None else list(argv))
    env = os.environ if environ is None else environ
    _configure_logging(env.get("EDCRAFT_LOG_LEVEL"))
    try:
        settings = load_environment(env)
    except WorkerConfigurationError as exc:
        logger.error(
            "job_id=- phase=startup status=failed error=%s",
            sanitize_error_message(exc),
        )
        return 1

    redaction = SecretRedactionFilter(_secrets_from_urls(settings))
    _install_redaction(redaction)
    logger.info("job_id=%s phase=startup status=started", settings.job_id)
    client = WorkerClient(
        context_url=settings.context_url,
        progress_url=settings.progress_url,
        callback_url=settings.callback_url,
        error_url=settings.error_url,
        secrets=redaction.secrets,
        sleep=sleep,
    )
    try:
        started = time.perf_counter()
        try:
            payload = client.fetch_context()
        except Exception as exc:
            _report_fatal(
                client,
                redaction,
                job_id=settings.job_id,
                phase="context",
                message="Could not fetch the authoring context",
                exc=exc,
            )
            return 1
        redaction.add_secrets(_context_secrets(payload))
        client.add_secrets(_context_secrets(payload))
        logger.info(
            "job_id=%s phase=context status=fetched duration_ms=%.1f",
            settings.job_id,
            (time.perf_counter() - started) * 1000,
        )

        try:
            prepared = prepare_job(
                payload,
                params=settings.params,
                library_revision=settings.library_revision,
                job_id=settings.job_id,
            )
        except WorkerContextError as exc:
            _report_fatal(
                client,
                redaction,
                job_id=settings.job_id,
                phase="validate",
                message=str(exc),
            )
            return 1

        def on_progress(progress: AuthoringProgress) -> None:
            client.post_progress(progress, job_id=settings.job_id)

        run_started = time.perf_counter()
        try:
            record = execute_job(
                prepared.command,
                prepared.plan,
                on_progress=on_progress,
                runner=runner or run_authoring_job_sync,
                tool_client_factory=tool_client_factory or build_model_tool_client,
                provider_factory=provider_factory or build_provider,
            )
        except Exception as exc:
            _report_fatal(
                client,
                redaction,
                job_id=settings.job_id,
                phase="run",
                message="Authoring job failed before producing a report",
                exc=exc,
            )
            return 1
        report: AuthoringResult = record.report
        logger.info(
            "job_id=%s phase=run status=%s duration_ms=%.1f",
            settings.job_id,
            report.status,
            (time.perf_counter() - run_started) * 1000,
        )

        delivered = client.deliver_result(
            {
                "library_revision": settings.library_revision,
                "report": report.model_dump(mode="json"),
            },
            job_id=settings.job_id,
        )
        if not delivered:
            _report_fatal(
                client,
                redaction,
                job_id=settings.job_id,
                phase="result",
                message="Could not deliver the authoring report",
            )
            return 1
        return 0 if report.status in {"checked", "needs_review"} else 1
    finally:
        client.close()
