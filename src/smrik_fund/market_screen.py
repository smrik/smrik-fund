"""Free, replayable Yahoo market snapshots. No inference or paid provider calls."""

import json
import math
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from pathlib import Path

US_EXCHANGES = {"NMS", "NGM", "NCM", "NYQ", "ASE", "BTS"}
SECTORS = (
	"Basic Materials", "Communication Services", "Consumer Cyclical",
	"Consumer Defensive", "Energy", "Financial Services", "Healthcare",
	"Industrials", "Real Estate", "Technology", "Utilities",
)
DEFAULT_FILTERS = {"min_cap": 1e9, "min_price": 3.0, "min_volume": 100_000.0}


def write_json(path: Path, value) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def number(value):
	if isinstance(value, bool) or not isinstance(value, int | float):
		return None
	return float(value) if math.isfinite(value) else None


def ratio(numerator, denominator, *, positive_numerator=False):
	a, b = number(numerator), number(denominator)
	if a is None or b is None or b <= 0 or (positive_numerator and a <= 0):
		return None
	return a / b


def symbol(value: str) -> str:
	value = value.strip().upper()
	if not re.fullmatch(r"[A-Z0-9][A-Z0-9.\-^=]{0,19}", value):
		raise ValueError("Invalid ticker syntax")
	return value


def basic_reasons(quote: dict, filters: dict, now: datetime) -> list[str]:
	reasons = []
	name = f"{quote.get('longName', '')} {quote.get('shortName', '')}".lower()
	if re.search(r"-(?:P[A-Z]?|W[ST]?|U|R)$", quote.get("symbol", "")) or re.search(r"\b(?:preferred|preference|depositary shares|warrants?|debentures|notes due)\b", name):
		reasons.append("Non-common security: issuer earnings/book cannot value this preferred, warrant, unit or debt claim")
	for key, label, minimum in (
		("marketCap", "market cap", filters["min_cap"]),
		("regularMarketPrice", "share price", filters["min_price"]),
		("averageDailyVolume3Month", "average volume", filters["min_volume"]),
	):
		value = number(quote.get(key))
		if value is None or value < minimum:
			reasons.append(f"Missing/below minimum {label}")
	if quote.get("quoteType") != "EQUITY":
		reasons.append("Not an equity listing")
	if quote.get("currency") != "USD" or quote.get("exchange") not in US_EXCHANGES:
		reasons.append("Outside supported US-exchange/USD scope")
	timestamp = number(quote.get("regularMarketTime"))
	if timestamp is None or not now.timestamp() - 7 * 86400 <= timestamp <= now.timestamp() + 600:
		reasons.append("Quote missing, future-dated or older than seven days")
	return reasons


def quote_metrics(quote: dict) -> dict:
	price = quote.get("regularMarketPrice")
	eps = quote.get("epsTrailingTwelveMonths", quote.get("trailingEps"))
	return {
		"pe": ratio(price, eps, positive_numerator=True),
		"pb": ratio(price, quote.get("bookValue"), positive_numerator=True),
	}


def value_seed(quote: dict) -> bool:
	metrics = quote_metrics(quote)
	return (metrics["pe"] is not None and metrics["pe"] <= 20) or (metrics["pb"] is not None and metrics["pb"] <= 2)


def seed_order(quote: dict) -> tuple:
	metrics = quote_metrics(quote)
	# Broad value search; this is a fetch priority, not a research score.
	cheapness = min(metrics["pe"] / 20 if metrics["pe"] else math.inf, metrics["pb"] / 2 if metrics["pb"] else math.inf)
	return cheapness, quote["symbol"]


def get_detail(ticker: str, cache: Path, *, refresh=False) -> dict:
	import yfinance as yf

	ticker = symbol(ticker)
	path = cache / f"{ticker}.json"
	now = datetime.now(UTC)
	if path.exists() and not refresh:
		try:
			saved = json.loads(path.read_text(encoding="utf-8"))
			observed = datetime.fromisoformat(saved["observed_at"])
			if saved["data"].get("symbol") == ticker and timedelta(0) <= now - observed < timedelta(hours=20):
				return saved
		except (OSError, ValueError, KeyError, TypeError):
			pass  # Interrupted/invalid caches are refetched, never treated as source facts.
	try:
		info = yf.Ticker(ticker).get_info()
		if not info or info.get("symbol", "").upper() != ticker:
			raise ValueError("Empty or mismatched ticker response")
		result = {"observed_at": now.isoformat(), "data": info, "error": None}
		write_json(path, result)
		return result
	except Exception as exc:
		# Public provider failures are visible, never converted into zero fundamentals.
		return {"observed_at": now.isoformat(), "data": {}, "error": type(exc).__name__}


def capture(output: Path, *, tickers=(), filters=None, max_enrich=0, refresh=False, progress=print) -> dict:
	import yfinance as yf

	filters = dict(filters or DEFAULT_FILTERS)
	if max_enrich < 0 or any(number(v) is None or v < 0 for v in filters.values()):
		raise ValueError("Filters and enrichment limit must be finite and nonnegative")
	cache = output.parent / ".market-cache"
	yf.set_tz_cache_location(str(cache / "yfinance"))
	started = datetime.now(UTC)
	quotes, sectors, pages, issues = {}, {}, [], []
	details = {}
	tickers = list(dict.fromkeys(symbol(t) for t in tickers))
	if tickers:
		for ticker in tickers:
			progress(f"Free quote: {ticker}")
			details[ticker] = get_detail(ticker, cache / "details", refresh=refresh)
			info = details[ticker]["data"]
			quotes[ticker] = {**info, "symbol": ticker}
			sectors[ticker] = info.get("sector", "Unknown")
	else:
		for sector in SECTORS:
			query = yf.EquityQuery("and", [
				yf.EquityQuery("eq", ["region", "us"]),
				yf.EquityQuery("eq", ["sector", sector]),
				yf.EquityQuery("gte", ["intradaymarketcap", filters["min_cap"]]),
				yf.EquityQuery("gte", ["intradayprice", filters["min_price"]]),
				yf.EquityQuery("gte", ["avgdailyvol3m", filters["min_volume"]]),
			])
			offset, seen, expected = 0, set(), None
			try:
				while True:
					result = yf.screen(query, offset=offset, size=250, sortField="intradaymarketcap", sortAsc=False)
					if not isinstance(result, dict) or not isinstance(result.get("quotes"), list):
						raise ValueError("Malformed screener response")
					expected = int(result["total"])
					pages.append({"sector": sector, "offset": offset, "response": result})
					rows = result["quotes"]
					new = {q["symbol"] for q in rows} - seen
					for quote in rows:
						ticker = symbol(quote["symbol"])
						quotes[ticker], sectors[ticker] = quote, sector
					seen.update(new)
					if offset + len(rows) >= expected:
						break
					if not new or not rows or offset >= 10_000:
						raise ValueError("Pagination incomplete")
					offset += len(rows)
				if len(seen) != expected:
					issues.append(f"{sector}: unique rows {len(seen)} differ from provider total {expected}")
			except Exception as exc:
				issues.append(f"{sector}: {type(exc).__name__}; captured {len(seen)} of {expected}")
			progress(f"Universe: {sector}, {len(seen)} listings")
			write_json(output / "capture.partial.json", {"pages": pages, "issues": issues})
	eligible = [q for q in quotes.values() if not basic_reasons(q, filters, started)]
	seeds = sorted((q for q in eligible if value_seed(q)), key=seed_order)
	selected = seeds[:max_enrich] if max_enrich else seeds
	pending = [q["symbol"] for q in selected if q["symbol"] not in details]
	# Small bounded fanout; cached successes survive an interrupted run.
	with ThreadPoolExecutor(max_workers=3) as pool:
		jobs = {pool.submit(get_detail, ticker, cache / "details", refresh=refresh): ticker for ticker in pending}
		for index, job in enumerate(as_completed(jobs), 1):
			details[jobs[job]] = job.result()
			if index % 10 == 0 or index == len(pending):
				progress(f"Free fundamentals: {index}/{len(pending)}")
	# Issuer identity collapses multiple share classes in the final shortlist.
	ciks = {}
	try:
		from edgar.reference.tickers import get_company_tickers

		from smrik_fund.ingestion.statements import configure_edgar

		configure_edgar()
		for record in get_company_tickers().to_dict(orient="records"):
			ciks[str(record["ticker"]).replace(".", "-")] = str(record["cik"])
	except Exception as exc:
		issues.append(f"SEC issuer identities unavailable: {type(exc).__name__}; unknown issuers cannot enter automatic shortlist")
	snapshot = {
		"schema_version": 1, "provider": "Yahoo Finance via yfinance; SEC ticker identities via EdgarTools",
		"started_at": started.isoformat(), "observed_at": datetime.now(UTC).isoformat(),
		"scope": "explicit US watchlist" if tickers else "Yahoo US-region equities in eleven named sectors after size/price/liquidity filters",
		"filters": filters, "max_enrich": max_enrich, "quotes": list(quotes.values()),
		"sectors": sectors, "details": details, "ciks": ciks, "issues": issues,
		"screen_pages": pages, "paid_calls": 0,
	}
	write_json(output / "snapshot.json", snapshot)
	return snapshot
