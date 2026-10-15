"""Blinded rubric/schema experiments retain the original three training anchors."""

import hashlib
import json

import pytest
from fastmcp import Client
from pydantic import ValidationError
from test_difficulty_tool import ForbiddenExecutor, Provider, assessment, question

from edcraft_validator.domains.code.difficulty import (
    DifficultyAssessment,
    load_code_difficulty_rubric,
)
from edcraft_validator.domains.code.difficulty_profiles import (
    PROFILES,
    build_profile_request,
    keyed_assessment_model,
    runtime_instructions,
    worked_anchors,
)
from edcraft_validator.mcp.difficulty_tools import configured_difficulty_provider
from edcraft_validator.mcp.server import create_validation_server


def keyed_payload(count=4):
    payload = assessment()
    payload["option_evidence"] = {
        item["option_id"]: {k: v for k, v in item.items() if k != "option_id"}
        for item in payload["option_evidence"][:count]
    }
    return payload


@pytest.mark.parametrize("count", [3, 4])
def test_exact_option_keys_are_required_closed_and_normalize_losslessly(count):
    model = keyed_assessment_model(count)
    schema = model.model_json_schema()
    for node in [schema, *schema["$defs"].values()]:
        if node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])
    payload = keyed_payload(count)
    result = model.model_validate(payload).to_assessment()
    assert isinstance(result, DifficultyAssessment)
    assert (
        result.option_evidence
        == DifficultyAssessment.model_validate(
            assessment() | {"option_evidence": assessment()["option_evidence"][:count]}
        ).option_evidence
    )
    del payload["option_evidence"]["C"]
    with pytest.raises(ValidationError):
        model.model_validate(payload)
    payload = keyed_payload(count)
    payload["option_evidence"]["E"] = payload["option_evidence"]["A"]
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_exact_option_schema_keeps_missing_information_and_text_validation():
    model = keyed_assessment_model(4)
    for change in (
        {"estimated_difficulty": None, "unable_to_assess_reason": None},
        {"reason": " "},
    ):
        with pytest.raises(ValidationError):
            model.model_validate(keyed_payload() | change)
    result = model.model_validate(
        keyed_payload()
        | {"estimated_difficulty": None, "unable_to_assess_reason": "Missing input."}
    )
    assert result.to_assessment().estimated_difficulty is None


def test_runtime_has_only_three_original_anchors_and_no_review_prerequisites():
    rubric = load_code_difficulty_rubric()
    prompt = runtime_instructions(rubric)
    anchors = worked_anchors(rubric)
    assert len(anchors) == 3 and prompt.count("```python") == 3
    assert all(anchor in rubric.text and anchor in prompt for anchor in anchors)
    assert len(prompt) < len(rubric.text)
    assert "Confidence is a qualitative judgment" not in prompt
    assert "Confirm execution-derived answer evidence" not in prompt
    assert "Repair ineligible cases before rating" not in prompt
    assert "Do not execute code, verify correctness" in prompt
    assert "Do not sum dimension ratings" in prompt


@pytest.mark.parametrize("profile", PROFILES)
async def test_profile_is_blinded_single_pass_and_mcp_output_remains_canonical(profile):
    providers = []

    def factory():
        value = Provider()
        providers.append(value)
        return value

    async with Client(
        create_validation_server(
            difficulty_provider_factory=factory,
            difficulty_request_builder=lambda q, r: build_profile_request(
                q, r, profile=profile
            ),
            code_execution_tool=ForbiddenExecutor(),
        )
    ) as client:
        response = await client.call_tool(
            "assess_code_difficulty",
            {
                "question": question().model_dump(mode="json"),
                "requested_difficulty": "hard",
            },
        )
    value = response.structured_content
    assert value["status"] == "assessed" and value["difficulty_match"] == "too_easy"
    assert value["judge"]["assessment"] == assessment()
    assert value["usage"]["model_call_count"] == len(providers) == 1
    request = providers[0].requests[0]
    assert json.loads(request.messages[1]["content"]) == {
        "question": question().model_dump(mode="json")
    }
    if profile == "control":
        assert (
            hashlib.sha256(
                json.dumps(
                    request.response_model.model_json_schema(), sort_keys=True
                ).encode()
            ).hexdigest()
            == "8662c389dc673db9874153fc740cc4602932ad96fd730ad467ccda9bea17f24f"
        )


def test_soclaas_is_default_and_other_providers_are_rejected(monkeypatch):
    from edcraft_validator.mcp import difficulty_tools

    selected = []
    monkeypatch.delenv("EDCRAFT_DIFFICULTY_PROVIDER", raising=False)
    monkeypatch.setattr(
        difficulty_tools,
        "create_model_provider",
        lambda s: selected.append(s) or Provider(),
    )
    configured_difficulty_provider()
    assert selected[0].provider == "soclaas"
    for name in ("openai", "ollama"):
        monkeypatch.setenv("EDCRAFT_DIFFICULTY_PROVIDER", name)
        with pytest.raises(ValueError, match="SocLaas only"):
            configured_difficulty_provider()
    assert len(selected) == 1
