# Provisional Python tracing difficulty rubric

Rubric version: `python-tracing-v0.2`.
Assessment conditions version: `manual-tracing-v0.1`.

Use this rubric to check whether a complete generated Python tracing MCQ matches
the user's requested difficulty. First assess the question independently, then
compare its estimated level with the request. Assess the code, concrete input,
question target, and all answer options together. Difficulty levels describe
EdCraft's provisional task-demand conventions under the conditions below, not
universal predictions of student performance. Results are advisory: they cannot
override failed correctness checks or supply missing technical evidence.
The rubric defines the review procedure for
[issue 41](https://github.com/edcraft-org/ai/issues/41);
reference-set curation and automated judging follow in issues
[42](https://github.com/edcraft-org/ai/issues/42) and
[43](https://github.com/edcraft-org/ai/issues/43).

## Assessment conditions and scope

Use manual tracing with scratch paper or a memory table, without executing code,
using a calculator, or consulting an AI assistant. Assess an untimed practice
question; record time limits or supplied scaffolding as a different assessment
condition. Assume the semantics used by the reference solution are understood;
describe those concepts and dependencies using evidence from the question. There
is no fixed student cohort or exhaustive knowledge catalogue. Tags can organise
descriptions but catalogue membership does not determine eligibility or level.
These assumptions standardise the task assessment; they do not establish what a
particular learner knows. Optional learner context must be recorded separately.
Scratch-paper conditions matter because tracing strategies can change performance
([Xie, Nelson and Ko, 2018](https://www.benjixie.com/publication/sigcse-2018/sigcse-2018.pdf)).

Scope covers return values and explicitly defined counts of branches, loop
iterations, loop executions, or function calls, within the application's supported
Python subset. Templates currently have at most 64 finite input combinations.
Technical support is established by existing checks, not by this rubric. Recursion
is technically supported within the finite execution limits; its presence does
not automatically imply `hard`. If a supported question cannot be related to the
anchors confidently, retain an uncertain assessment. Imports, I/O, networking,
exceptions as the requested answer, and unsupported language constructs are
outside this rubric.

For count questions, state exactly what counts. Distinguish a loop invocation from
an iteration; specify whether entry, helper, and built-in calls count; distinguish
an evaluated condition from a taken branch. The stem and execution-derived answer
must use the same convention. Ambiguous count wording requires repair.

## Difficulty labels and evidence

The application uses `easy`, `medium`, and `hard`. Issue 41 uses the terminology
`beginner`, `intermediate`, and `advanced`; the mapping below preserves the existing
request interface. This revision uses task-demand conventions rather than levels
of a fixed audience's proficiency:

| Stored assessment label | Issue terminology |
| --- | --- |
| `easy` | beginner |
| `medium` | intermediate |
| `hard` | advanced |

Use the application labels in review records. This documentation mapping does not
change request schemas or infer the estimate from the requested label.

| Evidence | Meaning |
| --- | --- |
| Requested difficulty | The author's target, retained unchanged and hidden during independent level assessment; revealed for comparison afterward. |
| Estimated difficulty | A reviewer or judge's provisional level under the recorded rubric and assessment conditions. |
| Difficulty match | `matches`, `too_easy`, `too_hard`, or `uncertain`, derived from the request and assessment as defined below. |
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
| Conceptual interaction | One semantic rule, or mostly independent rules. | One construct controls another, such as a condition selecting an update inside a loop. | Several dependencies recur together, such as changing inner bounds and accumulator lifetimes, or previous state controlling later decisions. |
| Answer discrimination | A basic semantic check distinguishes the options. | Rejecting plausible options requires a particular semantic rule or local update. | Rejecting plausible options requires coordinating several decisions or updates. |

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

Identify the semantic rules that matter to the requested answer, then explain their
dependencies in plain language. For example: parity selects a branch; the branch
selects an accumulator update; successive updates determine the returned value.
Record actual execution and any structural rule the learner must understand, even
if some paths are skipped. Mere presence of a nested construct is insufficient.

Use `low` for direct or separable rules, `moderate` for a meaningful coupling, and
`high` when several dependencies must be coordinated repeatedly. Specify the
dependency behind the rating. Two independent loops are not automatically high;
two coupled updates can require coordination even in short code. Cognitive load
theory motivates examining interacting information
([Sweller, 2010](https://link.springer.com/article/10.1007/s10648-010-9128-5));
but experienced cognitive load also depends on prior knowledge. The structural
categories here remain provisional EdCraft conventions, not audience-free
measurements of mental effort.

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
| `easy` | A short trace or direct inference using the question's semantic rules, with little changing state and limited coordination. A simple loop or helper may occur. |
| `medium` | A small organised trace coordinates repeated state updates, a construct combination, or straightforward call/return reasoning. |
| `hard` | A substantial trace or several interacting dependencies require sustained coordination under the stated assessment conditions. |

Choose the closest worked anchor and explain both the similarities and material
differences. Use the relevant solution and options together. A single high dimension
does not force `hard`; a shortcut or weak options can lower the complete MCQ's
demand. Conversely, a long repetitive question may have high burden and low
interaction. Explain the deciding evidence rather than counting high ratings.

Record confidence as `high` (clear anchor match), `moderate` (adjacent boundary),
or `low` (material ambiguity). Confidence is a qualitative judgment, not a calibrated
probability. Preserve an adjacent alternative level for borderline questions.
Use `estimated_difficulty: null` for an unresolved judgment; record the reason:
`missing_evidence`, `ambiguous_question`,
`unsupported_case`, or `unresolved_boundary`. A failed technical check leaves
the question ineligible for difficulty assessment. Do not default unknowns to medium.

## Matching the requested difficulty

After the independent assessment is recorded, reveal the unchanged requested
level and compare using the order `easy < medium < hard`. For a resolved assessment:

| Estimated level | Requested easy | Requested medium | Requested hard |
| --- | --- | --- | --- |
| `easy` | `matches` | `too_easy` | `too_easy` |
| `medium` | `too_hard` | `matches` | `too_easy` |
| `hard` | `too_hard` | `too_hard` | `matches` |

Use `uncertain` when the estimate is null, confidence is low, or a plausible
alternative level would change the comparison outcome. Alternatives entirely
below or above the request can support a directional mismatch if confidence is
at least moderate; explain the boundary. Never replace an uncertain assessment
with a confident match merely because the primary label equals the request.
For example, estimated medium with a plausible hard alternative and a requested
hard level is uncertain, while medium/easy alternatives both fall below hard.

Record the requested level, estimated level, match result, comparison reason,
uncertainty, and an optional suggested revision. For a requested easy question,
the hard nested-accumulation anchor below is `too_hard`: changing inner bounds,
subtotal resets, and a persistent total require sustained coordination. A
suggested revision is to simplify those dependencies while retaining the requested
topic or learning objective. This is advice, not automatic code modification.

A technical failure is ineligible for this comparison and has no match result;
record its correctness outcome separately. An unavailable or malformed judge
response is a recorded failure, not evidence of a match. In a later authoring
workflow, confirmed mismatches can inform revision and rechecking; uncertain
cases need review. Implementing the judge and comparison belongs to issue 43.

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
   ratings. Show the assessment conditions, complete MCQ, and separately identified
   verified answer/trace evidence. Reviewers may use the answer to check their solution;
   learners do not receive it. Generator distractor claims are not review evidence.
3. Explain the relevant solution, dependencies, accessible shortcuts, and each
   distractor. Record dimension ratings, nearest anchor, overall level, confidence,
   alternatives, and quality concerns independently.
4. Preserve original ratings before discussing disagreements. Record any adjudicated
   label and explanation separately; an unresolved reference remains unknown.
5. Reveal the requested difficulty and apply the comparison rule to the frozen
   independent assessment. Retain the level estimate even when it mismatches the
   request; record matching reasons and optional revision advice separately.

Store records in versioned files. The following fields describe the intended
review record; they do not add fields to existing runtime schemas:

| Record group | Fields to preserve |
| --- | --- |
| Identity and question | Question ID, template/code family, artifact/source revision, code, concrete inputs, seed if available, exact stem, ordered options, verified answer, answer target, and technical evidence reference. |
| Assessment context | Rubric and assessment conditions versions, concepts used by the reference solution with evidence, optional learner context, aids, timing/scaffolding, reviewer ID/date or model/provider/settings/prompt version. |
| Judgment | Four dimension ratings with reasons, option evidence table, closest anchor, estimated difficulty or null, confidence, alternative levels, uncertainty reason, and quality concerns. |
| Comparison | Unchanged requested difficulty, estimated level, difficulty match or null for an ineligible/failed assessment, comparison reason, uncertainty, and optional suggested revision. |
| Separate evidence | Requested difficulty hidden during level assessment and revealed afterward; observed learner performance null until measured; independent ratings and later adjudication retained separately. |
| Evaluation | Development/held-out membership, family ID, protocol version, and code/option revisions. |

Increment the rubric version when dimensions, anchors, level decisions, or review
conditions change. Record a source revision or content hash to identify the exact
rubric text. Changes to aids or timing require a new assessment conditions version.
Code, input, target, wording, or option edits invalidate the previous concrete assessment;
preserve it as history and recheck/review the edited question.

## Concrete questions and template variation

Rate concrete questions first. A template's requested label is not evidence that
every expansion has that difficulty. Input values can change paths, iterations,
state interactions, and distractor validity; seeds can select identical inputs.

Enumerate the declared domain for technical checks and available execution
descriptors. For rubric review, select distinct cases with different paths,
minimum/maximum burdens, early returns, and changing option distinctions. Record
the reviewed input combinations, their levels, and coverage out of the full domain.
Describe the reviewed level range; keep unreviewed rubric levels unknown.
Neither structural screening nor exhaustive correctness establishes exhaustive
difficulty coverage. Do not present a sampled maximum as a template-wide bound.
Report match outcomes for reviewed cases against the template's requested level.
A sampled `matches` result cannot establish that every possible expansion matches.

## Predeclared agreement protocol

Protocol version: `python-tracing-agreement-v0.2`. Declare the following before
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

Freeze human level ratings, confidence, and alternatives before revealing requested
labels. Then derive reference match outcomes using the same comparison rule as
the judge, preserving `uncertain` outcomes rather than forcing acceptance/rejection.
The primary matching evaluation measures conformity to the requested rubric level,
not observed student difficulty. Level agreement remains supporting evidence.

| Comparison or metric | Predeclared reporting rule |
| --- | --- |
| Match-decision accuracy | Report correct `matches`/`too_easy`/`too_hard`/`uncertain` decisions divided by all technically eligible items with a recorded human reference decision. Missing/malformed judge responses count as incorrect; include a 4 by 4 decision confusion table and report those failures separately. |
| False acceptance | Judge says `matches` when the reference says `too_easy` or `too_hard`; report the count and rate over all confirmed reference mismatches. |
| False rejection | Judge says `too_easy` or `too_hard` when the reference says `matches`; report the count and rate over all confirmed reference matches. |
| Uncertainty and decision coverage | Report judge and reference uncertain counts, judge non-uncertain valid decisions divided by eligible items with reference decisions, and failed-response counts. Separate judge matches/mismatches on uncertain references from confirmed false acceptance/rejection; do not discard uncertain cases from primary accuracy. |
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

For an empty false-acceptance or false-rejection denominator, report the rate as
unavailable with its count and denominator. A judge abstention on a confirmed
reference is a primary-accuracy error and coverage loss, not a false acceptance
or rejection. Directionally wrong mismatches appear in the decision confusion table.

These metrics are descriptive; v0.2 does not impose a calibrated acceptance cutoff.
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
