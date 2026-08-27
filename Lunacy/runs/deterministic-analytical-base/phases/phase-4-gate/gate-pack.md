# G1 gate pack — deterministic analytical base

## Snapshot

- Baseline/current HEAD: `f2fd3057dc415c484d19f2b7214393da0f53eb5b`; final diff inspected against `f2fd305`.
- In-scope final diff is limited to `src/smrik_fund/ingestion/statements.py` (`+193/-46`, `+147` net) and `tests/test_analytical_pnl.py` (`+139/-0`). No source/test edits were made by G1; production write barrier remains closed.
- Source slices: numeric guards/eligibility `statements.py:131-229`; one canonical `prepare_pnl` path and metric passes `:268-365`.
- Test slices: existing source/period/metric preservation `test_analytical_pnl.py:118-207`; new guard/CAGR/common-size/margin coverage `:209-346`.

## Acceptance mapping

- Positive growth and absolute change: `statements.py:179-203`, tests `:209-235`.
- Zero prior, negative-to-negative, sign change, and missing values fail closed while absolute change remains when defined: tests `:224-270`.
- Percent of revenue and ratio-bps movement: `statements.py:298-319`, tests `:272-290`.
- Positive-endpoint CAGR and zero/negative endpoint nulls: `statements.py:287-296`, tests `:209-259`.
- Gross/operating/pre-tax/net margin and ETR levels plus bps: `statements.py:321-365`, tests `:324-346`.
- EPS/share/ratio/abstract/breakdown eligibility and source immutability: `statements.py:161-176`, tests `:118-207` and `:292-322`.
- Period selection and reported values stay in the copied source columns: `statements.py:249-266`, tests `:118-207`.

## Verification authority

- R1 repair report claims final-state focused analytical `10 passed`, adjustment/reconciliation `25 passed` (4 subtests), full suite `142 passed` (45 subtests), Ruff clean, and `git diff --check` exit 0: `phases/phase-3-simplicity/repair-report.md:17-37`.
- The detailed terminal output is the pre-repair Phase-2 artifact at `phases/phase-2-implementation/evidence/terminal-verification.md:6-58`; R1 reports reran the matrix but supplies no separate raw final log.
- G1 bounded check (no broad suite rerun): `PYTHONPATH=src; ...python.exe -m pytest tests/test_analytical_pnl.py -k 'excludes_eps_and_share_common_size_metrics or exposes_all_margin_levels_and_bps_changes' -q` -> `2 passed, 8 deselected, 4 warnings`.
- Reported real-MSFT sanity: input `21x19`; `prepare_pnl(..., years=3)` `21x65`, FY26/FY25/FY24 newest-first, source unchanged, reconciliation `12/12 PASS`; sample and values are in `phases/phase-2-implementation/evidence/terminal-verification.md:31-58` and R1 `:31-37`.

## Residuals / contradictions for G2

1. **A1 P1 is resolved.** `_text()` now strips separators (`statements.py:155-158`), so label-only `Shares outstanding` is excluded; the repaired fixture asserts null common-size and bps fields (`test_analytical_pnl.py:292-322`), and G1's bounded check passes.
2. **P2 remains operational.** Ignored `data/MSFT/03_output/analytical_pnl.csv` currently has 34 columns and zero new-metric headers; the current `prepare_pnl` result is 65 columns. `load_analytical_pnl`/downstream consumers remain stale until an explicit analyze/write run. This conflicts with the Task-2 acceptance phrase “analytical_pnl.csv written,” but data refresh was explicitly out of the implementation/simplicity scope (`simplicity-report.md:19-24`; `repair-report.md:41-45`).
3. **Missing-CAGR proof gap.** Runtime `two_year_cagr` is guarded by positive finite endpoints (`statements.py:287-296`), but the “missing” test loop `:261-270` does not assert missing `two_year_cagr`; the reports' “all 12 cases” claim overstates the exact focused assertion coverage.
4. Existing unrelated dirty files were preserved: `main.py`, `tests/test_adjustment_analysis.py`, the modified implementation-spec/annotation artifacts, and untracked run/annotation artifacts. No final approval is issued by G1; G2/Sol owns the gate decision.
