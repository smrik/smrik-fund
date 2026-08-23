# Task 8 Risk Reviewer

## Authority

- `AGENTS.md`
- `docs/ai_fund_v1_section_1_updated.md`
- `docs/ai_fund_v1_section_2_implementation_spec.md`
- current Task 7 Analyst implementation and tests
- user Task 8 request in the active Codex task

## Execution shape

Full Implementation Hive, explicitly required by the user:

1. three independent read-only Luna proposal scouts at `xhigh`;
2. one fresh Luna synthesis/implementation owner at `max`;
3. one fresh Luna simplicity adversary at `xhigh`;
4. parent acceptance gate.

## Phase 1 — diversity

Three independent proposals inspect the same authority and repository state. They may write only their unique proposal reports. Each must recommend the smallest finance-first Reviewer design, affected files, invariants, non-goals, risks/verification, and estimated size.

## Phase 2 — synthesis and implementation

Fresh `max` Luna judges the three proposals, selects the simplest sound contract, implements the direct Reviewer module and focused tests, and persists the structured result. Reuse the established Analyst candidate and evidence handling where semantics fit. One candidate plus exactly supplied evidence per structured OpenAI call. No approval gate, revision runtime, retrieval, workflow, or Task 9 behavior.

## Phase 3 — simplicity adversary

Fresh `xhigh` Luna attacks removable complexity and verifies financial/evidence integrity. It may make only clear behavior-preserving simplifications; correctness defects require a repair decision/step.

## Phase 4 — parent gate

Parent inspects terminal reports, targeted final diff/code, and a bounded acceptance sample. A gate scout is required only if multiple writers changed interacting surfaces, a shared contract changed, reports conflict, or adversary edits materially reopen integration.

## Acceptance gate

- valid MSFT Xbox candidate, including null amount/unknown basis, is handled correctly;
- fabricated $3.1bn impairment amount is not accepted and flaw is identified;
- wrong target, wrong period, unsupported evidence, and amount-basis misrepresentation are caught as required by the chosen contract;
- only supplied evidence is sent/usable;
- focused tests and Ruff pass; relevant live MSFT path run if supported without inventing integration;
- final diff is focused and user changes remain intact.
