"""Free historical diagnostics and sensitivities of the actual workbook model.

Exploratory ranges are not confidence intervals. Python selects stresses and
ranks calculated effects; the existing spreadsheet engine remains DCF authority.
"""

import argparse
import copy
import math
from pathlib import Path
from statistics import pstdev

from smrik_fund.analysis_budget import content_hash


def ratio(numerator, denominator):
	if numerator is None or denominator is None or denominator == 0:
		return None
	return numerator / denominator


def historical_ratios(model):
	rows, previous = [], None
	for period in model.get("annual_history", {}).get("periods", []):
		v = period["values"]
		revenue = v.get("revenue")
		nwc = None
		if all(
			v.get(k) is not None
			for k in ("operating_current_assets", "operating_current_liabilities")
		):
			nwc = v["operating_current_assets"] - v["operating_current_liabilities"]
		growth = ratio(revenue, previous)
		rows.append(
			{
				"period": period["label"],
				"start": period["start"],
				"end": period["end"],
				"revenue": revenue,
				"growth": None if growth is None else growth - 1,
				"ebit_margin": ratio(v.get("ebit"), revenue),
				"cogs_ratio": ratio(v.get("cost_cogs"), revenue),
				"sga_ratio": ratio(v.get("cost_sga"), revenue),
				"research_ratio": ratio(v.get("cost_research"), revenue),
				"opex_ratio": ratio(v.get("operating_costs"), revenue),
				"sbc_ratio": ratio(v.get("sbc"), revenue),
				"sbc_to_cogs": ratio(v.get("sbc"), v.get("cost_cogs")),
				"capex_ratio": ratio(
					-v["capex_cash"] if v.get("capex_cash") is not None else None,
					revenue,
				),
				"nwc_ratio": ratio(nwc, revenue),
				"tax_rate": ratio(v.get("tax_expense"), v.get("pretax")),
				"cfo_margin": ratio(v.get("cfo"), revenue),
			}
		)
		previous = revenue
	return rows


def sensitivity_design(model, history):
	"""Observed annual range, widened by a stated minimum stress; bound controls."""
	c = model["controls"]
	h = model["history"]
	revenue = h["revenue"]["ttm"]
	drivers = []

	def add(key, area, base, metric, step, bounds, inputs, method):
		values = [r[metric] for r in history if metric and r.get(metric) is not None]
		lo = max(bounds[0], min([base - step, *values]))
		hi = min(bounds[1], max([base + step, *values]))
		drivers.append(
			{
				"id": key,
				"area": area,
				"base": base,
				"low": lo,
				"high": hi,
				"historical_values": values,
				"historical_observations": [
					{
						"period": r["period"],
						"start": r["start"],
						"end": r["end"],
						"value": r.get(metric),
					}
					for r in history
				]
				if metric
				else [],
				"historical_stddev": pstdev(values) if len(values) > 1 else None,
				"range_basis": "Annual observed range plus minimum stress; clipped to stated bounds. Not a confidence interval.",
				"minimum_stress": step,
				"bounds": list(bounds),
				"method": method,
				"scenarios": [
					{"id": f"{key}:{side}", "inputs": inputs(value)}
					for side, value in (("low", lo), ("high", hi))
				],
			}
		)

	for key in ("products_growth", "services_growth"):
		if any(
			model["segments"][
				"Products" if key == "products_growth" else "Services"
			].values()
		):
			add(
				key,
				"revenue",
				c[key],
				"growth",
				0.02,
				model["control_bounds"][key],
				lambda x, k=key: {k: x},
				"Constant annual growth; consolidated historical growth is a proxy for category uncertainty.",
			)
	components = model.get("operating_costs", {}).get("components", [])
	for component in components:
		key = component["control"]
		add(
			key,
			"operating_costs",
			c[key],
			key,
			0.01,
			model["control_bounds"][key],
			lambda x, k=key: {k: x},
			"Forecast expense/revenue including embedded D&A and SBC; other components fixed.",
		)
	if not components:
		base = sum(h[k]["ttm"] for k in ("cost_of_sales", "research", "sga")) / revenue
		add(
			"opex_ratio",
			"operating_costs",
			base,
			"opex_ratio",
			0.01,
			(0, 2),
			lambda x: {"stress_opex": x - base},
			"Forecast aggregate expense stress; detailed cost split unavailable.",
		)
	sbc = h["sbc"]["ttm"] / revenue
	add(
		"sbc_ratio",
		"sbc_equity",
		sbc,
		"sbc_ratio",
		0.005,
		(0, 1),
		lambda x: {"stress_sbc": x - sbc},
		"Incremental SBC expense AND cash/equity addback; SBC stays expensed in UFCF. Do not combine with an overlapping cost-ratio stress. No share-dilution model.",
	)
	capex = -h["capex_cash"]["ttm"] / revenue
	add(
		"capex_ratio",
		"ppe_capex",
		capex,
		"capex_ratio",
		0.01,
		(0, 1),
		lambda x: {"stress_capex": x - capex},
		"Forecast cash PP&E additions; linked depreciation and terminal capital recalculate.",
	)
	o = model["opening"]
	nwc = (
		sum(
			o[k]
			for k in (
				"receivables",
				"vendor_receivables",
				"inventory",
				"other_current_assets",
			)
		)
		- sum(o[k] for k in ("intangibles_current", "payables", "deferred_revenue"))
	) / revenue
	add(
		"nwc_ratio",
		"working_capital",
		nwc,
		"nwc_ratio",
		0.02,
		(-1, 1),
		lambda x: {"stress_nwc": x - nwc},
		"Additional forecast operating current assets as a ratio of annualized sales; opening balances unchanged. Historical aggregate composition may differ.",
	)
	for key, area, metric, step in (
		("forecast_tax_rate", "taxes", "tax_rate", 0.05),
		("ppe_life", "ppe_capex", None, 2),
		("intangible_life", "intangibles", None, 2),
		("intangible_additions_ratio", "intangibles", None, 0.01),
		("risk_free", "dcf_terminal", None, 0.01),
		("equity_premium", "dcf_terminal", None, 0.01),
		("beta", "dcf_terminal", None, 0.2),
		("debt_rate", "debt_interest", None, 0.01),
		("terminal_growth", "dcf_terminal", None, 0.01),
	):
		add(
			key,
			area,
			c[key],
			metric,
			step,
			model["control_bounds"][key],
			lambda x, k=key: {k: x},
			"One supported forecast control varied; all others held fixed.",
		)
	return drivers


def rank_drivers(drivers, snapshot, market_price):
	base = snapshot["per_share_value"]
	results = {s["id"]: s for s in snapshot["diagnostics"]}
	ranked = []
	for driver in drivers:
		outcomes = [results[s["id"]] for s in driver["scenarios"]]
		values = [s["per_share_value"] for s in outcomes]
		valid = [v for v in values if v is not None and math.isfinite(v)]
		impact = max((abs(v - base) for v in valid), default=None)
		ranked.append(
			{
				**driver,
				"outcomes": outcomes,
				"status": "MEASURED"
				if len(valid) == 2
				else "BLOCKED_STRESS_REQUIRES_RESEARCH",
				"max_absolute_change_per_share": impact,
				"impact_fraction_of_market_price": None
				if impact is None
				else impact / market_price,
				"market_price_bracketed": len(valid) == 2
				and min(valid) <= market_price <= max(valid),
			}
		)
	ranked.sort(
		key=lambda d: (
			d["status"] != "MEASURED",
			d["impact_fraction_of_market_price"]
			if d["impact_fraction_of_market_price"] is not None
			else -1,
		),
		reverse=True,
	)
	return [{"rank": i + 1, **d} for i, d in enumerate(ranked)]


def run_diagnostics(model, output, market):
	from smrik_fund.company_research import compact_snapshot
	from smrik_fund.company_run import build, fingerprint, save

	output = Path(output)
	history = historical_ratios(model)
	drivers = sensitivity_design(model, history)
	stressed = copy.deepcopy(model)
	stressed["diagnostic_scenarios"] = [s for d in drivers for s in d["scenarios"]]
	snapshot = build(stressed, output / "baseline")
	ranked = rank_drivers(drivers, snapshot, market["price"])
	result = {
		"case": model["case"],
		"case_hash": model["case_hash"],
		"model_hash": content_hash(model),
		"status": "PROVISIONAL_DETERMINISTIC_DIAGNOSTICS",
		"market": market,
		"units": "USD/share for valuation; decimal ratios; source statements USD millions",
		"baseline": {
			k: snapshot[k]
			for k in ("per_share_value", "wacc", "enterprise_value", "equity_value")
		},
		"controls": model["controls"],
		"calculated": compact_snapshot(
			{k: v for k, v in snapshot.items() if k != "diagnostics"}
		),
		"history": history,
		"ranked_drivers": ranked,
		"gaps": [
			{
				"id": "gap_leases",
				"area": "leases",
				"finding": "No independent lease reclassification sensitivity; assess consistency and materiality.",
			},
			{
				"id": "gap_nonoperating",
				"area": "nonoperating",
				"finding": "Discrete earnings items and nonoperating claims require filing evidence; no inferred normalization.",
			},
			{
				"id": "gap_capital_structure",
				"area": "debt_interest",
				"finding": "Constant refinanced debt and weighted-average share proxy; refinancing, dilution and dates need research.",
			},
		],
		"limitations": [
			"Ranking uses the maximum one-driver USD/share change divided by market price, avoiding instability near zero baseline equity value.",
			"Ranges contain historical observations and stated minimum stresses; no probabilities, covariance or additive interpretation.",
			"Price bracket is a reverse-DCF indication only: no unique implied driver or monotonicity is asserted.",
			"SBC, capex, aggregate expense and working-capital stresses diagnose forecast effects; they are not separately supported agent controls. A needed unimplemented treatment must be escalated.",
			*model.get("limitations", []),
			*model.get("annual_history", {}).get("issues", []),
		],
		"artifacts": {
			f"baseline/{name}": fingerprint(output / "baseline" / name)
			for name in ("model.json", "snapshot.json", f"{model['case']}.xlsx")
		},
	}
	save(output / "diagnostics.json", result)
	lines = [
		f"# {model['case']} — research priorities",
		"",
		"Free provisional diagnostics, before any LLM judgment. Ratios are decimal in JSON; values below are USD/share.",
		"",
		f"Baseline: ${snapshot['per_share_value']:.2f}; market: ${market['price']:.2f}. See diagnostics.json for quote timestamp, source hash, controls and range construction.",
		"",
		"| Rank | Driver | Low / base / high input | Value at low / high | Max change / quote | Status |",
		"|---:|---|---|---|---:|---|",
	]
	for d in ranked:
		values = " / ".join(
			"blocked"
			if x["per_share_value"] is None
			else f"${x['per_share_value']:.2f}"
			for x in d["outcomes"]
		)
		impact = d["impact_fraction_of_market_price"]
		lines.append(
			f"| {d['rank']} | {d['id']} | {d['low']:.4f} / {d['base']:.4f} / {d['high']:.4f} | {values} | {'unknown' if impact is None else f'{impact:.1%}'} | {d['status']} |"
		)
	lines += [
		"",
		"Ranges are exploratory, not confidence intervals. Effects overlap and must not be added. Blocked stresses and unsupported mechanisms require research.",
		"",
		*[f"- {g['finding']}" for g in result["gaps"]],
	]
	path = output / "DIAGNOSTICS.md"
	with path.open("x", encoding="utf-8") as stream:
		stream.write("\n".join(lines) + "\n")
	return result


def main():
	from smrik_fund.company_model import POLICY_CONTROL_BOUNDS
	from smrik_fund.company_research import market_quote
	from smrik_fund.portable_model import prepare_model
	from smrik_fund.workbook_template import compile_template

	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--case-dir", required=True, type=Path)
	parser.add_argument("--output-dir", required=True, type=Path)
	args = parser.parse_args()
	model = prepare_model(args.case_dir)
	model["workbook_template"] = compile_template()
	market = market_quote(model["case"], args.output_dir)
	model["controls"].update(
		share_price_proxy=market["price"],
		forecast_tax_rate=model["normalized_tax_rate"],
	)
	model["control_bounds"].update(POLICY_CONTROL_BOUNDS)
	run_diagnostics(model, args.output_dir, market)
	print(args.output_dir / "DIAGNOSTICS.md")


if __name__ == "__main__":
	main()
