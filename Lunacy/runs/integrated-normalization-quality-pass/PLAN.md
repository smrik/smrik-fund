# Integrated normalization quality pass

Mode: Implementation Hive.

## Goal

Review and minimally improve the existing integrated `analyze MSFT --adjustments` V1 so its grouped normalization output is financially accurate, evidence-grounded, state-safe, compact, and ready to commit. Do not redesign the product or commit.

## Authority

1. `AGENTS.md`
2. `docs/ai_fund_v1_section_1_updated.md`
3. `docs/ai_fund_v1_section_2_implementation_spec.md`
4. Current discovery/retrieval, Analyst, Reviewer, deterministic gate, adjustment engine/history, integrated CLI, tests, and actual diff
5. User acceptance criteria in this plan

## Invariants

- Preserve source signs, missing values, periods, exact cited evidence, locators, accession, and reported/adjusted separation.
- OpenAI FY2024-FY2026 evidence must render as signed loss/loss/gain; no product hardcoding.
- `primarily related to` must not become full attribution.
- Python may state deterministic facts but must not invent financial judgments.
- Analyst assessment, Reviewer verdict, gate decision, approval, and application status remain distinct.
- Exploratory/human-review/rejected/unresolved candidates never change canonical history or adjusted P&L.
- Discovery remains automatic and contains no MSFT/gold candidate hints.
- Prefer removal and direct local fixes; no new mechanism, stage, policy, UI, framework, or Task 10+ work.

## Acceptance

1. Real MSFT flow run and concise final output captured.
2. OpenAI signs/periods/attribution correct.
3. Xbox and divestiture null amounts remain unresolved.
4. Cross-period output contains no Python-created economic judgment.
5. Tax-position interest grouping does not hardcode rejection.
6. Reviewer, gate, and application state distinct.
7. Human-review candidates do not affect adjusted P&L.
8. Exploratory run leaves canonical adjustment history unchanged.
9. Full relevant tests pass.
10. Ruff and `git diff --check` pass.

## Phases

1. Three independent read-only Luna scouts: financial/judgment; evidence/state; human-output/simplicity.
2. One fresh Luna `max` synthesis and implementation owner; smallest supported fixes only.
3. One fresh Luna `xhigh` simplicity adversary; bounded behavior-preserving deletions only, correctness defects escalate.
4. Closed write barrier; parent Sol gate inspects final CLI output, targeted diff, and terminal evidence; verdict `PASS`, `PASS WITH SMALL FIXES`, or `DO NOT MERGE`.

## Non-goals

No new discovery/retrieval/LLM stages, approval or materiality policy, human-review UI, web UI, RAG, generic reporting/persistence framework, issuer generalization, commit, or push.
