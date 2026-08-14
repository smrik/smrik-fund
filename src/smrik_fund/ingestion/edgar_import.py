"""Fetch SEC EDGAR filings with edgartools and write source-step artifacts."""

from __future__ import annotations

import csv
import json
import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from edgar import Company, set_identity

DEFAULT_FORMS = ("10-K", "10-Q")
DEFAULT_YEARS = 5
DEFAULT_USER_AGENT = "SmrikFund research@example.com"
PARSER_VERSION = "edgartools-v1"
SOURCE_DIR_NAME = "filings"
INDEX_FILENAME = "filing_index.csv"
MANIFEST_FILENAME = "manifest.json"


def _resolve_user_agent() -> str:
    return os.getenv("SMRIK_EDGAR_USER_AGENT") or DEFAULT_USER_AGENT


@dataclass(frozen=True, slots=True)
class FilingRow:
    accession: str
    filing_date: str
    form_type: str
    period_of_report: str
    source_url: str
    output_path: str


@dataclass(frozen=True, slots=True)
class EdgarImportResult:
    ticker: str
    cik: str
    output_dir: Path
    filings: list[FilingRow]
    errors: list[str] = field(default_factory=list)

    @property
    def filing_count(self) -> int:
        return len(self.filings)

    @property
    def error_count(self) -> int:
        return len(self.errors)


def import_edgar_filings(
    ticker: str,
    *,
    years: int = DEFAULT_YEARS,
    forms: Iterable[str] = DEFAULT_FORMS,
    output_root: str | Path = "data",
    refresh: bool = False,
) -> EdgarImportResult:
    """Download the last ``years`` of ``forms`` filings for ``ticker`` into ``output_root``.

    Artifacts written under ``output_root/<TICKER>/01_source/edgar/``:
      - ``filings/<accession>.txt``   primary document text per filing
      - ``filing_index.csv``          accession, filing_date, form_type, source_url, output_path
      - ``manifest.json``             run metadata, per-filing rows, and non-fatal errors

    Already-downloaded filings are skipped unless ``refresh`` is set.
    """
    normalized_ticker: str = ticker.strip().upper()
    if not normalized_ticker:
        raise ValueError("ticker is required")
    form_list: list[str] = _normalise_forms(forms)

    set_identity(_resolve_user_agent())
    company = Company(normalized_ticker)
    cik = str(company.cik).zfill(10)

    ticker_dir = Path(output_root) / normalized_ticker
    source_dir = ticker_dir / "01_source" / "edgar"
    (source_dir / SOURCE_DIR_NAME).mkdir(parents=True, exist_ok=True)

    cutoff = (datetime.now(UTC).date() - timedelta(days=years * 365)).isoformat()
    rows: list[FilingRow] = []
    errors: list[str] = []
    seen_accessions: set[str] = set()

    for form in form_list:
        try:
            filings = company.get_filings(form=form)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{form}: listing failed: {exc}")
            continue
        for filing in filings:
            form_type = str(filing.form or "").strip().upper()
            accession = str(filing.accession_number or "").strip()
            filing_date = _iso_date(filing.filing_date)
            if form_type not in form_list:
                continue
            if filing_date < cutoff:
                continue
            if not accession or accession in seen_accessions:
                continue
            seen_accessions.add(accession)
            try:
                rows.append(_download_filing(filing, source_dir, refresh=refresh))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{form} {accession}: download failed: {exc}")

    _write_index(source_dir, rows)
    _write_manifest(
        source_dir,
        {
            "status": "completed",
            "ticker": normalized_ticker,
            "cik": cik,
            "forms": form_list,
            "years": years,
            "fetched_at": datetime.now(UTC).isoformat(),
            "parser_version": PARSER_VERSION,
            "filing_count": len(rows),
            "error_count": len(errors),
            "errors": errors,
            "filings": [row_to_dict(row) for row in rows],
        },
    )
    return EdgarImportResult(
        ticker=normalized_ticker,
        cik=cik,
        output_dir=ticker_dir,
        filings=rows,
        errors=errors,
    )


def _download_filing(filing: Any, destination: Path, *, refresh: bool) -> FilingRow:
    accession = str(filing.accession_number or "").strip()
    target = destination / SOURCE_DIR_NAME / f"{accession}.txt"
    if target.exists() and not refresh:
        output_path = str(target)
    else:
        text = filing.text()
        if not text:
            raise RuntimeError("edgartools returned no document text")
        target.write_text(text, encoding="utf-8")
        output_path = str(target)

    return FilingRow(
        accession=accession,
        filing_date=_iso_date(filing.filing_date),
        form_type=str(filing.form or "").strip().upper(),
        period_of_report=_iso_date(getattr(filing, "period_of_report", None)),
        source_url=str(getattr(filing, "filing_url", "") or ""),
        output_path=output_path,
    )


def _iso_date(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text[:10] if text else ""


def _normalise_forms(forms: Iterable[str]) -> list[str]:
    normalised: list[str] = []
    seen: set[str] = set()
    for value in forms:
        form = value.strip().upper()
        if not form or form in seen:
            continue
        normalised.append(form)
        seen.add(form)
    return normalised or list(DEFAULT_FORMS)


def row_to_dict(row: FilingRow) -> dict[str, str]:
    return {
        "accession": row.accession,
        "filing_date": row.filing_date,
        "form_type": row.form_type,
        "period_of_report": row.period_of_report,
        "source_url": row.source_url,
        "output_path": row.output_path,
    }


def _write_index(destination: Path, rows: list[FilingRow]) -> None:
    fieldnames = [
        "accession",
        "filing_date",
        "form_type",
        "period_of_report",
        "source_url",
        "output_path",
    ]
    with (destination / INDEX_FILENAME).open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row_to_dict(row))


def _write_manifest(destination: Path, payload: dict[str, Any]) -> None:
    (destination / MANIFEST_FILENAME).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
