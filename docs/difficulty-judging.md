# Advisory difficulty MCP tool

`assess_code_difficulty` estimates the provisional difficulty of one complete,
concrete Python tracing MCQ. It uses the [versioned rubric](difficulty-rubric.md),
including its manual-tracing conditions, semantic prerequisites and worked anchors.
It does not infer a fixed learner cohort or establish learner-calibrated difficulty.

This implements the callable judge portion of issue 43. Evaluation against frozen
human references, held-out agreement/confusion reports and disagreement analysis
remain pending. Existing AI recommendations and scripted test responses are not
evidence of judge accuracy.

## Configure and invoke

Start the existing stdio MCP server with a host-selected provider:

```bash
export EDCRAFT_DIFFICULTY_PROVIDER=openai
# Optional: export EDCRAFT_DIFFICULTY_MODEL=<your model name>
# Supply the provider's existing credentials/settings through the environment.
uv run python -m edcraft_validator.mcp
```

The provider registry supports `openai`, `ollama` and `soclaas`. The model defaults
to that provider's existing configuration when the difficulty-specific model is
omitted. Each invocation constructs a fresh provider. Listing tools and running
ordinary authoring jobs do not create a judge provider or make judge calls.
An unset/invalid provider or missing credentials produces a recorded
`JUDGE_CONFIGURATION_ERROR`.

The MCP input has a `question` object and an optional `requested_difficulty` field.
For example, an in-process caller can use:

```python
import asyncio
import json

from fastmcp import Client
from edcraft_validator.mcp.server import create_validation_server


async def main():
    async with Client(create_validation_server()) as client:
        result = await client.call_tool(
            "assess_code_difficulty",
            {
                "question": {
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
                },
                "requested_difficulty": "easy",
            },
        )
        print(json.dumps(result.structured_content, indent=2))


asyncio.run(main())
```

Supply the actual learner-facing option order: three or four options
labelled A/B/C[/D], with exactly one designated correct option. Answer types are
numbers, booleans, strings or integer lists; nonfinite values are rejected.
The input contract checks field types, option identifiers and required content.
It does not check option distinctness, answer correctness, the Python subset or
execution-specific parameter limits. Code is limited to 20,000 characters and the
stem to 8,000. Do not submit a template or curator difficulty/provenance fields.

All five answer targets are supported. Count conventions follow the execution
worker: evaluated `if` conditions, total loop-body iterations, loop statements
encountered, or traced function calls including entry and supported built-ins.
Stems must state the relevant convention. The judge can record uncertainty about
wording that affects its difficulty estimate.

## Evidence and outcomes

The service evaluates difficulty directly from the supplied MCQ. It has no code
executor, static analyser or correctness prerequisite. The designated correct option
is supplied context, not execution-verified evidence. Correctness tools retain
responsibility for code support, answers and distractor validity. An application
can combine their independent results; a difficulty assessment establishes no
correctness outcome and never replaces one.

The prompt contains the complete supplied MCQ and its answer designation.
It excludes the requested level, template/source IDs, generator identity and
curator recommendations. Code/comments, stem and options are identified as
untrusted data; they are not instructions to the judge. This prompt separation
reduces anchoring/instruction-following risk but does not establish model accuracy.

The judge supplies four dimension ratings with reasons, overall estimated level,
solution/dependency reasoning, shortcuts, nearest anchor, evidence for every
option, confidence, alternatives, uncertainty and quality concerns. Distractor
error explanations are hypotheses, not observed learner misconceptions.

The application then derives `matches`, `too_easy`, `too_hard` or `uncertain` using
the same comparison function as the human-reference workflow. Requested levels
and estimates remain separate. Low confidence, unresolved estimates and
alternatives that change the comparison retain `uncertain`. Without a requested
level, `difficulty_match` is null. Use `easy`/`medium`/`hard` in the API; the rubric
maps these to beginner/intermediate/advanced terminology.

| Report field | Meaning |
| --- | --- |
| `advisory: true` | Quality evidence cannot override correctness or required evidence. |
| `status: assessed` | A valid assessment was produced, including possible uncertainty or mismatch. |
| `status: error` | Rubric/provider configuration, judge timeout, malformed response or another judging error prevented assessment. |
| `judge.status` | `completed` or `error`; a model failure is not a valid uncertain estimate. |

Invalid MCP input is a protocol error. Operational failures return structured
reports with explicit codes and no fallback difficulty or fabricated match.
Reports include UTC time, tool version, normalized question hash, exact rubric
hash/version, assessment conditions version, prompt version and a request/schema
hash. Judge records retain provider/model/settings, latency, token usage and call
errors. Save returned reports alongside their exact source questions when keeping
versioned evaluation records. There is no database or automatic file write.
Schema failures also retain validation field locations, codes and messages while
omitting response values and exception context.

## Integration and deadlines

The tool is tagged `quality:code`, separate from `domain:code` correctness checks.
It is explicitly callable and never enters the existing authoring check plan.
Question expansion remains deterministic and makes no implicit judge calls.

The reusable entry point is
`application.code_difficulty.assess_code_question_difficulty`; the MCP wrapper
adds registration and host-owned provider configuration. The code domain owns
the question/assessment contracts, rubric and prompt. `llm.judging.run_judge`
shares structured-call execution and usage accounting without interpreting a rubric.

An embedding host can inject `difficulty_provider_factory` and set
`difficulty_judge_timeout_seconds` through `create_validation_server`. The factory
must return a fresh provider per call so concurrent usage records stay separate.
The default judge deadline is 60 seconds. Configure provider transport
timeouts/retries consistently with the host deadline. The service makes one judge
application call and does not retry malformed assessments; SDK transport retries
are separately recorded as provider settings.

An outer deadline stops waiting and ignores late synchronous results; it cannot
terminate the provider thread. Its report explicitly records unknown token usage.
Completed calls that fail response parsing still retain provider-reported tokens.
Unavailable token counts are null, never zero-cost claims. Assessing through a
remote provider sends the question to that configured service and may incur cost;
the tool's MCP annotations declare this external interaction and non-determinism.

Assessments apply only to the exact code, input, stem, target and options. Recheck
and reassess edited questions. Sampling questions from a template does not establish
the level of every expansion. For issue 43 evaluation, finish/freeze human
references, tune only on development families, freeze the judge configuration,
then score held-out families under the predeclared agreement protocol.

## Live selection smoke tests

With OpenAI credentials exported, run:

```bash
RUN_OPENAI_LIVE_TESTS=1 OPENAI_MAX_RETRIES=0 \
  uv run pytest tests/test_difficulty_live.py -q
```

These tests offer the model every tool discovered from the MCP server. Two
rubric-example requests ask for difficulty assessment without naming the tool;
a correctness-only control asks for answer/distractor checking. The chosen calls
are dispatched through MCP and their results are returned to the model for a final
summary. Each difficulty call invokes a separate structured judge. Source questions
and supplied answers must remain unchanged in tool arguments.

The existing provider requires a tool call on its tool-selection turn, so these
tests evaluate which tool the model selects and whether the call works. They do
not establish whether the model would spontaneously choose to use tools. The
ordinary authoring workflow continues to expose only correctness tools.

Full local transcripts, results and usage are saved under ignored
`.artifacts/difficulty-live/` (override with `DIFFICULTY_LIVE_OUTPUT`). These are
small smoke tests on worked anchors, not held-out judge-accuracy measurements.
They send the test questions, template, tool schemas and rubric to the configured
provider and incur inference costs.
