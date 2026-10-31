"""Structured-only providers used by authoring integration tests."""

from edcraft_validator.llm.llm_contracts import CheckPlanResponse


class RequestPendingTools:
    def generation_settings(self):
        return {"mode": "scripted"}

    def tool_turn(self, messages, tools):
        raise AssertionError("Workflow must dispatch checks without native tool turns")


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
