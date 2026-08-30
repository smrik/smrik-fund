"""Deterministic checks over one product result.

Every check is evaluated independently.  An earlier harness wrapped a single
product validator in one try/except and wrote the same exception text into three
different check ids, which made the report look like three signals when it was
one.  Here the reused product validator is exactly one check, and the harness
adds its own independent assertions alongside it.

``numeric_grounding`` is the check that carries the segment-margin contract: the
deterministic pipeline already computes ``operating_margin`` and its bps change
into ``segment_analytics.csv``, so any margin the model states must match that
computation rather than being re-derived or invented.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

import pandas as pd

from ..ingestion.adjustments import resolve_current_adjustments
from ..ingestion.filing import parse_evidence_packet
from ..ingestion.filing_investigation import (
	FinancialInvestigationResult,
	validate_financial_investigation,
)
from .cases import sha256_file

# Relative tolerance for matching a stated figure to a computed one.
_RELATIVE_TOLERANCE = 0.01
# Figures at or below this magnitude are too ambiguous to ground (counts, ranks).
_TRIVIAL_MAGNITUDE = 10.0

_HASHED_INPUTS = (
	("source_artifact", "source_sha256"),
	("source_manifest_artifact", "source_manifest_sha256"),
	("scan_artifact", "scan_sha256"),
	("analytical_pnl_artifact", "analytical_pnl_sha256"),
	("reconciliation_artifact", "reconciliation_sha256"),
	("segment_analytics_artifact", "segment_analytics_sha256"),
	("segment_reconciliation_artifact", "segment_reconciliation_sha256"),
)

_SCALES = {
	"bn": 1e9,
	"billion": 1e9,
	"b": 1e9,
	"m": 1e6,
	"million": 1e6,
	"mm": 1e6,
	"k": 1e3,
	"thousand": 1e3,
}

_PROSE_FIGURE = re.compile(
	r"(?<![\w.])(-?\d[\d,]*\.?\d*)\s*"
	r"(%|bps|basis points|bn|billion|b\b|mm|m\b|million|k\b|thousand)?",
	re.IGNORECASE,
)


def check(
	check_id: str, status: str, *, critical: bool, **extra: Any
) -> dict[str, Any]:
	return {"id": check_id, "status": status, "critical": critical, **extra}


def source_integrity(case: dict[str, Any], repository_root: str | Path) -> dict[str, Any]:
	"""Verify every frozen input still matches its recorded hash."""
	mismatches: list[dict[str, str | None]] = []
	verified = 0
	for path_key, hash_key in _HASHED_INPUTS:
		relative = case.get(path_key)
		expected = case.get(hash_key)
		if not relative or not expected:
			continue
		path = Path(repository_root) / relative
		actual = sha256_file(path)
		if actual != str(expected).upper():
			mismatches.append(
				{"input": path_key, "path": str(relative), "expected": str(expected), "actual": actual}
			)
		else:
			verified += 1
	if mismatches:
		return check(
			"source_integrity",
			"FAIL",
			critical=True,
			verified=verified,
			mismatches=mismatches,
			reason="frozen input content does not match the recorded hash",
		)
	return check("source_integrity", "PASS", critical=True, verified=verified)


def _grounded_magnitudes(
	pnl: pd.DataFrame, segments: pd.DataFrame | None
) -> tuple[set[float], set[float]]:
	"""Return absolute currency magnitudes and ratio/bps figures we can ground."""
	amounts: set[float] = set()
	ratios: set[float] = set()

	numeric = pnl.select_dtypes("number")
	for column in numeric.columns:
		values = [float(v) for v in numeric[column].dropna().tolist()]
		amounts.update(abs(v) for v in values)
		# Year-over-year deltas between adjacent annual columns are legitimate
		# derived magnitudes, so ground them too.
	columns = list(numeric.columns)
	for left, right in zip(columns, columns[1:], strict=False):
		delta = (numeric[left] - numeric[right]).dropna()
		amounts.update(abs(float(v)) for v in delta.tolist())

	if segments is not None:
		for column in ("numeric_value", "value", "absolute_yoy_change"):
			if column in segments:
				amounts.update(
					abs(float(v)) for v in pd.to_numeric(
						segments[column], errors="coerce"
					).dropna().tolist()
				)
		for column in (
			"yoy_growth",
			"revenue_share",
			"operating_margin",
			"revenue_growth_contribution",
			"operating_income_growth_contribution",
			"operating_growth_contribution",
		):
			if column in segments:
				ratios.update(
					abs(float(v)) for v in pd.to_numeric(
						segments[column], errors="coerce"
					).dropna().tolist()
				)
		for column in (
			"revenue_share_change_bps",
			"revenue_share_bps_change",
			"operating_margin_bps_change",
			"margin_bps_change",
		):
			if column in segments:
				ratios.update(
					abs(float(v)) / 10_000.0
					for v in pd.to_numeric(
						segments[column], errors="coerce"
					).dropna().tolist()
				)

	amounts.discard(0.0)
	ratios.discard(0.0)
	return amounts, ratios


def _matches(value: float, candidates: set[float]) -> bool:
	return any(
		math.isclose(value, candidate, rel_tol=_RELATIVE_TOLERANCE)
		for candidate in candidates
	)


def _prose_figures(text: str) -> list[tuple[str, float, str]]:
	"""Extract (literal, magnitude, kind) triples from narrative prose."""
	figures: list[tuple[str, float, str]] = []
	for match in _PROSE_FIGURE.finditer(text or ""):
		literal, suffix = match.group(1), (match.group(2) or "").lower().strip()
		try:
			number = float(literal.replace(",", ""))
		except ValueError:
			continue
		if suffix == "%":
			figures.append((match.group(0).strip(), abs(number) / 100.0, "ratio"))
		elif suffix in {"bps", "basis points"}:
			figures.append((match.group(0).strip(), abs(number) / 10_000.0, "ratio"))
		elif suffix in _SCALES:
			figures.append(
				(match.group(0).strip(), abs(number) * _SCALES[suffix], "amount")
			)
		elif abs(number) > _TRIVIAL_MAGNITUDE and not _looks_like_year(number):
			figures.append((match.group(0).strip(), abs(number), "amount"))
	return figures


def _looks_like_year(value: float) -> bool:
	return value.is_integer() and 1900 <= value <= 2100


def numeric_grounding(
	result: FinancialInvestigationResult,
	pnl: pd.DataFrame,
	segments: pd.DataFrame | None,
) -> dict[str, Any]:
	"""Every stated figure must reconcile to the deterministic analytics."""
	amounts, ratios = _grounded_magnitudes(pnl, segments)
	ungrounded: list[dict[str, Any]] = []
	checked = 0

	for index, driver in enumerate(result.disclosed_drivers):
		if driver.amount is None:
			continue
		checked += 1
		scale = _SCALES.get(str(driver.amount_unit).lower(), 1.0)
		magnitude = abs(float(driver.amount)) * scale
		if not (_matches(magnitude, amounts) or _matches(abs(float(driver.amount)), amounts)):
			ungrounded.append(
				{
					"location": f"disclosed_drivers[{index}].amount",
					"stated": driver.amount,
					"unit": driver.amount_unit,
				}
			)

	prose = {
		"interpretation": result.interpretation or "",
		"explanation": result.explanation,
		"unresolved_remainder": result.unresolved_remainder,
	}
	for index, driver in enumerate(result.disclosed_drivers):
		prose[f"disclosed_drivers[{index}].description"] = driver.description

	for location, text in prose.items():
		for literal, magnitude, kind in _prose_figures(text):
			checked += 1
			pool = ratios if kind == "ratio" else amounts
			if not _matches(magnitude, pool):
				ungrounded.append(
					{"location": location, "stated": literal, "kind": kind}
				)

	if ungrounded:
		return check(
			"numeric_grounding",
			"FAIL",
			critical=True,
			checked=checked,
			ungrounded=ungrounded,
			reason="stated figures do not reconcile to the frozen analytics",
		)
	if checked == 0:
		# An output that states no figures cannot be checked for grounding.
		# Reporting PASS here would look like evidence of correctness when the
		# check simply had nothing to examine.
		return check(
			"numeric_grounding",
			"NOT_APPLICABLE",
			critical=True,
			checked=0,
			reason="output stated no figures to ground",
		)
	return check("numeric_grounding", "PASS", critical=True, checked=checked)


def evidence_refs(
	result: FinancialInvestigationResult, packet: str
) -> dict[str, Any]:
	"""Every cited reference must exist in the frozen evidence packet."""
	try:
		parsed = parse_evidence_packet(packet)
	except Exception as exc:  # noqa: BLE001 - reported, not swallowed
		return check(
			"evidence_refs", "FAIL", critical=True, reason=f"unparsable packet: {exc}"
		)
	known = set(parsed.get("items", {}))
	cited: set[str] = set(result.interpretation_evidence_refs)
	cited.update(result.explanation_evidence_refs)
	cited.update(result.unresolved_remainder_evidence_refs)
	for driver in result.disclosed_drivers:
		cited.update(driver.evidence_refs)
	unknown = sorted(cited - known)
	if unknown:
		return check(
			"evidence_refs",
			"FAIL",
			critical=True,
			unknown_refs=unknown,
			known_count=len(known),
			reason="result cites references absent from the evidence packet",
		)
	return check(
		"evidence_refs", "PASS", critical=True, cited=len(cited), known=len(known)
	)


def amount_basis(result: FinancialInvestigationResult) -> dict[str, Any]:
	"""Quantified drivers must carry a period, a real unit, and a span."""
	incomplete: list[dict[str, Any]] = []
	quantified = sum(1 for d in result.disclosed_drivers if d.amount is not None)
	if quantified == 0:
		return check(
			"amount_basis",
			"NOT_APPLICABLE",
			critical=True,
			quantified=0,
			reason="output contained no quantified drivers",
		)
	for index, driver in enumerate(result.disclosed_drivers):
		if driver.amount is None:
			continue
		missing = [
			field
			for field, value in (
				("period", driver.period),
				("evidence_span", driver.evidence_span),
			)
			if not value
		]
		if str(driver.amount_unit).lower() == "unknown":
			missing.append("amount_unit")
		if missing:
			incomplete.append(
				{"location": f"disclosed_drivers[{index}]", "missing": missing}
			)
	if incomplete:
		return check(
			"amount_basis",
			"FAIL",
			critical=True,
			incomplete=incomplete,
			reason="quantified drivers are missing required basis metadata",
		)
	return check("amount_basis", "PASS", critical=True, quantified=quantified)


def product_validator(
	result: FinancialInvestigationResult,
	packet: str,
	allowed_periods: set[str] | None,
) -> dict[str, Any]:
	"""Run the product's own validator and report its verdict as one check."""
	try:
		validate_financial_investigation(
			result, packet, allowed_periods=allowed_periods
		)
	except Exception as exc:  # noqa: BLE001 - the product raises several types
		return check(
			"product_validator",
			"FAIL",
			critical=True,
			reason=str(exc),
			exception=type(exc).__name__,
		)
	return check("product_validator", "PASS", critical=True)


def candidate_fields(
	candidates: list[Any],
	pnl: pd.DataFrame,
	packet: str,
	*,
	research_request: str | None = None,
	expected: dict[str, Any] | None = None,
	relative_tolerance: float = _RELATIVE_TOLERANCE,
) -> list[dict[str, Any]]:
	"""Field assertions on proposed normalization candidates.

	The specification is explicit that LLM evals test fields, not wording, so
	these are deterministic rather than judge questions.

	``expected`` is optional: a verified expected candidate has to be written by
	a person who has read the filing, and inventing one would freeze whatever
	the model currently emits as the right answer.
	"""
	if not candidates:
		# Declining to propose is a valid outcome, not a failure: an analyst that
		# invents a candidate from a packet with nothing normalizable in it is
		# worse than one that says so. It is only a failure when the analyst
		# returns nothing and offers no reason - or when a human-verified
		# expected candidate exists, which no proposal can then match.
		if research_request:
			results = [
				check(
					"candidate_found",
					"NOT_APPLICABLE",
					critical=True,
					candidates=0,
					research_request=research_request,
					reason="analyst declined to propose and stated what it needs",
				)
			]
		else:
			results = [
				check(
					"candidate_found",
					"FAIL",
					critical=True,
					reason="analyst proposed no candidates and gave no reason",
				)
			]
		if expected is not None:
			results.append(
				check(
					"candidate_matches_expected",
					"FAIL",
					critical=True,
					expected=expected,
					stated=[],
					reason="no candidate proposed for the expected known case",
				)
			)
		return results

	labels = set(pnl.get("label", pd.Series(dtype=str)).dropna().astype(str))
	periods = {
		c
		for c in pnl.columns
		if isinstance(c, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2} \(FY\)", c)
	}
	try:
		known_refs = set(parse_evidence_packet(packet).get("items", {}))
	except Exception:  # noqa: BLE001 - packet validity is its own concern
		known_refs = set()

	problems: list[dict[str, Any]] = []
	for index, candidate in enumerate(candidates):
		where = f"candidates[{index}]"
		if candidate.target_line not in labels:
			problems.append({"at": where, "field": "target_line", "stated": candidate.target_line})
		if candidate.period not in periods:
			problems.append({"at": where, "field": "period", "stated": candidate.period})
		unknown = sorted(set(candidate.evidence_refs) - known_refs)
		if unknown:
			problems.append({"at": where, "field": "evidence_refs", "stated": unknown})
		if candidate.item_amount is not None and candidate.item_amount < 0:
			problems.append({"at": where, "field": "item_amount", "stated": candidate.item_amount})

	results = [
		check(
			"candidate_found",
			"PASS",
			critical=True,
			candidates=len(candidates),
			quantified=sum(1 for c in candidates if c.item_amount is not None),
		),
		check("candidate_fields", "FAIL", critical=True, problems=problems,
			reason="target_line, period, refs, and amount sign must match the inputs")
		if problems
		else check("candidate_fields", "PASS", critical=True),
	]

	if expected is None:
		results.append(
			check(
				"candidate_matches_expected",
				"NOT_APPLICABLE",
				critical=True,
				reason="no human-verified expected candidate defined for this case",
			)
		)
		return results

	matches = [
		c
		for c in candidates
		if c.target_line == expected["target_line"] and c.period == expected["period"]
	]
	amount = expected.get("item_amount")
	if matches and (
		amount is None
		or any(
			c.item_amount is not None
			and math.isclose(c.item_amount, float(amount), rel_tol=relative_tolerance)
			for c in matches
		)
	):
		results.append(check("candidate_matches_expected", "PASS", critical=True))
	else:
		results.append(
			check(
				"candidate_matches_expected",
				"FAIL",
				critical=True,
				expected=expected,
				stated=[
					{"target_line": c.target_line, "period": c.period, "item_amount": c.item_amount}
					for c in candidates
				],
				reason="no candidate matches the expected target, period, and amount",
			)
		)
	return results


def scan_findings(findings: list[Any]) -> dict[str, Any]:
	"""The scan must surface something to investigate.

	Reference validity is already enforced product-side, and whether a finding
	is a *real* abnormality is a judgment, not a mechanical assertion - so that
	question goes to the judge rather than here.
	"""
	if not findings:
		return check(
			"scan_found_movements", "FAIL", critical=True, reason="scan returned no findings"
		)
	refs = {str(r) for f in findings for r in f.affected_line_refs}
	return check(
		"scan_found_movements",
		"PASS",
		critical=True,
		findings=len(findings),
		refs_cited=len(refs),
	)


def adjustment_set(
	history: pd.DataFrame,
	expected: list[dict[str, Any]],
	*,
	relative_tolerance: float = _RELATIVE_TOLERANCE,
) -> dict[str, Any]:
	"""Assert the approved adjustments are exactly the expected ones.

	This is the "did the adjustment do its job" check.  It deliberately reads
	adjustment records rather than diffing a reported and an adjusted metric
	series: the records already state which line and period moved, so the
	cheaper read answers the same question.

	The third assertion - that nothing else moved - is the one that earns the
	check.  It catches over-adjustment and silent plugs, which a "the expected
	adjustment exists" test would pass straight through.
	"""
	try:
		current = resolve_current_adjustments(history)
	except (TypeError, ValueError) as exc:
		return check(
			"adjustment_set", "FAIL", critical=True, reason=f"unresolvable history: {exc}"
		)

	if current.empty:
		return check(
			"adjustment_set",
			"NOT_APPLICABLE",
			critical=True,
			approved=0,
			reason="no approved adjustments to assess",
		)

	applied: dict[tuple[str, str], float] = {}
	for _, row in current.iterrows():
		key = (
			str(row.get("target_row_key") or row.get("target_line") or ""),
			str(row.get("period") or ""),
		)
		delta = pd.to_numeric(row.get("line_delta"), errors="coerce")
		if pd.notna(delta):
			applied[key] = applied.get(key, 0.0) + float(delta)

	missing: list[dict[str, Any]] = []
	wrong: list[dict[str, Any]] = []
	matched: set[tuple[str, str]] = set()
	for item in expected:
		key = (str(item["target"]), str(item["period"]))
		if key not in applied:
			missing.append({"target": key[0], "period": key[1]})
			continue
		matched.add(key)
		if not math.isclose(
			applied[key], float(item["line_delta"]), rel_tol=relative_tolerance
		):
			wrong.append(
				{
					"target": key[0],
					"period": key[1],
					"expected": item["line_delta"],
					"applied": applied[key],
				}
			)

	unexpected = [
		{"target": key[0], "period": key[1], "applied": value}
		for key, value in sorted(applied.items())
		if key not in matched and value != 0.0
	]

	if missing or wrong or unexpected:
		return check(
			"adjustment_set",
			"FAIL",
			critical=True,
			approved=len(applied),
			missing=missing,
			wrong_amount=wrong,
			unexpected=unexpected,
			reason="approved adjustments do not match the expected set",
		)
	return check("adjustment_set", "PASS", critical=True, approved=len(applied))


def diagnostics(
	result: FinancialInvestigationResult, payload: dict[str, Any]
) -> list[dict[str, Any]]:
	"""Non-critical observations that never gate the judge."""
	unquantified = sum(
		1 for driver in result.disclosed_drivers if driver.amount is None
	)
	expansion = (payload.get("retrieval") or {}).get("expansion") or {}
	return [
		check(
			"quantification",
			"PASS",
			critical=False,
			drivers=len(result.disclosed_drivers),
			unquantified=unquantified,
		),
		check(
			"expansion",
			"PASS",
			critical=False,
			expansion_status=expansion.get("status"),
			accepted=expansion.get("accepted_query_count"),
		),
	]


def is_critical_failure(checks: list[dict[str, Any]]) -> bool:
	return any(c.get("critical") and c.get("status") == "FAIL" for c in checks)
