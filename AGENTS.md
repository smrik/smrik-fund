# AGENTS.md

## Project goal

Build the smallest working V1 of the AI financial-analysis pipeline.

The current target is MSFT.

Core principle:

> Open financial reasoning. Closed accounting mechanics.

Use LLMs for financial judgment.
Use Python for deterministic accounting, validation, and calculations.

## Verbostity, style

When reporting information to me, be extremely concise and sacrifice grammar for the sake of concision.

## Scope gate

Before building anything, read `docs/V1_STATUS.md`.
Only tasks from Section 2 Part F are in scope.
A task not on that list requires Patrik's explicit written approval.

## Source of truth

Read the relevant parts of:

- `docs/ai_fund_v1_section_1_updated.md` — product and architecture
- `docs/ai_fund_v1_section_2_implementation_spec.md` — implementation requirements

Use the current repository to understand existing paths, interfaces, and code.

Do not redesign the project unless the requested task requires it.

## Finance correctness

Financial correctness is more important than software elegance.

Always preserve:

- reported source values;
- reported signs;
- missing values;
- source periods;
- useful source metadata;
- reported vs adjusted separation.

Do not:

- convert missing values to zero;
- silently normalize signs;
- invent periods;
- invent mappings;
- silently select ambiguous source facts;
- create balancing plugs;
- modify reported values to make calculations reconcile.

If a financial relationship is ambiguous, preserve the ambiguity and report it.

Use accounting terminology precisely.
For example, Gross Profit is a monetary subtotal; Gross Margin is a percentage.

## Implementation style

Prefer:

- simple functions;
- Pandas DataFrames;
- explicit calculations;
- direct control flow;
- local code that is easy to inspect.

Use Pydantic only at structured external boundaries such as LLM outputs.

Avoid unless the current task clearly requires them:

- classes;
- services;
- repositories;
- controllers;
- managers;
- base classes;
- interfaces;
- provider hierarchies;
- generic rule engines;
- workflow frameworks;
- dependency injection;
- generic `utils` or `helpers` modules.

A little local duplication is preferable to a premature abstraction.

Do not generalize code for hypothetical future companies or features.

Code should be proportionate to the financial problem.

## Scope discipline

The task acceptance criteria define the scope.

Implement only what is required to satisfy them.

Do not fix unrelated problems discovered while working.

This includes unrelated:

- failing tests;
- typing errors;
- lint issues;
- CLI problems;
- path inconsistencies;
- legacy code;
- architecture problems.

If an unrelated issue does not prevent the requested behavior from working:

> Report it. Do not fix it.

Do not perform "while I am here" refactoring or cleanup.

Do not implement later tasks early.

If a small task starts requiring:

- more than about 4 changed production/test files; or
- more than about 200 new production lines,

treat this as a scope warning.

Before expanding further, determine whether the extra code is genuinely required by the acceptance criteria.

Prefer removing complexity over adding abstractions.

## Existing code

Existing code has no presumption of survival.

Before reusing an existing abstraction, confirm that it belongs to the current
V1 architecture.

Legacy compatibility is not a requirement.

Delete obsolete code rather than adapting new work around it.

## EdgarTools and data

Use EdgarTools directly where it already provides the required capability.

Do not recreate:

- SEC ingestion;
- XBRL parsing;
- statement hierarchy;
- raw filing caching;
- source metadata handling.

Use standard EdgarTools statement DataFrames as the primary financial-statement source unless a task explicitly requires raw facts.

Existing code has no presumption of survival.

Before reusing an existing abstraction, confirm that it belongs to the current
V1 architecture.

Legacy compatibility is not a requirement.

Delete obsolete code rather than adapting new work around it.

Do not build a canonical taxonomy or semantic mapping system unless a real case requires it.

## Testing

Testing should prove the financial behavior required by the task.

When practical:

1. write a focused test for the required behavior;
2. implement the smallest code needed;
3. run the focused tests;
4. run the relevant real MSFT path;
5. inspect the final diff.

Do not write tests for speculative future behavior.

Repository-wide checks are diagnostic unless the task explicitly requires them to be clean.

If full pytest, Pyright, or another repository-wide check reports a pre-existing unrelated failure:

- confirm it is unrelated when practical;
- report it;
- do not fix it.

Do not modify production code merely to satisfy unrelated static-typing warnings.

## Validation

Before claiming completion:

- run the focused tests;
- run Ruff on changed code;
- run the relevant real-data path when applicable;
- inspect `git diff --stat`;
- inspect the relevant diff.

Use full pytest as an additional regression check when practical.

Do not repeatedly rerun successful checks without a concrete reason.

## External skills and agent workflows

Do not invoke external development methodologies, planning systems, verifier agents,
subagents, or workflow skills unless the user explicitly requests them or the task
clearly cannot be completed without them.

Normal implementation tasks should use this repository's instructions directly.

Do not maintain separate agent session-state files unless explicitly requested.

## When something unexpected appears

Ask:

> Does this prevent the requested task from working correctly?

If no:

- leave it alone;
- mention it in `Findings`.

If yes:
- make the smallest necessary fix;
- do not broaden the fix into a general refactor.

## Output reviewability

Make material outputs understandable outside the current task. Where practical,
include the artifact's purpose, source/scope, relevant run or period, units and
definitions, key results, and important caveats in the output itself or alongside it.
Do not rely on the code or chat history as the only explanation.

In the final report, link every material output and show a small representative
preview appropriate to its format: for example, table headers plus five rows, a
sample JSON object, a report excerpt, a rendered page/image, or representative CLI
output. Include enough context that another person can understand what the preview
shows and assess the output without first inspecting the implementation.

## Completion report

Keep the final report short.

### Changed

What behavior was added or changed.

### Tests

Exact relevant checks and results.

### Findings

Only concrete findings that matter for later work.

### Not changed

Relevant nearby work deliberately left out of scope.
