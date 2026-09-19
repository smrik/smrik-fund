"""Focused offline tests for P2 source and period mechanics."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import TestCase

import pandas as pd

from smrik_fund.ingestion.history import (
	construct_ttm,
	latest_balance_sheet,
	preserve_unique_actual_periods,
	qualify_source_references,
	reconcile_quarterly_ttm,
)


def _flow(
	concept: str,
	start: str,
	end: str,
	value: float | None,
	*,
	accession: str = "A1",
	filing_date: str = "2026-04-29",
	unit: str = "U_USD",
	dimensions: str = "{}",
	period_type: str = "duration",
	fiscal_period: str = "Q3",
) -> dict[str, object]:
	return {
		"statement": "income_statement",
		"concept": concept,
		"standard_concept": concept,
		"period_type": period_type,
		"period_start": start,
		"period_end": end,
		"period_instant": None,
		"fiscal_period": fiscal_period,
		"numeric_value": value,
		"unit": unit,
		"currency": "USD",
		"scale_factor": 1.0,
		"dimensions": dimensions,
		"statement_role": "income-role",
		"source": "edgar",
		"accession": accession,
		"filing_date": filing_date,
		"form_type": "10-Q",
		"source_locator": f"{accession}:{start}:{end}:{value}",
	}


def _ttm_frame(**overrides: object) -> pd.DataFrame:
	row_overrides = {name: value for name, value in overrides.items() if name not in {"fy", "current", "prior"}}
	values = {
		"fy": 100.0,
		"current": 90.0,
		"prior": 80.0,
	}
	values.update(overrides)
	return pd.DataFrame(
		[
			_flow("Revenue", "2024-07-01", "2025-06-30", values["fy"], fiscal_period="FY", **row_overrides),
			_flow("Revenue", "2025-07-01", "2026-03-31", values["current"], **row_overrides),
			_flow("Revenue", "2024-07-01", "2025-03-31", values["prior"], **row_overrides),
		]
	)


class HistoryTests(TestCase):
	def test_ttm_uses_actual_periods_and_keeps_component_refs(self) -> None:
		result = construct_ttm(
			_ttm_frame(),
			concept="Revenue",
			full_fy_end="2025-06-30",
			current_ytd_start="2025-07-01",
			current_ytd_end="2026-03-31",
			prior_ytd_start="2024-07-01",
			prior_ytd_end="2025-03-31",
		)
		history = result["history"]
		self.assertEqual(history.iloc[0]["numeric_value"], 110.0)
		self.assertEqual(history.iloc[0]["period_start"], "2025-04-01")
		self.assertEqual(history.iloc[0]["period_end"], "2026-03-31")
		self.assertEqual(len(result["source_refs"]), 3)
		self.assertTrue(result["history"].iloc[0]["is_derived"])
		self.assertIn("PASS", result["checks"]["status"].tolist())

	def test_ttm_preserves_missing_and_zero(self) -> None:
		missing = construct_ttm(
			_ttm_frame(current=None),
			concept="Revenue",
			full_fy_end="2025-06-30",
			current_ytd_start="2025-07-01",
			current_ytd_end="2026-03-31",
			prior_ytd_start="2024-07-01",
			prior_ytd_end="2025-03-31",
		)
		self.assertIsNone(missing["history"].iloc[0]["numeric_value"])
		self.assertIn("missing_component_value", missing["checks"]["reason"].tolist())

		zero = construct_ttm(
			_ttm_frame(current=0.0),
			concept="Revenue",
			full_fy_end="2025-06-30",
			current_ytd_start="2025-07-01",
			current_ytd_end="2026-03-31",
			prior_ytd_start="2024-07-01",
			prior_ytd_end="2025-03-31",
		)
		self.assertEqual(zero["history"].iloc[0]["numeric_value"], 20.0)

	def test_ttm_rejects_instant_and_non_additive_inputs(self) -> None:
		instant = _ttm_frame()
		instant["period_type"] = "instant"
		instant["period_instant"] = instant["period_end"]
		instant_result = construct_ttm(
			instant,
			concept="Revenue",
			full_fy_end="2025-06-30",
			current_ytd_start="2025-07-01",
			current_ytd_end="2026-03-31",
			prior_ytd_start="2024-07-01",
			prior_ytd_end="2025-03-31",
		)
		self.assertIn("instant_fact_rejected", instant_result["checks"]["reason"].tolist())

		eps = _ttm_frame()
		eps["concept"] = "EarningsPerShareBasic"
		eps["standard_concept"] = "EarningsPerShareBasic"
		eps["unit"] = "USD/share"
		eps_result = construct_ttm(
			eps,
		concept="EarningsPerShareBasic",
		full_fy_end="2025-06-30",
		current_ytd_start="2025-07-01",
		current_ytd_end="2026-03-31",
		prior_ytd_start="2024-07-01",
		prior_ytd_end="2025-03-31",
		)
		self.assertIn("non_additive_concept", eps_result["checks"]["reason"].tolist())

	def test_ttm_rejects_mixed_units_and_scopes(self) -> None:
		units = _ttm_frame()
		units.loc[1, "unit"] = "U_EUR"
		result = construct_ttm(
			units,
			concept="Revenue",
			full_fy_end="2025-06-30",
			current_ytd_start="2025-07-01",
			current_ytd_end="2026-03-31",
			prior_ytd_start="2024-07-01",
			prior_ytd_end="2025-03-31",
		)
		self.assertIn("unknown_monetary_unit", result["checks"]["reason"].tolist())

		scopes = _ttm_frame()
		scopes.loc[2, "dimensions"] = '{"axis":"member"}'
		result = construct_ttm(
			scopes,
			concept="Revenue",
			full_fy_end="2025-06-30",
			current_ytd_start="2025-07-01",
			current_ytd_end="2026-03-31",
			prior_ytd_start="2024-07-01",
			prior_ytd_end="2025-03-31",
		)
		self.assertIn("unit_scope_or_period_mismatch", result["checks"]["reason"].tolist())

	def test_cutoff_excludes_later_sources_and_ambiguity_requires_basis(self) -> None:
		facts = _ttm_frame()
		later = facts.iloc[[0]].copy()
		later["accession"] = "A2"
		later["filing_date"] = "2026-05-01"
		facts = pd.concat([facts, later], ignore_index=True)
		cutoff = qualify_source_references(facts, "2026-04-30")
		self.assertEqual(len(cutoff["excluded_after_cutoff"]), 1)
		self.assertEqual(len(cutoff["qualified"]), 3)

		ambiguous_facts = pd.concat([facts.iloc[[0]], later], ignore_index=True)
		ambiguous = qualify_source_references(ambiguous_facts, "2026-05-30")
		self.assertTrue(ambiguous["qualified"].empty)
		self.assertIn("ambiguous_source_selection", ambiguous["checks"]["reason"].tolist())
		self.assertEqual(len(ambiguous["alternatives"]), 2)

		chosen = qualify_source_references(
			ambiguous_facts, "2026-05-30", selection_basis="accession:A2"
		)
		self.assertEqual(set(chosen["qualified"]["accession"]), {"A2"})

	def test_unique_periods_reject_conflicting_values(self) -> None:
		facts = _ttm_frame()
		duplicate = facts.iloc[[0]].copy()
		duplicate["numeric_value"] = 101.0
		conflict = preserve_unique_actual_periods(pd.concat([facts, duplicate], ignore_index=True))
		self.assertTrue(conflict["periods"].empty)
		self.assertIn("conflicting_period_values", conflict["checks"]["reason"].tolist())

		unique = preserve_unique_actual_periods(facts)
		self.assertEqual(len(unique["periods"]), 3)

	def test_four_quarters_are_independent_and_overlap_fails(self) -> None:
		quarters = pd.DataFrame(
			[
				_flow("Revenue", "2025-04-01", "2025-06-30", 10.0),
				_flow("Revenue", "2025-07-01", "2025-09-30", 20.0),
				_flow("Revenue", "2025-10-01", "2025-12-31", 30.0),
				_flow("Revenue", "2026-01-01", "2026-03-31", 40.0),
			]
		)
		result = reconcile_quarterly_ttm(
			quarters,
			concept="Revenue",
			quarter_ends=["2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31"],
			ttm_value=100.0,
		)
		self.assertEqual(result["value"], 100.0)
		self.assertIn("PASS", result["checks"]["status"].tolist())

		overlap = quarters.copy()
		overlap.loc[1, "period_start"] = "2025-06-30"
		bad = reconcile_quarterly_ttm(
			overlap,
			concept="Revenue",
			quarter_ends=["2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31"],
		)
		self.assertIn("quarters_overlap_or_gap", bad["checks"]["reason"].tolist())

	def test_latest_balance_sheet_is_an_instant_snapshot(self) -> None:
		rows = []
		for instant, value in (("2025-06-30", 50.0), ("2026-03-31", 60.0)):
			row = _flow("Assets", "", instant, value, period_type="instant")
			row["period_start"] = None
			row["period_end"] = instant
			row["period_instant"] = instant
			row["statement"] = "balance_sheet"
			rows.append(row)
		result = latest_balance_sheet(pd.DataFrame(rows), concept="Assets")
		self.assertEqual(len(result["balance_sheet"]), 1)
		self.assertEqual(result["balance_sheet"].iloc[0]["period_instant"], "2026-03-31")

	def test_existing_cache_has_native_period_and_source_metadata(self) -> None:
		path = Path("data/MSFT/02_processing/edgar/facts.csv")
		facts = pd.read_csv(path)
		result = qualify_source_references(facts, "2026-07-30")
		self.assertFalse(result["qualified"].empty)
		self.assertTrue(
			{"period_start", "period_end", "period_type", "unit", "scale_factor", "accession"}
			<= set(result["qualified"].columns)
		)
		balance = latest_balance_sheet(facts, information_cutoff="2026-07-30")
		self.assertEqual(
			balance["balance_sheet"]["period_instant"].max(), "2026-06-30"
		)
		self.assertEqual(balance["checks"].iloc[-1]["status"], "PASS")
		# Keep the fixture explicitly data-shape-only; no live or credential path.
		self.assertEqual(json.loads(facts.iloc[0]["metadata"])["cik"], "0000789019")

	def test_ttm_rejects_prior_ytd_that_is_not_anchored_to_full_fy(self) -> None:
		facts = _ttm_frame()
		facts.loc[2, "period_start"] = "2022-07-01"
		facts.loc[2, "period_end"] = "2023-03-31"
		result = construct_ttm(
			facts,
			concept="Revenue",
			full_fy_end="2025-06-30",
			current_ytd_start="2025-07-01",
			current_ytd_end="2026-03-31",
			prior_ytd_start="2022-07-01",
			prior_ytd_end="2023-03-31",
		)
		self.assertTrue(result["history"].empty)
		self.assertIn("prior_ytd_not_anchored", result["checks"]["reason"].tolist())

	def test_ttm_accepts_leap_day_when_fiscal_calendar_cutoff_matches(self) -> None:
		facts = _ttm_frame()
		facts.loc[0, ["period_start", "period_end"]] = ["2023-07-01", "2024-06-30"]
		facts.loc[1, ["period_start", "period_end"]] = ["2024-07-01", "2025-03-31"]
		facts.loc[2, ["period_start", "period_end"]] = ["2023-07-01", "2024-03-31"]
		result = construct_ttm(
			facts,
			concept="Revenue",
			full_fy_end="2024-06-30",
			current_ytd_start="2024-07-01",
			current_ytd_end="2025-03-31",
			prior_ytd_start="2023-07-01",
			prior_ytd_end="2024-03-31",
		)
		self.assertEqual(result["history"].iloc[0]["numeric_value"], 110.0)
		self.assertNotIn("ytd_duration_mismatch", result["checks"]["reason"].tolist())

	def test_ttm_rejects_non_annual_full_fy_span(self) -> None:
		facts = _ttm_frame()
		facts.loc[0, ["period_start", "period_end"]] = ["2024-07-01", "2025-06-29"]
		facts.loc[1, ["period_start", "period_end"]] = ["2025-06-30", "2026-03-31"]
		facts.loc[2, ["period_start", "period_end"]] = ["2024-07-01", "2025-03-31"]
		result = construct_ttm(
			facts,
			concept="Revenue",
			full_fy_end="2025-06-29",
			current_ytd_start="2025-06-30",
			current_ytd_end="2026-03-31",
			prior_ytd_start="2024-07-01",
			prior_ytd_end="2025-03-31",
		)
		self.assertTrue(result["history"].empty)
		self.assertIn("invalid_fy_span", result["checks"]["reason"].tolist())

	def test_ttm_rejects_inconsistent_scale_metadata(self) -> None:
		facts = _ttm_frame()
		facts.loc[1, "scale_factor"] = 1_000_000.0
		result = construct_ttm(
			facts,
			concept="Revenue",
			full_fy_end="2025-06-30",
			current_ytd_start="2025-07-01",
			current_ytd_end="2026-03-31",
			prior_ytd_start="2024-07-01",
			prior_ytd_end="2025-03-31",
		)
		self.assertTrue(result["history"].empty)
		self.assertIn("unit_scope_or_period_mismatch", result["checks"]["reason"].tolist())

	def test_ttm_requires_positive_monetary_unit_and_scale_metadata(self) -> None:
		unknown_unit = _ttm_frame(unit="widgets")
		result = construct_ttm(
			unknown_unit,
			concept="Revenue",
			full_fy_end="2025-06-30",
			current_ytd_start="2025-07-01",
			current_ytd_end="2026-03-31",
			prior_ytd_start="2024-07-01",
			prior_ytd_end="2025-03-31",
		)
		self.assertTrue(result["history"].empty)
		self.assertIn("unknown_monetary_unit", result["checks"]["reason"].tolist())

		missing_scale = _ttm_frame()
		missing_scale["scale_factor"] = None
		result = construct_ttm(
			missing_scale,
			concept="Revenue",
			full_fy_end="2025-06-30",
			current_ytd_start="2025-07-01",
			current_ytd_end="2026-03-31",
			prior_ytd_start="2024-07-01",
			prior_ytd_end="2025-03-31",
		)
		self.assertTrue(result["history"].empty)
		self.assertIn("missing_scale_metadata", result["checks"]["reason"].tolist())

	def test_latest_balance_sheet_requires_explicit_statement_scope(self) -> None:
		balance = _flow("Assets", "", "2025-06-30", 50.0, period_type="instant")
		balance["period_start"] = None
		balance["period_instant"] = "2025-06-30"
		balance["statement"] = "balance_sheet"
		other = balance.copy()
		other["statement"] = "income_statement"
		other["period_end"] = "2026-03-31"
		other["period_instant"] = "2026-03-31"
		other["numeric_value"] = 99.0
		result = latest_balance_sheet(pd.DataFrame([balance, other]), concept="Assets")
		self.assertEqual(len(result["balance_sheet"]), 1)
		self.assertEqual(result["balance_sheet"].iloc[0]["period_instant"], "2025-06-30")
		self.assertEqual(result["balance_sheet"].iloc[0]["statement"], "balance_sheet")

		missing_scope = latest_balance_sheet(
			pd.DataFrame([balance]).drop(columns=["statement"]), concept="Assets"
		)
		self.assertTrue(missing_scope["balance_sheet"].empty)
		self.assertIn("missing_balance_sheet_scope", missing_scope["checks"]["reason"].tolist())
