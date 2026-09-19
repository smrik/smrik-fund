"""P7 balance based working capital and cash conversion boundary.

The module owns source classification, the bounded analyst/reviewer contract,
and diagnostic previews.  Forecast balances are compiled as Mog formulas by
``scripts/spreadsheet_compat/asset_model.mjs``; Python never publishes a
precomputed balance array as the workbook authority.
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import math
import re
import subprocess
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from smrik_fund.analysis_budget import content_hash
from smrik_fund.operating_forecast import (
    BINDING_HASH_FIELDS,
    _dispatch_structured,
)

CASE = "MSFT"
INFORMATION_CUTOFF = "2026-04-30"
MEASUREMENT_DATE = "2026-03-31"
MODEL = "gpt-5.6-luna"
ENDPOINT_HOST = "api.openai.com"
BASE_URL = f"https://{ENDPOINT_HOST}/v1"
TASK_ID = "p7-msft-working-capital"
MAX_ATTEMPTS = 10
MAX_COMMITTED_EUR = 0.50
PERIODS = ("FY2026_STUB", "FY2027", "FY2028", "FY2029", "FY2030", "FY2031", "FY2032", "FY2033", "FY2034", "FY2035", "FY2036")
SCHEMA_VERSION = "p7-working-capital-proposal-v3"
PROMPT_VERSION = "p7-working-capital-reasoning-r4"
METHOD_CATALOG_VERSION = "p7-working-capital-methods-v2"
REASONING_EFFORT = "medium"
MAX_OUTPUT_TOKENS = 12_000
ACCRUED_COMPENSATION_MULTIPLIER_MIN = 0.8
ACCRUED_COMPENSATION_MULTIPLIER_MAX = 1.2

INITIAL_ANALYST_INSTRUCTION = (
    "Select one bounded P7 working-capital policy from the frozen packet. Preserve source facts, signs, periods, "
    "unknowns and exclusions. The application derives the contract recognition share, current contract presentation "
    "share, fixed contract billings base and accrued-compensation source baseline from the packet; do not return or "
    "change those source-owned values. Choose only genuine judgment drivers. The accrued_compensation_multiplier is "
    "dimensionless, has base 1.0 and must stay within [0.8, 1.2]; it scales the application-derived source baseline "
    "and is not a revenue fraction. Keep days nonnegative, the server-receivable first-stub shock within [-0.2, 0.2] "
    "and the contract billings first-stub multiplier within [0.9, 1.1]. "
    "State policy concerns, alternatives and uncertainty in the structured proposal. Return only a complete proposal."
)
ORIGINAL_REVIEW_INSTRUCTION = (
    "Independently review this P7 policy against source identity, period days, proxy denominators, application-owned "
    "source-locked contract parameters, the accrued-compensation source-baseline / dimensionless-multiplier / effective-"
    "ratio units contract, exclusions, deferred-liability bridge and actual Mog-calculated cash effects. "
    "Do not assume the candidate is correct. Return accept, revise or reject, with one bounded target when revising. "
    "Return compact JSON within the schema; do not spend output tokens on analysis prose."
)
REVISION_ANALYST_INSTRUCTION = (
    "Make exactly one consequential bounded P7 revision in the review target, preserving source facts, application-owned "
    "contract parameters, accrued-compensation source baseline and all other methods. Keep the accrued_compensation_"
    "multiplier dimensionless within [0.8, 1.2], keep other judgment inputs within their declared bounds and return a "
    "complete proposal."
)
REVISION_REVIEW_INSTRUCTION = (
    "Re-check the consequential P7 revision using the actual Mog-calculated balances, CFO and cash effects. Confirm the "
    "application-owned source-locked contract parameters and accrued-compensation source baseline remain derived from "
    "the current packet, and that the multiplier is dimensionless rather than a revenue fraction. Return a terminal "
    "verdict in compact JSON within the schema; do not spend output tokens on analysis prose."
)


def _is_p7_call(call: dict[str, Any]) -> bool:
    """Recognize only P7 calls when replaying the shared API ledger."""
    return call.get("task_id") == TASK_ID or str(call.get("call_id", "")).startswith(f"{TASK_ID}:")


class WorkingCapitalError(ValueError):
    """P7 source, proposal, review, or dependency failure."""


class WorkingCapitalProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["propose_forecast", "unresolved", "capability_gap"]
    method_id: Literal["balance_based_days_plus_contract_bridge"] | None
    method_version: Literal["v1"] | None
    current_ar_dso: float = Field(ge=0)
    inventory_dio: float = Field(ge=0)
    operating_ap_dpo: float = Field(ge=0)
    accrued_compensation_multiplier: float = Field(ge=ACCRUED_COMPENSATION_MULTIPLIER_MIN, le=ACCRUED_COMPENSATION_MULTIPLIER_MAX)
    server_receivable_change_first_stub: float = Field(ge=-0.2, le=0.2)
    contract_billing_multiplier_first_stub: float = Field(ge=0.9, le=1.1)
    long_term_ar_policy: Literal["hold_flat"]
    residual_oca_policy: Literal["hold_flat"]
    residual_ocl_policy: Literal["hold_flat"]
    server_receivable_policy: Literal["hold_flat_with_first_stub_scenario"]
    evidence_refs: list[str] = Field(min_length=1)
    rationale: str = Field(min_length=1)
    alternatives: list[str]
    uncertainty: list[str]
    follow_up_request: str | None

    @model_validator(mode="before")
    @classmethod
    def _reject_non_numeric_inputs(cls, value: Any) -> Any:
        """Reject coercible non-numbers at the structured analyst boundary."""
        if isinstance(value, dict):
            fields = (
                "current_ar_dso",
                "inventory_dio",
                "operating_ap_dpo",
                "accrued_compensation_multiplier",
                "server_receivable_change_first_stub",
                "contract_billing_multiplier_first_stub",
            )
            for field in fields:
                if field not in value:
                    continue
                raw = value[field]
                if isinstance(raw, bool) or not isinstance(raw, int | float) or not math.isfinite(raw):
                    raise ValueError(f"{field} must be a numeric value")
        return value


class WorkingCapitalReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["accept", "revise", "reject"]
    evidence_strength: Literal["strong", "mixed", "weak"]
    method_valid: bool
    source_valid: bool
    period_valid: bool
    cash_sign_valid: bool
    exclusions_valid: bool
    no_double_count: bool
    concerns: list[str] = Field(min_length=1)
    required_revision: str | None
    target: Literal["none", "days_driver", "contract_billing", "server_receivable", "accrued_compensation", "presentation"]
    rationale: str = Field(min_length=1)

def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def _number(value: Any, name: str, *, allow_zero: bool = True) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise WorkingCapitalError(f"{name} is missing/non-numeric")
    if not allow_zero and value == 0:
        raise WorkingCapitalError(f"{name} must be nonzero")
    return float(value)


def _source_table() -> Path:
    return Path(__file__).resolve().parents[2] / "Lunacy" / "runs" / "three-statement-dcf" / "phases" / "working-capital" / "P7-source-table-R1.csv"


def _read_source_table(path: Path | None = None) -> list[dict[str, str]]:
    table = path or _source_table()
    with table.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _f(value: str | None) -> float | None:
    if value is None or value.strip() == "":
        return None
    return float(value)


def _p2_fact(packet: dict[str, Any], section: str, key: str) -> float:
    value = ((packet.get("facts") or {}).get(section) or {}).get(key)
    if not isinstance(value, dict):
        raise WorkingCapitalError(f"P6 packet missing {section}.{key}")
    return _number(value.get("value"), f"{section}.{key}")


def _p6_ttm_cost_of_revenue(p6: dict[str, Any], p6_packet: dict[str, Any]) -> float:
    """Read the accepted P6 COGS baseline without substituting a constant."""
    costs = p6_packet.get("costs") or {}
    cogs_fact = costs.get("cost_of_revenue", {}).get("TTM") if isinstance(costs.get("cost_of_revenue"), dict) else None
    if cogs_fact is not None:
        return _number(cogs_fact, "TTM cost of revenue")

    ttm_cogs = ((p6_packet.get("facts") or {}).get("ttm") or {}).get("cost_of_revenue")
    if isinstance(ttm_cogs, dict) and ttm_cogs.get("value") is not None:
        return _number(ttm_cogs["value"], "TTM cost of revenue")

    # The accepted P6 R4 packet carries the source fact in its operating
    # forecast evidence list.  Parse only that identified evidence excerpt;
    # missing or malformed evidence remains a hard failure.
    evidence = (p6.get("operating_forecast") or {}).get("evidence") or []
    for item in evidence:
        if not isinstance(item, dict) or item.get("evidence_id") != "C-cost_of_revenue-TTM":
            continue
        match = re.search(r"Cost of Goods and Services Sold:\s*([0-9,]+(?:\.[0-9]+)?)", str(item.get("excerpt", "")))
        if match:
            return _number(float(match.group(1).replace(",", "")), "TTM cost of revenue")
    raise WorkingCapitalError("TTM cost of revenue is missing/non-numeric")


def _q3_dividend_payable() -> tuple[float, str]:
    """Read the Q3 Note 14 dividend stock that is embedded in OCL."""
    source = Path(__file__).resolve().parents[2] / "data" / "MSFT" / "01_source" / "edgar" / "filings" / "0001193125-26-191507.txt"
    if not source.exists():
        raise WorkingCapitalError("Q3 Note 14 source for dividend payable is missing")
    text = source.read_text(encoding="utf-8")
    match = re.search(r"March 10, 2026\s+May 21, 2026\s+June 11, 2026\s+0\.91\s+([0-9,]+)", text)
    if not match or "dividend declared on March 10, 2026 was included" not in text:
        raise WorkingCapitalError("Q3 Note 14 dividend payable evidence is missing/non-numeric")
    value = _number(float(match.group(1).replace(",", "")), "dividend payable")
    return value, f"Q3 Note 14; {source.as_posix()} lines 898-916"


def _p6_accepted(p6: dict[str, Any]) -> None:
    decision = p6.get("p6_decision") or p6.get("operating_decision") or {}
    if decision.get("status") != "SYSTEM_REVIEWED_PROVISIONAL":
        raise WorkingCapitalError("P6 input is not accepted system-reviewed provisional")
    review = decision.get("review") or {}
    if review and review.get("verdict") not in {"accept", None}:
        raise WorkingCapitalError("P6 input review is not accepted")
    binding = decision.get("binding")
    if isinstance(binding, dict) and binding.get("source_case_snapshot_sha256") and binding["source_case_snapshot_sha256"] != (p6.get("packet") or {}).get("frozen_case_snapshot_sha256"):
        raise WorkingCapitalError("P6 source-case binding is stale")


def build_evidence_packet(p6: dict[str, Any], source_table: Path | None = None) -> dict[str, Any]:
    """Build a P7 packet from the exact accepted P6 packet and frozen table."""
    _p6_accepted(p6)
    table_path = source_table or _source_table()
    rows = _read_source_table(table_path)
    p6_packet = copy.deepcopy(p6.get("packet") or {})
    ttm = (p6_packet.get("facts") or {}).get("ttm") or {}
    ttm_cogs = _p6_ttm_cost_of_revenue(p6, p6_packet)
    balances: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = row["line_item"]
        balances[item] = {
            "scope": row.get("scope"),
            "FY2024": _f(row.get("fy2024_06_30_usd_mm")),
            "FY2025": _f(row.get("fy2025_06_30_usd_mm")),
            "Q3FY2026": _f(row.get("q3fy2026_03_31_usd_mm")),
            "cfs_fy2025": _f(row.get("cfs_fy2025_usd_mm")),
            "cfs_q3fy2026_9m": _f(row.get("cfs_q3fy2026_9m_usd_mm")),
            "source_identity": row.get("source_identity"),
            "policy_note": row.get("policy_note"),
        }
    required = {
        "current_accounts_receivable", "inventory", "other_current_assets_reported",
        "server_component_receivables", "accounts_payable_reported", "ppe_payable_subset",
        "operating_ap_calculated", "accrued_compensation", "contract_liability_current",
        "contract_liability_noncurrent", "contract_liability_total_calculated",
        "other_current_liabilities", "operating_lease_liability_current",
        "finance_lease_liability_current", "current_income_taxes",
    }
    missing = sorted(required - balances.keys())
    if missing:
        raise WorkingCapitalError(f"P7 source table missing rows: {', '.join(missing)}")
    dividend_payable, dividend_source = _q3_dividend_payable()
    balances["dividend_payable_financing"] = {
        "scope": "current financing liability",
        "FY2024": None,
        "FY2025": None,
        "Q3FY2026": dividend_payable,
        "cfs_fy2025": None,
        "cfs_q3fy2026_9m": None,
        "source_identity": dividend_source,
        "policy_note": "Included in reported OCL; exclude from operating NWC; hold flat in P7; P8C owns payment/declaration roll-forward.",
    }
    reported_ocl = _number(balances["other_current_liabilities"]["Q3FY2026"], "reported OCL")
    operating_lease = _number(balances["operating_lease_liability_current"]["Q3FY2026"], "operating lease liability")
    finance_lease = _number(balances["finance_lease_liability_current"]["Q3FY2026"], "finance lease liability")
    unclassified_ocl = reported_ocl - operating_lease - finance_lease - dividend_payable
    if unclassified_ocl < 0:
        raise WorkingCapitalError("unclassified OCL residual is negative")
    bridge = {
        "opening_nine_month": 67265.0,
        "reported_deferrals": 143442.0,
        "recognized_revenue": 157030.0,
        "comparable_nine_month_revenue": 241832.0,
        "closing_nine_month": 53677.0,
        "identity_difference": 67265.0 + 143442.0 - 157030.0 - 53677.0,
        "reported_deferrals_label": "Deferrals",
        "cash_receipts": False,
        "source_identity": "0001193125-26-191507 Note 11; original_source character 1649844",
    }
    historical_bridge = {}
    cash_effect_direction = {
        "current_accounts_receivable": -1, "inventory": -1,
        "other_current_assets_reported": -1, "accounts_payable_reported": 1,
        "contract_liability_total_calculated": 1, "other_current_liabilities": 1,
    }
    for item, data in balances.items():
        if data["FY2025"] is not None and data["Q3FY2026"] is not None and data["cfs_q3fy2026_9m"] is not None:
            delta = data["Q3FY2026"] - data["FY2025"]
            cfs = data["cfs_q3fy2026_9m"]
            direction = cash_effect_direction.get(item)
            implied_cash = None if direction is None else direction * delta
            historical_bridge[item] = {
                "balance_change_fy25_to_q3": delta,
                "reported_cfs_contribution_9m": cfs,
                "stock_implied_cash_effect_9m": implied_cash,
                "unexplained_difference": None if implied_cash is None else cfs - implied_cash,
                "comparison_basis": "reported cash effect minus stock-implied cash effect; asset increase consumes cash, liability increase provides cash; noncash/acquisition/FX effects remain unallocated" if direction is not None else "unresolved account cash-effect direction",
                "source_identity": data["source_identity"],
            }
    p7 = {
        "schema_version": "p7-msft-evidence-v1",
        "case": CASE,
        "information_cutoff": INFORMATION_CUTOFF,
        "measurement_date": MEASUREMENT_DATE,
        "source_table": str(table_path).replace("\\", "/"),
        "source_table_sha256": _sha256(table_path),
        "balances": balances,
        "contract_bridge": bridge,
        "ocl_bridge": {
            "reported_other_current_liabilities": reported_ocl,
            "operating_lease_liability": operating_lease,
            "finance_lease_liability": finance_lease,
            "dividend_payable_financing": dividend_payable,
            "unclassified_operating_residual": unclassified_ocl,
            "source_identity": dividend_source,
            "financing_exclusion": "Dividend payable remains in reported OCL and balance-sheet liabilities, but is excluded from operating NWC and held flat during P7.",
        },
        "historical_bridge": historical_bridge,
        "ttm_revenue": _number((ttm.get("revenue") or {}).get("value"), "TTM revenue"),
        "ttm_cost_of_revenue": ttm_cogs,
        "p6_dependency": {
            "decision_id": (p6.get("p6_decision") or {}).get("decision_id"),
            "decision_status": (p6.get("p6_decision") or {}).get("status"),
            "source_case_snapshot_sha256": p6_packet.get("frozen_case_snapshot_sha256"),
            "p6_input_hash": content_hash(p6),
        },
        "unavailable": [
            "Contract assets and aggregate cash billings are not separately disclosed; missing is not zero.",
            "Credit purchases, forward supplier terms, and seasonality for working-capital balances are unavailable.",
            "Historical balance/CFS differences retain unresolved acquisition, FX, write-off and reclassification causes.",
        ],
    }
    return p7


def default_proposal(packet: dict[str, Any]) -> WorkingCapitalProposal:
    b = packet["balances"]
    revenue = _number(packet["ttm_revenue"], "TTM revenue", allow_zero=False)
    cogs = _number(packet["ttm_cost_of_revenue"], "TTM cost of revenue", allow_zero=False)
    ar = _number(b["current_accounts_receivable"]["Q3FY2026"], "current AR")
    inventory = _number(b["inventory"]["Q3FY2026"], "inventory")
    ap = _number(b["operating_ap_calculated"]["Q3FY2026"], "operating AP")
    proposal = WorkingCapitalProposal(
        outcome="propose_forecast",
        method_id="balance_based_days_plus_contract_bridge",
        method_version="v1",
        current_ar_dso=ar / revenue * 365,
        inventory_dio=inventory / cogs * 365,
        operating_ap_dpo=ap / cogs * 365,
        accrued_compensation_multiplier=1.0,
        server_receivable_change_first_stub=0.0,
        contract_billing_multiplier_first_stub=1.0,
        long_term_ar_policy="hold_flat",
        residual_oca_policy="hold_flat",
        residual_ocl_policy="hold_flat",
        server_receivable_policy="hold_flat_with_first_stub_scenario",
        evidence_refs=["current_accounts_receivable", "inventory", "operating_ap_calculated", "contract_bridge"],
        rationale="Use balance based DSO/DIO/DPO proxies, a source-baseline accrued compensation proxy with a bounded dimensionless multiplier, a separately visible server receivable scenario, and an aggregate contract liability bridge. Unknown residuals remain flat and visible.",
        alternatives=[
            "Current-only contract liabilities would omit the selected noncurrent contract balance from cash conversion.",
            "A cash-billings schedule is unavailable; modeled billings create the scoped contract liability and are not cash receipts.",
        ],
        uncertainty=[
            "DSO, DIO and DPO use revenue or cost of revenue proxies rather than disclosed collection or credit-purchase terms.",
            "The accrued compensation baseline is source-derived; its bounded dimensionless multiplier and deferred recognition/billings assumptions are explicit estimates; seasonality is unavailable.",
            "Unknown OCA/OCL composition and contract assets remain unresolved; P8D must address material residuals.",
        ],
        follow_up_request=None,
    )
    validate_proposal(proposal, packet)
    return proposal


def validate_proposal(proposal: WorkingCapitalProposal, packet: dict[str, Any]) -> None:
    if proposal.outcome != "propose_forecast" or proposal.method_id != "balance_based_days_plus_contract_bridge" or proposal.method_version != "v1":
        raise WorkingCapitalError("P7 proposal method is unsupported")
    for name in ("current_ar_dso", "inventory_dio", "operating_ap_dpo"):
        if _number(getattr(proposal, name), name) < 0:
            raise WorkingCapitalError(f"{name} cannot be negative")
    multiplier = _number(proposal.accrued_compensation_multiplier, "accrued_compensation_multiplier")
    if not ACCRUED_COMPENSATION_MULTIPLIER_MIN <= multiplier <= ACCRUED_COMPENSATION_MULTIPLIER_MAX:
        raise WorkingCapitalError("accrued_compensation_multiplier must be within [0.8, 1.2]")
    if not -0.2 <= proposal.server_receivable_change_first_stub <= 0.2:
        raise WorkingCapitalError("server receivable first-stub scenario must be within +/-20%")
    if not 0.9 <= proposal.contract_billing_multiplier_first_stub <= 1.1:
        raise WorkingCapitalError("contract billings shock must be within 0.9/1.1")
    locked = _source_locked_parameters(packet)
    if not 0 < locked["contract_recognition_share"] <= 1:
        raise WorkingCapitalError("application-derived contract recognition share must be within (0,1]")
    if not 0 < locked["current_contract_presentation_share"] <= 1:
        raise WorkingCapitalError("application-derived contract presentation share must be within (0,1]")
    _number(packet["ttm_revenue"], "TTM revenue", allow_zero=False)
    _number(packet["ttm_cost_of_revenue"], "TTM cost of revenue", allow_zero=False)


def _period_meta() -> list[dict[str, Any]]:
    # FY2026 stub is future to the 2026-03-31 measurement date; later periods
    # use their actual Microsoft fiscal calendar spans.
    values = [("2026-04-01", "2026-06-30"), ("2026-07-01", "2027-06-30"), ("2027-07-01", "2028-06-30"), ("2028-07-01", "2029-06-30"), ("2029-07-01", "2030-06-30"), ("2030-07-01", "2031-06-30"), ("2031-07-01", "2032-06-30"), ("2032-07-01", "2033-06-30"), ("2033-07-01", "2034-06-30"), ("2034-07-01", "2035-06-30"), ("2035-07-01", "2036-06-30")]
    result = []
    for period, (start, end) in zip(PERIODS, values, strict=True):
        days = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
        result.append({"id": period, "start": start, "end": end, "days": days})
    return result


def _opening(packet: dict[str, Any], key: str) -> float:
    return _number(packet["balances"][key]["Q3FY2026"], key)


def _accrued_compensation_driver(packet: dict[str, Any], multiplier: float) -> dict[str, Any]:
    """Derive the source baseline and explicit dimensionless multiplier."""
    source_ttm_revenue = _number(packet.get("ttm_revenue"), "TTM revenue", allow_zero=False)
    opening_balance = _opening(packet, "accrued_compensation")
    source_baseline = opening_balance / source_ttm_revenue
    selected_multiplier = _number(multiplier, "accrued_compensation_multiplier")
    if not ACCRUED_COMPENSATION_MULTIPLIER_MIN <= selected_multiplier <= ACCRUED_COMPENSATION_MULTIPLIER_MAX:
        raise WorkingCapitalError("accrued_compensation_multiplier must be within [0.8, 1.2]")
    return {
        "source_baseline": source_baseline,
        "source_baseline_units": "ratio of USD millions accrued compensation to USD millions TTM revenue",
        "multiplier": selected_multiplier,
        "multiplier_units": "dimensionless",
        "effective_ratio": source_baseline * selected_multiplier,
        "effective_ratio_units": "ratio of USD millions accrued compensation to USD millions revenue",
        "formula": "period revenue / actual period days * 365 * source baseline * multiplier",
    }


def _source_locked_parameters(packet: dict[str, Any]) -> dict[str, Any]:
    """Derive contract parameters from the packet outside the analyst schema."""
    bridge = packet.get("contract_bridge") or {}
    balances = packet.get("balances") or {}
    recognized = _number(bridge.get("recognized_revenue"), "contract recognized revenue", allow_zero=False)
    comparable = _number(bridge.get("comparable_nine_month_revenue"), "comparable nine-month revenue", allow_zero=False)
    current = _number(
        (balances.get("contract_liability_current") or {}).get("Q3FY2026"),
        "current contract liability",
    )
    total = _number(
        (balances.get("contract_liability_total_calculated") or {}).get("Q3FY2026"),
        "contract liability total",
    )
    if total <= 0:
        raise WorkingCapitalError("contract liability total must be positive")
    accrued = _accrued_compensation_driver(packet, 1.0)
    return {
        "contract_billings_to_recognition": 1.0,
        "contract_recognition_share": recognized / comparable,
        "current_contract_presentation_share": current / total,
        "accrued_compensation_source_baseline": accrued["source_baseline"],
        "basis": {
            "contract_billings_to_recognition": "selected policy fixed base for modeled liability additions",
            "contract_recognition_share": "packet disclosed recognized revenue / comparable nine-month consolidated revenue",
            "current_contract_presentation_share": "packet current contract liability / packet total contract liability",
            "accrued_compensation_source_baseline": "packet opening accrued compensation / packet TTM revenue",
        },
    }


def build_working_capital_model(packet: dict[str, Any], proposal: WorkingCapitalProposal, review: WorkingCapitalReview) -> dict[str, Any]:
    validate_proposal(proposal, packet)
    locked = _source_locked_parameters(packet)
    p6 = packet.get("p6_forecast") or {}
    revenue = [float(value) for value in p6.get("consolidated_revenue", [])]
    cogs = [float(value) for value in p6.get("cost_of_revenue", [])]
    if len(revenue) != len(PERIODS) or len(cogs) != len(PERIODS):
        # The exact P6 input carries the same values in operating_forecast.
        raise WorkingCapitalError("P7 requires the eleven-period P6 revenue and cost-of-revenue preview")
    days = [item["days"] for item in _period_meta()]
    ar_open, inventory_open, ap_open = _opening(packet, "current_accounts_receivable"), _opening(packet, "inventory"), _opening(packet, "operating_ap_calculated")
    lt_ar_open, server_open = _opening(packet, "long_term_accounts_receivable"), _opening(packet, "server_component_receivables")
    oca_open = _number(packet["balances"]["other_current_assets_reported"]["Q3FY2026"], "reported OCA") - server_open
    ocl_open = packet["ocl_bridge"]["unclassified_operating_residual"]
    accrued_open = _opening(packet, "accrued_compensation")
    contract_open = _opening(packet, "contract_liability_total_calculated")
    contract_current_open = _opening(packet, "contract_liability_current")
    contract_noncurrent_open = _opening(packet, "contract_liability_noncurrent")
    accrued_driver = _accrued_compensation_driver(packet, proposal.accrued_compensation_multiplier)
    rows: dict[str, list[float]] = {name: [] for name in ("current_ar_opening", "current_ar_closing", "inventory_opening", "inventory_closing", "operating_ap_opening", "operating_ap_closing", "long_term_ar_opening", "long_term_ar_closing", "server_receivables_opening", "server_receivables_closing", "other_oca_opening", "other_oca_closing", "accrued_compensation_opening", "accrued_compensation_closing", "contract_liability_opening", "contract_recognition", "contract_billings", "contract_liability_closing", "current_contract_presentation", "noncurrent_contract_presentation", "other_ocl_opening", "other_ocl_closing", "conventional_current_nwc", "cash_conversion_nwc", "cash_conversion_nwc_change", "cfo_contribution")}
    prev = {"ar": ar_open, "inventory": inventory_open, "ap": ap_open, "lt_ar": lt_ar_open, "server": server_open, "oca": oca_open, "accrued": accrued_open, "contract": contract_open, "ocl": ocl_open}
    for i, _period in enumerate(PERIODS):
        ar = revenue[i] / days[i] * proposal.current_ar_dso
        inv = cogs[i] / days[i] * proposal.inventory_dio
        ap = cogs[i] / days[i] * proposal.operating_ap_dpo
        lt_ar = prev["lt_ar"]
        server = prev["server"] * (1 + proposal.server_receivable_change_first_stub) if i == 0 else prev["server"]
        oca = prev["oca"]
        accrued = revenue[i] / days[i] * 365 * accrued_driver["effective_ratio"]
        recognition = revenue[i] * locked["contract_recognition_share"]
        billings_ratio = locked["contract_billings_to_recognition"] * (proposal.contract_billing_multiplier_first_stub if i == 0 else 1.0)
        billings = recognition * billings_ratio
        contract = prev["contract"] + billings - recognition
        if contract < -1e-9:
            raise WorkingCapitalError("negative contract liability requires a supported contract-asset method")
        current_contract = contract * locked["current_contract_presentation_share"]
        noncurrent_contract = contract - current_contract
        ocl = prev["ocl"]
        current_nwc = ar + inv + server + oca - ap - accrued - current_contract - ocl
        cash_nwc = ar + inv + server + oca + lt_ar - ap - accrued - contract - ocl
        change = cash_nwc - (ar_open + inventory_open + server_open + oca_open + lt_ar_open - ap_open - accrued_open - contract_open - ocl_open if i == 0 else rows["cash_conversion_nwc"][-1])
        values = {"current_ar_opening": prev["ar"], "current_ar_closing": ar, "inventory_opening": prev["inventory"], "inventory_closing": inv, "operating_ap_opening": prev["ap"], "operating_ap_closing": ap, "long_term_ar_opening": prev["lt_ar"], "long_term_ar_closing": lt_ar, "server_receivables_opening": prev["server"], "server_receivables_closing": server, "other_oca_opening": prev["oca"], "other_oca_closing": oca, "accrued_compensation_opening": prev["accrued"], "accrued_compensation_closing": accrued, "contract_liability_opening": prev["contract"], "contract_recognition": recognition, "contract_billings": billings, "contract_liability_closing": contract, "current_contract_presentation": current_contract, "noncurrent_contract_presentation": noncurrent_contract, "other_ocl_opening": prev["ocl"], "other_ocl_closing": ocl, "conventional_current_nwc": current_nwc, "cash_conversion_nwc": cash_nwc, "cash_conversion_nwc_change": change, "cfo_contribution": -change}
        for name, value in values.items():
            rows[name].append(value)
        prev = {"ar": ar, "inventory": inv, "ap": ap, "lt_ar": lt_ar, "server": server, "oca": oca, "accrued": accrued, "contract": contract, "ocl": ocl}
    return {
        "schema_version": "p7-msft-working-capital-model-v1",
        "forecast_authority": "Mog formulas compiled by asset_model.mjs; Python arrays are diagnostic preview only",
        "periods": _period_meta(),
        "method": {"id": proposal.method_id, "version": proposal.method_version},
        "inputs": {"current_ar_dso": proposal.current_ar_dso, "inventory_dio": proposal.inventory_dio, "operating_ap_dpo": proposal.operating_ap_dpo, "accrued_compensation_baseline": accrued_driver["source_baseline"], "accrued_compensation_multiplier": accrued_driver["multiplier"], "accrued_compensation_effective_ratio": accrued_driver["effective_ratio"], "accrued_compensation_units": {"baseline": accrued_driver["source_baseline_units"], "multiplier": accrued_driver["multiplier_units"], "effective_ratio": accrued_driver["effective_ratio_units"]}, "server_receivable_change_first_stub": proposal.server_receivable_change_first_stub, "contract_billings_to_recognition": locked["contract_billings_to_recognition"], "contract_billing_multiplier_first_stub": proposal.contract_billing_multiplier_first_stub, "contract_recognition_share": locked["contract_recognition_share"], "current_contract_presentation_share": locked["current_contract_presentation_share"], "source_locked_parameters": locked, "opening_current_ar": ar_open, "opening_inventory": inventory_open, "opening_operating_ap": ap_open, "opening_long_term_ar": lt_ar_open, "opening_server_receivables": server_open, "opening_other_oca_residual": oca_open, "opening_accrued_compensation": accrued_open, "opening_contract_current": contract_current_open, "opening_contract_noncurrent": contract_noncurrent_open, "opening_other_ocl_residual": ocl_open, "opening_dividend_payable_financing": packet['ocl_bridge']['dividend_payable_financing']},
        "forecast": {"revenue": revenue, "cost_of_revenue": cogs, **rows},
        "historical_bridge": packet["historical_bridge"],
        "contract_bridge": packet["contract_bridge"],
        "decision": {"status": "SYSTEM_REVIEWED_PROVISIONAL" if review.verdict == "accept" else "REVIEW_REQUIRED", "review_verdict": review.verdict},
        "limitations": packet["unavailable"],
    }


def review_proposal(proposal: WorkingCapitalProposal, packet: dict[str, Any], authoritative: dict[str, Any] | None = None) -> WorkingCapitalReview:
    try:
        validate_proposal(proposal, packet)
    except WorkingCapitalError as exc:
        return WorkingCapitalReview(verdict="reject", evidence_strength="weak", method_valid=False, source_valid=False, period_valid=False, cash_sign_valid=False, exclusions_valid=False, no_double_count=False, concerns=[str(exc)], required_revision=None, target="none", rationale="P7 proposal failed deterministic validation")
    concerns = ["Historical balance/CFS differences remain unresolved diagnostics and are not forecast plugs.", "Modeled contract billings are additions to the deferred liability bridge, not cash receipts.", "Accrued compensation uses the packet-derived source baseline times a dimensionless multiplier; the multiplier is not a revenue fraction."]
    if authoritative is None:
        concerns.append("Authoritative Mog consequence preview is not attached.")
        strength = "mixed"
    else:
        strength = "strong"
    return WorkingCapitalReview(verdict="accept", evidence_strength=strength, method_valid=True, source_valid=True, period_valid=True, cash_sign_valid=True, exclusions_valid=True, no_double_count=True, concerns=concerns, required_revision=None, target="none", rationale="Selected P7 balances, exclusions, period days, contract bridge and single CFO movement satisfy the bounded working-capital contract.")


def _request(instruction: str, payload: dict[str, Any], response_model: type[BaseModel]) -> dict[str, Any]:
    return {"model": MODEL, "reasoning": {"effort": REASONING_EFFORT}, "service_tier": "default", "input": json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")), "instructions": instruction, "text": {"format": {"type": "json_schema", "name": "working_capital_review" if response_model is WorkingCapitalReview else "working_capital_proposal", "strict": True, "schema": response_model.model_json_schema()}}, "max_output_tokens": MAX_OUTPUT_TOKENS, "tools": [], "background": False}


def _context(packet: dict[str, Any], authoritative: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "proposal_schema_hash": content_hash(WorkingCapitalProposal.model_json_schema()), "review_schema_hash": content_hash(WorkingCapitalReview.model_json_schema()), "prompt_version": PROMPT_VERSION, "method_catalog_version": METHOD_CATALOG_VERSION, "model": MODEL, "reasoning_effort": REASONING_EFFORT, "max_output_tokens": MAX_OUTPUT_TOKENS, "endpoint": f"{BASE_URL}/responses", "case": CASE, "information_cutoff": INFORMATION_CUTOFF, "measurement_date": MEASUREMENT_DATE, "packet_hash": content_hash(packet), "authoritative_consequences_hash": content_hash(authoritative) if authoritative else None}


def _proposal_payload(packet: dict[str, Any], context: dict[str, Any], purpose: str, candidate: WorkingCapitalProposal | None = None, review: WorkingCapitalReview | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"purpose": purpose, "packet": packet, "context": context, "required_periods": list(PERIODS), "contract": {"schema_version": SCHEMA_VERSION, "method_catalog_version": METHOD_CATALOG_VERSION, "allowed_method_ids": ["balance_based_days_plus_contract_bridge"], "no_runtime_code": True, "no_human_financial_approval": True, "negative_nwc_valid": True, "unknowns_must_remain_visible": True, "source_locked_parameters": {"owner": "application", "fields": ["contract_billings_to_recognition", "contract_recognition_share", "current_contract_presentation_share", "accrued_compensation_source_baseline"], "derivation": "derive from the current packet at validation and model-build time; the analyst schema cannot edit them"}, "judgment_bounds": {"server_receivable_change_first_stub": [-0.2, 0.2], "contract_billing_multiplier_first_stub": [0.9, 1.1], "accrued_compensation_multiplier": [ACCRUED_COMPENSATION_MULTIPLIER_MIN, ACCRUED_COMPENSATION_MULTIPLIER_MAX], "days": "nonnegative"}, "bounded_default_values": {"server_receivable_change_first_stub": 0.0, "contract_billing_multiplier_first_stub": 1.0, "accrued_compensation_multiplier": 1.0}, "bounded_default_instruction": "Use the bounded defaults unless a source-supported alternative is essential; keep source-locked parameters outside the proposal. The accrued compensation multiplier is dimensionless and never a revenue fraction."}}
    if candidate is not None:
        payload["candidate"] = candidate.model_dump(mode="json")
    if review is not None:
        payload["review"] = review.model_dump(mode="json")
    return payload


def _review_payload(packet: dict[str, Any], context: dict[str, Any], candidate: WorkingCapitalProposal, review_preview: dict[str, Any], authoritative: dict[str, Any] | None = None, prior_review: WorkingCapitalReview | None = None) -> dict[str, Any]:
    return {"purpose": "independent P7 working-capital review", "packet": packet, "context": context, "candidate": candidate.model_dump(mode="json"), "accrued_compensation_driver": _accrued_compensation_driver(packet, candidate.accrued_compensation_multiplier), "forecast_preview": review_preview, "authoritative_mog": authoritative or {"status": "NOT_ATTACHED"}, "prior_review": prior_review.model_dump(mode="json") if prior_review else None, "review_contract": {"review_only": True, "accept_requires_authoritative_mog": True, "revise_requires_one_consequential_target": True, "do_not_return_formulas_or_code": True, "accrued_compensation_units": "source baseline is a ratio; multiplier is dimensionless [0.8,1.2]; effective ratio is baseline multiplied by multiplier; multiplier is never an annualized revenue fraction"}}


def _validate_review(review: WorkingCapitalReview) -> None:
    if review.verdict == "revise" and (review.target == "none" or not review.required_revision):
        raise WorkingCapitalError("P7 revise verdict must name one target and required revision")
    if review.verdict != "revise" and review.target != "none":
        raise WorkingCapitalError("P7 accept/reject verdict cannot carry revision target")


def _eligible(review: WorkingCapitalReview) -> bool:
    return review.evidence_strength != "weak" and all((review.method_valid, review.source_valid, review.period_valid, review.cash_sign_valid, review.exclusions_valid, review.no_double_count))


def _consequential(old: WorkingCapitalProposal, new: WorkingCapitalProposal, target: str) -> None:
    oldv, newv = old.model_dump(mode="json"), new.model_dump(mode="json")
    if target == "presentation":
        raise WorkingCapitalError("P7 application-locked contract presentation cannot be analyst-revised")
    if target == "days_driver" and oldv["current_ar_dso"] == newv["current_ar_dso"] and oldv["inventory_dio"] == newv["inventory_dio"] and oldv["operating_ap_dpo"] == newv["operating_ap_dpo"]:
        raise WorkingCapitalError("P7 days-driver revision did not change a days driver")
    if target == "contract_billing" and oldv["contract_billing_multiplier_first_stub"] == newv["contract_billing_multiplier_first_stub"]:
        raise WorkingCapitalError("P7 contract-billing revision did not change billings")
    if target == "server_receivable" and oldv["server_receivable_change_first_stub"] == newv["server_receivable_change_first_stub"]:
        raise WorkingCapitalError("P7 server-receivable revision did not change scenario")
    if target == "accrued_compensation" and oldv["accrued_compensation_multiplier"] == newv["accrued_compensation_multiplier"]:
        raise WorkingCapitalError("P7 accrued-compensation revision did not change multiplier")
    if oldv == newv:
        raise WorkingCapitalError("P7 analyst revision returned the same proposal")


def _build_authority(p6: dict[str, Any], packet: dict[str, Any], candidate: WorkingCapitalProposal, review: WorkingCapitalReview, authority_dir: Path) -> dict[str, Any]:
    model = copy.deepcopy(p6)
    p7 = copy.deepcopy(packet)
    p7["p6_forecast"] = {"consolidated_revenue": p6["operating_forecast"]["forecast_revenue"], "cost_of_revenue": p6["operating_forecast"]["costs"]["cost_of_revenue"]}
    wc = build_working_capital_model(p7, candidate, review)
    wc["decision"]["status"] = "REVIEW_REQUIRED"
    model["working_capital_packet"] = packet
    model["working_capital_forecast"] = wc
    model["working_capital_decision"] = {"proposal": candidate.model_dump(mode="json"), "review": review.model_dump(mode="json"), "status": "REVIEW_REQUIRED", "decision_id": "P7-MSFT-WORKING-CAPITAL-PREVIEW-R4"}
    authority_dir.mkdir(parents=True, exist_ok=True)
    input_path = authority_dir / "model-input.json"
    _write_json(input_path, model)
    repo_root = Path(__file__).resolve().parents[2]
    command = ["node", "scripts/spreadsheet_compat/run-p7.mjs", "authority", str(input_path), str(authority_dir)]
    try:
        subprocess.run(command, cwd=repo_root, check=True, capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.SubprocessError) as exc:
        _write_json(authority_dir / "mog-authority-error.json", {"error_type": type(exc).__name__, "error": str(exc), "stdout": getattr(exc, "stdout", ""), "stderr": getattr(exc, "stderr", "")})
        raise WorkingCapitalError(f"P7 Mog authority failed; see {authority_dir / 'mog-authority-error.json'}") from exc
    result_path = authority_dir / "working-capital-verification.json"
    if not result_path.exists():
        raise WorkingCapitalError("P7 Mog authority did not persist verification")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if result.get("status") != "PASS":
        raise WorkingCapitalError("P7 Mog authority verification failed")
    return result


def _terminal_outcome(
    run_dir: Path,
    packet: dict[str, Any],
    context: dict[str, Any],
    *,
    stage: str,
    status: str,
    reason: str,
) -> None:
    """Persist the current failure state without publishing a model."""
    _write_json(
        run_dir / "terminal-outcome.json",
        {
            "status": status,
            "stage": stage,
            "reason": reason,
            "context_hash": content_hash(context),
            "source_packet_hash": content_hash(packet),
            "publication": "no P7 model published; prior attempt artifacts remain preserved",
        },
    )


def _p7_packet(packet: dict[str, Any], p6: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(packet)
    result["p6_forecast"] = {
        "consolidated_revenue": p6["operating_forecast"]["forecast_revenue"],
        "cost_of_revenue": p6["operating_forecast"]["costs"]["cost_of_revenue"],
    }
    return result


def prepare_live_handoff(
    p6: dict[str, Any],
    run_dir: Path,
    *,
    source_table: Path | None = None,
    output_path: Path | None = None,
    budget_path: Path | None = None,
) -> dict[str, Any]:
    """Prepare the exact first live request without touching credentials or budget state."""
    packet = _p7_packet(build_evidence_packet(p6, source_table), p6)
    context = _context(packet)
    payload = _proposal_payload(packet, context, "initial analyst selection")
    request = _request(INITIAL_ANALYST_INSTRUCTION, payload, WorkingCapitalProposal)
    rebuilt_request = _request(INITIAL_ANALYST_INSTRUCTION, payload, WorkingCapitalProposal)
    request_path = run_dir / "attempts" / "01-analyst-initial.request.json"
    run_dir.mkdir(parents=True, exist_ok=True)
    request_path.parent.mkdir(parents=True, exist_ok=True)

    def write_or_verify(path: Path, value: Any) -> None:
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing != value:
                raise WorkingCapitalError(f"prepared handoff artifact differs: {path}")
            return
        _write_json(path, value)

    write_or_verify(run_dir / "run-context.json", context)
    write_or_verify(run_dir / "evidence-packet.json", packet)
    write_or_verify(request_path, request)
    command = (
        "PYTHONPATH=src python -m smrik_fund.working_capital "
        f"--p6-model {Path('data/build-guide-p6/live-r4-20260906/model-input.json').as_posix()} "
        f"--output {(output_path or run_dir / 'model-input.json').as_posix()} "
        f"--run-dir {run_dir.as_posix()} "
        f"--budget {(budget_path or Path('data/build-guide-api-budget.json')).as_posix()}"
    )
    manifest = {
        "status": "PREPARED_NO_DISPATCH",
        "stage": "analyst-initial",
        "case": CASE,
        "request_path": request_path.as_posix(),
        "request_hash": content_hash(request),
        "request_rebuilt_hash": content_hash(rebuilt_request),
        "canonical_request_equal": request == rebuilt_request,
        "context_hash": content_hash(context),
        "payload_hash": content_hash(payload),
        "source_packet_hash": content_hash(packet),
        "settings": {
            "model": MODEL,
            "reasoning": {"effort": REASONING_EFFORT},
            "service_tier": "default",
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "tools": [],
            "background": False,
        },
        "cli": command,
        "replay_policy": "only an exact completed request may resume; invalid or unsettled outcomes remain held",
    }
    write_or_verify(run_dir / "prepared-manifest.json", manifest)
    return manifest


def run_reasoning(packet: dict[str, Any], p6: dict[str, Any], run_dir: Path, budget_path: Path, *, offline: bool = False, client: Any | None = None) -> tuple[WorkingCapitalProposal, WorkingCapitalReview, dict[str, Any]]:
    run_dir.mkdir(parents=True, exist_ok=True)
    packet = _p7_packet(packet, p6)
    context = _context(packet)
    context_path = run_dir / "run-context.json"
    if context_path.exists() and json.loads(context_path.read_text(encoding="utf-8")) != context:
        _terminal_outcome(run_dir, packet, context, stage="context", status="CONTEXT_STALE", reason="P7 run context changed; prior outputs cannot be reused")
        raise WorkingCapitalError("P7 run context changed; prior outputs cannot be reused")
    _write_json(context_path, context)
    _write_json(run_dir / "evidence-packet.json", packet)
    proposal: WorkingCapitalProposal
    review: WorkingCapitalReview
    if offline:
        proposal = default_proposal(packet)
        review = review_proposal(proposal, packet)
        status = "OFFLINE_FIXTURE"
    else:
        stage = "analyst-initial"
        review = None
        final_review = None
        try:
            payload = _proposal_payload(packet, context, "initial analyst selection")
            request = _request(INITIAL_ANALYST_INSTRUCTION, payload, WorkingCapitalProposal)
            proposal, _ = _dispatch_structured(stage=stage, run_dir=run_dir, budget_path=budget_path, instruction=INITIAL_ANALYST_INSTRUCTION, payload=payload, response_model=WorkingCapitalProposal, client=client, prepared_request=request, task_id=TASK_ID, max_attempts=MAX_ATTEMPTS, max_committed_eur=MAX_COMMITTED_EUR, call_filter=_is_p7_call)
            validate_proposal(proposal, packet)
            _write_json(run_dir / "candidate-initial.json", proposal.model_dump(mode="json"))

            stage = "mog-authority-initial"
            authority = _build_authority(p6, packet, proposal, review_proposal(proposal, packet), run_dir / "mog-authority" / "analyst-initial")
            review_payload = _review_payload(packet, _context(packet, authority), proposal, authority.get("snapshot", authority), authority)
            review_request = _request(ORIGINAL_REVIEW_INSTRUCTION, review_payload, WorkingCapitalReview)
            stage = "reviewer-original"
            review, _ = _dispatch_structured(stage=stage, run_dir=run_dir, budget_path=budget_path, instruction=ORIGINAL_REVIEW_INSTRUCTION, payload=review_payload, response_model=WorkingCapitalReview, client=client, prepared_request=review_request, task_id=TASK_ID, max_attempts=MAX_ATTEMPTS, max_committed_eur=MAX_COMMITTED_EUR, call_filter=_is_p7_call)
            _validate_review(review)
            _write_json(run_dir / "review-original.json", review.model_dump(mode="json"))
            if review.verdict == "revise":
                _write_json(run_dir / "revision-request.json", {"requested_by": "system_review", "target": review.target, "required_revision": review.required_revision, "prior_candidate_hash": content_hash(proposal.model_dump(mode="json")), "context_hash": content_hash(context)})
                revision_payload = _proposal_payload(packet, context, "required consequential analyst revision", proposal, review)
                revision_request = _request(REVISION_ANALYST_INSTRUCTION, revision_payload, WorkingCapitalProposal)
                stage = "analyst-revision"
                revised, _ = _dispatch_structured(stage=stage, run_dir=run_dir, budget_path=budget_path, instruction=REVISION_ANALYST_INSTRUCTION, payload=revision_payload, response_model=WorkingCapitalProposal, client=client, prepared_request=revision_request, task_id=TASK_ID, max_attempts=MAX_ATTEMPTS, max_committed_eur=MAX_COMMITTED_EUR, call_filter=_is_p7_call)
                validate_proposal(revised, packet)
                _consequential(proposal, revised, review.target)
                _write_json(run_dir / "candidate-revision.json", revised.model_dump(mode="json"))

                stage = "mog-authority-revision"
                revision_authority = _build_authority(p6, packet, revised, review_proposal(revised, packet), run_dir / "mog-authority" / "analyst-revision")
                final_payload = _review_payload(packet, _context(packet, revision_authority), revised, revision_authority.get("snapshot", revision_authority), revision_authority, review)
                final_request = _request(REVISION_REVIEW_INSTRUCTION, final_payload, WorkingCapitalReview)
                stage = "reviewer-revision"
                final_review, _ = _dispatch_structured(stage=stage, run_dir=run_dir, budget_path=budget_path, instruction=REVISION_REVIEW_INSTRUCTION, payload=final_payload, response_model=WorkingCapitalReview, client=client, prepared_request=final_request, task_id=TASK_ID, max_attempts=MAX_ATTEMPTS, max_committed_eur=MAX_COMMITTED_EUR, call_filter=_is_p7_call)
                _validate_review(final_review)
                _write_json(run_dir / "review-revision.json", final_review.model_dump(mode="json"))
                if final_review.verdict != "accept" or not _eligible(final_review):
                    raise WorkingCapitalError("P7 review did not accept the consequential revision")
                proposal, review, authority = revised, final_review, revision_authority
            elif review.verdict != "accept" or not _eligible(review):
                raise WorkingCapitalError("P7 review did not accept the policy")
            status = "SYSTEM_REVIEWED_PROVISIONAL"
        except Exception as exc:
            if ((stage == "reviewer-original" and review is not None and review.verdict == "reject") or (stage == "reviewer-revision" and final_review is not None and final_review.verdict == "reject")):
                failure_status = "REJECTED_BY_REVIEW"
            elif stage in {"analyst-initial", "analyst-revision"}:
                failure_status = "ANALYST_INCOMPLETE"
            elif stage.startswith("mog-authority"):
                failure_status = "MOG_AUTHORITY_INCOMPLETE"
            elif stage == "reviewer-revision":
                failure_status = "REVISION_REQUIRED"
            else:
                failure_status = "REVIEW_INCOMPLETE"
            _terminal_outcome(run_dir, packet, context, stage=stage, status=failure_status, reason=str(exc))
            raise
    wc = build_working_capital_model(packet, proposal, review)
    wc["decision"].update({"status": status, "context_hash": content_hash(context), "source_packet_hash": content_hash(packet), "candidate_hash": content_hash(proposal.model_dump(mode="json")), "review_hash": content_hash(review.model_dump(mode="json"))})
    wc["decision"]["binding"] = {**{field: wc["decision"][field] for field in BINDING_HASH_FIELDS}, "candidate_snapshot": proposal.model_dump(mode="json"), "review_snapshot": review.model_dump(mode="json"), "source_case_snapshot_sha256": packet.get("p6_dependency", {}).get("source_case_snapshot_sha256"), "accrued_compensation_driver": {"source_baseline": wc["inputs"]["accrued_compensation_baseline"], "multiplier": wc["inputs"]["accrued_compensation_multiplier"], "effective_ratio": wc["inputs"]["accrued_compensation_effective_ratio"], "units": wc["inputs"]["accrued_compensation_units"]}}
    wc["working_capital_decision"] = {"proposal": proposal.model_dump(mode="json"), "review": review.model_dump(mode="json"), "status": status, "binding": wc["decision"]["binding"]}
    _write_json(run_dir / "candidate.json", proposal.model_dump(mode="json"))
    _write_json(run_dir / "review.json", review.model_dump(mode="json"))
    _write_json(run_dir / "model.json", wc)
    _write_json(run_dir / "terminal-outcome.json", {"status": status, "stage": "complete", "context_hash": content_hash(context), "source_packet_hash": content_hash(packet), "publication": "P7 model published only after deterministic validation and review state handling"})
    return proposal, review, wc


def _run_cli(args: argparse.Namespace) -> None:
    p6_path = Path(args.p6_model)
    p6 = json.loads(p6_path.read_text(encoding="utf-8"))
    packet = build_evidence_packet(p6, Path(args.source_table) if args.source_table else None)
    proposal, review, wc = run_reasoning(packet, p6, Path(args.run_dir), Path(args.budget), offline=args.offline)
    output_model = copy.deepcopy(p6)
    output_model["working_capital_packet"] = packet
    output_model["working_capital_forecast"] = wc
    output_model["working_capital_decision"] = wc["working_capital_decision"]
    output_model["p7_decision"] = {"decision_id": "P7-MSFT-WORKING-CAPITAL-DECISION-R4", "status": wc["decision"]["status"], "human_approval": False, "review": review.model_dump(mode="json"), "binding": wc["decision"]["binding"], **{field: wc["decision"][field] for field in BINDING_HASH_FIELDS}}
    output_model["decision"] = {**(p6.get("decision") or {}), "status": wc["decision"]["status"], "p7_status": wc["decision"]["status"], "p7_decision_id": output_model["p7_decision"]["decision_id"], "coverage": "P5 asset + P6 operating + P7 working capital; P8-P12 remain incomplete"}
    output_model["schema_version"] = "p7-msft-working-capital-input-v3"
    _write_json(Path(args.output), output_model)
    _write_json(Path(args.run_dir) / "model-input.json", output_model)
    print(json.dumps({"status": wc["decision"]["status"], "output": str(Path(args.output)), "run_dir": str(Path(args.run_dir)), "proposal": proposal.model_dump(mode="json"), "review": review.model_dump(mode="json")}, indent=2))


def _prepare_cli(args: argparse.Namespace) -> None:
    p6 = json.loads(Path(args.p6_model).read_text(encoding="utf-8"))
    manifest = prepare_live_handoff(
        p6,
        Path(args.run_dir),
        source_table=Path(args.source_table) if args.source_table else None,
        output_path=Path(args.output),
        budget_path=Path(args.budget),
    )
    print(json.dumps(manifest, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--p6-model", default="data/build-guide-p6/live-r4-20260906/model-input.json")
    parser.add_argument("--output", default="data/build-guide-p7/model-input.json")
    parser.add_argument("--run-dir", default="data/build-guide-p7/live-r1")
    parser.add_argument("--budget", default="data/build-guide-api-budget.json")
    parser.add_argument("--source-table", default=None)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--prepare", action="store_true", help="Prepare the exact initial live request without dispatching or reading credentials/budget state")
    args = parser.parse_args()
    if args.prepare:
        _prepare_cli(args)
    else:
        _run_cli(args)


if __name__ == "__main__":
    main()
