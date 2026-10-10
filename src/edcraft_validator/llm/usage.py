"""Small, job-scoped records of application model calls and reported usage."""

import time
from typing import Literal

from pydantic import BaseModel, Field


class TokenUsage(BaseModel):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)

    @classmethod
    def from_counts(cls, input_tokens, output_tokens):
        # Missing or malformed provider metadata must not change checking behavior.
        def count(value):
            return value if type(value) is int and value >= 0 else None

        return cls(input_tokens=count(input_tokens), output_tokens=count(output_tokens))


class ModelCallRecord(TokenUsage):
    operation: Literal["generation", "revision", "checking", "acknowledgement"]
    duration_ms: float = Field(ge=0)
    error: str | None = None
    usage_unavailable_reason: str | None = None


class ModelUsageSummary(BaseModel):
    model_call_count: int = 0
    unavailable_call_count: int = 0
    input_tokens: int | None = 0
    output_tokens: int | None = 0
    # These remain useful when a timeout leaves the complete totals unknown.
    reported_input_tokens: int = 0
    reported_output_tokens: int = 0


def summarize_usage(calls: list[ModelCallRecord]) -> ModelUsageSummary:
    inputs = sum(call.input_tokens or 0 for call in calls)
    outputs = sum(call.output_tokens or 0 for call in calls)
    return ModelUsageSummary(
        model_call_count=len(calls),
        unavailable_call_count=sum(
            call.input_tokens is None or call.output_tokens is None for call in calls
        ),
        input_tokens=inputs if all(c.input_tokens is not None for c in calls) else None,
        output_tokens=outputs
        if all(c.output_tokens is not None for c in calls)
        else None,
        reported_input_tokens=inputs,
        reported_output_tokens=outputs,
    )


class MeasuredProvider:
    """Observe calls without changing provider return types or domain schemas.

    Adapters may expose ``last_usage``, reset at the start of each call. Providers
    without usage metadata still work; their calls explicitly retain unknown usage.
    Counts describe application calls, not HTTP retries inside an SDK.
    """

    def __init__(self, delegate):
        self.delegate = delegate
        self.provider = delegate.provider
        self.model = delegate.model
        self.calls: list[ModelCallRecord] = []

    def generate(self, request):
        operation = (
            "revision" if request.schema_name == "template_revision" else "generation"
        )
        return self._call(operation, self.delegate.generate, request)

    def tool_turn(self, messages, tools):
        operation = "checking" if tools else "acknowledgement"
        return self._call(operation, self.delegate.tool_turn, messages, tools)

    def _call(self, operation, method, *args):
        started = time.perf_counter()
        error = None
        try:
            return method(*args)
        except Exception as exc:
            error = getattr(exc, "category", type(exc).__name__)
            raise
        finally:
            usage = getattr(self.delegate, "last_usage", None)
            if not isinstance(usage, TokenUsage):
                usage = TokenUsage()
            self.calls.append(
                ModelCallRecord(
                    operation=operation,
                    duration_ms=(time.perf_counter() - started) * 1000,
                    **usage.model_dump(),
                    error=error,
                    usage_unavailable_reason=(
                        "Provider did not report complete token usage for this call"
                        if usage.input_tokens is None or usage.output_tokens is None
                        else None
                    ),
                )
            )
