# smrik-fund

A Python prototype for reading a company's latest annual SEC filing and saving
its income statement, balance sheet and cash flow statement as CSV files.

## Current status

The CLI and the older artifact pipeline need an integration fix before the
`parse` command is ready to use. The current statement module calls `os.getenv`
without importing `os`. The tests also expect artifact types and functions that
the module no longer exports. These are known source-level blockers; this
README update does not fix them or claim a successful runtime check.

## Development setup

Use Python 3.13 or later and `uv`:

```bash
uv sync --frozen
uv run smrik-fund --help
```

The dependencies and command entry point are defined in `pyproject.toml`; exact
versions are recorded in `uv.lock`.

## Intended use after the integration fix

Set `EDGAR_IDENTITY` to your name and contact email, then run:

```bash
export EDGAR_IDENTITY='Your Name your-email@example.com'
uv run smrik-fund parse MSFT
```

This command requests the latest 10-K through EdgarTools. The current CLI path
is designed to write:

```text
data/MSFT/
  income_statement.csv
  balance_sheet.csv
  cash_flow_statement.csv
```

A later run for the same ticker replaces those CSVs. Keep copies when you need
to compare results over time. Live retrieval needs internet access.

## Code and checks

- `src/smrik_fund/main.py` defines the CLI.
- `src/smrik_fund/ingestion/statements.py` implements its current statement path.
- `ingestion/parser.py`, `facts.py` and `artifacts.py` contain the separate,
  richer filing and fact pipeline. They are not the current CLI output contract.
- `tests/test_statements.py` describes the older artifact contract and needs to
  be aligned with the chosen interface.

Run the existing checks after setting up the environment:

```bash
uv run python -m unittest discover -s tests -v
uv run ruff check .
```

The integration mismatch above must be resolved before treating these checks as
passing. Keep credentials and downloaded research data outside published changes.

## Project workflow

Use [Project workflow](docs/PATRIK_WORKFLOW.md) for tasks, proposals, feedback and review.
