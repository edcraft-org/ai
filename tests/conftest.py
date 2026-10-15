import os

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Keep real model calls opt-in during local work."""
    for marker, variable in (
        ("openai_live", "RUN_OPENAI_LIVE_TESTS"),
        ("ollama_live", "RUN_OLLAMA_LIVE_TESTS"),
    ):
        if os.getenv(variable) != "1":
            for item in items:
                if marker in item.keywords:
                    item.add_marker(pytest.mark.skip(reason=f"Set {variable}=1"))
