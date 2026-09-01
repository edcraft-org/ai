import os

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Keep real OpenAI API tests opt-in for normal local development."""
    if os.getenv("RUN_OPENAI_LIVE_TESTS") == "1":
        return
    skip_openai_live = pytest.mark.skip(
        reason=(
            "Real OpenAI API tests are opt-in; set RUN_OPENAI_LIVE_TESTS=1 before a PR"
        )
    )
    for item in items:
        if "openai_live" in item.keywords:
            item.add_marker(skip_openai_live)
