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
	AnalyticalScanError,
	AnalyticalScanFinding,
	AnalyticalScanResult,
	format_analytical_pnl_for_scan,
	run_analytical_scan,
	save_analytical_scan,
	validate_analytical_scan_result,
)
from smrik_fund.ingestion.statements import prepare_pnl
from smrik_fund.main import app

PERIODS = (
	"2026-06-30 (FY)",
	"2025-06-30 (FY)",
	"2024-06-30 (FY)",
)


def make_pnl() -> pd.DataFrame:
	rows = [
		("us-gaap_Revenue", "Revenue", "Revenue", [120.0, 100.0, 80.0], False, False),
		("us-gaap_Revenue", "Product", None, [50.0, 40.0, 30.0], False, True),
		("us-gaap_Revenue", "Service and Other", None, [70.0, 60.0, 50.0], False, True),
		("us-gaap_CostOfGoodsAndServicesSold", "Cost of revenue", "CostOfGoodsAndServicesSold", [60.0, 50.0, 40.0], False, False),
		("us-gaap_CostOfGoodsAndServicesSold", "Product", None, [20.0, 18.0, 16.0], False, True),
		("us-gaap_CostOfGoodsAndServicesSold", "Service and Other", None, [40.0, 32.0, 24.0], False, True),
		("us-gaap_GrossProfit", "Gross margin", "GrossProfit", [60.0, 50.0, 40.0], False, False),
		("us-gaap_ResearchAndDevelopmentExpense", "Research and development", "ResearchAndDevelopmentExpenses", [12.0, 10.0, 8.0], False, False),
		("us-gaap_OperatingIncomeLoss", "Operating income", "OperatingIncomeLoss", [30.0, 25.0, 20.0], False, False),
		("us-gaap_NonoperatingIncomeExpense", "Other income (expense), net", "NonoperatingIncomeExpense", [5.0, -3.0, -2.0], False, False),
		("us-gaap_PretaxIncomeLoss", "Income before income taxes", "PretaxIncomeLoss", [35.0, 22.0, 18.0], False, False),
		("us-gaap_IncomeTaxExpenseBenefit", "Provision for income taxes", "IncomeTaxes", [7.0, 4.0, 3.6], False, False),
		("us-gaap_NetIncomeLoss", "Net income", "NetIncome", [28.0, 18.0, 14.4], False, False),
		("us-gaap_EarningsPerShareAbstract", "Earnings per share:", None, [None, None, None], True, False),
		("us-gaap_EarningsPerShareBasic", "Basic", None, [1.8, 1.3, 1.0], False, False),
		("us-gaap_WeightedAverageNumberOfSharesOutstandingBasic", "Basic", "SharesAverage", [7.4, 7.5, 7.6], False, False),
		("xbrl_noise", "XBRL noise", None, [99.0, 99.0, 99.0], False, False),
	]
	return prepare_pnl(
		pd.DataFrame(
			{
				"concept": [row[0] for row in rows],
				"label": [row[1] for row in rows],
				"standard_concept": [row[2] for row in rows],
				**{period: [row[3][index] for row in rows] for index, period in enumerate(PERIODS)},
				"abstract": [row[4] for row in rows],
				"dimension": [row[5] for row in rows],
				"is_breakdown": [False] * len(rows),
				"dimension_axis": ["srt:ProductOrServiceAxis" if row[5] else None for row in rows],
				"dimension_member": ["us-gaap_ProductMember" if row[5] and row[1] == "Product" else ("us-gaap_ServiceOtherMember" if row[5] else None) for row in rows],
				"dimension_label": [row[1] if row[5] else None for row in rows],
				"parent_concept": [None] * len(rows),
			}
		)
	)


class FormatterTests(TestCase):
	def test_context_preserves_periods_hierarchy_metrics_and_exclusions(self) -> None:
		context = format_analytical_pnl_for_scan(make_pnl())

		for period in PERIODS:
			self.assertIn(period, context)
		self.assertIn("Revenue > Product", context)
		self.assertIn("Cost of revenue > Product", context)
		self.assertIn("Research and development", context)
		self.assertIn("common-size (% revenue)", context)
		self.assertIn("2Y CAGR", context)
		self.assertIn("Gross profit (reported label: Gross margin)", context)
		self.assertIn("Gross margin ratio", context)
		self.assertIn("Pretax margin", context)
		self.assertIn("Effective tax rate", context)
		self.assertIn("abs=+$8", context)
		self.assertIn("growth=N/A", context)
		self.assertNotIn("XBRL noise", context)
		self.assertNotIn("Earnings per share:", context)
		self.assertNotIn("nan", context.casefold())
		self.assertIn("line_ref=L01", context)
		self.assertNotIn("[L01]", context)

		eps_section = context.split("## EPS and shares", 1)[1]
		self.assertNotIn("common-size", eps_section)

	def test_share_movements_use_share_units(self) -> None:
		context = format_analytical_pnl_for_scan(make_pnl())

		eps_section = context.split("## EPS and shares", 1)[1]
		self.assertIn("abs=-0.1 shares", eps_section)
		self.assertNotIn("abs=-$0.1", eps_section)

	def test_scan_suppresses_boundary_growth_and_cagr_without_changing_pnl_metrics(self) -> None:
		pnl = make_pnl()
		other_income = pnl["label"].eq("Other income (expense), net")
		pnl.loc[other_income, PERIODS[0]] = 0.0
		pnl.loc[other_income, f"yoy_growth_{PERIODS[0]}"] = -1.0
		pnl.loc[other_income, f"absolute_yoy_change_{PERIODS[0]}"] = 3.0
		pnl.loc[other_income, "two_year_cagr"] = 0.5

		row = pnl.loc[other_income].iloc[0]
		self.assertEqual(row[f"yoy_growth_{PERIODS[0]}"], -1.0)
		line = next(
			line
			for line in format_analytical_pnl_for_scan(pnl).splitlines()
			if "Other income (expense), net" in line
		)
		self.assertIn("FY26 abs=+$3, growth=N/A", line)
		self.assertIn("2Y CAGR=N/A", line)

	def test_only_provably_identical_aliases_are_deduplicated(self) -> None:
		pnl = make_pnl()
		alias = pnl.iloc[[0]].copy()
		alias["label"] = "Revenue alias"
		repeated_dimension = pnl.loc[pnl["label"].eq("Product")].iloc[[0]].copy()
		repeated_dimension["dimension_member"] = "us-gaap_AlternateProductMember"
		unidentified_aliases = pd.DataFrame(
			{
				"concept": [None, None],
				"label": ["Unidentified A", "Unidentified B"],
				"standard_concept": [None, None],
				**{period: [9.0, 9.0] for period in PERIODS},
			}
		)
		context = format_analytical_pnl_for_scan(
			pd.concat(
				[pnl, repeated_dimension, unidentified_aliases, alias],
				ignore_index=True,
			)
		)

		self.assertNotIn("source_label=Revenue alias", context)
		self.assertIn("dimension_member=us-gaap_AlternateProductMember", context)
		self.assertIn("source_label=Unidentified A", context)
		self.assertIn("source_label=Unidentified B", context)


class SchemaTests(TestCase):
	def finding(self, rank: int = 1, refs: list[str] | None = None) -> AnalyticalScanFinding:
		return AnalyticalScanFinding(
			rank=rank,
			title="Review movement",
			importance="medium",
			affected_line_refs=refs or ["L01"],
			observation="The supplied value moved.",
			why_it_matters="The movement may merit filing research.",
		)

	def test_zero_and_eight_findings_are_valid(self) -> None:
		self.assertEqual(validate_analytical_scan_result(AnalyticalScanResult(), set()).findings, [])
		result = AnalyticalScanResult(findings=[self.finding(rank) for rank in range(1, 9)])
		self.assertEqual(len(validate_analytical_scan_result(result, {"L01"}).findings), 8)

	def test_shape_and_reference_failures_are_rejected(self) -> None:
		too_many = [self.finding(index).model_dump() for index in range(1, 9)]
		too_many.append({**too_many[-1], "rank": 9})
		with self.assertRaises(AnalyticalScanError):
			validate_analytical_scan_result(
				{"findings": too_many},
				{"L01"},
			)
		with self.assertRaises(AnalyticalScanError):
			validate_analytical_scan_result(
				AnalyticalScanResult(findings=[self.finding(2)]), {"L01"}
			)
		with self.assertRaises(AnalyticalScanError):
			validate_analytical_scan_result(
				AnalyticalScanResult(findings=[self.finding(refs=["L01", "L01"])]), {"L01"}
			)
		with self.assertRaises(AnalyticalScanError):
			validate_analytical_scan_result(
				AnalyticalScanResult(findings=[self.finding(refs=["L99"])]), {"L01"}
			)
		with self.assertRaises(AnalyticalScanError):
			validate_analytical_scan_result(
				AnalyticalScanResult(
					findings=[self.finding(refs=["L01"]).model_copy(update={"investigation_questions": ["1", "2", "3", "4"]})]
				),
				{"L01"},
			)
		with self.assertRaises(AnalyticalScanError):
			validate_analytical_scan_result(
				{"findings": [self.finding().model_dump() | {"affected_line_refs": ["[L01]"]}]},
				{"L01"},
			)

	def test_bare_line_reference_is_the_only_accepted_schema_syntax(self) -> None:
		result = validate_analytical_scan_result(
			AnalyticalScanResult(findings=[self.finding()]), {"L01"}
		)
		self.assertEqual(result.findings[0].affected_line_refs, ["L01"])

	def test_extra_fields_are_forbidden(self) -> None:
		with self.assertRaises(ValidationError):
			AnalyticalScanResult.model_validate({"findings": [], "extra": True})


class ResponsesAndPersistenceTests(TestCase):
	def test_native_responses_call_and_inspectable_json(self) -> None:
		client = Mock()
		client.responses.parse.return_value = SimpleNamespace(
			output_parsed=AnalyticalScanResult()
		)
		pnl = make_pnl()

		result, metadata = run_analytical_scan(
			" msft ", pnl, client=client, model="test-model", reasoning_effort="low", run_id="r1"
		)
		call = client.responses.parse.call_args.kwargs
		self.assertEqual(call["model"], "test-model")
		self.assertEqual(call["reasoning"], {"effort": "low"})
		self.assertIs(call["text_format"], AnalyticalScanResult)
		self.assertEqual(call["input"][1]["content"], format_analytical_pnl_for_scan(pnl))
		self.assertNotIn("nan", call["input"][1]["content"].casefold())

		with TemporaryDirectory() as directory:
			path = save_analytical_scan(
				"MSFT", result, metadata, call["input"][1]["content"], directory
			)
			saved = json.loads(Path(path).read_text(encoding="utf-8"))
			self.assertEqual(saved["metadata"]["run_id"], "r1")
			self.assertEqual(saved["result"], {"findings": []})
			self.assertEqual(saved["context"], call["input"][1]["content"])


class CliIsolationTests(TestCase):
	def test_scan_only_uses_output_root_and_skips_adjustment_pipeline(self) -> None:
		pnl = make_pnl()
		with TemporaryDirectory() as directory:
			with (
				patch("smrik_fund.main.build_analytical_pnl", return_value=pnl),
				patch("smrik_fund.main.run_analytical_scan", return_value=(AnalyticalScanResult(), {"run_id": "r1", "model": "m"})),
				patch("smrik_fund.main._run_adjustment_analysis") as adjustments,
			):
				result = CliRunner().invoke(app, ["analyze", "MSFT", "--scan", "--output-root", directory])

			self.assertEqual(result.exit_code, 0, result.output)
			adjustments.assert_not_called()
			output = Path(directory) / "MSFT" / "03_output"
			self.assertTrue((output / "analytical_pnl.csv").exists())
			self.assertTrue((output / "reconciliation_checks.csv").exists())
			self.assertEqual(len(list((output / "analysis").glob("analytical_scan_*.json"))), 1)
			self.assertFalse((output / "adjustment_history.csv").exists())
			self.assertFalse((output / "adjusted_pnl.csv").exists())

	def test_scan_and_adjustments_are_mutually_exclusive(self) -> None:
		result = CliRunner().invoke(app, ["analyze", "MSFT", "--scan", "--adjustments"])
		self.assertNotEqual(result.exit_code, 0)
		self.assertIn("cannot be combined", result.output)
