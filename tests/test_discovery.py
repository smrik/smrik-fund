from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import pandas as pd

from smrik_fund.ingestion.adjustment_analysis import AnalystCandidate, AnalystResult
from smrik_fund.ingestion.discovery import (
	DiscoveryResult,
	DiscoveryTopic,
	build_discovery_context,
	deduplicate_topics,
	run_discovery,
)
from smrik_fund.ingestion.filing import retrieve_filing_evidence
from smrik_fund.ingestion.reviewer import ReviewResult
from smrik_fund.ingestion.statements import prepare_pnl
from smrik_fund.main import _run_adjustment_analysis


def make_pnl() -> pd.DataFrame:
	return prepare_pnl(
		pd.DataFrame(
			{
				"concept": [
					"us-gaap_Revenue",
					"us-gaap_CostOfGoodsAndServicesSold",
					"us-gaap_GrossProfit",
					"us-gaap_ResearchAndDevelopmentExpenses",
					"us-gaap_OperatingIncomeLoss",
				],
				"label": [
					"Revenue",
					"Cost of revenue",
					"Gross profit",
					"Research and development",
					"Operating income",
				],
				"standard_concept": [
					"Revenue",
					"CostOfGoodsAndServicesSold",
					"GrossProfit",
					"ResearchAndDevelopmentExpenses",
					"OperatingIncomeLoss",
				],
				"2026-06-30 (FY)": [1000.0, 400.0, 600.0, 100.0, 500.0],
				"2025-06-30 (FY)": [900.0, 350.0, 550.0, 90.0, 460.0],
			}
		),
		years=2,
	)


class Filing:
	accession_no = "A1"
	form = "10-K"
	filing_date = "2026-07-29"
	report_date = "2026-06-30"
	primary_document = "sample.htm"
	text_url = "https://example.test/sample.txt"

	def __init__(self) -> None:
		self.searches: list[str] = []

	def text(self) -> str:
		return "Revenue grew.\nResearch and development costs rose.\n"

	def search(self, query: str, regex: bool = False) -> object:
		self.searches.append(query)
		assert regex is False
		return SimpleNamespace(sections=[SimpleNamespace(loc=7, doc=self.text())])


class DiscoveryTests(TestCase):
	def test_context_and_discovery_are_bounded_and_single_call(self) -> None:
		filing = Filing()
		context = build_discovery_context(make_pnl(), filing, max_passages=2)
		client = Mock()
		client.responses.parse.return_value = SimpleNamespace(
			output_parsed=DiscoveryResult(
				topics=[
					DiscoveryTopic(
						name="R and D review",
						likely_target_line="Research and development",
						queries=["Research and development costs"],
						rationale="The source discusses a change.",
					)
				]
			)
		)

		result, _ = run_discovery(
			"MSFT", make_pnl(), context, client=client, run_id="r1"
		)

		client.responses.parse.assert_called_once()
		self.assertEqual(len(result.topics), 1)
		payload = json.loads(client.responses.parse.call_args.kwargs["input"][1]["content"])
		self.assertIn("Research and development costs rose.", json.dumps(payload))
		self.assertNotIn("E1", client.responses.parse.call_args.kwargs["input"][0]["content"])
		self.assertIsInstance(context["passages"], list)

	def test_topic_dedupe_is_first_occurrence_only(self) -> None:
		topic = DiscoveryTopic(
			name=" R&D ",
			likely_target_line="Research and development",
			queries=[" research costs "],
			rationale="review",
		)
		retained, records = deduplicate_topics([topic, topic])

		self.assertEqual(len(retained), 1)
		self.assertEqual([record["status"] for record in records], ["retained", "duplicate"])
		self.assertEqual(records[1]["collapsed_into"], 0)

	def test_retrieval_uses_only_discovered_query_and_exact_excerpt(self) -> None:
		filing = Filing()
		packet, metadata = retrieve_filing_evidence(
			filing,
			"MSFT",
			"R and D review",
			["Research and development costs rose"],
		)

		self.assertEqual(filing.searches, ["Research and development costs rose"])
		self.assertIn("> Research and development costs rose.", packet)
		self.assertEqual(metadata["queries"], ["Research and development costs rose"])
		self.assertEqual(metadata["evidence_item_count"], 1)

	def test_literal_query_metacharacters_are_not_regex_and_search_once(self) -> None:
		class LiteralFiling(Filing):
			text_value = "Header\nA.B [x] appears literally.\n"

			def text(self) -> str:
				return self.text_value

		filing = LiteralFiling()
		packet, _ = retrieve_filing_evidence(
			filing, "MSFT", "literal", ["A.B [x]"],
		)
		self.assertEqual(filing.searches, ["A.B [x]"])
		self.assertIn("> A.B [x] appears literally.", packet)

	def test_empty_resolution_keeps_history_unchanged_and_records_topic(self) -> None:
		filing = Filing()
		discovery = DiscoveryResult(
			topics=[
				DiscoveryTopic(
					name="R and D review",
					queries=["Research and development costs rose"],
					rationale="review",
				)
			]
		)
		with TemporaryDirectory() as temporary_directory:
			pnl = make_pnl()
			pnl.attrs["edgar_filing"] = filing
			with (
				patch("smrik_fund.main.run_discovery", return_value=(discovery, {"run_id": "r1"})),
				patch(
					"smrik_fund.main.run_analyst",
					return_value=(AnalystResult(candidates=[]), {"run_id": "r1", "model": "m"}),
				),
			):
				manifest_path = _run_adjustment_analysis(
					"MSFT",
					pnl,
					"m",
					"high",
					output_root=temporary_directory,
					filing=filing,
				)

			manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
			self.assertEqual(len(manifest["topics"]), 1)
			self.assertEqual(manifest["topics"][0]["status"], "analyst_empty")
			self.assertTrue(manifest["reported_equals_adjusted"])
			self.assertFalse(
				(Path(temporary_directory) / "MSFT" / "03_output" / "adjustment_history.csv").exists()
			)

	def test_zero_topic_discovery_persists_artifact(self) -> None:
		filing = Filing()
		discovery = DiscoveryResult(topics=[])
		with TemporaryDirectory() as temporary_directory:
			pnl = make_pnl()
			pnl.attrs["edgar_filing"] = filing
			with (
				patch("smrik_fund.main.run_discovery", return_value=(discovery, {"run_id": "r1"})) as discover,
				patch("smrik_fund.main.run_analyst") as analyst,
			):
				manifest_path = _run_adjustment_analysis(
					"MSFT", pnl, "m", "high", output_root=temporary_directory, filing=filing
				)

			manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
			discovery_path = Path(manifest["discovery_path"])
			saved = json.loads(discovery_path.read_text(encoding="utf-8"))
			self.assertEqual(discover.call_count, 1)
			analyst.assert_not_called()
			self.assertEqual(saved["result"]["topics"], [])
			self.assertEqual(saved["topics"], [])

	def test_candidate_limit_closes_topic_before_reviewer_fanout(self) -> None:
		filing = Filing()
		discovery = DiscoveryResult(
			topics=[
				DiscoveryTopic(
					name="R and D review",
					queries=["Research and development costs rose"],
					rationale="review",
				)
			]
		)
		candidates = [
			AnalystCandidate(
				target_line="Research and development",
				period="2026-06-30 (FY)",
				amount_basis="unknown",
				reason=f"Candidate {number}",
				evidence_refs=["E1"],
			)
			for number in range(4)
		]
		with TemporaryDirectory() as temporary_directory:
			pnl = make_pnl()
			pnl.attrs["edgar_filing"] = filing
			with (
				patch("smrik_fund.main.run_discovery", return_value=(discovery, {"run_id": "r1"})),
				patch(
					"smrik_fund.main.run_analyst",
					return_value=(AnalystResult(candidates=candidates), {"run_id": "r1", "model": "m"}),
				),
				patch("smrik_fund.main.run_reviewer") as reviewer,
			):
				manifest_path = _run_adjustment_analysis(
					"MSFT", pnl, "m", "high", output_root=temporary_directory, filing=filing
				)

			manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
			topic = manifest["topics"][0]
			self.assertEqual(topic["status"], "candidate_limit_exceeded")
			self.assertEqual(topic["candidate_count"], 4)
			self.assertEqual(topic["candidate_limit"], 3)
			self.assertIn("per-topic limit is 3", topic["error"])
			reviewer.assert_not_called()
			self.assertFalse(
				(Path(temporary_directory) / "MSFT" / "03_output" / "adjustment_history.csv").exists()
			)

	def test_discovered_packet_resolves_once_then_null_candidate_stays_unapplied(self) -> None:
		class XboxFiling(Filing):
			text_value = (
				"Research and development expenses increased driven by impairment and "
				"other related expenses in our XBOX business.\n"
			)

			def text(self) -> str:
				return self.text_value

		filing = XboxFiling()
		discovery = DiscoveryResult(
			topics=[
				DiscoveryTopic(
					name="XBOX impairment expenses",
					likely_target_line="Research and development",
					queries=["impairment and other related expenses in our XBOX business"],
					rationale="review",
				)
			]
		)
		candidate = AnalystCandidate(
			target_line="Research and development",
			period="2026-06-30 (FY)",
			item_amount=None,
			item_effect_on_line=None,
			amount_basis="unknown",
			reason="The packet does not quantify the item.",
			evidence_refs=["E1"],
		)
		review = ReviewResult(
			verdict="revise",
			evidence_strength="medium",
			amount_basis="unknown",
			judgment_level="high",
			calculation_valid=None,
			target_valid=True,
			period_valid=True,
			concerns=["Amount is not disclosed."],
		)
		with TemporaryDirectory() as temporary_directory:
			pnl = make_pnl()
			pnl.attrs["edgar_filing"] = filing
			with (
				patch("smrik_fund.main.run_discovery", return_value=(discovery, {"run_id": "r1"})) as discover,
				patch(
					"smrik_fund.main.run_analyst",
					return_value=(AnalystResult(candidates=[candidate]), {"run_id": "r1", "model": "m"}),
				) as analyst,
				patch(
					"smrik_fund.main.run_reviewer",
					return_value=(review, {"run_id": "r1", "model": "m"}),
				) as reviewer,
			):
				manifest_path = _run_adjustment_analysis(
					"MSFT", pnl, "m", "high", output_root=temporary_directory, filing=filing
				)
				manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
				history_exists = (
					Path(temporary_directory) / "MSFT" / "03_output" / "adjustment_history.csv"
				).exists()
		topic = manifest["topics"][0]
		self.assertEqual(discover.call_count, 1)
		self.assertEqual(analyst.call_count, 1)
		self.assertEqual(reviewer.call_count, 1)
		self.assertEqual(topic["status"], "human_review")
		self.assertEqual(topic["candidates"][0]["final_status"], "human_review")
		self.assertEqual(topic["candidates"][0]["application_status"], "not_applied")
		self.assertTrue(manifest["reported_equals_adjusted"])
		self.assertFalse(history_exists)
