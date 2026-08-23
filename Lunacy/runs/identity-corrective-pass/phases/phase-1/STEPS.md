# Phase 1 steps

## O1 — Legacy-history and target-row correction

Status: COMPLETED — PASS

Owner: one fresh GPT-5.6 Luna xhigh writer.

Read first: project `AGENTS.md`; `docs/ai_fund_v1_section_1_updated.md`; `docs/ai_fund_v1_section_2_implementation_spec.md`; relevant current `main.py`, history/application, P&L row selection, and identity/lifecycle tests; `C:\Users\patri\.codex\skills\lunatic-hive\worker\ENGINEERING.md`.

Contract:

- Inspect actual current diff and implementation before editing.
- Distinguish inert legacy non-effective rows from unknown effective legacy rows and malformed v2 rows. Inert legacy proposed rows must neither apply nor block v2 matching. Unknown effective legacy and malformed v2 must fail closed. Do not migrate or rewrite history.
- Use the smallest deterministic target-row identity supported by current P&L fields: prefer a unique standard concept independent of label; disambiguate duplicate concepts with existing row metadata, normally label; deterministic label fallback when concept missing; reject derived subtotals before identity.
- Preserve all existing economic identity, exact matching, state fingerprint, provenance exclusion, sign/direction, Reviewer policy, retrieval, and approved-version semantics.
- Add the user's required history and row-key tests. Avoid unrelated cleanup and infrastructure.
- Run focused identity/history, lifecycle/idempotence, adjustment engine, full suite, Ruff changed Python, and `git diff --check`. Attempt live MSFT only if credentials are visible; do not fake it.
- Inspect final diff and report exact production added/deleted lines.

Report: `Lunacy/runs/identity-corrective-pass/reports/O1.md` (immutable after FINAL). Long evidence under this run only.
