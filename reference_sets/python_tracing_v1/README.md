# Python tracing reference set v1

Prepared for [issue 42](https://github.com/edcraft-org/ai/issues/42), using
`python-tracing-v0.2`, `manual-tracing-v0.1` and
`python-tracing-agreement-v0.2`. This is a **provisional collection awaiting human
review**, not a training dataset or learner-calibrated benchmark. Automated
execution establishes answers and count conventions, not educational difficulty
or distractor plausibility. No human labels have been supplied yet.

## Collection and split

The collection has 30 complete concrete MCQs, six in each of arithmetic,
conditionals, loops, functions and lists. Fifteen underlying code families each
have two variants. Nine families (18 items) are development and six families
(12 items) are held out. The family split was assigned during collection, before
human ratings or judge tuning. All input/target/option variants stay together.
The manifest is fixed for this collection revision; do not rebalance it after
seeing ratings. Requested levels are authoring intentions and are not references.
Actual reviewed labels need not form equal groups.

Ten questions adapt five existing fixture families; twenty were newly authored
with AI assistance. No CRUXEval items were used. Provenance records source IDs,
repository links/revisions and file hashes for adaptations, plus changes to
concrete inputs, options, targets or wording. New items explicitly identify
AI-assisted curation. Distractor explanations in the manifest are curator
hypotheses, not human evidence or observed misconceptions.

The collection covers all five answer targets, including explicitly defined
condition evaluations, loop iterations versus invocations, and function calls.
It includes base-case recursion, an accessible algebraic shortcut, changing
state and changed-target variants. Their presence does not assign a reviewed
level. This directory is separate from the 15 frozen topic/difficulty authoring
requests in `profiles.py`; those requests and provider comparison evaluation
have not changed. Reusing fixture source code does not turn its old label into
ground truth.

## Files and verification

- `questions.json`: code, entry function, exact concrete inputs, exact stem,
  ordered options, designated correct option and answer target. Seed is null:
  inputs were selected directly, with no random sampling.
- `manifest.json`: family/split membership, intended levels, provenance,
  distractor hypotheses, rubric hash/version and protocol version. **Do not
  inspect this while independently rating.**
- `technical-evidence.json`: supported-subset checks, distinct options, verified
  answers and trace summaries. Hashes cover complete questions and the manifest.
  The answers were obtained with the existing resource-limited local execution
  worker and the project's pinned StepTracer revision. No model calls are needed.

From the repository root:

```bash
uv run python scripts/difficulty_reference.py verify
```

The verifier checks every recorded answer against execution, the trace target,
option validity, item identity and family isolation. On an intentional item or
manifest revision, preserve the old collection/reviews first, update the version,
then regenerate evidence with `verify --write-evidence`. Any code, input, stem,
target or option change invalidates the previous concrete review. Hash checks
also reject stale evidence and a changed rubric.

## Single human review

Keith has opted to be the sole reviewer for this collection. No AI-generated
ratings are substituted for his review. Human–human agreement will be unavailable;
any resulting references must disclose the single-reviewer limitation. If another
person becomes available, prepare a separate packet and retain their independent
ratings before discussion. The current comparison command handles one reviewer;
multi-reviewer adjudication and agreement are not implemented here.

Prepare a self-contained form and a blank JSON record:

```bash
uv run python scripts/difficulty_reference.py prepare-review \
  --reviewer keith --output .artifacts/difficulty-review-keith
```

Open `.artifacts/difficulty-review-keith/review.html` in a browser. The packet uses
opaque IDs and a fixed hash-based question order. It includes code, inputs, stem,
all options and separately expandable verified answers/traces. It excludes
requested levels, source/generator identity, source explanations, family/topic
metadata, split membership and other ratings. The reviewer may consult verified
answers to check their solution; learners would not receive them.

Use the full [rubric](../../docs/difficulty-rubric.md), including its anchors,
without executing the questions or using AI judgments. Explain the concrete
solution, relevant concepts and dependencies, shortcuts, each dimension and each
option. For a wrong option, record a rule yielding that exact value or explain
why it is implausible. Record the nearest anchor, estimate, confidence,
alternatives, uncertainty and quality concerns. A supported recursive base case
need not be hard; a count shortcut can avoid tracing irrelevant state. Unknowns
remain unknown. If wording or correctness appears faulty, describe the concern
and leave an uncertain review; repair/version and re-review the item before
using it as a confirmed reference.

Drafts may be saved locally by the browser. **Download ratings to preserve them**;
if your browser does not support downloads, use **Show ratings JSON** and save the
visible text as a `.json` file.
Browser storage is not a versioned review record. The HTML form never sends
answers to a service. Keep your downloaded original JSON unchanged. To check a
partial review without revealing intended labels:

```bash
uv run python scripts/difficulty_reference.py validate-review \
  /path/to/difficulty-review-keith.json
```

Only after all 30 independent ratings are finished, archive/commit the original
human JSON as a dated review record, then create the separate comparison report:

```bash
uv run python scripts/difficulty_reference.py compare-review \
  /path/to/difficulty-review-keith.json \
  --output .artifacts/difficulty-reference-comparison.json
```

The command rejects incomplete reviews, stale item/rubric/packet hashes and
unattested reviews. Reviewed unknown labels are allowed with reasons. Comparison
keeps estimates separate from requests and applies `matches`, `too_easy`,
`too_hard` or `uncertain`, retaining low confidence and alternatives that change
the match decision. The output records the original review hash and explicitly
marks the single-reviewer reference, unavailable human–human agreement and absent
learner-performance evidence. It does not rewrite ratings or adjudicate them.

## Remaining evidence and issue status

Technical verification: 30/30 supported concrete questions with execution-verified
answers and distinct options; 15 families, with 18 development/12 held-out items.
Human review: 0/30 completed at delivery. Distractor plausibility, task-demand
levels and confirmed reference match decisions remain pending. No learner
responses, response times or option-selection frequencies were collected.

Issue 42 stays open until the actual human review and any repairs are recorded.
The development/held-out manifest is ready; issue 43 must tune only on development
families and freeze its judge/prompt/settings before scoring held-out families.
No automated judge, held-out agreement statistics or calibration claim is part
of this change. If held-out results later inform tuning, disclose that inspection
and use fresh held-out families for the next evaluation.
