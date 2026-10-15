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

SocLaas assesses the **typical instance**, treating listed parameter values as
independent and uniformly distributed. It considers common tracing demands and
reports substantial variation in `domain_variation` and `quality_concerns`. This
is one holistic estimate, not an exhaustive difficulty measurement of every case.
The original dimensions, level descriptions and three worked anchors are reused;
no evaluation examples are added. Required closed keys D1, D2, ... cover every
checked distractor recipe. Template ID, topic and declared level are hidden from
the judge. The declared level is compared with its estimate afterwards.

The tool returns ordinary `ToolEvidence`: `passed` means the advisory estimate
matches the declared level, `failed` means a mismatch or missing essential
information, and `error` means the assessment failed. Full judge reasoning, usage,
request/rubric hashes and the exact template hash are retained in `details`.
The finalizer checks that difficulty evidence belongs to the saved template.
This tool does not execute code or check correctness, even when called independently.

Authoring permits the initial proposal plus up to three **template** revisions.
The original request, target and selected check names stay fixed. Mismatch feedback
can change code, parameter domains, wording and distractor recipes coherently; the
new template must pass correctness again before another difficulty assessment.
A judge error ends the job without a check retry or template revision. `validate`
checks once without revision. `generate` remains deterministic local expansion
and makes no model calls. The selected author provider performs generation and
revision; every difficulty assessment uses SocLaas.

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
