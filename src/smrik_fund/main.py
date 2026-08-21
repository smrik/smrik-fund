import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import typer

from .ingestion.adjustment_analysis import (
	DEFAULT_MODEL,
	DEFAULT_REASONING_EFFORT,
	AdjustmentAnalysisError,
	run_analyst,
)
from .ingestion.adjustments import apply_adjustments, resolve_current_adjustments
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
) -> Path:
	checks = reconcile_pnl(pnl)
	output_path = save_reconciliation_checks(ticker, checks)

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
	"target_line",
	"period",
	"amount",
	"status",
)

# Keep Reviewer fan-out finite without truncating an Analyst response.
MAX_CANDIDATES_PER_TOPIC = 3


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


def _source_line_indices(pnl: pd.DataFrame, target_line: object) -> list[object]:
	"""Return unique exact source-line matches without guessing between rows."""
	matches: list[object] = []
	for column in ("label", "standard_concept"):
		if column in pnl:
			matches.extend(
				pnl.index[pnl[column].eq(target_line).fillna(False)].tolist()
			)
	return list(dict.fromkeys(matches))


def _reported_source_value(
	pnl: pd.DataFrame,
	target_line: object,
	period: object,
) -> float | None:
	"""Return one exact signed reported value, or None when it is unavailable."""
	if period not in pnl.columns:
		return None
	line_indices = _source_line_indices(pnl, target_line)
	if len(line_indices) != 1:
		return None
	value = pd.to_numeric(
		pd.Series([pnl.at[line_indices[0], period]]), errors="coerce"
	).iloc[0]
	return None if pd.isna(value) else float(value)


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
		"reviewer_verdicts",
		"gate_decisions",
		"final_statuses",
		"application_statuses",
	)
	nullable_fields = set(list_fields[-4:])

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
		period_row = {
			"period": candidate.get("period"),
			"amount": candidate.get("adjustment_amount"),
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
			period_row["reported_value"] = _reported_source_value(
				pnl, candidate.get("target_line"), candidate.get("period")
			)
		group["periods"].append(period_row)
		values = {
			"financial_assessments": (candidate.get("reason"),),
			"uncertainties": (candidate.get("uncertainty"),),
			"reviewer_concerns": review.get("concerns") or (),
			"reviewer_notes": (review.get("note"),),
			"unresolved_issues": (record.get("error"),),
			"why_not_automatic": gate.get("reasons") or (),
			"reviewer_verdicts": (review.get("verdict"),),
			"gate_decisions": (gate.get("decision"),),
			"final_statuses": (record.get("final_status"),),
			"application_statuses": (record.get("application_status"),),
		}
		for field, entries in values.items():
			for value in entries or ():
				add(group, field, value, allow_none=field in nullable_fields)
	return list(groups.values())


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

	gate_reason_labels = {
		"reviewer_verdict_revise": "Reviewer requested revision",
		"reviewer_verdict_reject": "Reviewer rejected the candidate",
		"evidence_strength_not_strong": "Reviewer evidence strength is not strong",
		"adjustment_amount_missing": "Candidate magnitude is not disclosed",
		"adjustment_amount_not_finite": "Candidate magnitude is not finite",
		"adjustment_amount_negative": "Candidate magnitude is negative",
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
		"reconciliation_unresolved_or_unknown": (
			"Source reconciliation is unresolved or unknown"
		),
		"possible_duplicate_or_unknown": "Possible duplicate is present or unknown",
		"group_reconciliation_failed_or_unknown": (
			"Group reconciliation failed or is unknown"
		),
		"aggregate_over_adjustment_or_unknown": (
			"Aggregate adjustment exceeds the target or is unknown"
		),
		"source_target_missing_or_unknown": (
			"Reported target value is missing or unknown"
		),
		"source_target_negative_or_unknown": (
			"Reported target value is negative or unknown"
		),
		"individual_over_adjustment_or_unknown": (
			"Individual adjustment exceeds the target or is unknown"
		),
		"zero_target_positive_adjustment_or_unknown": (
			"Reported target is zero or unknown with a positive candidate magnitude"
		),
		"deterministic_checks_failed_or_unknown": (
			"Deterministic checks failed or are unknown"
		),
	}

	def gate_reason_label(reason: Any) -> str:
		return gate_reason_labels.get(str(reason), "Gate condition is not satisfied")

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
		periods = "; ".join(
			(
				f"{type_label(row['period'])}="
				f"reported {amount_label(row.get('reported_value'), signed=True)}, "
				f"candidate magnitude {amount_label(row['amount'])} "
				f"({type_label(row['amount_basis'])})"
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
				label = gate_reason_label(reason)
				if label not in shown_reasons:
					shown_reasons.append(label)
			shown_reasons = shown_reasons[:3]
			shown = "; ".join(shown_reasons)
			if len(reasons) > 3:
				shown += f"; (+{len(reasons) - 3} more in manifest)"
			typer.echo("  Why not automatic: " + shown)


def _gate_conditions(
	pnl: pd.DataFrame,
	candidate: Any,
	reconciliation_checks: pd.DataFrame,
) -> RiskGateConditions:
	"""Build only facts already established by deterministic V1 code."""
	if reconciliation_checks.empty or "status" not in reconciliation_checks:
		reconciliation_clear = None
	else:
		reconciliation_clear = bool(reconciliation_checks["status"].eq("PASS").all())
	line_matches = _source_line_indices(pnl, candidate.target_line)
	source_available = (
		candidate.period in pnl.columns
		and len(line_matches) == 1
		and pd.notna(pnl.at[line_matches[0], candidate.period])
	)
	source_target_negative = None
	if source_available:
		source_value = pd.to_numeric(
			pd.Series([pnl.at[line_matches[0], candidate.period]]), errors="coerce"
		).iloc[0]
		if pd.notna(source_value):
			source_target_negative = bool(source_value < 0)
	return RiskGateConditions(
		reconciliation_clear=reconciliation_clear,
		source_target_available=source_available,
		source_target_negative=source_target_negative,
	)


def _run_adjustment_analysis(
	ticker: str,
	pnl: pd.DataFrame,
	model: str,
	reasoning_effort: str,
	*,
	output_root: str | Path = "data",
	filing: Any | None = None,
) -> Path:
	"""Run one discovery call, then exact retrieval and existing review mechanics."""
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

	reconciliation_checks = reconcile_pnl(pnl)
	history_path = output_directory / "adjustment_history.csv"
	history_path.parent.mkdir(parents=True, exist_ok=True)
	history = _load_adjustment_history(history_path)
	records: list[dict[str, Any]] = []
	history_rows: list[dict[str, Any]] = []
	next_offset = 0

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
			adjustment_id = _next_adjustment_id(history, next_offset)
			next_offset += 1
			candidate_data = candidate.model_dump(mode="json")
			if not candidate.evidence_refs:
				records.append(
					{
						"adjustment_id": adjustment_id,
						"topic": item["topic"],
						"candidate": candidate_data,
						"final_status": "unresolved",
						"application_status": "not_applied",
						"error": "candidate returned no evidence references",
					}
				)
				continue
			try:
				validate_evidence_refs(
					packet,
					candidate.evidence_refs,
					require_identity=filing is not None,
				)
			except FilingEvidenceError as exc:
				records.append(
					{
						"adjustment_id": adjustment_id,
						"topic": item["topic"],
						"candidate": candidate_data,
						"final_status": "unresolved",
						"application_status": "not_applied",
						"error": str(exc),
					}
				)
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
				review_path = save_reviewer_result(
					ticker,
					adjustment_id,
					candidate,
					review,
					review_metadata,
					output_root=output_root,
				)
			except ReviewerError as exc:
				records.append(
					{
						"adjustment_id": adjustment_id,
						"topic": item["topic"],
						"candidate": candidate_data,
						"final_status": "unresolved",
						"application_status": "not_applied",
						"error": str(exc),
					}
				)
				continue

			gate = evaluate_risk_gate(
				candidate,
				review,
				_gate_conditions(pnl, candidate, reconciliation_checks),
			)
			is_approved = gate.eligible_for_auto_approval
			final_status = "approved" if is_approved else "human_review"
			review_data = review.model_dump(mode="json")
			records.append(
				{
					"adjustment_id": adjustment_id,
					"topic": item["topic"],
					"candidate_number": candidate_number + 1,
					"candidate": candidate_data,
					"review": review_data,
					"review_metadata": review_metadata,
					"review_path": str(review_path),
					"gate": {
						"decision": gate.decision,
						"reasons": list(gate.reasons),
					},
					"final_status": final_status,
					"application_status": ("applied" if is_approved else "not_applied"),
				}
			)
			if is_approved:
				history_rows.append(
					{
						"adjustment_id": adjustment_id,
						"version": 1,
						"run_id": run_id,
						"origin": "llm",
						"target_line": candidate_data["target_line"],
						"sub_item": candidate_data.get("sub_item"),
						"period": candidate_data["period"],
						"amount": candidate_data["adjustment_amount"],
						"status": "approved",
						"amount_basis": candidate_data["amount_basis"],
						"evidence_strength": review_data["evidence_strength"],
						"judgment_level": review_data["judgment_level"],
						"reviewer_verdict": review_data["verdict"],
						"target_valid": review_data["target_valid"],
						"period_valid": review_data["period_valid"],
						"calculation_valid": review_data["calculation_valid"],
						"reviewer_amount_basis": review_data["amount_basis"],
						"gate_decision": gate.decision,
						"gate_reasons": json.dumps(gate.reasons),
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
		current_adjustments = resolve_current_adjustments(history)
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
		typer.echo(
			f"Adjustment history updated ({len(history_rows)} approved rows): "
			f"{history_path}"
		)
	else:
		typer.echo(f"Adjustment history unchanged (0 approved rows): {history_path}")
	typer.echo(f"Saved adjusted P&L: {adjusted_pnl_path}")
	typer.echo(f"Saved adjusted reconciliation: {adjusted_reconciliation_path}")
	typer.echo(f"Saved integrated adjustment run: {manifest_path}")
	return manifest_path


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
) -> None:
	"""Build the analytical P&L and save deterministic reconciliation checks."""
	pnl = build_analytical_pnl(ticker, years=years)
	output_path = save_analytical_pnl(ticker, pnl)

	typer.echo(f"Saved analytical P&L: {output_path}")

	# Reconciliation stays deterministic and runs before the optional Analyst.
	_save_and_report_reconciliation(ticker, pnl)
	if adjustments:
		try:
			_run_adjustment_analysis(
				ticker,
				pnl,
				model,
				reasoning_effort,
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
