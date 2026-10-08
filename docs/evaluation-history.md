# Earlier evaluation results

These results describe earlier prompts and checking behavior. They provide
background for issue 40, which will evaluate the current model-selected workflow.
They should not be treated as its current pass rates.

Historical records may use `beginner`, `intermediate`, and `advanced`. The current
labels are `easy`, `medium`, and `hard`.

## Original code-template milestone

By 9 September 2026, the original milestone had:

- 15 topic/difficulty fixtures with positive and negative tests.
- Exhaustive checking of up to 64 inputs in one Python execution batch.
- Saved templates generating seeded questions without further AI or tracing calls.
- OpenAI and Ollama adapters using shared template types.
- Evaluation records containing requests, settings, outcomes, and timings.

Real OpenAI runs produced valid templates for every profile while the profile
contracts were being refined. This was development evidence, not a frozen benchmark.

## Ollama prompt experiments

The following runs used `qwen2.5-coder:14b`:

| Prompt/run | Result | Latency | Main finding |
| --- | --- | --- | --- |
| v8, before profile relaxation | 10/15 validated (66.7%) | Mean 44.1 s; range 26.2–63.8 s | Five proposals failed schema, safety, answer-kind, or answer checks. No timeout or transport failures. |
| v9, 25 September 2026, arithmetic/easy | 0/6 validated | Mean 45.8 s; range 35.3–59.8 s | Question wording did not name the selected entry function. |
| v10, temperature 0 | 1/1 validated | 36.6 s | An explicit wording example helped the model satisfy that requirement. |
| v10, temperature 0.2 | 6/6 validated | Mean 39.9 s; range 29.8–49.9 s | The additional runs also satisfied the requirement. |

The v9 runs used Ollama 0.33.0 and failed with `QUESTION_TEMPLATE_INVALID` during
`template_structure`. The v10 prompt added an example requiring the exact
entry-function name in the question. The validator and proposal schema stayed the
same between these v9 and v10 runs.

The v8 fixtures later allowed a broader set of valid proposals, so new runs are
needed for a fair comparison. Small prompt experiments also do not establish general
model reliability. Use observed failures to improve prompts and models while
preserving the correctness checks.
