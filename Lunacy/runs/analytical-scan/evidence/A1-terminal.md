# A1 terminal evidence

## Final verification

- `$env:PYTHONPATH='src'; C:\Users\patri\miniconda3\envs\ai-fund\python.exe -m pytest tests/test_analytical_scan.py tests/test_analytical_pnl.py -q -p no:cacheprovider`: 18 passed.
- `ruff check src/smrik_fund/ingestion/analytical_scan.py src/smrik_fund/ingestion/statements.py`: all checks passed.
- `git diff --check`: passed (pre-existing line-ending warnings only).

## Adversarial probes

- Cached `data/MSFT/03_output/analytical_pnl.csv` formatter output shows share movement as `abs=-$4,000,000` and `abs=-$12,000,000` on the Basic/Diluted share rows; those are share counts, not dollars.
- A formatter probe appending a same-value `Revenue alias` row retained both `[L01] Revenue` and `[L22] Revenue alias`; `_signature()` includes label/path, so duplicate aliases are not removed.
- A `prepare_pnl()` probe with Other income values FY26=`0`, FY25=`-2`, FY24=`-1` returned FY26 `yoy_growth=-1.0`; zero-boundary sign transitions are not guarded as N/A.
