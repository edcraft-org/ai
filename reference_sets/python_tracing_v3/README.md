# Python tracing reference set v3

Prepared for [issue 42](https://github.com/edcraft-org/ai/issues/42), using the
unchanged `python-tracing-v0.2` rubric and `manual-tracing-v0.1` conditions.
There are **30 distinct programs, with six new provisional hard candidates**.
Keith's decisions on 24 unchanged complete questions and their exact AI proposals
carry forward. **Only the six replacements need review.** AI recommendations do
not count as completed human ratings.

## Why these six changed

The [v2 audit](../python_tracing_v2/quality-audit-2026-10-15.json) found that the
three old hard questions had counting or answer-option shortcuts. Keith requested
six hard candidates, replacing those three plus three easier items. Each new
question requires following dependencies that affect its actual answer; code
length, concept count and execution counts alone do not establish difficulty.

Question numbers are version-specific; the mapping below prevents confusing old
approvals with new questions.

| V2 question | V3 question | Replacement focus | Split |
| --- | --- | --- | --- |
| Q11 | Q01 | Coupled arithmetic updates and running result | Development |
| Q14 | Q23 | Nested subtotal resets, total and carry feedback | Reserved |
| Q19 | Q29 | State-dependent guarded loop invocations | Development |
| Q22 | Q11 | Interacting conditional chains, reset and swap | Reserved |
| Q24 | Q20 | List swaps, score timing and tail mutation | Development |
| Q30 | Q12 | Branching recursion with return-dependent arguments | Reserved |

All six are newly authored by Codex, with explicit AI provenance. They are not
attributed to CRUXEval and are not human-labelled source questions. The separate
AI proposals include four dimension ratings, a worked solution, concepts,
option-by-option reasons and a shorter-solution caveat. Each proposes **hard with
medium as an alternative**, at medium confidence. Please correct a candidate if
its shortest sound solution makes medium more appropriate; the target mix must
not determine your rating. Difficulty is not a sum of dimension scores.

The projected primary mix is **13 easy, 11 medium and six hard**: the first 24
are retained human estimates; the last six are unapproved AI estimates. This is
not a completed human reference or learner-calibrated distribution. The retained
human decisions comprise 23 approvals and one correction, with original notes,
confidence, alternatives and ratings preserved. The other two historical
corrections concern replaced questions and remain in v2's original review.

## Verification and provenance

All 30 designated answers are execution-verified and the four options of each
question are distinct and type-compatible. Each new candidate has three wrong
options reproduced by specific code mutations representing hypothetical tracing
mistakes. Both the original programs and all 18 selected mutations were checked
in a separate bounded Python process as well as the tracing worker. These checks
establish answer consistency, not difficulty or observed student misconceptions.

`replacement-audit-2026-10-15.json` records the six old/new identities and hashes,
verified answers, worked trace observers, mutation programs and their outputs.
Observer rows copy the list at each stage rather than retaining aliases to its
final contents. The loop-invocation question explicitly counts each reached loop
statement, including the outer loop, rather than individual body iterations.

The 24 retained questions include 13 unchanged source programs from
[CRUXEval](https://github.com/facebookresearch/cruxeval), pinned to
`190faf16d175b5847b0af05d937872b1fb395942`. Their original source records, MIT notice,
file/record hashes and provenance remain in `sources/`. CRUXEval supplies program
input/output examples, not human difficulty labels. Two replaced source records
remain archived in v2. Public source items may have appeared in model training.

There is one complete question per family. Verification rejects normalized AST
clones after removing local names, literal values and formatting, and
`curation-audit.json` records distinct reasoning patterns. This screen is not
proof of semantic independence. The five topics each retain six questions; all
five answer targets remain represented. There are 18 development and 12 reserved
items. Replacements inherit the topic and split of the removed question, giving
three new candidates in each split. Retained families never move between splits.

V3 was selected after inspecting v2 human ratings and both splits for quality.
This is deliberate curation for coverage, not a fresh independent sample. No
judge has been tuned using this collection. Tune only on development families,
freeze the judge before reserved scoring, and disclose any reserved results used
for tuning; fresh reserved families are then needed for an independent estimate.

## Review the six pending items

Use a fresh output folder so earlier saved exports remain intact:

```bash
uv run python scripts/difficulty_reference.py carry-review \
  --source-set reference_sets/python_tracing_v2 \
  reference_sets/python_tracing_v2/reviews/keith-2026-10-15-final.json \
  --output .artifacts/difficulty-review-keith-v3
uv run python scripts/difficulty_reference.py prepare-review \
  --reviewer keith --assisted --output .artifacts/difficulty-review-keith-v3
```

Open `review.html`. The form starts at the first pending question. **Next
unreviewed** visits the six replacements; 24 carried decisions already count as
reviewed. Approve, correct or mark uncertain. Only corrections and abstentions
need a brief human note. The requested levels stay hidden. Save with **Download
ratings** or **Show ratings JSON**. Browser storage is a convenience; the exported
review becomes the versioned record after validation.

```bash
uv run python scripts/difficulty_reference.py verify
uv run python scripts/difficulty_reference.py validate-review \
  reference_sets/python_tracing_v3/reviews/keith-2026-10-15-carried.json
```

The CLI defaults to v3. `compare-review` rejects this partial review until the six
new items have explicit human decisions. Once completed, compare the frozen
export against authoring requests; alternatives that change the comparison keep
`uncertain`. Never convert a pending AI proposal into a human rating.

The original [v1](../python_tracing_v1/README.md) and
[v2](../python_tracing_v2/README.md) questions, proposals, original human uploads,
comparisons and audits remain unchanged. Use `--set reference_sets/python_tracing_v2`
before the command when reproducing v2 workflows. Carry-forward checks full
question hashes, exact AI records, rubric, conditions and assistance disclosure;
opaque question numbers alone cannot authorize reuse.

## Files and limits

- `questions.json` and `manifest.json`: concrete MCQs, answers, topic/family/split,
  source provenance, requested levels and distractor hypotheses.
- `technical-evidence.json`: verified answers, counters and collection hashes.
- `ai-recommendations.json`: separate provisional AI judgments and explanations.
- `reviews/keith-2026-10-15-carried.json`: 24 human decisions and six pending items.
- `reviews/carry-forward.json`: exact source review hash and old/new review mapping.
- `replacement-audit-2026-10-15.json`: executable evidence for the six replacements.
- `curation-audit.json` and `sources/`: clone-screen evidence and source attribution.

This remains an AI-assisted, single-reviewer reference. Independent human
agreement and learner correctness, timing and option-selection data are
unavailable. Technical checks cannot establish difficulty. PR #83 remains draft
until the six replacements are reviewed. Runtime judging and empirical agreement
are separate [issue 43](https://github.com/edcraft-org/ai/issues/43) work.
