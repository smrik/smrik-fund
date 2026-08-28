"""Reported operating-segment facts and guarded analytical context."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from .statements import ANNUAL_PERIOD_PATTERN

REPORTABLE_SEGMENT_AXIS = "StatementBusinessSegmentsAxis"
SEGMENT_METRIC_ORDER = ("Revenue", "OperatingIncomeLoss")
_CONCEPTS = {
	"revenue": "Revenue",
	"revenuefromcontractwithcustomerexcludingassessedtax": "Revenue",
	"salesrevenuenet": "Revenue",
	"operatingincomeloss": "OperatingIncomeLoss",
}
DEFAULT_RECONCILIATION_TOLERANCE = 0.01
_DERIVED_COLUMNS = (
	"absolute_yoy_change",
	"yoy_growth",
	"revenue_share",
	"revenue_share_change_bps",
	"revenue_share_bps_change",
	"revenue_growth_contribution",
	"operating_margin",
	"operating_margin_bps_change",
	"margin_bps_change",
	"operating_income_growth_contribution",
	"operating_growth_contribution",
)
_SOURCE_COLUMNS = (
	"segment_axis",
	"segment_member",
	"segment_label",
	"metric",
	"period",
	"period_end",
	"value",
	"reported_value",
	"numeric_value",
	"unit",
	"currency",
	"concept",
	"standard_concept",
	"fact_id",
	"context_ref",
	"label",
	"original_label",
	"dimension_label",
	"dimension_member_label",
	"full_dimension_label",
	"period_type",
	"period_start",
	"period_instant",
	"fiscal_year",
	"fiscal_period",
	"filing_date",
	"form_type",
	"accession",
	"source_url",
	"source_locator",
	"statement_role",
	"reported_basis",
	"fact_status",
	"status_message",
	"segment_ref",
)


class SegmentAnalyticsError(RuntimeError):
	"""Segment facts cannot be used safely for analytical context."""


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


def _first_text(row: pd.Series, *columns: str) -> str:
	for column in columns:
		value = _text(row.get(column))
		if value:
			return value
	return ""


def _local(value: object) -> str:
	text = _text(value)
	if ":" in text:
		text = text.rsplit(":", 1)[-1]
	elif "_" in text:
		text = text.split("_", 1)[-1]
	return re.sub(r"[^a-zA-Z0-9]", "", text).casefold()


def _axis_is_target(value: object) -> bool:
	return _local(value) == _local(REPORTABLE_SEGMENT_AXIS)


def _metric(row: pd.Series) -> str | None:
	for value in (row.get("standard_concept"), row.get("concept")):
		if (metric := _CONCEPTS.get(_local(value))) is not None:
			return metric
	return None


def _dimensions(row: pd.Series) -> dict[str, str]:
	"""Read raw ``dim_*``, normalized JSON, and structured EdgarTools fields."""
	dimensions: dict[str, str] = {}
	raw = row.get("dimensions")
	if isinstance(raw, dict):
		dimensions.update(
			{_text(k): _text(v) for k, v in raw.items() if _text(k) and _text(v)}
		)
	else:
		try:
			parsed = json.loads(_text(raw))
		except (TypeError, ValueError, json.JSONDecodeError):
			parsed = {}
		if isinstance(parsed, dict):
			dimensions.update(
				{_text(k): _text(v) for k, v in parsed.items() if _text(k) and _text(v)}
			)
	for column, value in row.items():
		if isinstance(column, str) and column.startswith("dim_") and _text(value):
			dimensions.setdefault(column.removeprefix("dim_"), _text(value))
	axis = _first_text(row, "dimension_axis", "dimension")
	member = _first_text(row, "dimension_member", "member")
	if axis and member:
		dimensions.setdefault(axis, member)
	# EdgarTools exposes both the structured ``dimension``/``member`` pair and
	# a duplicate ``dim_*`` column. Collapse only exact axis/member aliases;
	# distinct members on one axis remain separate and therefore unresolved.
	canonical: dict[str, tuple[str, str]] = {}
	for axis, member in dimensions.items():
		key = _local(axis)
		if key not in canonical:
			canonical[key] = (axis, member)
		elif canonical[key][1] != member:
			canonical[f"{key}#{len(canonical)}"] = (axis, member)
	return dict(canonical.values())


def _period_end(value: object) -> str:
	return _text(value)[:10]


def _period_label(value: object) -> str:
	end = _period_end(value)
	return f"{end} (FY)" if end else ""


def _filing_attr(filing: Any, *names: str) -> str:
	for name in names:
		try:
			value = getattr(filing, name)
		except Exception:
			continue
		if not callable(value) and (text := _text(value)):
			return text
	return ""


def _facts(filing: Any) -> pd.DataFrame:
	if filing is None:
		raise SegmentAnalyticsError("filing is required")
	try:
		xbrl_attr = getattr(filing, "xbrl", None)
		xbrl = xbrl_attr() if callable(xbrl_attr) else xbrl_attr
	except Exception as exc:
		raise SegmentAnalyticsError(f"could not load filing XBRL: {exc}") from exc
	if xbrl is None:
		raise SegmentAnalyticsError("filing XBRL is unavailable")
	facts = getattr(xbrl, "facts", None)
	if facts is None:
		facts = getattr(xbrl, "facts_view", None)
	if isinstance(facts, pd.DataFrame):
		return facts.copy(deep=True)
	if facts is None or not hasattr(facts, "to_dataframe"):
		raise SegmentAnalyticsError("filing XBRL facts are unavailable")
	try:
		frame = facts.to_dataframe()
	except Exception as exc:
		raise SegmentAnalyticsError(f"could not read XBRL facts: {exc}") from exc
	if not isinstance(frame, pd.DataFrame):
		raise SegmentAnalyticsError("XBRL facts did not return a DataFrame")
	return frame.copy(deep=True)


def _source_row(
	row: pd.Series,
	axis: str,
	member: str,
	label: str,
	metric: str,
	period: str,
) -> dict[str, object]:
	value = row.get("value")
	numeric = row.get("numeric_value")
	if _number(numeric) is None:
		numeric = value
	return {
		"segment_axis": axis,
		"segment_member": member,
		"segment_label": label,
		"metric": metric,
		"period": period,
		"period_end": _period_end(row.get("period_end")),
		"value": value,
		"reported_value": value,
		"numeric_value": numeric,
		"unit": _first_text(row, "unit", "unit_ref"),
		"currency": _text(row.get("currency")),
		"concept": _text(row.get("concept")),
		"standard_concept": _text(row.get("standard_concept")),
		"fact_id": _first_text(row, "fact_id", "fact_key"),
		"context_ref": _text(row.get("context_ref")),
		"label": _text(row.get("label")),
		"original_label": _text(row.get("original_label")),
		"dimension_label": _text(row.get("dimension_label")),
		"dimension_member_label": _first_text(
			row, "dimension_member_label", "member_label"
		),
		"full_dimension_label": _text(row.get("full_dimension_label")),
		"period_type": _text(row.get("period_type")),
		"period_start": _text(row.get("period_start")),
		"period_instant": _text(row.get("period_instant")),
		"fiscal_year": _text(row.get("fiscal_year")),
		"fiscal_period": _text(row.get("fiscal_period")),
		"filing_date": _text(row.get("filing_date")),
		"form_type": _text(row.get("form_type")),
		"accession": _text(row.get("accession")),
		"source_url": _first_text(row, "source_url", "filing_url", "url"),
		"source_locator": _text(row.get("source_locator")),
		"statement_role": _text(row.get("statement_role")),
		"reported_basis": "reported",
		"fact_status": "PASS",
		"status_message": "",
	}


def extract_segment_facts(
	filing: Any,
	*,
	periods: Sequence[str] | None = None,
) -> pd.DataFrame:
	"""Extract annual facts on exactly one generic reportable-segment axis."""
	requested = {
		_period_end(period): period for period in (periods or []) if _period_end(period)
	}
	rows: list[dict[str, object]] = []
	for _, source in _facts(filing).iterrows():
		metric = _metric(source)
		if metric is None:
			continue
		dimensions = _dimensions(source)
		target = [
			(axis, member)
			for axis, member in dimensions.items()
			if _axis_is_target(axis)
		]
		if len(target) != 1:
			continue
		period_end = _period_end(source.get("period_end"))
		if not period_end or (requested and period_end not in requested):
			continue
		period_type = _text(source.get("period_type")).casefold()
		fiscal_period = _text(source.get("fiscal_period")).casefold()
		if period_type and period_type != "duration":
			continue
		if fiscal_period and fiscal_period not in {"fy", "annual"}:
			continue
		axis, member = target[0]
		label = _first_text(
			source,
			"dimension_member_label",
			"member_label",
			"segment_label",
		)
		record = _source_row(
			source,
			axis,
			member,
			label,
			metric,
			requested.get(period_end, _period_label(period_end)),
		)
		if len(dimensions) != 1:
			record.update(
				fact_status="UNRESOLVED",
				status_message="fact has additional dimensions",
			)
		elif not label:
			record.update(
				fact_status="UNRESOLVED",
				status_message="segment member label is unavailable",
			)
		rows.append(record)
	result = pd.DataFrame(rows)
	if result.empty:
		return pd.DataFrame(columns=[*_SOURCE_COLUMNS, *_DERIVED_COLUMNS])
	# EdgarTools normally carries filing metadata on each fact. Keep the
	# provenance usable with older/cached fact tables too, without fabricating
	# values: only fill genuinely blank fact-level fields from the filing.
	for column, names in {
		"filing_date": ("filing_date", "filed_date"),
		"form_type": ("form", "form_type"),
		"accession": ("accession_number", "accession_no"),
		"source_url": ("filing_url", "url"),
	}.items():
		fallback = _filing_attr(filing, *names)
		if fallback and column in result:
			blank = result[column].isna() | result[column].astype(
				"string"
			).str.strip().eq("")
			result.loc[blank, column] = fallback
	keys = ["segment_axis", "segment_member", "metric", "period"]
	duplicates = result.groupby(keys, dropna=False)["fact_id"].transform("size").ne(1)
	result.loc[duplicates, "fact_status"] = "UNRESOLVED"
	result.loc[duplicates, "status_message"] = "duplicate segment fact candidates"
	for _, group in result.groupby(
		["segment_axis", "segment_member", "metric"], dropna=False
	):
		if not _label_consistent(group):
			result.loc[group.index, "fact_status"] = "UNRESOLVED"
			result.loc[group.index, "status_message"] = (
				"segment member label is inconsistent"
			)
		units = {_text(value) for value in group["unit"]}
		if len(units) != 1 or "" in units:
			result.loc[group.index, "fact_status"] = "UNRESOLVED"
			result.loc[group.index, "status_message"] = (
				"segment units are incomplete or inconsistent"
			)
	for _, group in result.groupby(["segment_axis", "period"], dropna=False):
		starts = {_text(value) for value in group["period_start"]}
		if len(starts) != 1 or "" in starts:
			result.loc[group.index, "fact_status"] = "UNRESOLVED"
			result.loc[group.index, "status_message"] = (
				"segment period starts are not comparable"
			)
	return result


def _periods(pnl: pd.DataFrame, years: int) -> list[str]:
	return [
		column
		for column in pnl.columns
		if isinstance(column, str) and ANNUAL_PERIOD_PATTERN.fullmatch(column)
	][:years]


def _pnl_value(pnl: pd.DataFrame, concept: str, period: str) -> float | None:
	if period not in pnl or "standard_concept" not in pnl:
		return None
	matches = pnl[pnl["standard_concept"].astype("string").eq(concept).fillna(False)]
	return _number(matches.iloc[0][period]) if len(matches) == 1 else None


def _growth(current: float | None, previous: float | None) -> float | None:
	if current is None or previous is None or current <= 0 or previous <= 0:
		return None
	value = current / previous - 1.0
	return value if math.isfinite(value) else None


def _difference(current: float | None, previous: float | None) -> float | None:
	if current is None or previous is None:
		return None
	return current - previous


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
	if numerator is None or denominator is None or denominator <= 0:
		return None
	value = numerator / denominator
	return value if math.isfinite(value) else None


def _bps(current: float | None, previous: float | None) -> float | None:
	if current is None or previous is None:
		return None
	return (current - previous) * 10_000


def _label_consistent(group: pd.DataFrame) -> bool:
	labels = {_text(value) for value in group["segment_label"] if _text(value)}
	return len(labels) == 1 and all(_text(value) for value in group["segment_label"])


def assign_segment_refs(segments: pd.DataFrame) -> pd.DataFrame:
	"""Assign deterministic, collision-safe ``S##`` refs to safe groups."""
	result = segments.copy(deep=True)
	if "fact_status" not in result:
		result["fact_status"] = "PASS"
	result["segment_ref"] = ""
	if result.empty:
		return result
	if not {"segment_axis", "segment_member", "metric", "segment_label"}.issubset(
		result.columns
	):
		return result
	valid = result[result["fact_status"].fillna("PASS").eq("PASS")]
	groups: list[tuple[str, str, str]] = []
	for key, group in valid.groupby(
		["segment_axis", "segment_member", "metric"], dropna=False
	):
		axis, member, metric = map(_text, key)
		if metric in SEGMENT_METRIC_ORDER and member and _label_consistent(group):
			groups.append((axis, member, metric))
	groups.sort(key=lambda key: (key[0], key[1], SEGMENT_METRIC_ORDER.index(key[2])))
	refs = {key: f"S{index:02d}" for index, key in enumerate(groups, 1)}
	for index, row in result.iterrows():
		key = (
			_text(row.get("segment_axis")),
			_text(row.get("segment_member")),
			_text(row.get("metric")),
		)
		if _text(row.get("fact_status")) == "PASS":
			result.at[index, "segment_ref"] = refs.get(key, "")
	return result


def build_segment_analytics(
	filing: Any,
	pnl: pd.DataFrame,
	*,
	years: int = 3,
	tolerance: float = DEFAULT_RECONCILIATION_TOLERANCE,
) -> pd.DataFrame:
	"""Build long source-grain segment analytics without mutating ``pnl``."""
	if isinstance(filing, pd.DataFrame) and not isinstance(pnl, pd.DataFrame):
		filing, pnl = pnl, filing
	if not isinstance(pnl, pd.DataFrame):
		raise TypeError("pnl must be a pandas DataFrame")
	if years < 1:
		raise ValueError("years must be positive")
	periods = _periods(pnl, years)
	result = assign_segment_refs(extract_segment_facts(filing, periods=periods))
	for column in _DERIVED_COLUMNS:
		result[column] = float("nan")
	if result.empty:
		result.attrs["periods"] = periods
		result.attrs["segment_reconciliation"] = pd.DataFrame()
		return result
	by_key = {
		(
			_text(row.get("segment_member")),
			_text(row.get("metric")),
			_text(row.get("period")),
		): index
		for index, row in result.iterrows()
	}
	positions = {period: index for index, period in enumerate(periods)}
	for (member, metric), group in result.groupby(
		["segment_member", "metric"], dropna=False
	):
		if not group["segment_ref"].fillna("").astype(str).str.strip().ne("").any():
			continue
		for period in periods:
			index = by_key.get((_text(member), _text(metric), period))
			if index is None or _text(result.at[index, "fact_status"]) != "PASS":
				continue
			position = positions[period]
			previous_index = (
				by_key.get((_text(member), _text(metric), periods[position + 1]))
				if position + 1 < len(periods)
				else None
			)
			current = _number(result.at[index, "numeric_value"])
			previous = (
				_number(result.at[previous_index, "numeric_value"])
				if previous_index is not None
				and _text(result.at[previous_index, "fact_status"]) == "PASS"
				else None
			)
			absolute, growth = (
				_difference(current, previous),
				_growth(current, previous),
			)
			result.at[index, "absolute_yoy_change"] = absolute
			result.at[index, "yoy_growth"] = growth
			if metric == "Revenue":
				consolidated = _pnl_value(pnl, "Revenue", period)
				prior_consolidated = (
					_pnl_value(pnl, "Revenue", periods[position + 1])
					if position + 1 < len(periods)
					else None
				)
				share, prior_share = (
					_ratio(current, consolidated),
					_ratio(previous, prior_consolidated),
				)
				delta = _difference(consolidated, prior_consolidated)
				contribution = (
					absolute / delta
					if absolute is not None
					and delta not in (None, 0)
					and growth is not None
					else None
				)
				result.loc[
					index,
					[
						"revenue_share",
						"revenue_share_change_bps",
						"revenue_share_bps_change",
						"revenue_growth_contribution",
					],
				] = [
					share,
					_bps(share, prior_share),
					_bps(share, prior_share),
					contribution,
				]
			elif metric == "OperatingIncomeLoss":
				revenue_index = by_key.get((_text(member), "Revenue", period))
				prior_revenue_index = (
					by_key.get((_text(member), "Revenue", periods[position + 1]))
					if position + 1 < len(periods)
					else None
				)
				revenue = (
					_number(result.at[revenue_index, "numeric_value"])
					if revenue_index is not None
					and _text(result.at[revenue_index, "fact_status"]) == "PASS"
					else None
				)
				prior_revenue = (
					_number(result.at[prior_revenue_index, "numeric_value"])
					if prior_revenue_index is not None
					and _text(result.at[prior_revenue_index, "fact_status"]) == "PASS"
					else None
				)
				margin, prior_margin = (
					_ratio(current, revenue),
					_ratio(previous, prior_revenue),
				)
				consolidated = _pnl_value(pnl, "OperatingIncomeLoss", period)
				prior_consolidated = (
					_pnl_value(pnl, "OperatingIncomeLoss", periods[position + 1])
					if position + 1 < len(periods)
					else None
				)
				delta = _difference(consolidated, prior_consolidated)
				contribution = (
					absolute / delta
					if absolute is not None
					and delta not in (None, 0)
					and growth is not None
					else None
				)
				result.loc[
					index,
					[
						"operating_margin",
						"operating_margin_bps_change",
						"margin_bps_change",
						"operating_income_growth_contribution",
						"operating_growth_contribution",
					],
				] = [
					margin,
					_bps(margin, prior_margin),
					_bps(margin, prior_margin),
					contribution,
					contribution,
				]
	result.attrs["periods"] = periods
	result.attrs["segment_reconciliation"] = build_segment_reconciliation(
		pnl, result, tolerance=tolerance
	)
	return result


def build_segment_reconciliation(
	pnl: pd.DataFrame,
	segments: pd.DataFrame,
	*,
	tolerance: float = DEFAULT_RECONCILIATION_TOLERANCE,
) -> pd.DataFrame:
	"""Reconcile complete disclosed members and leave residuals explicit."""
	if isinstance(pnl, pd.DataFrame) and not isinstance(segments, pd.DataFrame):
		pnl, segments = segments, pnl
	if not isinstance(pnl, pd.DataFrame) or not isinstance(segments, pd.DataFrame):
		raise TypeError("pnl and segments must be pandas DataFrames")
	if tolerance < 0 or not math.isfinite(tolerance):
		raise ValueError("tolerance must be a finite non-negative number")
	periods = [
		column
		for column in pnl.columns
		if isinstance(column, str) and ANNUAL_PERIOD_PATTERN.fullmatch(column)
	]
	rows: list[dict[str, object]] = []
	for metric, concept in (
		("Revenue", "Revenue"),
		("OperatingIncomeLoss", "OperatingIncomeLoss"),
	):
		metric_rows = segments[
			segments.get("metric", pd.Series(index=segments.index)).eq(metric)
		]
		members = sorted(
			{
				_text(value)
				for value in metric_rows.get(
					"segment_member", pd.Series(index=metric_rows.index)
				)
				if _text(value)
			}
		)
		for period in periods:
			candidates = metric_rows[
				metric_rows.get("period", pd.Series(index=metric_rows.index)).eq(period)
			]
			pass_rows = candidates[
				candidates.get("fact_status", pd.Series("PASS", index=candidates.index))
				.fillna("PASS")
				.eq("PASS")
			]
			values: dict[str, list[float]] = {}
			for _, candidate in pass_rows.iterrows():
				member = _text(candidate.get("segment_member"))
				value = _number(candidate.get("numeric_value"))
				if value is None:
					value = _number(candidate.get("value"))
				if member and value is not None:
					values.setdefault(member, []).append(value)
			complete = bool(members) and all(
				len(
					candidates[
						candidates.get(
							"segment_member", pd.Series(index=candidates.index)
						).eq(member)
					]
				)
				== 1
				and len(values.get(member, [])) == 1
				for member in members
			)
			segment_total = (
				sum(values[member][0] for member in members) if complete else None
			)
			consolidated = _pnl_value(pnl, concept, period)
			residual = (
				consolidated - segment_total
				if consolidated is not None and segment_total is not None
				else None
			)
			if not complete or consolidated is None:
				status, message = (
					"UNRESOLVED",
					"segment members or consolidated value are incomplete",
				)
			elif abs(residual or 0.0) <= tolerance:
				status, message = (
					"PASS",
					"reported segment total reconciles to consolidated total",
				)
			else:
				status, message = (
					"NOT_DIRECTLY_COMPARABLE",
					"reported residual remains; no plug or allocation applied",
				)
			units = sorted(
				{
					_text(value)
					for value in pass_rows.get("unit", pd.Series(index=pass_rows.index))
					if _text(value)
				}
			)
			if len(units) > 1:
				status, message = "UNRESOLVED", "segment units are not comparable"
			rows.append(
				{
					"metric": metric,
					"period": period,
					"reported_segment_total": segment_total,
					"segment_total": segment_total,
					"reported_consolidated_total": consolidated,
					"consolidated_total": consolidated,
					"residual": residual,
					"reconciliation_item": residual,
					"member_coverage": f"{sum(len(values.get(member, [])) == 1 for member in members)}/{len(members)}"
					if members
					else "0/0",
					"members": "; ".join(members),
					"unit": "; ".join(units),
					"status": status,
					"message": message,
					"tolerance": tolerance,
				}
			)
	return pd.DataFrame(rows)


def build_segment_enrichment(
	filing: Any,
	pnl: pd.DataFrame,
	*,
	years: int = 3,
	tolerance: float = DEFAULT_RECONCILIATION_TOLERANCE,
) -> tuple[pd.DataFrame, pd.DataFrame]:
	segments = build_segment_analytics(filing, pnl, years=years, tolerance=tolerance)
	checks = segments.attrs.get("segment_reconciliation")
	segments.attrs["segment_reconciliation"] = checks
	return segments, checks


def _save(
	ticker: str, frame: pd.DataFrame, output_root: str | Path, filename: str
) -> Path:
	path = Path(output_root) / ticker.strip().upper() / "03_output" / filename
	path.parent.mkdir(parents=True, exist_ok=True)
	frame.to_csv(path, index=False)
	return path


def save_segment_analytics(
	ticker: str, segments: pd.DataFrame, output_root: str | Path = "data"
) -> Path:
	return _save(ticker, segments, output_root, "segment_analytics.csv")


def save_segment_reconciliation(
	ticker: str, checks: pd.DataFrame, output_root: str | Path = "data"
) -> Path:
	return _save(ticker, checks, output_root, "segment_reconciliation_checks.csv")


def save_segment_reconciliation_checks(
	ticker: str, checks: pd.DataFrame, output_root: str | Path = "data"
) -> Path:
	return save_segment_reconciliation(ticker, checks, output_root)


def load_segment_analytics(
	ticker: str, output_root: str | Path = "data"
) -> pd.DataFrame:
	"""Load persisted segment rows and their non-selectable reconciliation."""
	normalized_ticker = ticker.strip().upper()
	output_directory = (
		Path(output_root) / normalized_ticker / "03_output"
	)
	analytics_path = output_directory / "segment_analytics.csv"
	if not analytics_path.is_file():
		raise FileNotFoundError(f"Segment analytics not found: {analytics_path}")
	try:
		segments = pd.read_csv(analytics_path)
	except (OSError, ValueError) as exc:
		raise SegmentAnalyticsError(
			f"could not read persisted segment analytics: {exc}"
		) from exc
	required = {
		"segment_axis",
		"segment_member",
		"segment_label",
		"metric",
		"period",
		"reported_value",
		"numeric_value",
		"fact_status",
	}
	missing = sorted(required.difference(segments.columns))
	if missing:
		raise SegmentAnalyticsError(
			"persisted segment analytics is missing columns: " + ", ".join(missing)
		)
	reconciliation_path = output_directory / "segment_reconciliation_checks.csv"
	if not reconciliation_path.is_file():
		raise SegmentAnalyticsError(
			f"persisted segment reconciliation not found: {reconciliation_path}"
		)
	try:
		checks = pd.read_csv(reconciliation_path)
	except (OSError, ValueError) as exc:
		raise SegmentAnalyticsError(
			f"could not read persisted segment reconciliation: {exc}"
		) from exc
	check_columns = {
		"metric",
		"period",
		"reported_segment_total",
		"reported_consolidated_total",
		"residual",
		"status",
	}
	if not checks.empty or len(checks.columns) > 0:
		missing_checks = sorted(check_columns.difference(checks.columns))
		if missing_checks:
			raise SegmentAnalyticsError(
				"persisted segment reconciliation is missing columns: "
				+ ", ".join(missing_checks)
			)
	segments = assign_segment_refs(segments)
	segments.attrs["periods"] = tuple(
		period
		for period in segments["period"].dropna().astype(str).drop_duplicates()
	)
	segments.attrs["segment_reconciliation"] = checks
	return segments


__all__ = [
	"DEFAULT_RECONCILIATION_TOLERANCE",
	"REPORTABLE_SEGMENT_AXIS",
	"SegmentAnalyticsError",
	"assign_segment_refs",
	"build_segment_analytics",
	"build_segment_enrichment",
	"build_segment_reconciliation",
	"extract_segment_facts",
	"load_segment_analytics",
	"save_segment_analytics",
	"save_segment_reconciliation",
	"save_segment_reconciliation_checks",
]
