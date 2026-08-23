# Phase 1 steps

## O1 — Manifest comparison, review, cleanup, docs, verification

Status: COMPLETED — PASS

Owner: fresh GPT-5.6 Luna xhigh writer.

Read first: project `AGENTS.md`; current docs Sections 1/2; completed corrective reports `Lunacy/runs/identity-corrective-pass/reports/R2.md` and `A3.md`; current code/diff/tests/history/application; `C:\Users\patri\.codex\skills\lunatic-hive\worker\ENGINEERING.md`.

Manifest comparison:

- Old: `data/MSFT/03_output/analysis/adjustment_run_20260822T145101565886Z.json`.
- New: `data/MSFT/03_output/analysis/adjustment_run_20260822T183907711663Z.json`.
- Report every candidate's `item_key`, economic identity, target row key, identity status/reason, duplicate condition/reason, final/application status, and meaningful old/new change. Explicitly assess OpenAI periods, Xbox source vs derived subtotal, UTP, legacy-history poisoning, provenance exclusion, history writes/effective P&L, and reconciliation.

Review/cleanup/docs:

- Inspect `git status --short`, `git diff --stat`, full relevant diff, and surrounding active paths.
- Verify stable economic identity, exact occupied-row matching, strict malformed/effective legacy fail-closed behavior, inert legacy handling, row-key stability, application through row key, proposal/version fingerprint, approved supersession without stacking, sign/direction algebra, and LLM/Python boundary.
- Remove/simplify only concrete milestone bloat or stale compatibility paths. No new abstractions or unrelated cleanup.
- Ensure Sections 1/2 accurately describe identity, provenance exclusion, conservative matching, inert legacy vs corrupt/effective legacy, target-row key rule, and approved-version semantics. Do not document future functionality as present.
- Do not modify/delete canonical data or live manifests. Remove only verification artifacts created by this step.
- Run focused identity/history/lifecycle/adjustment-engine/Analyst/Reviewer/risk tests, full suite, Ruff all changed Python, and `git diff --check`.

Report: `Lunacy/runs/identity-merge-pass/reports/O1.md`. Evidence: `Lunacy/runs/identity-merge-pass/evidence/manifest-comparison.md` and bounded logs if needed. No commit/merge/push.
