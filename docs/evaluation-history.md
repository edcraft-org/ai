# Evaluation results

The issue 40 baseline below uses the current model-selected checking workflow.
Earlier milestones and provider experiments are historical context and should
not be treated as its current pass rates.

Historical records may use `beginner`, `intermediate`, and `advanced`. The current
labels are `easy`, `medium`, and `hard`.

## Shared relevance service and independent Python checks: 22 October 2026

The shared `assess_relevance` MCP tool replaces the former combined
`assess_code_quality` name. Python correctness and explicit requirements now have
separate tools. The evaluator collects their reports under the
`code-relevance-evaluation-v4-shared` protocol. Existing references, controls and
historical live records are unchanged. The Python renderer retains the exact v3
comparison text and excludes the correct-option designation.

Automated verification passed 616 tests, with three opt-in live tests skipped.
Lint, formatting, dependency-lock, diff-whitespace and source/wheel builds passed.
Review covered service and adapter dependencies, input rejection, rendering
identity, independent failure paths, unchanged comparison text and evaluator
output ownership. Authoring dispatch and difficulty policy were not changed.

The final opt-in MCP integration test passed all four synthetic cases with
`text-embedding-3-large` and 3,072-dimensional responses:

| Case | Correctness | Explicit requirements | Relevance measurement | Cosine |
| --- | --- | --- | --- | --- |
| Python arithmetic | Passed; canonical answer 10 | Satisfied | Completed | 0.493973 |
| Same question, wrong answer designation | Failed | Satisfied | Completed | 0.493973 |
| Arithmetic when a loop was required | Passed | Missing | Completed | 0.453291 |
| Generic triangle-angle text | Not invoked | Not invoked | Completed | 0.499359 |

The run used four embedding requests and 664 input tokens, three Python execution
requests, zero judge calls and zero SDK retries. Shared relevance triggered no
execution requests. Exact comparison text, rendering provenance, input hashes,
response dimensions and usage were checked, and cosine was independently
recomputed from the saved vectors. Changing only the answer designation changed
correctness identity but preserved relevance identity and the observed score.
The generic text case retained its declared omitted-diagram limitation.

Evidence is saved locally in
`.artifacts/shared-relevance-2026-10-22/live-20261021T183345540367Z/` as manifest,
tool schemas, reports, calls/vectors and verification JSON. The UTC timestamp
corresponds to 22 October in Singapore. The source fingerprint, including the live
test, is `b9199f3d199fe8dce09c6201cc44b8e901e7b15f2bfd802a3c725c7d4e466e52`.
Reproduce with `RUN_EMBEDDING_LIVE_TESTS=1 uv run pytest -q
tests/test_relevance_live.py` after supplying the embedding configuration. Each
run creates a new evidence directory and is capped at four embedding requests.

These are integration and independence checks, not relevance accuracy, model
ranking or threshold calibration. The generic text case does not implement or
validate a second question domain. The two authoring-provider live tests were not
rerun because this change does not alter authoring or difficulty judging.

## Issue 44 simplification and model selection: 21 October 2026

This section records the historical v2 design. The later v3 design removes its
difficulty-report reuse to keep assessments independent; see the
[project report](edcraft%20logs.docx), Section 6. The measurements below remain historical.

At the user's request, v2 removes the separate SocLaas quality assessment and
reuses an already available concrete difficulty report for the exact question.
Missing evidence stays explicit; the tool never generates a replacement.
Correctness and explicit requirement checks remain independent of cosine
similarity and reused opinions. Existing difficulty prompts are unchanged.

The [project report](edcraft%20logs.docx), Section 6, evaluates the
vendor-published MTEB results for small, large and ada-002, with current documented
prices. Large is the provisional default; small remains configurable. This is
published general benchmark evidence, not a new EdCraft accuracy measurement.
The original frozen dataset, controls and v1 live records remain unchanged.

Verification passed 582 tests, with two existing opt-in live workflow tests
skipped, plus lint, formatting, dependency-lock, diff-whitespace and package checks.
The 19-case evaluator regression used scripted embeddings and actual bounded
execution, reusing one existing scripted difficulty report across three matching
cases with zero additional judge calls. It retained an injected embedding error,
rejected both invalid-answer controls, and reported all three missing explicit
requirements. Tests also cover stale evidence, incomplete option coverage, strict
JSON timestamp round-tripping, malformed reports, provider failures and unknown
usage. Manual review found and fixed the wire timestamp parsing issue and added
validation of all reused reports before any evaluation requests. No live API calls
were made for this refactor or online model selection.

## Issue 44 relevance and quality review: 21 October 2026

This section records the original v1 implementation. After this review, v2 removed
the separate quality judge call, added optional reuse of exact-question difficulty
evidence, and changed the provisional embedding default to large using
published model evidence recorded in the project log. The records and results
below remain unchanged; they do not evaluate v2 or the new default.

The original quality assessment protocol was evaluated at commit
`f7cbc0ac6533005d2075ca5317e1087c7f3195b9`. The source fingerprint, covering
`src/**/*.py` and `scripts/evaluate_code_quality.py`, was:

```text
483c110ba8507e0d5f2e1d5bec9492d94b8243f4bc01dbfc9868757c589b0331
```

The manifest froze the unchanged 12 reserved MCQs and seven engineering controls
before the first call. The judge used SocLaas model ID `default`, strict JSON
schema, provider-default sampling and reasoning, a 16,384-token output budget,
110-second transport timeout, 120-second application deadline and zero retries.
Embeddings used OpenAI `text-embedding-3-small`, 1,536 dimensions, a 30-second
transport timeout, 35-second application deadline and zero retries. Two cases
ran concurrently. These provider model IDs do not identify immutable weights.
The judge received full question content and prerequisites, with reference
difficulty labels, dimensions and solutions withheld. No prompt, setting,
expectation or dataset label changed during or after this review.

All 19 requested cases produced both measurements, with no errors, unresolved
cases or protocol failures. All 12 reserved questions passed canonical-answer
and distinct-wrong-option checks. Both invalid controls (wrong designation and
duplicate distractor) failed those checks. Explicit requirements reported missing
for the off-topic, omitted-count and topic-words controls. These results are
separate from the advisory judgments below.

| Reserved-set dimension | Good | Concern | Unknown |
| --- | ---: | ---: | ---: |
| Relevance | 10 | 2 | 0 |
| Clarity | 10 | 2 | 0 |
| Answerability | 7 | 3 | 2 |
| Distractor plausibility, 36 wrong options | 27 | 8 | 1 |

The relevant control received `good` for all three question dimensions. The
ambiguous control received clarity and answerability concerns. The topic-words
control received a relevance concern despite a higher similarity than the
relevant control:

| Control | Cosine similarity | Rubric relevance | Explicit requirements |
| --- | ---: | --- | --- |
| Relevant | 0.624653 | good | satisfied |
| Off-topic | 0.579690 | unknown | missing |
| Omitted requested distractor count | 0.622671 | good | missing |
| Topic words without nested-loop reasoning | 0.684808 | concern | missing |
| Ambiguous wording | 0.651379 | concern | satisfied |

The off-topic and omitted-count relevance ratings disagreed with their frozen
`concern` expectations. In particular, the omitted-count control shows why a good
LLM rating cannot replace explicit checks. The wrong-answer control had exactly
the same similarity as the relevant control because the answer designation is
excluded from learner-facing embedding text. No similarity cutoff is justified
by these observations; reserved-set similarities ranged from 0.486476 to 0.591797.

Manual review also found important judge limitations. For
`conditionals-conditional-feedback-01`, the judge treated supplied inputs as
potentially hidden metadata, even though the assessment includes them. For
`functions-branching-recursion-01`, it partly conflated a demanding trace with
answerability. For `functions-recursive-sum-01`, it criticized the lack of a
recursive step although the request only specified functions, then returned
`unknown` answerability with reasoning that described a clear answer. The
quotient/remainder case similarly received `unknown` answerability despite
reasoning that recognized the stated prerequisites and a unique answer. Four
reserved records retained nonempty uncertainty lists; empty lists in other
records must not be interpreted as calibrated certainty. These judgments and
their inconsistencies remain in the raw records rather than being repaired.

The 19 single-pass judge calls reported 10,926 input and 24,126 output tokens.
The 19 batched embedding calls reported 4,892 input tokens. No call lacked usage
metadata. Median complete-assessment latency was 10.024 seconds, with a range of
6.988–12.960 seconds; median judge and embedding latencies were 9.919 and 0.416
seconds respectively. The independently recomputed summary matched every saved
record. Verification also matched the source/dataset/control hashes, exact
comparison texts, judge request hashes, option coverage and single-call counts.

Local evidence is under ignored `.artifacts/issue-44/`: `quality.jsonl`,
`quality.manifest.json`, `quality.summary.json` and `quality.verification.json`.
The JSONL SHA256 is:

```text
57420b291330ed50e25a9ee958e3055a4bf9a97b28425c7eb9225d317592cedc
```

The implementation passed 576 tests, with two existing opt-in live workflow tests
skipped; lint, formatting, dependency-lock, package-build and diff-whitespace
checks passed. Manual code review corrected the public option-evidence schema,
preservation of evaluation records on settings drift, and handling of unavailable
embedding usage before the frozen live run. No further actionable implementation
findings remained after the run.

This is a small, single-judge descriptive review. The reserved set has human
difficulty labels but no human quality labels, and control expectations are
engineering hypotheses rather than independent reference judgments. Neither
these rating counts nor technical correctness establish educational validity or
learner-calibrated quality. Deeper educational calibration remains later work.

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
