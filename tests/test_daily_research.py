import copy
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest
from typer.testing import CliRunner

from smrik_fund.analysis_budget import initialize_budget
from smrik_fund.daily_cli import app
from smrik_fund.daily_ic import prepare_packet, run_ic
from smrik_fund.daily_research import (
	analyze,
	build_report,
	export_report,
	peer_references,
)
from smrik_fund.market_screen import DEFAULT_FILTERS, capture, ratio, write_json


@pytest.fixture
def snapshot():
	now = datetime.now(UTC)
	quotes, details, sectors, ciks = [], {}, {}, {}
	for i in range(9):
		ticker = f"TEST{i}"
		info = {
			"symbol": ticker, "longName": "Synthetic company", "quoteType": "EQUITY",
			"regularMarketPrice": 10.0 if i == 0 else 30.0,
			"regularMarketTime": int(now.timestamp()), "marketCap": 2e9,
			"currency": "USD", "financialCurrency": "USD", "exchange": "NMS",
			"averageDailyVolume3Month": 200_000, "epsTrailingTwelveMonths": 1.0,
			"trailingEps": 1.0, "bookValue": 10.0, "sector": "Technology",
			"industry": "Software", "freeCashflow": 200e6, "totalDebt": 100e6,
			"totalCash": 50e6, "ebitda": 100e6, "enterpriseValue": 2.05e9,
			"revenueGrowth": .05, "operatingMargins": .1, "returnOnEquity": .15,
			"mostRecentQuarter": int((now - timedelta(days=75)).timestamp()),
		}
		quotes.append(info.copy())
		details[ticker] = {"data": info, "observed_at": now.isoformat(), "error": None}
		sectors[ticker], ciks[ticker] = "Technology", str(i)
	return {
		"schema_version": 1, "observed_at": now.isoformat(), "scope": "synthetic US test universe",
		"filters": DEFAULT_FILTERS.copy(), "max_enrich": 0, "quotes": quotes,
		"details": details, "sectors": sectors, "ciks": ciks, "issues": [],
	}


def test_economic_ratios_do_not_replace_missing_or_flip_signs():
	assert ratio(None, 10) is None
	assert ratio(1, 0) is None
	assert ratio(1, -2) is None
	assert ratio(float("nan"), 10) is None
	assert ratio(-2, 10) == -.2


def test_two_signal_candidate_and_explicit_arithmetic(snapshot):
	report = build_report(snapshot)
	assert report["shortlist"] == ["TEST0"]
	row = report["rows"][0]
	assert row["metrics"]["pe"] == 10
	assert row["metrics"]["sector_pe_median"] == 30
	assert row["metrics"]["pe_discount"] == pytest.approx(2 / 3)
	assert row["metrics"]["vendor_fcf_yield"] == .1
	assert row["metrics"]["net_debt_ebitda"] == .5
	assert [s["illustrative_price"] for s in row["scenarios"]] == pytest.approx([12.8, 20, 24.2])
	assert report["paid_calls"] == report["paid_cost_eur"] == 0


@pytest.mark.parametrize("field,value,reason", [
	("freeCashflow", None, "Quality gate"),
	("freeCashflow", -100e6, "Quality gate"),
	("totalDebt", None, "Quality gate"),
	("ebitda", -10, "Quality gate"),
	("revenueGrowth", -.3, "Quality gate"),
	("operatingMargins", -.1, "Quality gate"),
	("financialCurrency", "CNY", "currency"),
	("mostRecentQuarter", 1, "200 days"),
	("regularMarketTime", 1, "seven days"),
	("industry", "REIT - Retail", "REIT"),
	("profitMargins", .5, "mixed periods"),
	("longName", "Issuer preferred depositary shares", "Non-common"),
])
def test_bad_or_missing_evidence_cannot_escalate(snapshot, field, value, reason):
	snapshot["details"]["TEST0"]["data"][field] = value
	report = build_report(snapshot)
	row = next(r for r in report["rows"] if r["ticker"] == "TEST0")
	assert not row["candidate"]
	assert any(reason in flag for flag in row["flags"])
	assert snapshot["details"]["TEST0"]["data"][field] == value
	if field == "financialCurrency":
		assert row["metrics"]["pe"] is None and row["scenarios"] == []


def test_bank_uses_book_and_roe_not_industrial_cash_flow(snapshot):
	for ticker, detail in snapshot["details"].items():
		detail["data"].update(sector="Financial Services", industry="Banks - Regional", freeCashflow=-2e9, totalDebt=9e9)
		snapshot["sectors"][ticker] = "Financial Services"
	report = build_report(snapshot)
	row = next(r for r in report["rows"] if r["ticker"] == "TEST0")
	assert row["candidate"] and row["method"].startswith("Bank:")
	assert row["metrics"]["vendor_fcf_yield"] is None
	assert row["metrics"]["ev_ebitda"] is None
	assert row["metrics"]["net_debt_ebitda"] is None
	assert len(row["signals"]) == 2


def test_share_classes_cannot_fill_shortlist_twice(snapshot):
	for ticker in ("TEST0", "TEST1"):
		snapshot["details"][ticker]["data"]["regularMarketPrice"] = 10
	snapshot["ciks"]["TEST1"] = snapshot["ciks"]["TEST0"]
	report = build_report(snapshot)
	assert report["counts"]["candidates"] == 2
	assert len(report["shortlist"]) == 1
	assert report["rows"][0]["metrics"]["sector_pe_n"] == 7
	with pytest.raises(ValueError, match="1 and 30"):
		build_report(snapshot, shortlist_size=31)


def test_unknown_issuer_sparse_peers_and_changed_period_are_explicit(snapshot):
	snapshot["ciks"].pop("TEST0")
	snapshot["quotes"] = snapshot["quotes"][:4]
	report = build_report(snapshot)
	row = next(r for r in report["rows"] if r["ticker"] == "TEST0")
	assert row["metrics"]["sector_pe_median"] is None
	assert not row["candidate"]
	assert any("identity" in f for f in row["flags"])


def test_no_api_fallback_for_unfetched_or_failed_fundamentals(snapshot):
	snapshot["details"].pop("TEST0")
	snapshot["details"]["TEST1"] = {"data": {}, "error": "Timeout", "observed_at": snapshot["observed_at"]}
	report = build_report(snapshot)
	assert not report["shortlist"]
	assert report["counts"]["fundamentals_failed"] == 1
	assert report["counts"]["fundamentals_fetched"] == 7


def test_replay_exports_and_source_binding(snapshot, tmp_path, monkeypatch):
	monkeypatch.setattr("smrik_fund.daily_cli.capture", lambda *a, **k: pytest.fail("Replay must not fetch"))
	source = tmp_path / "source.json"
	write_json(source, snapshot)
	output = tmp_path / "output"
	result = CliRunner().invoke(app, ["run", "--snapshot", str(source), "--output-dir", str(output)])
	assert result.exit_code == 0, result.output
	assert (output / "index.html").exists()
	assert (output / "briefs/TEST0.md").exists()
	packet = prepare_packet(output, "TEST0", thesis="Durable earnings may be underappreciated", question="What could invalidate the discount?")
	assert packet["company"]["metrics"]["pe"] == 10
	report = json.loads((output / "report.json").read_text())
	report["rows"][0]["metrics"]["pe"] = 1
	write_json(output / "report.json", report)
	with pytest.raises(ValueError, match="evidence differs"):
		prepare_packet(output, "TEST0", thesis="T", question="Q")


def test_provider_text_cannot_inject_html_csv_or_paths(snapshot, tmp_path):
	snapshot["details"]["TEST0"]["data"]["longName"] = "=1+1<script>alert(1)</script>"
	report = build_report(snapshot)
	export_report(report, tmp_path)
	assert "<script>alert(1)</script>" not in (tmp_path / "index.html").read_text()
	assert "'=1+1" in (tmp_path / "screen.csv").read_text(encoding="utf-8-sig")
	snapshot["quotes"][0]["symbol"] = "../escape"
	with pytest.raises(ValueError, match="ticker"):
		build_report(snapshot)


def test_capture_pagination_failure_and_free_cache_boundary(tmp_path, monkeypatch, snapshot):
	import yfinance as yf

	quote = snapshot["quotes"][0]
	monkeypatch.setattr("smrik_fund.market_screen.SECTORS", ("Technology",))
	monkeypatch.setattr(yf, "set_tz_cache_location", lambda *a: None)
	monkeypatch.setattr(yf, "screen", lambda *a, **k: {"total": 500, "quotes": [quote]})
	monkeypatch.setattr("smrik_fund.market_screen.get_detail", lambda *a, **k: snapshot["details"]["TEST0"])
	monkeypatch.setattr("edgar.reference.tickers.get_company_tickers", lambda: pd.DataFrame([{"ticker": "TEST0", "cik": 1}]))
	result = capture(tmp_path, progress=lambda x: None)
	assert len(result["quotes"]) == 1
	assert result["issues"] and "captured 1 of 500" in result["issues"][0]
	assert result["paid_calls"] == 0


def packet_for(snapshot, tmp_path):
	report = build_report(snapshot)
	write_json(tmp_path / "snapshot.json", snapshot)
	export_report(report, tmp_path)
	return prepare_packet(tmp_path, "TEST0", thesis="Possible normalized earnings discount", question="What would falsify this?")


def prices_and_budget(tmp_path):
	today = datetime.now(UTC).date().isoformat()
	prices = {
		"model": "test-model", "service_tier": "default", "endpoint_host": "api.openai.com",
		"observed_date": today, "valid_through": today, "fx_observation_date": today,
		"input_usd_per_million": .2, "cached_read_usd_per_million": .02,
		"cache_write_usd_per_million": .25, "output_usd_per_million": 1.2,
		"input_wrapper_allowance_tokens": 1024, "max_input_tokens": 272000,
		"reservation_headroom": 1.25, "endpoint_uplift": 1.0, "usd_per_eur": 1.1,
	}
	path = tmp_path / "budget.json"
	initialize_budget(path, ceiling_eur=5, final_review_reserve_eur=.5, prices=prices)
	return prices, path


def test_ic_default_cannot_spend_and_nonshortlist_cannot_escalate(snapshot, tmp_path):
	packet = packet_for(snapshot, tmp_path)
	client = SimpleNamespace(responses=SimpleNamespace(create=lambda **k: pytest.fail("No paid call authorized")))
	result = run_ic(packet, tmp_path / "ic", client=client)
	assert result["status"] == "PREPARED_NO_PAID_CALL"
	with pytest.raises(ValueError, match="restricted"):
		prepare_packet(tmp_path, "TEST1", thesis="T", question="Q")
	with pytest.raises(ValueError, match="mispricing thesis"):
		prepare_packet(tmp_path, "TEST0", thesis="", question="Q")


def test_ic_live_pricing_and_freshness_gates(snapshot, tmp_path):
	packet = packet_for(snapshot, tmp_path)
	prices, budget = prices_and_budget(tmp_path)
	prices["valid_through"] = "2000-01-01"
	with pytest.raises(ValueError):
		run_ic(packet, tmp_path / "stale-price", live=True, budget_path=budget, prices=prices)
	assert json.loads(budget.read_text())["calls"] == []
	packet["snapshot_observed_at"] = "2000-01-01T00:00:00+00:00"
	with pytest.raises(ValueError, match="Refresh"):
		run_ic(packet, tmp_path / "stale-data", live=True, budget_path=budget, prices=prices)


@pytest.mark.parametrize("failure", [None, "transport", "invalid_fact", "incomplete"])
def test_paid_transport_accounting_no_retries_and_evidence_gates(snapshot, tmp_path, failure):
	packet = packet_for(snapshot, tmp_path)
	prices, budget = prices_and_budget(tmp_path)
	calls = []
	assessment = {"priority": "investigate", "headline": "Verify earnings quality", "case_for": [{"text": "A sector discount merits attention", "fact_keys": ["pe" if failure != "invalid_fact" else "invented"]}], "case_against": [{"text": "Cash flow needs reconciliation", "fact_keys": ["vendor_fcf_yield"]}], "unknowns": ["Sustainability"], "work_plan": ["Read filings"], "catalyst_to_verify": "None verified"}
	def dispatch(**kwargs):
		calls.append(kwargs)
		if failure == "transport":
			raise TimeoutError()
		return {"id": "mock-response", "model": "test-model", "status": "incomplete" if failure == "incomplete" else "completed", "usage": {"input_tokens": 1000, "output_tokens": 100, "total_tokens": 1100}, "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(assessment)}]}]}
	client = SimpleNamespace(base_url="https://api.openai.com/v1", responses=SimpleNamespace(create=dispatch))
	if failure:
		with pytest.raises(ValueError):
			run_ic(packet, tmp_path / "ic", live=True, budget_path=budget, prices=prices, client=client)
	else:
		assert run_ic(packet, tmp_path / "ic", live=True, budget_path=budget, prices=prices, client=client)["status"] == "UNREVIEWED_IC_SYNTHESIS"
	assert len(calls) == 1
	ledger = json.loads(budget.read_text())
	assert len(ledger["calls"]) == 1
	assert ledger["calls"][0]["status"] == ("usage_unknown" if failure == "transport" else "completed")
	with pytest.raises(ValueError, match="already has an admission"):
		run_ic(packet, tmp_path / "retry", live=True, budget_path=budget, prices=prices, client=client)
	assert len(calls) == 1


def test_shortlist_changes_and_missing_ratios_are_visible(snapshot):
	old = build_report(snapshot)
	changed = copy.deepcopy(snapshot)
	changed["details"]["TEST0"]["data"]["freeCashflow"] = None
	report = build_report(changed, previous=old)
	assert report["changes"]["removed"] == ["TEST0"]
	row = analyze(changed["quotes"][0], changed, peer_references(changed, datetime.now(UTC)), datetime.now(UTC))
	assert row["metrics"]["vendor_fcf_yield"] is None


def test_interrupted_cache_is_refetched_without_inference(snapshot, tmp_path, monkeypatch):
	import yfinance as yf

	from smrik_fund.market_screen import get_detail

	(tmp_path / "TEST0.json").write_text('{"interrupted":')
	monkeypatch.setattr(yf, "Ticker", lambda ticker: SimpleNamespace(get_info=lambda: snapshot["details"][ticker]["data"]))
	assert get_detail("TEST0", tmp_path)["data"]["symbol"] == "TEST0"
	assert json.loads((tmp_path / "TEST0.json").read_text())["error"] is None


def test_deep_rejects_other_issuer_and_preserves_existing_output(snapshot, tmp_path, monkeypatch):
	packet_for(snapshot, tmp_path)
	monkeypatch.setattr("smrik_fund.company_case.validate_case", lambda path: {"information_cutoff": datetime.now(UTC).date().isoformat(), "ticker": "TEST0", "cik": "wrong"})
	monkeypatch.setattr("smrik_fund.company_run.run_case", lambda *a, **k: pytest.fail("Wrong issuer must not reach DCF"))
	output = tmp_path / "deep"
	result = CliRunner().invoke(app, ["deep", str(tmp_path), "TEST0", "--output-dir", str(output), "--case-dir", str(tmp_path / "source")])
	assert result.exit_code == 1 and "issuer differs" in result.output
	before = (output / "blocked.json").read_bytes()
	result = CliRunner().invoke(app, ["deep", str(tmp_path), "TEST0", "--output-dir", str(output)])
	assert result.exit_code == 1 and (output / "blocked.json").read_bytes() == before
