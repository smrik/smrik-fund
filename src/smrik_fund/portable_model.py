"""Consolidated development DCF inputs from dated SEC statement aggregates.

No ticker-specific mappings. Missing required facts stop the model. Structural
zero slots mean a category is grouped elsewhere, never a missing reported fact.
"""

import calendar
import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from smrik_fund.analysis_budget import content_hash
from smrik_fund.company_case import validate_case
from smrik_fund.company_model import (
	CONTROL_BOUNDS,
	DEFAULT_CONTROLS,
	source_value,
	validate_controls,
)
from smrik_fund.company_notes import note_claims


def flow_windows(annual, latest):
	"""Select comparable durations by boundaries, including 12/36-week issuers."""

	def durations(meta):
		return [p for p in meta["reporting_periods"] if p["type"] == "duration"]

	fy = [
		p
		for p in durations(annual)
		if p["end_date"] == annual["measurement_date"] and 350 <= p["days"] <= 380
	]
	if len(fy) != 1:
		raise ValueError("Unsupported/ambiguous annual duration")
	if latest["form"] == "10-K":
		return fy[0], None, None
	start = (date.fromisoformat(fy[0]["end_date"]) + timedelta(days=1)).isoformat()
	current = [
		p
		for p in durations(latest)
		if p["start_date"] == start and p["end_date"] == latest["measurement_date"]
	]
	prior = [
		p
		for p in durations(latest)
		if p["start_date"] == fy[0]["start_date"]
		and current
		and abs(p["days"] - current[0]["days"]) <= 7
	]
	if len(current) != 1 or len(prior) != 1:
		raise ValueError("Unsupported/ambiguous comparable fiscal durations")
	return fy[0], current[0], prior[0]


def flow_column(frame, period, *, annual=False):
	columns = [c for c in frame if c.startswith(period["end_date"] + " (")]
	preferred = [c for c in columns if c.endswith("(FY)" if annual else "(YTD)")]
	# A first-quarter YTD has the same start/end as its only quarterly column.
	if not preferred and not annual and 75 <= period["days"] <= 100:
		preferred = [c for c in columns if c.endswith("(Q1)")]
	if len(preferred) != 1:
		raise ValueError(
			f"Unsupported/ambiguous statement column for {period['start_date']}:{period['end_date']}"
		)
	return preferred[0]


def prepare_model(case_dir, controls=None):
	case_dir = Path(case_dir).resolve()
	manifest = validate_case(case_dir)
	metadata = [
		json.loads((case_dir / a / "filing.json").read_text())
		for a in manifest["selected_filings"]
	]
	annual = next(m for m in metadata if m["form"] == "10-K")
	latest = max(metadata, key=lambda m: m["measurement_date"])
	frames = {
		m["accession"]: {
			s: pd.read_csv(case_dir / m["accession"] / f"{s}.csv")
			for s in ("income_statement", "balance_sheet", "cash_flow_statement")
		}
		for m in metadata
	}
	fy, cp, pp = flow_windows(annual, latest)
	evidence, allocations = [], []

	def face(meta, statement):
		df = frames[meta["accession"]][statement]
		return df.loc[
			~df.dimension.astype(str).str.lower().eq("true")
			& ~df.abstract.astype(str).str.lower().eq("true")
		]

	def read(meta, statement, concepts, column):
		matches = face(meta, statement)
		matches = matches.loc[
			matches.concept.isin(
				[c.replace(":", "_") if ":" in c else "us-gaap_" + c for c in concepts]
			)
		]
		if len(matches) != 1:
			raise ValueError(
				f"Unsupported/ambiguous {statement} fact: {concepts}; found {len(matches)}"
			)
		concept = matches.iloc[0].concept
		concept = (
			concept.removeprefix("us-gaap_")
			if concept.startswith("us-gaap_")
			else concept.replace("_", ":", 1)
		)
		value, line = source_value(
			frames[meta["accession"]][statement], concept, column
		)
		evidence.append(
			{
				"id": f"S{len(evidence) + 1}",
				"file": f"{meta['accession']}/{statement}.csv",
				"line": line,
				"concept": concept,
				"column": column,
				"reported_value": value * 1e6,
				"display_value": value,
				"units": "million shares" if "Shares" in concept else "USD millions",
			}
		)
		return value

	current = latest["measurement_date"]
	bs = face(latest, "balance_sheet")
	# This enterprise DCF requires an industrial-company classified balance sheet.
	if any(
		bs.concept.str.contains(r"Deposits|Policyholder|InsuranceContract", case=False)
	):
		raise ValueError(
			"Unsupported enterprise DCF: financial institution requires a sector-specific valuation method"
		)

	def balance(*concepts):
		return read(latest, "balance_sheet", concepts, current)

	def disclosed_group(name, groups):
		values = []
		for alternatives in groups:
			found = bs.loc[bs.concept.isin(["us-gaap_" + c for c in alternatives])]
			if not found.empty:
				values.append(balance(*alternatives))
		allocations.append(
			{
				"group": name,
				"basis": "Sum of separately presented components; absent detail remains inside its reported parent aggregate",
				"component_count": len(values),
				"value": sum(values),
			}
		)
		return sum(values)

	if "us-gaap_CashAndCashEquivalentsAtCarryingValue" in set(bs.concept):
		cash = balance("CashAndCashEquivalentsAtCarryingValue")
	else:
		cash_total = balance(
			"CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"
		)
		cash_caption = bs.loc[
			bs.concept.eq(
				"us-gaap_CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"
			),
			"label",
		].iloc[0]
		cash_note = note_claims(
			case_dir, latest, evidence, cash_total=cash_total, cash_caption=cash_caption
		)
		if cash_note is None:
			raise ValueError("Combined cash requires a frozen note reconciliation")
		cash = cash_note["unrestricted_cash"]
		allocations.append(
			{"group": "available cash", "basis": cash_note["basis"], "value": cash}
		)
	assets, ca = balance("Assets"), balance("AssetsCurrent")
	cl = balance("LiabilitiesCurrent")
	if "us-gaap_Liabilities" in set(bs.concept):
		liabilities = balance("Liabilities")
	else:
		children = bs.loc[
			bs.parent_concept.eq("us-gaap_LiabilitiesAndStockholdersEquity")
			& ~bs.concept.isin(
				[
					"us-gaap_StockholdersEquity",
					"us-gaap_StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
					"us-gaap_MinorityInterest",
					"us-gaap_CommitmentsAndContingencies",
				]
			)
		]
		if len(children) < 2 or "us-gaap_LiabilitiesCurrent" not in set(
			children.concept
		):
			raise ValueError(
				"Missing liabilities total and unambiguous statement hierarchy"
			)
		liabilities = sum(
			balance(
				c.removeprefix("us-gaap_")
				if c.startswith("us-gaap_")
				else c.replace("_", ":", 1)
			)
			for c in children.concept
		)
		allocations.append(
			{
				"group": "total liabilities",
				"basis": "Sum of disclosed direct liability children of LiabilitiesAndStockholdersEquity; equity and nonmonetary commitments excluded",
				"value": liabilities,
			}
		)
	equity = balance("StockholdersEquity")
	minority = None
	if "us-gaap_MinorityInterest" in set(bs.concept):
		minority = balance("MinorityInterest")
		total_equity = balance(
			"StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"
		)
		if minority < 0 or abs(equity + minority - total_equity) > 0.001:
			raise ValueError(
				"Common equity and minority interest do not reconcile to consolidated equity"
			)
		allocations.append(
			{
				"group": "minority interest claim",
				"basis": "Reported common equity plus minority interest reconciles to consolidated equity. Consolidated forecast retains all earnings; NCI claim deducted from enterprise-to-common-equity bridge at a provisional constant carrying-value proxy. No separate minority earnings forecast.",
				"value": minority,
			}
		)
		equity = total_equity
	if abs(assets - liabilities - equity) > 0.001:
		raise ValueError(
			"Unsupported equity/claims: reported assets minus liabilities differs from common-company equity"
		)
	short = disclosed_group(
		"current investments",
		[
			("MarketableSecuritiesCurrent", "ShortTermInvestments"),
			("DebtSecuritiesCurrent",),
			("EquitySecuritiesFvNi",),
		],
	)
	long = disclosed_group(
		"noncurrent investments",
		[
			(
				"MarketableSecuritiesNoncurrent",
				"LongTermInvestments",
				"OtherLongTermInvestments",
			)
		],
	)
	debt_current = disclosed_group(
		"current borrowing",
		[
			("LongTermDebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent"),
			("ShortTermBorrowings", "ShortTermDebtCurrent"),
			("CommercialPaper",),
		],
	)
	if "us-gaap_DebtCurrent" in set(bs.concept):
		if debt_current:
			raise ValueError("Ambiguous current debt total and components")
		debt_current = balance("DebtCurrent")
	debt_long = disclosed_group(
		"noncurrent borrowing",
		[
			(
				"LongTermDebtNoncurrent",
				"LongTermDebt",
				"LongTermDebtAndCapitalLeaseObligations",
			)
		],
	)
	notes = note_claims(case_dir, latest, evidence)
	if notes:
		if notes["finance_current"] is not None:
			combined = {
				"us-gaap_LongTermDebtAndCapitalLeaseObligationsCurrent",
				"us-gaap_LongTermDebtAndCapitalLeaseObligations",
			}
			if combined.issubset(set(bs.concept)):
				if (
					notes["finance_current"] > debt_current
					or notes["finance_noncurrent"] > debt_long
				):
					raise ValueError(
						"Finance leases exceed their combined borrowing balances"
					)
				basis = "Finance lease notes are components of BOTH reported combined borrowing tags. Already counted in current/noncurrent debt; not added again."
			elif any(c in set(bs.concept) for c in combined):
				raise ValueError(
					"Incomplete combined borrowing classification for finance leases"
				)
			else:
				debt_current += notes["finance_current"]
				debt_long += notes["finance_noncurrent"]
				basis = "Sourced finance lease liabilities reclassified from current/noncurrent operating aggregates into constant refinanced borrowing"
			allocations.append(
				{
					"group": "finance lease debt claim",
					"basis": basis,
					"value": notes["finance_current"] + notes["finance_noncurrent"],
				}
			)
		if notes["nonmarketable_investments"] is not None:
			if long:
				raise ValueError(
					"Potential overlap between face investment total and supplementary note components"
				)
			long = notes["nonmarketable_investments"]
			allocations.append(
				{
					"group": "nonmarketable investments",
					"basis": "Note-bound private equity, equity-method, warrant and convertible-note assets removed from Other assets and added once to investment bridge at carrying-value proxy",
					"value": long,
				}
			)
	ppe = balance(
		"PropertyPlantAndEquipmentNet",
		"PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization",
	)
	intangible = disclosed_group(
		"separately disclosed finite intangibles",
		[("FiniteLivedIntangibleAssetsNet", "IntangibleAssetsNetExcludingGoodwill")],
	)
	# Derived parent-minus-component groups preserve every other reported balance.
	other_ca = ca - cash - short
	other_nca = assets - ca - long - ppe - intangible
	other_cl = cl - debt_current
	other_ncl = liabilities - cl - debt_long
	if min(other_ca, other_nca, other_cl, other_ncl, ppe, intangible) < -0.001:
		raise ValueError("Overlapping or incompatible source balance components")
	allocations.extend(
		[
			{"group": k, "basis": formula, "value": v}
			for k, formula, v in [
				(
					"operating current assets",
					"AssetsCurrent - cash - separately disclosed current investments",
					other_ca,
				),
				(
					"remaining noncurrent assets",
					"Assets - AssetsCurrent - noncurrent investments - PPE - disclosed finite intangibles",
					other_nca,
				),
				(
					"operating current liabilities",
					"LiabilitiesCurrent - separately disclosed current borrowing",
					other_cl,
				),
				(
					"remaining noncurrent liabilities",
					"Liabilities - LiabilitiesCurrent - separately disclosed noncurrent borrowing",
					other_ncl,
				),
			]
		]
	)
	opening = {
		"cash": cash,
		"short_investments": short,
		"long_investments": long,
		"receivables": other_ca,
		"vendor_receivables": 0,
		"inventory": 0,
		"other_current_assets": 0,
		"ppe": ppe,
		"intangibles_noncurrent": intangible,
		"intangibles_current": 0,
		"other_noncurrent_assets": other_nca,
		"payables": other_cl,
		"deferred_revenue": 0,
		"other_current_liabilities": 0,
		"commercial_paper": 0,
		"current_debt": debt_current,
		"long_debt": debt_long,
		"other_noncurrent_liabilities": other_ncl,
		"equity": equity,
		"assets": assets,
		"liabilities": liabilities,
	}
	if minority is not None:
		opening["minority_interest_proxy"] = minority

	def history(statement, concepts):
		windows = [(annual, fy)] + ([(latest, cp), (latest, pp)] if cp else [])
		values = [
			read(
				m,
				statement,
				concepts,
				flow_column(frames[m["accession"]][statement], period, annual=i == 0),
			)
			for i, (m, period) in enumerate(windows)
		]
		if cp is None:
			# Structural zero: no stub/YTD required for an annual-only model.
			values += [0, 0]
		return dict(
			zip(
				("annual", "current_ytd", "prior_ytd", "ttm"),
				values + [values[0] + values[1] - values[2]],
				strict=True,
			)
		)

	flow = {
		k: history(s, concepts)
		for k, s, concepts in [
			(
				"revenue",
				"income_statement",
				(
					"RevenueFromContractWithCustomerExcludingAssessedTax",
					"Revenues",
					"SalesRevenueNet",
					"RevenueFromContractWithCustomerIncludingAssessedTax",
				),
			),
			("ebit", "income_statement", ("OperatingIncomeLoss",)),
			("net_income", "income_statement", ("NetIncomeLoss",)),
			("tax", "income_statement", ("IncomeTaxExpenseBenefit",)),
			(
				"da",
				"cash_flow_statement",
				(
					"DepreciationDepletionAndAmortization",
					"DepreciationDepletionAndAmortizationPropertyPlantAndEquipment",
					"DepreciationAmortizationAndAccretionNet",
					"Depreciation",
				),
			),
			("sbc", "cash_flow_statement", ("ShareBasedCompensation",)),
			(
				"capex_cash",
				"cash_flow_statement",
				(
					"PaymentsToAcquirePropertyPlantAndEquipment",
					"PaymentsToAcquireProductiveAssets",
				),
			),
			(
				"cfo",
				"cash_flow_statement",
				("NetCashProvidedByUsedInOperatingActivities",),
			),
			(
				"cfi",
				"cash_flow_statement",
				("NetCashProvidedByUsedInInvestingActivities",),
			),
			(
				"cff",
				"cash_flow_statement",
				("NetCashProvidedByUsedInFinancingActivities",),
			),
		]
	}
	flow["tax_reported"] = dict(flow["tax"])
	minority_income = "NetIncomeLossAttributableToNoncontrollingInterest"
	if all(
		"us-gaap_" + minority_income in set(face(m, "income_statement").concept)
		for m in metadata
	):
		flow["net_income_parent"] = dict(flow["net_income"])
		flow["minority_income"] = history("income_statement", (minority_income,))
		flow["net_income"] = {
			p: flow["net_income_parent"][p] + flow["minority_income"][p]
			for p in flow["revenue"]
		}
		allocations.append(
			{
				"group": "consolidated net income",
				"basis": "Reported parent-company earnings plus separately reported noncontrolling earnings. Parent and minority amounts retained separately; consolidated earnings reconcile to consolidated equity.",
				"value": flow["net_income"]["ttm"],
			}
		)
	pretax_concepts = (
		"IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
		"IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
	)
	if all(
		any(
			"us-gaap_" + c in set(face(m, "income_statement").concept)
			for c in pretax_concepts
		)
		for m in metadata
	):
		flow["pretax"] = history("income_statement", pretax_concepts)
		equity_concept = "IncomeLossFromEquityMethodInvestments"
		equity_income = dict.fromkeys(flow["revenue"], 0)
		excludes_equity_income = "us-gaap_IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"
		# Only the pretax subtotal explicitly EXCLUDING equity-method income
		# needs an after-tax addback. Otherwise it is already in reported pretax.
		if all(
			excludes_equity_income in set(face(m, "income_statement").concept)
			for m in metadata
		) and all(
			"us-gaap_" + equity_concept in set(face(m, "income_statement").concept)
			for m in metadata
		):
			equity_income = history("income_statement", (equity_concept,))
			flow["equity_income_after_tax"] = equity_income
		for period in flow["revenue"]:
			expense = (
				flow["pretax"][period]
				+ equity_income[period]
				- flow["net_income"][period]
			)
			if (
				min(
					abs(expense - flow["tax_reported"][period]),
					abs(expense + flow["tax_reported"][period]),
				)
				> 0.001
			):
				raise ValueError("Tax/net-income/pretax bridge does not reconcile")
			flow["tax"][period] = expense
		allocations.append(
			{
				"group": "tax expense",
				"basis": "Derived reported pretax plus disclosed after-tax equity income minus net income; signed source tax retained separately in tax_reported; bridge checked",
				"value": flow["tax"]["ttm"],
			}
		)
	else:
		flow["pretax"] = {
			p: flow["net_income"][p] + flow["tax"][p] for p in flow["revenue"]
		}
	flow["cost_of_sales"] = {
		p: flow["revenue"][p] - flow["ebit"][p] for p in flow["revenue"]
	}
	flow["research"] = dict.fromkeys(flow["revenue"], 0)
	flow["sga"] = dict.fromkeys(flow["revenue"], 0)
	if (
		flow["capex_cash"]["ttm"] > 0
		or flow["revenue"]["ttm"] <= 0
		or flow["cost_of_sales"]["ttm"] <= 0
	):
		raise ValueError(
			"Unsupported cash-flow sign or nonpositive revenue/operating expense base"
		)
	historical_rate = (
		flow["tax"]["ttm"] / flow["pretax"]["ttm"]
		if flow["pretax"]["ttm"] > 0
		else None
	)
	tax_rate = (
		historical_rate
		if historical_rate is not None and 0 <= historical_rate < 1
		else 0.25
	)
	allocations.append(
		{
			"group": "forecast tax rate",
			"basis": "Historical effective rate when usable; otherwise explicit provisional 25% normalized rate, without changing reported tax or modeling NOLs",
			"value": tax_rate,
			"units": "ratio",
		}
	)
	share_col = current + (
		" (FY)" if cp is None else f" ({latest['entity']['fiscal_period']})"
	)
	income_frame = frames[latest["accession"]]["income_statement"]
	if cp is not None and share_col not in income_frame:
		quarters = [
			p
			for p in latest["reporting_periods"]
			if p.get("end_date") == current and 75 <= p.get("days", 0) <= 100
		]
		columns = [
			c for c in income_frame if c.startswith(current + " (Q") and c.endswith(")")
		]
		if len(quarters) != 1 or len(columns) != 1:
			raise ValueError("Ambiguous current-quarter period for diluted shares")
		share_col = columns[0]
		allocations.append(
			{
				"group": "quarterly share period",
				"basis": f"Unique native quarter column {share_col} bound to reported {quarters[0]['start_date']} through {current}; provider quarter label differs from issuer fiscal label",
				"value": None,
			}
		)
	if "us-gaap_WeightedAverageNumberOfDilutedSharesOutstanding" in set(
		face(latest, "income_statement").concept
	):
		opening["shares_proxy"] = read(
			latest,
			"income_statement",
			("WeightedAverageNumberOfDilutedSharesOutstanding",),
			share_col,
		)
	else:
		income = read(latest, "income_statement", ("NetIncomeLoss",), share_col)
		eps = (
			read(latest, "income_statement", ("EarningsPerShareDiluted",), share_col)
			* 1e6
		)
		evidence[-1].update(display_value=eps, units="USD/share")
		if eps <= 0 or income <= 0:
			raise ValueError(
				"Unsupported diluted-share inference from nonpositive income/EPS"
			)
		opening["shares_proxy"] = income / eps
		allocations.append(
			{
				"group": "shares_proxy",
				"basis": "ESTIMATE: quarterly net income / rounded consolidated diluted EPS; if-converted and award dilution embedded, no separate preferred claim",
				"value": opening["shares_proxy"],
			}
		)
	if opening["shares_proxy"] <= 0:
		raise ValueError("Nonpositive diluted-share proxy")
	measurement = date.fromisoformat(current)
	year = int(latest["entity"]["fiscal_year"])
	month = int(latest["entity"]["fiscal_year_end_month"])
	day = int(latest["entity"]["fiscal_year_end_day"])
	end = date(year, month, min(day, calendar.monthrange(year, month)[1]))
	if cp is None:
		year += 1
		end = date(year, month, min(day, calendar.monthrange(year, month)[1]))
	elif end <= measurement:
		# Retail issuers can name FY2026 for a year ending in January 2027.
		# Keep the issuer's fiscal label; place its reported month/day after the
		# measurement date, independently of that label.
		end = date(
			measurement.year + 1,
			month,
			min(day, calendar.monthrange(measurement.year + 1, month)[1]),
		)
	week_calendar = fy["days"] + 1 in (364, 371)
	ends = [
		end + timedelta(weeks=52 * i)
		if week_calendar
		else date(
			end.year + i, month, min(day, calendar.monthrange(end.year + i, month)[1])
		)
		for i in range(11)
	]
	if cp is None and week_calendar:
		ends = [measurement + timedelta(weeks=52 * (i + 1)) for i in range(11)]
	periods = [
		{
			"id": f"FY{year + i}" + ("_STUB" if i == 0 and cp else ""),
			"end": e.isoformat(),
			"fraction": (e - measurement).days
			/ (
				364
				if week_calendar
				else (
					e
					- date(
						e.year - 1,
						month,
						min(day, calendar.monthrange(e.year - 1, month)[1]),
					)
				).days
			)
			if i == 0
			else 1,
			"elapsed": (e - measurement).days / 365,
		}
		for i, e in enumerate(ends)
	]
	chosen = dict(DEFAULT_CONTROLS if controls is None else controls)
	chosen["payout_ratio"] = 0 if controls is None else chosen["payout_ratio"]
	chosen["services_growth"] = 0
	chosen["intangible_additions_ratio"] = 0
	validate_controls(chosen)
	return {
		"schema_version": "company-dcf-development-v1",
		"method": "consolidated-development-v1",
		"case": manifest["ticker"],
		"company_name": manifest["company_name"],
		"case_dir": str(case_dir),
		"case_hash": content_hash(manifest),
		"measurement_date": current,
		"information_cutoff": manifest["information_cutoff"],
		"units": "USD millions, million shares, USD/share",
		"opening": opening,
		"history": flow,
		"segments": {
			"Products": flow["revenue"],
			"Services": dict.fromkeys(flow["revenue"], 0),
		},
		"estimated_ttm_ppe_depreciation": flow["da"]["ttm"] * ppe / (ppe + intangible)
		if ppe + intangible
		else 0,
		"periods": periods,
		"normalized_tax_rate": tax_rate,
		"controls": chosen,
		"control_bounds": CONTROL_BOUNDS,
		"evidence": evidence,
		"allocations": allocations,
		"review": {"status": "PROVISIONAL_UNREVIEWED", "human_approval": False},
		"limitations": [
			"Consolidated development scenario: no segment forecast. Revenue growth controls the whole company; additional revenue slots are structural zeros, not missing source facts.",
			"Operating expense = reported revenue minus operating income; pretax is reported when available, otherwise net income plus tax; tax expense is derived from the checked earnings bridge while signed reported tax is retained separately. Separate R&D/SG&A slots are structural zeros because expenses are aggregated. Discontinued/minority earnings require separate review.",
			"Current operating assets/liabilities are explicit reported parent-minus-component groups and scale with revenue; tax accruals, leases and deferred revenue remain aggregated. No balance plugs.",
			"Only separately presented borrowing and investment amounts are isolated; components embedded in other balances remain there. Debt uses carrying values and constant refinancing; investments use carrying-value and scenario-yield proxies.",
			"Total historical D&A is provisionally assigned to disclosed PPE/finite-intangible pools by carrying weights; forecast uses declining balance with half-period additions. Hidden intangible detail remains in other balances; no claim of sourced depreciation lives.",
			"Reported productive-asset capex, when combined, is allocated to the PP&E schedule provisionally; PP&E may include finance-lease ROU assets. Depreciation-only disclosures are not relabeled as separately sourced total amortization. Financed asset additions are not projected separately.",
			"Goodwill and other noncurrent balances are held flat. No future acquisitions or intangible additions by default; omitted additions may be a material scenario limitation.",
			"Where note detail is available, finance leases are reclassified into refinanced debt and nonmarketable investment components into the carrying-value bridge. Operating leases remain operating. Future asset additions are cash funded; no new finance leases are assumed.",
			"Default distributions are zero to retain cash for capital spending; analyst controls may change this. No automatic debt/cash plugs. Cash tax equals book tax; usable historical effective-tax ratio retained, otherwise explicit 25% normalized development tax rate (no NOL modeling). Future SBC remains expensed in UFCF, with a separate cash addback and equity contribution.",
			"Diluted weighted-average shares, or net income divided by rounded consolidated diluted EPS when the count is not on the face statement, are a valuation proxy; no separate award claim. Market-price, beta, yields and terminal growth are provisional scenarios, not observed investment inputs.",
			"Forecast dates use the reported fiscal year-end and a provisional 52-week or calendar-year extension. Annual-only cases start with a full forecast year.",
			"Terminal reinvestment is growth times closing operating capital; future excess cash is not added again. Human financial approval is false.",
		],
	}
