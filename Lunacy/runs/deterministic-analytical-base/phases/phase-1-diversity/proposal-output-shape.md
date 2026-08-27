# Phase 1 S1 — analytical output-shape proposal

Status: FINAL (read-only scout; report is the only write)

## Current repo reality

- Canonical path: `ingestion/statements.py::prepare_pnl` (lines 129–220) copies
  the EdgarTools income-statement frame, keeps the first three annual columns,
  and appends derived columns. `build_analytical_pnl` and `save_analytical_pnl`
  are thin wrappers (223–259); `main.analyze` calls this path (2230–2268).
- Current saved MSFT shape: 21 rows x 34 columns, FY26/FY25/FY24, 19 rows
  with values and 2 abstract rows without values. Existing derived columns are
  `yoy_change_*` (currently growth), `percent_of_revenue_*`,
  `gross_margin_*`, `operating_margin_*`, and `effective_tax_rate_*`.
- Real MSFT has four dimension breakdown rows (`Product`, `Service and Other`),
  two EPS rows whose `concept` identifies `EarningsPerShare`, two share rows,
  duplicate `SellingGeneralAndAdminExpenses` concepts (Sales and marketing vs
  General and administrative), and a `GrossProfit` row labelled `Gross margin`.
  Do not relabel or collapse these source rows.
- `adjustments.py::apply_adjustments` copies source, recalculates subtotals,
  then calls `prepare_pnl` (312–365). `reconciliation.py::reconcile_pnl`
  only discovers annual FY columns (244–426); extra metrics are inert. No
  changes are needed in either surface, `main.py`, or any LLM module.

## Recommendation: extend the existing wide frame

Keep `analytical_pnl.csv` and the existing one-row-per-source-row shape. A
second derived table would duplicate persistence/selection and create drift;
the current 34-column wide shape is already the established CSV/LLM contract,
and a flat prefixed extension remains inspectable. Keep source metadata and FY
columns in their current order, then append stable metric groups:

```text
absolute_yoy_change_<FY>
yoy_growth_<FY>
yoy_change_<FY>                 # compatibility alias of yoy_growth, one calculation
percent_of_revenue_<FY>
percent_of_revenue_bps_change_<FY>
gross_margin_<FY> + gross_margin_bps_change_<FY>
operating_margin_<FY> + operating_margin_bps_change_<FY>
pretax_margin_<FY> + pretax_margin_bps_change_<FY>
net_margin_<FY> + net_margin_bps_change_<FY>
effective_tax_rate_<FY> + effective_tax_rate_bps_change_<FY>
two_year_cagr
```

Use the current-first period order: YoY compares positions 0→1 and 1→2;
`two_year_cagr` compares positions 0 and 2 (null when fewer than three periods).
Keep the old `yoy_change_*` values as a compatibility alias because persisted
CSV/tests currently use that name; calculate growth once and assign both names.

Implement locally in `statements.py`: one safe numeric absolute-change helper,
one fail-closed growth helper, one ratio-level/bps pass, and one endpoint CAGR
pass. Row-level percent-of-revenue must be based on displayed signed values,
not absolute values. Exclude abstract rows and EPS/share/ratio rows from
common-size only; include meaningful non-abstract dimension breakdowns. Detect
EPS from the existing concept text and shares from `SHARE_CONCEPTS`, without a
taxonomy. Growth/absolute change/CAGR may remain available for numeric EPS or
share rows; their common-size and ratio-bps fields stay null.

Math contract: absolute change requires both values; growth requires both,
nonzero prior, no sign crossing, and not both negative; ratios require valid
finite denominators and both levels for bps; bps is `(current - prior)*10000`;
CAGR requires finite positive endpoints and uses `(newest/oldest)**0.5 - 1`.
Never coerce missing/invalid values to zero. Preserve all source columns/values
and source period order.

## Maintained surfaces, invariants, and non-goals

- Modify only `src/smrik_fund/ingestion/statements.py` and the existing focused
  `tests/test_analytical_pnl.py` in Phase 2; no new module, dependency, config,
  CLI, formatter, LLM call, adjustment, identity, materiality, review, or
  reconciliation change.
- `apply_adjustments` must recalculate every new field through the same
  `prepare_pnl` call; reported inputs remain deep-copy/byte-equivalent.
- Keep derived subtotal rows identified by standard concept. Add pre-tax/net
  margins but do not create adjustment targets, plugs, anomaly scores,
  thresholds, ranking, normalization, forecast, segment, or retrieval logic.

## Risks and verification

- Zero-current/negative-to-zero growth boundary needs one explicit test;
  interpret “sign change” consistently (recommended: product `< 0` is a
  crossing, while the explicit both-negative rule still fails closed).
- Real MSFT’s `GrossProfit` label and dimension rows test that source labels and
  duplicate concepts are not normalized away. `Other income (expense), net`
  is positive in FY26 but negative in FY25/FY24, so growth/CAGR must fail closed
  where signs/endpoints invalidate them.
- Add focused synthetic assertions for the 12 requested cases in the existing
  fixture, retain current save/build checks, then run adjustment and
  reconciliation tests to prove new columns are inert to their contracts.
  Implementer should inspect the real FY26/FY25/FY24 sample and run the full
  mandated matrix, Ruff, and `git diff --check`.

Estimated Phase 2 delta: 60–100 net production lines in `statements.py`,
roughly 90–140 test lines in the existing analytical test file; comfortably
below the 150–200 production-line decision gate.

## Pre-existing dirty state (do not overwrite)

Before Phase 2, `git status` showed generated annotation changes/untracked
files, plus unrelated `docs/ai_fund_v1_section_2_implementation_spec.md`,
`src/smrik_fund/main.py` (+74/−12), and `tests/test_adjustment_analysis.py`
(+140/−4). The active run files are also untracked. None overlap the proposed
statement/test surfaces; preserve them and do not stage/commit/merge.
