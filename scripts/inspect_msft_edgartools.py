"""Print the real MSFT statement shape returned by EdgarTools."""

from __future__ import annotations

import os
import re
from importlib.metadata import version

import pandas as pd
from dotenv import load_dotenv
from edgar import Company, set_identity

DATE_PATTERN = re.compile(r"\b20\d{2}-\d{2}-\d{2}\b")
HIERARCHY_WORDS = (
    "level",
    "abstract",
    "parent",
    "subtotal",
    "balance",
    "weight",
    "sign",
    "role",
)
METADATA_WORDS = (
    "balance",
    "weight",
    "preferred_sign",
    "statement_role",
    "context",
    "is_dimensioned",
)


def _period_columns(frame: pd.DataFrame) -> list[object]:
    return [column for column in frame.columns if DATE_PATTERN.search(str(column))]


def _matching_columns(frame: pd.DataFrame, words: tuple[str, ...]) -> list[object]:
    return [
        column
        for column in frame.columns
        if any(word in str(column).lower() for word in words)
    ]


def _print_frame(name: str, frame: pd.DataFrame) -> None:
    period_columns = _period_columns(frame)

    print(f"\n{name}")
    print(f"  type: {type(frame).__name__}")
    print(f"  shape: {frame.shape[0]} rows x {frame.shape[1]} columns")
    print(f"  index type: {type(frame.index).__name__}")
    print(f"  index name: {frame.index.name!r}")
    print(f"  index sample: {list(frame.index[:5])!r}")
    print(f"  columns: {list(frame.columns)!r}")
    print(f"  periods: {period_columns!r}")
    if len(period_columns) < 3:
        print(
            "  period note: fewer than three date-bearing columns were returned; "
            "this is recorded as an observation"
        )
    print(f"  dtypes: {frame.dtypes.astype(str).to_dict()!r}")

    print("  sign counts by period:")
    for column in period_columns:
        values = pd.to_numeric(frame[column], errors="coerce")
        print(
            f"    {column}: negative={(values < 0).sum()}, "
            f"positive={(values > 0).sum()}, zero={(values == 0).sum()}, "
            f"missing={values.isna().sum()}"
        )

    hierarchy_columns = _matching_columns(frame, HIERARCHY_WORDS)
    print(f"  hierarchy/subtotal columns: {hierarchy_columns or 'none observed'}")

    key_columns = [
        column
        for column in ("concept", "standard_concept", "label", *period_columns)
        if column in frame.columns
    ]
    if len(key_columns) >= 2:
        duplicate_rows = frame[frame.duplicated(key_columns, keep=False)]
        print(f"  duplicate statement rows on {key_columns}: {len(duplicate_rows)}")
        if not duplicate_rows.empty:
            print(duplicate_rows[key_columns].head(8).to_string(index=False))
    else:
        print("  duplicate statement rows: not enough identifying columns")

    print("  sample:")
    print(frame.head(8).to_string())


def _first_present(frame: pd.DataFrame, names: tuple[str, ...]) -> object | None:
    for name in names:
        if name in frame.columns:
            return name
    return None


def _print_facts(facts: pd.DataFrame) -> None:
    print("\nRaw XBRL facts")
    print(f"  shape: {facts.shape[0]} rows x {facts.shape[1]} columns")
    print(f"  columns: {list(facts.columns)!r}")

    metadata_columns = _matching_columns(facts, METADATA_WORDS)
    print(f"  metadata columns: {metadata_columns or 'none observed'}")
    if metadata_columns:
        print(facts[metadata_columns].head(8).to_string(index=False))

    dimension_columns = _matching_columns(facts, ("dimension", "axis", "member"))
    if dimension_columns:
        print("  non-empty dimension counts:")
        for column in dimension_columns:
            values = facts[column]
            if pd.api.types.is_bool_dtype(values):
                count = values.eq(True).sum()
            else:
                non_empty = values.notna() & values.astype(str).str.strip().ne("")
                count = non_empty.sum()
            print(f"    {column}: {count}")
    else:
        print("  dimension columns: none observed")

    concept_column = _first_present(facts, ("concept", "name"))
    value_column = _first_present(facts, ("value", "val"))
    unit_column = _first_present(facts, ("unit", "unit_ref"))
    period_columns = [
        column
        for column in (
            _first_present(facts, ("period_start", "start")),
            _first_present(facts, ("period_end", "end")),
            _first_present(facts, ("period_instant", "instant")),
        )
        if column is not None
    ]
    duplicate_key = [
        column
        for column in (concept_column, value_column, unit_column, *period_columns)
        if column is not None
    ]
    if len(duplicate_key) >= 2:
        duplicate_rows = facts[facts.duplicated(duplicate_key, keep=False)]
        print(f"  duplicate facts on {duplicate_key}: {len(duplicate_rows)}")
        if not duplicate_rows.empty:
            sample_columns = [
                column
                for column in (
                    concept_column,
                    value_column,
                    unit_column,
                    *period_columns,
                    "context_ref",
                    "dimensions",
                )
                if column is not None and column in facts.columns
            ]
            print(
                duplicate_rows[sample_columns].head(8).to_string(index=False)
            )
    else:
        print("  duplicate facts: not enough identifying columns")

    print("  sample:")
    sample_columns = [
        column
        for column in (
            "concept",
            "label",
            "value",
            "numeric_value",
            "unit_ref",
            "period_type",
            "period_start",
            "period_end",
            "period_instant",
            "is_dimensioned",
            "dimension",
            "member",
            "balance",
            "preferred_sign",
            "statement_type",
            "statement_role",
            "weight",
            "context_ref",
        )
        if column in facts.columns
    ]
    print(facts[sample_columns].head(5).to_string(index=False))


def main() -> None:
    load_dotenv()
    set_identity(
        os.getenv("SMRIK_EDGAR_USER_AGENT") or "SmrikFund research@example.com"
    )

    company = Company("MSFT")
    filing = company.get_filings(form="10-K").latest()
    xbrl = filing.xbrl()
    statement_objects = {
        "income_statement": xbrl.statements.income_statement(),
        "balance_sheet": xbrl.statements.balance_sheet(),
        "cash_flow_statement": xbrl.statements.cashflow_statement(),
    }
    frames = {
        name: statement.to_dataframe(view="standard")
        for name, statement in statement_objects.items()
    }

    print(f"EdgarTools version: {version('edgartools')}")
    print("Ticker: MSFT")
    print(f"Company CIK: {getattr(company, 'cik', '')}")
    print(f"Accession: {getattr(filing, 'accession_number', '')}")
    print(f"Form: {getattr(filing, 'form', '')}")
    print(f"Filing date: {getattr(filing, 'filing_date', '')}")
    print(f"Period of report: {getattr(filing, 'period_of_report', '')}")
    print(f"Source URL: {getattr(filing, 'filing_url', '')}")

    for name, frame in frames.items():
        _print_frame(name, frame)

    _print_facts(xbrl.facts.to_dataframe())


if __name__ == "__main__":
    main()
