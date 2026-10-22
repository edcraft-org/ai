# Ordinary-trace Python difficulty rubric

Rubric version: `python-tracing-v0.3`.
Assessment conditions version: `manual-tracing-v0.2-no-shortcuts`.

This is an operational EdCraft convention for complete concrete Python tracing
MCQs. It is not a measured prediction of learner performance. Assess untimed
manual tracing with scratch paper and understood Python semantics. Requested
difficulty and generator identity must be hidden during assessment.

Follow ordinary execution of the supplied input, including every reached branch
and loop iteration. Algebraic cancellation, invariants, recognising algorithms,
memoising repeated calls, option elimination and other shortcuts never reduce a
rating. Record option quality separately. Exclude unreachable statements and
computations with no data or control effect on the requested answer; explain
these exclusions. Target relevance is not permission to replace a trace with a
closed-form or invariant argument.

## Execution burden

Count these target-relevant dynamic events:

| Event | Units |
| --- | ---: |
| Executed assignment, including simultaneous assignment | 1 |
| Executed augmented assignment | 1 |
| Evaluated `if`, `elif` or `while` condition | 1 |
| Each reached `for` iteration's variable binding | 1 |
| Executed call, including `len` and `range` | 1 plus relevant callee events |
| Return needed to determine the answer | 1 |

The initial function entry and provisioning its inputs are excluded. This is
independent of a question's answer convention, which can count that entry call.
A comparison or Boolean test inside an expression belongs to its statement and
adds no separate condition event. Short-circuit expression evaluation still
follows Python semantics. Calls inside expressions count separately. Reaching a
`for` statement adds no unit beyond its iterator-expression calls and bindings;
loop-invocation answer counts are a separate convention. A return holding a
relevant helper call can be excluded for a call-count target while retaining the
call event. Count each invocation independently, including repeated arguments.

| Rating | Events |
| --- | --- |
| low | 0–5 |
| moderate | 6–20 |
| high | 21 or more |

Zero covers a supported target with no relevant executed events, such as zero
evaluated conditions. These are provisional counting bands, not cognitive-load
thresholds. Provide an event breakdown and the total. High burden alone never
makes an item hard.

## Changing state

| Rating | Required evidence |
| --- | --- |
| low | No evolving data must be retained between iterations or for later helper returns. Ordinary indices, straight-line reassignment, sequential flags and single container mutations remain low. |
| moderate | One evolving value, independent carried values or a one-way dependency chain is retained across iterations; or a single caller retains needed intermediates across a helper return. |
| high | Repeated mutually dependent carried values, coordinated reset/persistent lifetimes, or multiple unresolved call frames with retained values needed on return. |

The moderate one-way-chain clause applies across iterations or calls, not to
ordinary straight-line substitution. A flat periodic reset plus persistent total
can have high changing-state demand without high conceptual interaction.
Identify carried values, updates, later uses, and the mechanism for high ratings.

## Conceptual interaction

| Rating | Required evidence |
| --- | --- |
| low | Direct expression evaluation or straight-line substitution, including read-after-write reassignment, single mutations, short-circuit expressions, slicing, formatting and Boolean indices; one reachability decision or a directly determined execution count. |
| moderate | Repeated locally resolvable combinations such as condition-to-update, pair-selection-to-predicate-to-counter, index-to-comparison-to-early-return; dependent helper results; sequential conditions whose executed updates affect later conditions. |
| high | A repeated interaction satisfying one of the four high patterns below. |

1. State-dependent control: evolving data changes later control or bounds, whose
   execution feeds the data controlling subsequent choices. Ordinary advancing
   loop indices or input-driven predicates feeding only a counter do not qualify.
2. Nested lifetimes: resetting inner-loop data interacts with persistent outer-loop
   data. A flat loop with a periodically reset value and a persistent accumulator
   remains moderate on this dimension.
3. Dependent call results: multiple unresolved frames retain local context and
   dependent returned results that must be coordinated.
4. Coupled recurrence with accumulation: mutually dependent updates feed a
   separately evolving result across iterations.

The explicit low examples take precedence over the generic idea of combining
semantic rules. Count only executed dependencies of the concrete target. Merely
having multiple expressions, nested syntax or recursion earns no increase.
Identify the high pattern and its actual dependency chain when rating high.

## Overall level

1. `hard`: conceptual interaction is high with an evidenced high pattern.
2. Otherwise `easy`: all three dimensions are low.
3. Otherwise `medium`: every other resolved combination.

Use unknown dimensions and a null overall estimate if essential information is
missing or these explicit rules cannot resolve the case. Do not substitute medium
for uncertainty. Never sum ratings. Report the three ratings with reasons,
trace-event breakdown, target-relevance omissions and overall deciding evidence.

## Reference and evaluation scope

Answer discrimination is no longer a difficulty dimension. Correctness,
distinctness, distractor hypotheses, wording and cues are separate option-quality
evidence. The v0.2 reference and its four dimensions are archived unchanged.

All 30 current reference questions were inspected while clarifying v0.3, with
AI-assisted labels and user-approved boundary rules. Their historical development
and held-out fields are retained for provenance, not as an unseen test claim.
Agreement on these questions is descriptive reference agreement. Fresh families
and independent human review are needed for a later generalisation evaluation.

This version is used by the explicit offline v0.3 evaluation. Existing production
MCP judging and authoring policy retain their versioned v0.2 contracts until a
separate integration change; do not present v0.3 results as that tool's accuracy.
