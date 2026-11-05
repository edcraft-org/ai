"""Worker entrypoint tests with a local backend stub and no model calls."""

from __future__ import annotations

import base64
import io
import json
import logging
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from edcraft_validator.application.authoring_api import AuthoringJobCommand
from edcraft_validator.application.authoring_contracts import (
    AuthoringProgress,
    AuthoringResult,
)
from edcraft_validator.worker.client import (
    SecretRedactionFilter,
    redact_secrets,
    sanitize_error_message,
)
from edcraft_validator.worker.main import (
    load_environment,
    main,
    prepare_job,
)
from edcraft_validator.worker.providers import ProviderPlan, build_provider

REVISION = "0392a726dac501e4f5ec4f2f3ea741d9785a3375"
TOKEN = "worker-token-secret"
PREFIX = f"/ai-authoring/worker/{TOKEN}"


def command_payload(job_id: UUID) -> dict:
    return {
        "job_id": str(job_id),
        "domain": "code",
        "author": {"provider": "soclaas", "model": "author-model"},
        "request": {"prompt": "Create an addition question", "difficulty": "easy"},
    }


def context_payload(job_id: UUID, *, revision: str = REVISION) -> dict:
    return {
        "job_id": str(job_id),
        "library_revision": revision,
        "timeout_seconds": 1800,
        "command": command_payload(job_id),
        "plan": {
            "author": {
                "provider": "soclaas",
                "model": "author-model",
                "api_key": "sk-author-secret",
                "base_url": "https://soclaas.example/v1",
                "timeout_seconds": 600,
            },
            "difficulty": {
                "provider": "soclaas",
                "model": "difficulty-model",
                "api_key": "sk-difficulty-secret",
                "base_url": "https://soclaas.example/v1",
                "timeout_seconds": 60,
            },
            "relevance": {
                "provider": "openai",
                "model": "relevance-model",
                "api_key": "sk-relevance-secret",
                "base_url": "https://openai.example/v1",
                "timeout_seconds": 30,
            },
        },
    }


def encode_params(command: dict) -> str:
    raw = json.dumps(command, separators=(",", ":")).encode()
    return base64.b64encode(raw).decode()


def environment(
    stub: StubBackend,
    job_id: UUID,
    *,
    revision: str = REVISION,
    with_params: bool = True,
) -> dict[str, str]:
    values = {
        "EDCRAFT_CONTEXT_URL": stub.url(f"{PREFIX}/context"),
        "EDCRAFT_PROGRESS_URL": stub.url(f"{PREFIX}/progress"),
        "EDCRAFT_CALLBACK_URL": stub.url(f"{PREFIX}/result"),
        "EDCRAFT_ERROR_URL": stub.url(f"{PREFIX}/error"),
        "EDCRAFT_LIBRARY_REVISION": revision,
        "EDCRAFT_JOB_ID": str(job_id),
    }
    if with_params:
        values["EDCRAFT_PARAMS_B64"] = encode_params(command_payload(job_id))
    return values


def make_report(status: str = "checked") -> AuthoringResult:
    return AuthoringResult(
        status=status,
        provider="soclaas",
        model="author-model",
        domain="code",
        request={"prompt": "Create an addition question"},
        prompt_version="test-prompt-v1",
        fixed_plan=[],
        tool_catalogue=[],
    )


class FakeRunner:
    def __init__(self, report: AuthoringResult | None = None) -> None:
        self.report = report or make_report()
        self.calls: list[AuthoringJobCommand] = []

    def __call__(
        self,
        command: AuthoringJobCommand,
        *,
        application_factory,
        provider_factory,
        on_progress,
    ):
        self.calls.append(command)
        on_progress(AuthoringProgress(phase="generating", attempt=1))
        on_progress(AuthoringProgress(phase="checking", attempt=1))
        return SimpleNamespace(report=self.report)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        self._record(None)
        stub = self.server.stub
        if self.path == f"{PREFIX}/context" and stub.context_status == 200:
            self._json(200, stub.context)
        else:
            status = stub.context_status if self.path == f"{PREFIX}/context" else 404
            self._empty(status)

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        body = json.loads(raw) if raw else None
        self._record(body)
        stub = self.server.stub
        if self.path == f"{PREFIX}/progress":
            status = stub.progress_status
        elif self.path == f"{PREFIX}/result":
            status = (
                stub.result_statuses.pop(0)
                if len(stub.result_statuses) > 1
                else stub.result_statuses[0]
            )
        elif self.path == f"{PREFIX}/error":
            status = stub.error_status
        else:
            status = 404
        self._empty(status)

    def _record(self, body) -> None:
        self.server.stub.requests.append(
            {
                "method": self.command,
                "path": self.path,
                "headers": dict(self.headers.items()),
                "body": body,
            }
        )

    def _json(self, status: int, payload) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _empty(self, status: int) -> None:
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args) -> None:
        return


class StubBackend:
    def __init__(self, context: dict) -> None:
        self.context = context
        self.requests: list[dict] = []
        self.context_status = 200
        self.progress_status = 204
        self.result_statuses = [204]
        self.error_status = 204
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.httpd.stub = self
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def base(self) -> str:
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}"

    def url(self, path: str) -> str:
        return self.base + path

    def __enter__(self) -> StubBackend:
        self.thread.start()
        return self

    def __exit__(self, *args) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)

    def calls(self, method: str, suffix: str) -> list[dict]:
        path = f"{PREFIX}{suffix}"
        return [
            request
            for request in self.requests
            if request["method"] == method and request["path"] == path
        ]


def run_worker(
    stub: StubBackend,
    job_id: UUID,
    *,
    runner: FakeRunner,
    environ: dict[str, str] | None = None,
    sleep=lambda _: None,
) -> int:
    return main(
        environ=environ or environment(stub, job_id),
        runner=runner,
        tool_client_factory=lambda **_: object(),
        provider_factory=lambda _plan: object(),
        sleep=sleep,
    )


def test_context_progress_and_result_bodies() -> None:
    job_id = uuid4()
    with StubBackend(context_payload(job_id)) as stub:
        runner = FakeRunner()
        assert run_worker(stub, job_id, runner=runner) == 0

        context = stub.calls("GET", "/context")
        assert len(context) == 1
        assert context[0]["headers"].get("Cache-Control") == "no-store"

        progress = [call["body"] for call in stub.calls("POST", "/progress")]
        assert progress == [
            {"phase": "generating", "attempt": 1},
            {"phase": "checking", "attempt": 1},
        ]

        results = stub.calls("POST", "/result")
        assert len(results) == 1
        assert results[0]["body"]["library_revision"] == REVISION
        assert results[0]["body"]["report"]["status"] == "checked"
        assert results[0]["body"]["report"]["provider"] == "soclaas"
        assert results[0]["body"]["report"]["domain"] == "code"
        assert not stub.calls("POST", "/error")
        assert len(runner.calls) == 1
        assert runner.calls[0].job_id == job_id


def test_prepare_job_reconstructs_command_and_role_plan() -> None:
    job_id = uuid4()
    payload = context_payload(job_id)
    params = AuthoringJobCommand.model_validate(payload["command"])

    prepared = prepare_job(
        payload,
        params=params,
        library_revision=REVISION,
        job_id=str(job_id),
    )

    assert prepared.command == params
    assert prepared.plan.author.provider == "soclaas"
    assert prepared.plan.author.model == "author-model"
    assert prepared.plan.author.base_url == "https://soclaas.example/v1"
    assert prepared.plan.author.timeout_seconds == 600
    assert prepared.plan.difficulty.provider == "soclaas"
    assert prepared.plan.relevance.provider == "openai"
    assert prepared.plan.relevance.effective_timeout_seconds == 30
    assert "sk-author-secret" not in repr(prepared.plan.author)


def test_environment_decodes_required_base64_params() -> None:
    job_id = uuid4()
    with StubBackend(context_payload(job_id)) as stub:
        settings = load_environment(environment(stub, job_id))
    assert settings.job_id == str(job_id)
    assert settings.params is not None
    assert settings.params.job_id == job_id
    assert settings.params.author.model == "author-model"


class FakeOpenAIClient:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.timeout = kwargs["timeout"]
        self.max_retries = kwargs["max_retries"]
        self.closed = False

    def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize("provider", ["soclaas", "openai"])
def test_build_provider_uses_context_credentials(provider: str) -> None:
    plan = ProviderPlan(
        provider=provider,
        model="selected-model",
        api_key="sk-selected-secret",
        base_url="https://model.example/v1",
        timeout_seconds=42,
    )
    clients: list[FakeOpenAIClient] = []

    def client_factory(**kwargs) -> FakeOpenAIClient:
        client = FakeOpenAIClient(**kwargs)
        clients.append(client)
        return client

    built = build_provider(plan, client_factory=client_factory)
    assert clients[0].kwargs == {
        "api_key": "sk-selected-secret",
        "base_url": "https://model.example/v1",
        "timeout": 42,
        "max_retries": 1,
    }
    assert built.provider == provider
    assert built.model == "selected-model"
    built.close()
    assert clients[0].closed


@pytest.mark.parametrize("variant", ["missing_env", "wrong_context", "missing_context"])
def test_bad_revision_fails_before_running(variant: str) -> None:
    job_id = uuid4()
    payload = context_payload(job_id)
    if variant == "missing_context":
        del payload["library_revision"]
    with StubBackend(payload) as stub:
        env = environment(stub, job_id)
        if variant == "missing_env":
            env["EDCRAFT_LIBRARY_REVISION"] = ""
        elif variant == "wrong_context":
            payload["library_revision"] = "0" * 40
            stub.context = payload
        runner = FakeRunner()

        assert run_worker(stub, job_id, runner=runner, environ=env) == 1

        assert runner.calls == []
        assert not stub.calls("POST", "/result")
        if variant == "missing_env":
            assert not stub.requests
        else:
            errors = stub.calls("POST", "/error")
            assert len(errors) == 1
            assert errors[0]["body"]["code"] == "AUTHORING_FAILED"


def test_progress_failure_does_not_abort_the_run() -> None:
    job_id = uuid4()
    with StubBackend(context_payload(job_id)) as stub:
        stub.progress_status = 500
        runner = FakeRunner()

        assert run_worker(stub, job_id, runner=runner) == 0

        assert len(stub.calls("POST", "/progress")) == 2
        assert len(stub.calls("POST", "/result")) == 1
        assert not stub.calls("POST", "/error")


def test_result_retry_succeeds_after_transient_failure() -> None:
    job_id = uuid4()
    with StubBackend(context_payload(job_id)) as stub:
        stub.result_statuses = [500, 204]
        delays: list[float] = []
        runner = FakeRunner()

        assert run_worker(stub, job_id, runner=runner, sleep=delays.append) == 0

        assert len(stub.calls("POST", "/result")) == 2
        assert delays == [1.0]
        assert not stub.calls("POST", "/error")


def test_result_retry_exhaustion_reports_error_once() -> None:
    job_id = uuid4()
    with StubBackend(context_payload(job_id)) as stub:
        stub.result_statuses = [500, 500, 500, 500]
        delays: list[float] = []
        runner = FakeRunner()

        assert run_worker(stub, job_id, runner=runner, sleep=delays.append) == 1

        assert len(stub.calls("POST", "/result")) == 4
        assert delays == [1.0, 2.0, 4.0]
        errors = stub.calls("POST", "/error")
        assert len(errors) == 1
        assert errors[0]["body"]["code"] == "AUTHORING_FAILED"
        message = errors[0]["body"]["message"]
        assert TOKEN not in message
        assert "sk-author-secret" not in message


def test_worker_exits_nonzero_for_error_report() -> None:
    job_id = uuid4()
    with StubBackend(context_payload(job_id)) as stub:
        runner = FakeRunner(make_report("error"))

        assert run_worker(stub, job_id, runner=runner) == 1

        assert len(stub.calls("POST", "/result")) == 1
        assert not stub.calls("POST", "/error")


def test_redaction_hides_keys_headers_and_tokens() -> None:
    secret = "sk-live-abcdefghijklmnop"
    text = f"api_key={secret} Authorization: Bearer {secret} endpoint={PREFIX}/result"

    redacted = redact_secrets(text, [secret])

    assert secret not in redacted
    assert "Authorization: ***" in redacted
    assert f"/ai-authoring/worker/{TOKEN}/result" not in redacted
    assert "/ai-authoring/worker/***/result" in redacted


def test_log_filter_redacts_formatted_records() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    test_logger = logging.getLogger("edcraft-test-worker-redaction")
    test_logger.handlers = [handler]
    test_logger.propagate = False
    test_logger.setLevel(logging.INFO)
    handler.addFilter(SecretRedactionFilter(["top-secret-value"]))

    test_logger.info(
        "api_key=%s Authorization: Bearer %s", "top-secret-value", "raw-worker-token"
    )

    output = stream.getvalue()
    assert "top-secret-value" not in output
    assert "raw-worker-token" not in output
    assert "***" in output


def test_sanitize_error_message_removes_credentials() -> None:
    secret = "sk-error-secret-value"
    exc = RuntimeError(f"request failed api_key={secret} at {PREFIX}/context")

    message = sanitize_error_message(exc, [secret])

    assert "RuntimeError" in message
    assert secret not in message
    assert TOKEN not in message


def test_module_help_works_without_backend() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "edcraft_validator.worker", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "EDCRAFT_*" in result.stdout
