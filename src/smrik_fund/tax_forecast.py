"""P8A linked book/current/deferred/cash tax boundary.

The module validates a small, explicit tax policy and produces a diagnostic
preview.  Forecast formulas are compiled by the Mog workbook builder; the
arrays returned here are used for inspection, review context, and frozen
offline tests only.
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import math
import subprocess
from datetime import date
from pathlib import Path
from typing import Annotated, Any, Literal

from openai.lib._pydantic import to_strict_json_schema
from pydantic import BaseModel, ConfigDict, Field, model_validator

from smrik_fund.analysis_budget import content_hash
from smrik_fund.operating_forecast import BINDING_HASH_FIELDS, _dispatch_structured

CASE = "MSFT"
INFORMATION_CUTOFF = "2026-04-30"
MEASUREMENT_DATE = "2026-03-31"
MODEL = "gpt-5.6-luna"
ENDPOINT_HOST = "api.openai.com"
BASE_URL = f"https://{ENDPOINT_HOST}/v1"
TASK_ID = "p8a-msft-taxes"
MAX_ATTEMPTS = 10
MAX_COMMITTED_EUR = 0.50
PERIODS = (
    "FY2026_STUB", "FY2027", "FY2028", "FY2029", "FY2030", "FY2031",
    "FY2032", "FY2033", "FY2034", "FY2035", "FY2036",
)
SCHEMA_VERSION = "p8a-tax-proposal-r6"
PROMPT_VERSION = "p8a-tax-reasoning-r6"
METHOD_CATALOG_VERSION = "p8a-tax-methods-r6"
METHOD_ID = "linked_book_current_deferred_cash_tax"
METHOD_VERSION = "v2"
PAYABLE_TIMING_METHOD = "source_anchored_payable_days"
EXPLICIT_PAYABLE_METHOD = "explicit_closing_balance"
PAYABLE_DAYS_MAX = 365.0
REASONING_EFFORT = "medium"
MAX_OUTPUT_TOKENS = 12_000
TOLERANCE = 1e-8

INITIAL_ANALYST_INSTRUCTION = (
    "Select one bounded P8A tax policy from the frozen packet. Preserve reported "
    "values, signs, units, periods and source identity. Keep book tax, current "
    "tax, deferred tax, cash tax, current payable, long-term tax liability and "
    "the operating-tax measure distinct. Select either the source-anchored "
    "current-payable-days method or the explicit-closing-balance alternative. "
    "For the days method return one nonnegative payable-days driver, bounded to "
    "0-365, and let the application derive each closing balance from current tax "
    "expense and actual period days. For the explicit method return eleven closing "
    "balances and no days driver. A loss does not create a refund, NOL use or new "
    "deferred tax asset. Return only a complete proposal in the schema."
)
ORIGINAL_REVIEW_INSTRUCTION = (
    "Independently review the P8A tax proposal against the frozen source facts, "
    "the linked P7 EBIT periods, the actual Mog tax preview, source-account "
    "containment, current/deferred/cash bridge, actual-period timing, long-term "
    "settlement, loss behavior, and operating-tax independence from financing. "
    "Judge a source-anchored provisional forecast and its material limitations; "
    "future reported facts are not required, estimates are not disclosures, and "
    "human approval remains separate from system review. Historical cash residuals "
    "are diagnostics, not forecast plugs. Do not accept a negative unsupported "
    "cash payment, over-settlement, DTL below zero, inactive timing revision, or "
    "missing required numeric input. Return compact schema JSON."
)
REVISION_ANALYST_INSTRUCTION = (
    "Make exactly one consequential bounded P8A tax-policy revision named by the "
    "review. Preserve source facts, opening balances, method identity and all "
    "other drivers. A current-payable timing revision must change the active "
    "days driver or active closing-balance trajectory, not an inactive field or "
    "prose only. Return a complete proposal in the schema."
)
REVISION_REVIEW_INSTRUCTION = (
    "Re-check the consequential P8A tax revision using the actual Mog-calculated "
    "tax schedule and linked statements. Confirm actual-period payable timing, an "
    "effective forecast change under the selected timing method, one-time cash/"
    "liability settlement, no loss refund, no DTL underflow, and independent "
    "operating tax. Return a terminal schema verdict."
)


class TaxForecastError(ValueError):
    """P8A source, policy, preview, review, or dependency failure."""


DeferredShare = Annotated[float, Field(ge=-1, le=1)]
NonnegativeUsdMillions = Annotated[float, Field(ge=0)]
PayableDays = Annotated[float, Field(ge=0, le=PAYABLE_DAYS_MAX)]
PayableMethod = Literal["source_anchored_payable_days", "explicit_closing_balance"]


class TaxProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["propose_forecast", "unresolved", "capability_gap"]
    method_id: Literal["linked_book_current_deferred_cash_tax"] | None = None
    method_version: Literal["v2"] | None = None
    book_tax_rate: float | None = Field(default=None, ge=0, le=1, description="Decimal fraction, for example 0.20 means 20%.")
    operating_tax_rate: float | None = Field(default=None, ge=0, le=1, description="Decimal fraction applied to positive EBIT for normalized operating tax.")
    deferred_share: list[DeferredShare] | None = Field(default=None, min_length=11, max_length=11, description="Eleven dimensionless deferred-tax expense shares, each bounded to [-1, 1]. Required for a forecast proposal.")
    current_tax_payable_method: PayableMethod | None = Field(default=None, description="Active current-tax payable timing method. The days method and explicit-closing method are mutually exclusive.")
    current_tax_payable_days: PayableDays | None = Field(default=None, description="Active payable-days driver in calendar days, bounded to [0, 365]. Required only for source_anchored_payable_days.")
    current_tax_payable_closing: list[NonnegativeUsdMillions] | None = Field(default=None, min_length=11, max_length=11, description="Eleven closing current-tax payable balances in USD millions; required only for explicit_closing_balance.")
    long_term_tax_settlement: list[NonnegativeUsdMillions] | None = Field(default=None, min_length=11, max_length=11, description="Eleven long-term tax settlements in USD millions; each is nonnegative and capped semantically by the booked liability.")
    dta_policy: Literal["hold_flat_no_new_recognition"] | None = None
    nol_policy: Literal["no_utilization_or_refund"] | None = None
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
        scalar_fields = ("book_tax_rate", "operating_tax_rate", "current_tax_payable_days")
        array_fields = ("deferred_share", "current_tax_payable_closing", "long_term_tax_settlement")
        for field in scalar_fields:
            if field in value:
                raw = value[field]
                if raw is None:
                    continue
                if isinstance(raw, bool) or not isinstance(raw, int | float) or not math.isfinite(raw):
                    raise ValueError(f"{field} must be a numeric value")
        for field in array_fields:
            if field not in value:
                continue
            raw_values = value[field]
            if raw_values is None:
                continue
            if not isinstance(raw_values, list):
                raise ValueError(f"{field} must be an array of numeric values")
            for index, raw in enumerate(raw_values):
                if isinstance(raw, bool) or not isinstance(raw, int | float) or not math.isfinite(raw):
                    raise ValueError(f"{field}[{index}] must be a numeric value")
        return value

    @model_validator(mode="after")
    def _validate_forecast_shape(self) -> TaxProposal:
        if self.outcome != "propose_forecast":
            if not self.follow_up_request:
                raise ValueError("non-forecast outcome requires follow_up_request")
            return self
        required = {
            "method_id": self.method_id,
            "method_version": self.method_version,
            "book_tax_rate": self.book_tax_rate,
            "operating_tax_rate": self.operating_tax_rate,
            "deferred_share": self.deferred_share,
            "current_tax_payable_method": self.current_tax_payable_method,
            "long_term_tax_settlement": self.long_term_tax_settlement,
            "dta_policy": self.dta_policy,
            "nol_policy": self.nol_policy,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise ValueError(f"forecast proposal missing required fields: {', '.join(missing)}")
        if self.current_tax_payable_method == PAYABLE_TIMING_METHOD:
            if self.current_tax_payable_days is None:
                raise ValueError("source_anchored_payable_days requires current_tax_payable_days")
            if self.current_tax_payable_closing is not None:
                raise ValueError("source_anchored_payable_days cannot carry explicit closing balances")
        elif self.current_tax_payable_method == EXPLICIT_PAYABLE_METHOD:
            if self.current_tax_payable_closing is None:
                raise ValueError("explicit_closing_balance requires current_tax_payable_closing")
            if self.current_tax_payable_days is not None:
                raise ValueError("explicit_closing_balance cannot carry payable days")
        return self


class TaxReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["accept", "revise", "reject"]
    evidence_strength: Literal["strong", "mixed", "weak"]
    method_valid: bool
    source_valid: bool
    period_valid: bool
    cash_bridge_valid: bool
    operating_tax_independent: bool
    no_double_count: bool
    concerns: list[str] = Field(min_length=1)
    required_revision: str | None
    target: Literal["none", "book_rate", "operating_rate", "deferred_share", "current_payable", "payable_timing", "lt_settlement"]
    rationale: str = Field(min_length=1)


_PERIOD_SPANS = (
    ("FY2026_STUB", "2026-04-01", "2026-06-30", 0.25),
    ("FY2027", "2026-07-01", "2027-06-30", 1.0),
    ("FY2028", "2027-07-01", "2028-06-30", 1.0),
    ("FY2029", "2028-07-01", "2029-06-30", 1.0),
    ("FY2030", "2029-07-01", "2030-06-30", 1.0),
    ("FY2031", "2030-07-01", "2031-06-30", 1.0),
    ("FY2032", "2031-07-01", "2032-06-30", 1.0),
    ("FY2033", "2032-07-01", "2033-06-30", 1.0),
    ("FY2034", "2033-07-01", "2034-06-30", 1.0),
    ("FY2035", "2034-07-01", "2035-06-30", 1.0),
    ("FY2036", "2035-07-01", "2036-06-30", 1.0),
)


def _days_between(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days + 1


def _period_meta() -> list[dict[str, Any]]:
    return [
        {"id": period, "start": start, "end": end, "days": _days_between(start, end), "year_fraction": year_fraction}
        for period, start, end, year_fraction in _PERIOD_SPANS
    ]


def _period_days() -> list[int]:
    return [item["days"] for item in _period_meta()]


def _source_amount(source_facts: dict[str, Any], item: str, period: str) -> float:
    value = (source_facts.get(item) or {}).get(period)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise TaxForecastError(f"{item}.{period} source amount is missing")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise TaxForecastError(f"{item}.{period} source amount is nonnumeric") from exc
    if not math.isfinite(number):
        raise TaxForecastError(f"{item}.{period} source amount is nonfinite")
    return number


def _payable_timing_anchors(source_facts: dict[str, Any]) -> dict[str, Any]:
    """Derive payable days from reported source amounts and actual FY spans."""
    fy25_days = _days_between("2024-07-01", "2025-06-30")
    fy24_days = _days_between("2023-07-01", "2024-06-30")
    fy25_payable = _source_amount(source_facts, "current_income_tax_liability", "FY2025")
    fy25_expense = _source_amount(source_facts, "current_tax_expense", "FY2025")
    fy24_payable = _source_amount(source_facts, "current_income_tax_liability", "FY2024")
    fy24_expense = _source_amount(source_facts, "current_tax_expense", "FY2024")
    if fy25_payable < 0 or fy24_payable < 0:
        raise TaxForecastError("source current-tax payable cannot be negative")
    if fy25_expense <= 0 or fy24_expense <= 0:
        raise TaxForecastError("source current-tax expense must be positive for payable-days derivation")
    baseline_days = fy25_payable / fy25_expense * fy25_days
    alternative_days = fy24_payable / fy24_expense * fy24_days
    flat_closing = _source_amount(source_facts, "current_income_tax_liability", "Q3FY2026_BS")
    if not 0 <= baseline_days <= PAYABLE_DAYS_MAX or not 0 <= alternative_days <= PAYABLE_DAYS_MAX:
        raise TaxForecastError("source-derived payable days are outside [0,365]")
    return {
        "selected_method": PAYABLE_TIMING_METHOD,
        "baseline_days": baseline_days,
        "baseline_period": "FY2025",
        "baseline_source": {
            "current_tax_payable": fy25_payable,
            "current_tax_expense": fy25_expense,
            "actual_period_days": fy25_days,
            "formula": "current tax payable / current tax expense * actual source-period days",
        },
        "fy2024_alternative_days": alternative_days,
        "fy2024_alternative_source": {
            "current_tax_payable": fy24_payable,
            "current_tax_expense": fy24_expense,
            "actual_period_days": fy24_days,
            "formula": "current tax payable / current tax expense * actual source-period days",
        },
        "flat_alternative": {"closing_balance": flat_closing, "units": "USD millions", "source_period": "Q3FY2026_BS"},
        "formula": "modeled current tax expense / actual forecast-period days * selected payable days",
        "purpose": "Historical source-derived timing anchor for a provisional forecast estimate; not a reported future balance or exact cash-tax reconciliation.",
    }


def _historical_tax_diagnostic(source_facts: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for fiscal_year in ("FY2023", "FY2024", "FY2025"):
        current = _source_amount(source_facts, "current_tax_expense", fiscal_year)
        deferred = _source_amount(source_facts, "deferred_tax_expense", fiscal_year)
        book = _source_amount(source_facts, "book_tax_expense", fiscal_year)
        cfs_movement = _source_amount(source_facts, "cfs_income_taxes_change", fiscal_year)
        reported_cash = _source_amount(source_facts, "cash_taxes_paid_net_refunds", fiscal_year)
        cash_proxy = current - cfs_movement
        rows.append(
            {
                "fiscal_year": int(fiscal_year.removeprefix("FY")),
                "book_tax_expense": book,
                "current_tax_expense": current,
                "deferred_tax_expense": deferred,
                "current_plus_deferred_minus_book": current + deferred - book,
                "cfs_income_taxes_movement": cfs_movement,
                "reported_cash_taxes_paid_net_refunds": reported_cash,
                "cash_proxy_current_expense_minus_cfs_movement": cash_proxy,
                "proxy_minus_reported_cash": cash_proxy - reported_cash,
                "reported_cash_is_rounded": True,
            }
        )
    return {
        "purpose": "Historical diagnostic only; reported cash payments are rounded and the current-expense/CFS-movement proxy is not a universal exact reconciliation.",
        "rows": rows,
        "forecast_identity_note": "Future model accounting identities remain exact within the stated arithmetic tolerance; historical residuals are not plugs.",
    }


def _is_p8a_call(call: dict[str, Any]) -> bool:
    return call.get("task_id") == TASK_ID or str(call.get("call_id", "")).startswith(f"{TASK_ID}:")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def _number(value: Any, name: str, *, allow_zero: bool = True) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise TaxForecastError(f"{name} is missing/non-numeric")
    if not allow_zero and value == 0:
        raise TaxForecastError(f"{name} must be nonzero")
    return float(value)


def _period_array(value: Any, name: str) -> list[float]:
    if not isinstance(value, list) or len(value) != len(PERIODS):
        raise TaxForecastError(f"{name} must contain eleven forecast values")
    return [_number(item, f"{name}[{index}]") for index, item in enumerate(value)]


def _fact(packet: dict[str, Any], key: str) -> dict[str, Any]:
    value = (packet.get("facts") or {}).get("opening_balance_sheet", {}).get(key)
    if not isinstance(value, dict):
        raise TaxForecastError(f"opening_balance_sheet.{key} source fact is missing")
    _number(value.get("value"), f"opening_balance_sheet.{key}")
    return value


def _source_table() -> Path:
    return Path(__file__).resolve().parents[2] / "Lunacy" / "runs" / "three-statement-dcf" / "phases" / "taxes" / "P8A-source-table-R1.csv"


def _read_source_table(path: Path | None = None) -> list[dict[str, str]]:
    table = path or _source_table()
    with table.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _p7_accepted(p7: dict[str, Any]) -> None:
    decision = p7.get("p7_decision") or p7.get("working_capital_decision") or {}
    if decision.get("status") != "SYSTEM_REVIEWED_PROVISIONAL":
        raise TaxForecastError("P7 input is not accepted system-reviewed provisional")
    review = decision.get("review") or {}
    if review and review.get("verdict") not in {"accept", None}:
        raise TaxForecastError("P7 input review is not accepted")
    binding = decision.get("binding")
    packet = p7.get("packet") or {}
    if isinstance(binding, dict) and binding.get("source_case_snapshot_sha256") and binding["source_case_snapshot_sha256"] != packet.get("frozen_case_snapshot_sha256"):
        raise TaxForecastError("P7 source-case binding is stale")


def build_evidence_packet(p7: dict[str, Any], source_table: Path | None = None) -> dict[str, Any]:
    """Build a tax packet from accepted P7 and the frozen tax source table."""
    _p7_accepted(p7)
    table_path = source_table or _source_table()
    rows = _read_source_table(table_path)
    by_item = {row.get("line_item"): row for row in rows}
    required_rows = {"book_pretax_income", "book_tax_expense", "current_tax_expense", "deferred_tax_expense", "cash_taxes_paid_net_refunds", "current_income_tax_liability", "long_term_income_tax_liability", "deferred_income_tax_liability"}
    missing = sorted(required_rows - by_item.keys())
    if missing:
        raise TaxForecastError(f"tax source table missing rows: {', '.join(missing)}")
    source_facts = {}
    for key, row in by_item.items():
        source_facts[key] = {
            "category": row.get("category"),
            "FY2023": row.get("fy2023_06_30_usd_mm") or None,
            "FY2024": row.get("fy2024_06_30_usd_mm") or None,
            "FY2025": row.get("fy2025_06_30_usd_mm") or None,
            "Q3FY2026_3M": row.get("q3fy2026_3m_flow_usd_mm") or None,
            "Q3FY2026_9M": row.get("q3fy2026_9m_flow_usd_mm") or None,
            "Q3FY2026_BS": row.get("q3fy2026_03_31_bs_usd_mm") or None,
            "TTM": row.get("ttm_to_2026_03_31_usd_mm") or None,
            "source_locator": row.get("source_locator"),
            "source_status": row.get("source_status"),
            "notes": row.get("notes"),
        }
    required_opening = {
        "current_tax_payable": "short_term_taxes",
        "long_term_tax_liability": "long_term_taxes",
        "deferred_tax_liability": "deferred_taxes",
    }
    opening_balances = {}
    for output_name, source_name in required_opening.items():
        fact = _fact(p7.get("packet", {}), source_name)
        opening_balances[output_name] = {
            "value": fact["value"],
            "unit": fact.get("unit", "u_usd"),
            "period": fact.get("period", "Latest balance sheet"),
            "period_key": fact.get("period_key", "instant_2026-03-31"),
            "source_locator": fact.get("source_locator"),
            "source_fact_id": fact.get("source_fact_id"),
            "source_status": fact.get("source_selection_status"),
        }
    operating = p7.get("operating_forecast") or {}
    ebit = _period_array(operating.get("forecast_operating_income"), "P7 forecast operating income")
    ttm_facts = (p7.get("packet", {}).get("facts", {}).get("ttm", {}))
    ttm_pretax = _number((ttm_facts.get("pretax_income") or {}).get("value"), "TTM pretax income")
    ttm_tax = _number((ttm_facts.get("tax_expense") or {}).get("value"), "TTM tax expense")
    if ttm_pretax == 0:
        raise TaxForecastError("TTM pretax income must be nonzero")
    payable_timing = _payable_timing_anchors(source_facts)
    historical_tax_diagnostic = _historical_tax_diagnostic(source_facts)
    return {
        "schema_version": "p8a-msft-tax-evidence-r6",
        "case": CASE,
        "information_cutoff": INFORMATION_CUTOFF,
        "measurement_date": MEASUREMENT_DATE,
        "source_table": str(table_path).replace("\\", "/"),
        "source_table_sha256": _sha256(table_path),
        "source_facts": source_facts,
        "payable_timing": payable_timing,
        "historical_tax_diagnostic": historical_tax_diagnostic,
        "opening_balances": opening_balances,
        "ttm_book_tax_rate": ttm_tax / ttm_pretax,
        "p7_dependency": {
            "decision_id": (p7.get("p7_decision") or {}).get("decision_id"),
            "decision_status": (p7.get("p7_decision") or {}).get("status"),
            "source_case_snapshot_sha256": (p7.get("packet") or {}).get("frozen_case_snapshot_sha256"),
            "p7_input_hash": content_hash(p7),
        },
        "p7_forecast": {"ebit": ebit, "periods": list(PERIODS), "period_meta": _period_meta()},
        "unavailable": [
            "Q3 FY2026 cash taxes and detailed current/deferred split are not disclosed in the selected source context.",
            "Q3 deferred-tax asset decomposition, NOL utilization timing and uncertain-tax settlement timing are unavailable.",
            "FY25 DTA detail is not substituted for the Q3 balance-sheet other-long-term-assets amount.",
        ],
    }


def _opening_balance(packet: dict[str, Any], key: str) -> float:
    value = (packet.get("opening_balances") or {}).get(key, {}).get("value")
    return _number(value, f"opening_balances.{key}")


def _p7_ebit(packet: dict[str, Any]) -> list[float]:
    candidate = (packet.get("p7_forecast") or {}).get("ebit")
    if candidate is None:
        candidate = (packet.get("forecast") or {}).get("ebit")
    return _period_array(candidate, "forecast EBIT")


def default_proposal(packet: dict[str, Any]) -> TaxProposal:
    rate = _number(packet.get("ttm_book_tax_rate"), "TTM book tax rate")
    if not 0 <= rate <= 1:
        raise TaxForecastError("TTM book tax rate is outside [0,1]")
    payable_timing = packet.get("payable_timing") or _payable_timing_anchors(packet.get("source_facts") or {})
    proposal = TaxProposal(
        outcome="propose_forecast",
        method_id=METHOD_ID,
        method_version=METHOD_VERSION,
        book_tax_rate=rate,
        operating_tax_rate=rate,
        deferred_share=[0.0] * len(PERIODS),
        current_tax_payable_method=PAYABLE_TIMING_METHOD,
        current_tax_payable_days=payable_timing["baseline_days"],
        current_tax_payable_closing=None,
        long_term_tax_settlement=[0.0] * len(PERIODS),
        dta_policy="hold_flat_no_new_recognition",
        nol_policy="no_utilization_or_refund",
        evidence_refs=["book_tax_expense", "current_tax_expense", "deferred_tax_expense", "cash_taxes_paid_net_refunds", "current_income_tax_liability", "long_term_income_tax_liability", "deferred_income_tax_liability"],
        rationale="Use the sourced TTM book-tax/pretax proxy for book and independently editable operating tax. Derive current-payable closing balances from modeled current tax expense, actual forecast-period days and the FY2025 source-anchored payable-days estimate. Hold deferred share, long-term tax liability and DTA recognition neutral while preserving the reported opening accounts.",
        alternatives=["Use the FY2024 actual-366-day source-derived payable-days anchor as a visible sensitivity.", "Use the explicit-closing-balance method with the reported opening payable held flat as a control.", "Use FY2025 or Q3 nine-month effective rate as a visible sensitivity."],
        uncertainty=["TTM effective tax is a book-tax proxy, not historical cash tax.", "Source-derived payable days are a provisional timing estimate, not a reported future payment calendar or exact cash-tax reconciliation.", "Q3 cash tax and deferred/current detail are unavailable; no missing value becomes zero.", "NOL, DTA realization and uncertain-tax settlement timing remain unresolved in the base."],
        follow_up_request="Obtain jurisdictional temporary-difference, NOL-utilization and uncertain-tax settlement schedules before modeling non-neutral tax movements.",
    )
    validate_proposal(proposal, packet)
    return proposal


def _forecast_values(packet: dict[str, Any], proposal: TaxProposal, *, interest_expense: list[float] | None = None, pretax_income: list[float] | None = None) -> dict[str, list[float]]:
    ebit = _p7_ebit(packet)
    interest = _period_array(interest_expense if interest_expense is not None else [0.0] * len(PERIODS), "interest expense")
    pretax = _period_array(pretax_income, "pretax income") if pretax_income is not None else [ebit[i] - interest[i] for i in range(len(PERIODS))]
    if proposal.current_tax_payable_method == PAYABLE_TIMING_METHOD:
        payable_days = _number(proposal.current_tax_payable_days, "current_tax_payable_days")
        if not 0 <= payable_days <= PAYABLE_DAYS_MAX:
            raise TaxForecastError("current_tax_payable_days must be within [0,365]")
        period_days = _period_days()
    elif proposal.current_tax_payable_method == EXPLICIT_PAYABLE_METHOD:
        if proposal.current_tax_payable_closing is None:
            raise TaxForecastError("explicit_closing_balance requires current tax payable closing balances")
        current_close = list(proposal.current_tax_payable_closing)
        period_days = _period_days()
    else:
        raise TaxForecastError("current-tax payable timing method is unsupported")
    book = [max(0.0, value) * proposal.book_tax_rate for value in pretax]
    deferred = [book[i] * proposal.deferred_share[i] for i in range(len(PERIODS))]
    current = [book[i] - deferred[i] for i in range(len(PERIODS))]
    current_open: list[float] = []
    if proposal.current_tax_payable_method == PAYABLE_TIMING_METHOD:
        current_close = [current[i] / period_days[i] * payable_days for i in range(len(PERIODS))]
    current_payment: list[float] = []
    lt_open: list[float] = []
    lt_close: list[float] = []
    lt_settlement = list(proposal.long_term_tax_settlement)
    dtl_open: list[float] = []
    dtl_close: list[float] = []
    for i in range(len(PERIODS)):
        current_open.append(_opening_balance(packet, "current_tax_payable") if i == 0 else current_close[i - 1])
        current_payment.append(current_open[i] + current[i] - current_close[i])
        lt_open.append(_opening_balance(packet, "long_term_tax_liability") if i == 0 else lt_close[i - 1])
        lt_close.append(lt_open[i] - lt_settlement[i])
        dtl_open.append(_opening_balance(packet, "deferred_tax_liability") if i == 0 else dtl_close[i - 1])
        dtl_close.append(dtl_open[i] + deferred[i])
    operating_tax = [max(0.0, value) * proposal.operating_tax_rate for value in ebit]
    return {
        "ebit": ebit,
        "interest_expense": interest,
        "pretax_income": pretax,
        "positive_pretax_income": [max(0.0, value) for value in pretax],
        "book_tax_expense": book,
        "deferred_tax_expense": deferred,
        "current_tax_expense": current,
        "current_tax_payable_opening": current_open,
        "current_tax_payable_closing": current_close,
        "current_tax_payable_method": [proposal.current_tax_payable_method] * len(PERIODS),
        "current_tax_payable_days": [proposal.current_tax_payable_days] * len(PERIODS) if proposal.current_tax_payable_method == PAYABLE_TIMING_METHOD else [None] * len(PERIODS),
        "period_days": period_days,
        "current_tax_payment": current_payment,
        "long_term_tax_liability_opening": lt_open,
        "long_term_tax_settlement": lt_settlement,
        "long_term_tax_liability_closing": lt_close,
        "deferred_tax_liability_opening": dtl_open,
        "deferred_tax_liability_closing": dtl_close,
        "deferred_tax_addback": deferred,
        "current_tax_payable_movement": [current_close[i] - current_open[i] for i in range(len(PERIODS))],
        "long_term_tax_settlement_cash_effect": [-value for value in lt_settlement],
        "tax_cfo_adjustment": [deferred[i] + current_close[i] - current_open[i] - lt_settlement[i] for i in range(len(PERIODS))],
        "cash_taxes": [current_payment[i] + lt_settlement[i] for i in range(len(PERIODS))],
        "operating_tax_rate": [proposal.operating_tax_rate] * len(PERIODS),
        "operating_tax_expense": operating_tax,
        "tax_status": ["PASS" if current_payment[i] >= -TOLERANCE and lt_close[i] >= -TOLERANCE and dtl_close[i] >= -TOLERANCE else "FAIL" for i in range(len(PERIODS))],
    }


def validate_proposal(proposal: TaxProposal, packet: dict[str, Any]) -> None:
    if proposal.outcome != "propose_forecast":
        reason = proposal.follow_up_request or proposal.rationale or "no forecast supplied"
        raise TaxForecastError(f"P8A declared {proposal.outcome} outcome; no forecast publication: {reason}")
    if proposal.method_id != METHOD_ID or proposal.method_version != METHOD_VERSION:
        raise TaxForecastError("P8A proposal method is unsupported")
    if proposal.book_tax_rate is None or proposal.operating_tax_rate is None:
        raise TaxForecastError("P8A tax rates are required for a forecast proposal")
    if not 0 <= proposal.book_tax_rate <= 1 or not 0 <= proposal.operating_tax_rate <= 1:
        raise TaxForecastError("P8A tax rates must be within [0,1] decimal fractions")
    if proposal.deferred_share is None or proposal.long_term_tax_settlement is None:
        raise TaxForecastError("P8A deferred share and long-term settlement are required for a forecast proposal")
    _period_array(proposal.deferred_share, "deferred_share")
    _period_array(proposal.long_term_tax_settlement, "long_term_tax_settlement")
    if any(value < -1 or value > 1 for value in proposal.deferred_share):
        raise TaxForecastError("deferred_share must stay within [-1,1]")
    if proposal.current_tax_payable_method == PAYABLE_TIMING_METHOD:
        if proposal.current_tax_payable_days is None:
            raise TaxForecastError("source_anchored_payable_days requires current_tax_payable_days")
        payable_days = _number(proposal.current_tax_payable_days, "current_tax_payable_days")
        if not 0 <= payable_days <= PAYABLE_DAYS_MAX:
            raise TaxForecastError("current_tax_payable_days must be within [0,365]")
        if proposal.current_tax_payable_closing is not None:
            raise TaxForecastError("source_anchored_payable_days cannot use explicit closing balances")
    elif proposal.current_tax_payable_method == EXPLICIT_PAYABLE_METHOD:
        if proposal.current_tax_payable_closing is None:
            raise TaxForecastError("explicit_closing_balance requires current_tax_payable_closing")
        _period_array(proposal.current_tax_payable_closing, "current_tax_payable_closing")
        if proposal.current_tax_payable_days is not None:
            raise TaxForecastError("explicit_closing_balance cannot use current_tax_payable_days")
    else:
        raise TaxForecastError("P8A current-tax payable timing method is unsupported")
    opening_current = _opening_balance(packet, "current_tax_payable")
    opening_lt = _opening_balance(packet, "long_term_tax_liability")
    opening_dtl = _opening_balance(packet, "deferred_tax_liability")
    if proposal.current_tax_payable_closing is not None and any(value < 0 for value in proposal.current_tax_payable_closing):
        raise TaxForecastError("current tax payable cannot be negative")
    if any(value < 0 for value in proposal.long_term_tax_settlement):
        raise TaxForecastError("long-term tax settlement cannot be negative")
    if sum(proposal.long_term_tax_settlement) > opening_lt + TOLERANCE:
        raise TaxForecastError("long-term tax settlement exceeds booked liability")
    preview = _forecast_values(packet, proposal)
    if any(value < -TOLERANCE for value in preview["current_tax_payment"]):
        raise TaxForecastError("unsupported negative current tax payment/refund")
    if any(value < -TOLERANCE for value in preview["long_term_tax_liability_closing"]):
        raise TaxForecastError("long-term tax settlement underflows booked liability")
    if any(value < -TOLERANCE for value in preview["deferred_tax_liability_closing"]):
        raise TaxForecastError("deferred-tax benefit underflows reported DTL; DTA creation is unsupported")
    if opening_current < 0 or opening_lt < 0 or opening_dtl < 0:
        raise TaxForecastError("reported opening tax liabilities cannot be negative")


def build_tax_model(packet: dict[str, Any], proposal: TaxProposal, review: TaxReview, *, interest_expense: list[float] | None = None, pretax_income: list[float] | None = None) -> dict[str, Any]:
    validate_proposal(proposal, packet)
    forecast = _forecast_values(packet, proposal, interest_expense=interest_expense, pretax_income=pretax_income)
    period_meta = _period_meta()
    return {
        "schema_version": "p8a-msft-tax-model-r6",
        "forecast_authority": "Mog formulas compiled by asset_model.mjs; Python arrays are diagnostic preview only",
        "periods": period_meta,
        "method": {"id": proposal.method_id, "version": proposal.method_version},
        "inputs": {
            "book_tax_rate": proposal.book_tax_rate,
            "operating_tax_rate": proposal.operating_tax_rate,
            "deferred_share": list(proposal.deferred_share),
            "current_tax_payable_method": proposal.current_tax_payable_method,
            "current_tax_payable_days": proposal.current_tax_payable_days,
            "current_tax_payable_closing": list(proposal.current_tax_payable_closing) if proposal.current_tax_payable_closing is not None else None,
            "period_days": [item["days"] for item in period_meta],
            "long_term_tax_settlement": list(proposal.long_term_tax_settlement),
            "opening_current_tax_payable": _opening_balance(packet, "current_tax_payable"),
            "opening_long_term_tax_liability": _opening_balance(packet, "long_term_tax_liability"),
            "opening_deferred_tax_liability": _opening_balance(packet, "deferred_tax_liability"),
            "dta_policy": proposal.dta_policy,
            "nol_policy": proposal.nol_policy,
            "units": {"rates": "decimal fraction", "deferred_share": "dimensionless", "current_tax_payable_days": "calendar days", "period_days": "calendar days", "current_tax_payable_closing": "USD millions", "long_term_tax_settlement": "USD millions", "balances": "USD millions"},
            "payable_timing": packet["payable_timing"],
        },
        "forecast": forecast,
        "source": {
            "source_table": packet["source_table"],
            "source_table_sha256": packet["source_table_sha256"],
            "opening_balances": packet["opening_balances"],
            "historical_facts": packet["source_facts"],
        },
        "decision": {"status": "SYSTEM_REVIEWED_PROVISIONAL" if review.verdict == "accept" else "REVIEW_REQUIRED", "review_verdict": review.verdict},
        "historical_tax_diagnostic": packet["historical_tax_diagnostic"],
        "limitations": packet["unavailable"],
    }


def review_proposal(proposal: TaxProposal, packet: dict[str, Any], authoritative: dict[str, Any] | None = None) -> TaxReview:
    try:
        validate_proposal(proposal, packet)
    except TaxForecastError as exc:
        return TaxReview(verdict="reject", evidence_strength="weak", method_valid=False, source_valid=False, period_valid=False, cash_bridge_valid=False, operating_tax_independent=False, no_double_count=False, concerns=[str(exc)], required_revision=None, target="none", rationale="P8A proposal failed deterministic validation")
    concerns = [
        "TTM effective tax is a book-tax proxy and is separately editable as the operating-tax driver.",
        "Current payable uses the selected timing method: source-derived payable days with actual forecast-period days, or an explicit closing trajectory control.",
        "Deferred share and long-term settlement are explicit trajectories; no DTA or NOL benefit is invented.",
        "Current tax, long-term tax and deferred tax remain separate from P7 working capital.",
        "Historical current-plus-deferred ties and cash-proxy residuals are diagnostics, not forecast plugs; the provisional system review is separate from human approval.",
    ]
    if authoritative is None:
        concerns.append("Authoritative Mog consequence preview is not attached.")
        strength = "mixed"
    else:
        strength = "strong"
    return TaxReview(verdict="accept", evidence_strength=strength, method_valid=True, source_valid=True, period_valid=True, cash_bridge_valid=True, operating_tax_independent=True, no_double_count=True, concerns=concerns, required_revision=None, target="none", rationale="The selected P8A bridge preserves source tax accounts and keeps operating UFCF tax independent from financing and tax-balance timing.")


def _validate_review(review: TaxReview) -> None:
    if review.verdict == "revise" and (review.target == "none" or not review.required_revision):
        raise TaxForecastError("P8A revise verdict must name one target and required revision")
    if review.verdict != "revise" and review.target != "none":
        raise TaxForecastError("P8A accept/reject verdict cannot carry revision target")


def _eligible(review: TaxReview) -> bool:
    return review.evidence_strength != "weak" and all((review.method_valid, review.source_valid, review.period_valid, review.cash_bridge_valid, review.operating_tax_independent, review.no_double_count))


def _consequential(old: TaxProposal, new: TaxProposal, target: str, packet: dict[str, Any] | None = None) -> None:
    oldv, newv = old.model_dump(mode="json"), new.model_dump(mode="json")
    if oldv == newv:
        raise TaxForecastError("P8A analyst revision returned the same proposal")
    fields = {
        "book_rate": "book_tax_rate",
        "operating_rate": "operating_tax_rate",
        "deferred_share": "deferred_share",
        "current_payable": "current_tax_payable_closing",
        "payable_timing": "current_tax_payable_days",
        "lt_settlement": "long_term_tax_settlement",
    }
    if target not in fields:
        raise TaxForecastError(f"Unsupported P8A revision target: {target}")
    if target in {"current_payable", "payable_timing"}:
        if old.current_tax_payable_method != new.current_tax_payable_method:
            active_changed = True
        elif old.current_tax_payable_method == PAYABLE_TIMING_METHOD:
            active_changed = old.current_tax_payable_days != new.current_tax_payable_days
        else:
            active_changed = old.current_tax_payable_closing != new.current_tax_payable_closing
        if not active_changed:
            raise TaxForecastError(f"P8A revision did not change active current-payable timing for {target}")
        if packet is not None:
            old_effective = _forecast_values(packet, old)["current_tax_payable_closing"]
            new_effective = _forecast_values(packet, new)["current_tax_payable_closing"]
            if not any(abs(left - right) > TOLERANCE for left, right in zip(old_effective, new_effective, strict=True)):
                raise TaxForecastError("P8A current-payable revision did not change the effective forecast target")
        return
    field = fields[target]
    if oldv[field] == newv[field]:
        raise TaxForecastError(f"P8A revision did not change {target}")


def _request(instruction: str, payload: dict[str, Any], response_model: type[BaseModel]) -> dict[str, Any]:
    schema = to_strict_json_schema(response_model)
    return {
        "model": MODEL,
        "reasoning": {"effort": REASONING_EFFORT},
        "service_tier": "default",
        "input": json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")),
        "instructions": instruction,
        "text": {"format": {"type": "json_schema", "name": "p8a_tax_review_r6" if response_model is TaxReview else "p8a_tax_proposal_r6", "strict": True, "schema": schema}},
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "tools": [],
        "background": False,
    }


def _context(packet: dict[str, Any], authoritative: dict[str, Any] | None = None) -> dict[str, Any]:
    proposal_schema = to_strict_json_schema(TaxProposal)
    review_schema = to_strict_json_schema(TaxReview)
    return {
        "schema_version": SCHEMA_VERSION,
        "proposal_schema_hash": content_hash(proposal_schema),
        "review_schema_hash": content_hash(review_schema),
        "prompt_version": PROMPT_VERSION,
        "method_catalog_version": METHOD_CATALOG_VERSION,
        "method_id": METHOD_ID,
        "method_version": METHOD_VERSION,
        "payable_timing_method_version": "r6",
        "period_basis": _period_meta(),
        "model": MODEL,
        "reasoning_effort": REASONING_EFFORT,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "endpoint": f"{BASE_URL}/responses",
        "case": CASE,
        "information_cutoff": INFORMATION_CUTOFF,
        "measurement_date": MEASUREMENT_DATE,
        "packet_hash": content_hash(packet),
        "authoritative_consequences_hash": content_hash(authoritative) if authoritative else None,
    }


def _proposal_payload(packet: dict[str, Any], context: dict[str, Any], purpose: str, candidate: TaxProposal | None = None, review: TaxReview | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "purpose": purpose,
        "packet": packet,
        "context": context,
        "required_periods": list(PERIODS),
        "contract": {
            "schema_version": SCHEMA_VERSION,
            "method_catalog_version": METHOD_CATALOG_VERSION,
            "allowed_method_ids": [METHOD_ID],
            "allowed_current_tax_payable_methods": [PAYABLE_TIMING_METHOD, EXPLICIT_PAYABLE_METHOD],
            "rates_are_decimal_fractions": True,
            "no_runtime_code": True,
            "no_human_financial_approval": True,
            "missing_is_not_zero": True,
            "loss_has_no_automatic_refund_or_dta": True,
            "units": {"rates": "decimal fraction", "deferred_share": "dimensionless", "current_tax_payable_days": "calendar days", "current_tax_payable_closing": "USD millions", "long_term_tax_settlement": "USD millions"},
            "judgment_bounds": {"deferred_share": [-1, 1], "current_tax_payable_days": [0, PAYABLE_DAYS_MAX], "current_tax_payable_closing": "nonnegative USD millions", "long_term_tax_settlement": "nonnegative and no greater than booked liability"},
            "bounded_defaults": {"deferred_share": [0.0] * len(PERIODS), "current_tax_payable_method": PAYABLE_TIMING_METHOD, "current_tax_payable_days": packet.get("payable_timing", {}).get("baseline_days"), "long_term_tax_settlement": [0.0] * len(PERIODS)},
            "timing_formula": "closing current payable = modeled current tax expense / actual forecast-period days * selected payable days",
            "timing_field_exclusivity": "source_anchored_payable_days uses current_tax_payable_days and leaves current_tax_payable_closing null; explicit_closing_balance uses the closing array and leaves days null",
            "provisional_review_standard": "Judge a source-anchored estimate and its limitations; do not require undisclosed future facts, infer zero from missing data, or confuse system review with human approval.",
        },
    }
    if candidate is not None:
        payload["candidate"] = candidate.model_dump(mode="json")
    if review is not None:
        payload["review"] = review.model_dump(mode="json")
    return payload


def _review_payload(packet: dict[str, Any], context: dict[str, Any], candidate: TaxProposal, preview: dict[str, Any], authoritative: dict[str, Any] | None = None, prior_review: TaxReview | None = None) -> dict[str, Any]:
    return {
        "purpose": "independent P8A tax review",
        "packet": packet,
        "historical_tax_diagnostic": packet.get("historical_tax_diagnostic"),
        "context": context,
        "candidate": candidate.model_dump(mode="json"),
        "forecast_preview": preview,
        "authoritative_mog": authoritative or {"status": "NOT_ATTACHED"},
        "prior_review": prior_review.model_dump(mode="json") if prior_review else None,
        "review_contract": {
            "review_only": True,
            "accept_requires_authoritative_mog": True,
            "revise_requires_one_consequential_target": True,
            "timing_revision_must_change_active_effective_forecast": True,
            "declared_unresolved_means_no_forecast_publication": True,
            "provisional_review_is_not_human_financial_approval": True,
            "historical_cash_residuals_are_diagnostics_not_plugs": True,
            "do_not_return_formulas_or_code": True,
        },
    }


def _build_authority(p7: dict[str, Any], packet: dict[str, Any], candidate: TaxProposal, review: TaxReview, authority_dir: Path) -> dict[str, Any]:
    model = copy.deepcopy(p7)
    tax = build_tax_model(packet, candidate, review)
    tax["decision"]["status"] = "REVIEW_REQUIRED"
    model["tax_packet"] = packet
    model["tax_forecast"] = tax
    model["tax_decision"] = {"proposal": candidate.model_dump(mode="json"), "review": review.model_dump(mode="json"), "status": "REVIEW_REQUIRED", "decision_id": "P8A-MSFT-TAX-PREVIEW-R6"}
    authority_dir.mkdir(parents=True, exist_ok=True)
    input_path = authority_dir / "model-input.json"
    _write_json(input_path, model)
    repo_root = Path(__file__).resolve().parents[2]
    command = ["node", "scripts/spreadsheet_compat/run-p8a.mjs", "authority", str(input_path), str(authority_dir)]
    try:
        subprocess.run(command, cwd=repo_root, check=True, capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.SubprocessError) as exc:
        _write_json(authority_dir / "mog-authority-error.json", {"error_type": type(exc).__name__, "error": str(exc), "stdout": getattr(exc, "stdout", ""), "stderr": getattr(exc, "stderr", "")})
        raise TaxForecastError(f"P8A Mog authority failed; see {authority_dir / 'mog-authority-error.json'}") from exc
    result_path = authority_dir / "tax-verification.json"
    if not result_path.exists():
        raise TaxForecastError("P8A Mog authority did not persist verification")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if result.get("status") != "PASS":
        raise TaxForecastError("P8A Mog authority verification failed")
    return result


def _terminal_outcome(
    run_dir: Path,
    packet: dict[str, Any],
    context: dict[str, Any],
    *,
    stage: str,
    status: str,
    reason: str,
    outcome: str | None = None,
    follow_up_request: str | None = None,
    candidate: TaxProposal | None = None,
) -> None:
    value: dict[str, Any] = {
        "status": status,
        "stage": stage,
        "reason": reason,
        "context_hash": content_hash(context),
        "source_packet_hash": content_hash(packet),
        "publication": "no P8A model published; prior attempt artifacts remain preserved",
    }
    if outcome is not None:
        value["outcome"] = outcome
    if follow_up_request is not None:
        value["follow_up_request"] = follow_up_request
    if candidate is not None:
        value["candidate_snapshot"] = candidate.model_dump(mode="json")
    _write_json(run_dir / "terminal-outcome.json", value)


def _declared_outcome_status(proposal: TaxProposal) -> str:
    return {
        "unresolved": "UNRESOLVED_NO_FORECAST",
        "capability_gap": "CAPABILITY_GAP_NO_FORECAST",
    }.get(proposal.outcome, "NO_FORECAST")


def prepare_live_handoff(p7: dict[str, Any], run_dir: Path, *, source_table: Path | None = None, output_path: Path | None = None, budget_path: Path | None = None) -> dict[str, Any]:
    packet = build_evidence_packet(p7, source_table)
    context = _context(packet)
    payload = _proposal_payload(packet, context, "initial analyst selection")
    request = _request(INITIAL_ANALYST_INSTRUCTION, payload, TaxProposal)
    rebuilt_request = _request(INITIAL_ANALYST_INSTRUCTION, payload, TaxProposal)
    request_path = run_dir / "attempts" / "01-analyst-initial.request.json"
    run_dir.mkdir(parents=True, exist_ok=True)
    request_path.parent.mkdir(parents=True, exist_ok=True)

    def write_or_verify(path: Path, value: Any) -> None:
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing != value:
                raise TaxForecastError(f"prepared handoff artifact differs: {path}")
            return
        _write_json(path, value)

    write_or_verify(run_dir / "run-context.json", context)
    write_or_verify(run_dir / "evidence-packet.json", packet)
    write_or_verify(request_path, request)
    command = f"$env:PYTHONPATH='src'; .\\.venv\\Scripts\\python.exe -m smrik_fund.tax_forecast --p7-model {Path('data/build-guide-p7/live-r4/model-input.json').as_posix()} --output {(output_path or run_dir / 'model-input.json').as_posix()} --run-dir {run_dir.as_posix()} --budget {(budget_path or Path('data/build-guide-api-budget.json')).as_posix()}"
    manifest = {"status": "PREPARED_NO_DISPATCH", "stage": "analyst-initial", "case": CASE, "request_path": request_path.as_posix(), "request_hash": content_hash(request), "request_rebuilt_hash": content_hash(rebuilt_request), "canonical_request_equal": request == rebuilt_request, "context_hash": content_hash(context), "payload_hash": content_hash(payload), "source_packet_hash": content_hash(packet), "settings": {"model": MODEL, "reasoning": {"effort": REASONING_EFFORT}, "service_tier": "default", "max_output_tokens": MAX_OUTPUT_TOKENS, "tools": [], "background": False}, "limits": {"max_attempts": MAX_ATTEMPTS, "max_committed_eur": MAX_COMMITTED_EUR}, "cli": command, "replay_policy": "only an exact completed request may resume; invalid, unresolved, rejected or unsettled outcomes remain held"}
    write_or_verify(run_dir / "prepared-manifest.json", manifest)
    return manifest


def run_reasoning(packet: dict[str, Any], p7: dict[str, Any], run_dir: Path, budget_path: Path, *, offline: bool = False, client: Any | None = None) -> tuple[TaxProposal, TaxReview, dict[str, Any]]:
    run_dir.mkdir(parents=True, exist_ok=True)
    context = _context(packet)
    context_path = run_dir / "run-context.json"
    if context_path.exists() and json.loads(context_path.read_text(encoding="utf-8")) != context:
        _terminal_outcome(run_dir, packet, context, stage="context", status="CONTEXT_STALE", reason="P8A run context changed; prior outputs cannot be reused")
        raise TaxForecastError("P8A run context changed; prior outputs cannot be reused")
    _write_json(context_path, context)
    _write_json(run_dir / "evidence-packet.json", packet)
    proposal: TaxProposal
    review: TaxReview
    if offline:
        proposal = default_proposal(packet)
        review = review_proposal(proposal, packet)
        status = "OFFLINE_FIXTURE"
    else:
        stage = "analyst-initial"
        final_review = None
        review = None
        terminal_outcome_written = False
        try:
            payload = _proposal_payload(packet, context, "initial analyst selection")
            request = _request(INITIAL_ANALYST_INSTRUCTION, payload, TaxProposal)
            proposal, _ = _dispatch_structured(stage=stage, run_dir=run_dir, budget_path=budget_path, instruction=INITIAL_ANALYST_INSTRUCTION, payload=payload, response_model=TaxProposal, client=client, prepared_request=request, task_id=TASK_ID, max_attempts=MAX_ATTEMPTS, max_committed_eur=MAX_COMMITTED_EUR, call_filter=_is_p8a_call)
            _write_json(run_dir / "candidate-initial.json", proposal.model_dump(mode="json"))
            if proposal.outcome != "propose_forecast":
                _terminal_outcome(run_dir, packet, context, stage=stage, status=_declared_outcome_status(proposal), reason=proposal.rationale, outcome=proposal.outcome, follow_up_request=proposal.follow_up_request, candidate=proposal)
                terminal_outcome_written = True
                raise TaxForecastError(f"P8A declared {proposal.outcome} outcome; no forecast publication")
            validate_proposal(proposal, packet)
            stage = "mog-authority-initial"
            authority = _build_authority(p7, packet, proposal, review_proposal(proposal, packet), run_dir / "mog-authority" / "analyst-initial")
            review_payload = _review_payload(packet, _context(packet, authority), proposal, authority.get("snapshot", authority), authority)
            review_request = _request(ORIGINAL_REVIEW_INSTRUCTION, review_payload, TaxReview)
            stage = "reviewer-original"
            review, _ = _dispatch_structured(stage=stage, run_dir=run_dir, budget_path=budget_path, instruction=ORIGINAL_REVIEW_INSTRUCTION, payload=review_payload, response_model=TaxReview, client=client, prepared_request=review_request, task_id=TASK_ID, max_attempts=MAX_ATTEMPTS, max_committed_eur=MAX_COMMITTED_EUR, call_filter=_is_p8a_call)
            _validate_review(review)
            _write_json(run_dir / "review-original.json", review.model_dump(mode="json"))
            if review.verdict == "revise":
                _write_json(run_dir / "revision-request.json", {"requested_by": "system_review", "target": review.target, "required_revision": review.required_revision, "prior_candidate_hash": content_hash(proposal.model_dump(mode="json")), "context_hash": content_hash(context)})
                revision_payload = _proposal_payload(packet, context, "required consequential analyst revision", proposal, review)
                revision_request = _request(REVISION_ANALYST_INSTRUCTION, revision_payload, TaxProposal)
                stage = "analyst-revision"
                revised, _ = _dispatch_structured(stage=stage, run_dir=run_dir, budget_path=budget_path, instruction=REVISION_ANALYST_INSTRUCTION, payload=revision_payload, response_model=TaxProposal, client=client, prepared_request=revision_request, task_id=TASK_ID, max_attempts=MAX_ATTEMPTS, max_committed_eur=MAX_COMMITTED_EUR, call_filter=_is_p8a_call)
                _write_json(run_dir / "candidate-revision.json", revised.model_dump(mode="json"))
                if revised.outcome != "propose_forecast":
                    _terminal_outcome(run_dir, packet, context, stage=stage, status=_declared_outcome_status(revised), reason=revised.rationale, outcome=revised.outcome, follow_up_request=revised.follow_up_request, candidate=revised)
                    terminal_outcome_written = True
                    raise TaxForecastError(f"P8A declared {revised.outcome} outcome; no forecast publication")
                validate_proposal(revised, packet)
                _consequential(proposal, revised, review.target, packet)
                stage = "mog-authority-revision"
                revision_authority = _build_authority(p7, packet, revised, review_proposal(revised, packet), run_dir / "mog-authority" / "analyst-revision")
                final_payload = _review_payload(packet, _context(packet, revision_authority), revised, revision_authority.get("snapshot", revision_authority), revision_authority, review)
                final_request = _request(REVISION_REVIEW_INSTRUCTION, final_payload, TaxReview)
                stage = "reviewer-revision"
                final_review, _ = _dispatch_structured(stage=stage, run_dir=run_dir, budget_path=budget_path, instruction=REVISION_REVIEW_INSTRUCTION, payload=final_payload, response_model=TaxReview, client=client, prepared_request=final_request, task_id=TASK_ID, max_attempts=MAX_ATTEMPTS, max_committed_eur=MAX_COMMITTED_EUR, call_filter=_is_p8a_call)
                _validate_review(final_review)
                _write_json(run_dir / "review-revision.json", final_review.model_dump(mode="json"))
                if final_review.verdict != "accept" or not _eligible(final_review):
                    raise TaxForecastError("P8A review did not accept the consequential revision")
                proposal, review, authority = revised, final_review, revision_authority
            elif review.verdict != "accept" or not _eligible(review):
                raise TaxForecastError("P8A review did not accept the policy")
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
            if not terminal_outcome_written:
                _terminal_outcome(run_dir, packet, context, stage=stage, status=failure_status, reason=str(exc))
            raise
    tax = build_tax_model(packet, proposal, review)
    tax["decision"].update({"status": status, "context_hash": content_hash(context), "source_packet_hash": content_hash(packet), "candidate_hash": content_hash(proposal.model_dump(mode="json")), "review_hash": content_hash(review.model_dump(mode="json"))})
    tax["decision"]["binding"] = {**{field: tax["decision"][field] for field in BINDING_HASH_FIELDS}, "candidate_snapshot": proposal.model_dump(mode="json"), "review_snapshot": review.model_dump(mode="json"), "source_case_snapshot_sha256": packet.get("p7_dependency", {}).get("source_case_snapshot_sha256")}
    tax["tax_decision"] = {"proposal": proposal.model_dump(mode="json"), "review": review.model_dump(mode="json"), "status": status, "binding": tax["decision"]["binding"]}
    _write_json(run_dir / "candidate.json", proposal.model_dump(mode="json"))
    _write_json(run_dir / "review.json", review.model_dump(mode="json"))
    _write_json(run_dir / "model.json", tax)
    _write_json(run_dir / "terminal-outcome.json", {"status": status, "stage": "complete", "context_hash": content_hash(context), "source_packet_hash": content_hash(packet), "publication": "P8A model published only after deterministic validation and review state handling"})
    return proposal, review, tax


def _run_cli(args: argparse.Namespace) -> None:
    p7 = json.loads(Path(args.p7_model).read_text(encoding="utf-8"))
    packet = build_evidence_packet(p7, Path(args.source_table) if args.source_table else None)
    proposal, review, tax = run_reasoning(packet, p7, Path(args.run_dir), Path(args.budget), offline=args.offline)
    output_model = copy.deepcopy(p7)
    output_model["tax_packet"] = packet
    output_model["tax_forecast"] = tax
    output_model["tax_decision"] = tax["tax_decision"]
    output_model["p8a_decision"] = {"decision_id": "P8A-MSFT-TAX-DECISION-R6", "status": tax["decision"]["status"], "human_approval": False, "review": review.model_dump(mode="json"), "binding": tax["decision"]["binding"], **{field: tax["decision"][field] for field in BINDING_HASH_FIELDS}}
    output_model["decision"] = {**(p7.get("decision") or {}), "status": tax["decision"]["status"], "p8a_status": tax["decision"]["status"], "p8a_decision_id": output_model["p8a_decision"]["decision_id"], "coverage": "P5 asset + P6 operating + P7 working capital + P8A taxes; P8B-P12 remain incomplete"}
    output_model["schema_version"] = "p8a-msft-tax-input-r6"
    _write_json(Path(args.output), output_model)
    _write_json(Path(args.run_dir) / "model-input.json", output_model)
    print(json.dumps({"status": tax["decision"]["status"], "output": str(Path(args.output)), "run_dir": str(Path(args.run_dir)), "proposal": proposal.model_dump(mode="json"), "review": review.model_dump(mode="json")}, indent=2))


def _prepare_cli(args: argparse.Namespace) -> None:
    p7 = json.loads(Path(args.p7_model).read_text(encoding="utf-8"))
    manifest = prepare_live_handoff(p7, Path(args.run_dir), source_table=Path(args.source_table) if args.source_table else None, output_path=Path(args.output), budget_path=Path(args.budget))
    print(json.dumps(manifest, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--p7-model", default="data/build-guide-p7/live-r4/model-input.json")
    parser.add_argument("--output", default="data/build-guide-p8a/model-input.json")
    parser.add_argument("--run-dir", default="data/build-guide-p8a/offline-r1")
    parser.add_argument("--budget", default="data/build-guide-api-budget.json")
    parser.add_argument("--source-table", default=None)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    if args.prepare:
        _prepare_cli(args)
    else:
        _run_cli(args)


if __name__ == "__main__":
    main()
