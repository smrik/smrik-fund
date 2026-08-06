# Core

- Python src-layout package: `src/smrik_fund/`.
- Typer entry point: `smrik-fund = smrik_fund.main:app`.
- Main modules: `main.py` for CLI; `ingestion/edgar_import.py` for EDGAR filing downloads; `ingestion/statements.py` for XBRL statement parsing and workbook export.
- Generated artifacts use `data/`; the statement command writes `data/<TICKER>/<TICKER>_edgar_statements.xlsx`.
- Read `mem:tech_stack` for runtime and dependencies, `mem:suggested_commands` for Windows commands, `mem:conventions` for code style, and `mem:task_completion` for verification commands.