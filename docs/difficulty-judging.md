# Advisory difficulty MCP tool

`assess_code_difficulty` v2 assesses one complete concrete Python tracing MCQ.
It returns one closest `easy`, `medium` or `hard` label with rubric-based evidence.
It performs no code execution, correctness verification or question repair.
Assessment conditions and anchors come from the [frozen rubric](difficulty-rubric.md).
The result remains advisory and does not establish learner-calibrated difficulty.

## Configure and invoke

```bash
export EDCRAFT_DIFFICULTY_PROVIDER=soclaas
# Optional: EDCRAFT_DIFFICULTY_MODEL=<model>
uv run python -m edcraft_validator.mcp
```

Difficulty checks use **SocLaas only**, by default. Supply `SOCLAAS_API_KEY`,
`SOCLAAS_BASE_URL` and `SOCLAAS_MODEL` through the environment. A non-SocLaas
`EDCRAFT_DIFFICULTY_PROVIDER` value is rejected; there is no provider fallback.
Strict JSON-schema output is the default. Each call creates a fresh provider so
settings, usage and failures remain separate. Listing tools makes no model calls.
Missing configuration is an explicit error. The general provider registry still
supports other authoring providers independently of this check policy.

The input has `question` and optional `requested_difficulty`. A question contains
`code`, `entry_function`, concrete `inputs`, the `question` stem, `answer_target`,
three or four ordered `options` (`A` through `C` or `D`) and `correct_option`.
Supported targets are return value, branch evaluations, loop iterations, loop
invocations and function calls. Stems must define relevant counting conventions.
Code is limited to 20,000 characters and the stem to 8,000. Templates, approved
reference levels, reference explanations and provenance are not question fields.

For an in-process caller with a complete question dictionary:

```python
async with Client(create_validation_server()) as client:
    result = await client.call_tool(
        "assess_code_difficulty",
        {"question": question, "requested_difficulty": "medium"},
        timeout=250,
    )
    report = result.structured_content
```

Question content is untrusted data, never instructions. The requested level and
generator identity are hidden from the judge.
Supplied answer designations are context, not execution-verified evidence.
The service validates input shapes and identifiers without checking the Python
subset, evaluating answers or verifying distractors. Those checks belong to the
separate correctness tools. Ordinary authoring continues to expose correctness
tools; this advisory operation is explicitly invoked with tag `quality:code`.
Deterministic question expansion makes no implicit model calls.

## Single-label policy and reports

The default prompt, `code-difficulty-v6-runtime-exact-options`, requires one closest
anchor for a complete
question, including adjacent boundary cases. The response contains four dimension
ratings/reasons, the estimated level, deciding reason, solution/dependency
reasoning, shortcuts, nearest anchor, evidence for every supplied option and quality
concerns. Distractor explanations remain hypotheses rather than learner data.

Confidence, alternative levels and `uncertainty_reason` are absent from the v2
schema. A null estimate is allowed only when essential question information is
missing, with `unable_to_assess_reason`; borderline difficulty and missing learner
calibration are not grounds for abstention. The runtime-rubric experiment removes
historical review instructions about confidence, uncertainty and correctness
eligibility instead of including contradictory instructions. Its dimension/level
tables and three core worked anchors come directly from the frozen rubric. No new
examples or evaluation labels are added. Approved reference data is unchanged.

The selected exact-options schema uses a closed wire object with required A/B/C or
A/B/C/D evidence keys, matching the supplied question. It then converts these
entries to the existing ordered `option_evidence` list in the public MCP report.
Missing or extra keys still fail validation; no repair call is made. The normalized
assessment retains the original request hash, prompt version and usage. The rubric
hash identifies the original source document; the request hash identifies the
actual runtime instructions and wire schema. See the experiment section below and
[evaluation history](evaluation-history.md) for the selected profile and results.

| Field | Meaning |
| --- | --- |
| `status: assessed` | A valid single-label assessment, not a correctness pass. |
| `status: unable_to_assess` | Essential information is missing; no label is invented. |
| `status: error` | The single assessment failed. |
| `difficulty_match` | `matches`, `too_easy` or `too_hard`, derived only from the selected label. Null without a requested level or usable estimate. |
| `judge` | The single assessment run, with output or sanitized error diagnostics. |
| `usage` | Usage from that run, including a failed call; aliases `judge.usage`. |

Reports retain the normalized question hash, rubric/conditions versions, exact
rubric hash, prompt/request hashes, model/settings, timestamps, latency and usage.
Failed schema responses retain field locations, codes and messages while omitting
response values and exception context. Missing token counts are null, with known
partial totals retained; unknown usage is never represented as a zero-cost call.
Historical records remain unchanged and require their original interpretation.
The v2 tool/report version identifies the single-label response contract. Current
reports omit the experimental `judge_attempts` and `max_correction_attempts` fields.

## Single-pass checks

Each invocation makes **one assessment call**. Invalid output, option-evidence
mismatches, timeouts, transport failures and configuration/internal errors return
an error with available diagnostics. The tool sends no correction feedback and
does not make replacement judgments or rewrite the question. A valid disagreement
remains a disagreement. Missing essential information returns `unable_to_assess`.

`create_validation_server` accepts `difficulty_judge_timeout_seconds` (60 seconds
by default), an injected provider factory and an optional host-side request builder
for controlled experiments. None of these is an MCP question argument. There is
no check correction setting.
MCP callers should allow the per-call timeout plus overhead. An outer model deadline
stops waiting and discards late results; it cannot terminate a synchronous provider
thread. Align transport deadlines and SDK retry settings with the application budget.
The evaluation examples set SDK retries to zero; any host-configured transport
retries remain a provider setting, separate from application-level corrections.

## Generate, assess, correct and reassess

`application.difficulty_authoring.author_question_with_difficulty` owns question
creation and revision. It preserves the original brief/target and permits one
initial generation plus up to three generation/question corrections. Valid
`too_easy`/`too_hard` feedback revises the full MCQ; missing essential information
can be supplied by a revision. Failed generation receives sanitized diagnostics
and can regenerate from the same brief. The original failures are retained.

Each assessment makes one call. An assessment error immediately ends the job
without prompting a question rewrite or another assessment of that version.
Neither operation executes code or establishes question correctness. The theoretical
bound is four author calls plus four single-call assessments: eight model calls.
The author and judge use the same configured provider/model in separate conversations.

```bash
SOCLAAS_MAX_RETRIES=0 SOCLAAS_TIMEOUT_SECONDS=240 \
SOCLAAS_RESPONSE_FORMAT=json_schema \
uv run python scripts/evaluate_difficulty_authoring.py \
  --providers soclaas --env-file .env \
  --output .artifacts/single-label-workflow/run-01 --timeout-seconds 250
```

The fixed easy/medium/hard briefs and settings are recorded before calls. Every
accepted MCQ version and tool report is saved. Summaries separate initial/final
matches, question correction attempts, changed MCQs, failures, missing-information
outcomes and total model usage. An unsuccessful fourth version is not accepted.
Use a new output directory. This experiment and the dataset runner accept SocLaas
only. Historical cross-provider evidence remains readable.

## Evaluate the approved dataset

```bash
SOCLAAS_MAX_RETRIES=0 SOCLAAS_TIMEOUT_SECONDS=240 \
SOCLAAS_RESPONSE_FORMAT=json_schema \
uv run python scripts/evaluate_difficulty_dataset.py \
  --dataset reference_sets/python_tracing/dataset.json \
  --dataset-revision <approved-dataset-commit> --env-file .env \
  --providers soclaas --followup-of <previous-run> \
  --output .artifacts/single-label-dataset/run-01 --timeout-seconds 250
```

Protocol `single-pass-difficulty-dataset-evaluation-v3` keeps all approved questions,
labels, dimensions and development/held-out splits fixed. Only MCQ content and the
designated answer enter model calls. The reference label, dimension ratings,
explanation, solution, ID, provenance, topic and split remain hidden. Every question
gets one assessment, without correction or reassessment. Valid disagreements and
failed checks remain results; evaluation questions are never rewritten.

The pre-call manifest freezes source, schema, prompt, rubric, dataset and settings.
Individual records are saved as jobs complete. Summaries report exact agreement,
failures, missing estimates, confusion, dimensions, ordinal alpha, family bootstrap
intervals and usage. Legacy first-pass/repair summary fields remain readable for
archived experiments; correction/recovery counts are zero in new runs. Historical
comparison rules remain available when reading old records; current reports never
return `uncertain` comparisons.

## Bounded accuracy experiments

```bash
SOCLAAS_MAX_RETRIES=0 SOCLAAS_TIMEOUT_SECONDS=240 \
SOCLAAS_RESPONSE_FORMAT=json_schema \
PYTHONPATH=src:. uv run python scripts/experiment_soclaas_difficulty.py \
  --env-file .env --output .artifacts/soclaas-ablations/run-01
```

Protocol `soclaas-difficulty-ablations-v1` freezes four profiles: the original
single-label prompt/array schema (`control`), a difficulty-only compact rubric
(`runtime_rubric`), exact option keys with the original prompt (`exact_options`),
and both changes (`combined`). The same three original core worked anchors are
used; no evaluation question becomes a prompt example and no new example is added.
All settings, instruction/schema/anchor hashes and the interleaved schedule are
saved before calls. There is one check per question/profile, with zero SDK retries
and concurrency three across all profiles. Generation and question correction are
not part of this experiment.

All four profiles assess the 18 development questions (72 calls). The candidate
is selected using development macro recall, with failures as nonmatches; ties use
exact matches, fewer invalid reports, shorter instructions, then fixed profile
order. Selection is saved before evaluating control and that candidate on the
12 reserved questions, using at most 24 further calls. A fixed promotion gate
requires no regression in reserved macro recall, all-item agreement, severe
disagreements or invalid reports. A failed gate retains control, without testing
another candidate. The entire run is bounded at 96 calls. Every failure stays in
the results.

The reserved collection has already been inspected in previous work; this is a
regression screen, not a fresh unbiased estimate. Example count and source are
fixed to avoid expanding the prompt around evaluation cases. Even a positive
result requires new independently reviewed families before a general accuracy
claim. Judge agreement and response validity are reported separately from token
usage; no monetary cost is inferred without a known service price.

This adapts the original rubric agreement protocol: the final dataset omits
original authoring targets, so original-target false acceptance/rejection are
unavailable. Approved categories cannot substitute for those authoring requests.
The reference is AI-assisted and approved by one human, not independent human
agreement or learner calibration. Existing held-out items have been inspected;
follow-ups are regression evidence. Tuning based on them needs fresh held-out
families for confirmatory evaluation. Full results and earlier policies are
preserved in [evaluation history](evaluation-history.md).
