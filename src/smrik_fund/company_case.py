"""Freeze a company's native statements and filing context before forecasting."""

import argparse
import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path

from edgar import Company

from smrik_fund.ingestion.statements import configure_edgar


def _json_default(value):
	if isinstance(value, (date, datetime)):
		return value.isoformat()
	raise TypeError(f"Unsupported source metadata: {type(value).__name__}")


def _write_json(path: Path, value) -> None:
	with path.open("x", encoding="utf-8") as stream:
		json.dump(value, stream, indent=2, default=_json_default, allow_nan=False)
		stream.write("\n")


def _identity(ticker: str, cutoff: str) -> tuple[str, date]:
	ticker = ticker.strip().upper()
	if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", ticker):
		raise ValueError("A ticker, not a filesystem path, is required")
	return ticker, date.fromisoformat(cutoff)


def freeze_filings(ticker: str, cutoff: str, filings: list, output_dir: Path, *, expected_cik: str | None = None, include_notes: bool = False) -> dict:
	"""Preserve standard DataFrames; never infer mappings, units or missing facts.

	The manifest is written last. Its hashes bind source text, period metadata,
	and statement CSVs. A partial directory is not a completed company case.
	"""
	ticker, cutoff_date = _identity(ticker, cutoff)
	if not filings:
		raise ValueError("At least one annual filing is required")
	prepared = []
	company_cik = None
	for filing in filings:
		filing_date = date.fromisoformat(str(filing.filing_date))
		measurement = date.fromisoformat(str(filing.period_of_report))
		if not measurement <= filing_date <= cutoff_date:
			raise ValueError("Filing/measurement lies beyond the information cutoff")
		if filing.form not in {"10-K", "10-Q"}:
			raise ValueError("Only unamended 10-K/10-Q statements are supported")
		accession = str(filing.accession_no)
		if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession):
			raise ValueError("Invalid filing accession")
		xbrl = filing.xbrl()
		if xbrl is None:
			raise ValueError("Required filing has no XBRL statements")
		entity = xbrl.entity_info
		cik = str(int(entity["identifier"]))
		if (expected_cik is not None and cik != str(int(expected_cik))) or (expected_cik is None and entity.get("ticker", "").upper() != ticker):
			raise ValueError("Filing ticker does not match the requested company")
		if company_cik is not None and cik != company_cik:
			raise ValueError("Mixed-company source filings")
		company_cik = cik
		if str(entity.get("document_period_end_date")) != measurement.isoformat():
			raise ValueError("Filing and XBRL document periods disagree")
		frames = {}
		for name, getter in (
			("income_statement", xbrl.statements.income_statement),
			("balance_sheet", xbrl.statements.balance_sheet),
			("cash_flow_statement", xbrl.statements.cashflow_statement),
		):
			statement = getter()
			if statement is None:
				raise ValueError(f"Required statement unavailable: {name}")
			frames[name] = statement.to_dataframe(view="standard")
			if frames[name].empty:
				raise ValueError(f"Required statement empty: {name}")
		if include_notes:
			frames["note_facts"] = xbrl.facts.to_dataframe()
		metadata = {
			"accession": accession, "cik": cik, "ticker": ticker,
			"form": filing.form, "filing_date": filing_date.isoformat(),
			"measurement_date": measurement.isoformat(),
			"source_url": filing.homepage_url,
			"entity": entity, "reporting_periods": xbrl.reporting_periods,
		}
		text = filing.text()
		if not isinstance(text, str) or not text.strip():
			raise ValueError("Original filing text is unavailable")
		prepared.append((metadata, frames, text))
	if not any(metadata["form"] == "10-K" for metadata, _, _ in prepared):
		raise ValueError("Annual history is required alongside interim statements")
	if len({metadata["accession"] for metadata, _, _ in prepared}) != len(prepared):
		raise ValueError("Duplicate source filing")
	output_dir = Path(output_dir)
	output_dir.mkdir(parents=True, exist_ok=False)
	artifacts = {}
	for metadata, frames, text in prepared:
		folder = output_dir / metadata["accession"]
		folder.mkdir()
		_write_json(folder / "filing.json", metadata)
		(folder / "source.txt").write_text(text, encoding="utf-8")
		for name, frame in frames.items():
			frame.to_csv(folder / f"{name}.csv", index=False)
		for path in sorted(folder.iterdir()):
			artifacts[path.relative_to(output_dir).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
	latest = max((metadata for metadata, _, _ in prepared), key=lambda item: item["measurement_date"])
	manifest = {
		"schema_version": "company-case-v1", "ticker": ticker, "cik": company_cik,
		"information_cutoff": cutoff_date.isoformat(),
		"measurement_date": latest["measurement_date"],
		"company_name": latest["entity"]["entity_name"],
		"selected_filings": [metadata["accession"] for metadata, _, _ in prepared],
		"artifacts": artifacts,
		"status": "SOURCE_FROZEN_NOT_MODELED",
		"limitations": [
			"Native statement signs, missing values, hierarchy and dimensions are preserved.",
			"Statement columns and XBRL periods are retained separately; ambiguous period joins require review.",
			"No unit conversion, TTM calculation, financial mapping, forecast or analytical approval is implied.",
		],
	}
	_write_json(output_dir / "case.json", manifest)
	return manifest


def freeze_company(ticker: str, cutoff: str, output_dir: Path, *, history_years: int = 5) -> dict:
	ticker, cutoff_date = _identity(ticker, cutoff)
	if type(history_years) is not int or not 1 <= history_years <= 10:
		raise ValueError("Historical annual years must be between 1 and 10")
	configure_edgar()
	company = Company(ticker)
	annuals = company.get_filings(form="10-K", filing_date=f":{cutoff_date}", amendments=False).head(history_years)
	if not len(annuals):
		raise ValueError("No annual filing available at the information cutoff")
	quarter = company.get_filings(form="10-Q", filing_date=f":{cutoff_date}", amendments=False).latest()
	filings = list(annuals)
	annual = max(filings, key=lambda filing: str(filing.period_of_report))
	if quarter is not None and str(quarter.period_of_report) > str(annual.period_of_report):
		filings.append(quarter)
	return freeze_filings(ticker, cutoff, filings, output_dir, expected_cik=str(company.cik), include_notes=True)


def validate_case(output_dir: Path) -> dict:
	"""Reject incomplete, changed or cross-directory evidence before downstream use."""
	output_dir = Path(output_dir).resolve()
	manifest = json.loads((output_dir / "case.json").read_text(encoding="utf-8"))
	_identity(manifest["ticker"], manifest["information_cutoff"])
	if manifest.get("schema_version") != "company-case-v1" or not manifest.get("artifacts"):
		raise ValueError("Unsupported or incomplete company case")
	selected = manifest.get("selected_filings", [])
	if not selected or len(selected) != len(set(selected)):
		raise ValueError("Missing or duplicate selected filings")
	required = {f"{accession}/{name}" for accession in selected for name in (
		"filing.json", "source.txt", "income_statement.csv", "balance_sheet.csv", "cash_flow_statement.csv",
	)}
	required |= {f"{a}/note_facts.csv" for a in selected if f"{a}/note_facts.csv" in manifest["artifacts"]}
	if set(manifest["artifacts"]) != required:
		raise ValueError("Required source artifacts are not fully bound")
	for relative, expected in manifest["artifacts"].items():
		path = (output_dir / relative).resolve()
		if not path.is_relative_to(output_dir):
			raise ValueError("Source artifact escapes company case")
		if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
			raise ValueError(f"Changed source artifact: {relative}")
	metadata_rows = []
	for accession in selected:
		name = f"{accession}/filing.json"
		if name not in manifest["artifacts"]:
			raise ValueError("Unbound filing metadata")
		metadata = json.loads((output_dir / name).read_text(encoding="utf-8"))
		if (metadata["ticker"], metadata["cik"]) != (manifest["ticker"], manifest["cik"]):
			raise ValueError("Company identity changed")
		if not metadata["measurement_date"] <= metadata["filing_date"] <= manifest["information_cutoff"]:
			raise ValueError("Source outside case cutoff")
		metadata_rows.append(metadata)
	if manifest["measurement_date"] != max(row["measurement_date"] for row in metadata_rows):
		raise ValueError("Company measurement date does not match source filings")
	return manifest


def main() -> None:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("ticker")
	parser.add_argument("--as-of", required=True)
	parser.add_argument("--output-dir", required=True, type=Path)
	args = parser.parse_args()
	print(json.dumps(freeze_company(args.ticker, args.as_of, args.output_dir), indent=2))


if __name__ == "__main__":
	main()
