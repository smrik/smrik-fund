# Phase 2 I1 implementation report

Status: PASS / DO NOT MERGE

## Scope and proposal judgment

Implemented the single-wide-frame recommendation in `prepare_pnl`; no second
derived table, new dependency, LLM call, CLI change, data refresh, or
adjustment/reconciliation rewrite.

Accepted the three proposals' common core: one canonical Pandas calculation
path, fail-closed growth/CAGR/null handling, compatibility `yoy_change_*`,
and focused synthetic tests. For common size, retained meaningful dimension
rows when `is_breakdown` is false, while excluding abstract/breakdown,
EPS/share, and ratio rows; this preserves the existing breakdown test and the
real MSFT monetary breakdowns.

## Changed

- `src/smrik_fund/ingestion/statements.py`: finite guarded absolute YoY,
  explicit `yoy_growth_*`, compatibility growth alias, signed common size and
  bps movement, two-year positive-endpoint CAGR, gross/operating/pretax/net
  margin levels plus bps movement, and ETR bps movement.
- `tests/test_analytical_pnl.py`: focused coverage for all 12 required math,
  null, eligibility, and source-preservation cases.
- Production diff: `+193 / -46` lines (`+147` net); tests `+138 / -0`.

No changes to dirty `main.py`, adjustment-analysis tests, annotation files, or
canonical `data/**`. No commit/merge/push.

## Verification

Exact terminal output and the printed MSFT sample are in
`evidence/terminal-verification.md`.

- `$env:PYTHONPATH='src'; & 'C:\Users\patri\miniconda3\envs\ai-fund\python.exe' -m pytest tests/test_analytical_pnl.py -q` -> 10 passed.
- Same interpreter, `tests/test_adjustments.py tests/test_reconciliation.py -q` -> 25 passed, 4 subtests.
- Same interpreter, `-m pytest -q` -> 142 passed, 45 subtests.
- `ruff check src/smrik_fund/ingestion/statements.py tests/test_analytical_pnl.py` -> All checks passed.
- `git diff --check` -> exit 0; only existing CRLF conversion warnings.

The default `python` lacked Pandas; no install was attempted. The installed
`ai-fund` interpreter with `PYTHONPATH=src` supplied the verified path.

## Real MSFT findings

Local source `data/MSFT/02_processing/edgar/statements/income_statement.csv`
produced 21 rows x 65 columns, with FY26/FY25/FY24 newest-first and all 12
reconciliation checks passing. Reported values, signs, labels, and metadata
remain unchanged; `GrossProfit` retains EdgarTools' `Gross margin` label.
The sample records negative/sign-changing other income as null growth while
retaining absolute and ratio-bps movements; margin levels/bps are included in
the evidence table.

Terminal verdict: PASS / DO NOT MERGE.
