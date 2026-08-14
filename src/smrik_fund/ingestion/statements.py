"""Public interfaces for standard statements and the derived MSFT P&L."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from edgar import Company, set_identity

from .artifacts import save_statement_artifacts
from .parser import (
    DEFAULT_USER_AGENT,
    FilingMetadata,
    StatementArtifacts,
    parse_statement_artifacts,
)
from .parser import (
    parse_statements as _parse_standard_statements,
)

load_dotenv()

ANNUAL_PERIOD_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2} \(FY\)$")
SHARE_CONCEPTS = {"SharesAverage", "SharesFullyDilutedAverage"}


def configure_edgar() -> None:
    """Set the SEC identity used by EdgarTools."""
    set_identity(
        os.getenv("SMRIK_EDGAR_USER_AGENT")
        or os.getenv("EDGAR_IDENTITY")
        or DEFAULT_USER_AGENT
    )


def get_statements(ticker: str) -> dict[str, pd.DataFrame]:
    """Return the latest 10-K statements in EdgarTools' standard view."""
    load_dotenv()
    return _parse_standard_statements(ticker)


def parse_statements(
    ticker: str,
    form: str = "10-K",
    view: str = "standard",
) -> dict[str, pd.DataFrame]:
    """Keep the older statement-parser name as a compatibility wrapper."""
    if form == "10-K" and view == "standard":
        return get_statements(ticker)

    configure_edgar()
    company = Company(ticker.strip().upper())
    filing = company.get_filings(form=form).latest()
    xbrl = filing.xbrl()
    return {
        "income_statement": xbrl.statements.income_statement().to_dataframe(
            view=view
        ),
        "balance_sheet": xbrl.statements.balance_sheet().to_dataframe(view=view),
        "cash_flow_statement": xbrl.statements.cashflow_statement().to_dataframe(
            view=view
        ),
    }


def _annual_period_columns(income_statement: pd.DataFrame) -> list[str]:
    return [
        column
        for column in income_statement.columns
        if isinstance(column, str) and ANNUAL_PERIOD_PATTERN.fullmatch(column)
    ]


def _standard_concept_mask(
    frame: pd.DataFrame,
    standard_concept: str,
) -> pd.Series:
    concepts = frame["standard_concept"].astype("string")
    return concepts.eq(standard_concept).fillna(False)


def _unique_standard_concept_index(
    frame: pd.DataFrame,
    standard_concept: str,
) -> int | None:
    matches = frame.index[_standard_concept_mask(frame, standard_concept)]
    if len(matches) != 1:
        return None
    return matches[0]


def _numeric_values(frame: pd.DataFrame, period: str) -> pd.Series:
    return pd.to_numeric(frame[period], errors="coerce")


def _safe_change(current: pd.Series, previous: pd.Series) -> pd.Series:
    result = current.div(previous).sub(1.0)
    return result.mask(current.isna() | previous.isna() | previous.eq(0))


def _safe_ratio(numerator: pd.Series, denominator: float) -> pd.Series:
    if pd.isna(denominator) or denominator == 0:
        return pd.Series(float("nan"), index=numerator.index)
    return numerator.div(denominator).mask(numerator.isna())


def _single_line_metric(
    frame: pd.DataFrame,
    period: str,
    numerator_concept: str,
    denominator_concept: str,
) -> pd.Series | None:
    numerator_index = _unique_standard_concept_index(frame, numerator_concept)
    denominator_index = _unique_standard_concept_index(frame, denominator_concept)
    if numerator_index is None or denominator_index is None:
        return None

    values = pd.Series(float("nan"), index=frame.index)
    denominator = pd.to_numeric(
        pd.Series([frame.loc[denominator_index, period]]),
        errors="coerce",
    ).iloc[0]
    numerator = pd.to_numeric(
        pd.Series([frame.loc[numerator_index, period]]),
        errors="coerce",
    ).iloc[0]
    ratio = numerator / denominator if pd.notna(denominator) and denominator != 0 else float("nan")
    values.loc[numerator_index] = ratio
    return values


def prepare_pnl(
    income_statement: pd.DataFrame,
    years: int = 3,
) -> pd.DataFrame:
    """Create a derived analytical P&L without changing source values.

    YoY change is the percentage change from the prior reported period.
    Metric values are ratios, so ``0.25`` means 25 percent.
    """
    if years < 1:
        raise ValueError("years must be positive")

    annual_periods = _annual_period_columns(income_statement)
    if len(annual_periods) < years:
        raise ValueError(
            f"income statement must contain at least {years} annual periods"
        )

    selected_periods = annual_periods[:years]
    source_columns = [
        column
        for column in income_statement.columns
        if column not in annual_periods or column in selected_periods
    ]
    pnl = income_statement.loc[:, source_columns].copy(deep=True)

    for position, period in enumerate(selected_periods):
        current = _numeric_values(pnl, period)
        if position + 1 < len(selected_periods):
            previous = _numeric_values(pnl, selected_periods[position + 1])
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
            percent_of_revenue = _safe_ratio(_numeric_values(pnl, period), revenue)
            pnl[f"percent_of_revenue_{period}"] = percent_of_revenue.where(eligible)

    for metric, numerator, denominator in (
        ("gross_margin", "GrossProfit", "Revenue"),
        ("operating_margin", "OperatingIncomeLoss", "Revenue"),
        ("effective_tax_rate", "IncomeTaxes", "PretaxIncomeLoss"),
    ):
        for period in selected_periods:
            values = _single_line_metric(pnl, period, numerator, denominator)
            if values is not None:
                pnl[f"{metric}_{period}"] = values

    return pnl


def build_analytical_pnl(ticker: str, years: int = 3) -> pd.DataFrame:
    """Load standard statements and prepare the income-statement view."""
    statements = get_statements(ticker)
    return prepare_pnl(statements["income_statement"], years=years)


def save_analytical_pnl(
    ticker: str,
    pnl: pd.DataFrame,
    output_root: str | Path = "data",
) -> Path:
    """Save the derived P&L under ``data/<TICKER>/03_output``."""
    normalized_ticker = ticker.strip().upper()
    output_path = (
        Path(output_root)
        / normalized_ticker
        / "03_output"
        / "analytical_pnl.csv"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pnl.to_csv(output_path, index=False)
    return output_path


def save_statements(
    ticker: str,
    statements: dict[str, pd.DataFrame],
) -> Path:
    """Save source statement DataFrames as CSV files for compatibility."""
    output_dir = (
        Path("data")
        / ticker.strip().upper()
        / "02_processing"
        / "edgar"
        / "statements"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    for statement_name, dataframe in statements.items():
        dataframe.to_csv(output_dir / f"{statement_name}.csv", index=False)
    return output_dir


__all__ = [
    "FilingMetadata",
    "StatementArtifacts",
    "build_analytical_pnl",
    "configure_edgar",
    "get_statements",
    "parse_statement_artifacts",
    "parse_statements",
    "prepare_pnl",
    "save_analytical_pnl",
    "save_statement_artifacts",
    "save_statements",
]
