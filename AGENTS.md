# Engineering Guidelines

These instructions apply to the entire repository.

## Working approach

- Understand the existing behavior and relevant tests before editing code.
- Make the smallest coherent change that fully addresses the requested issue.
- Keep changes within scope; do not perform unrelated refactoring or formatting.
- Preserve existing public interfaces and behavior unless the task explicitly
  requires a change.
- State important assumptions when requirements are ambiguous.

## Design and implementation

- Prefer simple, readable solutions over unnecessary abstractions.
- Keep modules and functions focused on one responsibility.
- Reuse established project patterns before introducing new ones.
- Add dependencies only when their value clearly outweighs their maintenance and
  security cost.
- Validate inputs at system boundaries and return clear, actionable errors.
- Never commit secrets, credentials, generated caches, virtual environments, or
  local configuration.
- Treat AI-generated code and external input as untrusted. Use isolation,
  timeouts, resource limits, and explicit allowlists where appropriate.

## Testing and verification

- Add or update tests for every behavior change and bug fix.
- Run the most focused relevant tests first, followed by the broader suite when
  practical.
- Run configured linting, formatting, and type checks before completion.
- Do not weaken, delete, or skip tests merely to make a change pass.
- Verify failure paths and edge cases, not only the successful path.

## Repository hygiene

- Keep commits focused and use messages that explain the purpose of the change.
- Do not rewrite or discard another contributor's work without explicit
  authorization.
- Update documentation when setup, behavior, interfaces, or limitations change.
- Report what changed, what was verified, and any remaining limitations.
