from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import pandas as pd

from smrik_fund.ingestion.adjustments import apply_adjustments, derive_line_delta
from smrik_fund.ingestion.line_details import (
	attach_model_rows,
	build_line_details,
	load_reported_details,
	save_reported_details,
	validate_reported_details,
)
from smrik_fund.ingestion.reconciliation import reconcile_pnl
from smrik_fund.main import _rebuild_adjusted_outputs, _run_adjustment_analysis

PERIOD = "2026-06-30 (FY)"


def make_pnl() -> pd.DataFrame:
	return pd.DataFrame(
		{
			"label": ["Revenue", "Other income (expense), net"],
			"standard_concept": ["Revenue", "NonoperatingIncomeExpense"],
			PERIOD: [100.0, 10_697.0],
		}
	)


def make_statement_pnl() -> pd.DataFrame:
	period_2025 = "2025-06-30 (FY)"
	return pd.DataFrame(
		{
			"label": [
				"Revenue",
				"Cost of revenue",
				"Gross profit",
				"Research and development",
				"Sales and marketing",
				"General and administrative",
				"Operating income",
				"Other income (expense), net",
				"Income before income taxes",
				"Provision for income taxes",
				"Net income",
			],
			"standard_concept": [
				"Revenue",
				"CostOfGoodsAndServicesSold",
				"GrossProfit",
				"ResearchAndDevelopmentExpenses",
				"SellingAndMarketingExpense",
				"GeneralAndAdministrativeExpense",
				"OperatingIncomeLoss",
				"NonoperatingIncomeExpense",
				"PretaxIncomeLoss",
				"IncomeTaxes",
				"NetIncome",
			],
			PERIOD: [1000.0, 600.0, 400.0, 100.0, 50.0, 50.0, 200.0, 10.0, 210.0, 42.0, 168.0],
			period_2025: [900.0, 540.0, 360.0, 90.0, 45.0, 45.0, 180.0, 5.0, 185.0, 40.0, 145.0],
		}
	)


def make_reported_detail(*, source_snapshot_id: str = "sec:0000950170-25-100235", amount: float = 1300.0) -> pd.DataFrame:
	return pd.DataFrame(
		[
			{
				"parent_row_key": "standard_concept:IncomeTaxes",
				"detail_row_key": "uncertain-tax-position-interest",
				"period": "2025-06-30 (FY)",
				"label": "Interest expense related to uncertain tax positions",
				"amount": amount,
				"source_ref": "data/MSFT/01_source/edgar/filings/0000950170-25-100235.txt",
				"breakdown_group": "reported",
				"source_status": "SUPPORTED",
				"source_snapshot_id": source_snapshot_id,
				"filing_accession": "0000950170-25-100235",
				"source_locator": "source text line 2485",
				"evidence_ref": "filing:0000950170-25-100235:line:2485",
				"unit": "USD",
				"scale": "millions",
				"source_qualification": "net of income tax benefits",
			}
		]
	)


def make_source_context(detail: pd.DataFrame | None = None) -> dict[str, dict[str, object]]:
	row = (detail if detail is not None else make_reported_detail()).iloc[0]
	source_path = Path(__file__).parents[1] / row["source_ref"].split("#", 1)[0]
	return {
		row["evidence_ref"]: {
			"source_snapshot_id": row["source_snapshot_id"],
			"filing_accession": row["filing_accession"],
			"source_ref": row["source_ref"],
			"source_locator": row["source_locator"],
			"parent_row_key": row["parent_row_key"],
			"period": row["period"],
			"unit": row["unit"],
			"scale": row["scale"],
			"source_qualification": row["source_qualification"],
			"amount": row["amount"],
			"source_status": row["source_status"],
			"source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
			"text": "The provision for income taxes for fiscal years 2025, 2024, and 2023 included interest expense related to uncertain tax positions of $1.3 billion, $1.5 billion, and $918 million, respectively, net of income tax benefits.",
		}
	}


def make_adjustment(
	amount: float = 6_500.0,
	*,
	adjustment_id: str = "A0030",
	target_line: str = "Other income (expense), net",
	target_row_key: str = "standard_concept:NonoperatingIncomeExpense",
	item_key: str = "openai-dilution-gain",
	sub_item: str = "OpenAI investment net gain",
) -> pd.DataFrame:
	identity = {
		"identity_version": "economic-adjustment-v2",
		"company": "MSFT",
		"fiscal_period": PERIOD,
		"target_row_key": target_row_key,
		"item_key": item_key,
	}
	state = {
		"item_amount": amount,
		"item_effect_on_line": "increased_line",
		"amount_basis": "disclosed",
	}
	return pd.DataFrame(
		[
			{
				"adjustment_id": adjustment_id,
				"version": 1,
				"status": "approved",
				"run_id": "line-detail-test",
				"identity_version": "economic-adjustment-v2",
				"candidate_identity": json.dumps(identity, sort_keys=True),
				"candidate_state": json.dumps(state, sort_keys=True),
				"target_row_key": identity["target_row_key"],
				"target_line": target_line,
				"sub_item": sub_item,
				"period": PERIOD,
				"item_amount": amount,
				"item_effect_on_line": "increased_line",
				"line_delta": derive_line_delta(amount, "increased_line"),
			}
		]
	)


class LineDetailTests(TestCase):
	def test_segment_breakdown_is_signed_and_has_explicit_remaining(self) -> None:
		pnl = make_pnl()
		before = pnl.copy(deep=True)
		segments = pd.DataFrame(
			[
				{
					"segment_ref": "S01",
					"fact_id": "fact-alpha",
					"segment_label": "Alpha",
					"metric": "Revenue",
					"period": PERIOD,
					"numeric_value": 60.0,
					"fact_status": "PASS",
				},
				{
					"segment_ref": "S02",
					"fact_id": "fact-beta",
					"segment_label": "Beta",
					"metric": "Revenue",
					"period": PERIOD,
					"numeric_value": 30.0,
					"fact_status": "PASS",
				},
			]
		)
		rows = build_line_details(pnl, segments=segments)
		details = rows[rows["row_type"] == "detail"]
		remaining = rows[rows["row_type"] == "remaining"].iloc[0]
		self.assertEqual(details["amount"].tolist(), [60.0, 30.0])
		self.assertEqual(details["detail_row_key"].tolist(), ["S01", "S02"])
		self.assertEqual(details["source_ref"].tolist(), ["fact-alpha", "fact-beta"])
		self.assertNotIn("parent_reported_value", rows)
		self.assertNotIn("parent_adjusted_value", rows)
		self.assertTrue(details["line_delta"].eq(0).all())
		self.assertEqual(remaining["breakdown_group"], "segment")
		self.assertEqual(remaining["amount"], 10.0)
		self.assertTrue(rows.loc[rows["row_type"] == "parent", "included_in_subtotals"].all())
		pd.testing.assert_frame_equal(pnl, before)

	def test_normalization_and_segment_groups_do_not_mix(self) -> None:
		segments = pd.DataFrame(
			[
				{
					"segment_ref": "S01",
					"fact_id": "fact-alpha",
					"segment_label": "Alpha",
					"metric": "Revenue",
					"period": PERIOD,
					"numeric_value": 90.0,
					"fact_status": "PASS",
				}
			]
		)
		adjustments = pd.concat(
			[
				make_adjustment(
					20.0,
					adjustment_id="A0031",
					target_line="Revenue",
					target_row_key="standard_concept:Revenue",
					item_key="revenue-normalization",
					sub_item="revenue-normalization",
				),
				make_adjustment(),
			],
			ignore_index=True,
		)
		rows = build_line_details(make_pnl(), segments, adjustments)
		remainders = rows[rows["row_type"] == "remaining"]
		revenue_remainders = remainders[remainders["parent_row_key"].eq("standard_concept:Revenue")]
		self.assertEqual(
			revenue_remainders.loc[revenue_remainders["breakdown_group"].eq("segment"), "amount"].iloc[0],
			10.0,
		)
		self.assertEqual(
			revenue_remainders.loc[revenue_remainders["breakdown_group"].eq("normalization"), "amount"].iloc[0],
			80.0,
		)
		other_parent = rows[
			(rows["row_type"] == "parent")
			& rows["parent_row_key"].eq("standard_concept:NonoperatingIncomeExpense")
		].iloc[0]
		self.assertEqual(other_parent["amount"], 10_697.0)
		self.assertEqual(other_parent["adjusted_value"], 4_197.0)
		normalization = rows[
			(rows["row_type"] == "detail")
			& rows["breakdown_group"].eq("normalization")
			& rows["parent_row_key"].eq("standard_concept:NonoperatingIncomeExpense")
		].iloc[0]
		self.assertEqual(normalization["amount"], 6_500.0)
		self.assertEqual(normalization["line_delta"], -6_500.0)

	def test_missing_segment_value_keeps_remaining_missing(self) -> None:
		segments = pd.DataFrame(
			[
				{
					"segment_ref": "S01",
					"fact_id": "fact-alpha",
					"segment_label": "Unknown",
					"metric": "Revenue",
					"period": PERIOD,
					"numeric_value": None,
					"reported_value": None,
					"fact_status": "PASS",
				}
			]
		)
		rows = build_line_details(make_pnl(), segments=segments)
		remaining = rows[rows["row_type"] == "remaining"].iloc[0]
		self.assertTrue(pd.isna(remaining["amount"]))

	def test_reported_detail_is_durable_idempotent_and_keeps_parent_unchanged(self) -> None:
		with TemporaryDirectory() as temporary_directory:
			path = Path(temporary_directory) / "reported_details.csv"
			detail = make_reported_detail()
			context = make_source_context(detail)
			source_text = (
				Path(__file__).parents[1]
				/ "data/MSFT/01_source/edgar/filings/0000950170-25-100235.txt"
			).read_text(encoding="utf-8")
			self.assertIn(
				"The provision for income taxes for fiscal years 2025, 2024, and 2023 included interest expense",
				source_text,
			)
			first = save_reported_details(path, detail, source_context=context)
			second = save_reported_details(path, detail, source_context=context)
			self.assertEqual(len(first), 1)
			self.assertEqual(len(second), 1)
			loaded = load_reported_details(path, source_context=context)
			self.assertEqual(loaded.iloc[0]["amount"], 1300.0)
			self.assertEqual(loaded.iloc[0]["scale"], "millions")
			rows = build_line_details(
				make_statement_pnl(), reported_details=loaded, source_context=context
			)
			detail_row = rows.loc[rows["row_type"].eq("detail")].iloc[0]
			parent = rows.loc[rows["row_type"].eq("parent")].iloc[0]
			self.assertEqual(detail_row["line_delta"], 0.0)
			self.assertFalse(bool(detail_row["included_in_subtotals"]))
		self.assertEqual(parent["amount"], 40.0)
		self.assertEqual(parent["adjusted_value"], 40.0)

	def test_reported_detail_survives_normal_rebuild_and_is_not_a_model_parent(self) -> None:
		with TemporaryDirectory() as temporary_directory:
			root = Path(temporary_directory)
			output = root / "MSFT" / "03_output"
			output.mkdir(parents=True)
			detail = make_reported_detail()
			context = make_source_context(detail)
			save_reported_details(output / "reported_details.csv", detail, source_context=context)
			(output / "reported_details_context.json").write_text(
				json.dumps(context), encoding="utf-8"
			)
			_rebuild_adjusted_outputs("MSFT", root, make_statement_pnl())
			rows = pd.read_csv(output / "line_details.csv")
			child = rows.loc[rows["detail_row_key"].eq("uncertain-tax-position-interest")].iloc[0]
			self.assertEqual(child["amount"], 1300.0)
			self.assertEqual(child["breakdown_group"], "reported")
			model = pd.read_csv(output / "adjusted_pnl.csv")
			self.assertEqual(
				model.loc[model["label"].eq("Provision for income taxes"), PERIOD].iloc[0],
				42.0,
			)
			self.assertTrue(bool(model.loc[model["label"].eq(child["label"]), "is_breakdown"].iloc[0]))

	def test_reported_detail_survives_integrated_run_rebuild(self) -> None:
		with TemporaryDirectory() as temporary_directory:
			root = Path(temporary_directory)
			output = root / "MSFT" / "03_output"
			output.mkdir(parents=True)
			detail = make_reported_detail()
			context = make_source_context(detail)
			save_reported_details(output / "reported_details.csv", detail, source_context=context)
			(output / "reported_details_context.json").write_text(
				json.dumps(context), encoding="utf-8"
			)
			_run_adjustment_analysis(
				"MSFT",
				make_statement_pnl(),
				"test-model",
				"high",
				output_root=root,
				filing=object(),
				findings=[],
			)
			rows = pd.read_csv(output / "line_details.csv")
			self.assertEqual(
				rows.loc[
					rows["detail_row_key"].eq("uncertain-tax-position-interest"),
					"amount",
				].iloc[0],
				1300.0,
			)

	def test_reported_detail_rejects_conflicting_source_and_normalization_delta(self) -> None:
		with TemporaryDirectory() as temporary_directory:
			path = Path(temporary_directory) / "reported_details.csv"
			detail = make_reported_detail()
			context = make_source_context(detail)
			save_reported_details(path, detail, source_context=context)
			changed_source = make_reported_detail(source_snapshot_id="sec:new")
			changed_context = make_source_context(changed_source)
			with self.assertRaisesRegex(ValueError, "source changed"):
				save_reported_details(path, changed_source, source_context=changed_context)
			invalid = make_reported_detail()
			invalid["line_delta"] = -1.0
			with self.assertRaisesRegex(ValueError, "line_delta"):
				save_reported_details(path, invalid, source_context=context)

	def test_reported_detail_requires_resolvable_source_context(self) -> None:
		detail = make_reported_detail()
		context = make_source_context(detail)
		self.assertEqual(len(validate_reported_details(detail, source_context=context)), 1)
		with self.assertRaisesRegex(ValueError, "complete source context"):
			validate_reported_details(detail)
		with TemporaryDirectory() as temporary_directory, self.assertRaisesRegex(
			ValueError, "complete source context"
		):
			save_reported_details(Path(temporary_directory) / "details.csv", detail)
		for field, value in (
			("amount", 99_000_000_000.0),
			("period", "2024-06-30 (FY)"),
			("source_qualification", ""),
		):
			wrong = detail.copy()
			wrong.loc[0, field] = value
			with self.assertRaises(ValueError):
				validate_reported_details(wrong, source_context=context)
		invalid = detail.copy()
		invalid.loc[0, "evidence_ref"] = "no-such-evidence"
		invalid.loc[0, "filing_accession"] = "not-an-accession"
		invalid.loc[0, "source_locator"] = "missing-locator"
		invalid.loc[0, "unit"] = "widgets"
		with self.assertRaises(ValueError):
			validate_reported_details(invalid, source_context=context)

		for field, value in (
			("period", "2024-06-30 (FY)"),
			("parent_row_key", "standard_concept:Revenue"),
			("unit", "EUR"),
			("scale", "raw units"),
		):
			wrong = detail.copy()
			wrong.loc[0, field] = value
			with self.assertRaises(ValueError):
				validate_reported_details(wrong, source_context=context)

	def test_reported_detail_rejects_changed_source_content(self) -> None:
		detail = make_reported_detail()
		with TemporaryDirectory() as temporary_directory:
			source_path = Path(temporary_directory) / "0000950170-25-100235.txt"
			source_path.write_bytes(
				(Path(__file__).parents[1] / detail.loc[0, "source_ref"]).read_bytes()
			)
			detail.loc[0, "source_ref"] = str(source_path)
			context = make_source_context(detail)
			source_path.write_text(
				source_path.read_text(encoding="utf-8").replace("$1.3 billion", "$1.4 billion"),
				encoding="utf-8",
			)
			with self.assertRaisesRegex(ValueError, "content changed"):
				validate_reported_details(detail, source_context=context)

	def test_reported_detail_rejects_invalid_period_and_valid_shaped_missing_parent(self) -> None:
		invalid_period = make_reported_detail()
		invalid_period.loc[0, "period"] = "2024-06-30 (FY)"
		with self.assertRaises(ValueError):
			build_line_details(make_statement_pnl(), reported_details=invalid_period)
		missing_parent = make_reported_detail()
		missing_parent.loc[0, "parent_row_key"] = "standard_concept:DoesNotExist"
		with self.assertRaises((ValueError, KeyError)):
			build_line_details(make_statement_pnl(), reported_details=missing_parent)

	def test_reported_detail_write_failure_preserves_prior_bytes(self) -> None:
		with TemporaryDirectory() as temporary_directory:
			path = Path(temporary_directory) / "reported_details.csv"
			detail = make_reported_detail()
			context = make_source_context(detail)
			save_reported_details(path, detail, source_context=context)
			before = path.read_bytes()
			with (
				patch("smrik_fund.ingestion.adjustments.os.replace", side_effect=OSError),
				self.assertRaises(OSError),
			):
				save_reported_details(path, detail, source_context=context)
			self.assertEqual(path.read_bytes(), before)

	def test_reported_breakdown_groups_remain_separate(self) -> None:
		first = make_reported_detail()
		second = make_reported_detail()
		second.loc[0, "detail_row_key"] = "uncertain-tax-position-interest-context"
		second.loc[0, "breakdown_group"] = "classification"
		rows = build_line_details(
			make_statement_pnl(),
			reported_details=pd.concat([first, second], ignore_index=True),
			source_context=make_source_context(first),
		)
		details = rows.loc[rows["row_type"].eq("detail")]
		self.assertEqual(set(details["breakdown_group"]), {"reported", "classification"})
		parent = rows.loc[rows["row_type"].eq("parent")].iloc[0]
		self.assertEqual(parent["amount"], 40.0)
		self.assertEqual(parent["adjusted_value"], 40.0)

	def test_adjusted_rebuild_persists_line_detail_view(self) -> None:
		with TemporaryDirectory() as temporary_directory:
			root = Path(temporary_directory)
			output = root / "MSFT" / "03_output"
			output.mkdir(parents=True)
			history = pd.concat(
				[
					make_adjustment(
						20.0,
						adjustment_id="A0031",
						target_line="Revenue",
						target_row_key="standard_concept:Revenue",
						item_key="revenue-normalization",
						sub_item="revenue-normalization",
					),
					make_adjustment(),
				],
				ignore_index=True,
			)
			history.to_csv(output / "adjustment_history.csv", index=False)
			pd.DataFrame(
				[
					{
						"segment_axis": "StatementBusinessSegmentsAxis",
						"segment_member": "Alpha",
						"segment_ref": "S01",
						"fact_id": "fact-alpha",
						"segment_label": "Alpha",
						"metric": "Revenue",
						"period": PERIOD,
						"reported_value": 90.0,
						"numeric_value": 90.0,
						"fact_status": "PASS",
					}
				]
			).to_csv(output / "segment_analytics.csv", index=False)
			pd.DataFrame(
				columns=[
					"metric",
					"period",
					"reported_segment_total",
					"reported_consolidated_total",
					"residual",
					"status",
				]
			).to_csv(output / "segment_reconciliation_checks.csv", index=False)
			_rebuild_adjusted_outputs("MSFT", root, make_pnl())
			rows = pd.read_csv(output / "line_details.csv")
			revenue = rows[rows["parent_row_key"].eq("standard_concept:Revenue")]
			self.assertEqual(
				set(revenue.loc[revenue["row_type"] == "detail", "breakdown_group"]),
				{"segment", "normalization"},
			)
			self.assertEqual(
				revenue.loc[
					(revenue["row_type"] == "remaining")
					& (revenue["breakdown_group"] == "segment"),
					"amount",
				].iloc[0],
				10.0,
			)
			self.assertEqual(
				revenue.loc[
					(revenue["row_type"] == "remaining")
					& (revenue["breakdown_group"] == "normalization"),
					"amount",
				].iloc[0],
				80.0,
			)
			other = rows[rows["parent_row_key"].eq("standard_concept:NonoperatingIncomeExpense")]
			self.assertEqual(other.loc[other["row_type"].eq("detail"), "amount"].iloc[0], 6_500.0)
			self.assertEqual(other.loc[other["row_type"].eq("parent"), "adjusted_value"].iloc[0], 4_197.0)
			model = pd.read_csv(output / "adjusted_pnl.csv")
			self.assertEqual(
				model.loc[model["label"].eq("Other income (expense), net"), PERIOD].iloc[0],
				4_197.0,
			)
			self.assertEqual(
				model.loc[model["label"].eq("OpenAI investment net gain"), PERIOD].iloc[0],
				6_500.0,
			)
			self.assertTrue(
				bool(model.loc[model["label"].eq("OpenAI investment net gain"), "is_breakdown"].iloc[0])
			)
			self.assertEqual(
				model.loc[model["label"].eq("Alpha"), PERIOD].iloc[0],
				90.0,
			)

	def test_model_inserts_children_without_changing_parents(self) -> None:
		pnl = make_pnl()
		before = pnl.copy(deep=True)
		pnl["dimension"] = False
		pnl["is_breakdown"] = False
		segments = pd.DataFrame(
			[
				{
					"segment_ref": "S01",
					"fact_id": "fact-alpha",
					"segment_label": "Alpha",
					"metric": "Revenue",
					"period": PERIOD,
					"numeric_value": 60.0,
					"fact_status": "PASS",
				},
				{
					"segment_ref": "S02",
					"fact_id": "fact-beta",
					"segment_label": "Beta",
					"metric": "Revenue",
					"period": PERIOD,
					"numeric_value": 30.0,
					"fact_status": "PASS",
				},
			]
		)
		details = build_line_details(pnl, segments=segments, adjustments=make_adjustment())
		model = attach_model_rows(pnl, details)
		labels = model["label"].tolist()
		self.assertEqual(
			labels,
			[
				"Revenue",
				"Alpha",
				"Beta",
				"Remaining / unexplained",
				"Other income (expense), net",
				"OpenAI investment net gain",
			],
		)
		self.assertEqual(model.loc[model["label"].eq("Revenue"), PERIOD].iloc[0], 100.0)
		self.assertEqual(model.loc[model["label"].eq("Other income (expense), net"), PERIOD].iloc[0], 10_697.0)
		self.assertEqual(model.loc[model["label"].eq("OpenAI investment net gain"), PERIOD].iloc[0], 6_500.0)
		self.assertTrue(model.loc[model["label"].eq("Alpha"), "is_breakdown"].all())
		self.assertTrue(model.loc[model["label"].eq("OpenAI investment net gain"), "standard_concept"].isna().all())
		self.assertNotIn("OpenAI investment net gain", before["label"].tolist())
		pd.testing.assert_frame_equal(pnl[before.columns], before)

	def test_line_item_added_line_and_segment_children_on_working_statement(self) -> None:
		periods = (
			"2026-06-30 (FY)",
			"2025-06-30 (FY)",
			"2024-06-30 (FY)",
		)
		reported = pd.DataFrame(
			{
				"label": [
					"Revenue",
					"Cost of revenue",
					"Gross profit",
					"Research and development",
					"Sales and marketing",
					"General and administrative",
					"Operating income",
					"Other income (expense), net",
					"Income before income taxes",
					"Provision for income taxes",
					"Net income",
				],
				"standard_concept": [
					"Revenue",
					"CostOfGoodsAndServicesSold",
					"GrossProfit",
					"ResearchAndDevelopmentExpenses",
					"SellingAndMarketingExpense",
					"GeneralAndAdministrativeExpense",
					"OperatingIncomeLoss",
					"NonoperatingIncomeExpense",
					"PretaxIncomeLoss",
					"IncomeTaxes",
					"NetIncome",
				],
				periods[0]: [120.0, 30.0, 90.0, 20.0, 10.0, 5.0, 55.0, 5.0, 60.0, 12.0, 48.0],
				periods[1]: [100.0, 25.0, 75.0, 18.0, 9.0, 4.0, 44.0, -2.0, 42.0, 8.4, 33.6],
				periods[2]: [80.0, 20.0, 60.0, 16.0, 8.0, 3.0, 33.0, -1.0, 32.0, 6.4, 25.6],
			}
		)
		before = reported.copy(deep=True)
		history = make_adjustment(
			3.0,
			target_line="Other income (expense), net",
			target_row_key="standard_concept:NonoperatingIncomeExpense",
			item_key="one-time-gain",
			sub_item="Disclosed one-time gain",
		)
		adjusted = apply_adjustments(reported, history)
		pd.testing.assert_frame_equal(reported, before)
		self.assertEqual(
			adjusted.loc[
				adjusted["label"].eq("Other income (expense), net"), periods[0]
			].iloc[0],
			2.0,
		)
		self.assertEqual(
			before.loc[
				before["label"].eq("Other income (expense), net"), periods[0]
			].iloc[0],
			5.0,
		)
		checks = reconcile_pnl(adjusted)
		self.assertTrue((checks["status"] == "PASS").all(), checks.to_string())
		segments = pd.DataFrame(
			[
				{
					"segment_ref": "S01",
					"fact_id": "fact-alpha",
					"segment_label": "Alpha",
					"metric": "Revenue",
					"period": periods[0],
					"numeric_value": 70.0,
					"fact_status": "PASS",
				},
				{
					"segment_ref": "S02",
					"fact_id": "fact-beta",
					"segment_label": "Beta",
					"metric": "Revenue",
					"period": periods[0],
					"numeric_value": 40.0,
					"fact_status": "PASS",
				},
			]
		)
		details = build_line_details(reported, segments=segments, adjustments=history)
		model = attach_model_rows(adjusted, details)
		gain = model.loc[model["label"].eq("Disclosed one-time gain")].iloc[0]
		self.assertTrue(bool(gain["is_breakdown"]))
		self.assertEqual(gain["included_in_subtotals"], False)
		self.assertEqual(gain[periods[0]], 3.0)
		alpha = model.loc[model["label"].eq("Alpha")].iloc[0]
		self.assertTrue(bool(alpha["is_breakdown"]))
		self.assertEqual(alpha["included_in_subtotals"], False)
		self.assertEqual(alpha[periods[0]], 70.0)
		self.assertEqual(
			model.loc[model["label"].eq("Revenue"), periods[0]].iloc[0],
			120.0,
		)
		self.assertNotIn("Disclosed one-time gain", before["label"].tolist())
		self.assertNotIn("Alpha", before["label"].tolist())
