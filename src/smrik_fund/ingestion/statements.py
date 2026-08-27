"""Public interfaces for standard statements and the derived MSFT P&L."""

import math
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
_NON_MONETARY_CONCEPT_MARKERS = (
	"earningspershare",
	"eps",
	"pershare",
	"sharesaverage",
	"sharesfullydilutedaverage",
	"weightedaveragenumberofshares",
	"sharesoutstanding",
	"sharecount",
	"margin",
	"ratio",
	"rate",
	"percent",
	"percentage",
)
_NON_MONETARY_ROW_MARKERS = (
	"earningspershare",
	"eps",
	"pershare",
	"sharesaverage",
	"sharesfullydilutedaverage",
	"weightedaveragenumberofshares",
	"sharesoutstanding",
	"sharecount",
)


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


def _finite_numeric(values: pd.Series) -> pd.Series:
	"""Coerce calculation inputs while keeping missing and non-finite values null."""
	return pd.to_numeric(values, errors="coerce").replace(
		[float("inf"), float("-inf")], float("nan")
	)


def _safe_number(value: object) -> float | None:
	"""Return one finite numeric value, or None when it is unavailable."""
	try:
		number = float(pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0])
	except (TypeError, ValueError):
		return None
	return number if math.isfinite(number) else None


def _truthy(value: object) -> bool:
	if value is None or pd.isna(value):
		return False
	if isinstance(value, str):
		return value.strip().lower() in {"1", "true", "yes"}
	return bool(value)


def _text(value: object) -> str:
	if value is None or pd.isna(value):
		return ""
	return re.sub(r"[^a-z0-9]", "", str(value).strip().lower())


def _common_size_eligible(row: pd.Series) -> bool:
	"""Exclude structural, ratio, EPS, and share rows from common size."""
	if _truthy(row.get("abstract")) or _truthy(row.get("is_breakdown")):
		return False
	standard_concept = _text(row.get("standard_concept"))
	if standard_concept:
		if standard_concept in {_text(concept) for concept in SHARE_CONCEPTS}:
			return False
		if any(
			marker in standard_concept
			for marker in _NON_MONETARY_CONCEPT_MARKERS
		):
			return False
		row_text = " ".join(
			_text(row.get(column)) for column in ("concept", "label")
		)
		return not any(marker in row_text for marker in _NON_MONETARY_ROW_MARKERS)
	row_text = " ".join(
		_text(row.get(column)) for column in ("concept", "label")
	)
	return not any(marker in row_text for marker in _NON_MONETARY_CONCEPT_MARKERS)


def _safe_change(current: pd.Series, previous: pd.Series) -> pd.Series:
	current = _finite_numeric(current)
	previous = _finite_numeric(previous)
	sign_change = (current.gt(0) & previous.lt(0)) | (
		current.lt(0) & previous.gt(0)
	)
	valid = (
		current.notna()
		& previous.notna()
		& previous.ne(0)
		& ~sign_change
		& ~(current.lt(0) & previous.lt(0))
	)
	result = current.div(previous).sub(1.0).replace(
		[float("inf"), float("-inf")], float("nan")
	)
	return result.where(valid)


def _safe_absolute_change(current: pd.Series, previous: pd.Series) -> pd.Series:
	current = _finite_numeric(current)
	previous = _finite_numeric(previous)
	return current.subtract(previous).replace(
		[float("inf"), float("-inf")], float("nan")
	).where(current.notna() & previous.notna())


def _safe_bps_change(current: pd.Series, previous: pd.Series) -> pd.Series:
	current = _finite_numeric(current)
	previous = _finite_numeric(previous)
	return current.subtract(previous).mul(10_000).replace(
		[float("inf"), float("-inf")], float("nan")
	).where(current.notna() & previous.notna())


def _safe_bps_value(current: object, previous: object) -> float:
	current_number = _safe_number(current)
	previous_number = _safe_number(previous)
	if current_number is None or previous_number is None:
		return float("nan")
	change = (current_number - previous_number) * 10_000
	return change if math.isfinite(change) else float("nan")


def _safe_ratio(numerator: pd.Series, denominator: object) -> pd.Series:
	denominator_number = _safe_number(denominator)
	if denominator_number is None or denominator_number == 0:
		return pd.Series(float("nan"), index=numerator.index)
	return _finite_numeric(numerator).div(denominator_number).replace(
		[float("inf"), float("-inf")], float("nan")
	)


# endregion


def prepare_pnl(
	income_statement: pd.DataFrame,
	years: int = 3,
) -> pd.DataFrame:
	"""
	Create a derived analytical P&L without changing source values.

	Metric values are ratios, so ``0.25`` means 25 percent. Reported annual
	columns remain unchanged; all additional columns are deterministic context.
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

	# * 2. Calculates one canonical set of numerical context metrics
	numeric_periods = {
		period: _finite_numeric(pnl[period]) for period in selected_periods
	}
	for position, period in enumerate(selected_periods):
		current = numeric_periods[period]
		previous = (
			numeric_periods[selected_periods[position + 1]]
			if position + 1 < len(selected_periods)
			else pd.Series(float("nan"), index=pnl.index)
		)
		growth = _safe_change(current, previous)
		pnl[f"absolute_yoy_change_{period}"] = _safe_absolute_change(
			current, previous
		)
		pnl[f"yoy_growth_{period}"] = growth
		# Keep the original field as a compatibility alias of the same result.
		pnl[f"yoy_change_{period}"] = growth

	if len(selected_periods) >= 3:
		newest = numeric_periods[selected_periods[0]]
		oldest = numeric_periods[selected_periods[2]]
		valid_endpoints = newest.gt(0) & oldest.gt(0)
		cagr = newest.div(oldest).pow(0.5).sub(1.0).replace(
			[float("inf"), float("-inf")], float("nan")
		)
		pnl["two_year_cagr"] = cagr.where(valid_endpoints)
	else:
		pnl["two_year_cagr"] = pd.Series(float("nan"), index=pnl.index)

	revenue_index = _unique_standard_concept_index(pnl, "Revenue")
	eligible = pnl.apply(_common_size_eligible, axis=1)
	percent_levels: dict[str, pd.Series] = {}
	for period in selected_periods:
		revenue = (
			_safe_number(pnl.loc[revenue_index, period])
			if revenue_index is not None
			else None
		)
		percent_of_revenue = _safe_ratio(numeric_periods[period], revenue)
		percent_of_revenue = percent_of_revenue.where(eligible)
		percent_levels[period] = percent_of_revenue
		pnl[f"percent_of_revenue_{period}"] = percent_of_revenue
	for position, period in enumerate(selected_periods):
		previous = (
			percent_levels[selected_periods[position + 1]]
			if position + 1 < len(selected_periods)
			else pd.Series(float("nan"), index=pnl.index)
		)
		pnl[f"percent_of_revenue_bps_change_{period}"] = _safe_bps_change(
			percent_levels[period], previous
		)

	for metric, numerator_concept, denominator_concept in (
		("gross_margin", "GrossProfit", "Revenue"),
		("operating_margin", "OperatingIncomeLoss", "Revenue"),
		("pretax_margin", "PretaxIncomeLoss", "Revenue"),
		("net_margin", "NetIncome", "Revenue"),
		("effective_tax_rate", "IncomeTaxes", "PretaxIncomeLoss"),
	):
		numerator_index = _unique_standard_concept_index(pnl, numerator_concept)
		denominator_index = _unique_standard_concept_index(pnl, denominator_concept)
		levels: dict[str, float] = {}
		for period in selected_periods:
			numerator = (
				_safe_number(pnl.loc[numerator_index, period])
				if numerator_index is not None
				else None
			)
			denominator = (
				_safe_number(pnl.loc[denominator_index, period])
				if denominator_index is not None
				else None
			)
			ratio = (
				numerator / denominator
				if numerator is not None
				and denominator is not None
				and denominator != 0
				and math.isfinite(numerator / denominator)
				else float("nan")
			)
			levels[period] = ratio
			values = pd.Series(float("nan"), index=pnl.index)
			if numerator_index is not None:
				values.loc[numerator_index] = ratio
			pnl[f"{metric}_{period}"] = values
		for position, period in enumerate(selected_periods):
			previous = (
				levels[selected_periods[position + 1]]
				if position + 1 < len(selected_periods)
				else float("nan")
			)
			bps = _safe_bps_value(levels[period], previous)
			values = pd.Series(float("nan"), index=pnl.index)
			if numerator_index is not None:
				values.loc[numerator_index] = bps
			pnl[f"{metric}_bps_change_{period}"] = values

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
