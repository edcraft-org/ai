# Evaluation results

The issue 40 baseline below uses the current model-selected checking workflow.
Earlier milestones and provider experiments are historical context and should
not be treated as its current pass rates.

Historical records may use `beginner`, `intermediate`, and `advanced`. The current
labels are `easy`, `medium`, and `hard`.

## Confidence-free generation and correction: 15 October 2026

The runtime difficulty assessment no longer contains a confidence field.
Unresolved estimates and alternatives retain explicit uncertainty. Historical
human-review confidence and comparisons are unchanged. The separate authoring
operation generates a complete MCQ, calls the difficulty MCP tool, and makes one
correction on `too_easy`, `too_hard` or `uncertain`, then reassesses the revised
question under the unchanged request. Errors remain errors and do not trigger a
fabricated correction. The tool itself neither generates nor repairs questions.

The experiment used two fresh briefs per provider: medium conditional accumulation
and hard list/helper processing with interacting state. Author and judge used the
same configured provider/model in separate conversations. No reference questions
were used and generated code was not executed. This is an integration experiment,
not an independent judge evaluation or provider ranking.

Final runtime revision: `671d1de656a36b6fb0a017687275ed7f9a25505a`.
The final source fingerprint is
`a15ab39e99256af4de1b47aa07de9541dd9bc4da9a227c8b43f235f421991480`.
The judge prompt is `code-difficulty-v4` and the author prompt is
`concrete-question-difficulty-authoring-v2`.

| Provider/model | Target | Initial assessment | Correction and reassessment |
| --- | --- | --- | --- |
| OpenAI / `gpt-5-mini` | medium | medium with easy alternative: uncertain | Question changed; still medium with easy alternative: uncertain |
| OpenAI / `gpt-5-mini` | hard | medium with easy/hard alternatives: uncertain | Question changed; hard with medium alternative: uncertain |
| SocLaas / `default` | medium | Question generated; judge transport error | No assessed level, so no correction |
| SocLaas / `default` | hard | Author response failed schema validation | No accepted question or assessment |
| Ollama / `tobestyledintro/qwen3.8-9b-distill:latest` | medium | medium: matches | No correction needed |
| Ollama / `tobestyledintro/qwen3.8-9b-distill:latest` | hard | medium: too easy | Correction returned the identical MCQ; still medium: too easy |

The preliminary configuration is also retained. OpenAI's preliminary author
requests failed before a question was accepted, and Ollama was initially not
running. The follow-up used a closed named-input authoring schema for OpenAI and
an explicit 16,384-token context for the installed local Ollama model. No model
was downloaded. The temporary local server was stopped after the experiment.
SocLaas's preliminary medium case produced an easy estimate, a correction, then a
medium estimate with an easy alternative (`uncertain`); its preliminary hard judge
response failed schema validation. These outcomes are retained separately rather
than replacing later failures with successful earlier calls. The SocLaas `default`
alias does not establish the backend model's identity.

The [summary](evidence/difficulty-correction-2026-10-15/summary.json) links exact
byte-preserved [preliminary records](evidence/difficulty-correction-2026-10-15/initial-v1.json)
and [final records](evidence/difficulty-correction-2026-10-15/final-v2.json).
Every accepted initial/corrected MCQ and complete tool result is retained with
hashes, requested levels, model/settings, timings, usage and failures. OpenAI's
corrections and the preliminary SocLaas correction changed the question hashes.
Ollama returned an unchanged question on its correction attempt; that failure to
revise is recorded explicitly rather than counted as an improvement.
The final six cases contain one confirmed match, two uncertain outcomes, one
remaining mismatch and two errors; none establishes technical correctness.

Offline verification: 519 tests passed, five opt-in live tests skipped. Focused
tests cover both mismatch directions, uncertainty, the one-correction bound,
failed generation/correction/judging, frozen requested levels, closed authoring
schemas, and effective Ollama context settings. Lint, formatting, lockfile and
diff checks passed; a wheel contained the correction workflow and exact rubric.

## Issue 43 difficulty-tool live smoke: 15 October 2026

The [advisory difficulty tool](difficulty-judging.md) was exercised through the
full discovered MCP catalogue using OpenAI `gpt-5-mini`. Two worked-rubric MCQs
asked for difficulty assessment without naming a tool; a correctness-only
template request served as a control. The selector supplied tool arguments,
the selected calls ran through MCP, and the selector consumed their results for
a final summary. No reserved reference questions were used.

The final `code-difficulty-v3` run passed all three smoke tests:

| Request | Model-selected tool | Outcome | End-to-end time |
| --- | --- | --- | --- |
| Arithmetic MCQ, requested hard | `assess_code_difficulty` | Assessed easy; `too_easy` | 27.18 s |
| Conditional accumulation MCQ, requested easy | `assess_code_difficulty` | Assessed medium; `too_hard` | 24.87 s |
| Answer/distractor correctness only | `code_validate_answers_and_distractors` | Technical check passed; no difficulty call | 11.66 s |

The initial v2 run selected the intended tools in all three cases, but its
conditional-accumulation judge response failed local schema validation. The
service returned `JUDGE_SCHEMA_VALIDATION`, retained reported tokens and timing,
and produced no match decision. The precise validation finding was not retained
in that initial implementation. The follow-up added field-level diagnostics that
exclude response values and made the existing uncertainty/alternative constraints
explicit in the response schema descriptions and prompt. Validation rules were
not relaxed, and production did not retry or substitute a judgment. The original
failure and the separate final run are both retained in the
[machine-readable evidence](evidence/difficulty-tool-live-2026-10-15.json).

Both runs used strict JSON schema generation, provider-default sampling, a
120-second provider timeout, zero SDK retries, and a 120-second judge deadline
in the test host. Selector turns used `tool_choice=required` and
`parallel_tool_calls=true`. Therefore this tests selection among tools and
successful dispatch, not whether a model spontaneously decides to use tools.
The ordinary authoring workflow still exposes only its correctness tools.

The evidence records the final source fingerprint, exact tool names, model and
settings, rubric/prompt/request hashes, usage including failed calls, timings,
assessment reasons and final summaries. Full local transcripts remain under
ignored `.artifacts/difficulty-live/`. These tiny worked-anchor smoke tests are
not held-out agreement measurements or learner calibration. Issue 43's empirical
reference evaluation remains pending completion/freezing of the human references.

Final offline verification: 506 tests passed, five opt-in live tests skipped;
the three new live smoke tests passed separately. Lint, formatting, lockfile and
diff checks passed, and a wheel build verified the bundled rubric against its
source bytes. The separate original live authoring/provider tests were not rerun
in this smoke experiment.

## Issue 41 rubric verification: 14 October 2026

The [difficulty rubric](difficulty-rubric.md) defines `python-tracing-v0.2`,
assessment conditions `manual-tracing-v0.1`, and agreement protocol
`python-tracing-agreement-v0.2`. This revision centres on matching the generated
question to the requested difficulty under manual-tracing conditions, replacing
the fixed introductory-Python audience framing. The four dimensions and worked
anchors remain. The rubric content SHA256 is:

```text
f6db392f32c41566d3f0520d6734a80745ccff15350a50afa638fb22e3f66e8f
```

Focused verification extracted the three Python anchors from the Markdown and
ran the application's subset checker and isolated execution tracer. The answers
were 10, 4, and 18; each matched the stated correct option and all options were
distinct. Nine executable error-rule variants reproduced all stated distractors.
The tracer confirmed four iterations for conditional accumulation and nine total
iterations across four loop invocations for nested accumulation. At `n = 0`, the
nested example and its three error-rule variants returned 0, confirming the
documented collision boundary. Local details are saved under ignored
`.artifacts/issue41-rubric-verification.json`.

All nine entries in the documented level-comparison table were checked against
`easy < medium < hard`: three matches, three too-easy results, and three too-hard
results. The review also checked that null estimates, low confidence, and
outcome-changing alternatives retain uncertainty, and technical failures remain
ineligible. This verifies the documented policy, not an implemented comparator.

The existing offline suite passed with 414 tests and two opt-in live tests skipped;
lint, formatting, lockfile, and diff whitespace checks passed. After explicit
authorization, the separate live OpenAI author/edit/revalidate/replay smoke test
also passed (one test). The live smoke test verifies the provider workflow, not
educational difficulty.

These results verify executable examples and existing technical behavior. The
anchor levels are rubric design judgments, not independent human labels. Human
agreement, held-out LLM agreement, and learner calibration have not been measured.
The reference set and judge remain issues 42 and 43 work.

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
