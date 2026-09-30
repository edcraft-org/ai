"""Small real-provider authoring exercise; saves full evidence, never credentials."""

import argparse
import json
import time
from pathlib import Path

from dotenv import load_dotenv

from edcraft_validator.application.template_workflow import TemplateApplication
from edcraft_validator.domains.code.code_domain import CodeDomain
from edcraft_validator.domains.code.code_schemas import CodeTemplateRequest
from edcraft_validator.llm.llm_contracts import TemplateProviderSelection
from edcraft_validator.llm.provider_registry import create_model_provider


class ObservedProvider:
    """Count model calls; optionally corrupt the first answer for a drill."""

    def __init__(self, provider, inject_failure):
        self.delegate = provider
        self.provider = provider.provider
        self.model = provider.model
        self.inject_failure = inject_failure
        self.generation_calls = 0
        self.tool_turns = 0
        self.original_proposal = None

    def generate(self, request):
        self.generation_calls += 1
        response = self.delegate.generate(request)
        if self.inject_failure and self.generation_calls == 1:
            self.original_proposal = response.proposal.model_dump(mode="json")
            response = response.model_copy(
                update={
                    "proposal": response.proposal.model_copy(
                        update={
                            "answer_expression": (
                                f"({response.proposal.answer_expression}) + 1"
                            )
                        }
                    )
                }
            )
        return response

    def tool_turn(self, messages, tools):
        self.tool_turns += 1
        return self.delegate.tool_turn(messages, tools)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--provider", default="openai")
    parser.add_argument("--model")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--correction-drill", action="store_true")
    args = parser.parse_args()
    if args.env_file:
        load_dotenv(args.env_file)
    prompts = [
        (
            "beginner",
            "Create a Python MCQ about adding two integers. "
            "Use two finite integer parameters.",
        ),
        (
            "intermediate",
            "Create a Python MCQ about accumulating a total in a for loop. "
            "Use finite integer parameters and ask for the return value.",
        ),
        (
            "advanced",
            "Create a Python MCQ about a helper function called inside a loop. "
            "Use finite integer parameters and ask for the return value.",
        ),
    ]
    if args.correction_drill:
        prompts = prompts[:1]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w") as output:
        for difficulty, prompt in prompts:
            provider = ObservedProvider(
                create_model_provider(
                    TemplateProviderSelection(provider=args.provider, model=args.model)
                ),
                args.correction_drill,
            )
            request = CodeTemplateRequest(prompt=prompt, difficulty=difficulty)
            started = time.perf_counter()
            record = {
                "provider": provider.provider,
                "model": provider.model,
                "request": request.model_dump(mode="json"),
                "controlled_failure_injection": args.correction_drill,
            }
            print(
                f"Starting {provider.provider}/{provider.model}: {difficulty}",
                flush=True,
            )
            try:
                result = TemplateApplication().author_template(
                    request, domain=CodeDomain(), provider=provider
                )
                record["result"] = result.model_dump(mode="json")
                if result.artifact:
                    app = TemplateApplication()
                    preview = app.generate_question(
                        result.artifact, domain=CodeDomain(), seed=42
                    )
                    assert preview == app.generate_question(
                        result.artifact, domain=CodeDomain(), seed=42
                    )
                    record["preview_seed_42"] = preview.model_dump(mode="json")
            except Exception as exc:
                record["error"] = f"{type(exc).__name__}: {exc}"
            record.update(
                duration_seconds=round(time.perf_counter() - started, 3),
                generation_calls=provider.generation_calls,
                tool_turns=provider.tool_turns,
                original_model_proposal=provider.original_proposal,
            )
            print(json.dumps(record), file=output, flush=True)
            result = record.get("result", {})
            print(
                json.dumps(
                    {
                        "difficulty": difficulty,
                        "status": result.get("status", "error"),
                        "attempts": len(result.get("attempts", [])),
                        "seconds": record["duration_seconds"],
                        "reason": result.get("reason", record.get("error")),
                    }
                ),
                flush=True,
            )


if __name__ == "__main__":
    main()
