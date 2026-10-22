"""Four synthetic MCP integration cases; opt-in, paid embedding requests only."""

import hashlib
import json
import math
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastmcp import Client

from edcraft_validator.domains.code.difficulty import CodeDifficultyQuestion
from edcraft_validator.domains.code.relevance import (
    CodeQuestionRequest,
    relevance_input,
)
from edcraft_validator.llm.embeddings import OpenAIEmbeddingProvider
from edcraft_validator.mcp.server import create_validation_server
from edcraft_validator.relevance_contracts import RelevanceInput
from edcraft_validator.tools.python_execution import LocalPythonTool

pytestmark = pytest.mark.embedding_live


async def test_real_shared_relevance_and_independent_python_checks():
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY is not configured")
    root = Path(__file__).resolve().parents[1]
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    output = Path(
        os.getenv(
            "EDCRAFT_RELEVANCE_LIVE_OUTPUT",
            str(root / ".artifacts" / f"shared-relevance-live-{timestamp}"),
        )
    )
    output.mkdir(parents=True, exist_ok=False)
    calls, records, executions = [], [], []

    def save(name, value):
        (output / name).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")

    class RecordedEmbeddings(OpenAIEmbeddingProvider):
        def embed(self, texts):
            assert len(calls) < 4, "Live test exceeded its four-request budget"
            call = {
                "texts": texts.copy(),
                "provider": self.provider,
                "model": self.model,
            }
            calls.append(call)
            try:
                vectors = super().embed(texts)
                call.update(
                    vectors=vectors, usage=self.last_usage.model_dump(mode="json")
                )
                return vectors
            except Exception as exc:
                call["error_type"] = type(exc).__name__
                raise
            finally:
                save("calls.json", calls)

    class RecordedExecutor:
        def execute_batch(self, code, entry_function, inputs, *, timeout_seconds):
            executions.append({"entry_function": entry_function, "inputs": inputs})
            return LocalPythonTool().execute_batch(
                code, entry_function, inputs, timeout_seconds=timeout_seconds
            )

    def forbidden_judge():
        pytest.fail("Relevance integration must never construct a difficulty judge")

    item = CodeDifficultyQuestion.model_validate(
        {
            "code": "def f(x):\n    y = x + 2\n    return y * 2\n",
            "entry_function": "f",
            "inputs": {"x": 3},
            "question": "What does f(3) return?",
            "answer_target": "return_value",
            "options": [
                {"id": "A", "value": 6},
                {"id": "B", "value": 7},
                {"id": "C", "value": 10},
                {"id": "D", "value": 12},
            ],
            "correct_option": "C",
        }
    )
    request = CodeQuestionRequest(
        prompt="Create a Python tracing MCQ about arithmetic.",
        required_features=["arithmetic"],
        answer_target="return_value",
        num_distractors=3,
    )
    cases = [
        ("python-positive", item, request, "passed", "satisfied"),
        (
            "python-wrong-designation",
            item.model_copy(update={"correct_option": "A"}),
            request,
            "failed",
            "satisfied",
        ),
        (
            "python-missing-loop",
            item,
            request.model_copy(
                update={
                    "prompt": "Create a Python tracing MCQ that uses a loop.",
                    "required_features": ["loop"],
                }
            ),
            "passed",
            "missing",
        ),
    ]
    generic = RelevanceInput(
        author_request="Create a multiple-choice question about triangle angles.",
        question_text=(
            "Two angles of a triangle are 50 and 60 degrees. What is the third "
            "angle? Options: A 60 degrees; B 70 degrees; C 80 degrees."
        ),
        rendering_version="generic-text-v1",
        representation_limitations=["The accompanying diagram is not represented."],
    )
    source_files = sorted((root / "src").rglob("*.py")) + [Path(__file__)]
    save(
        "manifest.json",
        {
            "protocol": "shared-relevance-live-v1",
            "created_at": datetime.now(UTC).isoformat(),
            "source_revision": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True
            ).strip(),
            "source_sha256": hashlib.sha256(
                b"".join(
                    str(p.relative_to(root)).encode() + b"\0" + p.read_bytes()
                    for p in source_files
                )
            ).hexdigest(),
            "endpoint_host": urlsplit(
                os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1"
            ).hostname,
            "embedding_request_budget": 4,
            "sdk_retries": 0,
            "judge_call_budget": 0,
            "cases": [
                {
                    "case_id": name,
                    "question": q.model_dump(mode="json"),
                    "request": r.model_dump(mode="json"),
                    "expected_technical": technical,
                    "expected_requirements": requirements,
                }
                for name, q, r, technical, requirements in cases
            ]
            + [{"case_id": "generic-text", "relevance_input": generic.model_dump()}],
            "limitations": [
                "Synthetic integration checks, not a relevance accuracy evaluation.",
                "Interface smoke test; no second domain implementation.",
                "No semantic threshold or model ranking is evaluated.",
            ],
        },
    )
    verified = False
    try:
        async with Client(
            create_validation_server(
                code_execution_tool=RecordedExecutor(),
                embedding_provider_factory=RecordedEmbeddings,
                difficulty_provider_factory=forbidden_judge,
            )
        ) as client:
            tools = await client.list_tools()
            save(
                "tool-schemas.json",
                [t.model_dump(mode="json", by_alias=True) for t in tools],
            )

            async def measure(case_id, representation, **evidence):
                before_calls, before_executions = len(calls), len(executions)
                response = await client.call_tool(
                    "assess_relevance",
                    {"request": representation.model_dump(mode="json")},
                )
                data = response.structured_content
                records.append({"case_id": case_id, **evidence, "relevance": data})
                save("reports.json", records)
                assert data["status"] == "assessed", data
                assert len(calls) == before_calls + 1
                assert len(executions) == before_executions
                assert data["input_sha256"] == representation.sha256
                assert data["rendering_version"] == representation.rendering_version
                assert (
                    data["representation_limitations"]
                    == representation.representation_limitations
                )
                assert not {
                    "technical",
                    "requirements",
                    "judge",
                    "difficulty_report",
                } & set(data)
                similarity = data["similarity"]
                assert calls[-1]["texts"] == [
                    similarity["request_text"],
                    similarity["question_text"],
                ]
                assert similarity["request_text"] == representation.author_request
                assert similarity["question_text"] == representation.question_text
                assert similarity["model"] == calls[-1]["model"]
                first, second = calls[-1]["vectors"]
                expected = math.fsum(
                    a * b for a, b in zip(first, second, strict=True)
                ) / (
                    math.sqrt(math.fsum(x * x for x in first))
                    * math.sqrt(math.fsum(x * x for x in second))
                )
                assert similarity["similarity"] == pytest.approx(expected, abs=1e-12)
                assert similarity["dimensions"] == len(first) == len(second)
                assert similarity["usage"] == calls[-1]["usage"]

            for name, q, r, technical, requirements in cases:
                correctness = await client.call_tool(
                    "check_code_question_correctness",
                    {"question": q.model_dump(mode="json")},
                )
                required = await client.call_tool(
                    "check_code_question_requirements",
                    {
                        "question": q.model_dump(mode="json"),
                        "request": r.model_dump(mode="json"),
                    },
                )
                assert correctness.structured_content["status"] == technical
                assert required.structured_content["status"] == requirements
                assert correctness.structured_content["canonical_answer"] == 10
                await measure(
                    name,
                    relevance_input(q, r),
                    technical=correctness.structured_content,
                    requirements=required.structured_content,
                )
            await measure("generic-text", generic)
        assert len(calls) == 4 and len(executions) == 3
        assert len({call["model"] for call in calls}) == 1
        assert (
            records[0]["relevance"]["input_sha256"]
            == records[1]["relevance"]["input_sha256"]
        )
        assert (
            records[0]["technical"]["question_sha256"]
            != records[1]["technical"]["question_sha256"]
        )
        verified = True
    finally:
        save("calls.json", calls)
        save("reports.json", records)
        known_usage = [call.get("usage", {}).get("input_tokens") for call in calls]
        save(
            "verification.json",
            {
                "passed": verified,
                "embedding_requests": len(calls),
                "execution_requests": len(executions),
                "judge_calls": 0,
                "completed_cases": len(records),
                "embedding_input_tokens": sum(known_usage)
                if all(v is not None for v in known_usage)
                else None,
            },
        )
