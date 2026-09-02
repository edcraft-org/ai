# EdCraft Goals

## Vision

EdCraft should help educators and learners create trustworthy, varied questions
without requiring an AI call for every question.

The intended workflow is:

1. A human selects a domain, topic, and difficulty.
2. An AI model authors a reusable question template.
3. Domain-specific tools validate the complete template.
4. The approved template generates many deterministic questions from different
   parameter values.
5. A future frontend lets a human review, approve, and use those templates and
   questions.

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

### 3. Complete the code domain first

Build a reliable end-to-end workflow for Python code questions before expanding
to other domains. The code domain should support the topics and difficulty levels
accepted by the public interface, with corresponding validator support for every
advertised capability.

### 4. Keep models and providers replaceable

Select the provider explicitly and allow its model to be configured independently.
Changing an Ollama or OpenAI model should not require changes to domain logic or
validation code. Adding a provider should require only a small adapter that
produces the shared template contract.

Provider-specific wire formats are acceptable, but they must be normalized into
the same provider-neutral template before validation.

### 5. Keep domains modular

Each domain should own its template contract, generation guidance, and validation
tools. The application workflow should coordinate these modules without containing
code-, mathematics-, or physics-specific rules.

Planned domain direction:

- Code: static analysis and isolated execution.
- Mathematics: symbolic checking with SymPy and formal verification with Lean
  where appropriate.
- Physics: symbolic, numerical, dimensional, and constraint-based checks.

### 6. Preserve reproducibility and observability

Record enough metadata to reproduce and evaluate template generation, including
the provider, model, prompt version, request, template version, validation result,
and timing. Approved templates and generated questions should be reproducible from
their stored template and seed.

### 7. Keep the architecture simple

Prefer explicit interfaces, small modules, deterministic transformations, and
clear validation errors. Add abstractions only when they support a real second
implementation, domain, provider, or tool.

## Current Priority

The immediate priority is a dependable code-domain template workflow:

1. Improve Ollama template reliability without restoring per-question generation.
2. Derive deterministic fields locally when they do not require model judgment.
3. Validate and select distractor recipes across the complete parameter domain.
4. Evaluate every supported code topic and difficulty using real model outputs.
5. Expose provider and model selection cleanly for future frontend integration.

## Success Criteria

The code-domain milestone is complete when:

- Every advertised topic and difficulty has a documented, validator-supported
  template profile.
- Approved templates generate multiple questions without additional AI calls or
  per-question validation.
- All possible parameter combinations in an approved template have been checked.
- Invalid, unsafe, ambiguous, or inconsistent templates are rejected with useful
  diagnostics.
- Ollama and OpenAI can be selected explicitly and produce the same canonical
  template type.
- Changing a model under an existing provider requires configuration rather than
  domain-code changes.
- Automated tests cover deterministic behavior, provider adapters, validation,
  Docker isolation, and mocked API behavior; real-provider checks remain explicit.
- A repeatable evaluation reports template pass rate, failure category, and latency
  by provider, model, topic, and difficulty.

## Non-Goals for the Current Milestone

- Building the final frontend or human approval interface.
- Supporting every programming language.
- Adding mathematics or physics before the code-domain contract is dependable.
- Trusting generated templates without deterministic validation.
- Reintroducing the costly workflow where AI generates every concrete question.

## Code-Domain Milestone Evidence

As of 2 September 2026, the code-domain architecture satisfies the success
criteria above:

- All 15 topic/difficulty profiles have machine-readable parameter, answer-kind,
  AST-feature, and exact semantic contracts backed by positive and negative tests.
- Approved templates exhaustively validate at most 64 combinations in one Docker
  batch, then generate seeded questions locally without AI, Docker, or per-question
  validation.
- OpenAI and Ollama normalize provider-specific responses into the same proposal and
  approved-template types; provider and model selection are explicit configuration.
- Evaluation records provider, resolved model, prompt hash/version, request, timing,
  failure stage/code, and approved output. JSONL attempts are flushed incrementally.
- The final automated baseline passes 190 non-live tests and 19 Docker integration
  tests. Real OpenAI evaluations produced approved templates for every profile while
  the profile contracts were tightened.
- A complete Ollama `qwen2.5-coder:14b` v8 matrix approved 10 of 15 profiles (66.7%)
  in 26.2–63.8 seconds per attempt, with no timeout or transport failure. The five
  unsuitable proposals were rejected for schema, safety, answer-kind, or answer
  mismatch errors, demonstrating the intended untrusted-draft boundary.

Provider pass rate is an evaluation signal, not a reason to weaken validation.
Improving the remaining Ollama generation quality or choosing a stronger local model
is follow-up model work; correctness continues to depend on deterministic approval.
