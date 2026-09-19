"""Bounded, resumable P10 analysis and whole-model review workflow."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import subprocess
from datetime import date
from pathlib import Path
from typing import Any, Literal
from xml.etree import ElementTree
from zipfile import ZipFile

from openai.lib._pydantic import to_strict_json_schema
from pydantic import BaseModel, ConfigDict, Field, model_validator

from smrik_fund.analysis_budget import content_hash, reservation

ROOT = Path(__file__).resolve().parents[2]
AREA_SEQUENCE = (
	"revenue",
	"operating_costs",
	"ppe_capex",
	"intangibles",
	"working_capital",
	"taxes",
	"debt_interest",
	"leases",
	"sbc_equity",
	"nonoperating",
	"cash_flow_cash",
	"dcf_terminal",
)
PERIODS = (
	"FY2026_STUB",
	"FY2027",
	"FY2028",
	"FY2029",
	"FY2030",
	"FY2031",
	"FY2032",
	"FY2033",
	"FY2034",
	"FY2035",
	"FY2036",
)
Area = Literal[
	"revenue",
	"operating_costs",
	"ppe_capex",
	"intangibles",
	"working_capital",
	"taxes",
	"debt_interest",
	"leases",
	"sbc_equity",
	"nonoperating",
	"cash_flow_cash",
	"dcf_terminal",
]
Period = Literal[
	"FY2026_STUB",
	"FY2027",
	"FY2028",
	"FY2029",
	"FY2030",
	"FY2031",
	"FY2032",
	"FY2033",
	"FY2034",
	"FY2035",
	"FY2036",
	"MEASUREMENT_DATE",
	"TERMINAL_FY2037",
	"HISTORICAL_TTM",
]
MODEL = "gpt-5.6-sol"
PROMPT_VERSION = "p10-whole-model-review-v3-current-schedules"
WORKFLOW_VERSION = "p10-analysis-workflow-v1"
MAX_OUTPUT_TOKENS = 16000
MAX_P10_CALLS = 4
PROPOSED_P10_CAP_EUR = 2.0
EXPECTED_MODEL_SHA256 = (
	"24ecc22c7a213f1959dfd50bd77fc34803af8883e658806cf64e64e1ec13d630"
)


class WorkflowError(ValueError):
	pass


class EvidenceRequest(BaseModel):
	model_config = ConfigDict(extra="forbid")

	question_id: str = Field(min_length=1, max_length=80)
	question: str = Field(min_length=1, max_length=500)
	literal_phrases: list[str] = Field(min_length=1, max_length=3)
	followup_index: int = Field(ge=0, le=2)

	@model_validator(mode="after")
	def _literal_bounds(self) -> EvidenceRequest:
		if any(not phrase.strip() or len(phrase) > 160 for phrase in self.literal_phrases):
			raise ValueError("Evidence phrases must be nonempty and at most 160 characters")
		return self


class AreaAssessment(BaseModel):
	model_config = ConfigDict(extra="forbid")

	area: Area
	outcome: Literal[
		"supported_no_change",
		"reassessment_required",
		"unresolved",
		"capability_gap",
		"request_evidence",
	]
	prior_decision_carried: bool
	changed_dependencies_assessed: list[Area]
	source_refs: list[str] = Field(min_length=1)
	period_refs: list[Period] = Field(min_length=1)
	basis_type: Literal[
		"reported_source",
		"calculated",
		"explicit_estimate",
		"explained_no_extra_treatment",
		"justified_not_applicable",
		"mixed",
	]
	basis: str = Field(min_length=1)
	concerns: list[str]
	evidence_request: EvidenceRequest | None

	@model_validator(mode="after")
	def _outcome_shape(self) -> AreaAssessment:
		if (self.outcome == "request_evidence") != (self.evidence_request is not None):
			raise ValueError("Only request_evidence outcomes may include an evidence request")
		return self


class WholeModelReview(BaseModel):
	model_config = ConfigDict(extra="forbid")

	verdict: Literal["accept", "revise", "reject"]
	areas: list[AreaAssessment] = Field(min_length=12, max_length=12)
	cross_schedule_concerns: list[str] = Field(description="Unresolved consequential cross-schedule problems; empty on accept. Put accepted estimates and caveats in area basis.")
	required_revision: str | None
	rationale: str = Field(min_length=1)

	@model_validator(mode="after")
	def _complete_shape(self) -> WholeModelReview:
		if tuple(item.area for item in self.areas) != AREA_SEQUENCE:
			raise ValueError("Whole-model review must cover each financial area in fixed order")
		if self.verdict == "accept" and any(
			item.outcome != "supported_no_change" for item in self.areas
		):
			raise ValueError("Accepted review requires supported no-change for every area")
		if self.verdict == "accept" and self.required_revision is not None:
			raise ValueError("Accepted review cannot require a revision")
		if self.verdict == "accept" and self.cross_schedule_concerns:
			raise ValueError("Accepted review cannot retain unresolved cross-schedule concerns")
		if self.verdict != "accept" and not self.required_revision:
			raise ValueError("Revise/reject verdict requires a concrete revision")
		return self


class AnalystCorrection(BaseModel):
	model_config = ConfigDict(extra="forbid")

	area: Area
	outcome: Literal["select", "unresolved", "capability_gap", "request_evidence"]
	selection_id: str | None
	source_refs: list[str]
	period_refs: list[Period]
	basis: str = Field(min_length=1)
	follow_up_request: EvidenceRequest | None

	@model_validator(mode="after")
	def _shape(self) -> AnalystCorrection:
		if (self.outcome == "select") != (self.selection_id is not None):
			raise ValueError("Only select outcomes may provide a closed selection ID")
		if (self.outcome == "request_evidence") != (self.follow_up_request is not None):
			raise ValueError("Only request_evidence outcomes may provide a request")
		return self


class IndependentRecheck(BaseModel):
	model_config = ConfigDict(extra="forbid")

	verdict: Literal["accept", "reject"]
	area: Area
	selection_id: str | None
	source_valid: bool
	period_valid: bool
	method_valid: bool
	no_double_count: bool
	cross_schedule_concerns_resolved: bool
	concerns: list[str]
	rationale: str = Field(min_length=1)


DEPENDENCIES: dict[str, tuple[str, ...]] = {
	"revenue": (),
	"operating_costs": ("revenue",),
	"ppe_capex": ("revenue", "operating_costs", "leases", "nonoperating"),
	"intangibles": ("operating_costs", "taxes"),
	"working_capital": ("revenue", "operating_costs", "sbc_equity"),
	"taxes": ("operating_costs", "debt_interest", "nonoperating"),
	"debt_interest": ("cash_flow_cash",),
	"leases": ("operating_costs", "ppe_capex", "debt_interest"),
	"sbc_equity": ("operating_costs", "cash_flow_cash"),
	"nonoperating": ("taxes", "cash_flow_cash"),
	"cash_flow_cash": tuple(AREA_SEQUENCE[:10]),
	"dcf_terminal": tuple(AREA_SEQUENCE[:11]),
}
DECISION_KEYS = {
	"revenue": "p6_decision",
	"operating_costs": "p6_decision",
	"ppe_capex": "p5_decision",
	"intangibles": "other_balances_decision",
	"working_capital": "p7_decision",
	"taxes": "p8a_decision",
	"debt_interest": "p8b_decision",
	"leases": "p8b_decision",
	"sbc_equity": "p8c_decision",
	"nonoperating": "other_balances_decision",
	"cash_flow_cash": "p8c_decision",
	"dcf_terminal": "valuation_policy",
}
CORRECTION_CHOICES: dict[str, dict[str, dict[str, Any]]] = {
	"ppe_capex": {
		"ppe_capex:cash_additions_rate_low": {
			"description": "Use the existing 25% cash PP&E additions-rate sensitivity.",
			"value": 0.25,
			"control": "cash_ppe_additions_rate",
		},
		"ppe_capex:cash_additions_rate_high": {
			"description": "Use the existing 36% cash PP&E additions-rate sensitivity.",
			"value": 0.36,
			"control": "cash_ppe_additions_rate",
		},
	},
	"taxes": {
		"taxes:include_current_tax_face_claim": {
			"description": "Turn on the existing current-tax face-claim stress.",
			"value": 1,
			"control": "current_tax_claim_switch",
		},
	},
	"nonoperating": {
		"nonoperating:investment_multiplier_zero": {
			"description": "Use the existing zero-value investment-multiplier sensitivity.",
			"value": 0,
			"control": "other_investment_value_multiplier",
		},
	},
	"dcf_terminal": {
		"dcf_terminal:terminal_growth_zero": {
			"description": "Use the existing 0% terminal-growth sensitivity.",
			"value": 0,
			"control": "terminal_growth",
		},
		"dcf_terminal:terminal_growth_three_pct": {
			"description": "Use the existing 3% terminal-growth sensitivity.",
			"value": 0.03,
			"control": "terminal_growth",
		},
		"dcf_terminal:beta_low": {
			"description": "Use the existing 0.85 beta sensitivity.",
			"value": 0.85,
			"control": "beta",
		},
		"dcf_terminal:beta_high": {
			"description": "Use the existing 1.15 beta sensitivity.",
			"value": 1.15,
			"control": "beta",
		},
	},
}


def _json_bytes(value: object) -> bytes:
	return json.dumps(
		value, sort_keys=True, ensure_ascii=False, allow_nan=False
	).encode("utf-8")


def _sha256(path: Path) -> str:
	return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
	value = json.loads(path.read_text(encoding="utf-8-sig"))
	if not isinstance(value, dict):
		raise WorkflowError(f"Expected JSON object: {path}")
	return value


def _write_immutable(path: Path, value: object) -> None:
	payload = _json_bytes(value) + b"\n"
	path.parent.mkdir(parents=True, exist_ok=True)
	if path.exists():
		if path.read_bytes() != payload:
			raise WorkflowError(f"Immutable checkpoint differs: {path}")
		return
	path.write_bytes(payload)


def _strict_schema(model: type[BaseModel]) -> dict[str, Any]:
	schema = to_strict_json_schema(model)
	_assert_strict(schema)
	return schema


def _assert_strict(node: Any) -> None:
	if isinstance(node, dict):
		if node.get("type") == "object" or "properties" in node:
			if set(node.get("properties", {})) != set(node.get("required", [])):
				raise WorkflowError("Strict schema must require every object property")
			if node.get("additionalProperties") is not False:
				raise WorkflowError("Strict schema must forbid extra object properties")
		for value in node.values():
			_assert_strict(value)
	elif isinstance(node, list):
		for value in node:
			_assert_strict(value)


def _decision_summary(model: dict[str, Any], area: str) -> dict[str, Any]:
	key = DECISION_KEYS[area]
	record = model.get(key) or {}
	if key == "valuation_policy":
		return {
			"record": key,
			"status": "PROVISIONAL_REVIEW_REQUIRED",
			"method_id": record.get("method_id"),
			"identity_hash": content_hash(record),
			"human_approval": False,
			"carried_prior_decision_only": True,
		}
	binding = record.get("binding") or {}
	return {
		"record": key,
		"status": record.get("status"),
		"method_id": record.get("method_id"),
		"review_verdict": record.get("review_verdict")
		or (record.get("review") or {}).get("verdict"),
		"candidate_hash": record.get("candidate_hash")
		or binding.get("candidate_hash"),
		"review_hash": record.get("review_hash") or binding.get("review_hash"),
		"context_hash": record.get("context_hash") or binding.get("context_hash"),
		"source_packet_hash": record.get("source_packet_hash")
		or binding.get("source_packet_hash"),
		"human_approval": bool(record.get("human_approval", False)),
		"carried_prior_decision_only": True,
	}


def _short_text(value: Any, limit: int = 1600) -> str | None:
	if not isinstance(value, str) or not value.strip():
		return None
	return value if len(value) <= limit else value[: limit - 3] + "..."


def _area_payload(model: dict[str, Any], area: str) -> dict[str, Any]:
	if area == "ppe_capex":
		return {
			"method": {
				"id": model["candidate"]["method_id"],
				"version": model["candidate"]["method_version"],
			},
			"selected_controls": model["candidate"]["parameters"],
			"rationale": model["candidate"].get("rationale"),
			"alternatives": model["candidate"].get("alternatives"),
			"uncertainty": model["candidate"].get("uncertainty"),
			"limitations": model["p5_decision"].get("limitations", []),
		}
	forecast_key = {
		"revenue": "operating_forecast",
		"operating_costs": "operating_forecast",
		"working_capital": "working_capital_forecast",
		"taxes": "tax_forecast",
		"debt_interest": "financing_forecast",
		"leases": "financing_forecast",
		"sbc_equity": "equity_forecast",
		"cash_flow_cash": "equity_forecast",
		"intangibles": "other_balances_forecast",
		"nonoperating": "other_balances_forecast",
	}.get(area)
	if forecast_key is None:
		policy = model["valuation_policy"]
		return {
			"method": {"id": policy["method_id"], "version": policy["method_version"]},
			"selected_controls": policy,
			"rationale": "Selected P9 WACC, terminal normalization, and once-only equity-claim policy.",
			"alternatives": "Live terminal-growth, beta, debt-spread, and tax-shield sensitivities.",
			"uncertainty": "Beta, terminal growth, and supplier-financing terms remain estimates or unavailable as identified in the valuation packet.",
			"limitations": model.get("historical_bridge", {}).get("unavailable", []),
		}
	forecast = model[forecast_key]
	selected = forecast.get("inputs") or forecast.get("driver_inputs") or {}
	if area == "revenue":
		selected = {
			"segment_growth": forecast["driver_inputs"]["segment_growth"],
			"historical_anchors": forecast["driver_inputs"]["historical_anchors"],
			"corporate_eliminations": forecast["corporate_eliminations"],
			"stub_basis": forecast["stub_basis"],
		}
	elif area == "operating_costs":
		selected = {
			"cost_ratio": forecast["driver_inputs"]["cost_ratio"],
			"embedded_ppe_baseline": forecast["embedded_ppe_baseline"],
			"expense_formula": forecast["expense_bridge"]["formula"],
			"reported_cost_basis": forecast["reported_cost_basis"],
		}
	decision = forecast.get("decision") or {}
	review = decision.get("review") or forecast.get("review") or {}
	candidate = (decision.get("binding") or {}).get("candidate_snapshot") or forecast.get(
		"candidate", {}
	)
	if area in {"revenue", "operating_costs"}:
		selected = {**selected, "forecast_basis": "Segment cost of revenue and aggregate operating expenses ARE disclosed. The selected consolidated functional cost ratios preserve reported cost of revenue, R&D, sales/marketing and G&A without inventing their within-segment functional allocation. This is an analyst modeling choice, not absence of segment cost disclosure; segment margin forecasting is a valid alternative."}
	if area in {"debt_interest", "leases"}:
		selected = {**selected, "selected_policy": {key: candidate[key] for key in (
			"debt_coupon_rate", "debt_refinance_policy", "debt_tail_policy", "refinance_term_years", "refinance_fee_rate",
			"lease_bundle", "pipeline_finance_share", "pipeline_operating_life_years", "pipeline_finance_life_years",
			"pipeline_operating_rate", "pipeline_finance_rate", "pipeline_timing_policy", "opening_finance_life_years",
		)}}
	return {
		"method": forecast.get("method"),
		"selected_controls": selected,
		"rationale": _short_text(review.get("rationale") or candidate.get("rationale")),
		"alternatives": candidate.get("alternatives"),
		"uncertainty": ["Forward growth and functional cost ratios are estimates, not company guidance. Stub uses prior comparable quarter and current/prior YTD growth; segment mix and AI infrastructure can change margins. Segment total costs are disclosed, but segment functional expense splits are unavailable."] if area in {"revenue", "operating_costs"} else candidate.get("uncertainty"),
		"limitations": forecast.get("limitations", []),
	}


def _source_records(
	model: dict[str, Any],
	source_manifest: dict[str, Any],
	valuation_context: dict[str, Any],
	bindings: dict[str, str],
) -> dict[str, dict[str, Any]]:
	records: dict[str, dict[str, Any]] = {}
	_validate_filing_context(valuation_context, source_manifest)
	for row in valuation_context["filing_source_rows"]:
		records[row["source_id"]] = row
	for filing in source_manifest.get("selected_filings", []):
		accession = str(filing["accession"])
		binding_key = f"original_source:{accession}"
		if binding_key not in bindings:
			continue
		record_id = f"SEC:{accession}"
		records[record_id] = {
			"kind": "pinned_original_source",
			"sha256": bindings[binding_key],
			"information_cutoff": source_manifest["information_cutoff"],
			"period": filing["period_of_report"],
			"publication_date": filing["publication_date"],
			"locator": filing["source_locator"],
		}
	for row in valuation_context.get("market_source_rows", []):
		record_id = str(row["source_id"])
		records[record_id] = {
			"kind": "pinned_market_source_record",
			"record_hash": content_hash(row),
			"information_cutoff": source_manifest["information_cutoff"],
			"period": row.get("observation_date") or row.get("publication_date"),
			"locator": row.get("url"),
			"excerpt": row.get("locator_or_excerpt"),
			"status": row.get("status"),
			"limitation": row.get("limitation"),
		}
	for area in AREA_SEQUENCE:
		record_id = f"AREA-PACKET:{area}"
		records[record_id] = {
			"kind": "pinned_prior_decision_not_primary_evidence",
			"record_hash": content_hash(model[DECISION_KEYS[area]]),
			"selected_model_sha256": bindings["selected_model"],
			"information_cutoff": model["information_cutoff"],
			"period": "FY2026_STUB-FY2036"
			if area != "dcf_terminal"
			else "FY2026_STUB-TERMINAL_FY2037",
			"locator": f"selected-model.json#/{DECISION_KEYS[area]}",
			"purpose": "Identify the prior task context only; source claims require the filing excerpts. Historical reasoning and limitations may be superseded by later schedules.",
		}
	return records


def _validate_filing_context(context: dict[str, Any], manifest: dict[str, Any]) -> None:
	"""Validate known cached filing passages before they enter a paid request."""
	selected = {row["accession"]: row for row in manifest["selected_filings"]}
	sources = {}
	for item in context.get("filing_source_files", []):
		accession = item["accession"]
		if accession not in selected:
			raise WorkflowError("Filing excerpt is outside the frozen source selection")
		path = ROOT / "data/MSFT/01_source/edgar/filings" / f"{accession}.txt"
		if Path(item["path"]).resolve() != path.resolve() or _sha256(path) != item["sha256"]:
			raise WorkflowError("STALE_CONTEXT: cached filing text differs from its source binding")
		sources[accession] = (item, path.read_text(encoding="utf-8").splitlines())
	rows = context.get("filing_source_rows", [])
	if not rows or {area for row in rows for area in row["areas"]} != set(AREA_SEQUENCE):
		raise WorkflowError("Initial filing context must cover all twelve financial areas")
	for row in rows:
		accession = row["source_accession"]
		if accession not in sources:
			raise WorkflowError("Filing excerpt has no pinned source file")
		item, lines = sources[accession]
		filing = selected[accession]
		start, end = row["line_start"], row["line_end"]
		if not 1 <= start <= end <= len(lines):
			raise WorkflowError("Invalid original filing line range")
		source_slice = "\n".join(lines[start - 1:end])
		excerpt = re.sub(r"[ \t]+", " ", source_slice)
		if (
			row["source_file_sha256"] != item["sha256"]
			or row["period"] != filing["period_of_report"]
			or row["publication_date"] != filing["publication_date"]
			or row["publication_date"] > manifest["information_cutoff"]
			or row["excerpt"] != excerpt
			or row["excerpt_sha256"] != hashlib.sha256(excerpt.encode()).hexdigest()
			or row["source_slice_sha256"] != hashlib.sha256(source_slice.encode()).hexdigest()
		):
			raise WorkflowError("Filing excerpt content, source, or period is invalid")


def validate_frozen_inputs(
	model_path: Path,
	verification_path: Path,
	source_manifest_path: Path,
	valuation_context_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
	if _sha256(model_path) != EXPECTED_MODEL_SHA256:
		raise WorkflowError("STALE_CONTEXT: selected P9 model hash changed")
	model = _load(model_path)
	verification = _load(verification_path)
	source_manifest = _load(source_manifest_path)
	valuation_context = _load(valuation_context_path)
	if (model.get("case"), model.get("measurement_date"), model.get("information_cutoff")) != (
		"MSFT",
		"2026-03-31",
		"2026-04-30",
	):
		raise WorkflowError("Frozen case/date/cutoff mismatch")
	if verification.get("status") != "PASS":
		raise WorkflowError("P9 calculated evidence did not pass")
	p9 = verification.get("snapshot", {}).get("p9", {})
	if p9.get("valuationGate") != "PASS" or p9.get("status") != "PROVISIONAL_REVIEW_REQUIRED":
		raise WorkflowError("P9 analytical starting state is invalid")
	if valuation_context.get("selected_model_sha256") != EXPECTED_MODEL_SHA256:
		raise WorkflowError("Valuation context is not bound to the selected model")
	if (source_manifest.get("case"), source_manifest.get("information_cutoff")) != ("MSFT", "2026-04-30"):
		raise WorkflowError("Source manifest case mismatch")
	_validate_filing_context(valuation_context, source_manifest)
	return model, verification, source_manifest, valuation_context


def build_compact_review_context(
	model: dict[str, Any],
	calculated: dict[str, Any],
	source_manifest: dict[str, Any],
	valuation_context: dict[str, Any],
	bindings: dict[str, str],
) -> dict[str, Any]:
	snapshot = calculated["snapshot"]
	statements = snapshot["statements"]
	if sum(len(rows) for rows in statements.values()) != 50:
		raise WorkflowError("Expected 50 statement rows")
	if any(len(row.get("values", [])) != 11 for rows in statements.values() for row in rows):
		raise WorkflowError("Every statement row must contain all 11 periods")
	p9 = snapshot["p9"]
	coverage = []
	for area in AREA_SEQUENCE:
		area_payload = _area_payload(model, area)
		area_payload["prior_rationale_not_revalidated"] = area_payload.pop("rationale")
		area_payload["prior_package_limitations_may_be_superseded"] = area_payload.pop("limitations")
		area_payload["scope_note"] = "Controls describe the selected model; accompanying prior narrative describes the earlier package only. Use current calculated statements and later decisions to reassess it."
		coverage.append(
			{
				"area": area,
				"sequence": AREA_SEQUENCE.index(area) + 1,
				"depends_on": list(DEPENDENCIES[area]),
				"prior": _decision_summary(model, area),
				"current_assumptions_and_treatments": area_payload,
				"pinned_source_records": [row["source_id"] for row in valuation_context["filing_source_rows"] if area in row["areas"]],
				"fresh_reassessment_required": True,
				"outcome": "pending_whole_model_review",
			}
		)
	source_records = _source_records(model, source_manifest, valuation_context, bindings)
	sensitivities = {}
	for name, rows in calculated.get("sensitivities", {}).items():
		sensitivities[name] = [
			{
				"row": row["row"],
				"label": row.get("values", [None])[0],
				"values": row.get("values", [])[1:],
				"formula_hash": content_hash(row.get("formulas", [])),
			}
			for row in rows
		]
	mechanical_pass = (
		snapshot["allPeriodStatus"] == "PASS"
		and p9["inputGate"] == "PASS"
		and p9["terminalGate"] == "PASS"
		and p9["claimCheck"] == "PASS"
		and p9["valuationGate"] == "PASS"
		and all(value == "PASS" for value in snapshot["checks"])
	)
	return {
		"workflow_version": WORKFLOW_VERSION,
		"case": "MSFT",
		"measurement_date": "2026-03-31",
		"information_cutoff": "2026-04-30",
		"basis": "later-informed, not point-in-time; USD millions except per-share values",
		"bindings": bindings,
		"coverage": coverage,
		"source_records": source_records,
		"source_ref_allowlist": sorted(source_records),
		"source_universe": {
			"manifest_selected_accessions": [
				item["accession"] for item in source_manifest["selected_filings"]
			],
			"literal_followups": "Only manifest-selected files present in evidence/original_source; outside requests are unsupported/unresolved",
		},
		"statements_all_11_periods": statements,
		"schedules_and_bridges": {
			"original_pool_depreciation": snapshot["originalPoolDepreciation"],
			"total_depreciation": snapshot["totalDepreciation"],
			"working_capital": {
				"cash_conversion_nwc": snapshot["workingCapital"]["cashConversionNwc"],
				"change": snapshot["workingCapital"]["cashConversionNwcChange"],
			},
			"tax": {
				"operating_tax": snapshot["tax"]["operatingTaxExpense"],
				"current_payable": snapshot["tax"]["currentTaxPayableClosing"],
			},
			"financing": {
				**{key: snapshot["financing"][key] for key in ("debtOpeningFace", "debtClosingFace", "debtRepayment", "debtProceeds", "debtNetCash", "debtContraRelease", "debtClosingContra", "debtBookExpense", "debtCurrentCarrying", "debtNoncurrentCarrying")},
				"debt_reconciliation_basis": "Opening face plus refinancing proceeds minus gross repayments equals closing face. Disclosed FY27/FY29 maturities refinance at par; thereafter is explicitly held through FY36. Interest uses opening face times the selected coupon times actual days/365. Original signed contra releases proportionally on redemption; replacement debt is par. Gross repayments and proceeds offset in financing cash, rather than disappearing.",
				"debt_cash_interest": snapshot["financing"]["debtCashInterest"],
				"operating_lease_payment": snapshot["financing"]["operatingPayment"],
				"finance_lease_payment": snapshot["financing"]["financePayment"],
				"finance_ppe": snapshot["financing"]["financePpeClosing"],
			},
			"cfo_noncash_and_lease_adjustments": {
				"basis": "CashFlow row7 = PP&E depreciation + operating ROU amortization + debt contra release - operating lease principal + book SBC + finite intangible amortization + goodwill impairment - noncash investment gain. Operating principal converts book lease cost to cash payments; it is not a depreciation add-back.",
				"ppe_depreciation": snapshot["totalDepreciation"],
				"operating_rou_amortization": snapshot["financing"]["operatingAmortization"],
				"debt_contra_release": snapshot["financing"]["debtContraRelease"],
				"operating_lease_principal_to_subtract": snapshot["financing"]["operatingPrincipal"],
				"book_sbc": snapshot["equity"]["bookSbc"],
				"finite_amortization": snapshot["otherBalances"]["intangibleAmortization"],
				"goodwill_impairment": snapshot["otherBalances"]["goodwillImpairment"],
				"noncash_gain_to_subtract": snapshot["otherBalances"]["noncashGain"],
			},
			"equity": {
				"book_sbc": snapshot["equity"]["bookSbc"],
				"new_sbc": snapshot["equity"]["newSbc"],
				"point_shares": snapshot["equity"]["pointSharesClosing"],
				"valuation_ufcf": snapshot["equity"]["valuationUfcf"],
				"cfo_ufcf": snapshot["equity"]["cfoUfcf"],
			},
			"nonoperating": {
				"investment_value": snapshot["otherBalances"]["investmentValue"],
				"intangible_closing": snapshot["otherBalances"]["intangibleClosing"],
				"cash_income": snapshot["otherBalances"]["cashIncome"],
			},
			"economic_ufcf": p9["explicitUfcf"],
		},
		"valuation": {
			"wacc": p9["wacc"],
			"explicit_pv": p9["explicitPv"],
			"terminal": p9["terminal"],
			"enterprise_value": p9["enterpriseValue"],
			"common_equity_value": p9["commonEquityValue"],
			"per_share_value": p9["perShareValue"],
			"claim_check": p9["claimCheck"],
			"tax_timing_diagnostic": {
				"pv": p9["taxTimingPv"],
				"per_share": p9["taxTimingPerShare"],
			},
			"historical_bridge": p9["history"],
			"terminal_growth_sensitivity": p9["terminalGrowthSensitivity"],
			"other_sensitivities": sensitivities,
		},
		"mechanical_state": {
			"result": "PASS" if mechanical_pass else "FAIL",
			"all_period": snapshot["allPeriodStatus"],
			"p9_input": p9["inputGate"],
			"p9_terminal": p9["terminalGate"],
			"p9_claim": p9["claimCheck"],
			"p9_valuation": p9["valuationGate"],
			"statement_checks": snapshot["checks"],
		},
		"selected_valuation_development_context": {key: value for key, value in valuation_context.items() if key not in {"filing_source_rows", "filing_source_files"}},
		"correction_options": {
			area: [
				{"selection_id": f"{area}:retain_effective_decision", "description": "Retain the existing effective decision after fresh reassessment."},
				*[
					{"selection_id": selection_id, **details}
					for selection_id, details in CORRECTION_CHOICES.get(area, {}).items()
				],
			]
			for area in AREA_SEQUENCE
		},
	}


def build_whole_model_request(context: dict[str, Any]) -> dict[str, Any]:
	# Keep full records locally; send each current control and evidence text once.
	payload = copy.deepcopy(context)
	shared_controls: dict[str, Any] = {}
	for area in payload["coverage"]:
		current = area["current_assumptions_and_treatments"]
		for name in ("prior_rationale_not_revalidated", "prior_package_limitations_may_be_superseded"):
			current.pop(name, None)
		controls = current.pop("selected_controls")
		identity = content_hash(controls)
		shared_controls.setdefault(identity, controls)
		current["selected_controls_ref"] = identity
		area["prior"] = {"record": area["prior"]["record"], "identity_hash": content_hash(area["prior"]), "human_approval": area["prior"]["human_approval"]}
	payload["shared_current_controls"] = shared_controls
	for record in payload["source_records"].values():
		for name in ("source_path", "source_file_sha256", "source_slice_sha256", "normalization", "interpretation"):
			record.pop(name, None)
	payload["selected_valuation_development_context"].pop("market_source_rows", None)
	instruction = (
		"Independently review the complete MSFT model. The listed package decisions are "
		"identified carried decisions, not fresh reasoning. Reassess every area in the fixed "
		"order, especially dependencies changed by later schedules. Inspect all 11 statement "
		"periods, UFCF, terminal, claims, sensitivities, and source limitations. Do not choose "
		"paths, tools, formulas, or new numeric inputs. Request evidence only with 1-3 literal "
		"phrases. Consequential changes require analyst correction and independent recheck."
		" Cite at least one relevant FILING excerpt for every supported area. AREA-PACKET "
		"records identify historical decisions, not original sources. Explicitly reassess "
		"their outdated pending-package statements using the current all-period model. "
		"Financial estimates can be supported with explicit caveats; never relabel an "
		"estimate as a reported fact. Keep each area basis and concern concise."
	)
	return {
		"model": MODEL,
		"reasoning": {"effort": "high"},
		"service_tier": "default",
		"input": instruction
		+ "\n"
		+ json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")),
		"text": {
			"format": {
				"type": "json_schema",
				"name": "p10_whole_model_review",
				"strict": True,
				"schema": _strict_schema(WholeModelReview),
			}
		},
		"max_output_tokens": MAX_OUTPUT_TOKENS,
		"tools": [],
		"background": False,
	}


def prepare_from_documents(
	*,
	model: dict[str, Any],
	verification: dict[str, Any],
	calculated: dict[str, Any],
	source_manifest: dict[str, Any],
	valuation_context: dict[str, Any],
	prices: dict[str, Any],
	paths: dict[str, Path],
	run_dir: Path,
) -> dict[str, Any]:
	comparison = copy.deepcopy(calculated.get("snapshot"))
	if comparison:
		for row in comparison["statements"]["cashFlow"]:
			if row["row"] == 7 and row["label"] == "Noncash and operating-lease CFO adjustments":
				row["label"] = "Depreciation add-back"  # Only the corrected historical label differs.
	if comparison != verification.get("snapshot"):
		raise WorkflowError("STALE_CONTEXT: fresh calculation differs from accepted P9 evidence")
	provenance_bindings = {name: _sha256(path) for name, path in paths.items()}
	method_context = {
		"valuation_policy": model["valuation_policy"],
		"p9_formulas": verification["snapshot"]["p9"]["formulas"],
		"formula_authority": verification["formulaAuthority"],
		"decision_identities": {
			area: _decision_summary(model, area) for area in AREA_SEQUENCE
		},
	}
	bindings = {
		"selected_model": provenance_bindings["selected_model"],
		"source_manifest": provenance_bindings["source_manifest"],
		"valuation_review_context": provenance_bindings["valuation_review_context"],
		"financial_snapshot": content_hash(calculated["snapshot"]),
		"financial_formulas": _financial_formula_hash(Path(calculated.get("workbookPath") or ROOT / "data/build-guide-p9/parent-repair/model/p9-authority.xlsx")),
		"sensitivity_values_and_formula_context": content_hash(
			calculated.get("sensitivities", {})
		),
		**{
			name: value
			for name, value in provenance_bindings.items()
			if name.startswith("original_source:")
		},
	}
	bindings["method_financial_context"] = content_hash(method_context)
	context = build_compact_review_context(
		model, calculated, source_manifest, valuation_context, bindings
	)
	if context["mechanical_state"]["result"] != "PASS":
		raise WorkflowError("MECHANICAL_FAILURE: calculated model checks did not pass")
	request = build_whole_model_request(context)
	request_hash = content_hash(request)
	estimate = reservation(request, prices, today=date.fromisoformat(prices["observed_date"]))
	if estimate["input_token_upper_bound"] > prices["max_input_tokens"]:
		raise WorkflowError("Prepared request exceeds admitted input tier")
	if PROPOSED_P10_CAP_EUR > 5 - 0.39287515:
		raise WorkflowError("Proposed P10 cap exceeds the known remaining program ceiling")
	manifest = {
		"workflow_version": WORKFLOW_VERSION,
		"execution": "PREPARED",
		"bindings": bindings,
		"artifact_and_code_provenance": provenance_bindings,
		"input_paths": {name: str(path.resolve()) for name, path in paths.items()},
		"context_hash": content_hash(context),
		"prompt_version": PROMPT_VERSION,
		"schema_hash": content_hash(_strict_schema(WholeModelReview)),
		"settings_hash": content_hash(
			{
				"model": MODEL,
				"reasoning": "high",
				"service_tier": "default",
				"max_output_tokens": MAX_OUTPUT_TOKENS,
				"tools": [],
				"background": False,
				"max_retries": 0,
			}
		),
		"request_hash": request_hash,
		"request_utf8_bytes": len(_json_bytes(request)),
		"input_utf8_bytes": len(request["input"].encode("utf-8")),
		"context_utf8_bytes": len(_json_bytes(context)),
		"schema_utf8_bytes": len(_json_bytes(_strict_schema(WholeModelReview))),
		"reservation": estimate,
		"admitted_prices": prices,
		"call_policy": {
			"max_calls": MAX_P10_CALLS,
			"proposed_p10_cap_eur": PROPOSED_P10_CAP_EUR,
			"known_program_ceiling_eur": 5,
			"known_committed_before_p10_eur": 0.39287515,
			"protected_final_review_eur": 0.5,
			"only_whole_model_review_is_final_review": True,
			"one_analyst_revision_then_one_independent_recheck": True,
		},
	}
	queue = {
		"fixed_sequence": list(AREA_SEQUENCE),
		"areas": context["coverage"],
		"queue": [
			{
				"stage": "whole_model_review",
				"request_hash": request_hash,
				"status": "PREPARED_NOT_DISPATCHED",
				"final_review": True,
			}
		],
		"limits": {
			"literal_phrases_per_request": 3,
			"evidence_attempts_per_question": 3,
			"analyst_revisions": 1,
			"independent_rechecks": 1,
		},
	}
	status = {
		"execution": "PREPARED_NOT_DISPATCHED",
		"mechanical": "PASS",
		"coverage": "PENDING_12_AREA_REVIEW",
		"analytical": "PENDING_WHOLE_MODEL_REVIEW",
		"budget": "ESTIMATED_NOT_RESERVED",
		"human": "NOT_APPROVED",
	}
	_write_immutable(run_dir / "review-context.json", context)
	_write_immutable(run_dir / "requests" / "01-whole-model-review.request.json", request)
	_write_immutable(run_dir / "workflow-manifest.json", manifest)
	_write_immutable(run_dir / "review-queue.json", queue)
	_write_immutable(run_dir / "status.json", status)
	return {"manifest": manifest, "queue": queue, "status": status}


def _financial_formula_hash(workbook_path: Path) -> str:
	"""Formula identity excludes presentation, notes, paths and ZIP timestamps."""
	ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
	rid = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
	formulas = {}
	with ZipFile(workbook_path) as archive:
		rels = {node.attrib["Id"]: node.attrib["Target"] for node in ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))}
		for sheet in ElementTree.fromstring(archive.read("xl/workbook.xml")).findall("s:sheets/s:sheet", ns):
			name = sheet.attrib["name"]
			if name in {"Review", "Evidence", "Decisions"}:
				continue
			target = rels[sheet.attrib[rid]]
			path = target.lstrip("/") if target.startswith("/") else "xl/" + target
			root = ElementTree.fromstring(archive.read(path))
			formulas[name] = {cell.attrib["r"]: {"text": cell.find("s:f", ns).text, "attributes": cell.find("s:f", ns).attrib} for cell in root.findall(".//s:c", ns) if cell.find("s:f", ns) is not None and not (name == "SavedInputs" and re.match(r"[D-Z]", cell.attrib["r"]))}
	return content_hash(formulas)


def validate_current_context(run_dir: Path) -> None:
	"""Reject changed sources, financial inputs, formulas or workflow before dispatch."""
	manifest = _load(run_dir / "workflow-manifest.json")
	context = _load(run_dir / "review-context.json")
	if content_hash(context) != manifest["context_hash"] or context["bindings"] != manifest["bindings"]:
		raise WorkflowError("STALE_CONTEXT: prepared analytical context changed")
	paths = {name: Path(path) for name, path in manifest["input_paths"].items()}
	for name, expected in manifest["bindings"].items():
		if name in paths and _sha256(paths[name]) != expected:
			raise WorkflowError(f"STALE_CONTEXT: {name} changed")
	for name, expected in manifest.get("artifact_and_code_provenance", {}).items():
		if name.endswith("_code") and _sha256(paths[name]) != expected:
			raise WorkflowError(f"STALE_CONTEXT: {name} changed; prepare a fresh deterministic context")
	validate_frozen_inputs(paths["selected_model"], paths["accepted_p9_verification"], paths["source_manifest"], paths["valuation_review_context"])
	calculated = _load(paths["calculated_context"])
	if content_hash(calculated["snapshot"]) != manifest["bindings"]["financial_snapshot"]:
		raise WorkflowError("STALE_CONTEXT: calculated financial results changed")
	if content_hash(calculated.get("sensitivities", {})) != manifest["bindings"]["sensitivity_values_and_formula_context"]:
		raise WorkflowError("STALE_CONTEXT: sensitivity calculation changed")
	workbook_path = Path(calculated.get("workbookPath") or ROOT / "data/build-guide-p9/parent-repair/model/p9-authority.xlsx")
	if _financial_formula_hash(workbook_path) != manifest["bindings"]["financial_formulas"]:
		raise WorkflowError("STALE_CONTEXT: workbook financial formulas changed")
	request = _load(run_dir / "requests/01-whole-model-review.request.json")
	if content_hash(request) != manifest["request_hash"] or manifest["prompt_version"] != PROMPT_VERSION or manifest["schema_hash"] != content_hash(_strict_schema(WholeModelReview)):
		raise WorkflowError("STALE_CONTEXT: request, prompt or schema changed")
	if context["mechanical_state"]["result"] != "PASS":
		raise WorkflowError("MECHANICAL_FAILURE: prepared calculation failed")


def manifest_sources(source_manifest_path: Path) -> list[tuple[str, Path]]:
	manifest = _load(source_manifest_path)
	selected = {str(item["accession"]) for item in manifest["selected_filings"]}
	root = source_manifest_path.parent / "evidence" / "original_source"
	return [
		(accession, root / f"{accession}.txt")
		for accession in sorted(selected)
		if re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession)
		if (root / f"{accession}.txt").is_file()
	]


def retrieve_evidence(
	source_manifest_path: Path,
	request: EvidenceRequest,
	*,
	excerpt_radius: int = 240,
	max_excerpts: int = 6,
) -> dict[str, Any]:
	sources = manifest_sources(source_manifest_path)
	matches: list[dict[str, Any]] = []
	for phrase in request.literal_phrases:
		needle = phrase.encode("utf-8").lower()
		for source_id, path in sources:
			data = path.read_bytes()
			start = data.lower().find(needle)
			if start < 0:
				continue
			left = max(0, start - excerpt_radius)
			right = min(len(data), start + len(needle) + excerpt_radius)
			matches.append(
				{
					"source_id": f"SEC:{source_id}",
					"phrase": phrase,
					"byte_start": left,
					"byte_end": right,
					"excerpt": data[left:right].decode("utf-8", errors="replace"),
				}
			)
			if len(matches) >= max_excerpts:
				break
		if len(matches) >= max_excerpts:
			break
	resolved = bool(matches)
	return {
		"question_id": request.question_id,
		"followup_index": request.followup_index,
		"status": "RESOLVED" if resolved else "CAPPED_NO_RESULT"
		if request.followup_index == 2
		else "PENDING_FOLLOWUP",
		"matches": matches,
		"no_result_scope": None
		if resolved
		else {
			"searched_source_ids": [f"SEC:{source_id}" for source_id, _ in sources],
			"literal_phrases": request.literal_phrases,
			"scope": "manifest-selected local original_source files only",
		},
	}


def validate_review(
	value: dict[str, Any], *, source_allowlist: set[str], source_records: dict | None = None
) -> WholeModelReview:
	review = WholeModelReview.model_validate(value)
	for item in review.areas:
		if item.outcome == "supported_no_change" and not item.prior_decision_carried:
			raise WorkflowError(f"{item.area} did not identify the carried prior decision")
		assessed = set(item.changed_dependencies_assessed)
		if not set(DEPENDENCIES[item.area]) <= assessed or len(assessed) != len(item.changed_dependencies_assessed) or item.area in assessed:
			raise WorkflowError(f"{item.area} did not reassess its bound dependencies")
		if item.outcome in {"supported_no_change", "reassessment_required"} and not item.source_refs:
			raise WorkflowError(f"{item.area} outcome lacks supporting source refs")
		if source_records is not None and item.outcome in {"supported_no_change", "reassessment_required"} and not any(
				source_records.get(ref, {}).get("kind") == "pinned_filing_excerpt"
				and item.area in source_records[ref]["areas"]
				for ref in item.source_refs
			):
			raise WorkflowError(f"{item.area} lacks a relevant original filing excerpt")
	unknown = {
		ref for area in review.areas for ref in area.source_refs if ref not in source_allowlist
	}
	if unknown:
		raise WorkflowError(f"Review contains unsupported source refs: {sorted(unknown)}")
	return review


def validate_correction(
	value: dict[str, Any],
	*,
	options: dict[str, list[dict[str, Any]]],
	source_allowlist: set[str],
) -> AnalystCorrection:
	correction = AnalystCorrection.model_validate(value)
	selection_ids = {item["selection_id"] for item in options[correction.area]}
	if correction.selection_id not in selection_ids and correction.selection_id is not None:
		raise WorkflowError("Analyst correction selected an unbound method/input option")
	if any(ref not in source_allowlist for ref in correction.source_refs):
		raise WorkflowError("Analyst correction contains unsupported source refs")
	return correction


def derive_status(
	review: WholeModelReview | None,
	*,
	budget_state: str = "AVAILABLE",
	mechanical_state: str = "PASS",
) -> dict[str, str]:
	status = {
		"execution": "AWAITING_WHOLE_MODEL_REVIEW",
		"mechanical": mechanical_state,
		"coverage": "PENDING_12_AREA_REVIEW",
		"analytical": "PENDING_WHOLE_MODEL_REVIEW",
		"budget": budget_state,
		"human": "NOT_APPROVED",
	}
	if mechanical_state != "PASS" or budget_state in {
		"EXHAUSTED",
		"STALE",
		"USAGE_UNKNOWN",
	}:
		status["execution"] = "BLOCKED"
		return status
	if review is None:
		return status
	outcomes = {item.outcome for item in review.areas}
	status["coverage"] = (
		"COMPLETE"
		if outcomes <= {"supported_no_change"}
		else "PENDING_EVIDENCE_OR_REASSESSMENT"
	)
	status["analytical"] = {
		"accept": "REVIEW_ACCEPTED",
		"revise": "REVISION_REQUIRED",
		"reject": "REJECTED",
	}[review.verdict]
	status["execution"] = (
		"ANALYTICAL_COMPLETE"
		if review.verdict == "accept" and status["coverage"] == "COMPLETE"
		else "ACTION_REQUIRED"
	)
	return status


def _followup_request(
	*,
	stage: Literal["analyst_correction", "independent_recheck"],
	context: dict[str, Any],
	prior: dict[str, Any],
) -> dict[str, Any]:
	if stage == "analyst_correction":
		instruction = (
			"Address the reviewer's required revision once. Select only an application-provided "
			"closed selection ID. Do not emit a new number, formula, path, tool, or code. If no "
			"supported selection resolves the concern, return unresolved, capability_gap, or a "
			"bounded literal evidence request. The prior effective decision remains in force until "
			"an independent recheck accepts this correction."
		)
		response_model: type[BaseModel] = AnalystCorrection
		name = "p10_analyst_correction"
	else:
		instruction = (
			"Independently recheck the single bounded analyst correction against the complete "
			"financial context and original review. Accept or reject it. Do not revise the value, "
			"select another option, or request another correction round."
		)
		response_model = IndependentRecheck
		name = "p10_independent_recheck"
	target = next(item for item in prior["review"]["areas"] if item["outcome"] == "reassessment_required")
	references = set(target["source_refs"]) | set(prior.get("analyst_correction", {}).get("source_refs", []))
	financial_context = {
		key: context[key] for key in ("case", "measurement_date", "information_cutoff", "basis", "bindings", "statements_all_11_periods", "schedules_and_bridges", "valuation", "mechanical_state")
	}
	financial_context["target_area"] = next(item for item in context["coverage"] if item["area"] == target["area"])
	financial_context["correction_options"] = {target["area"]: context["correction_options"][target["area"]]}
	financial_context["source_records"] = {key: value for key, value in context["source_records"].items() if key in references or (target["area"] == "dcf_terminal" and key.startswith("MKT-"))}
	if target["area"] in {"dcf_terminal", "taxes"}:
		financial_context["selected_valuation_development_context"] = context["selected_valuation_development_context"]
	payload = {
		"workflow_version": WORKFLOW_VERSION,
		"stage": stage,
		"bindings": context["bindings"],
		"financial_context": financial_context,
		"prior": prior,
	}
	return {
		"model": MODEL,
		"reasoning": {"effort": "high"},
		"service_tier": "default",
		"input": instruction
		+ "\n"
		+ json.dumps(payload, sort_keys=True, ensure_ascii=False),
		"text": {
			"format": {
				"type": "json_schema",
				"name": name,
				"strict": True,
				"schema": _strict_schema(response_model),
			}
		},
		"max_output_tokens": 8000,
		"tools": [],
		"background": False,
	}


def _apply_closed_selection(
	model: dict[str, Any], area: str, selection_id: str
) -> dict[str, Any]:
	updated = copy.deepcopy(model)
	choice = CORRECTION_CHOICES.get(area, {}).get(selection_id)
	if choice is None:
		raise WorkflowError("Correction does not select a consequential closed control")
	control = choice["control"]
	value = choice["value"]
	if control == "cash_ppe_additions_rate":
		parameter = next(
			(item for item in updated["candidate"]["parameters"] if item["name"] == control),
			None,
		)
		if parameter is None:
			raise WorkflowError("Bound PP&E correction control is missing")
		parameter["value"] = value
	elif control == "other_investment_value_multiplier":
		updated["other_balances_forecast"]["inputs"][control] = value
		updated["other_balances_forecast"]["candidate"][control] = value
	else:
		updated["valuation_policy"][control] = value
	updated["_p10_correction"] = {
		"base_model_sha256": EXPECTED_MODEL_SHA256,
		"area": area,
		"selection_id": selection_id,
		"control": control,
		"value": value,
	}
	return updated


def _candidate_review_context(calculated: dict[str, Any]) -> dict[str, Any]:
	snapshot = calculated["snapshot"]
	return {
		"status": calculated["status"],
		"selection_id": calculated["selectionId"],
		"model_sha256": calculated["correctionModelSha256"],
		"financial_formula_hash": _financial_formula_hash(Path(calculated["workbookPath"])),
		"all_11_period_statements": snapshot["statements"],
		"checks": snapshot["checks"],
		"all_period_status": snapshot["allPeriodStatus"],
		"p9": {key: value for key, value in snapshot["p9"].items() if key != "formulas"},
		"p9_formula_context_hash": content_hash(snapshot["p9"]["formulas"]),
		"sensitivity_values_and_formula_hash": {
			name: [
				{
					"row": row["row"],
					"values": row["values"],
					"formula_hash": content_hash(row["formulas"]),
				}
				for row in rows
			]
			for name, rows in calculated.get("sensitivities", {}).items()
		},
	}


def checkpoint_whole_model_review(
	run_dir: Path, value: dict[str, Any]
) -> dict[str, Any]:
	validate_current_context(run_dir)
	manifest = _load(run_dir / "workflow-manifest.json")
	context = _load(run_dir / "review-context.json")
	request = _load(run_dir / "requests" / "01-whole-model-review.request.json")
	if content_hash(request) != manifest["request_hash"]:
		raise WorkflowError("STALE_CONTEXT: prepared whole-model request hash changed")
	review = validate_review(value, source_allowlist=set(context["source_ref_allowlist"]), source_records=context["source_records"])
	review_value = review.model_dump(mode="json")
	_write_immutable(
		run_dir / "results" / "01-whole-model-review.structured.json", review_value
	)
	evidence = [
		{"area": item.area, "request": item.evidence_request.model_dump(mode="json")}
		for item in review.areas
		if item.evidence_request is not None
	]
	mechanical = context["mechanical_state"]["result"]
	transition: dict[str, Any] = {
		"review_hash": content_hash(review_value),
		"verdict": review.verdict,
		"effective_prior_decisions_preserved": True,
		"evidence_queue": evidence,
		"status": derive_status(review, mechanical_state=mechanical),
	}
	reassessment = [item for item in review.areas if item.outcome == "reassessment_required"]
	other_open = [
		item
		for item in review.areas
		if item.outcome not in {"supported_no_change", "reassessment_required"}
	]
	if (
		review.verdict == "revise"
		and not evidence
		and not other_open
		and len(reassessment) == 1
		and mechanical == "PASS"
	):
		followup = _followup_request(
			stage="analyst_correction", context=context, prior={"review": review_value}
		)
		_write_immutable(
			run_dir / "requests" / "02-analyst-correction.request.json", followup
		)
		transition["next"] = {
			"stage": "analyst_correction",
			"request_hash": content_hash(followup),
			"final_review": False,
		}
	elif evidence:
		transition["next"] = {"stage": "bounded_evidence", "final_review": False}
	else:
		transition["next"] = None
	_write_immutable(run_dir / "transitions" / "01-after-review.json", transition)
	if transition["status"]["execution"] == "ANALYTICAL_COMPLETE":
		_write_immutable(run_dir / "effective-model.json", {"model_path": manifest["input_paths"]["selected_model"], "model_sha256": manifest["bindings"]["selected_model"], "review_path": str((run_dir / "results/01-whole-model-review.structured.json").resolve()), "review_hash": content_hash(review_value), "status": "SYSTEM_REVIEWED", "human_approval": False})
	return transition


def checkpoint_analyst_correction(
	run_dir: Path, value: dict[str, Any]
) -> dict[str, Any]:
	context = _load(run_dir / "review-context.json")
	review = _load(run_dir / "results" / "01-whole-model-review.structured.json")
	if review.get("verdict") != "revise":
		raise WorkflowError("Analyst correction requires a revise verdict")
	correction = validate_correction(
		value,
		options=context["correction_options"],
		source_allowlist=set(context["source_ref_allowlist"]),
	)
	reassessment = [
		item for item in review["areas"] if item["outcome"] == "reassessment_required"
	]
	if len(reassessment) != 1 or correction.area != reassessment[0]["area"]:
		raise WorkflowError("Analyst correction does not match the single bounded review target")
	correction_value = correction.model_dump(mode="json")
	_write_immutable(
		run_dir / "results" / "02-analyst-correction.structured.json",
		correction_value,
	)
	if correction.outcome != "select":
		transition = {"correction_hash": content_hash(correction_value), "effective_prior_decisions_preserved": True, "next": None, "status": {"execution": "ACTION_REQUIRED", "mechanical": "PASS", "coverage": correction.outcome.upper(), "analytical": "CORRECTION_NOT_ADOPTED", "budget": "AVAILABLE", "human": "NOT_APPROVED"}, "requested_evidence": correction_value.get("follow_up_request")}
		_write_immutable(run_dir / "transitions/02-after-correction.json", transition)
		return transition
	candidate_context: dict[str, Any]
	if correction.selection_id and correction.selection_id.endswith(
		":retain_effective_decision"
	):
		candidate_context = {
			"status": "BASE_CALCULATION_REUSED",
			"selection_id": correction.selection_id,
			"mechanical": "PASS",
			"financial_snapshot_hash": context["bindings"]["financial_snapshot"],
		}
	else:
		if correction.selection_id is None:
			raise WorkflowError("Unresolved correction cannot proceed to independent recheck")
		candidate_model = _apply_closed_selection(
			_load(ROOT / "data/build-guide-p9/parent-repair/model/selected-model.json"),
			correction.area,
			correction.selection_id,
		)
		candidate_model_path = run_dir / "candidates" / "02-corrected-model.json"
		_write_immutable(candidate_model_path, candidate_model)
		candidate_output = run_dir / "candidates" / "02-corrected-calculation.json"
		candidate_workbook = run_dir / "candidates" / "02-corrected-model.xlsx"
		try:
			_run_adapter(candidate_model_path, ROOT / "data/build-guide-p9/parent-repair/model/p9-verification.json", candidate_output, candidate_workbook, command="correction")
		except Exception as exc:
			raise WorkflowError("MECHANICAL_FAILURE: candidate build failed; prior effective model preserved") from exc
		candidate_context = _candidate_review_context(_load(candidate_output))
		if candidate_context["model_sha256"] == EXPECTED_MODEL_SHA256:
			raise WorkflowError("Consequential correction did not change the bound model")
		_write_immutable(
			run_dir / "candidates" / "02-corrected-review-context.json",
			candidate_context,
		)
	recheck = _followup_request(
		stage="independent_recheck",
		context=context,
		prior={
			"review": review,
			"analyst_correction": correction_value,
			"recalculated_candidate": candidate_context,
		},
	)
	_write_immutable(
		run_dir / "requests" / "03-independent-recheck.request.json", recheck
	)
	transition = {
		"correction_hash": content_hash(correction_value),
		"effective_prior_decisions_preserved": True,
		"new_selection_not_yet_adopted": correction.outcome == "select",
		"candidate_recalculated_before_recheck": candidate_context["status"]
		in {"PASS", "BASE_CALCULATION_REUSED"},
		"next": {
			"stage": "independent_recheck",
			"request_hash": content_hash(recheck),
			"final_review": False,
		},
		"status": {
			"execution": "AWAITING_INDEPENDENT_RECHECK",
			"mechanical": "PASS",
			"coverage": "PENDING_CORRECTION_RECHECK",
			"analytical": "REVISION_NOT_ADOPTED",
			"budget": "AVAILABLE",
			"human": "NOT_APPROVED",
		},
	}
	_write_immutable(run_dir / "transitions" / "02-after-correction.json", transition)
	return transition


def checkpoint_independent_recheck(
	run_dir: Path, value: dict[str, Any]
) -> dict[str, Any]:
	validate_current_context(run_dir)
	correction = _load(run_dir / "results" / "02-analyst-correction.structured.json")
	recheck = IndependentRecheck.model_validate(value)
	if recheck.area != correction["area"] or recheck.selection_id != correction["selection_id"]:
		raise WorkflowError("Independent recheck changed the analyst correction")
	if recheck.verdict == "accept" and not all(
		(
			recheck.source_valid,
			recheck.period_valid,
			recheck.method_valid,
			recheck.no_double_count,
			recheck.cross_schedule_concerns_resolved,
		)
	):
		raise WorkflowError("Independent recheck cannot accept failed controls")
	value = recheck.model_dump(mode="json")
	_write_immutable(
		run_dir / "results" / "03-independent-recheck.structured.json", value
	)
	review = _load(run_dir / "results" / "01-whole-model-review.structured.json")
	other_areas_closed = all(
		item["outcome"] == "supported_no_change"
		for item in review["areas"]
		if item["area"] != recheck.area
	)
	validated = (
		recheck.verdict == "accept"
		and correction["outcome"] == "select"
		and other_areas_closed
		and recheck.cross_schedule_concerns_resolved
	)
	retains_prior = validated and str(correction["selection_id"]).endswith(
		":retain_effective_decision"
	)
	adopted = validated and not retains_prior
	if adopted:
		candidate_path = run_dir / "candidates/02-corrected-model.json"
		calculated = _load(run_dir / "candidates/02-corrected-calculation.json")
		if _sha256(candidate_path) != calculated["correctionModelSha256"] or calculated["status"] != "PASS" or calculated["snapshot"]["allPeriodStatus"] != "PASS" or calculated["snapshot"]["p9"]["valuationGate"] != "PASS":
			raise WorkflowError("MECHANICAL_FAILURE: accepted correction has no matching valid candidate")
	transition = {
		"recheck_hash": content_hash(value),
		"correction_adopted": adopted,
		"effective_selection_id": correction["selection_id"] if validated else None,
		"effective_prior_decision_retained": retains_prior or not validated,
		"further_revision_allowed": False,
		"status": {
			"execution": "RECHECK_COMPLETE" if validated else "BLOCKED",
			"mechanical": "PASS",
			"coverage": "COMPLETE" if validated else "INCOMPLETE",
			"analytical": "RECHECK_ACCEPTED" if validated else "REJECTED",
			"budget": "AVAILABLE",
			"human": "NOT_APPROVED",
		},
	}
	_write_immutable(run_dir / "transitions" / "03-after-recheck.json", transition)
	if validated:
		manifest = _load(run_dir / "workflow-manifest.json")
		model_path = run_dir / "candidates/02-corrected-model.json" if adopted else Path(manifest["input_paths"]["selected_model"])
		_write_immutable(run_dir / "effective-model.json", {"model_path": str(model_path.resolve()), "model_sha256": _sha256(model_path), "review_path": str((run_dir / "results/03-independent-recheck.structured.json").resolve()), "review_hash": content_hash(value), "selection_id": correction["selection_id"], "status": "SYSTEM_REVIEWED", "human_approval": False})
	return transition


def checkpoint_evidence(
	run_dir: Path, source_manifest_path: Path, request: EvidenceRequest
) -> dict[str, Any]:
	question_key = content_hash({"question_id": request.question_id})[:16]
	prior = sorted((run_dir / "evidence").glob(f"{question_key}-*.json"))
	if request.followup_index != len(prior):
		raise WorkflowError("Evidence follow-up index is stale or out of sequence")
	if len(prior) >= 3:
		raise WorkflowError("Evidence request reached its initial-plus-two-followups cap")
	result = retrieve_evidence(source_manifest_path, request)
	_write_immutable(
		run_dir
		/ "evidence"
		/ f"{question_key}-{request.followup_index}.json",
		result,
	)
	return result


def _run_adapter(
	model_path: Path,
	verification_path: Path,
	output_path: Path,
	workbook_path: Path,
	*,
	command: Literal["snapshot", "correction"] = "snapshot",
) -> None:
	command = [
		"node",
		str(ROOT / "scripts" / "spreadsheet_compat" / "run-analysis.mjs"),
		command,
		str(model_path),
		str(verification_path),
		str(output_path),
		str(workbook_path),
	]
	completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
	if completed.returncode != 0:
		raise WorkflowError(
			f"P10 calculation adapter failed ({completed.returncode}): {completed.stderr.strip()}"
		)


def run_stage(
	*,
	run_dir: Path,
	stage: Literal["whole_model_review", "analyst_correction", "independent_recheck"],
	budget_path: Path,
	prices: dict[str, Any],
	client: Any = None,
) -> dict[str, Any]:
	from smrik_fund.analysis_transport import dispatch_request

	validate_current_context(run_dir)
	request_name = {
		"whole_model_review": "01-whole-model-review.request.json",
		"analyst_correction": "02-analyst-correction.request.json",
		"independent_recheck": "03-independent-recheck.request.json",
	}[stage]
	request = _load(run_dir / "requests" / request_name)
	if stage != "whole_model_review":
		previous = "01-after-review.json" if stage == "analyst_correction" else "02-after-correction.json"
		transition = _load(run_dir / "transitions" / previous)
		if content_hash(request) != (transition.get("next") or {}).get("request_hash"):
			raise WorkflowError("STALE_CONTEXT: follow-up request differs from the queued stage")
	structured, metadata = dispatch_request(
		request,
		run_dir=run_dir,
		stage=stage,
		budget_path=budget_path,
		prices=prices,
		final_review=stage == "whole_model_review",
		client=client,
	)
	transition = {
		"whole_model_review": checkpoint_whole_model_review,
		"analyst_correction": checkpoint_analyst_correction,
		"independent_recheck": checkpoint_independent_recheck,
	}[stage](run_dir, structured)
	return {"transport": metadata, "transition": transition}


def current_status(run_dir: Path) -> dict[str, Any]:
	try:
		validate_current_context(run_dir)
	except (ValueError, KeyError, OSError) as exc:
		return {"source": "current context validation", "status": derive_status(None, budget_state="STALE", mechanical_state="NOT_CURRENTLY_VERIFIED"), "reason": str(exc)}
	terminal = run_dir / "analysis-run/terminal.json"
	if terminal.exists():
		return {"source": str(terminal), **_load(terminal)}
	for name in (
		"03-after-recheck.json",
		"02-after-correction.json",
		"01-after-review.json",
	):
		path = run_dir / "transitions" / name
		if path.exists():
			return {"source": str(path), "status": _load(path)["status"]}
	path = run_dir / "status.json"
	return {"source": str(path), "status": _load(path)}


def prepare_cli(args: argparse.Namespace) -> dict[str, Any]:
	run_dir = args.run_dir.resolve()
	if (run_dir / "workflow-manifest.json").exists():
		raise WorkflowError("Existing P10 run must be resumed; prepare never overwrites it")
	model, verification, source_manifest, valuation_context = validate_frozen_inputs(
		args.model, args.verification, args.source_manifest, args.valuation_context
	)
	calculated_path = run_dir / "calculated-context.json"
	workbook_path = run_dir / "p10-calculated.xlsx"
	_run_adapter(args.model, args.verification, calculated_path, workbook_path)
	calculated = _load(calculated_path)
	paths = {
		"selected_model": args.model,
		"accepted_p9_verification": args.verification,
		"source_manifest": args.source_manifest,
		"valuation_review_context": args.valuation_context,
		"price_snapshot": args.prices,
		"calculated_context": calculated_path,
		"analysis_workflow_code": Path(__file__).resolve(),
		"calculation_adapter_code": ROOT
		/ "scripts"
		/ "spreadsheet_compat"
		/ "run-analysis.mjs",
		"analysis_transport_code": ROOT / "src" / "smrik_fund" / "analysis_transport.py",
		"analysis_run_code": ROOT / "src" / "smrik_fund" / "analysis_run.py",
	}
	for accession, path in manifest_sources(args.source_manifest):
		paths[f"original_source:{accession}"] = path
	return prepare_from_documents(
		model=model,
		verification=verification,
		calculated=calculated,
		source_manifest=source_manifest,
		valuation_context=valuation_context,
		prices=_load(args.prices),
		paths=paths,
		run_dir=run_dir,
	)


def build_parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(description=__doc__)
	subparsers = parser.add_subparsers(dest="command", required=True)
	prepare = subparsers.add_parser("prepare")
	prepare.add_argument(
		"--model",
		type=Path,
		default=ROOT / "data/build-guide-p9/parent-repair/model/selected-model.json",
	)
	prepare.add_argument(
		"--verification",
		type=Path,
		default=ROOT / "data/build-guide-p9/parent-repair/model/p9-verification.json",
	)
	prepare.add_argument(
		"--source-manifest",
		type=Path,
		default=ROOT / "data/build-guide-p2-r2/MSFT/source_manifest.json",
	)
	prepare.add_argument(
		"--valuation-context",
		type=Path,
		default=ROOT / "data/build-guide-p10/parent-preflight/financial-review-context-r2.json",
	)
	prepare.add_argument(
		"--prices",
		type=Path,
		default=ROOT / "data/build-guide-p10/parent-preflight/sol-price-snapshot.json",
	)
	prepare.add_argument(
		"--run-dir", type=Path, default=ROOT / "data/build-guide-p10/parent-final-r4"
	)
	retrieve = subparsers.add_parser("retrieve")
	retrieve.add_argument("--source-manifest", type=Path, required=True)
	retrieve.add_argument("--request", type=Path, required=True)
	retrieve.add_argument("--run-dir", type=Path, required=True)
	run = subparsers.add_parser("run")
	run.add_argument(
		"--stage",
		choices=("whole_model_review", "analyst_correction", "independent_recheck"),
		required=False,
	)
	run.add_argument("--run-dir", type=Path, required=True)
	run.add_argument(
		"--budget", type=Path, default=ROOT / "data/build-guide-api-budget.json"
	)
	run.add_argument(
		"--prices",
		type=Path,
		default=ROOT / "data/build-guide-p10/parent-preflight/sol-price-snapshot.json",
	)
	status = subparsers.add_parser("status")
	status.add_argument("--run-dir", type=Path, required=True)
	return parser


def main() -> None:
	args = build_parser().parse_args()
	if args.command == "prepare":
		result = prepare_cli(args)
	elif args.command == "retrieve":
		request = EvidenceRequest.model_validate(_load(args.request))
		result = checkpoint_evidence(
			args.run_dir.resolve(), args.source_manifest.resolve(), request
		)
	elif args.command == "run":
		if args.stage:
			result = run_stage(run_dir=args.run_dir.resolve(), stage=args.stage, budget_path=args.budget.resolve(), prices=_load(args.prices))
		else:
			from smrik_fund.analysis_run import run_analysis

			result = run_analysis(args.run_dir.resolve(), args.budget.resolve(), _load(args.prices))
	else:
		result = current_status(args.run_dir.resolve())
	print(json.dumps(result, indent=2))
	if args.command == "run" and not args.stage and result["status"]["execution"] in {"BLOCKED", "ACTION_REQUIRED"}:
		raise SystemExit(2)


if __name__ == "__main__":
	main()
