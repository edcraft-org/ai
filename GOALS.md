# EdCraft Goals

## Vision

EdCraft should help educators and learners create trustworthy, varied questions
without requiring an AI call for every question.

The intended workflow is:

1. A user uploads source documents and organizes them into a personal knowledge
   base.
2. The user selects a domain, topic, difficulty, and relevant source material.
3. An AI model authors a reusable, source-grounded question template.
4. Domain-specific tools validate correctness, grounding, answerability, relevance,
   coverage, difficulty, and redundancy as far as deterministic methods allow.
5. The user reviews and manually approves the template.
6. The approved template generates many deterministic questions from different
   parameter values without additional AI calls.

## Main Goals

### 1. Generate once, reuse many times

Use AI to create reusable templates rather than individual questions. After a
template is approved, question generation should be deterministic, reproducible,
fast, and require no additional AI calls.

### 2. Make correctness depend on tools, not model confidence

Treat model output as an untrusted draft. A template is usable only after
domain-specific validators establish that its generated questions and answers are
correct throughout its supported parameter domain.

For code questions, validation should use static safety analysis and isolated
execution. Future domains may use tools such as SymPy, Lean, or physics-specific
solvers.

### 3. Strengthen question and template evaluation

Evaluate more than executable correctness. The quality pipeline should cover:

- Relevance to the selected topic and learning objectives.
- Coverage of the requested concepts and uploaded source material.
- Content grounding, including traceable evidence from source documents.
- Answerability using the question, code, and permitted context.
- Bloom's taxonomy classification and alignment with the requested cognitive level.
- Redundancy and near-duplicate detection within a template, knowledge base, and
  generated question set.

Prefer deterministic and explainable checks, including schemas, static analysis,
symbolic methods, source-span matching, structural feature checks, rules, and
embedding-based similarity. Use an LLM as a judge only when a quality dimension
cannot be evaluated adequately by deterministic methods. LLM-judge results must be
recorded as heuristic evidence and must not override a deterministic correctness or
safety failure.

### 4. Ground generation in user knowledge bases

Allow users to upload documents and create their own knowledge bases. Generation
requests should identify the exact sources and passages used to author a template.
Approved artifacts should preserve source identifiers, content hashes, and citations
so that grounding can be inspected and reproduced without storing hidden model
reasoning.

Document ingestion, retrieval, and generation must remain separate stages. Retrieved
content is untrusted input: it may provide subject matter but must not change system
instructions, validation policy, or tool permissions.

### 5. Keep human approval explicit

Technical validation establishes that a template meets the system's rules; it does
not establish that the template is suitable for a particular class or learner. A
user must be able to inspect the template, validation evidence, source citations,
and representative generated questions before approving or rejecting it. Reuse the
existing template workflow rather than introducing a separate template state
machine. Only a technically valid template that the user approves should be used to
generate learner-facing questions.

### 6. Complete and preserve the code domain

Build a reliable end-to-end workflow for Python code questions before expanding
to other domains. The code domain should support the topics and difficulty levels
accepted by the public interface, with corresponding validator support for every
advertised capability.

### 7. Keep models and providers replaceable

Select the provider explicitly and allow its model to be configured independently.
Changing an Ollama or OpenAI model should not require changes to domain logic or
validation code. Adding a provider should require only a small adapter that
produces the shared template contract.

Provider-specific wire formats are acceptable, but they must be normalized into
the same provider-neutral template before validation.

### 8. Keep domains modular

Each domain should own its template contract, generation guidance, and validation
tools. The application workflow should coordinate these modules without containing
code-, mathematics-, or physics-specific rules.

Planned domain direction:

- Code: static analysis and isolated execution.
- Mathematics: symbolic checking with SymPy and formal verification with Lean
  where appropriate.
- Physics: symbolic, numerical, dimensional, and constraint-based checks.

### 9. Preserve reproducibility and observability

Record enough metadata to reproduce and evaluate template generation, including
the provider, model, generation settings, prompt version, request, source document
and passage hashes, template version, validation evidence, evaluation scores,
threshold versions, and timing. Approved templates and generated questions should
be reproducible from their stored template and seed.

### 10. Keep the architecture simple

Prefer explicit interfaces, small modules, deterministic transformations, and
clear validation errors. Add abstractions only when they support a real second
implementation, domain, provider, or tool.

## Milestones

### Milestone 1: Code template generation

Complete the reusable Python code-template workflow: explicit provider and model
selection, normalized proposals, deterministic fields, exhaustive Docker approval,
reproducible seeded question generation, and provider evaluation. This milestone is
complete; its evidence is recorded below.

### Milestone 2: Enhanced validation

- Define a common evaluation result that separates hard validation failures from
  advisory quality scores and records the assurance level of each method.
- Strengthen deterministic checks for relevance, concept coverage, grounding,
  answerability, and redundancy.
- Investigate symbolic, property-based, and other deterministic validation methods
  where they provide value beyond finite exhaustive execution.
- Continue provider evaluations and record all generation settings.

### Milestone 3: Difficulty and question quality

- Define versioned learning objectives and concept tags for code-domain profiles.
- Make difficulty levels measurable using structural code features, reasoning steps,
  trace complexity, and the concepts required to answer a question.
- Add Bloom's taxonomy classification and alignment checks.
- Add a knowledge base that grounds template generation in selected source material.
- Preserve source identifiers, passage hashes, and citations on generated templates.
- Calibrate embeddings and any fallback LLM judges using a labelled set of
  human-reviewed EdCraft templates.

### Milestone 4: Frontend

- Allow users to upload documents and organize a personal knowledge base.
- Let users choose the domain, topic, difficulty, provider, model, and source
  material used for generation.
- Present generated templates, citations, validation evidence, and representative
  questions for a simple user approve/reject decision.
- Generate and present questions from templates the user approves.

### Milestone 5: Mathematics and physics modules

- Add mathematics as an independent domain module using symbolic checking with
  SymPy and formal verification with Lean where appropriate.
- Add physics as an independent module using symbolic, numerical, dimensional, and
  constraint-based checks.
- Extract shared domain abstractions only when both the existing code domain and a
  real second domain demonstrate the requirement.

### Milestone 6: Optional chemistry module

If project time permits, add a narrowly scoped chemistry module with its own
template schema and deterministic validation tools. Chemistry must not delay the
code, validation, quality, frontend, mathematics, or physics milestones.

### Milestone 7: UAT and refinement

- Conduct user acceptance testing with representative users and workflows.
- Record usability problems, rejected-template reasons, quality failures, latency,
  and model/provider performance.
- Prioritize refinements from observed UAT evidence rather than adding speculative
  complexity.
- Recalibrate quality thresholds and improve prompts, validators, and interactions
  while preserving reproducibility.

## Current Priority

Milestone 1 is complete. The immediate priority is Milestone 2: enhanced
validation. Milestone 3 should follow once the validation evidence model is stable.

## Quality and Product Success Criteria

The validation, question-quality, knowledge-base, and frontend milestones are
complete when:

- A user can create an isolated knowledge base from uploaded documents and receive
  structured ingestion diagnostics.
- Every authored template records the source passages and immutable content hashes
  used during generation.
- Grounding checks can detect unsupported claims or answers that cannot be derived
  from the selected source material and executable template.
- Relevance and coverage are checked against versioned learning objectives and
  concept definitions using deterministic structural methods first.
- Bloom classification combines explainable structural signals with calibrated
  semantic methods and reports uncertainty rather than forcing a classification.
- Redundancy detection identifies exact and semantic duplicates while preserving
  legitimate variations produced from one approved template.
- Embedding models, revisions, preprocessing, reference hashes, similarity metrics,
  and thresholds are pinned and recorded.
- LLM judges are optional, explicitly labelled as heuristic, and invoked only when
  deterministic evaluators return insufficient evidence.
- Validation output distinguishes `proof`, `exhaustive`, `bounded`, `sampled`, and
  `heuristic` evidence.
- A technically valid template is presented for a direct user approve/reject
  decision before it is used for learner-facing generation.
- Automated tests cover document isolation, provenance, retrieval, grounding,
  quality evaluators, user decisions, and template tamper detection.

## Non-Goals for the Current Milestone

- Building the final production frontend; the backend contracts and lifecycle come
  first.
- Treating embedding similarity or an LLM judge as proof of correctness.
- Using technically valid templates for learners without a user approve/reject
  decision.
- Supporting every document type, programming language, or learning platform.
- Adding broad mathematics or physics support before the shared domain boundary is
  exercised by one narrow second-domain module.
- Reintroducing the costly workflow where AI generates every concrete question.

## Code-Domain Milestone Evidence

As of 2 September 2026, the code-domain architecture satisfies the success
criteria defined for the original code-template milestone:

- All 15 topic/difficulty profiles have machine-readable parameter, answer-kind, and
  broad reachable-feature contracts backed by positive and negative tests.
- Approved templates exhaustively validate at most 64 combinations in one Docker
  batch, then generate seeded questions locally without AI, Docker, or per-question
  validation.
- OpenAI and Ollama normalize provider-specific responses into the same proposal and
  approved-template types; provider and model selection are explicit configuration.
- Evaluation records provider, resolved model, prompt hash/version, request, timing,
  failure stage/code, and approved output. JSONL attempts are flushed incrementally.
- The automated baseline covers both non-live tests and 19 Docker integration
  tests. Real OpenAI evaluations produced approved templates for every profile while
  the profile contracts were refined.
- Before profile relaxation, a complete Ollama `qwen2.5-coder:14b` v8 matrix
  approved 10 of 15 profiles (66.7%) in 26.2–63.8 seconds per attempt, with no
  timeout or transport failure. The five unsuitable proposals were rejected for
  schema, safety, answer-kind, or answer mismatch errors, demonstrating the intended
  untrusted-draft boundary. A new matrix is required for direct comparison under the
  broader contracts.

Provider pass rate is an evaluation signal, not a reason to weaken safety or
correctness validation. Improving the remaining Ollama generation quality or choosing
a stronger local model is follow-up model work; correctness continues to depend on
deterministic exhaustive approval.
