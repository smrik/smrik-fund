from __future__ import annotations

import csv
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from db.loader import load_statement_facts
from db.schema import get_read_only_connection


@dataclass(frozen=True, slots=True)
class EdgarSourceResult:
    payload: dict[str, Any]
    output_dir: Path

    @property
    def filing_count(self) -> int:
        return len(self.payload["filings"])


def write_edgar_artifacts(
    ticker: str,
    cache_path: str | Path,
    output_dir: str | Path,
    *,
    reference_db_path: str | Path | None = None,
) -> EdgarSourceResult:
    """Copy cached filing text into the run folder without network access."""
    cache = Path(cache_path)
    rows = _read_cache_index(cache, ticker, reference_db_path)
    destination = Path(output_dir)
    (destination / "filings").mkdir(parents=True, exist_ok=True)

    copied_rows: list[dict[str, str]] = []
    for row in rows:
        accession = row["accession"]
        source_path = Path(row["source_path"])
        if not source_path.is_absolute():
            source_path = cache / source_path
        if not source_path.exists():
            raise FileNotFoundError(f"cached EDGAR filing not found: {source_path}")
        target = destination / "filings" / f"{accession}.txt"
        shutil.copyfile(source_path, target)
        copied_rows.append({**row, "output_path": str(target)})

    facts = _load_cached_facts(ticker, copied_rows, cache, reference_db_path)

    _write_csv(
        destination / "filing_index.csv",
        copied_rows,
        ["accession", "filing_date", "form_type", "source_path", "output_path"],
    )
    manifest = {
        "status": "completed",
        "ticker": ticker.upper(),
        "source": str(cache),
        "filing_count": len(copied_rows),
        "filings": copied_rows,
        "parser_version": "edgar-cache-v1",
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    return EdgarSourceResult(
        payload={"ticker": ticker.upper(), "filings": copied_rows, "facts": facts},
        output_dir=destination,
    )


def _load_cached_facts(
    ticker: str,
    filings: list[dict[str, str]],
    cache: Path,
    reference_db_path: str | Path | None,
) -> list[dict[str, Any]]:
    db_path = (
        Path(reference_db_path)
        if reference_db_path
        else (cache if cache.is_file() else Path("data/alpha_pod.db"))
    )
    if not db_path.exists():
        return []
    accessions = {row["accession"] for row in filings}
    with get_read_only_connection(db_path) as connection:
        cached = load_statement_facts(
            connection,
            ticker,
            sources=[
                "sec_xbrl_filing_presentation_v1",
                "sec_xbrl_derived_ltm_v1",
            ],
        )
    facts: list[dict[str, Any]] = []
    for row in cached:
        if row.get("accession") not in accessions and row.get("source") != (
            "sec_xbrl_derived_ltm_v1"
        ):
            continue
        item = dict(row)
        item["original_source"] = item.get("source")
        item["source"] = "edgar"
        item["ticker"] = ticker.upper()
        item["value"] = item.get("value", item.get("numeric_value"))
        item["source_locator"] = item.get("source_locator") or (
            f"edgar:{item.get('accession') or item.get('fact_id')}"
        )
        facts.append(item)
    return facts


def _read_cache_index(
    cache: Path,
    ticker: str,
    reference_db_path: str | Path | None,
) -> list[dict[str, str]]:
    index_path = cache / "filing_index.csv" if cache.is_dir() else None
    if index_path and index_path.exists():
        return _read_csv_index(index_path, cache, ticker)

    db_path = (
        cache if cache.is_file() else Path(reference_db_path or "data/alpha_pod.db")
    )
    if not db_path.exists():
        raise FileNotFoundError(
            "EDGAR cache needs filing_index.csv or a reference database with cached filings"
        )
    with get_read_only_connection(db_path) as connection:
        rows = connection.execute(
            """
            SELECT accession_no, filing_date, form_type, clean_path, raw_path
            FROM edgar_filing_cache
            WHERE ticker = ? AND form_type IN ('10-K', '10-Q')
            ORDER BY COALESCE(filing_date, '') DESC
            """,
            (ticker.upper(),),
        ).fetchall()
    return [
        {
            "accession": str(row[0]),
            "filing_date": str(row[1] or ""),
            "form_type": str(row[2]),
            "source_path": str(row[3] or row[4] or ""),
        }
        for row in rows
        if row[3] or row[4]
    ]


def _read_csv_index(path: Path, cache: Path, ticker: str) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    output: list[dict[str, str]] = []
    for row in rows:
        row_ticker = str(row.get("ticker") or ticker).strip().upper()
        if row_ticker != ticker.upper():
            continue
        accession = str(row.get("accession") or row.get("accession_no") or "").strip()
        source_path = str(row.get("source_path") or row.get("path") or "").strip()
        if not accession or not source_path:
            raise ValueError("filing_index.csv needs accession and source_path")
        output.append(
            {
                "accession": accession,
                "filing_date": str(row.get("filing_date") or ""),
                "form_type": str(row.get("form_type") or ""),
                "source_path": str((cache / source_path).resolve())
                if not Path(source_path).is_absolute()
                else source_path,
            }
        )
    return output


def _write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
