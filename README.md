# EdCraft AI Question Templates

EdCraft uses AI to create a reusable Python multiple-choice question template.
It checks sampled variants with Hypothesis, then generates draft questions locally.
Generated questions require manual review; sampled checks are not a correctness proof.
The same saved template and seed produce the same question without another AI call.

## What works now

You can request a template using a free-form prompt and an `easy`, `medium`, or
`hard` difficulty. The model chooses checks, receives their results, and revises
failed templates. It gets four total attempts: the first proposal and up to three
revisions.

Code proposals use an array of indented Python lines in model responses, then
normalize to ordinary source text for checking and reuse. Authors receive the
checker's level definitions without extra worked examples. When only distractors
fail, revisions contain recipes and parameter values; the application preserves
the program, question wording and function interface. Difficulty mismatches allow
a coherent full revision. Author generation/revision calls allow one additional
attempt for connection failures or transient HTTP errors; invalid content and
timeouts are not retried. Difficulty checks remain single-pass. OpenAI/SocLaas check plans constrain names
to the available catalogue instead of allowing invented names.

You can also edit a template candidate, check it again, and generate questions from
the saved result. This works through the library and command line. The new AI
workflow is not yet connected to the product's editing and approval screens.

The focused workflow baseline for [issue 40](https://github.com/edcraft-org/ai/issues/40)
is recorded in the [evaluation results](docs/evaluation-history.md#issue-40-baseline-10-october-2026).
Difficulty calibration and question quality follow in Milestone 3; the user review
and approval workflow follows in Milestone 4.

## Setup

Use Python 3.12 or newer, then install the dependencies:

```bash
uv sync
cp .env.example .env
```

Edit `.env` for the provider you want to use. For OpenAI, set `OPENAI_API_KEY` and
`OPENAI_MODEL`. For Ollama, run the local server and set `OLLAMA_MODEL`.
The remaining settings are listed in [.env.example](.env.example).

Ollama thinking defaults to off so its output budget goes to proposals and tool
calls. Set `OLLAMA_THINK=true` to enable it, `default` to use the model's setting,
or a supported level such as `low` for models that require a named thinking level.
Enabled thinking may require a larger `OLLAMA_NUM_PREDICT` budget.

Always select a provider with `--provider`. Use `--model` to override its configured
model. OpenAI, Ollama, and SocLaas are available providers. SocLaas uses the
OpenAI-compatible interface with `SOCLAAS_API_KEY`, `SOCLAAS_BASE_URL`, and
`SOCLAAS_MODEL`. SocLaas defaults to GLM5.3 Flash (`x-test-1`); set
`SOCLAAS_MODEL` or pass `--model` to choose another model. The serving alias is
labelled Testing GLM 5.3 Flash in the SoCLaaS catalogue. OpenAI and SocLaas both
default to strict JSON-schema output.
Local schema validation and all template checks still apply.
`SOCLAAS_RESPONSE_FORMAT=json_object` explicitly opts into the weaker JSON mode
for endpoints without strict-schema support; its schema is supplied in the prompt.
`SOCLAAS_REASONING_EFFORT=default` leaves reasoning to the model; an explicit value
such as `none` or `medium` is sent when configured. The default request timeout is
300 seconds. Generation and tool/acknowledgement output budgets are 16384 and 4096
tokens; adjust `SOCLAAS_GENERATION_MAX_TOKENS` and `SOCLAAS_TOOL_MAX_TOKENS` as needed.
These budgets must cover reasoning and the final response.
Every provider is asked to batch the current stage's checks in one native-tool response.
The application executes each returned call, collects its evidence, and requests
only checks still pending if the batch is incomplete. Corrections start after the
stage finishes. Owned arguments and every returned call are validated.
The template difficulty check runs after correctness passes, using the selected
distractors and the declared parameter distribution. SocLaas
estimates the typical instance. A mismatch at confidence 0.80 or higher feeds
back to the authoring model for up to three template revisions; a lower-confidence
mismatch returns a warning with both labels. Confidence is a provisional self-estimate. A failed judge response ends the job without
retrying the check. Configure SocLaas even when OpenAI authors the template.

## Create a template

```bash
uv run python -m edcraft_validator.cli author \
  --domain code --provider openai --model gpt-5-mini \
  --prompt "Create a question about adding and subtracting integers." \
  --difficulty easy --num-distractors 3 \
  --output /tmp/authoring-result.json \
  --template-output /tmp/reusable-template.json
```

One job produces one report, even when it takes four attempts. Each attempt stores
its candidate once, followed by its tool arguments and results. The report also
contains the request, model settings, selected checks, timings, per-call token usage,
model-call count, and a reusable
`artifact` if checking succeeded.

`--template-output` saves that small artifact separately: the template, checked
answers, a short check summary, and origin metadata. It contains no attempt history
or tool schemas. This file is written only when checking succeeds; on failure, any
existing file at that path is left unchanged.

| Status | Meaning |
| --- | --- |
| `checked` | A reusable artifact is available. |
| `needs_review` | Checking failed or required answer data is missing. |
| `error` | The workflow could not finish. |

`checked` means all selected checks passed their policy. Inspect `warnings` and
`difficulty_match`: a low-confidence mismatch can pass with an advisory warning.
A difficulty match is an advisory rubric
estimate, independent of correctness and learner calibration. Inspect `fixed_plan`
to see which checks the model selected. Human approval is a later workflow step.
The command exits with 0 for success, 2 for an unsuccessful recorded result, or 1
for an input or provider-creation failure. Initial generation and MCP setup failures
produce recorded `error` results with available usage and timing.

If you did not use `--template-output`, extract the artifact from the report:

```bash
jq -e '.artifact // error("No reusable artifact")' /tmp/authoring-result.json \
  > /tmp/reusable-template.json
```

You can use Ollama by changing the provider and model. You can also supply request
fields through `--request-json examples/code-request.json` instead of `--prompt`,
`--difficulty`, and `--num-distractors`. The default distractor count is three;
two is also supported.

For diagnostics, add `--tool-schemas /tmp/tool-schemas.json` to save full MCP tool
definitions separately. The normal report lists only tool names, versions and
descriptions. Full schemas are still used when checking tool arguments and results.

Read the report in smaller pieces:

```bash
jq '{status, fixed_plan, reason}' /tmp/authoring-result.json
jq '.attempts[] | {number, passed, candidate}' /tmp/authoring-result.json
jq '.attempts[].executions[] | {tool, error, evidence}' /tmp/authoring-result.json
```

## Generate questions

```bash
uv run python -m edcraft_validator.cli generate \
  --domain code /tmp/reusable-template.json --seed 42
```

Change the seed to select another input combination. Different seeds may select the
same inputs because each template has a finite set of values. Use this command for
previews too. It makes no model, MCP, or Python tracing calls.

## Edit and check a template

Extract the candidate from the authoring result:

```bash
jq -e '.attempts[-1].candidate // error("No candidate")' /tmp/authoring-result.json \
  > /tmp/candidate.json
```

The candidate is the draft template before checking. Edit that file, then check it
again:

```bash
uv run python -m edcraft_validator.cli validate \
  --domain code --provider openai --model gpt-5-mini \
  /tmp/candidate.json --output /tmp/check-result.json \
  --template-output /tmp/reusable-template.json
```

`validate` checks the supplied candidate once. It does not rewrite it. If you change
code or parameter values, update the answer and distractor recipes as needed.
Answer recipes are required and compared with execution on sampled cases.
Generate questions from the new artifact after checking succeeds.

## Supported questions

- Python execution questions about return values, branches, loops, and function calls.
- Basic expressions, assignments, `if`, bounded `for` loops, helper functions, and
  recursion with bounded inputs suitable for manual tracing.
- One to three parameters containing finite sets of integers, booleans, strings,
  or integer lists. Each parameter has two to 32 values; there is no 64-combination
  enumeration limit.
- Two or three wrong-answer options, distinct from the correct answer and each other
  on all checked samples. Generation cheaply evaluates recipes and retries up to
  32 times for option collisions, without executing each generated question.

Template checking uses 32 generated examples by default, plus a few explicit axis
boundaries (including declared zero values). Replay and shrinking share a hard
budget of 128 execution calls and 30 seconds. Configure these through
`PropertyCheckSettings` and `create_validation_server(template_property_settings=...)`.
A failed property requests revision; an exhausted budget returns an error.
The report records actual sample/call counts and limits, not a confidence percentage.

Saved template format 2 stores the tested answer recipe and sampled-check summary,
not a complete answer table. Generated instances set `requires_manual_review=true`.
The old artifact format and exhaustive checker are removed; regenerate saved
artifacts. There is no migration or legacy generation path. The example candidates
already include general recipes and are checked using the new format.

Imports, file access, networking, and other unsupported Python features
are rejected. The template retains its requested difficulty label. When selected,
the SocLaas difficulty check compares that label with an advisory estimate for a
typical instance; it does not establish measured learner difficulty.

The explicitly invoked [`assess_code_difficulty` MCP tool](docs/difficulty-judging.md)
adds a separate provisional LLM assessment of a complete concrete MCQ. It records
one closest difficulty label, reasons, model usage and comparison in a single
assessment call. Failed checks return errors without correction or reassessment.
Difficulty checks use SocLaas only, with no provider fallback.

The explicitly invoked `assess_relevance` MCP tool uses local
`Qwen/Qwen3-Reranker-0.6B` to assess whether a question exercises an author request.
It returns an advisory `decision.relevant`, raw `decision.score`, and threshold
(`0.0020295610011089593`). The score is a yes/no token score, not a calibrated
probability. No embedding API or generated answer is used. Correctness,
requirements and difficulty remain separate checks.

Install the local inference extra and download weights once:

```bash
uv sync --locked --extra relevance
uv run --extra relevance hf download Qwen/Qwen3-Reranker-0.6B
```

Inference reads existing local files and sends no question text outside the
process. Set `EDCRAFT_RELEVANCE_MODEL_PATH` to a downloaded copy of that model,
or leave it unset to use the Hugging Face cache. Weights are loaded lazily once
per process and reused; MPS/CUDA use FP16, with FP32 CPU fallback. Allow roughly
3 GB of memory for the model and inference. Inputs over 4,096 tokens are rejected
rather than truncated. Missing dependencies/weights and inference timeouts return
errors with no relevance decision. The default application deadline is 35 seconds;
a timeout does not stop an already running local inference thread.

This replaces the v1 cosine report: relevance reports/tool definitions are v2,
`similarity` becomes `decision`, and embedding dimensions/usage are removed.
Injected callers now use `decision_provider_factory` and
`relevance_timeout_seconds`. The cutoff comes from a small chemistry pilot;
Python accuracy and combined-request behavior remain unvalidated.

Python callers use `domains/code/relevance.py` to render code, exact inputs,
wording, target and all options while excluding the correct-option designation.
The separate `check_code_question_correctness` and
`check_code_question_requirements` MCP tools provide execution-backed answer
checks and explicit syntax/target/count checks respectively. The evaluation runner
collects these independent results alongside shared relevance evidence for the
12 reserved questions and seven engineering controls. Difficulty judgments remain
separate. See [evaluation and migration](docs/evaluation.md#what-to-report) and the
[project report](docs/edcraft%20logs.docx), Section 6, for the earlier experiments.

## Tests

```bash
uv lock --check
uv sync --locked
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

The default tests use scripted model responses and make no paid API calls. They
exercise the checking loop, failure handling, domain operations, and local tracer.
For live model calls and workflow evaluation, see the [evaluation guide](docs/evaluation.md).

## More information

- [How the workflow works](docs/question-generation/README.md)
- [Goals and milestones](GOALS.md)
- [Evaluation guide](docs/evaluation.md)
- [Provisional Python difficulty rubric](docs/difficulty-rubric.md)
- [Project log, including relevance and embedding model comparison](docs/edcraft%20logs.docx)
- [Frozen Python tracing evaluation dataset](reference_sets/python_tracing/README.md)
- [Developer reference](docs/development.md)
- [Earlier evaluation results](docs/evaluation-history.md)

The current offline difficulty reference is [v0.3](docs/difficulty-rubric-v0.3.md).
See the [GLM/Qwen statistics](docs/difficulty-glm-comparison-v0.3.md).
Production difficulty tools retain their v0.2 contract; the offline rubric is a
separate evaluation.
