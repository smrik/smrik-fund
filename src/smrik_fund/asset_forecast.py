"""Bounded P5 evidence, analyst, review, and candidate storage seam.

This module deliberately stops at the external structured decision boundary.
It does not calculate the forecast.  The spreadsheet runner owns formulas and
the linked three-statement model; this module owns source qualification,
method validation, native structured calls, and the serial API ledger.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import time
from datetime import date
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

from smrik_fund.analysis_budget import (
	content_hash,
	record_outcome,
	reservation,
	reserve_call,
)

MODEL = "gpt-5.6-luna"
ENDPOINT_HOST = "api.openai.com"
ENDPOINT_URL = f"https://{ENDPOINT_HOST}/v1/responses"
BASE_URL = f"https://{ENDPOINT_HOST}/v1"
REASONING_EFFORT = "high"
MAX_OUTPUT_TOKENS = 12_000
SCHEMA_VERSION = "p5-asset-proposal-v3"
PROMPT_VERSION = "p5-asset-reasoning-v4"
METHOD_CATALOG_VERSION = "p5-asset-methods-v2"
P5_TASK_ID = "p5-msft-asset-slice"
P5_MAX_ATTEMPTS = 8
P5_MAX_COMMITTED_EUR = 0.75
CASE = "MSFT"
INFORMATION_CUTOFF = "2026-04-30"
MEASUREMENT_DATE = "2026-03-31"


class AssetForecastError(ValueError):
	"""A source, candidate, budget, or structured-call contract failure."""


class AssetParameter(BaseModel):
	"""One application-owned forecast parameter selected by the analyst."""

	model_config = ConfigDict(extra="forbid")

	name: Literal[
		"opening_remaining_life_years",
		"new_addition_useful_life_years",
		"new_addition_timing_fraction",
		"cash_ppe_additions_rate",
		"noncash_ppe_additions_ratio",
		"lease_additions_modeled",
		"tax_rate",
		"revenue_growth",
		"wacc",
		"terminal_growth",
	]
	value: float
	basis: Literal["disclosed", "calculated", "estimated"]
	evidence_refs: list[str]
	rationale: str = Field(min_length=1)
	uncertainty: str = Field(min_length=1)


class AssetSensitivity(BaseModel):
	"""A meaningful bounded scenario description, without formulas or code."""

	model_config = ConfigDict(extra="forbid")

	parameter: Literal[
		"opening_remaining_life_years",
		"new_addition_useful_life_years",
		"cash_ppe_additions_rate",
		"noncash_ppe_additions_ratio",
	]
	low: float
	base: float
	high: float
	interpretation: str = Field(min_length=1)


class AssetProposal(BaseModel):
	"""Native structured analyst result, kept intentionally small and explicit."""

	model_config = ConfigDict(extra="forbid")

	outcome: Literal[
		"propose_forecast", "request_evidence", "capability_gap", "unresolved"
	]
	method_id: str | None
	method_version: str | None
	parameters: list[AssetParameter]
	evidence_refs: list[str]
	rationale: str
	alternatives: list[str]
	uncertainty: list[str]
	sensitivities: list[AssetSensitivity]
	follow_up_request: str | None


class AssetReview(BaseModel):
	"""Native structured system review of one candidate."""

	model_config = ConfigDict(extra="forbid")

	verdict: Literal["accept", "revise", "reject"]
	evidence_strength: Literal["strong", "mixed", "weak"]
	method_valid: bool
	source_valid: bool
	period_valid: bool
	cash_noncash_separated: bool
	depreciation_base_valid: bool
	concerns: list[str] = Field(min_length=1)
	# Keep the field required in the native strict schema while allowing null
	# for accept/reject verdicts. OpenAI strict structured output requires every
	# property to appear in ``required``.
	required_revision: str | None
	target_parameter: Literal[
		"opening_remaining_life_years",
		"cash_ppe_additions_rate",
		"noncash_ppe_additions_ratio",
		"new_addition_useful_life_years",
		"none",
	]
	target_direction: Literal["lower", "higher", "restate", "none"]
	rationale: str = Field(min_length=1)


class EvidencePacket(BaseModel):
	"""A packet-qualified source item passed into the analyst prompt."""

	model_config = ConfigDict(extra="forbid")

	evidence_id: str
	packet_id: str
	kind: Literal["statement", "note", "policy", "calculated"]
	period: str
	unit_context: str
	excerpt: str
	source_file: str
	source_locator: str
	source_sha256: str
	source_url: str | None = None


METHOD_CATALOG: dict[str, dict[str, Any]] = {
	"aggregate_remaining_life_plus_additions": {
		"version": "v2",
		"description": (
			"Keep disclosed opening net PP&E and land separate; depreciate the "
			"opening depreciable aggregate with a bounded remaining-life proxy, "
			"then depreciate cash and noncash recognized additions separately."
		),
		"required_parameters": [
			"opening_remaining_life_years",
			"new_addition_useful_life_years",
			"new_addition_timing_fraction",
			"cash_ppe_additions_rate",
			"noncash_ppe_additions_ratio",
			"lease_additions_modeled",
			"tax_rate",
			"revenue_growth",
			"wacc",
			"terminal_growth",
		],
		"supported_conventions": {
			"opening_assets": "aggregate depreciable net PP&E excluding disclosed land",
			"new_assets": "cash additions plus recognized noncash additions",
			"payables": "period-end PP&E-payable stock is diagnostic only; it is not a period-addition flow",
			"timing": "period fraction multiplied by midpoint timing fraction",
			"land": "held constant and never depreciated",
			"leases": "lease additions modeled as zero pending P8B; finance lease PP&E remains in opening PP&E",
		},
	},
}


def _sha256(path: Path) -> str:
	digest = hashlib.sha256()
	with path.open("rb") as stream:
		for chunk in iter(lambda: stream.read(1024 * 1024), b""):
			digest.update(chunk)
	return digest.hexdigest()


def _json_write(path: Path, value: Any) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(
		json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
		encoding="utf-8",
	)


def _json_read(path: Path) -> Any:
	return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> list[dict[str, str]]:
	with path.open(newline="", encoding="utf-8-sig") as stream:
		return list(csv.DictReader(stream))


def _csv_fact(
	path: Path, concept: str, period_name: str | None = None
) -> dict[str, Any]:
	matches = [row for row in _read_csv(path) if row.get("concept") == concept]
	if period_name is not None:
		matches = [row for row in matches if row.get("period_name") == period_name]
	if not matches:
		raise AssetForecastError(
			f"Required source fact is unavailable: {concept} / {period_name or 'any period'}"
		)
	row = matches[0]
	display = row.get("display_value", "")
	if display in ("", "nan", "NaN"):
		raise AssetForecastError(
			f"Required source fact has no reported value: {concept}"
		)
	return {
		"concept": concept,
		"label": row.get("label"),
		"value": float(display),
		"native_value": float(row["numeric_value"])
		if row.get("numeric_value") not in (None, "", "nan")
		else None,
		"unit": row.get("unit"),
		"period": row.get("period_name"),
		"period_key": row.get("period_key"),
		"source_fact_id": row.get("source_fact_id"),
		"source_locator": row.get("source_locator"),
		"source_accession": row.get("source_accession") or row.get("accession"),
		"source_selection_status": row.get("source_selection_status"),
		"numeric_basis": row.get("numeric_basis"),
	}


def _packet_by_keyword(
	packets: list[dict[str, Any]], accession: str, keyword: str
) -> dict[str, Any]:
	for packet in packets:
		if packet.get("accession") == accession and packet.get("keyword") == keyword:
			return packet
	raise AssetForecastError(f"Missing evidence packet: {accession} / {keyword}")


def _number_after(text: str, label: str, *, occurrence: int = 0) -> float:
	matches = re.findall(rf"{re.escape(label)}[^0-9]*([0-9][0-9,]*)", text, flags=re.I)
	if len(matches) <= occurrence:
		raise AssetForecastError(f"Could not parse disclosed asset note value: {label}")
	return float(matches[occurrence].replace(",", ""))


def _decimal_numbers_after(text: str, label: str) -> list[float]:
	"""Read disclosed decimal amounts without changing their source units."""
	match = re.search(re.escape(label), text, flags=re.I)
	if match is None:
		raise AssetForecastError(f"Could not parse disclosed asset note value: {label}")
	tail = text[match.end() :]
	tail = re.split(r"\bAs of\b", tail, maxsplit=1, flags=re.I)[0]
	matches = re.findall(r"\$\s*([0-9][0-9,]*(?:\.[0-9]+)?)", tail)
	if not matches:
		raise AssetForecastError(f"Could not parse disclosed asset note value: {label}")
	return [float(value.replace(",", "")) for value in matches]


def _policy_packet(
	path: Path, start: int, end: int, packet_id: str, evidence_id: str, period: str
) -> EvidencePacket:
	lines = path.read_text(encoding="utf-8").splitlines()
	if start < 1 or end > len(lines) or start > end:
		raise AssetForecastError(f"Invalid source line range for {packet_id}")
	excerpt = "\n".join(lines[start - 1 : end])
	return EvidencePacket(
		evidence_id=evidence_id,
		packet_id=packet_id,
		kind="policy",
		period=period,
		unit_context="Narrative accounting policy; no numeric unit unless stated",
		excerpt=excerpt,
		source_file=str(path).replace("\\", "/"),
		source_locator=f"{path.as_posix()}#line={start}-{end}",
		source_sha256=_sha256(path),
		source_url="https://www.sec.gov/Archives/edgar/data/789019/000095017025100235/msft-20250630.htm",
	)


def build_evidence_packet(
	p2_root: Path,
	legacy_source: Path,
) -> dict[str, Any]:
	"""Build the fixed packet and facts used by every analyst/reviewer call."""

	excerpts_path = p2_root / "evidence" / "original_filing_excerpts.json"
	source_manifest_path = p2_root / "source_manifest.json"
	frozen_path = (
		p2_root.parent.parent / "build-guide-p3-frozen" / "MSFT" / "frozen_case.json"
	)
	excerpts = _json_read(excerpts_path)
	packets = excerpts["packets"]
	latest_accession = "0001193125-26-191507"
	annual_accession = "0000950170-25-100235"
	selected = [
		(
			"E1",
			"latest_property_and_equipment_note",
			"note",
			latest_accession,
			"property_and_equipment_note",
		),
		(
			"E2",
			"latest_balance_sheet",
			"statement",
			latest_accession,
			"balance_sheet_table",
		),
		("E3", "latest_cash_flow", "statement", latest_accession, "cash_flow_table"),
		(
			"E4",
			"fy25_property_and_equipment_note",
			"note",
			annual_accession,
			"property_and_equipment_note",
		),
		("E5", "fy25_cash_flow", "statement", annual_accession, "cash_flow_table"),
	]
	evidence: list[EvidencePacket] = []
	for evidence_id, _name, kind, accession, keyword in selected:
		packet = _packet_by_keyword(packets, accession, keyword)
		evidence.append(
			EvidencePacket(
				evidence_id=evidence_id,
				packet_id=packet["packet_id"],
				kind=kind,  # type: ignore[arg-type]
				period=packet["period"],
				unit_context=packet["unit_context"],
				excerpt=packet["excerpt"],
				source_file=packet["source_file"],
				source_locator=packet["source_locator"],
				source_sha256=packet["source_sha256"],
				source_url=packet["sec_locator"],
			)
		)
	evidence.append(
		_policy_packet(
			legacy_source,
			1934,
			1938,
			"P5-POLICY-0000950170-25-100235-property-useful-life",
			"E6",
			"FY2025 policy",
		)
	)
	evidence.append(
		_policy_packet(
			legacy_source,
			2553,
			2588,
			"P5-POLICY-0000950170-25-100235-lease-note",
			"E7",
			"FY2025 lease note",
		)
	)

	latest_note = next(item for item in evidence if item.evidence_id == "E1").excerpt
	gross = _number_after(latest_note, "Total, at cost")
	accumulated = _number_after(latest_note, "Accumulated depreciation")
	net = _number_after(latest_note, "Total, net")
	land = _number_after(latest_note, "Land")
	if gross - accumulated != net:
		raise AssetForecastError(
			"Latest PP&E gross less accumulated depreciation does not reconcile to net"
		)
	lease_note = next(item for item in evidence if item.evidence_id == "E7").excerpt
	finance_lease_net = _number_after(lease_note, "Property and equipment, net")
	latest_bs = p2_root / "latest_balance_sheet.csv"
	ttm = p2_root / "ttm_history.csv"
	annual = p2_root / "annual_history.csv"
	ytd = p2_root / "ytd_history.csv"
	balance_facts = {
		key: _csv_fact(latest_bs, concept)
		for key, concept in {
			"cash": "us-gaap_CashAndCashEquivalentsAtCarryingValue",
			"short_term_investments": "us-gaap_ShortTermInvestments",
			"accounts_receivable": "us-gaap_AccountsReceivableNetCurrent",
			"inventory": "us-gaap_InventoryNet",
			"other_current_assets": "us-gaap_OtherAssetsCurrent",
			"operating_lease_rou": "us-gaap_OperatingLeaseRightOfUseAsset",
			"long_term_investments": "us-gaap_LongTermInvestments",
			"goodwill": "us-gaap_Goodwill",
			"intangibles": "us-gaap_FiniteLivedIntangibleAssetsNet",
			"other_noncurrent_assets": "us-gaap_OtherAssetsNoncurrent",
			"total_assets": "us-gaap_Assets",
			"accounts_payable": "us-gaap_AccountsPayableCurrent",
			"short_term_debt": "us-gaap_LongTermDebtCurrent",
			"accrued_liabilities": "us-gaap_EmployeeRelatedLiabilitiesCurrent",
			"short_term_taxes": "us-gaap_AccruedIncomeTaxesCurrent",
			"short_term_unearned_revenue": "us-gaap_ContractWithCustomerLiabilityCurrent",
			"other_current_liabilities": "us-gaap_OtherLiabilitiesCurrent",
			"long_term_debt": "us-gaap_LongTermDebtNoncurrent",
			"long_term_taxes": "us-gaap_AccruedIncomeTaxesNoncurrent",
			"long_term_unearned_revenue": "us-gaap_ContractWithCustomerLiabilityNoncurrent",
			"deferred_taxes": "us-gaap_DeferredIncomeTaxLiabilitiesNet",
			"operating_lease_liabilities": "us-gaap_OperatingLeaseLiabilityNoncurrent",
			"other_noncurrent_liabilities": "us-gaap_OtherLiabilitiesNoncurrent",
			"total_liabilities": "us-gaap_Liabilities",
			"total_equity": "us-gaap_StockholdersEquity",
		}.items()
	}
	ttm_facts = {
		key: _csv_fact(ttm, concept, "TTM to 2026-03-31")
		for key, concept in {
			"revenue": "us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax",
			"operating_income": "us-gaap_OperatingIncomeLoss",
			"pretax_income": "us-gaap_IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
			"tax_expense": "us-gaap_IncomeTaxExpenseBenefit",
			"net_income": "us-gaap_NetIncomeLoss",
			"dna_other": "msft_DepreciationAmortizationAndOther",
			"cash_ppe_payments": "us-gaap_PaymentsToAcquirePropertyPlantAndEquipment",
		}.items()
	}
	annual_facts = {
		key: _csv_fact(annual, concept, "FY2025")
		for key, concept in {
			"revenue": "us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax",
			"operating_income": "us-gaap_OperatingIncomeLoss",
			"dna_other": "msft_DepreciationAmortizationAndOther",
			"cash_ppe_payments": "us-gaap_PaymentsToAcquirePropertyPlantAndEquipment",
		}.items()
	}
	ytd_facts = {
		key: _csv_fact(ytd, concept, "Current YTD")
		for key, concept in {
			"cash_ppe_payments": "us-gaap_PaymentsToAcquirePropertyPlantAndEquipment",
			"dna_other": "msft_DepreciationAmortizationAndOther",
		}.items()
	}
	ppe_payables = {
		"latest_2026_03_31": 22_600.0,
		"fy2025_06_30": 6_900.0,
		"basis": (
			"disclosed in E1 and E4 as period-end PP&E purchases remaining in "
			"accounts payable; stock measures, not period additions"
		),
		"measurement_type": "period_end_stock",
		"evidence_refs": ["E1", "E4"],
	}
	calculated = {
		"opening_depreciable_net_ppe": net - land,
		"opening_total_net_ppe": net,
		"ttm_ebit_margin": ttm_facts["operating_income"]["value"]
		/ ttm_facts["revenue"]["value"],
		"ttm_tax_rate": ttm_facts["tax_expense"]["value"]
		/ ttm_facts["pretax_income"]["value"],
		"ttm_cash_ppe_rate": ttm_facts["cash_ppe_payments"]["value"]
		/ ttm_facts["revenue"]["value"],
		"fy25_ppe_payable_stock_to_cash_flow_ratio": ppe_payables["fy2025_06_30"]
		/ annual_facts["cash_ppe_payments"]["value"],
		"q3_ppe_payable_stock_to_ytd_cash_flow_ratio": ppe_payables["latest_2026_03_31"]
		/ ytd_facts["cash_ppe_payments"]["value"],
	}
	current_dep = _decimal_numbers_after(latest_note, "Depreciation expense was")
	annual_dep = _decimal_numbers_after(
		next(item for item in evidence if item.evidence_id == "E4").excerpt,
		"depreciation expense was",
	)
	if len(current_dep) < 4 or not annual_dep:
		raise AssetForecastError(
			"PP&E depreciation disclosure does not contain the required comparative periods"
		)
	# Disclosures are in USD billions.  This is a supported historical PP&E
	# depreciation amount used only to keep forecast operating-cost treatment
	# explicit; it is not a forecast age-profile allocation.
	calculated["ttm_ppe_depreciation"] = (
		annual_dep[0] + current_dep[1] - current_dep[3]
	) * 1000.0
	calculated["ttm_ppe_depreciation_basis"] = (
		"FY2025 annual PP&E depreciation + FY2026 nine-month PP&E depreciation "
		"- FY2025 comparative nine-month PP&E depreciation; USD millions"
	)
	calculated["ttm_ppe_depreciation_scope"] = (
		"PP&E depreciation disclosure only; lease-term/amortization components and "
		"other D&A/SBC remain embedded pending P6-P8"
	)
	# This packet is itself persisted and hashable; it is not an unqualified path
	# retrieval interface.  Include source hashes and frozen case identity.
	frozen = _json_read(frozen_path)
	manifest = _json_read(source_manifest_path)
	return {
		"schema_version": SCHEMA_VERSION,
		"case": CASE,
		"information_cutoff": manifest["information_cutoff"],
		"measurement_date": manifest["measurement_date"],
		"frozen_case_snapshot_id": frozen["case_snapshot_id"],
		"frozen_case_snapshot_sha256": frozen["case_snapshot_sha256"],
		"evidence": [item.model_dump(mode="json") for item in evidence],
		"facts": {
			"opening_balance_sheet": balance_facts,
			"ttm": ttm_facts,
			"annual": annual_facts,
			"ytd": ytd_facts,
			"ppe_note": {
				"gross": gross,
				"accumulated_depreciation": accumulated,
				"net": net,
				"land": land,
				"finance_lease_net_included_in_ppe": finance_lease_net,
			},
			"ppe_payables": ppe_payables,
			"calculated": calculated,
		},
		"unavailable": [
			"opening asset age profile by category",
			"category-level net PP&E after accumulated depreciation",
			"exact future PP&E mix and useful-life distribution",
			"complete separation of other embedded operating costs from PP&E depreciation (P6-P8)",
			"current restricted-cash balance",
			"final finance/operating lease valuation policy (P8B)",
		],
		"allowlisted_followups": [
			"useful_life_policy",
			"lease_treatment",
			"noncash_ppe_payables",
		],
	}


def _evidence_map(packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
	return {item["evidence_id"]: item for item in packet["evidence"]}


def expand_evidence(packet: dict[str, Any], request: str) -> dict[str, Any]:
	"""Expand only one of the real, packet-qualified follow-up topics."""

	allowlisted = {
		"useful_life_policy": {"evidence_ids": ["E6"]},
		"lease_treatment": {"evidence_ids": ["E6", "E7"]},
		"noncash_ppe_payables": {"evidence_ids": ["E1", "E4", "E5"]},
	}
	if request not in allowlisted:
		raise AssetForecastError(
			f"Follow-up request is outside the allowlist: {request}"
		)
	items = [
		_evidence_map(packet)[item] for item in allowlisted[request]["evidence_ids"]
	]
	return {
		"request": request,
		"status": "fulfilled",
		"evidence": items,
		"source_hashes": sorted({item["source_sha256"] for item in items}),
	}


def _parameter_map(candidate: AssetProposal) -> dict[str, AssetParameter]:
	result = {item.name: item for item in candidate.parameters}
	if len(result) != len(candidate.parameters):
		raise AssetForecastError("Candidate repeats a forecast parameter")
	return result


def _development_parameters(packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
	"""Fixed context for the asset experiment, not analyst-selected financial facts."""
	rows = {
		"lease_additions_modeled": (
			0.0, "estimated", ["E6"],
			"Application assumption: future lease additions excluded from this P5 slice.",
			"P8B must replace the exclusion with a complete lease policy.",
		),
		"tax_rate": (
			packet["facts"]["calculated"]["ttm_tax_rate"], "calculated", ["E3", "E5"],
			"Application uses the historical TTM effective tax rate for this experiment.",
			"The historical rate is a temporary forecast convention pending P8A.",
		),
		"revenue_growth": (
			0.08, "estimated", [],
			"Application-supplied annual growth assumption for the P5 development comparison.",
			"Not a sourced MSFT forecast; replace in P6.",
		),
		"wacc": (
			0.08, "estimated", [],
			"Application-supplied discount rate for the P5 development comparison.",
			"Not a sourced market WACC; replace in P9.",
		),
		"terminal_growth": (
			0.02, "estimated", [],
			"Application-supplied terminal growth for the P5 development comparison.",
			"Not an adopted terminal policy; replace in P9.",
		),
	}
	return {
		name: dict(zip(("value", "basis", "evidence_refs", "rationale", "uncertainty"), values, strict=True))
		for name, values in rows.items()
	}


def validate_proposal(
	candidate: AssetProposal, packet: dict[str, Any]
) -> AssetProposal:
	"""Reject unsupported methods, missing source refs, and unsafe parameters."""

	if candidate.outcome != "propose_forecast":
		raise AssetForecastError(
			f"Candidate outcome is not a forecast proposal: {candidate.outcome}"
		)
	method = METHOD_CATALOG.get(candidate.method_id)
	if method is None or candidate.method_version != method["version"]:
		raise AssetForecastError(
			f"Unsupported asset method/version: {candidate.method_id}/{candidate.method_version}"
		)
	evidence_ids = set(_evidence_map(packet))
	if not set(candidate.evidence_refs).issubset(evidence_ids):
		raise AssetForecastError("Candidate cites an unknown evidence packet")
	params = _parameter_map(candidate)
	required = set(method["required_parameters"])
	if set(params) != required:
		raise AssetForecastError(
			f"Candidate parameter set mismatch: expected {sorted(required)}, got {sorted(params)}"
		)
	if params["lease_additions_modeled"].value != 0:
		raise AssetForecastError("P5 cannot model lease additions before P8B")
	provided = _development_parameters(packet)
	for name, expected in provided.items():
		actual = params[name]
		if (actual.value, actual.basis, actual.evidence_refs) != (
			expected["value"], expected["basis"], expected["evidence_refs"]
		):
			raise AssetForecastError(f"Application-supplied development parameter changed: {name}")
	noncash = params["noncash_ppe_additions_ratio"]
	if noncash.basis != "estimated":
		raise AssetForecastError(
			"Noncash PP&E additions must remain an estimate; period-end payable stock "
			"does not disclose a period-addition flow"
		)
	if not any(
		marker in noncash.rationale.lower()
		for marker in ("stock", "period-end", "period end")
	):
		raise AssetForecastError(
			"Noncash PP&E rationale must state the period-end stock limitation"
		)
	for parameter in params.values():
		if parameter.name not in provided and not parameter.evidence_refs:
			raise AssetForecastError(f"Asset estimate lacks supporting context: {parameter.name}")
		if (
			not isinstance(parameter.value, (int, float))
			or not math.isfinite(float(parameter.value))
		):
			raise AssetForecastError(
				f"Parameter is not a finite number: {parameter.name}"
			)
		if not set(parameter.evidence_refs).issubset(evidence_ids):
			raise AssetForecastError(
				f"Parameter {parameter.name} cites an unknown evidence packet"
			)
		if any(
			token in parameter.rationale.lower()
			for token in ("=", "formula", "python", "javascript", "code")
		):
			raise AssetForecastError(
				f"Parameter {parameter.name} contains runtime instructions"
			)
	ranges = {
		"opening_remaining_life_years": (1.0, 20.0),
		"new_addition_useful_life_years": (1.0, 20.0),
		"new_addition_timing_fraction": (0.0, 1.0),
		"cash_ppe_additions_rate": (0.0, 2.0),
		"noncash_ppe_additions_ratio": (0.0, 1.0),
		"lease_additions_modeled": (0.0, 0.0),
		"tax_rate": (0.0, 1.0),
		"revenue_growth": (-0.5, 0.5),
		"wacc": (0.001, 0.5),
		"terminal_growth": (0.0, 0.2),
	}
	for name, (lower, upper) in ranges.items():
		value = float(params[name].value)
		if value < lower or value > upper:
			raise AssetForecastError(
				f"Parameter {name} outside supported range [{lower}, {upper}]"
			)
	if params["terminal_growth"].value >= params["wacc"].value:
		raise AssetForecastError("terminal_growth must be below wacc")
	ppe = packet["facts"]["ppe_note"]
	if ppe["net"] - ppe["land"] <= 0 or ppe["land"] < 0:
		raise AssetForecastError("Opening PP&E base/land source validation failed")
	# E2 supplies the model's balance-sheet context; it need not be cited as
	# evidence for an asset-life/investment assumption that does not use it.
	required_source = {"E1", "E3", "E4", "E5", "E6"}
	if not required_source.issubset(set(candidate.evidence_refs)):
		raise AssetForecastError(
			"Candidate omitted a required latest PP&E/statement/policy packet"
		)
	if not candidate.sensitivities:
		raise AssetForecastError("Candidate must include a meaningful sensitivity")
	if (
		candidate.follow_up_request is not None
		and candidate.follow_up_request not in packet["allowlisted_followups"]
	):
		raise AssetForecastError("Candidate follow-up request is outside the allowlist")
	for sensitivity in candidate.sensitivities:
		if not sensitivity.low <= sensitivity.base <= sensitivity.high:
			raise AssetForecastError(
				f"Sensitivity is not ordered: {sensitivity.parameter}"
			)
		if sensitivity.base != params[sensitivity.parameter].value:
			raise AssetForecastError(f"Sensitivity base differs from selected parameter: {sensitivity.parameter}")
		lower, upper = ranges[sensitivity.parameter]
		if sensitivity.low < lower or sensitivity.high > upper:
			raise AssetForecastError(f"Sensitivity exceeds supported method range: {sensitivity.parameter}")
		if sensitivity.low == sensitivity.high:
			raise AssetForecastError(f"Sensitivity has no variation: {sensitivity.parameter}")
	return candidate


def validate_analyst_outcome(
	candidate: AssetProposal, packet: dict[str, Any]
) -> AssetProposal:
	"""Validate an analyst result without treating evidence requests as proposals."""
	if candidate.outcome == "propose_forecast":
		return validate_proposal(candidate, packet)
	if candidate.outcome == "request_evidence":
		if candidate.follow_up_request not in packet["allowlisted_followups"]:
			raise AssetForecastError(
				"Analyst evidence request is outside the packet follow-up allowlist"
			)
		if not candidate.rationale or not candidate.uncertainty:
			raise AssetForecastError(
				"Analyst evidence request must explain the gap and uncertainty"
			)
		if not set(candidate.evidence_refs).issubset(set(_evidence_map(packet))):
			raise AssetForecastError("Analyst evidence request cites an unknown packet")
		return candidate
	if candidate.outcome in {"capability_gap", "unresolved"}:
		if candidate.follow_up_request is not None:
			raise AssetForecastError(
				"Capability-gap and unresolved outcomes cannot hide a follow-up request"
			)
		if not candidate.rationale or not candidate.uncertainty:
			raise AssetForecastError(
				f"Analyst {candidate.outcome} outcome must explain the limitation"
			)
		if not set(candidate.evidence_refs).issubset(set(_evidence_map(packet))):
			raise AssetForecastError("Analyst outcome cites an unknown packet")
		return candidate
	raise AssetForecastError(f"Unsupported analyst outcome: {candidate.outcome}")


def proposal_schema() -> dict[str, Any]:
	return AssetProposal.model_json_schema()


def _prompt(instruction: str) -> str:
	return f"""You are the MSFT P5 real-assets analyst at a structured financial-analysis boundary.
The application, not you, owns source retrieval, formula execution, and validation.
Return only the requested native structured object. Never return code, formulas, paths,
tool calls, or an invented category age profile.

Case: {CASE}; information cutoff: {INFORMATION_CUTOFF}; measurement date: {MEASUREMENT_DATE}.
Display units: USD millions. Forecast shape: Apr-Jun FY2026 stub followed by FY2027-FY2036.
The frozen evidence packet is authoritative for facts. Sourced facts and asset estimates
must cite their packet-qualified E# context. Distinguish disclosed/calculated/estimated
bases. Keep cash PP&E payments, accounts-payable PP&E purchases, and lease additions
	separate. Accounts-payable PP&E purchases are period-end stock observations, not
	period-addition flows, so do not turn their stock-to-cash ratios into a disclosed
	noncash-addition rate. Finance-lease PP&E already sits inside opening consolidated
	PP&E. Lease additions must be zero in P5 pending P8B. A proposal is system-reviewed
	provisional, never human approved.
	The packet's supported historical PP&E depreciation is a baseline only; remaining
	operating costs are a visible temporary assumption pending P6.

Implemented method catalog version: {METHOD_CATALOG_VERSION}.
Supported method IDs are: {", ".join(METHOD_CATALOG)}.
Required parameter names are exactly: {", ".join(METHOD_CATALOG["aggregate_remaining_life_plus_additions"]["required_parameters"])}.
Use bounded numeric estimates only where the packet supports a clearly labeled proxy;
do not claim that a disclosure provides an exact remaining life or future asset mix.
Asset uncertainty can be represented by an explicitly estimated aggregate life or
noncash-addition scenario and sensitivity; it need not be a disclosed point estimate.
The noncash scenario is a temporary financing assumption, never a flow derived from
the period-end payable stock. Explain any material inadequacy of that convention.
The payload supplies fixed development parameters for revenue, tax, leases, WACC and
terminal growth. Copy their values, bases and references unchanged. Their unsourced
values are application assumptions, not missing facts for you to invent or cite to a
filing. Empty references are required for those unsourced assumptions. Explain that
P6/P8/P9 will replace them. Assess assets conditional on this supplied context; retain
capability_gap/unresolved when an actual asset-method or evidence gap prevents it.
Use the chosen method's own version, not the catalog version, in method_version.

Task:
{instruction}
"""


def _call_request(
	system_prompt: str,
	payload: dict[str, Any],
	*,
	response_model: type[BaseModel] = AssetProposal,
	schema_name: str | None = None,
) -> dict[str, Any]:
	"""Build the exact request body passed to ``responses.create``.

	The persisted body and the dispatched body are deliberately the same object;
	there is no second SDK-specific reconstruction after admission.
	"""
	input_text = json.dumps(
		payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
	)
	name = schema_name or (
		"asset_review" if response_model is AssetReview else "asset_proposal"
	)
	return {
		"model": MODEL,
		"reasoning": {"effort": REASONING_EFFORT},
		"service_tier": "default",
		"input": input_text,
		"instructions": system_prompt,
		"text": {
			"format": {
				"type": "json_schema",
				"name": name,
				"strict": True,
				"schema": response_model.model_json_schema(),
			}
		},
		"max_output_tokens": MAX_OUTPUT_TOKENS,
		"tools": [],
		"background": False,
	}


def _safe_model_dump(value: Any) -> Any:
	if value is None:
		return None
	try:
		return value.model_dump(mode="json")
	except (AttributeError, TypeError, ValueError):
		try:
			return json.loads(value.model_dump_json())
		except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
			return {"repr": repr(value)}


def _usage_dict(response: Any) -> dict[str, Any] | None:
	usage = getattr(response, "usage", None)
	value = _safe_model_dump(usage)
	if not isinstance(value, dict):
		return None
	if not all(
		key in value for key in ("input_tokens", "output_tokens", "total_tokens")
	):
		return None
	return value


def _ledger_p5_state(budget_path: Path) -> tuple[int, float]:
	state = _json_read(budget_path)
	calls = [
		item
		for item in state.get("calls", [])
		if item.get("task_id", "").startswith(P5_TASK_ID)
	]
	total = sum(
		item.get("cost", {}).get("priced_eur", item.get("reserved_eur", 0.0))
		for item in calls
	)
	return len(calls), float(total)


def _response_value(response: Any) -> Any:
	"""Extract structured content without validating it before persistence."""
	raw = response if isinstance(response, dict) else None
	parsed = getattr(response, "output_parsed", None)
	if parsed is not None:
		return parsed
	output_text = getattr(response, "output_text", None)
	if isinstance(output_text, str) and output_text.strip():
		return output_text
	if raw is None:
		raw = _safe_model_dump(response)
	if not isinstance(raw, dict):
		return None
	if raw.get("output_parsed") is not None:
		return raw["output_parsed"]
	if isinstance(raw.get("output_text"), str) and raw["output_text"].strip():
		return raw["output_text"]
	for item in raw.get("output") or []:
		for content in item.get("content") or []:
			if isinstance(content, dict):
				if isinstance(content.get("text"), str) and content["text"].strip():
					return content["text"]
				if content.get("parsed") is not None:
					return content["parsed"]
	return None


def _parse_structured_response(response: Any, response_model: type[BaseModel]) -> BaseModel:
	value = _response_value(response)
	if isinstance(value, response_model):
		return value
	if isinstance(value, str):
		return response_model.model_validate_json(value)
	if isinstance(value, dict):
		return response_model.model_validate(value)
	raise AssetForecastError("Provider response contained no structured output")


def _prior_stage_result(
	attempts_dir: Path,
	stage: str,
	request_hash: str,
	response_model: type[BaseModel],
	budget_path: Path,
) -> tuple[BaseModel, dict[str, Any]] | None:
	"""Resume a matching completed stage or hold its unsettled outcome."""
	ledger = _json_read(budget_path)
	ledger_matches = [
		call
		for call in ledger.get("calls", [])
		if call.get("task_id") == P5_TASK_ID
		and call.get("request_hash") == request_hash
		and call.get("call_id", "").endswith(f"-{stage}")
	]
	for matching_ledger in ledger_matches:
		if matching_ledger.get("status") in {"reserved", "usage_unknown"}:
			raise AssetForecastError(
				f"{stage} has a held ledger admission "
				f"({matching_ledger.get('status')}); no duplicate dispatch is allowed"
			)
	for request_path in sorted(attempts_dir.glob(f"*-{stage}.request.json")):
		try:
			request = _json_read(request_path)
		except (OSError, json.JSONDecodeError):
			continue
		if content_hash(request) != request_hash:
			continue
		prefix = request_path.name[: -len(".request.json")]
		outcome_path = attempts_dir / f"{prefix}.outcome.json"
		outcome = _json_read(outcome_path) if outcome_path.exists() else {}
		status = outcome.get("status")
		if ledger_matches and any(
			call.get("status") != "completed" for call in ledger_matches
		):
			raise AssetForecastError(
				f"{stage} has an unsettled ledger admission; no duplicate dispatch is allowed"
			)
		if ledger_matches and status != "completed":
			raise AssetForecastError(
				f"{stage} has a completed ledger admission without a local completed "
				"outcome; the stage is held to prevent duplicate dispatch"
			)
		if status in {"reserved", "usage_unknown"}:
			raise AssetForecastError(
				f"{stage} has a held prior {status} outcome; no duplicate dispatch is allowed"
			)
		if status != "completed":
			continue
		structured_path = attempts_dir / f"{prefix}.structured.json"
		metadata_path = attempts_dir / f"{prefix}.metadata.json"
		if structured_path.exists():
			value = response_model.model_validate(_json_read(structured_path))
		else:
			response_path = attempts_dir / f"{prefix}.response.json"
			if not response_path.exists():
				raise AssetForecastError(
					f"{stage} completed without a persisted raw response; result is held"
				)
			raw = _json_read(response_path)
			try:
				value = _parse_structured_response(raw, response_model)
			except Exception as exc:
				raise AssetForecastError(
					f"{stage} completed output cannot be resumed: {exc}"
				) from exc
			_json_write(structured_path, value.model_dump(mode="json"))
		metadata = _json_read(metadata_path) if metadata_path.exists() else {}
		metadata["resumed"] = True
		return value, metadata
	if ledger_matches:
		raise AssetForecastError(
			f"{stage} has a prior ledger admission without resumable local artifacts; "
			"the stage is held to prevent duplicate dispatch"
		)
	return None


def _dispatch_structured(
	*,
	stage: str,
	run_dir: Path,
	budget_path: Path,
	system_prompt: str,
	payload: dict[str, Any],
	response_model: type[BaseModel],
	client: Any | None = None,
) -> tuple[BaseModel, dict[str, Any]]:
	"""Admit once, dispatch once, persist raw/usage, then validate structured data."""
	request = _call_request(
		system_prompt, payload, response_model=response_model
	)
	request_hash = content_hash(request)
	attempts_dir = run_dir / "attempts"
	attempts_dir.mkdir(parents=True, exist_ok=True)
	prior = _prior_stage_result(
		attempts_dir, stage, request_hash, response_model, budget_path
	)
	if prior is not None:
		return prior
	ordinal, committed = _ledger_p5_state(budget_path)
	if ordinal >= P5_MAX_ATTEMPTS:
		raise AssetForecastError("P5 dispatched-attempt cap reached")
	today = date.today()
	prices = _json_read(budget_path)["prices"]
	reserved_estimate = reservation(request, prices, today=today)["reserved_eur"]
	if committed + reserved_estimate > P5_MAX_COMMITTED_EUR:
		raise AssetForecastError("P5 committed/reserved allowance would exceed EUR0.75")
	call_id = f"{P5_TASK_ID}-{ordinal + 1:02d}-{stage}"
	prefix = f"{ordinal + 1:02d}-{stage}"
	_json_write(attempts_dir / f"{prefix}.request.json", request)
	reserved = reserve_call(
		budget_path,
		call_id=call_id,
		task_id=P5_TASK_ID,
		request=request,
		endpoint_host=ENDPOINT_HOST,
		final_review=False,
		today=today,
	)
	_json_write(attempts_dir / f"{prefix}.reservation.json", reserved)
	if client is None:
		load_dotenv()
		from openai import OpenAI

		client = OpenAI(max_retries=0, base_url=BASE_URL)
	started = time.perf_counter()
	response = None
	error: Exception | None = None
	try:
		# Dispatch the exact admitted request.  Do not rebuild a reduced SDK body.
		response = client.responses.create(**request)
	except Exception as exc:  # preserve unknown-use failure in the ledger
		error = exc
	elapsed = time.perf_counter() - started
	response_id = getattr(response, "id", None)
	returned_model = getattr(response, "model", None)
	raw = _safe_model_dump(response) if response is not None else {"response": None}
	if error is not None:
		raw = {"error_type": type(error).__name__, "error": str(error), "response": raw}
	_json_write(attempts_dir / f"{prefix}.response.json", raw)
	usage = _usage_dict(response) if response is not None else None
	try:
		outcome = record_outcome(
			budget_path,
			call_id=call_id,
			usage=usage,
			elapsed_seconds=elapsed,
			response_id=response_id,
			returned_model=returned_model,
		)
	except Exception as exc:
		# The reservation stays held when usage is malformed or provider metadata
		# is not usable; no hidden retry is safe.
		_json_write(
			attempts_dir / f"{prefix}.outcome-error.json",
			{"error_type": type(exc).__name__, "error": str(exc)},
		)
		outcome = record_outcome(
			budget_path,
			call_id=call_id,
			usage=None,
			elapsed_seconds=elapsed,
			response_id=response_id,
			returned_model=returned_model,
		)
		if error is None:
			error = AssetForecastError(
				f"{stage} usage could not be recorded after admission: {exc}"
			)
	_json_write(attempts_dir / f"{prefix}.outcome.json", outcome)
	metadata = {
		"call_id": call_id,
		"stage": stage,
		"endpoint": ENDPOINT_URL,
		"request_hash": request_hash,
		"stage_context_hash": content_hash({"stage": stage, "request": request}),
		"response_id": response_id,
		"returned_model": returned_model,
		"usage": usage,
		"elapsed_seconds": elapsed,
		"status": outcome["status"],
		"instruction_hash": content_hash(system_prompt),
		"payload_hash": content_hash(payload),
		"schema_hash": content_hash(request["text"]["format"]["schema"]),
		"model": request["model"],
		"reasoning": request["reasoning"],
		"service_tier": request["service_tier"],
		"max_retries": 0,
		"method_catalog_version": payload.get("contract", {}).get(
			"method_catalog_version"
		),
		"source_packet_hash": content_hash(payload["packet"])
		if isinstance(payload.get("packet"), dict)
		else None,
	}
	_json_write(attempts_dir / f"{prefix}.metadata.json", metadata)
	if error is not None:
		raise AssetForecastError(
			f"{stage} provider call failed after admission: {error}"
		) from error
	try:
		parsed = _parse_structured_response(response, response_model)
	except Exception as exc:
		_json_write(
			attempts_dir / f"{prefix}.parse-error.json",
			{"error_type": type(exc).__name__, "error": str(exc)},
		)
		raise AssetForecastError(
			f"{stage} returned invalid structured output after raw/usage persistence: {exc}"
		) from exc
	_json_write(attempts_dir / f"{prefix}.structured.json", parsed.model_dump(mode="json"))
	return parsed, metadata


def _dispatch(
	*,
	stage: str,
	run_dir: Path,
	budget_path: Path,
	system_prompt: str,
	payload: dict[str, Any],
	client: Any | None = None,
) -> tuple[AssetProposal | AssetReview, dict[str, Any]]:
	parsed, metadata = _dispatch_structured(
		stage=stage,
		run_dir=run_dir,
		budget_path=budget_path,
		system_prompt=system_prompt,
		payload=payload,
		response_model=AssetProposal,
		client=client,
	)
	return parsed, metadata


def _dispatch_review(
	*,
	stage: str,
	run_dir: Path,
	budget_path: Path,
	system_prompt: str,
	payload: dict[str, Any],
	client: Any | None = None,
) -> tuple[AssetReview, dict[str, Any]]:
	parsed, metadata = _dispatch_structured(
		stage=stage,
		run_dir=run_dir,
		budget_path=budget_path,
		system_prompt=system_prompt,
		payload=payload,
		response_model=AssetReview,
		client=client,
	)
	return parsed, metadata


def _proposal_payload(
	packet: dict[str, Any], *, instruction: str, context: dict[str, Any] | None = None
) -> dict[str, Any]:
	return {
		"task": instruction,
		"packet": packet,
		"context": context or {},
		"provided_development_parameters": _development_parameters(packet),
		"contract": {
			"method_catalog_version": METHOD_CATALOG_VERSION,
			"implemented_methods": METHOD_CATALOG,
			"allowed_method_ids": sorted(METHOD_CATALOG),
			"allowed_outcomes": [
				"propose_forecast",
				"request_evidence",
				"capability_gap",
				"unresolved",
			],
			"allowlisted_followups": packet["allowlisted_followups"],
			"required_parameter_names": METHOD_CATALOG[
				"aggregate_remaining_life_plus_additions"
			]["required_parameters"],
			"no_runtime_code": True,
			"no_hidden_human_approval": True,
		},
	}


def _review_payload(
	packet: dict[str, Any], candidate: AssetProposal, *, purpose: str
) -> dict[str, Any]:
	return {
		"purpose": purpose,
		"packet": packet,
		"candidate": candidate.model_dump(mode="json"),
		"provided_development_parameters": _development_parameters(packet),
		"implemented_methods": METHOD_CATALOG,
		"review_contract": {
			"review_only": True,
			"revise_requires_exactly_one_bounded_revision_target": True,
			"accept_requires_no_revision_target": True,
			"reject_requires_no_revision_target": True,
			"do_not_return_formulas_or_code": True,
			"lease_additions_must_remain_zero": True,
		},
	}


def _review_is_eligible(review: AssetReview) -> bool:
	return (
		review.evidence_strength != "weak"
		and review.method_valid
		and review.source_valid
		and review.period_valid
		and review.cash_noncash_separated
		and review.depreciation_base_valid
	)


def _validate_review_contract(review: AssetReview) -> None:
	if review.verdict == "revise":
		if (
			review.target_parameter == "none"
			or review.target_direction == "none"
			or not review.required_revision
		):
			raise AssetForecastError(
				"A revise verdict must name one target, direction, and requirement"
			)
		return
	if review.target_parameter != "none" or review.target_direction != "none":
		raise AssetForecastError(
			f"{review.verdict} verdict cannot carry a revision target"
		)


def _terminal_outcome(
	*,
	run_dir: Path,
	budget_path: Path,
	packet: dict[str, Any],
	candidate: AssetProposal,
	status: str,
	reason: str,
	call_metadata: list[dict[str, Any]],
) -> dict[str, Any]:
	decision = {
		"decision_id": "P5-MSFT-ASSET-HELD-001",
		"decision_version": 3,
		"status": status,
		"human_approval": False,
		"selected_candidate": None,
		"method_catalog_version": METHOD_CATALOG_VERSION,
		"review_verdict": None,
		"all_periods_validated": False,
		"reason": reason,
		"candidate_hashes": {"initial": content_hash(candidate.model_dump(mode="json"))},
		"call_metadata": call_metadata,
		"limitations": packet["unavailable"],
	}
	_json_write(run_dir / "decision-held.json", decision)
	_json_write(
		run_dir / "terminal-outcome.json",
		{"candidate": candidate.model_dump(mode="json"), "decision": decision},
	)
	return {
		"packet": packet,
		"candidate": candidate,
		"decision": decision,
		"reviews": {},
		"attempt_count": _ledger_p5_state(budget_path)[0],
		"committed_eur": _ledger_p5_state(budget_path)[1],
	}


def run_reasoning(
	*,
	packet: dict[str, Any],
	run_dir: Path,
	budget_path: Path,
	client: Any | None = None,
) -> dict[str, Any]:
	"""Run the bounded analyst/review path with resumable exact-context stages."""

	run_dir.mkdir(parents=True, exist_ok=True)
	context = {
		"schema_version": SCHEMA_VERSION,
		"proposal_schema_hash": content_hash(AssetProposal.model_json_schema()),
		"review_schema_hash": content_hash(AssetReview.model_json_schema()),
		"prompt_version": PROMPT_VERSION,
		"method_catalog_version": METHOD_CATALOG_VERSION,
		"method_catalog_hash": content_hash(METHOD_CATALOG),
		"model": MODEL,
		"reasoning_effort": REASONING_EFFORT,
		"max_output_tokens": MAX_OUTPUT_TOKENS,
		"endpoint": ENDPOINT_URL,
		"case": CASE,
		"information_cutoff": INFORMATION_CUTOFF,
		"measurement_date": MEASUREMENT_DATE,
		"packet_hash": content_hash(packet),
		"development_parameters_hash": content_hash(_development_parameters(packet)),
	}
	context_path = run_dir / "run-context.json"
	if context_path.exists():
		prior_context = _json_read(context_path)
		for key, value in context.items():
			if prior_context.get(key) != value:
				raise AssetForecastError(
					f"Existing P5 run context differs at {key}; use a new run directory"
				)
	else:
		_json_write(context_path, context)
	_json_write(run_dir / "evidence-packet.json", packet)

	# Keep the lease-note detail out of the initial question.  The analyst must
	# request an allowlisted expansion when it needs that detail; the application
	# never picks a follow-up topic on the analyst's behalf.
	initial_packet = {
		**packet,
		"evidence": [
			item
			for item in packet["evidence"]
			if item["evidence_id"] != "E7"
		],
	}
	initial_prompt = _prompt(
		"Select one supported method and all required parameters for a provisional "
		"PP&E/depreciation/cash-investment schedule. The latest note and statements "
		"must drive the question. If one bounded allowlisted source expansion is needed, "
		"return request_evidence with follow_up_request set to that topic. If the packet "
		"cannot support a safe answer, return capability_gap or unresolved and explain "
		"why. Do not force a proposal, fill missing facts, or invent a follow-up."
	)
	initial, initial_meta = _dispatch(
		stage="analyst-initial",
		run_dir=run_dir,
		budget_path=budget_path,
		system_prompt=initial_prompt,
		payload=_proposal_payload(
			initial_packet, instruction="Make the initial bounded analyst outcome."
		),
		client=client,
	)
	if not isinstance(initial, AssetProposal):
		initial = AssetProposal.model_validate(initial)
	_json_write(run_dir / "candidate-initial.json", initial.model_dump(mode="json"))
	validate_analyst_outcome(initial, initial_packet)
	metadata = [initial_meta]

	if initial.outcome in {"capability_gap", "unresolved"}:
		result = _terminal_outcome(
			run_dir=run_dir,
			budget_path=budget_path,
			packet=packet,
			candidate=initial,
			status=initial.outcome.upper(),
			reason=initial.rationale,
			call_metadata=metadata,
		)
		result["attempt_count"], result["committed_eur"] = _ledger_p5_state(budget_path)
		return result

	followup = initial
	followup_meta: dict[str, Any] | None = None
	followup_called = False
	follow_up_topic = initial.follow_up_request
	if follow_up_topic:
		expansion = expand_evidence(packet, follow_up_topic)
		_json_write(run_dir / f"evidence-followup-{follow_up_topic}.json", expansion)
		followup_evidence = {
			item["evidence_id"]: item for item in initial_packet["evidence"]
		}
		followup_evidence.update(
			{item["evidence_id"]: item for item in expansion["evidence"]}
		)
		followup_packet = {**packet, "evidence": list(followup_evidence.values())}
		followup_prompt = _prompt(
			f"Use the analyst-requested {follow_up_topic} evidence expansion to produce "
			"a complete bounded outcome. Return a proposal only if the expanded packet "
			"supports it; otherwise return capability_gap or unresolved. Keep finance-lease "
			"PP&E already included in opening PP&E, keep future lease additions at zero "
			"pending P8B, and do not return a patch or runtime instructions."
		)
		followup, followup_meta = _dispatch(
			stage="analyst-followup",
			run_dir=run_dir,
			budget_path=budget_path,
			system_prompt=followup_prompt,
			payload=_proposal_payload(
				followup_packet,
				instruction="Respond after the analyst-requested evidence expansion.",
				context={
					"initial_outcome": initial.model_dump(mode="json"),
					"follow_up": expansion,
				},
			),
			client=client,
		)
		followup_called = True
		if not isinstance(followup, AssetProposal):
			followup = AssetProposal.model_validate(followup)
		_json_write(run_dir / "candidate-followup.json", followup.model_dump(mode="json"))
		validate_analyst_outcome(followup, packet)
		if followup_meta is not None:
			metadata.append(followup_meta)
		if followup.outcome != "propose_forecast":
			result = _terminal_outcome(
				run_dir=run_dir,
				budget_path=budget_path,
				packet=packet,
				candidate=followup,
				status=followup.outcome.upper(),
				reason=followup.rationale,
				call_metadata=metadata,
			)
			result["attempt_count"], result["committed_eur"] = _ledger_p5_state(budget_path)
			return result

	if followup.outcome != "propose_forecast":
		raise AssetForecastError(
			"Initial analyst outcome must propose or request one bounded evidence expansion"
		)
	validate_proposal(followup, packet)

	review_prompt = _prompt(
		"Review the candidate against every financial-integrity condition and every "
		"forecast period. Accept when it is usable as a provisional candidate. Use "
		"revise only when one bounded parameter needs a financial correction; "
		"then name exactly one target and direction. Reject when the candidate "
		"cannot be safely used. Never invent a revision target merely to fill a workflow."
	)
	review, review_meta = _dispatch_review(
		stage="review-original",
		run_dir=run_dir,
		budget_path=budget_path,
		system_prompt=review_prompt,
		payload=_review_payload(
			packet, followup, purpose="Consequential original candidate review"
		),
		client=client,
	)
	_json_write(run_dir / "review-original.json", review.model_dump(mode="json"))
	_validate_review_contract(review)
	metadata.append(review_meta)
	if review.verdict == "reject" or (
		review.verdict == "accept" and not _review_is_eligible(review)
	):
		result = _terminal_outcome(
			run_dir=run_dir,
			budget_path=budget_path,
			packet=packet,
			candidate=followup,
			status="REJECTED_BY_REVIEW" if review.verdict == "reject" else "HELD_BY_REVIEW",
			reason=review.rationale,
			call_metadata=metadata,
		)
		result["decision"]["review_verdict"] = review.verdict
		_json_write(run_dir / "decision-held.json", result["decision"])
		result["attempt_count"], result["committed_eur"] = _ledger_p5_state(budget_path)
		return result

	final_candidate = followup
	final_review = review
	revision_meta: dict[str, Any] | None = None
	revision: AssetProposal | None = None
	# The guide requests one development comparison even when the reviewer
	# accepts the first candidate. Do not manufacture a reviewer objection.
	revision_request = {
		"kind": "correction" if review.verdict == "revise" else "development_what_if",
		"requested_by": "system_review" if review.verdict == "revise" else "development_controller",
		"target_parameter": review.target_parameter if review.verdict == "revise" else "opening_remaining_life_years",
		"direction": review.target_direction if review.verdict == "revise" else "restate",
		"instruction": review.required_revision if review.verdict == "revise" else (
			"For the guide's development comparison, reassess the original-pool "
			"remaining-life proxy. Propose one different, evidence-consistent value "
			"within its uncertainty, explaining the tradeoff. Preserve all other "
			"parameters. The accepted original remains recorded; this request is "
			"not a reviewer objection or human approval."
		),
	}
	_json_write(run_dir / "revision-request.json", revision_request)
	target_parameter = revision_request["target_parameter"]
	target_direction = revision_request["direction"]
	if review.verdict in {"accept", "revise"}:
		revision_prompt = _prompt(
			"Produce a complete candidate responding to the explicit revision request. "
			"Change exactly the named target parameter in the requested direction within "
			"the supported range; retain every other parameter and evidence. Explain the "
			"change and preserve meaningful sensitivities. This is not human approval."
		)
		revision, revision_meta = _dispatch(
			stage="analyst-revision",
			run_dir=run_dir,
			budget_path=budget_path,
			system_prompt=revision_prompt,
			payload=_proposal_payload(
				packet,
				instruction="Respond to the separately recorded bounded revision request.",
				context={
					"candidate": followup.model_dump(mode="json"),
					"review": review.model_dump(mode="json"),
					"revision_request": revision_request,
				},
			),
			client=client,
		)
		if not isinstance(revision, AssetProposal):
			revision = AssetProposal.model_validate(revision)
		_json_write(run_dir / "candidate-revision-v2.json", revision.model_dump(mode="json"))
		validate_analyst_outcome(revision, packet)
		if revision_meta is not None:
			metadata.append(revision_meta)
		if revision.outcome != "propose_forecast":
			result = _terminal_outcome(
				run_dir=run_dir,
				budget_path=budget_path,
				packet=packet,
				candidate=revision,
				status=revision.outcome.upper(),
				reason=revision.rationale,
				call_metadata=metadata,
			)
			result["decision"]["review_verdict"] = review.verdict
			_json_write(run_dir / "decision-held.json", result["decision"])
			result["attempt_count"], result["committed_eur"] = _ledger_p5_state(budget_path)
			return result
		validate_proposal(revision, packet)
		before = _parameter_map(followup)
		after = _parameter_map(revision)
		changed = [name for name in before if after[name].value != before[name].value]
		if changed != [target_parameter]:
			raise AssetForecastError(
				f"Targeted revision changed {changed}; expected [{target_parameter}]"
			)
		old_value = before[target_parameter].value
		new_value = after[target_parameter].value
		if target_direction == "lower" and not new_value < old_value:
			raise AssetForecastError("Targeted revision did not move lower as reviewed")
		if target_direction == "higher" and not new_value > old_value:
			raise AssetForecastError("Targeted revision did not move higher as reviewed")
		if target_direction == "restate" and new_value == old_value:
			raise AssetForecastError("Restated revision did not change the target value")
		final_review_prompt = _prompt(
			"Re-check the development what-if revision across every source, period, "
			"method, depreciation-base, cash/noncash, cross-statement, and P8B lease "
			"condition. Accept only if all conditions hold; otherwise reject or explain "
			"why it remains unresolved. This is system-reviewed provisional, never human approval."
		)
		final_review, final_review_meta = _dispatch_review(
			stage="review-revision",
			run_dir=run_dir,
			budget_path=budget_path,
			system_prompt=final_review_prompt,
			payload=_review_payload(
				packet, revision, purpose="Targeted revised candidate re-check"
			),
			client=client,
		)
		_json_write(run_dir / "review-revision.json", final_review.model_dump(mode="json"))
		_validate_review_contract(final_review)
		metadata.append(final_review_meta)
		if final_review.verdict != "accept" or not _review_is_eligible(final_review):
			result = _terminal_outcome(
				run_dir=run_dir,
				budget_path=budget_path,
				packet=packet,
				candidate=revision,
				status="REJECTED_BY_REVIEW" if final_review.verdict == "reject" else "HELD_BY_REVIEW",
				reason=final_review.rationale,
				call_metadata=metadata,
			)
			result["decision"]["review_verdict"] = final_review.verdict
			_json_write(run_dir / "decision-held.json", result["decision"])
			result["attempt_count"], result["committed_eur"] = _ledger_p5_state(budget_path)
			return result
		final_candidate = revision

	if revision is not None:
		final_name = "candidate-revision-v2.json"
	elif followup_called:
		final_name = "candidate-followup.json"
	else:
		final_name = "candidate-initial.json"
	decision = {
		"decision_id": "P5-MSFT-ASSET-DECISION-001",
		"decision_version": 2,
		"status": "SYSTEM_REVIEWED_PROVISIONAL",
		"human_approval": False,
		"selected_candidate": final_name,
		"method_catalog_version": METHOD_CATALOG_VERSION,
		"method_id": final_candidate.method_id,
		"method_version": final_candidate.method_version,
		"changed_parameter": target_parameter if revision is not None else "none",
		"change_direction": target_direction if revision is not None else "none",
		"review_verdict": final_review.verdict,
		"original_review_verdict": review.verdict,
		"mechanical_validation_status": "PENDING_MODEL_BUILD",
		"review_flags": {
			"evidence_strength": final_review.evidence_strength,
			"method_valid": final_review.method_valid,
			"source_valid": final_review.source_valid,
			"period_valid": final_review.period_valid,
			"cash_noncash_separated": final_review.cash_noncash_separated,
			"depreciation_base_valid": final_review.depreciation_base_valid,
		},
		"revision": {
			"kind": revision_request["kind"],
			"requested_by": revision_request["requested_by"],
			"review_verdict_before": review.verdict,
			"final_review_verdict": final_review.verdict,
			"target_parameter": target_parameter if revision is not None else "none",
			"direction": target_direction if revision is not None else "none",
		},
		"review_rationale": final_review.rationale,
		"candidate_hashes": {
			"initial": content_hash(initial.model_dump(mode="json")),
			"followup": content_hash(followup.model_dump(mode="json")),
			"revision": content_hash(revision.model_dump(mode="json")) if revision else None,
		},
		"review_hashes": {
			"original": content_hash(review.model_dump(mode="json")),
			"revision": content_hash(final_review.model_dump(mode="json")),
		},
		"call_metadata": metadata,
		"limitations": packet["unavailable"],
	}
	_json_write(run_dir / "decision-v2.json", decision)
	_json_write(
		run_dir / "model-input.json",
		{
			"schema_version": SCHEMA_VERSION,
			"case": CASE,
			"information_cutoff": INFORMATION_CUTOFF,
			"measurement_date": MEASUREMENT_DATE,
			"packet": packet,
			"candidate": final_candidate.model_dump(mode="json"),
			"decision": decision,
		},
	)
	committed_count, committed_eur = _ledger_p5_state(budget_path)
	return {
		"packet": packet,
		"candidate": final_candidate,
		"decision": decision,
		"reviews": {"original": review, "revision": final_review},
		"attempt_count": committed_count,
		"committed_eur": committed_eur,
	}


def default_offline_candidate(
	packet: dict[str, Any], *, remaining_life: float = 8.0
) -> AssetProposal:
	"""A test-only fixture candidate; never used as a live-call fallback."""

	return AssetProposal(
		outcome="propose_forecast",
		method_id="aggregate_remaining_life_plus_additions",
		method_version="v2",
		parameters=[
			AssetParameter(
				name="opening_remaining_life_years",
				value=remaining_life,
				basis="estimated",
				evidence_refs=["E1", "E6"],
				rationale="Aggregate proxy because no remaining-age profile is disclosed.",
				uncertainty="Actual mix and remaining lives are unavailable.",
			),
			AssetParameter(
				name="new_addition_useful_life_years",
				value=10.0,
				basis="estimated",
				evidence_refs=["E6"],
				rationale="Bounded proxy within the disclosed useful-life ranges.",
				uncertainty="Future category mix is unavailable.",
			),
			AssetParameter(
				name="new_addition_timing_fraction",
				value=0.5,
				basis="estimated",
				evidence_refs=["E3", "E5"],
				rationale="Midpoint timing convention for period additions.",
				uncertainty="Within-period payment timing is unavailable.",
			),
			AssetParameter(
				name="cash_ppe_additions_rate",
				value=packet["facts"]["calculated"]["ttm_cash_ppe_rate"],
				basis="calculated",
				evidence_refs=["E3", "E5"],
				rationale="TTM cash PP&E payments divided by TTM revenue.",
				uncertainty="Future investment intensity may differ.",
			),
			AssetParameter(
				name="noncash_ppe_additions_ratio",
				value=0.2,
				basis="estimated",
				evidence_refs=["E1", "E4"],
				rationale=(
					"Bounded scenario informed by period-end payable stock observations; "
					"not a disclosed period-addition flow."
				),
				uncertainty="Only period-end payable stock is disclosed; period additions are unavailable.",
			),
			*[
				AssetParameter(name=name, **definition)
				for name, definition in _development_parameters(packet).items()
			],
		],
		evidence_refs=["E1", "E2", "E3", "E4", "E5", "E6", "E7"],
		rationale="Test fixture only; use aggregate opening base plus separately tracked additions.",
		alternatives=["Use a lower opening-life proxy after review."],
		uncertainty=packet["unavailable"],
		sensitivities=[
			AssetSensitivity(
				parameter="opening_remaining_life_years",
				low=max(1.0, remaining_life - 2),
				base=remaining_life,
				high=remaining_life + 2,
				interpretation="Shorter life raises opening-asset depreciation and lowers EBIT/PP&E.",
			),
			AssetSensitivity(
				parameter="cash_ppe_additions_rate",
				low=0.8 * packet["facts"]["calculated"]["ttm_cash_ppe_rate"],
				base=packet["facts"]["calculated"]["ttm_cash_ppe_rate"],
				high=1.2 * packet["facts"]["calculated"]["ttm_cash_ppe_rate"],
				interpretation="Higher cash investment lowers cash flow and raises recognized additions.",
			),
		],
		follow_up_request=None,
	)


def _run_cli(args: argparse.Namespace) -> None:
	p2_root = Path(args.p2_root).resolve()
	legacy = Path(args.legacy_source).resolve()
	budget = Path(args.budget).resolve()
	packet = build_evidence_packet(p2_root, legacy)
	if args.offline:
		candidate = default_offline_candidate(packet)
		validate_proposal(candidate, packet)
		output = {
			"status": "PASS",
			"mode": "offline",
			"packet_hash": content_hash(packet),
			"candidate_hash": content_hash(candidate.model_dump(mode="json")),
		}
		_json_write(Path(args.run_dir).resolve() / "offline-check.json", output)
		print(json.dumps(output, indent=2))
		return
	result = run_reasoning(
		packet=packet, run_dir=Path(args.run_dir).resolve(), budget_path=budget
	)
	print(
		json.dumps(
			{
				"status": result["decision"]["status"],
				"attempt_count": result["attempt_count"],
				"committed_eur": result["committed_eur"],
				"decision": result["decision"],
			},
			indent=2,
		)
	)


def main() -> None:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--p2-root", default="data/build-guide-p2-r2/MSFT")
	parser.add_argument(
		"--legacy-source",
		default="data/MSFT/01_source/edgar/filings/0000950170-25-100235.txt",
	)
	parser.add_argument("--budget", default="data/build-guide-api-budget.json")
	parser.add_argument("--run-dir", required=True)
	parser.add_argument("--offline", action="store_true")
	_run_cli(parser.parse_args())


if __name__ == "__main__":
	main()
