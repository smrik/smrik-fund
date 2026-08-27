# Phase 4 R3 repair report

Verdict: **PASS / DO NOT MERGE**. The Sol G2 eligibility leak is repaired;
parent Sol remains authoritative for the final gate.

## Changed

- `src/smrik_fund/ingestion/statements.py:34-43,171-191`: generic
  `standard_concept` rows now inspect normalized share/EPS text markers in
  `concept` and `label`. `Shares outstanding` and `Revenue per share` therefore
  fail closed even with `standard_concept=CustomMetric`; margin/ratio label
  markers are not applied to this row-level check, preserving monetary
  `GrossProfit` when EdgarTools labels it `Gross margin`.
- `tests/test_analytical_pnl.py:293-345`: focused proof covers both generic
  custom share/EPS labels and the monetary GrossProfit/margin-label case;
  growth/CAGR remain available for excluded rows.
- Repair delta: production `+15/-0`; tests `+22/-0`. Combined current diff
  remains within the run's bounded analytical-P&L scope. No LLM, adjustment,
  identity, review, reconciliation, or canonical data code changed. No
  commit, merge, or push.

## Terminal verification

- `$env:PYTHONPATH='src'; & 'C:\Users\patri\miniconda3\envs\ai-fund\python.exe' -m pytest tests/test_analytical_pnl.py -q -p no:cacheprovider` -> **11 passed**, 3 warnings.
- Same interpreter, `tests/test_adjustments.py tests/test_reconciliation.py -q -p no:cacheprovider` -> **25 passed**, 4 subtests, 3 warnings.
- Same interpreter, `-m pytest -q -p no:cacheprovider` -> **143 passed**, 45 subtests, 3 warnings.
- `ruff check src/smrik_fund/ingestion/statements.py tests/test_analytical_pnl.py` -> **All checks passed**.
- `git diff --check` -> **exit 0**; only existing LF/CRLF conversion warnings.
- Direct eligibility probe -> `[False, False, True]` for generic
  `Shares outstanding`, generic `Revenue per share`, and `GrossProfit` /
  `Gross margin`, respectively.

## Bounded real-MSFT sanity / self-review

- Read-only local input `data/MSFT/02_processing/edgar/statements/income_statement.csv`
  -> `(21, 19)`; `prepare_pnl(..., years=3)` -> `(21, 65)` with annual
  periods FY26/FY25/FY24; source unchanged; reconciliation **12/12 PASS**.
- Real MSFT `GrossProfit` retains label `Gross margin` and has
  `percent_of_revenue_2026-06-30 (FY)=0.6794409337`. No canonical data write.
- Final diff inspection found only the bounded eligibility/test repair plus
  pre-existing analytical implementation and unrelated dirty files/run
  artifacts. Stale persisted CSV residual remains as documented in
  `gate-pack-2.md`; refresh was not authorized.
