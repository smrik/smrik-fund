"""Public interface for EDGAR statement parsing and artifact writing."""

from pathlib import Path

from dotenv import load_dotenv
import pandas as pd
from edgar import Company, set_identity


load_dotenv()


def configure_edgar() -> None:
	"""Set the SEC identity used by EdgarTools."""
	identity = os.getenv("EDGAR_IDENTITY")

	if not identity:
		raise RuntimeError("EDGAR_IDENTITY is missing. Add it to your .env file.")

	set_identity(identity)


def parse_statements(
	ticker: str,
	form: str = "10-K",
	view: str = "standard",
) -> dict[str, pd.DataFrame]:
	"""
	Get the latest financial statements for the ticker.
	"""

	configure_edgar()

	# 1. Clean ticker
	ticker = ticker.strip().upper()

	# 2. Make edgartools call
	company = Company(ticker)
	filing = company.latest(form)
	xbrl = filing.xbrl()

	# 3. Create dict with three statements
	statements = {
		"income_statement": xbrl.statements.income_statement().to_dataframe(
			view=view,
		),
		"balance_sheet": xbrl.statements.balance_sheet().to_dataframe(
			view=view,
		),
		"cash_flow_statement": xbrl.statements.cashflow_statement().to_dataframe(
			view=view,
		),
	}

	# Return
	return statements


def save_statements(
	ticker: str,
	statements: dict[str, pd.DataFrame],
) -> Path:
	"""
	Save statement DataFrames as CSV files.
	"""

	# clean ticker
	normalized_ticker = ticker.strip().upper()
	# get directory
	output_dir = Path("data") / normalized_ticker

	# make directory if it doesn't exist
	output_dir.mkdir(parents=True, exist_ok=True)

	# for every statement 1) make path 2) save df to path as csv
	for statement_name, dataframe in statements.items():
		output_path = output_dir / f"{statement_name}.csv"
		dataframe.to_csv(output_path, index=False)

	# return where saved
	return output_dir
