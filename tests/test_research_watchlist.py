"""Watchlist persistence, provenance, freshness and local HTTP boundaries."""

import copy
import json
import re
import threading
from datetime import UTC, datetime, timedelta
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from test_daily_research import snapshot as snapshot
from test_research_workspace import screen_case

from smrik_fund.daily_research import build_report, export_report
from smrik_fund.market_screen import write_json
from smrik_fund.research_watchlist import (
	load_watchlist,
	save_entry,
	screener,
	watchlist,
)
from smrik_fund.research_workspace import make_server


def edit(ticker="TEST0", revision=0, **changes):
	return {
		"revision": revision,
		"entry": {
			"ticker": ticker,
			"stage": "Idea",
			"review_price": None,
			"thesis": "",
			"risks": "",
			"next_step": "",
			**changes,
		},
	}


def test_notes_persist_archive_restore_and_conflicting_edits_are_not_lost(tmp_path):
	assert load_watchlist(tmp_path)["entries"] == []
	saved = save_entry(
		edit("test0", thesis="<script>alert(1)</script>", review_price=12), tmp_path
	)
	assert saved["entries"][0]["ticker"] == "TEST0"
	assert load_watchlist(tmp_path) == saved
	before = (tmp_path / "workspace/watchlist.json").read_bytes()
	with pytest.raises(ValueError, match="another tab"):
		save_entry(edit(thesis="overwrite"), tmp_path)
	assert (tmp_path / "workspace/watchlist.json").read_bytes() == before
	archived = save_entry(
		edit(revision=1, stage="Archived", thesis=saved["entries"][0]["thesis"]),
		tmp_path,
	)
	assert archived["entries"][0]["added_at"] == saved["entries"][0]["added_at"]
	restored = save_entry(
		edit(revision=2, stage="Researching", thesis=archived["entries"][0]["thesis"]),
		tmp_path,
	)
	assert restored["entries"][0]["thesis"] == "<script>alert(1)</script>"


@pytest.mark.parametrize("price", [0, -1, True, "10", float("nan"), float("inf")])
def test_invalid_review_prices_do_not_write(tmp_path, price):
	with pytest.raises(ValueError, match="positive USD"):
		save_entry(edit(review_price=price), tmp_path)
	assert load_watchlist(tmp_path)["revision"] == 0


@pytest.mark.parametrize(
	"change",
	[
		{"ticker": "../private"},
		{"stage": "Buy now"},
		{"thesis": 12},
		{"risks": "a" * 2001},
		{"paid": True},
	],
)
def test_invalid_fields_do_not_write(tmp_path, change):
	with pytest.raises(ValueError):
		save_entry(edit(**change), tmp_path)


def test_thirty_active_companies_archive_retains_notes_and_frees_space(tmp_path):
	for i in range(30):
		save_entry(edit(f"TEST{i}", i), tmp_path)
	with pytest.raises(ValueError, match="30 active"):
		save_entry(edit("NEW", 30), tmp_path)
	save_entry(edit("TEST0", 30, stage="Archived", thesis="Retained"), tmp_path)
	saved = save_entry(edit("NEW", 31), tmp_path)
	assert len(saved["entries"]) == 31
	assert sum(x["stage"] != "Archived" for x in saved["entries"]) == 30


def test_full_universe_precedes_newer_small_screen(tmp_path, snapshot):
	broad = screen_case(tmp_path, snapshot)
	small = copy.deepcopy(snapshot)
	small["scope"] = "explicit US watchlist"
	small["quotes"] = small["quotes"][:1]
	path = tmp_path / "workspace/runs/newer"
	write_json(path / "snapshot.json", small)
	export_report(
		build_report(small, now=datetime.now(UTC) + timedelta(minutes=1)), path
	)
	result = screener(data_root=tmp_path)
	assert result["screen"]["id"] == broad.relative_to(tmp_path).as_posix()
	assert len(result["rows"]) == 9
	assert (
		screener("workspace/runs/newer", tmp_path)["screen"]["counts"]["universe"] == 1
	)


def test_review_price_is_separate_from_scenario_and_stale_data_cannot_trigger(
	tmp_path, snapshot
):
	path = screen_case(tmp_path, snapshot)
	original = (path / "report.json").read_bytes()
	save_entry(edit(review_price=12, stage="Waiting for price"), tmp_path)
	item = watchlist(tmp_path)["items"][0]
	assert item["review_gap"] == pytest.approx(10 / 12 - 1)
	assert item["at_review_price"]
	assert item["company"]["shortlisted"]
	later = datetime.now(UTC) + timedelta(days=9)
	item = watchlist(tmp_path, later)["items"][0]
	assert item["company"]["quote_status"] == "Stale"
	assert item["company"]["candidate"]  # original frozen conclusion is preserved
	assert not item["company"]["candidate_now"]
	assert item["review_gap"] is None and not item["at_review_price"]
	assert (path / "report.json").read_bytes() == original
	save_entry(edit(revision=1, review_price=12, stage="Archived"), tmp_path)
	assert not watchlist(tmp_path)["items"][0]["at_review_price"]


@pytest.mark.parametrize(
	"field,value",
	[
		("currency", "EUR"),
		("regularMarketTime", None),
		("regularMarketPrice", None),
		("regularMarketTime", 9999999999),
	],
)
def test_missing_currency_or_bad_quote_cannot_trigger(tmp_path, snapshot, field, value):
	snapshot["details"]["TEST0"]["data"][field] = value
	screen_case(tmp_path, snapshot)
	save_entry(edit(review_price=12), tmp_path)
	item = watchlist(tmp_path)["items"][0]
	assert item["review_gap"] is None
	assert not item["at_review_price"]
	if field == "regularMarketPrice":
		assert item["company"]["metrics"]["price"] is None


def test_newest_quote_selected_and_tampering_never_reaches_watchlist(
	tmp_path, snapshot
):
	screen_case(tmp_path, snapshot)
	newer = copy.deepcopy(snapshot)
	now = datetime.now(UTC) + timedelta(minutes=2)
	newer["details"]["TEST0"]["data"].update(
		regularMarketPrice=8, regularMarketTime=int(now.timestamp())
	)
	path = tmp_path / "workspace/runs/newer"
	write_json(path / "snapshot.json", newer)
	export_report(build_report(newer, now=now), path)
	save_entry(edit(review_price=9), tmp_path)
	assert watchlist(tmp_path, now)["items"][0]["company"]["metrics"]["price"] == 8
	report = json.loads((path / "report.json").read_text())
	report["rows"][0]["metrics"]["price"] = 1
	write_json(path / "report.json", report)
	result = watchlist(tmp_path, now)
	assert result["items"][0]["company"]["metrics"]["price"] == 10
	assert not result["items"][0]["at_review_price"]
	assert any("excluded from watchlist" in issue for issue in result["issues"])
	with pytest.raises(ValueError, match="evidence"):
		screener("workspace/runs/newer", tmp_path)


def test_unknown_ticker_has_no_invented_metrics_and_paths_are_confined(tmp_path):
	save_entry(edit("UNKNOWN", thesis="Research first"), tmp_path)
	item = watchlist(tmp_path)["items"][0]
	assert item["company"] is None and item["review_gap"] is None
	with pytest.raises(ValueError, match="leaves"):
		screener("../../private", tmp_path)


def test_watchlist_http_routes_require_local_session_and_do_not_expose_saved_file(
	tmp_path, snapshot
):
	screen_case(tmp_path, snapshot)
	server = make_server(tmp_path, port=0)
	thread = threading.Thread(target=server.serve_forever, daemon=True)
	thread.start()
	base = f"http://127.0.0.1:{server.server_port}"
	try:
		with urlopen(base + "/screener") as response:
			page = response.read().decode()
		token = re.search(r'const token\s*=\s*"([^"]+)"', page)[1]
		body = json.dumps(edit(review_price=12)).encode()
		for headers in (
			{},
			{"X-Workbench-Token": token, "Origin": "https://evil.example"},
		):
			with pytest.raises(HTTPError) as exc:
				urlopen(Request(base + "/api/watchlist", data=body, headers=headers))
			assert exc.value.code == 403
		with urlopen(
			Request(
				base + "/api/watchlist", data=body, headers={"X-Workbench-Token": token}
			)
		) as response:
			assert json.load(response)["revision"] == 1
		with urlopen(base + "/api/watchlist") as response:
			assert json.load(response)["items"][0]["review_gap"] == pytest.approx(
				10 / 12 - 1
			)
		with urlopen(base + "/api/screener") as response:
			assert len(json.load(response)["rows"]) == 9
		with pytest.raises(HTTPError) as exc:
			urlopen(base + "/files/workspace/watchlist.json")
		assert exc.value.code == 404
		with pytest.raises(HTTPError) as exc:
			urlopen(base + "/api/screener?screen=..%2F..%2Fprivate")
		assert exc.value.code == 400
	finally:
		server.shutdown()
		server.server_close()
		thread.join(timeout=5)
