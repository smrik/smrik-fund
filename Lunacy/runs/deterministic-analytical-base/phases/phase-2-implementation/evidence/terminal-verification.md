# I1 terminal verification evidence

Final implementation state was verified with the existing local data and the
already-installed `ai-fund` environment. No dependency installation or data
refresh was performed.

## Commands and results

```text
$env:PYTHONPATH='src'; & 'C:\Users\patri\miniconda3\envs\ai-fund\python.exe' -m pytest tests/test_analytical_pnl.py -q
10 passed, 4 warnings

$env:PYTHONPATH='src'; & 'C:\Users\patri\miniconda3\envs\ai-fund\python.exe' -m pytest tests/test_adjustments.py tests/test_reconciliation.py -q
25 passed, 4 warnings, 4 subtests passed

$env:PYTHONPATH='src'; & 'C:\Users\patri\miniconda3\envs\ai-fund\python.exe' -m pytest -q
142 passed, 4 warnings, 45 subtests passed

ruff check src/smrik_fund/ingestion/statements.py tests/test_analytical_pnl.py
All checks passed!

git diff --check
exit 0; only existing CRLF conversion warnings for dirty files
```

The default `python` interpreter could not collect tests because it lacks
Pandas (`ModuleNotFoundError: No module named 'pandas'`). The installed
`ai-fund` interpreter has Pandas 2.3.3 and all project imports when
`PYTHONPATH=src` is set.

## Local MSFT sample

Input: `data/MSFT/02_processing/edgar/statements/income_statement.csv`.
`prepare_pnl` output: 21 rows x 65 columns; annual periods are FY26, FY25,
FY24 in source/newest-first order. `reconcile_pnl` returned 12 checks, all
`PASS`.

Values below are $bn; percentage metrics are percent; movement metrics are
bps. The table is printed from the final `prepare_pnl` output.

| label | FY24 | FY25 | FY26 | FY26 abs YoY | FY26 growth | FY26 % rev | FY26 % rev bps | 2y CAGR |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Revenue | 245.122 | 281.724 | 331.839 | 50.115 | 17.789 | 100.000 | 0.000 | 16.352 |
| Cost of revenue | 74.114 | 87.831 | 106.374 | 18.543 | 21.112 | 32.056 | 87.965 | 19.803 |
| Gross margin (GrossProfit) | 171.008 | 193.893 | 225.465 | 31.572 | 16.283 | 67.944 | -87.965 | 14.824 |
| Research and development | 29.510 | 32.488 | 35.562 | 3.074 | 9.462 | 10.717 | -81.521 | 9.776 |
| Sales and marketing | 24.456 | 25.654 | 26.710 | 1.056 | 4.116 | 8.049 | -105.699 | 4.507 |
| General and administrative | 7.609 | 7.223 | 7.956 | 0.733 | 10.148 | 2.398 | -16.631 | 2.255 |
| Operating income | 109.433 | 128.528 | 155.237 | 26.709 | 20.781 | 46.781 | 115.886 | 19.103 |
| Other income (expense), net | -1.646 | -4.901 | 10.697 | 15.598 | null | 3.224 | 496.320 | null |
| Income before income taxes | 107.787 | 123.627 | 165.934 | 42.307 | 34.221 | 50.004 | 612.206 | 24.075 |
| Provision for income taxes | 19.651 | 21.795 | 32.185 | 10.390 | 47.671 | 9.699 | 196.269 | 27.978 |
| Net income | 88.136 | 101.832 | 133.749 | 31.917 | 31.343 | 40.305 | 415.937 | 23.188 |

Margin levels FY24/FY25/FY26 and bps changes FY25/FY26:

```text
Gross margin: 69.764%, 68.824%, 67.944%; -94.070, -87.965
Operating margin: 44.644%, 45.622%, 46.781%; 97.766, 115.886
Pretax margin: 43.973%, 43.882%, 50.004%; -9.049, 612.206
Net margin: 35.956%, 36.146%, 40.305%; 19.004, 415.937
Effective tax rate: 18.231%, 17.630%, 19.396%; -60.168, 176.662
```
