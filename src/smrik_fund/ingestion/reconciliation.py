"""Deterministic source reconciliation for reported P&L subtotals."""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

from .statements import ANNUAL_PERIOD_PATTERN

# Source values are stored in dollars. One cent covers presentation/float
# rounding while keeping a one-dollar mismatch materially failed.
DEFAULT_RECONCILIATION_TOLERANCE = 0.01


def _matching_positions(
	pnl: pd.DataFrame,
	column: str,
	target: str,
) -> list[int]:
	"""Return positional row identities matching one source field."""
	if column not in pnl.columns:
		return []

	values = pnl[column].astype("string").eq(target).fillna(False)
	return [position for position, matches in enumerate(values) if matches]


def _unique_position(
	pnl: pd.DataFrame,
	name: str,
	concept: str | None = None,
) -> int | None:
	"""Find a unique source row without collapsing duplicate analytical rows."""
	if concept is not None and "standard_concept" in pnl.columns:
		matches = _matching_positions(pnl, "standard_concept", concept)
	else:
		matches = _matching_positions(pnl, "label", name)
	return matches[0] if len(matches) == 1 else None


def _row_value(pnl: pd.DataFrame, position: int, period: str) -> float | None:
	if period not in pnl.columns:
		return None

	try:
		value = float(pd.to_numeric(pnl.iloc[position][period], errors="coerce"))
	except (TypeError, ValueError):
		return None
	if pd.isna(value) or not math.isfinite(value):
		return None
	return value


def _value(
	pnl: pd.DataFrame,
	period: str,
	name: str,
	concept: str | None = None,
) -> float | None:
	position = _unique_position(pnl, name, concept=concept)
	return None if position is None else _row_value(pnl, position, period)


def _truthy(value: object) -> bool:
	if pd.isna(value):
		return False
	if isinstance(value, str):
		return value.strip().lower() in {"1", "true", "yes"}
	return bool(value)


def _is_non_statement_row(row: pd.Series) -> bool:
	return any(
		_truthy(row.get(column)) for column in ("abstract", "dimension", "is_breakdown")
	)


def _concept_variants(value: object) -> set[str]:
	if value is None or pd.isna(value):
		return set()
	text = str(value)
	unprefixed = text.removeprefix("us-gaap_")
	return {text, unprefixed}


def _operating_component_direction(row: pd.Series) -> int:
	"""Use existing statement sign metadata to identify expense vs income rows.

	EdgarTools exposes expense rows with a negative ``weight``/debit balance
	while their reported amounts remain positive.  The source amount itself is
	never changed; the direction only determines the arithmetic relationship.
	"""
	if "weight" in row.index:
		try:
			weight = float(row["weight"])
		except (TypeError, ValueError):
			weight = float("nan")
		if pd.notna(weight) and weight != 0:
			return -1 if weight < 0 else 1

	balance = str(row.get("balance", "")).strip().lower()
	if balance == "debit":
		return -1
	if balance == "credit":
		return 1

	# In the bounded fallback, rows between gross profit and operating income
	# are operating expense rows when no sign metadata is available.
	return -1


def _row_name(pnl: pd.DataFrame, position: int) -> str:
	row = pnl.iloc[position]
	for column in ("label", "standard_concept", "concept"):
		value = row.get(column)
		if value is not None and not pd.isna(value) and str(value).strip():
			return str(value)
	return f"row {position}"


def _display_names(pnl: pd.DataFrame, positions: list[int]) -> dict[int, str]:
	names: dict[int, str] = {}
	counts: dict[str, int] = {}
	for position in positions:
		name = _row_name(pnl, position)
		counts[name] = counts.get(name, 0) + 1
		names[position] = name

	for position, name in names.items():
		if counts[name] > 1:
			names[position] = f"{name} [row {position}]"
	return names


def _operating_component_positions(
	pnl: pd.DataFrame,
	gross_profit_position: int,
	operating_income_position: int,
) -> list[int]:
	"""Find operating rows from statement hierarchy, then row order as fallback."""
	excluded = {gross_profit_position, operating_income_position}
	structural_positions: list[int] = []

	if "parent_concept" in pnl.columns:
		operating_row = pnl.iloc[operating_income_position]
		expected_parents = {
			"OperatingIncomeLoss",
			"us-gaap_OperatingIncomeLoss",
			*_concept_variants(operating_row.get("concept")),
		}
		for position in range(len(pnl)):
			if position in excluded:
				continue
			row = pnl.iloc[position]
			if _is_non_statement_row(row):
				continue
			if str(row.get("parent_concept", "")) in expected_parents:
				structural_positions.append(position)

	if structural_positions:
		return structural_positions

	# The standard statement view is hierarchical and ordered.  This fallback
	# uses that existing row identity without inventing concept mappings.
	if gross_profit_position >= operating_income_position:
		return []
	return [
		position
		for position in range(gross_profit_position + 1, operating_income_position)
		if not _is_non_statement_row(pnl.iloc[position])
	]


def _operating_values(
	pnl: pd.DataFrame,
	period: str,
	positions: list[int],
) -> tuple[dict[str, float | None], list[tuple[str, int]]]:
	names = _display_names(pnl, positions)
	values = {
		names[position]: _row_value(pnl, position, period) for position in positions
	}
	return values, [
		(names[position], _operating_component_direction(pnl.iloc[position]))
		for position in positions
	]


def _passes_tolerance(difference: float, tolerance: float) -> bool:
	"""Treat only small absolute presentation-rounding differences as passing."""
	return abs(difference) <= tolerance


def _add_check(
	checks: list[dict[str, object]],
	*,
	check_id: str,
	period: str,
	subtotal: str,
	expression: str,
	values: dict[str, float | None],
	reported_value: float | None,
	calculated_value: float | None,
	tolerance: float,
) -> None:
	missing = [name for name, value in values.items() if value is None]
	if reported_value is None:
		missing.append(subtotal)
	if calculated_value is None and not missing:
		missing.append("calculated subtotal")

	if missing:
		difference = None
		status = "SKIPPED"
		message = f"SKIPPED: {expression}; missing {', '.join(missing)}"
		output_calculated_value = None
	else:
		assert calculated_value is not None
		assert reported_value is not None
		difference = calculated_value - reported_value
		status = "PASS" if _passes_tolerance(difference, tolerance) else "FAIL"
		message = f"{status}: {expression}; difference={difference:g}"
		output_calculated_value = calculated_value

	checks.append(
		{
			"check_id": check_id,
			"period": period,
			"subtotal": subtotal,
			"reported_value": reported_value,
			"calculated_value": output_calculated_value,
			"difference": difference,
			"tolerance": tolerance,
			"status": status,
			"acknowledged": False,
			"affected_lines": "; ".join([*values, subtotal]),
			"message": message,
		}
	)


def reconcile_pnl(
	pnl: pd.DataFrame,
	tolerance: float = DEFAULT_RECONCILIATION_TOLERANCE,
) -> pd.DataFrame:
	"""
	Reconcile safe reported P&L subtotal relationships without mutation.
	"""

	# 0 check if tolrance is ok
	if tolerance < 0 or not math.isfinite(tolerance):
		raise ValueError("tolerance must be a finite non-negative number")

	# build a list of periods
	periods = [
		column
		for column in pnl.columns
		if isinstance(column, str) and ANNUAL_PERIOD_PATTERN.fullmatch(column)
	]
	if not periods:
		raise ValueError("analytical P&L must contain annual FY periods")

	checks: list[dict[str, object]] = []
	for period in periods:
		revenue = _value(pnl, period, "Revenue", concept="Revenue")
		cost_of_revenue = _value(
			pnl,
			period,
			"Cost of revenue",
			concept="CostOfGoodsAndServicesSold",
		)
		gross_profit = _value(
			pnl,
			period,
			"Gross profit",
			concept="GrossProfit",
		)
		gross_profit_calculated = (
			revenue - cost_of_revenue
			if revenue is not None and cost_of_revenue is not None
			else None
		)
		_add_check(
			checks,
			check_id="gross_profit",
			period=period,
			subtotal="Gross profit",
			expression="Revenue - Cost of revenue = Gross profit",
			values={"Revenue": revenue, "Cost of revenue": cost_of_revenue},
			reported_value=gross_profit,
			calculated_value=gross_profit_calculated,
			tolerance=tolerance,
		)

		gross_profit_position = _unique_position(
			pnl,
			"Gross profit",
			concept="GrossProfit",
		)
		operating_income_position = _unique_position(
			pnl,
			"Operating income",
			concept="OperatingIncomeLoss",
		)
		operating_components: dict[str, float | None]
		operating_terms: list[tuple[str, int]]
		if gross_profit_position is None or operating_income_position is None:
			operating_components = {"operating expense rows": None}
			operating_terms = []
		else:
			positions = _operating_component_positions(
				pnl,
				gross_profit_position,
				operating_income_position,
			)
			operating_components, operating_terms = _operating_values(
				pnl,
				period,
				positions,
			)
			if not operating_components:
				operating_components = {"operating expense rows": None}

		operating_income = _value(
			pnl,
			period,
			"Operating income",
			concept="OperatingIncomeLoss",
		)
		if gross_profit is None or any(
			value is None for value in operating_components.values()
		):
			operating_income_calculated = None
		else:
			operating_income_calculated = gross_profit
			for (name, direction), value in zip(
				operating_terms,
				operating_components.values(),
				strict=True,
			):
				assert value is not None
				operating_income_calculated += direction * value

		expression = "Gross profit"
		for name, direction in operating_terms:
			expression += f" {'+' if direction > 0 else '-'} {name}"
		expression += " = Operating income"
		_add_check(
			checks,
			check_id="operating_income",
			period=period,
			subtotal="Operating income",
			expression=expression,
			values={"Gross profit": gross_profit, **operating_components},
			reported_value=operating_income,
			calculated_value=operating_income_calculated,
			tolerance=tolerance,
		)

		other_income = _value(
			pnl,
			period,
			"Other income (expense), net",
			concept="NonoperatingIncomeExpense",
		)
		pretax_income = _value(
			pnl,
			period,
			"Income before income taxes",
			concept="PretaxIncomeLoss",
		)
		pretax_income_calculated = (
			operating_income + other_income
			if operating_income is not None and other_income is not None
			else None
		)
		_add_check(
			checks,
			check_id="pretax_income",
			period=period,
			subtotal="Income before income taxes",
			expression=(
				"Operating income + Other income (expense), net "
				"= Income before income taxes"
			),
			values={
				"Operating income": operating_income,
				"Other income (expense), net": other_income,
			},
			reported_value=pretax_income,
			calculated_value=pretax_income_calculated,
			tolerance=tolerance,
		)

		income_taxes = _value(
			pnl,
			period,
			"Provision for income taxes",
			concept="IncomeTaxes",
		)
		net_income = _value(pnl, period, "Net income", concept="NetIncome")
		net_income_calculated = (
			pretax_income - income_taxes
			if pretax_income is not None and income_taxes is not None
			else None
		)
		_add_check(
			checks,
			check_id="net_income",
			period=period,
			subtotal="Net income",
			expression=(
				"Income before income taxes - Provision for income taxes = Net income"
			),
			values={
				"Income before income taxes": pretax_income,
				"Provision for income taxes": income_taxes,
			},
			reported_value=net_income,
			calculated_value=net_income_calculated,
			tolerance=tolerance,
		)

	return pd.DataFrame(checks)


def reconcile_analytical_pnl(
	analytical_pnl: pd.DataFrame,
	tolerance: float = DEFAULT_RECONCILIATION_TOLERANCE,
) -> pd.DataFrame:
	"""Public descriptive alias for :func:`reconcile_pnl`."""
	return reconcile_pnl(analytical_pnl, tolerance=tolerance)


def save_reconciliation_checks(
	ticker: str,
	checks: pd.DataFrame,
	output_root: str | Path = "data",
) -> Path:
	"""Save reconciliation checks under the existing output-stage convention."""
	output_path = (
		Path(output_root)
		/ ticker.strip().upper()
		/ "03_output"
		/ "reconciliation_checks.csv"
	)
	output_path.parent.mkdir(parents=True, exist_ok=True)
	checks.to_csv(output_path, index=False)
	return output_path
