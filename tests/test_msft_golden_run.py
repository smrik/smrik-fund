"""Frozen real-MSFT proof for the complete V1 adjustment path."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from typer.testing import CliRunner

from smrik_fund.ingestion.adjustment_analysis import AnalystCandidate, AnalystResult
from smrik_fund.ingestion.analytical_scan import (
	AnalyticalScanFinding,
	AnalyticalScanResult,
)
from smrik_fund.ingestion.filing import retrieve_filing_evidence
from smrik_fund.ingestion.reviewer import ReviewResult
from smrik_fund.ingestion.statements import prepare_pnl
from smrik_fund.main import _queries_from_finding, app

ACCESSION = "0001193125-26-323660"
PERIOD = "2026-06-30 (FY)"


class GoldenFiling:
	accession_no = ACCESSION
	form = "10-K"
	filing_date = "2026-07-29"
	report_date = "2026-06-30"
	primary_document = "msft-20260630.htm"
	text_url = (
		"https://www.sec.gov/Archives/edgar/data/789019/"
		"000119312526323660/0001193125-26-323660.txt"
	)

	def __init__(self, text: str) -> None:
		self._text = text

	def text(self) -> str:
		return self._text


def golden_pnl(filing: GoldenFiling) -> pd.DataFrame:
	rows = [
		(
			"RevenueFromContractWithCustomerExcludingAssessedTax",
			"Revenue",
			"Revenue",
			331839,
			281724,
			245122,
		),
		(
			"CostOfGoodsAndServicesSold",
			"Cost of revenue",
			"CostOfGoodsAndServicesSold",
			106374,
			87831,
			74114,
		),
		("GrossProfit", "Gross margin", "GrossProfit", 225465, 193893, 171008),
		(
			"ResearchAndDevelopmentExpense",
			"Research and development",
			"ResearchAndDevelopementExpenses",
			35562,
			32488,
			29510,
		),
		(
			"SellingAndMarketingExpense",
			"Sales and marketing",
			"SellingGeneralAndAdminExpenses",
			26710,
			25654,
			24456,
		),
		(
			"GeneralAndAdministrativeExpense",
			"General and administrative",
			"SellingGeneralAndAdminExpenses",
			7956,
			7223,
			7609,
		),
		(
			"OperatingIncomeLoss",
			"Operating income",
			"OperatingIncomeLoss",
			155237,
			128528,
			109433,
		),
		(
			"NonoperatingIncomeExpense",
			"Other income (expense), net",
			"NonoperatingIncomeExpense",
			10697,
			-4901,
			-1646,
		),
		(
			"IncomeLossFromContinuingOperationsBeforeIncomeTaxes",
			"Income before income taxes",
			"PretaxIncomeLoss",
			165934,
			123627,
			107787,
		),
		(
			"IncomeTaxExpenseBenefit",
			"Provision for income taxes",
			"IncomeTaxes",
			32185,
			21795,
			19651,
		),
		("NetIncomeLoss", "Net income", "NetIncome", 133749, 101832, 88136),
	]
	raw = pd.DataFrame(
		[
			{
				"concept": f"us-gaap_{concept}",
				"label": label,
				"standard_concept": standard_concept,
				"2026-06-30 (FY)": fy2026 * 1_000_000.0,
				"2025-06-30 (FY)": fy2025 * 1_000_000.0,
				"2024-06-30 (FY)": fy2024 * 1_000_000.0,
			}
			for concept, label, standard_concept, fy2026, fy2025, fy2024 in rows
		]
	)
	pnl = prepare_pnl(raw, years=3)
	pnl.attrs["edgar_filing"] = filing
	return pnl


def test_scan_finding_queries_prefer_literal_phrases() -> None:
	finding = AnalyticalScanFinding(
		rank=1,
		title="Non-operating sign swing",
		importance="high",
		affected_line_refs=["L03"],
		observation="Gross profit compressed on mix.",
		why_it_matters="May need filing research.",
		investigation_questions=[
			"Why did gross profit decline?",
			"Gross profit decreased due to",
		],
	)
	assert _queries_from_finding(finding) == ["Gross profit decreased due to"]
	finding.investigation_questions = ["Why did gross profit decline?"]
	assert _queries_from_finding(finding) == [finding.title]
	pnl = pd.DataFrame({"label": ["Revenue", "Cost of revenue", "Gross profit"]})
	assert _queries_from_finding(finding, pnl) == ["Gross profit"]


def test_question_only_finding_retrieves_notes_without_issuer_query() -> None:
	finding = AnalyticalScanFinding(
		rank=1,
		title="Margin compression needs research",
		importance="high",
		affected_line_refs=["L03"],
		observation="Gross profit compressed on mix.",
		why_it_matters="May need filing research.",
		investigation_questions=["Why did gross profit decline?"],
	)
	pnl = pd.DataFrame({"label": ["Revenue", "Cost of revenue", "Gross profit"]})
	queries = _queries_from_finding(finding, pnl)
	table = "".join(f"  Gross profit                    {index}\n" for index in range(25))
	note = (
		"Gross profit decreased due to higher service costs. "
		"The decrease was primarily driven by mix rather than a one-time item.\n"
	)

	class BusyFiling:
		accession_no = "0000000000-00-000000"
		form = "10-K"
		filing_date = "2026-01-01"
		report_date = "2025-12-31"
		primary_document = "acme.htm"
		text_url = "https://example.test/acme.txt"
		text_value = "Header\n" + table + note

		def text(self) -> str:
			return self.text_value

		def search(self, query: str, regex: bool = False) -> object:
			assert regex is False
			assert query == "Gross profit"
			return type(
				"Results",
				(),
				{"sections": [type("Section", (), {"loc": 8, "doc": self.text_value})()]},
			)()

	packet, metadata = retrieve_filing_evidence(
		BusyFiling(), "ACME", finding.title, queries
	)
	assert queries == ["Gross profit"]
	assert metadata["queries"] == ["Gross profit"]
	assert metadata["evidence_item_count"] <= 20
	assert "primarily driven by mix" in packet


def test_msft_openai_golden_run(tmp_path: Path) -> None:
	packet = Path(__file__).with_name("msft_openai_gold.md").read_text(encoding="utf-8")
	filing = GoldenFiling(packet)
	pnl = golden_pnl(filing)
	scan = AnalyticalScanResult(
		findings=[
			AnalyticalScanFinding(
				rank=1,
				title="OpenAI recapitalization dilution gain",
				importance="high",
				affected_line_refs=["L08"],
				observation=(
					"Other income (expense), net increased on a disclosed "
					"OpenAI investment net gain."
				),
				why_it_matters="The gain may require normalization.",
				investigation_questions=[
					"dilution gain from the OpenAI Recapitalization"
				],
			)
		]
	)
	analyst = AnalystResult(
		candidates=[
			AnalystCandidate(
				target_line="Other income (expense), net",
				sub_item="OpenAI investment net gains",
				item_key="openai-investment-net-gain",
				period=PERIOD,
				item_amount=6_500_000_000.0,
				item_effect_on_line="increased_line",
				amount_basis="disclosed",
				reason="FY2026 included $6.5 billion of OpenAI investment net gains.",
				evidence_refs=["E1", "E2", "E3", "E4"],
				uncertainty="The dilution-gain component is not separately quantified.",
			)
		]
	)
	reviewer = ReviewResult(
		verdict="accept",
		evidence_strength="strong",
		amount_basis="disclosed",
		judgment_level="high",
		calculation_valid=None,
		target_valid=True,
		item_effect_on_line="increased_line",
		period_valid=True,
		normalization_assessment="eligible",
		recurrence_class="single_period",
		concerns=[
			"The $6.5 billion is the aggregate net gain, not a separately "
			"quantified dilution gain."
		],
		suggested_amount=6_500_000_000.0,
	)

	def retrieve(_filing, ticker, topic, queries, *, output_path=None):
		assert ticker == "MSFT"
		assert topic == "OpenAI recapitalization dilution gain"
		assert queries == ["dilution gain from the OpenAI Recapitalization"]
		assert output_path is not None
		path = Path(output_path)
		path.parent.mkdir(parents=True, exist_ok=True)
		path.write_text(packet, encoding="utf-8")
		return packet, {
			"filing_accession": ACCESSION,
			"form": "10-K",
			"period_of_report": "2026-06-30",
			"source_url": GoldenFiling.text_url,
			"evidence_item_count": 4,
		}

	runner = CliRunner()
	with (
		patch("smrik_fund.main.build_analytical_pnl", return_value=pnl) as build,
		patch(
			"smrik_fund.main.run_analytical_scan",
			return_value=(
				scan,
				{"run_id": "golden-run", "filing_accession": ACCESSION},
			),
		),
		patch(
			"smrik_fund.main.run_discovery",
			side_effect=AssertionError("run uses scan findings, not discovery"),
		),
		patch("smrik_fund.main.retrieve_filing_evidence", side_effect=retrieve),
		patch(
			"smrik_fund.main.run_analyst",
			return_value=(analyst, {"run_id": "golden-run", "model": "frozen"}),
		),
		patch(
			"smrik_fund.main.run_reviewer",
			return_value=(reviewer, {"run_id": "golden-run", "model": "frozen"}),
		),
		patch("smrik_fund.main._new_run_id", return_value="golden-run"),
	):
		run_result = runner.invoke(app, ["run", "MSFT", "--output-root", str(tmp_path)])

	assert run_result.exit_code == 0, run_result.output
	build.assert_called_once_with("MSFT", years=3)

	output = tmp_path / "MSFT" / "03_output"
	manifest = json.loads(
		(output / "analysis" / "adjustment_run_golden-run.json").read_text(
			encoding="utf-8"
		)
	)
	record = manifest["candidates"][0]
	assert manifest["topics"][0]["retrieval"]["filing_accession"] == ACCESSION
	assert record["candidate"]["target_line"] == "Other income (expense), net"
	assert record["candidate"]["period"] == PERIOD
	assert record["candidate"]["item_amount"] == 6_500_000_000.0
	assert record["review"]["verdict"] == "accept"
	assert record["final_status"] == "approved"
	assert record["application_status"] == "applied"
	assert manifest["reported_equals_adjusted"] is False

	history = pd.read_csv(output / "adjustment_history.csv")
	assert len(history) == 1
	assert history.loc[0, "status"] == "approved"
	assert history.loc[0, "origin"] == "llm"
	assert history.loc[0, "target_line"] == "Other income (expense), net"
	assert history.loc[0, "period"] == PERIOD
	assert history.loc[0, "item_amount"] == 6_500_000_000.0
	assert history.loc[0, "line_delta"] == -6_500_000_000.0

	reported = pd.read_csv(output / "analytical_pnl.csv")
	adjusted = pd.read_csv(output / "adjusted_pnl.csv")
	assert (
		reported.loc[reported["label"] == "Other income (expense), net", PERIOD].iloc[0]
		== 10_697_000_000.0
	)
	assert (
		adjusted.loc[adjusted["label"] == "Other income (expense), net", PERIOD].iloc[0]
		== 4_197_000_000.0
	)
	openai = adjusted.loc[adjusted["label"] == "OpenAI investment net gains"]
	assert len(openai) == 1
	assert openai[PERIOD].iloc[0] == 6_500_000_000.0
	assert bool(openai["is_breakdown"].iloc[0])
	assert (
		adjusted.loc[adjusted["label"] == "Income before income taxes", PERIOD].iloc[0]
		== 159_434_000_000.0
	)
	assert (
		adjusted.loc[adjusted["label"] == "Net income", PERIOD].iloc[0]
		== 127_249_000_000.0
	)
	checks = pd.read_csv(output / "adjusted_reconciliation_checks.csv")
	assert list(checks["status"]) == ["PASS"] * len(checks)
	print(
		"CLI run Other-income path: reported "
		f"{10_697_000_000.0:,.0f} -> adjusted {4_197_000_000.0:,.0f}; "
		"added child OpenAI investment net gains "
		f"{6_500_000_000.0:,.0f} is_breakdown=True; "
		f"recon PASS x{len(checks)}"
	)
