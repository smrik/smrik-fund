import json
from types import SimpleNamespace

import pandas as pd
import pytest

from smrik_fund.company_case import freeze_filings, validate_case


def filing(ticker="AAPL", filing_date="2025-10-31"):
	frame = pd.DataFrame({"concept": ["cash", "debt", "unavailable"], "2025-09-27": [10.0, -3.0, None]})
	statement = SimpleNamespace(to_dataframe=lambda **kwargs: frame.copy())
	xbrl = SimpleNamespace(
		entity_info={"identifier": "320193", "ticker": ticker, "entity_name": "Apple Inc.", "document_period_end_date": "2025-09-27"},
		reporting_periods=[{"type": "duration", "start_date": "2024-09-29", "end_date": "2025-09-27"}],
		statements=SimpleNamespace(income_statement=lambda: statement, balance_sheet=lambda: statement, cashflow_statement=lambda: statement),
	)
	return SimpleNamespace(
		filing_date=filing_date, period_of_report="2025-09-27", form="10-K",
		accession_no="0000320193-25-000079", homepage_url="https://www.sec.gov/example",
		xbrl=lambda: xbrl, text=lambda: "Original reported statement evidence",
	)


def test_freeze_preserves_missing_signs_and_noncalendar_periods(tmp_path):
	out = tmp_path / "case"
	manifest = freeze_filings("aapl", "2025-10-31", [filing()], out)
	assert validate_case(out) == manifest
	assert manifest["status"] == "SOURCE_FROZEN_NOT_MODELED"
	root = out / manifest["selected_filings"][0]
	frame = pd.read_csv(root / "balance_sheet.csv")
	assert frame.iloc[1, 1] == -3.0
	assert pd.isna(frame.iloc[2, 1])
	metadata = json.loads((root / "filing.json").read_text())
	assert metadata["reporting_periods"][0]["start_date"] == "2024-09-29"
	(root / "source.txt").write_text("altered")
	with pytest.raises(ValueError, match="Changed source"):
		validate_case(out)


@pytest.mark.parametrize("ticker,source,cutoff", [
	("../MSFT", filing(), "2025-10-31"),
	("MSFT", filing(), "2025-10-31"),
	("AAPL", filing(), "2025-10-30"),
	("AAPL", filing(filing_date="2025-09-01"), "2025-10-31"),
])
def test_wrong_company_path_or_cutoff_never_creates_case(tmp_path, ticker, source, cutoff):
	out = tmp_path / "case"
	with pytest.raises(ValueError):
		freeze_filings(ticker, cutoff, [source], out)
	assert not out.exists()


def test_existing_case_is_not_overwritten(tmp_path):
	out = tmp_path / "case"
	freeze_filings("AAPL", "2025-10-31", [filing()], out)
	with pytest.raises(FileExistsError):
		freeze_filings("AAPL", "2025-10-31", [filing()], out)


@pytest.mark.parametrize("change", ["omit_source", "measurement"])
def test_manifest_cannot_hide_required_evidence_or_change_measurement(tmp_path, change):
	out = tmp_path / "case"
	manifest = freeze_filings("AAPL", "2025-10-31", [filing()], out)
	if change == "omit_source":
		del manifest["artifacts"]["0000320193-25-000079/source.txt"]
	else:
		manifest["measurement_date"] = "2025-10-31"
	(out / "case.json").write_text(json.dumps(manifest))
	with pytest.raises(ValueError):
		validate_case(out)
