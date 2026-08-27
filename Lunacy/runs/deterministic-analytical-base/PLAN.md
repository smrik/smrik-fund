# Deterministic analytical base

Mode: Implementation Hive (explicit user request).

Goal: extend the existing three-year MSFT analytical P&L with one deterministic numerical-context path. No LLM changes, new analytical judgment, or parallel financial model.

Authority: root `AGENTS.md`; `docs/ai_fund_v1_section_1_updated.md`; `docs/ai_fund_v1_section_2_implementation_spec.md`; current repository contracts; user task.

## Phases

1. Diversity: three independent read-only Luna scouts inspect the same current repository from distinct angles and write proposals.
2. Synthesis/implementation: one fresh Luna max worker selects the smallest sound approach, implements it, proves all required synthetic cases, runs real-MSFT inspection, and performs the authoritative verification matrix.
3. Simplicity/adversarial review: one fresh Luna xhigh worker attacks math, source-value preservation, output shape, scope, and removable complexity. Correctness findings become a fresh repair step; no silent redesign.
4. Sol gate: inspect the terminal reports and targeted final diff, run one bounded acceptance check, and issue PASS / PASS WITH SMALL FIXES / DO NOT MERGE.

## Invariants

- Existing adjustment, identity, lifecycle, materiality, review, reconciliation, and LLM behavior remains unchanged.
- Missing values remain missing; reported values/signs are preserved.
- Percentage growth fails closed for zero, missing, negative-to-negative, and sign-changing cases; absolute change remains available when both values exist.
- Common-size metrics are absent for economically meaningless rows.
- CAGR requires positive, present endpoints.
- One canonical calculation path; direct Pandas/simple functions; no new dependencies or framework.
- Stop for a decision before materially exceeding 150–200 net new production lines.
- No commit, merge, push, or live external mutation.

## Verification ownership

Implementer owns focused analytical tests, relevant reconciliation tests, full suite, Ruff on changed Python, `git diff --check`, and real MSFT sample generation. Adversary verifies only any simplification delta. Sol performs a bounded focused acceptance sample.

