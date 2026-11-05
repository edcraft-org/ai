"""Run the authoring worker as ``python -m edcraft_validator.worker``."""

import sys

from edcraft_validator.worker.main import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
