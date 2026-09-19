"""Annual trend observations from frozen EdgarTools standard statements.

Choose the latest available comparative presentation for each statement/period.
Never fall back to an older value when the selected presentation is missing it.
"""

import math
from datetime import date

import pandas as pd

FLOW_FIELDS = {
	"continuing_income": ("income_statement", ("IncomeLossFromContinuingOperations",)),
	"sga_reported": ("income_statement", ("SellingGeneralAndAdministrativeExpense",)),
	"revenue": (
		"income_statement",
		(
			"RevenueFromContractWithCustomerExcludingAssessedTax",
			"Revenues",
			"SalesRevenueNet",
			"RevenueFromContractWithCustomerIncludingAssessedTax",
		),
	),
	"cost_of_revenue": (
		"income_statement",
		("CostOfGoodsAndServicesSold", "CostOfRevenue"),
	),
	"gross_profit": ("income_statement", ("GrossProfit",)),
	"ebit": ("income_statement", ("OperatingIncomeLoss",)),
	"pretax": (
		"income_statement",
		(
			"IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
		),
	),
	"tax_reported": ("income_statement", ("IncomeTaxExpenseBenefit",)),
	"net_income": ("income_statement", ("NetIncomeLoss",)),
	"discontinued_income": (
		"income_statement",
		(
			"IncomeLossFromDiscontinuedOperationsNetOfTax",
			"IncomeLossFromDiscontinuedOperationsNetOfTaxAttributableToParent",
			"IncomeLossFromDiscontinuedOperationsNetOfTaxAttributableToReportingEntity",
		),
	),
	"minority_income": (
		"income_statement",
		("NetIncomeLossAttributableToNoncontrollingInterest",),
	),
	"interest_reported": (
		"income_statement",
		("InterestExpense", "InterestAndDebtExpense"),
	),
	"da": (
		"cash_flow_statement",
		(
			"DepreciationDepletionAndAmortization",
			"DepreciationDepletionAndAmortizationPropertyPlantAndEquipment",
			"DepreciationAmortizationAndAccretionNet",
			"Depreciation",
		),
	),
	"sbc": ("cash_flow_statement", ("ShareBasedCompensation",)),
	"capex_cash": (
		"cash_flow_statement",
		(
			"PaymentsToAcquirePropertyPlantAndEquipment",
			"PaymentsToAcquireProductiveAssets",
		),
	),
	"cfo": ("cash_flow_statement", ("NetCashProvidedByUsedInOperatingActivities",)),
	"cfi": ("cash_flow_statement", ("NetCashProvidedByUsedInInvestingActivities",)),
	"cff": ("cash_flow_statement", ("NetCashProvidedByUsedInFinancingActivities",)),
}
BALANCE_FIELDS = {
	"cash": ("CashAndCashEquivalentsAtCarryingValue",),
	"receivables_reported": ("AccountsReceivableNetCurrent",),
	"inventory_reported": ("InventoryNet",),
	"payables_reported": ("AccountsPayableCurrent",),
	"current_assets": ("AssetsCurrent",),
	"current_liabilities": ("LiabilitiesCurrent",),
	"ppe": (
		"PropertyPlantAndEquipmentNet",
		"PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization",
	),
	"intangibles": (
		"FiniteLivedIntangibleAssetsNet",
		"IntangibleAssetsNetExcludingGoodwill",
	),
	"assets": ("Assets",),
	"liabilities": ("Liabilities",),
	"liabilities_equity": ("LiabilitiesAndStockholdersEquity",),
	"equity_parent": ("StockholdersEquity",),
	"equity_total": (
		"StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
	),
	"minority": ("MinorityInterest",),
	"current_debt": (
		"DebtCurrent",
		"LongTermDebtCurrent",
		"LongTermDebtAndCapitalLeaseObligationsCurrent",
	),
	"long_debt": (
		"LongTermDebtNoncurrent",
		"LongTermDebt",
		"LongTermDebtAndCapitalLeaseObligations",
	),
}


def annual_history(metadata, frames, evidence, years=5):
	"""Return raw observations, exact source bindings and visible coverage gaps."""
	annuals = sorted(
		(m for m in metadata if m["form"] == "10-K"),
		key=lambda m: m["filing_date"],
		reverse=True,
	)
	periods = {}
	for meta in annuals:
		for p in meta["reporting_periods"]:
			if p["type"] != "duration" or not 350 <= p.get("days", 0) <= 380:
				continue
			end = p["end_date"]
			if end > meta["measurement_date"]:
				continue
			# Labels use the issuer's own fiscal label where a primary filing exists.
			primary = next((m for m in annuals if m["measurement_date"] == end), None)
			periods.setdefault(
				end,
				{
					"start": p["start_date"],
					"end": end,
					"label": f"FY{primary['entity']['fiscal_year']}"
					if primary
					else f"Year ended {end}",
				},
			)
	chosen = [periods[end] for end in sorted(periods)[-years:]]
	issues = []
	if len(chosen) < years:
		issues.append(
			f"Only {len(chosen)} of {years} requested annual periods are available in this frozen case; capture a new case for more history."
		)
	result = []
	for period in chosen:
		values, sources = {}, {}
		for statement in ("income_statement", "balance_sheet", "cash_flow_statement"):
			column = period["end"] + ("" if statement == "balance_sheet" else " (FY)")
			candidates = [
				m for m in annuals if column in frames[m["accession"]][statement]
			]
			meta = candidates[0] if candidates else None
			fields = (
				BALANCE_FIELDS
				if statement == "balance_sheet"
				else {k: tags for k, (s, tags) in FLOW_FIELDS.items() if s == statement}
			)
			if meta is None:
				values.update(dict.fromkeys(fields))
				issues.append(f"{period['label']}: no {statement} at {period['end']}.")
				continue
			frame = frames[meta["accession"]][statement]
			face = frame.loc[
				~frame.dimension.astype(str).str.lower().eq("true")
				& ~frame.abstract.astype(str).str.lower().eq("true")
			]
			sources[statement] = {
				"accession": meta["accession"],
				"filing_date": meta["filing_date"],
				"column": column,
				"url": meta["source_url"],
			}
			for key, concepts in fields.items():
				matches = face.loc[
					face.concept.isin(["us-gaap_" + c for c in concepts])
				]
				value = None
				if len(matches) == 1 and pd.notna(matches.iloc[0][column]):
					raw = float(matches.iloc[0][column])
					if math.isfinite(raw):
						value = raw / 1e6
						evidence.append(
							{
								"id": f"H{len(evidence) + 1}",
								"file": f"{meta['accession']}/{statement}.csv",
								"line": int(matches.index[0]) + 2,
								"concept": matches.iloc[0].concept,
								"column": column,
								"reported_value": raw,
								"display_value": value,
								"units": "USD millions",
								"history_period": period["end"],
								"source_url": meta["source_url"],
							}
						)
				if len(matches) > 1:
					issues.append(
						f"{period['label']} {key}: ambiguous source rows; left blank."
					)
				values[key] = value
			if statement != "balance_sheet":
				windows = [
					p
					for p in meta["reporting_periods"]
					if p["type"] == "duration"
					and p.get("end_date") == period["end"]
					and p.get("start_date") == period["start"]
					and 350 <= p.get("days", 0) <= 380
				]
				if len(windows) != 1:
					raise ValueError(
						f"Ambiguous annual history duration: {period['end']}"
					)
		groups = {}
		balance_source = sources.get("balance_sheet")
		if balance_source:
			frame = frames[balance_source["accession"]]["balance_sheet"]
			face = frame.loc[
				~frame.dimension.astype(str).str.lower().eq("true")
				& ~frame.abstract.astype(str).str.lower().eq("true")
			]
			column = balance_source["column"]

			def components(alternatives, face=face, column=column):
				total = 0
				for tags in alternatives:
					matches = face.loc[
						face.concept.isin(["us-gaap_" + tag for tag in tags])
					]
					if len(matches) > 1 or (
						len(matches) == 1 and pd.isna(matches.iloc[0][column])
					):
						return None
					if len(matches) == 1:
						value = float(matches.iloc[0][column]) / 1e6
						if not math.isfinite(value):
							return None
						total += value
				return total

			investments = components(
				[
					(
						"MarketableSecuritiesCurrent",
						"ShortTermInvestments",
						"DebtSecuritiesCurrent",
						"EquitySecuritiesFvNi",
					),
				]
			)
			borrowing = components(
				[
					(
						"DebtCurrent",
						"LongTermDebtCurrent",
						"LongTermDebtAndCapitalLeaseObligationsCurrent",
						"ShortTermBorrowings",
						"ShortTermDebtCurrent",
						"CommercialPaper",
					),
				]
			)
			for key, parent, excluded, amount, basis in (
				(
					"operating_current_assets",
					values.get("current_assets"),
					values.get("cash"),
					investments,
					"Current assets minus cash minus separately disclosed current investments",
				),
				(
					"operating_current_liabilities",
					values.get("current_liabilities"),
					0,
					borrowing,
					"Current liabilities minus separately disclosed current borrowing",
				),
			):
				value = (
					parent - excluded - amount
					if all(x is not None for x in (parent, excluded, amount))
					else None
				)
				groups[key] = {
					"value": value,
					"basis": basis
					+ "; absent face categories stay in the parent, never asserted as reported zero balances. Historical face groups do not include later note reclassifications.",
				}
				if value is None:
					issues.append(
						f"{period['label']} {key}: incomplete or potentially overlapping face categories; derived group left blank."
					)
		values.update({k: v["value"] for k, v in groups.items()})
		# Use the earnings bridge, not abs(reported tax): EdgarTools editions can
		# present deductions with different signs. An unreconciled bridge stays blank.
		pretax, reported_tax = values.get("pretax"), values.get("tax_reported")
		after_tax = values.get("continuing_income")
		if after_tax is None and values.get("discontinued_income") in (None, 0):
			after_tax = values.get("net_income")
			if after_tax is not None and values.get("minority_income") is not None:
				after_tax += values["minority_income"]
		values["tax_expense"] = None
		if all(v is not None for v in (pretax, reported_tax, after_tax)):
			expense = pretax - after_tax
			if min(abs(expense - reported_tax), abs(expense + reported_tax)) < 0.001:
				values["tax_expense"] = expense
				groups["tax_expense"] = {
					"value": expense,
					"basis": "Pretax minus continuing/consolidated after-tax income, checked against signed reported tax. Source tax is retained separately; no absolute-value normalization.",
				}
			else:
				issues.append(
					f"{period['label']}: tax earnings bridge is not reconciled; comparable tax expense left blank."
				)
		if values.get("discontinued_income") not in (None, 0):
			issues.append(
				f"{period['label']}: reported net income includes discontinued operations; it is not a like-for-like continuing-operations earnings trend."
			)
		# Durations are real boundaries, including a 53-week year, not invented calendar years.
		result.append(
			{
				**period,
				"days": (
					date.fromisoformat(period["end"])
					- date.fromisoformat(period["start"])
				).days
				+ 1,
				"values": values,
				"sources": sources,
				"groups": groups,
			}
		)
	return {
		"periods": result,
		"requested_years": years,
		"policy": "Latest available comparative presentation per statement and period within the frozen cutoff; missing/ambiguous values remain blank. Different filing editions are identified in Evidence. Balance sheets are dated observations, never TTM sums.",
		"issues": issues,
	}
