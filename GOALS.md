# EdCraft goals and milestones

EdCraft should help educators create reusable, checked question templates.
AI is used during authoring. Once a template is saved, questions are generated
locally from that template and a seed.

## Current priority

As of 6 October 2026, the code workflow supports free-form prompts, model-selected
MCP checks, corrections, saved checking records, and repeatable question generation.
Issues #34–#39 are complete.

The next step is [issue 40: workflow evaluation](https://github.com/edcraft-org/ai/issues/40).
Evaluate whether the active providers choose useful checks, respond to failures,
and produce reusable templates. Difficulty calibration and question quality are
later work. The difficulty values are `easy`, `medium`, and `hard`.

## Design principles

- Create templates once and reuse them for many questions.
- Use actual tool results to establish technical correctness.
- Let the model choose checks and revise proposals using their results.
- Keep domain algorithms separate from model-provider communication.
- Save enough information to explain checking and reproduce questions.
- Keep the workflow simple; add tools and abstractions when a demonstrated need arises.
- Give users a clear review and approval step when the product workflow is built.

Technical correctness and educational suitability are separate questions. A template
can pass execution checks while still needing clearer wording, better distractors,
or a more appropriate difficulty. Future quality scores must not override a failed
correctness check.

## Milestones

| Milestone | Deliverable | Status |
| --- | --- | --- |
| 1. Code templates | Checked Python templates and repeatable question generation. | Complete |
| 2. Model-selected workflow | Free-form requests, model-selected checks, corrections, saved records, and provider evaluation. | Implementation complete; evaluation remains |
| 3. Difficulty and quality | A reviewed dataset and explainable assessment of difficulty, distractors, and learning-objective alignment. | Planned |
| 4. Authoring and review | Request, inspect, edit, recheck, approve, and reuse templates through the product UI. | Planned |
| 5. Mathematics pilot | One bounded question family using the shared workflow and suitable symbolic checks. | Planned |
| 6. Source grounding | A small document corpus, retrieval, citations, and grounding evaluation. | Conditional on earlier milestones being stable |
| 7. User testing and release | User feedback, final evaluation, observed fixes, and a reproducible demonstration. | Planned |

## What completes Milestone 2?

The implemented workflow must be tested and evaluated for:

- Free-form requests within the supported Python limits, with the original prompt
  and requested difficulty preserved.
- Model-selected checks from the domain's allowed tools.
- Results returned to the model and used for correction.
- Three total attempts, with unresolved failures returned as `needs_review`.
- Answers and distractors checked across every declared input combination.
- Saved templates reproducing questions without more model or MCP calls.
- Malformed output, unsuitable plans, invalid arguments, tool failures, and incomplete
  conversations producing useful failure records.

Run the same reviewed cases across active providers. Report selection mistakes,
correction success, false acceptance/rejection, and latency separately from schema
and tool-call failures. The current smoke scripts are a starting point, not a complete
benchmark.

## Later work

Milestone 3 will assess requested versus estimated difficulty and question quality
against reviewed examples. Milestone 4 will let users inspect the template, check
results, and previews before approval. Edits require fresh checking before approval;
question generation then uses the approved artifact.

The mathematics pilot starts with one question family. Investigate more complex
verification only when that family needs it. Source grounding is optional and should
be deferred if it would delay the core workflow or final evaluation.

Broad physics support, Bloom classification, cross-corpus duplicate detection, and
a general-purpose agent framework are outside the current milestone.

## Related documents

- [Workflow](docs/question-generation/README.md): current behavior and responsibilities.
- [Evaluation](docs/evaluation.md): live checks, evaluation commands, and reporting.
- [Earlier results](docs/evaluation-history.md): evidence from previous milestones.
