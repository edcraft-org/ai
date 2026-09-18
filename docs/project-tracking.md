# GitHub Projects setup

Use GitHub Projects for delivery status, repository issues for actionable work, and
[GOALS.md](../GOALS.md) plus [the workflow specification](question-generation/README.md)
for design and acceptance criteria. This document recommends setup; it does not
claim a project or its automation has been configured.

## Minimal configuration

1. Create or select an organization project under `edcraft-org`, and link the `ai`
   repository from its Projects tab. A personal project is also possible; organization
   ownership makes team access easier to manage. Choose visibility and collaborator
   permissions deliberately; project access does not grant access to a private repo.
2. Use a board grouped by Status: Backlog, Ready, In progress, In review, Done.
   Keep a table view for sorting the backlog. Start with existing Assignees and
   Labels; an optional Priority field (High/Medium/Low) is sufficient initially.
3. Use repository milestones matching GOALS.md, starting with Milestone 2. Group
   larger deliverables into parent issues and smaller actionable issues as needed.
   Record dependencies in issue descriptions. Avoid separate milestone definitions
   in several custom fields.
4. Add existing relevant issues manually. Configure the built-in Auto-add workflow:
   select repository `edcraft-org/ai`, with filter `is:issue is:open`.
   Linking a repository alone does not populate the project; enabling Auto-add does
   not backfill existing matching items.
5. Check the built-in workflows that set closed issues/merged PRs to Done. Move
   implementation issues to In review when opening their PR. Use `Closes #N` in the
   PR body when merging it into the default branch should close the issue.
6. Put the workflow specification and sequence-diagram links in the project's
   description or README. Add the project URL here once it has been selected.

No new repository configuration, custom GitHub Action, token or secret is required
for this built-in setup. A project URL/number is only needed if configuring external
automation or adding items programmatically later.

## Initial implementation backlog

Implement the issues below in the order defined by the workflow specification:

| Order | Deliverable | Evidence needed to close |
| --- | --- | --- |
| 1 | Schema-based provider parsing | No domain parser callbacks; adapters validate responses through supplied schemas. |
| 2 | Free-form requests and proposal/selection contract | Novel supported prompts work; original prompt retained; old profiles do not gate authoring. |
| 3 | Documented capabilities and code-check MCP server | Shared definitions, structured results and retained technical constraints. |
| 4 | Cached discovery and model planning | Catalogue reused and passed to providers; generation makes no checking calls. |
| 5 | Validator execution and acceptance | Selected plans, prerequisites and coverage enforced; failures preserved. |
| 6 | Finalization, provenance and deterministic reuse | Evidence bound to artifact; seeded previews/reuse require no AI or MCP. |
| 7 | Workflow tests and live evaluation | Selection and correctness metrics reported for supported exact model versions. |

## Implementation issues

The following issues are created on GitHub. Dependencies refer to implementation
prerequisites, not requirements to begin design or tests.

| Order | Issue | Depends on |
| --- | --- | --- |
| 1 | [#34 — Move model response parsing from domain callbacks into provider adapters](https://github.com/edcraft-org/ai/issues/34) | None |
| 2 | [#35 — Accept free-form authoring prompts and return proposals with check selections](https://github.com/edcraft-org/ai/issues/35) | #34 |
| 3 | [#36 — Expose documented code-check capabilities through an MCP server](https://github.com/edcraft-org/ai/issues/36) | #35 |
| 4 | [#37 — Cache MCP capability discovery and supply the catalogue to model planning](https://github.com/edcraft-org/ai/issues/37) | #34, #35, #36 |
| 5 | [#38 — Execute model-selected validation plans through MCP and enforce evidence requirements](https://github.com/edcraft-org/ai/issues/38) | #36, #37 |
| 6 | [#39 — Finalize checked artifacts and record plan provenance for deterministic reuse](https://github.com/edcraft-org/ai/issues/39) | #35, #38 |
| 7 | [#40 — Verify the complete planning workflow and evaluate check selection across models](https://github.com/edcraft-org/ai/issues/40) | #34, #35, #36, #37, #38, #39 |

Keep future approval
UI/persistence, knowledge-base ingestion and new domains in their own milestones
rather than expanding the immediate implementation scope. The existing guardrails
issue #3 is related; this backlog covers the concrete authoring and validation work.

The repository already has feature, bug and research issue templates and a PR
template under `.github/`. No replacement is needed. In implementation issues,
include the user-visible outcome, scope, relevant workflow section, acceptance
criteria, dependencies and verification. In research issues, include a hypothesis,
fixed evaluation cases and measured results.

## References

- [About GitHub Projects](https://docs.github.com/en/issues/planning-and-tracking-with-projects/learning-about-projects/about-projects)
- [Built-in Auto-add and existing-item behavior](https://docs.github.com/en/issues/planning-and-tracking-with-projects/automating-your-project/adding-items-automatically)
- [Built-in status automation](https://docs.github.com/en/issues/planning-and-tracking-with-projects/automating-your-project/using-the-built-in-automations)
- [Linking PRs to issues](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/linking-a-pull-request-to-an-issue)
