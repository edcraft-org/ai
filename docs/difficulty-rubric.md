# Provisional Python tracing difficulty rubric

Rubric version: `python-tracing-v0.1`. Audience version: `intro-python-v0.1`.

Use this rubric to estimate the difficulty of a complete Python tracing MCQ for
the audience below. Assess the code, concrete input, question target, and all
answer options together. Estimates are advisory: they cannot override failed
correctness checks or supply missing technical evidence. The rubric defines the
review procedure for [issue 41](https://github.com/edcraft-org/ai/issues/41);
reference-set curation and automated judging follow in issues
[42](https://github.com/edcraft-org/ai/issues/42) and
[43](https://github.com/edcraft-org/ai/issues/43).

## Audience and scope

The audience is students taking introductory Python who have been taught:

- Variables, sequential assignment, integers, booleans, strings, and integer lists.
- Arithmetic including precedence, `%` and `//`, comparisons, and boolean operators.
- `if/else`, early returns, bounded `for` loops, and exclusive upper bounds in `range`.
- List indexing and iteration, and the meaning of `len`, `sum`, `min`, `max`, and
  `sorted` when used in a question.
- Top-level helper functions, parameters, local variables, and return values.

Assume learners can use scratch paper or a memory table but cannot run the code,
use a calculator, or consult an AI assistant. Assess an untimed practice question;
record time limits or supplied scaffolding as a different assessment condition.
An unfamiliar operator is a prerequisite mismatch, not evidence for a higher level.
Scratch-paper conditions matter because tracing strategies can change performance
([Xie, Nelson and Ko, 2018](https://www.benjixie.com/publication/sigcse-2018/sigcse-2018.pdf)).

Scope covers return values and explicitly defined counts of branches, loop
iterations, loop executions, or function calls, within the application's supported
Python subset. Templates currently have at most 64 finite input combinations.
Technical support is established by existing checks, not by this rubric. Recursion
can pass those checks but is outside this audience's prerequisites; judging it
requires an audience and rubric revision. Imports, I/O, networking, exceptions as
the requested answer, and unsupported language constructs are outside this rubric.

For count questions, state exactly what counts. Distinguish a loop invocation from
an iteration; specify whether entry, helper, and built-in calls count; distinguish
an evaluated condition from a taken branch. The stem and execution-derived answer
must use the same convention. Ambiguous count wording requires repair.

## Difficulty labels and evidence

The application uses `easy`, `medium`, and `hard`. Issue 41 describes the equivalent
audience-relative terms `beginner`, `intermediate`, and `advanced`:

| Stored assessment label | Issue terminology |
| --- | --- |
| `easy` | beginner |
| `medium` | intermediate |
| `hard` | advanced within introductory Python |

Use the application labels in review records. This documentation mapping does not
change request schemas or infer the estimate from the requested label.

| Evidence | Meaning |
| --- | --- |
| Requested difficulty | The author's intent, retained unchanged and hidden while rating. |
| Estimated difficulty | A reviewer or judge's provisional assessment for a named audience and rubric version. |
| Observed learner performance | Actual learner correctness, response times, or option selections under recorded conditions; absent until collected. |

Technical correctness, educational difficulty, and question quality are separate.
Distinct wrong answers do not establish plausible distractors. A correct question
may still have poor wording or options. Record those quality concerns separately.

## Dimensions and evidence to record

Rate each dimension `low`, `moderate`, or `high`, or `unknown` if evidence is
insufficient. These categories organise explanations; do not sum them or apply a
weighted formula to produce a difficulty score. The operational anchors below are
EdCraft conventions, not calibrated thresholds or claims of measured cognitive load.

| Dimension | Low | Moderate | High |
| --- | --- | --- | --- |
| Execution and reasoning burden | A short direct calculation or simple trace. | Repeated updates or several decisions need a small organised trace. | Sustained bookkeeping, changing paths, or repeated call/return transitions need a substantial trace. |
| Changing state | Few values with a short dependency chain. | An accumulator or local values change and must be carried forward. | Coupled values, repeated resets, or values across execution contexts must be coordinated. |
| Conceptual interaction | One taught rule, or mostly independent rules. | One construct controls another, such as a condition selecting an update inside a loop. | Several dependencies recur together, such as changing inner bounds and accumulator lifetimes, or previous state controlling later decisions. |
| Answer discrimination | A basic semantic check distinguishes the options. | Rejecting plausible options requires a particular taught rule or local update. | Rejecting plausible options requires coordinating several decisions or updates. |

### Execution and changing state

Describe a correct solution for the concrete input and identify the operations,
iterations, conditions, and calls relevant to the answer. State which values change,
which depend on earlier values, and where resets or scope changes occur. Separate
raw execution counts from the work a learner needs: an obvious `range(n)` count may
be answered without tracing every iteration. Include accessible shortcuts and
explain why any irrelevant statements can be ignored.

Trace summaries can support the explanation, but event counts, variable snapshot
counts, code length, and syntax features are not direct measurements of mental
effort. Increasing a loop from four to many iterations can increase execution
burden without introducing a new conceptual interaction.

### Conceptual interaction

Identify the taught rules that matter to the requested answer, then explain their
dependencies in plain language. For example: parity selects a branch; the branch
selects an accumulator update; successive updates determine the returned value.
Record actual execution and any structural rule the learner must understand, even
if some paths are skipped. Mere presence of a nested construct is insufficient.

Use `low` for direct or separable rules, `moderate` for a meaningful coupling, and
`high` when several dependencies must be coordinated repeatedly. Specify the
dependency behind the rating. Two independent loops are not automatically high;
two coupled updates can be demanding even in short code. This emphasis on
interacting information follows cognitive load theory
([Sweller, 2010](https://link.springer.com/article/10.1007/s10648-010-9128-5));
the category boundaries remain provisional EdCraft choices.

### Answer discrimination

For each distractor, record the following:

| Field | Required explanation |
| --- | --- |
| Incorrectness | The option is distinct from the execution-verified answer and other options. |
| Error rule | A specific erroneous interpretation or trace that produces the value, if one is identifiable. |
| Plausibility evidence | `hypothesised`, `reviewer_supported`, or `learner_observed`, with the supporting reason or evidence reference. |
| Distinction | The rule or state dependency that eliminates this option. |
| Cue | Any wording, type, magnitude, formatting, or other shortcut that bypasses the intended skill. |

Assign the dimension from the easiest defensible way to distinguish the correct
answer from the actual options. Do not rate it high merely because distractors are
numerically close. Unsupported error rules get an explicit concern; ambiguous or
misleading options require repair rather than a higher difficulty label.
Alternative erroneous execution paths are useful distractor hypotheses
([Thomas et al., 2019](https://www2.seas.gwu.edu/~simha/research/andy-sigcse.pdf)),
but producing such a value does not prove learners commonly make that error.

Here answer discrimination means option-distinguishing demand. Statistical item
discrimination, such as a corrected item-total correlation, requires learner data
and is deferred with calibration.

## Overall levels and uncertainty

| Level | Anchor description |
| --- | --- |
| `easy` | A short trace or direct inference using taught rules, with little changing state and limited coordination. A simple loop or helper may occur. |
| `medium` | A small organised trace coordinates repeated state updates, a construct combination, or straightforward call/return reasoning. |
| `hard` | A substantial trace or several interacting dependencies require sustained coordination within the stated prerequisites. |

Choose the closest worked anchor and explain both the similarities and material
differences. Use the relevant solution and options together. A single high dimension
does not force `hard`; a shortcut or weak options can lower the complete MCQ's
demand. Conversely, a long repetitive question may have high burden and low
interaction. Explain the deciding evidence rather than counting high ratings.

Record confidence as `high` (clear anchor match), `moderate` (adjacent boundary),
or `low` (material ambiguity). Confidence is a qualitative judgment, not a calibrated
probability. Preserve an adjacent alternative level for borderline questions.
Use `estimated_difficulty: null` for an unresolved judgment; record the reason:
`missing_evidence`, `prerequisite_mismatch`, `ambiguous_question`,
`unsupported_case`, or `unresolved_boundary`. A failed technical check leaves
the question ineligible for difficulty assessment. Do not default unknowns to medium.

## Worked anchors

These original examples are reviewer training material, not held-out reference
items. The levels illustrate the rubric and are not independent human labels.
The stems ask for return values unless explicitly stated otherwise.

### Easy arithmetic

```python
def f(x):
    y = x + 2
    return y * 2
```

What does `f(3)` return? A: `6`, B: `7`, C: `10`, D: `12`.

Answer: C, `10`. First `y = 5`, then `5 * 2 = 10`. All four dimensions are low:
the trace is short and requires only sequential evaluation. The hypothesised error
rules are using `x * 2` (6), calculating `x + 2 * 2` (7), and incorrectly using
`x + 3` for the first assignment (12). The last is an arithmetic slip, with weaker
pedagogical support; retain that option-quality concern without inflating difficulty.

### Medium conditional accumulation

```python
def f(values):
    total = 0
    for x in values:
        if x % 2 == 0:
            total += x
        else:
            total -= 1
    return total
```

What does `f([1, 2, 3, 4])` return? A: `4`, B: `6`, C: `8`, D: `10`.

Answer: A, `4`. The totals after the four iterations are `-1`, `1`, `0`, `4`.
Burden, state, interaction, and answer discrimination are moderate: parity controls
each update and the accumulator carries the result forward. Hypothesised errors
are ignoring odd values (6), adding one for odd values (8), and summing all values
(10). Eliminating these options requires understanding the conditional updates.

Changing the target changes the MCQ: "How many iterations of the `for` loop occur
when `f([1, 2, 3, 4])` executes? A: 2, B: 3, C: 4, D: 6" has answer C and is an
easy variant. The learner can count the list elements; no accumulator trace is
needed. These are separate questions despite sharing code and inputs.

### Hard nested accumulation

```python
def f(n):
    total = 0
    for i in range(1, n + 1):
        subtotal = 0
        for j in range(i):
            subtotal += i + j
        total += subtotal
    return total
```

What does `f(3)` return? A: `14`, B: `18`, C: `25`, D: `30`.

Answer: B, `18`. For `i = 1`, subtotal is 1; for `i = 2`, it is `2 + 3 = 5`;
for `i = 3`, it is `3 + 4 + 5 = 12`. Total is `1 + 5 + 12 = 18`.
Execution burden is moderate; changing state, interaction, and answer discrimination
are high. Inner bounds depend on `i`; subtotal resets while total persists; the
options require distinguishing these dependencies. Omitting `j` produces 14,
failing to reset subtotal produces 25, and using `range(i + 1)` produces 30.
These error rules are hypotheses, not observed learner misconceptions.

For count targets, the outer loop has 3 iterations and the inner loop has 6 across
3 invocations: 9 total iterations and 4 total loop invocations. A count stem must
say whether it includes both loops; it cannot reuse the return-value answer.

Changing `n` to 0 produces 0 without entering the outer loop and substantially
reduces the relevant reasoning. Also, the return-value distractor recipes above
would collide at that input. Recheck options and rate the complete concrete MCQ;
the `hard` anchor is specifically the `n = 3` question.

## Reviewer procedure and records

1. Confirm execution-derived answer evidence, distinct valid options, and a clear
   stem. Repair ineligible cases before rating; retain their rejection reasons.
2. Hide requested difficulty, generator identity, generator explanations, and other
   ratings. Show the audience, complete MCQ, and separately identified verified
   answer/trace evidence. Reviewers may use the answer to check their solution;
   learners do not receive it. Generator distractor claims are not review evidence.
3. Explain the relevant solution, dependencies, accessible shortcuts, and each
   distractor. Record dimension ratings, nearest anchor, overall level, confidence,
   alternatives, and quality concerns independently.
4. Preserve original ratings before discussing disagreements. Record any adjudicated
   label and explanation separately; an unresolved reference remains unknown.

Store records in versioned files. The following fields describe the intended
review record; they do not add fields to existing runtime schemas:

| Record group | Fields to preserve |
| --- | --- |
| Identity and question | Question ID, template/code family, artifact/source revision, code, concrete inputs, seed if available, exact stem, ordered options, verified answer, answer target, and technical evidence reference. |
| Assessment context | Rubric and audience versions, prerequisites, aids, timing/scaffolding, reviewer ID/date or model/provider/settings/prompt version. |
| Judgment | Four dimension ratings with reasons, option evidence table, closest anchor, estimated difficulty or null, confidence, alternative levels, uncertainty reason, and quality concerns. |
| Separate evidence | Requested difficulty in a blinded provenance record; observed learner performance null until measured; independent ratings and later adjudication retained separately. |
| Evaluation | Development/held-out membership, family ID, protocol version, and code/option revisions. |

Increment the rubric version when dimensions, anchors, level decisions, or review
conditions change. Record a source revision or content hash to identify the exact
rubric text. Audience changes also require a new audience version. Code, input,
target, wording, or option edits invalidate the previous concrete assessment;
preserve it as history and recheck/review the edited question.

## Concrete questions and template variation

Rate concrete questions first. A template's requested label is not evidence that
every expansion has that difficulty. Input values can change paths, iterations,
state interactions, and distractor validity; seeds can select identical inputs.

Enumerate the declared domain for technical checks and available execution
descriptors. For educational review, select distinct cases with different paths,
minimum/maximum burdens, early returns, and changing option distinctions. Record
the reviewed input combinations, their levels, and coverage out of the full domain.
Describe the observed level range; keep unreviewed educational difficulty unknown.
Neither structural screening nor exhaustive correctness establishes exhaustive
difficulty coverage. Do not present a sampled maximum as a template-wide bound.

## Predeclared agreement protocol

Protocol version: `python-tracing-agreement-v0.1`. Declare the following before
held-out judging. Subsequent protocol changes require a new version and disclosure.

- Issue 42 targets about 30 complete questions, approximately 18 development and
  12 held out. Split by underlying template/code family before rubric/prompt tuning;
  keep parameter variants, altered targets, and option variants from one family
  together. Keep training anchors in development only and the reference set
  separate from the frozen authoring requests used for provider comparison.
- Cover all five supported topics and varied intended levels without forcing the
  reviewed labels into equal groups. Freeze the item/family manifest and rubric.
  Issue 43 additionally freezes the judge prompt, model/settings, and repeat policy
  using only development items before held-out scoring. The primary comparison
  uses one scheduled judgment per item; exploratory repeats stay separate and
  cannot replace a failed or disagreeing primary result.
- Use two independent human reviewers where available. If only one participates,
  disclose single-reviewer reference labels; human-human agreement is unavailable.
  Multiple model calls do not supply a second human reviewer.

| Comparison or metric | Predeclared reporting rule |
| --- | --- |
| Human-human agreement | Use original independent ratings, before adjudication. For two reviewers, report exact matches divided by items both labelled. For more, report pairwise counts and each pair's denominator. |
| Ordinal Krippendorff alpha | Use ordered easy/medium/hard categories and an ordinal disagreement function. Treat unknowns as missing, not a fourth level; report the number of items with at least two labels. Do not substitute interval distance or tune the metric after seeing results. |
| LLM-reference agreement | Compare the frozen judge's primary estimate with the separately adjudicated human reference, or disclosed single-reviewer reference. Report exact matches over jointly labelled eligible items and matches over all eligible items with known references; unknown/malformed judge results are nonmatches in the latter. |
| Confusion and severe disagreements | Report full 3 by 3 counts with axes identified and easy-to-hard/hard-to-easy counts. Show unknowns and malformed responses separately. |
| Coverage | Report total collected, technically eligible, reference-labelled, judge-labelled, and jointly labelled counts; reasons for every exclusion or unknown. Report each human's abstentions too. |
| Dimension agreement | Report exact-match counts for each dimension where both reviewers supplied a rating and preserve representative evidence disagreements. |
| Uncertainty | Report 95% confidence intervals where estimable, resampling whole code families rather than treating variants as independent. With too few families or no category variation, mark the interval or alpha unavailable and explain why. |

Ordinal alpha is supported by
[Hayes and Krippendorff, 2007](https://doi.org/10.1080/19312450709336664).
Record the implementation/version, category order, family sampling method, random
seed, and 2000 bootstrap replicates. Report unavailable statistics explicitly rather
than replacing them with zero. Freeze the human reference before inspecting LLM
outputs, and do not rewrite reference labels to agree with the judge.

These metrics are descriptive; v0.1 does not impose a calibrated acceptance cutoff.
For 12 labelled held-out questions, one result changes exact agreement by about
8.3 percentage points. Report counts, category support, and disagreement examples.
Reviewer agreement establishes reproducibility of these estimates, not learner
validity. Stronger models or simulated student personas do not guarantee human
difficulty alignment
([Li et al., 2026](https://arxiv.org/abs/2512.18880)).

Use development disagreements to revise the rubric. If held-out results motivate a
revision, identify the old set as inspected and use fresh held-out families for a
new evaluation. Preserve uncertainty rather than moving cases to development
after observing disagreement. Broad Bloom classification, statistical distractor
effectiveness, student response calibration, and trained numerical estimators are
deferred. An LLM implementation and held-out agreement results are issue 43 work.
