"""Shared question, template and judge fixtures without test-module imports."""

import json

from edcraft_validator.domains.code.code_domain import CodeDomain
from edcraft_validator.domains.code.code_schemas import (
    CodeTemplateProposal,
    CodeTemplateRequest,
)
from edcraft_validator.llm.usage import TokenUsage


def proposal(*, code: str = "def add(a, b):\n    return a + b") -> CodeTemplateProposal:
    return CodeTemplateProposal.model_validate(
        {
            "question_template": "What does add({a}, {b}) return?",
            "code": code,
            "entry_function": "add",
            "parameters": [
                {"name": "a", "kind": "integer", "values": [1, 2]},
                {"name": "b", "kind": "integer", "values": [3, 4]},
            ],
            "answer_target": "return_value",
            "answer_expression": "a + b",
            "distractors": [
                {"expression": "a + b", "reason_template": "Repeats answer."},
                {"expression": "a - b", "reason_template": "Subtracts."},
                {"expression": "a + b + 1", "reason_template": "Adds one."},
                {"expression": "a + b - 1", "reason_template": "Subtracts one."},
                {"expression": "a + b + 2", "reason_template": "Adds two."},
            ],
        }
    )


def assessment():
    return {
        "estimated_difficulty": "easy",
        "dimensions": {
            name: {"rating": "low", "reason": reason}
            for name, reason in {
                "execution_burden": "Two sequential calculations give 5 then 10.",
                "changing_state": "Only y is assigned before the return.",
                "conceptual_interaction": "Addition feeds multiplication directly.",
                "answer_discrimination": "Sequential evaluation distinguishes C.",
            }.items()
        },
        "reason": "A short direct trace needs little coordination.",
        "solution_reasoning": "x is 3, y becomes 5, and the return value is 10.",
        "concepts_and_dependencies": "Assignment, addition, then multiplication.",
        "shortcuts": "Substitution gives (3 + 2) * 2.",
        "nearest_anchor": "The easy arithmetic worked anchor.",
        "option_evidence": [
            {
                "option_id": option_id,
                "reasoning": reason,
                "hypothesised_error": None if option_id == "C" else reason,
                "shortcut_or_cue": None,
            }
            for option_id, reason in zip(
                "ABCD",
                [
                    "6 omits the addition.",
                    "7 applies multiplication before addition.",
                    "10 follows both assignments correctly.",
                    "12 uses an extra increment, a weak distractor hypothesis.",
                ],
                strict=True,
            )
        ],
        "unable_to_assess_reason": None,
        "quality_concerns": ["The 12 distractor has weak plausibility evidence."],
    }


def candidate():
    return CodeDomain().build_candidate(
        CodeTemplateRequest(prompt="Create an addition question", difficulty="easy"),
        proposal(),
    )


class TemplateJudge:
    provider, model = "scripted", "template-judge"

    def __init__(self, estimate="easy", failure=None, confidence=0.95):
        self.estimate, self.failure = estimate, failure
        self.confidence = confidence
        self.requests = []

    def generation_settings(self):
        return {"sampling": "scripted", "max_retries": 0}

    def generate(self, request):
        self.requests.append(request)
        self.last_usage = TokenUsage(input_tokens=100, output_tokens=50)
        if self.failure:
            raise self.failure
        value = assessment()
        options = value.pop("option_evidence")
        value.update(
            estimated_difficulty=self.estimate,
            confidence=self.confidence if self.estimate else 0,
            domain_variation="All listed inputs need the same short reasoning.",
            unable_to_assess_reason="Essential code missing."
            if self.estimate is None
            else None,
            distractor_evidence={
                f"D{i}": {k: v for k, v in options[0].items() if k != "option_id"}
                for i in range(
                    1,
                    len(
                        json.loads(request.messages[1]["content"])["template"][
                            "distractors"
                        ]
                    )
                    + 1,
                )
            },
        )
        return request.response_model.model_validate(value)


class TemplateAuthor:
    provider, model = "scripted", "author"

    def __init__(self, *, wrong_first=False):
        self.calls = 0
        self.wrong_first = wrong_first
        self.thread_ids = []
        self.closed = False

    def generation_settings(self):
        return {"mode": "scripted"}

    def generate(self, request):
        import threading

        from edcraft_validator.llm.llm_contracts import PlannedGenerationResponse

        self.calls += 1
        self.thread_ids.append(threading.get_ident())
        self.last_usage = TokenUsage(input_tokens=10, output_tokens=5)
        value = proposal()
        if self.wrong_first and self.calls == 1:
            value = value.model_copy(update={"answer_expression": "a - b"})
        if not issubclass(request.response_model, PlannedGenerationResponse):
            return request.response_model.model_validate(value.model_dump())
        return PlannedGenerationResponse(
            proposal=value,
            checks=[
                {"name": "code_validate_answers_and_distractors", "arguments": {}},
                {"name": "code_verify_template_structure", "arguments": {}},
            ],
        )

    def close(self):
        self.closed = True


class AdditionExecutor:
    def execute_batch(self, code, entry_function, inputs, *, timeout_seconds):
        from edcraft_validator.tools.python_execution import ExecutionResult

        return [
            ExecutionResult(ok=True, answer=item["a"] + item["b"]) for item in inputs
        ]
