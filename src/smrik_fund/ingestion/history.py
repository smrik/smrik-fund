"""Date-aware, source-preserving history mechanics for the P2 package.

Inputs are raw-fact-shaped EdgarTools frames. Source rows stay untouched;
derived values are returned in separate frames with explicit checks.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from datetime import date, timedelta
from typing import Any

import pandas as pd


class HistoryInputError(ValueError):
	"""Raised for malformed API arguments, never for financial ambiguity."""


_PERIOD_FIELDS = ("period_type", "period_start", "period_end", "period_instant")
_SERIES_FIELDS = (
	"statement", "concept", "standard_concept", "canonical_key", "period_type",
	"period_start", "period_end", "period_instant", "fiscal_year", "fiscal_period",
	"unit", "unit_ref", "currency", "scale_factor", "scale", "dimensions",
	"statement_role",
)
_SOURCE_FIELDS = ("source", "accession", "filing_date", "form_type", "source_locator")
_NON_ADDITIVE_MARKERS = (
	"earningspershare", "eps", "pershare", "margin", "growth", "ratio",
	"percent", "percentage", "weightedaverage", "sharesaverage",
	"sharesoutstanding", "sharecount",
)


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


def _number(value: object) -> float | None:
	try:
		number = float(value)
	except (TypeError, ValueError):
		return None
	return number if pd.notna(number) and math.isfinite(number) else None


def _date_value(value: object) -> date | None:
	if not _cell(value):
		return None
	parsed = pd.to_datetime(value, errors="coerce")
	return None if pd.isna(parsed) else parsed.date()


def _period_missing(frame: pd.DataFrame) -> list[str]:
	return [name for name in _PERIOD_FIELDS if name not in frame.columns]


def _series_fields(frame: pd.DataFrame) -> list[str]:
	return [name for name in _SERIES_FIELDS if name in frame.columns]


def _source_key(row: pd.Series) -> tuple[str, ...]:
	fields = [name for name in _SOURCE_FIELDS if name in row.index]
	# A locator is normally unique for every fact. Accession identifies the
	# filing source, while locator remains available in source_refs output.
	if _cell(row.get("accession")):
		fields = [name for name in fields if name != "source_locator"]
	return tuple(_cell(row.get(name)) for name in fields)


def _value_column(frame: pd.DataFrame) -> str | None:
	return next((name for name in ("numeric_value", "value") if name in frame), None)


def _unit_column(frame: pd.DataFrame) -> str | None:
	return next((name for name in ("unit", "unit_ref") if name in frame), None)


def _has_non_additive_marker(normalized: str, marker: str) -> bool:
	if marker != "ratio":
		return marker in normalized
	for match in re.finditer(marker, normalized):
		before = match.start() > 0 and normalized[match.start() - 1].isalpha()
		after = match.end() < len(normalized) and normalized[match.end()].isalpha()
		if not (before and after):
			return True
	return False


def _is_additive_monetary(
	frame: pd.DataFrame, concept: str, expected_currency: str = "USD"
) -> tuple[bool, str]:
	texts = [concept]
	texts.extend(
		_cell(value)
		for column in ("concept", "standard_concept", "canonical_key", "label")
		if column in frame
		for value in frame[column]
	)
	for text in texts:
		normalized = "".join(ch for ch in text.lower() if ch.isalnum())
		if any(_has_non_additive_marker(normalized, marker) for marker in _NON_ADDITIVE_MARKERS):
			return False, "non_additive_concept"
	unit_column = _unit_column(frame)
	if unit_column is None or "currency" not in frame:
		return False, "missing_currency_or_unit_metadata"
	currency = {_cell(value).strip().upper() for value in frame["currency"]}
	if not currency or "" in currency:
		return False, "missing_currency_or_unit_metadata"
	expected = expected_currency.strip().upper()
	if currency != {expected}:
		return False, "currency_mismatch"
	units = {_cell(value).strip().lower() for value in frame[unit_column]}
	if not units or "" in units:
		return False, "missing_unit_metadata"
	unit_names = {
		"USD": {"usd", "u_usd", "iso4217:usd", "iso4217-usd", "us dollar"},
	}.get(expected)
	if unit_names is None or not units <= unit_names:
		return False, "unknown_monetary_unit"
	scale_column = "scale_factor" if "scale_factor" in frame else "scale" if "scale" in frame else None
	if scale_column is None or any(
		(_number(value) is None or _number(value) <= 0) for value in frame[scale_column]
	):
		return False, "missing_scale_metadata"
	return True, ""


def _select_sources(
	frame: pd.DataFrame, *, selection_basis: str | None = None
) -> tuple[pd.DataFrame, pd.DataFrame, list[tuple[str, str, str, str]]]:
	"""Select one filing source per series/period and retain alternatives."""
	fields = _series_fields(frame)
	if not fields:
		return frame.iloc[0:0].copy(), frame.copy(), [
			("source_selection", "FAIL", "missing_source_identity", "no period/series fields")
		]
	selected: list[int] = []
	alternatives: list[int] = []
	checks: list[tuple[str, str, str, str]] = []
	for _, group in frame.groupby(fields, dropna=False, sort=False):
		sources: dict[tuple[str, ...], list[int]] = {}
		for index, row in group.iterrows():
			sources.setdefault(_source_key(row), []).append(index)
		if len(sources) == 1:
			selected.extend(group.index)
			continue
		chosen: tuple[str, ...] | None = None
		if selection_basis:
			basis = selection_basis.strip()
			if basis.startswith("accession:"):
				accession = basis.split(":", 1)[1].strip()
				matches = [key for key in sources if accession and accession in key]
				if len(matches) == 1:
					chosen = matches[0]
			elif basis == "latest_filing":
				dated: list[tuple[date, tuple[str, ...]]] = []
				for key, indices in sources.items():
					published = max(
						(_date_value(value) for value in group.loc[indices].get("filing_date", [])),
						default=None,
					)
					if published is not None:
						dated.append((published, key))
				if dated:
					latest = max(item[0] for item in dated)
					matches = [key for published, key in dated if published == latest]
					if len(matches) == 1:
						chosen = matches[0]
			if chosen is None:
				checks.append(("source_selection", "FAIL", "selection_basis_unresolved", basis))
		else:
			checks.append((
				"source_selection", "FAIL", "ambiguous_source_selection",
				"multiple filing/source references; explicit basis required",
			))
		if chosen is None:
			alternatives.extend(group.index)
		else:
			selected.extend(sources[chosen])
			alternatives.extend(index for key, indices in sources.items() if key != chosen for index in indices)
			checks.append(("source_selection", "PASS", "basis_applied", str(chosen)))
	if any(status == "FAIL" for _, status, _, _ in checks):
		return frame.iloc[0:0].copy(), frame.loc[alternatives].copy(), checks
	return frame.loc[selected].copy(), frame.loc[alternatives].copy(), checks


def qualify_source_references(
	facts: pd.DataFrame,
	information_cutoff: str | date,
	*,
	selection_basis: str | None = None,
) -> dict[str, pd.DataFrame]:
	"""Qualify references published by cutoff; never silently choose conflicts."""
	if not isinstance(facts, pd.DataFrame):
		raise HistoryInputError("facts must be a pandas DataFrame")
	cutoff = _date_value(information_cutoff)
	if cutoff is None:
		raise HistoryInputError("information_cutoff must be a valid date")
	publication = "filing_date" if "filing_date" in facts else "publication_timestamp"
	if publication not in facts:
		return {
			"qualified": facts.iloc[0:0].copy(), "alternatives": facts.copy(),
			"excluded_after_cutoff": facts.iloc[0:0].copy(),
			"checks": _checks(("publication_cutoff", "FAIL", "missing_publication_metadata", "filing_date/publication_timestamp")),
		}
	dates = facts[publication].map(_date_value)
	known = dates.notna()
	eligible = facts.loc[known & dates.le(cutoff)].copy()
	excluded = facts.loc[known & dates.gt(cutoff)].copy()
	unknown = facts.loc[~known].copy()
	selected, alternatives, source_checks = _select_sources(
		eligible, selection_basis=selection_basis
	)
	checks = [(
		"publication_cutoff", "PASS" if unknown.empty else "FAIL",
		"qualified_by_publication_date" if unknown.empty else "unknown_publication_date",
		f"cutoff={cutoff.isoformat()}, excluded={len(excluded)}",
	)]
	checks.extend(source_checks)
	if not unknown.empty:
		alternatives = pd.concat([alternatives, unknown])
	return {
		"qualified": selected, "alternatives": alternatives,
		"excluded_after_cutoff": excluded, "checks": _checks(*checks),
	}


def preserve_unique_actual_periods(
	facts: pd.DataFrame, *, statement: str | None = None, concept: str | None = None
) -> dict[str, pd.DataFrame]:
	"""Return reported facts with unique actual period identities preserved."""
	if not isinstance(facts, pd.DataFrame):
		raise HistoryInputError("facts must be a pandas DataFrame")
	missing = _period_missing(facts)
	if missing:
		return {"periods": facts.iloc[0:0].copy(), "alternatives": facts.copy(), "checks": _checks(("period_identity", "FAIL", "missing_period_metadata", ",".join(missing)))}
	frame = facts.copy()
	if statement is not None and "statement" in frame:
		frame = frame.loc[frame["statement"].eq(statement)]
	if concept is not None:
		columns = [name for name in ("concept", "standard_concept", "canonical_key") if name in frame]
		frame = frame.loc[frame[columns].eq(concept).any(axis=1)] if columns else frame.iloc[0:0]
	if "is_derived" in frame:
		frame = frame.loc[~frame["is_derived"].map(lambda value: _cell(value).lower() in {"true", "1"})]
	value_column = _value_column(frame)
	if value_column is None:
		return {"periods": frame.iloc[0:0].copy(), "alternatives": frame, "checks": _checks(("period_identity", "FAIL", "missing_value_metadata", "numeric_value/value"))}
	selected: list[int] = []
	duplicates: list[int] = []
	for _, group in frame.groupby(_series_fields(frame), dropna=False, sort=False):
		if len({_cell(value) for value in group[value_column]}) > 1:
			return {"periods": frame.iloc[0:0].copy(), "alternatives": frame, "checks": _checks(("period_identity", "FAIL", "conflicting_period_values", "same series/period has different values"))}
		selected.append(group.index[0])
		duplicates.extend(group.index[1:])
	return {"periods": frame.loc[selected].copy(), "alternatives": frame.loc[duplicates].copy(), "checks": _checks(("period_identity", "PASS", "unique_actual_periods", f"{len(selected)} periods"))}


def _ttm_result(frame: pd.DataFrame, refs: pd.DataFrame, checks: list[tuple[str, str, str, str]]) -> dict[str, Any]:
	return {"history": frame, "source_refs": refs, "checks": _checks(*checks)}


def construct_ttm(
	facts: pd.DataFrame, *, concept: str, full_fy_end: str | date,
	current_ytd_start: str | date, current_ytd_end: str | date,
	prior_ytd_start: str | date, prior_ytd_end: str | date,
	information_cutoff: str | date | None = None, selection_basis: str | None = None,
	expected_currency: str = "USD",
) -> dict[str, Any]:
	"""Construct full FY + current YTD - prior comparable YTD."""
	if not isinstance(facts, pd.DataFrame):
		raise HistoryInputError("facts must be a pandas DataFrame")
	dates = {name: _date_value(value) for name, value in {
		"full_fy_end": full_fy_end, "current_ytd_start": current_ytd_start,
		"current_ytd_end": current_ytd_end, "prior_ytd_start": prior_ytd_start,
		"prior_ytd_end": prior_ytd_end,
	}.items()}
	if any(value is None for value in dates.values()):
		raise HistoryInputError("all TTM component dates must be valid")
	frame = facts.copy()
	checks: list[tuple[str, str, str, str]] = []
	if information_cutoff is not None:
		qualified = qualify_source_references(frame, information_cutoff, selection_basis=selection_basis)
		frame, refs = qualified["qualified"], qualified["alternatives"]
		checks.extend(qualified["checks"].itertuples(index=False, name=None))
	else:
		frame, refs, source_checks = _select_sources(frame, selection_basis=selection_basis)
		checks.extend(source_checks)
	if "is_derived" in frame:
		frame = frame.loc[~frame["is_derived"].map(lambda value: _cell(value).lower() in {"true", "1"})]
	missing = _period_missing(frame)
	value_column = _value_column(frame)
	concept_columns = [name for name in ("concept", "standard_concept", "canonical_key") if name in frame]
	if missing or value_column is None or not concept_columns:
		reason = "missing_period_metadata" if missing else "missing_value_or_concept_metadata"
		return _ttm_result(frame.iloc[0:0].copy(), frame, checks + [("ttm_components", "FAIL", reason, ",".join(missing) or "numeric_value/value/concept")])
	frame = frame.loc[frame[concept_columns].eq(concept).any(axis=1)].copy()
	if frame.empty:
		return _ttm_result(frame, frame, checks + [("ttm_components", "FAIL", "concept_not_found", concept)])
	if "period_type" not in frame:
		return _ttm_result(frame.iloc[0:0].copy(), frame, checks + [("ttm_components", "FAIL", "missing_period_type", "duration required")])
	full = frame.loc[frame["period_type"].eq("duration") & frame.get("fiscal_period", pd.Series("", index=frame.index)).astype("string").str.upper().eq("FY") & frame["period_end"].map(_date_value).eq(dates["full_fy_end"])]
	current = frame.loc[frame["period_type"].eq("duration") & frame["period_start"].map(_date_value).eq(dates["current_ytd_start"]) & frame["period_end"].map(_date_value).eq(dates["current_ytd_end"])]
	prior = frame.loc[frame["period_type"].eq("duration") & frame["period_start"].map(_date_value).eq(dates["prior_ytd_start"]) & frame["period_end"].map(_date_value).eq(dates["prior_ytd_end"])]
	parts = {"full_fy": full, "current_ytd": current, "prior_ytd": prior}
	if any(part.empty for part in parts.values()):
		reason = "instant_fact_rejected" if frame["period_type"].eq("instant").any() else "missing_component_period"
		return _ttm_result(frame.iloc[0:0].copy(), frame, checks + [("ttm_components", "FAIL", reason, ",".join(name for name, part in parts.items() if part.empty))])
	if any(len(part) != 1 for part in parts.values()):
		return _ttm_result(frame.iloc[0:0].copy(), frame, checks + [("ttm_components", "FAIL", "ambiguous_component_period", str({name: len(part) for name, part in parts.items()}))])
	full_start = _date_value(full.iloc[0]["period_start"])
	full_end = _date_value(full.iloc[0]["period_end"])
	if full_start is None or full_end is None or (full_end - full_start).days + 1 not in {365, 366}:
		return _ttm_result(frame.iloc[0:0].copy(), frame, checks + [("ttm_period_alignment", "FAIL", "invalid_fy_span", "full FY must cover one July-to-June year")])
	if dates["prior_ytd_start"] != full_start:
		return _ttm_result(frame.iloc[0:0].copy(), frame, checks + [("ttm_period_alignment", "FAIL", "prior_ytd_not_anchored", "prior YTD must start at full FY start")])
	if dates["prior_ytd_end"] >= full_end:
		return _ttm_result(frame.iloc[0:0].copy(), frame, checks + [("ttm_period_alignment", "FAIL", "prior_ytd_not_contained", "prior YTD must end inside full FY")])
	if dates["current_ytd_start"] != full_end + timedelta(days=1) or dates["current_ytd_end"] <= dates["current_ytd_start"]:
		return _ttm_result(frame.iloc[0:0].copy(), frame, checks + [("ttm_period_alignment", "FAIL", "current_ytd_not_after_full_fy", "actual component dates do not form a fiscal sequence")])
	if (dates["current_ytd_end"].month, dates["current_ytd_end"].day) != (dates["prior_ytd_end"].month, dates["prior_ytd_end"].day) or dates["current_ytd_end"].year != dates["prior_ytd_end"].year + 1:
		return _ttm_result(frame.iloc[0:0].copy(), frame, checks + [("ttm_period_alignment", "FAIL", "comparable_cutoff_mismatch", "current/prior YTD fiscal cutoffs differ")])
	if abs((dates["current_ytd_end"] - dates["current_ytd_start"]).days - (dates["prior_ytd_end"] - dates["prior_ytd_start"]).days) > 1:
		return _ttm_result(frame.iloc[0:0].copy(), frame, checks + [("ttm_period_alignment", "FAIL", "ytd_duration_mismatch", "current/prior lengths differ")])
	if (dates["current_ytd_end"] - dates["prior_ytd_end"]).days not in {365, 366}:
		return _ttm_result(frame.iloc[0:0].copy(), frame, checks + [("ttm_period_alignment", "FAIL", "not_trailing_year", "derived period is not one trailing year")])
	component_frame = pd.concat(parts.values(), ignore_index=True)
	additive, reason = _is_additive_monetary(component_frame, concept, expected_currency)
	if not additive:
		return _ttm_result(frame.iloc[0:0].copy(), component_frame, checks + [("ttm_additivity", "FAIL", reason, concept)])
	compatibility = [name for name in ("unit", "unit_ref", "currency", "scale_factor", "scale", "dimensions", "statement_role", "period_type") if name in component_frame]
	if any(component_frame[name].map(_cell).nunique(dropna=False) != 1 for name in compatibility):
		return _ttm_result(frame.iloc[0:0].copy(), component_frame, checks + [("ttm_compatibility", "FAIL", "unit_scope_or_period_mismatch", ",".join(compatibility))])
	numbers = [_number(part.iloc[0][value_column]) for part in parts.values()]
	ttm_value = None if any(number is None for number in numbers) else numbers[0] + numbers[1] - numbers[2]
	checks.append(("ttm_compatibility", "PASS", "compatible_additive_flows", "FY + current YTD - prior YTD"))
	checks.append(("ttm_value", "PASS" if ttm_value is not None else "NOT_TESTED", "computed_without_normalization" if ttm_value is not None else "missing_component_value", str(ttm_value)))
	result = component_frame.iloc[[0]].copy()
	result[value_column] = ttm_value
	result["period_start"] = (dates["prior_ytd_end"] + timedelta(days=1)).isoformat()
	result["period_end"] = dates["current_ytd_end"].isoformat()
	result["period_kind"] = "derived"
	result["is_derived"] = True
	result["derivation"] = "full_fy + current_ytd - prior_comparable_ytd"
	result["source_references"] = [[_source_key(row) for _, row in component_frame.iterrows()]]
	return _ttm_result(result, component_frame, checks)


def reconcile_quarterly_ttm(
	facts: pd.DataFrame, *, concept: str, quarter_ends: Iterable[str | date],
	ttm_value: float | None = None,
) -> dict[str, Any]:
	"""Independently sum four contiguous, non-overlapping quarterly flows."""
	if not isinstance(facts, pd.DataFrame):
		raise HistoryInputError("facts must be a pandas DataFrame")
	ends = [_date_value(value) for value in quarter_ends]
	if len(ends) != 4 or any(value is None for value in ends):
		raise HistoryInputError("quarter_ends must contain four valid dates")
	frame = facts.copy()
	missing = _period_missing(frame)
	value_column = _value_column(frame)
	if missing or value_column is None:
		return {"quarterly": frame.iloc[0:0].copy(), "value": None, "checks": _checks(("quarter_components", "FAIL", "missing_period_or_value_metadata", ",".join(missing) or "numeric_value/value"))}
	concept_columns = [name for name in ("concept", "standard_concept", "canonical_key") if name in frame]
	frame = frame.loc[frame[concept_columns].eq(concept).any(axis=1)] if concept_columns else frame.iloc[0:0]
	quarters = frame.loc[frame["period_type"].eq("duration") & frame["period_end"].map(_date_value).isin(ends)].copy()
	checks: list[tuple[str, str, str, str]] = []
	if len(quarters) != 4:
		return {"quarterly": quarters, "value": None, "checks": _checks(("quarter_components", "FAIL", "quarter_count_or_duplicate", str(len(quarters))))}
	quarters = quarters.sort_values("period_start")
	starts = [_date_value(value) for value in quarters["period_start"]]
	actual_ends = [_date_value(value) for value in quarters["period_end"]]
	if any(start is None or end is None for start, end in zip(starts, actual_ends, strict=True)) or any(starts[i] != actual_ends[i - 1] + timedelta(days=1) for i in range(1, 4)):
		return {"quarterly": quarters, "value": None, "checks": _checks(("quarter_components", "FAIL", "quarters_overlap_or_gap", "periods are not contiguous"))}
	additive, reason = _is_additive_monetary(quarters, concept)
	if not additive:
		return {"quarterly": quarters, "value": None, "checks": _checks(("quarter_additivity", "FAIL", reason, concept))}
	numbers = [_number(value) for value in quarters[value_column]]
	value = None if any(number is None for number in numbers) else sum(numbers)
	checks.append(("quarter_independent_sum", "PASS" if value is not None else "NOT_TESTED", "four_non_overlapping_quarters", str(value)))
	if ttm_value is not None and value is not None:
		difference = value - ttm_value
		checks.append(("ttm_reconciliation", "PASS" if difference == 0 else "FAIL", "four_quarter_sum_matches_ttm" if difference == 0 else "four_quarter_sum_differs_from_ttm", str(difference)))
	return {"quarterly": quarters, "value": value, "checks": _checks(*checks)}


def latest_balance_sheet(
	facts: pd.DataFrame, *, concept: str | None = None,
	selection_basis: str | None = None, information_cutoff: str | date | None = None,
	statement_scope: str = "balance_sheet",
) -> dict[str, pd.DataFrame]:
	"""Return the latest included instant balance-sheet snapshot."""
	if not isinstance(facts, pd.DataFrame):
		raise HistoryInputError("facts must be a pandas DataFrame")
	frame = facts.copy()
	checks: list[tuple[str, str, str, str]] = []
	if "statement" not in frame or not statement_scope:
		return {
			"balance_sheet": frame.iloc[0:0].copy(), "alternatives": frame,
			"checks": _checks(("balance_sheet_scope", "FAIL", "missing_balance_sheet_scope", "explicit statement scope required")),
		}
	frame = frame.loc[frame["statement"].eq(statement_scope)].copy()
	if frame.empty:
		return {
			"balance_sheet": frame, "alternatives": facts.copy(),
			"checks": _checks(("balance_sheet_scope", "FAIL", "balance_sheet_scope_not_found", statement_scope)),
		}
	if information_cutoff is not None:
		qualified = qualify_source_references(frame, information_cutoff, selection_basis=selection_basis)
		frame, alternatives = qualified["qualified"], qualified["alternatives"]
		checks.extend(qualified["checks"].itertuples(index=False, name=None))
	else:
		frame, alternatives, source_checks = _select_sources(frame, selection_basis=selection_basis)
		checks.extend(source_checks)
	missing = _period_missing(frame)
	if missing:
		return {"balance_sheet": frame.iloc[0:0].copy(), "alternatives": frame, "checks": _checks(*(checks + [("balance_sheet_period", "FAIL", "missing_period_metadata", ",".join(missing))]))}
	if "period_type" not in frame:
		return {"balance_sheet": frame.iloc[0:0].copy(), "alternatives": frame, "checks": _checks(*(checks + [("balance_sheet_period", "FAIL", "missing_period_type", "instant required")]))}
	frame = frame.loc[frame["period_type"].eq("instant")].copy()
	if concept is not None:
		columns = [name for name in ("concept", "standard_concept", "canonical_key") if name in frame]
		frame = frame.loc[frame[columns].eq(concept).any(axis=1)] if columns else frame.iloc[0:0]
	instants = frame["period_instant"].map(_date_value) if not frame.empty else pd.Series(dtype="object")
	if frame.empty or instants.dropna().empty:
		return {"balance_sheet": frame.iloc[0:0].copy(), "alternatives": frame, "checks": _checks(*(checks + [("balance_sheet_period", "FAIL", "instant_fact_not_found", concept or "balance_sheet")]))}
	latest = max(value for value in instants if value is not None)
	selected = frame.loc[instants.eq(latest)].copy()
	checks.append(("balance_sheet_period", "PASS", "latest_instant_snapshot", latest.isoformat()))
	return {"balance_sheet": selected, "alternatives": frame.loc[~instants.eq(latest)].copy(), "checks": _checks(*checks)}


build_ttm = construct_ttm
reconcile_four_quarters = reconcile_quarterly_ttm
