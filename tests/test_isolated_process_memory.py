"""Parent-side RSS watchdog, self-reported peak RSS and platform limits."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time

import pytest

from edcraft_validator.tools import isolated_process

requires_rss = pytest.mark.skipif(
    not isolated_process._RSS_AVAILABLE,
    reason="POSIX RSS watchdog is unavailable on this platform",
)

NO_KERNEL_LIMITS_SITECUSTOMIZE = """\
from edcraft_validator.tools import isolated_process

isolated_process.apply_resource_limits = lambda **kwargs: {}
isolated_process.apply_best_effort_data_limit = lambda memory_bytes: None
"""

FAST_PROBE = """\
import json
import sys


def main() -> int:
    json.load(sys.stdin)
    ballast = bytearray(64 * 1024 * 1024)
    ballast[::4096] = b"x" * (len(ballast) // 4096)
    json.dump({"result": {"ok": True}}, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
"""

SLOW_PROBE = """\
import json
import sys
import time


def main() -> int:
    json.load(sys.stdin)
    ballast = bytearray(64 * 1024 * 1024)
    ballast[::4096] = b"x" * (len(ballast) // 4096)
    time.sleep(8)
    json.dump({"result": {"ok": True}}, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
"""

TINY_PROBE = """\
import json
import sys


def main() -> int:
    json.load(sys.stdin)
    json.dump({"result": {"ok": True}}, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
"""


class WorkerMemoryError(RuntimeError):
    """Local memory-error type mirroring a caller's public exception."""


def _install_probe(tmp_path, monkeypatch, name: str, source: str) -> str:
    """Put a probe module plus a no-kernel-limit ``sitecustomize`` on sys.path.

    Disabling the kernel limits lets every platform exercise the same
    deterministic layers: the self-reported peak RSS and the parent watchdog.
    The child interpreter imports ``sitecustomize`` from ``PYTHONPATH`` before
    the bootstrap module resolves its imports.
    """
    (tmp_path / "sitecustomize.py").write_text(
        NO_KERNEL_LIMITS_SITECUSTOMIZE, encoding="utf-8"
    )
    (tmp_path / f"{name}.py").write_text(source, encoding="utf-8")
    existing = os.environ.get("PYTHONPATH")
    path = str(tmp_path)
    if existing:
        path = f"{path}{os.pathsep}{existing}"
    monkeypatch.setenv("PYTHONPATH", path)
    return name


def _run(module: str, memory_bytes: int) -> dict[str, object]:
    return isolated_process.run_json_worker(
        {},
        module=module,
        timeout_seconds=10,
        timeout_error=TimeoutError,
        worker_error=RuntimeError,
        memory_error=WorkerMemoryError,
        description="memory probe",
        memory_bytes=memory_bytes,
    )


class FakeWatchdogChild:
    def __init__(self) -> None:
        self.kills = 0

    def kill(self) -> None:
        self.kills += 1


def test_ps_rss_output_is_parsed_as_kibibytes():
    assert isolated_process.rss_bytes_from_ps("  2048\n") == 2 * 1024 * 1024
    assert isolated_process.rss_bytes_from_ps("\n") is None
    assert isolated_process.rss_bytes_from_ps("not-a-number") is None
    assert isolated_process.rss_bytes_from_ps("-4") is None


def test_ru_maxrss_is_normalised_to_bytes():
    assert isolated_process.normalise_maxrss(2048, "darwin") == 2048
    assert isolated_process.normalise_maxrss(2048, "linux") == 2048 * 1024
    with pytest.raises(ValueError):
        isolated_process.normalise_maxrss(-1, "linux")
    with pytest.raises(ValueError):
        isolated_process.normalise_maxrss(True, "linux")  # type: ignore[arg-type]


def test_watchdog_kills_a_process_above_the_cap():
    child = FakeWatchdogChild()
    exceeded: list[bool] = []
    readings = iter([1024, 5000, 5000])
    watchdog = isolated_process.RssWatchdog(
        4242,
        4096,
        kill=child.kill,
        on_exceeded=lambda: exceeded.append(True),
        read_rss=lambda pid: next(readings),
    )

    assert watchdog.poll_once() is False
    assert watchdog.exceeded is False
    assert child.kills == 0

    assert watchdog.poll_once() is True
    assert watchdog.exceeded is True
    assert child.kills == 1
    assert exceeded == [True]

    # Once exceeded, later polls never kill twice or read again.
    assert watchdog.poll_once() is True
    assert child.kills == 1
    assert next(readings, None) == 5000


def test_watchdog_ignores_missing_and_below_cap_readings():
    child = FakeWatchdogChild()
    watchdog = isolated_process.RssWatchdog(
        7,
        2048,
        kill=child.kill,
        read_rss=lambda pid: None,
    )
    assert watchdog.poll_once() is False
    assert child.kills == 0
    assert watchdog.exceeded is False


def test_watchdog_rejects_invalid_cap_arithmetic():
    with pytest.raises(ValueError):
        isolated_process.RssWatchdog(1, 0, kill=lambda: None)
    with pytest.raises(ValueError):
        isolated_process.RssWatchdog(1, -10, kill=lambda: None)
    with pytest.raises(ValueError):
        isolated_process.RssWatchdog(1, True, kill=lambda: None)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        isolated_process.RssWatchdog(1, 10, kill=lambda: None, interval=0)


def test_worker_memory_failure_uses_the_memory_error_path(monkeypatch):
    stop = threading.Event()
    exceeded = threading.Event()
    exceeded.set()
    monkeypatch.setattr(
        isolated_process,
        "_start_memory_watchdog",
        lambda memory_bytes: ("/tmp/unused.pid", stop, exceeded),
    )
    monkeypatch.setattr(
        isolated_process.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            [], -signal.SIGKILL, "", ""
        ),
    )

    with pytest.raises(WorkerMemoryError, match="memory limit"):
        isolated_process.run_json_worker(
            {},
            module="edcraft_validator.domains.math.engine.worker",
            timeout_seconds=5,
            timeout_error=TimeoutError,
            worker_error=RuntimeError,
            memory_error=WorkerMemoryError,
            description="test worker",
        )


def test_worker_memory_failure_does_not_require_a_nonzero_exit_code(monkeypatch):
    stop = threading.Event()
    envelope = (
        '{"worker_envelope": "edcraft-worker-envelope/1", '
        '"peak_rss_bytes": 2048, "pid_published": true, '
        '"kernel_memory_bytes": null, "payload_valid": true, "payload": {}}'
    )
    monkeypatch.setattr(
        isolated_process,
        "_start_memory_watchdog",
        lambda memory_bytes: ("/tmp/unused.pid", stop, threading.Event()),
    )
    monkeypatch.setattr(
        isolated_process.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess([], 0, envelope, ""),
    )

    with pytest.raises(WorkerMemoryError, match="memory limit"):
        _run("ignored.module", 1024)


def test_worker_without_a_pid_handshake_fails_closed(monkeypatch):
    stop = threading.Event()
    monkeypatch.setattr(
        isolated_process,
        "_start_memory_watchdog",
        lambda memory_bytes: (
            "/nonexistent-edcraft/worker.pid",
            stop,
            threading.Event(),
        ),
    )
    monkeypatch.setattr(
        isolated_process.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            [],
            0,
            '{"worker_envelope": "edcraft-worker-envelope/1", '
            '"peak_rss_bytes": 1024, "pid_published": false, '
            '"kernel_memory_bytes": null, "payload_valid": true, "payload": {}}',
            "",
        ),
    )

    with pytest.raises(
        isolated_process.MemoryLimitUnavailable, match="could not be enforced"
    ):
        _run("ignored.module", 1024 * 1024)


@pytest.mark.skipif(
    isolated_process.resource is None, reason="resource module unavailable"
)
def test_macos_data_limit_preserves_the_hard_limit(monkeypatch):
    resource = isolated_process.resource
    assert resource is not None
    calls: list[tuple[int, tuple[int, int]]] = []
    memory = 512 * 1024 * 1024
    monkeypatch.setattr(isolated_process.sys, "platform", "darwin")
    monkeypatch.setattr(
        isolated_process.resource,
        "getrlimit",
        lambda kind: (resource.RLIM_INFINITY, resource.RLIM_INFINITY),
    )
    monkeypatch.setattr(
        isolated_process.resource,
        "setrlimit",
        lambda kind, limits: calls.append((kind, limits)),
    )

    assert isolated_process.apply_best_effort_data_limit(memory) == memory
    assert calls == [(resource.RLIMIT_DATA, (memory, resource.RLIM_INFINITY))]

    hard = 256 * 1024 * 1024
    monkeypatch.setattr(
        isolated_process.resource,
        "getrlimit",
        lambda kind: (resource.RLIM_INFINITY, hard),
    )
    calls.clear()
    assert isolated_process.apply_best_effort_data_limit(memory) == hard
    assert calls == [(resource.RLIMIT_DATA, (hard, hard))]

    # A tighter inherited soft limit is never raised.
    soft = 128 * 1024 * 1024
    monkeypatch.setattr(
        isolated_process.resource,
        "getrlimit",
        lambda kind: (soft, hard),
    )
    calls.clear()
    assert isolated_process.apply_best_effort_data_limit(memory) == soft
    assert calls == [(resource.RLIMIT_DATA, (soft, hard))]

    monkeypatch.setattr(isolated_process.sys, "platform", "linux")
    calls.clear()
    assert isolated_process.apply_best_effort_data_limit(memory) is None
    assert calls == []


def test_watchdog_does_not_kill_a_recycled_pid():
    child = FakeWatchdogChild()
    watchdog = isolated_process.RssWatchdog(
        4242,
        1024,
        kill=child.kill,
        read_rss=lambda pid: 4096,
        verify=lambda: False,
    )

    assert watchdog.poll_once() is False
    assert watchdog.exceeded is False
    assert child.kills == 0


def test_watchdog_rechecks_stop_before_killing():
    child = FakeWatchdogChild()
    stop = threading.Event()
    stop.set()
    watchdog = isolated_process.RssWatchdog(
        4242,
        1024,
        kill=child.kill,
        read_rss=lambda pid: 4096,
        verify=lambda: True,
    )

    assert watchdog.poll_once(stop) is False
    assert watchdog.exceeded is False
    assert child.kills == 0


def test_kill_pid_refuses_an_unverified_process(monkeypatch):
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(
        isolated_process.os, "kill", lambda pid, sig: signals.append((pid, sig))
    )

    assert isolated_process._kill_pid(4242, verify=lambda: False) is False
    assert signals == []
    assert isolated_process._kill_pid(4242, verify=lambda: True) is True
    assert signals == [(4242, signal.SIGKILL)]


def test_fast_worker_over_the_cap_is_rejected(tmp_path, monkeypatch):
    module = _install_probe(tmp_path, monkeypatch, "dme_fast_probe", FAST_PROBE)

    started = time.perf_counter()
    with pytest.raises(WorkerMemoryError, match="memory limit"):
        _run(module, 1024 * 1024)
    assert time.perf_counter() - started < 10


def test_small_worker_under_the_cap_still_succeeds(tmp_path, monkeypatch):
    module = _install_probe(tmp_path, monkeypatch, "dme_tiny_probe", TINY_PROBE)

    assert _run(module, 256 * 1024 * 1024) == {"result": {"ok": True}}


def test_long_running_worker_over_the_cap_is_killed(tmp_path, monkeypatch):
    module = _install_probe(tmp_path, monkeypatch, "dme_slow_probe", SLOW_PROBE)

    started = time.perf_counter()
    with pytest.raises(WorkerMemoryError, match="memory limit"):
        _run(module, 48 * 1024 * 1024)
    assert time.perf_counter() - started < 5


def test_missing_pid_file_fails_closed_end_to_end(tmp_path, monkeypatch):
    module = _install_probe(tmp_path, monkeypatch, "dme_tiny_probe_closed", TINY_PROBE)
    stop = threading.Event()
    monkeypatch.setattr(
        isolated_process,
        "_start_memory_watchdog",
        lambda memory_bytes: (
            "/nonexistent-edcraft/worker.pid",
            stop,
            threading.Event(),
        ),
    )

    with pytest.raises(
        isolated_process.MemoryLimitUnavailable, match="could not be enforced"
    ):
        _run(module, 256 * 1024 * 1024)


@requires_rss
def test_cheap_child_that_grows_memory_is_killed(tmp_path):
    pid_path = tmp_path / "child.pid"
    program = (
        "import os, sys, time\n"
        "open(sys.argv[1], 'w').write(str(os.getpid()))\n"
        "ballast = bytearray(64 * 1024 * 1024)\n"
        "ballast[::4096] = b'x' * (len(ballast) // 4096)\n"
        "time.sleep(5)\n"
    )
    child = subprocess.Popen([sys.executable, "-c", program, str(pid_path)])
    deadline = time.monotonic() + 5
    while not pid_path.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert pid_path.exists(), "child never published its pid"

    stop = threading.Event()
    watchdog = isolated_process.RssWatchdog(
        int(pid_path.read_text()),
        48 * 1024 * 1024,
        kill=lambda: os.kill(child.pid, signal.SIGKILL),
        interval=0.02,
    )
    watcher = threading.Thread(target=watchdog.watch, args=(stop,), daemon=True)
    watcher.start()
    try:
        child.wait(timeout=8)
    finally:
        stop.set()
        watcher.join(timeout=2)
        if child.poll() is None:  # pragma: no cover - safety net
            child.kill()
            child.wait(timeout=5)

    assert watchdog.exceeded is True
    assert child.returncode != 0
