"""Load a case's frozen inputs and build a file-backed filing seam.

The filing seam is why live execution stays reproducible.  The product runs its
normal retrieval and model calls, but the filing *text* comes from the frozen
snapshot pinned by the case rather than from a network fetch, so two runs of the
same case differ only by model sampling - not by source drift.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd

from ..ingestion.analytical_scan import AnalyticalScanFinding
from ..ingestion.filing_investigation import (
	FilingInvestigationError,
	load_saved_scan,
	select_saved_finding,
)
from ..ingestion.segments import load_segment_analytics
from ..ingestion.statements import load_analytical_pnl


class CaseInputError(RuntimeError):
	"""Raised when a case's frozen inputs are missing or inconsistent."""


def resolve(repository_root: str | Path, value: str | Path) -> Path:
	path = Path(value)
	return path if path.is_absolute() else Path(repository_root) / path


def filing_from_source(case: dict[str, Any], repository_root: str | Path) -> Any:
	"""Return a filing-like object backed by the frozen source text."""
	source_path = resolve(repository_root, case["source_artifact"])
	text = source_path.read_text(encoding="utf-8")
	accession = str(case.get("accession") or "").strip()
	period = str(case.get("filing_period") or "").strip()
	filing_url = f"https://www.sec.gov/Archives/edgar/data/{accession}"

	manifest_path = resolve(repository_root, case["source_manifest_artifact"])
	if manifest_path.is_file():
		try:
			manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
		except json.JSONDecodeError:
			manifest = {}
		for item in manifest.get("filings", []) if isinstance(manifest, dict) else []:
			if str(item.get("accession", "")) == accession:
				filing_url = str(item.get("source_url") or filing_url)
				period = str(item.get("period_of_report") or period)
				break

	def text_method() -> str:
		return text

	def search_method(query: str, regex: bool = False) -> Any:
		matched = (
			bool(re.search(query, text, flags=re.IGNORECASE))
			if regex
			else query.casefold() in text.casefold()
		)
		if not matched:
			return SimpleNamespace(sections=[])
		section = SimpleNamespace(doc=text, loc=1, section="frozen SEC filing text")
		return SimpleNamespace(sections=[section])

	return SimpleNamespace(
		accession_no=accession,
		accession_number=accession,
		form="10-K",
		filing_date=None,
		report_date=period,
		period_of_report=period,
		primary_document=source_path.name,
		filing_url=filing_url,
		text_url=filing_url,
		source_path=str(source_path),
		text=text_method,
		search=search_method,
	)


class CaseInputs(SimpleNamespace):
	"""The frozen inputs one product execution needs."""

	pnl: pd.DataFrame
	filing: Any
	finding: AnalyticalScanFinding
	scan_context: str
	scan_metadata: dict[str, Any]
	segments: pd.DataFrame | None


def load(case: dict[str, Any], repository_root: str | Path) -> CaseInputs:
	"""Load and cross-check every frozen input required by one case."""
	ticker = str(case["ticker"]).strip().upper()
	input_root = resolve(repository_root, case["input_root"])
	pnl = load_analytical_pnl(ticker, input_root)

	segments = None
	if case.get("requires_segments") or any(
		str(ref).startswith("S") for ref in case.get("finding_refs", [])
	):
		segments = load_segment_analytics(ticker, input_root)

	if not case.get("scan_artifact"):
		# The scan workflow produces the scan rather than consuming one, so
		# there is no saved finding to cross-check here.
		return CaseInputs(
			pnl=pnl,
			filing=filing_from_source(case, repository_root),
			finding=None,
			scan_context=None,
			scan_metadata={},
			segments=segments,
		)

	scan_path = resolve(repository_root, case["scan_artifact"])
	scan_result, _first, scan_context, scan_metadata = load_saved_scan(
		scan_path, ticker, pnl, segments
	)

	expected = str(case.get("accession") or "").strip()
	actual = str(scan_metadata.get("filing_accession") or "").strip()
	if actual != expected:
		raise CaseInputError(
			f"saved scan accession {actual!r} does not match frozen case {expected!r}"
		)

	try:
		finding = select_saved_finding(scan_result, int(case["finding_rank"]))
	except (FilingInvestigationError, ValueError, KeyError) as exc:
		raise CaseInputError(f"could not select frozen finding: {exc}") from exc

	if tuple(finding.affected_line_refs) != tuple(case.get("finding_refs", ())):
		raise CaseInputError(
			"frozen finding identity does not match the case: "
			f"{tuple(finding.affected_line_refs)} != "
			f"{tuple(case.get('finding_refs', ()))}"
		)

	return CaseInputs(
		pnl=pnl,
		filing=filing_from_source(case, repository_root),
		finding=finding,
		scan_context=scan_context,
		scan_metadata=scan_metadata,
		segments=segments,
	)
