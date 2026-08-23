# Plan

Goal: correct the existing stable-economic-identity implementation without redesigning it.

Authority: project `AGENTS.md`; current user request; existing v2 identity contract and approved-version semantics.

## Phase 1 — Correct and prove

- One Luna xhigh owner inspects current code and actual analytical P&L, implements the smallest safe legacy-history distinction and target-row-key rule, adds required focused proofs, runs the required terminal matrix, and self-reviews.
- Preserve unrelated changes and canonical data. No migration, registry, taxonomy, fuzzy matching, commit, or merge.

## Phase 2 — Adversarial gate

- After the writer is terminal, one fresh read-only Luna xhigh attacks legacy authority/corruption boundaries, row-key stability/collision risk, and unnecessary complexity.
- Sol fixes only concrete failures, reruns invalidated checks, then decides PASS / DO NOT MERGE.

Required verification: focused identity/history, lifecycle/idempotence, adjustment engine, full suite, Ruff on changed Python files, `git diff --check`. Attempt live MSFT only if credentials are accessible; never fake it.
