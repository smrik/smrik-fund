# I1 terminal evidence

Workspace: `C:\Projects\finance\smrik-fund`
Branch: `codex/idempotent-approved-application`
Baseline: `736c239`

- `$env:PYTHONPATH='src'; C:\Users\patri\miniconda3\envs\ai-fund\python.exe -m pytest tests/test_adjustment_analysis.py -q` -> `22 passed, 4 warnings`.
- `$env:PYTHONPATH='src'; C:\Users\patri\miniconda3\envs\ai-fund\python.exe -m pytest -q` -> `69 passed, 4 warnings, 26 subtests`.
- `ruff check src/smrik_fund/main.py tests/test_adjustment_analysis.py` -> pass.
- `git diff --check` -> pass; Git emitted only existing LF/CRLF working-copy warnings.

The focused fixture is deterministic and patches discovery/Analyst/Reviewer outputs. It uses MSFT line/period-shaped P&L data and a stable filing/evidence fixture; no network or live LLM call is used. The explicit `materiality_passed=True` is supplied only by the frozen test boundary. The live-safe test leaves it unset and remains human review with no history row.
