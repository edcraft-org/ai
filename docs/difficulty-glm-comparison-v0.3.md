# v0.3 difficulty evaluation: GLM5.3 Flash versus Qwen

Run date: 22 October 2026. Protocol: `trace-difficulty-v0.3-model-comparison-r1-recovery-r2`.

## Result

GLM5.3 Flash achieved **51/54 (94.4%)**,
higher observed overall agreement than Qwen3.6:35b's **47/60 (78.3%)**.
Transport failures are excluded from accuracy. Content/schema failures and
abstentions remain nonmatches. This is descriptive agreement on the same 30
inspected questions, each assessed twice, rather than 60 independent questions.

| Measure | Qwen3.6:35b | GLM5.3 Flash |
| --- | ---: | ---: |
| Overall agreement | 47/60 (78.3%) | 51/54 (94.4%) |
| Agreement on identical scored slots | 43/54 (79.6%) | 51/54 (94.4%) |
| Execution burden | 68.3% | 98.1% |
| Changing state | 73.3% | 88.9% |
| Conceptual interaction | 70.0% | 94.4% |
| All three dimensions correct | 37/60 | 48/54 |
| Overall and all dimensions correct | 36/60 | 48/54 |
| Exact event count | 12/60 | 48/54 |
| Macro F1 | 0.7403 | 0.9619 |
| Same label among questions with two valid outputs | 23/30 | 22/22 |
| Scored assessment coverage | 60/60 | 54/60 |
| Recorded returned attempts (all phases) | 63 | 117 |
| Operator-interrupted, unreturned attempts | 0 | 4 |
| Questions with at least one valid prediction | 30/30 | 29/30 |
| Median successful response | 9.45s | 31.97s |
| 95th-percentile successful response | 30.87s | 177.60s |
| Reported input tokens | 99,438 | 86,227 |
| Reported output tokens | 49,746 | 264,530 |

## Reference and controlled settings

The user selected v0.3 after the v0.4 experiment did not improve overall
agreement. The active dataset was restored byte for byte from the exact v0.3
snapshot: **15 easy, 9 medium, 6 hard**. The v0.4 dataset and stopped-run evidence
were preserved. No reference rating or question content was changed for GLM.

SoCLaaS identifies `x-test-1` as **Testing GLM 5.3 Flash**. Returned model metadata:
`{"glm-5.3-flash": 54, "null": 63}`. The alias does not pin immutable weights.
The current catalogue, model pricing metadata and exact settings are retained.

The candidate used the exact Qwen v0.3 messages, response schema, schema name,
prompt versions, dataset and rubric. Every inference request hash was independently
matched to the Qwen baseline. Reference ratings, event counts, solutions and
historical splits were hidden from the model. Raw model labels were scored;
v0.4's derived ratings and stricter evidence validators were not used.
Both runs used two assessments per question, concurrency two, strict JSON schema,
16,384 output tokens per request, and provider-default sampling/reasoning.

GLM client/judge deadlines were disabled; SDK retries were zero. Transport
failures received identical-request retries, with concurrency slots released
between attempts. After a provider-wide HTTP 503 burst exhausted the original
one-retry budget, one extra transport retry per failed slot was declared before
new inference. Availability errors trigger 5–60-second backoff. Completed content
failures and predictions are never rerun.
GLM recorded **117 returned attempts**, including **63
transport-failed attempts**, and **6 final transport-excluded
slots**. Separately, **4 unreturned attempts**
were interrupted during the user-approved recovery and are unscored.
Content errors: `{"JUDGE_INVALID_RESPONSE": 1}`. Missing overall labels in completed
responses: **2**. Transport HTTP
status counts across recorded attempts: `{"502": 4, "503": 56, "None": 3}`.

The existing Qwen baseline combines 57 original valid responses and three
transport-only retry responses (63 attempts in total, three historical transport
failures). Initial Qwen calls had finite deadlines; its three retries and this
GLM run had no client/judge deadlines. This is a historical comparison, with
possible provider-load, serving-weight and default-sampling differences.

## User-approved recovery

Two requests held the initial batch open. The user explicitly approved restarting
only unfinished requests. All 28 completed non-transport assessments were retained
unchanged, including their raw responses. One HTTP 502 transport failure received
its planned retry. A later burst of HTTP 503 responses led to another transport-only
recovery phase, with additional backoff. All 35 previously scored assessments,
including the output-budget content failure, were retained unchanged in that phase. Two unreturned calls were recorded as operator interruptions,
separately from transport failures and accuracy. A later recovery restarted two
more unreturned calls after prolonged stalls, preserving all 52 scored outcomes
and the transport retry budget. The recovered and previously
queued requests used identical frozen prompts/schema/settings. This is a documented
operational protocol amendment, not resampling completed predictions.

## Per-pass and per-class results

| Pass | GLM matches | Agreement |
| --- | ---: | ---: |
| 1 | 29/29 | 100.0% |
| 2 | 22/25 | 88.0% |

Confusion rows are reference labels; columns are predictions.

| Reference | Easy | Medium | Hard | Recall |
| --- | ---: | ---: | ---: | ---: |
| easy | 27 | 0 | 0 | 100.0% |
| medium | 0 | 14 | 0 | 87.5% |
| hard | 0 | 0 | 10 | 90.9% |

## Remaining dimension disagreements in valid responses

| Question | Pass | Dimension | Reference | GLM |
| --- | ---: | --- | --- | --- |
| `functions-composition-01` | 1 | changing_state | moderate | low |
| `functions-composition-01` | 1 | conceptual_interaction | moderate | low |
| `cruxeval-223` | 1 | changing_state | moderate | high |
| `cruxeval-506` | 2 | changing_state | moderate | low |
| `functions-composition-01` | 2 | changing_state | moderate | low |
| `functions-composition-01` | 2 | conceptual_interaction | moderate | low |
| `loops-conditional-reset-02` | 2 | changing_state | high | moderate |

## Paired changes and uncertainty

On 54 slots scored for both models:

- Both correct: 41.
- GLM correct, Qwen incorrect: 10.
- Qwen correct, GLM incorrect: 2.
- Both incorrect: 1.

Agreement on these identical slots was 79.6% for Qwen
and 94.4% for GLM, a difference of
14.8 percentage points. Coverage differs from
the full Qwen baseline; do not silently equate the denominators.

The descriptive 95% paired cluster-bootstrap interval for GLM minus Qwen
agreement is **1.9% to 27.8%**, using 2,000 resamples,
seed 86 and 30 exact code-family clusters while retaining repeated
assessments together. This does not establish generalisation to fresh families
or learner performance. All 30 items were inspected during rubric development;
labels are AI-assisted with user-approved operational boundaries.

## Item-level comparison

`Invalid` means a content/schema failure or abstention. Transport errors are
excluded from scoring. All raw outputs and explanations remain available.

| Question | Reference | Qwen pass 1 | Qwen pass 2 | GLM pass 1 | GLM pass 2 |
| --- | --- | --- | --- | --- | --- |
| `arithmetic-coupled-arithmetic-01` | hard | hard | hard | hard | hard |
| `arithmetic-quotient-remainder-01` | easy | easy | easy | easy | easy |
| `cruxeval-082` | easy | easy | easy | easy | easy |
| `lists-adjacent-differences-02` | medium | medium | easy | medium | Transport |
| `cruxeval-274` | medium | medium | medium | medium | medium |
| `cruxeval-752` | easy | easy | easy | easy | Transport |
| `functions-recursive-sum-01` | easy | easy | easy | easy | easy |
| `conditionals-boolean-01` | easy | easy | easy | easy | easy |
| `functions-single-helper-01` | easy | easy | easy | easy | easy |
| `cruxeval-506` | medium | easy | medium | medium | medium |
| `conditionals-conditional-feedback-01` | hard | medium | medium | hard | hard |
| `functions-branching-recursion-01` | hard | hard | medium | hard | hard |
| `functions-composition-01` | medium | easy | easy | medium | Invalid |
| `cruxeval-253` | easy | easy | easy | easy | easy |
| `lists-endpoint-swap-02` | easy | easy | easy | easy | easy |
| `cruxeval-783` | medium | easy | easy | medium | medium |
| `cruxeval-147` | easy | easy | easy | easy | easy |
| `cruxeval-356` | medium | medium | medium | medium | Transport |
| `conditionals-sequential-02` | easy | easy | easy | easy | easy |
| `lists-mutating-selection-score-01` | hard | medium | hard | hard | hard |
| `cruxeval-498` | easy | easy | easy | easy | Transport |
| `loops-conditional-reset-02` | medium | medium | medium | medium | Invalid |
| `loops-coupled-prefix-fold-01` | hard | hard | hard | hard | hard |
| `loops-iteration-count-01` | easy | easy | easy | easy | Transport |
| `cruxeval-793` | medium | medium | medium | medium | medium |
| `arithmetic-reassignment-01` | easy | easy | easy | easy | easy |
| `cruxeval-197` | easy | medium | easy | easy | easy |
| `cruxeval-223` | medium | medium | hard | medium | medium |
| `loops-guarded-sweep-01` | hard | medium | hard | Transport | Invalid |
| `cruxeval-598` | easy | easy | easy | easy | easy |

## Evidence and verification

Versioned [portable evidence and verification instructions](../evidence/issue-86/README.md)
include the frozen requests, final records and all returned attempts.
The export removes local home paths; original provenance digests are identified separately.

Retained manifest, exact requests/schema/settings/catalogue, raw responses,
all attempts, final slot records, CSV predictions, dataset/rubric/source snapshots,
Qwen baseline records, aggregate and paired statistics, verification and checksums.
GLM recovery-phase wall time: 113.0 seconds.
The initial phase and operator-approved interruption are recorded in
`recovery-parent/operator-recovery.json`; this phase duration excludes the
initial phase and the restart preparation interval.

Reported-token catalogue metering equivalents: Qwen
$0.113408, GLM
$0.146620.
These are not personal bills or complete all-attempt costs when failed-attempt
usage is unavailable. Per-token price and total token consumption both matter.
Latency comparisons are observational and include different server conditions.

Independent verification passed for aggregate and per-dimension scores, 60 unique
slots and CSV rows, exact baseline request hashes, fixed references/source hashes,
disabled deadlines, and transport-only retries. Local verification: **637 tests
passed, 3 opt-in live tests skipped**; repository lint, formatting and whitespace
checks passed. The live benchmark above was run separately against SoCLaaS.
The current production MCP v0.2 contract was not migrated; this report evaluates
the explicit v0.3 reference-assessment workflow.

## Pre-PR workflow check

The separate live authoring smoke failed after template generation and correctness
checks passed: GLM exceeded the existing production judge deadline of 60 seconds
(`JUDGE_TIMEOUT`), leaving the template at `needs_review`. No finalized artifact
was produced. See [the smoke record](../evidence/issue-86/workflow-smoke.json).
This availability failure does not alter the frozen offline agreement scores.
Review production deadline/retry policy and pass the live workflow before merge.
