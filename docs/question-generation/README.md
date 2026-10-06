# How template generation works

The checking workflow is implemented. Evaluation across active providers is next
in [issue 40](https://github.com/edcraft-org/ai/issues/40).
For commands, see the [README](../../README.md).

## From a request to a reusable template

1. The user supplies a domain, prompt, and `easy`, `medium`, or `hard` difficulty.
2. The application gets the selected domain's allowed tools from MCP. MCP is the
   interface that lists checking tools and runs them when requested.
3. The model returns a template proposal and the checks it wants to run.
4. The model requests those checks. The application supplies the current candidate,
   calls MCP, and returns the results to the model.
5. If a check fails, the model can revise the proposal and try again. The selected
   check names stay the same throughout the job.
6. If all checks pass and the domain has the answers it needs, the application saves
   a reusable artifact. Otherwise, it returns the latest proposal and checking history.

There are at most three complete attempts: the initial proposal plus two revisions.
Each attempt runs the whole selected plan, even if one check fails. Checks must all
pass on the same candidate in the same attempt.

For example, the model might propose an addition question with a subtraction answer
by mistake. The execution check reports the actual answers. The model can then
correct the proposal and rerun its selected checks.

## Who does what?

| Component | Responsibility |
| --- | --- |
| Model | Propose the template, select and request checks, and revise failures. |
| Application | Coordinate model and tool calls, limit attempts, and save results. |
| Domain | Define the question format, allowed tools, checking algorithms, and question generation. |
| MCP | Publish tool descriptions and schemas, run domain operations, and return checking results. |
| Provider adapter | Translate requests and responses for OpenAI, Ollama, or another provider. |

The old fixed validation pipeline has been removed. Historical topic profiles are
examples and test fixtures; they do not decide which checks run.

## Available code checks

| Tool | What it checks |
| --- | --- |
| `code_verify_template_structure` | Supported Python, parameters, expressions, and question rendering. |
| `code_validate_answers_and_distractors` | Executes every allowed input combination, compares answers, and selects valid proposed distractors. |
| `code_require_features` | Requested features such as loops or helper functions occur in reachable code. |

The answer check must supply execution-derived answers and checked distractors before
an artifact can be saved. A structure-only plan therefore returns `needs_review`,
even if its selected check passes. The application does not add omitted checks.
Check-selection mistakes are measured during evaluation.

These tools establish technical properties within the supported input domain.
Feature presence does not establish that a question teaches the intended concept
well or has the right difficulty.

## Outcomes and failures

| Status | Meaning |
| --- | --- |
| `checked` | Selected checks passed and a reusable artifact was saved. |
| `needs_review` | Three authoring attempts failed, an existing candidate failed, or required answer data is missing. |
| `error` | The workflow was interrupted or could not complete the tool conversation. |

An initial configuration or generation failure can stop the command before a result
exists. Later errors retain the available proposal and attempt history.

Each tool result is `passed`, `failed`, or `error`. A successful tool call alone is
not a passing check. Calls are bounded and checked against the allowed plan and tool
schemas. The application supplies the candidate and required distractor count.

The final results are also sent to the model for acknowledgement. If that call fails,
`feedback_error` records it; the completed checking outcome is preserved.

## Saving, editing, and reuse

The finalizer packages checked answers and selected distractors. It does not change
the code or question wording. Later question generation reads the saved answers and
uses the seed to select inputs; it makes no model, MCP, or tracing calls.

Every successful checking job gets a new artifact ID. Its saved checking record
(called provenance in the code) contains the request, final proposal, provider/model
settings, tool definitions, selected plan, and results from every attempt. This
explains how the template was checked and gives future approval a record to refer to.

Users can edit candidates and recheck them through the library or CLI, as shown in
the [README](../../README.md#edit-and-check-a-template). Internal saved records are
trusted application data. Old development artifacts that fail the current schema
should be regenerated.

The planned product workflow lets users inspect and change the template before
approval, then generate questions from the approved result. The new editing/review
screens and approval storage are Milestone 4 work (#48–#50).

See the [sequence diagram](generate-template.puml) for the call order and the
[developer reference](../development.md) for implementation details.
