# Evaluation results

The issue 40 baseline below uses the current model-selected checking workflow.
Earlier milestones and provider experiments are historical context and should
not be treated as its current pass rates.

Historical records may use `beginner`, `intermediate`, and `advanced`. The current
labels are `easy`, `medium`, and `hard`.

## Shared strict schema: complete workflow and dataset follow-up, 15 October 2026

OpenAI and SocLaas now both default to the shared strict JSON-schema response
path. The former SocLaas JSON-object mode remains an explicit compatibility
opt-in. This follow-up used runtime revision `4b94b53`, the unchanged
`code-difficulty-v4` judge prompt and
`concrete-question-difficulty-authoring-v2` author prompt, rubric
`python-tracing-v0.2`, 240-second provider timeouts, 250-second application
deadlines and zero SDK retries. Cases and provider settings were recorded before
calls. No model-output repairs, replacement judgments or prompt tuning were made.
Provider identity and output budgets remain explicit: OpenAI used `gpt-5-mini`
with its existing uncapped output request; SocLaas used alias `default`, a
16,384-token generation cap and provider-default reasoning. Strict schema output,
prompts, deadlines and retry policy were shared; the provider-specific adapters
were not represented as having identical model settings.

### Generate, assess, revise and reassess

Both providers received three fresh briefs: easy direct arithmetic, medium
conditional accumulation and hard list/helper processing with interacting state.
The medium and hard briefs are retained from the earlier smoke experiment; the
easy brief adds a control. One initial generation and MCP assessment was allowed,
followed by one revision and reassessment for a valid mismatch or uncertain
comparison. Errors remain errors. These are authoring-target comparisons by the
same provider/model in separate conversations, not agreement with human labels.
No reference questions were used in generation and no correctness checks or
code execution were performed.

| Provider | Initial confirmed matches | Revisions attempted | Changed MCQs | Revisions reaching a confirmed match | Final outcomes |
| --- | ---: | ---: | ---: | ---: | --- |
| OpenAI | 1/3 | 2 | 2 | 0/2 | 1 match, 1 uncertain, 1 mismatch |
| SocLaas | 0/3 | 1 | 1 | 0/1 | 3 errors |

OpenAI's easy question matched immediately. Its medium question kept the same
code while revising other question content; both assessments selected medium
with alternatives, so uncertainty remained. Its hard question changed the helper,
state updates and list mutation, but both assessments selected medium, leaving
`too_easy`. Both revisions changed the normalized full-MCQ hash. OpenAI's primary
estimate equalled the target on two of three initial and final questions, but only
one was a confirmed match because of alternatives.

SocLaas's easy generation and its revision each produced a 20,000-character,
one-line function signature, despite a brief asking for a short arithmetic
program. The designated inputs were only x, y and z. The first judge inferred a
likely arithmetic operation from the stem/answer context and rated it medium
with an easy alternative; the supplied code did not show that inferred body.
The revision changed the MCQ but its reassessment failed because the primary
level also appeared in alternative levels. The medium and hard author requests
returned transport errors after about 120 seconds, before an accepted question
existed. The stored generation records identify the failure category and unknown
usage; they do not retain the HTTP status or response body, so the upstream cause
is unresolved. No correction was attempted for those errors.

This exposes a generation-quality failure alongside assessment inconsistency:
strictly shaped JSON still allowed content that did not fulfil the brief.
The pure difficulty tool is advisory and supplies no correctness guarantee.
The generation experiment made 16 application calls across six jobs and nine
generation/revision stages. None of the three revision attempts produced a
confirmed match. OpenAI reported 39,072 input and 32,562 output tokens. SocLaas
reported 40,990 input and 21,324 output tokens for known calls; two transport
failures have unknown usage, so its complete totals are unavailable.

### Repeat the fixed 30-question evaluation

After the generation workflow completed, each provider assessed all 30 unchanged
approved MCQs through MCP, with reference labels, dimensions, solutions, reasons,
IDs, topic and split hidden. The original 18/12 split was retained. This is a
requested configuration follow-up on an already inspected collection, recorded
with `followup_of`; its held-out results are regression evidence rather than fresh
confirmatory validation. The dataset SHA-256 remains
`fe1a31cf08c6c1ec8457336332b0e4fa79f1c1e6422fdab5b0a771a9d7bddd2a`.

| Provider | Primary-label agreement, all items | Jointly labelled agreement | Held out | Confirmed matches | Uncertain comparisons | Failed responses |
| --- | --- | --- | --- | --- | ---: | --- |
| OpenAI | 16/30 (53.3%) | 16/28 | 8/12 (66.7%) | 9/30 | 13 | 2 timeouts |
| SocLaas | 12/30 (40.0%) | 12/19 | 6/12 (50.0%) | 8/30 | 8 | 8 |

SocLaas returned 22 accepted assessments, including three null primary
estimates with explicit uncertainty. It had **zero recurrences of the earlier
non-text-field or missing-required-field errors**. Its eight failures were:

- Three model-level consistency validation failures: two missing a required
  uncertainty reason and one repeating the primary level among alternatives.
- Two option-evidence mismatches: the assessment did not cover the supplied option
  IDs exactly, despite satisfying the global response schema.
- Three timeouts with unknown usage.

These are distinct from the 16 JSON-mode structural schema failures in the
previous run. No runtime consistency guard was weakened or normalized away.
OpenAI's two failures were timeouts. Errors and null estimates remain nonmatches
in the all-items denominator; uncertainty and failures are reported separately.
Neither provider had an easy↔hard disagreement among jointly labelled items.

| Approved level | OpenAI easy / medium / hard | SocLaas easy / medium / hard |
| --- | --- | --- |
| Easy | 10 / 2 / 0 | 9 / 0 / 0 |
| Medium | 6 / 5 / 0 | 6 / 0 / 0 |
| Hard | 0 / 4 / 1 | 0 / 1 / 3 |

The confusion counts exclude failures and null estimates, both retained separately
in the summary. OpenAI dimension matches were 18/28 execution burden, 18/28
changing state, 15/28 conceptual interaction and 24/28 answer discrimination.
SocLaas's were 15/22, 16/22, 13/22 and 10/22. Ordinal alpha was 0.523 over
28 pairs for OpenAI and 0.569 over 19 pairs for SocLaas. The 95% family-bootstrap
primary-agreement intervals were 36.7–73.3% and 20.0–56.7%; held-out intervals
were 41.7–91.7% and 25.0–75.0%. These small-sample intervals do not establish a
provider ranking or learner calibration.

Compared with the previous scheduled run, OpenAI changed from 19/30 to 16/30
primary matches: two previously nonmatching items became matches, while five
previously matching items became nonmatches. SocLaas changed from 11/30 to
12/30: six became matches and five became nonmatches. These are repeat-run
transitions, not review corrections. OpenAI already used strict mode previously;
provider-default sampling, availability and the opaque SocLaas backend alias can
vary. The observed type-error reduction supports using strict output, while the
accuracy results and failed revisions do not demonstrate reliable difficulty
alignment. Reference labels were kept fixed.

The dataset run made 60 application calls. Five timeout records have unknown
usage; known calls reported 332,015 input and 133,049 output tokens. The complete
workflow plus dataset evaluation made 76 calls, with seven having incomplete
usage metadata. Missing counts are not zero-cost claims.

### Evidence and verification

The [workflow records](evidence/strict-difficulty-2026-10-15/workflow-results.json)
retain every accepted initial/revised MCQ and complete tool output. Its
[pre-call manifest](evidence/strict-difficulty-2026-10-15/workflow-manifest.json)
and [summary](evidence/strict-difficulty-2026-10-15/workflow-summary.json) preserve
the fixed briefs, provider settings, revision counts and unresolved outcomes.
The workflow source fingerprint is
`47f777577810178435fd151e5fb8ae696624ac38e783aad5cf0b50237e2cf055`.

The [dataset records](evidence/strict-difficulty-2026-10-15/dataset-results.json),
[manifest](evidence/strict-difficulty-2026-10-15/dataset-manifest.json),
[summary](evidence/strict-difficulty-2026-10-15/dataset-summary.json),
[paired comparison](evidence/strict-difficulty-2026-10-15/comparison.json) and
[verification](evidence/strict-difficulty-2026-10-15/verification.json) preserve
the follow-up separately from the original results. The dataset runner source
fingerprint is `92275bf52b3dd5542cead60ad86ad95361fbd046148a79b70fa0ff50020c7db7`.

Verification: 472 offline tests passed, with five opt-in live tests skipped.
Lint, formatting and diff checks passed. An independent offline audit reproduced
both summaries, all generation/feedback and judge request hashes, exact MCQ and
reference bindings, unchanged dataset bytes, frozen provider settings and one
application call per stage. It checked all six workflow jobs and 60 dataset
records and found no configured API key values in the saved JSON. The tests
specifically verify that both providers default to strict output and that summary
counts retain failed revisions and uncertain primary matches.

## Approved difficulty dataset: 15 October 2026

The frozen issue 42 dataset (`python-tracing-evaluation-2026-10-15`) contains
30 approved questions: 13 easy, 11 medium and six hard, split into 18 development
and 12 held-out items. Its bytes at dataset revision `498f6ff` match the dataset
merged into main by `7df7e77` (PR #83). The dataset SHA-256 is
`fe1a31cf08c6c1ec8457336332b0e4fa79f1c1e6422fdab5b0a771a9d7bddd2a`.
The approved questions, labels, dimension ratings and splits were not edited.

Each question was explicitly assessed through MCP with its reference label,
dimensions, explanation, solution, identity, topic and split withheld. The
supplied answer designation remained visible. The unchanged `code-difficulty-v4`
prompt used rubric `python-tracing-v0.2`, hash
`f6db392f32c41566d3f0520d6734a80745ccff15350a50afa638fb22e3f66e8f`.
One scheduled assessment per item/provider was allowed, with no application or
SDK retries, replacement judgments, generated questions or correctness checks.
Question correction would change the approved test item and was not performed.
Configuration was recorded before the first call; development results did not
change the configuration used for held-out calls.

Protocol `frozen-difficulty-dataset-evaluation-v1` adapts the rubric's v0.2
agreement protocol to the final dataset schema. Primary-label agreement compares
the judge's first estimate with the approved label; failures and null estimates
count as nonmatches over all items. The separate confirmed-match measure applies
the existing comparison rule against the approved level, retaining uncertainty
when alternatives cross its boundary. This is not an original authoring-target
acceptance decision: those targets and human match decisions are absent from the
final dataset. Original-target decision accuracy, false acceptance/rejection and
a four-way decision confusion table are unavailable rather than fabricated.

| Provider/model | All-item label agreement | Development | Held out | Confirmed matches | Uncertain comparisons | Failed assessments |
| --- | --- | --- | --- | --- | --- | --- |
| OpenAI / `gpt-5-mini` | 19/30 (63.3%) | 12/18 | 7/12 (58.3%) | 9/30 | 14 | 0 |
| SocLaas / `default` | 11/30 (36.7%) | 6/18 | 5/12 (41.7%) | 8/30 | 3 | 16 |
| Ollama / installed Qwen distill 9B (six-item subset) | 3/6 (50.0%) | 3/6 | Not run | 3/6 | 0 | 2 |

The user limited Ollama to six questions after the remote passes completed.
Its primary subset is the first six scheduled development items in dataset order,
including both timeouts, covering all five topics: `arithmetic-coupled-arithmetic-01`,
`cruxeval-082`, `lists-adjacent-differences-02`, `cruxeval-274`,
`conditionals-boolean-01` and `functions-single-helper-01`. Four produced valid
assessments: three agreed, and the hard arithmetic question was rated medium.
This convenience subset has no local held-out result and is not comparable to a
full 30-item provider pass. Its 95% primary-agreement bootstrap interval is broad
(see summary). Alpha is 0.900 over only four paired items and does not establish
reliable alignment. Dimension matches are 3/4, 3/4, 3/4 and 4/4 respectively.

A seventh local result (`cruxeval-506`) completed before the user's limit arrived;
it is retained as supplemental evidence and excluded from every primary score.
The next call (`cruxeval-253`) was interrupted without an accepted tool report;
its usage is unknown. The remaining 22 local questions were not dispatched.
The evaluation process and temporary local server were stopped. These untested
items are not model failures and are not added to the six-item denominator.
The original pre-call manifest remains intact; the separate completion audit
records the changed scope, supplemental result and interrupted call.

OpenAI's all-item confusion counts (rows approved, columns judge) are:

| Approved level | Easy | Medium | Hard |
| --- | ---: | ---: | ---: |
| Easy | 12 | 1 | 0 |
| Medium | 6 | 5 | 0 |
| Hard | 0 | 4 | 2 |

OpenAI underestimated ten questions and overestimated one. All three held-out
hard questions were rated medium. The six-round coupled arithmetic development
question was rated medium despite the approved hard label: the judge called its
repeated tuple/modular updates a straightforward short trace. Conversely,
`cruxeval-082` was rated medium instead of easy because the judge treated Python
short-circuit semantics as unfamiliar, although the assessment conditions assume
that the semantics are understood. Ten of the 19 correct primary estimates still
had boundary-crossing alternatives, reducing confirmed matches to nine.

SocLaas produced 14 valid assessments, of which 11 matched (78.6%); this conditional
rate must not replace the 11/30 overall score. Fifteen failures included a non-text
`concepts_and_dependencies` value; one response omitted required fields. One
failing response also exceeded the option-evidence length constraint. Raw invalid
values are intentionally omitted; the diagnostics retain field locations and
validation codes. The valid SocLaas confusion counts are easy→easy 5,
medium→easy 3, medium→medium 2 and hard→hard 4; the other 16 responses are errors,
not additional rows of a difficulty category. Neither remote provider had an
easy↔hard disagreement among valid estimates.

OpenAI's dimension matches were execution burden 17/30, changing state 20/30,
conceptual interaction 16/30 and answer discrimination 24/30. SocLaas's were
10/14, 11/14, 7/14 and 4/14 respectively, over its valid jointly rated questions.
Two-rater ordinal alpha was 0.627 for OpenAI (30 paired items) and 0.816 for
SocLaas (14 paired items). Alpha and valid-response rates must be read alongside
failures and category support, not as a provider ranking.

The summary includes 95% whole-family percentile bootstrap intervals using
2,000 replicates and seed 43. The final collection has one item per code family;
question IDs identify those families. OpenAI's all-item agreement interval is
43.3–80.0%; its held-out interval is 25.0–83.3%. SocLaas's respective intervals
are 20.0–53.3% and 16.7–66.7%. These broad intervals reflect the small sample;
one held-out result changes agreement by about 8.3 percentage points.

The SocLaas model name is the configured alias `default`; its underlying backend
is not independently identified. OpenAI and SocLaas use provider-default sampling,
240-second transport timeouts and zero SDK retries. Ollama uses the installed
`tobestyledintro/qwen3.8-9b-distill:latest` model, temperature 0.2, 16,384-token
context, 4,096 output tokens and thinking disabled. The tool's outer deadline is
250 seconds. Runtime source and request-schema hashes are recorded in the manifest.

This is agreement with an AI-assisted, single-human approved reference, not
independent human agreement or learner-calibrated difficulty. Earlier v2 seed
questions and AI recommendations exist in this branch's history. No final-set
results were used for tuning, but the collection is not an untouched external
benchmark. Future tuning informed by these held-out results needs fresh held-out
families for confirmatory evaluation.

Full [results](evidence/difficulty-dataset-2026-10-15/results.json) retain all
66 primary records and the supplemental record, including exact MCQs, references,
full valid tool outputs, sanitized failures, timings and usage. The
[summary](evidence/difficulty-dataset-2026-10-15/summary.json) includes split/topic
breakdowns, confusion, dimensions, category support, ordinal alpha and bootstrap
intervals. The [pre-call manifest](evidence/difficulty-dataset-2026-10-15/manifest.json),
[completion audit](evidence/difficulty-dataset-2026-10-15/completion.json),
[local model identities](evidence/difficulty-dataset-2026-10-15/ollama-models.json)
and [verification](evidence/difficulty-dataset-2026-10-15/verification.json)
bind the records to the frozen dataset, request/schema hashes, source and settings.
The runner at `c38f367` materializes the recorded source fingerprint; merging main
later left the judge and runner source bytes unchanged. Invalid-response values
are not archived. Unknown timeout/interrupted-call usage is not reported as zero.

Post-merge offline verification: 471 tests passed, five opt-in live tests skipped.
Main's removal of historical reference-review tests accounts for the difference
from the pre-merge 524-test result. Focused tests verify blinding through MCP,
no execution, error denominators, uncertainty, ordinal-alpha examples and
whole-family bootstrap reproducibility. Lint, formatting and diff checks passed.
An independent audit checked all 67 completed question/reference bindings,
reconstructed request hashes, one-call records, frozen provider settings and
absence of configured API key values. Reference data is unchanged from main.

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
