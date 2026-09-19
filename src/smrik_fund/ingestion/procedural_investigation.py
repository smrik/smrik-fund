"""Three-call procedural filing investigation.

This experiment keeps the existing one-shot result schema and validators. The
model only decomposes, assesses, and concludes; Python owns observation,
evidence identity, quantification, and reconciliation.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .analytical_scan import AnalyticalScanFinding
from .filing import FilingEvidenceError, validate_evidence_refs
from .filing_investigation import (
	DEFAULT_MODEL,
	DEFAULT_REASONING_EFFORT,
	FinancialInvestigationResult,
	_client,
	_parse,
	_validate_free_text_claims,
	_validated_packet,
	build_observed_movement,
	extract_period_paired_disclosures,
	reconcile_period_pair_bridge,
	validate_financial_investigation,
)

PROCEDURAL_PROMPT_VERSION = "filing-investigation-procedural-v1"
PROCEDURAL_SCHEMA_VERSION = "filing-investigation-procedural-v1"
DEFAULT_SKILL_PATH = (
	Path(__file__).resolve().parents[3] / "skills" / "filing-investigation" / "SKILL.md"
)


class ProceduralInvestigationError(RuntimeError):
	"""A procedural investigation cannot continue safely."""


class DriverHypothesis(BaseModel):
	model_config = ConfigDict(extra="forbid")

	name: str = Field(min_length=1, max_length=240)
	question: str = Field(min_length=1, max_length=600)
	evidence_refs: list[str] = Field(min_length=1, max_length=8)

	@field_validator("evidence_refs")
	@classmethod
	def _unique_refs(cls, value: list[str]) -> list[str]:
		if any(not isinstance(ref, str) or not ref.strip() for ref in value):
			raise ValueError("evidence_refs must contain non-empty IDs")
		if len(value) != len(set(value)):
			raise ValueError("evidence_refs must be unique")
		return value


class InvestigationDecomposition(BaseModel):
	model_config = ConfigDict(extra="forbid")

	hypotheses: list[DriverHypothesis] = Field(min_length=1, max_length=8)


class DriverAssessmentItem(BaseModel):
	model_config = ConfigDict(extra="forbid")

	hypothesis: str = Field(min_length=1, max_length=240)
	status: Literal["supported", "unsupported", "uncertain"]
	description: str = Field(min_length=1, max_length=600)
	effect: Literal["increased_line", "decreased_line", "unknown"] = "unknown"
	evidence_refs: list[str] = Field(min_length=1, max_length=8)

	@field_validator("evidence_refs")
	@classmethod
	def _unique_refs(cls, value: list[str]) -> list[str]:
		if any(not isinstance(ref, str) or not ref.strip() for ref in value):
			raise ValueError("evidence_refs must contain non-empty IDs")
		if len(value) != len(set(value)):
			raise ValueError("evidence_refs must be unique")
		return value


class DriverAssessment(BaseModel):
	model_config = ConfigDict(extra="forbid")

	assessments: list[DriverAssessmentItem] = Field(min_length=1, max_length=8)


def _load_skill(path: str | Path | None) -> tuple[str, str]:
	target = Path(path) if path is not None else DEFAULT_SKILL_PATH
	try:
		text = target.read_text(encoding="utf-8")
	except OSError as exc:
		raise ProceduralInvestigationError(
			f"filing investigation skill is unavailable: {target}"
		) from exc
	if not text.strip():
		raise ProceduralInvestigationError("filing investigation skill is empty")
	return text, hashlib.sha256(text.encode("utf-8")).hexdigest().upper()


def _allowed_periods(observation: list[dict[str, Any]]) -> set[str]:
	periods: set[str] = set()
	for row in observation:
		periods.update(str(period) for period in row.get("periods", {}) if period)
		for bridge in row.get("year_over_year", []):
			for field in ("period", "previous_period"):
				if bridge.get(field):
					periods.add(str(bridge[field]))
	return periods


def _validate_refs(packet: str, refs: list[str], label: str) -> None:
	try:
		validate_evidence_refs(packet, refs, require_identity=True)
	except FilingEvidenceError as exc:
		raise ProceduralInvestigationError(f"{label}: {exc}") from exc


def _validate_assessment(packet: str, item: DriverAssessmentItem) -> None:
	"""Apply the current narrative/reference validator to one assessed driver."""
	_validate_refs(packet, item.evidence_refs, "driver assessment evidence")
	try:
		parsed = _validated_packet(packet)
		_validate_free_text_claims(
			item.description,
			item.evidence_refs,
			parsed,
			"driver assessment",
		)
		if not parsed["items"]:
			raise FilingEvidenceError("evidence packet contains no items")
	except (FilingEvidenceError, ValueError, TypeError) as exc:
		raise ProceduralInvestigationError(
			f"driver assessment validation failed: {exc}"
		) from exc


def _call(
	client: Any,
	*,
	model: str,
	reasoning_effort: str,
	system: str,
	payload: dict[str, Any],
	text_format: type[BaseModel],
) -> BaseModel:
	try:
		response = client.responses.parse(
			model=model,
			reasoning={"effort": reasoning_effort},
			input=[
				{"role": "system", "content": system},
				{
					"role": "user",
					"content": json.dumps(
						payload, ensure_ascii=False, allow_nan=False
					),
				},
			],
			text_format=text_format,
		)
		return _parse(response, text_format)
	except Exception as exc:
		raise ProceduralInvestigationError(
			f"{text_format.__name__} call failed: {exc}"
		) from exc


def run_procedural_investigation(
	ticker: str,
	finding: AnalyticalScanFinding,
	pnl: pd.DataFrame,
	evidence_packet: str,
	*,
	expected_filing_accession: str,
	segments: pd.DataFrame | None = None,
	client: Any | None = None,
	model: str = DEFAULT_MODEL,
	reasoning_effort: str = DEFAULT_REASONING_EFFORT,
	observed_unit: str = "dollars",
	run_id: str | None = None,
	skill_path: str | Path | None = None,
	trace_path: str | Path | None = None,
) -> tuple[FinancialInvestigationResult, dict[str, Any], dict[str, Any]]:
	"""Run decomposition, driver assessment, and final conclusion exactly once."""
	if not isinstance(finding, AnalyticalScanFinding) or not isinstance(pnl, pd.DataFrame):
		raise TypeError("finding and pnl have invalid types")
	if not expected_filing_accession.strip():
		raise ProceduralInvestigationError("expected filing accession is required")
	skill, skill_sha256 = _load_skill(skill_path)
	try:
		packet_data = _validated_packet(
			evidence_packet,
			expected_ticker=ticker,
			expected_filing_accession=expected_filing_accession,
		)
	except FilingEvidenceError as exc:
		raise ProceduralInvestigationError(str(exc)) from exc
	observation = build_observed_movement(pnl, finding, segments)
	allowed_periods = _allowed_periods(observation)
	base = {
		"ticker": ticker.strip().upper(),
		"finding": finding.model_dump(mode="json"),
		"observation": observation,
		"evidence_packet": evidence_packet,
	}
	model_client = _client(client)
	decomposition = _call(
		model_client,
		model=model,
		reasoning_effort=reasoning_effort,
		system=skill + "\n\nStage: decompose the movement into testable hypotheses.",
		payload=base,
		text_format=InvestigationDecomposition,
	)
	for hypothesis in decomposition.hypotheses:
		_validate_refs(evidence_packet, hypothesis.evidence_refs, "decomposition evidence")
	assessment = _call(
		model_client,
		model=model,
		reasoning_effort=reasoning_effort,
		system=skill + "\n\nStage: assess each hypothesis against the packet.",
		payload={**base, "decomposition": decomposition.model_dump(mode="json")},
		text_format=DriverAssessment,
	)
	for item in assessment.assessments:
		_validate_assessment(evidence_packet, item)
	extraction = extract_period_paired_disclosures(
		pnl,
		finding,
		evidence_packet,
		observed_unit=observed_unit,
		segments=segments,
	)
	reconciliation = reconcile_period_pair_bridge(
		pnl,
		finding,
		evidence_packet,
		observed_unit=observed_unit,
		segments=segments,
	)
	final = _call(
		model_client,
		model=model,
		reasoning_effort=reasoning_effort,
		system=skill + "\n\nStage: write the final conclusion in the existing result schema.",
		payload={
			**base,
			"decomposition": decomposition.model_dump(mode="json"),
			"driver_assessment": assessment.model_dump(mode="json"),
			"python_quantified_disclosures": extraction,
			"python_reconciliation": reconciliation,
		},
		text_format=FinancialInvestigationResult,
	)
	try:
		result = validate_financial_investigation(
			final,
			evidence_packet,
			allowed_periods=allowed_periods,
		)
	except Exception as exc:
		raise ProceduralInvestigationError(
			f"final conclusion validation failed: {exc}"
		) from exc
	run_id = run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
	trace = {
		"arm": "procedural",
		"run_id": run_id,
		"ticker": ticker.strip().upper(),
		"finding": finding.model_dump(mode="json"),
		"observation": observation,
		"skill": {"path": str(skill_path or DEFAULT_SKILL_PATH), "sha256": skill_sha256},
		"evidence_identity": {
			"filing_accession": expected_filing_accession,
			"packet_sha256": hashlib.sha256(evidence_packet.encode("utf-8")).hexdigest().upper(),
			"packet_metadata": packet_data["metadata"],
			"evidence_refs": sorted(packet_data["items"]),
		},
		"decomposition": decomposition.model_dump(mode="json"),
		"driver_assessment": assessment.model_dump(mode="json"),
		"deterministic_quantification": extraction,
		"deterministic_reconciliation": reconciliation,
		"final_result": result.model_dump(mode="json"),
		"call_count": 3,
	}
	if trace_path is not None:
		path = Path(trace_path)
		path.parent.mkdir(parents=True, exist_ok=True)
		path.write_text(json.dumps(trace, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
	metadata = {
		"ticker": ticker.strip().upper(),
		"model": model,
		"reasoning_effort": reasoning_effort,
		"prompt_version": PROCEDURAL_PROMPT_VERSION,
		"schema_version": PROCEDURAL_SCHEMA_VERSION,
		"run_id": run_id,
		"call_count": 3,
		"skill_sha256": skill_sha256,
	}
	return result, metadata, trace
