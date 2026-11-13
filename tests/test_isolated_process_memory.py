"""Parent-side RSS watchdog and the macOS data-segment guard."""

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

    class WorkerMemoryError(RuntimeError):
        pass

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


@pytest.mark.skipif(
    isolated_process.resource is None, reason="resource module unavailable"
)
def test_macos_attempts_a_best_effort_data_limit(monkeypatch):
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
    assert calls == [(resource.RLIMIT_DATA, (memory, memory))]
    monkeypatch.setattr(isolated_process.sys, "platform", "linux")
    calls.clear()
    assert isolated_process.apply_best_effort_data_limit(memory) is None
    assert calls == []


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
