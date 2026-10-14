# Python tracing reference set v2

Prepared for [issue 42](https://github.com/edcraft-org/ai/issues/42), using
`python-tracing-v0.2`, `manual-tracing-v0.1` and
`python-tracing-agreement-v0.2`. This is a **provisional, AI-assisted,
single-human-review reference**, not a training dataset or learner-calibrated
benchmark. Technical execution establishes correct answers, not difficulty.

## What changed after Keith's review

The previous 30-item collection contained only 15 distinct programs, with two
variants each. Keith identified repetition during his review. V2 keeps one
unchanged question per original family and adds 15 distinct programs adapted from
[CRUXEval](https://github.com/facebookresearch/cruxeval). The primary collection
now has **30 distinct programs and normalised AST families**, six per topic:
arithmetic, conditionals, loops, functions and lists. String-based examples extend
existing Python semantics; the topic identifies the main demand, not every construct.

The original v1 collection, evidence, recommendations and Keith's complete
[review](../python_tracing_v1/reviews/keith-2026-10-15.json) remain versioned.
The original uploaded review is preserved byte-for-byte: 28 approvals and two
corrections. Both corrected questions are retained. Otherwise retention prefers
the sibling without a repetition concern, then the `-01` sibling; it does not
select on the human difficulty label. The 15 excluded siblings are also listed in
`robustness-variants.json` for optional within-family checks. They are excluded
from the primary set and its independent-item counts.

**15 ratings carry forward; 15 new items still need Keith's confirmation.** Only
unchanged complete questions with exact unchanged AI proposals are eligible for
carry-forward. Original human notes, confidence, alternatives and both corrections
are preserved; opaque question numbers may change. The initial partial review and
old-to-new mapping are in `reviews/`. No AI proposal becomes a completed human
rating without a per-item decision. New or edited questions/proposals stay pending.

## Sources and duplication checks

The external source is pinned to CRUXEval revision
`190faf16d175b5847b0af05d937872b1fb395942`. The original 15 source records,
MIT copyright/permission notice and provenance are vendored in `sources/`.
Each adaptation records its source ID, permalink, revision, file and record hashes,
licence, concrete-input changes and added question/options. **Source Python is
unchanged byte-for-byte.** Verification rejects modified source records, source
code or licence evidence. Concrete inputs and answers are verified locally.

CRUXEval contains 800 Python functions and input/output pairs. Its functions and
inputs were generated with Code Llama 34B, and its outputs obtained by execution.
It supplies neither MCQ options nor human difficulty labels. We screened for the
supported subset and input/output shapes, finding 48 compatible candidates, then
selected 15 different reasoning patterns. Some trivial original inputs were
replaced so the question exercises its relevant behaviour. Original source inputs
and outputs remain separate from our adapted concrete questions.

The primary set permits one question per declared family. Verification also rejects
clones after removing formatting, bound identifier names and literal values while
preserving operators, built-ins and statement structure. `curation-audit.json`
records fingerprints and the separate AI-assisted review of reasoning patterns.
This is a clone screen, **not proof of semantic independence**. Shared concepts are
expected. Public source questions may have appeared in model training; external
sourcing does not establish an uncontaminated model benchmark.

## Split and evidence

There are 18 development and 12 reserved questions. Retained families keep their
original split; nine new families are development and six reserved, assigned
before their AI recommendations. V2 was constructed after the v1 human review;
this is disclosed rather than described as a fresh independent sample. No judge
has been tuned using the collection. Do not alter split membership in response to
ratings. Optional sibling variants retain their family's assignment.

All five answer targets remain represented: returns, evaluated conditions, loop
iterations, loop invocations and function calls. New CRUXEval adaptations ask for
return values. Counter wording and technical conventions are unchanged. The
collection remains separate from the 15 frozen authoring requests in `profiles.py`.

- `questions.json`: complete concrete MCQs, including ordered options and answers.
- `manifest.json`: family, split, topic, authoring request, sources and distractor
  hypotheses. Requested levels are intentions, not reference labels.
- `technical-evidence.json`: execution-verified answers, trace counts and hashes.
- `ai-recommendations.json`: separate Codex proposals, reasons, concepts, solutions,
  option explanations, shortcuts and uncertainty for all 30 questions.
- `reviews/keith-2026-10-15-carried.json`: initial partial v2 review, 15 confirmed and
  15 pending. It does not replace Keith's eventual exported review.
- `reviews/carry-forward.json`: source-review hash and per-item transfer audit.

The 15 new proposals are provisional. In particular, growing-string indexing can
be answered from the first two updates with these options, pair-counting admits
shortcuts, and an apparently changing counter has a simplifying invariant. These
features are included in the explanations rather than equated with high difficulty.
The recursive string question has a proposed `hard` level with `medium` retained
as an alternative. Retained human corrections can differ from the AI proposals.
No category balance is imposed. Difficulty is not a sum of dimension ratings.

## Verify and continue reviewing

From the repository root:

```bash
uv run python scripts/difficulty_reference.py verify
uv run python scripts/difficulty_reference.py validate-review \
  reference_sets/python_tracing_v2/reviews/keith-2026-10-15-carried.json
```

The CLI defaults to v2. Use `--set reference_sets/python_tracing_v1` before the
command to validate historical v1 records. Evidence and all review hashes are
version-specific; do not copy old opaque question numbers into a new packet.

Reproduce the initial partial review in a **new** output directory:

```bash
uv run python scripts/difficulty_reference.py carry-review \
  --source-set reference_sets/python_tracing_v1 \
  reference_sets/python_tracing_v1/reviews/keith-2026-10-15.json \
  --output .artifacts/difficulty-review-keith-v2
uv run python scripts/difficulty_reference.py prepare-review \
  --reviewer keith --assisted --output .artifacts/difficulty-review-keith-v2
```

`carry-review` refuses to overwrite an existing review. `prepare-review` preserves
a saved review of the same format. Open the generated `review.html` and use
**Next unreviewed** to visit the 15 new questions. The form starts at the first
pending item and shows that earlier decisions were retained. Approve, correct or
mark uncertain; only corrections/abstentions need a short human note. Requested
levels remain hidden. Save using **Download ratings** or **Show ratings JSON**.
Browser storage is a convenience, not the versioned record. No network or model
calls occur from the review page.

The short independent form remains available without `--assisted`; original
review formats are still accepted. AI-assisted records cannot be relabelled as
independent blind human judgments. Carry-forward requires the same rubric,
conditions, assistance disclosure and exact per-item proposals.

After all new decisions are completed, preserve the exported original JSON as a
new dated review record, validate it, and only then create a comparison:

```bash
uv run python scripts/difficulty_reference.py compare-review \
  /path/to/exported-review.json --output .artifacts/reference-comparison-v2.json
```

The comparison rejects pending or stale reviews and keeps requested difficulty
separate from estimated difficulty. Confidence and alternatives retain `uncertain`
where appropriate. Agreement with these AI-assisted, human-checked labels measures
consistency with that process, not independent human accuracy or observed learner
performance. Human–human agreement and learner correctness/timing/option-selection
data remain unavailable. A reviewer unexposed to the proposals is needed for an
independent human benchmark.

Issue 42 stays open until the 15 new human decisions and any question repairs are
recorded. Runtime judging and held-out scoring remain issue 43 work: tune only on
development families and freeze the judge before reserved scoring. If reserved
results inform tuning, disclose that inspection and use fresh reserved families.
