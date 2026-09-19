"""Project EdgarTools standard statement frames into history observations."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from datetime import date
from typing import Any

import pandas as pd

_PERIOD_FIELDS = (
	"period_type", "period_start", "period_end", "period_instant", "unit",
	"currency", "scale_factor", "dimensions",
)
_SOURCE_FIELDS = ("source", "accession", "filing_date", "form_type", "source_locator")
_DATE_IN_COLUMN = re.compile(r"\b20\d{2}-\d{2}-\d{2}\b")
_NATIVE_METADATA_COLUMNS = {
	"concept", "standard_concept", "label", "unit", "unit_ref", "currency", "scale_factor", "scale", "point_in_time",
	"period_type", "period_start", "period_end", "period_instant", "level",
	"abstract", "dimension", "is_breakdown", "dimension_axis", "dimension_member",
	"dimension_member_label", "dimension_label", "balance", "weight",
	"preferred_sign", "preferred_label", "parent_concept", "parent_abstract_concept",
	"calculation_parent",
}


def _checks(*rows: tuple[str, str, str, str]) -> pd.DataFrame:
	return pd.DataFrame(rows, columns=["check_id", "status", "reason", "detail"])


def _cell(value: object) -> str:
	if value is None:
		return ""
	try:
		if pd.isna(value):
			return ""
	except (TypeError, ValueError):
		pass
	return str(value)


def _date_value(value: object) -> date | None:
	if not _cell(value):
		return None
	parsed = pd.to_datetime(value, errors="coerce")
	return None if pd.isna(parsed) else parsed.date()


def _number(value: object) -> float | None:
	try:
		number = float(value)
	except (TypeError, ValueError):
		return None
	return number if math.isfinite(number) else None


def _row_dimensions(row: pd.Series, fallback: object) -> object:
	if "dimensions" in row.index:
		return row["dimensions"]
	dimensions = {
		name: row[name]
		for name in ("dimension_axis", "dimension_member", "dimension_member_label", "dimension_label")
		if name in row.index and _cell(row[name])
	}
	return dimensions if dimensions else fallback


def _excluded(
	frame: pd.DataFrame,
	statement: str,
	period_column: object,
	reason: str,
	detail: str,
) -> pd.DataFrame:
	column = str(period_column)
	if frame.empty:
		frame = pd.DataFrame([{"concept": "", "label": ""}])
	result = pd.DataFrame({
		"statement": statement,
		"period_column": column,
		"concept": frame.get("concept", pd.Series("", index=frame.index)),
		"label": frame.get("label", pd.Series("", index=frame.index)),
		"numeric_value": frame.get(column, pd.Series(pd.NA, index=frame.index)),
		"reason": reason,
		"detail": detail,
	}, index=frame.index)
	return result.reset_index(drop=True)


def _excluded_row(
	row: pd.Series, statement: str, period_column: str, reason: str, detail: str
) -> pd.DataFrame:
	record = row.to_dict()
	record.update({
		"statement": statement,
		"period_column": period_column,
		"concept": row.get("concept", ""),
		"label": row.get("label", ""),
		"numeric_value": row.get(period_column, pd.NA),
		"reason": reason,
		"detail": detail,
	})
	return pd.DataFrame([record])


def _empty_excluded() -> pd.DataFrame:
	return _excluded(pd.DataFrame(), "", "", "", "").iloc[0:0]


def _native_period_columns(frame: pd.DataFrame) -> list[str]:
	"""Detect value columns from the installed standard statement layout."""
	return [
		str(column)
		for column in frame.columns
		if column not in _NATIVE_METADATA_COLUMNS and _DATE_IN_COLUMN.search(str(column))
	]


def _period_metadata(
	metadata: pd.DataFrame | Mapping[str, Mapping[str, object]],
) -> pd.DataFrame:
	if isinstance(metadata, pd.DataFrame):
		return metadata.copy()
	if not isinstance(metadata, Mapping):
		return pd.DataFrame()
	rows = []
	for period_column, values in metadata.items():
		if not isinstance(values, Mapping):
			return pd.DataFrame()
		row = dict(values)
		row.setdefault("period_column", period_column)
		rows.append(row)
	return pd.DataFrame(rows)


def _native_dataframe(statement: object) -> tuple[pd.DataFrame | None, str | None]:
	if isinstance(statement, pd.DataFrame):
		return statement.copy(), None
	to_dataframe = getattr(statement, "to_dataframe", None)
	if not callable(to_dataframe):
		return None, "statement must be a pandas DataFrame or EdgarTools Statement"
	try:
		try:
			frame = to_dataframe(
				view="standard", standard=True, include_unit=True,
				include_point_in_time=True, presentation=False,
			)
		except TypeError as legacy_error:
			# EdgarTools 5.45+ removed ``view`` while retaining the standard
			# DataFrame controls. Keep the older call first for the accepted
			# offline seam, then use the installed native signature.
			try:
				frame = to_dataframe(
					standard=True, include_unit=True,
					include_point_in_time=True, presentation=False,
				)
			except Exception as current_error:
				return None, f"native statement extraction failed: {current_error}; legacy: {legacy_error}"
	except Exception as exc:  # native failures are explicit unavailable results
		return None, f"native statement extraction failed: {exc}"
	if not isinstance(frame, pd.DataFrame):
		return None, "native statement did not return a pandas DataFrame"
	return frame.copy(), None


def _source_value(period: Mapping[str, object], filing: Mapping[str, object], field: str) -> object:
	value = period.get(field)
	if _cell(value):
		return value
	if field == "filing_date":
		return filing.get("filing_date", filing.get("publication_date", filing.get("publication_timestamp")))
	return filing.get(field)


def _resolve_period(
	row: Mapping[str, object], provided: set[str], filing: Mapping[str, object]
) -> tuple[dict[str, object] | None, str, str]:
	missing = [field for field in _PERIOD_FIELDS if field not in provided]
	if missing:
		return None, "missing_native_metadata", ",".join(missing)
	period_type = _cell(row.get("period_type")).strip().lower()
	start, end, instant = (_date_value(row.get(field)) for field in ("period_start", "period_end", "period_instant"))
	if period_type not in {"duration", "instant"}:
		return None, "invalid_period_metadata", "period_type must be duration or instant"
	if period_type == "duration":
		if start is None or end is None:
			return None, "invalid_period_metadata", "duration requires period_start and period_end"
		if start > end:
			return None, "invalid_period_metadata", "duration start is after end"
		if instant is not None:
			return None, "invalid_period_metadata", "duration cannot also provide period_instant"
	else:
		if instant is None:
			return None, "invalid_period_metadata", "instant requires period_instant"
		if start is not None or end is not None:
			return None, "invalid_period_metadata", "instant cannot also provide duration dates"

	source = {field: _source_value(row, filing, field) for field in _SOURCE_FIELDS}
	missing_source = [field for field, value in source.items() if not _cell(value)]
	if missing_source:
		return None, "missing_native_metadata", ",".join(missing_source)
	unit, currency, dimensions, scale = (row.get(field) for field in ("unit", "currency", "dimensions", "scale_factor"))
	if not _cell(unit) or not _cell(currency) or not _cell(dimensions):
		return None, "missing_native_metadata", "unit, currency, and dimensions are required"
	if _number(scale) is None or _number(scale) <= 0:
		return None, "missing_native_scale", "scale_factor must be explicit and positive"
	publication = row.get("publication_date")
	if not _cell(publication):
		publication = filing.get("publication_date", source["filing_date"])
	return {
		"period_type": period_type,
		"period_start": row.get("period_start"),
		"period_end": row.get("period_end"),
		"period_instant": row.get("period_instant"),
		"fiscal_year": row.get("fiscal_year"),
		"fiscal_period": row.get("fiscal_period"),
		"unit": unit,
		"unit_ref": row.get("unit_ref"),
		"currency": currency,
		"scale_factor": scale,
		"dimensions": dimensions,
		"statement_role": row.get("statement_role"),
		**source,
		"publication_date": publication,
	}, "", ""


def _final_metadata_error(row: Mapping[str, object]) -> tuple[str, str] | None:
	missing = [field for field in ("unit", "currency", "dimensions") if not _cell(row.get(field))]
	if missing:
		return "missing_native_metadata", ",".join(missing)
	scale = _number(row.get("scale_factor"))
	return None if scale is not None and scale > 0 else ("missing_native_scale", "scale_factor must be explicit and positive")


def _period_identity_error(period: Mapping[str, object], period_column: str) -> str | None:
	match = _DATE_IN_COLUMN.search(period_column)
	if match:
		period_type = _cell(period.get("period_type")).strip().lower()
		field = "period_instant" if period_type == "instant" else "period_end"
		observed = _date_value(period.get(field))
		if observed is not None and observed.isoformat() != match.group(0):
			return f"{field} does not match native period identity"
	for field in ("native_period", "period_identity"):
		identity = _cell(period.get(field))
		if identity and identity != period_column:
			return f"{field} does not match period_column"
	return None


def _project_one(
	statement_frame: object,
	statement: str,
	filing_metadata: Mapping[str, object],
	period_metadata: pd.DataFrame | Mapping[str, Mapping[str, object]],
) -> dict[str, Any]:
	frame, error = _native_dataframe(statement_frame)
	if frame is None:
		return {"history": pd.DataFrame(), "excluded": _excluded(pd.DataFrame(), statement, "", "native_statement_unavailable", error or "unknown native extraction error"), "alternatives": pd.DataFrame(), "checks": _checks(("native_interface", "FAIL", "native_statement_unavailable", error or ""))}
	metadata = _period_metadata(period_metadata)
	if "period_column" not in metadata.columns:
		return {"history": pd.DataFrame(), "excluded": _excluded(frame, statement, "", "missing_native_metadata", "period_column"), "alternatives": metadata, "checks": _checks(("native_metadata", "FAIL", "missing_native_metadata", "period_column"))}
	period_names = metadata["period_column"].map(str)
	duplicates = metadata.loc[period_names.duplicated(keep=False)].copy()
	if not duplicates.empty:
		columns = duplicates["period_column"].unique()
		return {"history": pd.DataFrame(), "excluded": pd.concat([_excluded(frame, statement, column, "ambiguous_period_metadata", "more than one metadata row") for column in columns], ignore_index=True), "alternatives": duplicates, "checks": _checks(("native_metadata", "FAIL", "ambiguous_period_metadata", "explicit basis required"))}

	actual_periods = _native_period_columns(frame)
	if not actual_periods:
		actual_periods = [column for column in period_names if column in frame.columns]
	checks: list[tuple[str, str, str, str]] = [("native_interface", "PASS", "standard_statement_dataframe", f"{len(frame)} rows")]
	excluded_parts: list[pd.DataFrame] = []
	for column in actual_periods:
		if column not in set(period_names):
			excluded_parts.append(_excluded(frame, statement, column, "missing_native_metadata", "native value-period column has no explicit metadata"))
			checks.append(("native_metadata", "FAIL", "missing_native_metadata", column))

	history_rows: list[dict[str, object]] = []
	orphans: list[pd.DataFrame] = []
	provided = set(metadata.columns)
	for _, period_row in metadata.iterrows():
		column = str(period_row["period_column"])
		if column not in frame.columns:
			checks.append(("native_metadata", "FAIL", "period_column_not_in_statement", column))
			orphans.append(metadata.loc[period_names.eq(column)])
			continue
		identity_error = _period_identity_error(period_row, column)
		if identity_error:
			excluded_parts.append(_excluded(frame, statement, column, "invalid_period_metadata", identity_error))
			checks.append(("native_metadata", "FAIL", "invalid_period_metadata", identity_error))
			continue
		resolved, reason, detail = _resolve_period(period_row.to_dict(), provided, filing_metadata)
		if resolved is None:
			excluded_parts.append(_excluded(frame, statement, column, reason, detail))
			checks.append(("native_metadata", "FAIL", reason, f"{column}: {detail}"))
			continue
		for _, native_row in frame.iterrows():
			projected = native_row.drop(labels=actual_periods, errors="ignore").to_dict()
			projected.update(resolved)
			projected.update({"statement": statement, "statement_scope": statement, "period_column": column, "numeric_value": native_row[column]})
			for field in ("unit", "unit_ref", "currency", "scale_factor"):
				if field in native_row.index:
					projected[field] = native_row[field]
			projected["dimensions"] = _row_dimensions(native_row, resolved["dimensions"])
			if "source_locator" in native_row.index and _cell(native_row["source_locator"]):
				projected["source_locator"] = native_row["source_locator"]
			metadata_error = _final_metadata_error(projected)
			if metadata_error:
				reason, detail = metadata_error
				excluded_parts.append(_excluded_row(native_row, statement, column, reason, detail))
				checks.append(("native_row_metadata", "FAIL", reason, f"{column}: {detail}"))
				continue
			history_rows.append(projected)
	checks.append(("native_projection", "PASS" if history_rows else "NOT_TESTED", "native_values_projected_without_transformation" if history_rows else "unavailable", str(len(history_rows))))
	return {
		"history": pd.DataFrame(history_rows),
		"excluded": pd.concat(excluded_parts, ignore_index=True) if excluded_parts else _empty_excluded(),
		"alternatives": pd.concat(orphans, ignore_index=True) if orphans else pd.DataFrame(),
		"checks": _checks(*checks),
	}


def native_statements_to_history(
	statements: Mapping[str, object],
	*,
	statement_metadata: Mapping[str, Mapping[str, object]],
	period_metadata: Mapping[str, pd.DataFrame | Mapping[str, Mapping[str, object]]],
) -> dict[str, Any]:
	"""Project native standard statements into rows accepted by ``history``."""
	if not isinstance(statements, Mapping) or not statements:
		raise ValueError("statements must be a non-empty mapping")
	history_parts: list[pd.DataFrame] = []
	excluded_parts: list[pd.DataFrame] = []
	alternative_parts: list[pd.DataFrame] = []
	checks: list[tuple[str, str, str, str]] = []
	for statement, native in statements.items():
		filing, periods = statement_metadata.get(statement), period_metadata.get(statement)
		if not isinstance(filing, Mapping) or periods is None:
			frame, _ = _native_dataframe(native)
			excluded_parts.append(_excluded(frame if frame is not None else pd.DataFrame(), statement, "", "missing_native_metadata", "statement_metadata and period_metadata"))
			checks.append((f"native_metadata:{statement}", "FAIL", "missing_native_metadata", "statement_metadata and period_metadata"))
			continue
		result = _project_one(native, statement, filing, periods)
		for key, target in (("history", history_parts), ("excluded", excluded_parts), ("alternatives", alternative_parts)):
			if not result[key].empty:
				target.append(result[key])
		checks.extend((f"{statement}:{row.check_id}", row.status, row.reason, row.detail) for row in result["checks"].itertuples(index=False))
	return {
		"history": pd.concat(history_parts, ignore_index=True) if history_parts else pd.DataFrame(),
		"excluded": pd.concat(excluded_parts, ignore_index=True) if excluded_parts else _empty_excluded(),
		"alternatives": pd.concat(alternative_parts, ignore_index=True) if alternative_parts else pd.DataFrame(),
		"checks": _checks(*checks),
	}
