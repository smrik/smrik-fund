"""Load one EDGAR 10-K and expose the statement parsing interface."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from edgar import Company, set_identity
from pandas import DataFrame

from .facts import FACT_COLUMNS, STATEMENT_NAMES, STATEMENT_TYPES, normalize_facts

DEFAULT_OUTPUT_ROOT = Path("data")
DEFAULT_USER_AGENT = "SmrikFund research@example.com"
PARSER_VERSION = "edgartools-standard-10k-v1"


@dataclass(frozen=True, slots=True)
class FilingMetadata:
    accession: str
    filing_date: str
    form_type: str
    period_of_report: str
    source_url: str


@dataclass(frozen=True, slots=True)
class StatementArtifacts:
    ticker: str
    cik: str
    filing: FilingMetadata
    statements: dict[str, DataFrame]
    facts: DataFrame
    filing_text: str


def parse_statements(ticker: str) -> dict[str, DataFrame]:
    """Return the latest 10-K statements in EdgarTools' standard view."""
    return _load(ticker).statements


def parse_statement_artifacts(ticker: str) -> StatementArtifacts:
    """Load one 10-K and prepare the files needed by the ai-fund pipeline."""
    loaded = _load(ticker)
    filing = _filing_metadata(loaded.filing)
    filing_text = str(loaded.filing.text() or "")
    if not filing_text:
        raise RuntimeError("edgartools returned no document text")

    raw_facts = loaded.xbrl.facts.to_dataframe()
    facts = normalize_facts(
        raw_facts,
        loaded.statements,
        loaded.ticker,
        loaded.cik,
        asdict(filing),
    )
    return StatementArtifacts(
        ticker=loaded.ticker,
        cik=loaded.cik,
        filing=filing,
        statements=loaded.statements,
        facts=facts,
        filing_text=filing_text,
    )


@dataclass(frozen=True, slots=True)
class _LoadedStatements:
    ticker: str
    cik: str
    filing: Any
    xbrl: Any
    statements: dict[str, DataFrame]


def _load(ticker: str) -> _LoadedStatements:
    normalized_ticker = _normalize_ticker(ticker)
    set_identity(os.getenv("SMRIK_EDGAR_USER_AGENT") or DEFAULT_USER_AGENT)

    company = Company(normalized_ticker)
    filing = company.get_filings(form="10-K").latest()
    xbrl = filing.xbrl()
    statements = {
        # Keep the presentation tables small and close to the filing view.
        "income_statement": xbrl.statements.income_statement().to_dataframe(
            view="standard"
        ),
        "balance_sheet": xbrl.statements.balance_sheet().to_dataframe(view="standard"),
        "cash_flow_statement": xbrl.statements.cashflow_statement().to_dataframe(
            view="standard"
        ),
    }
    return _LoadedStatements(
        ticker=normalized_ticker,
        cik=_normalize_cik(getattr(company, "cik", "")),
        filing=filing,
        xbrl=xbrl,
        statements=statements,
    )


def _filing_metadata(filing: Any) -> FilingMetadata:
    return FilingMetadata(
        accession=_text(getattr(filing, "accession_number", "")),
        filing_date=_iso_date(getattr(filing, "filing_date", "")),
        form_type=_text(getattr(filing, "form", "")).upper(),
        period_of_report=_iso_date(getattr(filing, "period_of_report", "")),
        source_url=_text(getattr(filing, "filing_url", "")),
    )


def _normalize_ticker(ticker: str) -> str:
    normalized = ticker.strip().upper()
    if not normalized:
        raise ValueError("ticker is required")
    return normalized


def _normalize_cik(value: Any) -> str:
    raw = _text(value)
    return raw.zfill(10) if raw.isdigit() else ""


def _iso_date(value: Any) -> str:
    return _text(value)[:10]


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


__all__ = [
    "DEFAULT_OUTPUT_ROOT",
    "FACT_COLUMNS",
    "STATEMENT_NAMES",
    "STATEMENT_TYPES",
    "FilingMetadata",
    "StatementArtifacts",
    "parse_statement_artifacts",
    "parse_statements",
]
