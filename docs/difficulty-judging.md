# Difficulty checking

## Reusable template workflow

`code_assess_template_difficulty` runs inside the normal `author` and `validate`
workflows. It is offered through the `domain:code` catalogue. The author prompt
asks the model to select it alongside the independent correctness checks; inspect
`fixed_plan` to confirm selection. No difficulty claim is made for an omitted check.

After the selected correctness checks pass, the application binds the exact
reusable template: code, full finite parameter domains, question pattern, answer
target and checked distractor recipes. The proposed answer expression is cleared,
just as in the saved artifact. The application invokes the selected MCP check
directly, without asking the authoring model for a native tool call. If correctness
fails, difficulty stays pending with a skip reason and no judge call is spent on
that attempt.

The configured judge model assesses the **typical instance** under the effective sampling policy.
Parameter values are sampled independently and uniformly; generation may resample
recipe/option collisions. Property-based checks do not prove correctness for every
variant. The checker reports
variation in `domain_variation` and `quality_concerns`. One estimate does not
establish uniform difficulty. The original dimensions, level descriptions and
three worked anchors are reused; no evaluation examples are added. Closed keys
D1, D2, ... cover every selected distractor. Template ID, topic and requested level
are hidden from the judge and the level is compared afterwards.

Template tool version 1.2.0 uses policy `decision-cascade-v1`:

1. Classify the exact template with reasoning disabled, using only one of
   `easy`, `medium`, `hard`. Normalize the first content token's observed top-k
   log-probability mass over these labels. Missing label mass is zero, so this
   conditional distribution is not a full-vocabulary probability or calibrated
   accuracy. Requested difficulty, template identity and topic are withheld.
2. Accept the decision at confidence **>=0.70**. A label mismatch fails the check
   and requests author revision, including decisions between 0.70 and 0.80.
3. For lower confidence or a failed/invalid decision, call the **same configured
   model** once with reasoning enabled and the existing full structured template
   prompt. Do not show the classifier label to the reasoning judge.

| Final result | Evidence and workflow |
| --- | --- |
| Accepted decision matches target | `passed`, `matches`; no reasoning call. |
| Accepted decision differs | `failed`, `revise`. |
| Reasoning estimate matches | `passed`, `matches`. |
| Reasoning mismatch, self-reported confidence >=0.80 | `failed`, `revise`. |
| Reasoning mismatch, confidence <0.80 | `passed`, `advisory_mismatch`, with warning. |
| Missing essential information in reasoning assessment | `failed`. |
| Reasoning failure or exhausted cascade deadline | `error`; never a pass. |

The 0.70 routing threshold uses token probabilities. The 0.80 revision threshold
uses the reasoning judge's self-reported confidence. Neither is calibrated.
`details.screen` retains the decision, distribution, served model, request hash,
settings and usage. `details.judge` retains the final decision or structured
reasoning report; `estimated_difficulty`, `confidence`, `confidence_source` and
`assessment_path` identify the final result without inventing rationale for a
one-word decision. Aggregated `usage` and `model_calls` include both calls.
The rubric and exact template hash bind both paths to the checked content.
A passing policy decision does not necessarily establish a difficulty match.

Authoring permits the initial proposal plus up to three template revisions. A
mismatch can change code, parameter domains, wording and distractors coherently;
each replacement passes correctness again before difficulty checking. The request,
target and selected checks remain fixed. A failed reasoning call ends checking
without retrying the check or revising the template. `validate` never revises;
`generate` remains deterministic local expansion and makes no model calls.

Decision and reasoning calls share the existing 310-second application budget;
the decision gets at most 35 seconds. The reasoning call uses only the remaining
time. A deadline stops waiting rather than cancelling a synchronous provider
thread. Fallback uses a fresh provider instance, preventing late decision usage
from contaminating reasoning records. Structured-only injected judge providers
can still be used; their unavailable decision capability is recorded and they
receive one structured assessment call.

The prior live cascade experiment assessed concrete questions with `x-test-3`
followed by `x-test-1`. It did not evaluate this same-model template policy.
Existing frozen evaluation artifacts remain unchanged.

The author receives the original level definitions and a short description of the
four dimensions, without added worked examples. Its wire format uses individual
indented Python lines. Every revision returns a complete proposal, including after
a distractor-only failure. Code, function interface, parameter domains, wording,
answer recipe and distractors may change together while staying consistent with
the original request. The application rebuilds and samples the replacement again
before judging difficulty. The requested label and required distractor count are
application-owned; free-text constraints are not generally enforced. Skipped
checks remain explicit in feedback and do not represent observed defects.
Collision evidence
includes up to 16 counterexamples, covering bad recipes and duplicate recipe pairs.

Author generation/revision calls have one bounded retry for connection failures
or transient HTTP status errors. Timeout, schema and content failures are not
retried. Both attempts remain in author call accounting, without consuming another
template revision. Set SDK retries to zero when using this application policy to
avoid multiplying transport attempts. The checker has no application retry and
each invocation assesses its supplied template exactly once.

## Standalone concrete-question API

`assess_code_difficulty` v2 assesses one concrete Python tracing MCQ using the configured model.
It returns one closest `easy`, `medium` or `hard` label under the original rubric's
manual, untimed tracing conditions. It is advisory: it does not execute code,
verify the answer or distractors, repair the question, or establish learner difficulty.

## Configuration

Set `EDCRAFT_JUDGE_PROVIDER` and `EDCRAFT_JUDGE_MODEL` to choose one model for
both difficulty stages and relevance. Defaults are `soclaas` and `x-test-3`.
The provider registry supplies endpoint/credential configuration; for SocLaas set
`SOCLAAS_API_KEY` and `SOCLAAS_BASE_URL`. These judge settings are independent of
`SOCLAAS_MODEL` or the selected authoring model. Old `EDCRAFT_DIFFICULTY_*`
configuration has been replaced by the shared `EDCRAFT_JUDGE_*` names.

`EDCRAFT_JUDGE_REASONING_EFFORT` defaults to `medium` and accepts `low`, `medium`,
`high` or `xhigh`. Only the fallback applies it; forced decisions always request
`reasoning_effort=none`, temperature 0, max_tokens 16, logprobs and top_logprobs 20.
OpenAI-compatible adapters implement this decision capability. Other injected
adapters must implement `decide(messages, labels)` to provide token decisions.
Do not substitute an LLM's self-reported confidence for missing logprobs.

Strict JSON-schema output remains the reasoning default. Set provider SDK retries
to zero for exactly one HTTP attempt per stage. The cascade never switches models
or providers automatically. The standalone concrete-question tool is preserved
for evaluation and the older authoring helper; it still runs one structured
assessment, outside the reusable-template cascade.

```bash
uv run python -m edcraft_validator.mcp
```

The host can inject a provider factory and set
`difficulty_judge_timeout_seconds` (default 310 seconds). The SoCLaaS transport
timeout defaults to 300 seconds, and the built-in MCP client allows 330 seconds
per tool call. These limits accommodate GLM's measured 178-second p95 with room
for slower responses and tool overhead. Keep custom client timeouts longer than
the judge deadline. An application deadline stops waiting and discards late
results; it cannot terminate a synchronous provider thread. The separate research evaluation uses disabled deadlines.

## Input and output

Supply `question` and an optional `requested_difficulty`. The question contains
`code`, `entry_function`, concrete `inputs`, its `question` stem, `answer_target`,
three or four ordered `options` (A/B/C[/D]) and `correct_option`. Supported targets
are return value, branch evaluations, loop iterations, loop invocations and
function calls. Relevant counting conventions must be stated in the stem.
Code is limited to 20,000 characters and the stem to 8,000.

For an existing complete question dictionary:

```python
async with Client(create_validation_server()) as client:
    result = await client.call_tool(
        "assess_code_difficulty",
        {"question": question, "requested_difficulty": "medium"},
        timeout=70,
    )
    report = result.structured_content
```

Requested difficulty stays hidden during estimation and is compared afterwards.
Reference labels and explanations are not question fields. Question content is
untrusted data. The supplied answer designation is context, not verified evidence.
The compact prompt uses the original dimension/level tables and three existing
worked anchors. It adds no evaluation examples. An internal closed response
object requires every supplied option key, then converts to the public ordered
`option_evidence` list. Missing or extra keys fail validation without a retry.

| Report field | Meaning |
| --- | --- |
| `status` | `assessed`, `unable_to_assess` for missing essential information, or `error`. |
| `difficulty_match` | `matches`, `too_easy` or `too_hard`; null without a target or usable estimate. |
| `judge.assessment` | Selected level, four dimension ratings/reasons, deciding evidence, solution/dependency reasoning, shortcuts, nearest anchor, option explanations and quality concerns. |
| `judge` | The single result or sanitized failure, with model/settings, request/prompt hashes, timing and usage. |
| `usage` | The same run's usage; unknown totals remain null rather than zero. |
| Question/rubric metadata | Normalized question hash, original rubric hash/version and assessment-condition version. |

Confidence and alternative labels are absent. Borderline cases select the closest
level; missing learner calibration alone does not justify abstention. The rubric
hash identifies the original source document, while the request hash identifies
the actual runtime instructions and response schema. Failures expose sanitized
field locations/codes/messages rather than raw response values or exception text.
This standalone tool has tag `quality:code` and is not offered to the reusable
template author. Listing tools makes no model calls.

## Standalone question generation and revision

`author_question_with_difficulty` in `application/difficulty_authoring.py` preserves
the brief and requested level while generating and assessing a concrete question.
It permits up to three generation/question revisions. Valid `too_easy`/`too_hard`
feedback can revise the complete MCQ; missing information can be supplied by a
revision. A failed assessment ends the job immediately. Every question version,
author failure and assessment remains in the returned result.

The caller supplies the author provider factory and a connected MCP client.
`configured_difficulty_provider` supplies the shared configured judge model;
author generation can use a different provider/model. Author and tool deadlines are configurable. The upper bound is
four author calls plus four single-call assessments. Neither operation invokes
correctness tools; applications combine their independent results when needed.
