import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import pandas as pd
import typer

from .ingestion.adjustment_analysis import (
	DEFAULT_MODEL,
	DEFAULT_REASONING_EFFORT,
	AdjustmentAnalysisError,
	run_analyst,
	valid_item_key,
)
from .ingestion.adjustments import (
	ADJUSTMENT_SCHEMA_VERSION,
	IDENTITY_VERSION,
	_find_line_index,
	_is_derived_line,
	apply_adjustments,
	derive_line_delta,
	resolve_current_adjustments,
)
from .ingestion.adjustments import (
	identity_components as _identity_components,
)
from .ingestion.adjustments import (
	validated_history_identity_rows as _validated_history_identity_rows,
)
from .ingestion.analytical_scan import (
	AnalyticalScanError,
	format_analytical_pnl_for_scan,
	render_analytical_scan_summary,
	run_analytical_scan,
	save_analytical_scan,
)
from .ingestion.discovery import (
	DiscoveryError,
	DiscoveryResult,
	build_discovery_context,
	deduplicate_topics,
	run_discovery,
	save_discovery_result,
)
from .ingestion.filing import (
	FilingEvidenceError,
	retrieve_filing_evidence,
	validate_evidence_refs,
)
from .ingestion.reconciliation import (
	reconcile_pnl,
	save_reconciliation_checks,
)
from .ingestion.reviewer import (
	ReviewerError,
	run_reviewer,
	save_reviewer_result,
)
from .ingestion.risk_gate import (
	RiskGateConditions,
	evaluate_risk_gate,
)
from .ingestion.statements import (
	ANNUAL_PERIOD_PATTERN,
	build_analytical_pnl,
	load_analytical_pnl,
	save_analytical_pnl,
)

app = typer.Typer(
	no_args_is_help=True, help="A small fundamental investment research system."
)


def _reconciliation_summary(checks: pd.DataFrame) -> dict[str, int]:
	return {
		"passed": int((checks["status"] == "PASS").sum()),
		"failed": int((checks["status"] == "FAIL").sum()),
		"skipped": int((checks["status"] == "SKIPPED").sum()),
	}


def _save_and_report_reconciliation(
	ticker: str,
	pnl: pd.DataFrame,
	output_root: str | Path = "data",
) -> Path:
	checks = reconcile_pnl(pnl)
	output_path = save_reconciliation_checks(ticker, checks, output_root)

	for check in checks.to_dict(orient="records"):
		if check["status"] in {"FAIL", "SKIPPED"}:
			typer.echo(
				f"WARNING {check['check_id']} {check['period']}: {check['message']}"
			)

	summary = _reconciliation_summary(checks)
	typer.echo(
		f"Reconciliation: {summary['passed']} passed, "
		f"{summary['failed']} failed, {summary['skipped']} skipped"
	)
	typer.echo(f"Saved reconciliation checks: {output_path}")
	return output_path


def _new_run_id() -> str:
	return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")


_HISTORY_COLUMNS = (
	"adjustment_id",
	"version",
	"candidate_identity",
	"candidate_state",
	"target_line",
	"period",
	"amount",
	"status",
)

# Keep Reviewer fan-out finite without truncating an Analyst response.
MAX_CANDIDATES_PER_TOPIC = 3

# Provisional auto-approval materiality limits (M3). These are placeholder
# constants, not calibrated policy; the benchmark milestone owns recalibration.
# Every applicable ratio must pass. An unavailable denominator yields None,
# which fails closed — an unknown size is never auto-approvable.
_AUTO_MATERIALITY_LIMITS = {
	"pct_revenue": 0.01,
	"pct_operating_income": 0.05,
	"pct_target_line": 0.10,
}

# Shadow mode (M3): the gate computes what it would do under the provisional
# policy, but canonical approval rows are never written from that result.
# Flip to True only after benchmark results justify live auto-approval (M5).
ENABLE_CANONICAL_AUTO_APPROVAL = False


def _materiality_eligible(metrics: dict[str, float | None]) -> bool:
	"""True only when every provisional ratio exists, is non-negative, and
	passes its limit. A negative ratio means a negative denominator (e.g. a
	net-loss line), where size-relative materiality is meaningless — that
	fails closed rather than sliding under the limit."""
	for name, limit in _AUTO_MATERIALITY_LIMITS.items():
		value = metrics.get(name)
		if value is None or value < 0 or value > limit:
			return False
	return True


def _load_adjustment_history(path: Path) -> pd.DataFrame:
	if not path.is_file():
		return pd.DataFrame(columns=_HISTORY_COLUMNS)
	try:
		return pd.read_csv(path)
	except pd.errors.EmptyDataError:
		return pd.DataFrame(columns=_HISTORY_COLUMNS)


def _next_adjustment_id(history: pd.DataFrame, offset: int = 0) -> str:
	pattern = re.compile(r"^A(\d+)$")
	numbers = [
		int(match.group(1))
		for value in history.get("adjustment_id", pd.Series(dtype="string"))
		if (match := pattern.fullmatch(str(value)))
	]
	return f"A{max(numbers, default=0) + offset + 1:04d}"


def _reported_source_value(
	pnl: pd.DataFrame,
	target_line: object,
	period: object,
) -> float | None:
	"""Return one exact signed reported value, or None when it is unavailable."""
	if period not in pnl.columns:
		return None
	try:
		line_index = _find_line_index(pnl, target_line)
	except (KeyError, ValueError):
		return None
	value = pd.to_numeric(
		pd.Series([pnl.at[line_index, period]]), errors="coerce"
	).iloc[0]
	if pd.isna(value):
		return None
	value = float(value)
	return value if math.isfinite(value) else None


def _canonical_json(value: object) -> str:
	return json.dumps(
		value,
		ensure_ascii=False,
		sort_keys=True,
		separators=(",", ":"),
	)


def _candidate_state(candidate: Any) -> dict[str, Any]:
	amount = candidate.item_amount
	return {
		"item_amount": None if amount is None else float(amount),
		"item_effect_on_line": candidate.item_effect_on_line,
		"amount_basis": candidate.amount_basis,
	}


def _target_row_key(pnl: pd.DataFrame, target_line: object) -> str:
	"""Return a deterministic selector for one non-derived source row.

	A unique standard concept is stable across presentation-label drift. When a
	concept occurs more than once, existing row metadata (normally the label)
	keeps the duplicate rows distinct. A label is the last safe fallback when a
	standard concept is unavailable.
	"""
	try:
		line_index = _find_line_index(pnl, target_line)
	except (KeyError, ValueError) as exc:
		raise FilingEvidenceError(
			"candidate target line is missing or ambiguous; row identity is unsafe"
		) from exc
	if _is_derived_line(pnl, line_index):
		raise FilingEvidenceError("candidate target line is missing, ambiguous, or derived")

	def text_value(value: object) -> str | None:
		try:
			if pd.isna(value):
				return None
		except (TypeError, ValueError):
			pass
		text = str(value).strip()
		return text or None

	def value_for_at(row: object, field: str) -> str | None:
		if field not in pnl:
			return None
		return text_value(pnl.at[row, field])

	def value_for(field: str) -> str | None:
		return value_for_at(line_index, field)

	def matches(field: str, value: str) -> list[object]:
		if field not in pnl:
			return []
		return pnl.index[pnl[field].eq(value).fillna(False)].tolist()

	standard_concept = value_for("standard_concept")
	if standard_concept is not None:
		concept_rows = matches("standard_concept", standard_concept)
		if len(concept_rows) == 1:
			return f"standard_concept:{standard_concept}"
		if len(concept_rows) > 1:
			# Keep the standard concept in the key, then add the first existing
			# metadata field that uniquely identifies this duplicate row.
			for field in (
				"label",
				"concept",
				"parent_concept",
				"dimension_axis",
				"dimension_member",
				"dimension_label",
				"dimension_member_label",
				"balance",
				"weight",
			):
				metadata_value = value_for(field)
				if metadata_value is None:
					continue
				duplicate_rows = [
					row
					for row in concept_rows
					if value_for_at(row, field) == metadata_value
				]
				if len(duplicate_rows) == 1:
					return (
						f"standard_concept:{standard_concept}|"
						f"{field}:{metadata_value}"
					)
			raise FilingEvidenceError("candidate target row has no stable selector")

	label = value_for("label")
	if label is not None and len(matches("label", label)) == 1:
		return f"label:{label}"
	raise FilingEvidenceError("candidate target row has no stable selector")


def _candidate_identity(
	ticker: str,
	pnl: pd.DataFrame,
	candidate: Any,
	packet_identity: dict[str, Any],
) -> str:
	"""Build economic identity only; packet provenance is deliberately ignored."""
	del packet_identity
	ticker = ticker.strip().upper()
	if not ticker:
		raise FilingEvidenceError("company identity is missing")
	if (
		not isinstance(candidate.period, str)
		or not ANNUAL_PERIOD_PATTERN.fullmatch(candidate.period)
		or candidate.period not in pnl.columns
	):
		raise FilingEvidenceError("candidate period is not an exact annual P&L period")
	try:
		line_index = _find_line_index(pnl, candidate.target_line)
	except (KeyError, ValueError) as exc:
		raise FilingEvidenceError(
			"candidate target line is missing, ambiguous, or derived"
		) from exc
	if _is_derived_line(pnl, line_index):
		raise FilingEvidenceError("candidate target line is missing, ambiguous, or derived")
	if _reported_source_value(pnl, candidate.target_line, candidate.period) is None:
		raise FilingEvidenceError("candidate target value is missing or non-finite")
	if not valid_item_key(candidate.item_key):
		raise FilingEvidenceError("candidate item_key is missing or invalid")
	return _canonical_json(
		{
			"identity_version": IDENTITY_VERSION,
			"company": ticker,
			"fiscal_period": candidate.period,
			"target_row_key": _target_row_key(pnl, candidate.target_line),
			"item_key": candidate.item_key,
		}
	)


def _canonical_history_json(value: object) -> str | None:
	if value is None:
		return None
	try:
		if pd.isna(value):
			return None
	except (TypeError, ValueError):
		pass
	text = str(value).strip()
	if not text or text.casefold() == "nan":
		return None
	try:
		return _canonical_json(json.loads(text))
	except (TypeError, ValueError, json.JSONDecodeError):
		return None


def _canonical_history_frame(history: pd.DataFrame) -> pd.DataFrame | None:
	"""Return only validated v2 rows for resolution, or None when unsafe."""
	rows = _validated_history_identity_rows(history)
	if rows is None:
		return None
	if not rows:
		return history.iloc[0:0].copy()
	return history.iloc[[row["_source_index"] for row in rows]].copy()


def _history_identity_complete(history: pd.DataFrame) -> bool:
	"""Return whether canonical history is safe to resolve or apply."""
	return _validated_history_identity_rows(history) is not None


def _history_identity_lookup(
	history: pd.DataFrame,
	identity: str,
	state: str,
) -> dict[str, Any]:
	"""Resolve exact economic identity and fail closed on occupied conflicts."""
	if history.empty:
		return {"status": "new", "adjustment_id": None, "version": 0}
	identity_rows = _validated_history_identity_rows(history)
	if identity_rows is None:
		return {
			"status": "identity_unresolved",
			"adjustment_id": None,
			"version": 0,
			"reason": "history contains legacy or corrupted identity data",
		}
	identity_parts = _identity_components(identity)
	if identity_parts is None:
		return {
			"status": "identity_unresolved",
			"adjustment_id": None,
			"version": 0,
			"reason": "candidate identity is invalid",
		}
	matching_rows = [
		row
		for row in identity_rows
		if row["_identity"] == identity_parts
	]
	occupied_rows = [
		row
		for row in identity_rows
		if all(
			row["_identity"][field] == identity_parts[field]
			for field in ("company", "fiscal_period", "target_row_key")
		)
	]
	selector_drift_rows = [
		row
		for row in identity_rows
		if all(
			row["_identity"][field] == identity_parts[field]
			for field in ("company", "fiscal_period", "item_key")
		)
	]
	selector_family = identity_parts["target_row_key"].split("|", 1)[0]
	selector_family_rows = [
		row
		for row in identity_rows
		if row["_identity"]["company"] == identity_parts["company"]
		and row["_identity"]["fiscal_period"] == identity_parts["fiscal_period"]
		and row["_identity"]["target_row_key"].split("|", 1)[0]
		== selector_family
	]
	if not matching_rows:
		if occupied_rows:
			return {
				"status": "identity_unresolved",
				"adjustment_id": None,
				"version": 0,
				"reason": "occupied row-period has a competing item_key",
			}
		if selector_drift_rows:
			return {
				"status": "identity_unresolved",
				"adjustment_id": None,
				"version": 0,
				"reason": "matching item_key has a changed target-row selector",
			}
		if selector_family_rows and "|" in identity_parts["target_row_key"]:
			return {
				"status": "identity_unresolved",
				"adjustment_id": None,
				"version": 0,
				"reason": "occupied concept-period has an ambiguous row selector",
			}
		return {"status": "new", "adjustment_id": None, "version": 0}
	matching_ids = {str(row["adjustment_id"]) for row in matching_rows}
	if len(matching_ids) != 1:
		return {
			"status": "identity_unresolved",
			"adjustment_id": None,
			"version": 0,
			"reason": "identity is assigned to multiple adjustment IDs",
		}
	adjustment_id = next(iter(matching_ids))
	id_rows = [row for row in identity_rows if row["adjustment_id"] == adjustment_id]
	approved_rows = [row for row in id_rows if row.get("status") == "approved"]
	if not approved_rows:
		latest = max(id_rows, key=lambda row: row["version"])
	else:
		# Current state is governed by the latest approved version. A newer
		# rejected/proposed workflow row must not hide that effective version.
		latest = max(approved_rows, key=lambda row: row["version"])
	latest_version = latest["version"]
	status = str(latest.get("status", ""))
	if _canonical_history_json(latest.get("candidate_state")) != _canonical_history_json(state):
		return {
			"status": "state_conflict",
			"adjustment_id": adjustment_id,
			"version": latest_version,
			"latest": latest,
		}
	return {
		"status": "replay" if status == "approved" else "blocked_existing",
		"adjustment_id": adjustment_id,
		"version": latest_version,
		"latest": latest,
	}


def _materiality_metrics(
	pnl: pd.DataFrame,
	candidate: Any,
) -> dict[str, float | None]:
	amount = candidate.item_amount
	if amount is None:
		return {
			"pct_revenue": None,
			"pct_target_line": None,
			"pct_operating_income": None,
		}
	try:
		amount_number = float(amount)
	except (TypeError, ValueError):
		return {
			"pct_revenue": None,
			"pct_target_line": None,
			"pct_operating_income": None,
		}
	if not math.isfinite(amount_number):
		return {
			"pct_revenue": None,
			"pct_target_line": None,
			"pct_operating_income": None,
		}
	period = candidate.period
	denominators = {
		"pct_revenue": _reported_source_value(pnl, "Revenue", period),
		"pct_target_line": _reported_source_value(pnl, candidate.target_line, period),
		"pct_operating_income": _reported_source_value(
			pnl, "Operating income", period
		),
	}
	return {
		name: (
			None
			if denominator is None or denominator == 0
			else amount_number / denominator
		)
		for name, denominator in denominators.items()
	}


def _automation_preview_text(preview: dict[str, Any] | None) -> str | None:
	"""Unambiguous shadow-mode wording; never a bare boolean."""
	if not preview:
		return None
	if preview.get("decision") == "auto_approve":
		return "would auto-approve under provisional policy"
	return "would require human review"


def build_normalization_summary(
	records: list[dict[str, Any]],
	*,
	pnl: pd.DataFrame | None = None,
) -> list[dict[str, Any]]:
	"""Build a display-only summary without changing candidate mechanics."""
	groups: dict[tuple[str, str], dict[str, Any]] = {}
	list_fields = (
		"financial_assessments",
		"uncertainties",
		"reviewer_concerns",
		"reviewer_notes",
		"unresolved_issues",
		"why_not_automatic",
		"automation_previews",
		"reviewer_verdicts",
		"gate_decisions",
		"final_statuses",
		"application_statuses",
	)
	nullable_fields = set(list_fields[-5:])

	def add(
		group: dict[str, Any], field: str, value: Any, *, allow_none: bool = False
	) -> None:
		if (allow_none or value is not None) and value not in group[field]:
			group[field].append(value)

	for record in records:
		candidate = record.get("candidate") or {}
		topic = record.get("topic")
		if isinstance(topic, dict):
			topic = topic.get("name") or topic.get("topic")
		group_id = record.get("group_id") or candidate.get("group_id")
		key = (
			("group_id", str(group_id))
			if group_id is not None and str(group_id).strip()
			else (
				"exact",
				"|".join(
					"" if value is None else str(value).strip().casefold()
					for value in (topic, candidate.get("target_line"), candidate.get("sub_item"))
				),
			)
		)
		group = groups.setdefault(
			key,
			{
				"group_key": f"{key[0]}:{key[1]}",
				"item": (
					candidate.get("sub_item")
					or candidate.get("target_line")
					or topic
				),
				"target_line": candidate.get("target_line"),
				"sub_item": candidate.get("sub_item"),
				"periods": [],
				**{field: [] for field in list_fields},
			},
		)
		item_amount = candidate.get("item_amount")
		line_delta = derive_line_delta(item_amount, candidate.get("item_effect_on_line"))
		period_row = {
			"period": candidate.get("period"),
			"item_amount": item_amount,
			"item_effect_on_line": candidate.get("item_effect_on_line"),
			"line_delta": line_delta,
			"amount_basis": candidate.get("amount_basis"),
			"candidate_ids": [record["adjustment_id"]] if record.get("adjustment_id") else [],
		}
		review = record.get("review") or {}
		gate = record.get("gate") or {}
		period_row.update(
			{
				"reviewer_verdict": review.get("verdict"),
				"gate_decision": gate.get("decision"),
				"final_status": record.get("final_status"),
				"application_status": record.get("application_status"),
			}
		)
		if pnl is not None:
			reported_value = _reported_source_value(
				pnl, candidate.get("target_line"), candidate.get("period")
			)
			period_row["reported_value"] = reported_value
			if reported_value is not None and line_delta is not None:
				period_row["adjusted_value"] = reported_value + line_delta
		group["periods"].append(period_row)
		values = {
			"financial_assessments": (candidate.get("reason"),),
			"uncertainties": (candidate.get("uncertainty"),),
			"reviewer_concerns": review.get("concerns") or (),
			"reviewer_notes": (review.get("note"),),
			"unresolved_issues": (record.get("error"),),
			"why_not_automatic": gate.get("reasons") or (),
			"automation_previews": (
				_automation_preview_text(record.get("automation_preview")),
			),
			"reviewer_verdicts": (review.get("verdict"),),
			"gate_decisions": (gate.get("decision"),),
			"final_statuses": (record.get("final_status"),),
			"application_statuses": (record.get("application_status"),),
		}
		for field, entries in values.items():
			for value in entries or ():
				add(group, field, value, allow_none=field in nullable_fields)
	return list(groups.values())


# Human-readable gate-reason labels shared by the run summary and review cards.
_GATE_REASON_LABELS = {
	"reviewer_verdict_revise": "Reviewer requested revision",
	"reviewer_verdict_reject": "Reviewer rejected the candidate",
	"evidence_strength_not_strong": "Reviewer evidence strength is not strong",
	"item_amount_missing": "Candidate magnitude is not disclosed",
	"item_amount_not_positive": "Candidate magnitude is not a positive number",
	"line_delta_underived": (
		"Line direction is unsupported, so no signed delta can be derived"
	),
	"item_effect_disagreement": (
		"Analyst and Reviewer disagree on the item's effect on the line"
	),
	"analyst_amount_basis_not_auto_approvable": (
		"Analyst amount basis is not disclosed or calculated"
	),
	"reviewer_amount_basis_not_auto_approvable": (
		"Reviewer amount basis is not disclosed or calculated"
	),
	"amount_basis_disagreement": "Analyst and Reviewer amount bases differ",
	"judgment_level_not_low": "Reviewer judgment level is not low",
	"target_invalid_or_unknown": "Reviewer target line is invalid or unknown",
	"period_invalid_or_unknown": "Reviewer period is invalid or unknown",
	"calculation_invalid_or_unknown": "Reviewer calculation is invalid or unknown",
	"materiality_failed_or_unknown": "Materiality is failed or unknown",
	"normalization_eligibility_failed_or_unknown": (
		"Not eligible for automatic normalization: Reviewer judgment or "
		"recurrence evidence does not support removing this item"
	),
	"reconciliation_unresolved_or_unknown": (
		"Source reconciliation is unresolved or unknown"
	),
	"possible_duplicate_or_unknown": "Possible duplicate is present or unknown",
	"group_reconciliation_failed_or_unknown": (
		"Group reconciliation failed or is unknown"
	),
	"aggregate_over_adjustment_or_unknown": (
		"Aggregate delta would push the line through zero or is unknown"
	),
	"source_target_missing_or_unknown": (
		"Reported target value is missing or unknown"
	),
	"individual_over_adjustment_or_unknown": (
		"Individual delta removes more than the reported line holds or is unknown"
	),
	"zero_target_with_line_delta_or_unknown": (
		"Reported target is zero with a nonzero signed delta or unknown"
	),
	"deterministic_checks_failed_or_unknown": (
		"Deterministic checks failed or are unknown"
	),
	"candidate_state_conflict": (
		"A different proposal state already exists for this adjustment"
	),
}


def _gate_reason_label(reason: Any) -> str:
	return _GATE_REASON_LABELS.get(str(reason), "Gate condition is not satisfied")


def _render_normalization_summary(summary: list[dict[str, Any]]) -> None:
	def type_label(value: Any) -> str:
		return "null" if value is None else str(value)

	def amount_label(value: Any, *, signed: bool = False) -> str:
		if value is None:
			return "not disclosed"
		if isinstance(value, int | float) and not isinstance(value, bool):
			sign = ""
			magnitude = float(value)
			if signed:
				sign = "+" if magnitude >= 0 else "-"
				magnitude = abs(magnitude)
			for divisor, suffix in ((1_000_000_000, "bn"), (1_000_000, "mn"), (1_000, "k")):
				if magnitude >= divisor:
					return f"{sign}${magnitude / divisor:.1f}{suffix}"
			return f"{sign}${magnitude:g}"
		return str(value)

	def first(values: list[Any]) -> str | None:
		if not values:
			return None
		more = f" (+{len(values) - 1} more in manifest)" if len(values) > 1 else ""
		return f"{type_label(values[0])}{more}"

	def period_status(row: dict[str, Any]) -> str:
		return (
			f"Reviewer verdict={type_label(row.get('reviewer_verdict'))}; "
			f"gate decision={type_label(row.get('gate_decision'))}; "
			f"final={type_label(row.get('final_status'))}; "
			f"application={type_label(row.get('application_status'))}"
		)

	typer.echo("Normalization summary (display groups; candidate mechanics unchanged):")
	for group in summary:
		typer.echo(
			f"Item: {type_label(group.get('item'))} | "
			f"Target line: {type_label(group.get('target_line'))}"
		)
		if group.get("sub_item"):
			typer.echo(f"  Sub-item: {group['sub_item']}")

		def period_text(row: dict[str, Any]) -> str:
			effect = row.get("item_effect_on_line")
			magnitude_text = (
				f"{amount_label(row.get('item_amount'))} ({type_label(row.get('amount_basis'))}"
				+ (f", {effect}" if effect is not None else "")
				+ ")"
			)
			if "adjusted_value" in row and row.get("line_delta") is not None:
				direction = "increases" if float(row["line_delta"]) > 0 else "decreases"
				text = (
					f"{type_label(row['period'])}: "
					f"{amount_label(row.get('reported_value'), signed=True)} -> "
					f"{amount_label(row['adjusted_value'], signed=True)} "
					f"(normalized line {direction} by {amount_label(abs(float(row['line_delta'])))});"
					f" magnitude {magnitude_text}"
				)
			else:
				text = (
					f"{type_label(row['period'])}="
					f"reported {amount_label(row.get('reported_value'), signed=True)}, "
					f"candidate magnitude {magnitude_text}"
				)
			return text

		periods = "; ".join(
			(
				period_text(row)
				+ (
					f" [{', '.join(row['candidate_ids'])}]"
					if row.get("candidate_ids")
					else ""
				)
				+ f"; {period_status(row)}"
			)
			for row in group["periods"]
		)
		typer.echo(f"  Periods / reported vs candidate magnitudes: {periods}")
		if assessment := first(group["financial_assessments"]):
			typer.echo(f"  Financial assessment: {assessment}")
		issues = (
			group["reviewer_concerns"]
			+ group["uncertainties"]
			+ group["reviewer_notes"]
			+ group["unresolved_issues"]
		)
		if issue := first(issues):
			typer.echo(f"  Unresolved issue / Reviewer concern: {issue}")
		if group["why_not_automatic"]:
			reasons = group["why_not_automatic"]
			shown_reasons = []
			for reason in reasons:
				label = _gate_reason_label(reason)
				if label not in shown_reasons:
					shown_reasons.append(label)
			shown_reasons = shown_reasons[:3]
			shown = "; ".join(shown_reasons)
			if len(reasons) > 3:
				shown += f"; (+{len(reasons) - 3} more in manifest)"
			typer.echo("  Why not automatic: " + shown)
		if preview := first(group["automation_previews"]):
			typer.echo(f"  Automation preview: {preview}")


def _run_identity_families(
	work_items: list[dict[str, Any]],
	ticker: str,
	pnl: pd.DataFrame,
) -> dict[tuple[str, str, str], set[str]]:
	"""Batch-collect economic families for one full run before any review.

	Recurrence must not depend on candidate processing order, so every valid
	candidate identity in the run is collected up front. Identity building is
	deterministic and cheap; this pre-pass duplicates the per-candidate
	evidence validation on purpose so the signal sees the whole run.
	"""
	families: dict[tuple[str, str, str], set[str]] = {}
	for item in work_items:
		packet = item.get("packet")
		result = item.get("result")
		if not isinstance(packet, str) or result is None:
			continue
		for candidate in result.candidates:
			try:
				packet_identity = validate_evidence_refs(
					packet,
					candidate.evidence_refs,
					require_identity=True,
				)
				identity = _candidate_identity(
					ticker, pnl, candidate, packet_identity
				)
			except FilingEvidenceError:
				continue
			parts = _identity_components(identity)
			if parts is None:
				continue
			family = (
				parts["company"],
				parts["target_row_key"],
				parts["item_key"],
			)
			families.setdefault(family, set()).add(parts["fiscal_period"])
	return families


def _multi_period_evidence(
	history: pd.DataFrame,
	run_families: dict[tuple[str, str, str], set[str]],
	identity: str | None,
) -> bool | None:
	"""One-way deterministic recurrence signal, order-independent.

	Same company + target_row_key + item_key observed in more than one distinct
	fiscal period proves multi-period recurrence. The run is scanned as a
	batch, so candidate ordering cannot change the result. ``False`` means
	only "not mechanically proven recurring"; it never establishes
	single-period status. The Reviewer's normalization judgment answers that
	independently.

	History evidence counts only rows with status ``approved``: recurrence is
	judged against effective economic state. Rejected or proposed rows must
	not become recurrence evidence merely by existing (policy re-checked when
	human decisions start being persisted in M2).
	"""
	if not identity:
		return None
	parts = _identity_components(identity)
	if parts is None:
		return None
	family = (parts["company"], parts["target_row_key"], parts["item_key"])

	run_periods = set(run_families.get(family, ()))
	run_periods.add(parts["fiscal_period"])
	if len(run_periods) > 1:
		return True

	def row_family(row: dict[str, Any]) -> tuple[str, str, str]:
		return (
			str(row.get("company") or "").strip().upper(),
			str(row.get("target_row_key") or ""),
			str(row.get("item_key") or ""),
		)

	for row in history.to_dict(orient="records"):
		if "status" in row and str(row.get("status")) != "approved":
			continue
		if row_family(row) != family:
			continue
		period = str(row.get("fiscal_period") or "")
		if period and period != parts["fiscal_period"]:
			return True
	return False


def _normalization_eligible(
	review: Any,
	multi_period_evidence: bool | None,
) -> bool:
	"""Auto-path eligibility combines Reviewer judgment with hard signal.

	Recurrence alone does not decide eligibility: the Reviewer must affirm the
	item belongs outside normalized earnings AND that it is single-period.
	The deterministic signal can only veto (proven recurring), never approve.
	"""
	return bool(
		multi_period_evidence is False
		and getattr(review, "normalization_assessment", "uncertain") == "eligible"
		and getattr(review, "recurrence_class", "uncertain") == "single_period"
	)


def _crosses_zero(value: float, delta: float) -> bool:
	# Removing more than the reported line holds pushes the adjusted value
	# through zero into the opposite sign.
	adjusted = value + delta
	if value > 0:
		return adjusted <= 0
	if value < 0:
		return adjusted >= 0
	return True


def _gate_conditions(
	pnl: pd.DataFrame,
	candidate: Any,
	reconciliation_checks: pd.DataFrame,
	*,
	history: pd.DataFrame | None = None,
	candidate_identity: str | None = None,
	identity_status: str = "new",
	materiality_passed: bool | None = None,
	normalization_eligible: bool | None = None,
	same_run_candidates: list[tuple[Any, str]] | None = None,
	group_facts: dict[str, Any] | None = None,
) -> RiskGateConditions:
	"""Build conservative mechanical facts; no financial policy is inferred."""
	history = history if history is not None else pd.DataFrame()
	same_run_candidates = same_run_candidates or []
	if reconciliation_checks.empty or "status" not in reconciliation_checks:
		reconciliation_clear = None
	else:
		period_checks = reconciliation_checks
		if "period" in reconciliation_checks:
			period_checks = reconciliation_checks.loc[
				reconciliation_checks["period"].eq(candidate.period)
			]
		if period_checks.empty:
			reconciliation_clear = None
		elif "affected_lines" not in period_checks:
			reconciliation_clear = bool(period_checks["status"].eq("PASS").all())
		else:
			def affects_target(value: object) -> bool:
				if value is None or pd.isna(value):
					return False
				return candidate.target_line in {
					part.strip() for part in str(value).split(";")
				}

			relevant = period_checks.loc[
				period_checks["affected_lines"].map(affects_target)
			]
			reconciliation_clear = (
				True
				if relevant.empty
				else bool(relevant["status"].eq("PASS").all())
			)
	source_value = (
		_reported_source_value(pnl, candidate.target_line, candidate.period)
		if candidate.period in pnl.columns
		else None
	)
	source_available = source_value is not None
	line_delta = derive_line_delta(candidate.item_amount, candidate.item_effect_on_line)
	try:
		candidate_row_key = _target_row_key(pnl, candidate.target_line)
	except FilingEvidenceError:
		candidate_row_key = None

	def same_target_period(
		target_line: object,
		period: object,
		row_key: object = None,
	) -> bool:
		if candidate.period != period:
			return False
		if candidate_row_key and isinstance(row_key, str) and row_key.strip():
			return candidate_row_key == row_key
		return candidate.target_line == target_line

	possible_duplicate = (
		False
		if identity_status in {"replay", "blocked_existing", "state_conflict", "new"}
		else None
	)

	if source_value is None or line_delta is None:
		individual_over_adjustment = None
		zero_target_with_line_delta = None
	else:
		individual_over_adjustment = _crosses_zero(source_value, line_delta)
		zero_target_with_line_delta = source_value == 0 and line_delta != 0

	if source_value is None or line_delta is None:
		aggregate_over_adjustment = None
	else:
		aggregate = 0.0
		unknown_component = False
		try:
			resolution_history = _canonical_history_frame(history)
			current = (
				resolution_history
				if resolution_history is not None and resolution_history.empty
				else (
					None
					if resolution_history is None
					else resolve_current_adjustments(resolution_history)
				)
			)
		except (TypeError, ValueError, KeyError):
			current = None
		if current is None:
			unknown_component = True
		else:
			existing_identities = {
				_canonical_history_json(value)
				for value in history.get("candidate_identity", ())
				if _canonical_history_json(value) is not None
			}
			for row in current.to_dict(orient="records"):
				if not same_target_period(
					row.get("target_line"),
					row.get("period"),
					row.get("target_row_key"),
				):
					continue
				if (
					identity_status in {"replay", "blocked_existing", "state_conflict"}
					and candidate_identity
					and _canonical_history_json(row.get("candidate_identity"))
					== candidate_identity
				):
					continue
				row_delta = derive_line_delta(
					row.get("item_amount"), row.get("item_effect_on_line")
				)
				if row_delta is None:
					unknown_component = True
					break
				aggregate += row_delta
			for other, other_identity in same_run_candidates:
				other_parts = _identity_components(other_identity)
				other_row_key = (
					other_parts["target_row_key"]
					if other_parts is not None
					else None
				)
				if (
					not same_target_period(
						other.target_line, other.period, other_row_key
					)
					or other_identity == candidate_identity
					or other_identity in existing_identities
				):
					continue
				other_delta = derive_line_delta(
					other.item_amount, other.item_effect_on_line
				)
				if other_delta is None:
					unknown_component = True
					break
				aggregate += other_delta
		if unknown_component:
			aggregate_over_adjustment = None
		else:
			aggregate += line_delta
			aggregate_over_adjustment = _crosses_zero(source_value, aggregate)
	if group_facts is None:
		group_reconciles = (
			True if not getattr(candidate, "group_id", None) else None
		)
	else:
		group_reconciles = group_facts.get("reconciles")
	deterministic_checks_pass: bool | None
	if source_value is None or line_delta is None:
		deterministic_checks_pass = None
	else:
		try:
			preview = pd.DataFrame(
				[
					{
						"target_row_key": _target_row_key(
							pnl, candidate.target_line
						),
						"target_line": candidate.target_line,
						"period": candidate.period,
						"item_amount": candidate.item_amount,
						"item_effect_on_line": candidate.item_effect_on_line,
						"line_delta": line_delta,
						"status": "approved",
					}
				]
			)
			preview_pnl = apply_adjustments(pnl, preview)
			preview_checks = reconcile_pnl(preview_pnl)
			deterministic_checks_pass = not bool(
				preview_checks["status"].eq("FAIL").any()
			)
		except (FilingEvidenceError, KeyError, TypeError, ValueError):
			deterministic_checks_pass = False
	return RiskGateConditions(
		materiality_eligible=materiality_passed,
		normalization_eligible=normalization_eligible,
		reconciliation_clear=reconciliation_clear,
		possible_duplicate=possible_duplicate,
		group_reconciles=group_reconciles,
		aggregate_over_adjustment=aggregate_over_adjustment,
		source_target_available=source_available,
		individual_over_adjustment=individual_over_adjustment,
		zero_target_with_line_delta=zero_target_with_line_delta,
		deterministic_checks_pass=deterministic_checks_pass,
	)


def _run_adjustment_analysis(
	ticker: str,
	pnl: pd.DataFrame,
	model: str,
	reasoning_effort: str,
	*,
	output_root: str | Path = "data",
	filing: Any | None = None,
	materiality_passed: bool | None = None,
) -> Path:
	"""Run discovery/review and persist only deterministic safe approvals.

	``materiality_passed`` is an explicit frozen integration-test fact. Live
	callers leave it unset until an approved materiality policy exists.
	"""
	ticker = ticker.strip().upper()
	output_directory = Path(output_root) / ticker / "03_output"
	attached_filing = pnl.attrs.get("edgar_filing")
	if filing is None:
		filing = attached_filing
	if filing is None:
		raise AdjustmentAnalysisError(
			"an EdgarTools filing is required for adjustment analysis"
		)

	run_id = _new_run_id()
	discovery_result: DiscoveryResult | None = None
	discovery_metadata: dict[str, Any] = {}
	discovery_context: dict[str, Any] | None = None
	discovery_path: Path | None = None
	discovery_decisions: list[dict[str, Any]] = []
	topic_records: list[dict[str, Any]] = []
	work_items: list[dict[str, Any]] = []
	try:
		discovery_context = build_discovery_context(pnl, filing)
		discovery_result, discovery_metadata = run_discovery(
			ticker,
			pnl,
			discovery_context,
			model=model,
			reasoning_effort=reasoning_effort,
			run_id=run_id,
		)
		retained_topics, discovery_decisions = deduplicate_topics(
			discovery_result.topics
		)
	except DiscoveryError as exc:
		raise AdjustmentAnalysisError(f"discovery failed: {exc}") from exc

	for ordinal, topic in enumerate(retained_topics, start=1):
		topic_data = topic.model_dump(mode="json")
		slug = re.sub(r"[^a-z0-9]+", "_", topic.name.casefold()).strip("_") or "topic"
		evidence_path = (
			output_directory / "evidence" / f"{ordinal:02d}_{slug}_{run_id}.md"
		)
		input_index = next(
			(
				decision["input_index"]
				for decision in discovery_decisions
				if decision.get("status") == "retained"
				and decision.get("topic") == topic_data
			),
			None,
		)
		topic_record: dict[str, Any] = {
			"input_index": input_index,
			"topic": topic_data,
			"status": "discovered",
			"evidence_path": str(evidence_path),
		}
		try:
			evidence_packet, retrieval_metadata = retrieve_filing_evidence(
				filing,
				ticker,
				topic.name,
				topic.queries,
				output_path=evidence_path,
			)
			topic_record["retrieval"] = retrieval_metadata
			topic_record["status"] = "retrieved"
		except FilingEvidenceError as exc:
			topic_record.update({"status": "retrieval_failed", "error": str(exc)})
			topic_records.append(topic_record)
			continue

		try:
			result, analyst_metadata = run_analyst(
				ticker,
				pnl,
				evidence_packet,
				model=model,
				reasoning_effort=reasoning_effort,
				evidence_ref=str(evidence_path),
				run_id=run_id,
			)
		except AdjustmentAnalysisError as exc:
			topic_record.update({"status": "analyst_failed", "error": str(exc)})
			topic_records.append(topic_record)
			continue

		analyst_metadata = dict(analyst_metadata)
		analyst_metadata.update(retrieval_metadata)
		analyst_metadata.update(
			{"topic": topic.name, "evidence_file": str(evidence_path)}
		)
		analysis_path = (
			output_directory / "analysis" / (f"{ordinal:02d}_{slug}_{run_id}.json")
		)
		analysis_path.parent.mkdir(parents=True, exist_ok=True)
		analysis_path.write_text(
			json.dumps(
				{
					"metadata": analyst_metadata,
					"result": result.model_dump(mode="json"),
				},
				indent=2,
				ensure_ascii=False,
			)
			+ "\n",
			encoding="utf-8",
		)
		topic_record["analysis_path"] = str(analysis_path)
		topic_record["analyst"] = analyst_metadata
		topic_record["candidate_count"] = len(result.candidates)
		if len(result.candidates) > MAX_CANDIDATES_PER_TOPIC:
			topic_record.update(
				{
					"status": "candidate_limit_exceeded",
					"candidate_limit": MAX_CANDIDATES_PER_TOPIC,
					"error": (
						f"Analyst returned {len(result.candidates)} candidates; "
						f"per-topic limit is {MAX_CANDIDATES_PER_TOPIC}"
					),
				}
			)
			topic_records.append(topic_record)
			continue
		topic_record["status"] = (
			"analyst_empty" if not result.candidates else "analyst_resolved"
		)
		topic_records.append(topic_record)
		work_items.append(
			{
				"topic": topic.name,
				"queries": list(topic.queries),
				"packet": evidence_packet,
				"metadata": analyst_metadata,
				"result": result,
				"analysis_path": analysis_path,
				"topic_record": topic_record,
			}
		)

	if work_items:
		typer.echo(f"Saved Analyst JSON files: {len(work_items)} (see integrated manifest)")

	# Batch recurrence signal: collected before any review so candidate
	# ordering can never change multi-period evidence.
	run_families = _run_identity_families(work_items, ticker, pnl)

	reconciliation_checks = reconcile_pnl(pnl)
	history_path = output_directory / "adjustment_history.csv"
	history_path.parent.mkdir(parents=True, exist_ok=True)
	history = _load_adjustment_history(history_path)
	records: list[dict[str, Any]] = []
	history_rows: list[dict[str, Any]] = []
	next_display_offset = 0
	same_run_approved: list[tuple[Any, str]] = []

	for item in work_items:
		record_start = len(records)
		result = item["result"]
		packet = item["packet"]
		metadata = dict(item["metadata"])
		evidence_path = Path(metadata["evidence_file"])
		try:
			validate_evidence_refs(packet, [], require_identity=True)
		except FilingEvidenceError as exc:
			raise AdjustmentAnalysisError(f"invalid evidence packet: {exc}") from exc

		for candidate_number, candidate in enumerate(result.candidates):
			candidate_data = candidate.model_dump(mode="json")
			base_record = {
				"adjustment_id": None,
				"topic": item["topic"],
				"candidate_number": candidate_number + 1,
				"candidate": candidate_data,
				"final_status": "unresolved",
				"application_status": "not_applied",
			}
			if not candidate.evidence_refs:
				base_record["error"] = "candidate returned no evidence references"
				records.append(base_record)
				continue
			try:
				candidate_packet_identity = validate_evidence_refs(
					packet,
					candidate.evidence_refs,
					require_identity=filing is not None,
				)
			except FilingEvidenceError as exc:
				records.append(
					{
						**base_record,
						"final_status": "unresolved",
						"application_status": "not_applied",
						"error": str(exc),
					}
				)
				continue

			identity_error: str | None = None
			try:
				identity = _candidate_identity(
					ticker, pnl, candidate, candidate_packet_identity
				)
			except FilingEvidenceError as exc:
				identity = None
				identity_error = str(exc)
			state = _canonical_json(_candidate_state(candidate))
			working_history = history
			if history_rows:
				working_history = pd.concat(
					[history, pd.DataFrame(history_rows)], ignore_index=True
				)
			lookup = (
				_history_identity_lookup(working_history, identity, state)
				if identity is not None
				else {
					"status": "identity_unresolved",
					"adjustment_id": None,
					"version": 0,
					"reason": identity_error or "candidate identity is unresolved",
				}
			)
			if lookup["status"] == "new":
				provisional_id = _next_adjustment_id(history, next_display_offset)
				next_display_offset += 1
				base_record["adjustment_id"] = provisional_id
			base_record.update(
				{
					"candidate_identity": identity,
					"candidate_state": state,
					"identity_status": lookup["status"],
				}
			)
			if lookup["status"] in {"unknown", "identity_unresolved"}:
				base_record["error"] = lookup.get("reason") or identity_error or (
					"candidate identity is missing or ambiguous"
				)
			if lookup["status"] in {"replay", "blocked_existing"}:
				latest = lookup.get("latest", {})
				persisted_status = str(latest.get("status", ""))
				is_replay = lookup["status"] == "replay"
				base_record.update(
					{
						"adjustment_id": lookup["adjustment_id"],
						"final_status": (
							"approved"
							if is_replay
							else (
								"rejected"
								if persisted_status == "rejected"
								else "human_review"
							)
						),
						"application_status": "applied" if is_replay else "not_applied",
						"replayed": is_replay,
						"gate": {
							"decision": latest.get("gate_decision") or "persisted",
							"reasons": json.loads(latest.get("gate_reasons", "[]"))
							if isinstance(latest.get("gate_reasons"), str)
							and latest.get("gate_reasons", "").startswith("[")
							else [],
						},
					}
				)
				records.append(base_record)
				continue

			try:
				review, review_metadata = run_reviewer(
					ticker,
					pnl,
					candidate,
					packet,
					model=model,
					reasoning_effort=reasoning_effort,
					evidence_ref=str(evidence_path),
					run_id=str(metadata.get("run_id", run_id)),
				)
				review_metadata = dict(review_metadata)
				review_metadata.setdefault("run_id", run_id)
				for key in (
					"filing_accession",
					"evidence_file",
					"topic",
					"filing_url",
					"text_url",
				):
					if key in metadata:
						review_metadata.setdefault(key, metadata[key])
				review_file_id = (
					lookup["adjustment_id"]
					or base_record.get("adjustment_id")
					or f"unresolved_{candidate_number + 1}"
				)
				review_path = save_reviewer_result(
					ticker,
					review_file_id,
					candidate,
					review,
					review_metadata,
					output_root=output_root,
				)
			except ReviewerError as exc:
				records.append(
					{
						**base_record,
						"final_status": "unresolved",
						"application_status": "not_applied",
						"error": str(exc),
					}
				)
				continue

			multi_period_evidence = _multi_period_evidence(
				working_history, run_families, identity
			)
			candidate_metrics = _materiality_metrics(pnl, candidate)
			if isinstance(materiality_passed, bool):
				# Explicit frozen test override; live callers never set this.
				materiality_value: bool | None = materiality_passed
			else:
				materiality_value = _materiality_eligible(candidate_metrics)
			conditions = _gate_conditions(
				pnl,
				candidate,
				reconciliation_checks,
				history=working_history,
				candidate_identity=identity,
				identity_status=lookup["status"],
				materiality_passed=materiality_value,
				normalization_eligible=_normalization_eligible(
					review, multi_period_evidence
				),
				same_run_candidates=same_run_approved,
			)
			gate = evaluate_risk_gate(
				candidate,
				review,
				conditions,
			)
			# Shadow mode: the gate decision is an automation preview only.
			# Canonical approval additionally requires the feature switch, so
			# a passing shadow result can never append history by itself.
			shadow_auto_approve = gate.eligible_for_auto_approval
			is_approved = (
				shadow_auto_approve
				and ENABLE_CANONICAL_AUTO_APPROVAL
				and lookup["status"] == "new"
			)
			gate_record = {
				"decision": gate.decision,
				"reasons": list(gate.reasons),
			}
			if lookup["status"] == "state_conflict":
				gate_record = {
					"decision": "human_review",
					"reasons": ["candidate_state_conflict", *gate.reasons],
				}
			final_status = "approved" if is_approved else "human_review"
			review_data = review.model_dump(mode="json")
			conditions_data = dict(conditions.__dict__)
			records.append(
				{
					**base_record,
					"adjustment_id": lookup["adjustment_id"] or base_record.get("adjustment_id"),
					"candidate": candidate_data,
					"review": review_data,
					"review_metadata": review_metadata,
					"review_path": str(review_path),
					"normalization": {
						"assessment": review_data["normalization_assessment"],
						"recurrence_class": review_data["recurrence_class"],
						"multi_period_evidence": multi_period_evidence,
					},
					"gate": {**gate_record, "conditions": conditions_data},
					"automation_preview": {
						# What the gate WOULD do under the provisional policy.
						"decision": (
							"auto_approve"
							if shadow_auto_approve
							else "human_review"
						),
						"canonical_writes_enabled": ENABLE_CANONICAL_AUTO_APPROVAL,
						"materiality_eligible": materiality_value,
						"thresholds": dict(_AUTO_MATERIALITY_LIMITS),
					},
					"materiality": {
						"passed": materiality_value,
						"metrics": candidate_metrics,
					},
					"final_status": final_status,
					"application_status": ("applied" if is_approved else "not_applied"),
				}
			)
			if is_approved:
				adjustment_id = lookup["adjustment_id"] or provisional_id
				version = (
					1
					if lookup["status"] == "new"
					else int(lookup["version"]) + 1
				)
				metrics = candidate_metrics
				# The gate blocks auto-approval without a derivable delta, so
				# every approved row records a provable direction.
				line_delta = derive_line_delta(
					candidate.item_amount, candidate.item_effect_on_line
				)
				history_rows.append(
					{
						"adjustment_id": adjustment_id,
						"version": version,
						"schema_version": ADJUSTMENT_SCHEMA_VERSION,
						"identity_version": IDENTITY_VERSION,
						"candidate_identity": identity,
						"candidate_state": state,
						"run_id": run_id,
						"origin": "llm",
						"company": ticker,
						"fiscal_period": candidate_data["period"],
						"target_row_key": (
							_identity_components(identity)["target_row_key"]
							if _identity_components(identity) is not None
							else None
						),
						"target_line": candidate_data["target_line"],
						"sub_item": candidate_data.get("sub_item"),
						"period": candidate_data["period"],
						"item_key": candidate_data.get("item_key"),
						"item_amount": candidate_data["item_amount"],
						"item_effect_on_line": candidate_data["item_effect_on_line"],
						"line_delta": line_delta,
						"status": "approved",
						"amount_basis": candidate_data["amount_basis"],
						"evidence_strength": review_data["evidence_strength"],
						"judgment_level": review_data["judgment_level"],
						"reviewer_verdict": review_data["verdict"],
						"target_valid": review_data["target_valid"],
						"period_valid": review_data["period_valid"],
						"calculation_valid": review_data["calculation_valid"],
						"reviewer_amount_basis": review_data["amount_basis"],
						"reviewer_normalization_assessment": review_data[
							"normalization_assessment"
						],
						"reviewer_recurrence_class": review_data[
							"recurrence_class"
						],
						"multi_period_evidence": multi_period_evidence,
						# Auto-approval requires eligibility, so an override
						# reason can only ever come from a human decision.
						"human_override_reason": None,
						"gate_decision": gate_record["decision"],
						"gate_reasons": json.dumps(gate_record["reasons"]),
						"materiality_eligible": conditions_data["materiality_eligible"],
						"pct_revenue": metrics["pct_revenue"],
						"pct_target_line": metrics["pct_target_line"],
						"pct_operating_income": metrics["pct_operating_income"],
						"possible_duplicate": conditions_data["possible_duplicate"],
						"group_reconciles": conditions_data["group_reconciles"],
						"aggregate_over_adjustment": conditions_data[
							"aggregate_over_adjustment"
						],
						"source_target_available": conditions_data[
							"source_target_available"
						],
						"individual_over_adjustment": conditions_data[
							"individual_over_adjustment"
						],
						"zero_target_with_line_delta": conditions_data[
							"zero_target_with_line_delta"
						],
						"deterministic_checks_pass": conditions_data[
							"deterministic_checks_pass"
						],
						"reconciliation_clear": conditions_data["reconciliation_clear"],
						"candidate_evidence_refs": _canonical_json(
							candidate.evidence_refs
						),
						"analyst_model": metadata.get("model"),
						"reviewer_model": review_metadata.get("model"),
						"analyst_prompt_version": metadata.get("prompt_version"),
						"reviewer_prompt_version": review_metadata.get(
							"prompt_version"
						),
						"evidence_file": metadata.get("evidence_file"),
						"analysis_file": str(item["analysis_path"]),
						"review_file": str(review_path),
						"filing_accession": metadata.get("filing_accession"),
						"topic": metadata.get("topic", item["topic"]),
						"reason": candidate_data["reason"],
					}
				)
				if is_approved:
					same_run_approved.append((candidate, identity))
		if item.get("topic_record") is not None:
			candidate_records = records[record_start:]
			item["topic_record"]["candidates"] = candidate_records
			statuses = {record.get("final_status") for record in candidate_records}
			if "approved" in statuses:
				item["topic_record"]["status"] = "approved"
			elif "human_review" in statuses:
				item["topic_record"]["status"] = "human_review"
			elif statuses:
				item["topic_record"]["status"] = "unresolved"

	# Merge runtime status into one record per discovered topic. Duplicates remain
	# visible, while retained topics carry retrieval and resolution outcomes.
	if discovery_result is not None:
		if discovery_decisions:
			runtime_by_index = {
				record.get("input_index"): record for record in topic_records
			}
			merged_records: list[dict[str, Any]] = []
			for decision in discovery_decisions:
				runtime = runtime_by_index.get(decision.get("input_index"))
				if runtime is None:
					merged_records.append(decision)
					continue
				merged_records.append(
					{
						**decision,
						**runtime,
						"discovery_status": decision.get("status"),
					}
				)
			topic_records = merged_records
			discovery_decisions = merged_records
		discovery_path = save_discovery_result(
			ticker,
			discovery_result,
			discovery_metadata,
			context=discovery_context or {},
			topics=discovery_decisions,
			output_root=output_root,
		)

	# Persist no canonical row for unresolved or human-review outcomes.
	if history_rows:
		new_history = pd.DataFrame(history_rows)
		history = (
			new_history
			if history.empty
			else pd.concat([history, new_history], ignore_index=True)
		)
		history.to_csv(history_path, index=False)

	try:
		resolution_history = _canonical_history_frame(history)
		if resolution_history is None:
			# Unknown effective authority must stop application; only inert legacy
			# proposed/rejected rows resolve to an empty canonical frame.
			raise ValueError("adjustment history identity is unresolved")
		current_adjustments = (
			history.iloc[0:0].copy()
			if resolution_history.empty
			else resolve_current_adjustments(resolution_history)
		)
		adjusted_pnl = apply_adjustments(pnl, current_adjustments)
	except (KeyError, TypeError, ValueError) as exc:
		raise AdjustmentAnalysisError(f"adjustment application failed: {exc}") from exc

	adjusted_pnl_path = output_directory / "adjusted_pnl.csv"
	adjusted_pnl.to_csv(adjusted_pnl_path, index=False)
	adjusted_checks = reconcile_pnl(adjusted_pnl)
	adjusted_reconciliation_path = (
		output_directory / "adjusted_reconciliation_checks.csv"
	)
	adjusted_checks.to_csv(adjusted_reconciliation_path, index=False)
	if (adjusted_checks["status"] == "FAIL").any():
		raise AdjustmentAnalysisError(
			f"adjusted P&L reconciliation failed; see {adjusted_reconciliation_path}"
		)

	normalization_groups = build_normalization_summary(records, pnl=pnl)
	reviewer_file_count = sum(bool(record.get("review_path")) for record in records)
	if reviewer_file_count:
		typer.echo(
			f"Saved Reviewer JSON files: {reviewer_file_count} "
			"(see integrated manifest)"
		)
	_render_normalization_summary(normalization_groups)

	manifest = {
		"metadata": {
			"ticker": ticker,
			"run_id": run_id,
			"analyst": discovery_metadata,
		},
		"discovery_path": (None if discovery_path is None else str(discovery_path)),
		"discovery": (
			None
			if discovery_result is None
			else {
				"metadata": discovery_metadata,
				"result": discovery_result.model_dump(mode="json"),
			}
		),
		"history_path": str(history_path),
		"adjusted_pnl_path": str(adjusted_pnl_path),
		"adjusted_reconciliation_path": str(adjusted_reconciliation_path),
		"reported_reconciliation": _reconciliation_summary(reconciliation_checks),
		"adjusted_reconciliation": _reconciliation_summary(adjusted_checks),
		"reported_equals_adjusted": pnl.round(10).equals(adjusted_pnl.round(10)),
		"normalization_summary": {
			"schema_version": "normalization-summary-v1",
			"groups": normalization_groups,
		},
		"topics": topic_records,
		"candidates": records,
	}
	manifest_path = output_directory / "analysis" / f"adjustment_run_{run_id}.json"
	manifest_path.parent.mkdir(parents=True, exist_ok=True)
	manifest_path.write_text(
		json.dumps(manifest, indent=2, ensure_ascii=False, default=str) + "\n",
		encoding="utf-8",
	)
	if history_rows:
		status_counts = {
			status: sum(row.get("status") == status for row in history_rows)
			for status in ("approved", "proposed")
		}
		status_summary = ", ".join(
			f"{count} {status}"
			for status, count in status_counts.items()
			if count
		) or "0 rows"
		typer.echo(
			f"Adjustment history updated ({status_summary} rows): "
			f"{history_path}"
		)
	else:
		typer.echo(f"Adjustment history unchanged (0 approved rows): {history_path}")
	typer.echo(f"Saved adjusted P&L: {adjusted_pnl_path}")
	typer.echo(f"Saved adjusted reconciliation: {adjusted_reconciliation_path}")
	typer.echo(f"Saved integrated adjustment run: {manifest_path}")
	return manifest_path


# region Human review (M2)
class ReviewActionError(RuntimeError):
	"""A proposed human decision fails hard deterministic mechanics."""


def _latest_manifest_path(ticker: str, output_root: Path) -> Path | None:
	analysis_dir = Path(output_root) / ticker / "03_output" / "analysis"
	candidates = list(analysis_dir.glob("adjustment_run_*.json"))
	# Newest by modification time; run ids are not lexicographically ordered.
	return max(candidates, key=lambda path: path.stat().st_mtime, default=None)


def _pending_review_entries(
	manifest: dict[str, Any],
	history: pd.DataFrame,
) -> list[dict[str, Any]]:
	"""Candidates still awaiting a human decision.

	Already-decided items are excluded by identity + proposal state: an
	approved state replays as effective, and any recorded latest decision
	(approved or rejected) suppresses re-review of the identical proposal.
	A changed proposal for the same identity stays in the queue.
	"""
	pending = []
	for record in manifest.get("candidates", []):
		if record.get("final_status") not in {
			"human_review",
			"unresolved",
			"identity_unresolved",
		}:
			continue
		identity = record.get("candidate_identity")
		state = record.get("candidate_state")
		if identity and state:
			lookup = _history_identity_lookup(history, identity, state)
			if lookup["status"] in {"replay", "blocked_existing"}:
				continue
		pending.append(record)
	return pending


def _decision_context(
	pnl: pd.DataFrame,
	record: dict[str, Any],
	history: pd.DataFrame,
) -> dict[str, Any]:
	"""Validate hard approval mechanics without applying anything.

	Human approval skips Reviewer/materiality requirements but must still
	pass target integrity, a derivable signed delta, and a clean trial
	reconciliation of the resulting effective adjustment set.
	"""
	candidate = record.get("candidate") or {}
	if not record.get("candidate_identity"):
		raise ReviewActionError(
			"candidate has no resolvable economic identity; cannot record approval"
		)
	target_line = candidate.get("target_line")
	period = candidate.get("period")
	try:
		line_index = _find_line_index(pnl, target_line)
	except (KeyError, ValueError) as exc:
		raise ReviewActionError(
			f"target line {target_line!r} is missing or ambiguous"
		) from exc
	if _is_derived_line(pnl, line_index):
		raise ReviewActionError(
			f"target line {target_line!r} is a derived subtotal"
		)
	reported = _reported_source_value(pnl, target_line, period)
	if reported is None:
		raise ReviewActionError(
			f"reported value for {target_line!r} / {period!r} is unavailable"
		)
	line_delta = derive_line_delta(
		candidate.get("item_amount"), candidate.get("item_effect_on_line")
	)
	if line_delta is None:
		raise ReviewActionError(
			"no derivable line delta (amount and direction must both be known)"
		)

	identity = record.get("candidate_identity")
	state = record.get("candidate_state")
	lookup = _history_identity_lookup(history, identity, state)
	if lookup["status"] == "replay":
		return {"already_effective": True}
	if lookup["status"] == "identity_unresolved":
		raise ReviewActionError(lookup.get("reason", "identity unresolved"))

	normalization = record.get("normalization") or {}
	override_required = (
		normalization.get("multi_period_evidence") is True
		or normalization.get("assessment") not in {None, "eligible"}
		or normalization.get("recurrence_class") not in {None, "single_period"}
	)
	return {
		"already_effective": False,
		"adjustment_id": lookup.get("adjustment_id"),
		"latest_version": lookup.get("version") or 0,
		"reported": reported,
		"line_delta": line_delta,
		"crosses_zero": _crosses_zero(reported, line_delta),
		"override_required": override_required,
	}


def _trial_reconciles(
	pnl: pd.DataFrame,
	history: pd.DataFrame,
	row: dict[str, Any],
) -> bool:
	try:
		trial = pd.concat([history, pd.DataFrame([row])], ignore_index=True)
		current = resolve_current_adjustments(trial)
		adjusted = apply_adjustments(pnl, current)
		checks = reconcile_pnl(adjusted)
	except (KeyError, TypeError, ValueError):
		return False
	return not bool(checks["status"].eq("FAIL").any())


def _decision_history_row(
	ticker: str,
	context_or_none: dict[str, Any] | None,
	record: dict[str, Any],
	*,
	status: Literal["approved", "rejected"],
	run_id: str,
	override_reason: str | None = None,
	reject_reason: str | None = None,
) -> dict[str, Any]:
	"""Build one canonical human-decision history row."""
	candidate = record.get("candidate") or {}
	identity = record.get("candidate_identity")
	state = record.get("candidate_state")
	normalization = record.get("normalization") or {}
	review = record.get("review") or {}

	if status == "rejected":
		if context_or_none is not None:
			adjustment_id = context_or_none.get("adjustment_id")
			version = int(context_or_none.get("latest_version") or 0) + 1
		else:
			# Identity-less rejects cannot tie to an existing item; they are
			# recorded for audit only and never match future candidates.
			adjustment_id = None
			version = 1
		if not reject_reason or not reject_reason.strip():
			raise ReviewActionError("a rejection requires a short reason")
	else:
		assert context_or_none is not None
		adjustment_id = context_or_none.get("adjustment_id")
		version = int(context_or_none.get("latest_version") or 0) + 1

	if not adjustment_id:
		raise ReviewActionError("no adjustment id was allocated")

	item_amount = candidate.get("item_amount")
	item_effect = candidate.get("item_effect_on_line")
	line_delta = derive_line_delta(item_amount, item_effect)
	parts = _identity_components(identity) if identity else None
	materiality = record.get("materiality") or {}
	metrics = materiality.get("metrics") or {}

	row = {
		"adjustment_id": adjustment_id,
		"version": version,
		"schema_version": ADJUSTMENT_SCHEMA_VERSION,
		"identity_version": IDENTITY_VERSION,
		"candidate_identity": identity,
		"candidate_state": state,
		"run_id": run_id,
		"origin": "human",
		"company": ticker,
		"fiscal_period": candidate.get("period"),
		"target_row_key": parts["target_row_key"] if parts else None,
		"target_line": candidate.get("target_line"),
		"sub_item": candidate.get("sub_item"),
		"period": candidate.get("period"),
		"item_key": candidate.get("item_key"),
		"item_amount": item_amount,
		"item_effect_on_line": item_effect,
		"line_delta": line_delta,
		"status": status,
		"amount_basis": candidate.get("amount_basis"),
		"reviewer_verdict": review.get("verdict"),
		"evidence_strength": review.get("evidence_strength"),
		"judgment_level": review.get("judgment_level"),
		"reviewer_normalization_assessment": normalization.get("assessment"),
		"reviewer_recurrence_class": normalization.get("recurrence_class"),
		"multi_period_evidence": normalization.get("multi_period_evidence"),
		"gate_decision": "human_decision",
		"gate_reasons": json.dumps(
			[reject_reason] if reject_reason else ["human_accepted"]
		),
		"materiality_eligible": None,
		"pct_revenue": metrics.get("pct_revenue"),
		"pct_target_line": metrics.get("pct_target_line"),
		"pct_operating_income": metrics.get("pct_operating_income"),
		"human_override_reason": override_reason,
		"reject_reason": reject_reason,
		"reason": candidate.get("reason"),
	}
	return row


def _append_history_row(history_path: Path, history: pd.DataFrame, row: dict[str, Any]) -> pd.DataFrame:
	updated = (
		pd.DataFrame([row])
		if history.empty
		else pd.concat([history, pd.DataFrame([row])], ignore_index=True)
	)
	updated.to_csv(history_path, index=False)
	return updated


def _review_card(index: int, total: int, record: dict[str, Any], pnl: pd.DataFrame) -> None:
	candidate = record.get("candidate") or {}
	review = record.get("review") or {}
	normalization = record.get("normalization") or {}
	gate = record.get("gate") or {}
	reported = _reported_source_value(
		pnl, candidate.get("target_line"), candidate.get("period")
	)
	delta = derive_line_delta(
		candidate.get("item_amount"), candidate.get("item_effect_on_line")
	)
	typer.echo("")
	typer.echo(
		f"[{index}/{total}] {record.get('adjustment_id') or '(no id)'} · "
		f"{candidate.get('sub_item') or candidate.get('item_key')}"
	)
	typer.echo(
		f"  Line: {candidate.get('target_line')} | Period: {candidate.get('period')}"
	)
	reported_text = (
		f"{reported:,.0f}" if reported is not None else "n/a"
	)
	if delta is not None and reported is not None:
		typer.echo(
			f"  Proposal: remove {candidate.get('item_amount')} "
			f"({candidate.get('item_effect_on_line')}) → delta {delta:+g} | "
			f"{reported_text} → {reported + delta:,.0f}"
		)
	elif delta is None and candidate.get("item_amount") is not None:
		typer.echo(
			f"  Proposal: amount={candidate.get('item_amount')} but direction unknown"
			" → no delta (cannot accept)"
		)
	else:
		typer.echo("  Proposal: amount not disclosed → no delta (cannot accept)")
	typer.echo(
		f"  Reviewer: {review.get('verdict')} | evidence={review.get('evidence_strength')}"
		f" | judgment={review.get('judgment_level')}"
	)
	concerns = review.get("concerns") or []
	if concerns:
		typer.echo(f"  Concerns: {concerns[0]} (+{len(concerns) - 1} more)" if len(concerns) > 1 else f"  Concerns: {concerns[0]}")
	typer.echo(
		f"  Eligibility: assessment={normalization.get('assessment')}"
		f" recurrence={normalization.get('recurrence_class')}"
		f" multi_period_signal={normalization.get('multi_period_evidence')}"
	)
	preview_text = _automation_preview_text(record.get("automation_preview"))
	if preview_text:
		typer.echo(f"  Automation preview: {preview_text}")
	reasons = [
		_gate_reason_label(reason) for reason in (gate.get("reasons") or [])
	]
	if reasons:
		shown = "; ".join(dict.fromkeys(reasons))
		typer.echo(f"  Why not automatic: {shown}")
	if record.get("final_status") == "identity_unresolved":
		typer.echo("  IDENTITY UNRESOLVED — this MVP can only skip this item.")


def _rebuild_adjusted_outputs(ticker: str, output_root: Path, pnl: pd.DataFrame) -> None:
	output_directory = output_root / ticker / "03_output"
	history = _load_adjustment_history(output_directory / "adjustment_history.csv")
	try:
		current = resolve_current_adjustments(history)
		adjusted = apply_adjustments(pnl, current)
		adjusted_checks = reconcile_pnl(adjusted)
	except (KeyError, TypeError, ValueError) as exc:
		typer.echo(f"Rebuild failed: {exc}", err=True)
		return
	adjusted_path = output_directory / "adjusted_pnl.csv"
	adjusted.to_csv(adjusted_path, index=False)
	checks_path = output_directory / "adjusted_reconciliation_checks.csv"
	adjusted_checks.to_csv(checks_path, index=False)

	summary_passed = int((adjusted_checks["status"] == "PASS").sum())
	summary_failed = int((adjusted_checks["status"] == "FAIL").sum())
	typer.echo("")
	typer.echo(
		f"Adjusted P&L rebuilt ({current.shape[0]} effective adjustments): "
		f"{adjusted_path} | reconciliation {summary_passed} pass / {summary_failed} fail"
	)
	for row in current.to_dict(orient="records"):
		adjusted_value = _reported_source_value(
			adjusted, row.get("target_line"), row.get("period")
		)
		reported_value = _reported_source_value(
			pnl, row.get("target_line"), row.get("period")
		)
		typer.echo(
			f"  {row['adjustment_id']} v{int(row['version'])} · "
			f"{row.get('target_line')} {row.get('period')} · "
			f"{reported_value:,.0f} → {adjusted_value:,.0f} "
			f"(delta {float(row['line_delta']):+g})"
		)


def _run_review_session(ticker: str, output_root: Path) -> None:
	manifest_path = _latest_manifest_path(ticker, output_root)
	if manifest_path is None:
		typer.echo(f"No analysis runs found for {ticker}. Run analyze first.")
		raise typer.Exit(1)
	manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
	pnl = load_analytical_pnl(ticker, str(output_root))
	history_path = output_root / ticker / "03_output" / "adjustment_history.csv"
	history = _load_adjustment_history(history_path)


	queue = _pending_review_entries(manifest, history)
	if not queue:
		typer.echo("Nothing pending human review.")
		_rebuild_adjusted_outputs(ticker, output_root, pnl)
		return

	typer.echo(
		f"{len(queue)} candidate(s) pending review from run "
		f"{manifest.get('metadata', {}).get('run_id', '?')}"
	)
	decisions = 0
	for index, record in enumerate(queue, start=1):
		_review_card(index, len(queue), record, pnl)
		action = typer.prompt(
			"[a]ccept / [r]eject / [e]dit amount / [s]kip / [q]uit",
			type=str,
			default="s",
		).strip().lower()

		if action == "q":
			break
		if action == "s":
			typer.echo("Skipped.")
			continue
		if action not in {"a", "r", "e"}:
			typer.echo("Unknown action; skipped.")
			continue

		run_id = f"human-{_new_run_id()}"
		try:
			if action == "r":
				reason = typer.prompt("Short rejection reason")
				context = None
				identity = record.get("candidate_identity")
				if identity:
					state = record.get("candidate_state")
					lookup = _history_identity_lookup(history, identity, state or "")
					if lookup["status"] != "new":
						context = {
							"adjustment_id": lookup.get("adjustment_id"),
							"latest_version": lookup.get("version") or 0,
						}
				if context is None:
					context = {
						"adjustment_id": _next_adjustment_id(history),
						"latest_version": 0,
					}
				elif not context.get("adjustment_id"):
					context["adjustment_id"] = _next_adjustment_id(history)
				row = _decision_history_row(
					ticker,
					context,
					record,
					status="rejected",
					run_id=run_id,
					reject_reason=reason.strip(),
				)
				typer.echo(f"Rejected as {row['adjustment_id']} v{row['version']}.")
			else:
				context = _decision_context(pnl, record, history)
				if context.get("already_effective"):
					typer.echo("Already approved and effective. Nothing to do.")
					continue
				if not context.get("adjustment_id"):
					context["adjustment_id"] = _next_adjustment_id(history)
				note: str | None = None
				if context["override_required"]:
					note = typer.prompt(
						"Not auto-eligible. Short override reason (required)"
					).strip()
					if not note:
						typer.echo("No override reason given; skipped.")
						continue
				if action == "e":
					new_amount_text = typer.prompt("New positive amount").strip()
					try:
						new_amount = float(new_amount_text)
					except ValueError:
						typer.echo("Not a number; skipped.")
						continue
					record = {
						**record,
						"candidate": {
							**record["candidate"],
							"item_amount": new_amount,
						},
					}
					context = _decision_context(pnl, record, history)
					if context.get("already_effective"):
						typer.echo("Edited amount matches what is already effective.")
						continue
					if not context.get("adjustment_id"):
						context["adjustment_id"] = _next_adjustment_id(history)
				if context["crosses_zero"]:
					confirm = typer.prompt(
						"WARNING: removes more than the reported line holds. Type yes to confirm",
						default="no",
					).strip().lower()
					if confirm != "yes":
						typer.echo("Not confirmed; skipped.")
						continue

				row = _decision_history_row(
					ticker,
					context,
					record,
					status="approved",
					run_id=run_id,
					override_reason=note,
				)
				if not _trial_reconciles(pnl, history, row):
					raise ReviewActionError(
						"approval would break adjusted reconciliation; refused"
					)
				label = "Approved" if action == "a" else "Approved edited amount"
				typer.echo(
					f"{label} as {row['adjustment_id']} v{row['version']}."
				)

			history = _append_history_row(history_path, history, row)
			decisions += 1
		except ReviewActionError as exc:
			typer.echo(f"Refused: {exc}")

	typer.echo(f"Session complete ({decisions} decision(s) recorded).")
	if decisions:
		_rebuild_adjusted_outputs(ticker, output_root, pnl)


@app.command()
def review(
	ticker: str,
	output_root: Path = typer.Option(
		default=Path("data"),
		help="Workspace root containing data outputs.",
	),
) -> None:
	"""Interactive human review of pending normalization candidates."""
	_run_review_session(ticker.strip().upper(), output_root)


@app.command()
def analyze(
	ticker: str,
	years: int = typer.Option(
		default=3,
		help="Number of annual periods to include.",
	),
	adjustments: bool = typer.Option(
		default=False,
		help="Run integrated LLM adjustment analysis and deterministic application.",
	),
	model: str = typer.Option(
		default=DEFAULT_MODEL,
		help="OpenAI model for proposals. Default: gpt-5.6-luna",
	),
	reasoning_effort: str = typer.Option(
		default=DEFAULT_REASONING_EFFORT,
		help="OpenAI reasoning effort for proposals; override as needed.",
	),
	scan: bool = typer.Option(
		default=False,
		help="Run the read-only Analytical Scan over the reported P&L.",
	),
	output_root: Path = typer.Option(
		default=Path("data"),
		help="Workspace root containing data outputs.",
	),
) -> None:
	"""Build the analytical P&L and save deterministic reconciliation checks."""
	if scan and adjustments:
		raise typer.BadParameter("--scan cannot be combined with --adjustments")
	pnl = build_analytical_pnl(ticker, years=years)
	output_path = save_analytical_pnl(ticker, pnl, output_root)

	typer.echo(f"Saved analytical P&L: {output_path}")

	# Reconciliation stays deterministic and runs before the optional Analyst.
	_save_and_report_reconciliation(ticker, pnl, output_root)
	if scan:
		try:
			context = format_analytical_pnl_for_scan(pnl)
			result, metadata = run_analytical_scan(
				ticker,
				pnl,
				filing=pnl.attrs.get("edgar_filing"),
				model=model,
				reasoning_effort=reasoning_effort,
				context=context,
			)
			output_path = save_analytical_scan(
				ticker,
				result,
				metadata,
				context,
				output_root,
			)
			typer.echo(f"Saved analytical scan: {output_path}")
			typer.echo(render_analytical_scan_summary(result))
		except AnalyticalScanError as exc:
			typer.echo(f"Analytical scan unavailable: {exc}", err=True)
		return
	if adjustments:
		try:
			_run_adjustment_analysis(
				ticker,
				pnl,
				model,
				reasoning_effort,
				output_root=output_root,
				filing=pnl.attrs.get("edgar_filing"),
			)
		except AdjustmentAnalysisError as exc:
			typer.echo(f"Adjustment analysis unavailable: {exc}", err=True)


@app.command()
def reconcile(ticker: str) -> None:
	"""Reconcile safe reported P&L subtotals from the existing analytical P&L."""
	pnl = load_analytical_pnl(ticker)
	_save_and_report_reconciliation(ticker, pnl)


def main() -> None:
	app()
