# Task Completion

- Run the focused unit tests with `.venv\\Scripts\\python.exe -m unittest discover -s tests -v`.
- Run Ruff on changed code with `.venv\\Scripts\\ruff.exe check src/smrik_fund/main.py src/smrik_fund/ingestion/statements.py tests/test_statements.py`.
- Run formatting and compile checks on `src` and `tests`.
- For parser changes, run the CLI on at least two real tickers and inspect that each workbook has the three statement sheets and both concept columns.