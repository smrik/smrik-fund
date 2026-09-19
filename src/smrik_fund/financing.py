"""P8B debt and lease financing boundary.

This module is deliberately small.  It freezes the source rows supplied by the
P8B packet, validates the selected policy, and produces the arrays consumed by
the Mog workbook builder.  The workbook remains the formula authority for the
linked three statements; the Python arrays are an offline preview and binding
input record.
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
ENDPOINT_HOST = "api.openai.com"
BASE_URL = f"https://{ENDPOINT_HOST}/v1"
ENDPOINT_URL = f"{BASE_URL}/responses"
TASK_ID = "p8b-msft-financing"
MAX_ATTEMPTS = 6
MAX_COMMITTED_EUR = 0.50
REASONING_EFFORT = "medium"
MAX_OUTPUT_TOKENS = 12_000
SCHEMA_VERSION = "p8b-financing-proposal-r2"
PROMPT_VERSION = "p8b-financing-reasoning-r5"
METHOD_CATALOG_VERSION = "p8b-financing-methods-r1"
METHOD_ID = "debt_lease_cash_rollforward"
METHOD_VERSION = "v1"
PROVENANCE_CONTRACT_VERSION = "p8b-provenance-r5"
PIPELINE_FINANCE_SHARE_REFERENCE = "source_mix_disclosed_recent_additions"
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


class FinancingError(ValueError):
    """P8B source, policy, calibration, preview, or dependency failure."""


class FinancingProposal(BaseModel):
    """Judgment fields eligible for the analyst/reviewer boundary.

    Source balances, dates, payment buckets, and calibrated rates are always
    application-owned.  The fields below describe the bounded policy selected
    for the offline implementation and eventual live review.
    """

    model_config = ConfigDict(extra="forbid")

    outcome: Literal["propose_forecast", "unresolved", "capability_gap"]
    method_id: Literal["debt_lease_cash_rollforward"] | None = None
    method_version: Literal["v1"] | None = None
    debt_coupon_rate: float | None = Field(default=None, gt=0, le=1)
    debt_refinance_policy: Literal["refinance_disclosed_maturities"] | None = None
    debt_tail_policy: Literal["hold_through_fy2036"] | None = None
    refinance_term_years: Literal[30] | None = None
    refinance_fee_rate: Literal[0.0] | None = None
    lease_bundle: Literal["operating_expense_finance_debt_like"] | None = None
    pipeline_finance_share: Literal["source_mix_disclosed_recent_additions"] | None = None
    pipeline_operating_life_years: Literal[6] | None = None
    pipeline_finance_life_years: Literal[13] | None = None
    pipeline_operating_rate: float | None = Field(default=None, gt=0, le=1)
    pipeline_finance_rate: float | None = Field(default=None, gt=0, le=1)
    pipeline_timing_policy: Literal["actual_day_weighted_fy2026_fy2031"] | None = None
    opening_finance_life_years: Literal[13] | None = None
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
        scalar_fields = (
            "debt_coupon_rate", "refinance_fee_rate",
            "pipeline_operating_rate", "pipeline_finance_rate",
            "refinance_term_years", "pipeline_operating_life_years",
            "pipeline_finance_life_years", "opening_finance_life_years",
        )
        for field in scalar_fields:
            if field not in value or value[field] is None:
                continue
            raw = value[field]
            if isinstance(raw, bool) or not isinstance(raw, int | float):
                raise ValueError(f"{field} must be numeric")
            if isinstance(raw, float) and not math.isfinite(raw):
                raise ValueError(f"{field} must be finite")
        return value

    @model_validator(mode="after")
    def _validate_shape(self) -> FinancingProposal:
        if self.outcome != "propose_forecast":
            if not self.follow_up_request:
                raise ValueError("non-forecast outcome requires follow_up_request")
            inactive_fields = (
                "method_id", "method_version", "debt_coupon_rate", "debt_refinance_policy",
                "debt_tail_policy", "refinance_term_years", "refinance_fee_rate", "lease_bundle",
                "pipeline_finance_share", "pipeline_operating_life_years", "pipeline_finance_life_years",
                "pipeline_operating_rate", "pipeline_finance_rate", "pipeline_timing_policy",
                "opening_finance_life_years",
            )
            populated = [field for field in inactive_fields if getattr(self, field) is not None]
            if populated:
                raise ValueError(f"non-forecast outcome requires inactive fields null: {', '.join(populated)}")
            return self
        required = {
            "method_id": self.method_id,
            "method_version": self.method_version,
            "debt_coupon_rate": self.debt_coupon_rate,
            "debt_refinance_policy": self.debt_refinance_policy,
            "debt_tail_policy": self.debt_tail_policy,
            "refinance_term_years": self.refinance_term_years,
            "refinance_fee_rate": self.refinance_fee_rate,
            "lease_bundle": self.lease_bundle,
            "pipeline_finance_share": self.pipeline_finance_share,
            "pipeline_operating_life_years": self.pipeline_operating_life_years,
            "pipeline_finance_life_years": self.pipeline_finance_life_years,
            "pipeline_operating_rate": self.pipeline_operating_rate,
            "pipeline_finance_rate": self.pipeline_finance_rate,
            "pipeline_timing_policy": self.pipeline_timing_policy,
            "opening_finance_life_years": self.opening_finance_life_years,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise ValueError(f"forecast proposal missing required fields: {', '.join(missing)}")
        if self.refinance_fee_rate != 0:
            raise ValueError("P8B selected policy requires zero refinance fees")
        return self


class FinancingReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["accept", "revise", "reject"]
    evidence_strength: Literal["strong", "mixed", "weak"]
    method_valid: bool
    source_valid: bool
    period_valid: bool
    debt_bridge_valid: bool
    lease_bridge_valid: bool
    cash_bridge_valid: bool
    ufcf_independent: bool
    no_double_count: bool
    funding_visible: bool
    concerns: list[str] = Field(min_length=1)
    required_revision: str | None
    target: Literal["none", "debt_policy", "lease_bundle", "pipeline", "opening_rates", "funding"]
    rationale: str = Field(min_length=1)


def _period_days(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days + 1


def period_meta() -> list[dict[str, Any]]:
    return [
        {
            "id": period,
            "start": start,
            "end": end,
            "days": _period_days(start, end),
            "year_fraction": _period_days(start, end) / 365,
        }
        for period, start, end in _PERIOD_SPANS
    ]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _calculation_implementation_hashes() -> dict[str, str]:
    """Hash the small, explicit set of files that determines P8B mechanics."""
    repo_root = Path(__file__).resolve().parents[2]
    relative_paths = (
        "src/smrik_fund/financing.py",
        "scripts/spreadsheet_compat/asset_model.mjs",
        "scripts/spreadsheet_compat/run-p8b.mjs",
    )
    hashes: dict[str, str] = {}
    for relative_path in relative_paths:
        path = repo_root / Path(*relative_path.split("/"))
        if not path.is_file():
            raise FinancingError(f"P8B calculation implementation is missing: {relative_path}")
        hashes[relative_path] = _sha256(path)
    return hashes


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _number(value: Any, name: str, *, allow_zero: bool = True) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise FinancingError(f"{name} is missing/non-numeric")
    if not allow_zero and value == 0:
        raise FinancingError(f"{name} must be nonzero")
    return float(value)


def _source_table() -> Path:
    return Path(__file__).resolve().parents[2] / "Lunacy" / "runs" / "three-statement-dcf" / "phases" / "financing" / "P8B-source-table-R1.csv"


def _read_source_table(path: Path | None = None) -> list[dict[str, str]]:
    table = path or _source_table()
    if not table.exists():
        raise FinancingError(f"P8B source table is missing: {table}")
    with table.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        extras = row.pop(None, None)  # One narrative source row contains an unquoted comma.
        if extras:
            existing = row.get("limitation", "")
            row["limitation"] = ", ".join([item.strip() for item in [existing, *extras] if item and item.strip()])
    return rows


def _p8a_accepted(p8a: dict[str, Any]) -> None:
    decision = p8a.get("p8a_decision") or p8a.get("tax_decision") or {}
    if decision.get("status") != "SYSTEM_REVIEWED_PROVISIONAL":
        raise FinancingError("P8A input is not accepted system-reviewed provisional")
    review = decision.get("review") or {}
    if review.get("verdict") not in {None, "accept"}:
        raise FinancingError("P8A input review is not accepted")
    packet = p8a.get("packet") or {}
    binding = decision.get("binding") or {}
    if binding.get("source_case_snapshot_sha256") and binding["source_case_snapshot_sha256"] != packet.get("frozen_case_snapshot_sha256"):
        raise FinancingError("P8A source-case binding is stale")


def _row_map(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    return {(row.get("line_item", ""), row.get("period", "")): row for row in rows}


def _value(row: dict[str, str] | None, name: str) -> float:
    if not row:
        raise FinancingError(f"P8B source row is missing: {name}")
    raw = row.get("reported_value", "")
    if raw is None or not str(raw).strip():
        raise FinancingError(f"P8B source value is missing: {name}")
    try:
        number = float(raw)
    except (TypeError, ValueError) as exc:
        raise FinancingError(f"P8B source value is nonnumeric: {name}") from exc
    if not math.isfinite(number):
        raise FinancingError(f"P8B source value is nonfinite: {name}")
    return number


def _parse_schedule(raw: str, prefix: str) -> list[float]:
    if not raw:
        raise FinancingError(f"P8B {prefix} schedule is missing")
    start = f"{prefix}="
    start_index = raw.find(start)
    if start_index < 0:
        raise FinancingError(f"P8B {prefix} schedule is missing")
    value = raw[start_index + len(start):]
    for next_prefix in (";finance_payments=", ";operating_imputed_interest=", ";finance_imputed_interest=", "|finance_payments=", "|operating_imputed_interest=", "|finance_imputed_interest="):
        if next_prefix in value:
            value = value.split(next_prefix, 1)[0]
            break
    if value is None:
        raise FinancingError(f"P8B {prefix} schedule is missing")
    try:
        parsed = [float(item) for item in value.split("|")]
    except ValueError as exc:
        raise FinancingError(f"P8B {prefix} schedule is nonnumeric") from exc
    if not parsed or any(not math.isfinite(item) or item < 0 for item in parsed):
        raise FinancingError(f"P8B {prefix} schedule is invalid")
    return parsed


def _parse_named_values(raw: str, name: str) -> dict[str, float]:
    if not raw:
        raise FinancingError(f"P8B {name} source value is missing")
    values: dict[str, float] = {}
    for token in raw.replace("|", ";").split(";"):
        if not token.strip():
            continue
        key, separator, value = token.partition("=")
        if not separator or not key.strip() or not value.strip():
            raise FinancingError(f"P8B {name} source value is malformed")
        try:
            number = float(value.rstrip("%y"))
            if value.rstrip("%y") != value and value.endswith("%"):
                number /= 100
        except ValueError as exc:
            raise FinancingError(f"P8B {name} source value is nonnumeric") from exc
        if not math.isfinite(number):
            raise FinancingError(f"P8B {name} source value is nonfinite")
        values[key.strip()] = number
    if not values:
        raise FinancingError(f"P8B {name} source value is empty")
    return values


def build_evidence_packet(p8a: dict[str, Any], source_table: Path | None = None) -> dict[str, Any]:
    """Freeze P8B source rows and the exact accepted P8A dependency."""
    _p8a_accepted(p8a)
    table_path = source_table or _source_table()
    rows = _read_source_table(table_path)
    if len(rows) != 84:
        raise FinancingError(f"P8B source table expected 84 rows, got {len(rows)}")
    by_key = _row_map(rows)
    q3 = "Q3 FY2026"
    q3_9m = "Q3 FY2026 9m"
    required = {
        "debt_face_value": q3,
        "total_debt_net": q3,
        "debt_contra_components": q3,
        "debt_maturity_schedule": q3,
        "lease_term_discount_rate": q3,
        "current_portion_long_term_debt": q3,
        "long_term_debt": q3,
        "operating_lease_rou_asset": q3,
        "operating_lease_total_liability": q3,
        "operating_lease_current_liability": q3,
        "operating_lease_noncurrent_liability": q3,
        "finance_lease_ppe_net": q3,
        "finance_lease_total_liability": q3,
        "finance_lease_current_liability": q3,
        "finance_lease_noncurrent_liability": q3,
        "operating_lease_cost": q3_9m,
        "cash_paid_operating_leases": q3_9m,
        "cash_paid_finance_lease_operating": q3_9m,
        "cash_paid_finance_lease_financing": q3_9m,
        "noncash_operating_lease_rou_additions": q3_9m,
        "noncash_finance_lease_rou_additions": q3_9m,
        "lease_maturity_schedule": q3,
        "uncommenced_lease_commitments": q3,
        "consolidated_ppe_net": q3,
    }
    for line_item, period in required.items():
        if (line_item, period) not in by_key:
            raise FinancingError(f"P8B required source row is missing: {line_item}.{period}")
    debt_face = _value(by_key[("debt_face_value", q3)], "debt_face_value.Q3 FY2026")
    debt_carrying = _value(by_key[("total_debt_net", q3)], "total_debt_net.Q3 FY2026")
    debt_current = _value(by_key[("current_portion_long_term_debt", q3)], "current_portion_long_term_debt.Q3 FY2026")
    debt_noncurrent = _value(by_key[("long_term_debt", q3)], "long_term_debt.Q3 FY2026")
    if abs(debt_face - 46156) > TOLERANCE or abs(debt_carrying - 40262) > TOLERANCE:
        raise FinancingError("P8B opening debt source identity changed")
    contra = _parse_named_values(by_key[("debt_contra_components", q3)]["reported_value"], "debt contra components")
    expected_contra = {"discount_and_issuance_costs", "hedge_fv_adjustment", "premium_on_debt_exchange"}
    if set(contra) != expected_contra or any(value > 0 for value in contra.values()):
        raise FinancingError("P8B debt contra components are not the expected signed source rows")
    if abs(debt_face + sum(contra.values()) - debt_carrying) > TOLERANCE:
        raise FinancingError("P8B debt face/contra/carrying identity failed")
    if abs(debt_current + debt_noncurrent - debt_carrying) > TOLERANCE:
        raise FinancingError("P8B debt current/noncurrent containment failed")
    operating_current = _value(by_key[("operating_lease_current_liability", q3)], "operating_lease_current_liability.Q3 FY2026")
    operating_noncurrent = _value(by_key[("operating_lease_noncurrent_liability", q3)], "operating_lease_noncurrent_liability.Q3 FY2026")
    operating_liability = _value(by_key[("operating_lease_total_liability", q3)], "operating_lease_total_liability.Q3 FY2026")
    finance_current = _value(by_key[("finance_lease_current_liability", q3)], "finance_lease_current_liability.Q3 FY2026")
    finance_noncurrent = _value(by_key[("finance_lease_noncurrent_liability", q3)], "finance_lease_noncurrent_liability.Q3 FY2026")
    finance_liability = _value(by_key[("finance_lease_total_liability", q3)], "finance_lease_total_liability.Q3 FY2026")
    if abs(operating_current + operating_noncurrent - operating_liability) > TOLERANCE:
        raise FinancingError("P8B operating lease liability containment failed")
    if abs(finance_current + finance_noncurrent - finance_liability) > TOLERANCE:
        raise FinancingError("P8B finance lease liability containment failed")
    consolidated_ppe = _value(by_key[("consolidated_ppe_net", q3)], "consolidated_ppe_net.Q3 FY2026")
    finance_ppe = _value(by_key[("finance_lease_ppe_net", q3)], "finance_lease_ppe_net.Q3 FY2026")
    if finance_ppe > consolidated_ppe + TOLERANCE:
        raise FinancingError("P8B finance lease PP&E exceeds consolidated PP&E")
    maturity = _parse_named_values(by_key[("debt_maturity_schedule", q3)]["reported_value"], "debt maturity schedule")
    maturity_total = maturity.get("total")
    maturity_buckets = [maturity.get("2026_remainder"), maturity.get("2027"), maturity.get("2028"), maturity.get("2029"), maturity.get("2030"), maturity.get("thereafter")]
    if maturity_total is None or any(value is None or value < 0 for value in maturity_buckets) or abs(sum(maturity_buckets) - maturity_total) > TOLERANCE or abs(maturity_total - debt_face) > TOLERANCE:
        raise FinancingError("P8B debt maturity source identity failed")
    lease_terms = _parse_named_values(by_key[("lease_term_discount_rate", q3)]["reported_value"], "lease term and discount rate")
    if (
        lease_terms.get("operating_term") != 6
        or lease_terms.get("finance_term") != 13
        or abs(lease_terms.get("operating_discount", float("nan")) - 0.036) > TOLERANCE
        or abs(lease_terms.get("finance_discount", float("nan")) - 0.044) > TOLERANCE
    ):
        raise FinancingError("P8B lease term/rate source anchors changed")
    lease_schedule = by_key[("lease_maturity_schedule", q3)]["reported_value"]
    op_payment = _parse_schedule(lease_schedule, "operating_payments")
    fin_payment = _parse_schedule(lease_schedule, "finance_payments")
    if len(op_payment) != 6 or len(fin_payment) != 6:
        raise FinancingError("P8B lease maturity schedules must contain five buckets plus thereafter")
    packet = {
        "packet_id": "P8B-FINANCING-SOURCE-PACKET-R1",
        "case": CASE,
        "information_cutoff": INFORMATION_CUTOFF,
        "measurement_date": MEASUREMENT_DATE,
        "source_table": table_path.as_posix(),
        "source_table_sha256": _sha256(table_path),
        "source_row_count": len(rows),
        "accepted_upstream": {
            "path": "data/build-guide-p8a/live-r5/model-input.json",
            "schema_version": p8a.get("schema_version"),
            "source_case_snapshot_sha256": (p8a.get("p8a_decision") or {}).get("binding", {}).get("source_case_snapshot_sha256") or (p8a.get("packet") or {}).get("frozen_case_snapshot_sha256"),
            "model_sha256": content_hash(p8a),
        },
        "facts": {
            "debt": {
                "face": debt_face,
                "carrying": debt_carrying,
                "fair_value": 36600.0,
                "current": debt_current,
                "noncurrent": debt_noncurrent,
                "contra": contra,
                "maturities": {"FY2027": maturity["2027"], "FY2029": maturity["2029"], "thereafter": maturity["thereafter"]},
                "coupon_proxy": 0.045,
                "fair_value_source": "Note 9; Q3 FY2026; Level 2; source value distinct from book carrying value",
            },
            "operating_lease": {
                "rou": _value(by_key[("operating_lease_rou_asset", q3)], "operating_lease_rou_asset.Q3 FY2026"),
                "liability": operating_liability,
                "current_liability": operating_current,
                "noncurrent_liability": operating_noncurrent,
                "payments": op_payment,
                "book_cost": 27020.0,
                "disclosed_weighted_rate": lease_terms["operating_discount"],
                "disclosed_weighted_term_years": int(lease_terms["operating_term"]),
                "embedded_cost_latest_ytd": _value(by_key[("operating_lease_cost", q3_9m)], "operating_lease_cost.Q3 FY2026 9m"),
                "embedded_cost_proxy": _value(by_key[("operating_lease_cost", q3_9m)], "operating_lease_cost.Q3 FY2026 9m") * 4 / 3,
                "embedded_cost_proxy_basis": "annualized Q3 FY2026 nine-month disclosed operating lease cost; comparable TTM unavailable",
            },
            "finance_lease": {
                "ppe_net": finance_ppe,
                "liability": finance_liability,
                "current_liability": finance_current,
                "noncurrent_liability": finance_noncurrent,
                "payments": fin_payment,
                "disclosed_weighted_rate": lease_terms["finance_discount"],
                "disclosed_weighted_term_years": int(lease_terms["finance_term"]),
                "noncash_additions_latest_ytd": _value(by_key[("noncash_finance_lease_rou_additions", q3_9m)], "noncash_finance_lease_rou_additions.Q3 FY2026 9m"),
            },
            "pipeline": {
                "undiscounted_commitments": _value(by_key[("uncommenced_lease_commitments", q3)], "uncommenced_lease_commitments.Q3 FY2026"),
                "cohort_periods": ["FY2026_STUB", "FY2027", "FY2028", "FY2029", "FY2030", "FY2031"],
                "finance_share_source": _value(by_key[("noncash_finance_lease_rou_additions", q3_9m)], "noncash_finance_lease_rou_additions.Q3 FY2026 9m") / (_value(by_key[("noncash_finance_lease_rou_additions", q3_9m)], "noncash_finance_lease_rou_additions.Q3 FY2026 9m") + _value(by_key[("noncash_operating_lease_rou_additions", q3_9m)], "noncash_operating_lease_rou_additions.Q3 FY2026 9m")),
                "operating_share_source": _value(by_key[("noncash_operating_lease_rou_additions", q3_9m)], "noncash_operating_lease_rou_additions.Q3 FY2026 9m") / (_value(by_key[("noncash_finance_lease_rou_additions", q3_9m)], "noncash_finance_lease_rou_additions.Q3 FY2026 9m") + _value(by_key[("noncash_operating_lease_rou_additions", q3_9m)], "noncash_operating_lease_rou_additions.Q3 FY2026 9m")),
                "finance_additions_source": _value(by_key[("noncash_finance_lease_rou_additions", q3_9m)], "noncash_finance_lease_rou_additions.Q3 FY2026 9m"),
                "operating_additions_source": _value(by_key[("noncash_operating_lease_rou_additions", q3_9m)], "noncash_operating_lease_rou_additions.Q3 FY2026 9m"),
            },
        },
        "source_rows": rows,
        "limitations": [
            "Debt thereafter timing is unresolved; base holds 34,890 face through FY2036 and exposes a FY2031-FY2036 runoff scenario.",
            "Opening lease payment buckets are aggregate disclosed estimates; portfolio timing/rate calibration is not tranche effective interest.",
            "Operating lease cost proxy annualizes the latest nine-month disclosure because compatible TTM cost is unavailable; variable and short-term costs remain embedded.",
            "The 196,600 signed pipeline is undiscounted; split, cohort timing, terms and rates are explicit estimates.",
        ],
    }
    return packet


def _elapsed_years(start: date, end: date) -> float:
    return (end - start).days / 365


def calibrate_rate(payments: list[float], dates: list[str], liability: float, *, lower: float = 0.0, upper: float = 0.25) -> float:
    """Solve PV(cash, rate) = liability by a bounded bisection."""
    if not payments or len(payments) != len(dates):
        raise FinancingError("calibration cash and date arrays must have equal nonzero length")
    liability = _number(liability, "calibration liability", allow_zero=False)
    parsed_dates = [date.fromisoformat(item) for item in dates]
    if any(value <= date.fromisoformat(MEASUREMENT_DATE) for value in parsed_dates):
        raise FinancingError("calibration payment dates must be after measurement date")

    def pv(rate: float) -> float:
        return sum(amount / (1 + rate) ** _elapsed_years(date.fromisoformat(MEASUREMENT_DATE), when) for amount, when in zip(payments, parsed_dates, strict=True))

    target = liability
    if pv(lower) < target - 1e-7 or pv(upper) > target + 1e-7:
        raise FinancingError("calibration target is outside bounded rate interval")
    low, high = lower, upper
    for _ in range(120):
        mid = (low + high) / 2
        if pv(mid) > target:
            low = mid
        else:
            high = mid
    result = (low + high) / 2
    if abs(pv(result) - target) > 1e-7:
        raise FinancingError("calibration did not converge")
    return result


def _opening_payment_dates(pool: str) -> list[str]:
    if pool == "operating":
        return [item[2] for item in _PERIOD_SPANS]  # FY2026-FY2036, six tail buckets already supplied by packet
    if pool == "finance":
        return [item[2] for item in _PERIOD_SPANS] + [
            "2036-06-30", "2037-06-30", "2038-06-30", "2039-06-30",
            "2040-06-30",
        ]
    raise FinancingError(f"unknown opening lease pool: {pool}")


def _opening_schedule(pool: str, packet: dict[str, Any]) -> tuple[list[float], list[str]]:
    values = packet["facts"][f"{pool}_lease"]["payments"]
    if pool == "operating":
        dates = [item[2] for item in _PERIOD_SPANS]
        amounts = values[:5] + [values[5] / 6] * 6
    else:
        dates = [item[2] for item in _PERIOD_SPANS] + [f"{year}-06-30" for year in range(2037, 2041)]
        amounts = values[:5] + [values[5] / 10] * 10
    if len(amounts) != len(dates):
        raise FinancingError(f"{pool} opening schedule shape is invalid")
    return amounts, dates


def default_proposal(packet: dict[str, Any]) -> FinancingProposal:
    return FinancingProposal(
        outcome="propose_forecast",
        method_id=METHOD_ID,
        method_version=METHOD_VERSION,
        debt_coupon_rate=0.045,
        debt_refinance_policy="refinance_disclosed_maturities",
        debt_tail_policy="hold_through_fy2036",
        refinance_term_years=30,
        refinance_fee_rate=0.0,
        lease_bundle="operating_expense_finance_debt_like",
        pipeline_finance_share=PIPELINE_FINANCE_SHARE_REFERENCE,
        pipeline_operating_life_years=6,
        pipeline_finance_life_years=13,
        pipeline_operating_rate=0.036,
        pipeline_finance_rate=0.044,
        pipeline_timing_policy="actual_day_weighted_fy2026_fy2031",
        opening_finance_life_years=13,
        evidence_refs=["P8B-source-table-R1", "P8B_POLICY.md", "P8B_PARENT_ORACLE.md"],
        rationale="Use the selected bounded debt/refinancing, bundle-A lease, and signed-pipeline policy while preserving source balances and unresolved tail timing.",
        alternatives=["FY2031-FY2036 no-refinancing debt tail runoff", "50% and 90% pipeline finance-share sensitivities", "10/16-year opening finance-asset service life"],
        uncertainty=["Debt thereafter bucket timing is unresolved", "Opening pool rates are aggregate PV calibrations", "Pipeline split, terms and rates are estimates"],
        follow_up_request=None,
    )


def _period_end_dates() -> list[str]:
    return [item[2] for item in _PERIOD_SPANS]


def _days_to_period_start() -> list[int]:
    measurement = date.fromisoformat(MEASUREMENT_DATE)
    return [(date.fromisoformat(item[1]) - measurement).days for item in _PERIOD_SPANS]


def _pro_rata(original: float, redeemed: float, opening_face: float) -> float:
    return original * redeemed / opening_face if opening_face else 0.0


def _resolved_pipeline_finance_share(proposal: FinancingProposal, packet: dict[str, Any]) -> float:
    """Resolve the application-owned source-mix reference for calculation."""
    if proposal.pipeline_finance_share != PIPELINE_FINANCE_SHARE_REFERENCE:
        raise FinancingError("pipeline finance share must use the supported source-mix reference")
    pipeline = packet["facts"]["pipeline"]
    finance_additions = _number(pipeline["finance_additions_source"], "pipeline finance additions source", allow_zero=False)
    operating_additions = _number(pipeline["operating_additions_source"], "pipeline operating additions source", allow_zero=False)
    denominator = finance_additions + operating_additions
    if denominator <= 0:
        raise FinancingError("pipeline source-mix denominator must be positive")
    share = finance_additions / denominator
    source_share = _number(pipeline["finance_share_source"], "pipeline finance share source")
    if abs(source_share - share) > TOLERANCE:
        raise FinancingError("pipeline finance share source identity failed")
    if not 0 <= share <= 1:
        raise FinancingError("pipeline finance share source is outside [0, 1]")
    return share


def _debt_schedule(packet: dict[str, Any], proposal: FinancingProposal, *, tail_policy: str | None = None) -> dict[str, Any]:
    fact = packet["facts"]["debt"]
    dates = _period_end_dates()
    days = [item["days"] for item in period_meta()]
    redemptions = [0.0, 9250.0, 0.0, 2016.0, 0.0, *([0.0] * 6)]
    selected_tail_policy = tail_policy or proposal.debt_tail_policy
    if selected_tail_policy == "runoff_fy2031_fy2036":
        tail = fact["maturities"]["thereafter"] / 6
        redemptions[5:] = [tail] * 6
    # Only the disclosed FY2027/FY2029 maturities refinance.  The selected
    # tail alternative is explicitly a no-refinancing liquidity scenario.
    proceeds = [0.0] * len(redemptions)
    if proposal.debt_refinance_policy == "refinance_disclosed_maturities":
        proceeds[1] = redemptions[1]
        proceeds[3] = redemptions[3]
    opening_original, closing_original, new_opening, new_closing = [], [], [], []
    original_face = fact["face"]
    new_face = 0.0
    interest, contra_open, contra_release, contra_close = [], [], [], []
    carrying_close, current_face, current_contra, current_carrying, noncurrent_carrying = [], [], [], [], []
    original_contra = sum(fact["contra"].values())
    for index, (_period, day_count) in enumerate(zip(PERIODS, days, strict=True)):
        opening_original.append(original_face)
        new_opening.append(new_face)
        opening_total = original_face + new_face
        interest.append(opening_total * proposal.debt_coupon_rate * day_count / 365)
        redeemed = min(redemptions[index], original_face)
        contra_open.append(original_contra)
        release = _pro_rata(original_contra, redeemed, original_face)
        contra_release.append(-release)
        original_contra -= release
        original_face -= redeemed
        new_face += proceeds[index]
        closing_original.append(original_face)
        new_closing.append(new_face)
        contra_close.append(original_contra)
        carrying_close.append(original_face + new_face + original_contra)
        opening_face = max(original_face, 0.0)
        next_due = redemptions[index + 1] if index + 1 < len(redemptions) else 0.0
        current_face.append(next_due)
        current_contra.append(original_contra * next_due / opening_face if opening_face else 0.0)
        current_carrying.append(next_due + current_contra[-1])
        noncurrent_carrying.append(carrying_close[-1] - current_carrying[-1])
    return {
        "periods": list(PERIODS),
        "period_end_dates": dates,
        "opening_original_face": opening_original,
        "original_face_redemption": redemptions,
        "closing_original_face": closing_original,
        "opening_new_face": new_opening,
        "new_face_proceeds": proceeds,
        "closing_new_face": new_closing,
        "opening_face": [a + b for a, b in zip(opening_original, new_opening, strict=True)],
        "closing_face": [a + b for a, b in zip(closing_original, new_closing, strict=True)],
        "cash_interest": interest,
        "opening_contra": contra_open,
        "contra_release_expense": contra_release,
        "closing_contra": contra_close,
        "closing_carrying": carrying_close,
        "current_face_due_next_12_months": current_face,
        "current_contra": current_contra,
        "current_carrying": current_carrying,
        "noncurrent_carrying": noncurrent_carrying,
        "cash_repayment": redemptions,
        "cash_proceeds": proceeds,
        "net_financing_cash": [proceeds[i] - redemptions[i] for i in range(len(PERIODS))],
        "book_financing_expense": [interest[i] + contra_release[i] for i in range(len(PERIODS))],
        "fair_value_claim_once": fact["fair_value"],
        "tail_policy": selected_tail_policy,
    }


def _pool_schedule(pool: str, packet: dict[str, Any], rate: float, *, life_years: int) -> dict[str, Any]:
    amounts, dates = _opening_schedule(pool, packet)
    liability = packet["facts"][f"{pool}_lease"]["liability"]
    calibrated = calibrate_rate(amounts, dates, liability)
    measurement = date.fromisoformat(MEASUREMENT_DATE)
    visible_dates = _period_end_dates()
    opening, interest, payment, principal, closing = [], [], [], [], []
    for index, period_date in enumerate(visible_dates):
        opening_value = liability if index == 0 else closing[-1]
        elapsed = _elapsed_years(measurement if index == 0 else date.fromisoformat(visible_dates[index - 1]), date.fromisoformat(period_date))
        interest_value = opening_value * ((1 + calibrated) ** elapsed - 1)
        payment_value = amounts[index]
        principal_value = payment_value - interest_value
        closing_value = opening_value + interest_value - payment_value
        if closing_value < -1e-6:
            raise FinancingError(f"{pool} opening liability becomes negative in {PERIODS[index]}")
        opening.append(opening_value)
        interest.append(interest_value)
        payment.append(payment_value)
        principal.append(principal_value)
        closing.append(closing_value)
    # Continue the opening schedules beyond the visible horizon so an unpaid
    # thereafter bucket cannot disappear at FY2036.
    runoff_dates = dates
    runoff_opening = liability
    runoff = []
    previous = measurement
    for amount, period_date in zip(amounts, runoff_dates, strict=True):
        when = date.fromisoformat(period_date)
        elapsed = _elapsed_years(previous, when)
        accretion = runoff_opening * ((1 + calibrated) ** elapsed - 1)
        close = runoff_opening + accretion - amount
        runoff.append({"date": period_date, "opening": runoff_opening, "interest": accretion, "payment": amount, "principal": amount - accretion, "closing": close})
        runoff_opening = close
        previous = when
    if abs(runoff[-1]["closing"]) > 1e-5:
        raise FinancingError(f"{pool} opening runoff does not fully settle: {runoff[-1]['closing']}")
    book_cost = packet["facts"]["operating_lease"]["book_cost"] if pool == "operating" else None
    expense = []
    amortization = []
    rou = []
    if pool == "operating":
        rou_opening = packet["facts"]["operating_lease"]["rou"]
        total = sum(amounts)
        for index, pay in enumerate(payment):
            service_expense = book_cost * pay / total
            amort = service_expense - interest[index]
            rou_close = rou_opening - amort
            if rou_close < -1e-6:
                raise FinancingError(f"operating opening ROU becomes negative in {PERIODS[index]}")
            expense.append(service_expense)
            amortization.append(amort)
            rou.append(rou_close)
            rou_opening = rou_close
    else:
        ppe = packet["facts"]["finance_lease"]["ppe_net"]
        asset_opening = ppe
        for index in range(len(payment)):
            dep = min(asset_opening, ppe / life_years * (period_meta()[index]["days"] / 365))
            asset_opening -= dep
            expense.append(dep)
            amortization.append(0.0)
            rou.append(asset_opening)
    if pool == "operating" and abs(rou[-1]) > 1e-5:
        raise FinancingError(f"{pool} opening ROU runoff does not fully settle: {rou[-1]}")
    return {
        "pool": pool,
        "payments": amounts,
        "payment_dates": dates,
        "calibrated_rate": calibrated,
        "input_rate_argument": rate,
        "opening_liability": opening,
        "interest": interest,
        "payment": payment,
        "principal": principal,
        "closing_liability": closing,
        "expense": expense,
        "amortization": amortization,
        "closing_asset": rou,
        "full_runoff": runoff,
        "full_runoff_final_closing": runoff[-1]["closing"],
        "disclosed_weighted_rate": packet["facts"][f"{pool}_lease"]["disclosed_weighted_rate"],
        "service_life_years": life_years,
    }


def _pipeline_schedule(
    packet: dict[str, Any],
    proposal: FinancingProposal,
    *,
    weights: list[float] | None = None,
    finance_share: float | None = None,
) -> dict[str, Any]:
    pipeline = packet["facts"]["pipeline"]
    total = pipeline["undiscounted_commitments"]
    spans = period_meta()[:6]
    span_days = [item["days"] for item in spans]
    if weights is None:
        weights = [days / sum(span_days) for days in span_days]
    if len(weights) != len(spans) or any(not math.isfinite(value) or value < 0 for value in weights):
        raise FinancingError("pipeline cohort weights are invalid")
    weight_total = sum(weights)
    if weight_total <= 0:
        raise FinancingError("pipeline cohort weights must have a positive total")
    weights = [value / weight_total for value in weights]
    if finance_share is None:
        finance_share = _resolved_pipeline_finance_share(proposal, packet)
    elif isinstance(finance_share, bool) or not isinstance(finance_share, int | float) or not math.isfinite(finance_share) or not 0 <= finance_share <= 1:
        raise FinancingError("pipeline finance share sensitivity is outside [0, 1]")
    finance_share = float(finance_share)
    op_share = 1 - finance_share
    cohort_totals = [total * weight for weight in weights]
    cohorts = []
    horizon_dates = [item["end"] for item in spans]
    for _index, (period, commitment, commencement) in enumerate(zip([item["id"] for item in spans], cohort_totals, horizon_dates, strict=True)):
        row: dict[str, Any] = {"period": period, "commencement": commencement, "commitment": commitment}
        for kind, share, term, rate in (
            ("operating", op_share, proposal.pipeline_operating_life_years, proposal.pipeline_operating_rate),
            ("finance", finance_share, proposal.pipeline_finance_life_years, proposal.pipeline_finance_rate),
        ):
            nominal = commitment * share
            annual = nominal / term
            payments = []
            dates = []
            commencement_date = date.fromisoformat(commencement)
            for years in range(1, term + 1):
                when = date(commencement_date.year + years, commencement_date.month, commencement_date.day)
                dates.append(when.isoformat())
                payments.append(annual)
            pv = sum(amount / (1 + rate) ** _elapsed_years(commencement_date, date.fromisoformat(when)) for amount, when in zip(payments, dates, strict=True))
            flows = []
            liability_opening = pv
            previous_date = commencement_date
            for amount, when in zip(payments, dates, strict=True):
                payment_date = date.fromisoformat(when)
                elapsed = _elapsed_years(previous_date, payment_date)
                interest_amount = liability_opening * ((1 + rate) ** elapsed - 1)
                principal_amount = amount - interest_amount
                liability_closing = liability_opening + interest_amount - amount
                if liability_closing < -1e-6:
                    raise FinancingError(f"pipeline {kind} cohort becomes negative on {when}")
                flows.append({"date": when, "opening": liability_opening, "payment": amount, "interest": interest_amount, "principal": principal_amount, "closing": liability_closing})
                liability_opening = liability_closing
                previous_date = payment_date
            row[kind] = {
                "commitment": nominal,
                "annual_payment": annual,
                "payments": payments,
                "payment_dates": dates,
                "flows": flows,
                "initial_pv": pv,
                "rate": rate,
                "term_years": term,
                "expense": annual if kind == "operating" else 0.0,
                "depreciation": pv / term if kind == "finance" else 0.0,
            }
        cohorts.append(row)
    visible = []
    for index, period in enumerate(PERIODS):
        end = date.fromisoformat(_period_end_dates()[index])
        op_add = sum(row["operating"]["initial_pv"] for row in cohorts if row["period"] == period)
        fin_add = sum(row["finance"]["initial_pv"] for row in cohorts if row["period"] == period)
        op_payment = 0.0
        fin_payment = 0.0
        op_interest = 0.0
        fin_interest = 0.0
        op_principal = 0.0
        fin_principal = 0.0
        op_expense = 0.0
        fin_dep = 0.0
        for row in cohorts:
            for kind, _pay_key, _exp_key in (("operating", "op_payment", "op_expense"), ("finance", "fin_payment", "fin_dep")):
                lease = row[kind]
                for flow in lease["flows"]:
                    when = flow["date"]
                    if date.fromisoformat(when).year == end.year and date.fromisoformat(when) <= end:
                        if kind == "operating":
                            op_payment += flow["payment"]
                        else:
                            fin_payment += flow["payment"]
                        if kind == "operating":
                            op_interest += flow["interest"]
                            op_principal += flow["principal"]
                        else:
                            fin_interest += flow["interest"]
                            fin_principal += flow["principal"]
                # End-period commencement means no current-period service.
                # Service runs only through the cohort's final contractual
                # service/payment date; later visible periods carry no charge.
                if date.fromisoformat(row["commencement"]) < end:
                    if kind == "operating":
                        if end <= date.fromisoformat(lease["payment_dates"][-1]):
                            op_expense += lease["expense"]
                    else:
                        if end <= date.fromisoformat(lease["payment_dates"][-1]):
                            fin_dep += lease["depreciation"]
        visible.append({"period": period, "operating_additions": op_add, "finance_additions": fin_add, "operating_payment": op_payment, "finance_payment": fin_payment, "operating_interest": op_interest, "finance_interest": fin_interest, "operating_principal": op_principal, "finance_principal": fin_principal, "operating_expense": op_expense, "finance_depreciation": fin_dep})
    return {
        "undiscounted_commitments": total,
        "weights": weights,
        "cohort_totals": cohort_totals,
        "finance_share": finance_share,
        "operating_share": op_share,
        "cohorts": cohorts,
        "visible": visible,
        "runoff_end_dates": sorted({when for row in cohorts for kind in ("operating", "finance") for when in row[kind]["payment_dates"]}),
    }


def _pipeline_sensitivities(
    packet: dict[str, Any],
    proposal: FinancingProposal,
    base: dict[str, Any],
) -> dict[str, Any]:
    """Expose bounded timing, split and new-rate alternatives without changing base inputs."""
    base_weights = base["weights"]
    variants = [
        ("finance_share_50pct", {"pipeline_finance_share": 0.50}, base_weights),
        ("finance_share_90pct", {"pipeline_finance_share": 0.90}, base_weights),
        ("front_loaded_commencement", {}, [1.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
        ("back_loaded_commencement", {}, [0.0, 0.0, 0.0, 0.0, 0.0, 1.0]),
        (
            "new_rates_minus_100bp",
            {
                "pipeline_operating_rate": proposal.pipeline_operating_rate - 0.01,
                "pipeline_finance_rate": proposal.pipeline_finance_rate - 0.01,
            },
            base_weights,
        ),
        (
            "new_rates_plus_100bp",
            {
                "pipeline_operating_rate": proposal.pipeline_operating_rate + 0.01,
                "pipeline_finance_rate": proposal.pipeline_finance_rate + 0.01,
            },
            base_weights,
        ),
    ]
    results = []
    for name, updates, variant_weights in variants:
        share_override = updates.get("pipeline_finance_share")
        variant = proposal.model_copy(update={key: value for key, value in updates.items() if key != "pipeline_finance_share"})
        schedule = _pipeline_schedule(packet, variant, weights=variant_weights, finance_share=share_override)
        visible = schedule["visible"]
        results.append(
            {
                "name": name,
                "weights": schedule["weights"],
                "finance_share": schedule["finance_share"],
                "operating_rate": variant.pipeline_operating_rate,
                "finance_rate": variant.pipeline_finance_rate,
                "operating_additions": [item["operating_additions"] for item in visible],
                "finance_additions": [item["finance_additions"] for item in visible],
                "operating_expense": [item["operating_expense"] for item in visible],
                "finance_depreciation": [item["finance_depreciation"] for item in visible],
                "operating_interest": [item["operating_interest"] for item in visible],
                "finance_interest": [item["finance_interest"] for item in visible],
            }
        )
    return {"base_weights": base_weights, "scenarios": results}


def _opening_finance_life_sensitivities(packet: dict[str, Any]) -> list[dict[str, Any]]:
    """Preview the selected opening finance-asset life and bounded alternatives."""
    ppe = packet["facts"]["finance_lease"]["ppe_net"]
    days = [item["days"] for item in period_meta()]
    scenarios = []
    for life_years in (10, 13, 16):
        opening = ppe
        depreciation = []
        closing = []
        for day_count in days:
            charge = min(opening, ppe / life_years * day_count / 365)
            opening -= charge
            depreciation.append(charge)
            closing.append(opening)
        scenarios.append({"name": f"opening_finance_life_{life_years}y", "service_life_years": life_years, "depreciation": depreciation, "closing_ppe": closing})
    return scenarios


def validate_proposal(proposal: FinancingProposal, packet: dict[str, Any]) -> None:
    if proposal.outcome != "propose_forecast":
        return
    _resolved_pipeline_finance_share(proposal, packet)
    if proposal.debt_coupon_rate <= 0:
        raise FinancingError("debt coupon proxy must be positive")
    if proposal.debt_refinance_policy != "refinance_disclosed_maturities":
        raise FinancingError("P8B selected debt refinancing policy is unsupported")
    if proposal.debt_tail_policy != "hold_through_fy2036":
        raise FinancingError("P8B selected debt tail policy is unsupported for the base")
    if proposal.refinance_term_years != 30:
        raise FinancingError("P8B selected refinancing term is 30 years")
    if proposal.lease_bundle != "operating_expense_finance_debt_like":
        raise FinancingError("P8B selected lease bundle is unsupported")
    if proposal.pipeline_timing_policy != "actual_day_weighted_fy2026_fy2031":
        raise FinancingError("P8B selected pipeline timing policy is unsupported")
    if proposal.pipeline_operating_rate <= 0 or proposal.pipeline_finance_rate <= 0:
        raise FinancingError("new-cohort rates must be positive")
    if proposal.pipeline_operating_life_years != 6 or proposal.pipeline_finance_life_years != 13:
        raise FinancingError("P8B selected pipeline service lives are 6 and 13 years")
    if proposal.opening_finance_life_years != 13:
        raise FinancingError("P8B selected opening finance service life is 13 years")


def _review_eligible(review: FinancingReview) -> bool:
    return review.evidence_strength != "weak" and all((review.method_valid, review.source_valid, review.period_valid, review.debt_bridge_valid, review.lease_bridge_valid, review.cash_bridge_valid, review.ufcf_independent, review.no_double_count, review.funding_visible))


def review_proposal(proposal: FinancingProposal, packet: dict[str, Any]) -> FinancingReview:
    validate_proposal(proposal, packet)
    return FinancingReview(
        verdict="accept",
        evidence_strength="mixed",
        method_valid=True,
        source_valid=True,
        period_valid=True,
        debt_bridge_valid=True,
        lease_bridge_valid=True,
        cash_bridge_valid=True,
        ufcf_independent=True,
        no_double_count=True,
        funding_visible=True,
        concerns=["Aggregate opening pool rates, lease tails and pipeline split remain provisional estimates."],
        required_revision=None,
        target="none",
        rationale="Offline deterministic checks preserve source containment and separate debt, operating lease and finance lease mechanics.",
    )


def forecast_values(packet: dict[str, Any], proposal: FinancingProposal) -> dict[str, Any]:
    validate_proposal(proposal, packet)
    op_amounts, op_dates = _opening_schedule("operating", packet)
    fin_amounts, fin_dates = _opening_schedule("finance", packet)
    op_rate = calibrate_rate(op_amounts, op_dates, packet["facts"]["operating_lease"]["liability"])
    fin_rate = calibrate_rate(fin_amounts, fin_dates, packet["facts"]["finance_lease"]["liability"])
    debt = _debt_schedule(packet, proposal)
    debt_tail = _debt_schedule(packet, proposal, tail_policy="runoff_fy2031_fy2036")
    operating = _pool_schedule("operating", packet, op_rate, life_years=6)
    finance = _pool_schedule("finance", packet, fin_rate, life_years=proposal.opening_finance_life_years)
    pipeline = _pipeline_schedule(packet, proposal)
    candidate_policy = proposal.model_dump(mode="json")
    resolved_policy = {**candidate_policy, "pipeline_finance_share": pipeline["finance_share"]}
    return {
        "periods": list(PERIODS),
        "period_meta": period_meta(),
        "debt": debt,
        "debt_tail_alternative": {
            "policy": debt_tail["tail_policy"],
            "redemption": debt_tail["cash_repayment"],
            "proceeds": debt_tail["cash_proceeds"],
            "closing_face": debt_tail["closing_face"],
            "closing_carrying": debt_tail["closing_carrying"],
        },
        "operating_opening_pool": operating,
        "finance_opening_pool": finance,
        "pipeline": pipeline,
        "pipeline_sensitivities": _pipeline_sensitivities(packet, proposal, pipeline),
        "opening_finance_life_sensitivities": _opening_finance_life_sensitivities(packet),
        "opening_calibration": {
            "operating_rate": op_rate,
            "finance_rate": fin_rate,
            "operating_pv": sum(amount / (1 + op_rate) ** _elapsed_years(date.fromisoformat(MEASUREMENT_DATE), date.fromisoformat(when)) for amount, when in zip(op_amounts, op_dates, strict=True)),
            "finance_pv": sum(amount / (1 + fin_rate) ** _elapsed_years(date.fromisoformat(MEASUREMENT_DATE), date.fromisoformat(when)) for amount, when in zip(fin_amounts, fin_dates, strict=True)),
            "operating_target_liability": packet["facts"]["operating_lease"]["liability"],
            "finance_target_liability": packet["facts"]["finance_lease"]["liability"],
        },
        # The candidate retains the source-mix reference; the calculator gets
        # its exact application-resolved numeric value.
        "policy": resolved_policy,
        "candidate_policy": candidate_policy,
        "source_claims": {
            "debt_fair_value_claim_once": packet["facts"]["debt"]["fair_value"],
            "finance_lease_liability_claim_once": packet["facts"]["finance_lease"]["liability"],
            "operating_lease_debt_claim": "none; operating lease remains in UFCF/BS under bundle A",
            "bundle_a": {
                "operating_lease": {
                    "cost": "operating",
                    "payments": "operating CFO/UFCF",
                    "statement_assets_and_liabilities": "ROU asset and lease liability remain on the statements",
                    "equity_bridge_claim": "none",
                },
                "finance_lease": {
                    "interest": "financing",
                    "principal": "financing CFF",
                    "additions": "economic investment once in UFCF",
                    "equity_bridge_claim": "finance lease liability once as a later debt-like claim",
                },
            },
        },
    }


def build_financing_model(
    p8a: dict[str, Any],
    packet: dict[str, Any],
    proposal: FinancingProposal,
    review: FinancingReview,
    *,
    context: dict[str, Any] | None = None,
    decision_status: str = "REVIEW_REQUIRED",
) -> dict[str, Any]:
    validate_proposal(proposal, packet)
    forecast = forecast_values(packet, proposal)
    context = context or {
        "case": CASE,
        "measurement_date": MEASUREMENT_DATE,
        "upstream_schema_version": p8a.get("schema_version"),
        "method_id": METHOD_ID,
        "method_version": METHOD_VERSION,
        "source_packet_hash": content_hash(packet),
        "proposal_hash": content_hash(proposal.model_dump(mode="json")),
        "review_hash": content_hash(review.model_dump(mode="json")),
    }
    candidate_hash = content_hash(proposal.model_dump(mode="json"))
    review_hash = content_hash(review.model_dump(mode="json"))
    source_packet_hash = content_hash(packet)
    # The workflow context is the binding identity.  Keep these three hashes
    # current even when a caller supplies a richer context object.
    context = {
        **context,
        "proposal_hash": candidate_hash,
        "review_hash": review_hash,
        "source_packet_hash": source_packet_hash,
    }
    decision = {
        "decision_id": "P8B-MSFT-FINANCING-DECISION-R2",
        "status": decision_status,
        "review": review.model_dump(mode="json"),
        "candidate_hash": candidate_hash,
        "review_hash": review_hash,
        "context_hash": content_hash(context),
        "source_packet_hash": source_packet_hash,
        "binding": {
            "candidate_hash": candidate_hash,
            "review_hash": review_hash,
            "context_hash": content_hash(context),
            "source_packet_hash": source_packet_hash,
            "candidate_snapshot": proposal.model_dump(mode="json"),
            "review_snapshot": review.model_dump(mode="json"),
            "source_case_snapshot_sha256": packet["accepted_upstream"]["source_case_snapshot_sha256"],
        },
    }
    return {
        "schema_version": "p8b-msft-financing-model-r2",
        "case": CASE,
        "information_cutoff": INFORMATION_CUTOFF,
        "measurement_date": MEASUREMENT_DATE,
        "method": {"id": METHOD_ID, "version": METHOD_VERSION, "catalog_version": METHOD_CATALOG_VERSION},
        "packet": packet,
        "inputs": {
            "debt_face": packet["facts"]["debt"]["face"],
            "debt_carrying": packet["facts"]["debt"]["carrying"],
            "debt_fair_value": packet["facts"]["debt"]["fair_value"],
            "opening_operating_rou": packet["facts"]["operating_lease"]["rou"],
            "opening_operating_liability": packet["facts"]["operating_lease"]["liability"],
            "opening_finance_ppe": packet["facts"]["finance_lease"]["ppe_net"],
            "opening_finance_liability": packet["facts"]["finance_lease"]["liability"],
            "opening_operating_payments": _opening_schedule("operating", packet)[0],
            "opening_finance_payments": _opening_schedule("finance", packet)[0],
            "embedded_operating_lease_cost_proxy": packet["facts"]["operating_lease"]["embedded_cost_proxy"],
            "embedded_operating_lease_cost_proxy_basis": packet["facts"]["operating_lease"]["embedded_cost_proxy_basis"],
            "period_days": [item["days"] for item in period_meta()],
        },
        "forecast": forecast,
        "provenance_contract": _provenance_contract(packet, context),
        "decision": decision,
        "limitations": packet["limitations"],
        "context": context,
    }


ANALYST_INSTRUCTION = (
    "Select one bounded P8B financing policy from the frozen packet. Preserve source "
    "balances, signs, dates and calibrated schedules. Rates are decimal fractions, "
    "service lives integer years and amounts USD millions. Return only the native "
    "structured schema. Follow the application-owned provenance contract: distinguish "
    "reported measures, calculated existing-pool measures and selected prospective "
    "estimates. Do not call a proxy an exact disclosed contractual fact. For unresolved "
    "or capability_gap, set every inactive field to null and explain the follow-up. "
    "Never return formulas, code or a human approval."
)
REVIEW_INSTRUCTION = (
    "Independently review the P8B candidate against the frozen source packet, linked "
    "schedules and actual Mog consequences. Check source/period/method validity, debt "
    "and lease bridges, cash/UFCF separation, funding visibility and double counting. "
    "Assess the candidate rationale and evidence references against the application-owned "
    "provenance contract and bundle A explanation; candidate prose is not source evidence. "
    "Treat unsupported attribution or an unsupported forward-rate choice as a correction "
    "concern. Remain independent and free to return accept, reject, or one bounded "
    "consequential revision target."
)
REVISION_INSTRUCTION = (
    "Produce one complete consequential P8B analyst revision responding to the review. "
    "Use the shared application-owned provenance contract, correct any source/explanation "
    "contradiction, change the named supported financial assumption, preserve locked source "
    "facts and return only the native structured schema. Prose-only or inactive-field "
    "changes are invalid."
)
REREVIEW_INSTRUCTION = (
    "Independently re-review the revised P8B candidate and its fresh actual Mog "
    "consequences. Reassess rationale, evidence references, provenance attributions and "
    "bundle A explanations as well as the numerical checks. Accept only a consequential "
    "supported change with valid source, period, bridge, UFCF, funding and no-double-count "
    "checks; remain free to hold or reject an unsupported choice. Return a terminal verdict."
)


def _strict_schema(response_model: type[BaseModel]) -> dict[str, Any]:
    """Return the installed SDK's recursive strict schema."""
    schema = to_strict_json_schema(response_model)
    _assert_strict_schema(schema)
    return schema


def _assert_strict_schema(node: Any) -> None:
    if isinstance(node, dict):
        if node.get("type") == "object" or "properties" in node:
            properties = node.get("properties", {})
            required = node.get("required", [])
            if set(properties) != set(required):
                raise FinancingError("strict schema object properties must all be required")
            if node.get("additionalProperties") is not False:
                raise FinancingError("strict schema objects must forbid extra properties")
        for value in node.values():
            _assert_strict_schema(value)
    elif isinstance(node, list):
        for value in node:
            _assert_strict_schema(value)


def _request(instruction: str, payload: dict[str, Any], response_model: type[BaseModel]) -> dict[str, Any]:
    """Build the exact body passed to ``client.responses.create``."""
    schema = _strict_schema(response_model)
    name = "financing_review" if response_model is FinancingReview else "financing_proposal"
    return {
        "model": MODEL,
        "reasoning": {"effort": REASONING_EFFORT},
        "service_tier": "default",
        "input": json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")),
        "instructions": instruction,
        "text": {"format": {"type": "json_schema", "name": name, "strict": True, "schema": schema}},
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "tools": [],
        "background": False,
    }


def _run_context(p8a: dict[str, Any], packet: dict[str, Any]) -> dict[str, Any]:
    selected = default_proposal(packet)
    operating_amounts, operating_dates = _opening_schedule("operating", packet)
    finance_amounts, finance_dates = _opening_schedule("finance", packet)
    operating_rate = calibrate_rate(operating_amounts, operating_dates, packet["facts"]["operating_lease"]["liability"])
    finance_rate = calibrate_rate(finance_amounts, finance_dates, packet["facts"]["finance_lease"]["liability"])
    prior_keys = ("decision", "p5_decision", "p6_decision", "p7_decision", "p8a_decision")
    prior = {
        key: {
            "status": (p8a.get(key) or {}).get("status"),
            "decision_id": (p8a.get(key) or {}).get("decision_id"),
            "hash": content_hash(p8a.get(key) or {}),
        }
        for key in prior_keys
        if isinstance(p8a.get(key), dict)
    }
    implementation_files = _calculation_implementation_hashes()
    return {
        "schema_version": SCHEMA_VERSION,
        "proposal_schema_hash": content_hash(_strict_schema(FinancingProposal)),
        "review_schema_hash": content_hash(_strict_schema(FinancingReview)),
        "prompt_version": PROMPT_VERSION,
        "method_catalog_version": METHOD_CATALOG_VERSION,
        "method_id": METHOD_ID,
        "method_version": METHOD_VERSION,
        "implementation_hash": _sha256(Path(__file__)),
        "implementation_files": implementation_files,
        "implementation_aggregate_sha256": content_hash(implementation_files),
        "model": MODEL,
        "reasoning_effort": REASONING_EFFORT,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "endpoint": ENDPOINT_URL,
        "service_tier": "default",
        "tools": [],
        "background": False,
        "max_retries": 0,
        "case": CASE,
        "information_cutoff": INFORMATION_CUTOFF,
        "measurement_date": MEASUREMENT_DATE,
        "source_packet_hash": content_hash(packet),
        "accepted_upstream": packet["accepted_upstream"],
        "selected_policy_hash": content_hash(selected.model_dump(mode="json")),
        "opening_calibration": {
            "operating_rate": operating_rate,
            "finance_rate": finance_rate,
            "method": "bounded PV calibration from dated source payment buckets",
        },
        "prior_decisions": prior,
    }


def _provenance_contract(packet: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Describe source attribution rules shared by every reasoning stage."""
    context = context or {}
    opening = context.get("opening_calibration") or {}
    if not opening:
        operating_amounts, operating_dates = _opening_schedule("operating", packet)
        finance_amounts, finance_dates = _opening_schedule("finance", packet)
        opening = {
            "operating_rate": calibrate_rate(
                operating_amounts,
                operating_dates,
                packet["facts"]["operating_lease"]["liability"],
            ),
            "finance_rate": calibrate_rate(
                finance_amounts,
                finance_dates,
                packet["facts"]["finance_lease"]["liability"],
            ),
        }
    debt = packet["facts"]["debt"]
    operating = packet["facts"]["operating_lease"]
    finance = packet["facts"]["finance_lease"]
    pipeline = packet["facts"]["pipeline"]
    source_ratio = pipeline["finance_share_source"]
    return {
        "version": PROVENANCE_CONTRACT_VERSION,
        "owner": "application",
        "reported_original_measures": {
            "status": "reported_original",
            "rule": "Preserve reported value, sign, period, unit and source attribution.",
            "fields": {
                "debt_face": {"path": "packet.facts.debt.face", "value": debt["face"], "unit": "USD millions"},
                "debt_carrying": {"path": "packet.facts.debt.carrying", "value": debt["carrying"], "unit": "USD millions"},
                "debt_fair_value": {"path": "packet.facts.debt.fair_value", "value": debt["fair_value"], "unit": "USD millions"},
                "debt_current": {"path": "packet.facts.debt.current", "value": debt["current"], "unit": "USD millions"},
                "debt_noncurrent": {"path": "packet.facts.debt.noncurrent", "value": debt["noncurrent"], "unit": "USD millions"},
                "debt_contra": {"path": "packet.facts.debt.contra", "value": debt["contra"], "unit": "USD millions; signed"},
                "debt_maturities": {"path": "packet.facts.debt.maturities", "value": debt["maturities"], "unit": "USD millions"},
                "operating_rou": {"path": "packet.facts.operating_lease.rou", "value": operating["rou"], "unit": "USD millions"},
                "operating_liability": {"path": "packet.facts.operating_lease.liability", "value": operating["liability"], "unit": "USD millions"},
                "operating_liability_components": {
                    "path": "packet.facts.operating_lease.{current_liability,noncurrent_liability}",
                    "value": {"current": operating["current_liability"], "noncurrent": operating["noncurrent_liability"]},
                    "unit": "USD millions",
                },
                "finance_ppe": {"path": "packet.facts.finance_lease.ppe_net", "value": finance["ppe_net"], "unit": "USD millions"},
                "finance_liability": {"path": "packet.facts.finance_lease.liability", "value": finance["liability"], "unit": "USD millions"},
                "finance_liability_components": {
                    "path": "packet.facts.finance_lease.{current_liability,noncurrent_liability}",
                    "value": {"current": finance["current_liability"], "noncurrent": finance["noncurrent_liability"]},
                    "unit": "USD millions",
                },
                "lease_payment_buckets": {
                    "path": "packet.facts.*_lease.payments",
                    "value": {"operating": operating["payments"], "finance": finance["payments"]},
                    "unit": "USD millions",
                },
                "pipeline_commitments": {"path": "packet.facts.pipeline.undiscounted_commitments", "value": pipeline["undiscounted_commitments"], "unit": "USD millions; undiscounted"},
                "disclosed_weighted_anchors": {
                    "path": "packet.facts.*_lease.disclosed_weighted_{rate,term_years}",
                    "value": {
                        "operating_rate": operating["disclosed_weighted_rate"],
                        "operating_term_years": operating["disclosed_weighted_term_years"],
                        "finance_rate": finance["disclosed_weighted_rate"],
                        "finance_term_years": finance["disclosed_weighted_term_years"],
                    },
                    "unit": "decimal rate / integer years",
                },
            },
        },
        "calculated_existing_pool_measures": {
            "status": "calculated_existing_pool",
            "rule": "Application calculation from dated source inputs; not a disclosed rate or contractual schedule.",
            "fields": {
                "opening_operating_calibrated_rate": {
                    "path": "context.opening_calibration.operating_rate",
                    "value": opening["operating_rate"],
                    "basis": "PV of dated opening operating payment buckets equals reported operating liability",
                    "use": "opening operating pool only",
                },
                "opening_finance_calibrated_rate": {
                    "path": "context.opening_calibration.finance_rate",
                    "value": opening["finance_rate"],
                    "basis": "PV of dated opening finance payment buckets equals reported finance liability",
                    "use": "opening finance pool only",
                },
                "pipeline_finance_share_source_ratio": {
                    "path": "packet.facts.pipeline.finance_share_source",
                    "value": source_ratio,
                    "basis": "finance additions / (finance additions + operating additions) from disclosed recent additions",
                    "use": "source ratio used as a selected estimate for the undisclosed signed pipeline split",
                },
                "operating_cost_proxy": {
                    "path": "packet.facts.operating_lease.embedded_cost_proxy",
                    "value": operating["embedded_cost_proxy"],
                    "basis": operating["embedded_cost_proxy_basis"],
                    "use": "compatible embedded-cost replacement proxy",
                },
            },
        },
        "selected_prospective_policy_estimates": {
            "status": "selected_prospective_estimate",
            "rule": "Selected modeling assumptions for future periods; never present as exact disclosed contractual facts.",
            "fields": {
                "debt_coupon_rate": {"value": 0.045, "basis": "explicit annual coupon proxy; not a disclosed tranche point rate"},
                "refinance_term_years": {"value": 30, "basis": "period-end refinancing convention; not a disclosed contractual refinancing term"},
                "refinance_fee_rate": {"value": 0.0, "basis": "selected zero-fee assumption; not a disclosed fee fact"},
                "opening_finance_life_years": {"value": 13, "basis": "selected proxy using disclosed weighted remaining term; source asset life not inferred"},
                "pipeline_finance_share": {"value": source_ratio, "value_ref": "calculated_existing_pool_measures.fields.pipeline_finance_share_source_ratio", "basis": "selected proxy for undisclosed pipeline split; not a disclosed pipeline mix"},
                "pipeline_lives_years": {"value": {"operating": 6, "finance": 13}, "basis": "selected aggregate proxies; not exact signed-pipeline service lives"},
                "pipeline_timing_policy": {"value": "actual_day_weighted_fy2026_fy2031", "basis": "selected cohort timing estimate; not reconstructed contract dates"},
                "pipeline_rates": {
                    "value": {"operating": operating["disclosed_weighted_rate"], "finance": finance["disclosed_weighted_rate"]},
                    "basis": "default future-rate proxies use selected disclosed weighted anchors; they are not exact forward contractual rates",
                },
            },
        },
        "rate_attribution_rules": {
            "opening_calibrated_rates_are_not": ["disclosed weighted rates", "automatic forward cohort rates"],
            "default_future_rate_proxies": {"operating": operating["disclosed_weighted_rate"], "finance": finance["disclosed_weighted_rate"]},
            "supported_override_fields": ["pipeline_operating_rate", "pipeline_finance_rate"],
            "override_requirement": "A different forward rate requires a substantive forward-looking financial basis in the candidate explanation and independent reviewer assessment.",
            "unsupported_override_outcome": "reviewer may hold, require revision, or reject; application must not silently replace the candidate number.",
        },
        "bundle_a": {
            "operating_lease": {
                "cost": "operating",
                "payments": "operating CFO/UFCF",
                "statement_treatment": "ROU asset and liability remain on the statements",
                "equity_bridge_claim": "none",
            },
            "finance_lease": {
                "interest": "financing",
                "principal": "financing CFF",
                "additions": "economic investment once in UFCF",
                "equity_bridge_claim": "finance liability once as a later debt-like claim",
            },
        },
        "candidate_explanation_rule": {
            "rationale_and_evidence_refs": "candidate_explanation",
            "is_source_statement": False,
            "source_validity": "must be independently assessed against this contract and the packet",
            "contradiction_treatment": "Treat a mismatch as a correction concern; do not promote candidate prose into source evidence.",
        },
    }


def _method_contract(packet: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Describe the wire contract, including application-owned resolutions."""
    finance_share = _resolved_pipeline_finance_share(default_proposal(packet), packet)
    fixed_fields = {
        "method_id": METHOD_ID,
        "method_version": METHOD_VERSION,
        "debt_refinance_policy": "refinance_disclosed_maturities",
        "debt_tail_policy": "hold_through_fy2036",
        "refinance_term_years": 30,
        "refinance_fee_rate": 0.0,
        "lease_bundle": "operating_expense_finance_debt_like",
        "pipeline_finance_share": {
            "reference": PIPELINE_FINANCE_SHARE_REFERENCE,
            "resolve_from": "packet.facts.pipeline.finance_share_source",
            "calculation": "finance_additions_source / (finance_additions_source + operating_additions_source)",
            "resolved_value": finance_share,
        },
        "pipeline_operating_life_years": 6,
        "pipeline_finance_life_years": 13,
        "pipeline_timing_policy": "actual_day_weighted_fy2026_fy2031",
        "opening_finance_life_years": 13,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "method_catalog_version": METHOD_CATALOG_VERSION,
        "allowed_method_ids": [METHOD_ID],
        "allowed_outcomes": ["propose_forecast", "unresolved", "capability_gap"],
        "fixed_application_fields": fixed_fields,
        "changeable_judgment_fields": [
            "debt_coupon_rate", "pipeline_operating_rate", "pipeline_finance_rate",
        ],
        "judgment_constraints": {
            "debt_coupon_rate": {"type": "decimal_fraction", "exclusive_min": 0, "max": 1},
            "pipeline_operating_rate": {"type": "decimal_fraction", "exclusive_min": 0, "max": 1},
            "pipeline_finance_rate": {"type": "decimal_fraction", "exclusive_min": 0, "max": 1},
        },
        "application_sensitivities": {
            "debt_tail_policy": ["runoff_fy2031_fy2036"],
            "pipeline_finance_share": [0.50, 0.90],
            "opening_finance_life_years": [10, 16],
            "pipeline_rates": ["minus_100bp", "plus_100bp"],
        },
        "nonforecast_inactive_fields_must_be_null": [
            "method_id", "method_version", "debt_coupon_rate", "debt_refinance_policy",
            "debt_tail_policy", "refinance_term_years", "refinance_fee_rate", "lease_bundle",
            "pipeline_finance_share", "pipeline_operating_life_years", "pipeline_finance_life_years",
            "pipeline_operating_rate", "pipeline_finance_rate", "pipeline_timing_policy",
            "opening_finance_life_years",
        ],
        "unsupported_change_outcome": "capability_gap",
        "units": {
            "amounts": "USD millions", "rates": "decimal fraction",
            "service_lives": "integer years", "dates": "period-end ISO date", "shares": "dimensionless",
        },
        "source_fields_locked": True,
        "no_runtime_code": True,
        "no_human_approval": True,
        "provenance_contract": _provenance_contract(packet, context),
    }


def _proposal_payload(packet: dict[str, Any], context: dict[str, Any], *, purpose: str, candidate: FinancingProposal | None = None, review: FinancingReview | None = None, authority: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "purpose": purpose,
        "packet": packet,
        "context": context,
        "required_periods": list(PERIODS),
        "contract": _method_contract(packet, context),
    }
    if candidate is not None:
        payload["candidate"] = candidate.model_dump(mode="json")
    if review is not None:
        payload["review"] = review.model_dump(mode="json")
    if authority is not None:
        payload["actual_mog"] = authority
    return payload


def _review_payload(packet: dict[str, Any], context: dict[str, Any], candidate: FinancingProposal, *, purpose: str, authority: dict[str, Any], prior_review: FinancingReview | None = None) -> dict[str, Any]:
    payload = _proposal_payload(packet, context, purpose=purpose, candidate=candidate, review=prior_review, authority=authority) | {
        "candidate_forecast": forecast_values(packet, candidate),
        "review_contract": {
            "accept_requires_all_checks": True,
            "revise_requires_one_target_and_consequential_change": True,
            "reject_and_revision_failure_publish_nothing": True,
            "independent_reviewer": True,
            "fixed_fields_are_not_revision_choices": True,
            "provenance_explanation_review_required": True,
            "candidate_explanation_is_not_source_evidence": True,
            "source_valid_is_reviewer_assessed": True,
            "supported_revision_fields": [
                "debt_coupon_rate", "pipeline_operating_rate", "pipeline_finance_rate",
            ],
            "unsupported_fixed_change_outcome": "capability_gap",
        },
    }
    payload["candidate_explanation_review"] = {
        "classification": "candidate_explanation",
        "rationale": candidate.rationale,
        "evidence_refs": list(candidate.evidence_refs),
        "is_source_statement": False,
        "source_validity": "review_required",
        "correction_concern_if_mismatch": "A contradiction with the provenance contract is a correction concern, never a source statement.",
        "reviewer_discretion": "Assess the substance against the packet; remain free to accept, revise, reject or hold an unsupported choice.",
    }
    return payload


def _safe_model_dump(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list, str, int, float, bool)):
        return value
    try:
        return value.model_dump(mode="json")
    except (AttributeError, TypeError, ValueError):
        try:
            return json.loads(value.model_dump_json())
        except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
            return {"repr": repr(value)}


def _usage_dict(response: Any) -> dict[str, Any] | None:
    value = _safe_model_dump(getattr(response, "usage", None))
    if not isinstance(value, dict) or not all(key in value for key in ("input_tokens", "output_tokens", "total_tokens")):
        return None
    return value


def _response_value(response: Any) -> Any:
    parsed = getattr(response, "output_parsed", None)
    if parsed is not None:
        return parsed
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text.strip():
        return output_text
    raw = response if isinstance(response, dict) else _safe_model_dump(response)
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


def _wire_value(value: Any, response_model: type[BaseModel]) -> BaseModel:
    if isinstance(value, response_model):
        return value
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise FinancingError("provider response was not valid JSON") from exc
    if not isinstance(value, dict):
        raise FinancingError("provider response contained no structured output")
    schema = _strict_schema(response_model)
    required = set(schema.get("required", []))
    if set(value) != required:
        missing = sorted(required - set(value))
        extra = sorted(set(value) - required)
        raise FinancingError(f"provider structured output keys violate strict schema; missing={missing}, extra={extra}")
    try:
        return response_model.model_validate(value)
    except Exception as exc:
        raise FinancingError(f"provider structured output failed semantic validation: {exc}") from exc


def _parse_structured_response(response: Any, response_model: type[BaseModel]) -> BaseModel:
    return _wire_value(_response_value(response), response_model)


def _ledger_p8b_state(budget_path: Path) -> tuple[int, float]:
    state = json.loads(budget_path.read_text(encoding="utf-8"))
    calls = [item for item in state.get("calls", []) if item.get("task_id") == TASK_ID]
    total = sum(item.get("cost", {}).get("priced_eur", item.get("reserved_eur", 0.0)) for item in calls)
    return len(calls), float(total)


def _prior_stage_result(attempts: Path, stage: str, request_hash: str, response_model: type[BaseModel], budget_path: Path) -> tuple[BaseModel, dict[str, Any]] | None:
    state = json.loads(budget_path.read_text(encoding="utf-8"))
    matches = [call for call in state.get("calls", []) if call.get("task_id") == TASK_ID and call.get("request_hash") == request_hash]
    if any(call.get("status") in {"reserved", "usage_unknown"} for call in matches):
        raise FinancingError(f"{stage} exact request has a held ledger admission; explicit recovery required")
    for request_path in sorted(attempts.glob(f"*-{stage}.request.json")):
        try:
            request = json.loads(request_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if content_hash(request) != request_hash:
            continue
        prefix = request_path.name[:-len(".request.json")]
        outcome_path = attempts / f"{prefix}.outcome.json"
        outcome = json.loads(outcome_path.read_text(encoding="utf-8")) if outcome_path.exists() else {}
        if outcome.get("status") in {"reserved", "usage_unknown"} or any(call.get("status") != "completed" for call in matches):
            raise FinancingError(f"{stage} exact request has an unsettled admission; no duplicate dispatch")
        if outcome.get("status") != "completed" or not matches:
            continue
        structured_path = attempts / f"{prefix}.structured.json"
        response_path = attempts / f"{prefix}.response.json"
        if structured_path.exists():
            value = response_model.model_validate(json.loads(structured_path.read_text(encoding="utf-8")))
        elif response_path.exists():
            value = _parse_structured_response(json.loads(response_path.read_text(encoding="utf-8")), response_model)
            _write_json(structured_path, value.model_dump(mode="json"))
        else:
            raise FinancingError(f"{stage} completed without resumable structured output")
        metadata_path = attempts / f"{prefix}.metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
        metadata.update({"resumed": True, "resumed_call_ids": [call.get("call_id") for call in matches]})
        return value, metadata
    if matches:
        raise FinancingError(f"{stage} has a prior exact request without resumable artifacts")
    return None


def _dispatch_structured(*, stage: str, run_dir: Path, budget_path: Path, instruction: str, payload: dict[str, Any], response_model: type[BaseModel], client: Any | None = None) -> tuple[BaseModel, dict[str, Any]]:
    request = _request(instruction, payload, response_model)
    request_hash = content_hash(request)
    attempts = run_dir / "attempts"
    attempts.mkdir(parents=True, exist_ok=True)
    prior = _prior_stage_result(attempts, stage, request_hash, response_model, budget_path)
    if prior is not None:
        return prior
    ordinal, committed = _ledger_p8b_state(budget_path)
    if ordinal >= MAX_ATTEMPTS:
        raise FinancingError("P8B dispatched-attempt cap reached")
    prices = json.loads(budget_path.read_text(encoding="utf-8"))["prices"]
    estimate = reservation(request, prices, today=date.today())["reserved_eur"]
    if committed + estimate > MAX_COMMITTED_EUR:
        raise FinancingError("P8B committed/reserved allowance would exceed EUR0.50")
    call_id = f"{TASK_ID}-{ordinal + 1:02d}-{stage}"
    prefix = f"{ordinal + 1:02d}-{stage}"
    _write_json(attempts / f"{prefix}.request.json", request)
    admission = reserve_call(budget_path, call_id=call_id, task_id=TASK_ID, request=request, endpoint_host=ENDPOINT_HOST, today=date.today())
    _write_json(attempts / f"{prefix}.reservation.json", admission)
    if client is None:
        load_dotenv()
        from openai import OpenAI
        client = OpenAI(max_retries=0, base_url=BASE_URL)
    started = time.perf_counter()
    response = None
    error: Exception | None = None
    try:
        # The exact admitted body is passed through unchanged.
        response = client.responses.create(**request)
    except Exception as exc:
        error = exc
    elapsed = time.perf_counter() - started
    response_id = getattr(response, "id", None)
    returned_model = getattr(response, "model", None)
    raw = _safe_model_dump(response) if response is not None else {"response": None}
    if error is not None:
        raw = {"error_type": type(error).__name__, "error": str(error), "response": raw}
    _write_json(attempts / f"{prefix}.response.json", raw)
    usage = _usage_dict(response) if response is not None else None
    outcome_error: Exception | None = None
    try:
        outcome = record_outcome(budget_path, call_id=call_id, usage=usage, elapsed_seconds=elapsed, response_id=response_id, returned_model=returned_model)
    except Exception as exc:
        outcome_error = exc
        _write_json(attempts / f"{prefix}.outcome-error.json", {"error_type": type(exc).__name__, "error": str(exc)})
        outcome = record_outcome(budget_path, call_id=call_id, usage=None, elapsed_seconds=elapsed, response_id=response_id, returned_model=returned_model)
    _write_json(attempts / f"{prefix}.outcome.json", outcome)
    metadata = {
        "call_id": call_id, "stage": stage, "endpoint": ENDPOINT_URL,
        "request_hash": request_hash, "stage_context_hash": content_hash({"stage": stage, "request": request}),
        "response_id": response_id, "returned_model": returned_model, "usage": usage,
        "elapsed_seconds": elapsed, "status": outcome["status"],
        "instruction_hash": content_hash(instruction), "payload_hash": content_hash(payload),
        "schema_hash": content_hash(request["text"]["format"]["schema"]), "model": request["model"],
        "reasoning": request["reasoning"], "service_tier": request["service_tier"], "max_retries": 0,
        "prompt_version": payload.get("context", {}).get("prompt_version") if isinstance(payload.get("context"), dict) else None,
        "method_catalog_version": payload.get("context", {}).get("method_catalog_version") if isinstance(payload.get("context"), dict) else None,
        "source_packet_hash": content_hash(payload["packet"]) if isinstance(payload.get("packet"), dict) else None,
    }
    _write_json(attempts / f"{prefix}.metadata.json", metadata)
    if error is not None:
        raise FinancingError(f"{stage} provider call failed after admission: {error}") from error
    if outcome_error is not None or outcome.get("status") != "completed":
        raise FinancingError(f"{stage} usage is unknown after admission; exact-hash replay is held")
    try:
        parsed = _parse_structured_response(response, response_model)
    except Exception as exc:
        _write_json(attempts / f"{prefix}.parse-error.json", {"error_type": type(exc).__name__, "error": str(exc)})
        raise FinancingError(f"{stage} returned invalid structured output after persistence: {exc}") from exc
    _write_json(attempts / f"{prefix}.structured.json", parsed.model_dump(mode="json"))
    return parsed, metadata


def _review_contract(review: FinancingReview) -> None:
    if review.verdict == "revise":
        if review.target == "none" or not review.required_revision:
            raise FinancingError("revise verdict must name one target and required revision")
    elif review.target != "none" or review.required_revision is not None:
        raise FinancingError(f"{review.verdict} verdict cannot carry a revision target")


def _revision_is_consequential(original: FinancingProposal, revised: FinancingProposal, target: str) -> None:
    fields = {
        "debt_policy": ("debt_coupon_rate", "debt_refinance_policy", "debt_tail_policy", "refinance_term_years", "refinance_fee_rate"),
        "lease_bundle": ("lease_bundle", "opening_finance_life_years"),
        "pipeline": ("pipeline_finance_share", "pipeline_operating_life_years", "pipeline_finance_life_years", "pipeline_operating_rate", "pipeline_finance_rate", "pipeline_timing_policy"),
        "opening_rates": ("pipeline_operating_rate", "pipeline_finance_rate"),
        "funding": ("debt_refinance_policy", "debt_tail_policy", "debt_coupon_rate"),
    }.get(target)
    if not fields:
        raise FinancingError(f"unsupported revision target: {target}")
    before = original.model_dump(mode="json")
    after = revised.model_dump(mode="json")
    if not any(before.get(field) != after.get(field) for field in fields):
        raise FinancingError("revision must change a consequential supported financial assumption")


def _review_eligible_live(review: FinancingReview) -> bool:
    return review.evidence_strength != "weak" and all((
        review.method_valid,
        review.source_valid,
        review.period_valid,
        review.debt_bridge_valid,
        review.lease_bridge_valid,
        review.cash_bridge_valid,
        review.ufcf_independent,
        review.no_double_count,
        review.funding_visible,
    ))


def _terminal_outcome(run_dir: Path, packet: dict[str, Any], context: dict[str, Any], *, status: str, reason: str, metadata: dict[str, Any], candidate: FinancingProposal | None = None) -> dict[str, Any]:
    prior_model = run_dir / "model.json"
    result = {
        "decision_id": "P8B-MSFT-FINANCING-HELD-R2",
        "status": status,
        "human_approval": False,
        "selected_candidate": None,
        "candidate_hash": content_hash(candidate.model_dump(mode="json")) if candidate else None,
        "context_hash": content_hash(context),
        "source_packet_hash": content_hash(packet),
        "reason": reason,
        "previous_effective_model_sha256": _sha256(prior_model) if prior_model.exists() else None,
        "metadata": metadata,
    }
    _write_json(run_dir / "decision-held.json", result)
    terminal = {"status": status, "reason": reason, "decision": result}
    if candidate is not None:
        terminal["candidate"] = candidate.model_dump(mode="json")
    _write_json(run_dir / "terminal-outcome.json", terminal)
    return result


def _compose_model_input(p8a: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(p8a)
    result["financing_packet"] = model["packet"]
    result["financing_forecast"] = model
    result["financing_decision"] = model["decision"]
    result["p8b_decision"] = model["decision"]
    result["schema_version"] = "p8b-msft-financing-input-r2"
    return result


def _actual_mog_candidate(p8a: dict[str, Any], packet: dict[str, Any], proposal: FinancingProposal, context: dict[str, Any], run_dir: Path, stage: str) -> dict[str, Any]:
    """Run the existing local Mog workbook authority for one candidate."""
    mechanical_review = review_proposal(proposal, packet)
    model = build_financing_model(p8a, packet, proposal, mechanical_review, context=context, decision_status="REVIEW_REQUIRED")
    authority_dir = run_dir / "mog-authority" / stage
    authority_dir.mkdir(parents=True, exist_ok=True)
    input_path = authority_dir / "model-input.json"
    _write_json(input_path, _compose_model_input(p8a, model))
    script = Path(__file__).resolve().parents[2] / "scripts" / "spreadsheet_compat" / "run-p8b.mjs"
    if not script.exists():
        raise FinancingError(f"local Mog authority script is missing: {script}")
    completed = subprocess.run(
        ["node", str(script), "authority", str(input_path), str(authority_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    (authority_dir / "mog.stdout.log").write_text(completed.stdout, encoding="utf-8")
    (authority_dir / "mog.stderr.log").write_text(completed.stderr, encoding="utf-8")
    verification_path = authority_dir / "financing-verification.json"
    if completed.returncode != 0 or not verification_path.exists():
        raise FinancingError(f"Mog authority failed for {stage}; see {authority_dir}")
    verification = json.loads(verification_path.read_text(encoding="utf-8"))
    if verification.get("status") != "PASS" or not isinstance(verification.get("snapshot"), dict):
        raise FinancingError(f"Mog authority did not pass for {stage}")
    return {
        "status": "PASS",
        "engine": "Mog SDK",
        "stage": stage,
        "verification_path": verification_path.as_posix(),
        "candidate_hash": content_hash(proposal.model_dump(mode="json")),
        "snapshot": verification["snapshot"],
    }


def _write_final_model(run_dir: Path, p8a: dict[str, Any], packet: dict[str, Any], proposal: FinancingProposal, review: FinancingReview, context: dict[str, Any], *, authority: dict[str, Any], status: str = "SYSTEM_REVIEWED_PROVISIONAL") -> dict[str, Any]:
    model = build_financing_model(p8a, packet, proposal, review, context=context, decision_status=status)
    model["authoritative_mog"] = authority
    model["decision"]["authoritative_mog_attached"] = True
    model["decision"]["human_approval"] = False
    _write_json(run_dir / "candidate.json", proposal.model_dump(mode="json"))
    _write_json(run_dir / "review.json", review.model_dump(mode="json"))
    _write_json(run_dir / "model.json", model)
    return model


def run_reasoning(
    p8a: dict[str, Any],
    run_dir: Path,
    budget_path: Path,
    *,
    source_table: Path | None = None,
    offline: bool = False,
    client: Any | None = None,
    mog_builder: Any | None = None,
) -> dict[str, Any]:
    """Run P8B's serial analyst/reviewer/revision/re-review workflow."""
    run_dir.mkdir(parents=True, exist_ok=True)
    packet = build_evidence_packet(p8a, source_table)
    context = _run_context(p8a, packet)
    context_path = run_dir / "run-context.json"
    if context_path.exists():
        prior = json.loads(context_path.read_text(encoding="utf-8"))
        if prior != context:
            raise FinancingError("P8B run context changed; prior outputs cannot be reused")
    else:
        _write_json(context_path, context)
    _write_json(run_dir / "evidence-packet.json", packet)
    if offline:
        model = run_offline(p8a, run_dir, source_table=source_table)
        model["decision"]["offline_fixture"] = True
        _write_json(run_dir / "model.json", model)
        return model
    if not budget_path.exists():
        raise FinancingError(f"P8B budget ledger is missing: {budget_path}")
    meta: dict[str, Any] = {"context": context, "offline": False, "task_id": TASK_ID}
    current_candidate: FinancingProposal | None = None
    try:
        payload = _proposal_payload(packet, context, purpose="initial analyst selection")
        original, analyst_meta = _dispatch_structured(stage="analyst-initial", run_dir=run_dir, budget_path=budget_path, instruction=ANALYST_INSTRUCTION, payload=payload, response_model=FinancingProposal, client=client)
        current_candidate = original
        _write_json(run_dir / "candidate-initial.json", original.model_dump(mode="json"))
        meta["analyst"] = analyst_meta
        if original.outcome != "propose_forecast":
            status = "CAPABILITY_GAP" if original.outcome == "capability_gap" else "UNRESOLVED"
            _terminal_outcome(run_dir, packet, context, status=status, reason=original.follow_up_request or original.rationale, metadata=meta, candidate=original)
            raise FinancingError(f"P8B analyst terminated with {status}; no forecast was built")
        validate_proposal(original, packet)
        builder = mog_builder or _actual_mog_candidate
        original_authority = builder(p8a, packet, original, context, run_dir, "analyst-initial")
        original_review, review_meta = _dispatch_structured(
            stage="reviewer-original",
            run_dir=run_dir,
            budget_path=budget_path,
            instruction=REVIEW_INSTRUCTION,
            payload=_review_payload(packet, context, original, purpose="independent original review", authority=original_authority),
            response_model=FinancingReview,
            client=client,
        )
        _review_contract(original_review)
        _write_json(run_dir / "review-original.json", original_review.model_dump(mode="json"))
        meta["reviewer_original"] = review_meta
        if original_review.verdict == "accept":
            if not _review_eligible_live(original_review):
                _terminal_outcome(run_dir, packet, context, status="REVIEW_REQUIRED", reason="review accept did not satisfy all eligibility checks", metadata=meta, candidate=original)
                raise FinancingError("P8B review accept did not satisfy eligibility checks")
            return _write_final_model(run_dir, p8a, packet, original, original_review, context, authority=original_authority)
        if original_review.verdict == "reject":
            _terminal_outcome(run_dir, packet, context, status="REJECTED_BY_REVIEW", reason="; ".join(original_review.concerns), metadata=meta, candidate=original)
            raise FinancingError("P8B candidate rejected; prior effective model preserved")

        _write_json(run_dir / "revision-request.json", {"target": original_review.target, "required_revision": original_review.required_revision, "prior_candidate_hash": content_hash(original.model_dump(mode="json")), "context_hash": content_hash(context)})
        revision_payload = _proposal_payload(packet, context, purpose="required consequential analyst revision", candidate=original, review=original_review, authority=original_authority)
        revised, revision_meta = _dispatch_structured(stage="analyst-revision", run_dir=run_dir, budget_path=budget_path, instruction=REVISION_INSTRUCTION, payload=revision_payload, response_model=FinancingProposal, client=client)
        current_candidate = revised
        _write_json(run_dir / "candidate-revision.json", revised.model_dump(mode="json"))
        if revised.outcome != "propose_forecast":
            status = "CAPABILITY_GAP" if revised.outcome == "capability_gap" else "UNRESOLVED"
            revision_outcome = {
                "stage": "analyst-revision",
                "outcome": revised.outcome,
                "candidate": revised.model_dump(mode="json"),
                "candidate_hash": content_hash(revised.model_dump(mode="json")),
                "reason": revised.rationale,
                "follow_up_request": revised.follow_up_request,
                "requested_target": original_review.target,
                "prior_candidate_hash": content_hash(original.model_dump(mode="json")),
            }
            meta.update({
                "analyst_revision": revision_meta,
                "revision_outcome": revision_outcome,
                "revision": {
                    "target": original_review.target,
                    "original_candidate_hash": content_hash(original.model_dump(mode="json")),
                    "revised_candidate_hash": revision_outcome["candidate_hash"],
                },
            })
            _write_json(run_dir / "revision-outcome.json", revision_outcome)
            _terminal_outcome(
                run_dir,
                packet,
                context,
                status=status,
                reason=revised.follow_up_request or revised.rationale,
                metadata=meta,
                candidate=revised,
            )
            raise FinancingError(f"P8B analyst revision terminated with {status}; no forecast was built")
        _revision_is_consequential(original, revised, original_review.target)
        validate_proposal(revised, packet)
        revised_authority = builder(p8a, packet, revised, context, run_dir, "analyst-revision")
        revised_review, rereview_meta = _dispatch_structured(
            stage="reviewer-revision",
            run_dir=run_dir,
            budget_path=budget_path,
            instruction=REREVIEW_INSTRUCTION,
            payload=_review_payload(packet, context, revised, purpose="independent revision re-review", authority=revised_authority, prior_review=original_review),
            response_model=FinancingReview,
            client=client,
        )
        _review_contract(revised_review)
        _write_json(run_dir / "review-revision.json", revised_review.model_dump(mode="json"))
        meta.update({"analyst_revision": revision_meta, "reviewer_revision": rereview_meta, "revision": {"target": original_review.target, "original_candidate_hash": content_hash(original.model_dump(mode="json")), "revised_candidate_hash": content_hash(revised.model_dump(mode="json"))}})
        if revised_review.verdict != "accept" or not _review_eligible_live(revised_review):
            status = "REJECTED_BY_REVIEW" if revised_review.verdict == "reject" else "REVISION_REQUIRED"
            _terminal_outcome(run_dir, packet, context, status=status, reason="; ".join(revised_review.concerns), metadata=meta, candidate=revised)
            raise FinancingError("P8B revised candidate was not accepted; original was not adopted")
        return _write_final_model(run_dir, p8a, packet, revised, revised_review, context, authority=revised_authority)
    except FinancingError as exc:
        terminal_path = run_dir / "terminal-outcome.json"
        if not terminal_path.exists():
            message = str(exc).lower()
            status = "BUDGET_HELD" if any(
                marker in message
                for marker in ("budget", "allowance", "usage is unknown", "held")
            ) else "FAILED"
            _terminal_outcome(run_dir, packet, context, status=status, reason=str(exc), metadata=meta, candidate=current_candidate)
        raise
    except Exception as exc:
        message = str(exc).lower()
        status = "BUDGET_HELD" if any(
            marker in message
            for marker in ("budget", "allowance", "reservation", "usage")
        ) else "FAILED"
        _terminal_outcome(run_dir, packet, context, status=status, reason=str(exc), metadata=meta, candidate=current_candidate)
        raise FinancingError(f"P8B workflow failed; prior effective model preserved: {exc}") from exc


def run_live(
    p8a: dict[str, Any],
    run_dir: Path,
    budget_path: Path,
    *,
    source_table: Path | None = None,
    client: Any | None = None,
    mog_builder: Any | None = None,
) -> dict[str, Any]:
    """Named live entry point; production CLI delegates to ``run_reasoning``."""
    return run_reasoning(
        p8a,
        run_dir,
        budget_path,
        source_table=source_table,
        client=client,
        mog_builder=mog_builder,
    )


def prepare_live_handoff(p8a: dict[str, Any], run_dir: Path, *, source_table: Path | None = None, output_path: Path | None = None, budget_path: Path | None = None) -> dict[str, Any]:
    """Prepare a canonical live request without loading credentials or dispatching."""
    packet = build_evidence_packet(p8a, source_table)
    context = _run_context(p8a, packet)
    payload = _proposal_payload(packet, context, purpose="initial analyst selection")
    request = _request(ANALYST_INSTRUCTION, payload, FinancingProposal)
    rebuilt = _request(ANALYST_INSTRUCTION, payload, FinancingProposal)
    run_dir.mkdir(parents=True, exist_ok=True)
    request_path = run_dir / "attempts" / "01-analyst-initial.request.json"
    _write_json(run_dir / "run-context.json", context)
    _write_json(run_dir / "evidence-packet.json", packet)
    _write_json(request_path, request)
    schema_proof = {"proposal": {"schema_hash": content_hash(request["text"]["format"]["schema"]), "strict": True, "all_properties_required": True}, "review": {"schema_hash": content_hash(_strict_schema(FinancingReview)), "strict": True, "all_properties_required": True}}
    _write_json(run_dir / "schema-proof.json", schema_proof)
    prepared_output = output_path or run_dir / "model-input.json"
    prepared_budget = budget_path or Path("data/build-guide-api-budget.json")
    parent_cli = (
        "PYTHONPATH=src .venv\\Scripts\\python.exe -m smrik_fund.financing "
        "--p8a-model data/build-guide-p8a/live-r5/model-input.json "
        f"--output {prepared_output.as_posix()} --run-dir {run_dir.as_posix()} "
        f"--budget {prepared_budget.as_posix()}"
    )
    budget_read = None
    if budget_path is not None and budget_path.exists():
        state = json.loads(budget_path.read_text(encoding="utf-8"))
        calls = [item for item in state.get("calls", []) if item.get("task_id") == TASK_ID]
        budget_read = {"path": budget_path.as_posix(), "task_calls": len(calls), "task_committed_eur": sum(item.get("cost", {}).get("priced_eur", item.get("reserved_eur", 0.0)) for item in calls), "ledger_sha256": _sha256(budget_path)}
    manifest = {
        "status": "PREPARED_NO_DISPATCH",
        "stage": "analyst-initial",
        "case": CASE,
        "request_path": request_path.as_posix(),
        "request_hash": content_hash(request),
        "request_rebuilt_hash": content_hash(rebuilt),
        "canonical_request_equal": request == rebuilt,
        "source_packet_hash": content_hash(packet),
        "context_hash": content_hash(context),
        "implementation_files": context["implementation_files"],
        "implementation_aggregate_sha256": context["implementation_aggregate_sha256"],
        "settings": {"model": MODEL, "reasoning": {"effort": REASONING_EFFORT}, "endpoint": ENDPOINT_URL, "service_tier": "default", "max_output_tokens": MAX_OUTPUT_TOKENS, "tools": [], "background": False, "max_retries": 0},
        "caps": {"max_attempts": MAX_ATTEMPTS, "max_committed_eur": MAX_COMMITTED_EUR, "final_review_reserve_eur": 0.50},
        "cli": parent_cli,
        "replay_policy": "only exact completed requests in the same context may resume; invalid or unsettled outcomes remain held",
        "output_path": prepared_output.as_posix(),
        "budget_read_only": budget_read,
    }
    _write_json(run_dir / "prepared-manifest.json", manifest)
    return manifest


def run_offline(p8a: dict[str, Any], run_dir: Path, *, source_table: Path | None = None) -> dict[str, Any]:
    run_dir.mkdir(parents=True, exist_ok=True)
    packet = build_evidence_packet(p8a, source_table)
    proposal = default_proposal(packet)
    review = review_proposal(proposal, packet)
    model = build_financing_model(p8a, packet, proposal, review)
    model["decision"]["status"] = "OFFLINE_FIXTURE"
    model["decision"]["binding"]["status"] = "OFFLINE_FIXTURE"
    model["decision"]["offline_fixture"] = True
    _write_json(run_dir / "candidate.json", proposal.model_dump(mode="json"))
    _write_json(run_dir / "review.json", review.model_dump(mode="json"))
    _write_json(run_dir / "model.json", model)
    return model


def _write_output(p8a: dict[str, Any], model: dict[str, Any], output: Path, run_dir: Path) -> None:
    output_model = _compose_model_input(p8a, model)
    output.parent.mkdir(parents=True, exist_ok=True)
    _write_json(output, output_model)
    _write_json(run_dir / "model-input.json", output_model)


def _run_cli(args: argparse.Namespace) -> None:
    p8a_path = Path(args.p8a_model)
    if not p8a_path.exists():
        raise FinancingError(f"accepted P8A model is missing: {p8a_path}")
    p8a = json.loads(p8a_path.read_text(encoding="utf-8"))
    run_dir = Path(args.run_dir)
    if args.offline:
        model = run_offline(p8a, run_dir, source_table=Path(args.source_table) if args.source_table else None)
    else:
        model = run_reasoning(p8a, run_dir, Path(args.budget), source_table=Path(args.source_table) if args.source_table else None, client=None)
    _write_output(p8a, model, Path(args.output), run_dir)
    print(json.dumps({"status": model["decision"]["status"], "output": str(args.output), "run_dir": str(run_dir), "calibration": model["forecast"]["opening_calibration"]}, indent=2))


def _prepare_cli(args: argparse.Namespace) -> None:
    p8a = json.loads(Path(args.p8a_model).read_text(encoding="utf-8"))
    print(json.dumps(prepare_live_handoff(p8a, Path(args.run_dir), source_table=Path(args.source_table) if args.source_table else None, output_path=Path(args.output), budget_path=Path(args.budget) if args.budget else None), indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--p8a-model", default="data/build-guide-p8a/live-r5/model-input.json")
    parser.add_argument("--output", default="data/build-guide-p8b/live-r2/model-input.json")
    parser.add_argument("--run-dir", default="data/build-guide-p8b/live-r2")
    parser.add_argument("--source-table", default=None)
    parser.add_argument("--budget", default="data/build-guide-api-budget.json")
    parser.add_argument("--offline", action="store_true", help="Use the explicitly labeled deterministic fixture")
    parser.add_argument("--prepare", action="store_true", help="Prepare the real request without dispatch")
    args = parser.parse_args()
    if args.prepare:
        _prepare_cli(args)
    else:
        _run_cli(args)


if __name__ == "__main__":
    main()
