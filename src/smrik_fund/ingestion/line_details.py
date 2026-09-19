"""Long-form presentation rows for segment and normalization detail."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from pathlib import Path

import pandas as pd

from .adjustments import (
	_current_approved_adjustments,
	_find_line_index,
	_find_row_key_index,
	atomic_write_csv,
)
from .statements import ANNUAL_PERIOD_PATTERN

DETAIL_COLUMNS = (
	"row_type",
	"parent_row_key",
	"detail_row_key",
	"period",
	"label",
	"amount",
	"line_delta",
	"source_ref",
	"breakdown_group",
	"adjusted_value",
	"included_in_subtotals",
	"source_status",
	"source_snapshot_id",
	"filing_accession",
	"source_locator",
	"evidence_ref",
	"unit",
	"scale",
	"source_qualification",
)
REPORTED_DETAIL_COLUMNS = (
	"parent_row_key",
	"detail_row_key",
	"period",
	"label",
	"amount",
	"line_delta",
	"source_ref",
	"breakdown_group",
	"adjusted_value",
	"included_in_subtotals",
	"source_status",
	"source_snapshot_id",
	"filing_accession",
	"source_locator",
	"evidence_ref",
	"unit",
	"scale",
	"source_qualification",
)
_SEGMENT_PARENTS = {"Revenue": "Revenue", "OperatingIncomeLoss": "OperatingIncomeLoss"}
_REPORTED_REQUIRED = {
	"parent_row_key",
	"detail_row_key",
	"period",
	"label",
	"amount",
	"source_ref",
	"breakdown_group",
	"source_status",
	"source_snapshot_id",
	"filing_accession",
	"source_locator",
	"evidence_ref",
	"unit",
	"scale",
	"source_qualification",
}
_EVIDENCE_REF_PATTERN = re.compile(
	r"^filing:(?P<accession>[A-Za-z0-9-]+):line:(?P<line>[1-9][0-9]*)$"
)
_SOURCE_LOCATOR_PATTERN = re.compile(
	r"^source text line (?P<line>[1-9][0-9]*)$"
)


def _text(value: object) -> str:
	if value is None:
		return ""
	try:
		if bool(pd.isna(value)):
			return ""
	except (TypeError, ValueError):
		pass
	return " ".join(str(value).split())


def _number(value: object) -> float | None:
	try:
		number = float(value)
	except (TypeError, ValueError):
		return None
	return number if math.isfinite(number) else None


def _parent_key(pnl: pd.DataFrame, index: object) -> str:
	concept = _text(pnl.at[index, "standard_concept"]) if "standard_concept" in pnl else ""
	if concept and int(pnl["standard_concept"].eq(concept).fillna(False).sum()) == 1:
		return f"standard_concept:{concept}"
	label = _text(pnl.at[index, "label"]) if "label" in pnl else ""
	if label:
		return f"label:{label}"
	raise ValueError("parent P&L row has no stable source identity")


def _resolve_parent(pnl: pd.DataFrame, *, concept: object = None, target_line: object = None, target_row_key: object = None) -> tuple[object, str]:
	if key := _text(target_row_key):
		return _find_row_key_index(pnl, key), key
	if line := _text(target_line):
		index = _find_line_index(pnl, line)
		return index, _parent_key(pnl, index)
	if concept := _text(concept):
		key = f"standard_concept:{concept}"
		return _find_row_key_index(pnl, key), key
	raise ValueError("detail has no target parent row")


def _row(**values: object) -> dict[str, object]:
	row = dict.fromkeys(DETAIL_COLUMNS)
	row.update(values)
	return row


def _missing(value: object) -> bool:
	if value is None:
		return True
	try:
		return bool(pd.isna(value))
	except (TypeError, ValueError):
		return False


def _required_text(value: object, field: str) -> str:
	text = _text(value)
	if not text:
		raise ValueError(f"reported detail requires {field}")
	return text


def _source_file(source_ref: str) -> Path:
	path = Path(source_ref.split("#", 1)[0])
	if not path.is_absolute():
		path = Path.cwd() / path
	return path


def load_reported_detail_context(
	path: Path,
) -> dict[str, dict[str, object]] | None:
	"""Load the frozen evidence context paired with a reported-detail CSV."""
	context_path = Path(path).with_name("reported_details_context.json")
	if not context_path.is_file():
		return None
	try:
		payload = json.loads(context_path.read_text(encoding="utf-8"))
	except (OSError, UnicodeError, json.JSONDecodeError) as exc:
		raise ValueError("reported detail source context cannot be read") from exc
	if not isinstance(payload, Mapping) or any(
		not isinstance(key, str) or not isinstance(value, Mapping)
		for key, value in payload.items()
	):
		raise ValueError("reported detail source context must map evidence refs to objects")
	return {str(key): dict(value) for key, value in payload.items()}


def _validate_source_provenance(
	row: dict[str, object],
	source_context: Mapping[str, Mapping[str, object]] | None,
) -> None:
	"""Resolve mechanical identity and financial support from included context."""
	if source_context is None:
		raise ValueError("reported detail requires complete source context")
	evidence_match = _EVIDENCE_REF_PATTERN.fullmatch(row["evidence_ref"])
	locator_match = _SOURCE_LOCATOR_PATTERN.fullmatch(row["source_locator"])
	if evidence_match is None or locator_match is None:
		raise ValueError("reported detail source reference or locator is invalid")
	accession = evidence_match.group("accession")
	line_number = int(evidence_match.group("line"))
	if accession != row["filing_accession"] or line_number != int(locator_match.group("line")):
		raise ValueError("reported detail source identity does not match its evidence")
	entry = source_context.get(row["evidence_ref"])
	if not isinstance(entry, Mapping):
		raise ValueError("reported detail evidence is not present in source context")
	parent_context = entry.get("parent_row_key")
	if parent_context is None:
		parent_context = entry.get("scope")
	if any(
		field not in entry or not _text(entry[field])
		for field in (
			"source_snapshot_id",
			"filing_accession",
			"source_ref",
			"source_locator",
			"period",
			"unit",
			"scale",
			"source_qualification",
			"source_status",
		)
	) or not _text(parent_context):
		raise ValueError("reported detail source context is incomplete")
	if "amount" not in entry:
		raise ValueError("reported detail source context is missing period amount")
	source_path = _source_file(_text(entry["source_ref"]))
	if not source_path.is_file() or source_path.stem != accession:
		raise ValueError("reported detail source file does not match its filing")
	try:
		source_bytes = source_path.read_bytes()
		lines = source_bytes.decode("utf-8").splitlines()
	except (OSError, UnicodeError) as exc:
		raise ValueError("reported detail source file cannot be read") from exc
	if (
		not re.fullmatch(r"[0-9a-fA-F]{64}", _text(entry.get("source_sha256")))
		or hashlib.sha256(source_bytes).hexdigest() != _text(entry["source_sha256"]).casefold()
	):
		raise ValueError("reported detail source content changed; reassessment is required")
	if line_number > len(lines) or not lines[line_number - 1].strip():
		raise ValueError("reported detail source locator is not present")
	nearby_text = " ".join(lines[max(0, line_number - 2) : line_number + 1])
	context_text = _text(entry.get("text", entry.get("excerpt")))
	if not context_text or context_text.casefold() not in nearby_text.casefold():
		raise ValueError("reported detail source context text is not present at its locator")
	if row["label"].casefold() not in context_text.casefold():
		raise ValueError("reported detail lacks semantic source support")
	if row["source_qualification"].casefold() not in context_text.casefold():
		raise ValueError("reported detail lacks required source qualification")
	for field in (
		"source_snapshot_id",
		"filing_accession",
		"source_ref",
		"source_locator",
		"parent_row_key",
		"unit",
		"scale",
		"source_qualification",
	):
		expected = entry.get(field)
		if field == "parent_row_key" and expected is None:
			expected = entry.get("scope")
		if expected is not None and _text(expected) != row[field]:
			if field == "source_snapshot_id":
				raise ValueError(
					"reported detail source changed; explicit reassessment is required"
				)
			raise ValueError(f"reported detail {field} does not match source context")
	periods = entry.get("periods", entry.get("period"))
	if periods is None or _text(periods) != row["period"]:
		raise ValueError("reported detail source context is missing period scope")
	status = entry.get("source_status")
	if status is not None and _text(status).casefold() != row["source_status"].casefold():
		raise ValueError("reported detail source status does not match source context")
	context_amount = entry["amount"]
	if _missing(context_amount):
		if row["amount"] is not None:
			raise ValueError("reported detail amount does not match source context")
	else:
		context_amount = _number(context_amount)
		if context_amount is None or context_amount != row["amount"]:
			raise ValueError("reported detail amount does not match source context")


def validate_reported_details(
	details: pd.DataFrame,
	*,
	source_context: Mapping[str, Mapping[str, object]] | None = None,
) -> pd.DataFrame:
	"""Validate and de-duplicate persisted reported composition rows.

	Reported rows carry source support and can never carry a normalization
	delta. A changed source for the same logical detail is rejected until an
	explicit reassessment chooses which source applies.
	"""
	if not isinstance(details, pd.DataFrame):
		raise TypeError("reported_details must be a pandas DataFrame")
	if source_context is not None and not isinstance(source_context, Mapping):
		raise TypeError("source_context must be a mapping keyed by evidence_ref")
	if details.empty:
		return pd.DataFrame(columns=REPORTED_DETAIL_COLUMNS)
	missing = _REPORTED_REQUIRED.difference(details.columns)
	if missing:
		raise ValueError(
			"reported details are missing columns: " + ", ".join(sorted(missing))
		)
	normalized: list[dict[str, object]] = []
	for record in details.to_dict(orient="records"):
		row = {
			field: _required_text(record.get(field), field)
			for field in (
				"parent_row_key",
				"detail_row_key",
				"period",
				"label",
				"source_ref",
				"breakdown_group",
				"source_status",
				"source_snapshot_id",
				"filing_accession",
				"source_locator",
				"evidence_ref",
				"unit",
				"scale",
				"source_qualification",
			)
		}
		if not ANNUAL_PERIOD_PATTERN.fullmatch(row["period"]):
			raise ValueError(f"reported detail period {row['period']!r} is invalid")
		if row["breakdown_group"] == "normalization":
			raise ValueError("reported detail cannot use normalization breakdown group")
		raw_amount = record.get("amount")
		if _missing(raw_amount) or (isinstance(raw_amount, str) and not raw_amount.strip()):
			amount = None
		else:
			amount = _number(raw_amount)
			if amount is None:
				raise ValueError("reported detail amount must be finite or missing")
		row["amount"] = amount
		line_delta = record.get("line_delta")
		if not _missing(line_delta) and _number(line_delta) != 0:
			raise ValueError("reported detail line_delta must be zero")
		row["line_delta"] = 0.0
		row["adjusted_value"] = amount
		if "adjusted_value" in record and not _missing(record.get("adjusted_value")):
			adjusted_value = _number(record.get("adjusted_value"))
			if adjusted_value is None or amount is None or adjusted_value != amount:
				raise ValueError("reported detail adjusted_value must equal amount")
		if "included_in_subtotals" in record and _truthy(
			record.get("included_in_subtotals")
		):
			raise ValueError("reported detail cannot be included in subtotals")
		row["included_in_subtotals"] = False
		_validate_source_provenance(row, source_context)
		for field in REPORTED_DETAIL_COLUMNS:
			row.setdefault(field, None)
		normalized.append(row)
	frame = pd.DataFrame(normalized, columns=REPORTED_DETAIL_COLUMNS)
	identity_columns = [
		"source_snapshot_id",
		"filing_accession",
		"parent_row_key",
		"period",
		"detail_row_key",
		"breakdown_group",
	]
	compare_columns = [
		"label",
		"amount",
		"source_ref",
		"source_status",
		"source_locator",
		"evidence_ref",
		"unit",
		"scale",
		"source_qualification",
	]
	for _, duplicate in frame.groupby(identity_columns, dropna=False, sort=False):
		if len(duplicate) > 1 and duplicate[compare_columns].drop_duplicates().shape[0] > 1:
			raise ValueError("conflicting reported detail rows share one source identity")
	logical_columns = [
		"parent_row_key",
		"period",
		"detail_row_key",
		"breakdown_group",
	]
	for _, logical in frame.groupby(logical_columns, dropna=False, sort=False):
		if logical["source_snapshot_id"].nunique(dropna=False) > 1:
			raise ValueError(
				"reported detail source changed; explicit reassessment is required"
			)
	return frame.drop_duplicates(identity_columns, keep="first").reset_index(drop=True)


def load_reported_details(
	path: Path,
	*,
	source_context: Mapping[str, Mapping[str, object]] | None = None,
) -> pd.DataFrame:
	"""Load the durable reported composition file, failing closed if invalid."""
	if not path.is_file():
		return pd.DataFrame(columns=REPORTED_DETAIL_COLUMNS)
	if source_context is None:
		source_context = load_reported_detail_context(path)
	try:
		frame = pd.read_csv(path)
	except pd.errors.EmptyDataError:
		return pd.DataFrame(columns=REPORTED_DETAIL_COLUMNS)
	return validate_reported_details(frame, source_context=source_context)


def save_reported_details(
	path: Path,
	details: pd.DataFrame,
	*,
	source_context: Mapping[str, Mapping[str, object]] | None = None,
) -> pd.DataFrame:
	"""Append validated reported detail rows idempotently and persist them."""
	if source_context is None:
		source_context = load_reported_detail_context(path)
	incoming = validate_reported_details(details, source_context=source_context)
	existing = load_reported_details(path, source_context=source_context)
	if existing.empty:
		merged = incoming
	elif incoming.empty:
		merged = existing
	else:
		merged = validate_reported_details(
			pd.concat([existing, incoming], ignore_index=True),
			source_context=source_context,
		)
	atomic_write_csv(path, merged)
	return merged


def build_line_details(
	pnl: pd.DataFrame,
	segments: pd.DataFrame | None = None,
	adjustments: pd.DataFrame | None = None,
	reported_details: pd.DataFrame | None = None,
	source_context: Mapping[str, Mapping[str, object]] | None = None,
) -> pd.DataFrame:
	"""Build parent/detail/remaining rows without changing ``pnl``."""
	if not isinstance(pnl, pd.DataFrame):
		raise TypeError("pnl must be a pandas DataFrame")
	periods = [c for c in pnl if isinstance(c, str) and ANNUAL_PERIOD_PATTERN.fullmatch(c)]
	if not periods:
		raise ValueError("pnl must contain annual FY periods")
	parents: dict[tuple[str, str], tuple[object, float | None]] = {}
	order: list[tuple[str, str]] = []
	details: dict[tuple[str, str], list[dict[str, object]]] = {}
	groups: dict[tuple[str, str], list[str]] = {}
	deltas: dict[tuple[str, str], list[float | None]] = {}

	def add_parent(index: object, key: str, period: str) -> float | None:
		if period not in periods:
			raise ValueError(f"detail period {period!r} is not present in P&L")
		if (key, period) not in parents:
			parents[key, period] = (index, _number(pnl.at[index, period]))
			order.append((key, period))
		return parents[key, period][1]

	def add_detail(
		index: object,
		key: str,
		period: str,
		*,
		row_key: str,
		label: str,
		amount: float | None,
		line_delta: float,
		source_ref: str,
		group: str,
		status: str,
		metadata: dict[str, object] | None = None,
	) -> None:
		add_parent(index, key, period)
		row = _row(row_type="detail", parent_row_key=key, detail_row_key=row_key, period=period, label=label, amount=amount, line_delta=line_delta, source_ref=source_ref, breakdown_group=group, adjusted_value=amount + line_delta if amount is not None else None, included_in_subtotals=False, source_status=status, **(metadata or {}))
		details.setdefault((key, period), []).append(row)
		groups.setdefault((key, period), []).append(group)
		if group == "normalization":
			deltas.setdefault((key, period), []).append(line_delta)

	if reported_details is not None:
		for source in validate_reported_details(
			reported_details, source_context=source_context
		).to_dict(orient="records"):
			index, key = _resolve_parent(
				pnl, target_row_key=source["parent_row_key"]
			)
			add_detail(
				index,
				key,
				source["period"],
				row_key=source["detail_row_key"],
				label=source["label"],
				amount=source["amount"],
				line_delta=0.0,
				source_ref=source["source_ref"],
				group=source["breakdown_group"],
				status=source["source_status"],
				metadata={
					field: source[field]
					for field in (
						"source_snapshot_id",
						"filing_accession",
						"source_locator",
						"evidence_ref",
						"unit",
						"scale",
						"source_qualification",
					)
				},
			)

	if segments is not None:
		if not isinstance(segments, pd.DataFrame):
			raise TypeError("segments must be a pandas DataFrame")
		for _, source in segments.iterrows():
			if (_text(source.get("fact_status")) or "PASS") != "PASS":
				continue
			segment_ref = _text(source.get("segment_ref"))
			if not segment_ref:
				continue
			metric = _text(source.get("metric"))
			if metric not in _SEGMENT_PARENTS:
				raise ValueError(f"unsupported segment metric {metric!r}")
			index, key = _resolve_parent(pnl, concept=_SEGMENT_PARENTS[metric])
			amount = _number(source.get("numeric_value"))
			if amount is None:
				amount = _number(source.get("reported_value", source.get("value")))
			source_ref = _text(source.get("fact_id")) or _text(source.get("context_ref")) or _text(source.get("source_locator"))
			if not source_ref:
				continue
			add_detail(index, key, _text(source.get("period")), row_key=segment_ref, label=_text(source.get("segment_label")) or _text(source.get("segment_member")), amount=amount, line_delta=0.0, source_ref=source_ref, group="segment", status="PASS")

	if adjustments is not None:
		if not isinstance(adjustments, pd.DataFrame):
			raise TypeError("adjustments must be a pandas DataFrame")
		for _, source in _current_approved_adjustments(adjustments).iterrows():
			index, key = _resolve_parent(pnl, target_line=source.get("target_line"), target_row_key=source.get("target_row_key"))
			period = _text(source.get("period"))
			delta = _number(source.get("_line_delta_number"))
			if delta is None:
				raise ValueError("normalization adjustment has no signed line_delta")
			adjustment_id = _text(source.get("adjustment_id"))
			if not adjustment_id:
				raise ValueError("normalization adjustment requires adjustment_id")
			add_detail(
				index,
				key,
				period,
				row_key=adjustment_id,
				label=_text(source.get("sub_item"))
				or _text(source.get("reason"))
				or adjustment_id,
				amount=-delta,
				line_delta=delta,
				source_ref=_text(source.get("evidence_file"))
				or _text(source.get("filing_accession"))
				or adjustment_id,
				group="normalization",
				status="APPROVED",
				metadata={
					field: source.get(field)
					for field in (
						"source_snapshot_id",
						"filing_accession",
						"source_locator",
						"evidence_ref",
						"unit",
						"scale",
					)
				},
			)

	output: list[dict[str, object]] = []
	for key, period in order:
		index, parent = parents[key, period]
		delta = math.fsum(deltas.get((key, period), []))
		adjusted = parent + delta if parent is not None and delta is not None else None
		output.append(_row(row_type="parent", parent_row_key=key, period=period, label=_text(pnl.at[index, "label"]), amount=parent, line_delta=0.0, adjusted_value=adjusted, included_in_subtotals=True, source_status="REPORTED"))
		parent_details = details[key, period]
		output.extend(parent_details)
		for group in dict.fromkeys(groups[key, period]):
			amounts = [_number(row["amount"]) for row in parent_details if row["breakdown_group"] == group]
			amount = None if any(value is None for value in amounts) else math.fsum(amounts)
			remaining = parent - amount if parent is not None and amount is not None else None
			output.append(_row(row_type="remaining", parent_row_key=key, detail_row_key=f"remaining:{group}", period=period, label="Remaining / unexplained", amount=remaining, line_delta=0.0, breakdown_group=group, adjusted_value=remaining, included_in_subtotals=False, source_status="DERIVED"))
	return pd.DataFrame(output, columns=DETAIL_COLUMNS)


def _is_existing_breakdown(row: pd.Series) -> bool:
	if _text(row.get("standard_concept")):
		return False
	return _truthy(row.get("is_breakdown")) or _truthy(row.get("dimension"))


def _truthy(value: object) -> bool:
	if value is None:
		return False
	try:
		if bool(pd.isna(value)):
			return False
	except (TypeError, ValueError):
		pass
	if isinstance(value, str):
		return value.strip().lower() in {"1", "true", "yes"}
	return bool(value)


def _metric_columns(pnl: pd.DataFrame) -> list[str]:
	markers = (
		"yoy_",
		"absolute_yoy",
		"percent_of_revenue",
		"gross_margin",
		"operating_margin",
		"pretax_margin",
		"bps_change",
		"two_year_cagr",
	)
	return [
		column
		for column in pnl.columns
		if isinstance(column, str) and any(marker in column for marker in markers)
	]


def _child_rows_by_parent(
	details: pd.DataFrame, periods: list[str]
) -> dict[str, list[dict[str, object]]]:
	"""Pivot long-form details into one child row per parent."""
	children: dict[str, list[dict[str, object]]] = {}
	order: dict[str, list[tuple[object, ...]]] = {}
	amounts: dict[tuple[object, ...], dict[str, float | None]] = {}
	meta: dict[tuple[object, ...], dict[str, object]] = {}
	for record in details.to_dict(orient="records"):
		if record.get("row_type") == "parent":
			continue
		if (
			record.get("row_type") == "remaining"
			and record.get("breakdown_group") == "normalization"
		):
			# Parent already holds the residual after apply_adjustments.
			continue
		parent = record.get("parent_row_key")
		if not parent:
			continue
		identity = (
			parent,
			record.get("row_type"),
			record.get("detail_row_key"),
			record.get("breakdown_group"),
		)
		if identity not in meta:
			meta[identity] = record
			order.setdefault(str(parent), []).append(identity)
		amounts.setdefault(identity, {})
		period = record.get("period")
		if isinstance(period, str):
			amounts[identity][period] = _number(record.get("amount"))
	for parent, identities in order.items():
		rows: list[dict[str, object]] = []
		for identity in identities:
			record = meta[identity]
			row = {
				"row_type": record.get("row_type"),
				"row_key": record.get("detail_row_key"),
				"parent_row_key": parent,
				"label": record.get("label"),
				"breakdown_group": record.get("breakdown_group"),
				"source_status": record.get("source_status"),
				"source_ref": record.get("source_ref"),
				"included_in_subtotals": False,
				"is_breakdown": True,
				"dimension": record.get("breakdown_group") == "segment",
			}
			for field in (
				"source_snapshot_id",
				"filing_accession",
				"source_locator",
				"evidence_ref",
				"unit",
				"scale",
				"source_qualification",
			):
				row[field] = record.get(field)
			period_amounts = amounts[identity]
			for period in periods:
				row[period] = period_amounts.get(period)
			rows.append(row)
		children[parent] = rows
	return children


def attach_model_rows(pnl: pd.DataFrame, details: pd.DataFrame) -> pd.DataFrame:
	"""Insert segment and added-line children under statement parents.

	Reported/adjusted parent values are unchanged. Children are breakdown
	rows and are not included in subtotals. Normalization remaining is
	omitted: after application that residual already sits on the parent.
	"""
	if not isinstance(pnl, pd.DataFrame):
		raise TypeError("pnl must be a pandas DataFrame")
	if details is None:
		return pnl.copy(deep=True)
	if not isinstance(details, pd.DataFrame):
		raise TypeError("details must be a pandas DataFrame")
	if details.empty:
		return pnl.copy(deep=True)
	periods = [
		column
		for column in pnl.columns
		if isinstance(column, str) and ANNUAL_PERIOD_PATTERN.fullmatch(column)
	]
	children = _child_rows_by_parent(details, periods)
	if not children:
		return pnl.copy(deep=True)
	metric_columns = _metric_columns(pnl)
	output: list[dict[str, object]] = []
	index = 0
	length = len(pnl)
	while index < length:
		row = pnl.iloc[index]
		output.append(row.to_dict())
		index += 1
		if _is_existing_breakdown(row) or _truthy(row.get("abstract")):
			continue
		try:
			parent_key = _parent_key(pnl, row.name)
		except (KeyError, ValueError):
			continue
		inserted = children.get(parent_key)
		if not inserted:
			continue
		while index < length and _is_existing_breakdown(pnl.iloc[index]):
			output.append(pnl.iloc[index].to_dict())
			index += 1
		for child in inserted:
			model_row = dict.fromkeys(pnl.columns)
			model_row.update(child)
			for column in metric_columns:
				model_row[column] = None
			model_row["standard_concept"] = None
			model_row["concept"] = None
			output.append(model_row)
	frame = pd.DataFrame(output)
	extras = [
		column
		for column in (
			"row_type",
			"row_key",
			"parent_row_key",
			"breakdown_group",
			"source_status",
			"source_ref",
			"included_in_subtotals",
			"is_breakdown",
			"dimension",
			"source_snapshot_id",
			"filing_accession",
			"source_locator",
			"evidence_ref",
			"unit",
			"scale",
			"source_qualification",
		)
		if column not in pnl.columns
	]
	return frame.reindex(columns=[*pnl.columns, *extras])


__all__ = [
	"DETAIL_COLUMNS",
	"REPORTED_DETAIL_COLUMNS",
	"attach_model_rows",
	"build_line_details",
	"load_reported_detail_context",
	"load_reported_details",
	"save_reported_details",
	"validate_reported_details",
]
