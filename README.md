# EdCraft AI Question Templates

EdCraft uses AI to create a reusable Python multiple-choice question template.
It checks every allowed input combination, then generates questions locally.
The same saved template and seed produce the same question without another AI call.

## What works now

You can request a template using a free-form prompt and an `easy`, `medium`, or
`hard` difficulty. The model chooses checks, receives their results, and revises
failed templates. It gets three total attempts: the first proposal and up to two
revisions.

You can also edit a template candidate, check it again, and generate questions from
the saved result. This works through the library and command line. The new AI
workflow is not yet connected to the product's editing and approval screens.

The next step is workflow evaluation in [issue 40](https://github.com/edcraft-org/ai/issues/40).
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
model. OpenAI and Ollama are the active providers; the SocLaas adapter is available
but currently unused.

## Create a template

```bash
uv run python -m edcraft_validator.cli author \
  --domain code --provider openai --model gpt-5-mini \
  --prompt "Create a question about adding and subtracting integers." \
  --difficulty easy --num-distractors 3 \
  --output /tmp/authoring-result.json
```

The output contains the latest proposal, the checks and results from each attempt,
and a reusable `artifact` if checking succeeded. Here, an artifact means the saved
checked template together with its answers and checking record.

| Status | Meaning |
| --- | --- |
| `checked` | A reusable artifact is available. |
| `needs_review` | Checking failed or required answer data is missing. |
| `error` | The workflow could not finish. |

`checked` means the technical checks passed. Human approval is a later workflow step.
The command exits with 0 for success, 2 for an unsuccessful recorded result, or 1
for an initial input, configuration, or generation failure.

Save the artifact separately for question generation:

```bash
jq -e '.artifact // error("No reusable artifact")' /tmp/authoring-result.json \
  > /tmp/reusable-template.json
```

You can use Ollama by changing the provider and model. You can also supply request
fields through `--request-json examples/code-request.json` instead of `--prompt`,
`--difficulty`, and `--num-distractors`. The default distractor count is three;
two is also supported.

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
  /tmp/candidate.json --output /tmp/check-result.json
jq -e '.artifact // error("No reusable artifact")' /tmp/check-result.json \
  > /tmp/reusable-template.json
```

`validate` checks the supplied candidate once. It does not rewrite it. If you change
code or parameter values, update the answer and distractor expressions as needed.
Generate questions from the new artifact after checking succeeds.

## Supported questions

- Python execution questions about return values, branches, loops, and function calls.
- Basic expressions, assignments, `if`, bounded `for` loops, helper functions, and
  recursion that completes within the execution limits for every allowed input.
- One to three parameters containing finite sets of integers, booleans, strings,
  or integer lists. Each parameter has two to four values, with at most 64 total
  combinations.
- Two or three wrong-answer options, distinct from the correct answer and each other
  across every allowed input combination.

Imports, file access, networking, and other unsupported Python features
are rejected. Difficulty is currently the requested label; technical checking does
not measure educational difficulty or question quality.

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
- [Developer reference](docs/development.md)
- [Earlier evaluation results](docs/evaluation-history.md)
