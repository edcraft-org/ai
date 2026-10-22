# Issue 86: difficulty evaluation evidence

The current reference is **v0.3**: 30 inspected questions, 15 easy / 9 medium /
6 hard, assessed twice per model. GLM5.3 Flash (`x-test-1`) is the SoCLaaS default.
On identical scored slots it matched 51/54 labels (94.4%), versus Qwen3.6:35b's
43/54 (79.6%). Six GLM transport slots are excluded; one output-budget failure
and two missing labels remain nonmatches. See the
[comparison report](../../docs/difficulty-glm-comparison-v0.3.md) for limitations.

## Files

| File | Contents |
| --- | --- |
| `comparison.json` | Overall/dimension scores, paired outcomes, uncertainty, tokens and latency. |
| `glm-predictions.csv`, `qwen-predictions.csv` | Final per-question/per-pass results, including exclusions and failures. |
| `reference-changes.csv` | All 22 rating changes from v0.2 to v0.3. |
| `v0.3-glm-qwen.zip` | Frozen requests/schema/settings/catalogue, references, raw responses, all returned attempts, Qwen original/retry records, GLM recovery phases and operator audits, source snapshots. |
| `v0.4-stopped.zip` | Superseded experiment: 41/58 matches, 59 recorded attempts, one excluded transport slot and one unreturned slot; retained to avoid selecting only favorable experiments. |
| `workflow-smoke.json` | Separate pre-PR live workflow failure: GLM exceeded the existing 60-second production judge deadline. |
| `checksums.json` | SHA-256 of the seven data files above. |

The archives are portable exports of the completed research evidence. Only local
home/workspace paths were replaced with `<user-home>` / `<workspace>`; duplicate
report copies and obsolete checksum lists were removed. Each `export-index.json`
records the source archive digest and both original and exported file digests.
Hashes in historical manifests refer to the original pre-export bytes. Verify
exported bytes with the export index, rather than those historical path-sensitive
hashes. Prompts, numeric outcomes and reference labels are unchanged. Snapshots
record the code used during inference, before later default-model/document edits.
The top-level CSV copies use LF line endings for readable repository diffs.
The original workspace archives remain intact.

## Offline verification

From the repository root, verify all distributed bytes without model calls:

```sh
python - <<'PY'
import hashlib, json
from pathlib import Path
from zipfile import ZipFile
root = Path('evidence/issue-86')
for name, expected in json.loads((root / 'checksums.json').read_text()).items():
    assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected, name
    if name.endswith('.zip'):
        with ZipFile(root / name) as archive:
            assert archive.testzip() is None
            index = json.loads(archive.read('export-index.json'))
            for member, hashes in index['files'].items():
                actual = hashlib.sha256(archive.read(member)).hexdigest()
                assert actual == hashes['export_sha256'], member
print('All evidence checksums verified')
PY
```

To inspect/recompute results, extract `v0.3-glm-qwen.zip` to a new directory.
Inside `soclaas-v0.3-glm53flash-recovery-r4/`, `records.jsonl` contains 60 final
GLM slots and `baseline-records.jsonl` contains the 60 final Qwen slots.
`attempts.jsonl` contains all 117 returned GLM attempts; interrupted unreturned
requests are separate operator audits. Never treat retries as extra samples.
Use `classification_metrics` in `scripts/retry_trace_difficulty_transport.py`
and `paired_comparison` in `scripts/compare_soclaas_difficulty.py` to recompute
scores. `baseline-manifest.json` contains Qwen's exact frozen requests.

For a new **opt-in live run**, follow the
[evaluation guide](../../docs/evaluation.md#active-v03-model-comparison-glm53-flash-versus-qwen).
Create a separate baseline directory and copy the extracted
`baseline-manifest.json` into it as `manifest.json`; pass that new directory as
`--baseline`. Pass the extracted `baseline-records.jsonl` as `--baseline-records`,
a newly saved catalogue as `--catalogue`, and a fresh output directory.
Do not pass the GLM directory itself as the Qwen baseline. Never overwrite or resume this published result to improve a score.
No client/judge deadlines are imposed by the comparison; provider deadlines can
still occur. Transport-only recovery and additional retry budgets must be declared
and retained separately from content outcomes.

## Scope still open

These results measure agreement with an AI-assisted, user-approved reference.
All questions informed rubric development; historical held-out labels are not
an unseen test. Independent human/learner calibration, fresh families,
production migration from v0.2 and authoring mismatch-policy evaluation remain
open under issue 86. Changing the model default does not validate those workflows.

The pre-PR live workflow smoke did not produce a finalized template: generation
and correctness checks passed, but the production difficulty judge timed out
after 60 seconds. This is a merge blocker for validating the new default in the
authoring workflow, separate from the frozen offline classification results.
The draft PR retains existing deadlines pending a production-policy decision.
