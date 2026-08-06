from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ciq.workbook_parser import CIQWorkbookPayload, parse_ciq_workbook


@dataclass(frozen=True, slots=True)
class CIQSourceResult:
    payload: CIQWorkbookPayload
    output_dir: Path


def write_ciq_artifacts(
    workbook_path: str | Path, output_dir: str | Path
) -> CIQSourceResult:
    """Parse one CIQ workbook and write the source step artifacts."""
    source = Path(workbook_path)
    if not source.exists():
        raise FileNotFoundError(f"CIQ workbook not found: {source}")

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    payload = parse_ciq_workbook(source)
    shutil.copy2(source, destination / "source_workbook.xlsx")
    manifest = {
        "status": "completed",
        "ticker": payload.ticker,
        "source_file": payload.source_file,
        "file_hash": payload.file_hash,
        "parser_version": payload.parser_version,
        "template_fingerprint": payload.template_fingerprint,
        "rows_parsed": payload.rows_parsed,
        "valuation_fact_count": len(payload.valuation_snapshot),
        "comps_row_count": len(payload.comps_snapshot),
        "coverage": payload.coverage_manifest,
    }
    _write_json(destination / "manifest.json", manifest)
    return CIQSourceResult(payload=payload, output_dir=destination)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
