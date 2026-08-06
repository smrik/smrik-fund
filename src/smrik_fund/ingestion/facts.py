"""Convert EdgarTools facts to the long rows used by ai-fund."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

import pandas as pd
from pandas import DataFrame

STATEMENT_TYPES = {
    "income_statement": "IncomeStatement",
    "balance_sheet": "BalanceSheet",
    "cash_flow_statement": "CashFlowStatement",
}
STATEMENT_NAMES = tuple(STATEMENT_TYPES)

FACT_COLUMNS = (
    "fact_id",
    "ingestion_fingerprint",
    "ticker",
    "source",
    "statement",
    "concept",
    "standard_concept",
    "canonical_key",
    "label",
    "value",
    "numeric_value",
    "unit",
    "currency",
    "scale_factor",
    "period",
    "period_kind",
    "period_type",
    "period_start",
    "period_end",
    "period_instant",
    "fiscal_year",
    "fiscal_period",
    "filing_date",
    "form_type",
    "accession",
    "source_locator",
    "context_ref",
    "statement_role",
    "metadata",
    "dimensions",
    "is_derived",
    "derivation",
    "original_source",
)


def normalize_facts(
    raw_facts: DataFrame,
    statements: Mapping[str, DataFrame],
    ticker: str,
    cik: str,
    filing: Mapping[str, str],
) -> DataFrame:
    """Return numeric facts that belong to the three standard statements."""
    if raw_facts is None or raw_facts.empty:
        return pd.DataFrame(columns=FACT_COLUMNS)

    metadata = _statement_metadata(statements)
    rows: list[dict[str, Any]] = []
    for statement, statement_type in STATEMENT_TYPES.items():
        concepts = {concept for name, concept in metadata if name == statement}
        if not concepts or "concept" not in raw_facts.columns:
            continue

        selected = raw_facts[raw_facts["concept"].map(_concept_key).isin(concepts)]
        if "statement_type" in raw_facts.columns:
            typed = selected[selected["statement_type"] == statement_type]
            # Some filings do not attach a statement type to every fact.
            if not typed.empty:
                selected = typed

        for index, (_, fact) in enumerate(selected.iterrows()):
            if _is_missing(fact.get("numeric_value")):
                continue
            concept = _text(fact.get("concept"))
            rows.append(
                _normalize_fact(
                    fact,
                    statement,
                    ticker,
                    cik,
                    filing,
                    metadata.get((statement, _concept_key(concept)), {}),
                    index,
                )
            )

    return pd.DataFrame(rows, columns=FACT_COLUMNS)


def _statement_metadata(
    statements: Mapping[str, DataFrame],
) -> dict[tuple[str, str], dict[str, str]]:
    metadata: dict[tuple[str, str], dict[str, str]] = {}
    for statement in STATEMENT_NAMES:
        frame = statements.get(statement, pd.DataFrame())
        if "concept" not in frame.columns:
            continue
        for _, row in frame.iterrows():
            concept = _concept_key(row.get("concept"))
            if concept:
                metadata[(statement, concept)] = {
                    "label": _text(row.get("label")),
                    "standard_concept": _text(row.get("standard_concept")),
                }
    return metadata


def _normalize_fact(
    fact: pd.Series,
    statement: str,
    ticker: str,
    cik: str,
    filing: Mapping[str, str],
    concept_metadata: Mapping[str, str],
    index: int,
) -> dict[str, Any]:
    concept = _text(fact.get("concept"))
    fact_id = _text(fact.get("fact_id")) or f"{ticker}:{statement}:{index}"
    period_instant = _text(fact.get("period_instant"))
    period_end = _text(fact.get("period_end")) or period_instant
    label = (
        _text(fact.get("original_label"))
        or _text(fact.get("label"))
        or concept_metadata.get("label", "")
    )
    standard_concept = concept_metadata.get("standard_concept", "")
    row: dict[str, Any] = {
        "fact_id": fact_id,
        "ticker": ticker,
        "source": "edgar",
        "statement": statement,
        "concept": concept,
        "standard_concept": standard_concept,
        "canonical_key": _canonical_key(standard_concept or concept, label),
        "label": label,
        "value": fact.get("value"),
        "numeric_value": fact.get("numeric_value"),
        "unit": _text(fact.get("unit")) or _text(fact.get("unit_ref")),
        "currency": _text(fact.get("currency")),
        "scale_factor": 1.0,
        "period": _text(fact.get("period_key")) or period_end,
        "period_kind": "reported",
        "period_type": _text(fact.get("period_type")),
        "period_start": _text(fact.get("period_start")),
        "period_end": period_end,
        "period_instant": period_instant,
        "fiscal_year": fact.get("fiscal_year"),
        "fiscal_period": _text(fact.get("fiscal_period")),
        "filing_date": filing.get("filing_date", ""),
        "form_type": filing.get("form_type", ""),
        "accession": filing.get("accession", ""),
        "source_locator": f"edgar:{filing.get('accession', '')}:{fact_id}",
        "context_ref": _text(fact.get("context_ref")),
        "statement_role": _text(fact.get("statement_role")),
        "metadata": _metadata(fact, cik),
        "dimensions": _dimensions(fact),
        "is_derived": False,
        "derivation": None,
        "original_source": "edgar_xbrl",
    }
    row["ingestion_fingerprint"] = _fingerprint(row)
    return row


def _metadata(fact: pd.Series, cik: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {"cik": cik}
    for field in (
        "context_ref",
        "period_key",
        "statement_type",
        "statement_role",
        "balance",
        "weight",
        "preferred_sign",
        "period_instant",
    ):
        value = fact.get(field)
        if not _is_missing(value):
            metadata[field] = value
    return metadata


def _dimensions(fact: pd.Series) -> dict[str, str]:
    return {
        str(column)[4:]: _text(value)
        for column, value in fact.items()
        if str(column).startswith("dim_") and _text(value)
    }


def _fingerprint(row: Mapping[str, Any]) -> str:
    payload = {
        key: value for key, value in row.items() if key != "ingestion_fingerprint"
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _canonical_key(concept: str, label: str) -> str:
    value = concept.rsplit(":", 1)[-1] or label or "unknown"
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "unknown"


def _concept_key(value: Any) -> str:
    """Match EdgarTools' underscore and colon namespace spellings."""
    concept = _text(value)
    return concept.replace("_", ":", 1) if ":" not in concept else concept


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        result = pd.isna(value)
    except (TypeError, ValueError):
        return False
    return bool(result) if not hasattr(result, "__len__") else False


def _text(value: Any) -> str:
    return "" if _is_missing(value) else str(value).strip()
