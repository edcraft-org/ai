"""Shared JSON-only process boundary for trusted worker modules.

The math validation and check-pilot workers own their operations and public
exception types. This module owns only the transport they share: a sanitized
environment, bounded JSON framing, a hard parent wall-clock timeout, resource
limits applied by a tiny trusted bootstrap, and safe failure mapping.

Memory enforcement is layered. The bootstrap reports the child's peak resident
set size in its response envelope, so an intentionally or accidentally oversized
worker is rejected even when it finishes quickly and exits zero. A parent-side
RSS watchdog remains a secondary guard for long-running workers.
"""

from __future__ import annotations

import json
import math
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any

try:  # pragma: no cover - the resource module is unavailable on Windows
    import resource
except ImportError:  # pragma: no cover
    resource = None  # type: ignore[assignment]

BOOTSTRAP_MODULE = "edcraft_validator.tools.isolated_worker_bootstrap"
DEFAULT_MEMORY_LIMIT_BYTES = 1024 * 1024 * 1024
MAX_PAYLOAD_BYTES = 8 * 1024 * 1024
MAX_STDERR_CHARS = 500
MAX_ERROR_MESSAGE_CHARS = 1000
DEFAULT_RSS_POLL_INTERVAL_SECONDS = 0.1
PID_FILE_WAIT_SECONDS = 5.0
WORKER_ENVELOPE = "edcraft-worker-envelope/1"
_RSS_AVAILABLE = os.name == "posix"


class CodedWorkerError(RuntimeError):
    """Worker failure that may carry an explicit boundary error code.

    Subclassing opts an error type into receiving the worker's ``code`` field,
    so transport failures and untyped callers are unaffected.
    """

    code: str | None = None


class MemoryLimitUnavailable(RuntimeError):
    """The parent could not establish any memory ceiling for the child.

    Raised instead of running a worker whose peak memory can be neither watched
    nor limited by the kernel. It is deliberately distinct from the ordinary
    "limit exceeded" error so callers can tell a policy gap from a violation.
    """

    code = "memory_limit_unavailable"


def normalise_maxrss(value: int, platform: str | None = None) -> int:
    """Convert ``getrusage``'s ``ru_maxrss`` to bytes.

    Darwin reports bytes; Linux (and most other POSIX systems) report
    kibibytes.
    """
    if type(value) is not int or value < 0:
        raise ValueError("ru_maxrss must be a non-negative integer")
    selected = sys.platform if platform is None else platform
    if selected.startswith("darwin"):
        return value
    return value * 1024


_MODULE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
_RUNTIME_ENVIRONMENT_NAMES = frozenset(
    {
        "LANG",
        "LANGUAGE",
        "PATH",
        "PYTHONIOENCODING",
        "PYTHONPATH",
        "TEMP",
        "TMP",
        "TMPDIR",
    }
)
_ENVIRONMENT_PREFIXES = ("LC_",)
_WINDOWS_ENVIRONMENT_NAMES = frozenset({"COMSPEC", "PATHEXT", "SYSTEMROOT", "WINDIR"})


def worker_environment(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return only interpreter/runtime inputs, never ambient credentials."""
    source = os.environ if environ is None else environ
    names = set(_RUNTIME_ENVIRONMENT_NAMES)
    if os.name == "nt":
        names.update(_WINDOWS_ENVIRONMENT_NAMES)
    environment = {name: source[name] for name in names if name in source}
    for name, value in source.items():
        if name.startswith(_ENVIRONMENT_PREFIXES):
            environment[name] = value
    environment["PYTHONUNBUFFERED"] = "1"
    environment["PYTHONNOUSERSITE"] = "1"
    environment.setdefault("PYTHONIOENCODING", "utf-8")
    return environment


def validate_worker_module(module: str) -> str:
    """Reject non-module strings; callers still supply trusted constants."""
    if not isinstance(module, str) or _MODULE_NAME.fullmatch(module) is None:
        raise ValueError("isolated worker module name is invalid")
    return module


def cpu_limit_for_timeout(timeout_seconds: float) -> int:
    """Allow a small startup margin inside the parent wall-clock deadline."""
    return max(1, math.ceil(timeout_seconds) + 1)


def _inherited_limit(kind: int, requested: int) -> int:
    assert resource is not None
    soft, hard = resource.getrlimit(kind)
    infinity = getattr(resource, "RLIM_INFINITY", -1)
    candidates = [requested]
    if soft != infinity:
        candidates.append(int(soft))
    if hard != infinity:
        candidates.append(int(hard))
    return min(candidates)


def apply_resource_limits(
    *,
    cpu_seconds: int,
    memory_bytes: int = DEFAULT_MEMORY_LIMIT_BYTES,
) -> dict[str, int]:
    """Apply hard limits without ever raising a tighter inherited cap."""
    if type(cpu_seconds) is not int or cpu_seconds <= 0:
        raise ValueError("worker CPU limit must be a positive integer")
    if type(memory_bytes) is not int or memory_bytes <= 0:
        raise ValueError("worker memory limit must be a positive integer")
    applied: dict[str, int] = {}
    if resource is None:
        return applied
    if sys.platform.startswith("linux") and hasattr(resource, "RLIMIT_AS"):
        memory = _inherited_limit(resource.RLIMIT_AS, memory_bytes)
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
        applied["memory_bytes"] = memory
    if hasattr(resource, "RLIMIT_CPU"):
        cpu = _inherited_limit(resource.RLIMIT_CPU, cpu_seconds)
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
        applied["cpu_seconds"] = cpu
    return applied


def apply_best_effort_data_limit(memory_bytes: int) -> int | None:
    """Best-effort ``RLIMIT_DATA`` on macOS.

    ``RLIMIT_AS`` is not enforced on darwin, so the self-reported peak RSS and
    the parent-side RSS watchdog are the primary memory ceiling.
    ``RLIMIT_DATA`` is a cheap secondary guard where the platform honours it.

    The hard limit is read first: the soft limit is lowered to the desired cap
    but never below an inherited tighter soft limit, and the hard limit is
    preserved exactly. Raising the hard limit is never attempted; it would both
    be a privilege violation and weaken the inherited sandbox.
    """
    if type(memory_bytes) is not int or memory_bytes <= 0:
        raise ValueError("worker memory limit must be a positive integer")
    if resource is None or not sys.platform.startswith("darwin"):
        return None
    if not hasattr(resource, "RLIMIT_DATA"):
        return None
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_DATA)
        infinity = getattr(resource, "RLIM_INFINITY", -1)
        if hard == infinity:
            current = memory_bytes
        else:
            current = min(memory_bytes, int(hard))
        if soft != infinity:
            current = min(current, int(soft))
        if current <= 0:
            return None
        resource.setrlimit(resource.RLIMIT_DATA, (current, hard))
    except (OSError, ValueError):  # pragma: no cover - platform dependent
        return None
    return current


def rss_bytes_for_pid(pid: int) -> int | None:
    """Read a process's resident set size in bytes using POSIX ``ps``.

    Returns ``None`` when the process is gone or ``ps`` is unavailable; a
    missing reading is never treated as exceeding the cap.
    """
    if not _RSS_AVAILABLE or type(pid) is not int or pid <= 0:
        return None
    try:
        completed = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
            env=worker_environment(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return rss_bytes_from_ps(completed.stdout)


def rss_bytes_from_ps(output: str) -> int | None:
    """Parse ``ps -o rss=`` output, which is reported in kibibytes."""
    fields = output.split()
    if not fields:
        return None
    try:
        kibibytes = int(fields[0])
    except ValueError:
        return None
    if kibibytes < 0:
        return None
    return kibibytes * 1024


def pid_start_time(pid: int) -> str | None:
    """Return a process start timestamp, used to detect pid reuse.

    ``ps -o lstart=`` is available on both macOS and Linux. ``None`` means the
    process is gone or cannot be inspected; callers must not treat it as an
    identity match on its own.
    """
    if not _RSS_AVAILABLE or type(pid) is not int or pid <= 0:
        return None
    try:
        completed = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
            env=worker_environment(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    started = completed.stdout.strip()
    return started or None


class RssWatchdog:
    """Parent-side resident-memory watchdog for one child process."""

    def __init__(
        self,
        pid: int,
        memory_bytes: int,
        *,
        kill: Callable[[], None],
        on_exceeded: Callable[[], None] | None = None,
        interval: float = DEFAULT_RSS_POLL_INTERVAL_SECONDS,
        read_rss: Callable[[int], int | None] = rss_bytes_for_pid,
        verify: Callable[[], bool] | None = None,
    ) -> None:
        if type(memory_bytes) is not int or memory_bytes <= 0:
            raise ValueError("watchdog memory limit must be a positive integer")
        if interval <= 0:
            raise ValueError("watchdog poll interval must be positive")
        self.pid = pid
        self.memory_bytes = memory_bytes
        self.exceeded = False
        self._kill = kill
        self._on_exceeded = on_exceeded
        self._interval = interval
        self._read_rss = read_rss
        self._verify = verify

    def _same_process(self) -> bool:
        """Reject a recycled pid before sending any signal.

        A verifier that cannot prove identity (for example ``ps`` is missing)
        returns ``False``: leaving a process alive until the child self-reports
        its peak RSS is safer than killing an unrelated process.
        """
        if self._verify is None:
            return True
        try:
            return bool(self._verify())
        except Exception:  # pragma: no cover - defensive around external probes
            return False

    def poll_once(self, stop: threading.Event | None = None) -> bool:
        """Check one reading; kill the child once the cap is exceeded."""
        if self.exceeded:
            return True
        if stop is not None and stop.is_set():
            return False
        rss = self._read_rss(self.pid)
        if rss is None or rss <= self.memory_bytes:
            return False
        # Recheck the stop flag and the pid's identity immediately before the
        # kill: the child may have exited (and its pid been reused) while the
        # RSS probe ran.
        if stop is not None and stop.is_set():
            return False
        if not self._same_process():
            return False
        if stop is not None and stop.is_set():
            return False
        self.exceeded = True
        if self._on_exceeded is not None:
            self._on_exceeded()
        self._kill()
        return True

    def watch(self, stop: threading.Event) -> None:
        """Poll until the child exceeds the cap or ``stop`` is set."""
        while not stop.wait(self._interval):
            if self.poll_once(stop):
                return


def _read_pid_file(path: str) -> int | None:
    try:
        with open(path, encoding="ascii") as handle:
            text = handle.read().strip()
    except OSError:
        return None
    if not text.isdigit():
        return None
    pid = int(text)
    return pid if pid > 0 else None


def _wait_for_pid(path: str, stop: threading.Event) -> int | None:
    """Wait for the child's pid handshake until the watchdog is stopped.

    There is deliberately no deadline: giving up early would silently disable
    the watchdog for a slow-starting worker. The caller stops the watchdog once
    the child exits or the wall-clock timeout fires.
    """
    while not stop.is_set():
        pid = _read_pid_file(path)
        if pid is not None:
            return pid
        stop.wait(0.01)
    return None


def _kill_pid(pid: int, *, verify: Callable[[], bool] | None = None) -> bool:
    """Kill ``pid`` only when ``verify`` still identifies it as our child."""
    if verify is not None and not verify():
        return False
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:  # pragma: no cover - process race
        return False
    return True


def _watch_worker_memory(
    pid_path: str,
    memory_bytes: int,
    stop: threading.Event,
    exceeded: threading.Event,
) -> None:
    """Thread body: resolve the worker pid, then apply the RSS watchdog."""
    pid = _wait_for_pid(pid_path, stop)
    if pid is None or stop.is_set():
        return
    started = pid_start_time(pid)

    def verify() -> bool:
        # The pid file is removed only after the stop flag is set, so a file
        # that no longer names this pid means the handshake was torn down.
        if _read_pid_file(pid_path) != pid:
            return False
        if started is None:
            # ``ps`` is unavailable; the pid-file content is the remaining
            # identity evidence.
            return True
        current = pid_start_time(pid)
        return current is not None and current == started

    def kill() -> None:
        _kill_pid(pid, verify=verify)

    RssWatchdog(
        pid,
        memory_bytes,
        kill=kill,
        on_exceeded=exceeded.set,
        verify=verify,
    ).watch(stop)


@dataclass
class _MemoryWatchdog:
    """Handle for one watchdog thread and its handshake state."""

    pid_path: str
    stop: threading.Event
    exceeded: threading.Event
    thread: threading.Thread | None = None

    def __iter__(self) -> Iterator[str | threading.Event]:
        # Backwards-compatible three-value unpacking.
        yield self.pid_path
        yield self.stop
        yield self.exceeded


def _start_memory_watchdog(memory_bytes: int) -> _MemoryWatchdog:
    """Create the pid handshake file and start the RSS watchdog thread."""
    stop = threading.Event()
    exceeded = threading.Event()
    handle, pid_path = tempfile.mkstemp(prefix="edcraft-worker-", suffix=".pid")
    os.close(handle)
    os.unlink(pid_path)
    watch = _MemoryWatchdog(pid_path, stop, exceeded)
    if _RSS_AVAILABLE:
        thread = threading.Thread(
            target=_watch_worker_memory,
            args=(pid_path, memory_bytes, stop, exceeded),
            name="worker-rss-watchdog",
            daemon=True,
        )
        thread.start()
        watch.thread = thread
    return watch


def _stop_memory_watchdog(
    pid_path: str,
    stop: threading.Event,
    thread: threading.Thread | None = None,
) -> None:
    """Stop and join the watchdog before removing its handshake file."""
    stop.set()
    if thread is not None:
        thread.join(timeout=PID_FILE_WAIT_SECONDS)
    try:
        os.unlink(pid_path)
    except OSError:
        pass


def _watchdog_parts(
    watch: Any,
) -> tuple[str, threading.Event, threading.Event, threading.Thread | None]:
    """Normalise a watchdog handle, tolerating test doubles."""
    if isinstance(watch, _MemoryWatchdog):
        return watch.pid_path, watch.stop, watch.exceeded, watch.thread
    pid_path, stop, exceeded = watch
    return pid_path, stop, exceeded, None


def run_json_worker(
    payload: dict[str, Any],
    *,
    module: str,
    timeout_seconds: float,
    timeout_error: type[TimeoutError],
    worker_error: type[RuntimeError],
    description: str,
    worker_description: str | None = None,
    cpu_seconds: int | None = None,
    memory_bytes: int = DEFAULT_MEMORY_LIMIT_BYTES,
    memory_error: type[RuntimeError] | None = None,
) -> dict[str, Any]:
    """Run one closed JSON request in a fresh interpreter with hard limits."""
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError(f"{description} timeout must be finite and positive")
    selected_module = validate_worker_module(module)
    selected_cpu = (
        cpu_limit_for_timeout(timeout_seconds) if cpu_seconds is None else cpu_seconds
    )
    if type(selected_cpu) is not int or selected_cpu <= 0:
        raise ValueError("worker CPU limit must be a positive integer")
    if type(memory_bytes) is not int or memory_bytes <= 0:
        raise ValueError("worker memory limit must be a positive integer")

    serialized = json.dumps(payload, allow_nan=False, separators=(",", ":"))
    if len(serialized.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise ValueError(
            f"{description} payload exceeds the {MAX_PAYLOAD_BYTES}-byte limit"
        )

    worker_label = worker_description or description
    watch = _start_memory_watchdog(memory_bytes)
    pid_path, watch_stop, exceeded, watch_thread = _watchdog_parts(watch)
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                BOOTSTRAP_MODULE,
                "--cpu-seconds",
                str(selected_cpu),
                "--memory-bytes",
                str(memory_bytes),
                "--pid-file",
                pid_path,
                selected_module,
            ],
            input=serialized,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=worker_environment(),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise timeout_error(f"{description} exceeded {timeout_seconds:g}s") from exc
    finally:
        _stop_memory_watchdog(pid_path, watch_stop, watch_thread)

    def memory_failure() -> RuntimeError:
        return (memory_error or worker_error)(
            f"{worker_label} exceeded the {memory_bytes}-byte memory limit"
        )

    # A watchdog kill is authoritative even if the return code is ambiguous.
    if exceeded.is_set():
        raise memory_failure()
    envelope = _worker_envelope(completed.stdout)
    if envelope is not None:
        peak_rss = envelope.get("peak_rss_bytes")
        if type(peak_rss) is int and peak_rss > memory_bytes:
            raise memory_failure()
        if envelope.get("pid_published") is not True and not envelope.get(
            "kernel_memory_bytes"
        ):
            raise _memory_limit_unavailable(worker_error)
    if completed.returncode != 0:
        raise worker_error(
            f"{worker_label} exited with {completed.returncode}: "
            f"{completed.stderr.strip()[:MAX_STDERR_CHARS]}"
        )
    if envelope is not None:
        if envelope.get("payload_valid") is not True:
            raise worker_error(f"{worker_label} returned invalid JSON")
        response = envelope.get("payload")
    else:
        try:
            response = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise worker_error(f"{worker_label} returned invalid JSON") from exc
    if not isinstance(response, dict):
        raise worker_error(f"{worker_label} returned a non-object")
    if "error" in response:
        error = response["error"]
        code = ""
        if isinstance(error, dict):
            error_type = str(error.get("type", "error"))[:100]
            message = str(error.get("message", ""))[:MAX_ERROR_MESSAGE_CHARS]
            code = str(error.get("code", ""))[:100]
        else:
            error_type = "error"
            message = str(error)[:MAX_ERROR_MESSAGE_CHARS]
        failure = worker_error(f"{error_type}: {message}")
        if code and isinstance(failure, CodedWorkerError):
            failure.code = code
        raise failure
    return response


def _worker_envelope(stdout: str) -> dict[str, Any] | None:
    """Return the bootstrap envelope, or ``None`` for a legacy raw response."""
    try:
        response = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    if (
        not isinstance(response, dict)
        or response.get("worker_envelope") != WORKER_ENVELOPE
    ):
        return None
    return response


def _memory_limit_unavailable(worker_error: type[RuntimeError]) -> RuntimeError:
    """Build an error that is both distinct and catchable by the caller.

    Callers catch their own worker-error type; subclassing it dynamically keeps
    the fail-closed outcome on the existing error transport while letting
    callers and tests identify ``MemoryLimitUnavailable`` specifically.
    """
    failure_type = type(
        "MemoryLimitUnavailable", (MemoryLimitUnavailable, worker_error), {}
    )
    return failure_type(
        "worker memory limit could not be enforced: no pid handshake and no "
        "kernel limit were available"
    )


__all__ = [
    "BOOTSTRAP_MODULE",
    "CodedWorkerError",
    "DEFAULT_MEMORY_LIMIT_BYTES",
    "DEFAULT_RSS_POLL_INTERVAL_SECONDS",
    "MAX_PAYLOAD_BYTES",
    "MemoryLimitUnavailable",
    "RssWatchdog",
    "WORKER_ENVELOPE",
    "apply_best_effort_data_limit",
    "apply_resource_limits",
    "cpu_limit_for_timeout",
    "normalise_maxrss",
    "pid_start_time",
    "rss_bytes_for_pid",
    "rss_bytes_from_ps",
    "run_json_worker",
    "validate_worker_module",
    "worker_environment",
]
