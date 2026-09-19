"""Historical source selection and the exported, period-aligned workbook."""

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pandas as pd
import pytest

from smrik_fund.company_history import annual_history

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "data/history/20260919/BBWI/source"


def history_fixture():
	period = {
		"type": "duration",
		"start_date": "2023-01-29",
		"end_date": "2024-02-03",
		"days": 371,
	}
	old = {
		"form": "10-K",
		"accession": "old",
		"filing_date": "2024-03-01",
		"measurement_date": "2024-02-03",
		"entity": {"fiscal_year": 2023},
		"source_url": "https://www.sec.gov/old",
		"reporting_periods": [period],
	}
	new = {
		**old,
		"accession": "new",
		"filing_date": "2025-03-01",
		"measurement_date": "2025-02-01",
		"entity": {"fiscal_year": 2024},
		"source_url": "https://www.sec.gov/new",
	}
	columns = {
		"income_statement": "2024-02-03 (FY)",
		"cash_flow_statement": "2024-02-03 (FY)",
		"balance_sheet": "2024-02-03",
	}
	data = {
		"income_statement": {
			"Revenues": 100e6,
			"OperatingIncomeLoss": 20e6,
			"IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest": 15e6,
			"NetIncomeLoss": 12e6,
			"IncomeTaxExpenseBenefit": -3e6,
		},
		"cash_flow_statement": {
			"NetCashProvidedByUsedInOperatingActivities": 18e6,
			"PaymentsToAcquirePropertyPlantAndEquipment": -5e6,
		},
		"balance_sheet": {
			"Assets": 150e6,
			"AssetsCurrent": 50e6,
			"CashAndCashEquivalentsAtCarryingValue": 10e6,
			"LiabilitiesCurrent": 20e6,
			"DebtCurrent": 4e6,
		},
	}
	frames = {}
	for accession in ("old", "new"):
		frames[accession] = {
			s: pd.DataFrame(
				{
					"concept": ["us-gaap_" + c for c in values],
					"dimension": False,
					"abstract": False,
					columns[s]: list(values.values()),
				}
			)
			for s, values in data.items()
		}
	frames["old"]["income_statement"].loc[0, columns["income_statement"]] = 110e6
	return [old, new], frames


def test_latest_comparative_source_preserves_fiscal_year_signs_and_lineage():
	metadata, frames = history_fixture()
	evidence = []
	history = annual_history(metadata, frames, evidence)
	p = history["periods"][0]
	assert (p["label"], p["end"], p["days"]) == ("FY2023", "2024-02-03", 371)
	assert p["values"]["revenue"] == 100
	assert p["values"]["capex_cash"] == -5
	assert p["values"]["tax_reported"] == -3
	assert p["values"]["tax_expense"] == 3
	assert p["sources"]["income_statement"]["accession"] == "new"
	assert any(
		e["file"] == "new/income_statement.csv"
		and e["line"] == 2
		and e["reported_value"] == 100e6
		for e in evidence
	)
	assert "Only 1 of 5" in history["issues"][0]


@pytest.mark.parametrize("problem", ["null", "absent", "duplicate", "infinite"])
def test_missing_or_ambiguous_latest_fact_never_uses_older_value(problem):
	metadata, frames = history_fixture()
	frame = frames["new"]["income_statement"]
	if problem == "null":
		frame.iloc[0, 3] = None
	elif problem == "infinite":
		frame.iloc[0, 3] = float("inf")
	elif problem == "absent":
		frames["new"]["income_statement"] = frame.iloc[1:]
	else:
		frames["new"]["income_statement"] = pd.concat(
			[frame, frame.iloc[:1]], ignore_index=True
		)
	p = annual_history(metadata, frames, [])["periods"][0]
	assert p["values"]["revenue"] is None
	assert p["sources"]["income_statement"]["accession"] == "new"


def test_ambiguous_duration_stops_instead_of_inventing_history():
	metadata, frames = history_fixture()
	metadata[1]["reporting_periods"] = metadata[1]["reporting_periods"] * 2
	with pytest.raises(ValueError, match="Ambiguous annual history duration"):
		annual_history(metadata, frames, [])


def test_discontinued_income_and_tax_signs_are_not_normalized_blindly():
	metadata, frames = history_fixture()
	frame = frames["new"]["income_statement"]
	frame.loc[len(frame)] = [
		"us-gaap_IncomeLossFromContinuingOperations",
		False,
		False,
		10e6,
	]
	frame.loc[len(frame)] = [
		"us-gaap_IncomeLossFromDiscontinuedOperationsNetOfTax",
		False,
		False,
		2e6,
	]
	frame.loc[
		frame.concept.eq("us-gaap_IncomeTaxExpenseBenefit"), "2024-02-03 (FY)"
	] = 5e6
	history = annual_history(metadata, frames, [])
	assert history["periods"][0]["values"]["tax_expense"] == 5
	assert any("discontinued operations" in issue for issue in history["issues"])
	frame.loc[
		frame.concept.eq("us-gaap_IncomeTaxExpenseBenefit"), "2024-02-03 (FY)"
	] = 7e6
	assert (
		annual_history(metadata, frames, [])["periods"][0]["values"]["tax_expense"]
		is None
	)


def test_missing_current_component_keeps_group_missing():
	metadata, frames = history_fixture()
	frame = frames["new"]["balance_sheet"]
	frame.loc[frame.concept.eq("us-gaap_DebtCurrent"), "2024-02-03"] = None
	p = annual_history(metadata, frames, [])["periods"][0]
	assert p["values"]["operating_current_liabilities"] is None
	assert p["values"]["operating_current_assets"] == 40
	assert (
		"absent face categories stay in the parent"
		in p["groups"]["operating_current_assets"]["basis"]
	)


def test_capture_selects_five_annual_filings_and_latest_quarter(monkeypatch, tmp_path):
	import smrik_fund.company_case as module

	annuals = [
		SimpleNamespace(period_of_report=f"{year}-12-31")
		for year in range(2025, 2018, -1)
	]
	quarter = SimpleNamespace(period_of_report="2026-06-30")

	class Filings(list):
		def head(self, count):
			return self[:count]

		def latest(self):
			return self[0]

	def get_filings(**kwargs):
		assert kwargs["filing_date"] == ":2026-09-16"
		assert kwargs["amendments"] is False
		return Filings(annuals if kwargs["form"] == "10-K" else [quarter])

	monkeypatch.setattr(module, "configure_edgar", lambda: None)
	monkeypatch.setattr(
		module,
		"Company",
		lambda ticker: SimpleNamespace(cik=1, get_filings=get_filings),
	)
	monkeypatch.setattr(
		module, "freeze_filings", lambda ticker, cutoff, filings, output, **kw: filings
	)
	assert module.freeze_company("TEST", "2026-09-16", tmp_path) == annuals[:5] + [
		quarter
	]
	with pytest.raises(ValueError, match="Historical annual years"):
		module.freeze_company("TEST", "2026-09-16", tmp_path, history_years=True)


@pytest.mark.skipif(
	not CASE.exists(), reason="Local frozen BBWI acceptance case required"
)
def test_saved_bbwi_workbook_has_history_visible_drivers_and_no_schedules(tmp_path):
	from smrik_fund.company_run import build
	from smrik_fund.portable_model import prepare_model

	model = prepare_model(CASE)
	model["controls"] = json.loads(
		(ROOT / "data/weekend/20260919/BBWI/assumptions.json").read_text()
	)["controls"]
	snapshot = build(model, tmp_path)
	assert snapshot["per_share_value"] == pytest.approx(41.470558671367186)
	assert snapshot["presentation"]["history_columns"] == 5
	assert [p["label"] for p in model["annual_history"]["periods"]] == [
		f"FY{y}" for y in range(2021, 2026)
	]
	assert all("STUB" not in h for h in snapshot["presentation"]["headers"])
	assert snapshot["presentation"]["headers"][6].startswith("TTM")
	ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
	with ZipFile(tmp_path / "BBWI.xlsx") as archive:
		workbook = ET.fromstring(archive.read("xl/workbook.xml"))
		names = [s.attrib["name"] for s in workbook.findall("s:sheets/s:sheet", ns)]
		assert "Schedules" not in names

		def cells(name):
			root = ET.fromstring(
				archive.read(f"xl/worksheets/sheet{names.index(name) + 1}.xml")
			)
			return {c.attrib["r"]: c for c in root.findall(".//s:c", ns)}

		assets, income, balance = (
			cells("Assets"),
			cells("Income"),
			cells("BalanceSheet"),
		)
		cash_flow = cells("CashFlow")
		assert [
			float(cash_flow[f"{c}9"].findtext("s:v", namespaces=ns)) for c in "BCDEFG"
		] == [363, 221, 269, 282, 254, 246]
		for address in ("H12", "H16", "H24"):
			assert assets[address].find("s:f", ns) is not None, (
				f"Export lost driver {address}"
			)
		assert "H12" in income["H11"].findtext("s:f", namespaces=ns)
		assert "H29" in income["H28"].findtext("s:f", namespaces=ns)
		assert "SUM(H6:H11)" in balance["H15"].findtext("s:f", namespaces=ns)
		for name in names:
			assert all(
				"Schedules!" not in c.findtext("s:f", default="", namespaces=ns)
				for c in cells(name).values()
			)
	# No historical presentation edits are allowed to change the forecast economics.
	prior = json.loads(
		(ROOT / "data/weekend/20260919/BBWI/base-r2/reviewed/snapshot.json").read_text()
	)
	for metric, values in snapshot["schedules"].items():
		assert values == pytest.approx(prior["schedules"][metric], abs=1e-6)
