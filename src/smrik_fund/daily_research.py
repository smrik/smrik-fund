"""Deterministic research triage and self-contained daily reports, without LLMs."""

import csv
import hashlib
import html
import json
import statistics
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from smrik_fund.analysis_budget import content_hash
from smrik_fund.market_screen import (
	basic_reasons,
	number,
	quote_metrics,
	ratio,
	symbol,
	value_seed,
	write_json,
)


def method_for(info: dict) -> str:
	industry = str(info.get("industry", "")).lower()
	if "reit" in industry:
		return "REIT: AFFO/NAV review required"
	if "banks" in industry:
		return "Bank: earnings/book/ROE"
	if "insurance" in industry:
		return "Insurer: earnings/book/ROE"
	if info.get("sector") == "Financial Services":
		return "Other financial: specialist review required"
	if not info.get("sector"):
		return "Unclassified: review required"
	if (number(info.get("trailingEps")) or 0) <= 0:
		return "Loss/missing earnings: runway/unit economics review required"
	return "Operating company: earnings/cash flow"


def peer_references(snapshot: dict, now: datetime) -> dict:
	groups = {}
	for quote in snapshot["quotes"]:
		if basic_reasons(quote, snapshot["filters"], now):
			continue
		if quote.get("financialCurrency") not in (None, "USD"):
			continue
		sector = snapshot["sectors"].get(quote["symbol"], "Unknown")
		groups.setdefault(sector, []).append((quote["symbol"], quote_metrics(quote)))
	return groups


def median_peer(groups: dict, sector: str, ticker: str, key: str, ciks: dict) -> tuple:
	values, issuers = [], set()
	identity = ciks.get(ticker, ticker)
	for name, metrics in groups.get(sector, []):
		issuer = ciks.get(name, name)
		value = metrics[key]
		if issuer != identity and issuer not in issuers and value is not None and 0 < value <= (100 if key == "pe" else 20):
			values.append(value)
			issuers.add(issuer)
	return (statistics.median(values) if len(values) >= 5 else None), len(values)


def analyze(quote: dict, snapshot: dict, peers: dict, now: datetime) -> dict:
	ticker = quote["symbol"]
	detail = snapshot["details"].get(ticker)
	info = detail["data"] if detail and not detail["error"] else {}
	sector = info.get("sector", snapshot["sectors"].get(ticker, "Unknown"))
	method = method_for(info)
	noncommon = any(reason.startswith("Non-common") for reason in basic_reasons(info if info else quote, snapshot["filters"], now))
	if noncommon:
		method = "Non-common security: specialist instrument valuation required"
	financial = method.startswith(("Bank:", "Insurer:"))
	operating = method.startswith("Operating company:")
	metrics = quote_metrics(info if info else quote)
	price = number(info.get("regularMarketPrice", quote.get("regularMarketPrice")))
	metrics.update({
		"price": price, "market_cap": number(info.get("marketCap", quote.get("marketCap"))),
		"forward_pe_vendor": number(info.get("forwardPE")),
		"roe": number(info.get("returnOnEquity")), "revenue_growth": number(info.get("revenueGrowth")),
		"operating_margin": number(info.get("operatingMargins")),
		"net_margin_vendor": number(info.get("profitMargins")),
		"eps_ttm": number(info.get("trailingEps")), "book_per_share": number(info.get("bookValue")),
	})
	same_currency = info.get("financialCurrency") == info.get("currency") == "USD"
	if noncommon or (info and not same_currency):
		for key in ("pe", "pb", "eps_ttm", "book_per_share", "forward_pe_vendor"):
			metrics[key] = None
	metrics["vendor_fcf_yield"] = ratio(info.get("freeCashflow"), info.get("marketCap")) if operating and same_currency else None
	metrics["ev_ebitda"] = ratio(info.get("enterpriseValue"), info.get("ebitda"), positive_numerator=True) if operating and same_currency else None
	debt, cash, ebitda = (number(info.get(key)) for key in ("totalDebt", "totalCash", "ebitda"))
	metrics["net_debt_ebitda"] = ratio(debt - cash, ebitda) if operating and same_currency and debt is not None and cash is not None else None
	for key in ("pe", "pb"):
		median, count = median_peer(peers, sector, ticker, key, snapshot.get("ciks", {}))
		metrics[f"sector_{key}_median"], metrics[f"sector_{key}_n"] = median, count
		metrics[f"{key}_discount"] = 1 - metrics[key] / median if metrics[key] is not None and median else None
	flags = basic_reasons(info if info else quote, snapshot["filters"], now)
	if not detail:
		flags.append("Fundamentals not fetched: outside value seed or enrichment limit")
	elif detail["error"]:
		flags.append(f"Fundamentals fetch failed: {detail['error']}")
	if not same_currency:
		flags.append("Financial currency missing or differs from USD quote; no cross-currency valuation")
	quarter = number(info.get("mostRecentQuarter"))
	if quarter is None or not now.timestamp() - 200 * 86400 <= quarter <= now.timestamp():
		flags.append("Latest financial period missing, future-dated or older than 200 days")
	if not (financial or operating):
		flags.append(method)
	if ticker.replace(".", "-") not in snapshot.get("ciks", {}):
		flags.append("SEC issuer identity unavailable; verify listing/security manually")
	if metrics["pe"] is not None and metrics["pe"] < 3:
		flags.append("P/E below 3: verify one-off earnings and vendor data")
	if operating and metrics["net_margin_vendor"] is not None and metrics["operating_margin"] is not None and metrics["net_margin_vendor"] - metrics["operating_margin"] > .15:
		flags.append("Vendor net margin exceeds operating margin by >15pp: reconcile mixed periods and non-operating/tax items before using earnings")
	# Cheapness alone is insufficient. Missing quality inputs remain a visible gate.
	quality = False
	if financial:
		quality = metrics["roe"] is not None and metrics["roe"] >= .10 and metrics["pb"] is not None and metrics["pe"] is not None
	elif operating:
		quality = all(metrics[k] is not None for k in ("vendor_fcf_yield", "net_debt_ebitda", "revenue_growth", "operating_margin")) and metrics["vendor_fcf_yield"] > 0 and metrics["net_debt_ebitda"] <= 3.5 and metrics["revenue_growth"] >= -.10 and metrics["operating_margin"] > 0
	signals = []
	if metrics["pe"] is not None and metrics["pe"] <= 15 and metrics["pe_discount"] is not None and metrics["pe_discount"] >= .25:
		signals.append("P/E <= 15 and at least 25% below screened sector median")
	if financial and metrics["pb"] is not None and metrics["pb"] <= 1.5 and metrics["pb_discount"] is not None and metrics["pb_discount"] >= .25:
		signals.append("P/B <= 1.5 and at least 25% below screened sector median")
	if operating and metrics["vendor_fcf_yield"] is not None and metrics["vendor_fcf_yield"] >= .08:
		signals.append("Vendor free-cash-flow yield >= 8%")
	candidate = not flags and quality and len(signals) >= 2
	if not quality:
		flags.append("Quality gate failed or incomplete: verify profitability, funding and sustainable cash flow")
	if len(signals) < 2:
		flags.append("Fewer than two value signals; no automatic escalation")
	pe_discount = metrics["pe_discount"]
	score = round(50 * len(signals) + (20 if quality else 0) + 30 * max(0, min(1, pe_discount or 0)), 2)
	questions = (
		["Reconcile book value, tangible equity and sustainable ROE to filings.", "Check credit losses/reserves, capital requirements and funding sensitivity.", "Explain the sector discount; compare true business peers before valuing equity."] if financial else
		["Reconcile vendor earnings and cash flow to SEC statements; isolate one-offs and working-capital swings.", "Separate maintenance capex, growth capex, SBC and dilution; test durable owner earnings.", "Check maturities, leases, cyclicality and competitive pressure; explain why the market discount could close."]
	)
	if not operating and not financial:
		questions.insert(0, f"Choose the specialist valuation method first: {method}.")
	anchor = min(metrics["sector_pe_median"], 20) if metrics["sector_pe_median"] and metrics["eps_ttm"] and metrics["eps_ttm"] > 0 and (financial or operating) and same_currency else None
	scenarios = []
	if anchor and price and price > 0:
		for label, earnings, multiple in (("Stress", .8, .8), ("Reference", 1, 1), ("Stronger", 1.1, 1.1)):
			value = metrics["eps_ttm"] * earnings * anchor * multiple
			scenarios.append({"label": label, "eps_multiplier": earnings, "pe": anchor * multiple, "illustrative_price": value, "vs_quote": value / price - 1})
	return {
		"ticker": ticker, "issuer_cik": snapshot.get("ciks", {}).get(ticker.replace(".", "-")),
		"name": info.get("longName", quote.get("longName", ticker)), "sector": sector,
		"industry": info.get("industry"), "method": method, "metrics": metrics,
		"quote_time": info.get("regularMarketTime", quote.get("regularMarketTime")),
		"financial_period_end": datetime.fromtimestamp(quarter, UTC).date().isoformat() if quarter else None,
		"fundamentals_observed_at": detail["observed_at"] if detail else None,
		"currency": info.get("currency", quote.get("currency")), "financial_currency": info.get("financialCurrency"),
		"basic_pass": not basic_reasons(quote, snapshot["filters"], now), "value_seed": value_seed(quote),
		"candidate": candidate, "quality_pass": quality, "score": score,
		"signals": signals, "flags": flags, "questions": questions, "scenarios": scenarios,
		"business": info.get("longBusinessSummary", "Business description not available."),
		"source_url": f"https://finance.yahoo.com/quote/{ticker}/", "model": None,
	}


def saved_model(path: Path) -> dict:
	version = json.loads((path / "version.json").read_text(encoding="utf-8"))
	for filename, key in (("model.json", "model_sha256"), ("snapshot.json", "snapshot_sha256"), (f"{version['ticker']}.xlsx", "workbook_sha256")):
		if hashlib.sha256((path / "reviewed" / filename).read_bytes()).hexdigest() != version[key]:
			raise ValueError(f"Saved model hash mismatch: {filename}")
	model = json.loads((path / "reviewed/model.json").read_text(encoding="utf-8"))
	snapshot = json.loads((path / "reviewed/snapshot.json").read_text(encoding="utf-8"))
	return {
		"ticker": version["ticker"], "status": version["status"], "human_approval": version.get("human_approval", False),
		"information_cutoff": model["information_cutoff"], "measurement_date": model["measurement_date"],
		"scenario_value_per_share": snapshot["per_share_value"], "wacc": snapshot["wacc"],
		"controls": model["controls"], "limitations": model["limitations"], "path": str(path.resolve()),
		"note": "Historical provisional DCF scenario. Not refreshed to this quote; never used in screening score or implied upside.",
	}


def build_report(snapshot: dict, *, shortlist_size=20, now=None, model_dirs=(), previous=None) -> dict:
	if not 1 <= shortlist_size <= 30:
		raise ValueError("Shortlist size must be between 1 and 30")
	now = now or datetime.now(UTC)
	if snapshot.get("schema_version") != 1:
		raise ValueError("Unsupported market snapshot schema")
	tickers = [q["symbol"] for q in snapshot["quotes"]]
	if len(tickers) != len(set(tickers)) or any(symbol(t) != t for t in tickers):
		raise ValueError("Snapshot tickers must be unique and canonical")
	if any(not d["error"] and d["data"].get("symbol") != t for t, d in snapshot["details"].items()):
		raise ValueError("Snapshot fundamental ticker identity mismatch")
	peers = peer_references(snapshot, now)
	rows = [analyze(q, snapshot, peers, now) for q in snapshot["quotes"]]
	models = {m["ticker"]: m for m in map(saved_model, model_dirs)}
	for row in rows:
		row["model"] = models.get(row["ticker"])
	rows.sort(key=lambda r: (-r["score"], r["ticker"]))
	chosen, identities = [], set()
	for row in rows:
		if row["candidate"] and row["issuer_cik"] not in identities and len(chosen) < shortlist_size:
			chosen.append(row["ticker"])
			identities.add(row["issuer_cik"])
	old = set(previous["shortlist"]) if previous else set()
	counts = {
		"universe": len(rows), "basic_pass": sum(r["basic_pass"] for r in rows),
		"value_seeds": sum(r["basic_pass"] and r["value_seed"] for r in rows),
		"fundamentals_fetched": sum(not d["error"] for d in snapshot["details"].values()),
		"fundamentals_failed": sum(bool(d["error"]) for d in snapshot["details"].values()),
		"candidates": sum(r["candidate"] for r in rows), "shortlist": len(chosen),
		"value_seeds_without_fundamentals": sum(r["basic_pass"] and r["value_seed"] and not r["fundamentals_observed_at"] for r in rows),
	}
	return {
		"status": "PARTIAL_SOURCE_COVERAGE" if snapshot["issues"] or counts["fundamentals_failed"] or counts["value_seeds_without_fundamentals"] else "FREE_RESEARCH_COMPLETE",
		"implementation_hashes": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in ("market_screen.py", "daily_research.py")},
		"schema_version": 1, "created_at": now.isoformat(), "snapshot_observed_at": snapshot["observed_at"],
		"snapshot_hash": content_hash(snapshot), "scope": snapshot["scope"], "filters": snapshot["filters"],
		"max_enrich": snapshot["max_enrich"], "shortlist_limit": shortlist_size, "counts": counts,
		"paid_calls": 0, "paid_cost_eur": 0, "shortlist": chosen, "rows": rows,
		"issues": snapshot["issues"], "coverage": dict(Counter(r["method"] for r in rows)),
		"changes": {"compared": previous is not None, "added": sorted(set(chosen) - old), "removed": sorted(old - set(chosen))},
		"assumptions": [
			"Research priority only; cheapness does not establish mispricing. No price target, buy instruction or human investment approval.",
			"Default first filter: USD US-exchange equity listings, market cap >= USD1bn, price >= USD3, average volume >=100k shares/day. Universe excludes unclassified sectors and provider omissions.",
			"Free fundamentals seed: positive P/E <=20 or positive P/B <=2. Fetch priority is min(P/E/20, P/B/2); capped fetches remain visible. Set max-enrich=0 for all seeds.",
			"Research candidates need two value signals and quality gates. P/E <=15 with >=25% sector discount; operating-company vendor FCF yield >=8%; banks/insurers P/B <=1.5 with >=25% sector discount.",
			"Operating quality: positive vendor FCF and operating margin, net debt/EBITDA <=3.5, revenue growth >=-10%. Banks/insurers: positive book/earnings and ROE >=10%. Missing inputs fail automatic escalation.",
			"Preferred/warrant/unit/debt symbol or name indicators exclude issuer-ratio misuse. P/E below3 or operating-company vendor net margin >operating margin+15pp requires earnings reconciliation; margin periods may differ.",
			"Sector references exclude the issuer and duplicate known share classes; minimum five peers, positive P/E <=100 or P/B <=20. Broad screened-sector comparisons are not matched-business fair values.",
			"Yahoo fundamentals are vendor aggregates with mixed trailing/current periods; latest quarter is a freshness indicator, not an asserted period for every metric. Forward P/E is an estimate, never a ranking input.",
			"Free cash flow is the vendor freeCashflow field / market cap, not independently reconciled owner earnings or unlevered DCF cash flow. Cross-currency monetary ratios are suppressed.",
			"Illustrative earnings sensitivity: min(sector median P/E,20), EPS factors0.8/1/1.1 and multiple factors0.8/1/1.1. Unvalidated normalization; not fair value or a forecast.",
			"Quotes older than seven days, financial periods older than200 days, unknown SEC identities and specialist methods cannot enter the automatic shortlist. Quote pages are not an atomic market snapshot.",
		],
	}


LABELS = {
	"price": "Price (quote currency)", "market_cap": "Market cap (quote currency)", "pe": "P/E (TTM)", "pb": "P/B",
	"forward_pe_vendor": "Forward P/E (vendor estimate)", "vendor_fcf_yield": "Vendor FCF yield",
	"ev_ebitda": "EV/EBITDA", "net_debt_ebitda": "Net debt/EBITDA", "roe": "ROE (vendor)",
	"revenue_growth": "Revenue growth (vendor)", "operating_margin": "Operating margin (vendor)",
	"net_margin_vendor": "Net margin (vendor)",
	"eps_ttm": "EPS (TTM, USD)", "book_per_share": "Book/share (USD)",
	"sector_pe_median": "Sector P/E reference", "sector_pb_median": "Sector P/B reference",
	"sector_pe_n": "P/E peer count", "sector_pb_n": "P/B peer count", "pe_discount": "P/E sector discount", "pb_discount": "P/B sector discount",
}


def display(key: str, value) -> str:
	if value is None:
		return "Unavailable / not meaningful"
	if key in {"vendor_fcf_yield", "roe", "revenue_growth", "operating_margin", "net_margin_vendor", "pe_discount", "pb_discount"}:
		return f"{value:.1%}"
	return f"{value:,.2f}"


def brief(row: dict, report: dict) -> str:
	lines = [f"# {row['ticker']} — {row['name']}", "", f"Research snapshot: {report['snapshot_observed_at']}. Currency: {row['currency']}; financial currency: {row['financial_currency']}.", f"Financial period indicator: {row['financial_period_end']}; quote timestamp (Unix): {row['quote_time']}.", "", f"**{'Research shortlist' if row['ticker'] in report['shortlist'] else 'Watch / resolve gaps'}** · {row['method']}", "", row["business"], "", "## Why investigate", ""]
	lines += [f"- {s}" for s in row["signals"]] or ["- No qualifying value signals."]
	lines += ["", "## What could invalidate the case", ""] + [f"- {s}" for s in row["flags"]]
	lines += ["- Low multiples can reflect structural decline, unusual earnings or expected losses. No catalyst has been verified.", "", "## Crucial numbers", "", "| Metric | Value |", "|---|---:|"]
	lines += [f"| {LABELS[k]} | {display(k, v)} |" for k, v in row["metrics"].items()]
	lines += ["", "## Model breakdown", "", "Quick model: price / positive trailing EPS and price / positive book per share. Operating companies add vendor FCF / market cap and debt/EBITDA checks. No accounting forecasts or agent judgments in this stage.", "", "| Sensitivity (not fair value) | EPS factor | P/E | Implied USD/share | vs quote |", "|---|---:|---:|---:|---:|"]
	lines += [f"| {s['label']} | {s['eps_multiplier']:.2f} | {s['pe']:.2f} | {s['illustrative_price']:.2f} | {s['vs_quote']:.1%} |" for s in row["scenarios"]]
	if row["model"]:
		model = row["model"]
		lines += ["", "### Existing DCF", "", model["note"], f"Status: {model['status']}; source cutoff: {model['information_cutoff']}; scenario USD/share: {model['scenario_value_per_share']:.2f}; WACC: {model['wacc']:.2%}.", "", "Controls: " + json.dumps(model["controls"]), ""] + [f"- {s}" for s in model["limitations"]]
	lines += ["", "## How to approach the analysis", ""] + [f"{i}. {q}" for i, q in enumerate(row["questions"], 1)]
	lines += ["", "**Before paid analysis:** verify source earnings/cash flow, establish a credible normalized value range and a reason the discount might close. Use the IC agent only for unresolved interpretation worth investigating.", "", f"Market source: {row['source_url']}", "", "All metrics and controls are screening evidence or provisional assumptions. No human investment approval."]
	return "\n".join(lines) + "\n"


def export_report(report: dict, output: Path) -> None:
	write_json(output / "report.json", report)
	with (output / "screen.csv").open("w", newline="", encoding="utf-8-sig") as stream:
		writer = csv.DictWriter(stream, fieldnames=["ticker", "name", "sector", "method", "candidate", "score", *LABELS, "flags"])
		writer.writeheader()
		for row in report["rows"]:
			flat = {k: row[k] for k in ("ticker", "name", "sector", "method", "candidate", "score")}
			flat.update(row["metrics"])
			flat["flags"] = "; ".join(row["flags"])
			# Text comes from an external provider; neutralize spreadsheet formulas.
			writer.writerow({k: "'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@")) else v for k, v in flat.items()})
	(output / "briefs").mkdir(exist_ok=True)
	for row in report["rows"]:
		if row["fundamentals_observed_at"]:
			(output / "briefs" / f"{row['ticker']}.md").write_text(brief(row, report), encoding="utf-8")
			(output / "briefs" / f"{row['ticker']}.html").write_text(brief_html(row, report), encoding="utf-8")
	counts = report["counts"]
	intro = f"{counts['universe']} listings → {counts['basic_pass']} first-filter passes → {counts['value_seeds']} value seeds → {counts['candidates']} qualifying candidates → {counts['shortlist']} shortlisted. Free fundamentals fetched: {counts['fundamentals_fetched']} (including any watchlist or subsequently excluded listings). LLM calls: 0; cost: EUR0."
	escape = html.escape
	cards = []
	for row in report["rows"]:
		if row["ticker"] not in report["shortlist"]:
			continue
		metrics = " · ".join(f"{LABELS[k]}: {display(k, row['metrics'][k])}" for k in ("price", "pe", "pb", "vendor_fcf_yield", "roe"))
		cards.append(f"<article><h2>{escape(row['ticker'])} <small>{escape(row['name'])}</small></h2><p>{escape(row['method'])}</p><p>{escape(metrics)}</p><ul>" + "".join(f"<li>{escape(s)}</li>" for s in row["signals"]) + f"</ul><p>Next: {escape(row['questions'][0])}</p><a href='briefs/{row['ticker']}.html'>Full research brief</a></article>")
	if not cards:
		cards = ["<article><h2>No automatic shortlist today</h2><p>No need to fill a quota. Review the table for data gaps, specialist cases and near misses.</p></article>"]
	table = []
	for row in report["rows"]:
		link = f"<a href='briefs/{row['ticker']}.html'>{escape(row['ticker'])}</a>" if row["fundamentals_observed_at"] else escape(row["ticker"])
		table.append(f"<tr><td>{link}</td><td>{escape(row['sector'])}</td><td>{escape(row['method'])}</td><td>{display('pe', row['metrics']['pe'])}</td><td>{display('vendor_fcf_yield', row['metrics']['vendor_fcf_yield'])}</td><td>{escape('; '.join(row['signals']))}</td><td>{escape('; '.join(row['flags']))}</td></tr>")
	body = f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Daily research shortlist</title>
<style>body{{font:16px system-ui;margin:0;background:#f3f5f8;color:#16243b}}main{{max-width:1400px;margin:auto;padding:32px}}h1{{font-size:38px}}small{{font-weight:400;color:#516079}}article,details{{background:white;padding:22px;margin:16px 0;border-radius:10px}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:16px}}a{{color:#1a56b4}}td,th{{text-align:left;padding:10px;border-bottom:1px solid #dce1e9;vertical-align:top}}table{{width:100%;border-collapse:collapse;font-size:13px}}input{{padding:12px;width:min(500px,90%);margin:15px 0}}.scroll{{overflow:auto}}.muted{{color:#516079}}</style>
<main><p class="muted">FREE RESEARCH DESK · {escape(report['snapshot_observed_at'])}</p><h1>What deserves a closer look?</h1><p>{escape(intro)}</p><p>Research candidates, not proven mispricings. Source: Yahoo vendor fundamentals and SEC issuer identities. <a href="screen.csv">All results CSV</a> · <a href="report.json">Evidence & calculations</a></p><p>{escape(report['scope'])}. Enrichment limit: {report['max_enrich'] or 'all seeds'}; requested shortlist maximum: {report['shortlist_limit']}.</p><p>{escape('; '.join(report['issues']))}</p>
	<p>{escape('Shortlist changes: added ' + ', '.join(report['changes']['added']) + '; removed ' + ', '.join(report['changes']['removed']) if report['changes']['compared'] else 'First snapshot: no prior shortlist comparison.')}</p><div class="grid">{''.join(cards)}</div><details><summary>Model assumptions, thresholds and coverage</summary><ul>{''.join('<li>'+escape(s)+'</li>' for s in report['assumptions'])}</ul><pre>{escape(json.dumps(report['coverage'],indent=2))}</pre></details>
<h2>All listings and exclusion reasons</h2><input id="filter" aria-label="Filter listings" placeholder="Filter ticker, sector, method or reason"><div class="scroll"><table><thead><tr><th>Ticker</th><th>Sector</th><th>Method</th><th>P/E</th><th>Vendor FCF yield</th><th>Value signals</th><th>Gaps / exclusions</th></tr></thead><tbody>{''.join(table)}</tbody></table></div></main>
<script>document.getElementById('filter').addEventListener('input',function(){{const q=this.value.toLowerCase();document.querySelectorAll('tbody tr').forEach(r=>r.hidden=!r.textContent.toLowerCase().includes(q));}});</script></html>"""
	(output / "index.html").write_text(body, encoding="utf-8")
	(output / "README.md").write_text(f"# Daily research desk\n\n{intro}\n\nSnapshot: {report['snapshot_observed_at']}\n\nOpen index.html for the shortlist; screen.csv contains all listings and exclusion reasons; report.json binds the raw snapshot by SHA256; briefs/ contains free company analysis.\n\n" + "\n".join(f"- {s}" for s in report["assumptions"]) + "\n", encoding="utf-8")


def brief_html(row: dict, report: dict) -> str:
	"""Browser-readable brief, with escaped vendor text and no remote assets."""
	e = html.escape
	metrics = "".join(f"<tr><td>{LABELS[k]}</td><td>{display(k, v)}</td></tr>" for k, v in row["metrics"].items())
	scenarios = "".join(f"<tr><td>{s['label']}</td><td>{s['eps_multiplier']:.2f}</td><td>{s['pe']:.2f}</td><td>{s['illustrative_price']:.2f}</td><td>{s['vs_quote']:.1%}</td></tr>" for s in row["scenarios"])
	def lists(items):
		return "".join(f"<li>{e(s)}</li>" for s in items)
	model = ""
	if row["model"]:
		m = row["model"]
		model = f"<h2>Existing DCF</h2><p>{e(m['note'])}</p><p>{e(m['status'])} · source cutoff {e(m['information_cutoff'])} · scenario USD/share {m['scenario_value_per_share']:.2f} · WACC {m['wacc']:.2%}</p><pre>{e(json.dumps(m['controls'],indent=2))}</pre><ul>{lists(m['limitations'])}</ul>"
	return f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(row['ticker'])} research brief</title>
<style>body{{font:16px/1.6 system-ui;color:#16243b;background:#f3f5f8}}main{{max-width:1000px;margin:auto;padding:32px}}section{{padding:24px;background:white;border-radius:12px;margin:20px 0}}h1{{font-size:34px}}h2{{font-size:22px}}a{{color:#1a56b4}}table{{border-collapse:collapse;width:100%}}td,th{{padding:8px;text-align:left;border-bottom:1px solid #dce1e9}}pre{{white-space:pre-wrap}}.muted{{color:#516079}}code{{overflow-wrap:anywhere}}</style>
<main><a href="../index.html">← Daily desk</a><h1>{e(row['ticker'])} · {e(row['name'])}</h1><p>{e(row['method'])} · {'RESEARCH SHORTLIST' if row['ticker'] in report['shortlist'] else 'WATCH / RESOLVE GAPS'}</p><p class="muted">Snapshot {e(report['snapshot_observed_at'])}; financial period indicator {e(str(row['financial_period_end']))}; quote Unix timestamp {row['quote_time']}. Quote currency {e(str(row['currency']))}; financial currency {e(str(row['financial_currency']))}.</p>
<section><h2>Business</h2><p>{e(row['business'])}</p><h2>Why investigate</h2><ul>{lists(row['signals'] or ['No qualifying value signals.'])}</ul><h2>What could invalidate the case</h2><ul>{lists(row['flags'])}<li>Low multiples can reflect structural decline, unusual earnings or expected losses. No catalyst verified.</li></ul></section>
<section><h2>Crucial numbers</h2><table><tr><th>Metric</th><th>Value</th></tr>{metrics}</table></section>
<section><h2>Model breakdown</h2><p>Price / positive trailing EPS; price / positive book. Operating companies add vendor FCF / market cap and net debt / EBITDA. Bank/insurer cash flows and enterprise value ratios are excluded. Source values remain in snapshot.json.</p><p>Illustrative sensitivity only: reference P/E = min(screened sector median,20), EPS factors0.8/1/1.1, P/E factors0.8/1/1.1. This is not fair value or a forecast.</p><table><tr><th>Case</th><th>EPS factor</th><th>P/E</th><th>USD/share</th><th>vs quote</th></tr>{scenarios}</table>{model}</section>
<section><h2>How to approach the analysis</h2><ol>{lists(row['questions'])}</ol><p>Before paying: reconcile earnings/cash flow, establish a defensible normalized value range and a reason the discount could close. The optional IC agent interprets a supplied evidence packet; it cannot verify missing external facts.</p><p>Deeper source/model command (free of LLM calls):</p><code>smrik-fund daily deep RUN_DIRECTORY {e(row['ticker'])} --output-dir NEW_DIRECTORY</code></section>
<p><a href="{e(row['source_url'])}">Yahoo source</a> · <a href="{e(row['ticker'])}.md">Markdown brief</a> · <a href="../snapshot.json">Frozen vendor data</a></p><p class="muted">Screening evidence and provisional assumptions. No human investment approval.</p></main></html>"""
