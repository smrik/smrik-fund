"""Deterministic adjustment-history resolution and P&L application."""

from __future__ import annotations

import math

import pandas as pd

from .statements import ANNUAL_PERIOD_PATTERN, prepare_pnl

# Schema version 2 stores item_amount + item_effect_on_line and the derived
# signed line_delta. Version 1 rows (positive magnitude, always subtracted)
# cannot prove direction and fail closed.
ADJUSTMENT_SCHEMA_VERSION = 2

_ITEM_EFFECT_LINE_DELTAS = {
	# The item made the reported line larger, so removing it lowers the line.
	"increased_line": -1.0,
	# The item made the reported line smaller, so removing it raises the line.
	"decreased_line": 1.0,
}

_HISTORY_COLUMNS = {"adjustment_id", "version", "status"}
_ADJUSTMENT_COLUMNS = {"target_line", "period", "item_amount", "item_effect_on_line"}


def derive_line_delta(
	item_amount: object,
	item_effect_on_line: object,
) -> float | None:
	"""Derive the signed line delta from two independent supported facts.

	``adjusted_value = reported_value + line_delta``. Either input being
	unsupported leaves the delta underived; nothing is guessed.
	"""
	if item_amount is None or item_effect_on_line is None:
		return None
	try:
		if pd.isna(item_amount) or pd.isna(item_effect_on_line):
			return None
	except (TypeError, ValueError):
		pass
	try:
		amount = float(item_amount)
	except (TypeError, ValueError):
		return None
	if not math.isfinite(amount) or amount <= 0:
		return None
	effect = _ITEM_EFFECT_LINE_DELTAS.get(str(item_effect_on_line))
	return None if effect is None else effect * amount
_DERIVED_CONCEPTS = {
    "GrossProfit",
    "OperatingIncomeLoss",
    "PretaxIncomeLoss",
    "NetIncome",
}
_DERIVED_LABELS = {
    "Gross profit",
    "Operating income",
    "Income before income taxes",
    "Net income",
}


def resolve_current_adjustments(history: pd.DataFrame) -> pd.DataFrame:
    """Select the latest approved version for each adjustment ID.

    Non-approved workflow rows remain history only: they do not remove an
    earlier approved version from the current applied set. A later approved
    version replaces that ID's earlier approved version rather than stacking.
    """
    if not isinstance(history, pd.DataFrame):
        raise TypeError("history must be a pandas DataFrame")
    _require_columns(history, _HISTORY_COLUMNS, "adjustment history")
    if history.empty:
        return history.copy(deep=True)
    if history["adjustment_id"].isna().any():
        raise ValueError("adjustment_id cannot be missing")

    versions = pd.to_numeric(history["version"], errors="coerce")
    if versions.isna().any() or (versions < 1).any() or (versions % 1 != 0).any():
        raise ValueError("version must be an integer greater than or equal to 1")
    if history.duplicated(["adjustment_id", "version"]).any():
        raise ValueError("each adjustment_id/version pair must be unique")

    approved = history.loc[history["status"].eq("approved")].copy()
    if approved.empty:
        return approved.reset_index(drop=True)

    latest = (
        approved.assign(_version_number=versions.loc[approved.index])
        .sort_values(["adjustment_id", "_version_number"], kind="mergesort")
        .groupby("adjustment_id", sort=True, dropna=False)
        .tail(1)
        .drop(columns="_version_number")
        .sort_values("adjustment_id", kind="mergesort")
        .reset_index(drop=True)
    )
    return latest


def apply_adjustments(
    pnl: pd.DataFrame,
    adjustments: pd.DataFrame,
) -> pd.DataFrame:
    """Return an adjusted P&L without mutating the reported input frame."""
    if not isinstance(pnl, pd.DataFrame):
        raise TypeError("pnl must be a pandas DataFrame")
    periods = [
        column
        for column in pnl.columns
        if isinstance(column, str) and ANNUAL_PERIOD_PATTERN.fullmatch(column)
    ]
    if not periods:
        raise ValueError("analytical P&L must contain annual FY periods")

    current = _current_approved_adjustments(adjustments)
    result = pnl.copy(deep=True)
    if not current.empty:
        totals = (
            current.groupby(
                ["target_line", "period"], sort=True, as_index=False, dropna=False
            )["_line_delta_number"]
            .sum()
            .rename(columns={"_line_delta_number": "line_delta"})
        )
        for adjustment in totals.itertuples(index=False):
            if adjustment.period not in periods:
                raise ValueError(
                    f"adjustment period {adjustment.period!r} is not present in P&L"
                )
            line_index = _find_line_index(result, adjustment.target_line)
            if _is_derived_line(result, line_index):
                raise ValueError(
                    "adjustments must target source lines, not derived subtotals"
                )
            reported = _number(result, line_index, adjustment.period)
            if reported is None:
                raise ValueError(
                    f"cannot adjust missing reported value for "
                    f"{adjustment.target_line!r} / {adjustment.period!r}"
                )
            # adjusted = reported + signed line delta
            result.at[line_index, adjustment.period] = (
                reported + float(adjustment.line_delta)
            )

    _recalculate_subtotals(result, periods)
    return prepare_pnl(result, years=len(periods))


def _require_columns(frame: pd.DataFrame, required: set[str], name: str) -> None:
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"{name} is missing columns: {', '.join(sorted(missing))}")


def _current_approved_adjustments(adjustments: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(adjustments, pd.DataFrame):
        raise TypeError("adjustments must be a pandas DataFrame")
    if _HISTORY_COLUMNS.issubset(adjustments.columns):
        current = resolve_current_adjustments(adjustments)
    else:
        if "status" in adjustments and not adjustments["status"].eq("approved").all():
            raise ValueError("adjustments must contain approved rows only")
        current = adjustments.copy(deep=True)

    if current.empty:
        current["_line_delta_number"] = pd.Series(dtype="float64")
        return current
    try:
        _require_columns(current, _ADJUSTMENT_COLUMNS, "adjustments")
    except ValueError as exc:
        raise ValueError(
            f"{exc}; approved adjustments require item_amount and "
            "item_effect_on_line so the direction is provable; legacy rows "
            "without them fail closed"
        ) from exc
    if current["target_line"].isna().any() or current["period"].isna().any():
        raise ValueError("target_line and period cannot be missing")
    deltas = [
        derive_line_delta(row.item_amount, row.item_effect_on_line)
        for row in current.itertuples(index=False)
    ]
    if any(delta is None for delta in deltas):
        raise ValueError(
            "approved adjustments require a positive item_amount and an "
            "item_effect_on_line that together derive a line_delta; legacy "
            "rows without a provable direction fail closed"
        )
    current = current.copy(deep=True)
    current["_line_delta_number"] = pd.Series(deltas, index=current.index, dtype="float64")
    return current


def _find_line_index(pnl: pd.DataFrame, target_line: object) -> object:
    if not isinstance(target_line, str) or not target_line.strip():
        raise ValueError("target_line must be a non-empty string")
    for column in ("label", "standard_concept"):
        if column not in pnl:
            continue
        matches = pnl.index[pnl[column].eq(target_line).fillna(False)]
        if len(matches) > 1:
            raise ValueError(f"target line {target_line!r} is ambiguous")
        if len(matches) == 1:
            return matches[0]
    raise KeyError(f"target line {target_line!r} was not found in P&L")


def _is_derived_line(pnl: pd.DataFrame, line_index: object) -> bool:
    label = pnl.at[line_index, "label"] if "label" in pnl else None
    concept = (
        pnl.at[line_index, "standard_concept"]
        if "standard_concept" in pnl
        else None
    )
    return (
        isinstance(label, str)
        and label in _DERIVED_LABELS
        or isinstance(concept, str)
        and concept in _DERIVED_CONCEPTS
    )


def _unique_index(pnl: pd.DataFrame, column: str, value: str) -> object | None:
    if column not in pnl:
        return None
    matches = pnl.index[pnl[column].eq(value).fillna(False)]
    return matches[0] if len(matches) == 1 else None


def _number(pnl: pd.DataFrame, line_index: object | None, period: str) -> float | None:
    if line_index is None:
        return None
    value = pd.to_numeric(
        pd.Series([pnl.at[line_index, period]]), errors="coerce"
    ).iloc[0]
    return None if pd.isna(value) else float(value)


def _concept_value(pnl: pd.DataFrame, concept: str, period: str) -> float | None:
    return _number(pnl, _unique_index(pnl, "standard_concept", concept), period)


def _label_value(pnl: pd.DataFrame, label: str, period: str) -> float | None:
    return _number(pnl, _unique_index(pnl, "label", label), period)


def _set_concept(
    pnl: pd.DataFrame,
    concept: str,
    period: str,
    value: float | None,
) -> None:
    line_index = _unique_index(pnl, "standard_concept", concept)
    if line_index is not None and value is not None:
        pnl.at[line_index, period] = value


def _subtract(first: float | None, *others: float | None) -> float | None:
    if first is None:
        return None
    result = first
    for value in others:
        if value is None:
            return None
        result -= value
    return result


def _add(*values: float | None) -> float | None:
    result = 0.0
    for value in values:
        if value is None:
            return None
        result += value
    return result


def _recalculate_subtotals(pnl: pd.DataFrame, periods: list[str]) -> None:
    for period in periods:
        revenue = _concept_value(pnl, "Revenue", period)
        cost = _concept_value(pnl, "CostOfGoodsAndServicesSold", period)
        gross_profit = _subtract(revenue, cost)
        _set_concept(pnl, "GrossProfit", period, gross_profit)

        operating_income = _subtract(
            gross_profit,
            _concept_value(pnl, "ResearchAndDevelopmentExpenses", period),
            _label_value(pnl, "Sales and marketing", period),
            _label_value(pnl, "General and administrative", period),
        )
        _set_concept(pnl, "OperatingIncomeLoss", period, operating_income)

        pretax_income = _add(
            operating_income,
            _concept_value(pnl, "NonoperatingIncomeExpense", period),
        )
        _set_concept(pnl, "PretaxIncomeLoss", period, pretax_income)
        _set_concept(
            pnl,
            "NetIncome",
            period,
            _subtract(
                pretax_income,
                _concept_value(pnl, "IncomeTaxes", period),
            ),
        )
