"""Apply trusted resource limits, then load the selected worker module.

This module is intentionally tiny: it contains no application logic and accepts
only a trusted module constant, numeric limits and a parent-provided handshake
path from the parent process.
"""

from __future__ import annotations

import argparse
import os
import runpy

from edcraft_validator.tools.isolated_process import (
    apply_best_effort_data_limit,
    apply_resource_limits,
    validate_worker_module,
)


def _publish_pid(path: str) -> None:
    """Publish this process's pid atomically for the parent RSS watchdog."""
    temporary = f"{path}.tmp"
    try:
        with open(temporary, "w", encoding="ascii") as handle:
            handle.write(str(os.getpid()))
        os.replace(temporary, path)
    except OSError:  # pragma: no cover - best effort handshake
        return


def main(argv: list[str] | None = None) -> None:
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
    _publish_pid(arguments.pid_file)
    apply_resource_limits(
        cpu_seconds=arguments.cpu_seconds,
        memory_bytes=arguments.memory_bytes,
    )
    apply_best_effort_data_limit(arguments.memory_bytes)
    runpy.run_module(module, run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
