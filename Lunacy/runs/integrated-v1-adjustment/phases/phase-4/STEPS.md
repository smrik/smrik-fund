# Phase 4 — Sol gate

Status: COMPLETE — PASS

Gate scout only if required by final writer/report state.

Sol independently inspects targeted actual code/diff/behavior and answers:

1. Does one real command exercise Analyst -> Reviewer -> gate?
2. Is financial judgment confined to LLM stages?
3. Is accounting/application deterministic?
4. Can human-review candidates ever affect adjusted P&L?
5. Were existing mechanisms reused rather than duplicated?
6. Is Xbox correctly preserved and unapplied?

Run one bounded end-to-end acceptance proof. Verdict: PASS, PASS WITH SMALL FIXES, or DO NOT MERGE.

## G1 — read-only gate scout

Status: COMPLETE

Required because the synthesis owner and simplicity adversary both changed the integrated `main.py` surface and the task is cross-stage/high-integrity. Compress exact final call-path, persistence, non-application, accounting-boundary, verification, and diff navigation into `Lunacy/runs/integrated-v1-adjustment/gates/G1.md`. No approval, source/test/config edits, or broad-suite rerun.

## R1 — live EdgarTools annual-period boundary repair

Status: COMPLETE

Owner: fresh `gpt-5.6-luna` at `xhigh`.

The real command is blocked before Analyst because current EdgarTools standard-view columns are bare ISO annual dates (`2026-06-30`, etc.) while the established analytical/Analyst contract requires canonical `2026-06-30 (FY)` labels. Make the smallest boundary normalization needed for `build_analytical_pnl` to accept live bare annual dates and emit the established `(FY)` labels. Preserve raw values, signs, missing values, order, and all unrelated dirty statements work. Add focused proof and run impacted/full terminal verification. No retrieval redesign, fallback, stale cached substitution, or integration-policy change. Immutable report: `Lunacy/runs/integrated-v1-adjustment/reports/R1.md`.

## G2 — repaired-state gate scout

Status: COMPLETE

Fresh read-only pack after R1 and the real networked command reach a terminal state. Immutable `Lunacy/runs/integrated-v1-adjustment/gates/G2.md`.
