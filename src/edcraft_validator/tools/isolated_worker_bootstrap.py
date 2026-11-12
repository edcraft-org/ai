"""Apply trusted resource limits, then load the selected worker module.

This module is intentionally tiny: it contains no application logic and accepts
only a trusted module constant and numeric limits from the parent process.
"""

from __future__ import annotations

import argparse
import runpy

from edcraft_validator.tools.isolated_process import (
    apply_resource_limits,
    validate_worker_module,
)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--cpu-seconds", type=int, required=True)
    parser.add_argument("--memory-bytes", type=int, required=True)
    parser.add_argument("module")
    arguments = parser.parse_args(argv)
    if arguments.cpu_seconds <= 0:
        parser.error("--cpu-seconds must be positive")
    if arguments.memory_bytes <= 0:
        parser.error("--memory-bytes must be positive")
    module = validate_worker_module(arguments.module)
    apply_resource_limits(
        cpu_seconds=arguments.cpu_seconds,
        memory_bytes=arguments.memory_bytes,
    )
    runpy.run_module(module, run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
