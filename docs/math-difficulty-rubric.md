# Provisional mathematics difficulty rubric

Rubric version: `math-ir-v0.1`.
Assessment conditions version: `paper-no-cas-v0.1`.

Use this rubric to check whether a reusable mathematics MCQ template matches the
user's requested difficulty. Assess the typical concrete expansion independently,
then compare its estimated level with the request. Levels describe EdCraft's
provisional task-demand conventions under the conditions below. They are
uncalibrated and have no reference labels behind them. A match means the template
is consistent with this provisional rubric, so results stay advisory evidence for
educator review and never override failed correctness checks.

## Assessment conditions and scope

Use paper without a calculator, computer algebra system or AI assistant. Assess an
untimed practice question with the relevant mathematical prerequisites understood.
There is no fixed learner cohort and no measured learner performance. Record any
aids, time limit or scaffolding as a different assessment condition.

A template is rated on concrete expansions of its declared parameter family. Pick
representative combinations that show the range of demand, including the boundary
values that the checks sample. Parameter values can change an operation or an
option, so rate the range you reviewed and report substantial variation. A sampled
match cannot establish that every expansion matches.

Technical correctness, educational difficulty and question quality are separate.
Distinct wrong answers do not establish plausible distractors. A correct template
can still carry weak options or unclear wording. Record those concerns separately.

## Dimensions and evidence to record

Rate each dimension `low`, `moderate` or `high`, or `unknown` when the evidence is
insufficient. These categories organise the explanation. Do not sum them or apply a
weighted formula to produce a difficulty score. Level boundaries here are EdCraft
conventions and they are not calibrated thresholds.

| Dimension | Low | Moderate | High |
| --- | --- | --- | --- |
| Procedure length | One step or direct recall. | A short sequence of standard steps, about two to four. | A long chain, or a step needing a choice of method. |
| Operation type | Basic arithmetic or linear manipulation. | Polynomials, powers, simple derivatives, or 2 by 2 determinants. | Trigonometric, logarithmic or exponential forms, chain or product rules, systems, or 3 by 3 matrices. |
| Conceptual demand | Routine procedure. | A procedure with a connection, for example recognising which technique applies. | Non-routine reasoning. |
| Answer discrimination | Wrong options fall to a quick check or a magnitude cue. | Eliminating options needs one specific rule. | Plausible options need several rules or a full solution. |

### Procedure length and operation type

Describe a correct solution for the chosen expansion. State the operations the
learner performs and whether a method choice is involved. The expression tree,
number of unknowns, matrix order and goal kind are evidence of the required
operations. Raw node count alone does not set difficulty because a long but routine
expression can stay easy.

Use `low` for direct recall or a single standard step, `moderate` for a short
sequence of standard steps, and `high` for a long chain or a step where the learner
must choose a technique. Give the deciding operations behind the rating.

### Conceptual demand

Identify the rules that shape the solution and how they depend on each other. For
example, recognising that a quadratic factorises is a connection, while following a
stated formula is routine. Use `low` for direct application, `moderate` for one
meaningful connection, and `high` for non-routine reasoning. Mere presence of a
familiar form does not settle the rating.

### Answer discrimination

For each distractor, explain the error rule the option hypothesis uses and the rule
that eliminates it. The misconception tag is a hypothesis. Without learner data it
is not proof that learners make that error. Assign the dimension from the easiest
defensible way to distinguish the correct answer from the actual options. Unclear or
misleading options need repair rather than a higher difficulty label.

Here discrimination means option-distinguishing demand. Statistical item
discrimination needs learner data and is deferred with calibration.

## Overall levels and uncertainty

| Level | Anchor description |
| --- | --- |
| `easy` | A short routine procedure with small, simple numbers. At most one dimension is moderate. Options fall to a basic check. |
| `medium` | A routine procedure of several steps, or one connection, with limited number or form demand. Eliminating options needs a specific rule. |
| `hard` | A long or multi-method procedure with high operation demand, or non-routine reasoning, with plausible options that need a full solution. |

Choose the closest worked anchor and explain the similarities and the material
differences. A single high dimension does not force `hard`. A shortcut or weak
options can lower the complete MCQ's demand. Unknown evidence is not defaulted to
medium.

Record confidence from 0 to 1 in the selected level. It is a self-estimate and it is
uncalibrated. For missing essential information use `estimated_difficulty: null`
with an unable-to-assess reason and confidence 0. A technically failed template is
ineligible for difficulty assessment.

## Worked anchors

These examples are reviewer training material. They are not held-out reference
items. The levels illustrate the rubric and nobody has rated them independently.

### Easy linear equation

Solve `2x + 3 = 11`. A: `4`, B: `5`, C: `7`, D: `14`.

Answer: A, `4`. Subtract three, then divide by two. All four dimensions are low.
The distractors use a missing division (7), an added instead of subtracted constant
(14) and a sign slip (5).

### Medium quadratic expansion

Expand `(x - 2)(x + 3)`. A: `x^2 + x - 6`, B: `x^2 - x - 6`, C: `x^2 + 5x - 6`,
D: `x^2 - 5x - 6`.

Answer: A. The procedure is a short sequence with a sign and a product, so procedure
length and operation type are moderate. Conceptual demand is low to moderate because
the distributive rule is routine. Answer discrimination is moderate because each
option needs the sign rules checked.

### Hard product derivative

Differentiate `x^2 sin(x)` with respect to `x`. A: `2x sin(x) + x^2 cos(x)`,
B: `2x cos(x)`, C: `x^2 cos(x)`, D: `2x sin(x) - x^2 cos(x)`.

Answer: A. The product rule couples two operation families, so operation type and
conceptual demand are high. Procedure length is moderate to high. Answer
discrimination is high because each option needs the rule and both derivatives
checked. A learner who recalls the product rule still needs to coordinate the two
terms.

## Reviewer procedure and records

1. Confirm the checks passed and the stem is clear. Repair ineligible cases first.
2. Hide the requested difficulty, generator identity and other ratings. Show the
   conditions, the concrete MCQ and the verified answer.
3. Explain the solution and each distractor, then record dimension ratings, nearest
   anchor, overall level, confidence and quality concerns independently.
4. Reveal the requested difficulty and apply the comparison rule to the frozen
   assessment. A mismatch remains advisory and never requests automatic revision.

Store records in versioned files. Preserve the rubric and conditions versions, the
reviewed parameter combinations, the dimension ratings with reasons, the closest
anchor, the estimated level or null, confidence, quality concerns, the unchanged
requested level and the match result. Increment the rubric version when dimensions,
anchors, level decisions or conditions change. Code, expression or option edits
invalidate the previous concrete assessment.

## Validation plan

The planned protocol follows the code rubric's structure. Target about 60 concrete
questions from at least 20 template families across the supported goal kinds and all
three requested levels. Split by family before tuning and keep variants of one
family together. Use two or three independent mathematics teachers or tutors, with
the author disclosed separately. Record ordinal Krippendorff's alpha for the overall
level, per-dimension exact agreement and a confusion matrix against the adjudicated
reference. Report bootstrap intervals that resample families and expect wide
intervals. Calibration against learner responses is deferred until response data
exists. This rubric carries no accepted accuracy threshold.
