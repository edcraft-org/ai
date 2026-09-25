# EdCraft Goals

## Vision

EdCraft should help educators and learners create trustworthy, varied questions
without requiring an AI call for every question.

The agreed target workflow (23 September 2026) is documented in
[the workflow specification](docs/question-generation/README.md) and
[the sequence diagram](docs/question-generation/generate-template.puml).
It is the implementation target; the historical milestone evidence below does not
claim that free-form input, MCP execution or model-selected checks already exist.

1. The user selects a domain, supplies a free-form prompt, and chooses a required
   `beginner`, `intermediate`, or `advanced` difficulty. Provider/model remain separate
   configuration.
2. The domain supplies generation instructions, a proposal schema, and the names of
   tools allowed for that domain. The application obtains the corresponding tool
   descriptions and schemas from MCP.
3. In one generation attempt, the model returns both a structured reusable template
   proposal and its recommended fixed check plan.
4. The model requests every selected check, the application routes each request to
   MCP, and the resulting validation evidence is returned to the model.
5. If a check fails, the model revises the proposal and reruns the fixed plan, for a
   maximum of three complete attempts. After the third failure, the latest proposal
   and evidence are returned with a `needs_review` status.
6. A proposal whose selected checks pass is finalized and presented with its evidence.
   The user approves or rejects that exact artifact version. Approved templates then
   generate deterministic questions without additional AI or MCP calls.

Document upload and personal knowledge bases remain planned milestones. When
available, retrieved source passages augment the prompt and are preserved in
provenance; uploading documents is not a prerequisite for the initial workflow.

## Main Goals

### 1. Generate once, reuse many times

Use AI to create reusable templates rather than individual questions. After a
template is approved, question generation should be deterministic, reproducible,
fast, and require no additional AI calls.

### 2. Make correctness depend on tools, not model confidence

Treat model output and its proposed check plan as untrusted drafts. The domain limits
which tools may be offered, while the model selects a fixed plan from that set. The
application routes requested calls to MCP, records actual results, and returns the
evidence to the model. A proposal proceeds only when every check in its fixed plan
passes. For supported finite code templates, checking tools should cover every
declared parameter combination; narrower or heuristic evidence must be labelled
honestly.

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
within documented technical capabilities, without requiring a complete topic
catalogue. Every domain uses the common `beginner`, `intermediate`, and `advanced` request
levels, while domain-specific tools determine how those levels are assessed.
Unsupported Python features, answer formats or validation requirements must be
reported clearly. Existing profiles can remain presets and evaluation fixtures;
they must not gate all authoring requests.

### 7. Keep models and providers replaceable

Select the provider explicitly and allow its model to be configured independently.
Changing an Ollama or OpenAI model should not require changes to domain logic or
checking tools. Adding a provider should require only a small adapter that supports
the shared proposal/check-plan response and tool-calling loop.

Provider-specific wire formats are acceptable, but adapters must extract content
and invoke generic parsing against supplied schemas. Domains supply schemas, not
parser callbacks. The application supplies the domain-allowed tool definitions to
every model and mediates tool execution consistently across providers.

### 8. Keep domains modular

Each domain owns its proposal schema, generation guidance, allowed tool names,
finalization and deterministic expansion. MCP owns the authoritative tool
descriptions, input schemas, implementations, and evidence contracts. The
application resolves the domain's allowed names against MCP and supplies those
definitions to the model. The model selects checks, requests their execution, and
revises failed proposals; the application only orchestrates this loop. The
application contains no code-, mathematics-, or physics-specific algorithms.

Planned domain direction:

- Code: static analysis and traced local execution.
- Mathematics: symbolic checking with SymPy and formal verification with Lean
  where appropriate.
- Physics: symbolic, numerical, dimensional, and constraint-based checks.

### 9. Preserve reproducibility and observability

Record enough metadata to reproduce and evaluate template generation, including
the provider, model, generation settings, prompt version, request, source document
and passage hashes, validation evidence, evaluation scores,
threshold versions, original free-form prompt, requested difficulty, capability
catalogue snapshot, fixed check plan, per-attempt evidence, tool versions,
candidate/artifact hashes, and timing. Preserve user approval for the exact artifact
version. Approved templates and generated questions should be reproducible from
their stored template and seed.

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

- Replace required topic inputs with a domain and free-form prompt while requiring
  a `beginner`, `intermediate`, or `advanced` difficulty on every request.
- Remove domain parser callbacks; use generic JSON/schema parsing in provider adapters.
- Return the provider-neutral proposal and recommended fixed check plan from one
  model generation attempt.
- Let each domain declare its allowed tool names. Resolve their current descriptions
  and schemas from MCP and freeze that catalogue for the generation workflow.
- Let the model request every check in its fixed plan. Route calls through the
  application to MCP and return structured pass/fail evidence to the model.
- If evidence contains a failure, let the model revise the proposal and rerun the
  fixed plan for at most three complete attempts. Return the latest proposal and
  evidence as `needs_review` after the third failure.
- Retain deterministic code algorithms and technical execution constraints.
- Persist catalogue versions, the fixed plan, per-attempt evidence and artifact
  identity.
- Evaluate check-selection quality separately from proposal schema compliance and
  check execution. Include unknown/omitted checks, invalid arguments, unavailable
  tools, unsupported requests and false acceptance/rejection.
- Define a common evaluation result that separates hard validation failures from
  advisory quality scores and records the assurance level of each method.
- Investigate symbolic, property-based, and other deterministic validation methods
  where they provide value beyond finite exhaustive execution.
- Continue provider evaluations and record all generation settings.

### Milestone 3: Difficulty and question quality

- Build a reviewed benchmark of code questions labelled for difficulty and topic
  relevance, with a written annotation guide and agreement results.
- Extract deterministic static and execution-trace features that explain the work a
  learner must perform.
- Estimate code difficulty with a bounded rubric covering execution burden, state
  tracking, conceptual demand, and answer discrimination.
- Estimate relevance to the free-form learning objective using deterministic topic
  and structural evidence, with calibrated embedding similarity where it adds value.
- Version thresholds and report component evidence and uncertainty rather than only
  a final label.

### Milestone 4: Authoring and review workflow

- Let users select a domain, write a free-form prompt, and choose the required
  `beginner`, `intermediate`, or `advanced` difficulty. Keep provider/model settings
  separate.
- Show generation, check execution, correction attempts, errors, and `needs_review`
  without duplicating the application workflow in the frontend.
- Present the exact artifact, provenance, validation and quality evidence, and
  representative deterministic questions for user approval or rejection.
- Bind approval to the exact artifact version and support deterministic generation
  from approved templates.
- Prepare and pilot the usability protocol before the final UAT milestone.

### Milestone 5: Mathematics domain pilot

- Add one bounded mathematics question family as an independent domain module.
- Use symbolic checking with SymPy where appropriate; investigate Lean only where it
  adds assurance that the first pilot needs.
- Define mathematics-specific meanings for the common `beginner`, `intermediate`, and
  `advanced`
  labels and evaluate them against reviewed examples.
- Extract shared domain abstractions only when both the existing code domain and a
  real second domain demonstrate the requirement.

### Milestone 6: Conditional source-grounded generation pilot

If Milestones 2 to 5 are stable, add one bounded source format and corpus for
document ingestion, retrieval, cited generation, and grounding evaluation. Preserve
source identifiers, content hashes, selected passages, and citations on artifacts.
Retrieved content remains untrusted input and cannot change tool permissions or
system policy. Defer this milestone rather than weakening the core code,
mathematics, authoring, or evaluation work.

### Milestone 7: UAT and refinement

- Conduct user acceptance testing with representative users and workflows.
- Record usability problems, rejected-template reasons, quality failures, latency,
  and model/provider performance.
- Prioritize refinements from observed UAT evidence rather than adding speculative
  complexity.
- Recalibrate quality thresholds and improve prompts, checking tools, and interactions
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
  technical limits, the original prompt is retained, and every request includes an
  `beginner`, `intermediate`, or `advanced` difficulty.
- Every provider receives the domain-allowed tool definitions and produces the
  shared proposal and fixed check plan in one generation attempt.
- The model requests each selected check, the application routes it to MCP, and the
  resulting evidence is returned to the model.
- A failed proposal is revised and rechecked for at most three complete attempts;
  only a proposal whose entire fixed plan passes proceeds to approval, while the
  third failed attempt returns as `needs_review`.
- Canonical answers, distractors and deterministic expansion retain their existing
  correctness guarantees within the declared finite input domain.
- Workflow tests and live evaluations cover generation, selection, execution and
  acceptance failures for each supported provider/model configuration.

The later question-quality, authoring, mathematics, and conditional grounding
milestones are complete when:

- The code difficulty estimator reports its four component scores, supporting
  evidence, versioned thresholds, and agreement with reviewed examples.
- Relevance is measured against the original learning objective using explainable
  evidence and a calibrated labelled benchmark.
- Users can inspect evidence and representative questions, and their approval is
  bound to the exact artifact version used for deterministic reuse.
- A bounded mathematics family runs through the same application/model/MCP loop and
  demonstrates correct symbolic evidence and reproducible expansion.
- If the conditional grounding milestone proceeds, each artifact records immutable
  source and passage identifiers and citations, and evaluation detects unsupported
  claims within the supported scope.
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

- Provider-managed MCP execution or changing check membership during retries.
- A mandatory skills runtime or a general-purpose agent/workflow framework.
- Requiring a fixed topic catalogue or having the domain choose the proposal's final
  check plan.
- Building the final production frontend; the backend contracts and lifecycle come
  first.
- Treating embedding similarity or an LLM judge as proof of correctness.
- Adding physics, chemistry, broad Bloom classification, or cross-corpus redundancy
  detection before the planned code and mathematics evaluations justify them.
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
