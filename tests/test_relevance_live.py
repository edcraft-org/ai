"""Opt-in MCP integration using already downloaded local Qwen weights."""

import pytest
from fastmcp import Client

from edcraft_validator.llm.decision import DEFAULT_RELEVANCE_MODEL
from edcraft_validator.mcp.server import create_validation_server

pytestmark = pytest.mark.relevance_live


async def test_local_qwen_mcp_returns_decision_without_other_checks():
    def forbidden():
        pytest.fail("Relevance must not call the difficulty judge")

    class ForbiddenExecutor:
        def execute_batch(self, *args, **kwargs):
            pytest.fail("Relevance must not execute question code")

    server = create_validation_server(
        difficulty_provider_factory=forbidden,
        code_execution_tool=ForbiddenExecutor(),
    )
    async with Client(server) as client:
        for objective, text in [
            ("Add two integers.", "What is 2 + 3?"),
            ("Explain photosynthesis.", "What is 2 + 3?"),
        ]:
            result = await client.call_tool(
                "assess_relevance",
                {"request": {"author_request": objective, "question_text": text}},
            )
            data = result.structured_content
            assert data["status"] == "assessed", data
            decision = data["decision"]
            assert decision["model"] == DEFAULT_RELEVANCE_MODEL
            assert decision["provider"] == "transformers-local"
            assert 0 <= decision["score"] <= 1
            assert decision["relevant"] == (decision["score"] >= decision["threshold"])
            assert (
                not {"similarity", "technical", "difficulty", "requirements"}
                & data.keys()
            )
