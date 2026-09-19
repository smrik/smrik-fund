"""Workbench contracts: evidence binding, durable failures, and local-only writes."""

import json
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from test_daily_research import snapshot as snapshot

from smrik_fund.daily_research import build_report, export_report
from smrik_fund.market_screen import write_json
from smrik_fund.research_audit import audit_run, verify_screen, within_data
from smrik_fund.research_workflow import run_deep
from smrik_fund.research_workspace import (
	job_arguments,
	jobs,
	make_server,
	save_job,
	start_job,
	watch_worker,
)


def screen_case(root, snapshot):
	path = root / "daily/screen"
	path.mkdir(parents=True)
	write_json(path / "snapshot.json", snapshot)
	export_report(build_report(snapshot), path)
	return path


def test_audit_reproduces_decisions_and_detects_tampering(tmp_path, snapshot):
	path = screen_case(tmp_path, snapshot)
	assert audit_run(path, tmp_path)["integrity"] == "PASS"
	report = verify_screen(path)
	report["rows"][0]["method"] = "Changed method"
	write_json(path / "report.json", report)
	assert audit_run(path, tmp_path)["integrity"] == "FAIL"
	with pytest.raises(ValueError, match="company evidence"):
		verify_screen(path)


def test_deep_rejects_tampered_issuer_before_fetch(tmp_path, snapshot, monkeypatch):
	path = screen_case(tmp_path, snapshot)
	report = verify_screen(path)
	report["rows"][0]["issuer_cik"] = "999"
	write_json(path / "report.json", report)
	monkeypatch.setattr(
		"smrik_fund.company_case.freeze_company",
		lambda *a: pytest.fail("No provider call allowed"),
	)
	output = tmp_path / "stopped"
	with pytest.raises(ValueError, match="company evidence"):
		run_deep(path, "TEST0", output)
	blocked = json.loads((output / "blocked.json").read_text())
	assert blocked["stage"] == "selection"
	assert blocked["paid_calls"] == 0


def test_native_failure_preserves_inputs_and_stage(tmp_path, snapshot, monkeypatch):
	path = screen_case(tmp_path, snapshot)
	manifest = {
		"ticker": "TEST0",
		"cik": "0",
		"information_cutoff": datetime.now(UTC).date().isoformat(),
		"measurement_date": "2026-06-30",
	}
	monkeypatch.setattr("smrik_fund.company_case.freeze_company", lambda *a: manifest)

	def fail_run(ticker, source, output, *, live, assumptions, progress):
		assert live is False
		assert assumptions["controls"]["share_price_proxy"] == 10
		progress("excel", "RUNNING", "Opening native Excel")
		raise OSError("Excel unavailable")

	monkeypatch.setattr("smrik_fund.company_run.run_case", fail_run)
	output = tmp_path / "stopped"
	with pytest.raises(OSError, match="Excel unavailable"):
		run_deep(path, "TEST0", output)
	blocked = (output / "blocked.json").read_text()
	assert json.loads(blocked)["stage"] == "excel"
	assert (output / "deep-inputs.json").is_file()
	events = [
		json.loads(line) for line in (output / "events.jsonl").read_text().splitlines()
	]
	assert events[-1]["status"] == "BLOCKED"
	assert any(e["phase"] == "sources" and e["status"] == "PASS" for e in events)
	with pytest.raises(ValueError, match="new/empty"):
		run_deep(path, "TEST0", output)
	assert (output / "blocked.json").read_text() == blocked


@pytest.mark.parametrize(
	"payload",
	[
		{"action": "paid"},
		{"action": "screen", "live": True},
		{"action": "screen", "tickers": "MSFT;whoami"},
		{"action": "deep", "ticker": "MSFT", "screen": "../private"},
	],
)
def test_only_free_typed_jobs_are_admitted(tmp_path, payload):
	with pytest.raises(ValueError):
		job_arguments(payload, tmp_path / "out", tmp_path)


def test_parallel_jobs_rejected(tmp_path, monkeypatch):
	monkeypatch.setattr(
		"smrik_fund.research_workspace.subprocess.Popen",
		lambda *a, **kw: threading.Event(),
	)
	job = start_job({"action": "screen", "tickers": "MSFT"}, tmp_path)
	assert job["status"] == "QUEUED"
	assert job["paid_calls"] == 0
	with pytest.raises(ValueError, match="already active"):
		start_job({"action": "screen", "tickers": "META"}, tmp_path)


def test_worker_death_releases_admission_and_preserves_failure(tmp_path, monkeypatch):
	path = tmp_path / "workspace/jobs/test.json"
	save_job(path, {"status": "RUNNING", "pid": 999999, "paid_calls": 0})
	monkeypatch.setattr(
		"smrik_fund.research_workspace.process_alive", lambda pid: False
	)
	assert jobs(tmp_path)[0]["status"] == "FAILED"
	assert "partial outputs" in jobs(tmp_path)[0]["reason"]


def test_early_worker_crash_retains_receipt(tmp_path):
	from types import SimpleNamespace

	path = tmp_path / "job.json"
	save_job(path, {"status": "QUEUED"})
	watch_worker(SimpleNamespace(wait=lambda: None, returncode=1), path)
	assert json.loads(path.read_text())["status"] == "FAILED"


def test_http_requires_local_origin_token_and_confined_paths(tmp_path, monkeypatch):
	monkeypatch.setattr(
		"smrik_fund.research_workspace.subprocess.Popen",
		lambda *a, **kw: threading.Event(),
	)
	server = make_server(tmp_path, port=0)
	thread = threading.Thread(target=server.serve_forever, daemon=True)
	thread.start()
	base = f"http://127.0.0.1:{server.server_port}"
	try:
		with urlopen(base, timeout=5) as response:
			page = response.read().decode()
			assert (
				"style-src 'self' 'unsafe-inline'"
				in response.headers["Content-Security-Policy"]
			)
		token = re.search(r'const token\s*=\s*"([^"]+)"', page)[1]
		with urlopen(base + "/tokens.css", timeout=5) as response:
			assert response.headers.get_content_type() == "text/css"
			assert b"--color-paper:" in response.read()
		body = json.dumps({"action": "screen", "tickers": "META"}).encode()
		for headers in (
			{},
			{"X-Workbench-Token": token, "Origin": "https://evil.example"},
			{"X-Workbench-Token": token, "Host": "evil.example"},
		):
			with pytest.raises(HTTPError) as err:
				urlopen(
					Request(base + "/api/jobs", data=body, headers=headers), timeout=5
				)
			assert err.value.code == 403
		with urlopen(
			Request(
				base + "/api/jobs", data=body, headers={"X-Workbench-Token": token}
			),
			timeout=5,
		) as response:
			assert response.status == 202
		for route in (
			"/other.css",
			"/tokens.css/../pyproject.toml",
			"/files/../secret",
			"/files/%2e%2e/secret",
			"/files/.env",
			"/files/workspace/jobs/test.log",
		):
			with pytest.raises(HTTPError) as err:
				urlopen(base + route, timeout=5)
			assert err.value.code in {400, 404}
	finally:
		server.shutdown()
		server.server_close()
		thread.join(timeout=5)


def test_source_paths_stay_inside_data(tmp_path):
	with pytest.raises(ValueError, match="leaves"):
		within_data(tmp_path / "../private", tmp_path)


@pytest.fixture
def published_run(tmp_path):
	"""Synthetic receipts test integrity detection, not Excel financial correctness."""
	from test_company_case import filing

	from smrik_fund.analysis_budget import content_hash
	from smrik_fund.company_case import freeze_filings
	from smrik_fund.research_audit import file_hash

	run = tmp_path / "workspace/runs/example"
	source = run / "source"
	manifest = freeze_filings("AAPL", "2025-10-31", [filing()], source)
	reviewed = run / "reviewed"
	reviewed.mkdir()
	model = {
		"case_dir": str(source),
		"case_hash": content_hash(manifest),
		"controls": {},
		"measurement_date": "2025-09-27",
		"information_cutoff": "2025-10-31",
	}
	write_json(reviewed / "model.json", model)
	write_json(
		reviewed / "snapshot.json",
		{
			"mechanical": "PASS",
			"valuation_gate": "PASS",
			"per_share_value": 10,
			"wacc": 0.1,
			"enterprise_value": 100,
			"equity_value": 100,
		},
	)
	(reviewed / "AAPL.xlsx").write_bytes(b"synthetic test artifact")
	write_json(
		run / "native-excel-proof.json",
		{"status": "PASS", "native_beta_edit": "PASS", "per_share_value": 10},
	)
	version = {
		"ticker": "AAPL",
		"status": "PROVISIONAL_UNREVIEWED",
		"case_hash": content_hash(manifest),
		"native_excel_proof_sha256": file_hash(run / "native-excel-proof.json"),
	}
	for filename, field in (
		("model.json", "model_sha256"),
		("snapshot.json", "snapshot_sha256"),
		("AAPL.xlsx", "workbook_sha256"),
	):
		version[field] = file_hash(reviewed / filename)
	write_json(run / "version.json", version)
	assert audit_run(run, tmp_path)["integrity"] == "PASS"
	return run


def test_frozen_template_audit_detects_changes(published_run, tmp_path):
	from smrik_fund.research_audit import file_hash

	run = published_run
	(run / "template.xlsx").write_bytes(b"synthetic template")
	(run / "template.json").write_text("{}")
	model_path = run / "reviewed/model.json"
	model = json.loads(model_path.read_text())
	model["workbook_template"] = {
		"sha256": file_hash(run / "template.xlsx"),
		"contract_sha256": file_hash(run / "template.json"),
	}
	write_json(model_path, model)
	version_path = run / "version.json"
	version = json.loads(version_path.read_text())
	version["model_sha256"] = file_hash(model_path)
	write_json(version_path, version)
	assert audit_run(run, tmp_path)["integrity"] == "PASS"
	(run / "template.xlsx").write_bytes(b"changed template")
	result = audit_run(run, tmp_path)
	assert result["integrity"] == "FAIL"
	assert (
		next(c for c in result["checks"] if c["label"] == "Unchanged template.xlsx")[
			"status"
		]
		== "FAIL"
	)


@pytest.mark.parametrize(
	"relative",
	[
		"reviewed/model.json",
		"reviewed/snapshot.json",
		"reviewed/AAPL.xlsx",
		"native-excel-proof.json",
		"source/0000320193-25-000079/source.txt",
	],
)
def test_published_artifact_tampering_is_visible(published_run, tmp_path, relative):
	path = published_run / relative
	# Appending whitespace leaves JSON readable but changes its published hash.
	with path.open("ab") as stream:
		stream.write(b" ")
	audit = audit_run(published_run, tmp_path)
	assert audit["integrity"] == "FAIL"
	assert any(c["status"] == "FAIL" for c in audit["checks"])


def test_missing_source_manifest_is_not_an_integrity_pass(published_run, tmp_path):
	(published_run / "source/case.json").unlink()
	assert audit_run(published_run, tmp_path)["integrity"] == "FAIL"


def test_company_audit_detects_changed_selection_receipt(
	published_run, tmp_path, snapshot
):
	from smrik_fund.research_audit import file_hash

	screen = screen_case(tmp_path, snapshot)
	write_json(
		published_run / "deep-inputs.json",
		{
			"screen": str(screen),
			"report_sha256": file_hash(screen / "report.json"),
			"snapshot_hash": verify_screen(screen)["snapshot_hash"],
		},
	)
	assert audit_run(published_run, tmp_path)["integrity"] == "PASS"
	with (screen / "report.json").open("ab") as stream:
		stream.write(b" ")
	audit = audit_run(published_run, tmp_path)
	assert audit["integrity"] == "FAIL"
	assert any(
		"Selected screen changed" in check.get("reason", "")
		for check in audit["checks"]
	)


def test_unpublished_candidate_has_source_checks_without_false_binding_failure(
	published_run, tmp_path
):
	(published_run / "version.json").unlink()
	write_json(
		published_run / "blocked.json",
		{"ticker": "AAPL", "status": "BLOCKED", "reason": "Native Excel unavailable"},
	)
	audit = audit_run(published_run, tmp_path)
	assert audit["status"] == "BLOCKED"
	assert audit["integrity"] == "PASS"
	assert "valuation" not in audit
	assert any("Unpublished candidate" in warning for warning in audit["warnings"])


@pytest.mark.parametrize("ticker", ["KO", "HD"])
def test_additional_real_statement_bridges(ticker, tmp_path):
	from smrik_fund.company_run import build
	from smrik_fund.portable_model import prepare_model

	case = (
		Path(__file__).resolve().parents[1] / f"data/coverage/20260919/{ticker}/source"
	)
	if not case.exists():
		pytest.skip("Optional frozen SEC coverage case is not downloaded")
	model = prepare_model(case)
	if ticker == "KO":
		flow = model["history"]
		assert "equity_income_after_tax" not in flow
		for period in ("annual", "current_ytd", "prior_ytd", "ttm"):
			assert flow["net_income"][period] == pytest.approx(
				flow["net_income_parent"][period] + flow["minority_income"][period]
			)
			assert flow["pretax"][period] - flow["net_income"][period] == pytest.approx(
				flow["tax"][period]
			)
	else:
		assert model["opening"]["current_debt"] == 8945
		assert model["opening"]["long_debt"] == 43951
		assert any("Already counted" in a["basis"] for a in model["allocations"])
	result = build(model, tmp_path / ticker)
	assert result["mechanical"] == result["valuation_gate"] == "PASS"
