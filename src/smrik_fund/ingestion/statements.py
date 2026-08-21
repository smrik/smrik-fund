"""Public interfaces for standard statements and the derived MSFT P&L."""

import os
import re
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from edgar import Company, set_identity

load_dotenv()

DEFAULT_USER_AGENT = "SmrikFund research@example.com"
ANNUAL_PERIOD_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2} \(FY\)$")
BARE_ANNUAL_PERIOD_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SHARE_CONCEPTS = {"SharesAverage", "SharesFullyDilutedAverage"}


def configure_edgar() -> None:
	"""Set the SEC identity used by EdgarTools."""
	set_identity(
		os.getenv("SMRIK_EDGAR_USER_AGENT")
		or os.getenv("EDGAR_IDENTITY")
		or DEFAULT_USER_AGENT
	)


class _StatementsWithFiling(dict[str, pd.DataFrame]):
	"""Dict-compatible statement bundle carrying the already-loaded filing."""

	def __init__(self, values: dict[str, pd.DataFrame], filing: Any) -> None:
		super().__init__(values)
		self.filing = filing


def get_latest_filing(ticker: str) -> Any:
	"""Load one latest 10-K filing through EdgarTools."""
	ticker = ticker.strip().upper()
	if not ticker:
		raise ValueError("ticker is required")

	load_dotenv()
	configure_edgar()
	company = Company(ticker)
	return company.get_filings(form="10-K").latest()


def get_statements_from_filing(filing: Any) -> dict[str, pd.DataFrame]:
	"""Return EdgarTools standard statements for an existing filing object."""
	if filing is None:
		raise ValueError("filing is required")
	xbrl = filing.xbrl()
	if xbrl is None:
		raise ValueError("latest 10-K does not contain XBRL statements")
	return {
		"income_statement": xbrl.statements.income_statement().to_dataframe(
			view="standard"
		),
		"balance_sheet": xbrl.statements.balance_sheet().to_dataframe(view="standard"),
		"cash_flow_statement": xbrl.statements.cashflow_statement().to_dataframe(
			view="standard"
		),
	}


def get_statements(ticker: str) -> dict[str, pd.DataFrame]:
	"""Return latest 10-K statements and retain its filing for downstream use."""
	filing = get_latest_filing(ticker)
	return _StatementsWithFiling(get_statements_from_filing(filing), filing)


# region Support functions
def _normalize_annual_period_columns(
	income_statement: pd.DataFrame,
) -> pd.DataFrame:
	"""Normalize EdgarTools' bare annual dates to the analytical FY contract."""
	renames = {
		column: f"{column} (FY)"
		for column in income_statement.columns
		if isinstance(column, str) and BARE_ANNUAL_PERIOD_PATTERN.fullmatch(column)
	}
	conflicts = [
		target
		for target in renames.values()
		if target in income_statement.columns and target not in renames
	]
	if conflicts:
		raise ValueError(
			"ambiguous annual period columns after normalization: "
			+ ", ".join(conflicts)
		)
	return income_statement.rename(columns=renames)


def _annual_period_columns(income_statement: pd.DataFrame) -> list[str]:
	return [
		column
		for column in income_statement.columns
		if isinstance(column, str) and ANNUAL_PERIOD_PATTERN.fullmatch(column)
	]


def _unique_standard_concept_index(
	frame: pd.DataFrame,
	standard_concept: str,
) -> int | None:
	concepts = frame["standard_concept"].astype("string")
	matches = frame.index[concepts.eq(standard_concept).fillna(False)]
	if len(matches) != 1:
		return None
	return matches[0]


def _safe_change(current: pd.Series, previous: pd.Series) -> pd.Series:
	result = current.div(previous).sub(1.0)
	return result.mask(current.isna() | previous.isna() | previous.eq(0))


def _safe_ratio(numerator: pd.Series, denominator: float) -> pd.Series:
	if pd.isna(denominator) or denominator == 0:
		return pd.Series(float("nan"), index=numerator.index)
	return numerator.div(denominator).mask(numerator.isna())


# endregion


def prepare_pnl(
	income_statement: pd.DataFrame,
	years: int = 3,
) -> pd.DataFrame:
	"""
	Create a derived analytical P&L without changing source values.

	YoY change is the percentage change from the prior reported period.
	Metric values are ratios, so ``0.25`` means 25 percent.
	"""

	# * 0. Basic checks for incorrect inputs
	if years < 1:
		raise ValueError("years must be positive")
	income_statement = _normalize_annual_period_columns(income_statement)
	annual_periods = _annual_period_columns(income_statement)
	if len(annual_periods) < years:
		raise ValueError(
			f"income statement must contain at least {years} annual periods"
		)

	# * 1. Period creation
	# list of selected periods
	selected_periods = annual_periods[:years]
	# keeps only the annual periods and the metadata
	source_columns = [
		column
		for column in income_statement.columns
		if column not in annual_periods or column in selected_periods
	]
	# create deep copy to not link to old one still
	pnl = income_statement.loc[:, source_columns].copy(deep=True)

	# * 2. Calculates the YoY changes
	for position, period in enumerate(selected_periods):
		current = pd.to_numeric(pnl[period], errors="coerce")

		# check to not go out of bounds
		# calculates yoy changes
		if position + 1 < len(selected_periods):
			previous = pd.to_numeric(
				pnl[selected_periods[position + 1]],
				errors="coerce",
			)
			pnl[f"yoy_change_{period}"] = _safe_change(current, previous)
		else:
			pnl[f"yoy_change_{period}"] = float("nan")

	revenue_index = _unique_standard_concept_index(pnl, "Revenue")
	if revenue_index is not None:
		concepts = pnl["standard_concept"].astype("string")
		eligible = concepts.notna() & ~concepts.isin(SHARE_CONCEPTS)
		for period in selected_periods:
			revenue = pd.to_numeric(
				pd.Series([pnl.loc[revenue_index, period]]),
				errors="coerce",
			).iloc[0]
			percent_of_revenue = _safe_ratio(
				pd.to_numeric(pnl[period], errors="coerce"),
				revenue,
			)
			pnl[f"percent_of_revenue_{period}"] = percent_of_revenue.where(eligible)

	for metric, numerator_concept, denominator_concept in (
		("gross_margin", "GrossProfit", "Revenue"),
		("operating_margin", "OperatingIncomeLoss", "Revenue"),
		("effective_tax_rate", "IncomeTaxes", "PretaxIncomeLoss"),
	):
		numerator_index = _unique_standard_concept_index(pnl, numerator_concept)
		denominator_index = _unique_standard_concept_index(pnl, denominator_concept)
		if numerator_index is None or denominator_index is None:
			continue

		for period in selected_periods:
			denominator = pd.to_numeric(
				pd.Series([pnl.loc[denominator_index, period]]),
				errors="coerce",
			).iloc[0]
			numerator = pd.to_numeric(
				pd.Series([pnl.loc[numerator_index, period]]),
				errors="coerce",
			).iloc[0]
			ratio = (
				numerator / denominator
				if pd.notna(denominator) and denominator != 0
				else float("nan")
			)
			values = pd.Series(float("nan"), index=pnl.index)
			values.loc[numerator_index] = ratio
			pnl[f"{metric}_{period}"] = values

	return pnl


def build_analytical_pnl(ticker: str, years: int = 3) -> pd.DataFrame:
	"""Load standard statements and prepare the income-statement view."""
	statements = get_statements(ticker)
	pnl = prepare_pnl(statements["income_statement"], years=years)
	filing = getattr(statements, "filing", None)
	if filing is not None:
		# DataFrame attrs are run-local and are intentionally not serialized.
		pnl.attrs["edgar_filing"] = filing
	return pnl


def load_analytical_pnl(
	ticker: str,
	output_root: str | Path = "data",
) -> pd.DataFrame:
	"""Load the derived P&L saved by Task 2."""
	input_path = (
		Path(output_root) / ticker.strip().upper() / "03_output" / "analytical_pnl.csv"
	)
	if not input_path.is_file():
		raise FileNotFoundError(f"Analytical P&L not found: {input_path}")
	return pd.read_csv(input_path)


def save_analytical_pnl(
	ticker: str,
	pnl: pd.DataFrame,
	output_root: str | Path = "data",
) -> Path:
	"""Save the derived P&L under ``data/<TICKER>/03_output``."""
	normalized_ticker = ticker.strip().upper()
	output_path = (
		Path(output_root) / normalized_ticker / "03_output" / "analytical_pnl.csv"
	)
	output_path.parent.mkdir(parents=True, exist_ok=True)
	pnl.to_csv(output_path, index=False)
	return output_path
