# Evaluation results

The issue 40 baseline below uses the current model-selected checking workflow.
Earlier milestones and provider experiments are historical context and should
not be treated as its current pass rates.

Historical records may use `beginner`, `intermediate`, and `advanced`. The current
labels are `easy`, `medium`, and `hard`.

## Issue 40 baseline: 10 October 2026

The five natural jobs used `authoring-baseline-v1` with OpenAI `gpt-5-mini`.
Settings were strict JSON schema generation, provider-default sampling and
reasoning, a 120-second request timeout, zero SDK retries, and batched native
tool calls (`tool_choice=required`, `parallel_tool_calls=true`). No output-token
limit was supplied by the OpenAI adapter. The run did not inject failures.

The evaluated code is the uncommitted `codex/issue-40` worktree based on commit
`ee2a0442e0942e88a18f838b10fc8f26983af359`. Its source fingerprint covers all
`src/**/*.py` files and `scripts/evaluate_authoring_loop.py`:

```text
7855cb6bfcb9d559ab277d61e960fb6b46fe0f490c2fda6ceafec34ce429ba47
```

| Case | Requested difficulty | Outcome | Checking attempts | Job latency |
| --- | --- | --- | --- | --- |
| Addition | easy | checked | 1 | 19.603 s |
| Conditional | easy | checked | 2 | 43.278 s |
| Accumulation | medium | checked | 2 | 52.375 s |
| List-sum | medium | checked | 1 | 32.356 s |
| Helper-in-loop | hard | checked | 2 | 55.271 s |

All five requested jobs were recorded and checked; none failed or remained
unresolved. Two passed on the first attempt, and all three correction-eligible
jobs passed after revision. The run made 23 application model calls, reporting
63,091 input tokens and 33,164 output tokens, including checking, revision and
acknowledgement calls. No call lacked usage metadata or reported an
acknowledgement error. Median job latency was 43.278 seconds.

The conditional repair removed distractor collisions without changing the code.
Accumulation initially failed distractor selection and a model-imposed conditional
requirement; its repair added an unrequested conditional. The helper case initially
used an unsupported nested helper. All three checks rejected it, and the model
revised it to a top-level helper. These repaired findings are retained separately
from terminal failure counts.

The five stored templates reproduced all 15 previews at seeds 0, 1 and 42.
Independent verification forbade OpenAI/Ollama generation and tool turns, and
MCP connection, discovery and dispatch. It also confirmed that the manifest
matches the final source fingerprint and that summary usage equals the saved
application call records. Focused reporting regressions passed. The full suite
had 414 tests passed and two opt-in live tests skipped; lint, formatting and diff
whitespace checks passed.
Before PR submission, the separate live OpenAI author/edit/revalidate/replay
smoke test also passed (one test).

Local evidence remains under ignored `.artifacts/`: the
`issue40-final-openai-20261010` JSONL, manifest, summary and verification files,
with catalogues, templates and previews in the directory of the same name.
Generated templates and raw evaluation records are not committed. Earlier
SocLaas comparisons and seeded repair trials remain separate from this baseline.

Five jobs do not establish general reliability. Technical passes establish the
checked finite input domain and reusable output, not pedagogical quality or
difficulty calibration. The unrequested accumulation conditional remains a
quality limitation. Unsupported natural-language requests are deferred until
concrete cases arise; the nested-helper rejection above is an observed code
support boundary.

## Original code-template milestone

By 9 September 2026, the original milestone had:

- 15 topic/difficulty fixtures with positive and negative tests.
- Exhaustive checking of up to 64 inputs in one Python execution batch.
- Saved templates generating seeded questions without further AI or tracing calls.
- OpenAI and Ollama adapters using shared template types.
- Evaluation records containing requests, settings, outcomes, and timings.

Real OpenAI runs produced valid templates for every profile while the profile
contracts were being refined. This was development evidence, not a frozen benchmark.

## Ollama prompt experiments

The following runs used `qwen2.5-coder:14b`:

| Prompt/run | Result | Latency | Main finding |
| --- | --- | --- | --- |
| v8, before profile relaxation | 10/15 validated (66.7%) | Mean 44.1 s; range 26.2–63.8 s | Five proposals failed schema, safety, answer-kind, or answer checks. No timeout or transport failures. |
| v9, 25 September 2026, arithmetic/easy | 0/6 validated | Mean 45.8 s; range 35.3–59.8 s | Question wording did not name the selected entry function. |
| v10, temperature 0 | 1/1 validated | 36.6 s | An explicit wording example helped the model satisfy that requirement. |
| v10, temperature 0.2 | 6/6 validated | Mean 39.9 s; range 29.8–49.9 s | The additional runs also satisfied the requirement. |

The v9 runs used Ollama 0.33.0 and failed with `QUESTION_TEMPLATE_INVALID` during
`template_structure`. The v10 prompt added an example requiring the exact
entry-function name in the question. The validator and proposal schema stayed the
same between these v9 and v10 runs.

The v8 fixtures later allowed a broader set of valid proposals, so new runs are
needed for a fair comparison. Small prompt experiments also do not establish general
model reliability. Use observed failures to improve prompts and models while
preserving the correctness checks.
