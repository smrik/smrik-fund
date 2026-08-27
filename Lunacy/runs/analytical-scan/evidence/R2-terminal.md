# R2 terminal evidence

## Contract repair

- Rendered scan rows now use explicit `line_ref=L##` markers; no bracketed row
  syntax remains in the formatter output.
- Prompt/schema require bare `L##` values in `affected_line_refs`.
- Extraction reads only `line_ref=L##`; Pydantic item validation rejects bracketed
  or otherwise decorated refs before the existing exact supplied-row check.

## Verification

- `$env:PYTHONPATH='src'; C:\Users\patri\miniconda3\envs\ai-fund\python.exe -m pytest tests/test_analytical_scan.py -q -p no:cacheprovider`
  -> 11 passed, 3 warnings.
- `$env:PYTHONPATH='src'; C:\Users\patri\miniconda3\envs\ai-fund\python.exe -m pytest tests/test_analytical_pnl.py tests/test_adjustment_analysis.py tests/test_adjustments.py tests/test_reconciliation.py tests/test_reviewer.py tests/test_review_command.py -q -p no:cacheprovider`
  -> 89 passed, 15 subtests, 3 warnings.
- `$env:PYTHONPATH='src'; C:\Users\patri\miniconda3\envs\ai-fund\python.exe -m pytest -q -p no:cacheprovider`
  -> 154 passed, 45 subtests, 3 warnings.
- `C:\Users\patri\miniconda3\envs\ai-fund\Scripts\ruff.exe check src/smrik_fund/ingestion/analytical_scan.py tests/test_analytical_scan.py`
  -> All checks passed.
- `C:\Users\patri\miniconda3\envs\ai-fund\python.exe -m py_compile src/smrik_fund/ingestion/analytical_scan.py`
  -> passed.
- `git diff --check` -> passed; only pre-existing line-ending warnings on dirty
  tracked files.
