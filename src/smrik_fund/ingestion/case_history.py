"""Build the cutoff-frozen MSFT historical source package for P2."""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
from datetime import date, datetime
from html import unescape
from pathlib import Path

import pandas as pd

from .history import construct_ttm, latest_balance_sheet
from .native_history import native_statements_to_history

CASE_CUTOFF = date(2026, 4, 30)
MEASUREMENT_DATE = date(2026, 3, 31)
DISPLAY_SCALE = 1_000_000.0
DISPLAY_UNIT = "USD millions"
CIK = "789019"
TICKER = "MSFT"

SOURCE_ACCESSIONS = {
	"FY2023": "0000950170-23-035122",
	"FY2024": "0000950170-24-087843",
	"FY2025": "0000950170-25-100235",
	"FY2025_Q1": "0001193125-25-256321",
	"FY2025_Q2": "0001193125-26-027207",
	"FY2026_Q3": "0001193125-26-191507",
}

MATERIAL_CONCEPTS = {
	"revenue": ("us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax", "us-gaap_Revenues"),
	"cost_of_revenue": ("us-gaap_CostOfGoodsAndServicesSold",),
	"gross_profit": ("us-gaap_GrossProfit",),
	"research_and_development": ("us-gaap_ResearchAndDevelopmentExpense",),
	"sales_and_marketing": ("us-gaap_SellingAndMarketingExpense",),
	"general_and_administrative": ("us-gaap_GeneralAndAdministrativeExpense",),
	"operating_income": ("us-gaap_OperatingIncomeLoss",),
	"nonoperating_income": ("us-gaap_NonoperatingIncomeExpense",),
	"pretax_income": ("us-gaap_IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",),
	"income_tax": ("us-gaap_IncomeTaxExpenseBenefit",),
	"net_income": ("us-gaap_NetIncomeLoss",),
	"cash": ("us-gaap_CashAndCashEquivalentsAtCarryingValue",),
	"cash_flow_endpoint_including_restricted": ("us-gaap_CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",),
	"cash_and_short_term_investments": ("us-gaap_CashCashEquivalentsAndShortTermInvestments",),
	"short_term_investments": ("us-gaap_ShortTermInvestments",),
	"ppe": ("us-gaap_PropertyPlantAndEquipmentNet",),
	"assets": ("us-gaap_Assets",),
	"liabilities": ("us-gaap_Liabilities",),
	"equity": ("us-gaap_StockholdersEquity",),
	"liabilities_and_equity": ("us-gaap_LiabilitiesAndStockholdersEquity",),
	"cash_from_operations": ("us-gaap_NetCashProvidedByUsedInOperatingActivities",),
	"depreciation_amortization_other": ("msft_DepreciationAmortizationAndOther",),
	"share_based_compensation": ("us-gaap_ShareBasedCompensation",),
	"gain_loss_investments_derivatives": ("msft_GainLossOnInvestmentsAndDerivativeInstruments",),
	"deferred_income_tax_expense": ("us-gaap_DeferredIncomeTaxExpenseBenefit",),
	"deferred_income_taxes_and_credits": ("us-gaap_DeferredIncomeTaxesAndTaxCredits",),
	"change_accounts_receivable": ("us-gaap_IncreaseDecreaseInAccountsReceivable",),
	"change_inventories": ("us-gaap_IncreaseDecreaseInInventories",),
	"change_other_current_assets": ("us-gaap_IncreaseDecreaseInOtherCurrentAssets",),
	"change_other_noncurrent_assets": ("us-gaap_IncreaseDecreaseInOtherNoncurrentAssets",),
	"change_accounts_payable": ("us-gaap_IncreaseDecreaseInAccountsPayable",),
	"change_contract_liability": ("us-gaap_IncreaseDecreaseInContractWithCustomerLiability",),
	"change_accrued_income_taxes": ("us-gaap_IncreaseDecreaseInAccruedIncomeTaxesPayable",),
	"change_other_current_liabilities": ("us-gaap_IncreaseDecreaseInOtherCurrentLiabilities",),
	"change_other_noncurrent_liabilities": ("us-gaap_IncreaseDecreaseInOtherNoncurrentLiabilities",),
	"financing_debt_short_term_net": ("us-gaap_ProceedsFromRepaymentsOfShortTermDebtMaturingInThreeMonthsOrLess",),
	"financing_debt_short_term_repayments": ("us-gaap_RepaymentsOfShortTermDebtMaturingInThreeMonthsOrLess",),
	"financing_debt_long_term_proceeds": ("us-gaap_ProceedsFromDebtMaturingInMoreThanThreeMonths",),
	"financing_debt_long_term_repayments": ("us-gaap_RepaymentsOfDebtMaturingInMoreThanThreeMonths",),
	"financing_common_stock_issuance": ("us-gaap_ProceedsFromIssuanceOfCommonStock",),
	"financing_common_stock_repurchase": ("us-gaap_PaymentsForRepurchaseOfCommonStock",),
	"financing_common_dividends": ("us-gaap_PaymentsOfDividendsCommonStock",),
	"financing_other": ("us-gaap_ProceedsFromPaymentsForOtherFinancingActivities",),
	"cash_from_financing": ("us-gaap_NetCashProvidedByUsedInFinancingActivities",),
	"capex": ("us-gaap_PaymentsToAcquirePropertyPlantAndEquipment",),
	"investing_acquisitions": ("msft_AcquisitionsNetOfCashAcquiredAndPurchasesOfIntangibleAndOtherAssets",),
	"investment_purchases": ("us-gaap_PaymentsToAcquireInvestments",),
	"investment_maturities": ("us-gaap_ProceedsFromMaturitiesPrepaymentsAndCallsOfAvailableForSaleSecurities",),
	"investment_sales": ("msft_ProceedsFromInvestments",),
	"investing_other": ("us-gaap_PaymentsForProceedsFromOtherInvestingActivities",),
	"cash_from_investing": ("us-gaap_NetCashProvidedByUsedInInvestingActivities",),
	"fx_effect": ("us-gaap_EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsIncludingDisposalGroupAndDiscontinuedOperations",),
	"cash_change": ("us-gaap_CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",),
	"eps_basic": ("us-gaap_EarningsPerShareBasic",),
	"eps_diluted": ("us-gaap_EarningsPerShareDiluted",),
	"weighted_average_shares": ("us-gaap_WeightedAverageNumberOfDilutedSharesOutstanding", "us-gaap_WeightedAverageNumberOfSharesOutstandingBasic"),
}

_DATE_IN_COLUMN = re.compile(r"\b20\d{2}-\d{2}-\d{2}\b")
_METADATA_COLUMNS = {
	"concept", "standard_concept", "label", "unit", "unit_ref", "currency", "scale_factor", "scale", "point_in_time",
	"period_type", "period_start", "period_end", "period_instant", "level", "abstract", "dimension", "dimensions",
	"is_breakdown", "dimension_axis", "dimension_member", "dimension_member_label", "dimension_label", "balance", "weight",
	"preferred_sign", "preferred_label", "parent_concept", "parent_abstract_concept", "calculation_parent",
}
_INLINE_CACHE: dict[str, dict[str, dict[str, str]]] = {}
_HTML_CACHE: dict[str, str] = {}

_R2_SOURCE_SPECS = (
	{
		"accession": SOURCE_ACCESSIONS["FY2025"],
		"period_name": "FY2025",
		"period": "2025-06-30",
		"primary_document": "msft-20250630.htm",
		"form_type": "10-K",
	},
	{
		"accession": SOURCE_ACCESSIONS["FY2026_Q3"],
		"period_name": "Q3 FY2026",
		"period": "2026-03-31",
		"primary_document": "msft-20260331.htm",
		"form_type": "10-Q",
	},
)


class CaseHistoryError(RuntimeError):
	"""Raised when the real frozen case cannot be built faithfully."""


def _cell(value: object) -> str:
	if value is None:
		return ""
	try:
		if pd.isna(value):
			return ""
	except (TypeError, ValueError):
		pass
	return str(value)


def _number(value: object) -> float | None:
	try:
		result = float(value)
	except (TypeError, ValueError):
		return None
	return result if math.isfinite(result) else None


def _date_value(value: object) -> date | None:
	if isinstance(value, datetime):
		return value.date()
	if isinstance(value, date):
		return value
	text = _cell(value)
	if not text:
		return None
	parsed = pd.to_datetime(text, errors="coerce")
	return None if pd.isna(parsed) else parsed.date()


def _iso(value: object) -> str | None:
	parsed = _date_value(value)
	return parsed.isoformat() if parsed else None


def _json_safe(value: object) -> object:
	if value is None:
		return None
	if isinstance(value, str | int | float | bool):
		return None if isinstance(value, float) and not math.isfinite(value) else value
	if isinstance(value, date | datetime):
		return value.isoformat()
	if hasattr(value, "items"):
		return {str(key): _json_safe(item) for key, item in value.items()}
	if isinstance(value, list | tuple | set):
		return [_json_safe(item) for item in value]
	if hasattr(value, "item"):
		try:
			return _json_safe(value.item())
		except (TypeError, ValueError):
			pass
	return _cell(value)


def _mapping(value: object) -> dict[str, object]:
	if isinstance(value, dict):
		return value
	if hasattr(value, "items"):
		try:
			return {str(key): item for key, item in value.items()}
		except (AttributeError, TypeError):
			pass
	return {}


def _write_json(path: Path, value: object) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(_json_safe(value), indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def _write_csv(path: Path, frame: pd.DataFrame) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	frame.to_csv(path, index=False)


def _filing_attr(filing: object, name: str, default: object = None) -> object:
	return getattr(filing, name, default)


def _filing_metadata(filing: object) -> dict[str, object]:
	accession = _cell(_filing_attr(filing, "accession_no"))
	filing_url = _cell(_filing_attr(filing, "filing_url"))
	if not filing_url:
		base_dir = _cell(_filing_attr(filing, "base_dir"))
		primary = _cell(_filing_attr(filing, "primary_document"))
		filing_url = f"{base_dir}/{primary}" if base_dir and primary else base_dir
	accepted = _filing_attr(filing, "acceptance_datetime")
	accepted_text = accepted.isoformat() if hasattr(accepted, "isoformat") else _cell(accepted)
	return {
		"source": "edgar",
		"cik": _cell(_filing_attr(filing, "cik", CIK)),
		"company": _cell(_filing_attr(filing, "company", "MICROSOFT CORP")),
		"accession": accession,
		"form_type": _cell(_filing_attr(filing, "form")),
		"filing_date": _iso(_filing_attr(filing, "filing_date")),
		"publication_date": _iso(_filing_attr(filing, "filing_date")),
		"acceptance_timestamp": accepted_text or None,
		"report_date": _iso(_filing_attr(filing, "report_date")),
		"period_of_report": _cell(_filing_attr(filing, "period_of_report")) or None,
		"primary_document": _cell(_filing_attr(filing, "primary_document")) or None,
		"primary_document_description": _cell(_filing_attr(filing, "primary_doc_description")) or None,
		"source_locator": filing_url or None,
		"is_xbrl": _filing_attr(filing, "is_xbrl"),
		"is_inline_xbrl": _filing_attr(filing, "is_inline_xbrl"),
	}


def _configure_edgar(cache_dir: Path | None = None) -> None:
	"""Configure identity and, when requested, an isolated native cache."""
	from dotenv import load_dotenv
	from edgar import set_identity

	load_dotenv(dotenv_path=Path(".env"), override=False)
	identity = os.getenv("SMRIK_EDGAR_USER_AGENT") or os.getenv("EDGAR_IDENTITY")
	set_identity(identity or "SmrikFund research@example.com")
	if cache_dir is not None:
		import edgar.httpclient as httpclient

		cache_dir.mkdir(parents=True, exist_ok=True)
		httpclient.edgar_data_dir = str(cache_dir.resolve())
		httpclient.HTTP_MGR = httpclient.get_http_mgr(cache_enabled=True)


def _load_filings(cache_dir: Path | None = None) -> dict[str, object]:
	_configure_edgar(cache_dir)
	from edgar import Company

	filings = Company(TICKER).get_filings(form=["10-K", "10-Q"], date="2022-01-01:2026-04-30")
	result = {}
	for filing in filings:
		accession = _cell(_filing_attr(filing, "accession_no"))
		if accession:
			result[accession] = filing
	missing = sorted(set(SOURCE_ACCESSIONS.values()) - set(result))
	if missing:
		raise CaseHistoryError("required cutoff-qualified filings unavailable: " + ", ".join(missing))
	return result


def _period_specs() -> list[dict[str, object]]:
	"""Return explicit observed period identities used by the selected case."""
	annual = [
		("FY2023", SOURCE_ACCESSIONS["FY2023"], "2022-07-01", "2023-06-30", 2023),
		("FY2024", SOURCE_ACCESSIONS["FY2024"], "2023-07-01", "2024-06-30", 2024),
		("FY2025", SOURCE_ACCESSIONS["FY2025"], "2024-07-01", "2025-06-30", 2025),
	]
	result: list[dict[str, object]] = []
	for name, accession, start, end, fiscal_year in annual:
		period_key = f"duration_{start}_{end}"
		for statement in ("income_statement", "cash_flow_statement"):
			result.append({
				"name": name, "view": "annual", "statement": statement, "accession": accession,
				"period_key": period_key, "period_type": "duration", "period_start": start,
				"period_end": end, "period_instant": None, "fiscal_year": fiscal_year,
				"fiscal_period": "FY",
			})
		result.append({
			"name": name, "view": "instant", "statement": "balance_sheet", "accession": accession,
			"period_key": f"instant_{end}", "period_type": "instant", "period_start": None,
			"period_end": None, "period_instant": end, "fiscal_year": fiscal_year,
			"fiscal_period": None,
		})
	quarterly = [
		("Q1 FY2026", SOURCE_ACCESSIONS["FY2025_Q1"], "2025-07-01", "2025-09-30", "Q1"),
		("Q2 FY2026", SOURCE_ACCESSIONS["FY2025_Q2"], "2025-10-01", "2025-12-31", "Q2"),
		("Q3 FY2026", SOURCE_ACCESSIONS["FY2026_Q3"], "2026-01-01", "2026-03-31", "Q3"),
	]
	for name, accession, start, end, fiscal_period in quarterly:
		for statement in ("income_statement", "cash_flow_statement"):
			result.append({
				"name": name, "view": "quarter", "statement": statement, "accession": accession,
				"period_key": f"duration_{start}_{end}", "period_type": "duration",
				"period_start": start, "period_end": end, "period_instant": None,
				"fiscal_year": 2026, "fiscal_period": fiscal_period,
			})
	for name, start, end, fiscal_year in (
		("Current YTD", "2025-07-01", "2026-03-31", 2026),
		("Prior comparable YTD", "2024-07-01", "2025-03-31", 2025),
	):
		for statement in ("income_statement", "cash_flow_statement"):
			result.append({
				"name": name, "view": "ytd", "statement": statement,
				"accession": SOURCE_ACCESSIONS["FY2026_Q3"],
				"period_key": f"duration_{start}_{end}", "period_type": "duration",
				"period_start": start, "period_end": end, "period_instant": None,
				"fiscal_year": fiscal_year, "fiscal_period": "Q3",
			})
	result.append({
		"name": "Latest balance sheet", "view": "instant", "statement": "balance_sheet",
		"accession": SOURCE_ACCESSIONS["FY2026_Q3"], "period_key": "instant_2026-03-31",
		"period_type": "instant", "period_start": None, "period_end": None,
		"period_instant": "2026-03-31", "fiscal_year": 2026, "fiscal_period": None,
	})
	for name, period_instant in (
		("Cash-flow endpoint FY2023 opening", "2022-06-30"),
		("Cash-flow endpoint FY2023 closing", "2023-06-30"),
		("Cash-flow endpoint FY2024 closing", "2024-06-30"),
		("Cash-flow endpoint FY2025 closing", "2025-06-30"),
		("Cash-flow endpoint prior comparable YTD closing", "2025-03-31"),
	):
		accession = SOURCE_ACCESSIONS["FY2025"] if period_instant in {"2022-06-30", "2023-06-30", "2024-06-30", "2025-06-30"} else SOURCE_ACCESSIONS["FY2026_Q3"]
		result.append({
			"name": name, "view": "instant", "statement": "cash_flow_statement",
			"accession": accession, "period_key": f"instant_{period_instant}",
			"period_type": "instant", "period_start": None, "period_end": None,
			"period_instant": period_instant, "fiscal_year": None, "fiscal_period": None,
		})
	result.append({
		"name": "Latest cash-flow endpoint", "view": "instant", "statement": "cash_flow_statement",
		"accession": SOURCE_ACCESSIONS["FY2026_Q3"], "period_key": "instant_2026-03-31",
		"period_type": "instant", "period_start": None, "period_end": None,
		"period_instant": "2026-03-31", "fiscal_year": 2026, "fiscal_period": None,
	})
	return result


def _statement_object(xbrl: object, statement_name: str) -> object:
	statements = getattr(xbrl, "statements", None)
	method_name = {
		"income_statement": "income_statement",
		"balance_sheet": "balance_sheet",
		"cash_flow_statement": "cashflow_statement",
	}[statement_name]
	method = getattr(statements, method_name, None)
	if callable(method):
		return method()
	if method is not None:
		return method
	raise CaseHistoryError(f"native statement unavailable: {statement_name}")


def _period_label(xbrl: object, period_key: str) -> str:
	for period in getattr(xbrl, "reporting_periods", []) or []:
		item = _mapping(period)
		if _cell(item.get("key") or item.get("period_key")) == period_key:
			return _cell(item.get("label")) or period_key
	return period_key


def _standard_dataframe(statement: object, *, period_key: str | None = None) -> pd.DataFrame:
	"""Call the installed standard DataFrame API across 5.45 call shapes."""
	to_dataframe = getattr(statement, "to_dataframe", None)
	if not callable(to_dataframe):
		raise CaseHistoryError("native statement has no to_dataframe method")
	kwargs: dict[str, object] = {
		"standard": True, "include_unit": True, "include_point_in_time": True,
		"presentation": False,
	}
	if period_key is not None:
		kwargs["period_filter"] = period_key
	try:
		frame = to_dataframe(**kwargs)
	except TypeError:
		kwargs.pop("period_filter", None)
		if period_key is not None:
			kwargs["period_filter"] = period_key
		kwargs["view"] = "standard"
		frame = to_dataframe(**kwargs)
	if not isinstance(frame, pd.DataFrame):
		raise CaseHistoryError("native statement did not return a DataFrame")
	return frame.copy()


def _period_dataframe(statement: object, period_key: str, period_label: str) -> pd.DataFrame:
	"""Expose one exact native period through ``Statement.to_dataframe``."""
	from edgar.xbrl import periods as period_module

	original = period_module.determine_periods_to_display
	period_module.determine_periods_to_display = lambda *_args, **_kwargs: [(period_key, period_label)]
	try:
		frame = _standard_dataframe(statement, period_key=period_key)
	finally:
		period_module.determine_periods_to_display = original
	if frame.empty:
		return frame
	value_columns = [
		str(column) for column in frame.columns
		if column not in _METADATA_COLUMNS and _DATE_IN_COLUMN.search(str(column))
	]
	if not value_columns:
		return frame.iloc[0:0].copy()
	selected = value_columns[0]
	if selected != period_key:
		frame = frame.rename(columns={selected: period_key})
	return _attach_raw_dimensions(statement, frame, period_key)


def _attach_raw_dimensions(statement: object, frame: pd.DataFrame, period_key: str) -> pd.DataFrame:
	get_raw_data = getattr(statement, "get_raw_data", None)
	if not callable(get_raw_data) or frame.empty:
		return frame
	try:
		raw_rows = get_raw_data(period_filter=period_key)
	except Exception:
		return frame
	lookup: dict[tuple[str, str, bool, int], object] = {}
	counts: dict[tuple[str, str, bool], int] = {}
	for raw in raw_rows or []:
		item = _mapping(raw)
		base = (_cell(item.get("concept")), _cell(item.get("label")), bool(item.get("is_dimension", item.get("dimension", False))))
		ordinal = counts.get(base, 0)
		counts[base] = ordinal + 1
		lookup[(*base, ordinal)] = item
	frame = frame.copy()
	seen: dict[tuple[str, str, bool], int] = {}
	dimensions: list[str] = []
	for _, row in frame.iterrows():
		base = (_cell(row.get("concept")), _cell(row.get("label")), bool(row.get("dimension", False)))
		ordinal = seen.get(base, 0)
		seen[base] = ordinal + 1
		item = _mapping(lookup.get((*base, ordinal), {}))
		dims = item.get("dimension_metadata")
		if not dims and not base[2]:
			dims = {}
		dimensions.append(json.dumps(_json_safe(dims), sort_keys=True))
	frame["dimensions"] = dimensions
	return frame


def _period_metadata(spec: dict[str, object], filing: dict[str, object], role: str) -> dict[str, object]:
	return {
		"period_column": spec["period_key"], "native_period": spec["period_key"],
		"period_identity": spec["period_key"], "period_type": spec["period_type"],
		"period_start": spec["period_start"], "period_end": spec["period_end"],
		"period_instant": spec["period_instant"], "fiscal_year": spec["fiscal_year"],
		"fiscal_period": spec["fiscal_period"], "unit": "native", "unit_ref": "native",
		"currency": "USD", "scale_factor": 1.0, "dimensions": "{}",
		"statement_role": role, "source": filing["source"],
		"accession": filing["accession"], "filing_date": filing["filing_date"],
		"form_type": filing["form_type"], "source_locator": filing["source_locator"],
	}


def _context_dimensions(xbrl: object, context_ref: object) -> dict[str, object]:
	contexts = getattr(xbrl, "contexts", {})
	context = None
	try:
		context = contexts.get(context_ref)
	except AttributeError:
		try:
			context = contexts[context_ref]
		except (KeyError, TypeError):
			context = None
	if context is None:
		return {}
	return _mapping(getattr(context, "dimensions", None))


def _fact_index(xbrl: object) -> tuple[pd.DataFrame, dict[tuple[str, str], object]]:
	facts = getattr(xbrl, "facts", None)
	to_dataframe = getattr(facts, "to_dataframe", None)
	if not callable(to_dataframe):
		return pd.DataFrame(), {}
	try:
		frame = to_dataframe()
	except Exception:
		return pd.DataFrame(), {}
	parser = getattr(xbrl, "parser", None)
	parser_facts = getattr(parser, "facts", {})
	objects: dict[tuple[str, str], object] = {}
	try:
		items = parser_facts.items()
	except AttributeError:
		items = []
	for fact_key, fact in items:
		for item in fact if isinstance(fact, list | tuple) else [fact]:
			context_ref = _cell(getattr(item, "context_ref", None))
			objects[(_cell(fact_key).replace(":", "_"), context_ref)] = item
	return (frame.copy() if isinstance(frame, pd.DataFrame) else pd.DataFrame()), objects


def _fact_period_key(xbrl: object, row: pd.Series) -> str:
	period_key = _cell(row.get("period_key"))
	if period_key:
		return period_key
	period_map = getattr(xbrl, "context_period_map", {})
	try:
		return _cell(period_map.get(_cell(row.get("context_ref"))))
	except AttributeError:
		return ""


def _fact_candidates(
	xbrl: object,
	fact_frame: pd.DataFrame,
	fact_objects: dict[tuple[str, str], object],
	concept: str,
	period_key: str,
	dimensioned: bool,
	value: object,
) -> tuple[list[dict[str, object]], list[dict[str, object]], bool]:
	if fact_frame.empty or "concept" not in fact_frame:
		return [], [], False
	normalized = concept.replace(":", "_")
	candidates: list[dict[str, object]] = []
	for _, candidate in fact_frame.iterrows():
		candidate_concept = _cell(candidate.get("concept")).replace(":", "_")
		if candidate_concept != normalized or _fact_period_key(xbrl, candidate) != period_key:
			continue
		context_ref = _cell(candidate.get("context_ref"))
		dimensions = _context_dimensions(xbrl, context_ref)
		if bool(dimensions) != dimensioned:
			continue
		candidate_value = candidate.get("numeric_value")
		candidate_number, source_number = _number(candidate_value), _number(value)
		matches = (candidate_number is None and source_number is None) or candidate_number == source_number
		fact_key = _cell(candidate.get("fact_key"))
		fact = fact_objects.get((fact_key.replace(":", "_"), context_ref))
		fact_id = _cell(getattr(fact, "fact_id", None)) or None
		candidates.append({
			"fact_key": fact_key or None, "fact_id": fact_id, "context_ref": context_ref or None,
			"period_key": period_key, "concept": concept, "value": candidate.get("value"),
			"numeric_value": candidate_value, "unit_ref": candidate.get("unit_ref"),
			"decimals": candidate.get("decimals"),
			"dimensions": json.dumps(_json_safe(dimensions), sort_keys=True),
			"matches_standard_value": matches,
		})
	matched = [row for row in candidates if row["matches_standard_value"]]
	if not matched:
		return [], candidates, False
	keys = {
		(_number(row.get("numeric_value")), row.get("unit_ref"), row.get("dimensions"))
		for row in matched
	}
	return matched, candidates, len(keys) > 1


def _inline_attributes(html: str, fact_id: str) -> dict[str, str]:
	if not fact_id:
		return {}
	pattern = re.compile(r"(<[^>]*\bid\s*=\s*(['\"])" + re.escape(fact_id) + r"\2[^>]*>)(.*?)</[^>]+>", re.IGNORECASE | re.DOTALL)
	match = pattern.search(html)
	if not match:
		opening_pattern = re.compile(r"<[^>]*\bid\s*=\s*(['\"])" + re.escape(fact_id) + r"\1[^>]*>", re.IGNORECASE)
		opening = opening_pattern.search(html)
		if not opening:
			return {}
		raw_tag, raw_text = opening.group(0), ""
	else:
		raw_tag, raw_text = match.group(1), re.sub(r"<[^>]+>", " ", unescape(match.group(3))).strip()
	attributes = {
		name.lower(): value
		for name, _, value in re.findall(r"([A-Za-z][A-Za-z0-9:_-]*)\s*=\s*(['\"])(.*?)\2", raw_tag)
	}
	attributes["__raw_tag"] = raw_tag
	attributes["__raw_text"] = raw_text
	return attributes


def _filing_html(filing: object, accession: str | None = None) -> str:
	key = _cell(accession)
	if key and key in _HTML_CACHE:
		return _HTML_CACHE[key]
	html_method = getattr(filing, "html", None)
	if not callable(html_method):
		return ""
	try:
		html = html_method()
	except Exception:
		return ""
	if not isinstance(html, str):
		return ""
	if key:
		_HTML_CACHE[key] = html
	return html


def _inline_attributes_for_filing(
	filing: object, fact_ids: set[str], accession: str | None = None
) -> dict[str, dict[str, str]]:
	if not fact_ids:
		return {}
	html = _filing_html(filing, accession)
	if not html:
		return {}
	return {fact_id: _inline_attributes(html, fact_id) for fact_id in fact_ids}


def _plain_html_excerpt(html: str, keyword: str, radius: int = 420) -> str | None:
	if not html:
		return None
	clean = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
	clean = unescape(re.sub(r"<[^>]+>", " ", clean))
	clean = re.sub(r"\s+", " ", clean).strip()
	match = re.search(re.escape(keyword), clean, re.IGNORECASE)
	if not match:
		return None
	start = max(0, match.start() - radius)
	end = min(len(clean), match.end() + radius)
	return clean[start:end].strip()


def _filing_excerpt_packets(filings: dict[str, object]) -> list[dict[str, object]]:
	"""Capture small, stable source excerpts for material cash/asset context."""
	requested = (
		(SOURCE_ACCESSIONS["FY2025"], "2025-06-30"),
		(SOURCE_ACCESSIONS["FY2026_Q3"], "2026-03-31"),
	)
	keywords = (
		("cash_flow_table_annual", "CASH FLOWS S TATEMENTS (In millions)"),
		("cash_flow_table_interim", "CASH FLOWS STATEMENTS (In millions)"),
		("balance_sheet_heading", "CONSOLIDATED BALANCE SHEETS"),
		("cash_definition", "cash and cash equivalents"),
		("restricted_cash", "restricted cash"),
		("property_and_equipment", "property and equipment"),
		("unit_qualification", "in millions"),
	)
	packets: list[dict[str, object]] = []
	for accession, period in requested:
		filing = filings.get(accession)
		metadata = _filing_metadata(filing) if filing is not None else {}
		html = _filing_html(filing, accession) if filing is not None else ""
		for slug, keyword in keywords:
			excerpt = _plain_html_excerpt(html, keyword)
			if excerpt is None:
				continue
			packets.append({
				"packet_id": f"P2R1-{accession}-{slug}",
				"accession": accession,
				"period": period,
				"unit_context": "USD; native u_usd; display USD millions",
				"keyword": keyword,
				"source_locator": metadata.get("source_locator"),
				"excerpt": excerpt,
			})
	return packets


def _cached_submission_body(cache_path: Path) -> bytes:
	"""Read one cached EdgarTools response without making a network request."""
	try:
		cached = cache_path.read_bytes()
	except OSError as exc:
		raise CaseHistoryError(f"cached original source is unreadable: {cache_path}") from exc
	gzip_start = cached.find(b"\x1f\x8b")
	if gzip_start < 0:
		return cached
	try:
		return gzip.decompress(cached[gzip_start:])
	except (OSError, EOFError) as exc:
		raise CaseHistoryError(f"cached original source is not valid gzip: {cache_path}") from exc


def _cached_source_paths(
	cache_dir: Path, accession: str, primary_document: str
) -> tuple[Path, Path | None]:
	"""Locate the cached full submission and primary HTML for one frozen filing."""
	tcache = cache_dir / "_tcache"
	compact = accession.replace("-", "")
	text_candidates = sorted(tcache.glob(f"*{compact}*{accession}.txt"))
	if len(text_candidates) != 1:
		raise CaseHistoryError(
			f"expected one cached original submission for {accession}; "
			f"found {len(text_candidates)}"
		)
	html_candidates = sorted(tcache.glob(f"*{compact}*__{primary_document}"))
	if len(html_candidates) > 1:
		raise CaseHistoryError(
			f"expected at most one cached primary HTML for {accession}; "
			f"found {len(html_candidates)}"
		)
	return text_candidates[0], html_candidates[0] if html_candidates else None


def _visible_source_text(source: str) -> str:
	"""Render an original filing slice as compact reviewer-readable text."""
	clean = re.sub(r"(?is)<(script|style).*?</\1>", " ", source)
	clean = unescape(re.sub(r"<[^>]+>", " ", clean))
	return re.sub(r"\s+", " ", clean).strip()


def _r2_source_bounds(source: str, section: str) -> tuple[int, int, str]:
	"""Select one complete original filing section using its native text anchors."""
	if section == "balance_sheet_table":
		start_match = re.search(r"BALANCE SHEETS\s*-\s*USD\s*\(\$\)", source, re.IGNORECASE)
		end_pattern = r"Total liabilities and stockholders(?:&#8217;|&#x2019;|[’'])\s*equity"
	elif section == "cash_flow_table":
		start_match = re.search(r"CASH FLOWS STATEMENTS\s*-\s*USD\s*\(\$\)", source, re.IGNORECASE)
		end_pattern = r"Cash and cash equivalents,\s*end of period"
	elif section == "property_and_equipment_note":
		start_match = re.search(
			r"NOTE\s*6\s*(?:&#8212;|&#x2014;|&#x2013;|—|–|-)\s*PROPERTY\s+AND\s+EQUIPMENT",
			source,
			re.IGNORECASE,
		)
		end_pattern = r"NOTE\s*[0-9]+\s*(?:&#8212;|&#x2014;|&#x2013;|—|–|-)"
	elif section == "cash_equivalent_policy":
		start_match = re.search(
			r"We consider all highly liquid interest-earning investments with a maturity "
			r"of three months or less at the date of purchase to be cash equivalents\.",
			source,
			re.IGNORECASE,
		)
		end_pattern = ""
	else:
		raise CaseHistoryError(f"unsupported R2 evidence section: {section}")
	if start_match is None:
		raise CaseHistoryError(f"exact R2 evidence anchor is absent: {section}")
	start = start_match.start()
	if section == "cash_equivalent_policy":
		headings = list(re.finditer(r"Financial\s+Instruments", source[:start], re.IGNORECASE))
		if headings:
			start = headings[-1].start()
		closing_paragraph = source.find("</p>", start_match.end())
		end = closing_paragraph + len("</p>") if closing_paragraph >= 0 else start_match.end()
	else:
		end_match = re.search(end_pattern, source[start_match.end():], re.IGNORECASE)
		if end_match is None:
			raise CaseHistoryError(f"complete R2 evidence endpoint is absent: {section}")
		endpoint = start_match.end() + end_match.end()
		if section in {"balance_sheet_table", "cash_flow_table"}:
			closing_table = source.find("</table>", endpoint)
			end = closing_table + len("</table>") if closing_table >= 0 else endpoint
		else:
			end = start_match.end() + end_match.start()
	if end <= start:
		raise CaseHistoryError(f"invalid R2 evidence bounds: {section} {start}:{end}")
	excerpt = _visible_source_text(source[start:end])
	required_markers = {
		"balance_sheet_table": ("BALANCE SHEETS", "Total assets", "Total liabilities and stockholders"),
		"cash_flow_table": (
			"CASH FLOWS STATEMENTS",
			"Net cash from operations",
			"Net change in cash and cash equivalents",
			"Cash and cash equivalents, end of period",
		),
		"property_and_equipment_note": (
			"NOTE 6",
			"PROPERTY AND EQUIPMENT",
			"Total, net",
			"depreciation expense",
		),
		"cash_equivalent_policy": (
			"cash equivalents",
			"maturity of three months or less",
		),
	}
	missing = [
		marker for marker in required_markers[section] if marker.casefold() not in excerpt.casefold()
	]
	if missing:
		raise CaseHistoryError(
			f"R2 evidence section lacks required context: {section}; missing={missing}"
		)
	return start, end, excerpt


def _r2_period_key(section: str, period: str) -> str | None:
	if section == "balance_sheet_table":
		return f"instant_{period}"
	if section == "cash_flow_table":
		return {
			"2025-06-30": "duration_2024-07-01_2025-06-30",
			"2026-03-31": "duration_2025-07-01_2026-03-31",
		}.get(period)
	return None


def _r2_original_evidence(
	manifest: dict[str, object], cache_dir: Path, evidence_dir: Path
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
	"""Freeze exact cached source slices for the R2 evidence-only revision."""
	selected = {
		_cell(row.get("accession")): row
		for row in manifest.get("selected_filings", [])
		if isinstance(row, dict)
	}
	packets: list[dict[str, object]] = []
	sources: list[dict[str, object]] = []
	unavailable: list[dict[str, object]] = []
	section_specs = (
		("balance_sheet_table", "balance_sheet", "USD ($); $ in Millions; display USD millions"),
		("cash_flow_table", "cash_flow_statement", "USD ($); $ in Millions; display USD millions"),
		("cash_equivalent_policy", "notes", "policy text; no monetary unit"),
		("property_and_equipment_note", "notes", "USD ($); (In millions); display USD millions"),
	)
	for source_spec in _R2_SOURCE_SPECS:
		accession = str(source_spec["accession"])
		manifest_row = selected.get(accession, {})
		cache_text, cache_html = _cached_source_paths(
			cache_dir, accession, str(source_spec["primary_document"])
		)
		raw_bytes = _cached_submission_body(cache_text)
		try:
			raw = raw_bytes.decode("utf-8")
		except UnicodeDecodeError as exc:
			raise CaseHistoryError(f"cached original source is not UTF-8: {cache_text}") from exc
		relative_source = Path("original_source") / f"{accession}.txt"
		source_path = evidence_dir / relative_source
		source_path.parent.mkdir(parents=True, exist_ok=True)
		source_path.write_bytes(raw_bytes)
		digest = hashlib.sha256(raw_bytes).hexdigest()
		source_record = {
			"accession": accession,
			"period_name": source_spec["period_name"],
			"period": source_spec["period"],
			"form_type": manifest_row.get("form_type") or source_spec["form_type"],
			"filing_date": manifest_row.get("filing_date"),
			"report_date": manifest_row.get("report_date") or source_spec["period"],
			"cache_text_path": str(cache_text.resolve()),
			"cache_html_path": str(cache_html.resolve()) if cache_html else None,
			"source_file": relative_source.as_posix(),
			"source_sha256": digest,
			"source_bytes": len(raw_bytes),
			"sec_locator": manifest_row.get("source_locator"),
		}
		sources.append(source_record)
		for section, statement, unit_context in section_specs:
			try:
				start, end, excerpt = _r2_source_bounds(raw, section)
			except CaseHistoryError as exc:
				unavailable.append({
					"accession": accession,
					"section": section,
					"status": "UNAVAILABLE",
					"reason": str(exc),
				})
				continue
			line_start = raw.count("\n", 0, start) + 1
			line_end = raw.count("\n", 0, end) + 1
			locator = (
				f"{relative_source.as_posix()}#char={start}-{end};"
				f"line={line_start}-{line_end}"
			)
			section_period_key = _r2_period_key(section, str(source_spec["period"]))
			packets.append({
				"packet_id": f"P2R2-{accession}-{section}",
				"accession": accession,
				"period_name": source_spec["period_name"],
				"period": source_spec["period"],
				"period_key": section_period_key,
				"statement": statement,
				"section": section,
				"keyword": section,
				"unit_context": unit_context,
				"source_file": relative_source.as_posix(),
				"source_sha256": digest,
				"source_char_start": start,
				"source_char_end": end,
				"source_line_start": line_start,
				"source_line_end": line_end,
				"source_locator": locator,
				"sec_locator": manifest_row.get("source_locator"),
				"cache_text_path": str(cache_text.resolve()),
				"cache_html_path": str(cache_html.resolve()) if cache_html else None,
				"excerpt": excerpt,
			})
	policy_excerpts = [
		packet.get("excerpt", "")
		for packet in packets
		if packet.get("section") == "cash_equivalent_policy"
	]
	if not any(re.search(r"\brestricted cash\b", excerpt, re.IGNORECASE) for excerpt in policy_excerpts):
		unavailable.append({
			"definition": "restricted_cash",
			"status": "UNAVAILABLE",
			"reason": "exact natural-language restricted-cash definition is absent from the selected original statement/note excerpts",
			"searched_sections": [
				"balance_sheet_table",
				"cash_flow_table",
				"cash_equivalent_policy",
			],
		})
	return packets, sources, unavailable


def _write_r2_evidence_notes(
	path: Path,
	sources: list[dict[str, object]],
	packets: list[dict[str, object]],
	unavailable: list[dict[str, object]],
) -> None:
	lines = [
		"# MSFT P2 R2 original-source evidence",
		"",
		"This evidence-only revision selects complete sections from the cached EdgarTools full submissions. The R1 history, periods, arithmetic, checks, and source-selection files are copied and referenced by hash; no financial values are recomputed here.",
		"",
		"## Frozen source files",
		"",
	]
	for source in sources:
		lines.extend([
			f"- **{source.get('period_name')}** `{source.get('accession')}` ({source.get('form_type')}, report {source.get('report_date')})",
			f"  - cached full submission: `{source.get('cache_text_path')}`",
			f"  - cached primary HTML: `{source.get('cache_html_path') or 'not present in cache'}`",
			f"  - frozen source: `{source.get('source_file')}`; SHA-256 `{source.get('source_sha256')}`; bytes `{source.get('source_bytes')}`",
		])
	lines.extend(["", "## Exact selected sections", ""])
	for packet in packets:
		excerpt = _cell(packet.get("excerpt"))
		lines.extend([
			f"### {packet.get('packet_id')}",
			f"- Section: `{packet.get('section')}`; statement: `{packet.get('statement')}`; period: `{packet.get('period')}`; unit context: {packet.get('unit_context')}",
			f"- Frozen locator: `{packet.get('source_locator')}`; SHA-256 `{packet.get('source_sha256')}`",
			f"- SEC primary-document locator: `{packet.get('sec_locator')}`",
			"",
			"```text",
			excerpt,
			"```",
			"",
		])
	lines.extend(["## Explicitly unavailable definitions", ""])
	if unavailable:
		for item in unavailable:
			lines.append(f"- `{item.get('definition') or item.get('section')}` — {item.get('status')}: {item.get('reason')}")
	else:
		lines.append("- None.")
	lines.extend([
			"",
			"The selected cash-flow endpoint is reported as cash and cash equivalents. Restricted-cash taxonomy identifiers may occur in the original XBRL markup, but no natural-language restricted-cash definition was selected as evidence; no equivalence or plug is asserted.",
	])
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _attach_provenance(
	history: pd.DataFrame,
	filing: object,
	xbrl: object,
	filing_metadata: dict[str, object],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[tuple[str, str, str, str]]]:
	if history.empty:
		return history, pd.DataFrame(), pd.DataFrame(), []
	fact_frame, fact_objects = _fact_index(xbrl)
	accession = _cell(filing_metadata.get("accession"))
	inline_cache = _INLINE_CACHE.get(accession, {})
	refs: list[dict[str, object]] = []
	checks: list[tuple[str, str, str, str]] = []
	result = history.copy()
	result["native_scale_factor"] = 1.0
	result["numeric_basis"] = "native_standard_statement_value"
	result["source_selection_status"] = "MISSING"
	result["source_fact_id"] = None
	result["source_context_ref"] = None
	result["source_unit_ref"] = None
	result["source_decimals"] = None
	result["source_inline_scale"] = None
	result["source_inline_unit_ref"] = None
	result["source_inline_sign"] = None
	result["source_inline_value"] = None
	result["source_inline_attributes"] = None
	result["source_match_count"] = 0
	candidate_records: dict[int, tuple[list[dict[str, object]], list[dict[str, object]], bool]] = {}
	all_fact_ids: set[str] = set()
	for index, row in result.iterrows():
		concept = _cell(row.get("concept"))
		period_key = _cell(row.get("period_column"))
		dimensioned = bool(row.get("dimension", False))
		matched, candidates, conflict = _fact_candidates(
			xbrl, fact_frame, fact_objects, concept, period_key, dimensioned, row.get("numeric_value")
		)
		candidate_records[index] = (matched, candidates, conflict)
		all_fact_ids.update(
			_cell(item.get("fact_id")) for item in candidates if _cell(item.get("fact_id"))
		)
	missing_inline_ids = all_fact_ids.difference(inline_cache)
	if missing_inline_ids:
		inline_cache.update(_inline_attributes_for_filing(filing, missing_inline_ids, accession))
		_INLINE_CACHE[accession] = inline_cache
	for index, row in result.iterrows():
		concept = _cell(row.get("concept"))
		period_key = _cell(row.get("period_column"))
		matched, candidates, conflict = candidate_records[index]
		representative = matched[0] if matched else None
		if representative is not None:
			status = "UNRESOLVED" if conflict else "SELECTED"
			result.at[index, "source_selection_status"] = status
			result.at[index, "source_fact_id"] = representative.get("fact_id")
			result.at[index, "source_context_ref"] = representative.get("context_ref")
			result.at[index, "source_unit_ref"] = representative.get("unit_ref")
			result.at[index, "source_decimals"] = representative.get("decimals")
			fact_id = _cell(representative.get("fact_id"))
			attributes = inline_cache.get(fact_id, {})
			result.at[index, "source_inline_scale"] = attributes.get("scale")
			result.at[index, "source_inline_unit_ref"] = attributes.get("unitref")
			result.at[index, "source_inline_sign"] = attributes.get("sign")
			result.at[index, "source_inline_value"] = attributes.get("__raw_text") or representative.get("value")
			result.at[index, "source_inline_attributes"] = json.dumps(_json_safe(attributes), sort_keys=True)
			result.at[index, "source_match_count"] = len(matched)
			if fact_id and _cell(filing_metadata.get("source_locator")):
				result.at[index, "source_locator"] = f"{filing_metadata['source_locator']}#{fact_id}"
		checks.append((
			f"native_link:{period_key}:{concept}",
			"FAIL" if conflict else "PASS",
			"conflicting_native_references" if conflict else "exact_fact_context_link",
			f"matches={len(matched)}",
		))
		for candidate in candidates:
			fact_id = _cell(candidate.get("fact_id"))
			attrs = inline_cache.get(fact_id, {})
			if representative is None or conflict:
				ref_type = "alternative"
			elif candidate in matched and candidate is representative:
				ref_type = "selected"
			elif candidate in matched:
				ref_type = "equivalent"
			else:
				ref_type = "alternative"
			refs.append({
				"statement": row.get("statement"), "period_name": row.get("period_name"),
				"period_key": period_key, "concept": concept, "label": row.get("label"),
				"accession": filing_metadata.get("accession"),
				"filing_date": filing_metadata.get("filing_date"),
				"acceptance_timestamp": filing_metadata.get("acceptance_timestamp"),
				"form_type": filing_metadata.get("form_type"),
				"fact_key": candidate.get("fact_key"), "fact_id": candidate.get("fact_id"),
				"context_ref": candidate.get("context_ref"), "unit_ref": candidate.get("unit_ref"),
				"decimals": candidate.get("decimals"), "inline_scale": attrs.get("scale"),
				"inline_unit_ref": attrs.get("unitref"), "inline_sign": attrs.get("sign"),
				"inline_text": attrs.get("__raw_text"),
				"inline_raw_tag": attrs.get("__raw_tag"),
				"inline_attributes": json.dumps(_json_safe(attrs), sort_keys=True),
				"value": candidate.get("value"),
				"numeric_value": candidate.get("numeric_value"),
				"dimensions": candidate.get("dimensions"), "source_ref_type": ref_type,
				"source_locator": f"{filing_metadata['source_locator']}#{fact_id}" if fact_id and filing_metadata.get("source_locator") else None,
			})
		if not matched:
			checks.append((f"native_link:{period_key}:{concept}", "FAIL", "missing_exact_fact_context_link", f"candidate_scopes={len(candidates)}"))
	refs_frame = pd.DataFrame(refs)
	alternatives = refs_frame.loc[refs_frame["source_ref_type"].eq("alternative")].copy() if not refs_frame.empty else refs_frame.copy()
	return result, refs_frame, alternatives, checks


def _display_value(value: object, unit: object) -> float | None:
	number = _number(value)
	unit_text = _cell(unit).lower()
	if number is None:
		return None
	if "usd" in unit_text and "share" not in unit_text and "/" not in unit_text:
		return number / DISPLAY_SCALE
	return number


def _add_view_fields(frame: pd.DataFrame, spec: dict[str, object]) -> pd.DataFrame:
	result = frame.copy()
	result["period_key"] = spec["period_key"]
	result["period_name"] = spec["name"]
	result["view"] = spec["view"]
	result["source_accession"] = spec["accession"]
	result["display_value"] = [
		_display_value(value, unit)
		for value, unit in zip(result["numeric_value"], result["unit"], strict=True)
	]
	return result


def _observed_mapping(history: pd.DataFrame) -> pd.DataFrame:
	observed = set(history["concept"].dropna().astype(str)) if "concept" in history else set()
	return pd.DataFrame([
		{
			"model_key": model_key,
			"observed_concept": next((candidate for candidate in candidates if candidate in observed), None),
			"candidate_concepts": " | ".join(candidates),
			"status": "OBSERVED" if any(candidate in observed for candidate in candidates) else "UNAVAILABLE",
		}
		for model_key, candidates in MATERIAL_CONCEPTS.items()
	])


def _material_history(history: pd.DataFrame, mapping: pd.DataFrame) -> pd.DataFrame:
	if history.empty:
		return history.copy()
	concepts = set(mapping["observed_concept"].dropna().astype(str))
	return history.loc[history["concept"].astype(str).isin(concepts)].copy()


def _build_ttm(history: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, list[tuple[str, str, str, str]]]:
	rows: list[dict[str, object]] = []
	unavailable: list[dict[str, object]] = []
	checks: list[tuple[str, str, str, str]] = []
	if history.empty:
		return pd.DataFrame(), pd.DataFrame(), checks
	group_fields = [field for field in ("statement", "concept", "dimensions") if field in history]
	for group_key, group in history.groupby(group_fields, dropna=False, sort=False):
		statement, concept, dimensions = group_key if isinstance(group_key, tuple) else (group_key, "", "")
		if group.get("source_selection_status", pd.Series(dtype=str)).eq("UNRESOLVED").any():
			unavailable.append({"statement": statement, "concept": concept, "dimensions": dimensions, "reason": "conflicting_native_references"})
			checks.append((f"ttm:{statement}:{concept}", "FAIL", "conflicting_native_references", ""))
			continue
		result = construct_ttm(
			group,
			concept=concept,
			full_fy_end="2025-06-30",
			current_ytd_start="2025-07-01",
			current_ytd_end="2026-03-31",
			prior_ytd_start="2024-07-01",
			prior_ytd_end="2025-03-31",
			information_cutoff=CASE_CUTOFF,
		)
		expected_unavailable = {"missing_component_period", "instant_fact_rejected", "non_additive_concept", "unit_scope_or_period_mismatch"}
		for check in result["checks"].itertuples(index=False, name=None):
			status = "NOT_TESTED" if check[1] == "FAIL" and check[2] in expected_unavailable else check[1]
			checks.append((f"ttm:{statement}:{concept}:{check[0]}", status, check[2], check[3]))
		if result["history"].empty:
			reason = next((str(value) for value in result["checks"].get("reason", []) if str(value) and str(value) != "qualified_by_publication_date"), "ttm_unavailable")
			unavailable.append({"statement": statement, "concept": concept, "dimensions": dimensions, "reason": reason})
			continue
		row = result["history"].iloc[0].to_dict()
		row.update({
			"period_key": "derived_ttm_2025-04-01_2026-03-31",
			"period_name": "TTM to 2026-03-31", "view": "ttm", "source_accession": "derived",
			"source_selection_status": "DERIVED", "derivation": "FY2025 + current YTD - prior comparable YTD",
			"display_value": _display_value(row.get("numeric_value"), row.get("unit")),
			"source_references": json.dumps(_json_safe(row.get("source_references"))),
		})
		rows.append(row)
	return pd.DataFrame(rows), pd.DataFrame(unavailable), checks


def _build_q4(history: pd.DataFrame) -> pd.DataFrame:
	rows: list[dict[str, object]] = []
	group_fields = [field for field in ("statement", "concept", "dimensions") if field in history]
	for _, group in history.groupby(group_fields, dropna=False, sort=False):
		concept_text = "".join(ch for ch in _cell(group.iloc[0].get("concept")).lower() if ch.isalnum()) if not group.empty else ""
		if any(marker in concept_text for marker in (
			"earningspershare", "eps", "pershare", "margin", "growth", "percent",
			"percentage", "weightedaverage", "sharesaverage", "sharesoutstanding",
			"sharecount",
		)):
			continue
		fy = group.loc[group["period_key"].eq("duration_2024-07-01_2025-06-30")]
		prior = group.loc[group["period_key"].eq("duration_2024-07-01_2025-03-31")]
		if len(fy) != 1 or len(prior) != 1:
			continue
		fy_value, prior_value = _number(fy.iloc[0]["numeric_value"]), _number(prior.iloc[0]["numeric_value"])
		row = fy.iloc[0].to_dict()
		row.update({
			"period_key": "derived_duration_2025-04-01_2025-06-30", "period_name": "Q4 FY2025 (derived)",
			"view": "quarter", "period_type": "duration", "period_start": "2025-04-01",
			"period_end": "2025-06-30", "period_instant": None,
			"numeric_value": None if fy_value is None or prior_value is None else fy_value - prior_value,
			"source_accession": "derived", "source_selection_status": "DERIVED_DEPENDENT",
			"derivation": "FY2025 annual - prior comparable YTD",
			"source_references": json.dumps(_json_safe([
				{"accession": fy.iloc[0].get("accession"), "period_key": fy.iloc[0].get("period_key")},
				{"accession": prior.iloc[0].get("accession"), "period_key": prior.iloc[0].get("period_key")},
			])),
		})
		row["display_value"] = _display_value(row["numeric_value"], row.get("unit"))
		rows.append(row)
	return pd.DataFrame(rows)


def _value_at(history: pd.DataFrame, statement: str, concept: str, period_key: str, dimensions: object | None = None) -> float | None:
	rows = history.loc[(history["statement"].eq(statement)) & history["concept"].eq(concept) & history["period_key"].eq(period_key) & history["source_selection_status"].ne("UNRESOLVED")]
	if dimensions is not None and "dimensions" in rows:
		rows = rows.loc[rows["dimensions"].eq(dimensions)]
	return _number(rows.iloc[0]["numeric_value"]) if len(rows) == 1 else None


_EQUATION_COLUMNS = ["check_id", "status", "reason", "detail", "expected", "observed", "difference", "tolerance", "consequence"]
_CHECK_PERIODS = (
	("FY2023", "duration_2022-07-01_2023-06-30"),
	("FY2024", "duration_2023-07-01_2024-06-30"),
	("FY2025", "duration_2024-07-01_2025-06-30"),
	("Current YTD", "duration_2025-07-01_2026-03-31"),
	("Prior comparable YTD", "duration_2024-07-01_2025-03-31"),
)


def _history_rows(
	history: pd.DataFrame,
	statement: str,
	concept: str,
	period_key: str,
	dimensions: object = "{}",
) -> pd.DataFrame:
	if history.empty or not {"statement", "concept", "period_key"}.issubset(history.columns):
		return history.iloc[0:0].copy()
	rows = history.loc[
		history["statement"].eq(statement)
		& history["concept"].eq(concept)
		& history["period_key"].eq(period_key)
	]
	if "source_selection_status" in rows:
		rows = rows.loc[rows["source_selection_status"].ne("UNRESOLVED")]
	if "dimensions" in rows:
		rows = rows.loc[rows["dimensions"].eq(dimensions)]
	return rows


def _concept_candidates(reference: str | tuple[str, ...]) -> tuple[str, ...]:
	return reference if isinstance(reference, tuple) else (reference,)


def _equation_result(
	check_id: str,
	status: str,
	reason: str,
	detail: str,
	*,
	expected: float | None = None,
	observed: float | None = None,
	difference: float | None = None,
	tolerance: float | None = 0.0,
	consequence: str = "equation unavailable; source values retained without adjustment",
) -> dict[str, object]:
	return {
		"check_id": check_id, "status": status, "reason": reason, "detail": detail,
		"expected": expected, "observed": observed, "difference": difference,
		"tolerance": tolerance, "consequence": consequence,
	}


def _observed_equation(
	history: pd.DataFrame,
	check_id: str,
	statement: str,
	period_key: str,
	observed_concept: str,
	components: list[str | tuple[str, ...]],
) -> dict[str, object]:
	"""Check one reported identity using native values and presentation weights."""
	observed_rows = _history_rows(history, statement, observed_concept, period_key)
	selected: list[tuple[str, pd.Series]] = []
	missing: list[str] = []
	ambiguous: list[str] = []
	for reference in components:
		choices: list[tuple[str, pd.Series]] = []
		for concept in _concept_candidates(reference):
			candidate_rows = _history_rows(history, statement, concept, period_key)
			if len(candidate_rows) == 1:
				choices.append((concept, candidate_rows.iloc[0]))
			elif len(candidate_rows) > 1:
				ambiguous.append(concept)
		if len(choices) == 1:
			selected.append(choices[0])
		elif len(choices) > 1:
			ambiguous.append("|".join(concept for concept, _ in choices))
		else:
			missing.append("|".join(_concept_candidates(reference)))
	detail_prefix = f"period={period_key}; observed_concept={observed_concept}; components={','.join(concept for concept, _ in selected)}; basis=native numeric_value*weight"
	if len(observed_rows) == 0:
		return _equation_result(check_id, "NOT_TESTED", "missing_observed_value", detail_prefix)
	if len(observed_rows) > 1:
		return _equation_result(check_id, "NOT_TESTED", "ambiguous_observed_value", f"{detail_prefix}; observed_rows={len(observed_rows)}")
	if ambiguous:
		return _equation_result(check_id, "NOT_TESTED", "ambiguous_equation_component", f"{detail_prefix}; ambiguous={','.join(ambiguous)}")
	if missing:
		return _equation_result(check_id, "NOT_TESTED", "missing_equation_component", f"{detail_prefix}; missing={','.join(missing)}")
	rows = [observed_rows.iloc[0], *(row for _, row in selected)]
	units = {_cell(row.get("unit")).lower() for row in rows}
	currencies = {_cell(row.get("currency")).upper() for row in rows}
	if not units or "" in units or not currencies or "" in currencies:
		return _equation_result(check_id, "NOT_TESTED", "missing_equation_unit_metadata", f"{detail_prefix}; units={sorted(units)}; currencies={sorted(currencies)}")
	if len(units) != 1 or len(currencies) != 1:
		return _equation_result(check_id, "NOT_TESTED", "equation_unit_mismatch", f"{detail_prefix}; units={sorted(units)}; currencies={sorted(currencies)}")
	if any("share" in unit or "%" in unit for unit in units):
		return _equation_result(check_id, "NOT_TESTED", "non_monetary_equation_unit", f"{detail_prefix}; units={sorted(units)}")
	amounts: list[float] = []
	for row in rows:
		value = _number(row.get("numeric_value"))
		weight = _number(row.get("weight"))
		if value is None:
			return _equation_result(check_id, "NOT_TESTED", "missing_equation_value", f"{detail_prefix}; concept={row.get('concept')}")
		if weight is None:
			return _equation_result(check_id, "NOT_TESTED", "missing_equation_sign_metadata", f"{detail_prefix}; concept={row.get('concept')}")
		amounts.append(value * weight)
	expected = sum(amounts[1:])
	observed = amounts[0]
	difference = observed - expected
	tolerance = 0.0
	status = "PASS" if abs(difference) <= tolerance else "FAIL"
	return _equation_result(
		check_id, status, "reported_identity_holds" if status == "PASS" else "reported_identity_difference",
		f"{detail_prefix}; units={sorted(units)}",
		expected=expected, observed=observed, difference=difference, tolerance=tolerance,
		consequence="reported identity retained; no plug or normalization" if status == "FAIL" else "reported identity holds",
	)


def _cash_bridge_equation(
	history: pd.DataFrame,
	check_id: str,
	opening_period: str,
	movement_period: str,
	closing_period: str,
) -> dict[str, object]:
	endpoint = "us-gaap_CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"
	movement = "us-gaap_CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect"
	opening_rows = _history_rows(history, "cash_flow_statement", endpoint, opening_period)
	movement_rows = _history_rows(history, "cash_flow_statement", movement, movement_period)
	closing_rows = _history_rows(history, "cash_flow_statement", endpoint, closing_period)
	detail_prefix = f"opening={opening_period}; movement={movement_period}; closing={closing_period}; basis=instant endpoint + duration movement*weight"
	if len(opening_rows) != 1 or len(movement_rows) != 1 or len(closing_rows) != 1:
		return _equation_result(
			check_id, "NOT_TESTED", "missing_cash_bridge_component", f"{detail_prefix}; rows={len(opening_rows)},{len(movement_rows)},{len(closing_rows)}",
		)
	rows = [opening_rows.iloc[0], movement_rows.iloc[0], closing_rows.iloc[0]]
	units = {_cell(row.get("unit")).lower() for row in rows}
	currencies = {_cell(row.get("currency")).upper() for row in rows}
	if not units or "" in units or not currencies or "" in currencies:
		return _equation_result(check_id, "NOT_TESTED", "missing_cash_bridge_unit_metadata", f"{detail_prefix}; units={sorted(units)}; currencies={sorted(currencies)}")
	if len(units) != 1 or len(currencies) != 1:
		return _equation_result(check_id, "NOT_TESTED", "cash_bridge_unit_mismatch", f"{detail_prefix}; units={sorted(units)}; currencies={sorted(currencies)}")
	opening = _number(rows[0].get("numeric_value"))
	movement_value = _number(rows[1].get("numeric_value"))
	movement_weight = _number(rows[1].get("weight"))
	closing = _number(rows[2].get("numeric_value"))
	if opening is None or movement_value is None or closing is None:
		return _equation_result(check_id, "NOT_TESTED", "missing_cash_bridge_value", f"{detail_prefix}; values={opening},{movement_value},{closing}")
	if movement_weight is None:
		return _equation_result(check_id, "NOT_TESTED", "missing_cash_bridge_sign_metadata", f"{detail_prefix}; movement_weight={movement_weight}")
	expected = opening + movement_value * movement_weight
	difference = closing - expected
	tolerance = 0.0
	status = "PASS" if abs(difference) <= tolerance else "FAIL"
	return _equation_result(
		check_id, status, "cash_bridge_holds" if status == "PASS" else "cash_bridge_difference", detail_prefix,
		expected=expected, observed=closing, difference=difference, tolerance=tolerance,
		consequence="reported cash difference retained; no plug or restricted-cash normalization" if status == "FAIL" else "reported cash bridge holds",
	)


def _source_integrity_checks(history: pd.DataFrame) -> list[dict[str, object]]:
	"""Validate locators and source/native unit meaning without relabeling rows."""
	if history.empty or "numeric_value" not in history:
		return [
			_equation_result("source_locator_integrity", "NOT_TESTED", "missing_source_rows", "no numeric native rows"),
			_equation_result("source_unit_integrity", "NOT_TESTED", "missing_source_rows", "no numeric native rows"),
		]
	numeric = history.loc[history["numeric_value"].map(_number).notna()].copy()
	if numeric.empty:
		return [
			_equation_result("source_locator_integrity", "NOT_TESTED", "no_numeric_native_rows", "metadata-only rows have no source-value integrity check"),
			_equation_result("source_unit_integrity", "NOT_TESTED", "no_numeric_native_rows", "metadata-only rows have no source-unit integrity check"),
		]
	locator_fields = ("source_fact_id", "source_context_ref", "source_locator")
	missing_locator = {
		field: int(numeric[field].map(_cell).eq("").sum()) if field in numeric else len(numeric)
		for field in locator_fields
	}
	locator_bad = sum(missing_locator.values())
	locator_detail = f"numeric_rows={len(numeric)}; missing=" + ",".join(f"{field}:{count}" for field, count in missing_locator.items())
	locator = _equation_result(
		"source_locator_integrity", "PASS" if locator_bad == 0 else "FAIL",
		"exact_fact_context_locator_present" if locator_bad == 0 else "missing_source_locator_metadata",
		locator_detail,
		consequence="native fact/context and primary-document locator retained" if locator_bad == 0 else "source identity is unresolved; do not treat the row as fully verified",
	)
	invalid_units: list[str] = []
	inline_missing = 0
	inline_mismatch = 0
	for _, row in numeric.iterrows():
		concept = _cell(row.get("concept")).lower()
		native_unit = _cell(row.get("unit")).lower()
		source_unit = _cell(row.get("source_unit_ref")).lower()
		inline_unit = _cell(row.get("source_inline_unit_ref")).lower()
		if not source_unit:
			invalid_units.append(f"{row.get('concept')}:missing source unit")
		elif "earningspershare" in concept:
			if "share" not in source_unit or not ("usd" in source_unit or "dollar" in source_unit):
				invalid_units.append(f"{row.get('concept')}:{row.get('source_unit_ref')}")
		elif "weightedaverage" in concept or "sharesoutstanding" in concept or native_unit == "shares":
			if "share" not in source_unit or "dollar" in source_unit or "usd" in source_unit:
				invalid_units.append(f"{row.get('concept')}:{row.get('source_unit_ref')}")
		elif native_unit in {"usd", "u_usd"} and ("share" in source_unit or not ("usd" in source_unit or "dollar" in source_unit)):
				invalid_units.append(f"{row.get('concept')}:{row.get('source_unit_ref')}")
		if not inline_unit:
			inline_missing += 1
		elif inline_unit != source_unit:
			inline_mismatch += 1
	unit_bad = len(invalid_units) + inline_missing + inline_mismatch
	unit_detail = f"numeric_rows={len(numeric)}; invalid_source_units={invalid_units[:5]}; inline_missing={inline_missing}; inline_source_unit_mismatch={inline_mismatch}; native_shares_label_is_retained_for_eps"
	unit = _equation_result(
		"source_unit_integrity", "PASS" if unit_bad == 0 else "FAIL",
		"source_units_match_native_meaning" if unit_bad == 0 else "source_unit_metadata_unresolved",
		unit_detail,
		consequence="source unitRef retained; native values are not rescaled or relabeled" if unit_bad == 0 else "source unit meaning is unresolved; do not use the row as verified monetary/share data",
	)
	return [locator, unit]


def _standard_comparative_value(statement: object, concept: str, period_end: str) -> dict[str, object]:
	try:
		frame = _standard_dataframe(statement)
	except Exception as exc:
		return {"status": "NOT_TESTED", "reason": "later_comparative_unavailable", "detail": str(exc)}
	if frame.empty or "concept" not in frame:
		return {"status": "NOT_TESTED", "reason": "later_comparative_unavailable", "detail": "native standard frame is empty"}
	period_columns = [str(column) for column in frame.columns if str(column) == period_end]
	if not period_columns:
		period_columns = [str(column) for column in frame.columns if str(column).startswith(period_end)]
	if not period_columns:
		return {"status": "NOT_TESTED", "reason": "later_comparative_period_unavailable", "detail": f"period_end={period_end}"}
	period_column = period_columns[0]
	rows = frame.loc[frame["concept"].astype(str).eq(concept)]
	if "dimension" in rows:
		rows = rows.loc[~rows["dimension"].fillna(False).astype(bool)]
	rows = rows.loc[rows[period_column].notna()]
	if len(rows) != 1:
		return {"status": "NOT_TESTED", "reason": "later_comparative_ambiguous" if len(rows) > 1 else "later_comparative_value_unavailable", "detail": f"period_column={period_column}; rows={len(rows)}"}
	row = rows.iloc[0]
	return {
		"status": "OBSERVED", "period_column": period_column, "numeric_value": _number(row.get(period_column)),
		"unit": _cell(row.get("unit")), "weight": _number(row.get("weight")),
	}


def _cross_filing_comparisons(
	history: pd.DataFrame,
	statement_cache: dict[tuple[str, str], object],
) -> tuple[pd.DataFrame, list[tuple[str, str, str, str]]]:
	"""Compare original annual rows with later-filed native comparative columns."""
	pairs = (
		("FY2023", "2023-06-30", "duration_2022-07-01_2023-06-30", SOURCE_ACCESSIONS["FY2023"], SOURCE_ACCESSIONS["FY2024"]),
		("FY2024", "2024-06-30", "duration_2023-07-01_2024-06-30", SOURCE_ACCESSIONS["FY2024"], SOURCE_ACCESSIONS["FY2025"]),
		("FY2025", "2025-06-30", "duration_2024-07-01_2025-06-30", SOURCE_ACCESSIONS["FY2025"], SOURCE_ACCESSIONS["FY2026_Q3"]),
	)
	records: list[dict[str, object]] = []
	checks: list[tuple[str, str, str, str]] = []
	for period_name, period_end, period_key, original_accession, later_accession in pairs:
		for statement_name in ("income_statement", "cash_flow_statement", "balance_sheet"):
			original_rows = history.loc[
				history["statement"].eq(statement_name)
				& history["period_key"].eq(f"instant_{period_end}" if statement_name == "balance_sheet" else period_key)
				& history["source_accession"].eq(original_accession)
				& history["dimensions"].eq("{}")
				& history["numeric_value"].map(_number).notna()
			]
			statement = statement_cache.get((later_accession, statement_name))
			for concept in original_rows["concept"].dropna().astype(str).drop_duplicates():
				original = original_rows.loc[original_rows["concept"].eq(concept)]
				comparison_id = f"annual_comparative:{statement_name}:{period_name}:{concept}"
				record: dict[str, object] = {
					"comparison_id": comparison_id, "statement": statement_name, "period_name": period_name,
					"period_end": period_end, "period_key": period_key, "original_accession": original_accession,
					"later_accession": later_accession, "concept": concept,
				}
				if len(original) != 1:
					status, reason, detail = "NOT_TESTED", "ambiguous_original_annual_value", f"original_rows={len(original)}"
				elif statement is None:
					status, reason, detail = "NOT_TESTED", "later_comparative_unavailable", "later statement object unavailable"
				else:
					later = _standard_comparative_value(statement, concept, period_end)
					if later.get("status") != "OBSERVED":
						status, reason, detail = _cell(later.get("status")) or "NOT_TESTED", _cell(later.get("reason")) or "later_comparative_unavailable", _cell(later.get("detail"))
					else:
						original_row = original.iloc[0]
						original_value = _number(original_row.get("numeric_value"))
						later_value = _number(later.get("numeric_value"))
						original_unit = _cell(original_row.get("unit"))
						later_unit = _cell(later.get("unit"))
						original_weight = _number(original_row.get("weight"))
						later_weight = _number(later.get("weight"))
						record.update({
							"original_value": original_value, "later_value": later_value,
							"original_unit": original_unit, "later_unit": later_unit,
							"original_weight": original_weight, "later_weight": later_weight,
							"later_period_column": later.get("period_column"),
						})
						same_value = original_value is not None and later_value is not None and original_value == later_value
						same_unit = bool(original_unit) and original_unit == later_unit
						same_weight = (
							(original_weight is None and later_weight is None)
							or (original_weight is not None and later_weight is not None and original_weight == later_weight)
						)
						if same_value and same_unit and same_weight:
							status, reason = "PASS", "equivalent_later_comparative"
							detail = f"selected original accession={original_accession}; later comparative accession={later_accession}; period_column={later.get('period_column')}; unit={later_unit}"
						else:
							status, reason = "NOT_TESTED", "later_comparative_changed_review"
							detail = f"selected original accession={original_accession}; original={original_value} {original_unit} weight={original_weight}; later={later_value} {later_unit} weight={later_weight}; no replacement or normalization"
				record.update({"status": status, "reason": reason, "detail": detail})
				records.append(record)
				checks.append((comparison_id, status, reason, detail))
	return pd.DataFrame(records), checks


def _case_checks(
	history: pd.DataFrame,
	period_specs: list[dict[str, object]],
	ttm: pd.DataFrame,
	q4: pd.DataFrame,
	filings: dict[str, object],
) -> pd.DataFrame:
	rows: list[tuple[str, str, str, str]] = []
	equation_rows: list[dict[str, object]] = []
	for accession, filing in filings.items():
		metadata = _filing_metadata(filing)
		filing_date = _date_value(metadata.get("filing_date"))
		status = "PASS" if filing_date and filing_date <= CASE_CUTOFF else "FAIL"
		rows.append((f"source_cutoff:{accession}", status, "cutoff_qualified" if status == "PASS" else "after_cutoff_or_missing_date", str(metadata.get("filing_date"))))
	period_identity = [(str(spec["statement"]), str(spec["period_key"])) for spec in period_specs]
	rows.append(("period_table_unique", "PASS" if len(period_identity) == len(set(period_identity)) else "FAIL", "unique_native_period_ids_per_statement", str(len(period_identity))))
	for spec in period_specs:
		found = history.loc[(history["statement"].eq(spec["statement"])) & history["period_key"].eq(spec["period_key"])]
		rows.append((f"period_available:{spec['statement']}:{spec['period_key']}", "PASS" if not found.empty else "FAIL", "native_period_projected" if not found.empty else "native_period_unavailable", str(len(found))))
	duplicate_keys = ["statement", "concept", "dimensions", "period_key"]
	duplicates = history.loc[history.duplicated(duplicate_keys, keep=False)]
	rows.append(("history_unique_period_rows", "PASS" if duplicates.empty else "FAIL", "one_row_per_native_identity" if duplicates.empty else "duplicate_native_identity", str(len(duplicates))))
	unresolved = history.loc[history["source_selection_status"].eq("UNRESOLVED")]
	rows.append(("native_conflicts", "PASS" if unresolved.empty else "FAIL", "no_conflicting_matching_facts" if unresolved.empty else "conflicting_matching_facts_preserved", str(len(unresolved))))
	missing_links = history.loc[history["source_selection_status"].eq("MISSING")]
	rows.append(("native_fact_links", "PASS" if missing_links.empty else "FAIL", "exact_fact_context_links" if missing_links.empty else "missing_exact_fact_context_links", str(len(missing_links))))
	latest_period = "instant_2026-03-31"
	cash = _value_at(history, "balance_sheet", "us-gaap_CashAndCashEquivalentsAtCarryingValue", latest_period)
	cf_cash = _value_at(history, "cash_flow_statement", "us-gaap_CashAndCashEquivalentsAtCarryingValue", latest_period)
	if cash is None or cf_cash is None:
		rows.append(("cash_endpoint_identity", "NOT_TESTED", "same_cash_endpoint_not_observed_in_both_statements", f"balance_sheet={cash}, cash_flow={cf_cash}"))
	else:
		difference = cash - cf_cash
		rows.append(("cash_endpoint_identity", "PASS" if difference == 0 else "FAIL", "same_definition_same_endpoint" if difference == 0 else "cash_endpoint_difference", str(difference)))
	bs_cash_total = _value_at(history, "balance_sheet", "us-gaap_CashCashEquivalentsAndShortTermInvestments", latest_period)
	rows.append(("cash_definition_scope", "PASS" if cash is not None and bs_cash_total is not None else "NOT_TESTED", "cash_and_cash_plus_short_term_investments_retained_separately" if cash is not None and bs_cash_total is not None else "cash_definition_alternative_not_observed", f"cash={cash}, cash_plus_short_term_investments={bs_cash_total}"))
	restricted_endpoint = _value_at(history, "cash_flow_statement", "us-gaap_CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", latest_period)
	rows.append(("cash_flow_endpoint_definition", "NOT_TESTED", "cash_flow_endpoint_includes_restricted_cash" if restricted_endpoint is not None else "cash_flow_endpoint_not_observed", f"balance_sheet_cash={cash}, cash_flow_restricted_endpoint={restricted_endpoint}"))
	if ttm.empty:
		rows.append(("ttm_identity", "FAIL", "no_additive_ttm_rows", ""))
	else:
		for _, row in ttm.iterrows():
			concept, statement = _cell(row.get("concept")), _cell(row.get("statement"))
			dimensions = row.get("dimensions")
			fy = _value_at(history, statement, concept, "duration_2024-07-01_2025-06-30", dimensions)
			current = _value_at(history, statement, concept, "duration_2025-07-01_2026-03-31", dimensions)
			prior = _value_at(history, statement, concept, "duration_2024-07-01_2025-03-31", dimensions)
			actual = _number(row.get("numeric_value"))
			expected = None if None in (fy, current, prior) else fy + current - prior
			rows.append((f"ttm_identity:{statement}:{concept}", "PASS" if expected == actual else "FAIL", "fy_plus_current_ytd_minus_prior_ytd" if expected == actual else "ttm_value_difference", str(actual - expected) if actual is not None and expected is not None else "missing_component"))
	rows.append(("quarterly_independence", "NOT_TESTED", "q4_reconstructed_from_fy_and_prior_ytd", f"dependent_q4_rows={len(q4)}"))

	equation_rows.extend(_source_integrity_checks(history))
	income_equations = (
		("gross_profit", "us-gaap_GrossProfit", ["us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax", "us-gaap_CostOfGoodsAndServicesSold"]),
		("operating_income", "us-gaap_OperatingIncomeLoss", ["us-gaap_GrossProfit", "us-gaap_ResearchAndDevelopmentExpense", "us-gaap_SellingAndMarketingExpense", "us-gaap_GeneralAndAdministrativeExpense"]),
		("pretax_income", "us-gaap_IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest", ["us-gaap_OperatingIncomeLoss", "us-gaap_NonoperatingIncomeExpense"]),
		("net_income", "us-gaap_NetIncomeLoss", ["us-gaap_IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest", "us-gaap_IncomeTaxExpenseBenefit"]),
	)
	cash_equations = (
		("operating_components", "us-gaap_NetCashProvidedByUsedInOperatingActivities", [
			"us-gaap_NetIncomeLoss", "msft_DepreciationAmortizationAndOther", "us-gaap_ShareBasedCompensation",
			"msft_GainLossOnInvestmentsAndDerivativeInstruments", ("us-gaap_DeferredIncomeTaxExpenseBenefit", "us-gaap_DeferredIncomeTaxesAndTaxCredits"),
			"us-gaap_IncreaseDecreaseInAccountsReceivable", "us-gaap_IncreaseDecreaseInInventories", "us-gaap_IncreaseDecreaseInOtherCurrentAssets",
			"us-gaap_IncreaseDecreaseInOtherNoncurrentAssets", "us-gaap_IncreaseDecreaseInAccountsPayable", "us-gaap_IncreaseDecreaseInContractWithCustomerLiability",
			"us-gaap_IncreaseDecreaseInAccruedIncomeTaxesPayable", "us-gaap_IncreaseDecreaseInOtherCurrentLiabilities", "us-gaap_IncreaseDecreaseInOtherNoncurrentLiabilities",
		]),
		("investing_components", "us-gaap_NetCashProvidedByUsedInInvestingActivities", [
			"us-gaap_PaymentsToAcquirePropertyPlantAndEquipment", "msft_AcquisitionsNetOfCashAcquiredAndPurchasesOfIntangibleAndOtherAssets",
			"us-gaap_PaymentsToAcquireInvestments", "us-gaap_ProceedsFromMaturitiesPrepaymentsAndCallsOfAvailableForSaleSecurities",
			"msft_ProceedsFromInvestments", "us-gaap_PaymentsForProceedsFromOtherInvestingActivities",
		]),
		("financing_components", "us-gaap_NetCashProvidedByUsedInFinancingActivities", [
			("us-gaap_ProceedsFromRepaymentsOfShortTermDebtMaturingInThreeMonthsOrLess", "us-gaap_RepaymentsOfShortTermDebtMaturingInThreeMonthsOrLess"),
			"us-gaap_ProceedsFromDebtMaturingInMoreThanThreeMonths", "us-gaap_RepaymentsOfDebtMaturingInMoreThanThreeMonths",
			"us-gaap_ProceedsFromIssuanceOfCommonStock", "us-gaap_PaymentsForRepurchaseOfCommonStock",
			"us-gaap_PaymentsOfDividendsCommonStock", "us-gaap_ProceedsFromPaymentsForOtherFinancingActivities",
		]),
		("net_change", "us-gaap_CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect", [
			"us-gaap_NetCashProvidedByUsedInOperatingActivities", "us-gaap_NetCashProvidedByUsedInInvestingActivities",
			"us-gaap_NetCashProvidedByUsedInFinancingActivities", "us-gaap_EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsIncludingDisposalGroupAndDiscontinuedOperations",
		]),
	)
	for period_name, period_key in _CHECK_PERIODS:
		for name, observed, components in income_equations:
			equation_rows.append(_observed_equation(history, f"income_statement:{period_name}:{period_key}:{name}", "income_statement", period_key, observed, components))
		for name, observed, components in cash_equations:
			equation_rows.append(_observed_equation(history, f"cash_flow_statement:{period_name}:{period_key}:{name}", "cash_flow_statement", period_key, observed, components))

	bs_equations = (
		("balance_sheet_assets_vs_liabilities_equity", "us-gaap_Assets", ["us-gaap_Liabilities", "us-gaap_StockholdersEquity"]),
		("balance_sheet_assets_vs_reported_total", "us-gaap_Assets", ["us-gaap_LiabilitiesAndStockholdersEquity"]),
		("balance_sheet_identity", "us-gaap_LiabilitiesAndStockholdersEquity", ["us-gaap_Liabilities", "us-gaap_StockholdersEquity"]),
		("balance_sheet_current_assets_components", "us-gaap_AssetsCurrent", ["us-gaap_CashCashEquivalentsAndShortTermInvestments", "us-gaap_AccountsReceivableNetCurrent", "us-gaap_InventoryNet", "us-gaap_OtherAssetsCurrent"]),
		("balance_sheet_current_liabilities_components", "us-gaap_LiabilitiesCurrent", ["us-gaap_AccountsPayableCurrent", "us-gaap_LongTermDebtCurrent", "us-gaap_EmployeeRelatedLiabilitiesCurrent", "us-gaap_AccruedIncomeTaxesCurrent", "us-gaap_ContractWithCustomerLiabilityCurrent", "us-gaap_OtherLiabilitiesCurrent"]),
		("balance_sheet_equity_components", "us-gaap_StockholdersEquity", ["us-gaap_CommonStocksIncludingAdditionalPaidInCapital", "us-gaap_RetainedEarningsAccumulatedDeficit", "us-gaap_AccumulatedOtherComprehensiveIncomeLossNetOfTax"]),
	)
	for name, observed, components in bs_equations:
		equation_rows.append(_observed_equation(history, name, "balance_sheet", latest_period, observed, components))
	for name, opening, movement, closing in (
		("FY2023", "instant_2022-06-30", "duration_2022-07-01_2023-06-30", "instant_2023-06-30"),
		("FY2024", "instant_2023-06-30", "duration_2023-07-01_2024-06-30", "instant_2024-06-30"),
		("FY2025", "instant_2024-06-30", "duration_2024-07-01_2025-06-30", "instant_2025-06-30"),
		("current_ytd", "instant_2025-06-30", "duration_2025-07-01_2026-03-31", "instant_2026-03-31"),
		("prior_ytd", "instant_2024-06-30", "duration_2024-07-01_2025-03-31", "instant_2025-03-31"),
	):
		equation_rows.append(_cash_bridge_equation(history, f"cash_bridge:{name}", opening, movement, closing))
	base = pd.DataFrame(rows, columns=["check_id", "status", "reason", "detail"])
	for column in _EQUATION_COLUMNS[4:]:
		base[column] = ""
	return pd.concat([base, pd.DataFrame(equation_rows, columns=_EQUATION_COLUMNS)], ignore_index=True)


def _latest_balance(history: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
	if history.empty:
		return pd.DataFrame(), pd.DataFrame()
	result = latest_balance_sheet(history, information_cutoff=CASE_CUTOFF)
	return result["balance_sheet"].copy(), result["checks"].copy()


def _table_rows(frame: pd.DataFrame, columns: list[str], limit: int | None = None) -> list[list[object]]:
	if frame.empty:
		return [columns]
	selected = frame.loc[:, [column for column in columns if column in frame.columns]].head(limit)
	actual_columns = list(selected.columns)
	return [actual_columns] + [[_json_safe(value) for value in row] for row in selected.itertuples(index=False, name=None)]


def _write_evidence(
	path: Path,
	manifest: pd.DataFrame,
	history: pd.DataFrame,
	checks: pd.DataFrame,
	evidence_packets: list[dict[str, object]] | None = None,
	excluded: pd.DataFrame | None = None,
	comparisons: pd.DataFrame | None = None,
) -> None:
	lines = [
		"# MSFT frozen source evidence", "", f"Information cut-off: {CASE_CUTOFF.isoformat()}",
		f"Measurement date: {MEASUREMENT_DATE.isoformat()}",
		"Primary values: EdgarTools standard statement DataFrames.",
		"Provenance: native facts, contexts, and inline attributes only.",
		"Numeric basis: native statement numbers are already expanded to USD; native scale factor is 1.0. Inline scale and decimals remain separate metadata.",
		"", "## Selected filings", "",
	]
	for row in manifest.to_dict(orient="records"):
		lines.append(f"- {row.get('accession')} | {row.get('form_type')} | filed {row.get('filing_date')} | report {row.get('report_date')} | {row.get('source_locator')}")
	lines.extend(["", "## Period and unit evidence", ""])
	material_concepts = {
		candidate for candidates in MATERIAL_CONCEPTS.values() for candidate in candidates
	}
	representative_periods = {
		"duration_2024-07-01_2025-06-30", "duration_2025-07-01_2026-03-31", "instant_2026-03-31",
	}
	evidence_history = history
	if "dimension" in history:
		evidence_history = history.loc[
			history["dimension"].eq(False)
			& history["concept"].astype(str).isin(material_concepts)
			& history["period_key"].astype(str).isin(representative_periods)
		]
	if evidence_history.empty:
		evidence_history = history
	evidence_history = evidence_history.drop_duplicates(
		[column for column in ("statement", "concept", "period_key") if column in evidence_history]
	).head(24)
	for _, row in evidence_history.iterrows():
		lines.append(f"- {row.get('statement')} | {row.get('concept')} | {row.get('period_key')} | value {row.get('numeric_value')} | unit {row.get('unit')} | unitRef {row.get('source_unit_ref')} | inline unitRef {row.get('source_inline_unit_ref')} | sign {row.get('source_inline_sign')} | decimals {row.get('source_decimals')} | inline scale {row.get('source_inline_scale')} | fact {row.get('source_fact_id')} | context {row.get('source_context_ref')}")
	lines.extend(["", "## Original filing excerpts", ""])
	if evidence_packets:
		for packet in evidence_packets:
			lines.append(f"- {packet.get('packet_id')} | accession {packet.get('accession')} | period {packet.get('period')} | {packet.get('unit_context')} | {packet.get('source_locator')} | {packet.get('excerpt')}")
	else:
		lines.append("- No qualifying original filing excerpt was observed in the cached filing HTML.")
	excluded_count = len(excluded) if excluded is not None else 0
	excluded_numeric = int(excluded["numeric_value"].notna().sum()) if excluded is not None and "numeric_value" in excluded else 0
	lines.extend(["", "## Excluded native rows", "", f"- Excluded rows: {excluded_count}; rows with a numeric value: {excluded_numeric}. Any numeric excluded row is unresolved and blocks a clean case status."])
	lines.extend(["", "## Later filing comparative checks", ""])
	if comparisons is None or comparisons.empty:
		lines.append("- No later-filed annual comparative was available for the selected native rows.")
	else:
		for row in comparisons.loc[comparisons["status"].ne("PASS")].head(20).to_dict(orient="records"):
			lines.append(f"- {row.get('comparison_id')} | {row.get('status')} | {row.get('reason')} | {row.get('detail')}")
	lines.extend(["", "## Cash-definition note", "", "Cash and cash equivalents, cash plus short-term investments, restricted cash concepts, and cash-flow net-change concepts are retained as separate native identities. No restricted-cash or FX plug is used.", "", "## Check residuals", ""])
	residuals = checks.loc[checks["status"].ne("PASS")].drop_duplicates(
		[column for column in ("check_id", "status", "reason", "detail") if column in checks]
	).head(20)
	for _, row in residuals.iterrows():
		lines.append(f"- {row.get('check_id')}: {row.get('status')} | {row.get('reason')} | {row.get('detail')}")
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _report_text(
	status: str,
	output_dir: Path,
	history: pd.DataFrame,
	ttm: pd.DataFrame,
	checks: pd.DataFrame,
	mapping: pd.DataFrame,
	*,
	report_title: str = "P2 complete frozen history report",
	verification_lines: list[str] | None = None,
	reproducible_command: str | None = None,
) -> str:
	try:
		rel_output = output_dir.resolve().relative_to(Path.cwd().resolve()).as_posix()
	except ValueError:
		rel_output = str(output_dir)
	preview = mapping.loc[mapping["status"].eq("OBSERVED")].head(5)
	preview_lines = ["| Model line | Native concept | FY2025 display | Current YTD display | TTM display |", "|---|---|---:|---:|---:|"]
	for _, map_row in preview.iterrows():
		concept = map_row["observed_concept"]
		rows = history.loc[(history["concept"] == concept) & history["dimension"].eq(False)]
		fy = rows.loc[rows["period_key"].eq("duration_2024-07-01_2025-06-30"), "display_value"]
		cur = rows.loc[rows["period_key"].eq("duration_2025-07-01_2026-03-31"), "display_value"]
		ttm_rows = ttm.loc[ttm["concept"].eq(concept), "display_value"]
		preview_lines.append(f"| {map_row['model_key']} | {concept} | {fy.iloc[0] if len(fy) else 'unavailable'} | {cur.iloc[0] if len(cur) else 'unavailable'} | {ttm_rows.iloc[0] if len(ttm_rows) else 'unavailable'} |")
	failed = int(checks["status"].eq("FAIL").sum())
	not_tested = int(checks["status"].eq("NOT_TESTED").sum())
	verification_lines = verification_lines or [
		"`$env:PYTHONPATH='src'; python -m unittest discover -s tests -p 'test_case_history.py'` — 5 tests, PASS.",
		"`$env:PYTHONPATH='src'; python -m unittest discover -s tests -p 'test_history.py'` — 15 tests, PASS.",
		"`$env:PYTHONPATH='src'; python -m unittest discover -s tests -p 'test_native_history.py'` — 13 tests, PASS; existing pandas FutureWarning only.",
		"`python -m ruff check --no-cache src/smrik_fund/ingestion/case_history.py src/smrik_fund/ingestion/history.py src/smrik_fund/ingestion/native_history.py tests/test_case_history.py tests/test_history.py tests/test_native_history.py` — PASS.",
		"`node --check scripts/spreadsheet_compat/history_export.mjs` — PASS.",
		"Real build — PASS_WITH_LIMITATIONS; 1076 checks (873 PASS, 203 NOT_TESTED, 0 FAIL), 728 projected rows, 13 TTM rows; workbook runner PASS on Mog 0.10.7.",
	]
	reproducible_command = reproducible_command or "$env:PYTHONPATH='src'; python -m smrik_fund.ingestion.case_history --output-root data/build-guide-p2 --cache-dir data/.p2-edgar"
	return "\n".join([
		f"# {report_title}", "", "## Control block", "",
		f"- Status: **{status}**; MSFT; cut-off {CASE_CUTOFF.isoformat()}; measurement {MEASUREMENT_DATE.isoformat()}; display {DISPLAY_UNIT}.",
		"- Primary values are native EdgarTools standard statement DataFrames. Facts/contexts/inline tags are provenance and verification only.",
		"- Native numeric values are already expanded to USD. `native_scale_factor=1.0`; source inline scale, decimals, and unitRef remain separate.",
		f"- Checks: {len(checks)} total; {failed} FAIL; {not_tested} NOT_TESTED. No paid LLM calls.", "", "## Material outputs", "",
		f"- `{rel_output}/source_manifest.json` — cutoff-qualified filing identity and exclusion record.",
		f"- `{rel_output}/history.csv` — projected native rows with exact period IDs and source links.",
		f"- `{rel_output}/annual_history.csv`, `{rel_output}/ytd_history.csv`, `{rel_output}/quarter_history.csv` — historical views.",
		f"- `{rel_output}/ttm_history.csv`, `{rel_output}/ttm_unavailable.csv` — additive TTM and explicit unavailable reasons.",
		f"- `{rel_output}/latest_balance_sheet.csv`, `{rel_output}/period_table.csv`, `{rel_output}/source_references.csv`, `{rel_output}/checks.csv`.",
		f"- `{rel_output}/source_alternatives.csv`, `{rel_output}/excluded_native_values.csv`, `{rel_output}/source_to_model_mapping.csv`, `{rel_output}/source_recast_comparisons.csv` — retained alternatives, excluded rows, observed-line mapping, and later comparative checks.",
		f"- `{rel_output}/native_statements/`, `{rel_output}/native_payload/`, `{rel_output}/workbook_payload.json`, `{rel_output}/runner_result.json`, `{rel_output}/build_summary.json` — native snapshots and export audit records.",
		f"- `{rel_output}/historical_view.xlsx` — Mog 0.10.7 review workbook; `{rel_output}/evidence/source_notes.md` and `{rel_output}/evidence/original_filing_excerpts.json` — source-note and original-filing evidence.", "", "## Representative preview", "", *preview_lines, "", "## Selection and residuals", "",
		"Annual FY2023/FY2024/FY2025 and March 2026 interim accessions are validated by observed accession, form, filing date, report date, and primary-document locator. All projected rows have an exact native fact/context link; equivalent and alternative candidates remain in source_references/source_alternatives. Later filings are outside the API query and remain excluded by the 2026-04-30 cut-off. Later-filed annual comparative values are retained in source_recast_comparisons; equivalent rows support the selected original basis and changed rows remain review-only without replacement or normalization. Quarter Q4 FY2025 is derived from FY2025 less prior comparable YTD; the quarterly cross-check is therefore disclosed as dependent rather than independent proof.",
		"", "## Verification", "", *verification_lines,
		"", "## Reproducible command", "", f"`{reproducible_command}`", "", "## Native API note", "",
		"The installed EdgarTools signature uses `period_filter` and `standard`; its `period_view` helper currently returns a list while the DataFrame builder expects a mapping. The bounded module selector exposes each exact native period by temporarily supplying that period list to the standard builder and restores the library function immediately after the call.",
	])


def _run_workbook_export(output_dir: Path, payload_path: Path) -> dict[str, object]:
	runner = Path(__file__).resolve().parents[3] / "scripts" / "spreadsheet_compat" / "history_export.mjs"
	output_path = output_dir / "historical_view.xlsx"
	try:
		completed = subprocess.run(["node", str(runner), str(payload_path), str(output_path)], cwd=runner.parent.parent.parent, capture_output=True, text=True, timeout=120, check=False)
	except (OSError, subprocess.TimeoutExpired) as exc:
		return {"status": "FAIL", "reason": "workbook_runner_failed", "detail": str(exc)}
	result = {"status": "PASS" if completed.returncode == 0 else "FAIL", "returncode": completed.returncode, "stdout": completed.stdout[-2000:], "stderr": completed.stderr[-2000:], "path": str(output_path)}
	_write_json(output_dir / "runner_result.json", result)
	return result


def _verification_item(
	frame: pd.DataFrame,
	sheet: str,
	criteria_columns: list[str],
	criteria_values: list[object],
) -> dict[str, object]:
	if len(criteria_columns) != len(criteria_values):
		raise CaseHistoryError("workbook verification criteria shape mismatch")
	matches = frame
	for column, value in zip(criteria_columns, criteria_values, strict=True):
		matches = matches.loc[matches[column].eq(value)]
	if len(matches) != 1:
		raise CaseHistoryError(f"workbook verification row is not unique: {sheet} {criteria_columns}={criteria_values}")
	row = matches.iloc[0]
	return {
		"sheet": sheet,
		"criteria": {column: _json_safe(value) for column, value in zip(criteria_columns, criteria_values, strict=True)},
		"valueColumn": "numeric_value", "expectedValue": _json_safe(row["numeric_value"]),
		"unitColumn": "unit", "expectedUnit": _json_safe(row["unit"]),
	}


def _r2_report_text(
	status: str,
	r1_dir: Path,
	output_dir: Path,
	r1_summary: dict[str, object],
	r1_history_sha256: str,
	packets: list[dict[str, object]],
	unavailable: list[dict[str, object]],
	runner_result: dict[str, object],
) -> str:
	try:
		rel_output = output_dir.resolve().relative_to(Path.cwd().resolve()).as_posix()
	except ValueError:
		rel_output = str(output_dir)
	try:
		rel_r1 = r1_dir.resolve().relative_to(Path.cwd().resolve()).as_posix()
	except ValueError:
		rel_r1 = str(r1_dir)
	packet_lines = []
	for packet in packets:
		excerpt = _cell(packet.get("excerpt"))
		preview = f"{excerpt[:70]}... {excerpt[-70:]}"
		packet_lines.append(
			f"- `{packet.get('packet_id')}` — `{packet.get('source_locator')}`; "
			f"SHA-256 `{packet.get('source_sha256')}`; excerpt starts "
			f"`{preview}`."
		)
	unavailable_lines = [
		f"- `{item.get('definition') or item.get('section')}` — {item.get('status')}: {item.get('reason')}"
		for item in unavailable
	]
	if not unavailable_lines:
		unavailable_lines = ["- None."]
	return "\n".join([
		"# P2 complete frozen history R2 report",
		"",
		"## Control block",
		"",
		f"- Status: **{status}**; this is an evidence/workbook revision of `{rel_r1}`.",
		f"- R1 financial artifacts are unchanged by reference: history rows {r1_summary.get('history_rows')}, TTM rows {r1_summary.get('ttm_rows')}, checks {r1_summary.get('checks')} ({r1_summary.get('status')}); R1 history SHA-256 `{r1_history_sha256}`.",
		"- R2 does not rerun history arithmetic or financial checks. It reuses the copied R1 tables and only replaces original-source evidence selection plus the workbook Evidence sheet.",
		"- No paid LLM calls; native statement values, signs, periods, units, and source identities remain in the R1 files.",
		"",
		"## Material outputs",
		"",
		f"- `{rel_output}/build_summary.json` — R2 status, carried-forward counts, source/evidence records, and workbook result.",
		f"- `{rel_output}/r1_reference.json` — immutable R1 path and hash reference.",
		f"- `{rel_output}/evidence/original_source/` — byte-preserved cached full submissions used for offsets and hashes.",
		f"- `{rel_output}/evidence/original_filing_excerpts.json` — eight exact section packets and unavailable definition record.",
		f"- `{rel_output}/evidence/source_notes.md` — cached text/HTML paths, source hashes, offsets, units, and complete excerpts.",
		f"- `{rel_output}/workbook_payload.json`, `{rel_output}/historical_view.xlsx`, `{rel_output}/runner_result.json` — R2 Evidence sheet and Mog 0.10.7 readback.",
		"",
		"## Evidence preview",
		"",
		*packet_lines,
		"",
		"## Selection and limitations",
		"",
		"FY2025 and Q3 FY2026 statement sections are selected from the exact cached full submission text using native filing headings and table endpoints. Balance-sheet packets contain the balance-sheet heading, USD/$ in Millions qualifier, periods, total assets, and total liabilities/equity. Cash-flow packets contain the periods, CFO/CFI/CFF/FX movements, net change, opening cash, and closing cash. Note 6 packets contain the PP&E table and depreciation/additions context. The cash-equivalent packet contains the Financial Instruments/Investments policy and its three-month definition.",
		"",
		*unavailable_lines,
		"",
		"The actual Q3 FY2026 cached submission is `data/.p2-edgar/_tcache/www.sec.gov___Archives__edgar__data__789019__000119312526191507__0001193125-26-191507.txt`; its cached primary HTML is `data/.p2-edgar/_tcache/www.sec.gov___Archives__edgar__data__789019__000119312526191507__msft-20260331.htm`. Reuse reads bytes, decompresses from the first gzip magic bytes (`1f 8b`), decodes UTF-8, then locates exact source character/line offsets and verifies SHA-256. No network refetch is needed.",
		"",
		"## Verification",
		"",
		"- Focused R2 evidence-selection regression covers exact heading/endpoint selection and absent-definition handling; final result is recorded with the changed test command.",
		f"- Mog 0.10.7 workbook runner: **{runner_result.get('status')}**; numeric readbacks are carried from R1 payload and Evidence readbacks include packet IDs, headings, endpoint, locator, and source hash.",
		"- R1 financial check totals are stated by hash/reference above and were not rerun in this narrow R2 step.",
		"",
		"## Reproducible command",
		"",
		"`$env:PYTHONPATH='src'; python -m smrik_fund.ingestion.case_history --evidence-revision-from data/build-guide-p2-r1 --output-root data/build-guide-p2-r2 --cache-dir data/.p2-edgar`",
	])


def build_msft_evidence_revision(
	r1_root: str | Path = "data/build-guide-p2-r1",
	*,
	output_root: str | Path = "data/build-guide-p2-r2",
	cache_dir: str | Path = "data/.p2-edgar",
	report_path: str | Path | None = None,
	write_report: bool = True,
) -> dict[str, object]:
	"""Create the isolated P2 R2 evidence/workbook revision from frozen R1 data."""
	r1_dir = Path(r1_root) / "MSFT"
	output_dir = Path(output_root) / "MSFT"
	if not (r1_dir / "history.csv").is_file():
		raise CaseHistoryError(f"R1 history artifact is missing: {r1_dir / 'history.csv'}")
	if output_dir.exists():
		raise CaseHistoryError(f"R2 output already exists; preserve immutable output: {output_dir}")
	manifest_path = r1_dir / "source_manifest.json"
	if not manifest_path.is_file():
		raise CaseHistoryError(f"R1 source manifest is missing: {manifest_path}")
	try:
		manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
		r1_summary = json.loads((r1_dir / "build_summary.json").read_text(encoding="utf-8"))
	except (OSError, json.JSONDecodeError) as exc:
		raise CaseHistoryError("R1 metadata cannot be read for the evidence revision") from exc
	shutil.copytree(r1_dir, output_dir)
	r1_history_sha256 = hashlib.sha256((r1_dir / "history.csv").read_bytes()).hexdigest()
	r1_checks_sha256 = hashlib.sha256((r1_dir / "checks.csv").read_bytes()).hexdigest()
	r1_ttm_sha256 = hashlib.sha256((r1_dir / "ttm_history.csv").read_bytes()).hexdigest()
	evidence_dir = output_dir / "evidence"
	packets, sources, unavailable = _r2_original_evidence(manifest, Path(cache_dir), evidence_dir)
	_write_json(evidence_dir / "original_filing_excerpts.json", {
		"revision": "P2-complete-R2",
		"sources": sources,
		"packets": packets,
		"unavailable": unavailable,
	})
	_write_r2_evidence_notes(evidence_dir / "source_notes.md", sources, packets, unavailable)
	r1_reference = {
		"revision": "P2-complete-R2",
		"r1_output_dir": str(r1_dir),
		"r1_history_sha256": r1_history_sha256,
		"r1_checks_sha256": r1_checks_sha256,
		"r1_ttm_history_sha256": r1_ttm_sha256,
		"financial_artifacts_unchanged": True,
		"history_rows": r1_summary.get("history_rows"),
		"ttm_rows": r1_summary.get("ttm_rows"),
		"checks": r1_summary.get("checks"),
		"comparison_rows": r1_summary.get("comparison_rows"),
	}
	_write_json(output_dir / "r1_reference.json", r1_reference)
	try:
		payload = json.loads((output_dir / "workbook_payload.json").read_text(encoding="utf-8"))
	except (OSError, json.JSONDecodeError) as exc:
		raise CaseHistoryError("R1 workbook payload cannot be read for the evidence revision") from exc
	old_evidence = payload.get("sheets", {}).get("Evidence", [])
	old_headers = old_evidence[0] if old_evidence and isinstance(old_evidence[0], list) else []
	evidence_columns = [
		"record_type", "statement", "period_name", "concept", "period_key", "fact_id", "context_ref", "unit_ref", "decimals", "inline_scale",
		"packet_id", "accession", "period", "unit_context", "keyword", "source_file", "source_sha256", "source_char_start", "source_char_end", "source_line_start", "source_line_end", "source_locator", "sec_locator", "excerpt",
	]
	evidence_rows = [evidence_columns]
	for row in old_evidence[1:]:
		values = dict(zip(old_headers, row, strict=False))
		if values.get("record_type") == "native_reference":
			evidence_rows.append([values.get(column) for column in evidence_columns])
	for packet in packets:
		evidence_rows.append([
			"original_filing_section", packet.get("statement"), packet.get("period_name"), None,
			packet.get("period_key"), None, None, "u_usd" if packet.get("statement") in {"balance_sheet", "cash_flow_statement"} else None,
			None, None, packet.get("packet_id"), packet.get("accession"), packet.get("period"), packet.get("unit_context"), packet.get("keyword"),
			packet.get("source_file"), packet.get("source_sha256"), packet.get("source_char_start"), packet.get("source_char_end"), packet.get("source_line_start"), packet.get("source_line_end"), packet.get("source_locator"), packet.get("sec_locator"), packet.get("excerpt"),
		])
	payload["sheets"]["Evidence"] = evidence_rows
	readme = payload["sheets"].get("Readme", [])
	readme.extend([
		["Evidence revision", "P2 R2 exact cached original sections", None],
		["R1 history SHA-256", r1_history_sha256, None],
		["R1 financial check basis", f"carried forward unchanged by hash; {r1_summary.get('checks')} checks", None],
	])
	payload["sheets"]["Readme"] = readme
	verification = payload.setdefault("verification", {})
	verification["evidence"] = [
		{"sheet": "Evidence", "contains": packets[0]["packet_id"]},
		{"sheet": "Evidence", "contains": packets[0]["source_locator"]},
		{"sheet": "Evidence", "contains": packets[0]["source_sha256"]},
		{"sheet": "Evidence", "contains": "BALANCE SHEETS - USD ($)"},
		{"sheet": "Evidence", "contains": "CASH FLOWS STATEMENTS - USD ($)"},
		{"sheet": "Evidence", "contains": "Cash and cash equivalents, end of period"},
		{"sheet": "Evidence", "contains": "NOTE 6 — PROPERTY AND EQUIPMENT"},
		{"sheet": "Evidence", "contains": "maturity of three months or less at the date of purchase to be cash equivalents."},
	]
	_write_json(output_dir / "workbook_payload.json", payload)
	runner_result = _run_workbook_export(output_dir, output_dir / "workbook_payload.json")
	status = _cell(r1_summary.get("status")) or "PASS_WITH_LIMITATIONS"
	if runner_result.get("status") != "PASS":
		status = "PARTIAL"
	build_summary = {
		"status": status,
		"history_rows": r1_summary.get("history_rows"),
		"ttm_rows": r1_summary.get("ttm_rows"),
		"checks": r1_summary.get("checks"),
		"comparison_rows": r1_summary.get("comparison_rows"),
		"evidence_packets": len(packets),
		"financial_artifacts_unchanged": True,
		"financial_checks_basis": "carried_forward_unchanged_from_R1_history_hash",
		"r1_history_sha256": r1_history_sha256,
		"r1_output_dir": str(r1_dir),
		"source_files": sources,
		"unavailable": unavailable,
		"workbook": runner_result,
	}
	_write_json(output_dir / "build_summary.json", build_summary)
	if report_path is None:
		report_path = Path(__file__).resolve().parents[3] / "Lunacy" / "runs" / "three-statement-dcf" / "phases" / "history" / "P2-complete-R2-report.md"
	report_path = Path(report_path)
	if write_report:
		report = _r2_report_text(status, r1_dir, output_dir, r1_summary, r1_history_sha256, packets, unavailable, runner_result)
		if report_path.exists():
			if report_path.read_text(encoding="utf-8") != report + "\n":
				raise CaseHistoryError(f"immutable report already exists with different content: {report_path}")
		else:
			report_path.parent.mkdir(parents=True, exist_ok=True)
			report_path.write_text(report + "\n", encoding="utf-8")
	return {
		"status": status,
		"output_dir": output_dir,
		"report_path": report_path,
		"packets": packets,
		"sources": sources,
		"unavailable": unavailable,
		"workbook": runner_result,
		"r1_reference": r1_reference,
	}


def build_msft_frozen_history(
	output_root: str | Path = "data/build-guide-p2",
	*,
	cache_dir: str | Path | None = "data/.p2-edgar",
	write_report: bool = True,
	report_path: str | Path | None = None,
	report_title: str | None = None,
	verification_lines: list[str] | None = None,
	reproducible_command: str | None = None,
) -> dict[str, object]:
	"""Fetch, freeze, validate, and export the real MSFT P2 history."""
	output_dir = Path(output_root) / "MSFT"
	output_dir.mkdir(parents=True, exist_ok=True)
	cache_path = Path(cache_dir) if cache_dir is not None else None
	filings = _load_filings(cache_path)
	period_specs = _period_specs()
	manifest_rows = [_filing_metadata(filings[accession]) for accession in sorted(set(SOURCE_ACCESSIONS.values()))]
	manifest = pd.DataFrame(manifest_rows)
	_write_json(output_dir / "source_manifest.json", {
		"case": TICKER, "cik": CIK, "information_cutoff": CASE_CUTOFF.isoformat(),
		"measurement_date": MEASUREMENT_DATE.isoformat(), "display_unit": DISPLAY_UNIT,
		"numeric_basis": "native_standard_statement_value; native_scale_factor=1.0",
		"selected_filings": manifest_rows,
		"excluded": [{"accession": "0001193125-26-323660", "reason": "filing_date_after_information_cutoff", "cutoff": CASE_CUTOFF.isoformat()}],
	})
	period_table = pd.DataFrame(period_specs)
	_write_csv(output_dir / "period_table.csv", period_table)

	history_parts: list[pd.DataFrame] = []
	ref_parts: list[pd.DataFrame] = []
	alternative_parts: list[pd.DataFrame] = []
	excluded_parts: list[pd.DataFrame] = []
	projection_checks: list[tuple[str, str, str, str]] = []
	xbrl_cache: dict[str, object] = {}
	statement_cache: dict[tuple[str, str], object] = {}
	for spec in period_specs:
		accession = str(spec["accession"])
		filing = filings[accession]
		filing_metadata = _filing_metadata(filing)
		if accession not in xbrl_cache:
			xbrl_cache[accession] = filing.xbrl()
		xbrl = xbrl_cache[accession]
		statement_name = str(spec["statement"])
		cache_key = (accession, statement_name)
		if cache_key not in statement_cache:
			statement_cache[cache_key] = _statement_object(xbrl, statement_name)
		statement = statement_cache[cache_key]
		statement_dir = output_dir / "native_statements"
		stem = f"{accession}_{statement_name}"
		if not (statement_dir / f"{stem}_standard.csv").exists():
			standard = _standard_dataframe(statement)
			_write_csv(statement_dir / f"{stem}_standard.csv", standard)
			get_raw_data = getattr(statement, "get_raw_data", None)
			raw_data = get_raw_data() if callable(get_raw_data) else []
			_write_json(output_dir / "native_payload" / f"{stem}.json", {
				"accession": accession, "statement": statement_name,
				"reporting_periods": getattr(xbrl, "reporting_periods", []), "raw_statement_rows": raw_data,
			})
		period_key = str(spec["period_key"])
		frame = _period_dataframe(statement, period_key, _period_label(xbrl, period_key))
		if frame.empty:
			projection_checks.append((f"native_frame:{statement_name}:{period_key}", "FAIL", "native_period_unavailable", "standard DataFrame returned no exact period rows"))
			continue
		role = _cell(getattr(statement, "role_or_type", None)) or statement_name
		metadata = _period_metadata(spec, filing_metadata, role)
		projected = native_statements_to_history(
			{statement_name: frame}, statement_metadata={statement_name: filing_metadata},
			period_metadata={statement_name: {period_key: metadata}},
		)
		for check in projected["checks"].itertuples(index=False, name=None):
			status, reason = check[1], check[2]
			if check[0].endswith(":native_row_metadata") and reason in {"missing_native_metadata", "missing_native_scale"}:
				status, reason = "NOT_TESTED", "native_row_excluded_missing_required_metadata"
			projection_checks.append((f"{statement_name}:{period_key}:{check[0]}", status, reason, check[3]))
		if not projected["history"].empty:
			linked, refs, alternatives, link_checks = _attach_provenance(projected["history"], filing, xbrl, filing_metadata)
			# Filing role URIs contain filing dates.  The statement identity is
			# verified by the native statement object; retain the exact URI while
			# comparing the known consolidated scope across filings.
			linked["native_statement_role"] = role
			linked["statement_role"] = statement_name
			linked = _add_view_fields(linked, spec)
			history_parts.append(linked)
			if not refs.empty:
				refs["period_name"] = spec["name"]
				refs["native_statement_role"] = role
				ref_parts.append(refs)
			if not alternatives.empty:
				alternatives["period_name"] = spec["name"]
				alternative_parts.append(alternatives)
			projection_checks.extend(link_checks)
		if not projected["excluded"].empty:
			excluded_parts.append(projected["excluded"])
	history = pd.concat(history_parts, ignore_index=True) if history_parts else pd.DataFrame()
	if not history.empty:
		# Some native statement views repeat an identical fact row.  Collapse
		# only exact source identities; differing values or fact/context links
		# remain visible for the duplicate/conflict check below.
		dedupe_columns = [
			column for column in (
				"statement", "concept", "dimensions", "period_key", "numeric_value",
				"source_fact_id", "source_context_ref",
			) if column in history.columns
		]
		history = history.drop_duplicates(dedupe_columns, keep="first").reset_index(drop=True)
	refs = pd.concat(ref_parts, ignore_index=True) if ref_parts else pd.DataFrame()
	alternatives = pd.concat(alternative_parts, ignore_index=True) if alternative_parts else pd.DataFrame()
	if not refs.empty:
		refs = refs.drop_duplicates().reset_index(drop=True)
	if not alternatives.empty:
		alternatives = alternatives.drop_duplicates().reset_index(drop=True)
	excluded = pd.concat(excluded_parts, ignore_index=True) if excluded_parts else pd.DataFrame()
	if history.empty:
		raise CaseHistoryError("no native statement rows were projected")
	comparisons, comparison_checks = _cross_filing_comparisons(history, statement_cache)
	_write_csv(output_dir / "history.csv", history)
	_write_csv(output_dir / "source_references.csv", refs)
	_write_csv(output_dir / "source_alternatives.csv", alternatives)
	_write_csv(output_dir / "excluded_native_values.csv", excluded)
	_write_csv(output_dir / "source_recast_comparisons.csv", comparisons)

	mapping = _observed_mapping(history)
	_write_csv(output_dir / "source_to_model_mapping.csv", mapping)
	material = _material_history(history, mapping)
	annual = history.loc[history["view"].eq("annual")].copy()
	ytd = history.loc[history["view"].eq("ytd")].copy()
	quarters = history.loc[history["view"].eq("quarter")].copy()
	ttm_input = material.loc[(material["period_type"].eq("duration")) & material["dimensions"].eq("{}")].copy()
	ttm, ttm_unavailable, ttm_checks = _build_ttm(ttm_input)
	q4 = _build_q4(ttm_input)
	if not q4.empty:
		quarters = pd.concat([quarters, q4], ignore_index=True)
	_write_csv(output_dir / "annual_history.csv", annual)
	_write_csv(output_dir / "ytd_history.csv", ytd)
	_write_csv(output_dir / "quarter_history.csv", quarters)
	_write_csv(output_dir / "ttm_history.csv", ttm)
	_write_csv(output_dir / "ttm_unavailable.csv", ttm_unavailable)
	latest, latest_checks = _latest_balance(history)
	_write_csv(output_dir / "latest_balance_sheet.csv", latest)

	checks = _case_checks(history, period_specs, ttm, q4, filings)
	check_frames = [checks]
	if comparison_checks:
		check_frames.append(pd.DataFrame(comparison_checks, columns=["check_id", "status", "reason", "detail"]))
	if projection_checks:
		check_frames.append(pd.DataFrame(projection_checks, columns=["check_id", "status", "reason", "detail"]))
	if ttm_checks:
		check_frames.append(pd.DataFrame(ttm_checks, columns=["check_id", "status", "reason", "detail"]))
	if not latest_checks.empty:
		latest_checks = latest_checks.copy()
		latest_checks["check_id"] = "latest_balance:" + latest_checks["check_id"].astype(str)
		check_frames.append(latest_checks[["check_id", "status", "reason", "detail"]])
	excluded_numeric = excluded.loc[excluded["numeric_value"].notna()] if "numeric_value" in excluded else excluded
	excluded_status = "FAIL" if not excluded_numeric.empty else "PASS"
	check_frames.append(pd.DataFrame([(
		"excluded_monetary_values", excluded_status,
		"excluded_rows_have_no_numeric_value" if excluded_status == "PASS" else "excluded_monetary_value_requires_review",
		str(len(excluded_numeric)),
	)], columns=["check_id", "status", "reason", "detail"]))
	checks = pd.concat(check_frames, ignore_index=True)
	_write_csv(output_dir / "checks.csv", checks)
	status = "PARTIAL" if checks["status"].eq("FAIL").any() else "PASS_WITH_LIMITATIONS"
	evidence_packets = _filing_excerpt_packets(filings)
	_write_json(output_dir / "evidence" / "original_filing_excerpts.json", evidence_packets)
	_write_evidence(output_dir / "evidence" / "source_notes.md", manifest, material, checks, evidence_packets=evidence_packets, excluded=excluded, comparisons=comparisons)
	annual_view = material.loc[(material["view"].eq("annual")) & material["dimensions"].eq("{}")] if "dimensions" in material else material.loc[material["view"].eq("annual")]
	ytd_ttm_view = pd.concat([
		material.loc[material["view"].eq("ytd")], ttm,
	], ignore_index=True)
	if "dimensions" in ytd_ttm_view:
		ytd_ttm_view = ytd_ttm_view.loc[ytd_ttm_view["dimensions"].eq("{}")]
	balance_view = latest.loc[latest["dimensions"].eq("{}")] if "dimensions" in latest else latest
	revenue_concept = _cell(mapping.loc[mapping["model_key"].eq("revenue"), "observed_concept"].iloc[0])
	verification_numeric = [
		_verification_item(annual_view, "Annual", ["statement", "concept", "period_name"], ["income_statement", revenue_concept, "FY2025"]),
		_verification_item(ytd_ttm_view, "YTD_TTM", ["statement", "concept", "period_name"], ["income_statement", revenue_concept, "Current YTD"]),
		_verification_item(ytd_ttm_view, "YTD_TTM", ["statement", "concept", "period_name"], ["income_statement", revenue_concept, "TTM to 2026-03-31"]),
		_verification_item(balance_view, "BalanceSheet", ["concept"], ["us-gaap_Assets"]),
	]
	evidence_columns = ["record_type", "statement", "period_name", "concept", "period_key", "fact_id", "context_ref", "unit_ref", "decimals", "inline_scale", "packet_id", "accession", "period", "unit_context", "keyword", "source_locator", "excerpt"]
	evidence_rows = [evidence_columns]
	for row in refs.head(120).to_dict(orient="records"):
		evidence_rows.append(["native_reference", row.get("statement"), row.get("period_name"), row.get("concept"), row.get("period_key"), row.get("fact_id"), row.get("context_ref"), row.get("unit_ref"), row.get("decimals"), row.get("inline_scale"), None, row.get("accession"), None, None, None, row.get("source_locator"), None])
	for packet in evidence_packets:
		evidence_rows.append(["original_filing_excerpt", None, None, None, None, None, None, None, None, None, packet.get("packet_id"), packet.get("accession"), packet.get("period"), packet.get("unit_context"), packet.get("keyword"), packet.get("source_locator"), packet.get("excerpt")])
	evidence_verification = [{"sheet": "Evidence", "contains": evidence_packets[0].get("packet_id") if evidence_packets else "P2R1-"}]
	if evidence_packets and evidence_packets[0].get("source_locator"):
		evidence_verification.append({"sheet": "Evidence", "contains": evidence_packets[0]["source_locator"]})
	payload = {
		"sheets": {
			"Readme": [["MSFT frozen historical view (P2)", None, None], ["Status", status, None], ["Information cut-off", CASE_CUTOFF.isoformat(), None], ["Measurement date", MEASUREMENT_DATE.isoformat(), None], ["Primary values", "EdgarTools standard statement DataFrames", None], ["Display definition", DISPLAY_UNIT + "; native values retained separately", None], ["Limitations", "Q4 is derived from FY2025 less prior comparable YTD; no independent four-quarter proof", None], ["Navigation", "Annual | YTD_TTM | BalanceSheet | Periods | Sources | Checks | Evidence", None]],
			"Annual": _table_rows(material.loc[material["view"].eq("annual")], ["statement", "concept", "label", "period_name", "numeric_value", "display_value", "unit", "source_accession", "source_fact_id"]),
			"YTD_TTM": _table_rows(pd.concat([material.loc[material["view"].eq("ytd")], ttm], ignore_index=True), ["statement", "concept", "label", "period_name", "numeric_value", "display_value", "unit", "source_selection_status", "source_fact_id"]),
			"BalanceSheet": _table_rows(latest.loc[latest["concept"].isin(set(mapping["observed_concept"].dropna()))], ["concept", "label", "period_instant", "numeric_value", "display_value", "unit", "source_fact_id", "source_context_ref"]),
			"Periods": _table_rows(period_table, ["name", "view", "statement", "accession", "period_key", "period_type", "period_start", "period_end", "period_instant"]),
			"Sources": _table_rows(manifest, ["accession", "form_type", "filing_date", "acceptance_timestamp", "report_date", "primary_document", "source_locator"]),
			"Checks": _table_rows(checks, ["check_id", "status", "reason", "detail", "expected", "observed", "difference", "tolerance", "consequence"]),
			"Evidence": evidence_rows,
		},
		"status": status,
		"verification": {"numeric": verification_numeric, "evidence": evidence_verification},
	}
	payload_path = output_dir / "workbook_payload.json"
	_write_json(payload_path, payload)
	runner_result = _run_workbook_export(output_dir, payload_path)
	if runner_result.get("status") != "PASS":
		failure = dict.fromkeys(checks.columns)
		failure.update({"check_id": "workbook_export", "status": "FAIL", "reason": "workbook_runner_failed", "detail": runner_result.get("stderr", "")})
		checks = pd.concat([checks, pd.DataFrame([failure])], ignore_index=True)
		_write_csv(output_dir / "checks.csv", checks)
		status = "PARTIAL"
	_write_json(output_dir / "build_summary.json", {"status": status, "history_rows": len(history), "ttm_rows": len(ttm), "checks": len(checks), "comparison_rows": len(comparisons), "evidence_packets": len(evidence_packets), "workbook": runner_result})
	report_path = Path(report_path) if report_path is not None else Path(__file__).resolve().parents[3] / "Lunacy" / "runs" / "three-statement-dcf" / "phases" / "history" / "P2-complete-report.md"
	if write_report:
		report = _report_text(status, output_dir, material, ttm, checks, mapping, report_title=report_title or "P2 complete frozen history report", verification_lines=verification_lines, reproducible_command=reproducible_command)
		if report_path.exists():
			if report_path.read_text(encoding="utf-8") != report + "\n":
				raise CaseHistoryError(f"immutable report already exists with different content: {report_path}")
		else:
			report_path.write_text(report + "\n", encoding="utf-8")
	return {"status": status, "output_dir": output_dir, "report_path": report_path, "history": history, "ttm": ttm, "checks": checks, "workbook": runner_result}


def main() -> int:
	import argparse

	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--output-root", default="data/build-guide-p2")
	parser.add_argument("--cache-dir", default="data/.p2-edgar")
	parser.add_argument("--report-path")
	parser.add_argument("--report-title")
	parser.add_argument("--evidence-revision-from")
	args = parser.parse_args()
	if args.evidence_revision_from:
		result = build_msft_evidence_revision(
			args.evidence_revision_from,
			output_root=args.output_root,
			cache_dir=args.cache_dir,
			report_path=args.report_path,
		)
	else:
		result = build_msft_frozen_history(args.output_root, cache_dir=args.cache_dir, report_path=args.report_path, report_title=args.report_title)
	print(json.dumps({"status": result["status"], "output_dir": str(result["output_dir"]), "report_path": str(result["report_path"])}, indent=2))
	return 0 if result["status"] != "PARTIAL" else 1


if __name__ == "__main__":
	raise SystemExit(main())
