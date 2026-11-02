# EdCraft AI Question Templates

EdCraft authors reusable Python MCQ templates, checks sampled variants with
Hypothesis and execution tools, then expands saved templates locally using seeds.
Checks are sampled evidence, not a correctness proof. Generated questions require
human review. Model assessments provide evidence; they do not imply human approval.

## Setup

Python 3.12 or newer is required.

```bash
uv sync --locked
cp .env.example .env
```

Configure authoring credentials for OpenAI, SocLaas or Ollama in `.env`. Select the
authoring provider with `--provider`; `--model` overrides its configured default.
SocLaas uses `SOCLAAS_API_KEY` and `SOCLAAS_BASE_URL`; its structured output defaults
to strict JSON schema. Ollama must be running locally; thinking defaults to off.
See [.env.example](.env.example) for transport settings and output budgets.

For your own OpenAI-compatible endpoint, select `--provider openai` and configure
`OPENAI_BASE_URL`, `OPENAI_API_KEY` and `OPENAI_MODEL`. Set
`OPENAI_RESPONSE_FORMAT=json_object` if it lacks strict JSON schema support;
responses still undergo local schema validation. Token budgets and reasoning
effort are optional settings in `.env.example`, subject to endpoint support.

Difficulty decisions, reasoning fallback and relevance share one judge model,
independently of the authoring model:

```env
EDCRAFT_JUDGE_PROVIDER=soclaas
EDCRAFT_JUDGE_MODEL=x-test-3
EDCRAFT_JUDGE_REASONING_EFFORT=medium
EDCRAFT_RELEVANCE_THRESHOLD=0.9223792980579683
```

These replace `EDCRAFT_DIFFICULTY_PROVIDER` and `EDCRAFT_DIFFICULTY_MODEL`.
Forced decisions need token log probabilities and a model that supports disabling
reasoning. The relevance cutoff was fitted for `x-test-3`; check/recalibrate it when
changing models. Inputs go to the configured endpoint. Confidence is uncalibrated.

## Author, review and reuse

```bash
uv run python -m edcraft_validator.cli author --domain code --provider openai \
  --prompt 'Create a Python question about adding integers' --difficulty easy \
  --output .artifacts/authoring.json --template-output .artifacts/template.json

uv run python -m edcraft_validator.cli generate --domain code \
  .artifacts/template.json --seed 42 --output .artifacts/question.json
```

Authoring permits an initial proposal plus three complete revisions. The model
selects checks once from the domain catalogue; their names and model-owned
arguments stay fixed across revisions. Application-owned inputs cannot be replaced
by model arguments. Every replacement is rebuilt and checked again. Unsupported
Python, malformed responses and incomplete checks cannot become technical passes.

The selected difficulty check runs after correctness checks pass. It first returns
only a level. A decision at confidence >=0.70 is accepted; otherwise the same model
runs one structured reasoning assessment. Accepted mismatches request revision.
Reasoning mismatches use the existing 0.80 self-confidence policy.

Authoring also selects `code_assess_template_relevance`. It compares the original
author prompt with the correctness-checked template using the same judge model,
with reasoning disabled. An irrelevant decision fails the check and triggers a
revision under the unchanged request and check plan. Both assessments run after
correctness checks and independently of each other's verdicts. A relevance model
or configuration error stops checking without spending author revisions; an
unresolved mismatch exhausts the existing revision limit and produces no reusable
artifact. Score, threshold, provider and input/template identities are saved with
the evidence. The standalone `assess_relevance` tool remains advisory for research;
the concrete-question pilot does not establish accuracy on reusable templates.

Inspect the report's `status`, `fixed_plan`, `attempts`, `warnings` and `artifact`.
`checked` means the selected checking policy passed; it does not mean human
approval. `needs_review` and `error` do not produce an ordinary reusable artifact.
Inspect requested and estimated difficulty separately.

The application supports authoring and generation. To change a template, author it
again with the revised request so the result passes the complete checking loop.
The standalone `validate` command has been retired; individual MCP checks remain
independently callable for research and diagnostics.

Save the complete returned artifact. The old exhaustive artifact format is
unsupported. The same artifact and seed reproduce the same draft without model,
MCP or per-instance Python execution calls. Expansion uses bounded local recipe
checks and may reject a seed if usable options cannot be produced.

## Integration and development

The library/CLI authoring flow is not yet connected to the product's HTTP routes
or authoring/approval screens. The typed worker boundary and progress events are
ready for that integration; see [development](docs/development.md).

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

Default tests use scripted providers. Live tests are opt-in; run the OpenAI
workflow smoke before a PR. See [evaluation](docs/evaluation.md) for commands.

- [Development](docs/development.md): responsibilities, contracts and extension points.
- [Evaluation](docs/evaluation.md): reproducible runs and interpretation limits.
- [Production rubric](docs/difficulty-rubric.md): runtime v0.2 assessment resource.
- [Offline rubric](docs/difficulty-rubric-v0.3.md): distinct v0.3 research reference.
- [Reference set](reference_sets/python_tracing/README.md): dataset provenance.
- [Historical evidence](docs/evaluation-history.md): results for recorded revisions.

GitHub issues and milestones are the planning source of truth. Update these guides
when behavior or setup changes; keep routine change descriptions and test results
in PRs instead of creating a Markdown note for every change.
