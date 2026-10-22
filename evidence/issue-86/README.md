# Difficulty evaluation evidence

The current reference is v0.3: 30 inspected questions, assessed twice per model.
GLM matched **51/54 (94.4%)** versus Qwen **43/54 (79.6%)** on identical scored
slots. Six GLM transport slots are excluded; one output-budget failure and two
missing labels remain nonmatches. Qwen's full baseline is 47/60 (78.3%).
See [the report](../../docs/difficulty-glm-comparison-v0.3.md) for interpretation.

| File | Contents |
| --- | --- |
| `comparison.json` | Scores, paired outcomes, uncertainty, tokens and latency. |
| `glm-predictions.csv`, `qwen-predictions.csv` | Per-question/per-pass results, failures and exclusions. |
| `reference-changes.csv` | The 22 rating changes from v0.2 to v0.3. |
| `v0.3-glm-qwen.zip` | Raw responses, final records, all returned attempts, exact requests/settings, model catalogue and reference inputs. |
| `v0.4-stopped.zip` | Stopped experiment: 41/58 matches, 59 returned attempts, one transport-excluded and one unreturned slot. |
| `workflow-smoke.json` | Separate live authoring failure at the production judge's 60-second deadline. |

The compact archives remove repeated source copies, phase copies, checksum files
and export bookkeeping. Predictions, raw responses, reference labels and aggregate
statistics are unchanged. Complete pre-cleanup archives remain in Git at
`7601a8d` and in the original workspace output directory. Local home paths in the
published records were already replaced with `<workspace>` / `<user-home>`.
The manifest records the original run's Git revision; source copies and digests
from the original uncommitted experiment are available in that earlier commit.

To inspect results, extract `v0.3-glm-qwen.zip`. Inside
`soclaas-v0.3-glm53flash-recovery-r4/`:

- `records.jsonl`: 60 final GLM slots.
- `baseline-records.jsonl`: 60 final Qwen slots.
- `attempts.jsonl`: all 117 returned GLM attempts, including 63 transport failures.
- `baseline-original-attempts.jsonl` and `baseline-retry-attempts.jsonl`: Qwen history.
- `manifest.json` and `baseline-manifest.json`: run settings and exact requests.

Use `classification_metrics` and `paired_comparison` from
`scripts/evaluate_difficulty.py` to recompute scores without model calls.
Retries are attempts rather than additional samples. Four interrupted,
unreturned GLM requests are recorded in `comparison.json`, separately from the
117 returned attempts and accuracy denominator.

For a new live comparison, create a separate Qwen baseline directory and copy
`baseline-manifest.json` into it as `manifest.json`, and `baseline-records.jsonl`
as `records.jsonl`. Pass that directory as `--baseline` to the
[consolidated runner](../../docs/evaluation.md#v03-ordinary-trace-reference-agreement).
Use a fresh output directory. Completed wrong predictions, content failures and
missing labels are never rerun.

All questions informed rubric development. These are agreement results on an
AI-assisted reference, not unseen accuracy or learner calibration. Independent
review, fresh families, production v0.3 migration and mismatch-policy evaluation
remain open under issue 86. The separate live workflow smoke still failed because
GLM exceeded the existing production judge deadline; the PR remains draft.
