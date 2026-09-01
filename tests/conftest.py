import os

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Keep real OpenAI template-authoring tests opt-in during local work."""
    if os.getenv("RUN_OPENAI_LIVE_TESTS") == "1":
        return
    skip_openai_live = pytest.mark.skip(
        reason=("Real OpenAI template tests are opt-in; set RUN_OPENAI_LIVE_TESTS=1")
    )
    for item in items:
        if "openai_live" in item.keywords:
            item.add_marker(skip_openai_live)
