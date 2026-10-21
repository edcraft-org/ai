# Difficulty checking

## Reusable template workflow

`code_assess_template_difficulty` runs inside the normal `author` and `validate`
workflows. It is offered through the `domain:code` catalogue. The author prompt
asks the model to select it alongside the independent correctness checks; inspect
`fixed_plan` to confirm selection. No difficulty claim is made for an omitted check.

After the selected correctness checks pass, the application binds the exact
reusable template: code, full finite parameter domains, question pattern, answer
target and checked distractor recipes. The proposed answer expression is cleared,
just as in the saved artifact. The model requests the native tool call; it cannot
replace the application-owned candidate. If correctness fails, difficulty stays
pending and no judge call is spent on that attempt.

SocLaas assesses the **typical instance** under the effective sampling policy.
When `eligible_inputs` is supplied, only those collision-free combinations are
possible, each equally likely; parameters can be correlated. Otherwise the full
Cartesian product uses independent uniform parameter values. The checker reports
variation in `domain_variation` and `quality_concerns`. One estimate does not
establish uniform difficulty. The original dimensions, level descriptions and
three worked anchors are reused; no evaluation examples are added. Closed keys
D1, D2, ... cover every selected distractor. Template ID, topic and requested level
are hidden from the judge and the level is compared afterwards.

Template tool version 1.1.0 returns a bounded numeric `confidence` self-estimate.
Policy `confidence-gated-v1` uses a provisional threshold of 0.80:

| Result | Evidence and workflow |
| --- | --- |
| Estimate matches target | `passed`, decision `matches`. |
| Mismatch, confidence >= 0.80 | `failed`, decision `revise`; feedback goes to the authoring model. |
| Mismatch, confidence < 0.80 | `passed` with `DIFFICULTY_MISMATCH_LOW_CONFIDENCE`, decision `advisory_mismatch`. |
| Missing essential information | `failed`; no difficulty assessment is established. |
| Judge failure | `error`; no automatic check retry. |

A passing policy decision does **not** necessarily mean a difficulty match. Inspect
`difficulty_match`, `decision` and `AuthoringResult.warnings`. Low-confidence
mismatches preserve the requested label and expose the estimate, confidence and
warning in both the report and saved artifact; clients should show both labels.
Confidence is not calibrated accuracy (`confidence_calibrated: false`). Judge
reasoning, usage, request/rubric hashes and the exact template hash remain in
`details`. The finalizer binds the assessment to the exact saved eligible domain.
This tool does not execute code or check correctness, even when called independently.

Authoring permits the initial proposal plus up to three **template** revisions.
The original request, target and selected check names stay fixed. High-confidence mismatch feedback
can change code, parameter domains, wording and distractor recipes coherently; the
new template must pass correctness again before another difficulty assessment.
A judge error ends the job without a check retry or template revision. `validate`
checks once without revision. `generate` remains deterministic local expansion
and makes no model calls. The selected author provider performs generation and
revision; every difficulty assessment uses SocLaas.

The author receives the original level definitions and a short description of the
four dimensions, without added worked examples. Its wire format uses individual
indented Python lines. Full revisions must keep the function signature, parameter
domains, placeholders and expressions consistent. When the only failure is
distractor selection, a partial response can change recipes and parameter values;
the application preserves code, wording, answer target and ordered parameter
names/kinds. Correctness still checks the entire domain again. Collision evidence
includes up to 16 counterexamples, covering bad recipes and duplicate recipe pairs.

Author generation/revision calls have one bounded retry for connection failures
or transient HTTP status errors. Timeout, schema and content failures are not
retried. Both attempts remain in author call accounting, without consuming another
template revision. Set SDK retries to zero when using this application policy to
avoid multiplying transport attempts. The checker has no application retry and
each invocation assesses its supplied template exactly once.

## Standalone concrete-question API

`assess_code_difficulty` v2 assesses one concrete Python tracing MCQ using SocLaas.
It returns one closest `easy`, `medium` or `hard` label under the original rubric's
manual, untimed tracing conditions. It is advisory: it does not execute code,
verify the answer or distractors, repair the question, or establish learner difficulty.

## Configuration

Set `SOCLAAS_API_KEY`, `SOCLAAS_BASE_URL` and `SOCLAAS_MODEL` in the environment.
SocLaas is the default difficulty provider. A different
`EDCRAFT_DIFFICULTY_PROVIDER` is rejected; there is no provider fallback.
`EDCRAFT_DIFFICULTY_MODEL` optionally overrides the SocLaas model.
Strict JSON-schema output is the default. Set `SOCLAAS_MAX_RETRIES=0` to disable
SDK transport retries. Each tool invocation makes one assessment attempt and
returns failures immediately; it sends no correction feedback.

```bash
uv run python -m edcraft_validator.mcp
```

The host can inject a provider factory and set
`difficulty_judge_timeout_seconds` (default 60 seconds). Allow that timeout plus
overhead on the MCP client. An application deadline stops waiting and discards
late results; it cannot terminate a synchronous provider thread. Align the
SocLaas transport timeout with the application deadline.

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
`configured_difficulty_provider` supplies the SocLaas factory when authoring should
also use SocLaas. Author and tool deadlines are configurable. The upper bound is
four author calls plus four single-call assessments. Neither operation invokes
correctness tools; applications combine their independent results when needed.
