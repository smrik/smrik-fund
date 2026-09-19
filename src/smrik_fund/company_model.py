"""Source-bound inputs for the provisional second-company DCF method."""

import json
import math
import re
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from smrik_fund.analysis_budget import content_hash
from smrik_fund.company_case import validate_case
from smrik_fund.company_operating import COST_CONTROL_BOUNDS

BALANCES = {
	"cash": "CashAndCashEquivalentsAtCarryingValue",
	"short_investments": "MarketableSecuritiesCurrent",
	"receivables": "AccountsReceivableNetCurrent",
	"vendor_receivables": "NontradeReceivablesCurrent",
	"inventory": "InventoryNet", "other_current_assets": "OtherAssetsCurrent",
	"long_investments": "MarketableSecuritiesNoncurrent",
	"ppe": "PropertyPlantAndEquipmentNet",
	"intangibles_noncurrent": "aapl:IntangibleAssetsNetExcludingGoodwillNoncurrent",
	"other_noncurrent_assets": "OtherAssetsNoncurrent",
	"payables": "AccountsPayableCurrent", "other_current_liabilities": "OtherLiabilitiesCurrent",
	"deferred_revenue": "ContractWithCustomerLiabilityCurrent", "commercial_paper": "CommercialPaper",
	"current_debt": "LongTermDebtCurrent", "long_debt": "LongTermDebtNoncurrent",
	"other_noncurrent_liabilities": "OtherLiabilitiesNoncurrent", "equity": "StockholdersEquity",
	"assets": "Assets", "liabilities": "Liabilities",
}
FLOWS = {
	"revenue": ("income_statement", "RevenueFromContractWithCustomerExcludingAssessedTax"),
	"cost_of_sales": ("income_statement", "CostOfGoodsAndServicesSold"),
	"research": ("income_statement", "ResearchAndDevelopmentExpense"),
	"sga": ("income_statement", "SellingGeneralAndAdministrativeExpense"),
	"ebit": ("income_statement", "OperatingIncomeLoss"),
	"pretax": ("income_statement", "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"),
	"tax": ("income_statement", "IncomeTaxExpenseBenefit"),
	"net_income": ("income_statement", "NetIncomeLoss"),
	"da": ("cash_flow_statement", "DepreciationDepletionAndAmortization"),
	"sbc": ("cash_flow_statement", "ShareBasedCompensation"),
	"capex_cash": ("cash_flow_statement", "PaymentsToAcquirePropertyPlantAndEquipment"),
	"cfo": ("cash_flow_statement", "NetCashProvidedByUsedInOperatingActivities"),
	"cfi": ("cash_flow_statement", "NetCashProvidedByUsedInInvestingActivities"),
	"cff": ("cash_flow_statement", "NetCashProvidedByUsedInFinancingActivities"),
}
CONTROL_BOUNDS = {
	"products_growth": (-0.2, 0.3), "services_growth": (-0.2, 0.3),
	"ppe_life": (2, 20), "intangible_life": (2, 15),
	"intangible_additions_ratio": (0, 0.08), "payout_ratio": (0, 0.8),
	"risk_free": (0.01, 0.10), "equity_premium": (0.02, 0.10),
	"beta": (0.5, 2), "debt_rate": (0.01, 0.12),
	"terminal_growth": (0, 0.04), "share_price_proxy": (0.01, 1000000),
}
DEFAULT_CONTROLS = dict(zip(CONTROL_BOUNDS, [0.05, 0.10, 8, 5, 0.025, 0.4, 0.04, 0.05, 1.1, 0.045, 0.025, 250], strict=True))
POLICY_CONTROL_BOUNDS = {"forecast_tax_rate": (0, 0.6)}


def validate_controls(controls: dict) -> None:
	if not set(CONTROL_BOUNDS).issubset(controls) or set(controls) - (set(CONTROL_BOUNDS) | set(COST_CONTROL_BOUNDS) | set(POLICY_CONTROL_BOUNDS)):
		raise ValueError("Missing or unsupported forecast control")
	for key in controls:
		low, high = {**CONTROL_BOUNDS, **COST_CONTROL_BOUNDS, **POLICY_CONTROL_BOUNDS}[key]
		value = controls[key]
		if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not low <= value <= high:
			raise ValueError(f"Invalid forecast control: {key}")


def source_value(frame, concept, column, *, dimension_member=None):
	concept = concept.replace(":", "_") if ":" in concept else f"us-gaap_{concept}"
	rows = frame.loc[frame.concept.eq(concept)]
	if dimension_member is None:
		rows = rows.loc[~rows.dimension.astype(str).str.lower().eq("true")]
	else:
		rows = rows.loc[rows.dimension_member.eq(dimension_member)]
	rows = rows.loc[~rows.abstract.astype(str).str.lower().eq("true")]
	if len(rows) != 1 or column not in frame or pd.isna(rows.iloc[0][column]):
		raise ValueError(f"Missing/ambiguous source: {concept}, {column}, {dimension_member}")
	value = float(rows.iloc[0][column])
	if not math.isfinite(value):
		raise ValueError("Nonfinite reported value")
	return value / 1_000_000, int(rows.index[0]) + 2


def prepare_model(case_dir: Path, controls: dict | None = None) -> dict:
	case_dir = Path(case_dir).resolve()
	manifest = validate_case(case_dir)
	metadata = [json.loads((case_dir / a / "filing.json").read_text()) for a in manifest["selected_filings"]]
	annual = next(item for item in metadata if item["form"] == "10-K")
	interim = max(metadata, key=lambda item: item["measurement_date"])
	if interim["form"] != "10-Q":
		raise ValueError("Current provisional method requires annual and newer interim history")
	frames = {item["accession"]: {name: pd.read_csv(case_dir / item["accession"] / f"{name}.csv") for name in ("income_statement", "balance_sheet", "cash_flow_statement")} for item in metadata}
	current = interim["measurement_date"]
	periods = [p for p in interim["reporting_periods"] if p["type"] == "duration" and p.get("fiscal_period", "").startswith("YTD")]
	current_period = [p for p in periods if p["end_date"] == current]
	prior_period = [p for p in periods if p.get("fiscal_year") == int(interim["entity"]["fiscal_year"]) - 1]
	if len(current_period) != 1 or len(prior_period) != 1:
		raise ValueError("Ambiguous current/prior comparable YTD periods")
	cp, pp = current_period[0], prior_period[0]
	annual_period = [p for p in annual["reporting_periods"] if p.get("fiscal_period") == "FY" and p.get("end_date") == annual["measurement_date"]]
	if len(annual_period) != 1 or date.fromisoformat(cp["start_date"]) != date.fromisoformat(annual["measurement_date"]) + timedelta(days=1) or annual_period[0]["start_date"] != pp["start_date"] or abs(cp["days"] - pp["days"]) > 7:
		raise ValueError("Incompatible annual/YTD source windows")
	evidence = []
	def observe(meta, statement, concept, column, member=None):
		value, line = source_value(frames[meta["accession"]][statement], concept, column, dimension_member=member)
		evidence.append({"id": f"S{len(evidence)+1}", "file": f"{meta['accession']}/{statement}.csv", "line": line, "concept": concept, "column": column, "dimension_member": member, "reported_value": value * 1_000_000, "display_value": value, "display_scale": 1_000_000, "units": "USD millions" if "Shares" not in concept else "million shares"})
		return value
	opening = {key: observe(interim, "balance_sheet", concept, current) for key, concept in BALANCES.items()}
	flow_history = {}
	for key, (statement, concept) in FLOWS.items():
		values = [observe(meta, statement, concept, column) for meta, column in ((annual, annual["measurement_date"] + " (FY)"), (interim, current + " (YTD)"), (interim, pp["end_date"] + " (YTD)"))]
		flow_history[key] = {"annual": values[0], "current_ytd": values[1], "prior_ytd": values[2], "ttm": values[0] + values[1] - values[2]}
	segments = {}
	for label, member in (("Products", "us-gaap_ProductMember"), ("Services", "us-gaap_ServiceMember")):
		segments[label] = {key: observe(meta, "income_statement", FLOWS["revenue"][1], column, member) for key, meta, column in (("annual", annual, annual["measurement_date"] + " (FY)"), ("current_ytd", interim, current + " (YTD)"), ("prior_ytd", interim, pp["end_date"] + " (YTD)"))}
		segments[label]["ttm"] = segments[label]["annual"] + segments[label]["current_ytd"] - segments[label]["prior_ytd"]
	for period in ("annual", "current_ytd", "prior_ytd", "ttm"):
		if abs(sum(s[period] for s in segments.values()) - flow_history["revenue"][period]) > 0.001:
			raise ValueError("Product/service breakdown does not reconcile to consolidated revenue")
		if abs(flow_history["revenue"][period]-sum(flow_history[k][period] for k in ("cost_of_sales", "research", "sga"))-flow_history["ebit"][period]) > 0.001:
			raise ValueError("Reported operating-income bridge does not reconcile")
		if abs(flow_history["pretax"][period]-flow_history["tax"][period]-flow_history["net_income"][period]) > 0.001:
			raise ValueError("Reported net-income bridge does not reconcile")
	annual_text = (case_dir / annual["accession"] / "source.txt").read_text()
	interim_text = (case_dir / interim["accession"] / "source.txt").read_text()
	dep = re.search(r"Depreciation expense on property, plant and equipment was \$\s*([\d.]+)\s*billion", annual_text)
	cur_int = re.search(r"Less: Current portion of intangible assets, net\s*\(\s*([\d,]+)\)", interim_text)
	if not dep or not cur_int:
		raise ValueError("Required disclosed depreciation/intangible detail unavailable for this method")
	opening["intangibles_current"] = float(cur_int[1].replace(",", ""))
	for meta, text, match, name, value in ((annual, annual_text, dep, "annual_ppe_depreciation", float(dep[1])*1000), (interim, interim_text, cur_int, "intangibles_current", opening["intangibles_current"])):
		evidence.append({"id": f"S{len(evidence)+1}", "file": f"{meta['accession']}/source.txt", "line": text[:match.start()].count("\n")+1, "concept": name, "column": meta["measurement_date"], "display_value": value, "units": "USD millions", "excerpt": match[0]})
	opening["shares_proxy"] = observe(interim, "income_statement", "WeightedAverageNumberOfDilutedSharesOutstanding", current + f" ({interim['entity']['fiscal_period']})")
	asset_sum = sum(opening[k] for k in ("cash", "short_investments", "receivables", "vendor_receivables", "inventory", "other_current_assets", "long_investments", "ppe", "intangibles_noncurrent", "other_noncurrent_assets"))
	liab_sum = sum(opening[k] for k in ("payables", "other_current_liabilities", "deferred_revenue", "commercial_paper", "current_debt", "long_debt", "other_noncurrent_liabilities"))
	if max(abs(asset_sum-opening["assets"]), abs(liab_sum-opening["liabilities"]), abs(opening["assets"]-opening["liabilities"]-opening["equity"])) > 0.001:
		raise ValueError("Opening balance-sheet source components do not reconcile")
	if opening["intangibles_current"] > opening["other_current_assets"] or flow_history["capex_cash"]["ttm"] > 0:
		raise ValueError("Unsupported intangible allocation or reported capex sign")
	fy = int(interim["entity"]["fiscal_year"])
	first_end = date(fy, int(interim["entity"]["fiscal_year_end_month"]), int(interim["entity"]["fiscal_year_end_day"]))
	if first_end <= date.fromisoformat(current):
		raise ValueError("Forecast stub must follow the measurement date")
	ends = [first_end + timedelta(weeks=52*i) for i in range(11)]
	controls = dict(DEFAULT_CONTROLS if controls is None else controls)
	validate_controls(controls)
	return {
		"schema_version": "company-dcf-development-v1", "case": manifest["ticker"], "company_name": manifest["company_name"],
		"case_dir": str(case_dir), "case_hash": content_hash(manifest), "measurement_date": current, "information_cutoff": manifest["information_cutoff"],
		"units": "USD millions, million shares, USD/share", "opening": opening, "history": flow_history, "segments": segments,
		"estimated_ttm_ppe_depreciation": float(dep[1])*1000 / flow_history["da"]["annual"] * flow_history["da"]["ttm"],
		"periods": [{"id": f"FY{fy+i}" + ("_STUB" if i==0 else ""), "end": end.isoformat(), "fraction": (end-(date.fromisoformat(current) if i==0 else ends[i-1])).days/364, "elapsed": (end-date.fromisoformat(current)).days/365} for i, end in enumerate(ends)],
		"controls": controls, "control_bounds": CONTROL_BOUNDS, "evidence": evidence,
		"review": {"status": "PROVISIONAL_UNREVIEWED", "human_approval": False},
		"limitations": [
			"Development E2E scenario; not a current investment valuation. Agent-selected assumptions authorized by Patrik.",
			"Products/Services is a disclosed product view, not the geographic reportable-segment hierarchy; SG&A remains combined.",
			"TTM PP&E depreciation is estimated using the disclosed annual PP&E/combined-D&A ratio. Remaining D&A is allocated to intangibles provisionally.",
			"Forecast removes total embedded D&A and adds explicit PP&E/intangible schedules. The split is diagnostic; chosen depreciation horizons drive declining-carrying-value charges, not straight-line vintage useful lives.",
			"Future calendar assumes 52-week years after the disclosed current fiscal year end; future 53rd weeks are not claimed as reported dates.",
			"Other noncurrent assets/liabilities and securities held flat. Operating leases remain within reported operating costs/other balances, without debt reclassification.",
			"Debt held constant through refinancing; cash taxes equal book tax; no deferred-tax/tax-payable forecast split.",
			"Diluted quarterly average shares proxy for valuation shares and existing award dilution; not sourced point-in-time shares. No separate existing-award claim. Future SBC stays an economic expense in UFCF.",
			"Beta, risk-free rate, ERP, debt rate and share-price proxy are development scenarios, not observed market estimates.",
			"Terminal reinvestment normalizes capex minus depreciation to growth times closing PP&E/intangibles, plus working-capital growth; perpetual excess cash is not counted twice.",
		],
	}
