"""A local research watchlist joined to verified, frozen screening evidence.

User review prices and notes are stored separately from vendor inputs and DCFs.
Reads never fetch prices or invoke analysts. One workbench server owns writes.
"""

import json
import threading
from datetime import UTC, datetime
from pathlib import Path

from smrik_fund.market_screen import number, symbol
from smrik_fund.research_audit import (
	DATA_ROOT,
	list_runs,
	read_json,
	verify_screen,
	within_data,
)

STAGES = ("Idea", "Researching", "Waiting for price", "Archived")
FIELDS = {"ticker", "stage", "review_price", "thesis", "risks", "next_step"}
WRITE_LOCK = threading.Lock()


def load_watchlist(data_root=DATA_ROOT):
	path = within_data(Path(data_root) / "workspace/watchlist.json", Path(data_root))
	if not path.exists():
		return {"schema_version": 1, "revision": 0, "entries": []}
	saved = read_json(path)
	if (
		saved.get("schema_version") != 1
		or type(saved.get("revision")) is not int
		or not isinstance(saved.get("entries"), list)
	):
		raise ValueError(
			"Watchlist file is invalid; preserve it and repair before saving"
		)
	tickers = [entry["ticker"] for entry in saved["entries"]]
	if len(tickers) != len(set(tickers)):
		raise ValueError("Duplicate watchlist tickers")
	return saved


def save_entry(payload, data_root=DATA_ROOT):
	"""Validate one edit and reject stale revisions instead of losing another edit."""
	if not isinstance(payload, dict) or set(payload) != {"revision", "entry"}:
		raise ValueError("Expected revision and entry")
	entry = payload["entry"]
	if not isinstance(entry, dict) or set(entry) != FIELDS:
		raise ValueError("Unknown or missing watchlist fields")
	if type(payload["revision"]) is not int or not isinstance(entry["ticker"], str):
		raise ValueError("Invalid watchlist revision or ticker")
	entry = dict(entry, ticker=symbol(entry["ticker"]))
	if entry["stage"] not in STAGES:
		raise ValueError("Unknown research stage")
	price = entry["review_price"]
	if price is not None and (number(price) is None or price <= 0):
		raise ValueError("Review price must be a positive USD amount or blank")
	for key in ("thesis", "risks", "next_step"):
		if (
			not isinstance(entry[key], str)
			or len(entry[key]) > 2000
			or "\x00" in entry[key]
		):
			raise ValueError(f"{key} must be text of at most 2000 characters")
		entry[key] = entry[key].strip()
	with WRITE_LOCK:
		saved = load_watchlist(data_root)
		if payload["revision"] != saved["revision"]:
			raise ValueError(
				"Watchlist changed in another tab. Reload before saving; your form has been kept."
			)
		previous = next(
			(x for x in saved["entries"] if x["ticker"] == entry["ticker"]), None
		)
		now = datetime.now(UTC).isoformat()
		entry.update(added_at=previous["added_at"] if previous else now, updated_at=now)
		entries = [x for x in saved["entries"] if x["ticker"] != entry["ticker"]] + [
			entry
		]
		if sum(x["stage"] != "Archived" for x in entries) > 30:
			raise ValueError(
				"Watchlist has 30 active companies. Archive one before adding another."
			)
		result = {
			"schema_version": 1,
			"revision": saved["revision"] + 1,
			"entries": entries,
		}
		path = within_data(
			Path(data_root) / "workspace/watchlist.json", Path(data_root)
		)
		path.parent.mkdir(parents=True, exist_ok=True)
		temporary = path.with_suffix(".tmp")
		temporary.write_text(
			json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
			encoding="utf-8",
		)
		temporary.replace(path)
		return result


def screen_catalog(runs, data_root):
	screens, issues = [], []
	for run in runs:
		if run["kind"] != "screen":
			continue
		try:
			report = read_json(
				within_data(data_root / run["id"] / "report.json", data_root)
			)
			screens.append(
				{
					"id": run["id"],
					"created_at": report["created_at"],
					"scope": report["scope"],
					"counts": report["counts"],
				}
			)
		except (OSError, ValueError, KeyError, TypeError) as exc:
			issues.append(f"{run['id']}: {exc}")
	return sorted(screens, key=lambda x: x["created_at"], reverse=True), issues


def research_links(runs):
	result = {}
	for (
		run
	) in runs:  # list_runs is newest first; a later stopped attempt stays visible.
		if run["kind"] == "company":
			result.setdefault(run["ticker"], {"id": run["id"], "status": run["status"]})
	return result


def company_view(row, screen, latest_runs, now):
	"""Keep missing inputs missing; freshness is evaluated at viewing time."""
	timestamp = number(row.get("quote_time"))
	age = (now.timestamp() - timestamp) / 86400 if timestamp is not None else None
	fresh = age is not None and -600 / 86400 <= age <= 7
	quote_status = (
		"Missing"
		if age is None
		else "Future dated"
		if age < -600 / 86400
		else "Stale"
		if age > 7
		else "Fresh"
	)
	keys = (
		"ticker",
		"name",
		"sector",
		"method",
		"metrics",
		"currency",
		"financial_currency",
		"financial_period_end",
		"fundamentals_observed_at",
		"quote_time",
		"basic_pass",
		"candidate",
		"quality_pass",
		"score",
		"signals",
		"flags",
		"questions",
		"source_url",
	)
	result = {key: row.get(key) for key in keys}
	result.update(
		screen=screen["id"],
		screen_created_at=screen["created_at"],
		quote_status=quote_status,
		quote_age_days=max(0, age) if age is not None else None,
		research=latest_runs.get(row["ticker"]),
		shortlisted=row["ticker"] in screen.get("shortlist", []),
	)
	try:
		period_age = (
			now.date() - datetime.fromisoformat(row["financial_period_end"]).date()
		).days
		period_fresh = 0 <= period_age <= 200
	except (TypeError, ValueError):
		period_fresh = False
	result["candidate_now"] = bool(row["candidate"] and fresh and period_fresh)
	return result


def screener(screen_id=None, data_root=DATA_ROOT, now=None):
	data_root = Path(data_root).resolve()
	now = now or datetime.now(UTC)
	runs = list_runs(data_root)
	screens, issues = screen_catalog(runs, data_root)
	if not screens and not screen_id:
		return {"screens": [], "screen": None, "rows": [], "issues": issues}
	# Prefer the latest broad universe over a more recent small ticker run.
	if not screen_id:
		broad = [s for s in screens if s["scope"] != "explicit US watchlist"]
		screen_id = (broad or screens)[0]["id"]
	path = within_data(data_root / screen_id, data_root)
	report = verify_screen(path, data_root)
	screen = {
		"id": path.relative_to(data_root).as_posix(),
		"created_at": report["created_at"],
		"scope": report["scope"],
		"counts": report["counts"],
		"shortlist": report["shortlist"],
		"filters": report["filters"],
	}
	latest = research_links(runs)
	return {
		"screens": screens,
		"screen": screen,
		"rows": [company_view(row, screen, latest, now) for row in report["rows"]],
		"issues": issues + report["issues"],
	}


def watchlist(data_root=DATA_ROOT, now=None):
	data_root = Path(data_root).resolve()
	now = now or datetime.now(UTC)
	saved = load_watchlist(data_root)
	if not saved["entries"]:
		return {**saved, "items": [], "issues": [], "viewed_at": now.isoformat()}
	runs = list_runs(data_root)
	screens, issues = screen_catalog(runs, data_root)
	wanted = {entry["ticker"] for entry in saved["entries"]}
	candidates = {ticker: [] for ticker in wanted}
	# Use unverified files only to find possible sources; no values leave this
	# function until verify_screen has reproduced their saved decisions.
	for screen in screens:
		try:
			report = read_json(
				within_data(data_root / screen["id"] / "report.json", data_root)
			)
			for row in report["rows"]:
				if row["ticker"] in wanted:
					candidates[row["ticker"]].append(
						(
							number(row.get("quote_time")) or 0,
							screen["created_at"],
							screen,
						)
					)
		except (OSError, ValueError, KeyError, TypeError) as exc:
			issues.append(f"{screen['id']}: {exc}")
	verified, latest, result = {}, research_links(runs), []
	for entry in saved["entries"]:
		company = None
		for _, _, screen in sorted(
			candidates[entry["ticker"]], key=lambda x: (x[0], x[1]), reverse=True
		):
			key = screen["id"]
			if key not in verified:
				try:
					report = verify_screen(data_root / key, data_root)
					verified[key] = {r["ticker"]: r for r in report["rows"]}
					screen["shortlist"] = report["shortlist"]
					issues.extend(f"{key}: {issue}" for issue in report["issues"])
				except (OSError, ValueError, KeyError, TypeError) as exc:
					issues.append(f"{key}: {exc}; excluded from watchlist data")
					verified[key] = {}
			if entry["ticker"] in verified[key]:
				company = company_view(
					verified[key][entry["ticker"]], screen, latest, now
				)
				break
		price = number(company["metrics"].get("price")) if company else None
		target = entry["review_price"]
		comparable = (
			company
			and company["quote_status"] == "Fresh"
			and company["currency"] == "USD"
			and price is not None
			and price > 0
			and target is not None
		)
		result.append(
			{
				"entry": entry,
				"company": company,
				"review_gap": price / target - 1 if comparable else None,
				"at_review_price": bool(
					comparable and price <= target and entry["stage"] != "Archived"
				),
			}
		)
	return {
		**saved,
		"items": result,
		"issues": list(dict.fromkeys(issues)),
		"viewed_at": now.isoformat(),
	}
