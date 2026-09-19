"""Checked expense composition; no residual cost line or assumed missing zero."""

import math

COST_CONCEPTS = {
	"cogs": ("CostOfGoodsAndServicesSold", "CostOfRevenue"),
	"sga": ("SellingGeneralAndAdministrativeExpense",),
	"research": ("ResearchAndDevelopmentExpense",),
}
COST_LABELS = {"cogs": "Cost of revenue", "sga": "SG&A", "research": "R&D"}
COST_CONTROL_BOUNDS = {f"{key}_ratio": (0, 2) for key in COST_CONCEPTS}


def reconcile_costs(revenue, ebit, reported, gross_profit=None):
	"""Accept positive expense magnitudes only when they exhaust revenue - EBIT.

	Raw signs remain in the input. The returned multipliers make the presentation
	conversion explicit. Missing, nonfinite or unreconciled components reject the
	breakdown, rather than turning the difference into a forecast assumption.
	"""
	if "cogs" not in reported or not all(
		isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
		for v in (revenue, ebit, *reported.values())
	):
		return None
	costs = {k: abs(v) for k, v in reported.items()}
	if revenue <= 0 or abs(revenue - sum(costs.values()) - ebit) > 0.001:
		return None
	if gross_profit is not None and (
		not math.isfinite(gross_profit)
		or abs(revenue - costs["cogs"] - gross_profit) > 0.001
	):
		return None
	return {
		"values": costs,
		"sign_multipliers": {k: -1 if v < 0 else 1 for k, v in reported.items()},
		"difference": revenue - sum(costs.values()) - ebit,
	}


def operating_costs(flow, read_history, *, has_interim=True):
	"""read_history returns None for an absent category; a bad disclosure raises."""
	reported = {}
	try:
		for key, concepts in COST_CONCEPTS.items():
			values = read_history(concepts)
			if values is not None:
				reported[key] = values
		gross_profit = read_history(("GrossProfit",))
	except ValueError as error:
		return {"status": "aggregate", "reason": str(error), "components": []}
	bridges = {}
	periods = ("annual", "current_ytd", "prior_ytd") if has_interim else ("annual",)
	for period in periods:
		bridge = reconcile_costs(
			flow["revenue"][period],
			flow["ebit"][period],
			{k: v[period] for k, v in reported.items()},
			gross_profit[period] if gross_profit else None,
		)
		if bridge is None:
			return {
				"status": "aggregate",
				"components": [],
				"reason": f"{period}: disclosed COGS/SG&A/R&D do not fully reconcile to revenue minus EBIT or reported gross profit; retain total expenses without a residual forecast.",
			}
		bridges[period] = bridge
	components, normalized = [], {}
	for key in reported:
		values = {
			p: bridges[p]["values"][key] if p in bridges else 0
			for p in ("annual", "current_ytd", "prior_ytd")
		}
		values["ttm"] = values["annual"] + values["current_ytd"] - values["prior_ytd"]
		if values["ttm"] < 0:
			return {
				"status": "aggregate",
				"reason": "Negative TTM expense component requires review",
				"components": [],
			}
		normalized[f"cost_{key}"] = values
		components.append(
			{
				"key": key,
				"label": COST_LABELS[key],
				"control": f"{key}_ratio",
				"ttm_ratio": values["ttm"] / flow["revenue"]["ttm"],
			}
		)
	flow.update(normalized)
	return {
		"status": "detailed",
		"components": components,
		"bridges": bridges,
		"reported": {
			key: {p: raw[p] for p in periods} for key, raw in reported.items()
		},
		"reason": "Each FY/YTD reconciles to reported EBIT. Expense magnitudes are presentation conversions; signed facts remain in History/Evidence. Absent categories are not asserted to be zero. Forecast ratios start at TTM and include embedded D&A/SBC; total D&A is replaced once below EBITDA. No allocation of D&A between COGS and SG&A is claimed.",
	}
