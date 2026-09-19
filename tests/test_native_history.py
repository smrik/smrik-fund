"""Focused tests for the native EdgarTools statement projection seam."""

from __future__ import annotations

import inspect
from pathlib import Path
from unittest import TestCase

import pandas as pd

from smrik_fund.ingestion.history import construct_ttm, latest_balance_sheet
from smrik_fund.ingestion.native_history import native_statements_to_history

SOURCE = {
	"source": "edgar",
	"accession": "A1",
	"filing_date": "2026-04-29",
	"form_type": "10-Q",
	"source_locator": "A1:statement:fact",
}


def _period(
	column: str,
	start: str | None,
	end: str | None,
	*,
	period_type: str = "duration",
	fiscal_period: str | None = "Q3",
	instant: str | None = None,
) -> dict[str, object]:
	return {
		"period_column": column,
		"period_type": period_type,
		"period_start": start,
		"period_end": end,
		"period_instant": instant,
		"fiscal_year": 2026,
		"fiscal_period": fiscal_period,
		"unit": "USD",
		"unit_ref": "U_USD",
		"currency": "USD",
		"scale_factor": 1.0,
		"dimensions": "{}",
		"statement_role": "income-role",
	}


def _metadata(*periods: dict[str, object]) -> pd.DataFrame:
	return pd.DataFrame(periods)


def _frame(values: dict[str, object], *, concept: str = "Revenue") -> pd.DataFrame:
	return pd.DataFrame(
		[
			{
				"concept": concept,
				"label": "Revenue",
				"standard_concept": concept,
				"2025-06-30 (FY)": values.get("fy"),
				"2025-03-31 (YTD)": values.get("prior"),
				"2026-03-31 (YTD)": values.get("current"),
				"level": 4,
				"abstract": False,
				"dimension": False,
				"is_breakdown": False,
				"parent_concept": "us-gaap_GrossProfit",
			}
		]
	)


def _ttm_metadata() -> pd.DataFrame:
	return _metadata(
		_period("2025-06-30 (FY)", "2024-07-01", "2025-06-30", fiscal_period="FY"),
		_period("2026-03-31 (YTD)", "2025-07-01", "2026-03-31", fiscal_period="Q3"),
		_period("2025-03-31 (YTD)", "2024-07-01", "2025-03-31", fiscal_period="Q3"),
	)


class NativeHistoryTests(TestCase):
	def test_installed_edgartools_native_interface_has_standard_controls(self) -> None:
		from edgar.xbrl.statements import Statement

		parameters = inspect.signature(Statement.to_dataframe).parameters
		self.assertTrue({"view", "period_view"}.intersection(parameters))
		self.assertIn("presentation", parameters)
		self.assertIn("include_unit", parameters)

	def test_projection_preserves_cached_native_identity_and_value(self) -> None:
		path = Path("data/MSFT/02_processing/edgar/statements/income_statement.csv")
		cached = pd.read_csv(path).iloc[[0]].copy()
		metadata = _metadata(
			_period("2026-06-30 (FY)", "2025-07-01", "2026-06-30", fiscal_period="FY")
		)
		result = native_statements_to_history(
			{"income_statement": cached},
			statement_metadata={"income_statement": SOURCE},
			period_metadata={"income_statement": metadata},
		)

		history = result["history"]
		self.assertEqual(len(history), 1)
		self.assertEqual(history.iloc[0]["concept"], cached.iloc[0]["concept"])
		self.assertEqual(history.iloc[0]["label"], "Revenue")
		self.assertEqual(history.iloc[0]["parent_concept"], "us-gaap_GrossProfit")
		self.assertEqual(history.iloc[0]["numeric_value"], cached.iloc[0]["2026-06-30 (FY)"])
		self.assertEqual(history.iloc[0]["unit"], "USD")
		self.assertEqual(history.iloc[0]["accession"], "A1")
		self.assertEqual(history.iloc[0]["source_locator"], SOURCE["source_locator"])

		dimensional = cached.copy()
		dimensional["dimension"] = True
		dimensional["dimension_axis"] = "srt:ProductOrServiceAxis"
		dimensional["dimension_member"] = "us-gaap_ProductMember"
		dimensional["dimension_member_label"] = "Product"
		dim_result = native_statements_to_history(
			{"income_statement": dimensional},
			statement_metadata={"income_statement": SOURCE},
			period_metadata={"income_statement": metadata},
		)
		self.assertIn("dimension_axis", str(dim_result["history"].iloc[0]["dimensions"]))

	def test_native_object_uses_raw_standard_statement_values(self) -> None:
		frame = _frame({"fy": -5.0, "prior": 0.0, "current": None})

		class NativeStatement:
			def __init__(self) -> None:
				self.calls: dict[str, object] = {}

			def to_dataframe(self, **kwargs: object) -> pd.DataFrame:
				self.calls = kwargs
				return frame

		native = NativeStatement()
		result = native_statements_to_history(
			{"income_statement": native},
			statement_metadata={"income_statement": SOURCE},
			period_metadata={"income_statement": _ttm_metadata()},
		)

		self.assertEqual(len(result["history"]), 3)
		self.assertEqual(native.calls["view"], "standard")
		self.assertEqual(native.calls["presentation"], False)
		self.assertEqual(native.calls["include_unit"], True)
		self.assertEqual(native.calls["include_point_in_time"], True)
		values = result["history"].sort_values("period_column")["numeric_value"].tolist()
		self.assertEqual(values[:2], [0.0, -5.0])
		self.assertTrue(pd.isna(values[2]))

	def test_missing_scale_is_unavailable_and_reason_is_exposed(self) -> None:
		periods = _ttm_metadata()
		periods["scale_factor"] = None
		result = native_statements_to_history(
			{"income_statement": _frame({"fy": 100.0, "prior": 80.0, "current": 90.0})},
			statement_metadata={"income_statement": SOURCE},
			period_metadata={"income_statement": periods},
		)

		self.assertTrue(result["history"].empty)
		self.assertIn("missing_native_scale", result["excluded"]["reason"].tolist())

	def test_reversed_and_contradictory_periods_are_unavailable(self) -> None:
		for update, reason in (
			({"period_start": "2025-07-01", "period_end": "2025-06-30"}, "start is after end"),
			({"period_instant": "2025-06-30"}, "cannot also provide period_instant"),
			({"period_end": "2025-05-31"}, "period_end does not match native period identity"),
		):
			period = _period("2025-06-30 (FY)", "2024-07-01", "2025-06-30", fiscal_period="FY")
			period.update(update)
			result = native_statements_to_history(
				{"income_statement": _frame({"fy": 100.0})},
				statement_metadata={"income_statement": SOURCE},
				period_metadata={"income_statement": _metadata(period)},
			)
			self.assertTrue(result["history"].empty)
			self.assertTrue(any(reason in detail for detail in result["excluded"]["detail"]))
			self.assertIn("FAIL", result["checks"]["status"].tolist())

	def test_missing_native_row_unit_is_excluded_after_period_validation(self) -> None:
		frame = _frame({"fy": 100.0, "prior": 80.0, "current": 90.0})
		frame["unit"] = None
		result = native_statements_to_history(
			{"income_statement": frame},
			statement_metadata={"income_statement": SOURCE},
			period_metadata={"income_statement": _ttm_metadata()},
		)

		self.assertTrue(result["history"].empty)
		self.assertEqual(set(result["excluded"]["reason"]), {"missing_native_metadata"})
		self.assertTrue(result["excluded"]["numeric_value"].notna().all())
		self.assertIn("FAIL", result["checks"]["status"].tolist())

	def test_known_non_monetary_unit_stays_distinguishable_for_ttm(self) -> None:
		frame = _frame({"fy": 100.0, "prior": 80.0, "current": 90.0})
		frame["unit"] = "shares"
		result = native_statements_to_history(
			{"income_statement": frame},
			statement_metadata={"income_statement": SOURCE},
			period_metadata={"income_statement": _ttm_metadata()},
		)
		ttm = construct_ttm(
			result["history"],
			concept="Revenue",
			full_fy_end="2025-06-30",
			current_ytd_start="2025-07-01",
			current_ytd_end="2026-03-31",
			prior_ytd_start="2024-07-01",
			prior_ytd_end="2025-03-31",
		)

		self.assertEqual(set(result["history"]["unit"]), {"shares"})
		self.assertIn("unknown_monetary_unit", ttm["checks"]["reason"].tolist())

	def test_unmapped_native_period_is_excluded_with_value_evidence(self) -> None:
		frame = _frame({"fy": 100.0, "prior": 80.0, "current": 90.0})
		level_index = frame.columns.get_loc("level")
		frame.insert(level_index, "2025-03-31 (Q3)", 70.0)
		result = native_statements_to_history(
			{"income_statement": frame},
			statement_metadata={"income_statement": SOURCE},
			period_metadata={"income_statement": _ttm_metadata()},
		)

		self.assertEqual(len(result["history"]), 3)
		omitted = result["excluded"].loc[
			result["excluded"]["period_column"].eq("2025-03-31 (Q3)")
		]
		self.assertEqual(omitted.iloc[0]["numeric_value"], 70.0)
		self.assertIn("missing_native_metadata", omitted["reason"].tolist())
		self.assertIn("FAIL", result["checks"]["status"].tolist())

	def test_reordered_native_metadata_is_not_treated_as_a_period(self) -> None:
		frame = _frame({"fy": 100.0, "prior": 80.0, "current": 90.0})
		frame["unit"] = "u_usd"
		frame.insert(4, "2024-12-31 (Q2)", 70.0)
		ordered = frame[
			[
				"concept",
				"label",
				"level",
				"unit",
				"2024-12-31 (Q2)",
				"2025-06-30 (FY)",
				"2025-03-31 (YTD)",
				"2026-03-31 (YTD)",
				"abstract",
				"parent_concept",
			]
		]
		result = native_statements_to_history(
			{"income_statement": ordered},
			statement_metadata={"income_statement": SOURCE},
			period_metadata={"income_statement": _ttm_metadata()},
		)

		self.assertEqual(len(result["history"]), 3)
		self.assertEqual(set(result["history"]["label"]), {"Revenue"})
		self.assertEqual(
			set(result["excluded"]["period_column"]), {"2024-12-31 (Q2)"}
		)

	def test_conflicting_period_metadata_stays_as_alternatives(self) -> None:
		periods = _ttm_metadata()
		conflict = periods.iloc[[0]].copy()
		conflict["accession"] = "A2"
		periods = pd.concat([periods, conflict], ignore_index=True)
		result = native_statements_to_history(
			{"income_statement": _frame({"fy": 100.0, "prior": 80.0, "current": 90.0})},
			statement_metadata={"income_statement": SOURCE},
			period_metadata={"income_statement": periods},
		)

		self.assertTrue(result["history"].empty)
		self.assertEqual(len(result["alternatives"]), 2)
		self.assertIn("ambiguous_period_metadata", result["excluded"]["reason"].tolist())

	def test_projected_rows_feed_ttm_without_sign_or_period_rewrite(self) -> None:
		result = native_statements_to_history(
			{"income_statement": _frame({"fy": 100.0, "prior": 80.0, "current": 90.0})},
			statement_metadata={"income_statement": SOURCE},
			period_metadata={"income_statement": _ttm_metadata()},
		)
		ttm = construct_ttm(
			result["history"],
			concept="Revenue",
			full_fy_end="2025-06-30",
			current_ytd_start="2025-07-01",
			current_ytd_end="2026-03-31",
			prior_ytd_start="2024-07-01",
			prior_ytd_end="2025-03-31",
		)

		self.assertEqual(ttm["history"].iloc[0]["numeric_value"], 110.0)
		self.assertEqual(len(ttm["source_refs"]), 3)

	def test_projected_instant_rows_feed_latest_balance_sheet(self) -> None:
		frame = pd.DataFrame(
			[
				{
					"concept": "CashAndCashEquivalents",
					"label": "Cash and cash equivalents",
					"standard_concept": "CashAndMarketableSecurities",
					"2025-06-30": 50.0,
					"2026-03-31": 60.0,
					"level": 4,
					"abstract": False,
					"dimension": False,
				}
			]
		)
		periods = _metadata(
			_period(
				"2025-06-30",
				None,
				None,
				period_type="instant",
				fiscal_period=None,
				instant="2025-06-30",
			),
			_period(
				"2026-03-31",
				None,
				None,
				period_type="instant",
				fiscal_period=None,
				instant="2026-03-31",
			),
		)
		result = native_statements_to_history(
			{"balance_sheet": frame},
			statement_metadata={"balance_sheet": {**SOURCE, "form_type": "10-Q"}},
			period_metadata={"balance_sheet": periods},
		)
		balance = latest_balance_sheet(result["history"], concept="CashAndCashEquivalents")

		self.assertEqual(len(balance["balance_sheet"]), 1)
		self.assertEqual(balance["balance_sheet"].iloc[0]["period_instant"], "2026-03-31")
		self.assertEqual(balance["balance_sheet"].iloc[0]["numeric_value"], 60.0)

	def test_non_additive_native_rows_remain_available_but_ttm_rejects_them(self) -> None:
		result = native_statements_to_history(
			{"income_statement": _frame({"fy": 1.0, "prior": 0.8, "current": 0.9}, concept="EarningsPerShareBasic")},
			statement_metadata={"income_statement": SOURCE},
			period_metadata={"income_statement": _ttm_metadata()},
		)
		ttm = construct_ttm(
			result["history"],
			concept="EarningsPerShareBasic",
			full_fy_end="2025-06-30",
			current_ytd_start="2025-07-01",
			current_ytd_end="2026-03-31",
			prior_ytd_start="2024-07-01",
			prior_ytd_end="2025-03-31",
		)

		self.assertEqual(len(result["history"]), 3)
		self.assertIn("non_additive_concept", ttm["checks"]["reason"].tolist())
