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
| Saved records | `artifact_contracts.py` | Artifact ID and checking history. |
| Providers | `llm/llm_contracts.py`, provider adapters and registry | Shared interface and provider communication. |
| MCP | `mcp/server.py`, `mcp/code_tools.py`, `mcp/client.py` | Tool registration, deadlines, evidence, and calls. |
| Domain interface | `domains/domain_contract.py`, `domains/domain_registry.py` | Domain contract and lookup. |
| Code domain | `domains/code/code_domain.py`, schemas, prompts, and candidate builder | Code-specific authoring and finalization. |
| Checking algorithms | `domains/code/validation_operations.py`, `domains/code/checks/` | Structure, execution, answers, and distractors. |
| Question generation | `domains/code/question_generator.py`, expressions and rendering | Local expansion from saved answers and recipes. |
| Python tools | `tools/python_analysis.py`, `tools/python_execution.py`, `tools/python_worker.py` | Supported syntax and batched tracing. |

## Model and tool calls

The application resolves allowed tool definitions once and keeps them for the whole
job. The first model response contains a proposal and nonempty check plan. Planning
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

## Execution limits

The execution operation constructs `ExecutionCheck` using the Python execution tool
supplied by the MCP wrapper. The default tool sends all cases to one worker process.

- At most 64 parameter combinations per template.
- Per-case timeout and a 100,000 user-code trace-event limit.
- Scrubbed worker environment, host timeout, CPU limits, and a Linux 512 MiB
  address-space limit.
- Restricted Python syntax and a small set of allowed built-ins.
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
2. Implement `DomainModule`: prompts, allowed tools, candidate construction, tool
   bindings, finalization, and question generation.
3. Register the domain factory. Supply requests through `--request-json`.
4. Add the needed MCP tools and test success and failure paths.

Domain algorithms belong in the domain. Providers should not import domain models.
See the example domain in `tests/test_template_workflow.py` and request handling in
`tests/test_cli.py`.

## Adding a provider or check

A provider implements `generate`, `tool_turn`, and `generation_settings`, then
registers its factory. Parse responses against the supplied schema, normalize tool
calls, and report non-secret settings. Test the adapter with a mocked client before
live verification. To use another model from an existing provider, pass `--model`.

A check consists of a domain operation and an MCP wrapper with a description, input
and output schemas, version, deadline, and `ToolEvidence` result. Add its name to the
domain's allowed tools. Test success, invalid inputs, and failures. Any prerequisite
checks belong inside the operation; the application does not construct another plan.

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
