# Phase 3 R1 repair report

Verdict: **PASS / DO NOT MERGE**. A1 P1 is repaired; the overall run remains
subject to the parent Sol gate.

## Changed

- `src/smrik_fund/ingestion/statements.py`: `_text()` now removes all
  non-alphanumeric separators before marker matching. Label-only rows such as
  `Shares outstanding` therefore fail closed for common-size and
  percent-of-revenue bps metrics even when `standard_concept` is missing.
- `tests/test_analytical_pnl.py`: extended the focused EPS/share eligibility
  fixture with `concept=custom_shares`, `label=Shares outstanding`, and no
  standard concept. Its common-size level and bps fields are asserted null for
  all selected periods while growth/CAGR remain available.

The repair changed one existing production line and added one net test line.
The combined current diff remains `statements.py +193/-46` production lines
(`+147` net) and `test_analytical_pnl.py +139/-0`; the earlier Phase 2 work is
unchanged. No LLM, adjustment, identity, review, reconciliation, or canonical
data code was changed. No commit, merge, or push.

## Terminal verification

- `$env:PYTHONPATH='src'; & 'C:\Users\patri\miniconda3\envs\ai-fund\python.exe' -m pytest tests/test_analytical_pnl.py -q` -> **10 passed** (4 existing warnings).
- Same interpreter, `tests/test_adjustments.py tests/test_reconciliation.py -q` -> **25 passed**, 4 subtests (4 existing warnings).
- Same interpreter, `-m pytest -q` -> **142 passed**, 45 subtests (4 existing warnings).
- `ruff check src/smrik_fund/ingestion/statements.py tests/test_analytical_pnl.py` -> **All checks passed**.
- `git diff --check` -> **exit 0**; only existing CRLF conversion warnings.

Read-only local MSFT sanity: input `data/MSFT/02_processing/edgar/statements/income_statement.csv`
was `(21, 19)`; `prepare_pnl(..., years=3)` was `(21, 65)` for FY26/FY25/FY24;
`reconcile_pnl` returned 12/12 `PASS`; source frame remained unchanged. The
sample retained signed other income and null FY26 growth for its sign change,
plus the expected monetary common-size and margin/bps fields. No CSV/data
refresh or write occurred. The local import emitted the pre-existing Edgar
locale-cache permission warning only.

## Simplicity / findings

One shared text-normalization seam fixes the label-only edge without a second
eligibility path or special-case row mapping. P2 remains operational only:
the ignored persisted MSFT analytical CSV is stale until a future explicit
`analyze MSFT` run; it was not refreshed here. Existing dirty user files and
annotation artifacts were preserved.
