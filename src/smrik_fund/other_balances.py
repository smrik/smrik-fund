"""P8D investments, finite-lived intangibles, goodwill and residual balances.

The module is the application-owned boundary for the last non-operating asset
slice.  Source facts and arithmetic live here; the linked workbook remains the
calculation authority when a workbook builder is supplied.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import subprocess
import time
from datetime import date
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from openai.lib._pydantic import to_strict_json_schema
from pydantic import BaseModel, ConfigDict, Field, model_validator

from smrik_fund.analysis_budget import (
    content_hash,
    record_outcome,
    reservation,
    reserve_call,
)

CASE = "MSFT"
INFORMATION_CUTOFF = "2026-04-30"
MEASUREMENT_DATE = "2026-03-31"
MODEL = "gpt-5.6-luna"
ENDPOINT_URL = "https://api.openai.com/v1/responses"
TASK_ID = "p8d-msft-other-balances"
MAX_ATTEMPTS = 6
MAX_COMMITTED_EUR = 0.50
REASONING_EFFORT = "medium"
MAX_OUTPUT_TOKENS = 12_000
INITIAL_ANALYST_INSTRUCTION = (
    "Select a complete bounded P8D proposal under the supplied contract. "
    "Preserve source claims and unknowns."
)
SCHEMA_VERSION = "p8d-other-balances-proposal-r1"
PROMPT_VERSION = "p8d-other-balances-reasoning-r2"
METHOD_CATALOG_VERSION = "p8d-other-balances-methods-r1"
METHOD_ID = "investment_intangible_residual_rollforward"
METHOD_VERSION = "v1"
TOLERANCE = 1e-8
PERIODS = (
    "FY2026_STUB", "FY2027", "FY2028", "FY2029", "FY2030", "FY2031",
    "FY2032", "FY2033", "FY2034", "FY2035", "FY2036",
)


class OtherBalancesError(ValueError):
    """P8D source, proposal, calculation or workflow error."""


class OtherBalancesSensitivity(BaseModel):
    """One bounded sensitivity row returned by the reasoning provider."""

    model_config = ConfigDict(extra="forbid")

    parameter: str = Field(min_length=1)
    low: float
    base: float
    high: float

    @model_validator(mode="before")
    @classmethod
    def _reject_coercible_numbers(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        for name in ("low", "base", "high"):
            if name not in value:
                continue
            raw = value[name]
            if isinstance(raw, bool) or not isinstance(raw, int | float):
                raise ValueError(f"{name} must be numeric")
            if isinstance(raw, float) and not math.isfinite(raw):
                raise ValueError(f"{name} must be finite")
        return value


class OtherBalancesProposal(BaseModel):
    """Small strict judgment surface; source amounts remain application-owned."""

    model_config = ConfigDict(extra="forbid")

    outcome: Literal["propose_forecast", "unresolved", "capability_gap"]
    method_id: Literal["investment_intangible_residual_rollforward"] | None = None
    method_version: Literal["v1"] | None = None
    other_investment_value_multiplier: float | None = Field(default=None, ge=0, le=10)
    cash_income_yield: float | None = Field(default=None, ge=0, le=0.10)
    intangible_tail_life_years: Literal[6, 10, 15] | None = None
    goodwill_impairment: float | None = Field(default=None, ge=0)
    unfunded_commitment_value_fraction: float | None = Field(default=None, ge=0, le=1)
    legal_stress: float | None = Field(default=None, ge=0, le=400)
    incremental_net_dta_value: float | None = Field(default=None, ge=0, le=26273)
    unrealized_investment_gain: float | None = Field(default=None, ge=0)
    future_acquisitions: Literal[0] | None = None
    commitment_timing: Literal["FY2026_STUB_END"] | None = None
    evidence_refs: list[str] = Field(min_length=1)
    rationale: str = Field(min_length=1)
    alternatives: list[str]
    uncertainty: list[str]
    sensitivities: list[OtherBalancesSensitivity]
    follow_up_request: str | None

    @model_validator(mode="before")
    @classmethod
    def _reject_coercible_numbers(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        numeric = (
            "other_investment_value_multiplier", "cash_income_yield", "goodwill_impairment",
            "unfunded_commitment_value_fraction", "legal_stress", "incremental_net_dta_value",
            "unrealized_investment_gain",
        )
        for name in numeric:
            raw = value.get(name)
            if raw is None:
                continue
            if isinstance(raw, bool) or not isinstance(raw, int | float):
                raise ValueError(f"{name} must be numeric")
            if isinstance(raw, float) and not math.isfinite(raw):
                raise ValueError(f"{name} must be finite")
        return value

    @model_validator(mode="after")
    def _shape(self) -> OtherBalancesProposal:
        fixed = (
            "method_id", "method_version", "other_investment_value_multiplier", "cash_income_yield",
            "intangible_tail_life_years", "goodwill_impairment", "unfunded_commitment_value_fraction",
            "legal_stress", "incremental_net_dta_value", "unrealized_investment_gain",
            "future_acquisitions", "commitment_timing",
        )
        if self.outcome != "propose_forecast":
            if not self.follow_up_request:
                raise ValueError("non-forecast outcome requires follow_up_request")
            populated = [name for name in fixed if getattr(self, name) is not None]
            if populated:
                raise ValueError(f"non-forecast fields must be null: {', '.join(populated)}")
            return self
        missing = [name for name in fixed if getattr(self, name) is None]
        if missing:
            raise ValueError(f"forecast proposal missing fields: {', '.join(missing)}")
        if self.follow_up_request is not None:
            raise ValueError("forecast proposal follow_up_request must be null")
        if self.goodwill_impairment is not None and self.goodwill_impairment > 119661:
            raise ValueError("goodwill impairment exceeds opening goodwill")
        return self


class OtherBalancesReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["accept", "revise", "reject"]
    evidence_strength: Literal["strong", "mixed", "weak"]
    method_valid: bool
    source_valid: bool
    period_valid: bool
    investment_bridge_valid: bool
    intangible_bridge_valid: bool
    cash_noncash_separated: bool
    residual_coverage_valid: bool
    tax_effect_contained: bool
    no_double_count: bool
    concerns: list[str] = Field(min_length=1)
    required_revision: str | None
    target: Literal["none", "investment_value", "yield", "tail_life", "impairment", "commitment", "dta"]
    rationale: str = Field(min_length=1)


def _number(value: Any, name: str, *, allow_zero: bool = True) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise OtherBalancesError(f"{name} is missing/non-numeric")
    if not allow_zero and value == 0:
        raise OtherBalancesError(f"{name} must be nonzero")
    return float(value)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_table(path: Path | None = None) -> Path:
    return path or Path(__file__).resolve().parents[2] / "Lunacy/runs/three-statement-dcf/phases/other-balances/P8D-source-table-R1.csv"


def _source_calibration(path: Path | None = None) -> Path:
    return path or Path(__file__).resolve().parents[2] / "data/build-guide-p8d/integrity-r2/source-calibration.json"


def _read_source_table(path: Path | None = None) -> list[dict[str, str]]:
    table = _source_table(path)
    if not table.exists():
        raise OtherBalancesError(f"P8D source table is missing: {table}")
    with table.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _read_source_calibration(path: Path | None = None) -> dict[str, Any]:
    calibration_path = _source_calibration(path)
    if not calibration_path.exists():
        raise OtherBalancesError(f"P8D source calibration is missing: {calibration_path}")
    try:
        calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise OtherBalancesError(f"P8D source calibration is invalid JSON: {calibration_path}") from exc
    if calibration.get("schema_version") != "p8d-source-calibration-r2":
        raise OtherBalancesError("unsupported P8D source calibration schema")
    if calibration.get("case") != CASE or calibration.get("measurement_date") != MEASUREMENT_DATE:
        raise OtherBalancesError("P8D source calibration case/date does not match the accepted packet")
    values = calibration.get("values")
    if not isinstance(values, dict):
        raise OtherBalancesError("P8D source calibration values are missing")
    required = (
        "identified_long_term_debt_investments",
        "other_investment_pool",
        "embedded_ttm_intangible_amortization",
        "unidentified_dna_other",
    )
    for name in required:
        if name not in values:
            raise OtherBalancesError(f"P8D source calibration value {name} is missing")
    for name, item in values.items():
        if not isinstance(item, dict):
            raise OtherBalancesError(f"P8D source calibration entry is malformed: {name}")
        _number(item.get("value"), f"source calibration {name}")
    return calibration


def _packet_fact(packet_facts: dict[str, Any], name: str) -> float:
    fact = packet_facts.get(name)
    if not isinstance(fact, dict):
        raise OtherBalancesError(f"accepted P8C fact is missing: {name}")
    return _number(fact.get("value"), f"P8C fact {name}")


def _require_equal(left: float, right: float, label: str) -> float:
    if abs(left - right) > TOLERANCE:
        raise OtherBalancesError(f"P8D source mismatch for {label}: {left} != {right}")
    return left


def _parse_intangible_schedule(raw: str | None, *, expected_total: float) -> dict[str, Any]:
    if not raw:
        raise OtherBalancesError("P8D intangible future amortization schedule is missing")
    matches = {key: float(value) for key, value in re.findall(r"(2026_stub|FY2027|FY2028|FY2029|FY2030|thereafter|total)=([0-9]+(?:\.[0-9]+)?)", raw)}
    required = ("2026_stub", "FY2027", "FY2028", "FY2029", "FY2030", "thereafter", "total")
    if any(key not in matches for key in required):
        raise OtherBalancesError("P8D intangible schedule must contain stub, FY2027-FY2030, thereafter and total")
    explicit = [matches[key] for key in ("FY2027", "FY2028", "FY2029", "FY2030")]
    if abs(sum([matches["2026_stub"], *explicit, matches["thereafter"]]) - matches["total"]) > TOLERANCE:
        raise OtherBalancesError("P8D intangible schedule does not add to its reported total")
    if abs(matches["total"] - expected_total) > TOLERANCE:
        raise OtherBalancesError("P8D intangible schedule total does not tie opening carrying value")
    return {"stub": matches["2026_stub"], "annual_explicit": explicit, "tail": matches["thereafter"], "total": matches["total"], "raw": raw}


def _p8c_accepted(p8c: dict[str, Any]) -> None:
    decision = p8c.get("p8c_decision") or p8c.get("equity_decision") or p8c.get("decision") or {}
    status = decision.get("status")
    if status not in {"SYSTEM_REVIEWED_PROVISIONAL", "REVIEW_REQUIRED"}:
        raise OtherBalancesError("P8C input is not a valid accepted/system-reviewed model")
    if p8c.get("equity_forecast") is None:
        raise OtherBalancesError("P8C equity forecast is missing")


def _row_value(row: dict[str, str] | None, name: str, *, allow_missing: bool = False) -> float | None:
    raw = (row or {}).get("reported_value", "")
    if not str(raw).strip():
        if allow_missing:
            return None
        raise OtherBalancesError(f"P8D source value is missing: {name}")
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        if allow_missing:
            return None
        raise OtherBalancesError(f"P8D source value is nonnumeric: {name}") from exc
    if not math.isfinite(value):
        raise OtherBalancesError(f"P8D source value is nonfinite: {name}")
    return value


def build_evidence_packet(
    p8c: dict[str, Any],
    source_table: Path | None = None,
    source_calibration: Path | None = None,
) -> dict[str, Any]:
    """Build a source-locked packet from the immutable P8D table and P8C model.

    The packet carries facts and selected-input metadata only.  Mog owns all
    period calculations once this packet is compiled into the linked workbook.
    """
    _p8c_accepted(p8c)
    path = _source_table(source_table)
    calibration_path = _source_calibration(source_calibration)
    calibration = _read_source_calibration(calibration_path)
    rows = _read_source_table(path)
    by_name = {row.get("line_item", ""): row for row in rows}

    def value(name: str, missing: bool = False) -> float | None:
        return _row_value(by_name.get(name), name, allow_missing=missing)

    src = {
        row.get("line_item", ""): {
            "value": _row_value(row, row.get("line_item", ""), allow_missing=True),
            "unit": row.get("unit"),
            "period": row.get("period"),
            "sign": row.get("reported_sign"),
            "source_locator": row.get("source_locator"),
            "source_identity": row.get("source_identity"),
            "account_containment": row.get("account_containment"),
            "limitation": row.get("limitation"),
        }
        for row in rows
    }
    packet_facts = p8c.get("packet", {}).get("facts", {})
    opening = packet_facts.get("opening_balance_sheet")
    ttm = packet_facts.get("ttm")
    if not isinstance(opening, dict) or not isinstance(ttm, dict):
        raise OtherBalancesError("accepted P8C opening balance sheet and TTM facts are required")

    def anchored(source_name: str, packet_name: str) -> float:
        source_value = value(source_name)
        assert source_value is not None
        return _require_equal(source_value, _packet_fact(opening, packet_name), source_name)

    calibration_values = calibration["values"]
    other_pool = _number(calibration_values["other_investment_pool"]["value"], "other investment pool calibration")
    identified_lt_debt = _number(calibration_values["identified_long_term_debt_investments"]["value"], "identified long-term debt investments")
    embedded_amortization = _number(calibration_values["embedded_ttm_intangible_amortization"]["value"], "embedded TTM intangible amortization")
    unidentified_dna_other = _number(calibration_values["unidentified_dna_other"]["value"], "unidentified D&A residual")
    total_investment_bucket = value("cash_short_term_equity_total")
    assert total_investment_bucket is not None
    known_investment_value = total_investment_bucket - other_pool
    other_pool_formula = calibration_values["other_investment_pool"].get("formula")
    if other_pool_formula != "cash_short_term_equity_total - known_investment_value":
        raise OtherBalancesError("P8D Other pool calibration formula is not the accepted residual convention")
    schedule_row = by_name.get("intangible_future_amortization_schedule")
    schedule = _parse_intangible_schedule((schedule_row or {}).get("reported_value"), expected_total=anchored("intangible_net", "intangibles"))

    p8a = p8c.get("tax_forecast", {}).get("inputs")
    if not isinstance(p8a, dict):
        raise OtherBalancesError("accepted P8A tax inputs are required")
    required_tax = ("book_tax_rate", "operating_tax_rate", "deferred_share", "period_days", "opening_current_tax_payable", "opening_long_term_tax_liability", "opening_deferred_tax_liability")
    if any(key not in p8a for key in required_tax):
        raise OtherBalancesError("accepted P8A tax inputs are incomplete")
    deferred_share = p8a["deferred_share"]
    period_days = p8a["period_days"]
    if not isinstance(deferred_share, list) or len(deferred_share) != len(PERIODS):
        raise OtherBalancesError("accepted P8A deferred-share path must contain eleven values")
    if not isinstance(period_days, list) or len(period_days) != len(PERIODS):
        raise OtherBalancesError("accepted P8A period-day path must contain eleven values")
    deferred_share = [_number(item, f"deferred share[{index}]") for index, item in enumerate(deferred_share)]
    period_days = [_number(item, f"period days[{index}]") for index, item in enumerate(period_days)]
    current_tax = _number(p8a["opening_current_tax_payable"], "opening current tax payable")
    long_term_tax = _number(p8a["opening_long_term_tax_liability"], "opening long-term tax liability")
    deferred_tax = _number(p8a["opening_deferred_tax_liability"], "opening deferred tax liability")
    deferred_source = value("q3_deferred_income_tax_liability")
    if deferred_source is None:
        raise OtherBalancesError("P8D source value is missing: q3_deferred_income_tax_liability")
    _require_equal(deferred_tax, deferred_source, "deferred tax liability")
    revenue = _packet_fact(ttm, "revenue")
    interest_dividends = value("interest_and_dividends_income")
    assert interest_dividends is not None
    financing_receivables = value("financing_receivables_total")
    if financing_receivables is None:
        raise OtherBalancesError("P8D financing receivables source value is missing")
    opening_income_pool = anchored("cash_and_cash_equivalents", "cash") + anchored("short_term_investments", "short_term_investments") + identified_lt_debt + financing_receivables
    annualized_income_anchor = interest_dividends * 365.0 / 274.0
    packet = {
        "schema_version": SCHEMA_VERSION,
        "case": CASE,
        "information_cutoff": INFORMATION_CUTOFF,
        "measurement_date": MEASUREMENT_DATE,
        "source_table": str(path),
        "source_table_sha256": _sha256(path),
        "source_calibration": str(calibration_path),
        "source_calibration_sha256": _sha256(calibration_path),
        "facts": {
            "source": {
                "cash": anchored("cash_and_cash_equivalents", "cash"),
                "short_term_investments": anchored("short_term_investments", "short_term_investments"),
                "equity_other_investments": anchored("equity_and_other_investments", "long_term_investments"),
                "known_investment_buckets": known_investment_value,
                "other_investments": other_pool,
                "known_investment_value": known_investment_value,
                "other_investment_pool": other_pool,
                "identified_long_term_debt_investments": identified_lt_debt,
                "equity_method_investments": value("equity_method_investments"),
                "financing_receivables": value("financing_receivables_total"),
                "restricted_total": value("restricted_investments_total"),
                "restricted_short_term": value("restricted_short_term_investments"),
                "restricted_equity_other": value("restricted_equity_other_investments"),
                "debt_adjusted_cost": value("debt_investments_adjusted_cost"),
                "debt_fair_value": value("debt_investments_fair_value"),
                "interest_dividends_9m": interest_dividends,
                "unrealized_gain_9m": value("equity_unrealized_gains"),
                "oci_investment_change_9m": value("oci_investment_change"),
                "goodwill": anchored("goodwill_balance", "goodwill"),
                "intangibles": anchored("intangible_net", "intangibles"),
                "intangible_gross": value("intangible_gross_carrying_amount"),
                "intangible_accumulated_amortization": value("intangible_accumulated_amortization"),
                "intangible_amortization_9m": value("intangible_amortization_expense"),
                "goodwill_acquisitions_9m": value("goodwill_acquisitions"),
                "other_current_assets": anchored("other_current_assets_parent", "other_current_assets"),
                "other_current_assets_residual": value("other_current_assets_residual_calculated"),
                "other_long_term_assets": anchored("other_long_term_assets_parent", "other_noncurrent_assets"),
                "long_term_ar": value("long_term_accounts_receivable"),
                "other_current_liabilities": anchored("other_current_liabilities_parent", "other_current_liabilities"),
                "other_current_liability_residual": value("p7_other_current_liability_residual"),
                "other_long_term_liabilities": anchored("other_long_term_liabilities_parent", "other_noncurrent_liabilities"),
                "other_long_term_liability_residual": value("other_long_term_liability_residual_calculated"),
                "deferred_tax_liability": deferred_tax,
                "long_term_tax_liability": long_term_tax,
                "current_tax_payable": current_tax,
                "legal_accrued": value("legal_liabilities_accrued"),
                "legal_possible": value("legal_outcomes_possible_beyond_accrued"),
                "unfunded_commitment": value("openai_unfunded_commitments"),
                "construction_commitment": value("ppe_construction_commitment"),
                "rpo": value("remaining_performance_obligations"),
            },
            "rows": src,
            "intangible_schedule": schedule,
            "calculated": {
                "known_investment_value": known_investment_value,
                "ttm_revenue": revenue,
                "ttm_intangible_amortization": embedded_amortization,
                "embedded_intangible_ratio": embedded_amortization / revenue,
                "opening_income_pool": opening_income_pool,
                "annualized_income_anchor": annualized_income_anchor,
                "cash_income_yield_anchor": annualized_income_anchor / opening_income_pool,
                "period_days": period_days,
                "unidentified_dna_other": unidentified_dna_other,
            },
            "opening_balance_sheet": opening,
            "ttm": ttm,
        },
        "upstream_model": p8c,
        "p8a": {"book_tax_rate": _number(p8a["book_tax_rate"], "book tax rate"), "operating_tax_rate": _number(p8a["operating_tax_rate"], "operating tax rate"), "deferred_share": deferred_share, "period_days": period_days},
        "unavailable": ["OpenAI carrying amount inside the 11,100 equity-method pool", "current/noncurrent financing-receivable split", "Q3 deferred-tax decomposition and basis", "future acquisition timing and replacement spending"],
    }
    return packet


def default_proposal(packet: dict[str, Any]) -> OtherBalancesProposal:
    anchor = packet["facts"]["calculated"]["cash_income_yield_anchor"]
    return OtherBalancesProposal(
        outcome="propose_forecast", method_id=METHOD_ID, method_version=METHOD_VERSION,
        other_investment_value_multiplier=1.0, cash_income_yield=anchor,
        intangible_tail_life_years=10, goodwill_impairment=0.0,
        unfunded_commitment_value_fraction=1.0, legal_stress=0.0,
        incremental_net_dta_value=0.0, unrealized_investment_gain=0.0,
        future_acquisitions=0, commitment_timing="FY2026_STUB_END",
        evidence_refs=["cash_and_short_term_investments", "equity_without_readily_determinable_fv", "intangible_future_amortization_schedule", "openai_unfunded_commitments", "q3_deferred_tax_asset_decomposition"],
        rationale="Carry reported pools once; use opening income proxy, disclosed finite-intangible runoff and conservative NET DTA value.",
        alternatives=["6-year or 15-year tail; 0.5x or 1.5x other-investment value; restriction and credit haircuts."],
        uncertainty=packet["unavailable"],
        sensitivities=[{"parameter": "other_investment_value_multiplier", "low": 0.5, "base": 1.0, "high": 1.5}, {"parameter": "intangible_tail_life_years", "low": 6, "base": 10, "high": 15}, {"parameter": "incremental_net_dta_value", "low": 0, "base": 0, "high": 26273}],
        follow_up_request=None,
    )


def validate_proposal(proposal: OtherBalancesProposal, packet: dict[str, Any]) -> None:
    if proposal.outcome != "propose_forecast":
        return
    if proposal.method_id != METHOD_ID or proposal.method_version != METHOD_VERSION:
        raise OtherBalancesError("unsupported P8D method")
    if proposal.commitment_timing != "FY2026_STUB_END" or proposal.future_acquisitions != 0:
        raise OtherBalancesError("P8D commitment timing/acquisition policy is fixed")
    if proposal.intangible_tail_life_years not in {6, 10, 15}:
        raise OtherBalancesError("P8D tail life must be 6, 10 or 15 years")
    if proposal.cash_income_yield is None or proposal.cash_income_yield < 0 or proposal.cash_income_yield > 0.10:
        raise OtherBalancesError("P8D cash-income yield is outside [0,10%]")
    goodwill = packet["facts"]["source"]["goodwill"]
    if proposal.goodwill_impairment is None or proposal.goodwill_impairment > goodwill:
        raise OtherBalancesError("P8D impairment exceeds goodwill")
    if proposal.incremental_net_dta_value not in {0, 26273} and proposal.incremental_net_dta_value is not None:
        raise OtherBalancesError("P8D NET DTA value must be zero base or selected historical proxy")
    if not proposal.evidence_refs:
        raise OtherBalancesError("P8D evidence references are required")


def review_proposal(proposal: OtherBalancesProposal, packet: dict[str, Any]) -> OtherBalancesReview:
    validate_proposal(proposal, packet)
    return OtherBalancesReview(
        verdict="accept", evidence_strength="mixed", method_valid=True, source_valid=True,
        period_valid=True, investment_bridge_valid=True, intangible_bridge_valid=True,
        cash_noncash_separated=True, residual_coverage_valid=True, tax_effect_contained=True,
        no_double_count=True, concerns=["Q3 DTA decomposition and OpenAI carrying value remain unknown."],
        required_revision=None, target="none", rationale="Selected P8D policy is mechanically bounded and preserves disclosed parents/unknowns.",
    )


def _period_meta() -> list[dict[str, Any]]:
    spans = [("2026-04-01", "2026-06-30"), ("2026-07-01", "2027-06-30"), ("2027-07-01", "2028-06-30"), ("2028-07-01", "2029-06-30"), ("2029-07-01", "2030-06-30"), ("2030-07-01", "2031-06-30"), ("2031-07-01", "2032-06-30"), ("2032-07-01", "2033-06-30"), ("2033-07-01", "2034-06-30"), ("2034-07-01", "2035-06-30"), ("2035-07-01", "2036-06-30")]
    return [{"id": period, "start": start, "end": end, "days": (date.fromisoformat(end) - date.fromisoformat(start)).days + 1, "year_fraction": ((date.fromisoformat(end) - date.fromisoformat(start)).days + 1) / 365} for period, (start, end) in zip(PERIODS, spans, strict=True)]


def forecast_values(packet: dict[str, Any], proposal: OtherBalancesProposal) -> dict[str, Any]:
    """Return source and selected-input metadata for the Mog-owned forecast.

    This function deliberately does not calculate period income, cash, carrying
    values or balance-sheet outputs.  Those values are produced by the linked
    Mog workbook and are attached as ``authoritative_mog`` by the workflow.
    """
    validate_proposal(proposal, packet)
    src = packet["facts"]["source"]
    meta = _period_meta()
    schedule = packet["facts"]["intangible_schedule"]
    calc = packet["facts"]["calculated"]
    existing_value = src["known_investment_value"] + src["other_investment_pool"] * proposal.other_investment_value_multiplier + src["financing_receivables"]
    funding = src["unfunded_commitment"]
    rights_value = funding * proposal.unfunded_commitment_value_fraction
    commitment_adjustment = funding * (proposal.unfunded_commitment_value_fraction - 1.0) / (1.043 ** (91.0 / 365.0))
    value_bridge = {
        "known_market_and_cash": src["known_investment_value"],
        "other_investment_pool": src["other_investment_pool"] * proposal.other_investment_value_multiplier,
        "financing_receivables_proxy": src["financing_receivables"],
        "commitment_rights_value": rights_value,
        "commitment_net_measurement_adjustment": commitment_adjustment,
        "total_before_commitment_adjustment": existing_value,
        "total": existing_value + commitment_adjustment,
        "excluding_bridge_cash": existing_value + commitment_adjustment - src["cash"],
        "restriction_stress_20pct": src["restricted_total"] * .20,
        "restriction_stress_50pct": src["restricted_total"] * .50,
        "credit_stress_10pct": src["financing_receivables"] * .10,
        "credit_stress_25pct": src["financing_receivables"] * .25,
    }
    coverage = {
        "cash": {"opening": src["cash"], "policy": "reported carrying/fair-value approximation; no forced liquidity"},
        "short_term_investments": {"opening": src["short_term_investments"], "policy": "reported parent; restricted component retained"},
        "equity_other_investments": {"opening": src["equity_other_investments"], "policy": "carrying pool; other bucket marked by multiplier once"},
        "identified_long_term_debt_investments": {"opening": src["identified_long_term_debt_investments"], "policy": "selected eligible income pool anchor; retained as a separate source claim"},
        "financing_receivables": {"opening": src["financing_receivables"], "policy": "one nonoperating value proxy; current/LT split unknown"},
        "intangibles": {"opening": src["intangibles"], "policy": "disclosed schedule plus selected tail"},
        "goodwill": {"opening": src["goodwill"], "policy": "flat except explicit noncash nondeductible impairment"},
        "other_current_assets_residual": {"opening": src["other_current_assets_residual"], "policy": "P7 parent/residual held nominally flat"},
        "other_long_term_assets_residual": {"opening": src["other_long_term_assets"], "policy": "parent retained; DTA split unknown; NET value base zero"},
        "other_current_liability_residual": {"opening": src["other_current_liability_residual"], "policy": "P7 residual held flat; legal amount contained"},
        "other_long_term_liability_residual": {"opening": src["other_long_term_liability_residual"], "policy": "P8B carve-out retained; residual held flat"},
        "deferred_tax": {"opening": src["deferred_tax_liability"], "policy": "Q3 reported; no second DTL claim"},
    }
    checks = {
        "source_values_complete": True,
        "investment_value_once_definition": True,
        "intangible_schedule_total": abs(src["intangibles"] - schedule["total"]) <= TOLERANCE,
        "commitment_funding_once_definition": True,
        "unsupported_residual_movement": "requires_actual_mog_balance_check",
    }
    return {
        "forecast_authority": "Mog formulas compiled by asset_model.mjs; Python owns source facts and selected parameters",
        "periods": list(PERIODS),
        "period_meta": meta,
        "source_claims": src,
        "coverage": coverage,
        "investment": {
            "opening_income_pool": calc["opening_income_pool"],
            "cash_income_yield": proposal.cash_income_yield,
            "cash_income_policy": "opening eligible pool; actual prior-period closing cash thereafter; MAX(cash,0) only for yield eligibility; additions earn next period",
            "value_bridge": value_bridge,
            "income_excluded_from_ufcf": True,
        },
        "intangible": {
            "reported_schedule": schedule,
            "tail_life_years": proposal.intangible_tail_life_years,
            "embedded_ttm_removed_ratio": calc["embedded_intangible_ratio"],
            "unidentified_dna_other": calc["unidentified_dna_other"],
        },
        "goodwill": {"opening": src["goodwill"], "impairment_policy": "base zero; selected impairment is noncash and nondeductible"},
        "commitment": {
            "unfunded": funding,
            "funding_cfi_policy": "one-time stub CFI outflow equal to negative funding",
            "value_fraction": proposal.unfunded_commitment_value_fraction,
            "rights_value": rights_value,
            "net_measurement_adjustment": commitment_adjustment,
            "net_measurement_adjustment_formula": "1200 * (fraction - 1) / (1.043)^(91/365)",
            "future_acquisitions": 0,
        },
        "checks": checks,
        "all_pass": None,
        "unsupported_residual_movement": "requires_actual_mog_balance_check",
        "tax": {"known_unrealized_gain": proposal.unrealized_investment_gain, "deferred_tax_policy": "gain changes deferred tax once; no current tax on unrealized gain", "incremental_net_dta_value": proposal.incremental_net_dta_value, "historical_proxy_sensitivity": [0.0, 26273.0]},
    }


def build_other_balances_model(p8c: dict[str, Any], packet: dict[str, Any], proposal: OtherBalancesProposal, review: OtherBalancesReview, *, context: dict[str, Any] | None = None, decision_status: str = "REVIEW_REQUIRED") -> dict[str, Any]:
    validate_proposal(proposal, packet)
    forecast = forecast_values(packet, proposal)
    policy = proposal.model_dump(mode="json")
    review_payload = review.model_dump(mode="json")
    bound_context = context or {}
    decision = {"status": decision_status, "human_approval": False, "method_id": METHOD_ID, "method_version": METHOD_VERSION, "candidate_hash": content_hash(policy), "review_hash": content_hash(review_payload), "context_hash": content_hash(bound_context), "source_packet_hash": content_hash(packet), "review": review_payload, "review_verdict": review.verdict, "limitations": packet["unavailable"], "candidate_snapshot": policy, "binding": {"candidate_hash": content_hash(policy), "review_hash": content_hash(review_payload), "context_hash": content_hash(bound_context), "source_packet_hash": packet["source_table_sha256"], "candidate_snapshot": policy, "review_snapshot": review_payload}}
    return {"schema_version": SCHEMA_VERSION, "case": CASE, "information_cutoff": INFORMATION_CUTOFF, "measurement_date": MEASUREMENT_DATE, "packet": packet, "candidate": policy, "inputs": policy, "forecast": forecast, "context": bound_context, "review": review_payload, "decision": decision}


def _strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    schema = to_strict_json_schema(model)
    _assert_strict_schema(schema)
    return schema


def _assert_strict_schema(node: Any) -> None:
    if isinstance(node, dict):
        if node.get("type") == "object" or "properties" in node:
            properties = node.get("properties", {})
            if set(properties) != set(node.get("required", [])):
                raise OtherBalancesError("strict schema objects must require every property")
            if node.get("additionalProperties") is not False:
                raise OtherBalancesError("strict schema objects must forbid extra properties")
        for value in node.values():
            _assert_strict_schema(value)
    elif isinstance(node, list):
        for value in node:
            _assert_strict_schema(value)


def _request(instruction: str, payload: dict[str, Any], response_model: type[BaseModel]) -> dict[str, Any]:
    return {"model": MODEL, "reasoning": {"effort": REASONING_EFFORT}, "service_tier": "default", "input": instruction + "\n" + json.dumps(payload, ensure_ascii=False, sort_keys=True), "text": {"format": {"type": "json_schema", "name": "p8d_other_balances", "strict": True, "schema": _strict_schema(response_model)}}, "max_output_tokens": MAX_OUTPUT_TOKENS, "tools": [], "background": False}


def _run_context(p8c: dict[str, Any], packet: dict[str, Any]) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2]
    implementation_files = [
        "src/smrik_fund/other_balances.py",
        "scripts/spreadsheet_compat/asset_model.mjs",
        "scripts/spreadsheet_compat/run-p8d.mjs",
    ]
    implementation_digests = []
    for relative in implementation_files:
        path = root / relative
        implementation_digests.append({"path": relative, "sha256": _sha256(path) if path.exists() else None})
    return {"schema_version": SCHEMA_VERSION, "prompt_version": PROMPT_VERSION, "method_catalog_version": METHOD_CATALOG_VERSION, "model": MODEL, "reasoning_effort": REASONING_EFFORT, "max_output_tokens": MAX_OUTPUT_TOKENS, "endpoint": ENDPOINT_URL, "service_tier": "default", "tools": [], "background": False, "max_retries": 0, "case": CASE, "information_cutoff": INFORMATION_CUTOFF, "measurement_date": MEASUREMENT_DATE, "source_packet_hash": content_hash(packet), "upstream_hash": content_hash(p8c), "method_id": METHOD_ID, "method_version": METHOD_VERSION, "proposal_schema_hash": content_hash(_strict_schema(OtherBalancesProposal)), "review_schema_hash": content_hash(_strict_schema(OtherBalancesReview)), "implementation_files": implementation_digests, "implementation_aggregate_sha256": content_hash(implementation_digests), "selected_policy_hash": content_hash(_method_contract(packet))}


def _method_contract(packet: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    calc = packet["facts"]["calculated"]
    source = packet["facts"]["source"]
    schedule = packet["facts"]["intangible_schedule"]
    return {
        "method_id": METHOD_ID,
        "method_version": METHOD_VERSION,
        "units": "USD millions; rates/fractions decimal",
        "formula_authority": "Mog workbook formulas; Python persists source facts and selected parameters only",
        "fixed_application_fields": {
            "intangible_opening": {"value": source["intangibles"], "classification": "reported carrying"},
            "intangible_stub": {"value": schedule["stub"], "classification": "reported period amount"},
            "future_acquisitions": {"value": 0, "locked": True},
            "commitment_timing": {"value": "FY2026_STUB_END", "locked": True},
            "incremental_net_dta_base": {"value": 0, "classification": "selected estimate"},
        },
        "application_owned_arithmetic": {
            "opening_income_pool": {"value": calc["opening_income_pool"], "formula": "opening cash + short-term investments + identified LT debt investments + financing receivables"},
            "annualized_income_anchor": {"value": calc["annualized_income_anchor"], "formula": "reported 9m interest/dividends * 365 / 274"},
            "cash_income_yield_anchor": {"value": calc["cash_income_yield_anchor"], "formula": "annualized income anchor / opening eligible pool"},
            "intangible_tail": {"formula": "reported thereafter pool / selected tail life"},
            "commitment_adjustment": {"formula": "unfunded commitment * (value fraction - 1) / (1.043)^(91/365)"},
        },
        "cash_income_classification": {
            "company_statements": "Nonoperating interest/dividend income enters pretax income, company current tax and CFO. The company cash-tax schedule includes its tax effect.",
            "operating_ufcf": "Operating UFCF starts from operating EBIT and its separate normalized operating tax. Nonoperating cash income and the associated company tax are excluded; the CFO-to-UFCF bridge removes both. Compare actual period-by-period valuationUfcf and cfoUfcf, not company CFO alone.",
            "valuation": "Measurement-date nonoperating cash/investment value enters the equity bridge once; its forecast income is not capitalized in operating enterprise value.",
            "yield_zero": "A zero yield changes the company income and cash forecast. It does not change the classification of nonoperating income or its tax in operating UFCF.",
        },
        "judgment_constraints": {"other_investment_value_multiplier": {"min": 0, "max": 10, "base": 1}, "cash_income_yield": {"min": 0, "max": 0.1, "base": calc["cash_income_yield_anchor"]}, "tail_life_years": [6, 10, 15], "unfunded_commitment_value_fraction": [0, 1], "legal_stress": [0, 400]},
        "provenance": {"reported_values_are_not_estimates": True, "other_bucket_is_not_all_openai": True, "historical_dta_is_not_q3_carrying": True, "calibration_artifact": packet["source_calibration"]},
        "outcome_contract": {"propose_forecast": {"follow_up_request": "must be null"}, "nonforecast": {"all forecast fields": "must be null", "follow_up_request": "required"}},
        "context_hash": content_hash(context or {}),
    }


def _compact_upstream(model: dict[str, Any]) -> dict[str, Any]:
    """Keep wire payloads bounded while retaining the upstream series P8D uses."""
    operating = model.get("operating_forecast", {})
    equity = model.get("equity_forecast", {}).get("forecast", {})
    return {
        "schema_version": model.get("schema_version"),
        "p8c_decision": model.get("p8c_decision") or model.get("equity_decision") or model.get("decision"),
        "operating_forecast": {key: operating.get(key) for key in ("forecast_revenue", "forecast_operating_income")},
        "equity_forecast": {"forecast": {key: equity.get(key) for key in ("net_income", "cfo")}},
        "tax_forecast": {"inputs": model.get("tax_forecast", {}).get("inputs", {})},
    }


def _proposal_payload(packet: dict[str, Any], context: dict[str, Any], *, purpose: str, candidate: OtherBalancesProposal | None = None, review: OtherBalancesReview | None = None, authority: dict[str, Any] | None = None) -> dict[str, Any]:
    source_packet = dict(packet)
    source_packet["upstream_model"] = _compact_upstream(packet.get("upstream_model", {}))
    payload = {"purpose": purpose, "context": context, "contract": _method_contract(packet, context), "source_packet": source_packet, "selected_policy": {"other_investment_base": "1.0x carrying estimate", "cash_income_convention": "opening balance x yield x actual days/365; additions earn next period", "intangible_schedule": "stub 1024; FY27-30 disclosed; tail 9873 over 6/10/15 years", "goodwill": "no amortization; impairment 0 base", "commitment": "1200 CFI at stub end; future acquisitions 0", "dta": "NET value 0 base; historical 0-26273 sensitivity"}}
    if candidate is not None:
        payload["candidate"] = candidate.model_dump(mode="json")
    if review is not None:
        payload["review"] = review.model_dump(mode="json")
    if authority is not None:
        payload["authority"] = authority
    return payload


def _review_payload(packet: dict[str, Any], context: dict[str, Any], candidate: OtherBalancesProposal, *, purpose: str, authority: dict[str, Any], prior_review: OtherBalancesReview | None = None) -> dict[str, Any]:
    return _proposal_payload(packet, context, purpose=purpose, candidate=candidate, authority=authority, review=prior_review)


def _review_contract(review: OtherBalancesReview) -> None:
    if review.verdict == "revise":
        if review.target == "none" or not review.required_revision:
            raise OtherBalancesError("P8D revise verdict must name one target and required revision")
    elif review.target != "none" or review.required_revision is not None:
        raise OtherBalancesError("P8D accept/reject verdict cannot carry revision target")


def _review_eligible(review: OtherBalancesReview) -> bool:
    return review.verdict == "accept" and review.target == "none" and review.required_revision is None and all((review.method_valid, review.source_valid, review.period_valid, review.investment_bridge_valid, review.intangible_bridge_valid, review.cash_noncash_separated, review.residual_coverage_valid, review.tax_effect_contained, review.no_double_count))


def _revision_is_consequential(original: OtherBalancesProposal, revised: OtherBalancesProposal, target: str) -> None:
    fields = {"investment_value": ("other_investment_value_multiplier",), "yield": ("cash_income_yield",), "tail_life": ("intangible_tail_life_years",), "impairment": ("goodwill_impairment",), "commitment": ("unfunded_commitment_value_fraction",), "dta": ("incremental_net_dta_value",)}.get(target)
    if fields is None:
        raise OtherBalancesError(f"unsupported P8D revision target: {target}")
    before = original.model_dump(mode="json")
    after = revised.model_dump(mode="json")
    supported = {"other_investment_value_multiplier", "cash_income_yield", "intangible_tail_life_years", "goodwill_impairment", "unfunded_commitment_value_fraction", "incremental_net_dta_value"}
    changed = {field for field in supported if before[field] != after[field]}
    if changed != set(fields):
        raise OtherBalancesError(f"P8D revision changed {sorted(changed)}; expected only {list(fields)}")


def _response_value(response: Any) -> Any:
    text = getattr(response, "output_text", None)
    if isinstance(text, str) and text.strip():
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise OtherBalancesError("provider response was not valid JSON") from exc
    raw = response if isinstance(response, dict) else getattr(response, "model_dump", lambda **_: response)(mode="json")
    if isinstance(raw, dict) and raw.get("output_parsed") is not None:
        return raw["output_parsed"]
    if isinstance(raw, dict) and isinstance(raw.get("output_text"), str):
        try:
            return json.loads(raw["output_text"])
        except json.JSONDecodeError as exc:
            raise OtherBalancesError("provider response was not valid JSON") from exc
    return raw


def _parse_structured_response(response: Any, response_model: type[BaseModel]) -> BaseModel:
    value = _response_value(response)
    if isinstance(value, response_model):
        return value
    if not isinstance(value, dict):
        raise OtherBalancesError("provider response contained no structured output")
    required = set(_strict_schema(response_model).get("required", []))
    if set(value) != required:
        raise OtherBalancesError(f"provider structured output keys violate strict schema; missing={sorted(required - set(value))}, extra={sorted(set(value) - required)}")
    try:
        return response_model.model_validate(value)
    except Exception as exc:
        raise OtherBalancesError(f"provider output failed semantic validation: {exc}") from exc


def _usage_dict(response: Any) -> dict[str, Any] | None:
    usage = getattr(response, "usage", None)
    if usage is None and isinstance(response, dict):
        usage = response.get("usage")
    if usage is None:
        return None
    if isinstance(usage, dict):
        return usage
    dump = getattr(usage, "model_dump", None)
    return dump(mode="json") if dump is not None else None


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _ledger_state(budget_path: Path) -> tuple[int, float]:
    value = json.loads(budget_path.read_text(encoding="utf-8"))
    calls = [item for item in value.get("calls", []) if item.get("task_id") == TASK_ID]
    committed = sum(item.get("cost", {}).get("priced_eur", item.get("reserved_eur", 0.0)) for item in calls)
    return len(calls), float(committed)


def _has_held_call(budget_path: Path) -> bool:
    try:
        state = json.loads(budget_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return False
    return any(item.get("task_id") == TASK_ID and item.get("status") in {"reserved", "usage_unknown"} for item in state.get("calls", []))


def _dispatch(*, stage: str, run_dir: Path, budget_path: Path, instruction: str, payload: dict[str, Any], response_model: type[BaseModel], client: Any | None = None) -> tuple[BaseModel, dict[str, Any]]:
    run_dir.mkdir(parents=True, exist_ok=True)
    request = _request(instruction, payload, response_model)
    request_hash = content_hash(request)
    attempts = run_dir / "attempts"
    attempts.mkdir(parents=True, exist_ok=True)
    if not budget_path.exists():
        raise OtherBalancesError(f"P8D budget ledger is missing: {budget_path}")
    state = json.loads(budget_path.read_text(encoding="utf-8"))
    matches = [item for item in state.get("calls", []) if item.get("task_id") == TASK_ID and item.get("request_hash") == request_hash]
    if any(item.get("status") in {"reserved", "usage_unknown"} for item in matches):
        raise OtherBalancesError(f"{stage} exact request has a held ledger admission")
    for request_path in sorted(attempts.glob(f"*-{stage}.request.json")):
        try:
            prior = json.loads(request_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if content_hash(prior) != request_hash:
            continue
        prefix = request_path.name.removesuffix(".request.json")
        structured = attempts / f"{prefix}.structured.json"
        outcome = attempts / f"{prefix}.outcome.json"
        if structured.exists() and outcome.exists() and matches and all(item.get("status") == "completed" for item in matches):
            return response_model.model_validate(json.loads(structured.read_text(encoding="utf-8"))), {"stage": stage, "request_hash": request_hash, "status": "completed", "resumed": True, "resumed_call_ids": [item.get("call_id") for item in matches]}
        raise OtherBalancesError(f"{stage} exact request has no resumable artifact")
    ordinal, committed = _ledger_state(budget_path)
    if ordinal >= MAX_ATTEMPTS:
        raise OtherBalancesError("P8D dispatched-attempt cap reached")
    prices = state["prices"]
    estimate = reservation(request, prices, today=date.today())["reserved_eur"]
    if committed + estimate > MAX_COMMITTED_EUR:
        raise OtherBalancesError("P8D committed/reserved allowance would exceed EUR0.50")
    call_id = f"{TASK_ID}-{ordinal + 1:02d}-{stage}"
    prefix = f"{ordinal + 1:02d}-{stage}"
    request_path = attempts / f"{prefix}.request.json"
    _write_json(request_path, request)
    _write_json(attempts / f"{prefix}.reservation.json", reserve_call(budget_path, call_id=call_id, task_id=TASK_ID, request=request, endpoint_host="api.openai.com", today=date.today()))
    if client is None:
        load_dotenv()
        from openai import OpenAI
        client = OpenAI(max_retries=0)
    started = time.perf_counter()
    response = None
    error: Exception | None = None
    try:
        response = client.responses.create(**request)
    except Exception as exc:  # preserve the admitted attempt as usage-unknown
        error = exc
    elapsed = time.perf_counter() - started
    raw = _response_value(response) if response is not None else {"response": None}
    if error is not None:
        raw = {"error_type": type(error).__name__, "error": str(error), "response": raw}
    _write_json(attempts / f"{prefix}.response.json", raw)
    outcome_error: Exception | None = None
    try:
        outcome = record_outcome(budget_path, call_id=call_id, usage=_usage_dict(response), elapsed_seconds=elapsed, response_id=getattr(response, "id", None), returned_model=getattr(response, "model", None))
    except Exception as exc:
        outcome_error = exc
        _write_json(attempts / f"{prefix}.outcome-error.json", {"error_type": type(exc).__name__, "error": str(exc)})
        outcome = record_outcome(budget_path, call_id=call_id, usage=None, elapsed_seconds=elapsed, response_id=getattr(response, "id", None), returned_model=getattr(response, "model", None))
    _write_json(attempts / f"{prefix}.outcome.json", outcome)
    metadata = {"call_id": call_id, "stage": stage, "request_hash": request_hash, "status": outcome["status"], "model": MODEL, "reasoning": {"effort": REASONING_EFFORT}, "service_tier": "default", "resumed": False}
    _write_json(attempts / f"{prefix}.metadata.json", metadata)
    if error is not None:
        _write_json(attempts / f"{prefix}.error.json", {"stage": stage, "request_hash": request_hash, "error": str(error)})
        raise OtherBalancesError(f"{stage} provider call failed after admission: {error}") from error
    if outcome_error is not None or outcome.get("status") != "completed":
        raise OtherBalancesError(f"{stage} usage is unknown after admission; exact-hash replay is held")
    try:
        value = _parse_structured_response(response, response_model)
    except Exception as exc:
        _write_json(attempts / f"{prefix}.parse-error.json", {"error_type": type(exc).__name__, "error": str(exc)})
        raise OtherBalancesError(f"{stage} returned invalid structured output after persistence: {exc}") from exc
    _write_json(attempts / f"{prefix}.structured.json", value.model_dump(mode="json"))
    return value, metadata


def _actual_mog_candidate(p8c: dict[str, Any], packet: dict[str, Any], proposal: OtherBalancesProposal, context: dict[str, Any], run_dir: Path, stage: str) -> dict[str, Any]:
    """Run the actual shared Mog builder through the P8D runner."""
    input_path = run_dir / f"{stage}-model-input.json"
    forecast = forecast_values(packet, proposal)
    input_path.write_text(json.dumps({"p8c": p8c, "p8d_packet": packet, "candidate": proposal.model_dump(mode="json"), "forecast": forecast, "context": context}, indent=2) + "\n", encoding="utf-8")
    script = Path(__file__).resolve().parents[2] / "scripts/spreadsheet_compat/run-p8d.mjs"
    result = subprocess.run(["node", str(script), "authority", str(input_path), str(run_dir / f"{stage}-mog")], capture_output=True, text=True, check=False)
    if result.returncode:
        raise OtherBalancesError(f"P8D Mog authority failed: {result.stderr[-1000:]}")
    return json.loads(result.stdout)


def _terminal_outcome(run_dir: Path, packet: dict[str, Any], context: dict[str, Any], *, status: str, reason: str, metadata: list[dict[str, Any]], candidate: OtherBalancesProposal | None = None) -> dict[str, Any]:
    decision = {"status": status, "human_approval": False, "reason": reason, "source_packet_hash": content_hash(packet), "context_hash": content_hash(context), "call_metadata": metadata}
    previous = run_dir / "model.json"
    decision["previous_effective_model_sha256"] = _sha256(previous) if previous.exists() else None
    _write_json(run_dir / "decision-held.json", decision)
    terminal = {"status": status, "reason": reason, "decision": decision, "candidate": candidate.model_dump(mode="json") if candidate else None}
    _write_json(run_dir / "terminal-outcome.json", terminal)
    return {"packet": packet, "candidate": terminal["candidate"], "decision": decision, "reviews": {}, "forecast": None}


def _write_final_model(run_dir: Path, p8c: dict[str, Any], packet: dict[str, Any], proposal: OtherBalancesProposal, review: OtherBalancesReview, context: dict[str, Any], authority: dict[str, Any], *, selected_stage: str) -> dict[str, Any]:
    model = build_other_balances_model(p8c, packet, proposal, review, context=context, decision_status="SYSTEM_REVIEWED_PROVISIONAL")
    model["authority"] = authority
    model["decision"].update({"authoritative_mog_attached": True, "selected_stage": selected_stage, "selected_candidate": "candidate-revision.json" if selected_stage == "revision" else "candidate-initial.json", "selected_review": "review-revision.json" if selected_stage == "revision" else "review-original.json"})
    _write_json(run_dir / "candidate.json", proposal.model_dump(mode="json"))
    _write_json(run_dir / "review.json", review.model_dump(mode="json"))
    _write_json(run_dir / "model.json", model)
    return model


def run_reasoning(p8c: dict[str, Any], run_dir: Path, budget_path: Path, *, source_table: Path | None = None, offline: bool = False, client: Any | None = None, mog_builder: Any | None = None) -> dict[str, Any]:
    packet = build_evidence_packet(p8c, source_table)
    context = _run_context(p8c, packet)
    run_dir.mkdir(parents=True, exist_ok=True)
    context_path = run_dir / "run-context.json"
    if context_path.exists() and json.loads(context_path.read_text(encoding="utf-8")) != context:
        raise OtherBalancesError("Existing P8D run context differs; use a new run directory")
    context_path.write_text(json.dumps(context, indent=2) + "\n", encoding="utf-8")
    (run_dir / "evidence-packet.json").write_text(json.dumps(packet, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if offline:
        proposal = default_proposal(packet)
        validate_proposal(proposal, packet)
        review = review_proposal(proposal, packet)
        model = build_other_balances_model(p8c, packet, proposal, review, context=context, decision_status="OFFLINE_FIXTURE")
        for name, value in (("candidate.json", proposal.model_dump(mode="json")), ("review.json", review.model_dump(mode="json")), ("model.json", model)):
            (run_dir / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (run_dir / "model-input.json").write_text(json.dumps({"p8c": p8c, "p8d_packet": packet, "candidate": proposal.model_dump(mode="json"), "forecast": model["forecast"], "review": review.model_dump(mode="json"), "decision": model["decision"], "context": context}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return model
    if not budget_path.exists():
        raise OtherBalancesError(f"P8D budget ledger is missing: {budget_path}")
    metadata: list[dict[str, Any]] = []
    current: OtherBalancesProposal | None = None
    try:
        candidate, meta = _dispatch(stage="analyst-initial", run_dir=run_dir, budget_path=budget_path, instruction=INITIAL_ANALYST_INSTRUCTION, payload=_proposal_payload(packet, context, purpose="initial analyst selection"), response_model=OtherBalancesProposal, client=client)
        current = candidate
        metadata.append(meta)
        _write_json(run_dir / "candidate-initial.json", candidate.model_dump(mode="json"))
        if candidate.outcome != "propose_forecast":
            return _terminal_outcome(run_dir, packet, context, status=candidate.outcome.upper(), reason=candidate.follow_up_request or candidate.rationale, metadata=metadata, candidate=candidate)
        validate_proposal(candidate, packet)
        builder = mog_builder or _actual_mog_candidate
        authority = builder(p8c, packet, candidate, context, run_dir, "analyst-initial")
        review, meta = _dispatch(stage="review-original", run_dir=run_dir, budget_path=budget_path, instruction="Independently review P8D source claims, bridges, actual Mog effects, tax containment and coverage.", payload=_review_payload(packet, context, candidate, purpose="original candidate review", authority=authority), response_model=OtherBalancesReview, client=client)
        metadata.append(meta)
        _review_contract(review)
        _write_json(run_dir / "review-original.json", review.model_dump(mode="json"))
        if review.verdict == "accept":
            if not _review_eligible(review):
                return _terminal_outcome(run_dir, packet, context, status="REVIEW_REQUIRED", reason="review accept did not satisfy eligibility", metadata=metadata, candidate=candidate)
            return _write_final_model(run_dir, p8c, packet, candidate, review, context, authority, selected_stage="original")
        if review.verdict == "reject":
            return _terminal_outcome(run_dir, packet, context, status="REJECTED_BY_REVIEW", reason="; ".join(review.concerns), metadata=metadata, candidate=candidate)

        revision_request = {"target": review.target, "required_revision": review.required_revision, "prior_candidate_hash": content_hash(candidate.model_dump(mode="json")), "context_hash": content_hash(context)}
        _write_json(run_dir / "revision-request.json", revision_request)
        revision, meta = _dispatch(stage="analyst-revision", run_dir=run_dir, budget_path=budget_path, instruction="Produce one consequential P8D revision using the review target and supplied method contract. Keep locked source arithmetic/policy fields unchanged; change only the named supported judgment. If the correction needs unavailable evidence, return unresolved or capability_gap with inactive forecast fields null.", payload=_review_payload(packet, context, candidate, purpose="required consequential analyst revision", authority=authority, prior_review=review), response_model=OtherBalancesProposal, client=client)
        current = revision
        metadata.append(meta)
        _write_json(run_dir / "candidate-revision.json", revision.model_dump(mode="json"))
        if revision.outcome != "propose_forecast":
            return _terminal_outcome(run_dir, packet, context, status=revision.outcome.upper(), reason=revision.follow_up_request or revision.rationale, metadata=metadata, candidate=revision)
        _revision_is_consequential(candidate, revision, review.target)
        validate_proposal(revision, packet)
        revised_authority = builder(p8c, packet, revision, context, run_dir, "analyst-revision")
        rereview, meta = _dispatch(stage="review-revision", run_dir=run_dir, budget_path=budget_path, instruction="Independently re-review the revised P8D candidate and fresh actual Mog consequences against the full method contract. Confirm source containment, cash/noncash separation, coverage, tax containment and no double counting.", payload=_review_payload(packet, context, revision, purpose="independent revision re-review", authority=revised_authority, prior_review=review), response_model=OtherBalancesReview, client=client)
        metadata.append(meta)
        _review_contract(rereview)
        _write_json(run_dir / "review-revision.json", rereview.model_dump(mode="json"))
        if not _review_eligible(rereview):
            status = "REJECTED_BY_REVIEW" if rereview.verdict == "reject" else "REVISION_REQUIRED"
            return _terminal_outcome(run_dir, packet, context, status=status, reason="; ".join(rereview.concerns), metadata=metadata, candidate=revision)
        return _write_final_model(run_dir, p8c, packet, revision, rereview, context, revised_authority, selected_stage="revision")
    except OtherBalancesError as exc:
        if not (run_dir / "decision-held.json").exists():
            marker = str(exc).lower()
            status = "BUDGET_HELD" if _has_held_call(budget_path) or any(item in marker for item in ("budget", "allowance", "usage", "held", "reservation")) else "FAILED"
            _terminal_outcome(run_dir, packet, context, status=status, reason=str(exc), metadata=metadata, candidate=current)
        raise
    except Exception as exc:
        _terminal_outcome(run_dir, packet, context, status="BUDGET_HELD" if _has_held_call(budget_path) else "FAILED", reason=str(exc), metadata=metadata, candidate=current)
        raise OtherBalancesError(f"P8D workflow failed; prior effective model preserved: {exc}") from exc


def run_live(p8c: dict[str, Any], run_dir: Path, budget_path: Path, *, source_table: Path | None = None, client: Any | None = None, mog_builder: Any | None = None) -> dict[str, Any]:
    return run_reasoning(p8c, run_dir, budget_path, source_table=source_table, client=client, mog_builder=mog_builder)


def prepare_live_handoff(p8c: dict[str, Any], run_dir: Path, *, source_table: Path | None = None, output_path: Path | None = None, budget_path: Path | None = None) -> dict[str, Any]:
    packet = build_evidence_packet(p8c, source_table)
    context = _run_context(p8c, packet)
    proposal_request = _request(INITIAL_ANALYST_INSTRUCTION, _proposal_payload(packet, context, purpose="initial analyst selection"), OtherBalancesProposal)
    rebuilt_request = _request(INITIAL_ANALYST_INSTRUCTION, _proposal_payload(packet, context, purpose="initial analyst selection"), OtherBalancesProposal)
    run_dir.mkdir(parents=True, exist_ok=True)
    attempts = run_dir / "attempts"
    attempts.mkdir(exist_ok=True)
    request_path = attempts / "01-analyst-initial.request.json"
    _write_json(request_path, proposal_request)
    _write_json(run_dir / "evidence-packet.json", packet)
    _write_json(run_dir / "run-context.json", context)
    destination = output_path or run_dir / "model-input.json"
    _write_json(destination, {"schema_version": SCHEMA_VERSION, "case": CASE, "packet": packet, "context": context, "prepared_request": proposal_request})
    manifest = {"status": "PREPARED_NO_DISPATCH", "stage": "analyst-initial", "request_path": str(request_path), "output_path": str(destination), "request_hash": content_hash(proposal_request), "request_rebuilt_hash": content_hash(rebuilt_request), "canonical_request_equal": json.loads(request_path.read_text(encoding="utf-8")) == proposal_request == rebuilt_request, "source_packet_hash": content_hash(packet), "context_hash": content_hash(context), "implementation_files": context["implementation_files"], "implementation_aggregate_sha256": context["implementation_aggregate_sha256"], "settings": {"model": MODEL, "reasoning": {"effort": REASONING_EFFORT}, "endpoint": ENDPOINT_URL, "service_tier": "default", "max_output_tokens": MAX_OUTPUT_TOKENS, "tools": [], "background": False, "max_retries": 0}, "caps": {"max_attempts": MAX_ATTEMPTS, "max_committed_eur": MAX_COMMITTED_EUR, "final_review_reserve_eur": 0.50}, "cli": f"PYTHONPATH=src .venv\\Scripts\\python.exe -m smrik_fund.other_balances --p8c-input data/build-guide-p8c/live-r6/model-input.json --run-dir {run_dir.as_posix()} --budget {(budget_path or Path('data/build-guide-api-budget.json')).as_posix()}", "replay_policy": "only exact completed requests in same context may resume"}
    _write_json(run_dir / "prepared-manifest.json", manifest)
    return manifest


def run_offline(p8c: dict[str, Any], run_dir: Path, *, source_table: Path | None = None) -> dict[str, Any]:
    return run_reasoning(p8c, run_dir, run_dir / "budget.json", source_table=source_table, offline=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--p8c-input", default="data/build-guide-p8c/live-r6/model-input.json")
    parser.add_argument("--source-table", default=None)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--budget", default="data/build-guide-api-budget.json")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    p8c = json.loads(Path(args.p8c_input).read_text(encoding="utf-8"))
    if args.prepare:
        print(json.dumps(prepare_live_handoff(p8c, Path(args.run_dir), source_table=Path(args.source_table) if args.source_table else None, budget_path=Path(args.budget)), indent=2))
    else:
        result = run_reasoning(p8c, Path(args.run_dir), Path(args.budget), source_table=Path(args.source_table) if args.source_table else None, offline=args.offline)
        print(json.dumps({"status": result["decision"]["status"], "run_dir": args.run_dir}, indent=2))


if __name__ == "__main__":
    main()
