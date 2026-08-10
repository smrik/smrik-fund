# AGENTS.md

## Project

AI Fund V1 is a lean financial-analysis pipeline for Microsoft (`MSFT`).

The goal is to test whether LLMs can use financial statements and filing disclosures to propose useful analytical adjustments, while Python handles accounting mechanics deterministically.

Core principle:

> Open financial reasoning. Closed accounting mechanics.

V1 is complete when one MSFT path works correctly end to end.

## Source of truth

Before making changes, read the relevant parts of:

* `docs/ai_fund_v1_section_1.md` — product scope and architecture
* `docs/ai_fund_v1_section_2.md` — implementation flow, schemas, tests, and task order

Do not reinterpret or expand the approved V1 scope.

If the documents appear to conflict:

* Section 1 controls product scope and architecture principles.
* Section 2 controls detailed implementation behavior.

## Scope

Implement only the requested task.

Make normal in-scope technical decisions yourself.

Do not:

* add unrelated refactors;
* implement later tasks early;
* add abstractions for hypothetical future requirements;
* broaden support beyond MSFT unless explicitly requested;
* migrate old code or directories wholesale;
* perform "while I am here" cleanup.

If the task cannot be completed without a materially larger change, stop and explain the concrete blocker.

For a task expected to be small, touching more than roughly 5–8 files is a warning sign. Explain why before expanding further.

## Code style

Prefer simple, explicit Python.

Use:

* functions;
* Pandas DataFrames;
* dictionaries, lists, strings, and numbers;
* Pydantic only at structured external boundaries such as LLM outputs;
* descriptive names;
* short technical comments and docstrings;
* `# region` / `# endregion` when they improve navigation.

Prefer visible control flow over abstraction.

The code should be understandable by a finance-oriented Python user.

Do not add classes unless the current task clearly becomes simpler with one.

Do not create architecture based on:

* services;
* repositories;
* controllers;
* managers;
* provider hierarchies;
* base classes;
* interfaces;
* generic object models.

Do not create generic `utils`, `helpers`, or `common` modules without a concrete need.

## V1 architecture constraints

Use the existing V1 stack where applicable:

* Python 3.12
* Pandas
* Pydantic
* Typer
* Rich
* EdgarTools
* official OpenAI Python SDK
* pytest
* Ruff
* Pyright
* uv

Do not add these unless the approved task explicitly requires them:

* LangChain;
* generic agent frameworks;
* RAG frameworks;
* vector databases;
* workflow engines;
* ORMs;
* dependency-injection frameworks;
* event buses;
* generic multi-provider abstractions;
* autonomous multi-agent orchestration.

If EdgarTools already provides a capability, prefer using it over rebuilding it.

## Data principles

Preserve source data.

Do not mutate EdgarTools source values to make downstream analysis easier.

Keep reported data, adjustments, and adjusted data separate.

Use simple inspectable formats:

* CSV for financial and adjustment tables;
* JSON for structured LLM outputs;
* Markdown for evidence packets and prompts.

Do not introduce a database for V1.

## Testing

Start from the task acceptance criteria.

When practical:

1. write or update a focused failing test;
2. run it and confirm the expected failure;
3. implement the minimum required code;
4. run the focused test;
5. run the relevant broader checks.

Protect financial and data-integrity invariants, not arbitrary code coverage.

Normal pytest tests must not make live LLM calls.

LLM evaluations must run separately and explicitly.

Do not create verifier agents or repeat successful checks without a concrete reason.

## Git and safety

You may without asking:

* read project files;
* inspect Git status and diffs;
* edit files required by the current task;
* run non-destructive tests, lint, type checks, and local CLI commands.

Do not without explicit approval:

* perform destructive Git operations;
* rewrite unrelated history;
* deploy anything;
* make external writes unrelated to the requested task;
* expand project scope materially.

Do not modify unrelated user changes.

Do not commit unless the task explicitly asks you to commit.

## Subagents

Do not use subagents for small tasks or verification.

Use subagents only when there are genuinely independent, sizeable workstreams that can proceed without shared state.

Prefer one agent completing one bounded task.

## Working behavior

Read enough of the repository to understand the task before editing.

Do not spend time designing future architecture that the current task does not need.

Do not optimize for file count, abstraction, extensibility, or theoretical elegance.

Optimize for:

1. correctness;
2. financial transparency;
3. simple implementation;
4. testability;
5. inspectability.

If you discover an unrelated issue, report it. Do not fix it unless it blocks the requested task.

## Completion

Do not claim a task is complete based only on code inspection.

Run the relevant executable checks.

End with this format:

### Changed

* What changed.

### Tests

* Exact commands run.
* Exact results.

### Not changed

* Relevant nearby work intentionally left out of scope.

Keep the report concise.
