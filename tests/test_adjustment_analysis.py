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
from smrik_fund.main import _run_adjustment_analysis, app

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

	def test_evidence_packet_is_passed_unchanged(self) -> None:
		result = AnalystResult(candidates=[])
		packet = (
			"### E1\nSource: filing source\nSection: filing section\n"
			"Locator: line 1\n\n> Filing excerpt."
		)
		with (
			patch(
				"smrik_fund.main.Path.read_text",
				return_value=packet,
			),
			patch(
				"smrik_fund.main.run_analyst",
				return_value=(
					result,
					{
						"run_id": "run-1",
						"model": "test-model",
						"reasoning_effort": "high",
					},
				),
			) as run_analyst_mock,
			patch(
				"smrik_fund.main.save_analyst_result", return_value=Path("result.json")
			),
			patch("smrik_fund.main.typer.echo"),
		):
			_run_adjustment_analysis("MSFT", make_pnl(), "test-model", "high")

		self.assertEqual(run_analyst_mock.call_args.args[2], packet)

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
			patch("smrik_fund.main.save_analyst_result") as save_result,
			self.assertRaisesRegex(
				AdjustmentAnalysisError,
				"unknown evidence reference.*E99",
			),
		):
			_run_adjustment_analysis("MSFT", make_pnl(), "test-model", "high")

		save_result.assert_not_called()

	def test_cli_resolves_evidence_ids_in_human_display(self) -> None:
		result = AnalystResult(
			candidates=[
				AnalystCandidate(
					target_line="Research and development",
					sub_item="XBOX impairment",
					period=PERIOD,
					adjustment_amount=None,
					amount_basis="unknown",
					calculation="No attributable amount is separately disclosed.",
					reason="Potential unusual item.",
					evidence_refs=["E1", "E2"],
					uncertainty="Amount not separately disclosed.",
				)
			]
		)
		with (
			patch(
				"smrik_fund.main.Path.read_text",
				return_value=(
					"### E1\nSource: filing source\nSection: filing section\nLocator: line 1\n\n"
					"> First filing excerpt.\n\n"
					"### E2\nSource: filing source\nSection: filing section\nLocator: line 2\n\n"
					"> Second filing excerpt."
				),
			),
			patch(
				"smrik_fund.main.run_analyst",
				return_value=(
					result,
					{"model": "test-model", "reasoning_effort": "low"},
				),
			),
			patch(
				"smrik_fund.main.save_analyst_result",
				return_value=Path("analyst.json"),
			),
			patch("smrik_fund.main.typer.echo") as echo,
		):
			_run_adjustment_analysis("MSFT", make_pnl(), "test-model", "low")

		output = "\n".join(call.args[0] for call in echo.call_args_list)
		self.assertIn("Model: test-model", output)
		self.assertIn("Reasoning effort: low", output)
		self.assertIn("Target line: Research and development", output)
		self.assertIn("Sub-item: XBOX impairment", output)
		self.assertIn("Period: 2025-06-30 (FY)", output)
		self.assertIn("Amount: null", output)
		self.assertIn("Amount basis: unknown", output)
		self.assertIn(
			"Calculation: No attributable amount is separately disclosed.", output
		)
		self.assertIn("Reason: Potential unusual item.", output)
		self.assertIn("Uncertainty: Amount not separately disclosed.", output)
		self.assertIn("E1:", output)
		self.assertIn("E2:", output)
		self.assertIn("Source: filing source", output)
		self.assertIn("Section: filing section", output)
		self.assertIn("Locator: line 1", output)
		self.assertIn("Excerpt: First filing excerpt.", output)
		self.assertIn("Excerpt: Second filing excerpt.", output)
		self.assertIn("Saved Analyst JSON: analyst.json", output)

	def test_null_amount_is_valid_analyst_output(self) -> None:
		result = AnalystResult(
			candidates=[
				AnalystCandidate(
					target_line="Research and development",
					sub_item="XBOX impairment and related expenses",
					period="2026-06-30 (FY)",
					adjustment_amount=None,
					amount_basis="unknown",
					reason="The filing identifies the item but does not provide a separate amount.",
					evidence_refs=["E1"],
					uncertainty="Amount unresolved.",
				)
			]
		)

		self.assertIsNone(result.candidates[0].adjustment_amount)
		self.assertIsNone(
			AnalystResult.model_validate(result.model_dump())
			.candidates[0]
			.adjustment_amount
		)

	def test_one_structured_call_preserves_raw_result_and_metadata(self) -> None:
		expected = AnalystResult(
			candidates=[
				AnalystCandidate(
					target_line="Research and development",
					period="2026-06-30 (FY)",
					adjustment_amount=None,
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
					adjustment_amount=None,
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
		self.assertIsNone(saved["result"]["candidates"][0]["adjustment_amount"])
		self.assertEqual(saved["metadata"]["reasoning_effort"], "high")
