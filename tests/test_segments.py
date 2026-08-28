from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

import pandas as pd

from smrik_fund.ingestion.analytical_scan import (
	AnalyticalScanError,
	AnalyticalScanResult,
	format_analytical_pnl_for_scan,
	run_analytical_scan,
	validate_analytical_scan_result,
)
from smrik_fund.ingestion.segments import (
	build_segment_enrichment,
	extract_segment_facts,
	save_segment_analytics,
	save_segment_reconciliation,
)

PERIODS = (
	"2026-06-30 (FY)",
	"2025-06-30 (FY)",
	"2024-06-30 (FY)",
)
AXIS = "us-gaap_StatementBusinessSegmentsAxis"
MEMBERS = {
	"alpha": ("msft:AlphaMember", "Alpha"),
	"beta": ("msft:BetaMember", "Beta"),
	"gamma": ("msft:GammaMember", "Gamma"),
}
VALUES = {
	"Revenue": {
		"alpha": [120.0, 100.0, 80.0],
		"beta": [100.0, 90.0, 80.0],
		"gamma": [80.0, 90.0, 40.0],
	},
	"OperatingIncomeLoss": {
		"alpha": [60.0, 50.0, 40.0],
		"beta": [35.0, 30.0, 25.0],
		"gamma": [20.0, 25.0, 15.0],
	},
}
CONSOLIDATED = {
	"Revenue": [300.0, 280.0, 200.0],
	"OperatingIncomeLoss": [115.0, 105.0, 80.0],
}


class FakeFacts:
	def __init__(self, frame: pd.DataFrame) -> None:
		self.frame = frame

	def to_dataframe(self) -> pd.DataFrame:
		return self.frame.copy(deep=True)


class FakeFiling:
	accession_number = "0000000000-26-000001"
	filing_date = "2026-08-01"
	form = "10-K"
	filing_url = "https://example.test/filing"

	def __init__(self, frame: pd.DataFrame) -> None:
		self.xbrl_object = SimpleNamespace(facts=FakeFacts(frame))

	def xbrl(self) -> SimpleNamespace:
		return self.xbrl_object


def make_pnl() -> pd.DataFrame:
	return pd.DataFrame(
		{
			"concept": ["us-gaap_Revenue", "us-gaap_OperatingIncomeLoss"],
			"label": ["Revenue", "Operating income"],
			"standard_concept": ["Revenue", "OperatingIncomeLoss"],
			"abstract": [False, False],
			"dimension": [False, False],
			**{
				period: [CONSOLIDATED[metric][index] for metric in CONSOLIDATED]
				for index, period in enumerate(PERIODS)
			},
		}
	)


def make_facts() -> pd.DataFrame:
	rows: list[dict[str, object]] = []
	for metric, members in VALUES.items():
		concept = "us-gaap_Revenue" if metric == "Revenue" else "us-gaap_OperatingIncomeLoss"
		for member_key, values in members.items():
			member, label = MEMBERS[member_key]
			for index, value in enumerate(values):
				rows.append(
					{
						"concept": concept,
						"standard_concept": metric,
						"label": metric,
						"value": value,
						"numeric_value": value,
						"unit_ref": "USD",
						"currency": "USD",
						"period_type": "duration",
						"period_end": PERIODS[index][:10],
						"period_start": f"{int(PERIODS[index][:4]) - 1}-07-01",
						"fiscal_year": int(PERIODS[index][:4]),
						"fiscal_period": "FY",
						"fact_id": f"{metric}-{member_key}-{index}",
						"context_ref": f"ctx-{metric}-{member_key}-{index}",
						"dim_StatementBusinessSegmentsAxis": member,
						"dimension_member_label": label,
					}
				)
	return pd.DataFrame(rows)


class SegmentAnalyticsTests(TestCase):
	def setUp(self) -> None:
		self.pnl = make_pnl()
		self.original = self.pnl.copy(deep=True)
		self.filing = FakeFiling(make_facts())

	def test_extract_preserves_raw_values_and_filing_provenance(self) -> None:
		facts = extract_segment_facts(self.filing, periods=PERIODS)
		self.assertEqual(len(facts), 18)
		self.assertTrue(facts["fact_status"].eq("PASS").all())
		row = facts[
			facts["fact_id"].eq("Revenue-alpha-0")
		].iloc[0]
		self.assertEqual(row["reported_value"], 120.0)
		self.assertEqual(row["label"], "Revenue")
		self.assertEqual(row["dimension_member_label"], "Alpha")
		self.assertEqual(row["context_ref"], "ctx-Revenue-alpha-0")
		self.assertEqual(row["accession"], FakeFiling.accession_number)
		self.assertEqual(row["filing_date"], FakeFiling.filing_date)

	def test_metrics_refs_reconciliation_and_pnl_state(self) -> None:
		segments, checks = build_segment_enrichment(self.filing, self.pnl)
		self.assertEqual(len(segments), 18)
		self.assertEqual(set(segments["segment_ref"]), {f"S{index:02d}" for index in range(1, 7)})
		self.assertTrue(checks["status"].eq("PASS").all())
		self.assertTrue((checks["residual"].abs() <= 0.01).all())
		alpha = segments[
			segments["fact_id"].eq("Revenue-alpha-0")
		].iloc[0]
		self.assertAlmostEqual(alpha["absolute_yoy_change"], 20.0)
		self.assertAlmostEqual(alpha["yoy_growth"], 0.2)
		self.assertAlmostEqual(alpha["revenue_share"], 0.4)
		self.assertAlmostEqual(alpha["revenue_share_change_bps"], 428.5714286)
		self.assertAlmostEqual(alpha["revenue_growth_contribution"], 1.0)
		alpha_op = segments[
			segments["fact_id"].eq("OperatingIncomeLoss-alpha-0")
		].iloc[0]
		self.assertAlmostEqual(alpha_op["operating_margin"], 0.5)
		self.assertAlmostEqual(alpha_op["operating_margin_bps_change"], 0.0)
		self.assertAlmostEqual(alpha_op["operating_income_growth_contribution"], 1.0)
		pd.testing.assert_frame_equal(self.pnl, self.original)

	def test_nonpositive_growth_is_guarded(self) -> None:
		facts = make_facts()
		facts.loc[
			facts["fact_id"].eq("Revenue-alpha-1"), "numeric_value"
		] = 0.0
		facts.loc[facts["fact_id"].eq("Revenue-alpha-1"), "value"] = 0.0
		segments, _ = build_segment_enrichment(FakeFiling(facts), self.pnl)
		row = segments[segments["fact_id"].eq("Revenue-alpha-0")].iloc[0]
		self.assertAlmostEqual(row["absolute_yoy_change"], 120.0)
		self.assertTrue(pd.isna(row["yoy_growth"]))
		self.assertAlmostEqual(row["revenue_share_change_bps"], 4000.0)
		self.assertTrue(pd.isna(row["revenue_growth_contribution"]))

	def test_missing_and_sign_change_growth_are_guarded(self) -> None:
		facts = make_facts()
		facts.loc[facts["fact_id"].eq("Revenue-alpha-1"), ["value", "numeric_value"]] = None
		facts.loc[facts["fact_id"].eq("OperatingIncomeLoss-beta-0"), ["value", "numeric_value"]] = -5.0
		segments, _ = build_segment_enrichment(FakeFiling(facts), self.pnl)
		missing = segments[segments["fact_id"].eq("Revenue-alpha-0")].iloc[0]
		self.assertTrue(pd.isna(missing["yoy_growth"]))
		self.assertTrue(pd.isna(missing["revenue_growth_contribution"]))
		sign_change = segments[segments["fact_id"].eq("OperatingIncomeLoss-beta-0")].iloc[0]
		self.assertAlmostEqual(sign_change["absolute_yoy_change"], -35.0)
		self.assertTrue(pd.isna(sign_change["yoy_growth"]))
		self.assertTrue(pd.isna(sign_change["operating_income_growth_contribution"]))

	def test_refs_are_stable_when_fact_order_changes(self) -> None:
		first, _ = build_segment_enrichment(self.filing, self.pnl)
		reversed_filing = FakeFiling(make_facts().iloc[::-1].reset_index(drop=True))
		second, _ = build_segment_enrichment(reversed_filing, self.pnl)
		first_refs = first[["segment_member", "metric", "segment_ref"]].drop_duplicates()
		second_refs = second[["segment_member", "metric", "segment_ref"]].drop_duplicates()
		pd.testing.assert_frame_equal(
			first_refs.sort_values(first_refs.columns.tolist()).reset_index(drop=True),
			second_refs.sort_values(second_refs.columns.tolist()).reset_index(drop=True),
		)

	def test_unresolved_candidates_never_reconcile_or_get_refs(self) -> None:
		facts = make_facts()
		duplicate = facts[facts["fact_id"].eq("Revenue-alpha-0")].copy()
		duplicate["fact_id"] = "Revenue-alpha-0-duplicate"
		duplicate["value"] = 999.0
		duplicate["numeric_value"] = 999.0
		facts = pd.concat([facts, duplicate], ignore_index=True)
		facts.loc[facts["fact_id"].eq("Revenue-beta-0"), "dim_OtherAxis"] = "other:Member"
		facts.loc[facts["fact_id"].eq("Revenue-gamma-0"), "dimension_member_label"] = None
		segments, checks = build_segment_enrichment(FakeFiling(facts), self.pnl)
		bad = segments[segments["fact_id"].isin({
			"Revenue-alpha-0", "Revenue-alpha-0-duplicate", "Revenue-beta-0", "Revenue-gamma-0"
		})]
		self.assertTrue(bad["fact_status"].eq("UNRESOLVED").all())
		self.assertTrue(bad["segment_ref"].eq("").all())
		revenue_2026 = checks[(checks["metric"].eq("Revenue")) & checks["period"].eq(PERIODS[0])].iloc[0]
		self.assertEqual(revenue_2026["status"], "UNRESOLVED")
		self.assertTrue(pd.isna(revenue_2026["residual"]))

	def test_residual_is_explicit_and_not_a_plug(self) -> None:
		pnl = self.pnl.copy(deep=True)
		pnl.loc[pnl["standard_concept"].eq("Revenue"), PERIODS[0]] = 301.0
		segments, checks = build_segment_enrichment(self.filing, pnl)
		check = checks[(checks["metric"].eq("Revenue")) & checks["period"].eq(PERIODS[0])].iloc[0]
		self.assertEqual(check["status"], "NOT_DIRECTLY_COMPARABLE")
		self.assertEqual(check["residual"], 1.0)
		self.assertEqual(check["reported_segment_total"], 300.0)
		self.assertEqual(check["reported_consolidated_total"], 301.0)
		self.assertTrue(segments["reported_value"].isin([80.0, 90.0, 100.0, 120.0]).any())

	def test_writers_and_compact_scan_context(self) -> None:
		segments, checks = build_segment_enrichment(self.filing, self.pnl)
		context = format_analytical_pnl_for_scan(self.pnl, segments)
		self.assertIn("## Reportable segment results", context)
		self.assertIn("line_ref=S01", context)
		self.assertIn("revenue growth contribution", context)
		self.assertIn("operating-income growth contribution", context)
		self.assertNotIn("fact_id", context)
		self.assertNotIn("ctx-Revenue-alpha-0", context)
		validate_analytical_scan_result(
			{"findings": [{
				"rank": 1,
				"title": "Segment movement",
				"importance": "medium",
				"affected_line_refs": ["L01", "S01"],
				"observation": "The supplied segment moved.",
				"why_it_matters": "The movement merits review.",
			}]},
			{"L01", "S01"},
		)
		with self.assertRaises(AnalyticalScanError):
			validate_analytical_scan_result(
				{"findings": [{
					"rank": 1,
					"title": "Unknown",
					"importance": "low",
					"affected_line_refs": ["S99"],
					"observation": "Unknown.",
					"why_it_matters": "Unknown.",
				}]},
				{"S01"},
			)
		client = Mock()
		client.responses.parse.return_value = SimpleNamespace(output_parsed=AnalyticalScanResult())
		_, metadata = run_analytical_scan(
			"MSFT", self.pnl, client=client, segments=segments, run_id="segments-test"
		)
		self.assertEqual(metadata["supplied_segment_count"], 6)
		self.assertTrue(metadata["segment_enriched"])
		with TemporaryDirectory() as directory:
			analytics_path = save_segment_analytics("MSFT", segments, directory)
			reconciliation_path = save_segment_reconciliation("MSFT", checks, directory)
			self.assertTrue(Path(analytics_path).exists())
			self.assertTrue(Path(reconciliation_path).exists())
