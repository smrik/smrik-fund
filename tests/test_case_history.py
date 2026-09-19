"""Offline financial checks for the frozen-case orchestration boundaries."""

from __future__ import annotations

from unittest import TestCase

import pandas as pd

from smrik_fund.ingestion.case_history import (
	CASE_CUTOFF,
	CaseHistoryError,
	_build_q4,
	_build_ttm,
	_case_checks,
	_display_value,
	_inline_attributes_for_filing,
	_period_specs,
	_r2_source_bounds,
)


def _flow(period_key: str, start: str, end: str, value: float, accession: str) -> dict[str, object]:
	return {
		"statement": "income_statement",
		"concept": "us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax",
		"label": "Revenue",
		"dimensions": "{}",
		"dimension": False,
		"period_key": period_key,
		"period_type": "duration",
		"period_start": start,
		"period_end": end,
		"period_instant": None,
		"fiscal_year": 2025,
		"fiscal_period": "FY" if end == "2025-06-30" else "Q3",
		"unit": "USD",
		"unit_ref": "U_USD",
		"currency": "USD",
		"scale_factor": 1.0,
		"statement_role": "income-role",
		"numeric_value": value,
		"accession": accession,
		"filing_date": "2026-04-29",
		"form_type": "10-Q",
		"source": "edgar",
		"source_selection_status": "SELECTED",
	}


def _equation_frame(operating_income: float = 60.0, net_change: float = 70.0, liabilities_and_equity: float = 90.0, assets: float = 90.0) -> pd.DataFrame:
	period_key = "duration_2025-07-01_2026-03-31"
	rows: list[dict[str, object]] = []

	def add(statement: str, concept: str, value: float, weight: float = 1.0) -> None:
		rows.append({
			"statement": statement, "concept": concept, "dimensions": "{}", "dimension": False,
			"period_key": period_key, "period_type": "duration", "numeric_value": value,
			"unit": "u_usd", "currency": "USD", "weight": weight, "source_selection_status": "SELECTED",
		})

	add("income_statement", "us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax", 100.0)
	add("income_statement", "us-gaap_CostOfGoodsAndServicesSold", 20.0, -1.0)
	add("income_statement", "us-gaap_GrossProfit", 80.0)
	add("income_statement", "us-gaap_ResearchAndDevelopmentExpense", 10.0, -1.0)
	add("income_statement", "us-gaap_SellingAndMarketingExpense", 5.0, -1.0)
	add("income_statement", "us-gaap_GeneralAndAdministrativeExpense", 5.0, -1.0)
	add("income_statement", "us-gaap_OperatingIncomeLoss", operating_income)
	add("income_statement", "us-gaap_NonoperatingIncomeExpense", 0.0)
	add("income_statement", "us-gaap_IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest", 60.0)
	add("income_statement", "us-gaap_IncomeTaxExpenseBenefit", 10.0, -1.0)
	add("income_statement", "us-gaap_NetIncomeLoss", 50.0)
	add("cash_flow_statement", "us-gaap_NetCashProvidedByUsedInOperatingActivities", 100.0)
	add("cash_flow_statement", "us-gaap_NetCashProvidedByUsedInInvestingActivities", -20.0)
	add("cash_flow_statement", "us-gaap_NetCashProvidedByUsedInFinancingActivities", -10.0)
	add("cash_flow_statement", "us-gaap_EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsIncludingDisposalGroupAndDiscontinuedOperations", 0.0)
	add("cash_flow_statement", "us-gaap_CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect", net_change)
	for concept, value in (("us-gaap_Assets", assets), ("us-gaap_Liabilities", 40.0), ("us-gaap_StockholdersEquity", 50.0), ("us-gaap_LiabilitiesAndStockholdersEquity", liabilities_and_equity)):
		add("balance_sheet", concept, value)
	for row in rows:
		if row["statement"] == "balance_sheet":
			row["period_key"] = "instant_2026-03-31"
			row["period_type"] = "instant"
	return pd.DataFrame(rows)


class CaseHistoryTests(TestCase):
	def test_period_specs_keep_ytd_and_quarter_ids_distinct(self) -> None:
		specs = _period_specs()
		current_ytd = [row for row in specs if row["view"] == "ytd"]
		q3 = [row for row in specs if row["name"] == "Q3 FY2026"]
		self.assertEqual({row["period_key"] for row in current_ytd}, {"duration_2025-07-01_2026-03-31", "duration_2024-07-01_2025-03-31"})
		self.assertEqual({row["period_key"] for row in q3}, {"duration_2026-01-01_2026-03-31"})
		self.assertIn("0001193125-26-191507", {row["accession"] for row in specs})
		self.assertEqual(CASE_CUTOFF.isoformat(), "2026-04-30")

	def test_display_conversion_does_not_change_native_value(self) -> None:
		self.assertEqual(_display_value(241_832_000_000, "USD"), 241_832.0)
		self.assertEqual(_display_value(-1_250_000, "USD"), -1.25)
		self.assertEqual(_display_value(7.2, "USD/shares"), 7.2)
		self.assertIsNone(_display_value(None, "USD"))

	def test_ttm_uses_fy_plus_current_ytd_minus_prior_ytd(self) -> None:
		rows = [
			_flow("duration_2024-07-01_2025-06-30", "2024-07-01", "2025-06-30", 100.0, "FY25"),
			_flow("duration_2025-07-01_2026-03-31", "2025-07-01", "2026-03-31", 90.0, "Q3"),
			_flow("duration_2024-07-01_2025-03-31", "2024-07-01", "2025-03-31", 80.0, "Q3"),
		]
		ttm, unavailable, _ = _build_ttm(pd.DataFrame(rows))
		self.assertEqual(len(ttm), 1)
		self.assertEqual(ttm.iloc[0]["numeric_value"], 110.0)
		self.assertTrue(unavailable.empty)

	def test_q4_is_explicitly_dependent_and_preserves_sign(self) -> None:
		rows = [
			_flow("duration_2024-07-01_2025-06-30", "2024-07-01", "2025-06-30", -10.0, "FY25"),
			_flow("duration_2024-07-01_2025-03-31", "2024-07-01", "2025-03-31", -7.0, "Q3"),
		]
		q4 = _build_q4(pd.DataFrame(rows))
		self.assertEqual(len(q4), 1)
		self.assertEqual(q4.iloc[0]["numeric_value"], -3.0)
		self.assertEqual(q4.iloc[0]["source_selection_status"], "DERIVED_DEPENDENT")
		self.assertIn("prior comparable YTD", q4.iloc[0]["derivation"])

	def test_q4_skips_non_additive_share_metrics(self) -> None:
		rows = []
		for period_key, value in (
			("duration_2024-07-01_2025-06-30", 2.0),
			("duration_2024-07-01_2025-03-31", 1.0),
		):
			row = _flow(period_key, period_key[9:19], period_key[20:], value, "FY25")
			row["concept"] = "us-gaap_EarningsPerShareBasic"
			rows.append(row)
		self.assertTrue(_build_q4(pd.DataFrame(rows)).empty)

	def test_inline_lookup_collects_distinct_fact_ids_from_one_filing(self) -> None:
		class Filing:
			calls = 0

			def html(self) -> str:
				self.calls += 1
				return '<ix:nonFraction id="F1" unitRef="U_USD" scale="6" sign="-">123</ix:nonFraction><ix:nonFraction id="F2" unitRef="U_SHARES" scale="0">7.5</ix:nonFraction>'

		filing = Filing()
		attributes = _inline_attributes_for_filing(filing, {"F1", "F2"}, "TEST-INLINE")
		self.assertEqual(filing.calls, 1)
		self.assertEqual(attributes["F1"]["unitref"], "U_USD")
		self.assertEqual(attributes["F1"]["scale"], "6")
		self.assertEqual(attributes["F1"]["sign"], "-")
		self.assertEqual(attributes["F1"]["__raw_text"], "123")
		self.assertEqual(attributes["F2"]["unitref"], "U_SHARES")

	def test_statement_equations_fail_on_corrupted_income_cashflow_and_balance(self) -> None:
		cases = (
			("income_statement:Current YTD:duration_2025-07-01_2026-03-31:operating_income", {"operating_income": 61.0}),
			("cash_flow_statement:Current YTD:duration_2025-07-01_2026-03-31:net_change", {"net_change": 71.0}),
			("balance_sheet_identity", {"liabilities_and_equity": 91.0}),
			("balance_sheet_assets_vs_reported_total", {"assets": 91.0}),
		)
		for check_id, changes in cases:
			checks = _case_checks(_equation_frame(**changes), [], pd.DataFrame(), pd.DataFrame(), {})
			row = checks.loc[checks["check_id"].eq(check_id)].iloc[0]
			self.assertEqual(row["status"], "FAIL")
			self.assertEqual(row["reason"], "reported_identity_difference")
			self.assertTrue(pd.notna(row["expected"]))
			self.assertTrue(pd.notna(row["observed"]))
			self.assertTrue(pd.notna(row["difference"]))
			self.assertTrue(pd.notna(row["tolerance"]))
			self.assertIn("reported identity retained", row["consequence"])

	def test_r2_sections_select_complete_native_headings_and_endpoints(self) -> None:
		source = (
			"Accounting estimates discuss CONSOLIDATED BALANCE SHEETS and legal square feet in millions. "
			"BALANCE SHEETS - USD ($)<br> $ in Millions June 30, 2025 2024 "
			"Cash and cash equivalents 30 20 Total assets 100 90 "
			"Total liabilities and stockholders&#8217; equity 100 90</table>"
			"CASH FLOWS STATEMENTS - USD ($)<br> $ in Millions 12 Months Ended "
			"Net cash from operations 50 Net cash used in investing -20 "
			"Net cash used in financing -10 Net change in cash and cash equivalents 20 "
			"Cash and cash equivalents, beginning of period 10 "
			"Cash and cash equivalents, end of period 30</table>"
			"Financial Instruments Investments <p>We consider all highly liquid interest-earning investments "
			"with a maturity of three months or less at the date of purchase to be cash equivalents.</p>"
			"NOTE 6 &#8212; PROPERTY AND EQUIPMENT (In millions) Total, net 100 "
			"Depreciation expense was $ 22.0 billion.</p>NOTE 7 &#8212; GOODWILL"
		)
		for section, heading, endpoint in (
			("balance_sheet_table", "BALANCE SHEETS - USD ($)", "Total liabilities and stockholders"),
			("cash_flow_table", "CASH FLOWS STATEMENTS - USD ($)", "Cash and cash equivalents, end of period"),
			("cash_equivalent_policy", "Financial Instruments Investments", "cash equivalents"),
			("property_and_equipment_note", "NOTE 6", "Depreciation expense"),
		):
			_, _, excerpt = _r2_source_bounds(source, section)
			self.assertIn(heading.casefold(), excerpt.casefold())
			self.assertIn(endpoint.casefold(), excerpt.casefold())
			self.assertNotIn("Accounting estimates discuss", excerpt)

	def test_r2_rejects_incomplete_cash_flow_excerpt(self) -> None:
		with self.assertRaises(CaseHistoryError):
			_r2_source_bounds("CASH FLOWS STATEMENTS - USD ($) only", "cash_flow_table")
