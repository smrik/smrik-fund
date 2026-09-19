"""P8C stock compensation, share and equity boundary.

The module keeps source observations and the selected provisional policy in
plain dictionaries/arrays.  The Mog workbook is the linked-statement
authority; this module is its deterministic input builder and offline review
surface.
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import math
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
TASK_ID = "p8c-msft-equity"
MAX_ATTEMPTS = 6
MAX_COMMITTED_EUR = 0.50
REASONING_EFFORT = "medium"
MAX_OUTPUT_TOKENS = 12_000
SCHEMA_VERSION = "p8c-equity-proposal-r5"
PROMPT_VERSION = "p8c-equity-reasoning-r5"
METHOD_CATALOG_VERSION = "p8c-equity-methods-r5"
CONTRACT_VERSION = "p8c-equity-contract-r5"
METHOD_ID = "sbc_shares_equity_bundle"
METHOD_VERSION = "v1"
PROVENANCE_CONTRACT_VERSION = "p8c-provenance-r5"
TOLERANCE = 1e-8
PERIODS = (
    "FY2026_STUB", "FY2027", "FY2028", "FY2029", "FY2030", "FY2031",
    "FY2032", "FY2033", "FY2034", "FY2035", "FY2036",
)
_PERIOD_SPANS = (
    ("FY2026_STUB", "2026-04-01", "2026-06-30"),
    ("FY2027", "2026-07-01", "2027-06-30"),
    ("FY2028", "2027-07-01", "2028-06-30"),
    ("FY2029", "2028-07-01", "2029-06-30"),
    ("FY2030", "2029-07-01", "2030-06-30"),
    ("FY2031", "2030-07-01", "2031-06-30"),
    ("FY2032", "2031-07-01", "2032-06-30"),
    ("FY2033", "2032-07-01", "2033-06-30"),
    ("FY2034", "2033-07-01", "2034-06-30"),
    ("FY2035", "2034-07-01", "2035-06-30"),
    ("FY2036", "2035-07-01", "2036-06-30"),
)


class EquityError(ValueError):
    """P8C source, policy, dependency, preview, or workflow error."""


class EquityProposal(BaseModel):
    """Judgment boundary.  Source balances and arithmetic remain application-owned."""

    model_config = ConfigDict(extra="forbid")

    outcome: Literal["propose_forecast", "unresolved", "capability_gap"]
    method_id: Literal["sbc_shares_equity_bundle"] | None = None
    method_version: Literal["v1"] | None = None
    sbc_ratio: float | None = Field(default=None, ge=0, le=1)
    existing_award_units: float | None = Field(default=None, ge=0)
    existing_unrecognized_cost: float | None = Field(default=None, ge=0)
    existing_service_years: Literal[2, 3, 4] | None = None
    existing_claim_price: float | None = Field(default=None, gt=0)
    settlement_price: float | None = Field(default=None, gt=0)
    withholding_rate: float | None = Field(default=None, ge=0, le=1)
    cash_issuance_ratio: float | None = Field(default=None, ge=0)
    repurchase_ratio: float | None = Field(default=None, ge=0)
    repurchase_authorization: float | None = Field(default=None, ge=0)
    dividend_per_share_quarter: float | None = Field(default=None, ge=0)
    dividend_quarters_stub: Literal[1] | None = None
    dividend_quarters_annual: Literal[4] | None = None
    delivery_timing: float | None = Field(default=None, ge=0, le=1)
    issuance_timing: float | None = Field(default=None, ge=0, le=1)
    repurchase_timing: float | None = Field(default=None, ge=0, le=1)
    repurchase_policy: Literal["cap_disclosed_authorization"] | None = None
    settlement_policy: Literal["service_delivery_exogenous_price"] | None = None
    diluted_eps_policy: Literal["treasury_stock_proxy_loss_antidilutive"] | None = None
    evidence_refs: list[str] = Field(min_length=1)
    rationale: str = Field(min_length=1)
    alternatives: list[str]
    uncertainty: list[str]
    follow_up_request: str | None

    @model_validator(mode="before")
    @classmethod
    def _reject_coercible_numbers(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        numeric = (
            "sbc_ratio", "existing_award_units", "existing_unrecognized_cost",
            "existing_claim_price", "settlement_price", "withholding_rate",
            "cash_issuance_ratio", "repurchase_ratio", "repurchase_authorization",
            "dividend_per_share_quarter", "delivery_timing", "issuance_timing",
            "repurchase_timing",
        )
        for field in numeric:
            raw = value.get(field)
            if raw is None:
                continue
            if isinstance(raw, bool) or not isinstance(raw, int | float):
                raise ValueError(f"{field} must be numeric")
            if isinstance(raw, float) and not math.isfinite(raw):
                raise ValueError(f"{field} must be finite")
        return value

    @model_validator(mode="after")
    def _validate_shape(self) -> EquityProposal:
        fixed = (
            "method_id", "method_version", "sbc_ratio", "existing_award_units",
            "existing_unrecognized_cost", "existing_service_years", "existing_claim_price",
            "settlement_price", "withholding_rate", "cash_issuance_ratio", "repurchase_ratio",
            "repurchase_authorization", "dividend_per_share_quarter", "dividend_quarters_stub",
            "dividend_quarters_annual", "delivery_timing", "issuance_timing", "repurchase_timing",
            "repurchase_policy", "settlement_policy", "diluted_eps_policy",
        )
        if self.outcome != "propose_forecast":
            if not self.follow_up_request:
                raise ValueError("non-forecast outcome requires follow_up_request")
            populated = [name for name in fixed if getattr(self, name) is not None]
            if populated:
                raise ValueError(f"non-forecast fields must be null: {', '.join(populated)}")
            return self
        required = {name: getattr(self, name) for name in fixed}
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise ValueError(f"forecast proposal missing fields: {', '.join(missing)}")
        if self.follow_up_request is not None:
            raise ValueError("forecast proposal follow_up_request must be null")
        return self


class EquityReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["accept", "revise", "reject"]
    evidence_strength: Literal["strong", "mixed", "weak"]
    method_valid: bool
    source_valid: bool
    period_valid: bool
    sbc_bridge_valid: bool
    share_bridge_valid: bool
    equity_bridge_valid: bool
    cash_bridge_valid: bool
    eps_valid: bool
    valuation_valid: bool
    ufcf_independent: bool
    no_double_count: bool
    funding_visible: bool
    concerns: list[str] = Field(min_length=1)
    required_revision: str | None
    target: Literal["none", "sbc", "pricing", "withholding", "repurchase", "dividend"]
    rationale: str = Field(min_length=1)


def _period_days(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days + 1


def period_meta() -> list[dict[str, Any]]:
    return [{"id": p, "start": s, "end": e, "days": _period_days(s, e), "year_fraction": _period_days(s, e) / 365} for p, s, e in _PERIOD_SPANS]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _number(value: Any, name: str, *, allow_zero: bool = True) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise EquityError(f"{name} is missing/non-numeric")
    if not allow_zero and value == 0:
        raise EquityError(f"{name} must be nonzero")
    return float(value)


def _source_table() -> Path:
    return Path(__file__).resolve().parents[2] / "Lunacy/runs/three-statement-dcf/phases/equity/P8C-source-table-R1.csv"


def _read_source_table(path: Path | None = None) -> list[dict[str, str]]:
    table = path or _source_table()
    if not table.exists():
        raise EquityError(f"P8C source table is missing: {table}")
    with table.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        extras = row.pop(None, None)
        if extras:
            row["limitation"] = ", ".join(item.strip() for item in [row.get("limitation", ""), *extras] if item and item.strip())
    return rows


def _row_map(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    return {(row.get("line_item", ""), row.get("period", "")): row for row in rows}


def _value(row: dict[str, str] | None, name: str, *, allow_missing: bool = False) -> float | None:
    if not row or not str(row.get("reported_value", "")).strip():
        if allow_missing:
            return None
        raise EquityError(f"P8C source value is missing: {name}")
    try:
        number = float(row["reported_value"])
    except (ValueError, TypeError) as exc:
        raise EquityError(f"P8C source value is nonnumeric: {name}") from exc
    if not math.isfinite(number):
        raise EquityError(f"P8C source value is nonfinite: {name}")
    return number


def _p8b_accepted(p8b: dict[str, Any]) -> None:
    decision = p8b.get("p8b_decision") or p8b.get("financing_decision") or p8b.get("decision") or {}
    if decision.get("status") != "SYSTEM_REVIEWED_PROVISIONAL":
        raise EquityError("P8B input is not accepted system-reviewed provisional")
    if (decision.get("review") or {}).get("verdict") not in {None, "accept"}:
        raise EquityError("P8B input review is not accepted")
    packet = p8b.get("packet") or {}
    binding = decision.get("binding") or {}
    expected = packet.get("frozen_case_snapshot_sha256")
    if binding.get("source_case_snapshot_sha256") and binding["source_case_snapshot_sha256"] != expected:
        raise EquityError("P8B source-case binding is stale")


def build_evidence_packet(p8b: dict[str, Any], source_table: Path | None = None) -> dict[str, Any]:
    """Freeze the 75-row equity table and exact accepted P8B dependency."""
    _p8b_accepted(p8b)
    path = source_table or _source_table()
    rows = _read_source_table(path)
    if len(rows) != 75:
        raise EquityError(f"P8C source table expected 75 rows, got {len(rows)}")
    by_key = _row_map(rows)
    q3 = "Q3 FY2026 9m"
    bs = "Q3 FY2026 measurement 2026-03-31"
    required = {
        "sbc_expense": ("FY2025", "Q3 FY2026 9m"),
        "common_apic_balance": ("Q3 FY2026 9m end",),
        "retained_earnings_balance": ("Q3 FY2026 9m end",),
        "aoci_balance": ("Q3 FY2026 9m end",),
        "total_stockholders_equity": ("Q3 FY2026 9m end",),
        "program_repurchase_units": (q3,),
        "program_repurchase_cash": (q3,),
        "point_shares": (bs,),
        "unrecognized_stock_compensation": ("FY2025 end",),
        "stock_award_activity": ("FY2025",),
    }
    for item, periods in required.items():
        for period in periods:
            if (item, period) not in by_key:
                raise EquityError(f"P8C required source row is missing: {item}.{period}")
    ttm_sbc = _number(_value(by_key[("sbc_expense", "FY2025")], "sbc FY2025"), "sbc FY2025")
    q3_sbc = _number(_value(by_key[("sbc_expense", q3)], "sbc Q3 9m"), "sbc Q3 9m")
    # The frozen table records the comparable 9m amount in the policy brief
    # arithmetic, while the selected source slice does not carry a separate
    # row.  Keep that application-owned component explicit and attributed.
    prior_9m = 8901.0
    ttm_sbc = ttm_sbc + q3_sbc - prior_9m
    ttm_revenue = 318273.0
    apic = _number(_value(by_key[("common_apic_balance", "Q3 FY2026 9m end")], "APIC"), "APIC")
    retained = _number(_value(by_key[("retained_earnings_balance", "Q3 FY2026 9m end")], "retained earnings"), "retained earnings")
    aoci = _number(_value(by_key[("aoci_balance", "Q3 FY2026 9m end")], "AOCI"), "AOCI")
    equity = _number(_value(by_key[("total_stockholders_equity", "Q3 FY2026 9m end")], "equity"), "equity")
    shares = _number(_value(by_key[("point_shares", bs)], "point shares"), "point shares", allow_zero=False)
    program_cash = _number(_value(by_key[("program_repurchase_cash", q3)], "program repurchase cash"), "program repurchase cash")
    program_units = _number(_value(by_key[("program_repurchase_units", q3)], "program repurchase units"), "program repurchase units", allow_zero=False)
    packet = {
        "packet_id": "P8C-EQUITY-SOURCE-PACKET-R1",
        "case": CASE,
        "information_cutoff": INFORMATION_CUTOFF,
        "measurement_date": MEASUREMENT_DATE,
        "source_table": path.as_posix(),
        "source_table_sha256": _sha256(path),
        "source_row_count": len(rows),
        "accepted_upstream": {
            "path": "data/build-guide-p8b/live-r5/model-input.json",
            "schema_version": p8b.get("schema_version"),
            "source_case_snapshot_sha256": (p8b.get("p8b_decision") or {}).get("binding", {}).get("source_case_snapshot_sha256") or (p8b.get("packet") or {}).get("frozen_case_snapshot_sha256"),
            "model_sha256": content_hash(p8b),
        },
        "facts": {
            "opening_equity": {"common_apic": apic, "retained_earnings": retained, "aoci": aoci, "total_equity": equity, "point_shares": shares, "source_period": bs},
            "ttm": {"sbc": ttm_sbc, "revenue": ttm_revenue, "sbc_ratio": ttm_sbc / ttm_revenue, "basis": "FY25 + current 9m - prior comparable 9m"},
            "existing_awards": {"units": 82.0, "unrecognized_cost": 21600.0, "service_years": 3, "basis": "FY25 stale proxy; not a Q3 disclosure"},
            "withholding": {"cash": 5400.0, "vested_fair_value": 16200.0, "rate": 5400.0 / 16200.0, "basis": "FY25 rounded disclosures"},
            "cash_issuance": {"ttm": 2037.0, "ratio": 2037.0 / ttm_revenue, "basis": "FY25 2056 + current 9m 1489 - prior 9m 1508"},
            "program_repurchase": {
                "cash": program_cash,
                "units": program_units,
                "price_proxy": program_cash / program_units,
                "authorization_remaining": 44000.0,
                "ratio_reference": {
                    "cash": 13319.0,
                    "revenue": 241832.0,
                    "revenue_period": "FY2025",
                    "ratio": 13319.0 / 241832.0,
                    "basis": "Q3 program cash / FY2025 revenue reference selected in P8C_POLICY.md",
                },
            },
            "dividend": {"opening_payable": 6760.0, "per_share_quarter": 0.91, "stub_quarters": 1, "annual_quarters": 4},
            "market_quote": {"value": 370.17, "unit": "USD/share", "date": MEASUREMENT_DATE, "source": "P9_MARKET_POLICY.md; Mar31 unadjusted close", "status": "provisional_parent_verified"},
            "future_settlement_price": {"value": program_cash / program_units, "unit": "USD/share", "basis": "Q3 program cash / Q3 program units; historical average proxy"},
        },
        "source_rows": rows,
        # The accepted P8B model is a dependency snapshot for the workbook
        # builder/review. It is removed from provider prompts by _proposal_payload.
        "upstream_model": p8b,
        "limitations": [
            "FY25 82m/21,600/three-year award proxy is stale and missing Q3 inventory/timing; no option engine is inferred.",
            "Future settlement, cash issuance, repurchase and dividend timing use explicit exogenous estimates.",
            "Historical statement, dividend and cash timing/rounding differences remain diagnostics.",
        ],
    }
    return packet


def default_proposal(packet: dict[str, Any]) -> EquityProposal:
    facts = packet["facts"]
    return EquityProposal(
        outcome="propose_forecast", method_id=METHOD_ID, method_version=METHOD_VERSION,
        sbc_ratio=facts["ttm"]["sbc_ratio"], existing_award_units=facts["existing_awards"]["units"],
        existing_unrecognized_cost=facts["existing_awards"]["unrecognized_cost"], existing_service_years=facts["existing_awards"]["service_years"],
        existing_claim_price=facts["market_quote"]["value"], settlement_price=facts["future_settlement_price"]["value"],
        withholding_rate=facts["withholding"]["rate"], cash_issuance_ratio=facts["cash_issuance"]["ratio"],
        repurchase_ratio=facts["program_repurchase"]["ratio_reference"]["ratio"], repurchase_authorization=facts["program_repurchase"]["authorization_remaining"],
        dividend_per_share_quarter=0.91, dividend_quarters_stub=1, dividend_quarters_annual=4,
        # The selected real-company base remains midpoint timing. These are
        # live period fractions so native workbook variants can move each flow.
        delivery_timing=0.5, issuance_timing=0.5, repurchase_timing=0.5,
        repurchase_policy="cap_disclosed_authorization", settlement_policy="service_delivery_exogenous_price",
        diluted_eps_policy="treasury_stock_proxy_loss_antidilutive",
        evidence_refs=["P8C-source-table-R1", "P8C_POLICY.md", "P8C_PARENT_ORACLE.md", "P9_MARKET_POLICY.md"],
        rationale="Use TTM embedded SBC replacement, separate stale existing-award claim, exogenous settlement/repurchase pricing, and explicit delivery, dividend and retirement flows.",
        alternatives=["SBC ratio +/-20%", "existing units +/-20% and cost +/-25%", "two/four-year service runoff", "settlement price +/-25%", "zero and renewed repurchase program"],
        uncertainty=["Q3 award inventory, option detail and grant-level vesting are unavailable", "P9 quote boundary is provisional", "aggregate issuance timing is simplified"],
        follow_up_request=None,
    )


def validate_proposal(proposal: EquityProposal, packet: dict[str, Any]) -> None:
    if proposal.outcome != "propose_forecast":
        return
    if proposal.method_id != METHOD_ID or proposal.method_version != METHOD_VERSION:
        raise EquityError("unsupported P8C method")
    if proposal.existing_claim_price <= 0 or proposal.settlement_price <= 0:
        raise EquityError("required price must be positive and exogenous")
    if proposal.existing_award_units < 0 or proposal.existing_unrecognized_cost < 0:
        raise EquityError("existing award inputs cannot be negative")
    if proposal.existing_service_years not in {2, 3, 4}:
        raise EquityError("service years must be selected 2, 3 or 4")
    opening = packet["facts"]["opening_equity"]
    opening_apic = _number(opening["common_apic"], "opening APIC")
    opening_shares = _number(opening["point_shares"], "opening point shares", allow_zero=False)
    if opening_apic < 0:
        raise EquityError("opening APIC is unsupported for the selected retirement basis")
    if proposal.repurchase_ratio > 0 and proposal.settlement_price < opening_apic / opening_shares - TOLERANCE:
        raise EquityError("settlement price is below opening APIC retirement basis")
    if proposal.withholding_rate < 0 or proposal.withholding_rate > 1:
        raise EquityError("withholding rate outside [0,1]")
    for name in ("delivery_timing", "issuance_timing", "repurchase_timing"):
        value = getattr(proposal, name)
        if value < 0 or value > 1:
            raise EquityError(f"{name} outside [0,1]")
    if proposal.repurchase_authorization != 44000:
        raise EquityError("base authorization must equal disclosed 44,000")
    if proposal.dividend_quarters_stub != 1 or proposal.dividend_quarters_annual != 4:
        raise EquityError("dividend declaration counts must be 1 stub and 4 annual")
    if proposal.repurchase_policy != "cap_disclosed_authorization" or proposal.settlement_policy != "service_delivery_exogenous_price":
        raise EquityError("unsupported capital-return or settlement policy")
    if proposal.diluted_eps_policy != "treasury_stock_proxy_loss_antidilutive":
        raise EquityError("unsupported diluted EPS policy")
    market_quote = _number(packet["facts"]["market_quote"].get("value"), "dated market quote", allow_zero=False)
    if abs(proposal.existing_claim_price - market_quote) > TOLERANCE:
        raise EquityError("existing claim price must equal the selected dated market quote")
    cash_issuance_ratio = _number(packet["facts"]["cash_issuance"].get("ratio"), "cash issuance ratio")
    if abs(proposal.cash_issuance_ratio - cash_issuance_ratio) > TOLERANCE:
        raise EquityError("cash issuance ratio is application-resolved from source arithmetic")
    repurchase_ratio = _number(packet["facts"]["program_repurchase"]["ratio_reference"].get("ratio"), "repurchase ratio")
    if min(abs(proposal.repurchase_ratio - repurchase_ratio), abs(proposal.repurchase_ratio)) > TOLERANCE:
        raise EquityError("repurchase ratio must use the application-resolved source calibration or supported zero-program case")
    if market_quote <= 0:
        raise EquityError("missing market quote blocks existing claim")


def _review_eligible(review: EquityReview) -> bool:
    checks = (review.method_valid, review.source_valid, review.period_valid, review.sbc_bridge_valid, review.share_bridge_valid, review.equity_bridge_valid, review.cash_bridge_valid, review.eps_valid, review.valuation_valid, review.ufcf_independent, review.no_double_count, review.funding_visible)
    return review.evidence_strength != "weak" and all(checks)


def _review_contract(review: EquityReview) -> None:
    if review.verdict == "revise" and (review.target == "none" or not review.required_revision):
        raise EquityError("revise verdict needs target and required revision")
    if review.verdict != "revise" and (review.target != "none" or review.required_revision is not None):
        raise EquityError("accept/reject verdict cannot carry revision target")


def review_proposal(proposal: EquityProposal, packet: dict[str, Any]) -> EquityReview:
    validate_proposal(proposal, packet)
    forecast = forecast_values(packet, proposal)
    valid = forecast["checks"]["all_pass"]
    return EquityReview(
        verdict="accept" if valid else "reject", evidence_strength="mixed",
        method_valid=True, source_valid=True, period_valid=True,
        sbc_bridge_valid=forecast["checks"]["sbc_bridge"], share_bridge_valid=forecast["checks"]["share_bridge"],
        equity_bridge_valid=forecast["checks"]["equity_bridge"], cash_bridge_valid=forecast["checks"]["cash_bridge"],
        eps_valid=forecast["checks"]["eps"], valuation_valid=forecast["checks"]["valuation"],
        ufcf_independent=forecast["checks"]["ufcf"], no_double_count=forecast["checks"]["no_double_count"],
        funding_visible=forecast["checks"]["funding_visible"],
        concerns=["Existing inventory, delivery timing and future prices remain provisional proxies."],
        required_revision=None, target="none",
        rationale="Deterministic review preserves reported equity, separates existing claim from future expense, and checks cash/share/UFCF bridges.",
    )


def _days_overlap(start: date, end: date, window_start: date, window_end: date) -> int:
    return max(0, (min(end, window_end) - max(start, window_start)).days + 1)


def _period_sbc(packet: dict[str, Any], proposal: EquityProposal, revenue: list[float]) -> dict[str, list[float]]:
    # Opening stocks are measured at the close of the measurement date.  The
    # selected service window therefore starts the following day and ends on
    # the selected anniversary, both inclusive.
    service_start = date.fromisoformat(MEASUREMENT_DATE) + date.resolution
    service_end = date(service_start.year + proposal.existing_service_years, service_start.month, service_start.day) - date.resolution
    total_days = (service_end - service_start).days + 1
    old_cost, old_units = [], []
    service_days = []
    for _, start, end in _PERIOD_SPANS:
        s, e = date.fromisoformat(start), date.fromisoformat(end)
        overlap = _days_overlap(s, e, service_start, service_end)
        service_days.append(overlap)
        fraction = overlap / total_days
        old_cost.append(proposal.existing_unrecognized_cost * fraction)
        old_units.append(proposal.existing_award_units * fraction)
    total = [value * proposal.sbc_ratio for value in revenue]
    new = [value - old for value, old in zip(total, old_cost, strict=True)]
    if any(value < -TOLERANCE for value in new):
        raise EquityError("negative new compensation from selected assumptions")
    return {"total": total, "existing_service": old_cost, "new": new, "existing_units_delivered": old_units, "service_days": service_days, "total_service_days": total_days}


def _forecast_revenue(packet: dict[str, Any]) -> list[float]:
    upstream = packet.get("upstream_model") or {}
    revenue = (upstream.get("operating_forecast") or {}).get("forecast_revenue")
    if not isinstance(revenue, list) or len(revenue) != len(PERIODS):
        raise EquityError("accepted upstream forecast revenue is required for every period")
    return [_number(value, f"forecast revenue[{i}]") for i, value in enumerate(revenue)]


def _upstream_series(upstream: dict[str, Any], path: tuple[str, ...], name: str, *, allow_negative: bool = True) -> list[float]:
    value: Any = upstream
    for key in path:
        if not isinstance(value, dict) or key not in value:
            raise EquityError(f"accepted upstream {name} is missing")
        value = value[key]
    if not isinstance(value, list) or len(value) != len(PERIODS):
        raise EquityError(f"accepted upstream {name} must contain {len(PERIODS)} values")
    result = [_number(item, f"{name}[{i}]") for i, item in enumerate(value)]
    if not allow_negative and any(item < -TOLERANCE for item in result):
        raise EquityError(f"accepted upstream {name} contains a negative value")
    return result


def _upstream_number(upstream: dict[str, Any], path: tuple[str, ...], name: str, *, allow_zero: bool = True) -> float:
    value: Any = upstream
    for key in path:
        if not isinstance(value, dict) or key not in value:
            raise EquityError(f"accepted upstream {name} is missing")
        value = value[key]
    return _number(value, name, allow_zero=allow_zero)


def _asset_depreciation(p8b: dict[str, Any], revenue: list[float]) -> tuple[list[float], list[float], list[float]]:
    """Reproduce the accepted P8B asset schedule inputs for preview only.

    Mog remains the financial authority.  This preview uses the accepted
    P8B source rates and cohort policy so the Python review cannot fall back
    to zero investment or depreciation.
    """
    packet = p8b.get("packet") or {}
    calculated = packet.get("facts", {}).get("calculated") or {}
    financing = p8b.get("financing_forecast") or {}
    parameters = {item.get("name"): item.get("value") for item in (p8b.get("candidate") or {}).get("parameters", [])}
    life = _number(parameters.get("opening_remaining_life_years"), "opening remaining life", allow_zero=False)
    new_life = _number(parameters.get("new_addition_useful_life_years"), "new addition useful life", allow_zero=False)
    timing = _number(parameters.get("new_addition_timing_fraction"), "new addition timing", allow_zero=True)
    if timing < 0 or timing > 1:
        raise EquityError("accepted upstream new addition timing is outside [0,1]")
    cash_rate = _number(parameters.get("cash_ppe_additions_rate"), "cash PP&E additions rate")
    noncash_ratio = _number(parameters.get("noncash_ppe_additions_ratio"), "noncash PP&E additions ratio")
    opening_depreciable = _number(calculated.get("opening_depreciable_net_ppe"), "opening depreciable PP&E") - _upstream_number(financing, ("inputs", "opening_finance_ppe"), "opening finance PP&E")
    if opening_depreciable < -TOLERANCE:
        raise EquityError("accepted upstream opening depreciable PP&E is negative")
    cash_capex = [value * cash_rate for value in revenue]
    recognized = [value * (1 + noncash_ratio) for value in cash_capex]
    # The accepted P8B workbook deliberately uses a 0.25 stub and one-year
    # annual columns.  P8C service-day timing is separate and exact.
    fractions = [0.25] + [1.0] * (len(PERIODS) - 1)
    cumulative: list[float] = []
    running = 0.0
    for fraction in fractions:
        running += fraction
        cumulative.append(running)
    total: list[float] = []
    cohort_depreciation: list[float] = []
    for index, end in enumerate(cumulative):
        start = 0.0 if index == 0 else cumulative[index - 1]
        original_end = min(opening_depreciable, opening_depreciable / life * max(0.0, end))
        original_start = min(opening_depreciable, opening_depreciable / life * max(0.0, start))
        original = max(0.0, original_end - original_start)
        additions = 0.0
        for cohort, cost in enumerate(recognized):
            if index < cohort:
                continue
            cohort_start = 0.0 if cohort == 0 else cumulative[cohort - 1]
            placement = cohort_start + fractions[cohort] * (1 - timing)
            end_charge = min(cost, cost / new_life * max(0.0, end - placement))
            start_charge = min(cost, cost / new_life * max(0.0, start - placement))
            additions += max(0.0, end_charge - start_charge)
        cohort_depreciation.append(additions)
        total.append(original + additions)
    return cash_capex, recognized, total


def forecast_values(packet: dict[str, Any], proposal: EquityProposal, *, _with_sensitivities: bool = True) -> dict[str, Any]:
    validate_proposal(proposal, packet)
    facts = packet["facts"]
    upstream = packet.get("upstream_model")
    if not isinstance(upstream, dict):
        raise EquityError("accepted upstream model is required for P8C forecast")
    revenue = _forecast_revenue(packet)
    sbc = _period_sbc(packet, proposal, revenue)
    price = _number(proposal.settlement_price, "settlement price", allow_zero=False)
    claim_price = _number(proposal.existing_claim_price, "existing claim price", allow_zero=False)
    point_opening = facts["opening_equity"]["point_shares"]
    opening_apic = facts["opening_equity"]["common_apic"]
    opening_retained = facts["opening_equity"]["retained_earnings"]
    opening_aoci = facts["opening_equity"]["aoci"]

    source_ratio = _number((facts.get("ttm") or {}).get("sbc_ratio"), "embedded source SBC ratio")
    source_revenue = _number((facts.get("ttm") or {}).get("revenue"), "source TTM revenue", allow_zero=False)
    gross_cost = _upstream_series(upstream, ("operating_forecast", "gross_cost_total"), "gross operating costs", allow_negative=False)
    embedded_ppe = _upstream_series(upstream, ("operating_forecast", "embedded_ppe_depreciation"), "embedded PP&E depreciation", allow_negative=False)
    financing = upstream.get("financing_forecast") or {}
    financing_inputs = financing.get("inputs") or {}
    embedded_lease_proxy = _number(financing_inputs.get("embedded_operating_lease_cost_proxy"), "embedded operating lease cost proxy")
    financing_forecast = financing.get("forecast") or {}
    pipeline_visible = (financing_forecast.get("pipeline") or {}).get("visible")
    if not isinstance(pipeline_visible, list) or len(pipeline_visible) != len(PERIODS):
        raise EquityError("accepted upstream financing pipeline is required for every period")

    def pipeline_series(name: str, *, allow_negative: bool = False) -> list[float]:
        values = []
        for index, item in enumerate(pipeline_visible):
            if not isinstance(item, dict) or name not in item:
                raise EquityError(f"accepted upstream pipeline {name}[{index}] is missing")
            value = _number(item[name], f"pipeline {name}[{index}]")
            if not allow_negative and value < -TOLERANCE:
                raise EquityError(f"accepted upstream pipeline {name}[{index}] is negative")
            values.append(value)
        return values

    opening_op_expense = _upstream_series(financing, ("forecast", "operating_opening_pool", "expense"), "opening operating lease expense", allow_negative=False)
    opening_op_payment = _upstream_series(financing, ("forecast", "operating_opening_pool", "payment"), "opening operating lease payment", allow_negative=False)
    opening_op_principal = _upstream_series(financing, ("forecast", "operating_opening_pool", "principal"), "opening operating lease principal", allow_negative=False)
    opening_fin_dep = _upstream_series(financing, ("forecast", "finance_opening_pool", "expense"), "opening finance lease depreciation", allow_negative=False)
    opening_fin_interest = _upstream_series(financing, ("forecast", "finance_opening_pool", "interest"), "opening finance lease interest", allow_negative=False)
    opening_fin_principal = _upstream_series(financing, ("forecast", "finance_opening_pool", "principal"), "opening finance lease principal", allow_negative=False)
    pipeline_op_expense = pipeline_series("operating_expense")
    pipeline_op_payment = pipeline_series("operating_payment")
    pipeline_op_principal = pipeline_series("operating_principal")
    pipeline_fin_dep = pipeline_series("finance_depreciation")
    pipeline_fin_interest = pipeline_series("finance_interest")
    pipeline_fin_principal = pipeline_series("finance_principal")
    pipeline_fin_additions = pipeline_series("finance_additions")
    operating_lease_expense = [a + b for a, b in zip(opening_op_expense, pipeline_op_expense, strict=True)]
    operating_lease_payment = [a + b for a, b in zip(opening_op_payment, pipeline_op_payment, strict=True)]
    operating_lease_principal = [a + b for a, b in zip(opening_op_principal, pipeline_op_principal, strict=True)]
    # The lease identity is used here as an input bridge, while the workbook
    # computes the same relationship from its Financing rows.
    operating_lease_amortization = [expense - payment + principal for expense, payment, principal in zip(operating_lease_expense, operating_lease_payment, operating_lease_principal, strict=True)]
    finance_lease_depreciation = [a + b for a, b in zip(opening_fin_dep, pipeline_fin_dep, strict=True)]
    finance_lease_interest = [a + b for a, b in zip(opening_fin_interest, pipeline_fin_interest, strict=True)]
    finance_lease_principal = [a + b for a, b in zip(opening_fin_principal, pipeline_fin_principal, strict=True)]
    debt_expense = _upstream_series(upstream, ("financing_forecast", "forecast", "debt", "book_financing_expense"), "debt book financing expense", allow_negative=False)
    debt_contra_release = _upstream_series(upstream, ("financing_forecast", "forecast", "debt", "contra_release_expense"), "debt contra release", allow_negative=False)
    debt_repayment = _upstream_series(upstream, ("financing_forecast", "forecast", "debt", "cash_repayment"), "debt repayment", allow_negative=False)
    debt_proceeds = _upstream_series(upstream, ("financing_forecast", "forecast", "debt", "cash_proceeds"), "debt proceeds", allow_negative=False)
    cash_capex, recognized_ppe, depreciation = _asset_depreciation(upstream, revenue)
    noncash_ppe = [recognized - cash for recognized, cash in zip(recognized_ppe, cash_capex, strict=True)]
    integrated_costs = []
    book_sbc = sbc["total"]
    for index in range(len(PERIODS)):
        embedded_sbc = revenue[index] * source_ratio
        embedded_lease = embedded_lease_proxy * revenue[index] / source_revenue
        integrated_costs.append(gross_cost[index] - embedded_ppe[index] - embedded_lease + operating_lease_expense[index] - embedded_sbc + book_sbc[index])
    book_ebit = [revenue[index] - integrated_costs[index] - depreciation[index] - finance_lease_depreciation[index] for index in range(len(PERIODS))]
    # Finance-lease depreciation is a financing-row component of total D&A;
    # the accepted P8B asset schedule already supplies the PP&E components.
    total_depreciation = [depreciation[index] + finance_lease_depreciation[index] for index in range(len(PERIODS))]
    interest_expense = [debt_expense[index] + finance_lease_interest[index] for index in range(len(PERIODS))]
    pretax_income = [ebit - interest for ebit, interest in zip(book_ebit, interest_expense, strict=True)]
    tax_forecast = upstream.get("tax_forecast") or {}
    tax_inputs = tax_forecast.get("inputs") or {}
    book_tax_rate = _number(tax_inputs.get("book_tax_rate"), "book tax rate")
    operating_tax_rate = _number(tax_inputs.get("operating_tax_rate"), "operating tax rate")
    deferred_shares = tax_inputs.get("deferred_share")
    if not isinstance(deferred_shares, list) or len(deferred_shares) != len(PERIODS):
        raise EquityError("accepted upstream deferred-tax share is required for every period")
    deferred_shares = [_number(value, f"deferred tax share[{index}]") for index, value in enumerate(deferred_shares)]
    period_days = _upstream_series(upstream, ("tax_forecast", "inputs", "period_days"), "tax period days", allow_negative=False)
    payable_days = _upstream_number(upstream, ("tax_forecast", "inputs", "current_tax_payable_days"), "current tax payable days", allow_zero=False)
    long_term_settlement = _upstream_series(upstream, ("tax_forecast", "forecast", "long_term_tax_settlement"), "long-term tax settlement", allow_negative=False)
    opening_current_tax = _upstream_number(upstream, ("tax_forecast", "inputs", "opening_current_tax_payable"), "opening current tax payable")
    book_tax, deferred_tax, current_tax, payable_opening, payable_closing, current_tax_payment, cash_taxes, tax_bridge_adjustment = [], [], [], [], [], [], [], []
    for index, pretax in enumerate(pretax_income):
        book = max(0.0, pretax) * book_tax_rate
        deferred = book * deferred_shares[index]
        current = book - deferred
        opening = opening_current_tax if index == 0 else payable_closing[-1]
        closing = current / period_days[index] * payable_days
        payment = current + opening - closing
        cash = payment + long_term_settlement[index]
        book_tax.append(book)
        deferred_tax.append(deferred)
        current_tax.append(current)
        payable_opening.append(opening)
        payable_closing.append(closing)
        current_tax_payment.append(payment)
        cash_taxes.append(cash)
        tax_bridge_adjustment.append(deferred + closing - opening - long_term_settlement[index])
    cash_issue = [value * proposal.cash_issuance_ratio for value in revenue]
    issue_units = [value / price for value in cash_issue]
    gross_new_units = [value / price for value in sbc["new"]]
    gross_old_units = sbc["existing_units_delivered"]
    gross_delivered = [old + new for old, new in zip(gross_old_units, gross_new_units, strict=True)]
    withheld_units = [value * proposal.withholding_rate for value in gross_delivered]
    net_delivered = [value - withheld for value, withheld in zip(gross_delivered, withheld_units, strict=True)]
    withholding_cash = [value * price for value in withheld_units]
    program_target = [value * proposal.repurchase_ratio for value in revenue]
    remaining_auth = proposal.repurchase_authorization
    program_cash, program_units, auth_after = [], [], []
    for target in program_target:
        spend = min(target, remaining_auth)
        program_cash.append(spend)
        program_units.append(spend / price)
        remaining_auth -= spend
        auth_after.append(remaining_auth)
    net_income = [pretax - tax for pretax, tax in zip(pretax_income, book_tax, strict=True)]
    old_tax_shield = [old * operating_tax_rate for old in sbc["existing_service"]]
    valuation_ebit = [book + old for book, old in zip(book_ebit, sbc["existing_service"], strict=True)]
    normalized_tax = [max(0.0, value) * operating_tax_rate for value in valuation_ebit]
    nwc = _upstream_series(upstream, ("working_capital_forecast", "forecast", "cash_conversion_nwc_change"), "cash-conversion NWC change")
    valuation_ufcf = [e - t + d + lease_expense - lease_payment - ppe - finance_addition - working_capital for e, t, d, lease_expense, lease_payment, ppe, finance_addition, working_capital in zip(valuation_ebit, normalized_tax, total_depreciation, operating_lease_expense, operating_lease_payment, recognized_ppe, pipeline_fin_additions, nwc, strict=True)]
    cfo = []
    for index in range(len(PERIODS)):
        cfo.append(net_income[index] + total_depreciation[index] + operating_lease_amortization[index] + debt_contra_release[index] - operating_lease_principal[index] + book_sbc[index] + tax_bridge_adjustment[index] - nwc[index])
    cfo_ufcf = [cfo_value + debt_expense[index] + finance_lease_interest[index] + cash_taxes[index] - normalized_tax[index] - sbc["new"][index] - debt_contra_release[index] - recognized_ppe[index] - pipeline_fin_additions[index] for index, cfo_value in enumerate(cfo)]
    point_closing, basic_weighted = [], []
    current = point_opening
    for index in range(len(PERIODS)):
        net = net_delivered[index] + issue_units[index] - program_units[index]
        point_closing.append(current + net)
        basic_weighted.append(current + net_delivered[index] * proposal.delivery_timing + issue_units[index] * proposal.issuance_timing - program_units[index] * proposal.repurchase_timing)
        current = point_closing[-1]
    declaration = []
    payable_opening, payable_closing, dividends_paid = [], [], []
    opening_payable = facts["dividend"]["opening_payable"]
    point_opening_by_period = [point_opening] + point_closing[:-1]
    for index, shares in enumerate(point_opening_by_period):
        opening = opening_payable if index == 0 else payable_closing[index - 1]
        quarter_count = proposal.dividend_quarters_stub if index == 0 else proposal.dividend_quarters_annual
        declared = shares * proposal.dividend_per_share_quarter * quarter_count
        close = shares * proposal.dividend_per_share_quarter
        payable_opening.append(opening)
        declaration.append(declared)
        payable_closing.append(close)
        dividends_paid.append(opening + declared - close)
    remaining_units_opening, remaining_units_closing, remaining_cost_opening, remaining_cost_closing, diluted_increment = [], [], [], [], []
    units_remaining = proposal.existing_award_units
    cost_remaining = proposal.existing_unrecognized_cost
    for index, service_cost in enumerate(sbc["existing_service"]):
        units_open = units_remaining
        cost_open = cost_remaining
        units_remaining = max(0.0, units_remaining - gross_old_units[index])
        cost_remaining = max(0.0, cost_remaining - service_cost)
        units_close = units_remaining
        cost_close = cost_remaining
        remaining_units_opening.append(units_open)
        remaining_units_closing.append(units_close)
        remaining_cost_opening.append(cost_open)
        remaining_cost_closing.append(cost_close)
        average_units = (units_open + units_close) / 2
        average_cost = (cost_open + cost_close) / 2
        diluted_increment.append(max(0.0, average_units - average_cost / price) if net_income[index] >= 0 else 0.0)
    claim = proposal.existing_award_units * claim_price
    # Retirement basis follows the selected current-period opening convention:
    # reported opening APIC/shares in the stub, then each prior closing balance.
    program_basis = []
    program_opening_apic = []
    program_opening_shares = []
    rolling_apic, rolling_shares = opening_apic, point_opening
    for index, units in enumerate(program_units):
        program_opening_apic.append(rolling_apic)
        program_opening_shares.append(rolling_shares)
        if units > TOLERANCE:
            if rolling_shares <= TOLERANCE:
                raise EquityError(f"period {index} has no positive opening shares for retirement basis")
            if price < rolling_apic / rolling_shares - TOLERANCE:
                raise EquityError(f"settlement price is below period {index} opening APIC retirement basis")
        basis = rolling_apic / rolling_shares * units if rolling_shares > TOLERANCE else 0.0
        if basis > rolling_apic + TOLERANCE:
            raise EquityError(f"period {index} retirement basis exceeds opening APIC")
        program_basis.append(basis)
        rolling_apic += sbc["total"][index] + cash_issue[index] - withholding_cash[index] - basis
        rolling_shares += net_delivered[index] + issue_units[index] - units
    program_excess = [cash - basis for cash, basis in zip(program_cash, program_basis, strict=True)]
    apic_closing, retained_closing, equity_closing = [], [], []
    apic, retained = opening_apic, opening_retained
    for i in range(len(PERIODS)):
        apic += sbc["total"][i] + cash_issue[i] - withholding_cash[i] - program_basis[i]
        retained += net_income[i] - declaration[i] - program_excess[i]
        apic_closing.append(apic)
        retained_closing.append(retained)
        equity_closing.append(apic + retained + opening_aoci)
    cash_fact = ((upstream.get("packet") or {}).get("facts") or {}).get("opening_balance_sheet", {}).get("cash")
    opening_cash = _number(cash_fact.get("value") if isinstance(cash_fact, dict) else cash_fact, "opening cash")
    net_debt_cash = [proceeds - repayment for proceeds, repayment in zip(debt_proceeds, debt_repayment, strict=True)]
    cash_change, closing_cash = [], []
    cash = opening_cash
    for index in range(len(PERIODS)):
        change = cfo[index] - cash_capex[index] + net_debt_cash[index] - finance_lease_principal[index] + cash_issue[index] - withholding_cash[index] - program_cash[index] - dividends_paid[index]
        cash_change.append(change)
        cash += change
        closing_cash.append(cash)
    checks = {
        "sbc_bridge": all(abs(total - old - new) <= 1e-7 for total, old, new in zip(sbc["total"], sbc["existing_service"], sbc["new"], strict=True)),
        "share_bridge": all(abs(close - (point_opening if i == 0 else point_closing[i - 1]) - net_delivered[i] - issue_units[i] + program_units[i]) <= 1e-7 for i, close in enumerate(point_closing)),
        "equity_bridge": all(abs(eq - ap - re - facts["opening_equity"]["aoci"]) <= 1e-7 for eq, ap, re in zip(equity_closing, apic_closing, retained_closing, strict=True)),
        "cash_bridge": all(abs(closing_cash[i] - (opening_cash if i == 0 else closing_cash[i - 1]) - cash_change[i]) <= 1e-7 for i in range(len(PERIODS))),
        "eps": all(value > 0 for value in basic_weighted),
        "valuation": all(math.isfinite(value) for value in valuation_ufcf),
        "ufcf": all(abs(a - b) <= 1e-7 for a, b in zip(valuation_ufcf, cfo_ufcf, strict=True)),
        "service_calendar": sum(sbc["service_days"]) == sbc["total_service_days"],
        "full_runoff": abs(sum(sbc["existing_service"]) - proposal.existing_unrecognized_cost) <= 1e-7 and abs(sum(sbc["existing_units_delivered"]) - proposal.existing_award_units) <= 1e-7,
        "apic_supported": opening_apic >= 0 and all(basis <= opening_value + TOLERANCE for basis, opening_value in zip(program_basis, program_opening_apic, strict=True)) and all(value >= -TOLERANCE for value in apic_closing),
        "no_double_count": claim > 0 and all(value >= 0 for value in sbc["new"]) and opening_apic >= 0 and all(basis <= opening_value + TOLERANCE for basis, opening_value in zip(program_basis, program_opening_apic, strict=True)),
        "funding_visible": all(math.isfinite(value) for value in closing_cash),
    }
    checks["all_pass"] = all(checks.values())
    sensitivities = []
    for name, updates in (
        ("sbc_ratio_minus_20pct", {"sbc_ratio": proposal.sbc_ratio * 0.8}),
        ("sbc_ratio_plus_20pct", {"sbc_ratio": proposal.sbc_ratio * 1.2}),
        ("existing_units_minus_20pct", {"existing_award_units": proposal.existing_award_units * 0.8}),
        ("existing_units_plus_20pct", {"existing_award_units": proposal.existing_award_units * 1.2}),
        ("existing_cost_minus_25pct", {"existing_unrecognized_cost": proposal.existing_unrecognized_cost * 0.75}),
        ("existing_cost_plus_25pct", {"existing_unrecognized_cost": proposal.existing_unrecognized_cost * 1.25}),
        ("settlement_price_minus_25pct", {"settlement_price": proposal.settlement_price * 0.75}),
        ("settlement_price_plus_25pct", {"settlement_price": proposal.settlement_price * 1.25}),
    ):
        variant = proposal.model_copy(update=updates)
        try:
            variant_data = forecast_values(packet, variant, _with_sensitivities=False) if _with_sensitivities else None
            if variant_data is None:
                continue
            sensitivities.append({"name": name, "status": "PASS", "terminal_point_shares": variant_data["point_shares_closing"][-1], "claim": variant_data["existing_claim"]})
        except EquityError as exc:
            sensitivities.append({"name": name, "status": "BLOCKED", "reason": str(exc)})
    return {
        "periods": list(PERIODS), "period_meta": period_meta(), "revenue": revenue,
        "sbc": sbc, "cash_issuance": cash_issue, "issue_units": issue_units,
        "gross_new_units": gross_new_units, "gross_existing_units": gross_old_units,
        "withheld_units": withheld_units, "withholding_cash": withholding_cash, "net_delivered_units": net_delivered,
        "program_target": program_target, "program_cash": program_cash, "program_units": program_units,
        "program_authorization_remaining": auth_after, "program_apic_basis": program_basis,
        "program_opening_apic": program_opening_apic, "program_opening_point_shares": program_opening_shares,
        "program_retirement_excess": program_excess, "dividend_declaration": declaration,
        "dividend_payable_opening": payable_opening, "dividend_payable_closing": payable_closing, "dividend_cash_paid": dividends_paid,
        "book_ebit": book_ebit, "net_income": net_income, "cfo": cfo, "book_tax": book_tax, "cash_taxes": cash_taxes, "tax_bridge_adjustment": tax_bridge_adjustment,
        "valuation_ebit": valuation_ebit, "existing_service_tax_shield": old_tax_shield,
        "normalized_tax": normalized_tax, "valuation_ufcf": valuation_ufcf, "cfo_ufcf": cfo_ufcf,
        "cash_capex": cash_capex, "noncash_ppe_additions": noncash_ppe, "recognized_ppe_additions": recognized_ppe,
        "finance_lease_additions": pipeline_fin_additions, "capex": recognized_ppe, "depreciation": total_depreciation, "nwc": nwc,
        "interest_expense": interest_expense, "integrated_operating_costs": integrated_costs,
        "opening_cash": opening_cash, "cash_change": cash_change, "closing_cash": closing_cash,
        "point_shares_opening": [point_opening] + point_closing[:-1], "point_shares_closing": point_closing,
        "basic_weighted_shares": basic_weighted, "diluted_increment": diluted_increment,
        "basic_eps": [ni / shares for ni, shares in zip(net_income, basic_weighted, strict=True)],
        "diluted_eps": [ni / (shares + dil) for ni, shares, dil in zip(net_income, basic_weighted, diluted_increment, strict=True)],
        "existing_claim": claim, "existing_claim_price": claim_price,
        "remaining_existing_units_opening": remaining_units_opening, "remaining_existing_units_closing": remaining_units_closing,
        "remaining_existing_cost_opening": remaining_cost_opening, "remaining_existing_cost_closing": remaining_cost_closing,
        "apic_closing": apic_closing, "retained_earnings_closing": retained_closing, "aoci_closing": [opening_aoci] * len(PERIODS), "equity_closing": equity_closing,
        "sensitivities": sensitivities, "policy": proposal.model_dump(mode="json"), "checks": checks,
        "source_claims": {"opening_apic": opening_apic, "opening_retained_earnings": opening_retained, "opening_aoci": opening_aoci, "opening_equity": facts["opening_equity"]["total_equity"], "opening_point_shares": point_opening, "embedded_source_sbc_ratio": source_ratio, "market_quote": facts["market_quote"], "future_settlement_price": facts["future_settlement_price"]},
    }


def _calculation_implementation_hashes() -> dict[str, str]:
    root = Path(__file__).resolve().parents[2]
    paths = ("src/smrik_fund/equity.py", "scripts/spreadsheet_compat/asset_model.mjs", "scripts/spreadsheet_compat/run-p8c.mjs")
    return {item: _sha256(root / Path(*item.split("/"))) for item in paths if (root / Path(*item.split("/"))).is_file()}


def build_equity_model(p8b: dict[str, Any], packet: dict[str, Any], proposal: EquityProposal, review: EquityReview, *, context: dict[str, Any] | None = None, decision_status: str = "REVIEW_REQUIRED") -> dict[str, Any]:
    validate_proposal(proposal, packet)
    forecast = forecast_values(packet, proposal)
    context = context or {"case": CASE, "measurement_date": MEASUREMENT_DATE, "method_id": METHOD_ID, "method_version": METHOD_VERSION}
    candidate_hash = content_hash(proposal.model_dump(mode="json"))
    review_hash = content_hash(review.model_dump(mode="json"))
    packet_hash = content_hash(packet)
    context = {**context, "proposal_hash": candidate_hash, "review_hash": review_hash, "source_packet_hash": packet_hash}
    binding = {"candidate_hash": candidate_hash, "review_hash": review_hash, "context_hash": content_hash(context), "source_packet_hash": packet_hash, "candidate_snapshot": proposal.model_dump(mode="json"), "review_snapshot": review.model_dump(mode="json"), "source_case_snapshot_sha256": packet["accepted_upstream"]["source_case_snapshot_sha256"]}
    decision = {"decision_id": "P8C-MSFT-EQUITY-DECISION-R5", "status": decision_status, "review": review.model_dump(mode="json"), "candidate_hash": candidate_hash, "review_hash": review_hash, "context_hash": content_hash(context), "source_packet_hash": packet_hash, "binding": binding, "authoritative_mog_attached": False, "human_approval": False}
    opening = packet["facts"]["opening_equity"]
    return {"schema_version": "p8c-msft-equity-model-r5", "case": CASE, "information_cutoff": INFORMATION_CUTOFF, "measurement_date": MEASUREMENT_DATE, "method": {"id": METHOD_ID, "version": METHOD_VERSION, "catalog_version": METHOD_CATALOG_VERSION}, "packet": packet, "inputs": {"common_apic": opening["common_apic"], "retained_earnings": opening["retained_earnings"], "aoci": opening["aoci"], "total_equity": opening["total_equity"], "point_shares": opening["point_shares"], "opening_dividend_payable": packet["facts"]["dividend"]["opening_payable"], "embedded_sbc_ratio": packet["facts"]["ttm"]["sbc_ratio"]}, "forecast": forecast, "provenance_contract": {"version": PROVENANCE_CONTRACT_VERSION, "source_facts_locked": True, "reported_sbc": "P8C source table TTM 12,356 USDm", "stale_proxy": "FY25 82m units / 21,600 USDm / 3 years", "market_quote": packet["facts"]["market_quote"], "prices_are_exogenous": True}, "decision": decision, "limitations": packet["limitations"], "context": context}


def _strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    schema = to_strict_json_schema(model)
    _assert_strict_schema(schema)
    return schema


def _assert_strict_schema(node: Any) -> None:
    if isinstance(node, dict):
        if (node.get("type") == "object" or "properties" in node) and (
            set(node.get("properties", {})) != set(node.get("required", []))
            or node.get("additionalProperties") is not False
        ):
            raise EquityError("strict schema requires all properties and forbids extras")
        for value in node.values():
            _assert_strict_schema(value)
    elif isinstance(node, list):
        for value in node:
            _assert_strict_schema(value)


def _request(instruction: str, payload: dict[str, Any], response_model: type[BaseModel]) -> dict[str, Any]:
    name = "equity_review_r5" if response_model is EquityReview else "equity_proposal_r5"
    return {"model": MODEL, "reasoning": {"effort": REASONING_EFFORT}, "service_tier": "default", "input": json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")), "instructions": instruction, "text": {"format": {"type": "json_schema", "name": name, "strict": True, "schema": _strict_schema(response_model)}}, "max_output_tokens": MAX_OUTPUT_TOKENS, "tools": [], "background": False}


def _run_context(p8b: dict[str, Any], packet: dict[str, Any]) -> dict[str, Any]:
    selected = default_proposal(packet)
    prior = {key: {"status": (p8b.get(key) or {}).get("status"), "decision_id": (p8b.get(key) or {}).get("decision_id"), "hash": content_hash(p8b.get(key) or {})} for key in ("decision", "p5_decision", "p6_decision", "p7_decision", "p8a_decision", "p8b_decision") if isinstance(p8b.get(key), dict)}
    files = _calculation_implementation_hashes()
    context = {"schema_version": SCHEMA_VERSION, "contract_version": CONTRACT_VERSION, "proposal_schema_hash": content_hash(_strict_schema(EquityProposal)), "review_schema_hash": content_hash(_strict_schema(EquityReview)), "prompt_version": PROMPT_VERSION, "method_catalog_version": METHOD_CATALOG_VERSION, "method_id": METHOD_ID, "method_version": METHOD_VERSION, "implementation_files": files, "implementation_aggregate_sha256": content_hash(files), "model": MODEL, "reasoning_effort": REASONING_EFFORT, "max_output_tokens": MAX_OUTPUT_TOKENS, "endpoint": ENDPOINT_URL, "service_tier": "default", "tools": [], "background": False, "max_retries": 0, "case": CASE, "information_cutoff": INFORMATION_CUTOFF, "measurement_date": MEASUREMENT_DATE, "source_packet_hash": content_hash(packet), "accepted_upstream": packet["accepted_upstream"], "selected_policy_hash": content_hash(selected.model_dump(mode="json")), "prior_decisions": prior}
    context["method_contract_hash"] = content_hash(_method_contract(packet, context))
    return context


def _method_contract(packet: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Expose the selected method without turning the analyst into the calculator."""
    facts = packet["facts"]
    ttm = facts["ttm"]
    issuance = facts["cash_issuance"]
    repurchase = facts["program_repurchase"]
    repurchase_reference = repurchase["ratio_reference"]
    market_quote = facts["market_quote"]
    existing = facts["existing_awards"]
    withholding = facts["withholding"]
    inactive_fields = [
        "method_id", "method_version", "sbc_ratio", "existing_award_units",
        "existing_unrecognized_cost", "existing_service_years", "existing_claim_price",
        "settlement_price", "withholding_rate", "cash_issuance_ratio", "repurchase_ratio",
        "repurchase_authorization", "dividend_per_share_quarter", "dividend_quarters_stub",
        "dividend_quarters_annual", "delivery_timing", "issuance_timing", "repurchase_timing",
        "repurchase_policy", "settlement_policy", "diluted_eps_policy",
    ]
    fixed_fields = {
        "method_id": {"value": METHOD_ID, "classification": "method", "locked": True},
        "method_version": {"value": METHOD_VERSION, "classification": "method", "locked": True},
        "existing_claim_price": {
            "value": market_quote["value"], "unit": "USD/share", "classification": "source",
            "source_date": market_quote["date"], "source_ref": market_quote["source"],
            "basis": "selected Mar31 unadjusted close; historical grant-date fair value is not a measurement-date price",
            "locked": True,
        },
        "cash_issuance_ratio": {
            "value": issuance["ratio"], "unit": "decimal fraction", "classification": "calculated",
            "formula": "(2056 + 1489 - 1508) / 318273", "source_ref": "P8C_POLICY.md cash issuance calibration",
            "locked": True,
        },
        "repurchase_authorization": {
            "value": repurchase["authorization_remaining"], "unit": "USD millions", "classification": "source",
            "basis": "disclosed remaining authorization at the measurement boundary; no renewal in base",
            "locked": True,
        },
        "dividend_quarters_stub": {"value": 1, "unit": "declared quarters", "classification": "estimate", "basis": "selected one-quarter Apr-Jun stub schedule", "locked": True},
        "dividend_quarters_annual": {"value": 4, "unit": "declared quarters", "classification": "estimate", "basis": "selected four-quarter annual schedule", "locked": True},
        "repurchase_policy": {"value": "cap_disclosed_authorization", "classification": "method", "locked": True},
        "settlement_policy": {"value": "service_delivery_exogenous_price", "classification": "method", "locked": True},
        "diluted_eps_policy": {"value": "treasury_stock_proxy_loss_antidilutive", "classification": "method", "locked": True},
    }
    changeable = [
        "sbc_ratio", "existing_award_units", "existing_unrecognized_cost", "existing_service_years",
        "settlement_price", "withholding_rate", "repurchase_ratio", "dividend_per_share_quarter",
        "delivery_timing", "issuance_timing", "repurchase_timing",
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "contract_version": CONTRACT_VERSION,
        "method_catalog_version": METHOD_CATALOG_VERSION,
        "allowed_method_ids": [METHOD_ID],
        "allowed_outcomes": ["propose_forecast", "unresolved", "capability_gap"],
        "fixed_application_fields": fixed_fields,
        "changeable_judgment_fields": changeable,
        "judgment_constraints": {
            "sbc_ratio": {"unit": "decimal fraction", "minimum": 0, "maximum": 1, "base": ttm["sbc_ratio"], "base_label": "calculated TTM source proxy; future estimate"},
            "existing_award_units": {"unit": "millions of shares", "minimum": 0, "base": existing["units"], "label": "stale FY25 proxy; not a Q3 disclosure"},
            "existing_unrecognized_cost": {"unit": "USD millions", "minimum": 0, "base": existing["unrecognized_cost"], "label": "stale FY25 proxy; not a Q3 disclosure"},
            "existing_service_years": {"unit": "integer years", "allowed": [2, 3, 4], "base": existing["service_years"], "label": "explicit service-window estimate"},
            "settlement_price": {"unit": "USD/share", "exclusive_minimum": 0, "base": facts["future_settlement_price"]["value"], "label": "future exogenous settlement estimate; no circular model value"},
            "withholding_rate": {"unit": "decimal fraction", "minimum": 0, "maximum": 1, "base": withholding["rate"], "formula": "5400 / 16200", "label": "calculated historical proxy; future estimate"},
            "repurchase_ratio": {"unit": "USD millions / USD millions", "allowed": [0.0, repurchase_reference["ratio"]], "base": repurchase_reference["ratio"], "zero_case": "supported zero-program scenario"},
            "dividend_per_share_quarter": {"unit": "USD/share/quarter", "minimum": 0, "base": facts["dividend"]["per_share_quarter"], "label": "flat future estimate anchored to selected policy"},
            "timing": {"unit": "period fraction of movement outstanding", "minimum": 0, "maximum": 1, "base": 0.5, "semantics": "0 means the movement occurs at period end; 1 means it occurs at period opening; midpoint 0.5 is an explicit estimate and controls weighted-average-share timing"},
        },
        "application_owned_arithmetic": {
            "ttm_sbc": {"value": ttm["sbc"], "unit": "USD millions", "classification": "calculated", "formula": "11974 + 9283 - 8901", "basis": ttm["basis"]},
            "ttm_sbc_ratio": {"value": ttm["sbc_ratio"], "unit": "decimal fraction", "classification": "calculated", "formula": "12356 / 318273", "basis": "TTM source proxy"},
            "cash_issuance_ratio": {"value": issuance["ratio"], "unit": "decimal fraction", "classification": "calculated", "formula": "2037 / 318273", "basis": issuance["basis"]},
            "repurchase_ratio": {"value": repurchase_reference["ratio"], "unit": "decimal fraction", "classification": "calculated", "formula": "13319 / 241832", "basis": repurchase_reference["basis"], "source_cash": 13319.0, "source_revenue": 241832.0},
            "future_settlement_price": {"value": facts["future_settlement_price"]["value"], "unit": "USD/share", "classification": "calculated historical proxy / future estimate", "formula": "13319 / 27", "basis": facts["future_settlement_price"]["basis"]},
            "withholding_rate": {"value": withholding["rate"], "unit": "decimal fraction", "classification": "calculated historical proxy / future estimate", "formula": "5400 / 16200", "basis": withholding["basis"]},
        },
        "selected_prospective_estimates": {
            "existing_award_bundle": {"units": existing["units"], "unrecognized_cost": existing["unrecognized_cost"], "service_years": existing["service_years"], "unit": "millions of shares / USD millions / integer years", "classification": "estimate", "limitation": existing["basis"]},
            "timing": {"delivery_timing": 0.5, "issuance_timing": 0.5, "repurchase_timing": 0.5, "unit": "period fraction of movement outstanding", "classification": "estimate", "rationale": "A movement at period end contributes zero to the period weighted-average denominator; a movement at period opening contributes its full units. Evenly distributed flows use midpoint; point shares still roll at closing."},
            "dividend": {"per_share_quarter": facts["dividend"]["per_share_quarter"], "unit": "USD/share/quarter", "classification": "estimate", "rationale": "Nominally flat selected future rate; declarations reduce retained earnings and payments reduce the payable/CFF."},
        },
        "outcome_contract": {
            "propose_forecast": {"required": "every forecast field is populated", "follow_up_request": "must be null", "publication": "eligible only after application validation and independent review"},
            "unresolved": {"forecast_fields": "all inactive fields must be null", "follow_up_request": "required concrete missing-evidence/request text", "publication": "no forecast"},
            "capability_gap": {"forecast_fields": "all inactive fields must be null", "follow_up_request": "required concrete unsupported-capability request text", "publication": "no forecast"},
        },
        "nonforecast_inactive_fields_must_be_null": inactive_fields,
        "revision_contract": {"fixed_fields_are_not_revision_choices": True, "fixed_source_arithmetic": ["cash_issuance_ratio = 2037 / 318273"], "repurchase_exception": "repurchase_ratio may retain the source-calibrated 13319 / 241832 base or select the supported zero-program policy 0.0", "supported_revision_fields": changeable, "revision_must_change_effective_forecast": True, "unsupported_fixed_change_outcome": "capability_gap_or_reject", "prior_output_preserved_on_failure": True},
        "source_and_explanation_contract": {"source_facts_locked": True, "candidate_explanation_is_not_source_evidence": True, "labels_required": ["source", "calculated", "estimate"], "missing_is_not_zero": True, "no_runtime_code": True, "no_human_approval": True},
        "valuation_contract": {"existing_claim": "existing award units * dated 370.17 USD/share, deducted once from equity value", "partial_bridge": "actual Mog DCF B22 is the pre-claim cash/debt bridge; DCF B26 links Equity!B40; DCF B27 = B22 - B26; DCF B28 = measurement-date Inputs!B227 (7429m); DCF B29 = B27 / B28", "pending_limitations": "P8D investments, P8B lease claims and P9 terminal/complete valuation conventions remain outside this partial diagnostic", "future_compensation": "new compensation remains economic cost; reverse only its CFO add-back", "no_double_count": "existing claim is not added to current denominator and existing service expense is removed only in valuation operating-profit bridge", "prices": "settlement and repurchase pricing remain exogenous"},
        "units": {"amounts": "USD millions", "shares": "millions of shares", "prices": "USD/share", "rates": "decimal fraction", "timing": "period fraction", "dates": "ISO date"},
    }


ANALYST_INSTRUCTION = """Select one bounded P8C proposal using the supplied method contract. Return only the strict schema. For propose_forecast, populate every forecast field and set follow_up_request to null. For unresolved or capability_gap, set every inactive forecast field to null and provide a concrete follow_up_request; publish no forecast. Treat source facts and application-owned arithmetic as locked. Use the contract's 370.17 USD/share dated market quote for existing_claim_price, not the 413.9 historical grant-date fair value. Use the application-resolved 13319/241832 repurchase calibration or the supported zero-program policy 0.0, and the fixed 2037/318273 issuance calibration; do not invent denominators. Timing fractions are fractions of the movement outstanding during the period: 0 means period end, 1 means period opening, and 0.5 is the explicit midpoint estimate. Label rationale/evidence as source, calculated, or estimate, preserve limitations, and retain only supported revisions; do not return code or claim human approval."""
REVIEW_INSTRUCTION = """Independently review the P8C candidate against the supplied method contract and actual Mog consequences. Return only the strict reviewer schema. Check source/calculated/estimate labels, locked 370.17 USD/share existing-claim price, fixed 2037/318273 issuance arithmetic, repurchase calibration as either 13319/241832 or supported zero-program 0.0, opening/end timing semantics, cash/share/equity/UFCF bridges, and the actual Mog DCF claim/per-share fields: Equity!B40 -> DCF!B26 exactly once, DCF!B27 = pre-claim DCF!B22 minus that claim, DCF!B28 = measurement-date 7429m point shares, and DCF!B29 = B27/B28. Confirm the claim, denominator and partial-bridge limitations are visible in the actual snapshot/output; no outstanding awards may be added to B28. Check no double count, funding and sensitivities. Judge a source-anchored provisional estimate and its limitations; do not promote candidate prose to source evidence or require undisclosed future facts. Accept only when every required check passes. A revise verdict names one supported target; reject/revise preserves prior output."""
REVISION_INSTRUCTION = """Produce one consequential P8C revision using the review target and supplied method contract. Keep every locked application field unchanged, including method/version, the fixed source-resolved cash issuance ratio 2037/318273, authorization, policy enums, declaration counts, and the dated 370.17 USD/share existing-claim price. Repurchase ratio is the supported exception: when the named target is repurchase, retain the source-calibrated 13319/241832 base or select the supported zero-program policy 0.0. Change only the named supported judgment, recalculate its effective consequences, preserve source/calculated/estimate labels, and set follow_up_request to null for propose_forecast. If the requested correction needs unavailable evidence or a locked field, return unresolved or capability_gap with all inactive forecast fields null and a concrete follow_up_request. Return only the strict schema."""
REREVIEW_INSTRUCTION = """Independently re-review the revised P8C candidate and fresh Mog consequences against the full method contract. Return only the strict reviewer schema. Confirm the revision is consequential, locked fields and fixed application arithmetic did not drift, the repurchase revision remains either 13319/241832 or supported zero-program 0.0, all source/calculated/estimate explanations remain accurate, and the bridges, actual Mog claim deduction/per-share denominator (Equity!B40 -> DCF!B26 -> DCF!B27, with DCF!B28 = 7429m and DCF!B29 = B27/B28), opening/end timing, funding and no-double-count checks pass. Confirm partial P8D/P8B/P9 limitations remain visible. Accept only a complete valid candidate; otherwise name a supported revision or reject."""


def _proposal_payload(packet: dict[str, Any], context: dict[str, Any], *, purpose: str, candidate: EquityProposal | None = None, review: EquityReview | None = None, authority: dict[str, Any] | None = None) -> dict[str, Any]:
    prompt_packet = copy.deepcopy(packet)
    prompt_packet.pop("upstream_model", None)
    prompt_packet["accepted_upstream"] = {**packet["accepted_upstream"], "dependency_only": True}
    payload = {"purpose": purpose, "packet": prompt_packet, "context": context, "required_periods": list(PERIODS), "contract": _method_contract(packet, context)}
    if candidate is not None:
        payload["candidate"] = candidate.model_dump(mode="json")
    if review is not None:
        payload["review"] = review.model_dump(mode="json")
    if authority is not None:
        payload["actual_mog"] = authority
    return payload


def _review_payload(packet: dict[str, Any], context: dict[str, Any], candidate: EquityProposal, *, purpose: str, authority: dict[str, Any], prior_review: EquityReview | None = None) -> dict[str, Any]:
    payload = _proposal_payload(packet, context, purpose=purpose, candidate=candidate, review=prior_review, authority=authority) | {
        "candidate_forecast": forecast_values(packet, candidate),
        "review_contract": {
            "accept_requires_all_checks": True,
            "revise_requires_one_supported_target_and_consequential_change": True,
            "reject_and_revision_failure_publish_nothing": True,
            "fixed_fields_are_not_revision_choices": True,
            "provenance_explanation_review_required": True,
            "candidate_explanation_is_not_source_evidence": True,
            "declared_nonforecast_means_no_forecast_publication": True,
        },
        "candidate_explanation_review": {
            "classification": "candidate_explanation",
            "rationale": candidate.rationale,
            "evidence_refs": list(candidate.evidence_refs),
            "is_source_statement": False,
            "required_labels": ["source", "calculated", "estimate"],
            "source_validity": "review_required",
            "correction_concern_if_mismatch": "A contradiction with the method contract is a correction concern, never a source statement.",
        },
    }
    return payload


def _safe_model_dump(value: Any) -> Any:
    if value is None or isinstance(value, (dict, list, str, int, float, bool)):
        return value
    try:
        return value.model_dump(mode="json")
    except (AttributeError, TypeError, ValueError):
        return {"repr": repr(value)}


def _usage_dict(response: Any) -> dict[str, Any] | None:
    value = _safe_model_dump(getattr(response, "usage", None))
    return value if isinstance(value, dict) and all(key in value for key in ("input_tokens", "output_tokens", "total_tokens")) else None


def _response_value(response: Any) -> Any:
    parsed = getattr(response, "output_parsed", None)
    if parsed is not None:
        return parsed
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text.strip():
        return output_text
    raw = response if isinstance(response, dict) else _safe_model_dump(response)
    if isinstance(raw, dict) and raw.get("output_parsed") is not None:
        return raw["output_parsed"]
    if isinstance(raw, dict) and isinstance(raw.get("output_text"), str):
        return raw["output_text"]
    return None


def _wire_value(value: Any, response_model: type[BaseModel]) -> BaseModel:
    if isinstance(value, response_model):
        return value
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise EquityError("provider response was not valid JSON") from exc
    if not isinstance(value, dict):
        raise EquityError("provider response contained no structured output")
    required = set(_strict_schema(response_model).get("required", []))
    if set(value) != required:
        raise EquityError(f"provider structured output keys violate strict schema; missing={sorted(required - set(value))}, extra={sorted(set(value) - required)}")
    try:
        return response_model.model_validate(value)
    except Exception as exc:
        raise EquityError(f"provider output failed semantic validation: {exc}") from exc


def _parse_structured_response(response: Any, response_model: type[BaseModel]) -> BaseModel:
    return _wire_value(_response_value(response), response_model)


def _ledger_state(budget_path: Path) -> tuple[int, float]:
    state = json.loads(budget_path.read_text(encoding="utf-8"))
    calls = [item for item in state.get("calls", []) if item.get("task_id") == TASK_ID]
    return len(calls), float(sum(item.get("cost", {}).get("priced_eur", item.get("reserved_eur", 0.0)) for item in calls))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _prior_stage_result(attempts: Path, stage: str, request_hash: str, response_model: type[BaseModel], budget_path: Path) -> tuple[BaseModel, dict[str, Any]] | None:
    state = json.loads(budget_path.read_text(encoding="utf-8"))
    matches = [item for item in state.get("calls", []) if item.get("task_id") == TASK_ID and item.get("request_hash") == request_hash]
    if any(item.get("status") in {"reserved", "usage_unknown"} for item in matches):
        raise EquityError(f"{stage} exact request has a held ledger admission")
    for path in sorted(attempts.glob(f"*-{stage}.request.json")):
        try:
            request = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if content_hash(request) != request_hash:
            continue
        prefix = path.name.removesuffix(".request.json")
        outcome_path = attempts / f"{prefix}.outcome.json"
        structured_path = attempts / f"{prefix}.structured.json"
        if not outcome_path.exists() or not structured_path.exists() or not matches:
            continue
        outcome = json.loads(outcome_path.read_text(encoding="utf-8"))
        if outcome.get("status") != "completed" or any(item.get("status") != "completed" for item in matches):
            continue
        return response_model.model_validate(json.loads(structured_path.read_text(encoding="utf-8"))), {"resumed": True, "resumed_call_ids": [item.get("call_id") for item in matches]}
    if matches:
        raise EquityError(f"{stage} exact request has no resumable artifact")
    return None


def _dispatch_structured(*, stage: str, run_dir: Path, budget_path: Path, instruction: str, payload: dict[str, Any], response_model: type[BaseModel], client: Any | None = None) -> tuple[BaseModel, dict[str, Any]]:
    request = _request(instruction, payload, response_model)
    request_hash = content_hash(request)
    attempts = run_dir / "attempts"
    attempts.mkdir(parents=True, exist_ok=True)
    prior = _prior_stage_result(attempts, stage, request_hash, response_model, budget_path)
    if prior is not None:
        return prior
    ordinal, committed = _ledger_state(budget_path)
    if ordinal >= MAX_ATTEMPTS:
        raise EquityError("P8C dispatched-attempt cap reached")
    prices = json.loads(budget_path.read_text(encoding="utf-8"))["prices"]
    estimate = reservation(request, prices, today=date.today())["reserved_eur"]
    if committed + estimate > MAX_COMMITTED_EUR:
        raise EquityError("P8C committed/reserved allowance would exceed EUR0.50")
    call_id = f"{TASK_ID}-{ordinal + 1:02d}-{stage}"
    prefix = f"{ordinal + 1:02d}-{stage}"
    _write_json(attempts / f"{prefix}.request.json", request)
    _write_json(attempts / f"{prefix}.reservation.json", reserve_call(budget_path, call_id=call_id, task_id=TASK_ID, request=request, endpoint_host="api.openai.com", today=date.today()))
    if client is None:
        load_dotenv()
        from openai import OpenAI
        client = OpenAI(max_retries=0)
    started = time.perf_counter()
    response = None
    error = None
    try:
        response = client.responses.create(**request)
    except Exception as exc:
        error = exc
    elapsed = time.perf_counter() - started
    raw = _safe_model_dump(response) if response is not None else {"response": None}
    if error is not None:
        raw = {"error_type": type(error).__name__, "error": str(error), "response": raw}
    _write_json(attempts / f"{prefix}.response.json", raw)
    outcome_error = None
    try:
        outcome = record_outcome(budget_path, call_id=call_id, usage=_usage_dict(response), elapsed_seconds=elapsed, response_id=getattr(response, "id", None), returned_model=getattr(response, "model", None))
    except Exception as exc:
        outcome_error = exc
        _write_json(attempts / f"{prefix}.outcome-error.json", {"error_type": type(exc).__name__, "error": str(exc)})
        outcome = record_outcome(budget_path, call_id=call_id, usage=None, elapsed_seconds=elapsed, response_id=getattr(response, "id", None), returned_model=getattr(response, "model", None))
    _write_json(attempts / f"{prefix}.outcome.json", outcome)
    _write_json(attempts / f"{prefix}.metadata.json", {"call_id": call_id, "stage": stage, "request_hash": request_hash, "status": outcome["status"], "model": MODEL, "reasoning": {"effort": REASONING_EFFORT}, "service_tier": "default"})
    if error is not None:
        raise EquityError(f"{stage} provider call failed after admission: {error}") from error
    if outcome_error is not None or outcome.get("status") != "completed":
        raise EquityError(f"{stage} usage is unknown after admission; exact-hash replay is held")
    try:
        parsed = _parse_structured_response(response, response_model)
    except Exception as exc:
        _write_json(attempts / f"{prefix}.parse-error.json", {"error_type": type(exc).__name__, "error": str(exc)})
        raise EquityError(f"{stage} returned invalid structured output after persistence: {exc}") from exc
    _write_json(attempts / f"{prefix}.structured.json", parsed.model_dump(mode="json"))
    return parsed, {"call_id": call_id, "stage": stage, "request_hash": request_hash, "status": outcome["status"]}


def _revision_is_consequential(original: EquityProposal, revised: EquityProposal, target: str) -> None:
    fields = {"sbc": ("sbc_ratio",), "pricing": ("settlement_price",), "withholding": ("withholding_rate",), "repurchase": ("repurchase_ratio",), "dividend": ("dividend_per_share_quarter",)}.get(target)
    if not fields:
        raise EquityError(f"unsupported revision target: {target}")
    before, after = original.model_dump(mode="json"), revised.model_dump(mode="json")
    if not any(before[field] != after[field] for field in fields):
        raise EquityError("revision must change a consequential supported assumption")


def _terminal_outcome(run_dir: Path, packet: dict[str, Any], context: dict[str, Any], *, status: str, reason: str, metadata: dict[str, Any], candidate: EquityProposal | None = None) -> dict[str, Any]:
    prior = run_dir / "model.json"
    result = {"decision_id": "P8C-MSFT-EQUITY-HELD-R5", "status": status, "human_approval": False, "selected_candidate": None, "candidate_hash": content_hash(candidate.model_dump(mode="json")) if candidate else None, "context_hash": content_hash(context), "source_packet_hash": content_hash(packet), "reason": reason, "previous_effective_model_sha256": _sha256(prior) if prior.exists() else None, "metadata": metadata}
    _write_json(run_dir / "decision-held.json", result)
    terminal = {"status": status, "reason": reason, "decision": result}
    if candidate is not None:
        terminal["candidate"] = candidate.model_dump(mode="json")
    _write_json(run_dir / "terminal-outcome.json", terminal)
    return result


def _compose_model_input(p8b: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(p8b)
    result["equity_packet"] = model["packet"]
    result["equity_forecast"] = model
    result["equity_decision"] = model["decision"]
    result["p8c_decision"] = model["decision"]
    result["schema_version"] = "p8c-msft-equity-input-r5"
    return result


def _actual_mog_candidate(p8b: dict[str, Any], packet: dict[str, Any], proposal: EquityProposal, context: dict[str, Any], run_dir: Path, stage: str) -> dict[str, Any]:
    review = review_proposal(proposal, packet)
    model = build_equity_model(p8b, packet, proposal, review, context=context, decision_status="REVIEW_REQUIRED")
    authority_dir = run_dir / "mog-authority" / stage
    authority_dir.mkdir(parents=True, exist_ok=True)
    input_path = authority_dir / "model-input.json"
    _write_json(input_path, _compose_model_input(p8b, model))
    script = Path(__file__).resolve().parents[2] / "scripts/spreadsheet_compat/run-p8c.mjs"
    if not script.exists():
        raise EquityError(f"local Mog authority script is missing: {script}")
    completed = subprocess.run(["node", str(script), "authority", str(input_path), str(authority_dir)], capture_output=True, text=True, check=False)
    (authority_dir / "mog.stdout.log").write_text(completed.stdout, encoding="utf-8")
    (authority_dir / "mog.stderr.log").write_text(completed.stderr, encoding="utf-8")
    verification_path = authority_dir / "equity-verification.json"
    if completed.returncode != 0 or not verification_path.exists():
        raise EquityError(f"Mog authority failed for {stage}; see {authority_dir}")
    verification = json.loads(verification_path.read_text(encoding="utf-8"))
    if verification.get("status") != "PASS" or not isinstance(verification.get("snapshot"), dict):
        raise EquityError(f"Mog authority did not pass for {stage}")
    return {"status": "PASS", "engine": "Mog SDK", "stage": stage, "verification_path": verification_path.as_posix(), "candidate_hash": content_hash(proposal.model_dump(mode="json")), "snapshot": verification.get("snapshot", {})}


def _write_final_model(run_dir: Path, p8b: dict[str, Any], packet: dict[str, Any], proposal: EquityProposal, review: EquityReview, context: dict[str, Any], authority: dict[str, Any]) -> dict[str, Any]:
    model = build_equity_model(p8b, packet, proposal, review, context=context, decision_status="SYSTEM_REVIEWED_PROVISIONAL")
    model["authoritative_mog"] = authority
    model["decision"]["authoritative_mog_attached"] = True
    _write_json(run_dir / "candidate.json", proposal.model_dump(mode="json"))
    _write_json(run_dir / "review.json", review.model_dump(mode="json"))
    _write_json(run_dir / "model.json", model)
    return model


def run_reasoning(p8b: dict[str, Any], run_dir: Path, budget_path: Path, *, source_table: Path | None = None, offline: bool = False, client: Any | None = None, mog_builder: Any | None = None) -> dict[str, Any]:
    run_dir.mkdir(parents=True, exist_ok=True)
    packet = build_evidence_packet(p8b, source_table)
    packet["upstream_model"] = p8b
    context = _run_context(p8b, packet)
    context_path = run_dir / "run-context.json"
    if context_path.exists() and json.loads(context_path.read_text(encoding="utf-8")) != context:
        raise EquityError("P8C run context changed; prior outputs cannot be reused")
    _write_json(context_path, context)
    _write_json(run_dir / "evidence-packet.json", packet)
    if offline:
        model = run_offline(p8b, run_dir, source_table=source_table)
        model["decision"]["offline_fixture"] = True
        _write_json(run_dir / "model.json", model)
        return model
    if not budget_path.exists():
        raise EquityError(f"P8C budget ledger is missing: {budget_path}")
    meta: dict[str, Any] = {"context": context, "offline": False, "task_id": TASK_ID}
    current: EquityProposal | None = None
    try:
        proposal, analyst_meta = _dispatch_structured(stage="analyst-initial", run_dir=run_dir, budget_path=budget_path, instruction=ANALYST_INSTRUCTION, payload=_proposal_payload(packet, context, purpose="initial analyst selection"), response_model=EquityProposal, client=client)
        current = proposal
        _write_json(run_dir / "candidate-initial.json", proposal.model_dump(mode="json"))
        meta["analyst"] = analyst_meta
        if proposal.outcome != "propose_forecast":
            status = "CAPABILITY_GAP" if proposal.outcome == "capability_gap" else "UNRESOLVED"
            _terminal_outcome(run_dir, packet, context, status=status, reason=proposal.follow_up_request or proposal.rationale, metadata=meta, candidate=proposal)
            raise EquityError(f"P8C analyst terminated with {status}")
        validate_proposal(proposal, packet)
        builder = mog_builder or _actual_mog_candidate
        original_authority = builder(p8b, packet, proposal, context, run_dir, "analyst-initial")
        review, review_meta = _dispatch_structured(stage="reviewer-original", run_dir=run_dir, budget_path=budget_path, instruction=REVIEW_INSTRUCTION, payload=_review_payload(packet, context, proposal, purpose="independent original review", authority=original_authority), response_model=EquityReview, client=client)
        _review_contract(review)
        _write_json(run_dir / "review-original.json", review.model_dump(mode="json"))
        meta["reviewer_original"] = review_meta
        if review.verdict == "accept":
            if not _review_eligible(review):
                _terminal_outcome(run_dir, packet, context, status="REVIEW_REQUIRED", reason="review accept did not satisfy eligibility", metadata=meta, candidate=proposal)
                raise EquityError("P8C review accept did not satisfy eligibility")
            return _write_final_model(run_dir, p8b, packet, proposal, review, context, original_authority)
        if review.verdict == "reject":
            _terminal_outcome(run_dir, packet, context, status="REJECTED_BY_REVIEW", reason="; ".join(review.concerns), metadata=meta, candidate=proposal)
            raise EquityError("P8C candidate rejected; prior effective model preserved")
        _write_json(run_dir / "revision-request.json", {"target": review.target, "required_revision": review.required_revision, "prior_candidate_hash": content_hash(proposal.model_dump(mode="json")), "context_hash": content_hash(context)})
        revision, revision_meta = _dispatch_structured(stage="analyst-revision", run_dir=run_dir, budget_path=budget_path, instruction=REVISION_INSTRUCTION, payload=_proposal_payload(packet, context, purpose="required consequential analyst revision", candidate=proposal, review=review, authority=original_authority), response_model=EquityProposal, client=client)
        current = revision
        _write_json(run_dir / "candidate-revision.json", revision.model_dump(mode="json"))
        if revision.outcome != "propose_forecast":
            status = "CAPABILITY_GAP" if revision.outcome == "capability_gap" else "UNRESOLVED"
            revision_outcome = {"stage": "analyst-revision", "outcome": revision.outcome, "candidate": revision.model_dump(mode="json"), "candidate_hash": content_hash(revision.model_dump(mode="json")), "reason": revision.rationale, "follow_up_request": revision.follow_up_request, "requested_target": review.target, "prior_candidate_hash": content_hash(proposal.model_dump(mode="json"))}
            meta.update({"analyst_revision": revision_meta, "revision_outcome": revision_outcome, "revision": {"target": review.target, "original_candidate_hash": content_hash(proposal.model_dump(mode="json")), "revised_candidate_hash": revision_outcome["candidate_hash"]}})
            _write_json(run_dir / "revision-outcome.json", revision_outcome)
            _terminal_outcome(run_dir, packet, context, status=status, reason=revision.follow_up_request or revision.rationale, metadata=meta, candidate=revision)
            raise EquityError(f"P8C revision terminated with {status}")
        _revision_is_consequential(proposal, revision, review.target)
        validate_proposal(revision, packet)
        revised_authority = builder(p8b, packet, revision, context, run_dir, "analyst-revision")
        rereview, rereview_meta = _dispatch_structured(stage="reviewer-revision", run_dir=run_dir, budget_path=budget_path, instruction=REREVIEW_INSTRUCTION, payload=_review_payload(packet, context, revision, purpose="independent revision re-review", authority=revised_authority, prior_review=review), response_model=EquityReview, client=client)
        _review_contract(rereview)
        _write_json(run_dir / "review-revision.json", rereview.model_dump(mode="json"))
        meta.update({"analyst_revision": revision_meta, "reviewer_revision": rereview_meta})
        if rereview.verdict != "accept" or not _review_eligible(rereview):
            status = "REJECTED_BY_REVIEW" if rereview.verdict == "reject" else "REVISION_REQUIRED"
            _terminal_outcome(run_dir, packet, context, status=status, reason="; ".join(rereview.concerns), metadata=meta, candidate=revision)
            raise EquityError("P8C revised candidate was not accepted")
        return _write_final_model(run_dir, p8b, packet, revision, rereview, context, revised_authority)
    except EquityError as exc:
        if not (run_dir / "terminal-outcome.json").exists():
            marker = str(exc).lower()
            status = "BUDGET_HELD" if any(item in marker for item in ("budget", "allowance", "usage", "held")) else "FAILED"
            _terminal_outcome(run_dir, packet, context, status=status, reason=str(exc), metadata=meta, candidate=current)
        raise
    except Exception as exc:
        marker = str(exc).lower()
        status = "BUDGET_HELD" if any(item in marker for item in ("budget", "allowance", "reservation", "usage")) else "FAILED"
        _terminal_outcome(run_dir, packet, context, status=status, reason=str(exc), metadata=meta, candidate=current)
        raise EquityError(f"P8C workflow failed; prior effective model preserved: {exc}") from exc


def run_live(p8b: dict[str, Any], run_dir: Path, budget_path: Path, *, source_table: Path | None = None, client: Any | None = None, mog_builder: Any | None = None) -> dict[str, Any]:
    return run_reasoning(p8b, run_dir, budget_path, source_table=source_table, client=client, mog_builder=mog_builder)


def prepare_live_handoff(p8b: dict[str, Any], run_dir: Path, *, source_table: Path | None = None, output_path: Path | None = None, budget_path: Path | None = None) -> dict[str, Any]:
    packet = build_evidence_packet(p8b, source_table)
    packet["upstream_model"] = p8b
    context = _run_context(p8b, packet)
    request = _request(ANALYST_INSTRUCTION, _proposal_payload(packet, context, purpose="initial analyst selection"), EquityProposal)
    rebuilt = _request(ANALYST_INSTRUCTION, _proposal_payload(packet, context, purpose="initial analyst selection"), EquityProposal)
    run_dir.mkdir(parents=True, exist_ok=True)
    request_path = run_dir / "attempts/01-analyst-initial.request.json"
    _write_json(run_dir / "run-context.json", context)
    _write_json(run_dir / "evidence-packet.json", packet)
    _write_json(request_path, request)
    _write_json(run_dir / "schema-proof.json", {"proposal": {"schema_hash": content_hash(request["text"]["format"]["schema"]), "strict": True, "all_properties_required": True}, "review": {"schema_hash": content_hash(_strict_schema(EquityReview)), "strict": True, "all_properties_required": True}})
    prepared_output = output_path or run_dir / "model-input.json"
    budget = budget_path or Path("data/build-guide-api-budget.json")
    cli = f"PYTHONPATH=src .venv\\Scripts\\python.exe -m smrik_fund.equity --p8b-model data/build-guide-p8b/live-r5/model-input.json --output {prepared_output.as_posix()} --run-dir {run_dir.as_posix()} --budget {budget.as_posix()}"
    manifest = {"status": "PREPARED_NO_DISPATCH", "stage": "analyst-initial", "case": CASE, "request_path": request_path.as_posix(), "request_hash": content_hash(request), "request_rebuilt_hash": content_hash(rebuilt), "canonical_request_equal": request == rebuilt, "source_packet_hash": content_hash(packet), "context_hash": content_hash(context), "implementation_files": context["implementation_files"], "implementation_aggregate_sha256": context["implementation_aggregate_sha256"], "settings": {"model": MODEL, "reasoning": {"effort": REASONING_EFFORT}, "endpoint": ENDPOINT_URL, "service_tier": "default", "max_output_tokens": MAX_OUTPUT_TOKENS, "tools": [], "background": False, "max_retries": 0}, "caps": {"max_attempts": MAX_ATTEMPTS, "max_committed_eur": MAX_COMMITTED_EUR, "final_review_reserve_eur": 0.50}, "cli": cli, "replay_policy": "only exact completed requests in same context may resume", "output_path": prepared_output.as_posix()}
    _write_json(run_dir / "prepared-manifest.json", manifest)
    return manifest


def run_offline(p8b: dict[str, Any], run_dir: Path, *, source_table: Path | None = None) -> dict[str, Any]:
    packet = build_evidence_packet(p8b, source_table)
    packet["upstream_model"] = p8b
    proposal = default_proposal(packet)
    review = review_proposal(proposal, packet)
    model = build_equity_model(p8b, packet, proposal, review, decision_status="OFFLINE_FIXTURE")
    model["decision"]["offline_fixture"] = True
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_json(run_dir / "candidate.json", proposal.model_dump(mode="json"))
    _write_json(run_dir / "review.json", review.model_dump(mode="json"))
    _write_json(run_dir / "model.json", model)
    return model


def _run_cli(args: argparse.Namespace) -> None:
    p8b = json.loads(Path(args.p8b_model).read_text(encoding="utf-8"))
    run_dir, output = Path(args.run_dir), Path(args.output)
    model = run_offline(p8b, run_dir, source_table=Path(args.source_table) if args.source_table else None) if args.offline else run_reasoning(p8b, run_dir, Path(args.budget), source_table=Path(args.source_table) if args.source_table else None)
    _write_json(output, _compose_model_input(p8b, model))
    print(json.dumps({"status": model["decision"]["status"], "output": str(output), "run_dir": str(run_dir)}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--p8b-model", default="data/build-guide-p8b/live-r5/model-input.json")
    parser.add_argument("--output", default="data/build-guide-p8c/offline-r5/model-input.json")
    parser.add_argument("--run-dir", default="data/build-guide-p8c/offline-r5")
    parser.add_argument("--source-table", default=None)
    parser.add_argument("--budget", default="data/build-guide-api-budget.json")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    if args.prepare:
        print(json.dumps(prepare_live_handoff(json.loads(Path(args.p8b_model).read_text(encoding="utf-8")), Path(args.run_dir), source_table=Path(args.source_table) if args.source_table else None, output_path=Path(args.output), budget_path=Path(args.budget)), indent=2))
    else:
        _run_cli(args)


if __name__ == "__main__":
    main()
