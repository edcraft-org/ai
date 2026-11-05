"""Token-authenticated HTTP channel between the worker and the backend."""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable, Iterable
from typing import Any

import httpx

from edcraft_validator.application.authoring_contracts import AuthoringProgress

logger = logging.getLogger(__name__)

# Keep the worker independent of the backend's schema names. The wire format is
# intentionally small: a progress event, the final report, and a fatal error.
RETRY_DELAYS = (1.0, 2.0, 4.0)
DEFAULT_REQUEST_TIMEOUT_SECONDS = 30.0
DEFAULT_PROGRESS_TIMEOUT_SECONDS = 5.0

_AUTH_HEADER = re.compile(
    r"(?i)\b(authorization)\b\s*[:=]\s*(?:(?:bearer|basic)\s+)?\S+"
)
_KEY_VALUE = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|worker[_-]?token|token|password|secret)"
    r"\b\s*[:=]\s*[\"']?([^\s\"',;}]+)"
)
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_OPENAI_KEY = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")
_WORKER_PATH_TOKEN = re.compile(r"(/ai-authoring/worker/)[^/\s?#]+")


def redact_secrets(text: str, secrets: Iterable[str] = ()) -> str:
    """Remove credentials from arbitrary log or error text."""
    redacted = str(text)
    known = sorted({secret for secret in secrets if secret}, key=len, reverse=True)
    for secret in known:
        redacted = redacted.replace(secret, "***")
    redacted = _AUTH_HEADER.sub(r"\1: ***", redacted)
    redacted = _KEY_VALUE.sub(r"\1: ***", redacted)
    redacted = _BEARER.sub("Bearer ***", redacted)
    redacted = _OPENAI_KEY.sub("***", redacted)
    return _WORKER_PATH_TOKEN.sub(r"\1***", redacted)


def sanitize_error_message(
    exc: BaseException, secrets: Iterable[str] = (), *, limit: int = 500
) -> str:
    """Return a short, redacted error message safe to send to the backend."""
    detail = redact_secrets(str(exc), secrets).strip()
    message = f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__
    return message[:limit]


class SecretRedactionFilter(logging.Filter):
    """Defence in depth for records emitted by this process."""

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        super().__init__()
        self._secrets: set[str] = set()
        self.add_secrets(secrets)

    @property
    def secrets(self) -> tuple[str, ...]:
        return tuple(self._secrets)

    def add_secrets(self, secrets: Iterable[str]) -> None:
        self._secrets.update(secret for secret in secrets if secret)

    def filter(self, record: logging.LogRecord) -> bool:
        message = redact_secrets(record.getMessage(), self._secrets)
        record.msg = message
        record.args = ()
        return True


class WorkerClient:
    """Small retrying client for the backend's worker endpoints."""

    def __init__(
        self,
        *,
        context_url: str,
        progress_url: str,
        callback_url: str,
        error_url: str,
        secrets: Iterable[str] = (),
        retry_delays: tuple[float, ...] = RETRY_DELAYS,
        sleep: Callable[[float], None] = time.sleep,
        transport: httpx.BaseTransport | None = None,
        request_timeout: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
        progress_timeout: float = DEFAULT_PROGRESS_TIMEOUT_SECONDS,
    ) -> None:
        self.context_url = context_url
        self.progress_url = progress_url
        self.callback_url = callback_url
        self.error_url = error_url
        self._secrets = tuple(secret for secret in secrets if secret)
        self._retry_delays = retry_delays
        self._sleep = sleep
        self._request_timeout = request_timeout
        self._progress_timeout = progress_timeout
        self._client = httpx.Client(transport=transport)

    @property
    def secrets(self) -> tuple[str, ...]:
        return self._secrets

    def add_secrets(self, secrets: Iterable[str]) -> None:
        self._secrets = self._secrets + tuple(
            secret for secret in secrets if secret and secret not in self._secrets
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> WorkerClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def fetch_context(self) -> dict[str, Any]:
        """Fetch the job command and decrypted role plan once."""
        response = self._client.get(
            self.context_url,
            headers={"Cache-Control": "no-store"},
            timeout=self._request_timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Authoring context must be a JSON object")
        return payload

    def post_progress(
        self, progress: AuthoringProgress, *, job_id: str | None = None
    ) -> bool:
        """Deliver progress best-effort; a failure never aborts the run."""
        started = time.perf_counter()
        try:
            response = self._client.post(
                self.progress_url,
                json=progress.model_dump(mode="json"),
                timeout=self._progress_timeout,
            )
            response.raise_for_status()
        except Exception:
            logger.warning(
                "job_id=%s phase=progress attempt=%s status=failed duration_ms=%.1f",
                job_id or "-",
                progress.attempt,
                (time.perf_counter() - started) * 1000,
            )
            return False
        logger.info(
            "job_id=%s phase=%s attempt=%s status=delivered duration_ms=%.1f",
            job_id or "-",
            progress.phase,
            progress.attempt,
            (time.perf_counter() - started) * 1000,
        )
        return True

    def deliver_result(self, payload: dict[str, Any], *, job_id: str) -> bool:
        """POST the final report, retrying the configured number of times."""
        delays = self._retry_delays
        total_attempts = len(delays) + 1
        for attempt in range(1, total_attempts + 1):
            started = time.perf_counter()
            try:
                response = self._client.post(
                    self.callback_url,
                    json=payload,
                    timeout=self._request_timeout,
                )
                response.raise_for_status()
            except Exception:
                logger.warning(
                    "job_id=%s phase=result attempt=%s status=failed duration_ms=%.1f",
                    job_id,
                    attempt,
                    (time.perf_counter() - started) * 1000,
                )
            else:
                logger.info(
                    "job_id=%s phase=result attempt=%s status=delivered "
                    "duration_ms=%.1f",
                    job_id,
                    attempt,
                    (time.perf_counter() - started) * 1000,
                )
                return True
            if attempt < total_attempts:
                self._sleep(delays[attempt - 1])
        return False

    def post_error(self, code: str, message: str, *, job_id: str) -> bool:
        """Report one worker-side fatal error, best-effort."""
        started = time.perf_counter()
        try:
            response = self._client.post(
                self.error_url,
                json={"code": code, "message": redact_secrets(message, self._secrets)},
                timeout=self._request_timeout,
            )
            response.raise_for_status()
        except Exception:
            logger.error(
                "job_id=%s phase=error status=failed duration_ms=%.1f",
                job_id,
                (time.perf_counter() - started) * 1000,
            )
            return False
        logger.info(
            "job_id=%s phase=error status=delivered duration_ms=%.1f",
            job_id,
            (time.perf_counter() - started) * 1000,
        )
        return True
