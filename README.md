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
checker's level definitions without extra worked examples. Every revision returns
one complete proposal, including unchanged fields. The model may replace code,
wording, parameters, answer and distractors coherently; the application rechecks
the entire replacement under the original request and frozen check plan. Requested
difficulty and distractor count remain application-owned. Free-text requirements
still need review; sampled checks do not establish complete request compliance.
Author generation/revision calls allow one additional
attempt for connection failures or transient HTTP errors; invalid content and
timeouts are not retried. Difficulty checks remain single-pass. All providers receive
check plans constrained to the catalogue, with typed model-owned arguments. The
application freezes the plan and executes it directly through MCP, without native
tool requests or a final acknowledgement call.

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

Ollama thinking defaults to off so its output budget goes to proposals and
revisions. Set `OLLAMA_THINK=true` to enable it, `default` to use the model's setting,
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
300 seconds. The generation/revision output budget is 16384 tokens; adjust
`SOCLAAS_GENERATION_MAX_TOKENS` as needed. This budget covers reasoning and the final
response. `SOCLAAS_TOOL_MAX_TOKENS` remains available for optional native-tool API
users but is unused by template authoring. The application runs every selected
ordinary check once per candidate, validates owned arguments and evidence, and
collects results before requesting a revision. The initial plan includes a nonempty
`required` feature list when `code_require_features` is selected; other code checks
use empty model-owned arguments.
The template difficulty check runs after correctness passes, using the selected
distractors and declared parameter distribution. The configured judge model first
classifies the typical instance with reasoning disabled, then reasons only when
the decision confidence is below 0.70 or the decision fails. Accepted decision
mismatches request author revision. Reasoning mismatches use the existing 0.80
self-confidence policy; see [difficulty checking](docs/difficulty-judging.md).
Configure the shared judge independently of the authoring model.

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
the configured difficulty check compares that label with an advisory estimate for a
typical instance; it does not establish measured learner difficulty.

The explicitly invoked [`assess_code_difficulty` MCP tool](docs/difficulty-judging.md)
adds a separate provisional LLM assessment of a complete concrete MCQ. It records
one closest difficulty label, reasons, model usage and comparison in a single
assessment call. Failed checks return errors without correction or reassessment.
The standalone tool is retained for evaluations and the older concrete-question
helper; normal reusable-template authoring uses `code_assess_template_difficulty`.

Difficulty authoring and relevance share one configured judge model:

```env
EDCRAFT_JUDGE_PROVIDER=soclaas
EDCRAFT_JUDGE_MODEL=x-test-3
EDCRAFT_JUDGE_REASONING_EFFORT=medium
EDCRAFT_RELEVANCE_THRESHOLD=0.9223792980579683
```

These settings are independent of the authoring provider/model. The old
`EDCRAFT_DIFFICULTY_PROVIDER` and `EDCRAFT_DIFFICULTY_MODEL` settings are replaced
by `EDCRAFT_JUDGE_PROVIDER` and `EDCRAFT_JUDGE_MODEL`. Selection uses the existing
provider registry. Forced decisions require an endpoint that supports first-token
log probabilities and disabling reasoning (implemented by the OpenAI-compatible
adapters); unsupported relevance configurations return an error, not a guess.

The template difficulty check first requests only `easy`, `medium` or `hard`,
with reasoning disabled. It accepts the label when normalized first-token class
mass is at least 0.70; a mismatch requests author revision. Lower confidence,
invalid decisions or unavailable probability data invoke the **same model** once
with reasoning enabled and the full structured rubric. Reasoning mismatches use
the existing 0.80 self-reported-confidence revision policy. Both confidence measures
are provisional and uncalibrated. The complete cascade shares the existing judge
deadline, retains both call records and runs only after correctness checks pass.
No model calls are added to deterministic template expansion.

`assess_relevance` uses the same configured model with reasoning disabled and a
forced yes/no response. It reports advisory `decision.relevant`, normalized
`decision.score`, the effective threshold, served model, usage and latency.
Errors produce no decision. It does not invoke the difficulty reasoning fallback.
The default cutoff was fitted on development pairs for `x-test-3`; changing the
model requires checking/recalibrating that cutoff. It is not a calibrated
probability of educational alignment. Inputs go to the configured model endpoint.

The local `QwenDecisionProvider` remains available explicitly for reproducing
older evaluations, with its original cutoff and optional `relevance` dependencies;
it is no longer the server default. Relevance reports retain their v2 interface
with additional usage metadata. The same-model template cascade is a new
production policy: the earlier cascade evaluation used concrete questions and a
different reasoning model, so its accuracy is not evidence for this configuration.

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
