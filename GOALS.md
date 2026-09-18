# EdCraft Goals

## Vision

EdCraft should help educators and learners create trustworthy, varied questions
without requiring an AI call for every question.

The agreed target workflow (18 September 2026) is documented in
[the workflow specification](docs/question-generation/README.md) and
[the sequence diagram](docs/question-generation/generate-template.puml).
It is the implementation target; the historical milestone evidence below does not
claim that free-form input, MCP execution or model-selected checks already exist.

1. The user selects a domain and submits a free-form prompt describing the desired
   question, concepts and difficulty. Provider/model are separate configuration.
2. The application obtains domain guidance and schemas and a cached MCP capability
   catalogue, then passes check descriptions and argument schemas to the model.
3. The model returns a structured reusable template proposal and selected checks.
4. The central validator validates the selections, resolves prerequisites, executes
   checks through MCP and assesses actual evidence against acceptance requirements.
5. An accepted template is presented with evidence, limitations and deterministic
   preview questions. The user approves or rejects that exact artifact version.
6. Approved templates generate deterministic questions without additional AI or MCP
   calls. A failed attempt may be retried by the user; automatic repair is deferred.

Document upload and personal knowledge bases remain planned milestones. When
available, retrieved source passages augment the prompt and are preserved in
provenance; uploading documents is not a prerequisite for the initial workflow.

## Main Goals

### 1. Generate once, reuse many times

Use AI to create reusable templates rather than individual questions. After a
template is approved, question generation should be deterministic, reproducible,
fast, and require no additional AI calls.

### 2. Make correctness depend on tools, not model confidence

Treat model output and its proposed check plan as untrusted drafts. The model
selects checking capabilities; the central validator executes them and records
actual results. Acceptance requirements specify necessary properties and scope,
not a fixed domain-selected tool list. Missing required evidence is incomplete
validation. For supported finite code templates, check correctness across every
declared parameter combination; label narrower or heuristic evidence honestly.

For code questions, validation should use static safety analysis and isolated
execution. Future domains may use tools such as SymPy, Lean, or physics-specific
solvers.

### 3. Strengthen question and template evaluation

Evaluate more than executable correctness. The quality pipeline should cover:

- Relevance to the original prompt and requested learning objectives.
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
to other domains. The code domain should accept free-form learning objectives
within documented technical capabilities, without requiring a complete
topic/difficulty catalogue.
Unsupported Python features, answer formats or validation requirements must be
reported clearly. Existing profiles can remain presets and evaluation fixtures;
they must not gate all authoring requests.

### 7. Keep models and providers replaceable

Select the provider explicitly and allow its model to be configured independently.
Changing an Ollama or OpenAI model should not require changes to domain logic or
validation code. Adding a provider should require only a small adapter that
produces the shared proposal and check-selection contract.

Provider-specific wire formats are acceptable, but adapters must extract content
and invoke generic parsing against supplied schemas before validation. Domains
supply schemas, not parser callbacks. The application supplies the same documented capability catalogue to
all models. Hosted MCP access and native tool calling are not prerequisites: the
model emits a structured plan, and the validator controls MCP execution.

### 8. Keep domains modular

Each domain owns its template contract, generation guidance, acceptance
requirements, checking capabilities, finalization and deterministic expansion.
The application supplies the allowed catalogue to the model. The model selects
checks; the validator binds inputs, resolves declared prerequisites and executes
through an MCP client. Neither application nor validator contains code-,
mathematics-, or physics-specific algorithms. Keep one authoritative capability
definition for MCP exposure and planner documentation.

Planned domain direction:

- Code: static analysis and traced local execution.
- Mathematics: symbolic checking with SymPy and formal verification with Lean
  where appropriate.
- Physics: symbolic, numerical, dimensional, and constraint-based checks.

### 9. Preserve reproducibility and observability

Record enough metadata to reproduce and evaluate template generation, including
the provider, model, generation settings, prompt version, request, source document
and passage hashes, validation evidence, evaluation scores,
threshold versions, original free-form prompt, capability catalogue snapshot,
selected and resolved check plans, tool versions, candidate/artifact hashes, and
timing. Preserve user approval for the exact artifact version. Approved templates
and generated questions should be reproducible from their stored template and seed.

### 10. Keep the architecture simple

Prefer explicit interfaces, small modules, deterministic transformations, and
clear validation errors. Add abstractions only when they support a real second
implementation, domain, provider, or tool.

## Milestones

### Milestone 1: Code template generation

Complete the reusable Python code-template workflow: explicit provider and model
selection, provider-normalized proposals, deterministic fields, exhaustive validation,
reproducible seeded question generation, and provider evaluation. This milestone is
complete; its evidence is recorded below.

### Milestone 2: Free-form authoring and model-selected validation

- Replace required topic/difficulty inputs with a domain and free-form prompt.
- Remove domain parser callbacks; use generic JSON/schema parsing in provider adapters.
- Return a provider-neutral proposal and check-selection envelope.
- Expose documented code-check capabilities through MCP and pass discovered,
  allowed descriptions/schemas to the model. Cache discovery across requests and
  refresh on connection/deployment changes.
- Let the validator execute the selected plan, bind candidate inputs, resolve
  prerequisites and assess actual evidence against domain acceptance requirements.
- Retain deterministic code algorithms and technical execution constraints.
- Persist catalogue versions, plan selections, execution results and artifact identity.
- Evaluate check-selection quality separately from proposal schema compliance and
  check execution. Include unknown/omitted checks, invalid arguments, unavailable
  tools, unsupported requests and false acceptance/rejection.
- Define a common evaluation result that separates hard validation failures from
  advisory quality scores and records the assurance level of each method.
- Investigate symbolic, property-based, and other deterministic validation methods
  where they provide value beyond finite exhaustive execution.
- Continue provider evaluations and record all generation settings.

### Milestone 3: Difficulty and question quality

- Strengthen checks for relevance, concept coverage, grounding, answerability and
  redundancy using the new capability and evidence contracts.
- Describe requested learning objectives and concept tags without requiring an
  exhaustive profile catalogue; version any reference definitions used in checks.
- Make difficulty levels measurable using structural code features, reasoning steps,
  trace complexity, and the concepts required to answer a question.
- Add Bloom's taxonomy classification and alignment checks.
- Add a knowledge base that grounds template generation in selected source material.
- Preserve source identifiers, passage hashes, and citations on generated templates.
- Calibrate embeddings and any fallback LLM judges using a labelled set of
  human-reviewed EdCraft templates.

### Milestone 4: Frontend

- Allow users to upload documents and organize a personal knowledge base.
- Let users select a domain and write a prompt; offer provider/model settings and
  optional source selection separately. Topic/difficulty presets are conveniences.
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

The original Milestone 1 is complete. The immediate priority is implementing
Milestone 2's free-form authoring and model-selected validation workflow. Follow the
[implementation order](docs/question-generation/README.md#implementation-order-and-completion-criteria).
Milestone 3 follows once execution and evidence contracts are stable.
Track implementation issues and progress in GitHub Projects using the
[project setup guide](docs/project-tracking.md). Repository documents specify design
and acceptance criteria; Projects tracks delivery status.

## Quality and Product Success Criteria

Milestone 2 is complete when:

- Users can request concepts outside the old topic catalogue within supported
  technical limits, and the original prompt is retained.
- Every provider receives the allowed capability documentation and produces the
  shared proposal/selection envelope without executing validation tools.
- The validator executes selected checks and declared prerequisites through MCP,
  records actual evidence, and rejects invalid or insufficient plans.
- Canonical answers, distractors and deterministic expansion retain their existing
  correctness guarantees within the declared finite input domain.
- Workflow tests and live evaluations cover generation, selection, execution and
  acceptance failures for each supported provider/model configuration.

The later question-quality, knowledge-base, and frontend milestones are complete when:

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
  quality evaluators, and user decisions.

## Non-Goals for the Current Milestone

- Automatic model repair loops or provider-managed MCP execution.
- A mandatory skills runtime or a general-purpose agent/workflow framework.
- Requiring a fixed topic/difficulty catalogue or a fixed domain-selected check list.
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

As of 9 September 2026, the code-domain architecture satisfies the success
criteria defined for the original code-template milestone:

- All 15 topic/difficulty profiles have machine-readable parameter, answer-kind, and
  broad reachable-feature contracts backed by positive and negative tests.
- Validated templates exhaustively check at most 64 combinations in one local
  Python tool call, then generate seeded questions without AI or per-question
  validation.
- OpenAI and Ollama normalize provider-specific responses into the same proposal and
  validated-template types; provider and model selection are explicit configuration.
- Evaluation records provider, resolved model, base prompt version, request, timing,
  failure stage/code, and validated output. JSONL attempts are flushed incrementally.
- The automated suite covers provider adapters, the domain-agnostic application and
  validation contracts, the complete code matrix, and local tracing integration.
  Real OpenAI evaluations produced validated templates for every profile while the
  profile contracts were refined.
- Before profile relaxation, a complete Ollama `qwen2.5-coder:14b` v8 matrix
  validated 10 of 15 profiles (66.7%) in 26.2–63.8 seconds per attempt, with no
  timeout or transport failure. The five unsuitable proposals were rejected for
  schema, safety, answer-kind, or answer mismatch errors, demonstrating the intended
  untrusted-draft boundary. A new matrix is required for direct comparison under the
  broader contracts.

Provider pass rate is an evaluation signal, not a reason to weaken safety or
correctness validation. Improving the remaining Ollama generation quality or choosing
a stronger local model is follow-up model work; correctness continues to depend on
deterministic exhaustive validation.
