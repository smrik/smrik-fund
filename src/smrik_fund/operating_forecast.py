"""P6 segment revenue and consolidated operating-cost forecast.

This module owns the small P6 analytical boundary.  It reads frozen P2 exports,
keeps disclosed reportable business segments separate from geographic/product
alternatives, and emits validated driver inputs for the shared P5 asset engine.
Mog/Excel formulas are the forecast authority; Python keeps diagnostic arithmetic
only for source-contract checks and comparison metadata.
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
from pydantic import BaseModel, ConfigDict, Field

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
TASK_ID = "p6-msft-operating-slice"
MAX_ATTEMPTS = 12
MAX_COMMITTED_EUR = 0.50
PERIODS = ("FY2026_STUB", "FY2027", "FY2028", "FY2029", "FY2030", "FY2031", "FY2032", "FY2033", "FY2034", "FY2035", "FY2036")
SEGMENTS = ("Intelligent Cloud", "More Personal Computing", "Productivity and Business Processes")
COST_LINES = ("cost_of_revenue", "research_and_development", "sales_and_marketing", "general_and_administrative")
REV_CONCEPT = "us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax"
OP_CONCEPT = "us-gaap_OperatingIncomeLoss"
COST_CONCEPTS = {
    "cost_of_revenue": "us-gaap_CostOfGoodsAndServicesSold",
    "research_and_development": "us-gaap_ResearchAndDevelopmentExpense",
    "sales_and_marketing": "us-gaap_SellingAndMarketingExpense",
    "general_and_administrative": "us-gaap_GeneralAndAdministrativeExpense",
}
SCHEMA_VERSION = "p6-operating-proposal-v2"
PROMPT_VERSION = "p6-operating-reasoning-v2"
METHOD_CATALOG_VERSION = "p6-operating-methods-v2"
REASONING_EFFORT = "high"
MAX_OUTPUT_TOKENS = 8_000
INITIAL_ANALYST_PURPOSE = "initial analyst selection"
INITIAL_ANALYST_INSTRUCTION = (
    "Select a bounded P6 operating forecast from the frozen packet. Use the current versus prior comparable YTD "
    "segment growth for the FY2026 stub and explicit bounded analyst estimates for FY2027-FY2036. Keep reportable "
    "business segments separate from geography/product alternatives, costs consolidated, PP&E replaced once, and "
    "SBC/other amortization embedded pending P8. Return only a structured proposal."
)
BINDING_HASH_FIELDS = ("candidate_hash", "review_hash", "context_hash", "source_packet_hash")


class OperatingForecastError(ValueError):
    """P6 source, proposal, or review contract failure."""


class SegmentTrajectory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment: Literal["Intelligent Cloud", "More Personal Computing", "Productivity and Business Processes"]
    method_id: Literal["segment_revenue_growth"]
    method_version: Literal["v1"]
    stub_growth: float
    annual_growth: list[float] = Field(min_length=10, max_length=10)
    downside_growth: float
    upside_growth: float
    evidence_refs: list[str] = Field(min_length=1)
    rationale: str = Field(min_length=1)
    uncertainty: str = Field(min_length=1)


class CostTrajectory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cost_line: Literal["cost_of_revenue", "research_and_development", "sales_and_marketing", "general_and_administrative"]
    method_id: Literal["consolidated_cost_ratio"]
    method_version: Literal["v1"]
    stub_ratio: float
    annual_ratio: list[float] = Field(min_length=10, max_length=10)
    downside_ratio: float
    upside_ratio: float
    evidence_refs: list[str] = Field(min_length=1)
    rationale: str = Field(min_length=1)
    uncertainty: str = Field(min_length=1)


class OperatingProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["propose_forecast", "unresolved", "capability_gap"]
    method_id: Literal["segment_revenue_growth_plus_consolidated_cost_ratios"] | None
    method_version: Literal["v1"] | None
    ppe_treatment: Literal["replace_embedded_once"]
    sbc_treatment: Literal["retain_embedded_pending_p8"]
    segment_trajectories: list[SegmentTrajectory]
    cost_trajectories: list[CostTrajectory]
    evidence_refs: list[str] = Field(min_length=1)
    rationale: str = Field(min_length=1)
    alternatives: list[str]
    uncertainty: list[str]
    follow_up_request: str | None


class OperatingReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["accept", "revise", "reject"]
    evidence_strength: Literal["strong", "mixed", "weak"]
    method_valid: bool
    source_valid: bool
    period_valid: bool
    segment_reconciliation_valid: bool
    cost_treatment_valid: bool
    no_double_count: bool
    concerns: list[str] = Field(min_length=1)
    required_revision: str | None
    target: Literal["none", "segment_growth", "cost_ratio"]
    rationale: str = Field(min_length=1)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _dimensions(row: dict[str, str]) -> list[dict[str, Any]]:
    try:
        value = json.loads(row.get("dimensions", "[]"))
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []


def _segment_row(row: dict[str, str], segment: str) -> bool:
    return any(
        item.get("dimension_label") == "us-gaap:StatementBusinessSegmentsAxis"
        and item.get("member_label") == segment
        for item in _dimensions(row)
    )


def _segment_definition(row: dict[str, str]) -> tuple[tuple[str | None, str | None, str | None], ...]:
    """Return the stable business-segment identity carried by one source row."""
    values = [
        (
            item.get("dimension_label"),
            item.get("member"),
            item.get("member_label"),
        )
        for item in _dimensions(row)
        if item.get("dimension_label") == "us-gaap:StatementBusinessSegmentsAxis"
    ]
    return tuple(sorted(values, key=repr))


def _fact(rows: list[dict[str, str]], concept: str, period: str, *, segment: str | None = None) -> dict[str, Any]:
    matches = [
        row for row in rows
        if row.get("concept") == concept
        and row.get("period_name") == period
        and (row.get("label") == segment if segment is not None else row.get("dimension") == "False")
        and (segment is None or _segment_row(row, segment))
    ]
    if len(matches) != 1:
        who = segment or "consolidated"
        raise OperatingForecastError(f"Expected one {who} {concept} {period} fact; found {len(matches)}")
    row = matches[0]
    try:
        value = float(row["display_value"])
    except (KeyError, TypeError, ValueError) as exc:
        raise OperatingForecastError(f"Non-numeric display value for {concept} {period}") from exc
    if not math.isfinite(value):
        raise OperatingForecastError(f"Missing/non-finite display value for {concept} {period}")
    dimensions = _dimensions(row)
    return {
        "value": value,
        "label": row.get("label"),
        "period": period,
        "concept": concept,
        "accession": row.get("source_accession") or row.get("accession"),
        "filing_date": row.get("filing_date"),
        "source_locator": row.get("source_locator"),
        "source_fact_id": row.get("source_fact_id"),
        "basis": row.get("numeric_basis"),
        "unit": row.get("unit"),
        "period_key": row.get("period_key"),
        "source_selection_status": row.get("source_selection_status"),
        "dimensions": dimensions,
        "segment_definition": _segment_definition(row) if segment is not None else None,
    }


def _evidence(evidence_id: str, fact: dict[str, Any], source_file: Path, kind: str = "statement") -> dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "kind": kind,
        "period": fact["period"],
        "excerpt": f"{fact['label']}: {fact['value']:,.3f} USD millions ({fact['basis']})",
        "source_file": str(source_file).replace("\\", "/"),
        "source_locator": fact["source_locator"],
        "source_sha256": _sha256(source_file),
        "source_accession": fact["accession"],
        "source_fact_id": fact["source_fact_id"],
        "filing_date": fact["filing_date"],
    }


def _source_identity(fact: dict[str, Any], source_file: Path) -> dict[str, Any]:
    """Keep the selected fact identity beside the value used in a forecast."""
    return {
        "source_file": str(source_file).replace("\\", "/"),
        "source_sha256": _sha256(source_file),
        "source_locator": fact.get("source_locator"),
        "source_fact_id": fact.get("source_fact_id"),
        "accession": fact.get("accession"),
        "filing_date": fact.get("filing_date"),
        "period_key": fact.get("period_key"),
        "unit": fact.get("unit"),
        "basis": fact.get("basis"),
    }


def build_evidence_packet(p2_root: Path) -> dict[str, Any]:
    """Read only the frozen P2 history exports up to the approved cutoff."""
    annual_path = p2_root / "annual_history.csv"
    ytd_path = p2_root / "ytd_history.csv"
    ttm_path = p2_root / "ttm_history.csv"
    manifest_path = p2_root / "source_manifest.json"
    annual, ytd, ttm = _read(annual_path), _read(ytd_path), _read(ttm_path)
    evidence: list[dict[str, Any]] = []
    segment_history: dict[str, dict[str, dict[str, float]]] = {}
    segment_facts: dict[str, dict[str, dict[str, Any]]] = {}
    for segment in SEGMENTS:
        segment_history[segment] = {"revenue": {}, "operating_income": {}}
        segment_facts[segment] = {}
        for metric, concept in (("revenue", REV_CONCEPT), ("operating_income", OP_CONCEPT)):
            for year in ("FY2023", "FY2024", "FY2025"):
                fact = _fact(annual, concept, year, segment=segment)
                segment_history[segment][metric][year] = fact["value"]
                evidence.append(_evidence(f"S-{segment[:2].upper()}-{metric}-{year}", fact, annual_path))
                if year == "FY2025":
                    segment_facts[segment].setdefault("FY2025", {})[metric] = {
                        **fact,
                        "source_file": str(annual_path).replace("\\", "/"),
                    }
            for period, suffix in (("Current YTD", "CURRENT"), ("Prior comparable YTD", "PRIOR")):
                fact = _fact(ytd, concept, period, segment=segment)
                segment_history[segment][metric][suffix] = fact["value"]
                evidence.append(_evidence(f"Y-{segment[:2].upper()}-{metric}-{suffix}", fact, ytd_path))
                segment_facts[segment].setdefault(suffix, {})[metric] = {
                    **fact,
                    "source_file": str(ytd_path).replace("\\", "/"),
                }
    segment_definitions: dict[str, dict[str, list[tuple[str | None, str | None, str | None]]]] = {}
    segment_sources: dict[str, dict[str, dict[str, Any]]] = {}
    for segment in SEGMENTS:
        segment_definitions[segment] = {}
        segment_sources[segment] = {}
        reference_definition: tuple[tuple[str | None, str | None, str | None], ...] | None = None
        for period in ("FY2025", "CURRENT", "PRIOR"):
            facts = segment_facts[segment].get(period, {})
            if set(facts) != {"revenue", "operating_income"}:
                raise OperatingForecastError(
                    f"Missing comparable segment facts for {segment} {period}"
                )
            definitions = {fact.get("segment_definition") for fact in facts.values()}
            if len(definitions) != 1:
                raise OperatingForecastError(
                    f"Incompatible segment period definition within {segment} {period}"
                )
            definition = next(iter(definitions))
            if not definition:
                raise OperatingForecastError(
                    f"Missing segment period definition for {segment} {period}"
                )
            if reference_definition is None:
                reference_definition = definition
            elif definition != reference_definition:
                raise OperatingForecastError(
                    f"Incompatible segment period definition for {segment}: {period}"
                )
            segment_definitions[segment][period] = [list(item) for item in definition]
            segment_sources[segment][period] = {
                metric: _source_identity(fact, Path(fact["source_file"]))
                for metric, fact in facts.items()
            }
    recast_path = p2_root / "source_recast_comparisons.csv"
    recast_summary: dict[str, Any] = {"status": "NOT_PROVIDED"}
    if recast_path.exists():
        recast_rows = _read(recast_path)
        counts: dict[str, int] = {}
        for row in recast_rows:
            status = row.get("status") or "UNKNOWN"
            counts[status] = counts.get(status, 0) + 1
        recast_summary = {
            "status": "PASS" if counts and set(counts) == {"PASS"} else "MIXED",
            "source_file": str(recast_path).replace("\\", "/"),
            "source_sha256": _sha256(recast_path),
            "row_count": len(recast_rows),
            "status_counts": counts,
        }
    costs: dict[str, dict[str, float]] = {}
    cost_facts: dict[str, dict[str, dict[str, Any]]] = {}
    for line in COST_LINES:
        concept = COST_CONCEPTS[line]
        costs[line] = {}
        cost_facts[line] = {}
        for period, rows, suffix in (("FY2025", annual, "FY2025"), ("Current YTD", ytd, "CURRENT_YTD"), ("Prior comparable YTD", ytd, "PRIOR_YTD"), ("TTM to 2026-03-31", ttm, "TTM")):
            fact = _fact(rows, concept, period)
            costs[line][suffix] = fact["value"]
            cost_facts[line][suffix] = fact
            source_path = annual_path if period == "FY2025" else ytd_path if "YTD" in period else ttm_path
            evidence.append(_evidence(f"C-{line}-{suffix}", fact, source_path))
    consolidated: dict[str, dict[str, float]] = {"revenue": {}, "operating_income": {}}
    for metric, concept in (("revenue", REV_CONCEPT), ("operating_income", OP_CONCEPT)):
        for period, rows, suffix in (("FY2023", annual, "FY2023"), ("FY2024", annual, "FY2024"), ("FY2025", annual, "FY2025"), ("Current YTD", ytd, "CURRENT_YTD"), ("Prior comparable YTD", ytd, "PRIOR_YTD"), ("TTM to 2026-03-31", ttm, "TTM")):
            fact = _fact(rows, concept, period)
            consolidated[metric][suffix] = fact["value"]
            evidence.append(_evidence(f"K-{metric}-{suffix}", fact, annual_path if rows is annual else ytd_path if rows is ytd else ttm_path))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    return {
        "schema_version": "p6-msft-evidence-v2",
        "case": CASE,
        "information_cutoff": INFORMATION_CUTOFF,
        "measurement_date": MEASUREMENT_DATE,
        "source_root": str(p2_root).replace("\\", "/"),
        "source_manifest_sha256": _sha256(manifest_path) if manifest_path.exists() else None,
        "segment_history": segment_history,
        "segment_comparability": {
            "status": "COMPATIBLE",
            "axis": "us-gaap:StatementBusinessSegmentsAxis",
            "periods": {
                "FY2025": "annual FY2025",
                "CURRENT": "current comparable YTD through 2026-03-31",
                "PRIOR": "prior comparable YTD through 2025-03-31",
            },
            "definitions": segment_definitions,
            "source_identity": segment_sources,
            "recast_comparison": recast_summary,
        },
        "consolidated": consolidated,
        "costs": costs,
        "evidence": evidence,
        "alternatives": [
            "Geographic revenue alternatives are retained as a separate source view and are not mixed into reportable business segments.",
            "Product/service revenue alternatives are retained as a separate source view and are not used for this forecast.",
        ],
        "source_manifest": manifest,
        "unavailable": [
            "Segment-level cost allocation is undisclosed; operating costs remain consolidated.",
            "Embedded other amortization and SBC remain in consolidated costs pending P8C/P8D; PP&E depreciation is substituted once by P5 schedules.",
        ],
    }


def default_proposal(packet: dict[str, Any]) -> OperatingProposal:
    comparability = packet.get("segment_comparability", {})
    if comparability.get("status") != "COMPATIBLE":
        raise OperatingForecastError("Segment source comparability is not compatible")
    history = packet["segment_history"]
    trajectories: list[SegmentTrajectory] = []
    decay = (0.80, 0.65, 0.50, 0.40, 0.30, 0.22, 0.15, 0.10, 0.05, 0.0)
    for segment in SEGMENTS:
        current = history[segment]["revenue"]["CURRENT"]
        prior = history[segment]["revenue"]["PRIOR"]
        if prior is None:
            raise OperatingForecastError(f"Missing prior comparable YTD for {segment}")
        if prior == 0:
            raise OperatingForecastError(
                f"Zero prior comparable YTD cannot derive growth for {segment}"
            )
        growth = current / prior - 1
        refs = [f"Y-{segment[:2].upper()}-revenue-CURRENT", f"Y-{segment[:2].upper()}-revenue-PRIOR", f"S-{segment[:2].upper()}-revenue-FY2025"]
        trajectories.append(SegmentTrajectory(segment=segment, method_id="segment_revenue_growth", method_version="v1", stub_growth=growth, annual_growth=[growth * factor for factor in decay], downside_growth=growth - 0.05, upside_growth=growth + 0.05, evidence_refs=refs, rationale="Comparable current YTD versus prior comparable YTD growth, followed by an explicit mean-reversion path.", uncertainty="FY2026 stub uses prior-year comparable Q4; later estimates are analyst-selected trajectories."))
    cost_trajectories: list[CostTrajectory] = []
    revenue = packet["consolidated"]["revenue"]
    for line in COST_LINES:
        c = packet["costs"][line]
        if revenue["TTM"] is None or revenue["FY2025"] is None or revenue["PRIOR_YTD"] is None:
            raise OperatingForecastError(f"Missing consolidated revenue anchor for {line}")
        if revenue["TTM"] == 0:
            raise OperatingForecastError(f"Zero TTM revenue cannot derive cost ratio for {line}")
        stub_denominator = revenue["FY2025"] - revenue["PRIOR_YTD"]
        if stub_denominator == 0:
            raise OperatingForecastError(f"Zero FY2025 stub revenue cannot derive cost ratio for {line}")
        ttm_ratio = c["TTM"] / revenue["TTM"]
        stub_ratio = (c["FY2025"] - c["PRIOR_YTD"]) / stub_denominator
        refs = [f"C-{line}-TTM", f"C-{line}-FY2025", f"C-{line}-PRIOR_YTD"]
        cost_trajectories.append(CostTrajectory(cost_line=line, method_id="consolidated_cost_ratio", method_version="v1", stub_ratio=stub_ratio, annual_ratio=[ttm_ratio] * 10, downside_ratio=ttm_ratio + 0.02, upside_ratio=max(0.0, ttm_ratio - 0.02), evidence_refs=refs, rationale="Consolidated reported cost ratio; no unsupported segment allocation is introduced.", uncertainty="Cost ratios hold at TTM level after the explicitly derived FY2026 stub."))
    return OperatingProposal(outcome="propose_forecast", method_id="segment_revenue_growth_plus_consolidated_cost_ratios", method_version="v1", ppe_treatment="replace_embedded_once", sbc_treatment="retain_embedded_pending_p8", segment_trajectories=trajectories, cost_trajectories=cost_trajectories, evidence_refs=["S-IC-revenue-FY2025", "Y-IC-revenue-CURRENT", "C-cost_of_revenue-TTM"], rationale="Narrow reportable business segments drive revenue; consolidated reported costs drive the operating lines.", alternatives=packet["alternatives"], uncertainty=packet["unavailable"], follow_up_request=None)


def validate_proposal(proposal: OperatingProposal, packet: dict[str, Any]) -> None:
    comparability = packet.get("segment_comparability", {})
    if comparability.get("status") != "COMPATIBLE":
        raise OperatingForecastError("Segment source comparability is not compatible")
    if proposal.outcome != "propose_forecast" or proposal.method_id != "segment_revenue_growth_plus_consolidated_cost_ratios" or proposal.method_version != "v1" or proposal.ppe_treatment != "replace_embedded_once" or proposal.sbc_treatment != "retain_embedded_pending_p8":
        raise OperatingForecastError("P6 proposal does not implement the supported method")
    if {item.segment for item in proposal.segment_trajectories} != set(SEGMENTS) or len(proposal.segment_trajectories) != len(SEGMENTS):
        raise OperatingForecastError("P6 proposal must contain each disclosed segment exactly once")
    if {item.cost_line for item in proposal.cost_trajectories} != set(COST_LINES) or len(proposal.cost_trajectories) != len(COST_LINES):
        raise OperatingForecastError("P6 proposal must contain each consolidated cost line exactly once")
    for item in proposal.segment_trajectories:
        if any(abs(value) > 1 for value in item.annual_growth + [item.stub_growth, item.downside_growth, item.upside_growth]):
            raise OperatingForecastError(f"Unbounded segment growth for {item.segment}")
        if any(ref not in {entry["evidence_id"] for entry in packet["evidence"]} for ref in item.evidence_refs):
            raise OperatingForecastError(f"Unknown evidence for {item.segment}")
    for item in proposal.cost_trajectories:
        if any(value < 0 or value > 1 for value in item.annual_ratio + [item.stub_ratio, item.downside_ratio, item.upside_ratio]):
            raise OperatingForecastError(f"Cost ratio outside [0,1] for {item.cost_line}")
        if any(ref not in {entry["evidence_id"] for entry in packet["evidence"]} for ref in item.evidence_refs):
            raise OperatingForecastError(f"Unknown evidence for {item.cost_line}")


def _finite_number(value: Any, name: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise OperatingForecastError(f"Missing/non-numeric {name}")
    result = float(value)
    if minimum is not None and result < minimum:
        raise OperatingForecastError(f"Invalid {name}: {result}")
    return result


def _embedded_ppe_baseline(packet: dict[str, Any]) -> dict[str, Any] | None:
    """Resolve the P5 reported PP&E depreciation baseline without guessing."""
    candidate = packet.get("embedded_ppe_baseline")
    if candidate is None:
        p5_packet = packet.get("p5_packet")
        if isinstance(p5_packet, dict):
            candidate = p5_packet.get("embedded_ppe_baseline")
            facts = p5_packet.get("facts", {})
            calculated = facts.get("calculated", {}) if isinstance(facts, dict) else {}
            ttm = facts.get("ttm", {}) if isinstance(facts, dict) else {}
            if candidate is None and isinstance(calculated, dict):
                depreciation = calculated.get("ttm_ppe_depreciation")
                revenue_fact = ttm.get("revenue") if isinstance(ttm, dict) else None
                revenue = revenue_fact.get("value") if isinstance(revenue_fact, dict) else None
                if depreciation is not None and revenue is not None:
                    candidate = {
                        "ttm_ppe_depreciation": depreciation,
                        "ttm_revenue": revenue,
                        "basis": "P5 calculated TTM PP&E-only depreciation / TTM revenue",
                        "scope": "aggregate consolidated PP&E-only depreciation proxy",
                        "evidence_refs": ["E3", "E4", "E5"],
                    }
    if candidate is None:
        facts = packet.get("facts")
        if isinstance(facts, dict):
            calculated = facts.get("calculated", {})
            ttm = facts.get("ttm", {})
            depreciation = calculated.get("ttm_ppe_depreciation") if isinstance(calculated, dict) else None
            revenue_fact = ttm.get("revenue") if isinstance(ttm, dict) else None
            revenue = revenue_fact.get("value") if isinstance(revenue_fact, dict) else None
            if depreciation is not None and revenue is not None:
                candidate = {
                    "ttm_ppe_depreciation": depreciation,
                    "ttm_revenue": revenue,
                    "basis": "P5 calculated TTM PP&E-only depreciation / TTM revenue",
                    "scope": "aggregate consolidated PP&E-only depreciation proxy",
                    "evidence_refs": ["E3", "E4", "E5"],
                }
    if not isinstance(candidate, dict):
        return None
    depreciation = _finite_number(candidate.get("ttm_ppe_depreciation"), "TTM PP&E depreciation", minimum=0)
    revenue = _finite_number(candidate.get("ttm_revenue"), "TTM revenue", minimum=0)
    if revenue == 0:
        raise OperatingForecastError("TTM revenue cannot be zero for the PP&E baseline")
    ratio_value = candidate.get("ratio")
    ratio = _finite_number(ratio_value if ratio_value is not None else depreciation / revenue, "embedded PP&E ratio", minimum=0)
    if ratio > 1:
        raise OperatingForecastError("Embedded PP&E ratio exceeds 100%")
    return {
        **candidate,
        "ttm_ppe_depreciation": depreciation,
        "ttm_revenue": revenue,
        "ratio": ratio,
        "basis": candidate.get("basis") or "TTM PP&E-only depreciation / TTM revenue",
        "scope": candidate.get("scope") or "aggregate consolidated PP&E-only depreciation proxy",
        "evidence_refs": list(candidate.get("evidence_refs") or []),
    }


def _scheduled_depreciation(packet: dict[str, Any], periods: int) -> list[float] | None:
    for key in ("authoritative_scheduled_depreciation", "scheduled_depreciation"):
        value = packet.get(key)
        if value is not None:
            if not isinstance(value, list) or len(value) != periods:
                raise OperatingForecastError("Authoritative scheduled depreciation shape is invalid")
            return [_finite_number(item, f"scheduled depreciation {index}", minimum=0) for index, item in enumerate(value)]
    consequences = packet.get("authoritative_mog") or packet.get("authoritative_financial_consequences")
    if isinstance(consequences, dict):
        bridge = consequences.get("operatingBridge") if isinstance(consequences.get("operatingBridge"), dict) else {}
        if not bridge and isinstance(consequences.get("snapshot"), dict):
            bridge = consequences["snapshot"].get("operatingBridge", {})
        value = consequences.get("scheduled_depreciation") or consequences.get("total_depreciation") or bridge.get("scheduledPpeAdded")
        if value is not None:
            if not isinstance(value, list) or len(value) != periods:
                raise OperatingForecastError("Authoritative Mog depreciation shape is invalid")
            return [_finite_number(item, f"scheduled depreciation {index}", minimum=0) for index, item in enumerate(value)]
    return None


def _authoritative_consequence_payload(packet: dict[str, Any], preview: dict[str, Any]) -> dict[str, Any]:
    """Expose the actual Mog bridge when a caller has already recalculated it."""
    value = packet.get("authoritative_mog") or packet.get("authoritative_financial_consequences")
    if isinstance(value, dict):
        return value
    return {
        "status": "NOT_ATTACHED",
        "engine": "Mog SDK",
        "message": "Reviewer payload requires a persisted Mog recalculation before publication.",
        "preview_hash": content_hash(preview),
    }


def review_proposal(proposal: OperatingProposal, packet: dict[str, Any]) -> OperatingReview:
    try:
        validate_proposal(proposal, packet)
        return OperatingReview(verdict="accept", evidence_strength="mixed", method_valid=True, source_valid=True, period_valid=True, segment_reconciliation_valid=True, cost_treatment_valid=True, no_double_count=True, concerns=["Later-year growth and cost ratios are estimates and remain provisional."], required_revision=None, target="none", rationale="Supported reportable segment growth and consolidated cost ratios are traceable to frozen P2 facts; PP&E depreciation substitution remains in P5 schedules.")
    except OperatingForecastError as exc:
        return OperatingReview(verdict="reject", evidence_strength="weak", method_valid=False, source_valid=False, period_valid=False, segment_reconciliation_valid=False, cost_treatment_valid=False, no_double_count=False, concerns=[str(exc)], required_revision="Repair the proposal against the frozen evidence packet.", target="segment_growth", rationale="The proposal failed the deterministic P6 contract.")


def _forecast_segment(packet: dict[str, Any], trajectory: SegmentTrajectory) -> list[float]:
    hist = packet["segment_history"][trajectory.segment]["revenue"]
    prior_q4 = hist["FY2025"] - hist["PRIOR"]
    stub = prior_q4 * (1 + trajectory.stub_growth)
    fy26 = hist["CURRENT"] + stub
    values = [stub]
    prior_fy = fy26
    for growth in trajectory.annual_growth:
        prior_fy = prior_fy * (1 + growth)
        values.append(prior_fy)
    return values


def build_operating_model(packet: dict[str, Any], proposal: OperatingProposal, review: OperatingReview) -> dict[str, Any]:
    validate_proposal(proposal, packet)
    if review.verdict != "accept" or not review.no_double_count:
        raise OperatingForecastError("P6 review did not accept the candidate")
    seg_values = {item.segment: _forecast_segment(packet, item) for item in proposal.segment_trajectories}
    consolidated_forecast = [sum(seg_values[s][i] for s in SEGMENTS) for i in range(len(PERIODS))]
    costs = {item.cost_line: [consolidated_forecast[0] * item.stub_ratio, *[consolidated_forecast[i + 1] * item.annual_ratio[i] for i in range(10)]] for item in proposal.cost_trajectories}
    history = packet["segment_history"]
    segment_period = {"FY2023": "FY2023", "FY2024": "FY2024", "FY2025": "FY2025", "CURRENT_YTD": "CURRENT", "PRIOR_YTD": "PRIOR"}
    corp = {period: packet["consolidated"]["revenue"][period] - sum(history[s]["revenue"][segment_key] for s in SEGMENTS) for period, segment_key in segment_period.items()}
    reconciliation: dict[str, float] = {}
    for period, segment_key in segment_period.items():
        reconciliation[period] = packet["consolidated"]["revenue"][period] - (sum(history[s]["revenue"][segment_key] for s in SEGMENTS) + corp[period])
    for i, period in enumerate(PERIODS):
        reconciliation[period] = consolidated_forecast[i] - sum(seg_values[s][i] for s in SEGMENTS)
    forecast_cost_total = [sum(costs[line][i] for line in COST_LINES) for i in range(len(PERIODS))]
    baseline = _embedded_ppe_baseline(packet)
    scheduled = _scheduled_depreciation(packet, len(PERIODS))
    embedded = [value * baseline["ratio"] for value in consolidated_forecast] if baseline else None
    if baseline and embedded is not None:
        if scheduled is not None:
            total_expenses = [
                forecast_cost_total[i] - embedded[i] + scheduled[i]
                for i in range(len(PERIODS))
            ]
            operating_income = [
                consolidated_forecast[i] - total_expenses[i]
                for i in range(len(PERIODS))
            ]
            bridge_status = "AUTHORITATIVE_MOG"
        else:
            total_expenses = None
            operating_income = [
                consolidated_forecast[i] - forecast_cost_total[i]
                for i in range(len(PERIODS))
            ]
            bridge_status = "BASELINE_READY_SCHEDULE_PENDING"
    else:
        total_expenses = None
        operating_income = [
            consolidated_forecast[i] - forecast_cost_total[i]
            for i in range(len(PERIODS))
        ]
        bridge_status = "BASELINE_UNAVAILABLE"
    historical_residuals = {
        period: corp[period]
        for period in ("FY2023", "FY2024", "FY2025", "CURRENT_YTD", "PRIOR_YTD")
    }
    forecast_identity = {period: reconciliation[period] for period in PERIODS}
    driver_inputs = {
        "segment_growth": {
            item.segment: {"stub": item.stub_growth, "annual": list(item.annual_growth)}
            for item in proposal.segment_trajectories
        },
        "cost_ratio": {
            item.cost_line: {"stub": item.stub_ratio, "annual": list(item.annual_ratio)}
            for item in proposal.cost_trajectories
        },
        "historical_anchors": {
            segment: {
                "priorFy": history[segment]["revenue"]["FY2025"],
                "priorYtd": history[segment]["revenue"]["PRIOR"],
                "currentYtd": history[segment]["revenue"]["CURRENT"],
            }
            for segment in SEGMENTS
        },
        "source_observations_are_not_forecast_inputs": True,
    }
    return {
        "schema_version": "p6-msft-operating-model-v1",
        "repair_version": "p6-repair-r3",
        "forecast_authority": "Mog formulas compiled by asset_model.mjs",
        "case": CASE,
        "information_cutoff": INFORMATION_CUTOFF,
        "measurement_date": MEASUREMENT_DATE,
        "periods": list(PERIODS),
        "method": {"id": proposal.method_id, "version": proposal.method_version},
        "segments": {segment: {"historical_revenue": history[segment]["revenue"], "forecast_revenue": values, "forecast_role": "diagnostic_only_not_workbook_authority"} for segment, values in seg_values.items()},
        "corporate_eliminations": {"historical_revenue": corp, "forecast_revenue": [0.0] * len(PERIODS), "basis": "Consolidated reported revenue less disclosed reportable business segments; forecast held at zero because the selected MSFT segment view reconciles."},
        "consolidated_revenue_history": packet["consolidated"]["revenue"],
        "forecast_revenue": consolidated_forecast,
        "costs": costs,
        "gross_cost_total": forecast_cost_total,
        "embedded_ppe_baseline": baseline,
        "embedded_ppe_depreciation": embedded,
        "scheduled_ppe_depreciation": scheduled,
        "expense_bridge": {
            "status": bridge_status,
            "gross_costs": forecast_cost_total,
            "embedded_removed": embedded,
            "scheduled_added": scheduled,
            "total_operating_expenses": total_expenses,
            "operating_income": operating_income if total_expenses is not None else None,
            "operating_margin": [
                operating_income[i] / consolidated_forecast[i]
                if consolidated_forecast[i] else None
                for i in range(len(PERIODS))
            ] if total_expenses is not None else None,
            "formula": "gross_costs - embedded_ttm_ppe_depreciation + scheduled_p5_ppe_depreciation",
            "embedded_basis": baseline.get("basis") if baseline else None,
        },
        "forecast_operating_income": operating_income,
        "stub_basis": "FY2026_STUB is a prior-year comparable Apr-Jun quarter derived from FY2025 less prior comparable YTD, grown by current versus prior comparable YTD segment growth; FY2027 starts from actual current YTD plus this forecast stub.",
        "reported_cost_basis": packet["costs"],
        "segment_comparability": packet.get("segment_comparability", {}),
        "evidence": packet["evidence"],
        "decision": {"status": "SYSTEM_REVIEWED_PROVISIONAL", "human_approval": False, "review": review.model_dump(mode="json"), "rationale": proposal.rationale, "alternatives": proposal.alternatives, "uncertainty": proposal.uncertainty},
        "limitations": packet["unavailable"] + ["P5 diagnostic terminal economics limitation remains open for P9; P6 does not implement later package policies."],
        "historical_residuals": historical_residuals,
        "forecast_identity": forecast_identity,
        "reconciliation": reconciliation,
        "driver_inputs": driver_inputs,
        "diagnostic_forecast": {
            "segments": seg_values,
            "consolidated_revenue": consolidated_forecast,
            "costs": costs,
            "gross_cost_total": forecast_cost_total,
            "operating_income": operating_income,
            "source": "Python contract diagnostic; Mog workbook outputs are authoritative",
        },
    }


def _forecast_preview(
    packet: dict[str, Any],
    proposal: OperatingProposal,
    authoritative_consequences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Give the reviewer the persisted Mog forward table, with diagnostic fallback only for tests."""
    consequence = authoritative_consequences or packet.get("authoritative_mog") or packet.get("authoritative_financial_consequences")
    mog_forecast: dict[str, Any] | None = None
    if isinstance(consequence, dict):
        candidate = consequence.get("operatingForecast")
        if not isinstance(candidate, dict) and isinstance(consequence.get("snapshot"), dict):
            candidate = consequence["snapshot"].get("operatingForecast")
        if isinstance(candidate, dict):
            required = candidate.get("segments"), candidate.get("consolidatedRevenue"), candidate.get("costs")
            if isinstance(required[0], dict) and isinstance(required[1], list) and isinstance(required[2], dict):
                mog_forecast = candidate
    if mog_forecast is not None:
        segments = mog_forecast["segments"]
        revenue = mog_forecast["consolidatedRevenue"]
        costs = mog_forecast["costs"]
        gross_costs = mog_forecast.get("grossCosts") or [sum(costs[line][i] for line in COST_LINES) for i in range(len(PERIODS))]
        forecast_source = "Mog SDK authoritative workbook formulas"
    else:
        segments = {item.segment: _forecast_segment(packet, item) for item in proposal.segment_trajectories}
        revenue = [sum(segments[segment][i] for segment in SEGMENTS) for i in range(len(PERIODS))]
        costs = {item.cost_line: [revenue[0] * item.stub_ratio, *[revenue[i + 1] * item.annual_ratio[i] for i in range(10)]] for item in proposal.cost_trajectories}
        gross_costs = [sum(costs[line][i] for line in COST_LINES) for i in range(len(PERIODS))]
        forecast_source = "Python diagnostic fallback; publication requires persisted Mog formulas"
    baseline = _embedded_ppe_baseline(packet)
    embedded = (mog_forecast.get("embeddedPpeRemoved") if mog_forecast is not None else [value * baseline["ratio"] for value in revenue]) if baseline else None
    scheduled = mog_forecast.get("scheduledPpeAdded") if mog_forecast is not None else None
    if isinstance(consequence, dict):
        bridge = consequence.get("operatingBridge") if isinstance(consequence.get("operatingBridge"), dict) else {}
        if not bridge and isinstance(consequence.get("snapshot"), dict):
            bridge = consequence["snapshot"].get("operatingBridge", {})
        scheduled = scheduled or consequence.get("scheduled_depreciation") or consequence.get("total_depreciation") or bridge.get("scheduledPpeAdded")
    if scheduled is not None and (not isinstance(scheduled, list) or len(scheduled) != len(PERIODS)):
        raise OperatingForecastError("Authoritative Mog depreciation shape is invalid")
    total_expenses = (
        [gross_costs[i] - embedded[i] + float(scheduled[i]) for i in range(len(PERIODS))]
        if embedded is not None and scheduled is not None
        else None
    )
    return {
        "periods": list(PERIODS),
        "segment_revenue": segments,
        "consolidated_revenue": revenue,
        "costs": costs,
        "gross_costs": gross_costs,
        "embedded_ppe_depreciation": embedded,
        "scheduled_ppe_depreciation": scheduled,
        "total_operating_expenses": total_expenses,
        "operating_income": [revenue[i] - total_expenses[i] for i in range(len(PERIODS))] if total_expenses else [revenue[i] - gross_costs[i] for i in range(len(PERIODS))],
        "authoritative_financial_consequences": consequence if isinstance(consequence, dict) else {"status": "NOT_ATTACHED"},
        "forecast_source": forecast_source,
        "reconciliation": dict.fromkeys(PERIODS, 0.0),
        "stub_basis": "prior-year comparable Apr-Jun quarter, grown by current versus prior comparable YTD; FY2027 base is actual current YTD plus this stub",
        "ppe_bridge": "P5 total PP&E depreciation replaces the aggregate TTM embedded PP&E depreciation once: gross costs minus embedded baseline plus scheduled P5 depreciation. Reported other amortization and SBC stay in consolidated costs.",
        "sbc_bridge": "SBC remains embedded pending P8; any later treatment is a replacement of the embedded amount, never an incremental add-back.",
    }


def _request(instruction: str, payload: dict[str, Any], response_model: type[BaseModel]) -> dict[str, Any]:
    return {
        "model": MODEL,
        "reasoning": {"effort": REASONING_EFFORT},
        "service_tier": "default",
        "input": json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")),
        "instructions": instruction,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "operating_review" if response_model is OperatingReview else "operating_proposal",
                "strict": True,
                "schema": response_model.model_json_schema(),
            }
        },
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "tools": [],
        "background": False,
    }


def _initial_analyst_request(packet: dict[str, Any], context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build the exact initial analyst payload/request used by runtime and offline capture."""
    payload = _proposal_payload(packet, context, purpose=INITIAL_ANALYST_PURPOSE)
    return payload, _request(INITIAL_ANALYST_INSTRUCTION, payload, OperatingProposal)


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


def _parse_structured_response(response: Any, response_model: type[BaseModel]) -> BaseModel:
    value = _response_value(response)
    if isinstance(value, response_model):
        return value
    if isinstance(value, str):
        return response_model.model_validate_json(value)
    if isinstance(value, dict):
        return response_model.model_validate(value)
    raise OperatingForecastError("Provider response contained no structured output")


def _is_p6_call(call: dict[str, Any]) -> bool:
    task_id = str(call.get("task_id") or "")
    call_id = str(call.get("call_id") or "")
    return task_id == TASK_ID or task_id == "p6-analyst-1" or call_id.startswith("p6-")


def _ledger_p6_state(budget_path: Path, call_filter: Any = _is_p6_call) -> tuple[int, float]:
    state = json.loads(budget_path.read_text(encoding="utf-8"))
    calls = [item for item in state.get("calls", []) if call_filter(item)]
    total = sum(item.get("cost", {}).get("priced_eur", item.get("reserved_eur", 0.0)) for item in calls)
    return len(calls), float(total)


def _replay_lineage(budget_path: Path, call_filter: Any = _is_p6_call, task_id: str = TASK_ID) -> dict[str, Any]:
    """Describe historical P6 hash collisions without relabelling their outcomes."""
    if not budget_path.exists():
        return {"status": "BUDGET_NOT_FOUND", "groups": []}
    state = json.loads(budget_path.read_text(encoding="utf-8"))
    groups: dict[str, list[dict[str, Any]]] = {}
    for call in state.get("calls", []):
        if call_filter(call) and call.get("request_hash"):
            groups.setdefault(call["request_hash"], []).append(call)
    collisions = []
    for request_hash, calls in groups.items():
        if len(calls) > 1:
            collisions.append({
                "request_hash": request_hash,
                "call_ids": [call.get("call_id") for call in calls],
                "task_ids": [call.get("task_id") for call in calls],
                "statuses": [call.get("status") for call in calls],
                "lineage_status": "UNLINKED_HISTORICAL_DUPLICATE",
                "interpretation": "Same request hash is auditable; the historical retry is not relabelled as a successful exact resume and no provider receipt or prior approval is inferred.",
            })
    return {"status": "RECORDED", "task": task_id, "groups": collisions}


def _prior_stage_result(
    attempts_dir: Path,
    stage: str,
    request_hash: str,
    response_model: type[BaseModel],
    budget_path: Path,
    call_filter: Any = _is_p6_call,
) -> tuple[BaseModel, dict[str, Any]] | None:
    """Resume a matching completed response or hold every unsettled match."""
    ledger = json.loads(budget_path.read_text(encoding="utf-8"))
    matches = [
        call for call in ledger.get("calls", [])
        if call_filter(call) and call.get("request_hash") == request_hash
    ]
    unknown_ids = [call.get("call_id") for call in matches if call.get("status") in {"reserved", "usage_unknown"}]
    if unknown_ids:
        raise OperatingForecastError(
            f"{stage} exact-hash call is held ({', '.join(str(value) for value in unknown_ids)}); explicit recovery required"
        )
    for request_path in sorted(attempts_dir.glob("*.request.json")):
        try:
            request = json.loads(request_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if content_hash(request) != request_hash:
            continue
        prefix = request_path.name[:-len(".request.json")]
        metadata_path = attempts_dir / f"{prefix}.metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
        metadata_stage = metadata.get("stage")
        if metadata_stage and metadata_stage != stage:
            continue
        outcome_path = attempts_dir / f"{prefix}.outcome.json"
        outcome = json.loads(outcome_path.read_text(encoding="utf-8")) if outcome_path.exists() else {}
        status = outcome.get("status")
        if status in {"reserved", "usage_unknown"}:
            raise OperatingForecastError(f"{stage} has a held prior {status} outcome; no duplicate dispatch is allowed")
        if matches and any(call.get("status") != "completed" for call in matches):
            raise OperatingForecastError(f"{stage} has an unsettled exact-hash ledger admission; no duplicate dispatch is allowed")
        if status != "completed" or not matches:
            continue
        structured_path = attempts_dir / f"{prefix}.structured.json"
        if structured_path.exists():
            value = response_model.model_validate(json.loads(structured_path.read_text(encoding="utf-8")))
        else:
            response_path = attempts_dir / f"{prefix}.response.json"
            if not response_path.exists():
                raise OperatingForecastError(f"{stage} completed without a persisted raw response; result is held")
            try:
                value = _parse_structured_response(json.loads(response_path.read_text(encoding="utf-8")), response_model)
            except Exception as exc:
                raise OperatingForecastError(f"{stage} completed output cannot be resumed: {exc}") from exc
            structured_path.write_text(json.dumps(value.model_dump(mode="json"), indent=2, ensure_ascii=False), encoding="utf-8")
        metadata["resumed"] = True
        metadata["resumed_call_ids"] = [call.get("call_id") for call in matches]
        return value, metadata
    if matches:
        raise OperatingForecastError(f"{stage} has a prior exact-hash admission without resumable local artifacts; stage held")
    return None


def _dispatch_structured(
    *,
    stage: str,
    run_dir: Path,
    budget_path: Path,
    instruction: str,
    payload: dict[str, Any],
    response_model: type[BaseModel],
    client: Any | None = None,
    call_id: str | None = None,
    prepared_request: dict[str, Any] | None = None,
    task_id: str = TASK_ID,
    max_attempts: int = MAX_ATTEMPTS,
    max_committed_eur: float = MAX_COMMITTED_EUR,
    call_filter: Any = _is_p6_call,
) -> tuple[BaseModel, dict[str, Any]]:
    """Persist one exact request, admit once, dispatch once, then parse."""
    request = prepared_request if prepared_request is not None else _request(instruction, payload, response_model)
    request_hash = content_hash(request)
    attempts = run_dir / "attempts"
    attempts.mkdir(parents=True, exist_ok=True)
    prior = _prior_stage_result(attempts, stage, request_hash, response_model, budget_path, call_filter)
    if prior is not None:
        return prior
    ordinal, committed = _ledger_p6_state(budget_path, call_filter)
    if ordinal >= max_attempts:
        raise OperatingForecastError("P6 dispatched-attempt cap reached")
    prices = json.loads(budget_path.read_text(encoding="utf-8"))["prices"]
    estimate = reservation(request, prices, today=date.today())["reserved_eur"]
    if committed + estimate > max_committed_eur:
        raise OperatingForecastError("P6 committed/reserved allowance would exceed EUR0.50")
    ordinal_call_id = call_id or f"{task_id}-{ordinal + 1:02d}-{stage}"
    prefix = f"{ordinal + 1:02d}-{stage}"
    request_path = attempts / f"{prefix}.request.json"
    request_path.write_text(json.dumps(request, indent=2, ensure_ascii=False), encoding="utf-8")
    admission = reserve_call(
        budget_path,
        call_id=ordinal_call_id,
        task_id=task_id,
        request=request,
        endpoint_host=ENDPOINT_HOST,
        today=date.today(),
    )
    (attempts / f"{prefix}.reservation.json").write_text(json.dumps(admission, indent=2, ensure_ascii=False), encoding="utf-8")
    if client is None:
        load_dotenv()
        from openai import OpenAI
        client = OpenAI(max_retries=0, base_url=BASE_URL)
    started = time.perf_counter()
    response = None
    error: Exception | None = None
    try:
        response = client.responses.create(**request)
    except Exception as exc:
        error = exc
    elapsed = time.perf_counter() - started
    response_id = getattr(response, "id", None)
    returned_model = getattr(response, "model", None)
    raw = _safe_model_dump(response) if response is not None else {"response": None}
    if error is not None:
        raw = {"error_type": type(error).__name__, "error": str(error), "response": raw}
    (attempts / f"{prefix}.response.json").write_text(json.dumps(raw, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    usage = _usage_dict(response) if response is not None else None
    outcome_error: Exception | None = None
    try:
        outcome = record_outcome(
            budget_path,
            call_id=ordinal_call_id,
            usage=usage,
            elapsed_seconds=elapsed,
            response_id=response_id,
            returned_model=returned_model,
        )
    except Exception as exc:
        outcome_error = exc
        (attempts / f"{prefix}.outcome-error.json").write_text(json.dumps({"error_type": type(exc).__name__, "error": str(exc)}, indent=2), encoding="utf-8")
        outcome = record_outcome(
            budget_path,
            call_id=ordinal_call_id,
            usage=None,
            elapsed_seconds=elapsed,
            response_id=response_id,
            returned_model=returned_model,
        )
    (attempts / f"{prefix}.outcome.json").write_text(json.dumps(outcome, indent=2, ensure_ascii=False), encoding="utf-8")
    metadata = {
        "call_id": ordinal_call_id,
        "stage": stage,
        "endpoint": f"{BASE_URL}/responses",
        "request_hash": request_hash,
        "stage_context_hash": content_hash({"stage": stage, "request": request}),
        "response_id": response_id,
        "returned_model": returned_model,
        "usage": usage,
        "elapsed_seconds": elapsed,
        "status": outcome["status"],
        "instruction_hash": content_hash(instruction),
        "payload_hash": content_hash(payload),
        "schema_hash": content_hash(request["text"]["format"]["schema"]),
        "model": request["model"],
        "reasoning": request["reasoning"],
        "service_tier": request["service_tier"],
        "max_retries": 0,
        "prompt_version": payload.get("context", {}).get("prompt_version") if isinstance(payload.get("context"), dict) else None,
        "method_catalog_version": payload.get("contract", {}).get("method_catalog_version") if isinstance(payload.get("contract"), dict) else None,
        "source_packet_hash": content_hash(payload["packet"]) if isinstance(payload.get("packet"), dict) else None,
    }
    (attempts / f"{prefix}.metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    if error is not None:
        raise OperatingForecastError(f"{stage} provider call failed after admission: {error}") from error
    if outcome_error is not None or outcome.get("status") != "completed":
        raise OperatingForecastError(f"{stage} usage is unknown after admission; exact-hash replay is held")
    try:
        parsed = _parse_structured_response(response, response_model)
    except Exception as exc:
        (attempts / f"{prefix}.parse-error.json").write_text(json.dumps({"error_type": type(exc).__name__, "error": str(exc)}, indent=2), encoding="utf-8")
        raise OperatingForecastError(f"{stage} returned invalid structured output after raw/usage persistence: {exc}") from exc
    (attempts / f"{prefix}.structured.json").write_text(json.dumps(parsed.model_dump(mode="json"), indent=2, ensure_ascii=False), encoding="utf-8")
    return parsed, metadata


def _dispatch(call_id: str, instruction: str, payload: dict[str, Any], response_model: type[BaseModel], run_dir: Path, budget_path: Path, client: Any | None = None) -> tuple[BaseModel, dict[str, Any]]:
    role = "analyst" if response_model is OperatingProposal else "reviewer"
    stage = f"{role}-{call_id.rsplit('-', 1)[-1]}"
    return _dispatch_structured(
        stage=stage,
        run_dir=run_dir,
        budget_path=budget_path,
        instruction=instruction,
        payload=payload,
        response_model=response_model,
        client=client,
        call_id=call_id,
    )


def _run_context(packet: dict[str, Any], authoritative_consequences: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "proposal_schema_hash": content_hash(OperatingProposal.model_json_schema()),
        "review_schema_hash": content_hash(OperatingReview.model_json_schema()),
        "prompt_version": PROMPT_VERSION,
        "method_catalog_version": METHOD_CATALOG_VERSION,
        "model": MODEL,
        "reasoning_effort": REASONING_EFFORT,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "endpoint": f"{BASE_URL}/responses",
        "case": CASE,
        "information_cutoff": INFORMATION_CUTOFF,
        "measurement_date": MEASUREMENT_DATE,
        "packet_hash": content_hash(packet),
        "authoritative_consequences_hash": content_hash(authoritative_consequences) if authoritative_consequences else None,
    }


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def _publish_terminal_outcome(run_dir: Path, outcome: dict[str, Any]) -> None:
    """Publish the current result without erasing an earlier terminal outcome."""
    path = run_dir / "terminal-outcome.json"
    if path.exists():
        previous = json.loads(path.read_text(encoding="utf-8"))
        if previous != outcome:
            history = run_dir / "terminal-history"
            history.mkdir(exist_ok=True)
            archived = history / f"{content_hash(previous)}.json"
            if not archived.exists():
                _write_json(archived, previous)
    _write_json(path, outcome)


def _proposal_payload(packet: dict[str, Any], context: dict[str, Any], *, purpose: str, candidate: OperatingProposal | None = None, review: OperatingReview | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "purpose": purpose,
        "packet": packet,
        "context": context,
        "required_periods": list(PERIODS),
        "contract": {
            "schema_version": SCHEMA_VERSION,
            "method_catalog_version": METHOD_CATALOG_VERSION,
            "allowed_method_ids": ["segment_revenue_growth", "consolidated_cost_ratio"],
            "allowed_outcomes": ["propose_forecast", "unresolved", "capability_gap"],
            "ppe_treatment": "replace_embedded_once",
            "sbc_treatment": "retain_embedded_pending_p8",
            "no_runtime_code": True,
            "no_hidden_human_approval": True,
        },
    }
    if candidate is not None:
        payload["candidate"] = candidate.model_dump(mode="json")
    if review is not None:
        payload["review"] = review.model_dump(mode="json")
    return payload


def _review_payload(packet: dict[str, Any], context: dict[str, Any], candidate: OperatingProposal, *, purpose: str, prior_review: OperatingReview | None = None, authoritative_consequences: dict[str, Any] | None = None) -> dict[str, Any]:
    preview = _forecast_preview(packet, candidate, authoritative_consequences)
    return {
        "purpose": purpose,
        "packet": packet,
        "context": context,
        "candidate": candidate.model_dump(mode="json"),
        "forecast_preview": preview,
        "authoritative_mog": authoritative_consequences or _authoritative_consequence_payload(packet, preview),
        "prior_review": prior_review.model_dump(mode="json") if prior_review else None,
        "review_contract": {
            "review_only": True,
            "revise_requires_consequential_analyst_revision": True,
            "revise_requires_exactly_one_target": True,
            "accept_requires_no_revision_target": True,
            "reject_requires_no_revision_target": True,
            "authoritative_mog_consequences_required_for_accept": True,
            "do_not_return_formulas_or_code": True,
        },
    }


def _review_is_eligible(review: OperatingReview) -> bool:
    return review.evidence_strength != "weak" and review.method_valid and review.source_valid and review.period_valid and review.segment_reconciliation_valid and review.cost_treatment_valid and review.no_double_count


def _validate_review_contract(review: OperatingReview) -> None:
    if review.verdict == "revise":
        if review.target == "none" or not review.required_revision:
            raise OperatingForecastError("A revise verdict must name one target and required revision")
    elif review.target != "none":
        raise OperatingForecastError(f"{review.verdict} verdict cannot carry a revision target")


def _terminal_outcome(run_dir: Path, packet: dict[str, Any], candidate: OperatingProposal, context: dict[str, Any], *, status: str, reason: str, metadata: dict[str, Any]) -> None:
    decision = {
        "decision_id": "P6-MSFT-OPERATING-HELD-R2",
        "decision_version": 2,
        "status": status,
        "human_approval": False,
        "selected_candidate": None,
        "context_hash": content_hash(context),
        "source_packet_hash": content_hash(packet),
        "reason": reason,
        "metadata": metadata,
    }
    _write_json(run_dir / "decision-held.json", decision)
    _publish_terminal_outcome(run_dir, {"candidate": candidate.model_dump(mode="json"), "decision": decision})


def _revision_is_consequential(original: OperatingProposal, revised: OperatingProposal, target: str) -> None:
    old = original.model_dump(mode="json")
    new = revised.model_dump(mode="json")
    if old.get("ppe_treatment") != new.get("ppe_treatment") or old.get("sbc_treatment") != new.get("sbc_treatment"):
        raise OperatingForecastError("Analyst revision changed fixed PP&E/SBC treatment")
    changed_segments = old.get("segment_trajectories") != new.get("segment_trajectories")
    changed_costs = old.get("cost_trajectories") != new.get("cost_trajectories")
    if target == "segment_growth" and (not changed_segments or changed_costs):
        raise OperatingForecastError("Segment-growth revision was not consequential and bounded")
    if target == "cost_ratio" and (not changed_costs or changed_segments):
        raise OperatingForecastError("Cost-ratio revision was not consequential and bounded")
    if old == new:
        raise OperatingForecastError("Analyst revision returned the same proposal")


def _build_mog_authority(
    p5_model: dict[str, Any],
    packet: dict[str, Any],
    candidate: OperatingProposal,
    authority_dir: Path,
) -> dict[str, Any]:
    """Recalculate one candidate through the shared Mog workbook before review."""
    deterministic_review = review_proposal(candidate, packet)
    if deterministic_review.verdict != "accept":
        raise OperatingForecastError("Cannot build Mog authority for an invalid analyst candidate")
    operating = build_operating_model(packet, candidate, deterministic_review)
    model = copy.deepcopy(p5_model)
    # The calculation is authoritative, but this candidate has not received an
    # independent reviewer verdict yet. Keep that state visible in the workbook
    # instead of allowing the P5 status to imply a completed P6 review.
    operating["decision"]["status"] = "REVIEW_REQUIRED"
    model["operating_forecast"] = operating
    model["operating_decision"] = {
        "proposal": candidate.model_dump(mode="json"),
        "review": deterministic_review.model_dump(mode="json"),
        "status": "REVIEW_REQUIRED",
        "decision_id": "P6-MSFT-OPERATING-PREVIEW",
    }
    authority_dir.mkdir(parents=True, exist_ok=True)
    input_path = authority_dir / "model-input.json"
    _write_json(input_path, model)
    repo_root = Path(__file__).resolve().parents[2]
    command = [
        "node",
        "scripts/spreadsheet_compat/run-p6.mjs",
        "preview",
        str(input_path),
        str(authority_dir),
    ]
    try:
        subprocess.run(command, cwd=repo_root, check=True, capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.SubprocessError) as exc:
        stdout = getattr(exc, "stdout", None) or getattr(exc, "output", None) or ""
        stderr = getattr(exc, "stderr", None) or ""
        if not stderr:
            stderr = str(exc)
        if isinstance(stdout, bytes):
            stdout = stdout.decode(errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")
        (authority_dir / "mog-preview.stdout.log").write_text(str(stdout), encoding="utf-8")
        (authority_dir / "mog-preview.stderr.log").write_text(str(stderr), encoding="utf-8")
        raise OperatingForecastError(
            "Mog authority recalculation failed: "
            f"{type(exc).__name__}; stdout={authority_dir / 'mog-preview.stdout.log'}; "
            f"stderr={authority_dir / 'mog-preview.stderr.log'}"
        ) from exc
    verification_path = authority_dir / "operating-verification.json"
    if not verification_path.exists():
        raise OperatingForecastError("Mog authority did not persist operating verification")
    verification = json.loads(verification_path.read_text(encoding="utf-8"))
    snapshot = verification.get("snapshot")
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("operatingBridge"), dict):
        raise OperatingForecastError("Mog authority verification lacks the P6 operating bridge")
    if not isinstance(snapshot.get("operatingForecast"), dict):
        raise OperatingForecastError("Mog authority verification lacks the formula-owned operating forecast")
    return {
        "status": snapshot.get("combinedDecisionStatus", "REVIEW_REQUIRED"),
        "calculation_status": "PASS",
        "engine": "Mog SDK",
        "verification_path": str(verification_path).replace("\\", "/"),
        "candidate_hash": content_hash(candidate.model_dump(mode="json")),
        "operatingBridge": snapshot["operatingBridge"],
        "operatingForecast": snapshot["operatingForecast"],
        "snapshot": snapshot,
    }


def _has_hash(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _binding_fields_present(binding: Any) -> bool:
    return isinstance(binding, dict) and all(_has_hash(binding.get(field)) for field in BINDING_HASH_FIELDS)


def _p5_binding_records(decision: dict[str, Any]) -> dict[str, Any]:
    selected = "revision" if "revision" in str(decision.get("selected_candidate", "")) else "original"
    candidate_hash = (decision.get("candidate_hashes") or {}).get(selected)
    review_hash = (decision.get("review_hashes") or {}).get(selected)
    stage = "review-revision" if selected == "revision" else "review-original"
    metadata = next((item for item in reversed(decision.get("call_metadata") or []) if item.get("stage") == stage), {})
    return {
        "candidate_hash": candidate_hash,
        "review_hash": review_hash,
        "context_hash": metadata.get("stage_context_hash"),
        "source_packet_hash": metadata.get("source_packet_hash"),
    }


def _binding_matches(left: Any, right: Any) -> bool:
    return _binding_fields_present(left) and _binding_fields_present(right) and all(left.get(field) == right.get(field) for field in BINDING_HASH_FIELDS)


def _p5_decision_is_bound(decision: dict[str, Any], model: dict[str, Any] | None = None) -> bool:
    records = _p5_binding_records(decision)
    binding = decision.get("binding")
    if binding is None:
        # Existing P5 records predate the explicit binding object. Their selected
        # candidate/review and review-call context/source hashes are the contract.
        return _binding_fields_present(records)
    if not _binding_matches(binding, records):
        return False
    if model is not None and binding.get("candidate_snapshot") is not None and binding.get("candidate_snapshot") != model.get("candidate"):
        return False
    return not (model is not None and binding.get("source_case_snapshot_sha256") is not None and binding.get("source_case_snapshot_sha256") != (model.get("packet") or {}).get("frozen_case_snapshot_sha256"))


def _p6_decision_is_bound(decision: dict[str, Any], model: dict[str, Any] | None = None) -> bool:
    binding = decision.get("binding")
    if not _binding_matches(decision, binding):
        return False
    if model is not None:
        current_proposal = (model.get("operating_decision") or {}).get("proposal")
        current_review = (model.get("operating_decision") or {}).get("review")
        if binding.get("candidate_snapshot") is not None and binding.get("candidate_snapshot") != current_proposal:
            return False
        if binding.get("review_snapshot") is not None and binding.get("review_snapshot") != current_review:
            return False
        if binding.get("source_case_snapshot_sha256") is not None and binding.get("source_case_snapshot_sha256") != (model.get("packet") or {}).get("frozen_case_snapshot_sha256"):
            return False
    return True


def _combined_decision(p5_decision: dict[str, Any], p6_decision: dict[str, Any], *, model: dict[str, Any] | None = None) -> dict[str, Any]:
    """Keep P5/P6 lineage separate and derive one honest current headline."""
    p5_status = p5_decision.get("status", "MISSING")
    p6_status = p6_decision.get("status", "MISSING")
    p5_bound = _p5_decision_is_bound(p5_decision, model)
    p6_bound = _p6_decision_is_bound(p6_decision, model)
    p5_reviewed = p5_status == "SYSTEM_REVIEWED_PROVISIONAL" and p5_decision.get("review_verdict") == "accept" and p5_bound
    p6_reviewed = p6_status == "SYSTEM_REVIEWED_PROVISIONAL" and (p6_decision.get("review") or {}).get("verdict") == "accept" and p6_decision.get("stale") is not True and p6_bound
    if p6_status == "OFFLINE_FIXTURE":
        status = "OFFLINE_FIXTURE"
    elif p6_status == "SYSTEM_REVIEWED_PROVISIONAL" and p5_reviewed and p6_reviewed:
        status = "SYSTEM_REVIEWED_PROVISIONAL"
    elif p6_status in {"P6_REVIEW_MISSING", "REJECTED_BY_REVIEW", "REVISION_REQUIRED", "REVIEW_REQUIRED", "MOG_AUTHORITY_INCOMPLETE", "REVISION_INCOMPLETE"}:
        status = p6_status
    else:
        status = "UNREVIEWED_PROVISIONAL"
    return {
        "decision_id": "P6-MSFT-COMBINED-DECISION-R3",
        "decision_version": 3,
        "status": status,
        "human_approval": False,
        "p5_status": p5_status,
        "p6_status": p6_status,
        "p5_binding_valid": p5_bound,
        "p6_binding_valid": p6_bound,
        "p5_decision_id": p5_decision.get("decision_id", "P5 decision not attached"),
        "p6_decision_id": p6_decision.get("decision_id", "P6 decision not attached"),
        "coverage": "P5 asset slice + P6 operating slice; P7-P12 financial coverage remains incomplete",
    }


def _p5_current_binding(p5: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    """Bind the selected P5 records to the current candidate and source packet."""
    records = _p5_binding_records(decision)
    records["candidate_hash"] = content_hash(p5.get("candidate", {}))
    records["source_packet_hash"] = content_hash(p5.get("packet", {}))
    records["candidate_snapshot"] = copy.deepcopy(p5.get("candidate"))
    records["source_case_snapshot_sha256"] = (p5.get("packet") or {}).get("frozen_case_snapshot_sha256")
    return records


def _prepare_cli_packet(p2_root: Path, p5: dict[str, Any], p5_model_path: Path) -> dict[str, Any]:
    """Build the packet and dependency fields used by the direct CLI path."""
    packet = build_evidence_packet(p2_root)
    p5_packet = p5.get("packet", {})
    p5_facts = p5_packet.get("facts", {}) if isinstance(p5_packet, dict) else {}
    if isinstance(p5_packet, dict):
        for field in ("frozen_case_snapshot_id", "frozen_case_snapshot_sha256"):
            if p5_packet.get(field) is not None:
                packet[field] = p5_packet[field]
    p5_calculated = p5_facts.get("calculated", {}) if isinstance(p5_facts, dict) else {}
    p5_ttm = p5_facts.get("ttm", {}) if isinstance(p5_facts, dict) else {}
    p5_revenue_fact = p5_ttm.get("revenue", {}) if isinstance(p5_ttm, dict) else {}
    p5_depreciation = p5_calculated.get("ttm_ppe_depreciation") if isinstance(p5_calculated, dict) else None
    p5_revenue = p5_revenue_fact.get("value") if isinstance(p5_revenue_fact, dict) else None
    if p5_depreciation is None or p5_revenue is None:
        raise OperatingForecastError("P5 dependency lacks sourced TTM PP&E depreciation or revenue baseline")
    if p5_revenue == 0:
        raise OperatingForecastError("P5 TTM revenue baseline cannot be zero")
    if p5_depreciation < 0:
        raise OperatingForecastError("P5 TTM PP&E depreciation baseline cannot be negative")
    packet["embedded_ppe_baseline"] = {
        "ttm_ppe_depreciation": p5_depreciation,
        "ttm_revenue": p5_revenue,
        "ratio": p5_depreciation / p5_revenue,
        "basis": "P5 calculated TTM PP&E-only depreciation / TTM revenue",
        "scope": "aggregate consolidated PP&E-only depreciation proxy",
        "evidence_refs": ["E3", "E4", "E5"],
    }
    packet["p5_dependency"] = {
        "model_input_sha256": _sha256(p5_model_path),
        "packet_hash": content_hash(p5_packet),
        "candidate_hash": content_hash(p5.get("candidate", {})),
        "decision_hash": content_hash(p5.get("decision", {})),
    }
    return packet


def run_reasoning(
    packet: dict[str, Any],
    run_dir: Path,
    budget_path: Path,
    *,
    offline: bool = False,
    client: Any | None = None,
    authoritative_consequences: dict[str, Any] | None = None,
    authoritative_builder: Any | None = None,
) -> tuple[OperatingProposal, OperatingReview, dict[str, Any]]:
    """Run the bounded P6 analyst/reviewer path with exact-context lineage."""
    run_dir.mkdir(parents=True, exist_ok=True)
    context = _run_context(packet, authoritative_consequences)
    context_path = run_dir / "run-context.json"
    if context_path.exists():
        prior_context = json.loads(context_path.read_text(encoding="utf-8"))
        if prior_context != context:
            raise OperatingForecastError("P6 run context changed; prior outputs cannot be reused")
    else:
        _write_json(context_path, context)
    _write_json(run_dir / "evidence-packet.json", packet)
    _write_json(run_dir / "replay-lineage.json", _replay_lineage(budget_path))
    meta: dict[str, Any] = {"context": context, "offline": offline}
    original_candidate: OperatingProposal
    original_review: OperatingReview
    if offline:
        original_candidate = default_proposal(packet)
        original_review = review_proposal(original_candidate, packet)
        status = "OFFLINE_FIXTURE"
        _write_json(run_dir / "candidate.json", original_candidate.model_dump(mode="json"))
        _write_json(run_dir / "review.json", original_review.model_dump(mode="json"))
    else:
        initial_payload, initial_request = _initial_analyst_request(packet, context)
        original_candidate, analyst_meta = _dispatch_structured(
            stage="analyst-initial",
            run_dir=run_dir,
            budget_path=budget_path,
            instruction=INITIAL_ANALYST_INSTRUCTION,
            payload=initial_payload,
            response_model=OperatingProposal,
            client=client,
            prepared_request=initial_request,
        )
        validate_proposal(original_candidate, packet)
        _write_json(run_dir / "candidate-initial.json", original_candidate.model_dump(mode="json"))
        review_authority = authoritative_consequences
        if review_authority is None and authoritative_builder is not None:
            try:
                review_authority = authoritative_builder(original_candidate, "analyst-initial")
            except Exception as exc:
                _terminal_outcome(run_dir, packet, original_candidate, context, status="MOG_AUTHORITY_INCOMPLETE", reason=str(exc), metadata={"analyst": analyst_meta})
                raise OperatingForecastError(f"P6 Mog authority incomplete; prior candidate preserved: {exc}") from exc
        original_review, reviewer_meta = _dispatch_structured(
            stage="reviewer-original",
            run_dir=run_dir,
            budget_path=budget_path,
            instruction="Independently review the candidate against every frozen source, period, segment identity, forecast tie and no-double-count control. Review the actual authoritative Mog financial consequences supplied in the payload, including gross cost, embedded PP&E removal, scheduled PP&E depreciation, total expense, EBIT and margin. Return accept, revise, or reject with one bounded revision target when revising.",
            payload=_review_payload(packet, context, original_candidate, purpose="independent original review", authoritative_consequences=review_authority),
            response_model=OperatingReview,
            client=client,
        )
        _validate_review_contract(original_review)
        _write_json(run_dir / "review-original.json", original_review.model_dump(mode="json"))
        meta.update({"analyst": analyst_meta, "reviewer_original": reviewer_meta})
        if original_review.verdict == "revise":
            _write_json(run_dir / "revision-request.json", {"requested_by": "system_review", "target": original_review.target, "required_revision": original_review.required_revision, "prior_candidate_hash": content_hash(original_candidate.model_dump(mode="json")), "context_hash": content_hash(context)})
            try:
                revised_candidate, revision_meta = _dispatch_structured(
                    stage="analyst-revision",
                    run_dir=run_dir,
                    budget_path=budget_path,
                    instruction="Produce a consequential bounded analyst revision responding to the named review target. Change the named segment-growth or cost-ratio trajectory, preserve every other method, evidence, PP&E and SBC treatment, and return a complete candidate.",
                    payload=_proposal_payload(packet, context, purpose="required analyst revision", candidate=original_candidate, review=original_review),
                    response_model=OperatingProposal,
                    client=client,
                )
                validate_proposal(revised_candidate, packet)
                _revision_is_consequential(original_candidate, revised_candidate, original_review.target)
            except Exception as exc:
                _terminal_outcome(run_dir, packet, original_candidate, context, status="REVISION_INCOMPLETE", reason=str(exc), metadata={"original_review": original_review.model_dump(mode="json")})
                raise OperatingForecastError(f"P6 revision incomplete; prior candidate preserved: {exc}") from exc
            _write_json(run_dir / "candidate-revision.json", revised_candidate.model_dump(mode="json"))
            revision_authority = review_authority
            if authoritative_builder is not None:
                try:
                    revision_authority = authoritative_builder(revised_candidate, "analyst-revision")
                except Exception as exc:
                    _terminal_outcome(run_dir, packet, original_candidate, context, status="MOG_AUTHORITY_INCOMPLETE", reason=str(exc), metadata=meta)
                    raise OperatingForecastError(f"P6 revised Mog authority incomplete; prior candidate preserved: {exc}") from exc
            revised_review, final_meta = _dispatch_structured(
                stage="reviewer-revision",
                run_dir=run_dir,
                budget_path=budget_path,
                instruction="Independently re-check the consequential analyst revision. Accept only when the revised target moved, the candidate remains traceable to compatible source periods, and the authoritative Mog consequences show gross costs minus embedded PP&E depreciation plus scheduled P5 depreciation with no cancellation. Return a terminal verdict.",
                payload=_review_payload(packet, context, revised_candidate, purpose="independent revision re-check", prior_review=original_review, authoritative_consequences=revision_authority),
                response_model=OperatingReview,
                client=client,
            )
            _validate_review_contract(revised_review)
            _write_json(run_dir / "review-revision.json", revised_review.model_dump(mode="json"))
            meta.update({"analyst_revision": revision_meta, "reviewer_revision": final_meta, "revision": {"target": original_review.target, "original_candidate_hash": content_hash(original_candidate.model_dump(mode="json")), "revised_candidate_hash": content_hash(revised_candidate.model_dump(mode="json"))}})
            if revised_review.verdict != "accept" or not _review_is_eligible(revised_review):
                status = "REJECTED_BY_REVIEW" if revised_review.verdict == "reject" else "REVISION_REQUIRED"
                _terminal_outcome(run_dir, packet, original_candidate, context, status=status, reason="; ".join(revised_review.concerns), metadata=meta)
                raise OperatingForecastError(f"P6 review failed after revision: {revised_review.concerns}")
            if isinstance(revision_authority, dict):
                packet["authoritative_mog"] = revision_authority
            proposal, review = revised_candidate, revised_review
        else:
            proposal, review = original_candidate, original_review
            if review.verdict != "accept" or not _review_is_eligible(review):
                status = "REJECTED_BY_REVIEW" if review.verdict == "reject" else "REVIEW_REQUIRED"
                _terminal_outcome(run_dir, packet, proposal, context, status=status, reason="; ".join(review.concerns), metadata=meta)
                raise OperatingForecastError(f"P6 review failed: {review.concerns}")
            if isinstance(review_authority, dict):
                packet["authoritative_mog"] = review_authority
        status = "SYSTEM_REVIEWED_PROVISIONAL"
        _write_json(run_dir / "candidate.json", proposal.model_dump(mode="json"))
        _write_json(run_dir / "review.json", review.model_dump(mode="json"))
    if original_review.verdict != "accept" and offline:
        _terminal_outcome(run_dir, packet, original_candidate, context, status="REVIEW_REQUIRED", reason="; ".join(original_review.concerns), metadata=meta)
        raise OperatingForecastError(f"P6 offline review failed: {original_review.concerns}")
    selected_candidate = original_candidate if offline else proposal
    selected_review = original_review if offline else review
    candidate_json = selected_candidate.model_dump(mode="json")
    review_json = selected_review.model_dump(mode="json")
    model = build_operating_model(packet, selected_candidate, selected_review)
    model["decision"].update({"status": status, "context_hash": content_hash(context), "source_packet_hash": content_hash(packet), "candidate_hash": content_hash(candidate_json), "review_hash": content_hash(review_json), "authoritative_mog_attached": bool(authoritative_consequences or packet.get("authoritative_mog"))})
    model["decision"]["binding"] = {
        **{field: model["decision"][field] for field in BINDING_HASH_FIELDS},
        "candidate_snapshot": copy.deepcopy(candidate_json),
        "review_snapshot": copy.deepcopy(review_json),
        "source_case_snapshot_sha256": packet.get("frozen_case_snapshot_sha256"),
    }
    model["operating_decision"] = {
        "proposal": copy.deepcopy(candidate_json),
        "review": copy.deepcopy(review_json),
        "status": status,
        "binding": copy.deepcopy(model["decision"]["binding"]),
    }
    _write_json(run_dir / "model.json", model)
    meta.update({"status": status, "calls": _ledger_p6_state(budget_path)[0] if budget_path.exists() else 0, "cost_eur": _ledger_p6_state(budget_path)[1] if budget_path.exists() else 0.0})
    _write_json(run_dir / "run-metadata.json", meta)
    _publish_terminal_outcome(run_dir, {
        "candidate": candidate_json,
        "review": review_json,
        "decision": {**model["decision"], "selected_candidate": candidate_json},
    })
    return selected_candidate, selected_review, model


def _run_cli(args: argparse.Namespace) -> None:
    p2_root = Path(args.p2_root)
    output = Path(args.output)
    run_dir = Path(args.run_dir)
    p5_model_path = Path(args.p5_model)
    p5 = json.loads(p5_model_path.read_text(encoding="utf-8"))
    p5_decision = copy.deepcopy(p5.get("decision", {}))
    packet = _prepare_cli_packet(p2_root, p5, p5_model_path)
    authoritative = None
    authoritative_path = getattr(args, "authoritative_mog", None)
    if authoritative_path:
        authoritative = json.loads(Path(authoritative_path).read_text(encoding="utf-8"))
        packet["authoritative_mog"] = authoritative
    authority_builder = None if args.offline else lambda candidate, stage: _build_mog_authority(
        p5,
        packet,
        candidate,
        run_dir / "mog-authority" / stage,
    )
    proposal, review, operating = run_reasoning(packet, run_dir, Path(args.budget), offline=args.offline, authoritative_consequences=authoritative, authoritative_builder=authority_builder)
    p6_decision = copy.deepcopy(operating.get("decision", {}))
    p6_decision.update({
        "decision_id": "P6-MSFT-OPERATING-DECISION-R3",
        "status": operating["decision"].get("status", "UNREVIEWED_PROVISIONAL"),
        "review": review.model_dump(mode="json"),
        "human_approval": False,
    })
    proposal_json = proposal.model_dump(mode="json")
    review_json = review.model_dump(mode="json")
    p6_decision["binding"] = {
        **{field: p6_decision[field] for field in BINDING_HASH_FIELDS},
        "candidate_snapshot": copy.deepcopy(proposal_json),
        "review_snapshot": copy.deepcopy(review_json),
        "source_case_snapshot_sha256": packet.get("frozen_case_snapshot_sha256"),
    }
    p5_decision["binding"] = _p5_current_binding(p5, p5_decision)
    p5["operating_forecast"] = operating
    p5["operating_decision"] = {"proposal": proposal_json, "review": review_json, "status": p6_decision["status"], "decision_id": p6_decision["decision_id"], "binding": p6_decision["binding"]}
    p5["p5_decision"] = p5_decision
    p5["p6_decision"] = p6_decision
    p5["decision"] = _combined_decision(p5_decision, p6_decision, model=p5)
    p5["schema_version"] = "p6-msft-operating-input-v1"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(p5, indent=2, ensure_ascii=False), encoding="utf-8")
    (run_dir / "model-input.json").write_text(json.dumps(p5, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"output": str(output), "run_dir": str(run_dir), "status": operating["decision"]["status"], "periods": len(PERIODS), "segments": len(SEGMENTS)}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--p2-root", default="data/build-guide-p2-r2/MSFT")
    parser.add_argument("--p5-model", default="data/build-guide-p5/live-r3-20260906/model-input.json")
    parser.add_argument("--output", default="data/build-guide-p6/model-input.json")
    parser.add_argument("--run-dir", default="data/build-guide-p6/reasoning")
    parser.add_argument("--budget", default="data/build-guide-api-budget.json")
    parser.add_argument("--authoritative-mog", default=None, help="Persisted Mog consequence JSON used by the reviewer")
    parser.add_argument("--offline", action="store_true")
    _run_cli(parser.parse_args())


if __name__ == "__main__":
    main()
