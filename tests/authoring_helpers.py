"""Scripted native tool turns used by authoring integration tests."""

import uuid

from edcraft_validator.llm.llm_contracts import CheckPlanResponse, ModelTurn, ToolCall


class RequestPendingTools:
    def generation_settings(self):
        return {"mode": "scripted"}

    def tool_turn(self, messages, tools):
        return ModelTurn(
            calls=[
                ToolCall(
                    id=str(uuid.uuid4()),
                    name=tool["function"]["name"],
                    arguments_json="{}",
                )
                for tool in tools
            ]
        )


class SelectSemanticCheck(RequestPendingTools):
    """Deterministic model fixture; production selection always uses a provider."""

    provider = "stub"
    model = "stub-check-selector"

    def generate(self, request):
        assert request.response_model is CheckPlanResponse
        return CheckPlanResponse.model_validate(
            {
                "checks": [
                    {"name": "code_validate_answers_and_distractors", "arguments": {}}
                ]
            }
        )
