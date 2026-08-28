"""Bounded, evidence-backed investigation of one Analytical Scan finding."""

from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .analytical_scan import (
	AnalyticalScanError,
	AnalyticalScanFinding,
	AnalyticalScanResult,
	format_analytical_pnl_for_scan,
	validate_analytical_scan_result,
)
from .filing import (
	MAX_EVIDENCE_ITEMS,
	FilingEvidenceError,
	retrieve_filing_evidence,
	validate_evidence_refs,
)
from .statements import ANNUAL_PERIOD_PATTERN

DEFAULT_MODEL = "gpt-5.6-luna"
DEFAULT_REASONING_EFFORT = "high"
EXPANSION_PROMPT_VERSION = "filing-query-expansion-v1"
INVESTIGATION_PROMPT_VERSION = "financial-investigation-v5"
SCHEMA_VERSION = "filing-investigation-v3"
MAX_FINDINGS = 8
MAX_QUERIES = 3
MAX_DRIVERS = 8
MAX_QUERY_LENGTH = 240

_LINE_REF_PATTERN = re.compile(r"^line_ref=(L\d+)\b", re.MULTILINE)
_BARE_LINE_REF = re.compile(r"^L\d+$")
_EXPANSION_PROMPT = (
	Path(__file__).resolve().parents[3] / "prompts" / "filing_query_expansion.md"
).read_text(encoding="utf-8")
_INVESTIGATION_PROMPT = (
	Path(__file__).resolve().parents[3] / "prompts" / "financial_investigation.md"
).read_text(encoding="utf-8")

AmountUnit = Literal[
	"dollars", "usd_millions", "usd_billions", "millions", "billions", "unknown"
]
DriverEffect = Literal["increased_line", "decreased_line", "unknown"]


class FilingInvestigationError(RuntimeError):
	"""A finding investigation cannot continue safely."""


class FilingGroundedQuery(BaseModel):
	"""One literal query copied from an already retrieved filing excerpt."""

	model_config = ConfigDict(extra="forbid")

	query: str = Field(min_length=1, max_length=MAX_QUERY_LENGTH)
	evidence_refs: list[str] = Field(min_length=1, max_length=8)
	support_span: str = Field(min_length=1, max_length=1200)

	@field_validator("evidence_refs")
	@classmethod
	def _valid_expansion_refs(cls, value: list[str]) -> list[str]:
		refs = [ref.strip() for ref in value if isinstance(ref, str) and ref.strip()]
		if len(refs) != len(value) or len(refs) != len(set(refs)):
			raise ValueError("evidence_refs must contain unique non-empty IDs")
		return refs


class FilingQueryExpansion(BaseModel):
	"""At most one model-selected, filing-local expansion pass."""

	model_config = ConfigDict(extra="forbid")

	queries: list[FilingGroundedQuery] = Field(default_factory=list, max_length=3)


class InitialQueryDerivation(BaseModel):
	"""Deterministic lineage for one initial literal seed."""

	model_config = ConfigDict(extra="forbid")

	query: str = Field(min_length=1, max_length=MAX_QUERY_LENGTH)
	line_refs: list[str] = Field(min_length=1, max_length=8)
	source_label: str = Field(min_length=1, max_length=240)
	generic_cue: str | None = Field(default=None, max_length=40)
	pass_name: Literal["initial"] = "initial"


def _text(value: object) -> str:
	if value is None:
		return ""
	try:
		if bool(pd.isna(value)):
			return ""
	except (TypeError, ValueError):
		pass
	return str(value).strip()


def _finite(value: object) -> float | None:
	try:
		number = float(value)
	except (TypeError, ValueError):
		return None
	return number if math.isfinite(number) else None


def _unit(value: object) -> str:
	value = _text(value).casefold().replace("-", "_").replace(" ", "_")
	return {
		"usd": "dollars",
		"dollar": "dollars",
		"usd_dollar": "dollars",
		"usd_dollars": "dollars",
		"$": "dollars",
		"million": "usd_millions",
		"usd_million": "usd_millions",
		"usd_m": "usd_millions",
		"billion": "usd_billions",
		"usd_billion": "usd_billions",
		"usd_b": "usd_billions",
		"m": "millions",
		"bn": "billions",
		"na": "unknown",
		"n_a": "unknown",
		"none": "unknown",
	}.get(value, value or "unknown")


class FindingSearchPlan(BaseModel):
	"""Deterministic initial retrieval plan persisted for one finding."""

	model_config = ConfigDict(extra="forbid")

	finding_rank: int = Field(ge=1, le=MAX_FINDINGS)
	affected_line_refs: list[str] = Field(min_length=1, max_length=8)
	investigation_questions: list[str] = Field(default_factory=list, max_length=3)
	queries: list[str] = Field(default_factory=list, max_length=MAX_QUERIES)

	@field_validator("affected_line_refs")
	@classmethod
	def _valid_refs(cls, value: list[str]) -> list[str]:
		refs = [ref.strip() for ref in value]
		if any(not _BARE_LINE_REF.fullmatch(ref) for ref in refs):
			raise ValueError("affected_line_refs must contain bare L## references")
		if len(refs) != len(set(refs)):
			raise ValueError("affected_line_refs must be unique")
		return refs

	@field_validator("queries")
	@classmethod
	def _bounded_queries(cls, value: list[str]) -> list[str]:
		queries: list[str] = []
		seen: set[str] = set()
		for raw in value:
			if not isinstance(raw, str) or not raw.strip():
				raise ValueError("queries must be non-empty strings")
			query = raw.strip()
			if len(query) > MAX_QUERY_LENGTH:
				raise ValueError("queries are too long")
			if query.casefold() not in seen:
				seen.add(query.casefold())
				queries.append(query)
		return queries


class DisclosedDriver(BaseModel):
	"""One evidence-backed driver; null amount is retained as unquantified."""

	model_config = ConfigDict(extra="forbid")

	description: str = Field(min_length=1, max_length=600)
	amount: float | None = None
	amount_unit: AmountUnit = "unknown"
	period: str | None = None
	effect: DriverEffect = "unknown"
	amount_basis: Literal["disclosed", "unquantified"] | None = None
	evidence_span: str | None = Field(default=None, max_length=1200)
	evidence_refs: list[str] = Field(min_length=1, max_length=8)

	@field_validator("amount")
	@classmethod
	def _finite_amount(cls, value: float | None) -> float | None:
		if value is not None and not math.isfinite(value):
			raise ValueError("amount must be finite or null")
		return value

	@field_validator("amount_unit", mode="before")
	@classmethod
	def _clean_amount_unit(cls, value: object) -> str:
		return _unit(value)

	@field_validator("period", mode="before")
	@classmethod
	def _clean_period(cls, value: object) -> str | None:
		return _text(value) or None

	@field_validator("evidence_span", mode="before")
	@classmethod
	def _clean_evidence_span(cls, value: object) -> str | None:
		return _text(value) or None

	@field_validator("evidence_refs")
	@classmethod
	def _valid_evidence_refs(cls, value: list[str]) -> list[str]:
		refs = [ref.strip() for ref in value if isinstance(ref, str) and ref.strip()]
		if len(refs) != len(value) or len(refs) != len(set(refs)):
			raise ValueError("evidence_refs must contain unique non-empty IDs")
		return refs

	@model_validator(mode="after")
	def _basis_matches_amount(self) -> DisclosedDriver:
		expected = "disclosed" if self.amount is not None else "unquantified"
		if self.amount_basis is None:
			self.amount_basis = expected
		elif self.amount_basis != expected:
			raise ValueError("amount_basis must match amount presence")
		return self


class FinancialInvestigationResult(BaseModel):
	"""Structured filing explanation; observed movement stays deterministic."""

	model_config = ConfigDict(extra="forbid")

	disclosed_drivers: list[DisclosedDriver] = Field(
		default_factory=list, max_length=MAX_DRIVERS
	)
	interpretation: str | None = Field(default=None, max_length=1000)
	interpretation_evidence_refs: list[str] = Field(default_factory=list, max_length=8)
	unresolved_remainder: str = Field(min_length=1, max_length=1000)
	unresolved_remainder_evidence_refs: list[str] = Field(
		default_factory=list, max_length=8
	)
	explanation: str = Field(min_length=1, max_length=1200)
	explanation_evidence_refs: list[str] = Field(default_factory=list, max_length=8)

	@field_validator(
		"interpretation_evidence_refs",
		"unresolved_remainder_evidence_refs",
		"explanation_evidence_refs",
	)
	@classmethod
	def _valid_optional_refs(cls, value: list[str]) -> list[str]:
		refs = [ref.strip() for ref in value if isinstance(ref, str) and ref.strip()]
		if len(refs) != len(value) or len(refs) != len(set(refs)):
			raise ValueError("evidence references must be unique non-empty IDs")
		return refs


def _client(client: Any | None) -> Any:
	if client is not None:
		return client
	load_dotenv()
	if not os.getenv("OPENAI_API_KEY"):
		raise FilingInvestigationError("OPENAI_API_KEY is not set")
	try:
		from openai import OpenAI

		return OpenAI()
	except Exception as exc:
		raise FilingInvestigationError(
			f"could not initialize OpenAI client: {exc}"
		) from exc


def _parse(response: Any, model: type[BaseModel]) -> BaseModel:
	parsed = getattr(response, "output_parsed", None)
	try:
		return parsed if isinstance(parsed, model) else model.model_validate(parsed)
	except Exception as exc:
		raise FilingInvestigationError(
			f"structured model output failed validation: {exc}"
		) from exc


def _validated_packet(
	packet: str,
	*,
	expected_ticker: str | None = None,
	expected_filing_accession: str | None = None,
) -> dict[str, Any]:
	"""Validate packet identity at every investigation boundary."""
	parsed = validate_evidence_refs(packet, [], require_identity=True)
	metadata = parsed["metadata"]
	packet_ticker = _text(metadata.get("ticker")).upper()
	packet_source = _text(metadata.get("source"))
	accession = _text(metadata.get("filing_accession"))
	if expected_ticker is not None and packet_ticker != _text(expected_ticker).upper():
		raise FilingEvidenceError(
			"evidence packet ticker does not match investigation ticker"
		)
	if expected_filing_accession is not None and accession != _text(
		expected_filing_accession
	):
		raise FilingEvidenceError(
			"evidence packet accession does not match investigation filing"
		)
	for evidence_id, item in parsed["items"].items():
		if _text(item.get("source")) != packet_source:
			raise FilingEvidenceError(
				f"{evidence_id} source does not match packet source"
			)
		locator_match = re.match(
			r"^\s*accession\s+(?P<accession>[^;\s]+)(?:;|$)",
			_text(item.get("locator")),
			flags=re.IGNORECASE,
		)
		if locator_match is None or locator_match.group("accession") != accession:
			raise FilingEvidenceError(
				f"{evidence_id} locator does not match packet accession"
			)
	return parsed


_REGEX_SYNTAX_PATTERN = re.compile(r"[\\\[\]()?*+{}|]")
_INITIAL_UNSAFE_QUERY_PATTERN = re.compile(r"[\\\[\]?*+{}|]")
_UNSAFE_SOURCE_LABEL_PATTERN = re.compile(
	r"(?:\d|[$€£]|https?://|www\.)", re.IGNORECASE
)
_INITIAL_MOVEMENT_CUES: tuple[tuple[str, str], ...] = (
	("increased", "increased"),
	("decreased", "decreased"),
	("driven by", "driven by"),
	("due to", "due to"),
	("offset", "offset"),
)
_INITIAL_GENERIC_QUALIFIERS: tuple[tuple[str, str], ...] = (
	("revenue", "revenue"),
	("cost", "costs"),
	("expense", "expenses"),
	("income", "income"),
)
_INITIAL_LABEL_NOUN_PATTERN = re.compile(
	r"\b(?:revenue|costs?|expenses?|income|gains?|loss(?:es)?)\b",
	re.IGNORECASE,
)


def _source_context_rows(
	context: dict[str, Any] | list[dict[str, Any]],
) -> list[dict[str, str]]:
	"""Project supplied line context without ever copying filing passages."""
	if isinstance(context, list):
		context_map: dict[str, Any] = {}
		raw_rows: object = context
	else:
		if not isinstance(context, dict):
			raise FilingInvestigationError(
				"filing_context must be a dictionary or rows"
			)
		context_map = context
		raw_rows = None
		for key in ("lines", "source_lines", "affected_lines"):
			candidate = context.get(key)
			if isinstance(candidate, list):
				raw_rows = candidate
				break
	if raw_rows is None:
		# A direct single-row context is useful for narrow callers and remains
		# closed because only its source-label fields are copied.
		raw_rows = [context_map] if context_map.get("source_label") else []
	rows: list[dict[str, str]] = []
	for raw in raw_rows:
		if not isinstance(raw, dict):
			continue
		line_ref = _text(raw.get("line_ref") or raw.get("ref"))
		label = _text(raw.get("source_label") or raw.get("label"))
		if not label:
			continue
		rows.append(
			{
				"line_ref": line_ref,
				"source_label": label,
				"concept": _text(raw.get("concept")),
				"standard_concept": _text(raw.get("standard_concept")),
				"path": _text(raw.get("path") or raw.get("parent_path")),
			}
		)
	return rows


def _affected_source_context(
	context: dict[str, Any], finding: AnalyticalScanFinding
) -> list[dict[str, str]]:
	"""Return only source-label records attached to saved affected refs."""
	rows = _source_context_rows(context)
	refs = list(finding.affected_line_refs)
	by_ref: dict[str, list[dict[str, str]]] = {}
	for row in rows:
		line_ref = row.get("line_ref")
		if line_ref in refs:
			by_ref.setdefault(line_ref, []).append(row)
	selected: list[dict[str, str]] = []
	for index, ref in enumerate(refs):
		matches = by_ref.get(ref, [])
		row = matches[0] if len(matches) == 1 else None
		if (
			row is None
			and len(rows) == len(refs)
			and not any(item.get("line_ref") for item in rows)
		):
			# Older direct callers supplied only bounded label records. Pair them
			# by their supplied order, never by filing text.
			row = rows[index] if index < len(rows) else None
		if row is not None:
			selected.append({**row, "line_ref": ref})
	return selected


def _safe_source_label(value: object) -> str | None:
	label = " ".join(_text(value).split())
	if (
		not label
		or len(label) > 240
		or _UNSAFE_SOURCE_LABEL_PATTERN.search(label)
		or _INITIAL_UNSAFE_QUERY_PATTERN.search(label)
	):
		return None
	return label


def _initial_query_for_label(label: str) -> tuple[str, str | None]:
	"""Choose the existing static fallback for one source label."""
	lower = label.casefold()
	if any(token in lower for token in ("income", "expense", "gain", "loss")):
		return f"{label} included", "included"
	return label, None


def _initial_generic_qualifier(row: dict[str, str], label: str) -> str | None:
	"""Return one unambiguous generic noun from supplied concept metadata."""
	if _INITIAL_LABEL_NOUN_PATTERN.search(label):
		return None
	metadata = " ".join(
		_text(row.get(field)) for field in ("concept", "standard_concept")
	).casefold()
	matches = [
		qualifier
		for token, qualifier in _INITIAL_GENERIC_QUALIFIERS
		if token in metadata
	]
	return matches[0] if len(set(matches)) == 1 else None


def _initial_query_record(
	query: str,
	line_ref: str,
	label: str,
	cue: str | None,
) -> dict[str, Any]:
	return InitialQueryDerivation(
		query=query,
		line_refs=[line_ref],
		source_label=label,
		generic_cue=cue,
	).model_dump(mode="json")


def build_initial_search_plan(
	finding: AnalyticalScanFinding,
	affected_source_context: dict[str, Any],
) -> tuple[FindingSearchPlan, list[dict[str, Any]]]:
	"""Build bounded literal seeds from the saved finding and source labels."""
	if not isinstance(finding, AnalyticalScanFinding):
		raise TypeError("finding must be an AnalyticalScanFinding")
	rows = _affected_source_context(affected_source_context, finding)

	# Keep the supplied affected-reference order stable; no filing knowledge is
	# used to rank or replace a source label. All candidate phrases are bounded
	# by the five fixed generic movement cues plus one static fallback per row.
	ordered_rows = rows
	derivations: list[dict[str, Any]] = []
	seen: set[str] = set()
	for row in ordered_rows:
		label = _safe_source_label(row.get("source_label"))
		if label is None:
			continue
		subject = label
		qualifier = _initial_generic_qualifier(row, label)
		if qualifier:
			subject = f"{label} {qualifier}"
		for cue, phrase in _INITIAL_MOVEMENT_CUES:
			query = f"{subject} {phrase}"
			if len(query) > MAX_QUERY_LENGTH:
				continue
			key = query.casefold()
			if key in seen:
				for derivation in derivations:
					if derivation["query"].casefold() == key:
						if row["line_ref"] not in derivation["line_refs"]:
							derivation["line_refs"].append(row["line_ref"])
						break
				continue
			seen.add(key)
			derivations.append(
				_initial_query_record(query, row["line_ref"], label, cue)
			)
		query, cue = _initial_query_for_label(label)
		if len(query) > MAX_QUERY_LENGTH:
			continue
		key = query.casefold()
		if key in seen:
			for derivation in derivations:
				if derivation["query"].casefold() == key:
					if row["line_ref"] not in derivation["line_refs"]:
						derivation["line_refs"].append(row["line_ref"])
					break
			continue
		seen.add(key)
		derivations.append(_initial_query_record(query, row["line_ref"], label, cue))
	plan = FindingSearchPlan(
		finding_rank=finding.rank,
		affected_line_refs=list(finding.affected_line_refs),
		investigation_questions=list(finding.investigation_questions),
		queries=[item["query"] for item in derivations[:MAX_QUERIES]],
	)
	return plan, derivations


def build_finding_plan_context(
	pnl: pd.DataFrame,
	filing: Any,
	finding: AnalyticalScanFinding,
) -> dict[str, Any]:
	"""Build source-label context; filing text is intentionally excluded."""
	if not isinstance(finding, AnalyticalScanFinding):
		raise TypeError("finding must be an AnalyticalScanFinding")
	rows: list[dict[str, str]] = []
	for ref in finding.affected_line_refs:
		match = re.fullmatch(r"L(\d+)", ref)
		position = -1 if match is None else int(match.group(1)) - 1
		if 0 <= position < len(pnl):
			row = pnl.iloc[position]
			rows.append(
				{
					"line_ref": ref,
					"source_label": _text(row.get("label"))
					or _text(row.get("concept")),
					"concept": _text(row.get("concept")),
					"standard_concept": _text(row.get("standard_concept")),
				}
			)
	return {
		"filing_identity": _filing_identity(filing),
		"context_method": "persisted finding plus affected source-label context",
		"source_line_count": len(pnl),
		"lines": rows,
	}


def run_search_plan(
	ticker: str,
	finding: AnalyticalScanFinding,
	filing_context: dict[str, Any],
	*,
	run_id: str | None = None,
) -> tuple[FindingSearchPlan, dict[str, Any]]:
	"""Make deterministic initial seeds; no model call occurs in this stage."""
	if not isinstance(finding, AnalyticalScanFinding):
		raise TypeError("finding must be an AnalyticalScanFinding")
	plan, derivations = build_initial_search_plan(finding, filing_context)
	run_id = run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
	return plan, {
		"ticker": ticker.strip().upper(),
		"schema_version": SCHEMA_VERSION,
		"run_id": run_id,
		"pass": "initial",
		"seed_strategy": "deterministic_finding_source_label_movement_v2",
		"planner_call_count": 0,
		"query_count": len(plan.queries),
		"candidate_count": len(derivations),
		"accepted_query_count": len(plan.queries),
		"rejected_query_count": 0,
		"query_derivations": derivations,
		"timestamp_utc": datetime.now(UTC).isoformat(),
	}


def _expansion_rejection(reason: str, candidate: object) -> dict[str, Any]:
	return {
		"candidate": candidate if isinstance(candidate, dict) else str(candidate),
		"reason": reason,
	}


def validate_query_expansion(
	expansion: FilingQueryExpansion | dict[str, Any],
	initial_packet: str,
	initial_queries: Sequence[str],
	*,
	source_text: str | None = None,
) -> tuple[list[FilingGroundedQuery], dict[str, Any]]:
	"""Admit only verbatim queries supported by the first exact packet.

	When ``source_text`` is supplied by the filing retriever, the packet check
	is repeated against the filing text before any second retrieval call.  The
	packet remains the model's only input, while this independent check prevents
	a forged or stale packet excerpt from authorizing a query.
	"""
	try:
		parsed = (
			expansion
			if isinstance(expansion, FilingQueryExpansion)
			else FilingQueryExpansion.model_validate(expansion)
		)
		packet = _validated_packet(initial_packet)
	except (FilingEvidenceError, ValueError, TypeError) as exc:
		raise FilingInvestigationError(str(exc)) from exc
	accepted: list[FilingGroundedQuery] = []
	rejected: list[dict[str, Any]] = []
	seen = {query.casefold() for query in initial_queries}
	for candidate in parsed.queries:
		query = candidate.query
		if query != query.strip():
			rejected.append(
				_expansion_rejection(
					"query must be exactly trimmed", candidate.model_dump(mode="json")
				)
			)
			continue
		if _REGEX_SYNTAX_PATTERN.search(query):
			rejected.append(
				_expansion_rejection(
					"query contains regex syntax", candidate.model_dump(mode="json")
				)
			)
			continue
		if re.search(r"\d|[$€£]", query):
			rejected.append(
				_expansion_rejection(
					"query must not contain a numeric or currency term",
					candidate.model_dump(mode="json"),
				)
			)
			continue
		meaningful_tokens = [
			token for token in re.split(r"\s+", query) if re.search(r"[A-Za-z]", token)
		]
		if len(meaningful_tokens) < 2:
			rejected.append(
				_expansion_rejection(
					"query must contain at least two meaningful tokens",
					candidate.model_dump(mode="json"),
				)
			)
			continue
		if query.casefold() in seen:
			rejected.append(
				_expansion_rejection(
					"query duplicates an existing literal",
					candidate.model_dump(mode="json"),
				)
			)
			continue
		if not candidate.evidence_refs:
			rejected.append(
				_expansion_rejection(
					"query has no first-pass evidence refs",
					candidate.model_dump(mode="json"),
				)
			)
			continue
		unknown = sorted(set(candidate.evidence_refs).difference(packet["items"]))
		if unknown:
			rejected.append(
				_expansion_rejection(
					"unknown first-pass evidence ref: " + ", ".join(unknown),
					candidate.model_dump(mode="json"),
				)
			)
			continue
		matching_refs = [
			ref
			for ref in candidate.evidence_refs
			if candidate.support_span in packet["items"][ref]["excerpt"]
		]
		if not matching_refs or len(matching_refs) != len(candidate.evidence_refs):
			rejected.append(
				_expansion_rejection(
					"every support ref must contain the verbatim support span",
					candidate.model_dump(mode="json"),
				)
			)
			continue
		if query not in candidate.support_span:
			rejected.append(
				_expansion_rejection(
					"query is not contained in the verbatim support span",
					candidate.model_dump(mode="json"),
				)
			)
			continue
		if source_text is not None and (
			candidate.query not in source_text
			or candidate.support_span not in source_text
		):
			rejected.append(
				_expansion_rejection(
					"query/support span is not literal filing text",
					candidate.model_dump(mode="json"),
				)
			)
			continue
		seen.add(query.casefold())
		accepted.append(candidate)
		if len(accepted) >= MAX_QUERIES:
			break
	if len(parsed.queries) > MAX_QUERIES:
		for candidate in parsed.queries[MAX_QUERIES:]:
			rejected.append(
				_expansion_rejection(
					"expansion query limit exceeded", candidate.model_dump(mode="json")
				)
			)
	return accepted, {
		"candidate_count": len(parsed.queries),
		"accepted_query_count": len(accepted),
		"rejected_query_count": len(rejected),
		"rejected_candidates": rejected,
		"queries": [candidate.model_dump(mode="json") for candidate in accepted],
		"filing_text_verification": (
			"performed" if source_text is not None else "not_available"
		),
	}


def run_filing_query_expansion(
	initial_packet: str,
	initial_queries: Sequence[str],
	*,
	filing: Any | None = None,
	client: Any | None = None,
	model: str = DEFAULT_MODEL,
	reasoning_effort: str = DEFAULT_REASONING_EFFORT,
	run_id: str | None = None,
	initial_evidence_file: str | None = None,
) -> tuple[list[FilingGroundedQuery], dict[str, Any]]:
	"""Make one packet-only Structured Output expansion call."""
	try:
		initial_packet_data = _validated_packet(initial_packet)
	except FilingEvidenceError as exc:
		raise FilingInvestigationError(str(exc)) from exc
	source_text: str | None = None
	if filing is not None:
		try:
			source_text = filing.text()
		except Exception as exc:
			raise FilingInvestigationError(
				f"filing text failed before expansion validation: {exc}"
			) from exc
		if not isinstance(source_text, str) or not source_text:
			raise FilingInvestigationError(
				"filing text is empty before expansion validation"
			)
	call_id = run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
	payload = {
		"initial_queries": list(initial_queries),
		"evidence_packet": initial_packet,
	}
	try:
		response = _client(client).responses.parse(
			model=model,
			reasoning={"effort": reasoning_effort},
			input=[
				{"role": "system", "content": _EXPANSION_PROMPT},
				{
					"role": "user",
					"content": json.dumps(payload, ensure_ascii=False, allow_nan=False),
				},
			],
			text_format=FilingQueryExpansion,
		)
		parsed = _parse(response, FilingQueryExpansion)
		accepted, validation = validate_query_expansion(
			parsed,
			initial_packet,
			initial_queries,
			source_text=source_text,
		)
	except FilingInvestigationError:
		raise
	except Exception as exc:
		raise FilingInvestigationError(
			f"filing query expansion call failed: {exc}"
		) from exc
	return accepted, {
		"status": "applied" if accepted else "no_valid_queries",
		"pass": "expansion",
		"pass_count": 1,
		"expansion_call_count": 1,
		"model": model,
		"reasoning_effort": reasoning_effort,
		"prompt_version": EXPANSION_PROMPT_VERSION,
		"schema_version": SCHEMA_VERSION,
		"run_id": call_id,
		"source_evidence_file": initial_evidence_file,
		"source_evidence_refs": sorted(initial_packet_data["items"]),
		**validation,
		"timestamp_utc": datetime.now(UTC).isoformat(),
	}


def build_observed_movement(
	pnl: pd.DataFrame,
	finding: AnalyticalScanFinding,
) -> list[dict[str, Any]]:
	"""Copy finding rows and calculate only source-value year-over-year differences."""
	if not isinstance(pnl, pd.DataFrame):
		raise TypeError("pnl must be a pandas DataFrame")
	periods = [
		column
		for column in pnl.columns
		if isinstance(column, str) and ANNUAL_PERIOD_PATTERN.fullmatch(column)
	]
	if not periods:
		raise FilingInvestigationError("P&L contains no annual FY periods")
	rows: list[dict[str, Any]] = []
	for ref in finding.affected_line_refs:
		match = re.fullmatch(r"L(\d+)", ref)
		position = -1 if match is None else int(match.group(1)) - 1
		if position < 0 or position >= len(pnl):
			raise FilingInvestigationError(
				f"finding line reference is outside P&L: {ref}"
			)
		row = pnl.iloc[position]
		values = {period: _finite(row.get(period)) for period in periods}
		deltas = []
		for index, period in enumerate(periods[:-1]):
			current, previous = (
				_finite(row.get(period)),
				_finite(row.get(periods[index + 1])),
			)
			deltas.append(
				{
					"period": period,
					"previous_period": periods[index + 1],
					"difference": None
					if current is None or previous is None
					else current - previous,
				}
			)
		rows.append(
			{
				"line_ref": ref,
				"source_label": _text(row.get("label")) or _text(row.get("concept")),
				"concept": _text(row.get("concept")) or None,
				"standard_concept": _text(row.get("standard_concept")) or None,
				"periods": values,
				"year_over_year": deltas,
			}
		)
	return rows


def validate_financial_investigation(
	result: FinancialInvestigationResult | dict[str, Any],
	evidence_packet: str,
	*,
	allowed_periods: set[str] | None = None,
) -> FinancialInvestigationResult:
	"""Validate packet references and preserve unsupported claims as unknown."""
	try:
		parsed = (
			result
			if isinstance(result, FinancialInvestigationResult)
			else FinancialInvestigationResult.model_validate(result)
		)
		packet = _validated_packet(evidence_packet)
		validated_drivers: list[DisclosedDriver] = []
		for driver in parsed.disclosed_drivers:
			validate_evidence_refs(
				evidence_packet, driver.evidence_refs, require_identity=True
			)
			evidence_texts = [
				packet["items"][ref]["excerpt"] for ref in driver.evidence_refs
			]
			evidence_text = "\n".join(evidence_texts)
			respectively_ambiguous = any(
				"respectively" in text.casefold() and len(_amount_mentions(text)) > 1
				for text in evidence_texts
			)
			support_span = _matching_support_span(
				driver.evidence_span, driver.evidence_refs, packet
			)
			period_supported = False
			if driver.period is not None:
				period_supported = (
					allowed_periods is not None and driver.period in allowed_periods
				)
				if period_supported:
					year = re.search(r"\d{4}", driver.period)
					period_supported = (
						year is not None
						and re.search(rf"\b{year.group()}\b", evidence_text) is not None
					)
			updates: dict[str, Any] = {}
			if driver.amount is None:
				updates["effect"] = _effect_from_evidence(
					driver.description, evidence_texts
				)
				# An unquantified driver cannot carry stale quantitative metadata.
				# Keep the qualitative description and cited refs, but clear the
				# amount, unit, period, and verbatim numeric support atomically.
				updates.update(
					{
						"amount": None,
						"amount_unit": "unknown",
						"period": None,
						"amount_basis": "unquantified",
						"evidence_span": None,
					}
				)
			else:
				if driver.evidence_span is not None and support_span is None:
					updates["evidence_span"] = None
				if driver.period is not None and not period_supported:
					updates["period"] = None
				amount_supported = (
					driver.period is not None
					and period_supported
					and driver.amount_unit in _COMPARABLE_UNITS
					and support_span is not None
					and not respectively_ambiguous
					and _driver_claim_supported(
						driver.amount,
						driver.amount_unit,
						driver.period,
						support_span,
					)
				)
				if not amount_supported:
					updates.update(
						{
							"amount": None,
							"amount_unit": "unknown",
							"period": None,
							"amount_basis": "unquantified",
							"evidence_span": None,
						}
					)
					updates["effect"] = _effect_from_evidence(
						driver.description, evidence_texts
					)
				elif driver.amount > 0:
					updates["effect"] = "increased_line"
				elif driver.amount < 0:
					updates["effect"] = "decreased_line"
				else:
					updates["effect"] = "unknown"
			if updates:
				driver = DisclosedDriver.model_validate(
					{**driver.model_dump(mode="json"), **updates}
				)
			validated_drivers.append(driver)
		parsed = parsed.model_copy(update={"disclosed_drivers": validated_drivers})
		for driver in parsed.disclosed_drivers:
			_validate_free_text_claims(
				driver.description,
				driver.evidence_refs,
				packet,
				"driver description",
			)
		for refs, label in (
			(parsed.interpretation_evidence_refs, "interpretation"),
			(parsed.unresolved_remainder_evidence_refs, "unresolved remainder"),
			(parsed.explanation_evidence_refs, "explanation"),
		):
			if refs:
				validate_evidence_refs(evidence_packet, refs, require_identity=True)
			elif label == "interpretation" and parsed.interpretation:
				raise FilingEvidenceError("interpretation requires evidence references")
			elif label == "unresolved remainder":
				raise FilingEvidenceError(
					"unresolved remainder requires evidence references"
				)
			elif label == "explanation":
				raise FilingEvidenceError("explanation requires evidence references")
			if label == "interpretation" and parsed.interpretation:
				_validate_free_text_claims(
					parsed.interpretation, refs, packet, "interpretation"
				)
			elif label == "unresolved remainder":
				_validate_free_text_claims(
					parsed.unresolved_remainder,
					refs,
					packet,
					"unresolved remainder",
				)
			elif label == "explanation":
				_validate_free_text_claims(
					parsed.explanation, refs, packet, "explanation"
				)
	except (FilingEvidenceError, ValueError, TypeError) as exc:
		raise FilingInvestigationError(str(exc)) from exc
	return parsed


_COMPARABLE_UNITS = {"dollars", "usd_millions", "usd_billions", "millions", "billions"}

_AMOUNT_TOKEN_PATTERN = re.compile(
	r"(?P<open>\()?\s*(?P<sign>[+-])?"
	r"(?P<prefix>[$€£]|usd\b)?\s*"
	r"(?P<number>\d[\d,]*(?:\.\d+)?)\s*"
	r"(?P<suffix>usd\b|dollars?\b|millions?\b|billions?\b|mn\b|bn\b|m\b|b\b)?"
	r"\s*(?P<close>\))?",
	re.IGNORECASE,
)
_YEAR_PATTERN = re.compile(r"\b(?:19|20)\d{2}\b")
_PROSE_NUMBER_PATTERN = re.compile(r"(?<![A-Za-z0-9])\d[\d,]*(?:\.\d+)?(?![A-Za-z0-9])")
_NARRATIVE_DIGIT_PATTERN = re.compile(r"\d")
_NARRATIVE_SPELLED_NUMBER_PATTERN = re.compile(
	r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|"
	r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|"
	r"eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|"
	r"eighty|ninety|hundred|thousand|million|billion|trillion|"
	r"half|quarter|dozen|single|double|triple|once|twice|"
	r"first|second|third|fourth|fifth|sixth|seventh|eighth|"
	r"ninth|tenth|eleventh|twelfth|thirteenth|fourteenth|"
	r"fifteenth|sixteenth|seventeenth|eighteenth|nineteenth|"
	r"twentieth|thirtieth|fortieth|fiftieth|sixtieth|seventieth|"
	r"eightieth|ninetieth)\b",
	re.IGNORECASE,
)
_CLAUSE_BOUNDARY_PATTERN = re.compile(r"[.!?;:\n]")
_CLAUSE_JOINER_PATTERN = re.compile(
	r"\b(?:and|but|while|whereas|although|however|because|since|though)\b",
	re.IGNORECASE,
)
_TEMPORAL_LINK_PATTERN = re.compile(
	r"(?:\b(?:in|for|during|from|as\s+of|at)\s+"
	r"(?:the\s+)?(?:fiscal\s+)?(?:year\s+|fy\s*)?"
	r"|\b(?:fiscal\s+year|fiscal|year)\s+|\bfy\s*)$",
	re.IGNORECASE,
)
_YEAR_ENDED_LINK_PATTERN = re.compile(
	r"(?:\b(?:in|for|during|from|as\s+of|at)\s+)?(?:the\s+)?"
	r"(?:fiscal\s+)?year\s+(?:ended|ending)\s+(?:"
	r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
	r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|"
	r"Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},?\s*)?$",
	re.IGNORECASE,
)
_AMOUNT_DESCRIPTOR_PATTERN = re.compile(
	r"(?:of\s+)?(?:a\s+|an\s+|the\s+)?(?:net\s+)?"
	r"(?:(?:recognized|reported|recorded)\s+)?"
	r"(?:gain|gains|benefit|benefits|income|loss|losses|expense|expenses|"
	r"cost|costs|decrease|decreased|increase|increased|growth|decline|"
	r"declined)\s*$",
	re.IGNORECASE,
)
_NUMERIC_ARITHMETIC_PATTERN = re.compile(
	r"(?<![A-Za-z0-9])(?:[$€£]\s*)?\d[\d,]*(?:\.\d+)?"
	r"(?:\s+(?:usd|dollars?|millions?|billions?|mn|bn))?\s+"
	r"[+\-−×*/=]\s+(?:[$€£]\s*)?\d[\d,]*(?:\.\d+)?"
	r"(?:\s+(?:usd|dollars?|millions?|billions?|mn|bn))?"
)
_TEXTUAL_ARITHMETIC_PATTERN = re.compile(
	r"\b(?:equals?|equal to|minus|plus|sum of|subtract(?:ed|ing)?|"
	r"calculated|computed)\b",
	re.IGNORECASE,
)
_RESIDUAL_WORD_PATTERN = re.compile(
	r"\b(?:residual|remainder|unexplained|plug|balancing)\b",
	re.IGNORECASE,
)
_SPELLED_AMOUNT_PATTERN = re.compile(
	r"\b(?:a|an|half|quarter|zero|one|two|three|four|five|six|seven|eight|nine|ten|"
	r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|"
	r"eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|"
	r"eighty|ninety)(?:[\s-]+(?:a|an|zero|one|two|three|four|five|"
	r"six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|"
	r"fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|"
	r"forty|fifty|sixty|seventy|eighty|ninety|hundred))*[\s-]+"
	r"(?:thousand|million|billion|trillion|dollars?|usd)\b",
	re.IGNORECASE,
)
_POSITIVE_SEMANTIC_PATTERN = re.compile(
	r"\b(?:gain|gains|benefit|benefits|income|increase|increased|"
	r"increases|increasing|growth|grew|higher|favorable|favourable|"
	r"positive|credit|credits)\b",
	re.IGNORECASE,
)
_NEGATIVE_SEMANTIC_PATTERN = re.compile(
	r"\b(?:loss|losses|expense|expenses|cost|costs|decrease|decreased|"
	r"decreases|decreasing|decline|declined|declines|declining|lower|"
	r"reduced|reduction|negative|debit|debits|charge|charges)\b",
	re.IGNORECASE,
)
_NARRATIVE_TOKEN_PATTERN = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)?")
_NARRATIVE_GENERIC_WORDS_TEXT = """
	a about above after again against all also am an and amount analysis analyst are as assessment associated attributes away be been being below but by complete
	additional after available based before because between both bridge cited claim claims company composition component components conditions contains contribution contributor could
	cause caused causes causing causal disclosed disclose discloses disclosure directly drive driver drivers driven drove described describes description did does do due each either evidence exact excerpt excerpts
	explanation filing fiscal for from generated had has have her here him his identify identified identifies identifying if in include included
	includes including independent indicate indicates information into is latest current leaves line less limited mainly may might more movement net
	another no nor not note notes of on only or other overall packet passage period points portion previous prior primarily provide provided provides quoted related scope
	context detail details explains explain explained explaining partially presents reference references ref refs reported remain remains remaining remainder reports resulted results separately sign some specifically states supplied support supported supports further
	several show shows showing similar state states summary swing than that the their there these they this those through to under unquantified unsupported was were while where which within without would
	verbatim word words would year years unresolved
"""
_NARRATIVE_GENERIC_WORDS = frozenset(_NARRATIVE_GENERIC_WORDS_TEXT.split())
_NARRATIVE_CAUSAL_PATTERN = re.compile(
	r"\b(?:cause[ds]?|causing|drive[sn]?|driven|drove|due\s+to|"
	r"attribut(?:e[ds]?|able\s+to)|result(?:s|ed)?\s+from|"
	r"stem(?:s|med|ming)?\s+from|explain(?:s|ed|ing)?|"
	r"associated\s+with|related\s+to)\b",
	re.IGNORECASE,
)
_NARRATIVE_NAMED_ENTITY_TOKEN_PATTERN = re.compile(
	r"\b(?:[A-Z][A-Za-z]+(?:['’]s)?|[A-Z]{2,})\b"
)


def _amount_unit_family(unit: str) -> str:
	unit = _unit(unit)
	if unit in {"usd_millions", "millions"}:
		return "millions"
	if unit in {"usd_billions", "billions"}:
		return "billions"
	if unit == "dollars":
		return "dollars"
	return "unknown"


def _effect_from_evidence(
	description: str,
	evidence_texts: Sequence[str],
) -> DriverEffect:
	"""Derive an unquantified effect from cited filing polarity words only."""
	description_positive = _POSITIVE_SEMANTIC_PATTERN.search(description) is not None
	description_negative = _NEGATIVE_SEMANTIC_PATTERN.search(description) is not None
	evidence_signs: set[int] = set()
	for text in evidence_texts:
		positive = _POSITIVE_SEMANTIC_PATTERN.search(text) is not None
		negative = _NEGATIVE_SEMANTIC_PATTERN.search(text) is not None
		if positive and negative:
			return "unknown"
		if positive:
			evidence_signs.add(1)
		elif negative:
			evidence_signs.add(-1)
	if description_positive and description_negative:
		return "unknown"
	if description_positive and evidence_signs == {1}:
		return "increased_line"
	if description_negative and evidence_signs == {-1}:
		return "decreased_line"
	return (
		"increased_line"
		if evidence_signs == {1}
		else "decreased_line"
		if evidence_signs == {-1}
		else "unknown"
	)


def _amount_mentions(text: str) -> list[dict[str, Any]]:
	"""Extract only explicitly currency/unit-qualified numeric mentions."""
	mentions: list[dict[str, Any]] = []
	for match in _AMOUNT_TOKEN_PATTERN.finditer(text):
		prefix = (match.group("prefix") or "").casefold()
		suffix = (match.group("suffix") or "").casefold()
		if not prefix and not suffix:
			continue
		try:
			number = float(match.group("number").replace(",", ""))
		except ValueError:
			continue
		if not math.isfinite(number):
			continue
		if suffix.startswith("million") or suffix == "mn" or suffix == "m":
			unit = "millions"
		elif suffix.startswith("billion") or suffix == "bn" or suffix == "b":
			unit = "billions"
		else:
			unit = "dollars"
		sign = match.group("sign")
		before_sign = text[: match.start("sign")].rstrip() if sign else ""
		sign_attached = (
			sign is None
			or match.group("prefix") is not None
			or (match.start("number") == match.end("sign"))
			or not re.search(
				r"(?:\d|usd|dollars?|millions?|billions?|mn|bn|m|b)\s*$",
				before_sign,
				re.IGNORECASE,
			)
		)
		explicit_negative = (sign == "-" and sign_attached) or (
			match.group("open") == "(" and match.group("close") == ")"
		)
		token_start = match.start()
		if sign is not None and not sign_attached:
			token_start = match.start("number")
		mentions.append(
			{
				"value": -number if explicit_negative else number,
				"explicit_sign": sign is not None
				or (match.group("open") == "(" and match.group("close") == ")"),
				"unit": unit,
				"token": text[token_start : match.end()].strip(),
				"start": match.start(),
				"end": match.end(),
			}
		)
	return mentions


def _matching_support_span(
	span: str | None,
	evidence_refs: Sequence[str],
	packet: dict[str, Any],
) -> str | None:
	"""Return a verbatim span found in exactly one cited evidence item."""
	if not span:
		return None
	matches = [
		packet["items"][ref]["excerpt"]
		for ref in evidence_refs
		if span in packet["items"][ref]["excerpt"]
	]
	return span if len(matches) == 1 else None


def _same_local_clause(text: str, first_end: int, second_start: int) -> bool:
	"""Keep amount/period proof inside one short clause, not an adjacent sentence."""
	start, end = sorted((first_end, second_start))
	return not _CLAUSE_BOUNDARY_PATTERN.search(text[start:end])


def _is_temporal_link(value: str) -> bool:
	return bool(
		_TEMPORAL_LINK_PATTERN.search(value) or _YEAR_ENDED_LINK_PATTERN.search(value)
	)


def _temporal_link_is_local(
	text: str, mention: dict[str, Any], year: re.Match[str]
) -> bool:
	"""Require an explicit short temporal link between amount and source year."""
	amount_start = int(mention["start"])
	amount_end = int(mention["end"])
	if not _same_local_clause(text, amount_end, year.start()):
		return False
	if abs(year.start() - amount_end) > 100 and abs(amount_start - year.end()) > 100:
		return False
	if amount_end <= year.start():
		link = text[amount_end : year.start()]
		temporal_match = _TEMPORAL_LINK_PATTERN.search(link)
		if temporal_match is None:
			temporal_match = _YEAR_ENDED_LINK_PATTERN.search(link)
		descriptor = (
			link[: temporal_match.start()].strip(" ,")
			if temporal_match is not None
			else ""
		)
		return (
			("," not in link or _YEAR_ENDED_LINK_PATTERN.search(link) is not None)
			and not _CLAUSE_JOINER_PATTERN.search(link)
			and _is_temporal_link(link)
			and (not descriptor or _AMOUNT_DESCRIPTOR_PATTERN.fullmatch(descriptor))
		)
	prefix = text[max(0, year.start() - 80) : year.start()]
	link = text[year.end() : amount_start]
	return not _CLAUSE_JOINER_PATTERN.search(link) and bool(_is_temporal_link(prefix))


def _semantic_sign(text: str, mention: dict[str, Any]) -> int | None:
	"""Return source polarity near an amount; None means conflicting semantics."""
	start = int(mention["start"])
	end = int(mention["end"])
	left = max(
		(match.end() for match in _CLAUSE_BOUNDARY_PATTERN.finditer(text, 0, start)),
		default=0,
	)
	right_match = _CLAUSE_BOUNDARY_PATTERN.search(text, end)
	right = right_match.start() if right_match else len(text)
	clause = text[left:right]
	positive = _POSITIVE_SEMANTIC_PATTERN.search(clause) is not None
	negative = _NEGATIVE_SEMANTIC_PATTERN.search(clause) is not None
	if positive and negative:
		return None
	if negative:
		return -1
	if positive:
		return 1
	return 0


def _driver_claim_supported(
	amount: float,
	unit: str,
	period: str,
	support_span: str,
) -> bool:
	"""Require one local amount, one local year, and the source sign."""
	if "respectively" in support_span.casefold():
		return False
	mentions = _amount_mentions(support_span)
	year_matches = list(_YEAR_PATTERN.finditer(support_span))
	years = [match.group(0) for match in year_matches]
	period_match = _YEAR_PATTERN.search(period)
	if len(mentions) != 1 or len(years) != 1 or period_match is None:
		return False
	mention = mentions[0]
	try:
		amount_value = float(amount)
		period_year = period_match.group(0)
	except (TypeError, ValueError):
		return False
	if (
		int(mention["value"]) == mention["value"]
		and 1900 <= abs(mention["value"]) <= 2099
	):
		return False
	if not _temporal_link_is_local(support_span, mention, year_matches[0]):
		return False
	semantic_sign = _semantic_sign(support_span, mention)
	if semantic_sign is None:
		return False
	source_value = float(mention["value"])
	if semantic_sign:
		if mention["explicit_sign"] and (
			source_value == 0 or source_value * semantic_sign < 0
		):
			return False
		source_value = abs(source_value) * semantic_sign
	return (
		years[0] == period_year
		and _amount_unit_family(unit) == mention["unit"]
		and math.isclose(amount_value, source_value, rel_tol=0.0, abs_tol=1e-9)
	)


_PAIR_YEAR_PATTERN = re.compile(
	r"\bfor\s+fiscal\s+years?\s+(?P<first>(?:19|20)\d{2})\s+and\s+"
	r"(?P<second>(?:19|20)\d{2})\s*,\s*respectively\b",
	re.IGNORECASE,
)
_PAIR_POSITIVE_PATTERN = re.compile(
	r"\b(?:gain|gains|benefit|benefits|income|increase|increased|"
	r"increases|increasing|growth|credit|credits)\b",
	re.IGNORECASE,
)
_PAIR_NEGATIVE_PATTERN = re.compile(
	r"\b(?:loss|losses|expense|expenses|cost|costs|decrease|decreased|"
	r"decreases|decreasing|decline|declined|declines|charge|charges)\b",
	re.IGNORECASE,
)


def _period_year(period: str) -> str | None:
	match = re.match(r"(19|20)\d{2}", period)
	return None if match is None else match.group(0)


def _pair_source_polarity(
	before_amount: str,
	after_amount: str,
) -> int | None:
	"""Find one local polarity descriptor without borrowing the next amount."""
	signs: list[int] = []
	before = before_amount[-100:]
	before_matches = [
		(1, match)
		for match in _PAIR_POSITIVE_PATTERN.finditer(before)
		if re.fullmatch(r"\s*(?:of|:)\s*", before[match.end() :])
	]
	before_matches.extend(
		(-1, match)
		for match in _PAIR_NEGATIVE_PATTERN.finditer(before)
		if re.fullmatch(r"\s*(?:of|:)\s*", before[match.end() :])
	)
	if before_matches:
		signs.extend(sign for sign, _match in before_matches)

	after = after_amount[:100]
	joiner = re.search(r"\b(?:and|but|while|whereas)\b", after, re.IGNORECASE)
	search_after = after if joiner is None else after[: joiner.start()]
	after_matches = [
		(1, match) for match in _PAIR_POSITIVE_PATTERN.finditer(search_after)
	]
	after_matches.extend(
		(-1, match) for match in _PAIR_NEGATIVE_PATTERN.finditer(search_after)
	)
	signs.extend(sign for sign, _match in after_matches)
	if not signs or len(set(signs)) != 1:
		return None
	return signs[0]


def _parse_two_period_pair(
	excerpt: str,
	label: str,
) -> dict[str, Any] | None:
	"""Extract the deliberately narrow two-amount ``respectively`` grammar."""
	lead = re.escape(label)
	lead_matches = list(
		re.finditer(rf"{lead}\s+included\b", excerpt, flags=re.IGNORECASE)
	)
	lead_matches = [
		match
		for match in lead_matches
		if match.start() == 0 or excerpt[match.start() - 1] in ".;:\n("
	]
	if len(lead_matches) != 1:
		return None
	lead_match = lead_matches[0]
	years_match = None
	for candidate in _PAIR_YEAR_PATTERN.finditer(excerpt, lead_match.end()):
		between = excerpt[lead_match.end() : candidate.start()]
		boundary = False
		for boundary_match in re.finditer(r"[.!?;:\n]", between):
			position = boundary_match.start()
			if (
				between[position] == "."
				and position > 0
				and position + 1 < len(between)
				and between[position - 1].isdigit()
				and between[position + 1].isdigit()
			):
				continue
			boundary = True
			break
		if not boundary:
			years_match = candidate
			break
	if years_match is None:
		return None
	span = excerpt[lead_match.start() : years_match.end()]
	years = [years_match.group("first"), years_match.group("second")]
	if len(set(years)) != 2:
		return None
	mentions = _amount_mentions(span)
	if len(mentions) != 2:
		return None
	if any(
		not re.search(r"(?:^|\s)(?:\$|usd\b)", mention["token"], re.IGNORECASE)
		for mention in mentions
	):
		return None
	units = [_amount_unit_family(mention["unit"]) for mention in mentions]
	if units[0] not in {"millions", "billions"} or units[0] != units[1]:
		return None
	polarities: list[int] = []
	for index, mention in enumerate(mentions):
		before_start = mentions[index - 1]["end"] if index else lead_match.end()
		after_end = (
			mentions[index + 1]["start"] if index + 1 < len(mentions) else len(span)
		)
		polarity = _pair_source_polarity(
			span[before_start : mention["start"]],
			span[mention["end"] : after_end],
		)
		if polarity is None:
			return None
		polarities.append(polarity)
	signed_amounts: list[float] = []
	for mention, polarity in zip(mentions, polarities, strict=True):
		value = float(mention["value"])
		if mention["explicit_sign"] and value != 0 and value * polarity < 0:
			return None
		signed_amounts.append(abs(value) * polarity)
	return {
		"span": span,
		"years": years,
		"amounts": signed_amounts,
		"unit": units[0],
		"polarities": polarities,
	}


def _target_projection(
	pnl: pd.DataFrame,
	finding: AnalyticalScanFinding,
) -> tuple[list[dict[str, Any]], list[str]]:
	rows = build_observed_movement(pnl, finding)
	labels = [row["source_label"] for row in rows if row["source_label"]]
	if len(labels) != len({label.casefold() for label in labels}):
		return [], ["affected source labels are not unique"]
	return rows, []


def extract_period_paired_disclosures(
	pnl: pd.DataFrame,
	finding: AnalyticalScanFinding,
	evidence_packet: str,
	*,
	observed_unit: AmountUnit = "unknown",
) -> dict[str, Any]:
	"""Extract one exact signed two-period disclosure group from packet text."""
	try:
		packet = _validated_packet(evidence_packet)
		rows, mapping_errors = _target_projection(pnl, finding)
	except (
		FilingEvidenceError,
		FilingInvestigationError,
		TypeError,
		ValueError,
	) as exc:
		return {
			"status": "not_computable",
			"facts": [],
			"reason_code": "invalid_input",
			"reason": str(exc),
		}
	if mapping_errors:
		return {
			"status": "not_computable",
			"facts": [],
			"reason_code": "ambiguous_target_mapping",
			"reason": mapping_errors[0],
		}
	periods = [
		column
		for column in pnl.columns
		if isinstance(column, str) and ANNUAL_PERIOD_PATTERN.fullmatch(column)
	]
	if len(periods) < 2:
		return {
			"status": "not_computable",
			"facts": [],
			"reason_code": "missing_period_pair",
			"reason": "P&L does not contain a current/prior annual period pair",
		}
	if _unit(observed_unit) not in {"dollars", "usd_millions", "usd_billions"}:
		return {
			"status": "not_computable",
			"facts": [],
			"reason_code": "unknown_observed_unit",
			"reason": "observed P&L unit is not explicit",
		}
	period_years = [_period_year(period) for period in periods[:2]]
	if any(year is None for year in period_years):
		return {
			"status": "not_computable",
			"facts": [],
			"reason_code": "invalid_period_labels",
			"reason": "current/prior period labels do not expose fiscal years",
		}
	periods_by_year: dict[str, list[str]] = {}
	for period in periods:
		year = _period_year(period)
		if year is not None:
			periods_by_year.setdefault(year, []).append(period)
	if any(
		len(periods_by_year.get(year, [])) != 1
		for year in period_years
		if year is not None
	):
		return {
			"status": "not_computable",
			"facts": [],
			"reason_code": "ambiguous_period_mapping",
			"reason": "a disclosed source year does not map to exactly one P&L period",
		}
	if [
		periods_by_year[year][0] for year in period_years if year is not None
	] != periods[:2]:
		return {
			"status": "not_computable",
			"facts": [],
			"reason_code": "period_mapping_mismatch",
			"reason": "disclosed source years are not the supplied current/prior periods",
		}
	row_by_ref = {row["line_ref"]: row for row in rows}
	candidates: list[dict[str, Any]] = []
	for item_id, item in packet["items"].items():
		matches: list[dict[str, Any]] = []
		for line_ref, row in row_by_ref.items():
			if not row["source_label"]:
				continue
			parsed = _parse_two_period_pair(item["excerpt"], row["source_label"])
			if parsed is not None:
				matches.append({"line_ref": line_ref, "row": row, **parsed})
		if len(matches) > 1:
			return {
				"status": "not_computable",
				"facts": [],
				"reason_code": "ambiguous_evidence_target",
				"reason": f"{item_id} matches more than one affected source label",
			}
		if matches:
			candidate = matches[0]
			candidate["evidence_ref"] = item_id
			candidates.append(candidate)
	if not candidates:
		return {
			"status": "not_computable",
			"facts": [],
			"reason_code": "no_exact_two_period_pair",
			"reason": "packet has no exact target-labelled two-period respectively disclosure",
		}
	groups: dict[tuple[Any, ...], dict[str, Any]] = {}
	for candidate in candidates:
		years = candidate["years"]
		if years != period_years:
			continue
		row = candidate["row"]
		if any(_finite(row["periods"].get(period)) is None for period in periods[:2]):
			return {
				"status": "not_computable",
				"facts": [],
				"reason_code": "missing_target_value",
				"reason": "target source row has a missing current or prior value",
			}
		key_base = (
			candidate["line_ref"],
			candidate["unit"],
			tuple(candidate["years"]),
		)
		amount_key = tuple(round(float(amount), 12) for amount in candidate["amounts"])
		group_key = key_base + (amount_key,)
		group = groups.setdefault(
			group_key,
			{
				"line_ref": candidate["line_ref"],
				"source_label": row["source_label"],
				"years": candidate["years"],
				"amounts": candidate["amounts"],
				"unit": candidate["unit"],
				"polarities": candidate["polarities"],
				"evidence_span": candidate["span"],
				"evidence_refs": [],
			},
		)
		group["evidence_refs"].append(candidate["evidence_ref"])
	groups_by_base: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
	for key, group in groups.items():
		groups_by_base.setdefault(key[:-1], []).append(group)
	conflicting = [
		base for base, base_groups in groups_by_base.items() if len(base_groups) > 1
	]
	if conflicting:
		return {
			"status": "not_computable",
			"facts": [],
			"reason_code": "conflicting_disclosures",
			"reason": "packet contains conflicting amounts for one target period pair",
		}
	if not groups_by_base:
		return {
			"status": "not_computable",
			"facts": [],
			"reason_code": "period_mapping_mismatch",
			"reason": "disclosure years do not map to the supplied current/prior pair",
		}
	if len(groups_by_base) != 1:
		return {
			"status": "not_computable",
			"facts": [],
			"reason_code": "ambiguous_disclosure_groups",
			"reason": "packet contains more than one target disclosure group",
		}
	group = next(iter(next(iter(groups_by_base.values()))))
	facts: list[dict[str, Any]] = []
	unit_name = "usd_millions" if group["unit"] == "millions" else "usd_billions"
	for index, (period, polarity) in enumerate(
		zip(periods[:2], group["polarities"], strict=True)
	):
		facts.append(
			{
				"target_line_ref": group["line_ref"],
				"source_label": group["source_label"],
				"amount": group["amounts"][index],
				"amount_unit": unit_name,
				"period": period,
				"source_year": group["years"][index],
				"effect": "increased_line" if polarity > 0 else "decreased_line",
				"evidence_span": group["evidence_span"],
				"evidence_refs": sorted(set(group["evidence_refs"])),
				"extraction_basis": "exact_two_period_respectively_pair",
			}
		)
	return {
		"status": "extracted",
		"facts": facts,
		"reason_code": "exact_two_period_respectively_pair",
		"candidate_count": len(candidates),
		"group_count": 1,
	}


def _literal_token_supported(token: str, excerpt: str) -> bool:
	"""Match a cited token without allowing a digit substring inside a larger token."""
	token = token.strip()
	if not token:
		return False
	return bool(
		re.search(
			rf"(?<![A-Za-z0-9]){re.escape(token)}(?![A-Za-z0-9])",
			excerpt,
			re.IGNORECASE,
		)
	)


def _validate_free_text_claims(
	text: str,
	evidence_refs: Sequence[str],
	packet: dict[str, Any],
	label: str,
) -> None:
	"""Keep narrative numeric-free and ground specific entities and causes."""
	if _NARRATIVE_DIGIT_PATTERN.search(
		text
	) or _NARRATIVE_SPELLED_NUMBER_PATTERN.search(text):
		raise FilingEvidenceError(f"{label} must be numeric-free")
	cited_text = [packet["items"][ref]["excerpt"] for ref in evidence_refs]
	tokens = _NARRATIVE_TOKEN_PATTERN.findall(text)
	for match in _NARRATIVE_NAMED_ENTITY_TOKEN_PATTERN.finditer(text):
		token = match.group()
		if token.casefold() in _NARRATIVE_GENERIC_WORDS:
			continue
		prefix = text[: match.start()].rstrip()
		if token != token.upper() and (not prefix or prefix[-1] in ".!?"):
			continue
		if not any(_literal_token_supported(token, excerpt) for excerpt in cited_text):
			raise FilingEvidenceError(
				f"{label} contains unsupported named entity: {token}"
			)
	if _NARRATIVE_CAUSAL_PATTERN.search(text):
		concrete_terms = [
			token
			for token in tokens
			if token.casefold() not in _NARRATIVE_GENERIC_WORDS
		]
		if concrete_terms and not all(
			any(_literal_token_supported(token, excerpt) for excerpt in cited_text)
			for token in concrete_terms
		):
			raise FilingEvidenceError(f"{label} contains unsupported causal claim")
	amount_mentions = _amount_mentions(text)
	numeric_tokens = _PROSE_NUMBER_PATTERN.findall(text)
	spelled_amounts = list(_SPELLED_AMOUNT_PATTERN.finditer(text))
	residual_words = _RESIDUAL_WORD_PATTERN.search(text)
	non_year_numeric = [
		token
		for token in numeric_tokens
		if not (token.isdigit() and len(token) == 4 and 1900 <= int(token) <= 2099)
	]
	if residual_words and (amount_mentions or spelled_amounts or non_year_numeric):
		raise FilingEvidenceError(f"{label} must not contain a residual amount or plug")
	for mention in amount_mentions:
		if not any(
			_literal_token_supported(mention["token"], excerpt)
			for excerpt in cited_text
		):
			raise FilingEvidenceError(
				f"{label} contains an amount not present in cited evidence"
			)
	for match in spelled_amounts:
		token = match.group(0)
		if not any(_literal_token_supported(token, excerpt) for excerpt in cited_text):
			raise FilingEvidenceError(
				f"{label} contains an amount not present in cited evidence"
			)
	for token in numeric_tokens:
		if not any(_literal_token_supported(token, excerpt) for excerpt in cited_text):
			raise FilingEvidenceError(
				f"{label} contains a numeric claim not present in cited evidence"
			)
	if _NUMERIC_ARITHMETIC_PATTERN.search(text) or (
		(_PROSE_NUMBER_PATTERN.search(text) or spelled_amounts)
		and _TEXTUAL_ARITHMETIC_PATTERN.search(text)
	):
		raise FilingEvidenceError(f"{label} contains unsupported arithmetic")


def reconcile_disclosed_amounts(
	observed_amount: float | None,
	drivers: Sequence[DisclosedDriver],
	*,
	observed_period: str | None = None,
	observed_unit: AmountUnit = "unknown",
) -> dict[str, Any]:
	"""Sum only finite disclosures with identical explicit period and unit."""
	observed = _finite(observed_amount)
	unit = _unit(observed_unit)
	compatible: list[float] = []
	unquantified = 0
	incompatible = 0
	for raw_driver in drivers:
		driver = (
			raw_driver
			if isinstance(raw_driver, DisclosedDriver)
			else DisclosedDriver.model_validate(raw_driver)
		)
		if driver.amount is None:
			unquantified += 1
			continue
		driver_unit = _unit(driver.amount_unit)
		if (
			driver.period != observed_period
			or observed_period is None
			or driver_unit != unit
			or unit not in _COMPARABLE_UNITS
		):
			incompatible += 1
			continue
		compatible.append(driver.amount)
	known_total = sum(compatible) if compatible else None
	comparable = (
		observed is not None
		and observed_period is not None
		and unit in _COMPARABLE_UNITS
	)
	difference = (
		None
		if not comparable or known_total is None or incompatible
		else observed - known_total
	)
	status = (
		"not_computable"
		if not comparable or known_total is None
		else "partial"
		if incompatible or unquantified
		else "complete"
	)
	return {
		"status": status,
		"observed_amount": observed,
		"observed_period": observed_period,
		"observed_unit": unit,
		"known_disclosed_total": known_total,
		"known_disclosed_driver_count": len(compatible),
		"unquantified_driver_count": unquantified,
		"incompatible_driver_count": incompatible,
		"unresolved_difference": difference,
		"difference_is_reported_plug": False,
	}


def reconcile_period_pair_bridge(
	pnl: pd.DataFrame,
	finding: AnalyticalScanFinding,
	evidence_packet: str,
	*,
	observed_unit: AmountUnit = "unknown",
) -> dict[str, Any]:
	"""Reconcile one exact current/prior disclosure pair in Python only."""
	unit = _unit(observed_unit)
	extraction = extract_period_paired_disclosures(
		pnl,
		finding,
		evidence_packet,
		observed_unit=unit,
	)
	base: dict[str, Any] = {
		"status": "not_computable",
		"target_line_ref": None,
		"target_source_label": None,
		"period": None,
		"previous_period": None,
		"observed_amount": None,
		"observed_unit": unit,
		"observed_amount_comparable": None,
		"comparison_unit": "usd_billions",
		"known_disclosed_contribution": None,
		"known_disclosed_unit": "usd_billions",
		"unresolved_difference": None,
		"difference_is_reported_plug": False,
		"disclosed_facts": [],
		"reason_code": extraction.get("reason_code"),
		"reason": extraction.get("reason"),
	}
	if extraction.get("status") != "extracted":
		return base
	facts = extraction["facts"]
	if len(facts) != 2:
		base.update(
			{
				"reason_code": "invalid_fact_count",
				"reason": "exact bridge requires one current and one prior fact",
			}
		)
		return base
	rows = {row["line_ref"]: row for row in build_observed_movement(pnl, finding)}
	line_ref = facts[0]["target_line_ref"]
	row = rows.get(line_ref)
	if row is None:
		base.update(
			{
				"reason_code": "target_not_in_observed_context",
				"reason": "disclosure target is absent from supplied movement context",
			}
		)
		return base
	periods = [
		column
		for column in pnl.columns
		if isinstance(column, str) and ANNUAL_PERIOD_PATTERN.fullmatch(column)
	]
	if len(periods) < 2 or [facts[0]["period"], facts[1]["period"]] != periods[:2]:
		base.update(
			{
				"reason_code": "period_order_mismatch",
				"reason": "disclosed facts do not map to supplied current/prior periods",
			}
		)
		return base
	current = _finite(row["periods"].get(periods[0]))
	previous = _finite(row["periods"].get(periods[1]))
	if current is None or previous is None:
		base.update(
			{
				"reason_code": "missing_target_value",
				"reason": "target source row has a missing current or prior value",
			}
		)
		return base
	observed_raw = current - previous
	if unit == "dollars":
		observed_comparable = observed_raw / 1_000_000_000
	elif unit == "usd_millions":
		observed_comparable = observed_raw / 1_000
	else:
		observed_comparable = observed_raw
	fact_scale = {"usd_millions": 1 / 1_000, "usd_billions": 1}[facts[0]["amount_unit"]]
	known_contribution = (
		facts[0]["amount"] * fact_scale - facts[1]["amount"] * fact_scale
	)
	base.update(
		{
			"status": "partial",
			"target_line_ref": line_ref,
			"target_source_label": row["source_label"],
			"period": periods[0],
			"previous_period": periods[1],
			"observed_current_amount": current,
			"observed_previous_amount": previous,
			"observed_amount": observed_raw,
			"observed_amount_comparable": observed_comparable,
			"known_disclosed_contribution": known_contribution,
			"unresolved_difference": observed_comparable - known_contribution,
			"disclosed_facts": facts,
			"reason_code": "exact_two_period_respectively_pair",
			"reason": "exact source disclosure explains a validated portion of the movement",
		}
	)
	return base


def run_financial_investigation(
	ticker: str,
	finding: AnalyticalScanFinding,
	pnl: pd.DataFrame,
	evidence_packet: str,
	*,
	expected_filing_accession: str,
	client: Any | None = None,
	model: str = DEFAULT_MODEL,
	reasoning_effort: str = DEFAULT_REASONING_EFFORT,
	run_id: str | None = None,
) -> tuple[FinancialInvestigationResult, dict[str, Any]]:
	"""Make one structured investigator call against the unchanged packet."""
	if not isinstance(finding, AnalyticalScanFinding) or not isinstance(
		pnl, pd.DataFrame
	):
		raise TypeError("finding and pnl have invalid types")
	if not _text(expected_filing_accession):
		raise FilingInvestigationError(
			"expected filing accession is required at the investigation boundary"
		)
	try:
		_validated_packet(
			evidence_packet,
			expected_ticker=ticker,
			expected_filing_accession=expected_filing_accession,
		)
	except FilingEvidenceError as exc:
		raise FilingInvestigationError(str(exc)) from exc
	payload = {
		"ticker": ticker.strip().upper(),
		"finding": finding.model_dump(mode="json"),
		"observed_movement": build_observed_movement(pnl, finding),
		"evidence_packet": evidence_packet,
	}
	allowed_periods = {
		period
		for row in payload["observed_movement"]
		for period in (
			list(row["periods"].keys())
			+ [delta["period"] for delta in row["year_over_year"]]
			+ [delta["previous_period"] for delta in row["year_over_year"]]
		)
	}
	try:
		response = _client(client).responses.parse(
			model=model,
			reasoning={"effort": reasoning_effort},
			input=[
				{"role": "system", "content": _INVESTIGATION_PROMPT},
				{
					"role": "user",
					"content": json.dumps(payload, ensure_ascii=False, allow_nan=False),
				},
			],
			text_format=FinancialInvestigationResult,
		)
		result = validate_financial_investigation(
			_parse(response, FinancialInvestigationResult),
			evidence_packet,
			allowed_periods=allowed_periods,
		)
	except FilingInvestigationError:
		raise
	except Exception as exc:
		raise FilingInvestigationError(
			f"structured financial investigation failed: {exc}"
		) from exc
	run_id = run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
	return result, {
		"ticker": ticker.strip().upper(),
		"model": model,
		"reasoning_effort": reasoning_effort,
		"prompt_version": INVESTIGATION_PROMPT_VERSION,
		"schema_version": SCHEMA_VERSION,
		"run_id": run_id,
		"timestamp_utc": datetime.now(UTC).isoformat(),
	}


def _filing_identity(filing: Any) -> dict[str, str | None]:
	def value(*names: str) -> str | None:
		for name in names:
			candidate = getattr(filing, name, None)
			if candidate is not None and _text(candidate):
				return _text(candidate)
		return None

	return {
		"filing_accession": value("accession_no", "accession_number"),
		"form": value("form"),
		"filing_date": value("filing_date"),
		"period_of_report": value("report_date", "period_of_report"),
		"primary_document": value("primary_document"),
		"filing_url": value("filing_url", "url"),
		"text_url": value("text_url", "source_path"),
	}


def _literal_count(text: str, query: str) -> int:
	"""Count case-insensitive literal occurrences without regex semantics."""
	folded_text, folded_query = text.casefold(), query.casefold()
	if not folded_query:
		return 0
	count = 0
	start = 0
	while (position := folded_text.find(folded_query, start)) >= 0:
		count += 1
		start = position + 1
	return count


def _select_initial_queries(
	filing: Any,
	plan: FindingSearchPlan,
	derivations: list[dict[str, Any]],
) -> tuple[FindingSearchPlan, dict[str, Any]]:
	"""Select literal movement seeds before static fallbacks."""
	try:
		text = filing.text()
	except Exception:
		return plan, {"source_text_filter": "unavailable"}
	if not isinstance(text, str) or not text:
		return plan, {"source_text_filter": "unavailable"}
	line_order = {
		line_ref: index for index, line_ref in enumerate(plan.affected_line_refs)
	}
	cue_order = {
		cue: index for index, (cue, _) in enumerate(_INITIAL_MOVEMENT_CUES)
	}
	def sort_key(item: tuple[int, dict[str, Any]]) -> tuple[int, int, int, int]:
		index, derivation = item
		cue = _text(derivation.get("generic_cue")).casefold()
		is_movement = cue in cue_order
		tier = 0 if is_movement else 1
		movement_order = cue_order.get(cue, len(cue_order))
		ref_order = min(
			(line_order.get(ref, len(line_order)) for ref in derivation.get("line_refs", [])),
			default=len(line_order),
		)
		return tier, movement_order, ref_order, index

	accepted: list[str] = []
	accepted_derivations: list[dict[str, Any]] = []
	rejected: list[dict[str, Any]] = []
	item_budget = MAX_EVIDENCE_ITEMS
	accepted_line_refs: set[str] = set()
	accepted_movement_refs: set[str] = set()
	for _index, derivation in sorted(enumerate(derivations), key=sort_key):
		query = derivation["query"]
		occurrences = _literal_count(text, query)
		if occurrences == 0:
			rejected.append(
				{
					**derivation,
					"reason": "no literal source-text hit",
				}
			)
			continue
		cue = _text(derivation.get("generic_cue")).casefold()
		line_refs = set(derivation.get("line_refs", []))
		if cue not in cue_order and line_refs.intersection(accepted_movement_refs):
			rejected.append(
				{
					**derivation,
					"reason": "static fallback superseded by movement query",
					"occurrence_count": occurrences,
				}
			)
			continue
		if line_refs.intersection(accepted_line_refs):
			rejected.append(
				{
					**derivation,
					"reason": "line already covered by accepted query",
					"occurrence_count": occurrences,
				}
			)
			continue
		if occurrences > item_budget:
			rejected.append(
				{
					**derivation,
					"reason": "literal source-text hits exceed evidence budget",
					"occurrence_count": occurrences,
				}
			)
			continue
		if len(accepted) >= MAX_QUERIES:
			rejected.append(
				{
					**derivation,
					"reason": "initial query limit exceeded",
					"occurrence_count": occurrences,
				}
			)
			continue
		accepted.append(query)
		accepted_derivations.append(derivation)
		item_budget -= occurrences
		accepted_line_refs.update(line_refs)
		if cue in cue_order:
			accepted_movement_refs.update(line_refs)
	return plan.model_copy(update={"queries": accepted}), {
		"source_text_filter": "literal_occurrence_budget",
		"candidate_count": len(derivations),
		"accepted_query_count": len(accepted),
		"rejected_query_count": len(rejected),
		"rejected_candidates": rejected,
		"query_derivations": accepted_derivations,
		"candidate_derivations": derivations,
	}


def _save_payload(
	ticker: str,
	payload: dict[str, Any],
	output_root: str | Path,
	run_id: str,
	rank: int,
) -> Path:
	path = (
		Path(output_root)
		/ ticker
		/ "03_output"
		/ "analysis"
		/ f"filing_investigation_{rank:02d}_{run_id}.json"
	)
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(
		json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False, default=str)
		+ "\n",
		encoding="utf-8",
	)
	return path


def investigate_finding(
	ticker: str,
	pnl: pd.DataFrame,
	filing: Any,
	finding: AnalyticalScanFinding,
	*,
	scan_path: str | Path | None = None,
	scan_metadata: dict[str, Any] | None = None,
	scan_context: str | None = None,
	filing_context: dict[str, Any] | None = None,
	output_root: str | Path = "data",
	observed_unit: AmountUnit = "unknown",
	client: Any | None = None,
	model: str = DEFAULT_MODEL,
	reasoning_effort: str = DEFAULT_REASONING_EFFORT,
	run_id: str | None = None,
) -> tuple[dict[str, Any], Path]:
	"""Run one plan -> retrieve -> investigate flow and persist its status."""
	if not isinstance(finding, AnalyticalScanFinding):
		raise TypeError("finding must be an AnalyticalScanFinding")
	ticker = ticker.strip().upper()
	run_id = run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
	if scan_context is not None:
		try:
			context_matches = format_analytical_pnl_for_scan(pnl) == scan_context
		except (TypeError, ValueError) as exc:
			raise FilingInvestigationError(
				f"saved scan context cannot be checked: {exc}"
			) from exc
		if not context_matches:
			raise FilingInvestigationError(
				"saved scan context does not match current P&L"
			)
	expected = (scan_metadata or {}).get("filing_accession")
	actual = _filing_identity(filing).get("filing_accession")
	if expected and actual != str(expected).strip():
		raise FilingInvestigationError(
			"filing accession does not match saved Analytical Scan"
		)
	if filing_context is None:
		plan_context = build_finding_plan_context(pnl, filing, finding)
	else:
		plan_context = {
			"filing_identity": filing_context.get("filing_identity", {})
			if isinstance(filing_context, dict)
			else {},
			"context_method": "supplied affected source-label context",
			"source_line_count": filing_context.get("source_line_count")
			if isinstance(filing_context, dict)
			else None,
			"lines": _source_context_rows(filing_context),
		}
	payload: dict[str, Any] = {
		"metadata": {
			"ticker": ticker,
			"run_id": run_id,
			"finding_rank": finding.rank,
			"scan_run_id": (scan_metadata or {}).get("run_id"),
			"scan_path": None if scan_path is None else str(scan_path),
			"scan_metadata": scan_metadata or {},
			"model": model,
			"reasoning_effort": reasoning_effort,
			"investigation_prompt_version": INVESTIGATION_PROMPT_VERSION,
			"schema_version": SCHEMA_VERSION,
			"observed_unit": _unit(observed_unit),
			"filing_accession": _filing_identity(filing).get("filing_accession"),
			"filing": _filing_identity(filing),
		},
		"finding": finding.model_dump(mode="json"),
		"scan_context": scan_context,
		"plan_context": {
			"filing_identity": plan_context.get("filing_identity", {}),
			"context_method": plan_context.get("context_method"),
			"source_line_count": plan_context.get("source_line_count"),
			"line_count": len(plan_context.get("lines", [])),
		},
		"status": "started",
		"plan": None,
		"retrieval": None,
		"quantified_disclosures": None,
		"evidence_path": None,
		"investigation": None,
		"interpretation": None,
		"unresolved_remainder": None,
		"explanation": None,
		"observed_movement": None,
		"reconciliation": None,
	}
	try:
		payload["observed_movement"] = build_observed_movement(pnl, finding)
		plan, plan_metadata = run_search_plan(
			ticker,
			finding,
			plan_context,
			run_id=run_id,
		)
		plan, selection_metadata = _select_initial_queries(
			filing,
			plan,
			plan_metadata.get("query_derivations", []),
		)
		plan_metadata = {
			**plan_metadata,
			**selection_metadata,
			"query_count": len(plan.queries),
			"rejected_query_count": plan_metadata.get("rejected_query_count", 0)
			+ selection_metadata.get("rejected_query_count", 0),
		}
		payload["plan"] = {
			"metadata": plan_metadata,
			"result": plan.model_dump(mode="json"),
		}
		if not plan.queries:
			payload.update(
				{
					"status": "no_queries",
					"error_stage": "retrieval",
					"error_message": "deterministic seed generation returned no safe literal queries",
					"retrieval": {
						"status": "not_run",
						"initial": {
							"stage": "initial",
							"pass": "initial",
							"status": "not_run",
							"queries": [],
						},
					},
				}
			)
			return payload, _save_payload(
				ticker, payload, output_root, run_id, finding.rank
			)
		initial_evidence_path = (
			Path(output_root)
			/ ticker
			/ "03_output"
			/ "evidence"
			/ f"finding_{finding.rank:02d}_{run_id}_initial.md"
		)
		initial_packet, initial_retrieval_metadata = retrieve_filing_evidence(
			filing,
			ticker,
			f"finding-{finding.rank}",
			plan.queries,
			output_path=initial_evidence_path,
		)
		initial_stage = {
			**initial_retrieval_metadata,
			"stage": "initial",
			"pass": "initial",
			"status": "retrieved",
			"query_derivations": plan_metadata.get("query_derivations", []),
			"candidate_count": plan_metadata.get("candidate_count", len(plan.queries)),
			"accepted_query_count": len(plan.queries),
			"rejected_query_count": plan_metadata.get("rejected_query_count", 0),
			"retrieval_pass_count": 1,
		}
		final_packet = initial_packet
		final_retrieval_metadata = initial_stage
		final_evidence_path = initial_evidence_path
		expansion_metadata: dict[str, Any]
		try:
			expanded, expansion_metadata = run_filing_query_expansion(
				initial_packet,
				plan.queries,
				filing=filing,
				client=client,
				model=model,
				reasoning_effort=reasoning_effort,
				run_id=run_id,
				initial_evidence_file=str(initial_evidence_path),
			)
		except FilingInvestigationError as exc:
			expanded = []
			expansion_metadata = {
				"status": "failed",
				"pass": "expansion",
				"pass_count": 1,
				"expansion_call_count": 1,
				"model": model,
				"reasoning_effort": reasoning_effort,
				"prompt_version": EXPANSION_PROMPT_VERSION,
				"schema_version": SCHEMA_VERSION,
				"run_id": run_id,
				"source_evidence_file": str(initial_evidence_path),
				"source_evidence_refs": [
					f"E{index}"
					for index in range(
						1,
						int(initial_retrieval_metadata.get("evidence_item_count", 0))
						+ 1,
					)
				],
				"candidate_count": 0,
				"accepted_query_count": 0,
				"rejected_query_count": 0,
				"rejected_candidates": [],
				"error": str(exc),
				"timestamp_utc": datetime.now(UTC).isoformat(),
			}
		if expanded:
			final_evidence_path = (
				Path(output_root)
				/ ticker
				/ "03_output"
				/ "evidence"
				/ f"finding_{finding.rank:02d}_{run_id}.md"
			)
			try:
				final_packet, final_raw_metadata = retrieve_filing_evidence(
					filing,
					ticker,
					f"finding-{finding.rank}",
					[*plan.queries, *(query.query for query in expanded)],
					output_path=final_evidence_path,
				)
				identity_keys = (
					"filing_accession",
					"source_url",
					"text_url",
					"primary_document",
				)
				if any(
					final_raw_metadata.get(key) != initial_stage.get(key)
					for key in identity_keys
				):
					raise FilingInvestigationError(
						"expanded retrieval changed filing identity"
					)
				final_retrieval_metadata = {
					**final_raw_metadata,
					"stage": "final",
					"pass": "final",
					"status": "retrieved",
					"retrieval_pass_count": 1,
					"initial_evidence_file": str(initial_evidence_path),
					"initial_queries": list(plan.queries),
					"expansion_queries": [
						query.model_dump(mode="json") for query in expanded
					],
				}
			except (FilingEvidenceError, FilingInvestigationError) as exc:
				expansion_metadata = {
					**expansion_metadata,
					"status": "failed",
					"retrieval_error": str(exc),
				}
				final_packet = initial_packet
				final_evidence_path = initial_evidence_path
				final_retrieval_metadata = initial_stage
		payload["retrieval"] = {
			**final_retrieval_metadata,
			"initial": initial_stage,
			"expansion": expansion_metadata,
			"final": final_retrieval_metadata,
		}
		payload["evidence_path"] = str(final_evidence_path)
		result, result_metadata = run_financial_investigation(
			ticker,
			finding,
			pnl,
			final_packet,
			expected_filing_accession=_filing_identity(filing).get("filing_accession"),
			client=client,
			model=model,
			reasoning_effort=reasoning_effort,
			run_id=run_id,
		)
		payload["investigation"] = {
			"metadata": result_metadata,
			"result": result.model_dump(mode="json"),
		}
		payload["interpretation"] = result.interpretation
		payload["unresolved_remainder"] = {
			"text": result.unresolved_remainder,
			"evidence_refs": result.unresolved_remainder_evidence_refs,
		}
		payload["explanation"] = result.explanation
		payload["explanation_evidence_refs"] = result.explanation_evidence_refs
		payload["quantified_disclosures"] = extract_period_paired_disclosures(
			pnl,
			finding,
			final_packet,
			observed_unit=observed_unit,
		)
		payload["reconciliation"] = _movement_reconciliation(
			pnl,
			finding,
			result,
			final_packet,
			observed_unit=observed_unit,
		)
		payload["status"] = "completed"
	except (
		FilingInvestigationError,
		FilingEvidenceError,
		AnalyticalScanError,
		ValueError,
		TypeError,
	) as exc:
		payload.update(
			{
				"status": "failed",
				"error_stage": "plan"
				if payload["plan"] is None
				else "retrieval"
				if payload["retrieval"] is None
				else "investigation",
				"error_message": str(exc),
			}
		)
	return payload, _save_payload(ticker, payload, output_root, run_id, finding.rank)


def _movement_reconciliation(
	pnl: pd.DataFrame,
	finding: AnalyticalScanFinding,
	result: FinancialInvestigationResult,
	evidence_packet: str | None = None,
	*,
	observed_unit: AmountUnit = "dollars",
) -> dict[str, Any]:
	if evidence_packet is not None:
		return reconcile_period_pair_bridge(
			pnl,
			finding,
			evidence_packet,
			observed_unit=observed_unit,
		)
	observed_rows = build_observed_movement(pnl, finding)
	if len(observed_rows) != 1:
		return reconcile_disclosed_amounts(None, result.disclosed_drivers)
	movement = observed_rows[0]["year_over_year"]
	# A three-year P&L has two possible deltas. Without a period mapping in the
	# saved finding, choosing one would silently reconcile the wrong movement.
	if len(movement) != 1:
		return reconcile_disclosed_amounts(None, result.disclosed_drivers)
	bridge = movement[0]
	if bridge["difference"] is None:
		return reconcile_disclosed_amounts(None, result.disclosed_drivers)
	return reconcile_disclosed_amounts(
		bridge["difference"],
		result.disclosed_drivers,
		observed_period=bridge["period"],
		observed_unit="dollars",
	)


def render_finding_investigation_summary(
	payload: dict[str, Any] | FinancialInvestigationResult,
	finding: AnalyticalScanFinding | None = None,
) -> str:
	"""Render observed, disclosed, interpreted, and unresolved sections."""
	if isinstance(payload, FinancialInvestigationResult):
		result = payload
		data = finding.model_dump(mode="json") if finding else {}
		status = "completed"
	else:
		data = payload.get("finding", {})
		investigation = payload.get("investigation") or {}
		result_data = investigation.get("result")
		result = (
			None
			if result_data is None
			else FinancialInvestigationResult.model_validate(result_data)
		)
		status = payload.get("status", "unknown")
	lines = [f"Finding {data.get('rank', '')}: {data.get('title', '')}".rstrip()]
	lines.append(f"Observed movement: {data.get('observation', 'N/A')}")
	if result is None:
		lines.extend(
			[
				f"Disclosed explanation: unavailable ({status})",
				"Interpretation: N/A",
				"Unresolved remainder: investigation did not complete",
			]
		)
		return "\n".join(lines)
	lines.append("Disclosed explanation:")
	if not result.disclosed_drivers:
		lines.append("  None disclosed")
	for driver in result.disclosed_drivers:
		amount = (
			"unquantified"
			if driver.amount is None
			else f"{driver.amount:g} {driver.amount_unit}"
		)
		if driver.amount is not None and driver.period is not None:
			amount = f"{amount} for {driver.period}"
		lines.append(
			f"  - {driver.description}: {amount} [{', '.join(driver.evidence_refs)}]"
		)
	refs = (
		f" [{', '.join(result.interpretation_evidence_refs)}]"
		if result.interpretation_evidence_refs
		else ""
	)
	lines.append(f"Interpretation: {result.interpretation or 'N/A'}{refs}")
	lines.append(f"Explanation: {result.explanation}")
	refs = (
		f" [{', '.join(result.unresolved_remainder_evidence_refs)}]"
		if result.unresolved_remainder_evidence_refs
		else ""
	)
	lines.append(f"Unresolved remainder: {result.unresolved_remainder}{refs}")
	return "\n".join(lines)


def load_saved_scan(
	path: str | Path,
	ticker: str,
	pnl: pd.DataFrame | None = None,
) -> tuple[AnalyticalScanResult, AnalyticalScanFinding, str, dict[str, Any]]:
	"""Validate a persisted scan, including exact context when P&L is supplied."""
	try:
		payload = json.loads(Path(path).read_text(encoding="utf-8"))
	except (OSError, json.JSONDecodeError) as exc:
		raise FilingInvestigationError(f"could not read saved scan: {exc}") from exc
	if not isinstance(payload, dict):
		raise FilingInvestigationError("saved scan must be a JSON object")
	metadata, context = payload.get("metadata"), payload.get("context")
	if not isinstance(metadata, dict) or not isinstance(context, str) or not context:
		raise FilingInvestigationError("saved scan is missing metadata or context")
	if _text(metadata.get("ticker")).upper() != ticker.strip().upper():
		raise FilingInvestigationError(
			"saved scan ticker does not match requested ticker"
		)
	refs = set(_LINE_REF_PATTERN.findall(context))
	if not refs:
		raise FilingInvestigationError("saved scan context contains no line references")
	try:
		result = validate_analytical_scan_result(payload.get("result", {}), refs)
	except AnalyticalScanError as exc:
		raise FilingInvestigationError(str(exc)) from exc
	if not metadata.get("run_id"):
		raise FilingInvestigationError("saved scan metadata is missing run_id")
	if not _text(metadata.get("filing_accession")):
		raise FilingInvestigationError(
			"saved scan metadata is missing filing_accession"
		)
	if pnl is not None:
		try:
			context_matches = format_analytical_pnl_for_scan(pnl) == context
		except (TypeError, ValueError) as exc:
			raise FilingInvestigationError(
				f"saved scan context cannot be checked: {exc}"
			) from exc
		if not context_matches:
			raise FilingInvestigationError(
				"saved scan context does not match current P&L"
			)
	if not result.findings:
		raise FilingInvestigationError("saved scan contains no findings")
	return result, result.findings[0], context, metadata


def select_saved_finding(
	result: AnalyticalScanResult, rank: int
) -> AnalyticalScanFinding:
	if rank < 1 or rank > MAX_FINDINGS:
		raise FilingInvestigationError(
			f"finding rank must be between 1 and {MAX_FINDINGS}"
		)
	for finding in result.findings:
		if finding.rank == rank:
			return finding
	raise FilingInvestigationError(f"saved scan has no finding at rank {rank}")


def latest_scan_path(ticker: str, output_root: str | Path = "data") -> Path:
	directory = Path(output_root) / ticker.strip().upper() / "03_output" / "analysis"
	paths = list(directory.glob("analytical_scan_*.json"))
	if not paths:
		raise FilingInvestigationError(
			f"no saved analytical scan found for {ticker.strip().upper()}"
		)
	return max(paths, key=lambda path: path.stat().st_mtime)
