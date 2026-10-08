# Developer reference

Read the [workflow guide](question-generation/README.md) first. This page identifies
where behavior lives and what to change when extending it.

Use Python 3.12 or newer. Dependencies are locked in `uv.lock`; `step-tracer` is
pinned to commit `ab7e22ef18b776a9cbd5260bef4b4eeacc17db11`.

## Code layout

All paths below are under `src/edcraft_validator/`.

| Area | Main files | Purpose |
| --- | --- | --- |
| Application | `application/template_workflow.py`, `application/authoring_contracts.py` | Checking loop, attempts, and final results. |
| Saved records | `artifact_contracts.py` | Artifact ID and small origin record. |
| Providers | `llm/llm_contracts.py`, provider adapters and registry | Shared interface and provider communication. |
| MCP | `mcp/server.py`, `mcp/code_tools.py`, `mcp/client.py` | Tool registration, deadlines, evidence, and calls. |
| Domain interface | `domains/domain_contract.py`, `domains/domain_registry.py` | Domain contract and lookup. |
| Code domain | `domains/code/code_domain.py`, schemas, prompts, and candidate builder | Code-specific authoring and finalization. |
| Checking algorithms | `mcp/code_tools.py`, `mcp/code_checks/` | Structure, execution, answers, distractors, and feature detection. |
| Question generation | `domains/code/question_generator.py`, expressions and rendering | Local expansion from saved answers and recipes. |
| Python tools | `tools/python_analysis.py`, `tools/python_execution.py`, `tools/python_worker.py` | Supported syntax and batched tracing. |

## Model and tool calls

The application lists MCP tools once, selects those tagged `domain:<domain name>`,
and keeps their definitions for the whole job. Tools with multiple domain tags can
be shared; untagged tools are not offered. There is no domain-owned tool-name list.
The first model response contains a proposal and nonempty check plan. Planning
arguments are empty; later tool calls supply check-specific arguments, such as the
features to require. The application supplies the candidate and distractor count.

Only selected checks run. The model can change proposal fields and tool arguments
between attempts, but check membership stays fixed. Invalid arguments fail that
check's slot; they can be corrected on the next attempt. Each selected check runs at
most once per attempt. All selected names must finish before correction starts.

The tool conversation is limited to `2 * plan_size + 2` turns per attempt. Unfinished
plans return `error` with the available history. Tool replies are checked against
the saved schemas and versions. Final acknowledgement failures are recorded separately.

The code finalizer stores execution-derived answers, clears the proposed answer
expression, and retains selected supplied distractors. It leaves code and wording
unchanged and does not execute the template again.

## Saved output

`AuthoringResult` is one report per job. It stores the request, provider settings,
compact tool catalogue, selected plan, timings and all attempts. Each attempt owns
one candidate; its executions store requested arguments, additional application
arguments and full `ToolEvidence`. Valid argument JSON is saved as an object;
malformed argument JSON is retained as text so failures remain explainable.

The shared report envelope preserves domain-specific artifact fields on reload.
Before using a reloaded artifact, parse its JSON through the selected domain's
`validated_model`; that schema owns validation of its content. The code domain's
schema still rejects unknown fields. Report `failure` records the terminal error's
stage and code, independently of findings from earlier attempts. Generation timing
includes correction requests that time out or return invalid responses.

`ValidatedCodeTemplate` stores the reusable content and canonical input/answer
cases. Its check summaries retain names, versions and timings without copying
canonical answers or trace summaries again. `TemplateAuthoringProvenance` is only
small origin metadata; it does not contain the report. Question generation needs
neither the history nor the diagnostic schemas.

The CLI's `--template-output` writes the artifact only on success. The optional
`--tool-schemas` writes the complete discovered catalogue for diagnostics. Normal
reports omit schemas, but dispatch still validates against the original definitions.
Regenerate older development artifacts that fail the new schema.

Evaluation JSON stores the authoring report once under `authoring_result`.
`TemplateEvaluationAttempt` derives its Python convenience fields from that report
when loading, so `validated_template`, `tool_catalogue`, and `validation_evidence`
remain available without repeating them in saved records. Initial failures before
an authoring report exists retain their catalogue and evidence directly.

## Execution limits

The execution operation constructs `ExecutionCheck` using the Python execution tool
supplied by the MCP wrapper. The default tool sends all cases to one worker process.

- At most 64 parameter combinations per template.
- Per-case timeout and a 100,000 user-code trace-event limit.
- Scrubbed worker environment, host timeout, CPU limits, and a Linux 512 MiB
  address-space limit.
- Restricted Python syntax and a small set of allowed built-ins.
- Direct and mutual recursion are supported when every input case finishes within
  the existing limits. The tracer counts recursive calls and branch evaluations.
  Non-terminating or excessively deep recursion returns execution failure.
- Expressions limited to 500 source characters and 100 syntax nodes; numeric values
  bounded to magnitude 1 billion, sequences to 100 items, and nested values to
  a total logical size of 1,000.

MCP deadlines are five seconds for static checks and
`64 * per_case_timeout + 2` seconds for execution. A deadline stops waiting and
ignores late results; it does not terminate a running synchronous thread. The worker
has its own process limits. Deployment must supply outer job isolation, filesystem
and network restrictions, and resource limits; this package does not create a
container itself.

The application connects to MCP in process by default. Other integrations can start
the stdio server with:

```bash
uv run python -m edcraft_validator.mcp
```

## Adding a domain

1. Define request, proposal, candidate, saved-template, and question schemas. Extend
   `ValidatedTemplateArtifact` for saved templates.
2. Implement `DomainModule`: prompts, candidate construction, tool
   bindings, finalization, and question generation.
3. Register the domain factory. Supply requests through `--request-json`.
4. Register the needed MCP tools with tags matching the domain's `name` and test
   success and failure paths.

Checking algorithms belong under MCP. Template schemas, finalization, generation,
and their shared expression/rendering helpers remain in the domain. Providers should
not import domain models.
See the example domain in `tests/test_template_workflow.py` and request handling in
`tests/test_cli.py`.

## Adding a provider or check

A provider implements `generate`, `tool_turn`, and `generation_settings`, then
registers its factory. Parse responses against the supplied schema, normalize tool
calls, and report non-secret settings. Test the adapter with a mocked client before
live verification. To use another model from an existing provider, pass `--model`.

A check keeps its operation and MCP tool definition together, with a description,
input and output schemas, version, domain tags, deadline, and `ToolEvidence` result.
For code, add it to `mcp/code_tools.py` with `tags={"domain:code"}`; checking-only
helpers belong in `mcp/code_checks/`. Test success, invalid inputs, and failures.
Any prerequisite checks belong inside the operation; the application does not
construct another plan.

The 15 historical topic/difficulty fixtures remain regression tests and evaluation
examples. They do not restrict free-form authoring or select its checks.

## Supported answer targets

| Target | Meaning |
| --- | --- |
| `return_value` | Entry-function return value. |
| `branch_executions` | Number of evaluated `if` conditions. |
| `loop_iterations` | Total loop-body iterations. |
| `loop_executions` | Number of loop statements encountered. |
| `function_calls` | Traced calls, including the entry call and safe built-ins. |
