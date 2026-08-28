from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import pandas as pd
from pydantic import ValidationError
from typer.testing import CliRunner

from smrik_fund.ingestion.analytical_scan import (
	AnalyticalScanFinding,
	AnalyticalScanResult,
	format_analytical_pnl_for_scan,
	save_analytical_scan,
)
from smrik_fund.ingestion.filing_investigation import (
	DisclosedDriver,
	FilingGroundedQuery,
	FilingInvestigationError,
	FilingQueryExpansion,
	FinancialInvestigationResult,
	FindingSearchPlan,
	_driver_claim_supported,
	_movement_reconciliation,
	_select_initial_queries,
	build_finding_plan_context,
	build_initial_search_plan,
	extract_period_paired_disclosures,
	investigate_finding,
	load_saved_scan,
	reconcile_disclosed_amounts,
	reconcile_period_pair_bridge,
	render_finding_investigation_summary,
	run_financial_investigation,
	run_search_plan,
	validate_financial_investigation,
	validate_query_expansion,
)
from smrik_fund.ingestion.segments import (
	load_segment_analytics,
	save_segment_analytics,
	save_segment_reconciliation,
)
from smrik_fund.ingestion.statements import prepare_pnl, save_analytical_pnl
from smrik_fund.main import app

PERIODS = (
	"2026-06-30 (FY)",
	"2025-06-30 (FY)",
	"2024-06-30 (FY)",
)


def make_pnl() -> pd.DataFrame:
	return prepare_pnl(
		pd.DataFrame(
			{
				"concept": ["Revenue", "OtherIncome"],
				"label": ["Revenue", "Other income (expense), net"],
				"standard_concept": ["Revenue", "NonoperatingIncomeExpense"],
				PERIODS[0]: [110.0, -4.0],
				PERIODS[1]: [100.0, -1.0],
				PERIODS[2]: [90.0, 2.0],
			}
		)
	)


def finding() -> AnalyticalScanFinding:
	return AnalyticalScanFinding(
		rank=1,
		title="Reported movement",
		importance="high",
		affected_line_refs=["L01"],
		observation="Revenue increased by 10.",
		why_it_matters="The filing may explain the change.",
		investigation_questions=["What disclosed driver explains the movement?"],
	)


def make_segments() -> tuple[pd.DataFrame, pd.DataFrame]:
	rows: list[dict[str, object]] = []
	revenue_values = [110.0, 100.0, 90.0]
	for metric, values in {
		"Revenue": revenue_values,
		"OperatingIncomeLoss": [55.0, 50.0, 45.0],
	}.items():
		for index, (period, value) in enumerate(zip(PERIODS, values, strict=True)):
			previous = values[index + 1] if index + 1 < len(values) else None
			rows.append(
				{
					"segment_axis": "StatementBusinessSegmentsAxis",
					"segment_member": "example:Member",
					"segment_label": "Example",
					"metric": metric,
					"period": period,
					"reported_value": value,
					"numeric_value": value,
					"fact_status": "PASS",
					"segment_ref": "",
					"absolute_yoy_change": None if previous is None else value - previous,
					"yoy_growth": None if previous is None else value / previous - 1,
					"revenue_share": None
					if metric != "Revenue"
					else value / revenue_values[index],
					"revenue_share_change_bps": None,
					"revenue_growth_contribution": None,
					"operating_margin": None
					if metric != "OperatingIncomeLoss"
					else value / revenue_values[index],
					"operating_margin_bps_change": None,
					"operating_income_growth_contribution": None,
				}
			)
	checks = pd.DataFrame(
		{
			"metric": ["Revenue", "OperatingIncomeLoss"],
			"period": [PERIODS[0], PERIODS[0]],
			"reported_segment_total": [110.0, 55.0],
			"reported_consolidated_total": [110.0, 55.0],
			"residual": [0.0, 0.0],
			"status": ["PASS", "PASS"],
		}
	)
	segments = pd.DataFrame(rows)
	segments.attrs["segment_reconciliation"] = checks
	return segments, checks


class FakeSection:
	def __init__(self, doc: str, loc: int = 42) -> None:
		self.doc = doc
		self.loc = loc


class FakeFiling:
	accession_no = "A1"
	form = "10-K"
	filing_date = "2026-07-30"
	report_date = "2026-06-30"
	primary_document = "msft.htm"
	text_url = "https://example.test/msft.txt"
	filing_url = "https://example.test/msft.htm"

	def __init__(self) -> None:
		self.text_value = "Revenue increased $10 million driven by demand.\n"
		self.searches: list[tuple[str, bool]] = []

	def text(self) -> str:
		return self.text_value

	def search(self, query: str, regex: bool = False) -> object:
		self.searches.append((query, regex))
		return SimpleNamespace(sections=[FakeSection(self.text_value)])


class FakeResponsesClient:
	def __init__(self) -> None:
		self.calls: list[dict[str, object]] = []
		self.responses = SimpleNamespace(parse=self.parse)

	def parse(self, **kwargs: object) -> object:
		self.calls.append(kwargs)
		if len(self.calls) == 1:
			return SimpleNamespace(
				output_parsed=FindingSearchPlan(
					finding_rank=1,
					affected_line_refs=["L01"],
					queries=[" Revenue increased $10 million "],
				)
			)
		return SimpleNamespace(
			output_parsed=FinancialInvestigationResult(
				disclosed_drivers=[
					DisclosedDriver(
						description="Demand",
						amount=None,
						evidence_refs=["E1"],
					)
				],
				interpretation="The supplied passage attributes the movement to demand.",
				interpretation_evidence_refs=["E1"],
				unresolved_remainder="The unquantified contribution remains unresolved.",
				unresolved_remainder_evidence_refs=["E1"],
				explanation="Demand is disclosed, but no amount is disclosed.",
				explanation_evidence_refs=["E1"],
			)
		)


class FilingInvestigationTests(TestCase):
	def evidence_packet(
		self, excerpt: str = "The filing disclosed $5 million in 2026."
	) -> str:
		return (
			"Ticker: MSFT\nFiling accession: A1\nSource: filing\n\n"
			"### E1\nSource: filing\nSection: note\n"
			"Locator: accession A1; line 1\n\n> " + excerpt + "\n"
		)

	def paired_evidence_packet(self, excerpts: list[str]) -> str:
		lines = [
			"Ticker: MSFT",
			"Filing accession: A1",
			"Source: https://example.test/msft.txt",
			"",
		]
		for index, excerpt in enumerate(excerpts, start=1):
			lines.extend(
				[
					f"### E{index}",
					"Source: https://example.test/msft.txt",
					"Section: note",
					f"Locator: accession A1; line {index}",
					"",
					f"> {excerpt}",
					"",
				]
			)
		return "\n".join(lines)

	def target_pnl_and_finding(self) -> tuple[pd.DataFrame, AnalyticalScanFinding]:
		pnl = prepare_pnl(
			pd.DataFrame(
				{
					"concept": ["OtherIncome"],
					"label": ["Other income (expense), net"],
					"standard_concept": ["NonoperatingIncomeExpense"],
					PERIODS[0]: [10_697_000_000],
					PERIODS[1]: [-4_901_000_000],
					PERIODS[2]: [-1_646_000_000],
				}
			)
		)
		return pnl, AnalyticalScanFinding(
			rank=1,
			title="Other income swing",
			importance="high",
			affected_line_refs=["L01"],
			observation="The reported line moved.",
			why_it_matters="The movement is material.",
		)

	def test_plan_is_literal_bounded_and_deduplicated(self) -> None:
		plan = FindingSearchPlan(
			finding_rank=1,
			affected_line_refs=["L01"],
			queries=[" A.B [x] ", "a.b [x]"],
		)
		self.assertEqual(plan.queries, ["A.B [x]"])
		with self.assertRaises(ValidationError):
			FindingSearchPlan(
				finding_rank=1,
				affected_line_refs=["L01"],
				queries=["a", "b", "c", "d"],
			)

	def test_initial_seed_generation_is_deterministic_and_closed_world(self) -> None:
		context = {
			"lines": [
				{
					"line_ref": "L01",
					"source_label": "Other income (expense), net",
					"concept": "NonoperatingIncomeExpense",
				}
			],
			"filing_text": "OpenAI drove the result.",
		}
		plan, derivations = build_initial_search_plan(finding(), context)
		self.assertEqual(
			plan.queries,
			[
				"Other income (expense), net increased",
				"Other income (expense), net decreased",
				"Other income (expense), net driven by",
			],
		)
		self.assertNotIn("openai", " ".join(plan.queries).casefold())
		self.assertEqual(len(derivations), 6)
		self.assertEqual(derivations[0]["line_refs"], ["L01"])
		self.assertEqual(derivations[0]["generic_cue"], "increased")
		self.assertEqual(derivations[0]["pass_name"], "initial")
		run_plan, metadata = run_search_plan("MSFT", finding(), context)
		self.assertEqual(run_plan.queries, plan.queries)
		self.assertEqual(metadata["planner_call_count"], 0)

	def test_initial_candidates_use_generic_concept_qualifiers(self) -> None:
		context = {
			"lines": [
				{
					"line_ref": "L01",
					"source_label": "Sales and marketing",
					"concept": "us-gaap_SellingAndMarketingExpense",
				}
			]
		}
		plan, derivations = build_initial_search_plan(finding(), context)

		self.assertEqual(plan.queries[0], "Sales and marketing expenses increased")
		self.assertEqual(
			[item["query"] for item in derivations[:5]],
			[
				"Sales and marketing expenses increased",
				"Sales and marketing expenses decreased",
				"Sales and marketing expenses driven by",
				"Sales and marketing expenses due to",
				"Sales and marketing expenses offset",
			],
		)
		self.assertTrue(all("OpenAI" not in item["query"] for item in derivations))

	def test_initial_selection_prefers_movement_and_keeps_static_fallback(self) -> None:
		class MixedFiling:
			def text(self) -> str:
				return (
					"Sales and marketing expenses include payroll.\n"
					"Sales and marketing expenses increased driven by commercial sales.\n"
				)

		class StaticFiling:
			def text(self) -> str:
				return "Sales and marketing expenses include payroll.\n"

		context = {
			"lines": [
				{
					"line_ref": "L01",
					"source_label": "Sales and marketing",
					"concept": "us-gaap_SellingAndMarketingExpense",
				}
			]
		}
		plan, derivations = build_initial_search_plan(finding(), context)
		selected, metadata = _select_initial_queries(MixedFiling(), plan, derivations)
		self.assertEqual(selected.queries, ["Sales and marketing expenses increased"])
		self.assertEqual(metadata["query_derivations"][0]["generic_cue"], "increased")
		self.assertTrue(
			any(
				item["reason"] == "static fallback superseded by movement query"
				for item in metadata["rejected_candidates"]
			)
		)

		static_selected, static_metadata = _select_initial_queries(
			StaticFiling(), plan, derivations
		)
		self.assertEqual(static_selected.queries, ["Sales and marketing"])
		self.assertEqual(static_metadata["query_derivations"][0]["generic_cue"], None)

	def test_initial_selection_deduplicates_line_refs_before_query_cap(self) -> None:
		finding_value = finding().model_copy(update={"affected_line_refs": ["L01", "L02", "L03"]})
		context = {
			"lines": [
				{"line_ref": "L01", "source_label": "Cost of revenue"},
				{"line_ref": "L02", "source_label": "Gross margin"},
				{"line_ref": "L03", "source_label": "Service and Other"},
			]
		}
		plan, derivations = build_initial_search_plan(finding_value, context)
		class Filing:
			def text(self) -> str:
				return "Cost of revenue increased. Gross margin increased. Cost of revenue decreased. Service and Other."
		selected, metadata = _select_initial_queries(Filing(), plan, derivations)
		self.assertEqual(selected.queries, ["Cost of revenue increased", "Gross margin increased", "Service and Other"])
		self.assertEqual(metadata["query_derivations"][-1]["line_refs"], ["L03"])


	def test_build_finding_plan_context_excludes_filing_text(self) -> None:
		context = build_finding_plan_context(make_pnl(), FakeFiling(), finding())
		self.assertNotIn("passages", context)
		self.assertNotIn("OpenAI", json.dumps(context))
		self.assertEqual(context["lines"][0]["source_label"], "Revenue")

	def test_expansion_requires_verbatim_first_pass_support(self) -> None:
		packet = self.evidence_packet(
			"Other income included a dilution gain from OpenAI Recapitalization."
		)
		span = "Other income included a dilution gain from OpenAI Recapitalization."
		accepted, metadata = validate_query_expansion(
			FilingQueryExpansion(
				queries=[
					FilingGroundedQuery(
						query="OpenAI Recapitalization",
						evidence_refs=["E1"],
						support_span=span,
					),
					FilingGroundedQuery(
						query="OpenAI",
						evidence_refs=["E1"],
						support_span=span,
					),
					FilingGroundedQuery(
						query="Unsupported company term",
						evidence_refs=["E99"],
						support_span="Unsupported company term",
					),
				],
			),
			packet,
			["Other income included"],
		)
		self.assertEqual([item.query for item in accepted], ["OpenAI Recapitalization"])
		self.assertEqual(metadata["accepted_query_count"], 1)
		self.assertEqual(metadata["rejected_query_count"], 2)
		self.assertTrue(
			any(
				"two meaningful" in item["reason"]
				for item in metadata["rejected_candidates"]
			)
		)

	def test_expansion_requires_literal_filing_text_when_source_is_available(
		self,
	) -> None:
		packet = self.evidence_packet(
			"Other income included a dilution gain from OpenAI Recapitalization."
		)
		accepted, metadata = validate_query_expansion(
			FilingQueryExpansion(
				queries=[
					FilingGroundedQuery(
						query="OpenAI Recapitalization",
						evidence_refs=["E1"],
						support_span=(
							"Other income included a dilution gain from OpenAI "
							"Recapitalization."
						),
					)
				]
			),
			packet,
			["Other income included"],
			source_text="Other income included a different disclosure.",
		)
		self.assertEqual(accepted, [])
		self.assertEqual(metadata["rejected_query_count"], 1)
		self.assertIn(
			"literal filing text", metadata["rejected_candidates"][0]["reason"]
		)

	def test_expansion_rejects_unrelated_support_reference(self) -> None:
		packet = self.paired_evidence_packet(
			[
				"Other income included a dilution gain from OpenAI Recapitalization.",
				"Other income included a separate loss disclosure.",
			]
		)
		span = "Other income included a dilution gain from OpenAI Recapitalization."
		accepted, metadata = validate_query_expansion(
			FilingQueryExpansion(
				queries=[
					FilingGroundedQuery(
						query="dilution gain from OpenAI",
						evidence_refs=["E1", "E2"],
						support_span=span,
					)
				]
			),
			packet,
			["Other income included"],
		)
		self.assertEqual(accepted, [])
		self.assertIn("every support ref", metadata["rejected_candidates"][0]["reason"])

	def test_end_to_end_expansion_is_one_packet_grounded_pass(self) -> None:
		class ExpansionClient:
			def __init__(self) -> None:
				self.calls: list[dict[str, object]] = []
				self.responses = SimpleNamespace(parse=self.parse)

			def parse(self, **kwargs: object) -> object:
				self.calls.append(kwargs)
				if len(self.calls) == 1:
					return SimpleNamespace(
						output_parsed=FilingQueryExpansion(
							queries=[
								FilingGroundedQuery(
									query="driven by demand",
									evidence_refs=["E1"],
									support_span="Revenue increased $10 million driven by demand.",
								)
							]
						)
					)
				return SimpleNamespace(
					output_parsed=FinancialInvestigationResult(
						disclosed_drivers=[],
						interpretation="The supplied passage identifies demand conditions.",
						interpretation_evidence_refs=["E1"],
						unresolved_remainder="Other components remain unresolved.",
						unresolved_remainder_evidence_refs=["E1"],
						explanation="The supplied passage leaves other components unresolved.",
						explanation_evidence_refs=["E1"],
					)
				)

		filing = FakeFiling()
		client = ExpansionClient()
		with TemporaryDirectory() as directory:
			payload, _ = investigate_finding(
				"MSFT",
				make_pnl(),
				filing,
				finding(),
				output_root=directory,
				client=client,
				run_id="expansion-run",
			)
		self.assertEqual(payload["status"], "completed")
		self.assertEqual(len(client.calls), 2)
		self.assertEqual(payload["retrieval"]["expansion"]["status"], "applied")
		self.assertEqual(
			payload["retrieval"]["expansion"]["queries"][0]["evidence_refs"],
			["E1"],
		)
		self.assertEqual(
			filing.searches,
			[
				("Revenue increased", False),
				("Revenue increased", False),
				("driven by demand", False),
			],
		)

	def test_exact_period_pair_bridge_deduplicates_evidence_and_preserves_signs(
		self,
	) -> None:
		pnl, target = self.target_pnl_and_finding()
		pair = (
			"Other income (expense), net included $6.5 billion of net gains and "
			"$4.8 billion of net losses for fiscal years 2026 and 2025, respectively."
		)
		three_year = (
			"Other income (expense), net included $6.5 billion of net gains, "
			"$4.8 billion of net losses, and $1.5 billion of net losses for fiscal "
			"years 2026, 2025, and 2024, respectively."
		)
		packet = self.paired_evidence_packet([pair, pair, pair, three_year])
		extracted = extract_period_paired_disclosures(
			pnl, target, packet, observed_unit="dollars"
		)
		self.assertEqual(extracted["status"], "extracted")
		self.assertEqual([fact["amount"] for fact in extracted["facts"]], [6.5, -4.8])
		self.assertEqual(extracted["facts"][0]["evidence_refs"], ["E1", "E2", "E3"])
		bridge = reconcile_period_pair_bridge(
			pnl, target, packet, observed_unit="dollars"
		)
		self.assertEqual(bridge["status"], "partial")
		self.assertEqual(bridge["target_line_ref"], "L01")
		self.assertEqual(bridge["observed_amount"], 15_598_000_000)
		self.assertEqual(bridge["observed_amount_comparable"], 15.598)
		self.assertEqual(bridge["known_disclosed_contribution"], 11.3)
		self.assertEqual(bridge["unresolved_difference"], 4.298)
		self.assertFalse(bridge["difference_is_reported_plug"])
		before_amount = (
			"Other income (expense), net included gains of $6.5 billion and losses "
			"of $4.8 billion for fiscal years 2026 and 2025, respectively."
		)
		before_extracted = extract_period_paired_disclosures(
			pnl,
			target,
			self.paired_evidence_packet([before_amount]),
			observed_unit="dollars",
		)
		self.assertEqual(
			[fact["amount"] for fact in before_extracted["facts"]], [6.5, -4.8]
		)

	def test_period_pair_bridge_fails_closed_for_year_or_unit_ambiguity(self) -> None:
		pnl, target = self.target_pnl_and_finding()
		swapped = (
			"Other income (expense), net included $6.5 billion of net gains and "
			"$4.8 billion of net losses for fiscal years 2025 and 2026, respectively."
		)
		packet = self.paired_evidence_packet([swapped])
		result = reconcile_period_pair_bridge(
			pnl, target, packet, observed_unit="unknown"
		)
		self.assertEqual(result["status"], "not_computable")
		self.assertIsNone(result["known_disclosed_contribution"])
		self.assertEqual(result["reason_code"], "unknown_observed_unit")
		result = reconcile_period_pair_bridge(
			pnl, target, packet, observed_unit="dollars"
		)
		self.assertEqual(result["status"], "not_computable")
		self.assertEqual(result["reason_code"], "period_mapping_mismatch")

	def test_end_to_end_preserves_packet_and_avoids_adjustment_state(self) -> None:
		pnl = make_pnl()
		context = format_analytical_pnl_for_scan(pnl)
		filing = FakeFiling()
		client = FakeResponsesClient()
		with TemporaryDirectory() as directory:
			payload, path = investigate_finding(
				"MSFT",
				pnl,
				filing,
				finding(),
				scan_metadata={"run_id": "scan1", "filing_accession": "A1"},
				scan_context=context,
				output_root=directory,
				client=client,
				run_id="run1",
			)
			self.assertEqual(payload["status"], "completed")
			self.assertEqual(filing.searches, [("Revenue increased", False)])
			evidence_path = Path(payload["retrieval"]["evidence_file"])
			self.assertIn(
				"Revenue increased $10 million driven by demand.",
				evidence_path.read_text(),
			)
			self.assertEqual(len(client.calls), 2)
			self.assertFalse(
				(
					Path(directory) / "MSFT" / "03_output" / "adjustment_history.csv"
				).exists()
			)
			self.assertTrue(path.exists())
			self.assertEqual(json.loads(path.read_text())["scan_context"], context)

	def test_bad_evidence_reference_is_rejected_before_result(self) -> None:
		packet = (
			"Ticker: MSFT\nFiling accession: A1\nSource: filing\n\n"
			"### E1\nSource: filing\nSection: note\n"
			"Locator: accession A1; line 1\n\n> exact\n"
		)
		client = Mock()
		client.responses.parse.return_value = SimpleNamespace(
			output_parsed=FinancialInvestigationResult(
				disclosed_drivers=[],
				interpretation="Unsupported claim",
				interpretation_evidence_refs=["E99"],
				unresolved_remainder="Unknown",
				unresolved_remainder_evidence_refs=["E1"],
				explanation="Unsupported claim.",
				explanation_evidence_refs=["E1"],
			)
		)
		with self.assertRaisesRegex(FilingInvestigationError, "E99"):
			run_financial_investigation(
				"MSFT",
				finding(),
				make_pnl(),
				packet,
				expected_filing_accession="A1",
				client=client,
			)

	def test_packet_accession_token_must_match_exactly(self) -> None:
		packet = self.evidence_packet().replace("accession A1", "accession A10")
		with self.assertRaisesRegex(
			FilingInvestigationError, "locator does not match packet accession"
		):
			run_financial_investigation(
				"MSFT",
				finding(),
				make_pnl(),
				packet,
				expected_filing_accession="A1",
				client=Mock(),
			)

	def test_packet_ticker_must_match_investigation_ticker(self) -> None:
		packet = self.evidence_packet().replace("Ticker: MSFT", "Ticker: OTHER")
		with self.assertRaisesRegex(
			FilingInvestigationError, "ticker does not match investigation ticker"
		):
			run_financial_investigation(
				"MSFT",
				finding(),
				make_pnl(),
				packet,
				expected_filing_accession="A1",
				client=Mock(),
			)

	def test_packet_accession_must_match_investigation_filing(self) -> None:
		with self.assertRaisesRegex(
			FilingInvestigationError,
			"accession does not match investigation filing",
		):
			run_financial_investigation(
				"MSFT",
				finding(),
				make_pnl(),
				self.evidence_packet(),
				expected_filing_accession="A10",
				client=Mock(),
			)

	def test_packet_item_source_must_match_packet_identity(self) -> None:
		packet = self.evidence_packet().replace(
			"Source: filing\nSection", "Source: other\nSection"
		)
		result = FinancialInvestigationResult(
			disclosed_drivers=[],
			unresolved_remainder="Other components remain unresolved.",
			unresolved_remainder_evidence_refs=["E1"],
			explanation="The filing leaves other components unresolved.",
			explanation_evidence_refs=["E1"],
		)
		with self.assertRaisesRegex(FilingInvestigationError, "source does not match"):
			validate_financial_investigation(result, packet)

	def test_reconciliation_preserves_signs_units_and_unquantified_remainder(
		self,
	) -> None:
		drivers = [
			DisclosedDriver(
				description="Loss",
				amount=-3.0,
				amount_unit="dollars",
				period=PERIODS[0],
				evidence_refs=["E1"],
			),
			DisclosedDriver(
				description="Unquantified driver",
				amount=None,
				evidence_refs=["E1"],
			),
		]
		result = reconcile_disclosed_amounts(
			-5.0,
			drivers,
			observed_period=PERIODS[0],
			observed_unit="dollars",
		)
		self.assertEqual(result["status"], "partial")
		self.assertEqual(result["known_disclosed_total"], -3.0)
		self.assertEqual(result["unresolved_difference"], -2.0)
		self.assertEqual(result["unquantified_driver_count"], 1)
		mixed = reconcile_disclosed_amounts(
			-5.0,
			[drivers[0].model_copy(update={"amount_unit": "usd_millions"})],
			observed_period=PERIODS[0],
			observed_unit="dollars",
		)
		self.assertEqual(mixed["status"], "not_computable")
		self.assertIsNone(mixed["unresolved_difference"])

	def test_model_cannot_supply_a_residual_amount(self) -> None:
		with self.assertRaises(ValidationError):
			FinancialInvestigationResult(
				disclosed_drivers=[],
				unresolved_remainder="A residual remains.",
				unresolved_remainder_amount=4.298,
				explanation="The filing leaves a remainder.",
			)
		with self.assertRaises(FilingInvestigationError):
			validate_financial_investigation(
				FinancialInvestigationResult(
					disclosed_drivers=[],
					unresolved_remainder="The unresolved remainder is $4.298 billion.",
					unresolved_remainder_evidence_refs=["E1"],
					explanation="The filing leaves a remainder.",
					explanation_evidence_refs=["E1"],
				),
				self.evidence_packet("The filing disclosed $4.298 billion in 2026."),
				allowed_periods={"2026-06-30 (FY)"},
			)

	def test_reconciliation_requires_one_line_and_one_period_pair(self) -> None:
		result = FinancialInvestigationResult(
			disclosed_drivers=[],
			unresolved_remainder="Other components remain unresolved.",
			unresolved_remainder_evidence_refs=["E1"],
			explanation="The filing leaves other components unresolved.",
			explanation_evidence_refs=["E1"],
		)
		three_period_result = _movement_reconciliation(make_pnl(), finding(), result)
		self.assertEqual(three_period_result["status"], "not_computable")
		self.assertIsNone(three_period_result["observed_amount"])

		two_period_pnl = prepare_pnl(
			pd.DataFrame(
				{
					"concept": ["Revenue"],
					"label": ["Revenue"],
					"standard_concept": ["Revenue"],
					PERIODS[0]: [110.0],
					PERIODS[1]: [100.0],
				}
			),
			years=2,
		)
		two_period_result = _movement_reconciliation(two_period_pnl, finding(), result)
		self.assertEqual(two_period_result["observed_amount"], 10.0)
		self.assertEqual(two_period_result["observed_period"], PERIODS[0])

	def test_disclosed_claims_must_match_supplied_period_and_evidence_unit(
		self,
	) -> None:
		bad_period = FinancialInvestigationResult(
			disclosed_drivers=[
				DisclosedDriver(
					description="Unsupported period",
					amount=5.0,
					amount_unit="usd_millions",
					period="2027-06-30 (FY)",
					evidence_refs=["E1"],
				)
			],
			unresolved_remainder="Other components remain unresolved.",
			unresolved_remainder_evidence_refs=["E1"],
			explanation="The filing leaves other components unresolved.",
			explanation_evidence_refs=["E1"],
		)
		validated_period = validate_financial_investigation(
			bad_period,
			self.evidence_packet(),
			allowed_periods={"2026-06-30 (FY)"},
		)
		self.assertIsNone(validated_period.disclosed_drivers[0].amount)
		self.assertIsNone(validated_period.disclosed_drivers[0].period)
		self.assertEqual(validated_period.disclosed_drivers[0].amount_unit, "unknown")

		bad_unit = bad_period.model_copy(
			deep=True,
			update={
				"disclosed_drivers": [
					bad_period.disclosed_drivers[0].model_copy(
						update={
							"period": "2026-06-30 (FY)",
							"amount_unit": "usd_billions",
						}
					)
				]
			},
		)
		validated_unit = validate_financial_investigation(
			bad_unit,
			self.evidence_packet(),
			allowed_periods={"2026-06-30 (FY)"},
		)
		self.assertIsNone(validated_unit.disclosed_drivers[0].amount)
		self.assertEqual(validated_unit.disclosed_drivers[0].amount_unit, "unknown")

	def test_quantified_driver_requires_one_literal_support_span(self) -> None:
		result = FinancialInvestigationResult(
			disclosed_drivers=[
				DisclosedDriver(
					description="A disclosed driver.",
					amount=5.0,
					amount_unit="usd_millions",
					period=PERIODS[0],
					evidence_span="5 million in 2026",
					evidence_refs=["E1"],
				)
			],
			unresolved_remainder="Other components remain unresolved.",
			unresolved_remainder_evidence_refs=["E1"],
			explanation="The filing discloses a driver.",
			explanation_evidence_refs=["E1"],
		)
		validated = validate_financial_investigation(
			result,
			self.evidence_packet("The filing disclosed 5 million in 2026."),
			allowed_periods={PERIODS[0]},
		)
		driver = validated.disclosed_drivers[0]
		self.assertEqual(driver.amount, 5.0)
		self.assertEqual(driver.evidence_span, "5 million in 2026")

	def test_year_token_cannot_be_accepted_as_driver_amount(self) -> None:
		driver = DisclosedDriver(
			description="A disclosed driver.",
			amount=2026.0,
			amount_unit="usd_millions",
			period=PERIODS[0],
			evidence_span="5 million in 2026",
			evidence_refs=["E1"],
		)
		result = FinancialInvestigationResult(
			disclosed_drivers=[driver],
			unresolved_remainder="Other components remain unresolved.",
			unresolved_remainder_evidence_refs=["E1"],
			explanation="The filing discloses a driver.",
			explanation_evidence_refs=["E1"],
		)
		validated = validate_financial_investigation(
			result,
			self.evidence_packet("The filing disclosed 5 million in 2026."),
			allowed_periods={PERIODS[0]},
		)
		self.assertIsNone(validated.disclosed_drivers[0].amount)
		self.assertEqual(validated.disclosed_drivers[0].amount_unit, "unknown")
		self.assertIsNone(validated.disclosed_drivers[0].period)
		self.assertIsNone(validated.disclosed_drivers[0].evidence_span)
		self.assertEqual(validated.disclosed_drivers[0].amount_basis, "unquantified")

	def test_respectively_span_downgrades_cross_year_swap(self) -> None:
		excerpt = (
			"Other income included 6.5 billion and 4.8 billion for fiscal years "
			"2026 and 2025, respectively."
		)
		result = FinancialInvestigationResult(
			disclosed_drivers=[
				DisclosedDriver(
					description="A disclosed driver.",
					amount=4.8,
					amount_unit="usd_billions",
					period=PERIODS[0],
					evidence_span=excerpt,
					evidence_refs=["E1"],
				)
			],
			unresolved_remainder="Other components remain unresolved.",
			unresolved_remainder_evidence_refs=["E1"],
			explanation="The filing discloses the driver.",
			explanation_evidence_refs=["E1"],
		)
		validated = validate_financial_investigation(
			result,
			self.evidence_packet(excerpt),
			allowed_periods={PERIODS[0]},
		)
		self.assertIsNone(validated.disclosed_drivers[0].amount)
		self.assertIsNone(validated.disclosed_drivers[0].period)

	def test_sign_inversion_is_downgraded(self) -> None:
		excerpt = "The filing disclosed (5 million) in 2026."
		result = FinancialInvestigationResult(
			disclosed_drivers=[
				DisclosedDriver(
					description="A disclosed driver.",
					amount=5.0,
					amount_unit="usd_millions",
					period=PERIODS[0],
					evidence_span=excerpt,
					evidence_refs=["E1"],
				)
			],
			unresolved_remainder="Other components remain unresolved.",
			unresolved_remainder_evidence_refs=["E1"],
			explanation="The filing discloses the driver.",
			explanation_evidence_refs=["E1"],
		)
		validated = validate_financial_investigation(
			result,
			self.evidence_packet(excerpt),
			allowed_periods={PERIODS[0]},
		)
		self.assertIsNone(validated.disclosed_drivers[0].amount)
		self.assertEqual(validated.disclosed_drivers[0].amount_unit, "unknown")
		self.assertIsNone(validated.disclosed_drivers[0].period)
		self.assertIsNone(validated.disclosed_drivers[0].evidence_span)

	def test_unquantified_effect_is_derived_from_cited_loss_semantics(self) -> None:
		result = FinancialInvestigationResult(
			disclosed_drivers=[
				DisclosedDriver(
					description="Loss",
					amount=None,
					effect="increased_line",
					evidence_refs=["E1"],
				)
			],
			unresolved_remainder="Other components remain unresolved.",
			unresolved_remainder_evidence_refs=["E1"],
			explanation="The filing leaves other components unresolved.",
			explanation_evidence_refs=["E1"],
		)
		validated = validate_financial_investigation(
			result,
			self.evidence_packet("The filing disclosed a net loss."),
		)
		self.assertEqual(validated.disclosed_drivers[0].effect, "decreased_line")

	def test_unquantified_effect_downgrades_mixed_cited_polarity(self) -> None:
		result = FinancialInvestigationResult(
			disclosed_drivers=[
				DisclosedDriver(
					description="Gain",
					amount=None,
					effect="increased_line",
					evidence_refs=["E1"],
				)
			],
			unresolved_remainder="Other components remain unresolved.",
			unresolved_remainder_evidence_refs=["E1"],
			explanation="The filing leaves other components unresolved.",
			explanation_evidence_refs=["E1"],
		)
		validated = validate_financial_investigation(
			result,
			self.evidence_packet("The filing disclosed a gain and a loss."),
		)
		self.assertEqual(validated.disclosed_drivers[0].effect, "unknown")

	def test_unsupported_company_specific_narrative_fails_closed(self) -> None:
		result = FinancialInvestigationResult(
			disclosed_drivers=[],
			interpretation="A quantum teleportation transaction drove the movement.",
			interpretation_evidence_refs=["E1"],
			unresolved_remainder="Other components remain unresolved.",
			unresolved_remainder_evidence_refs=["E1"],
			explanation="The filing leaves other components unresolved.",
			explanation_evidence_refs=["E1"],
		)
		with self.assertRaisesRegex(
			FilingInvestigationError, "unsupported causal claim"
		):
			validate_financial_investigation(
				result,
				self.evidence_packet("The filing disclosed an investment gain."),
			)

	def test_mixed_supported_and_invented_causal_tokens_fail_closed(self) -> None:
		result = FinancialInvestigationResult(
			disclosed_drivers=[],
			interpretation="The investment gain drove demand and imaginary pressure.",
			interpretation_evidence_refs=["E1"],
			unresolved_remainder="Other components remain unresolved.",
			unresolved_remainder_evidence_refs=["E1"],
			explanation="The filing leaves other components unresolved.",
			explanation_evidence_refs=["E1"],
		)
		with self.assertRaisesRegex(
			FilingInvestigationError, "unsupported causal claim"
		):
			validate_financial_investigation(
				result,
				self.evidence_packet(
					"The filing disclosed an investment gain caused by demand."
				),
			)

	def test_unsupported_named_entity_fails_closed(self) -> None:
		result = FinancialInvestigationResult(
			disclosed_drivers=[],
			interpretation="The Azure product is disclosed.",
			interpretation_evidence_refs=["E1"],
			unresolved_remainder="Other components remain unresolved.",
			unresolved_remainder_evidence_refs=["E1"],
			explanation="The filing leaves other components unresolved.",
			explanation_evidence_refs=["E1"],
		)
		with self.assertRaisesRegex(
			FilingInvestigationError, "unsupported named entity"
		):
			validate_financial_investigation(
				result,
				self.evidence_packet("The filing disclosed an investment gain."),
			)

	def test_neutral_analytical_words_need_not_appear_in_evidence(self) -> None:
		result = FinancialInvestigationResult(
			disclosed_drivers=[
				DisclosedDriver(
					description="A disclosure identifies a driver component.",
					evidence_refs=["E1"],
				)
			],
			interpretation="The disclosure partially explains the movement.",
			interpretation_evidence_refs=["E1"],
			unresolved_remainder="A component remains unresolved.",
			unresolved_remainder_evidence_refs=["E1"],
			explanation="The driver is partially unresolved.",
			explanation_evidence_refs=["E1"],
		)
		validated = validate_financial_investigation(
			result,
			self.evidence_packet("The filing reports a gain."),
		)
		self.assertEqual(
			validated.disclosed_drivers[0].description,
			"A disclosure identifies a driver component.",
		)
		self.assertEqual(
			validated.interpretation,
			"The disclosure partially explains the movement.",
		)

	def test_unrelated_adjacent_year_downgrades_amount_period_claim(self) -> None:
		support_span = (
			"The company disclosed 5 million for a prior period. "
			"Results in fiscal 2026 improved."
		)
		self.assertFalse(
			_driver_claim_supported(5.0, "usd_millions", PERIODS[0], support_span)
		)

	def test_source_loss_requires_negative_driver_sign(self) -> None:
		support_span = "The filing disclosed 5 million loss in 2026."
		self.assertFalse(
			_driver_claim_supported(5.0, "usd_millions", PERIODS[0], support_span)
		)
		self.assertTrue(
			_driver_claim_supported(-5.0, "usd_millions", PERIODS[0], support_span)
		)

	def test_local_gain_and_loss_signs_are_preserved(self) -> None:
		self.assertTrue(
			_driver_claim_supported(
				5.0,
				"usd_millions",
				PERIODS[0],
				"The filing disclosed 5 million gain in 2026.",
			)
		)
		self.assertTrue(
			_driver_claim_supported(
				-5.0,
				"usd_millions",
				PERIODS[0],
				"The filing disclosed 5 million loss in 2026.",
			)
		)

	def test_prose_residual_arithmetic_is_rejected_in_every_result_field(self) -> None:
		for field in ("interpretation", "unresolved_remainder", "explanation"):
			for residual_text in (
				"The residual is 5 million.",
				"The residual is 5.",
				"The residual is five million.",
			):
				values: dict[str, object] = {
					"disclosed_drivers": [],
					"interpretation": "The filing identifies a driver.",
					"interpretation_evidence_refs": ["E1"],
					"unresolved_remainder": "Other components remain unresolved.",
					"unresolved_remainder_evidence_refs": ["E1"],
					"explanation": "The filing leaves other components unresolved.",
					"explanation_evidence_refs": ["E1"],
				}
				values[field] = residual_text
				values[f"{field}_evidence_refs"] = ["E1"]
				with self.assertRaisesRegex(FilingInvestigationError, "numeric-free"):
					validate_financial_investigation(
						FinancialInvestigationResult.model_validate(values),
						self.evidence_packet("The filing disclosed 5 million in 2026."),
						allowed_periods={PERIODS[0]},
					)

	def test_prose_arithmetic_is_rejected_outside_remainder_wording(self) -> None:
		result = FinancialInvestigationResult(
			disclosed_drivers=[],
			unresolved_remainder="Other components remain unresolved.",
			unresolved_remainder_evidence_refs=["E1"],
			explanation="The movement is 5 million - 2 million.",
			explanation_evidence_refs=["E1"],
		)
		with self.assertRaisesRegex(FilingInvestigationError, "numeric-free"):
			validate_financial_investigation(
				result,
				self.evidence_packet("The filing disclosed 5 million and 2 million."),
				allowed_periods={PERIODS[0]},
			)

	def test_narrative_amount_is_rejected_even_when_evidence_backed(self) -> None:
		result = FinancialInvestigationResult(
			disclosed_drivers=[],
			unresolved_remainder="Other components remain unresolved.",
			unresolved_remainder_evidence_refs=["E1"],
			explanation="The filing disclosed 5 million in 2026.",
			explanation_evidence_refs=["E1"],
		)
		with self.assertRaisesRegex(FilingInvestigationError, "numeric-free"):
			validate_financial_investigation(
				result,
				self.evidence_packet("The filing disclosed 5 million in 2026."),
				allowed_periods={PERIODS[0]},
			)

	def test_numeric_token_boundary_rejects_5_inside_15(self) -> None:
		result = FinancialInvestigationResult(
			disclosed_drivers=[],
			unresolved_remainder="Other components remain unresolved.",
			unresolved_remainder_evidence_refs=["E1"],
			explanation="The filing disclosed 5.",
			explanation_evidence_refs=["E1"],
		)
		with self.assertRaisesRegex(FilingInvestigationError, "numeric-free"):
			validate_financial_investigation(
				result,
				self.evidence_packet("The filing disclosed 15 million in 2026."),
				allowed_periods={PERIODS[0]},
			)

	def test_narrative_spelled_amount_is_rejected_even_when_evidence_backed(
		self,
	) -> None:
		result = FinancialInvestigationResult(
			disclosed_drivers=[],
			unresolved_remainder="Other components remain unresolved.",
			unresolved_remainder_evidence_refs=["E1"],
			explanation="The filing disclosed five million in 2026.",
			explanation_evidence_refs=["E1"],
		)
		with self.assertRaisesRegex(FilingInvestigationError, "numeric-free"):
			validate_financial_investigation(
				result,
				self.evidence_packet("The filing disclosed five million in 2026."),
				allowed_periods={PERIODS[0]},
			)

	def test_a4_numeric_variants_are_rejected_in_every_narrative_field(self) -> None:
		variants = (
			"The movement is 5M + 2M.",
			"The movement is 5mn.",
			"The movement is $5bn.",
			"The movement is FY26.",
			"The movement is five M.",
			"The movement is five million less two million.",
			"The difference between five million and two million explains the movement.",
			"Five million divided by two million is the implied amount.",
			"Five plus two explains the movement.",
			"The remaining amount is five million.",
			"The leftover is $5 million.",
			"The unresolved part is 5 million.",
			"The residual is five.",
		)
		for field in (
			"description",
			"interpretation",
			"unresolved_remainder",
			"explanation",
		):
			for text in variants:
				values: dict[str, object] = {
					"disclosed_drivers": [],
					"interpretation": "The filing identifies a driver.",
					"interpretation_evidence_refs": ["E1"],
					"unresolved_remainder": "Other components remain unresolved.",
					"unresolved_remainder_evidence_refs": ["E1"],
					"explanation": "The filing leaves other components unresolved.",
					"explanation_evidence_refs": ["E1"],
				}
				if field == "description":
					values["disclosed_drivers"] = [
						{
							"description": text,
							"evidence_refs": ["E1"],
						}
					]
				else:
					values[field] = text
					values[f"{field}_evidence_refs"] = ["E1"]
				with self.assertRaisesRegex(FilingInvestigationError, "numeric-free"):
					validate_financial_investigation(
						FinancialInvestigationResult.model_validate(values),
						self.evidence_packet(
							"The filing disclosed 5 million and 2 million in 2026."
						),
						allowed_periods={PERIODS[0]},
					)

	def test_unquantified_driver_clears_all_quantitative_metadata(self) -> None:
		driver = DisclosedDriver(
			description="Demand conditions",
			amount=None,
			amount_unit="usd_millions",
			period=PERIODS[0],
			evidence_span="5 million in 2026",
			evidence_refs=["E1"],
		)
		result = FinancialInvestigationResult(
			disclosed_drivers=[driver],
			unresolved_remainder="Other components remain unresolved.",
			unresolved_remainder_evidence_refs=["E1"],
			explanation="The filing identifies demand conditions.",
			explanation_evidence_refs=["E1"],
		)
		validated = validate_financial_investigation(
			result,
			self.evidence_packet("The filing disclosed demand conditions in 2026."),
			allowed_periods={PERIODS[0]},
		)
		validated_driver = validated.disclosed_drivers[0]
		self.assertEqual(validated_driver.description, "Demand conditions")
		self.assertEqual(validated_driver.evidence_refs, ["E1"])
		self.assertIsNone(validated_driver.amount)
		self.assertEqual(validated_driver.amount_unit, "unknown")
		self.assertIsNone(validated_driver.period)
		self.assertIsNone(validated_driver.evidence_span)
		self.assertEqual(validated_driver.amount_basis, "unquantified")

	def test_quantified_structured_claim_and_qualitative_prose_survive(self) -> None:
		excerpt = (
			"Demand conditions increased the reported line. The filing disclosed "
			"5 million gain in 2026. The filing attributes the movement to demand "
			"conditions. Other components remain unresolved. Demand conditions are "
			"disclosed, while other components remain unresolved."
		)
		result = FinancialInvestigationResult(
			disclosed_drivers=[
				DisclosedDriver(
					description="Demand conditions increased the reported line.",
					amount=5.0,
					amount_unit="usd_millions",
					period=PERIODS[0],
					evidence_span=excerpt,
					evidence_refs=["E1"],
				)
			],
			interpretation="The filing attributes the movement to demand conditions.",
			interpretation_evidence_refs=["E1"],
			unresolved_remainder="Other components remain unresolved.",
			unresolved_remainder_evidence_refs=["E1"],
			explanation="Demand conditions are disclosed, while other components remain unresolved.",
			explanation_evidence_refs=["E1"],
		)
		validated = validate_financial_investigation(
			result,
			self.evidence_packet(excerpt),
			allowed_periods={PERIODS[0]},
		)
		validated_driver = validated.disclosed_drivers[0]
		self.assertEqual(validated_driver.amount, 5.0)
		self.assertEqual(validated_driver.amount_unit, "usd_millions")
		self.assertEqual(validated_driver.period, PERIODS[0])
		self.assertEqual(validated_driver.evidence_span, excerpt)
		self.assertEqual(
			validated_driver.description, result.disclosed_drivers[0].description
		)
		self.assertEqual(validated.explanation, result.explanation)

	def test_summary_renders_structured_period_deterministically(self) -> None:
		result = FinancialInvestigationResult(
			disclosed_drivers=[
				DisclosedDriver(
					description="Demand conditions",
					amount=5.0,
					amount_unit="usd_millions",
					period=PERIODS[0],
					evidence_refs=["E1"],
				)
			],
			unresolved_remainder="Other components remain unresolved.",
			unresolved_remainder_evidence_refs=["E1"],
			explanation="Demand conditions are disclosed.",
			explanation_evidence_refs=["E1"],
		)
		summary = render_finding_investigation_summary(result)
		self.assertIn("5 usd_millions for 2026-06-30 (FY)", summary)

	def test_explanation_requires_validated_evidence_references(self) -> None:
		result = FinancialInvestigationResult(
			disclosed_drivers=[],
			unresolved_remainder="Other components remain unresolved.",
			unresolved_remainder_evidence_refs=["E1"],
			explanation="Unsupported company-specific explanation.",
		)
		with self.assertRaisesRegex(FilingInvestigationError, "explanation requires"):
			validate_financial_investigation(
				result,
				self.evidence_packet(),
				allowed_periods={"2026-06-30 (FY)"},
			)

	def test_duplicate_api_aliases_are_removed(self) -> None:
		import smrik_fund.ingestion.filing_investigation as investigation

		for name in (
			"FindingInvestigationError",
			"FilingSearchPlan",
			"SearchPlan",
			"FinancialInvestigation",
			"InvestigationResult",
			"run_finding_investigation",
			"run_filing_investigation",
			"run_investigation",
			"load_scan_artifact",
			"extract_quantified_disclosures",
			"FILING_SEARCH_PLAN_PROMPT",
		):
			self.assertFalse(hasattr(investigation, name), name)

	def test_segment_ref_filing_investigation_fails_closed_before_pnl_indexing(
		self,
	) -> None:
		segment_finding = finding().model_copy(update={"affected_line_refs": ["S01"]})
		with self.assertRaisesRegex(
			FilingInvestigationError, "S-ref filing investigation is unsupported"
		):
			investigate_finding(
				"MSFT", make_pnl(), FakeFiling(), segment_finding, client=Mock()
			)


class SavedScanTests(TestCase):
	def test_enriched_saved_scan_reconstructs_persisted_segment_context(self) -> None:
		pnl = make_pnl()
		segments, checks = make_segments()
		context = format_analytical_pnl_for_scan(pnl, segments)
		with TemporaryDirectory() as directory:
			root = Path(directory)
			save_analytical_pnl("MSFT", pnl, root)
			save_segment_analytics("MSFT", segments, root)
			save_segment_reconciliation("MSFT", checks, root)
			loaded_segments = load_segment_analytics("MSFT", root)
			path = save_analytical_scan(
				"MSFT",
				AnalyticalScanResult(findings=[finding()]),
				{"ticker": "MSFT", "filing_accession": "A1", "run_id": "s1"},
				context,
				root,
			)
			loaded, selected, loaded_context, _metadata = load_saved_scan(
				path, "MSFT", pnl, loaded_segments
			)
			self.assertEqual(selected.rank, 1)
			self.assertEqual(loaded_context, context)
			self.assertEqual(len(loaded.findings), 1)
			payload, _artifact = investigate_finding(
				"MSFT",
				pnl,
				FakeFiling(),
				selected,
				scan_metadata={"filing_accession": "A1"},
				scan_context=loaded_context,
				segments=loaded_segments,
				output_root=root,
				client=FakeResponsesClient(),
				run_id="investigation1",
			)
			self.assertEqual(payload["status"], "completed")

	def test_saved_scan_context_and_accession_are_checked(self) -> None:
		pnl = make_pnl()
		context = format_analytical_pnl_for_scan(pnl)
		with TemporaryDirectory() as directory:
			root = Path(directory)
			save_analytical_pnl("MSFT", pnl, root)
			path = save_analytical_scan(
				"MSFT",
				AnalyticalScanResult(findings=[finding()]),
				{"ticker": "MSFT", "filing_accession": "A1", "run_id": "s1"},
				context,
				root,
			)
			loaded, selected, loaded_context, metadata = load_saved_scan(
				path, "MSFT", pnl
			)
			self.assertEqual(selected.rank, 1)
			self.assertEqual(loaded_context, context)
			self.assertEqual(metadata["filing_accession"], "A1")
			self.assertEqual(len(loaded.findings), 1)
			with self.assertRaises(FilingInvestigationError):
				load_saved_scan(
					path,
					"MSFT",
					pnl.assign(label=["Changed", "Other income (expense), net"]),
				)


class CliIsolationTests(TestCase):
	def test_investigate_command_does_not_enter_adjustment_pipeline(self) -> None:
		pnl = make_pnl()
		context = format_analytical_pnl_for_scan(pnl)
		fake_filing = FakeFiling()
		with TemporaryDirectory() as directory:
			root = Path(directory)
			save_analytical_pnl("MSFT", pnl, root)
			scan_path = save_analytical_scan(
				"MSFT",
				AnalyticalScanResult(findings=[finding()]),
				{"ticker": "MSFT", "filing_accession": "A1", "run_id": "s1"},
				context,
				root,
			)
			fake_payload = {
				"status": "completed",
				"finding": finding().model_dump(mode="json"),
			}
			fake_artifact = root / "artifact.json"
			fake_artifact.write_text(json.dumps(fake_payload))
			with (
				patch("smrik_fund.main.get_latest_filing", return_value=fake_filing),
				patch(
					"smrik_fund.main.investigate_finding",
					return_value=(fake_payload, fake_artifact),
				),
			):
				result = CliRunner().invoke(
					app,
					[
						"investigate",
						"MSFT",
						"--scan-file",
						str(scan_path),
						"--output-root",
						str(root),
					],
				)
			self.assertEqual(result.exit_code, 0, result.output)
			self.assertIn("Observed movement", result.output)
			self.assertFalse(
				(root / "MSFT" / "03_output" / "adjustment_history.csv").exists()
			)
