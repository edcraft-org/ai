"""Shared host-selected model for difficulty decisions, reasoning and relevance."""

import os

from edcraft_validator.llm.llm_contracts import TemplateProviderSelection
from edcraft_validator.llm.provider_registry import create_model_provider


def configured_judge_provider():
    return create_model_provider(
        TemplateProviderSelection(
            provider=os.getenv("EDCRAFT_JUDGE_PROVIDER", "soclaas"),
            model=os.getenv("EDCRAFT_JUDGE_MODEL", "x-test-3"),
        )
    )


def configured_reasoning_effort():
    effort = os.getenv("EDCRAFT_JUDGE_REASONING_EFFORT", "medium").strip()
    if effort not in {"low", "medium", "high", "xhigh"}:
        raise ValueError("Judge reasoning effort must be low, medium, high or xhigh")
    return effort
