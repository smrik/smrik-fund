# R1 terminal evidence

## Verification

- `$env:PYTHONPATH='src'; C:\Users\patri\miniconda3\envs\ai-fund\python.exe -m pytest tests/test_analytical_scan.py -q -p no:cacheprovider`: 10 passed.
- `$env:PYTHONPATH='src'; C:\Users\patri\miniconda3\envs\ai-fund\python.exe -m pytest tests/test_analytical_scan.py tests/test_analytical_pnl.py -q -p no:cacheprovider`: 21 passed.
- `$env:PYTHONPATH='src'; C:\Users\patri\miniconda3\envs\ai-fund\python.exe -m pytest -q -p no:cacheprovider`: 153 passed, 45 subtests passed.
- `ruff check src/smrik_fund/ingestion/analytical_scan.py src/smrik_fund/ingestion/statements.py tests/test_analytical_scan.py`: all checks passed.
- AST parse/compile check for changed Python: passed.
- `git diff --check`: passed; existing line-ending warnings only.

## Repair probes

- Cached `data/MSFT/03_output/analytical_pnl.csv` formatter: share movement has no `$` and includes `shares`; three annual FY periods preserved.
- Boundary test keeps supplied canonical `yoy_growth=-1.0` but renders boundary growth and supplied boundary CAGR as `N/A`.
- Alias test removes a same-concept/value row differing only by presentation label, preserves a distinct dimension member, and preserves two unidentified rows because alias identity is not provable.
