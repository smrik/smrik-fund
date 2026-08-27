# Phase 1 S3 — MSFT scope proposal

Status: FINAL (read-only scout; only this report written). Baseline `f2fd305`; branch `main`.

## Recommendation

Extend `src/smrik_fund/ingestion/statements.py::prepare_pnl` and keep one flat analytical frame. Do not add a derived table, module, dependency, or LLM change. Preserve existing annual-period columns, source metadata, row order, and source values. Add guarded helpers/columns for absolute YoY, growth, percent-of-revenue bps movement, two-year CAGR, pretax/net margins, and bps movement for all margins/ETR. Keep existing `yoy_change_<FY>` as the growth field for compatibility; add a clearly named absolute-change field.

Use the selected annual columns in EdgarTools order (current artifact: FY26, FY25, FY24), but define CAGR explicitly as latest/oldest over two years. Attach subtotal margins by `standard_concept`; never rename or overwrite source rows. `adjustments.apply_adjustments()` already calls `prepare_pnl()` after recomputation (`src/smrik_fund/ingestion/adjustments.py:365`), so reconciliation/adjustment code should remain unchanged.

## Actual MSFT artifact (read-only)

Evidence: `data/MSFT/03_output/analytical_pnl.csv`, `data/MSFT/02_processing/edgar/statements/income_statement.csv`, `data/MSFT/02_processing/edgar/coverage.json`.

- Analytical frame: 21 rows, 34 columns, three annual periods `2026-06-30 (FY)`, `2025-06-30 (FY)`, `2024-06-30 (FY)`; periods are newest-first.
- 13 rows have `standard_concept`; four are dimensional Product/Service-and-Other breakdowns; two are abstract headers. Dimensions are flagged by `dimension=True`; `is_breakdown` is false in this real artifact.
- Expense values are positive magnitudes with `balance=debit`, `weight=-1`; `Other income (expense), net` is signed (`-1.646bn`, `-4.901bn`, `10.697bn` for FY24/FY25/FY26). Preserve both values and metadata.
- The monetary `GrossProfit` row is labelled `Gross margin` by EdgarTools. Preserve that source label; select by concept and show the mismatch in any human sample (do not relabel monetary Gross Profit as a percentage).
- `SellingGeneralAndAdminExpenses` occurs twice: `Sales and marketing` and `General and administrative`; row identity must retain label/metadata qualification, not assume concept uniqueness. EPS rows have concepts but blank `standard_concept`; share rows use `SharesAverage`/`SharesFullyDilutedAverage`.
- `coverage.json` says `years: 2` while the current analytical artifact has three FY periods; treat this as provenance/staleness to report, not a reason to mutate canonical data.

Compact reported sample ($bn, FY24 / FY25 / FY26):

| source label | values |
|---|---:|
| Revenue | 245.122 / 281.724 / 331.839 |
| Cost of revenue | 74.114 / 87.831 / 106.374 |
| Gross margin (`GrossProfit`) | 171.008 / 193.893 / 225.465 |
| Research and development | 29.510 / 32.488 / 35.562 |
| Sales and marketing | 24.456 / 25.654 / 26.710 |
| General and administrative | 7.609 / 7.223 / 7.956 |
| Operating income | 109.433 / 128.528 / 155.237 |
| Other income (expense), net | -1.646 / -4.901 / 10.697 |
| Income before income taxes | 107.787 / 123.627 / 165.934 |
| Provision for income taxes | 19.651 / 21.795 / 32.185 |
| Net income | 88.136 / 101.832 / 133.749 |

Real expected edge evidence: Other-income growth is null for FY25 (negative-to-negative) and FY26 (sign change), while absolute changes are `-3.255bn` and `+15.598bn`; percent-of-revenue is `-0.672% / -1.740% / 3.224%`, with bps movement `-107 / +496`. Gross/operating/pretax/net margin levels are respectively `69.76/68.82/67.94%`, `44.64/45.62/46.78%`, `43.97/43.88/50.00%`, `35.96/36.15/40.31%`; ETR is `18.23/17.63/19.40%`. Corresponding FY25/FY26 bps changes: gross `-94/-88`, operating `+98/+116`, pretax `-9/+612`, net `+19/+416`, ETR `-60/+177`.

## Current gaps and implementation boundaries

- `statements.py:115-123` currently only guards missing/zero prior values; it permits negative-to-negative and sign-changing growth. It has no absolute YoY, bps movement, CAGR, pretax margin, or net margin.
- Existing common-size logic (`statements.py:177-190`) excludes rows only when `standard_concept` is missing or in two share concepts. Add a small local eligibility guard for abstract/dimension/breakdown and explicit EPS/share/ratio concepts; do not build a taxonomy. Missing/zero/invalid revenue remains null. Preserve signed ratios for signed source lines.
- Existing margin logic (`statements.py:192-218`) writes levels only onto the unique concept row. Extend the same path with bps levels/movements and pretax/net margins; no new reconciliation behavior.
- New columns flow into existing discovery/Analyst payload serialization automatically. Keep the frame compact and inspectable; do not touch `discovery.py`, `adjustment_analysis.py`, or reviewer code.

## Tests, sample path, and risks

Add focused synthetic cases in `tests/test_analytical_pnl.py` for all 12 acceptance bullets: positive growth; zero prior; negative-negative; sign change; common size; common-size bps; positive-endpoint CAGR; zero/negative/missing CAGR; gross/operating margin bps; missing null; EPS/share common-size exclusion; source-frame equality. Existing positive/missing/source-preservation tests are reusable. Real smoke should read the ignored CSV only and assert three periods plus the 12 existing reconciliation checks; current read-only `reconcile_pnl()` result is 12/12 PASS.

Expected scope: one production file plus one focused test file, roughly 50–100 production lines and 80–140 test lines. Stop with `DECISION_REQUIRED` before exceeding 150–200 net new production lines. Non-goals: anomaly scores, thresholds/judgment, materiality, normalization, review fields, retrieval, segments, forecasts, LLM calls, classes/services/providers/config/taxonomy, data refresh, or reconciliation rewrites.

Verification owner should run: `python -m pytest tests/test_analytical_pnl.py -q`; relevant reconciliation/adjustment tests; full `python -m pytest -q`; Ruff on changed Python; `git diff --check`; and the real MSFT sample. This scout ran no test or data-refresh command.

## Dirty-diff overlap

Current dirty tracked surfaces are `.out-of-code-insights/**`, `docs/ai_fund_v1_section_2_implementation_spec.md`, `docs/annotations/**`, `src/smrik_fund/main.py`, and `tests/test_adjustment_analysis.py`; the assigned analytical/reconciliation surfaces (`statements.py`, `test_analytical_pnl.py`, `reconciliation.py`, `adjustments.py`) are clean versus `HEAD`. Preserve all dirty work, especially `main.py`/adjustment tests and annotation artifacts; do not edit ignored `data/**` or commit/merge.
