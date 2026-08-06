# Tech Stack

- Python 3.13, managed with uv.
- Typer 0.27+ for the CLI.
- EdgarTools 5.45+ for SEC company, filing, and XBRL access.
- pandas 3.0+ for statement DataFrames.
- XlsxWriter 3.2+ for Excel workbook output.
- Ruff is the configured formatter and linter.
- Dependencies are declared in `pyproject.toml` and pinned through `uv.lock`.