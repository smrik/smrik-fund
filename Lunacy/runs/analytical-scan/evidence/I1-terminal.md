# I1 terminal evidence

## Verification

- `pytest tests/test_analytical_scan.py -q -p no:cacheprovider`: 7 passed.
- Focused adjustment/P&L/reconciliation/reviewer/review tests: 74 passed, 11 subtests.
- `pytest -q -p no:cacheprovider`: 150 passed, 45 subtests.
- Ruff passed on the changed Python files; explicit `py_compile` to a temporary
  cache passed; `git diff --check` passed.

## Cached MSFT formatter smoke test

- Input: `data/MSFT/03_output/analytical_pnl.csv` (21 rows; FY26, FY25, FY24).
- Output: 10,022 characters; no case-insensitive `nan` token.
- Verified revenue/cost-of-revenue Product hierarchy, gross/operating/pretax/net
  margins, effective tax rate, and EPS/shares sections.

## Live path

- Attempted `smrik-fund analyze MSFT --scan --output-root` under an isolated
  evidence root.
- EdgarTools stopped before P&L construction at the Windows socket boundary:
  `ConnectError: [WinError 10013]`.
- No live scan JSON was produced; no credential files were read.
