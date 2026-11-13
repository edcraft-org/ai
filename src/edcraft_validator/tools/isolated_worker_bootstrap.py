"""Apply trusted resource limits, then load the selected worker module.

This module is intentionally tiny: it contains no application logic and accepts
only a trusted module constant, numeric limits and a parent-provided handshake
path from the parent process.

It also wraps the worker's stdout in a single envelope carrying the process's
peak resident set size. The parent compares that exact high-water mark with the
memory cap, so a fast worker that over-allocates and exits zero is still caught
even when the polling watchdog never gets a chance to run.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import runpy
import sys
from typing import Any

from edcraft_validator.tools.isolated_process import (
    WORKER_ENVELOPE,
    apply_best_effort_data_limit,
    apply_resource_limits,
    normalise_maxrss,
    validate_worker_module,
)

try:  # pragma: no cover - the resource module is unavailable on Windows
    import resource
except ImportError:  # pragma: no cover
    resource = None  # type: ignore[assignment]


def _publish_pid(path: str) -> bool:
    """Publish this process's pid atomically for the parent RSS watchdog."""
    temporary = f"{path}.tmp"
    try:
        with open(temporary, "w", encoding="ascii") as handle:
            handle.write(str(os.getpid()))
        os.replace(temporary, path)
    except OSError:  # pragma: no cover - reported to the parent in the envelope
        return False
    return True


def _peak_rss_bytes() -> int | None:
    """Return this process's lifetime peak RSS, normalised to bytes."""
    if resource is None or not hasattr(resource, "RUSAGE_SELF"):
        return None
    try:
        usage = resource.getrusage(resource.RUSAGE_SELF)
        return normalise_maxrss(usage.ru_maxrss)
    except (OSError, ValueError):  # pragma: no cover - platform dependent
        return None


def _run_module(module: str) -> tuple[bool, int, Any, int | None]:
    """Run the worker, capturing its stdout and exit status.

    Returns ``(payload_valid, exit_code, payload, peak_rss_bytes)``. The peak is
    sampled immediately after the worker returns, before envelope parsing or
    serialisation adds parent-side allocations.
    """
    buffer = io.StringIO()
    exit_code = 0
    with contextlib.redirect_stdout(buffer):
        try:
            runpy.run_module(module, run_name="__main__", alter_sys=True)
        except SystemExit as exc:
            if exc.code is None:
                exit_code = 0
            elif isinstance(exc.code, int):
                exit_code = exc.code
            else:
                print(exc.code, file=sys.stderr)
                exit_code = 1
    peak_rss = _peak_rss_bytes()
    try:
        payload = json.loads(buffer.getvalue())
    except json.JSONDecodeError:
        return False, exit_code, None, peak_rss
    return True, exit_code, payload, peak_rss


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--cpu-seconds", type=int, required=True)
    parser.add_argument("--memory-bytes", type=int, required=True)
    parser.add_argument("--pid-file", required=True)
    parser.add_argument("module")
    arguments = parser.parse_args(argv)
    if arguments.cpu_seconds <= 0:
        parser.error("--cpu-seconds must be positive")
    if arguments.memory_bytes <= 0:
        parser.error("--memory-bytes must be positive")
    module = validate_worker_module(arguments.module)

    pid_published = _publish_pid(arguments.pid_file)
    applied = apply_resource_limits(
        cpu_seconds=arguments.cpu_seconds,
        memory_bytes=arguments.memory_bytes,
    )
    data_limit = apply_best_effort_data_limit(arguments.memory_bytes)
    kernel_memory = applied.get("memory_bytes") or data_limit

    payload_valid, exit_code, payload, peak_rss = _run_module(module)
    envelope = {
        "worker_envelope": WORKER_ENVELOPE,
        "peak_rss_bytes": peak_rss,
        "pid_published": pid_published,
        "kernel_memory_bytes": kernel_memory,
        "payload_valid": payload_valid,
        "payload": payload,
    }
    json.dump(envelope, sys.stdout, allow_nan=False)
    sys.stdout.flush()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
