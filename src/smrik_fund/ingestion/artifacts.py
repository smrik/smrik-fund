"""Write statement results in the directory layout used by ai-fund."""

from __future__ import annotations

import csv
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from pandas import DataFrame

from .facts import FACT_COLUMNS, STATEMENT_NAMES
from .parser import DEFAULT_OUTPUT_ROOT, PARSER_VERSION, StatementArtifacts


def save_statement_artifacts(
    artifacts: StatementArtifacts,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
) -> Path:
    """Write source filing, normalized facts, manifest, and coverage files."""
    output_dir = Path(output_root) / artifacts.ticker
    source_dir = output_dir / "01_2_edgar"
    edgar_dir = output_dir / "02_preprocessing" / "edgar"
    filing_dir = source_dir / "filings"
    filing_dir.mkdir(parents=True, exist_ok=True)
    edgar_dir.mkdir(parents=True, exist_ok=True)

    accession = artifacts.filing.accession
    filing_name = f"{accession}.txt"
    (filing_dir / filing_name).write_text(artifacts.filing_text, encoding="utf-8")
    filing_row = {
        "accession": accession,
        "filing_date": artifacts.filing.filing_date,
        "form_type": artifacts.filing.form_type,
        "period_of_report": artifacts.filing.period_of_report,
        "source_url": artifacts.filing.source_url,
        "output_path": f"filings/{filing_name}",
    }

    _write_csv(source_dir / "filing_index.csv", [filing_row], tuple(filing_row))
    _write_csv(
        edgar_dir / "facts.csv",
        artifacts.facts.to_dict(orient="records"),
        FACT_COLUMNS,
    )
    _write_json(
        edgar_dir / "coverage.json", _coverage(artifacts.facts, artifacts.ticker)
    )
    _write_json(
        source_dir / "manifest.json",
        {
            "status": "completed",
            "ticker": artifacts.ticker,
            "cik": artifacts.cik,
            "forms": [artifacts.filing.form_type],
            "view": "standard",
            "parser_version": PARSER_VERSION,
            "fetched_at": datetime.now(UTC).isoformat(),
            "filing_count": 1,
            "fact_count": len(artifacts.facts),
            "filings": [filing_row],
        },
    )
    return output_dir


def _coverage(facts: DataFrame, ticker: str) -> dict[str, Any]:
    by_statement = {
        name: int((facts["statement"] == name).sum())
        if "statement" in facts.columns
        else 0
        for name in STATEMENT_NAMES
    }
    periods = sorted(
        {
            str(value)
            for value in facts.get("period_end", pd.Series(dtype=str)).dropna()
            if str(value)
        }
    )
    return {
        "ticker": ticker,
        "source": "edgar",
        "fact_count": len(facts),
        "concept_count": int(facts["concept"].nunique())
        if "concept" in facts.columns
        else 0,
        "period_count": len(periods),
        "periods": periods,
        "by_statement": by_statement,
    }


def _write_csv(
    path: Path,
    rows: list[Mapping[str, Any]],
    fieldnames: tuple[str, ...],
) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _csv_value(row.get(field)) for field in fieldnames})


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True, default=str)
    return value
