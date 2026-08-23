# Approved adjustment lifecycle idempotency

Mode: Implementation Hive. Baseline: commit `736c239` on branch `codex/idempotent-approved-application`.

## Goal

Prove the safe-acceptance half of the MSFT V1 pipeline end to end:

`same filing + same economic adjustment -> stable recognition -> all deterministic inputs known -> auto_approve -> append history exactly once -> apply exactly once -> rerun -> no duplicate history or double application`.

## Authority

1. `AGENTS.md`
2. `docs/ai_fund_v1_section_1_updated.md`
3. `docs/ai_fund_v1_section_2_implementation_spec.md`
4. Existing discovery/retrieval, Analyst, Reviewer, risk gate, adjustment history/application, CLI, tests, and committed baseline
5. This plan's user-directed lifecycle contract

## Required invariants

- Same filing and same supported economic adjustment resolve to stable identity across reruns.
- Candidate recognition uses only durable factual identity inputs; never fuzzy financial judgment in Python.
- Distinct economic adjustments must not collapse accidentally.
- Every gate input required for auto-approval is deterministically known in the proved case; no weakening/fabrication of checks.
- Reviewer `accept` remains distinct from gate `auto_approve`, history status, and application status.
- First approved run appends exactly one canonical history row and applies one magnitude once.
- Identical rerun appends zero duplicate history rows and cannot double-apply.
- Latest-version history resolution and reported-data immutability remain intact.
- Fail closed on missing/ambiguous identity, evidence, target, period, amount, sign, duplicate, group, reconciliation, or materiality inputs.
- Tests must prove replay behavior with the same persisted history, not two isolated mocks.

## Acceptance

1. Focused deterministic lifecycle test proves first-run auto-approval/history/application.
2. Same test reruns the identical filing/economic adjustment against persisted history.
3. Candidate identity is stable; history row count/version does not increase on identical replay.
4. Adjusted P&L changes exactly once and equals `reported - approved magnitude` after both runs.
5. A materially changed candidate does not silently reuse identity or overwrite reviewed state.
6. Human-review/rejected/unresolved paths remain unapplied and history-safe.
7. Relevant real MSFT or faithful frozen-MSFT path runs without external LLM nondeterminism; exact boundary documented.
8. Full relevant tests, Ruff, and `git diff --check` pass.

## Decision D1

The lifecycle proof may use an explicit frozen `materiality_passed=True` fact. No numeric materiality policy is authorized. Product/live paths must continue to return unknown materiality and fail closed unless a real approved policy supplies the fact later.

## Scope

Smallest current V1 changes to candidate identity/replay recognition, complete deterministic gate inputs for one proved case, canonical append behavior, application integration, and focused tests. Prefer existing CSV history and direct functions.

## Non-goals

No human-review UI, manifest cleanup, EdgarTools ACL work, database/event sourcing, fuzzy entity resolution, generic deduplication framework, cross-issuer identity system, new LLM/retrieval stages, new approval/materiality policy, or web UI.

## Phases

1. Three independent read-only Luna scouts: identity/replay; deterministic gate/finance; persistence/application/test proof.
2. Fresh Luna `max` synthesis/implementation owner due replay/finality and accounting integrity risk.
3. Fresh Luna `xhigh` simplicity adversary focused on duplicate state and unnecessary idempotency machinery.
4. Closed barrier, read-only gate scout if required, then parent Sol gate.
