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

from smrik_fund.ingestion.adjustment_analysis import (
	AdjustmentAnalysisError,
	AnalystCandidate,
	AnalystResult,
	run_analyst,
	save_analyst_result,
)
from smrik_fund.ingestion.adjustments import (
	apply_adjustments,
	resolve_current_adjustments,
)
from smrik_fund.ingestion.discovery import DiscoveryResult, DiscoveryTopic
from smrik_fund.ingestion.reviewer import ReviewResult
from smrik_fund.ingestion.risk_gate import RiskGateConditions
from smrik_fund.ingestion.statements import prepare_pnl
from smrik_fund.main import (
	_candidate_identity,
	_candidate_state,
	_canonical_json,
	_gate_conditions,
	_history_identity_lookup,
	_render_normalization_summary,
	_run_adjustment_analysis,
	app,
	build_normalization_summary,
)

PERIOD = "2025-06-30 (FY)"


def make_pnl() -> pd.DataFrame:
	return pd.DataFrame(
		{
			"concept": [
				"us-gaap_Revenue",
				"us-gaap_CostOfGoodsAndServicesSold",
				"us-gaap_GrossProfit",
				"us-gaap_SellingGeneralAndAdminExpense",
				"us-gaap_SellingGeneralAndAdminExpense",
				"us-gaap_OperatingIncomeLoss",
			],
			"label": [
				"Revenue",
				"Cost of revenue",
				"Gross profit",
				"Go-to-market",
				"Corporate",
				"Operating income",
			],
			"standard_concept": [
				"Revenue",
				"CostOfGoodsAndServicesSold",
				"GrossProfit",
				"SellingGeneralAndAdminExpenses",
				"SellingGeneralAndAdminExpenses",
				"OperatingIncomeLoss",
			],
			"parent_concept": [
				None,
				"us-gaap_GrossProfit",
				"us-gaap_OperatingIncomeLoss",
				"us-gaap_OperatingIncomeLoss",
				"us-gaap_OperatingIncomeLoss",
				None,
			],
			PERIOD: [1000.0, 600.0, 400.0, 100.0, 100.0, 200.0],
		}
	)


def make_integrated_pnl() -> pd.DataFrame:
	period = "2025-06-30 (FY)"
	rows = [
		("Revenue", "Revenue", 1000.0),
		("Cost of revenue", "CostOfGoodsAndServicesSold", 600.0),
		("Gross profit", "GrossProfit", 400.0),
		("Research and development", "ResearchAndDevelopmentExpenses", 100.0),
		("Sales and marketing", "SellingGeneralAndAdminExpenses", 50.0),
		("General and administrative", "SellingGeneralAndAdminExpenses", 50.0),
		("Operating income", "OperatingIncomeLoss", 200.0),
		("Other income (expense), net", "NonoperatingIncomeExpense", 0.0),
		("Income before income taxes", "PretaxIncomeLoss", 200.0),
		("Provision for income taxes", "IncomeTaxes", 40.0),
		("Net income", "NetIncome", 160.0),
	]
	raw = pd.DataFrame(
		{
			"concept": [f"us-gaap_{concept}" for _, concept, _ in rows],
			"label": [label for label, _, _ in rows],
			"standard_concept": [concept for _, concept, _ in rows],
			period: [value for _, _, value in rows],
		}
	)
	return prepare_pnl(raw, years=1)


class Filing:
	accession_no = "A1"
	form = "10-K"
	filing_date = "2026-07-29"
	report_date = "2026-06-30"
	primary_document = "sample.htm"
	text_url = "https://example.test/sample.txt"
	text_value = "Fixture one.\nFixture two.\n"

	def text(self) -> str:
		return self.text_value

	def search(self, query: str, regex: bool = False) -> object:
		assert regex is False
		return SimpleNamespace(sections=[SimpleNamespace(loc=1, doc=self.text())])


def make_discovery() -> DiscoveryResult:
	return DiscoveryResult(
		topics=[
			DiscoveryTopic(
				name="Fixture review",
				queries=["Fixture one", "Fixture two"],
				rationale="test fixture",
			)
		]
	)


class AdjustmentAnalysisTests(TestCase):
	def test_cli_defaults_and_overrides(self) -> None:
		runner = CliRunner()
		with (
			patch("smrik_fund.main.build_analytical_pnl", return_value=make_pnl()),
			patch(
				"smrik_fund.main.save_analytical_pnl",
				return_value=Path("data/MSFT/03_output/analytical_pnl.csv"),
			),
			patch("smrik_fund.main._save_and_report_reconciliation", create=True),
			patch("smrik_fund.main._run_adjustment_analysis") as run_analysis,
		):
			result = runner.invoke(
				app,
				[
					"analyze",
					"MSFT",
					"--adjustments",
					"--model",
					"test-model",
					"--reasoning-effort",
					"low",
				],
			)

		self.assertEqual(result.exit_code, 0, result.output)
		run_analysis.assert_called_once()
		self.assertEqual(run_analysis.call_args.args[2], "test-model")
		self.assertEqual(run_analysis.call_args.args[3], "low")

		with (
			patch("smrik_fund.main.build_analytical_pnl", return_value=make_pnl()),
			patch(
				"smrik_fund.main.save_analytical_pnl",
				return_value=Path("data/MSFT/03_output/analytical_pnl.csv"),
			),
			patch("smrik_fund.main._save_and_report_reconciliation", create=True),
			patch("smrik_fund.main._run_adjustment_analysis") as run_default,
		):
			result = runner.invoke(app, ["analyze", "MSFT", "--adjustments"])

		self.assertEqual(result.exit_code, 0, result.output)
		self.assertEqual(run_default.call_args.args[2], "gpt-5.6-luna")
		self.assertEqual(run_default.call_args.args[3], "high")

	def test_adjustment_analysis_requires_filing(self) -> None:
		with (
			patch("smrik_fund.main.run_analyst") as run_analyst_mock,
			self.assertRaisesRegex(AdjustmentAnalysisError, "filing is required"),
		):
			_run_adjustment_analysis("MSFT", make_pnl(), "test-model", "high")

		run_analyst_mock.assert_not_called()

	def test_integrated_human_review_is_preserved_and_not_applied(self) -> None:
		result = AnalystResult(
			candidates=[
				AnalystCandidate(
					target_line="Research and development",
					period="2025-06-30 (FY)",
					item_amount=None,
					amount_basis="unknown",
					reason="XBOX-related expense is not separately quantified.",
					evidence_refs=["E1", "E2"],
				)
			]
		)
		review = ReviewResult(
			verdict="revise",
			evidence_strength="weak",
			amount_basis="unknown",
			judgment_level="high",
			calculation_valid=None,
			target_valid=True,
			period_valid=True,
			concerns=["The amount is not separately disclosed."],
		)
		with TemporaryDirectory() as temporary_directory:
			root = Path(temporary_directory)
			with (
				patch("smrik_fund.main.run_discovery", return_value=(make_discovery(), {"run_id": "run-1"})),
				patch("smrik_fund.main.run_analyst", return_value=(result, {
					"ticker": "MSFT",
					"model": "test-model",
					"reasoning_effort": "high",
					"run_id": "run-1",
				})),
				patch("smrik_fund.main.run_reviewer", return_value=(review, {
					"ticker": "MSFT",
					"run_id": "run-1",
				})),
			):
				manifest_path = _run_adjustment_analysis(
					"MSFT",
					make_integrated_pnl(),
					"test-model",
					"high",
					output_root=root,
					filing=Filing(),
				)

			manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
			self.assertEqual(manifest["candidates"][0]["adjustment_id"], "A0001")
			self.assertEqual(manifest["candidates"][0]["final_status"], "human_review")
			self.assertEqual(
				manifest["candidates"][0]["application_status"], "not_applied"
			)
			self.assertEqual(
				manifest["normalization_summary"]["schema_version"],
				"normalization-summary-v1",
			)
			self.assertEqual(len(manifest["normalization_summary"]["groups"]), 1)
			self.assertTrue(manifest["reported_equals_adjusted"])
			self.assertFalse(
				(root / "MSFT" / "03_output" / "adjustment_history.csv").exists()
			)
			adjusted = pd.read_csv(root / "MSFT" / "03_output" / "adjusted_pnl.csv")
			self.assertEqual(
				adjusted.loc[
					adjusted["label"] == "Research and development",
					"2025-06-30 (FY)",
				].iloc[0],
				100.0,
			)

	def test_explicit_filing_uses_discovery_once(self) -> None:
		resolved = AnalystResult(
			candidates=[
				AnalystCandidate(
					target_line="Research and development",
					period="2025-06-30 (FY)",
					item_amount=None,
					amount_basis="unknown",
					reason="The filing does not separately quantify the item.",
					evidence_refs=["E1", "E2"],
				)
			]
		)
		review = ReviewResult(
			verdict="revise",
			evidence_strength="weak",
			amount_basis="unknown",
			judgment_level="high",
			calculation_valid=None,
			target_valid=True,
			period_valid=True,
			concerns=["Amount unresolved."],
		)
		with TemporaryDirectory() as temporary_directory:
			root = Path(temporary_directory)
			with (
				patch("smrik_fund.main.run_discovery", return_value=(make_discovery(), {"run_id": "run-1"})) as discovery,
				patch("smrik_fund.main.run_analyst", return_value=(resolved, {"run_id": "run-1", "model": "test-model"})) as analyst,
				patch(
					"smrik_fund.main.run_reviewer",
					return_value=(review, {"run_id": "resolved"}),
				),
			):
				manifest_path = _run_adjustment_analysis(
					"MSFT",
					make_integrated_pnl(),
					"test-model",
					"high",
					output_root=root,
					filing=Filing(),
				)

			self.assertEqual(discovery.call_count, 1)
			self.assertEqual(analyst.call_count, 1)
			manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
			self.assertNotIn("initial_analyst", manifest)
			self.assertFalse(
				(root / "MSFT" / "03_output" / "adjustment_history.csv").exists()
			)

	def test_auto_approved_fixture_reaches_existing_application_engine(self) -> None:
		result = AnalystResult(
			candidates=[
				AnalystCandidate(
					target_line="Research and development",
					period="2025-06-30 (FY)",
					item_amount=10.0,
					item_effect_on_line="increased_line",
					amount_basis="disclosed",
					reason="Safe fixture.",
					evidence_refs=["E1"],
				)
			]
		)
		review = ReviewResult(
			verdict="accept",
			evidence_strength="strong",
			amount_basis="disclosed",
			judgment_level="low",
			calculation_valid=None,
			target_valid=True,
			item_effect_on_line="increased_line",
			period_valid=True,
			concerns=[],
		)
		conditions = RiskGateConditions(
			materiality_eligible=True,
			reconciliation_clear=True,
			possible_duplicate=False,
			group_reconciles=True,
			aggregate_over_adjustment=False,
			source_target_available=True,
			individual_over_adjustment=False,
			zero_target_with_line_delta=False,
			deterministic_checks_pass=True,
		)
		with TemporaryDirectory() as temporary_directory:
			root = Path(temporary_directory)
			with (
				patch("smrik_fund.main.run_discovery", return_value=(make_discovery(), {"run_id": "run-approved"})),
				patch("smrik_fund.main.run_analyst", return_value=(result, {
					"model": "test-model",
					"reasoning_effort": "high",
					"run_id": "run-approved",
				})),
				patch("smrik_fund.main.run_reviewer", return_value=(review, {
					"run_id": "run-approved",
				})),
				patch("smrik_fund.main._gate_conditions", return_value=conditions),
			):
				manifest_path = _run_adjustment_analysis(
					"MSFT", make_integrated_pnl(), "test-model", "high", output_root=root,
					filing=Filing(),
				)

			manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
			self.assertEqual(manifest["candidates"][0]["final_status"], "approved")
			self.assertEqual(manifest["candidates"][0]["application_status"], "applied")
			history = pd.read_csv(root / "MSFT" / "03_output" / "adjustment_history.csv")
			self.assertEqual(history.loc[0, "status"], "approved")
			self.assertEqual(history.loc[0, "item_amount"], 10.0)
			self.assertEqual(history.loc[0, "item_effect_on_line"], "increased_line")
			self.assertEqual(history.loc[0, "line_delta"], -10.0)
			adjusted = pd.read_csv(root / "MSFT" / "03_output" / "adjusted_pnl.csv")
			self.assertEqual(
				adjusted.loc[
					adjusted["label"] == "Research and development",
					"2025-06-30 (FY)",
				].iloc[0],
				90.0,
			)

	def test_frozen_approval_replays_from_persisted_history_exactly_once(self) -> None:
		candidate = AnalystCandidate(
			target_line="Research and development",
			period=PERIOD,
			item_amount=10.0,
			item_effect_on_line="increased_line",
			amount_basis="disclosed",
			reason="Safe frozen fixture.",
			evidence_refs=["E1"],
		)
		result = AnalystResult(candidates=[candidate])
		review = ReviewResult(
			verdict="accept",
			evidence_strength="strong",
			amount_basis="disclosed",
			judgment_level="low",
			calculation_valid=None,
			target_valid=True,
			item_effect_on_line="increased_line",
			period_valid=True,
			concerns=[],
		)
		with TemporaryDirectory() as temporary_directory:
			root = Path(temporary_directory)
			with (
				patch(
					"smrik_fund.main.run_discovery",
					return_value=(make_discovery(), {"run_id": "run-approved"}),
				),
				patch(
					"smrik_fund.main.run_analyst",
					return_value=(result, {"model": "test-model", "run_id": "run-approved"}),
				),
				patch("smrik_fund.main.run_reviewer", return_value=(review, {"run_id": "run-approved"})) as reviewer,
			):
				first_manifest_path = _run_adjustment_analysis(
					"MSFT",
					make_integrated_pnl(),
					"test-model",
					"high",
					output_root=root,
					filing=Filing(),
					materiality_passed=True,
				)
				history_path = root / "MSFT" / "03_output" / "adjustment_history.csv"
				first_manifest = json.loads(first_manifest_path.read_text(encoding="utf-8"))
				first_adjusted = pd.read_csv(root / "MSFT" / "03_output" / "adjusted_pnl.csv")
				first_adjusted_value = first_adjusted.loc[
					first_adjusted["label"] == "Research and development", PERIOD
				].iloc[0]
				first_history = pd.read_csv(history_path)
				self.assertEqual(first_manifest["candidates"][0]["final_status"], "approved")
				self.assertEqual(
					first_manifest["candidates"][0]["application_status"], "applied"
				)
				self.assertEqual(first_adjusted_value, 90.0)
				self.assertEqual(
					first_history.loc[0, ["adjustment_id", "version", "status"]].tolist(),
					["A0001", 1, "approved"],
				)
				self.assertEqual(first_history.loc[0, "item_amount"], 10.0)
				self.assertEqual(first_history.loc[0, "line_delta"], -10.0)
				history_bytes = history_path.read_bytes()
				second_manifest_path = _run_adjustment_analysis(
					"MSFT",
					make_integrated_pnl(),
					"test-model",
					"high",
					output_root=root,
					filing=Filing(),
					materiality_passed=True,
				)

			second = json.loads(second_manifest_path.read_text(encoding="utf-8"))
			history = pd.read_csv(history_path)
			self.assertEqual(len(history), 1)
			self.assertEqual(history.loc[0, "adjustment_id"], "A0001")
			self.assertEqual(history.loc[0, "version"], 1)
			self.assertEqual(history.loc[0, "status"], "approved")
			self.assertEqual(history.loc[0, "item_amount"], 10.0)
			self.assertEqual(history.loc[0, "adjustment_id"], "A0001")
			self.assertEqual(first_manifest["candidates"][0]["identity_status"], "new")
			self.assertEqual(second["candidates"][0]["identity_status"], "replay")
			self.assertEqual(second["candidates"][0]["adjustment_id"], "A0001")
			self.assertEqual(
				second["candidates"][0]["application_status"], "applied"
			)
			self.assertTrue(
				all(
					value is not None
					for value in first_manifest["candidates"][0]["gate"]["conditions"].values()
				)
			)
			second_adjusted = pd.read_csv(root / "MSFT" / "03_output" / "adjusted_pnl.csv")
			second_adjusted_value = second_adjusted.loc[
				second_adjusted["label"] == "Research and development", PERIOD
			].iloc[0]
			self.assertEqual(first_adjusted_value, 90.0)
			self.assertEqual(second_adjusted_value, 90.0)
			self.assertEqual(second_adjusted_value, first_adjusted_value)
			self.assertEqual(history_bytes, history_path.read_bytes())
			self.assertEqual(reviewer.call_count, 1)

	def test_history_identity_lookup_ignores_legacy_rows_without_guessing(self) -> None:
		identity = _canonical_json({"identity": "stable"})
		state = _canonical_json({"item_amount": 10.0})
		legacy = pd.DataFrame(
			[{"adjustment_id": "A0001", "version": 1, "status": "proposed"}]
		)
		# Legacy rows cannot prove direction, but they also cannot match any
		# candidate identity, so they must not block new candidates.
		self.assertEqual(
			_history_identity_lookup(legacy, identity, state),
			{"status": "new", "adjustment_id": None, "version": 0},
		)

		unparseable = pd.DataFrame(
			[
				{
					"adjustment_id": "A0001",
					"version": 1,
					"candidate_identity": "",
					"candidate_state": state,
					"status": "proposed",
				},
			]
		)
		self.assertEqual(
			_history_identity_lookup(unparseable, identity, state),
			{"status": "new", "adjustment_id": None, "version": 0},
		)

		ambiguous = pd.DataFrame(
			[
				{
					"adjustment_id": "A0001",
					"version": 1,
					"candidate_identity": identity,
					"candidate_state": state,
					"status": "approved",
				},
				{
					"adjustment_id": "A0002",
					"version": 1,
					"candidate_identity": identity,
					"candidate_state": state,
					"status": "approved",
				},
			]
		)
		self.assertEqual(
			_history_identity_lookup(ambiguous, identity, state),
			{"status": "unknown", "adjustment_id": None, "version": 0},
		)

	def test_history_identity_lookup_uses_latest_approved_state(self) -> None:
		identity = _canonical_json({"identity": "stable"})
		state_v1 = _canonical_json({"item_amount": 10.0})
		state_v2 = _canonical_json({"item_amount": 12.0})
		history = pd.DataFrame(
			[
				{
					"adjustment_id": "A0001",
					"version": 1,
					"candidate_identity": identity,
					"candidate_state": state_v1,
					"status": "approved",
				},
				{
					"adjustment_id": "A0001",
					"version": 2,
					"candidate_identity": identity,
					"candidate_state": state_v2,
					"status": "rejected",
				},
			]
		)

		lookup = _history_identity_lookup(history, identity, state_v1)

		self.assertEqual(lookup["status"], "replay")
		self.assertEqual(lookup["version"], 1)
		self.assertEqual(lookup["latest"]["status"], "approved")
		self.assertEqual(
			_history_identity_lookup(history, identity, state_v2)["status"],
			"state_conflict",
		)

	def test_legacy_rows_do_not_block_new_candidate_matching(self) -> None:
		pnl = make_integrated_pnl()
		packet_identity = {
			"metadata": {"filing_accession": "A1", "ticker": "MSFT"},
			"items": {
				"E1": {"source": "filing", "section": "one", "locator": "line 1"},
			},
		}
		candidate = AnalystCandidate(
			target_line="Research and development",
			period=PERIOD,
			item_amount=10.0,
			item_effect_on_line="increased_line",
			amount_basis="disclosed",
			reason="Fixture.",
			evidence_refs=["E1"],
		)
		identity = _candidate_identity("MSFT", pnl, candidate, packet_identity)
		legacy_row = {
			"adjustment_id": "A0009",
			"version": 1,
			"run_id": "legacy",
			"origin": "llm",
			"target_line": "Research and development",
			"period": PERIOD,
			"amount": 10.0,
			"status": "proposed",
		}
		history = pd.DataFrame([legacy_row])

		self.assertEqual(
			_history_identity_lookup(
				history, identity, _canonical_json(_candidate_state(candidate))
			)["status"],
			"new",
		)

	def test_distinct_exact_identities_allocate_separate_candidates(self) -> None:
		pnl = make_integrated_pnl()
		packet_identity = {
			"metadata": {"filing_accession": "A1", "ticker": "MSFT"},
			"items": {
				"E1": {"source": "filing", "section": "one", "locator": "line 1"},
				"E2": {"source": "filing", "section": "two", "locator": "line 2"},
			},
		}
		first = AnalystCandidate(
			target_line="Research and development",
			period=PERIOD,
			item_amount=10.0,
			amount_basis="disclosed",
			sub_item="Cloud restructuring",
			reason="First distinct item.",
			evidence_refs=["E1"],
		)
		second = first.model_copy(
			update={
				"item_amount": 11.0,
				"sub_item": "Gaming restructuring",
				"reason": "Second distinct item.",
				"evidence_refs": ["E2"],
			}
		)
		first_identity = _candidate_identity("MSFT", pnl, first, packet_identity)
		second_identity = _candidate_identity("MSFT", pnl, second, packet_identity)
		self.assertNotEqual(first_identity, second_identity)
		history = pd.DataFrame(
			[
				{
					"adjustment_id": "A0001",
					"version": 1,
					"candidate_identity": first_identity,
					"candidate_state": _canonical_json(_candidate_state(first)),
					"status": "approved",
				}
			]
		)
		self.assertEqual(
			_history_identity_lookup(
				history, second_identity, _canonical_json(_candidate_state(second))
			)["status"],
			"new",
		)

	def test_changed_unapproved_candidate_preserves_v1_until_v2_is_approved(self) -> None:
		base = AnalystResult(
			candidates=[
				AnalystCandidate(
					target_line="Research and development",
					period=PERIOD,
					item_amount=10.0,
					item_effect_on_line="increased_line",
					amount_basis="disclosed",
					reason="Safe frozen fixture.",
					evidence_refs=["E1"],
				)
			]
		)
		changed = AnalystResult(
			candidates=[base.candidates[0].model_copy(update={"item_amount": 12.0})]
		)
		review = ReviewResult(
			verdict="accept",
			evidence_strength="strong",
			amount_basis="disclosed",
			item_effect_on_line="increased_line",
			judgment_level="low",
			calculation_valid=None,
			target_valid=True,
			period_valid=True,
			concerns=[],
		)
		with TemporaryDirectory() as temporary_directory:
			root = Path(temporary_directory)
			with (
				patch("smrik_fund.main.run_discovery", return_value=(make_discovery(), {"run_id": "run-approved"})),
				patch("smrik_fund.main.run_analyst", return_value=(base, {"model": "test-model", "run_id": "run-approved"})),
				patch("smrik_fund.main.run_reviewer", return_value=(review, {"run_id": "run-approved"})),
			):
				_run_adjustment_analysis(
					"MSFT", make_integrated_pnl(), "test-model", "high",
					output_root=root, filing=Filing(), materiality_passed=True,
				)
				with (
					patch("smrik_fund.main.run_analyst", return_value=(changed, {"model": "test-model", "run_id": "run-changed"})),
					patch("smrik_fund.main.typer.echo") as echo,
				):
					manifest_path = _run_adjustment_analysis(
						"MSFT", make_integrated_pnl(), "test-model", "high",
						output_root=root, filing=Filing(), materiality_passed=True,
					)

			manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
			history = pd.read_csv(root / "MSFT" / "03_output" / "adjustment_history.csv")
			self.assertEqual(len(history), 1)
			self.assertEqual(history["adjustment_id"].tolist(), ["A0001"])
			self.assertEqual(history["version"].tolist(), [1])
			self.assertEqual(history["status"].tolist(), ["approved"])
			self.assertEqual(history["item_amount"].tolist(), [10.0])
			self.assertEqual(history["line_delta"].tolist(), [-10.0])
			output = "\n".join(call.args[0] for call in echo.call_args_list)
			self.assertIn("Adjustment history unchanged (0 approved rows)", output)
			self.assertEqual(manifest["candidates"][0]["identity_status"], "state_conflict")
			self.assertIn("candidate_state_conflict", manifest["candidates"][0]["gate"]["reasons"])
			adjusted = pd.read_csv(root / "MSFT" / "03_output" / "adjusted_pnl.csv")
			self.assertEqual(
				adjusted.loc[adjusted["label"] == "Research and development", PERIOD].iloc[0],
				90.0,
			)

			approved_v2 = history.iloc[0].copy()
			approved_v2["version"] = 2
			approved_v2["item_amount"] = 12.0
			approved_v2["line_delta"] = -12.0
			approved_v2["candidate_state"] = _canonical_json(
				_candidate_state(changed.candidates[0])
			)
			approved_v2["status"] = "approved"
			history_with_v2 = pd.concat(
				[history, pd.DataFrame([approved_v2])], ignore_index=True
			)
			current = resolve_current_adjustments(history_with_v2)
			self.assertEqual(len(current), 1)
			self.assertEqual(current.loc[0, "version"], 2)
			self.assertEqual(current.loc[0, "item_amount"], 12.0)
			adjusted_v2 = apply_adjustments(make_integrated_pnl(), current)
			self.assertEqual(
				adjusted_v2.loc[
					adjusted_v2["label"] == "Research and development", PERIOD
				].iloc[0],
				88.0,
			)

	def test_live_materiality_stays_unknown_and_fail_closed(self) -> None:
		result = AnalystResult(
			candidates=[
				AnalystCandidate(
					target_line="Research and development",
					period=PERIOD,
					item_amount=10.0,
					item_effect_on_line="increased_line",
					amount_basis="disclosed",
					reason="Live-safe fixture.",
					evidence_refs=["E1"],
				)
			]
		)
		review = ReviewResult(
			verdict="accept",
			evidence_strength="strong",
			amount_basis="disclosed",
			judgment_level="low",
			calculation_valid=None,
			target_valid=True,
			period_valid=True,
			concerns=[],
		)
		with TemporaryDirectory() as temporary_directory:
			root = Path(temporary_directory)
			with (
				patch("smrik_fund.main.run_discovery", return_value=(make_discovery(), {"run_id": "run-live"})),
				patch("smrik_fund.main.run_analyst", return_value=(result, {"model": "test-model", "run_id": "run-live"})),
				patch("smrik_fund.main.run_reviewer", return_value=(review, {"run_id": "run-live"})),
			):
				manifest_path = _run_adjustment_analysis(
					"MSFT", make_integrated_pnl(), "test-model", "high",
					output_root=root, filing=Filing(),
				)
			manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
			self.assertIsNone(
				manifest["candidates"][0]["gate"]["conditions"]["materiality_eligible"]
			)
			self.assertEqual(manifest["candidates"][0]["final_status"], "human_review")
			self.assertFalse(
				(root / "MSFT" / "03_output" / "adjustment_history.csv").exists()
			)

	def test_gate_builder_marks_over_target_negative_parent_derived_and_missing_cases(self) -> None:
		pnl = make_integrated_pnl()
		checks = pd.DataFrame(
			[
				{
					"period": PERIOD,
					"status": "FAIL",
					"affected_lines": "Research and development; Operating income",
				}
			]
		)
		base = AnalystCandidate(
			target_line="Research and development",
			period=PERIOD,
			item_amount=10.0,
			item_effect_on_line="increased_line",
			amount_basis="disclosed",
			reason="Fixture.",
			evidence_refs=["E1"],
		)
		failed_reconciliation = _gate_conditions(
			pnl, base, checks, materiality_passed=True
		)
		self.assertFalse(failed_reconciliation.reconciliation_clear)
		self.assertFalse(failed_reconciliation.aggregate_over_adjustment)

		over_target = base.model_copy(update={"item_amount": 101.0})
		over_target_conditions = _gate_conditions(
			pnl, over_target, pd.DataFrame({"status": ["PASS"]}), materiality_passed=True
		)
		self.assertTrue(over_target_conditions.individual_over_adjustment)
		self.assertTrue(over_target_conditions.aggregate_over_adjustment)

		# A negative parent line alone is no longer a gate failure; only a
		# delta that pushes the adjusted value through zero is.
		negative_pnl = pnl.copy(deep=True)
		negative_pnl.loc[
			negative_pnl["label"] == "Research and development", PERIOD
		] = -100.0
		negative = _gate_conditions(
			negative_pnl,
			base,
			pd.DataFrame({"status": ["PASS"]}),
			materiality_passed=True,
		)
		self.assertFalse(negative.individual_over_adjustment)
		self.assertFalse(negative.aggregate_over_adjustment)
		negative_overshoot = base.model_copy(
			update={"item_amount": 150.0, "item_effect_on_line": "decreased_line"}
		)
		overshoot_conditions = _gate_conditions(
			negative_pnl,
			negative_overshoot,
			pd.DataFrame({"status": ["PASS"]}),
			materiality_passed=True,
		)
		self.assertTrue(overshoot_conditions.individual_over_adjustment)

		derived = base.model_copy(update={"target_line": "Gross profit"})
		derived_conditions = _gate_conditions(
			pnl, derived, pd.DataFrame({"status": ["PASS"]}), materiality_passed=True
		)
		self.assertFalse(derived_conditions.deterministic_checks_pass)

		missing = base.model_copy(update={"period": "2099-06-30 (FY)"})
		missing_conditions = _gate_conditions(
			pnl, missing, pd.DataFrame({"status": ["PASS"]}), materiality_passed=True
		)
		self.assertFalse(missing_conditions.source_target_available)

	def test_unknown_evidence_reference_fails_before_persistence(self) -> None:
		result = AnalystResult(
			candidates=[
				AnalystCandidate(
					target_line="Research and development",
					period=PERIOD,
					amount_basis="unknown",
					reason="Potential unusual item.",
					evidence_refs=["E99"],
				)
			]
		)
		with (
			patch("smrik_fund.main.run_discovery", return_value=(make_discovery(), {"run_id": "run-1"})),
			patch(
				"smrik_fund.main.Path.read_text",
				return_value=(
					"### E1\nSource: filing source\nSection: filing section\n"
					"Locator: line 1\n\n> Filing excerpt."
				),
			),
			patch(
				"smrik_fund.main.run_analyst",
				return_value=(result, {"model": "test-model"}),
			),
		):
			manifest_path = _run_adjustment_analysis(
				"MSFT", make_pnl(), "test-model", "high", filing=Filing()
			)

		manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
		self.assertEqual(manifest["candidates"][0]["final_status"], "unresolved")

	def test_empty_evidence_references_fail_before_persistence_or_review(self) -> None:
		result = AnalystResult(
			candidates=[
				AnalystCandidate(
					target_line="Research and development",
					period=PERIOD,
					amount_basis="unknown",
					reason="Potential unusual item.",
					evidence_refs=[],
				)
			]
		)
		with (
			patch("smrik_fund.main.run_discovery", return_value=(make_discovery(), {"run_id": "run-1"})),
			patch(
				"smrik_fund.main.Path.read_text",
				return_value=(
					"### E1\nSource: filing source\nSection: filing section\n"
					"Locator: line 1\n\n> Filing excerpt."
				),
			),
			patch(
				"smrik_fund.main.run_analyst",
				return_value=(result, {"model": "test-model"}),
			),
			patch("smrik_fund.main.run_reviewer") as run_reviewer,
		):
			manifest_path = _run_adjustment_analysis(
				"MSFT", make_pnl(), "test-model", "high", filing=Filing()
			)

		run_reviewer.assert_not_called()
		manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
		self.assertEqual(manifest["candidates"][0]["final_status"], "unresolved")

	def test_normalization_summary_groups_periods_and_preserves_states(self) -> None:
		records = [
			{
				"adjustment_id": "A0001",
				"topic": "Tax interest",
				"candidate": {
					"target_line": "Provision for income taxes",
					"sub_item": "Uncertain-tax-position interest",
					"period": "2024-06-30 (FY)",
					"item_amount": 1_500_000_000.0,
					"amount_basis": "disclosed",
					"reason": "Disclosed tax-position interest may distort comparability.",
					"uncertainty": "Treatment depends on the framework.",
				},
				"review": {
					"verdict": "revise",
					"evidence_strength": "strong",
					"concerns": ["Treatment remains unresolved."],
				},
				"gate": {
					"decision": "human_review",
					"reasons": ["judgment_level_not_low"],
				},
				"final_status": "human_review",
				"application_status": "not_applied",
			},
			{
				"adjustment_id": "A0002",
				"topic": "Tax interest",
				"candidate": {
					"target_line": "Provision for income taxes",
					"sub_item": "Uncertain-tax-position interest",
					"period": "2025-06-30 (FY)",
					"item_amount": 1_300_000_000.0,
					"amount_basis": "disclosed",
					"reason": "Disclosed tax-position interest may distort comparability.",
					"uncertainty": "Treatment depends on the framework.",
				},
				"review": {
					"verdict": "accept",
					"evidence_strength": "strong",
					"concerns": [],
				},
				"gate": {"decision": "human_review", "reasons": []},
				"final_status": "human_review",
				"application_status": "not_applied",
			},
			{
				"adjustment_id": "A0003",
				"topic": "Tax interest",
				"candidate": {
					"target_line": "Provision for income taxes",
					"sub_item": "Uncertain-tax-position interest",
					"period": "2026-06-30 (FY)",
					"item_amount": 1_400_000_000.0,
					"amount_basis": "disclosed",
					"reason": "Disclosed tax-position interest may distort comparability.",
					"uncertainty": "Treatment depends on the framework.",
				},
				"review": {"verdict": "accept", "concerns": []},
				"gate": {"decision": "human_review", "reasons": []},
				"final_status": "human_review",
				"application_status": "not_applied",
			},
		]

		groups = build_normalization_summary(records)
		self.assertEqual(len(groups), 1)
		group = groups[0]
		self.assertEqual(group["item"], "Uncertain-tax-position interest")
		self.assertEqual(
			[row["item_amount"] for row in group["periods"]],
			[1_500_000_000.0, 1_300_000_000.0, 1_400_000_000.0],
		)
		self.assertNotIn("cross_period_observations", group)
		self.assertEqual(
			group["financial_assessments"],
			["Disclosed tax-position interest may distort comparability."],
		)
		self.assertEqual(group["uncertainties"], ["Treatment depends on the framework."])
		self.assertNotIn("assessment_flags", group)
		self.assertNotIn("reviewer_evidence_strengths", group)
		self.assertEqual(group["reviewer_verdicts"], ["revise", "accept"])
		self.assertEqual(group["gate_decisions"], ["human_review"])
		self.assertEqual(group["final_statuses"], ["human_review"])
		self.assertEqual(group["application_statuses"], ["not_applied"])
		self.assertEqual(group["why_not_automatic"], ["judgment_level_not_low"])
		self.assertEqual(
			[
				(
					row["period"],
					row["candidate_ids"],
					row["reviewer_verdict"],
					row["gate_decision"],
					row["final_status"],
					row["application_status"],
				)
				for row in group["periods"]
			],
			[
				(
					"2024-06-30 (FY)",
					["A0001"],
					"revise",
					"human_review",
					"human_review",
					"not_applied",
				),
				(
					"2025-06-30 (FY)",
					["A0002"],
					"accept",
					"human_review",
					"human_review",
					"not_applied",
				),
				(
					"2026-06-30 (FY)",
					["A0003"],
					"accept",
					"human_review",
					"human_review",
					"not_applied",
				),
			],
		)

	def test_rendering_uses_neutral_candidate_label_and_factual_gate_text(self) -> None:
		records = [
			{
				"adjustment_id": "A0001",
				"topic": "Investment dilution gain",
				"candidate": {
					"target_line": "Other income (expense), net",
					"sub_item": "OpenAI investments",
					"period": "2025-06-30 (FY)",
					"item_amount": 4_800_000_000.0,
					"item_effect_on_line": None,
					"amount_basis": "disclosed",
				},
				"review": {"verdict": "revise"},
				"gate": {
					"decision": "human_review",
					"reasons": [
						"reviewer_verdict_revise",
						"line_delta_underived",
					],
				},
				"final_status": "human_review",
				"application_status": "not_applied",
			}
		]
		with patch("smrik_fund.main.typer.echo") as echo:
			_render_normalization_summary(build_normalization_summary(records))

		output = "\n".join(call.args[0] for call in echo.call_args_list)
		self.assertIn("Item: OpenAI investments |", output)
		self.assertNotIn("Item: Investment dilution gain |", output)
		self.assertIn("candidate magnitude $4.8bn (disclosed)", output)
		self.assertIn("Reviewer requested revision", output)
		self.assertIn(
			"Line direction is unsupported, so no signed delta can be derived", output
		)
		self.assertNotIn("reviewer_verdict_revise", output)
		self.assertNotIn("line_delta_underived", output)
		self.assertIn(
			"Reviewer verdict=revise; gate decision=human_review; "
			"final=human_review; application=not_applied",
			output,
		)

	def test_normalization_summary_does_not_merge_null_or_unrelated_candidates(self) -> None:
		record = {
			"adjustment_id": "A0001",
			"topic": "XBOX",
			"candidate": {
				"target_line": "Research and development",
				"sub_item": None,
				"period": PERIOD,
				"item_amount": None,
				"amount_basis": "unknown",
				"reason": "The amount is not separately disclosed.",
				"uncertainty": "Amount unresolved.",
			},
			"final_status": "unresolved",
			"application_status": "not_applied",
			"error": "Reviewer unavailable.",
		}
		other = {
			**record,
			"adjustment_id": "A0002",
			"topic": "Divestiture",
			"candidate": {
				**record["candidate"],
				"target_line": "General and administrative",
			},
		}

		groups = build_normalization_summary([record, other])
		self.assertEqual(len(groups), 2)
		self.assertIsNone(groups[0]["periods"][0]["item_amount"])
		self.assertIn("Amount unresolved.", groups[0]["uncertainties"])
		self.assertIn("Reviewer unavailable.", groups[0]["unresolved_issues"])

	def test_signed_source_value_displays_adjusted_arrow_without_parent_sign_block(self) -> None:
		pnl = make_integrated_pnl()
		pnl.loc[
			pnl["label"] == "Other income (expense), net", PERIOD
		] = -4_901_000_000.0
		candidate = AnalystCandidate(
			target_line="Other income (expense), net",
			period=PERIOD,
			item_amount=4_800_000_000.0,
			item_effect_on_line="decreased_line",
			amount_basis="disclosed",
			reason="Disclosed loss.",
			evidence_refs=["E1"],
		)
		record = {
			"adjustment_id": "A0001",
			"topic": "OpenAI investment losses",
			"candidate": candidate.model_dump(mode="json"),
			"final_status": "human_review",
			"application_status": "not_applied",
		}

		groups = build_normalization_summary([record], pnl=pnl)
		period_row = groups[0]["periods"][0]
		self.assertEqual(period_row["reported_value"], -4_901_000_000.0)
		self.assertEqual(period_row["line_delta"], 4_800_000_000.0)
		self.assertEqual(period_row["adjusted_value"], -101_000_000.0)
		conditions = _gate_conditions(
			pnl, candidate, pd.DataFrame({"status": ["PASS"]})
		)
		# The loss reduced a negative line; removing it raises the line toward
		# zero without crossing, so the negative parent alone cannot block.
		self.assertFalse(conditions.individual_over_adjustment)

		with patch("smrik_fund.main.typer.echo") as echo:
			_render_normalization_summary(build_normalization_summary([record], pnl=pnl))
		output = "\n".join(call.args[0] for call in echo.call_args_list)
		self.assertIn("-$4.9bn -> -$101.0mn", output)
		self.assertIn("normalized line increases by $4.8bn", output)

	def test_cli_prints_compact_summary_and_artifact_paths(self) -> None:
		result = AnalystResult(
			candidates=[
				AnalystCandidate(
					target_line="Research and development",
					sub_item="XBOX impairment",
					period=PERIOD,
					item_amount=None,
					amount_basis="unknown",
					calculation="No attributable amount is separately disclosed.",
					reason="Potential unusual item.",
					evidence_refs=["E1", "E2"],
					uncertainty="Amount not separately disclosed.",
				)
			]
		)
		with (
			patch("smrik_fund.main.run_discovery", return_value=(make_discovery(), {"run_id": "run-1"})),
			patch(
				"smrik_fund.main.run_analyst",
				return_value=(
					result,
					{"model": "test-model", "reasoning_effort": "low"},
				),
			),
			patch(
				"smrik_fund.main.run_reviewer",
				return_value=(
					ReviewResult(
						verdict="revise",
						evidence_strength="weak",
						amount_basis="unknown",
						judgment_level="high",
						calculation_valid=None,
						target_valid=True,
						period_valid=True,
						concerns=["Amount unresolved."],
					),
					{"run_id": "run-1"},
				),
			),
			patch(
				"smrik_fund.main.save_reviewer_result",
				return_value=Path("review.json"),
			),
			patch("smrik_fund.main.typer.echo") as echo,
		):
			_run_adjustment_analysis("MSFT", make_pnl(), "test-model", "low", filing=Filing())

		output = "\n".join(call.args[0] for call in echo.call_args_list)
		self.assertIn("Normalization summary", output)
		self.assertIn("Item: XBOX impairment | Target line: Research and development", output)
		self.assertIn(
			"Periods / reported vs candidate magnitudes: "
			"2025-06-30 (FY)=reported not disclosed, "
			"candidate magnitude not disclosed (unknown) ",
			output,
		)
		self.assertIn("Financial assessment: Potential unusual item.", output)
		self.assertIn("Unresolved issue / Reviewer concern: Amount unresolved.", output)
		self.assertIn("Why not automatic: Reviewer requested revision", output)
		self.assertNotIn("reviewer_verdict_revise", output)
		self.assertIn("Reviewer verdict=revise", output)
		self.assertIn("gate decision=human_review", output)
		self.assertIn("final=human_review", output)
		self.assertIn("application=not_applied", output)
		self.assertNotIn("recurr", output.casefold())
		self.assertNotIn("Excerpt: Fixture one.", output)
		self.assertNotIn("Cited evidence:", output)
		self.assertIn("Saved Analyst JSON files: 1", output)
		self.assertIn("Saved Reviewer JSON files: 1", output)
		self.assertIn("Adjustment history unchanged (0 approved rows)", output)
		self.assertIn("Saved integrated adjustment run:", output)

	def test_null_amount_is_valid_analyst_output(self) -> None:
		result = AnalystResult(
			candidates=[
				AnalystCandidate(
					target_line="Research and development",
					sub_item="XBOX impairment and related expenses",
					period="2026-06-30 (FY)",
					item_amount=None,
					amount_basis="unknown",
					reason="The filing identifies the item but does not provide a separate amount.",
					evidence_refs=["E1"],
					uncertainty="Amount unresolved.",
				)
			]
		)

		self.assertIsNone(result.candidates[0].item_amount)
		self.assertIsNone(
			AnalystResult.model_validate(result.model_dump())
			.candidates[0]
			.item_amount
		)

	def test_one_structured_call_preserves_raw_result_and_metadata(self) -> None:
		expected = AnalystResult(
			candidates=[
				AnalystCandidate(
					target_line="Research and development",
					period="2026-06-30 (FY)",
					item_amount=None,
					amount_basis="unknown",
					reason="The filing identifies an impairment-related item.",
					evidence_refs=["E1"],
				)
			]
		)
		client = Mock()
		client.responses.parse.return_value = SimpleNamespace(output_parsed=expected)

		result, metadata = run_analyst(
			" msft ",
			make_pnl(),
			"Frozen evidence packet",
			client=client,
			model="test-model",
			reasoning_effort="low",
			evidence_ref="restructuring.md",
			run_id="run-1",
		)

		self.assertEqual(result, expected)
		self.assertEqual(metadata["ticker"], "MSFT")
		self.assertEqual(metadata["model"], "test-model")
		self.assertEqual(metadata["reasoning_effort"], "low")
		self.assertEqual(metadata["run_id"], "run-1")
		client.responses.parse.assert_called_once()
		self.assertEqual(
			client.responses.parse.call_args.kwargs["reasoning"], {"effort": "low"}
		)
		user_content = client.responses.parse.call_args.kwargs["input"][1]["content"]
		self.assertIn("Frozen evidence packet", user_content)
		self.assertIn("Revenue", user_content)

	def test_missing_pnl_values_are_json_null(self) -> None:
		pnl = make_pnl()
		pnl.loc[0, PERIOD] = float("nan")
		client = Mock()
		client.responses.parse.return_value = SimpleNamespace(
			output_parsed=AnalystResult(candidates=[])
		)

		run_analyst("MSFT", pnl, "Frozen evidence packet", client=client)

		user_content = client.responses.parse.call_args.kwargs["input"][1]["content"]
		payload = json.loads(user_content)
		self.assertIsNone(payload["pnl"][0][PERIOD])
		self.assertNotIn("NaN", user_content)

	def test_unknown_structured_fields_are_rejected(self) -> None:
		with self.assertRaises(ValidationError):
			AnalystCandidate.model_validate(
				{
					"target_line": "Research and development",
					"period": PERIOD,
					"amount_basis": "unknown",
					"reason": "Potential unusual item.",
					"evidence_refs": ["E1"],
					"materiality": "high",
				}
			)

		with self.assertRaises(ValidationError):
			AnalystResult.model_validate({"candidates": [], "status": "accept"})

	def test_generated_run_id_has_microsecond_precision(self) -> None:
		client = Mock()
		client.responses.parse.return_value = SimpleNamespace(
			output_parsed=AnalystResult(candidates=[])
		)

		_, metadata = run_analyst(
			"MSFT", make_pnl(), "Frozen evidence packet", client=client
		)

		self.assertRegex(metadata["run_id"], r"^\d{8}T\d{12}Z$")

	def test_persistence_writes_result_and_metadata(self) -> None:
		result = AnalystResult(
			candidates=[
				AnalystCandidate(
					target_line="Research and development",
					period="2026-06-30 (FY)",
					item_amount=None,
					amount_basis="unknown",
					reason="Amount unresolved.",
					evidence_refs=["E1"],
				)
			]
		)
		metadata = {
			"ticker": "MSFT",
			"model": "test-model",
			"reasoning_effort": "high",
			"run_id": "run-1",
		}

		with TemporaryDirectory() as temporary_directory:
			output_path = save_analyst_result(
				" msft ", result, metadata, temporary_directory
			)
			saved = json.loads(output_path.read_text(encoding="utf-8"))

		self.assertEqual(
			output_path,
			Path(temporary_directory)
			/ "MSFT"
			/ "03_output"
			/ "analysis"
			/ "analyst_run-1.json",
		)
		self.assertIsNone(saved["result"]["candidates"][0]["item_amount"])
		self.assertEqual(saved["metadata"]["reasoning_effort"], "high")
