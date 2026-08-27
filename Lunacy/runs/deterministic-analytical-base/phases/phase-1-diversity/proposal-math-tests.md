# S2 proposal — analytical math, nulls, and tests

## Approach

- Keep one canonical path in `src/smrik_fund/ingestion/statements.py:129-220` (`prepare_pnl`); extend the derived wide view only. No changes needed to reconciliation or adjustment mechanics unless a regression test proves otherwise.
- Preserve existing `yoy_change_<FY>` as the growth field for compatibility; add explicit absolute-change, ratio-bps, margin/ETR-bps, and one `two_year_cagr` (or equivalently named) field. Use latest-first EdgarTools periods: FY3=`selected_periods[0]`, FY1=`selected_periods[2]`.
- Use numeric coercion only for calculations; treat non-numeric/non-finite values as unavailable. Never write back to input or replace missing with zero.

## Formula contract

- `absolute_yoy_change_t = current_t - prior_t` when both finite; otherwise null.
- Growth remains null unless both finite, `prior != 0`, signs do not differ (`current * prior >= 0`), and values are not both negative. This retains absolute change for negative-to-negative and sign-change pairs.
- Common size is `line / revenue` using the displayed signed/magnitude value (no `abs`); null for missing, non-finite, zero, or economically invalid revenue, and for non-monetary/meaningless rows.
- Ratio movement is `(ratio_t - ratio_prior) * 10_000`; no growth/sign rule is applied to ratio movement. Null if either ratio is unavailable.
- Levels: Gross/Operating/Pre-tax/Net margin = corresponding subtotal / Revenue; ETR = Income taxes / Pre-tax income. Bps fields use the same ratio-movement rule.
- Two-year CAGR is `sqrt(latest / oldest) - 1` only when at least three selected periods and both endpoint values are finite and strictly positive. Zero, negative, missing, or invalid endpoints yield null; do not force with absolute values.

## Eligibility and output risks

- Current `SHARE_CONCEPTS` exclusion is too narrow (`statements.py:17,179`): also exclude explicit EPS and weighted-share concepts (at minimum `EarningsPerShareBasic`, `EarningsPerShareDiluted`, `SharesAverage`, `SharesFullyDilutedAverage`, weighted-average/share-outstanding variants) from common size and its bps change. Exclude truthy `abstract`/`dimension`/`is_breakdown`; preserve row reported values and other mathematically meaningful metrics.
- Emit stable metric columns even when Revenue or a subtotal concept is absent/ambiguous, filled null, so consumers distinguish “metric unavailable” from “schema changed”. Keep existing source/period columns and names intact.
- Duplicate/ambiguous standard concepts should fail closed for derived subtotal levels; do not silently choose a row. Row-level common size remains possible for an unambiguous source row, subject to eligibility.

## Adjustment/reconciliation interaction

- `reconcile_pnl` identifies only annual columns (`reconciliation.py:244-429`), so appended metric columns are ignored safely.
- `apply_adjustments` recalculates subtotals then calls `prepare_pnl` (`adjustments.py:312-365`); the same extension will recompute all metrics on adjusted values. Existing reported-vs-adjusted and adjusted-reconciliation invariants remain intact if metric columns are overwritten deterministically, not accumulated.
- Do not alter `_recalculate_subtotals`, source reconciliation, materiality, gate, identity, or adjustment sign logic. Add one cheap adjustment regression assertion that a changed source line updates dependent margin/bps fields and does not mutate the reported input.

## Focused synthetic tests (`tests/test_analytical_pnl.py`)

1. positive growth (Revenue 120/100 = 0.20);
2. zero prior denominator => null growth but valid absolute change;
3. negative-to-negative => null growth, valid absolute change;
4. sign change => null growth, valid absolute change;
5. percent of revenue (e.g. Cost 60 / Revenue 120 = 0.50);
6. percent-of-revenue bps (e.g. 0.50 to 0.55 = -500 bps latest-vs-prior);
7. positive endpoint CAGR (`sqrt(120/80)-1`);
8. zero/negative/missing endpoints => null CAGR;
9. gross/operating margin bps movement;
10. missing source remains null across required dependent metrics;
11. EPS and share rows have null common-size and common-size-bps fields;
12. deep-equal source before/after, including signed values and NaN positions.

Also retain existing analytical save/build tests and run one adjustment test through `apply_adjustments`; no new fixture framework is needed.

## Invariants / non-goals

- Reported values, signs, periods, metadata, missingness, reconciliation semantics, and adjustment behavior unchanged.
- Python supplies numerical context only; no anomaly judgment, thresholds, ranking, normalization, retrieval, LLM calls, classes, dependencies, or parallel output path.
- Estimated scope: one production file, one focused test file (optionally one existing adjustment assertion), roughly 40–90 net production lines. Stop and request a decision before exceeding 150–200 net new production lines.

## Verification / current baseline

- Required after implementation: focused analytical tests, relevant reconciliation/adjustment tests, full suite, Ruff on changed Python, `git diff --check`, and real MSFT sample inspection.
- Current `python -m pytest tests/test_analytical_pnl.py -q` cannot collect in the base interpreter: `ModuleNotFoundError: No module named 'pandas'`; this is an environment blocker, not a source failure. No source/tests/config changed by this scout.

**Recommendation: proceed with the single `prepare_pnl` extension and focused edge-case tests; preserve existing interfaces and fail closed on every unavailable denominator/endpoint.**
