import json
from datetime import date
from types import SimpleNamespace

import pytest

from smrik_fund import calibration

TODAY = date(2026, 9, 8)


@pytest.fixture
def ledger(tmp_path):
	path = tmp_path / "budget.json"
	state = calibration.read(calibration.BUDGET)
	# Isolated not-yet-admitted fixture, also valid after the optional real calibration.
	state["calls"] = [call for call in state["calls"] if call["task_id"] != calibration.TASK_ID]
	path.write_text(json.dumps(state))
	return path


def test_preflight_changes_only_reasoning_and_never_dispatches_or_reserves(ledger, tmp_path):
	before = ledger.read_bytes()
	client = SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs: pytest.fail("Preflight cannot dispatch")))
	result = calibration.run(budget_path=ledger, output_dir=tmp_path / "unused", today=TODAY, client=client)
	assert result["status"] == "PREPARED_NO_CALL"
	assert result["admission_estimate"]["reserved_eur"] == pytest.approx(0.0496361964377904)
	assert ledger.read_bytes() == before
	assert not (tmp_path / "unused").exists()


def test_single_mock_call_records_raw_usage_and_blocks_another_attempt(ledger, tmp_path):
	structured = calibration.read(calibration.ROOT / "data/build-guide-p8d/parent-review-correction-r7/attempts/06-review-reassessment.structured.json")
	baseline = next(call for call in calibration.read(ledger)["calls"] if call["call_id"] == "p8d-msft-other-balances-06-review-reassessment")
	raw = {"id": "offline-calibration-test", "status": "completed", "model": "gpt-5.6-luna", "service_tier": "default", "usage": baseline["latest_outcome"]["usage"], "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(structured)}]}]}
	client = SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs: raw))
	result = calibration.run(execute_approved_transfer=True, budget_path=ledger, output_dir=tmp_path / "run", today=TODAY, client=client)
	assert result["status"] == "RECORDED_AWAITING_PARENT_COMPARISON"
	assert result["model_adoption"] is False
	assert result["alternative"]["business_flags_pass"]
	assert (tmp_path / "run/response.json").exists()
	assert calibration.read(ledger)["calls"][-1]["status"] == "completed"
	with pytest.raises(ValueError, match="single attempt"):
		calibration.run(execute_approved_transfer=True, budget_path=ledger, output_dir=tmp_path / "another", today=TODAY, client=client)


def test_failed_dispatch_retains_hold_and_original_ledger_records(ledger, tmp_path):
	before = calibration.read(ledger)["calls"]

	def fail(**kwargs):
		raise TimeoutError("Sensitive provider text must not be persisted")

	client = SimpleNamespace(responses=SimpleNamespace(create=fail))
	with pytest.raises(ValueError, match="usage unknown"):
		calibration.run(execute_approved_transfer=True, budget_path=ledger, output_dir=tmp_path / "failed", today=TODAY, client=client)
	state = calibration.read(ledger)
	assert state["calls"][:-1] == before
	assert state["calls"][-1]["status"] == "usage_unknown"
	assert calibration.read(tmp_path / "failed/transport-error.json") == {"error_type": "TimeoutError"}
	with pytest.raises(ValueError, match="single attempt"):
		calibration.prepare(budget_path=ledger, today=TODAY)


def test_budget_exhaustion_and_changed_task_block_preflight(ledger, tmp_path):
	state = calibration.read(ledger)
	state["ceiling_eur"] = 1.54
	ledger.write_text(json.dumps(state))
	with pytest.raises(ValueError, match="BUDGET_EXHAUSTED"):
		calibration.prepare(budget_path=ledger, today=TODAY)
	manifest = calibration.read(calibration.MANIFEST)
	request = calibration.read(calibration.ROOT / manifest["alternative"]["request_path"])
	request["max_output_tokens"] = 8000
	request_path = tmp_path / "changed-request.json"
	request_path.write_text(json.dumps(request))
	manifest["alternative"]["request_path"] = str(request_path)
	manifest["alternative"]["request_hash"] = calibration.content_hash(request)
	manifest_path = tmp_path / "manifest.json"
	manifest_path.write_text(json.dumps(manifest))
	with pytest.raises(ValueError, match="only the reasoning"):
		calibration.prepare(manifest_path=manifest_path, budget_path=ledger, today=TODAY)
