import json
import shutil
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import pytest

from smrik_fund import analysis_budget, analysis_transport
from smrik_fund import review_revision as revision

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS = ROOT / "data/build-guide-p10/parent-final-r6"
PRICES = revision.read(ROOT / "data/build-guide-p10/parent-preflight/sol-price-snapshot.json")


@pytest.fixture(scope="module")
def base_version(tmp_path_factory):
	root = tmp_path_factory.mktemp("review-base")
	path = root / "v1"
	original = revision.CURRENT
	try:
		revision.CURRENT = root / "authority/current-review.json"
		revision.export_base(ANALYSIS, path)
	finally:
		revision.CURRENT = original
	return path


@pytest.fixture(autouse=True)
def isolated_current(base_version, tmp_path, monkeypatch):
	# Replay the dated acceptance case at its recorded pricing date. Live
	# admission still rejects expired snapshots; historical tests do not age.
	class AcceptanceDate(date):
		@classmethod
		def today(cls):
			return cls.fromisoformat(PRICES["observed_date"])

	monkeypatch.setattr(analysis_budget, "date", AcceptanceDate)
	monkeypatch.setattr(analysis_transport, "date", AcceptanceDate)
	monkeypatch.setattr(revision, "CURRENT", tmp_path / "authority/current-review.json")
	revision._write_current(revision.validate_version(base_version))


def test_instruction_parser_is_bounded():
	assert revision.parse_instruction("set beta to 1.15") == {"kind": "change", "control": "beta", "value": 1.15}
	assert revision.parse_instruction("change terminal growth to 3%.")["value"] == 0.03
	assert revision.parse_instruction("research taxes: uncertain tax positions")["status"] == "QUEUED_NOT_ADOPTED"
	for text in ("set beta to 115%", "set beta to nan", "set beta to 1.15; run command", "investigate secret: credentials", "increase the value", "execute formula =1+1"):
		with pytest.raises(ValueError):
			revision.parse_instruction(text)


def test_actual_candidate_preview_confirmation_and_new_version(base_version, tmp_path, monkeypatch):
	prior = revision.validate_version(base_version)
	assert prior["is_current"] is True
	proposal_dir = tmp_path / "beta"
	proposal = revision.propose_revision(base_version, proposal_dir, instruction="set beta to 1.15", prices=PRICES)
	assert proposal["status"] == "AWAITING_CONFIRMATION"
	assert proposal["current_value"] == 1
	assert proposal["proposed_value"] == 1.15
	assert proposal["financial_impact"]["perShareValue"]["proposed"] == pytest.approx(210.06222140921045)
	assert not (proposal_dir / "reviewed-version/version.json").exists()
	assert revision.digest(Path(prior["model_path"])) == prior["model_sha256"]
	calls = []

	def independent(request, **kwargs):
		calls.append(kwargs)
		return {"verdict": "accept", "area": "dcf_terminal", "selection_id": proposal["selection_id"], "source_valid": True, "period_valid": True, "method_valid": True, "no_double_count": True, "cross_schedule_concerns_resolved": True, "concerns": [], "rationale": "Explicit higher-beta scenario, all statement values unchanged; lower DCF value is independently consistent."}, {"call_id": "offline-test-only", "resumed": len(calls) > 1}

	monkeypatch.setattr(revision, "dispatch_request", independent)
	build = revision._build
	write = revision.write_new

	def interrupted_build(*args):
		raise ValueError("Injected interruption after the reviewed model was saved")

	monkeypatch.setattr(revision, "_build", interrupted_build)
	with pytest.raises(ValueError, match="Injected interruption"):
		revision.confirm_revision(proposal_dir, prices=PRICES, budget_path=tmp_path / "unused-budget.json", development_confirmation=True)
	partial_model = proposal_dir / "reviewed-version/reviewed-model.json"
	partial_hash = revision.digest(partial_model)
	monkeypatch.setattr(revision, "_build", build)
	replace = revision.os.replace

	def interrupted_pointer(*args):
		raise OSError("Injected interruption before current pointer replacement")

	monkeypatch.setattr(revision.os, "replace", interrupted_pointer)
	with pytest.raises(OSError, match="pointer replacement"):
		revision.confirm_revision(proposal_dir, prices=PRICES, budget_path=tmp_path / "unused-budget.json", development_confirmation=True)
	assert revision.validate_version(base_version)["is_current"] is True
	monkeypatch.setattr(revision.os, "replace", replace)

	def interrupted_outcome(path, value):
		if path == proposal_dir / "outcome.json":
			raise OSError("Injected interruption after complete publication")
		return write(path, value)

	monkeypatch.setattr(revision, "write_new", interrupted_outcome)
	with pytest.raises(OSError, match="complete publication"):
		revision.confirm_revision(proposal_dir, prices=PRICES, budget_path=tmp_path / "unused-budget.json", development_confirmation=True)
	monkeypatch.setattr(revision, "write_new", write)
	result = revision.confirm_revision(proposal_dir, prices=PRICES, budget_path=tmp_path / "unused-budget.json", development_confirmation=True)
	assert result["status"] == "ADOPTED_NEW_VERSION"
	assert Path(result["version_dir"]).name == "reviewed-version-recovery"
	assert revision.digest(partial_model) == partial_hash
	assert result["human_approval"] is False
	new_version = revision.validate_version(Path(result["version_dir"]))
	assert new_version["prior_version"] == prior["version"]
	assert new_version["user_choices"]["beta"] == {"value": 1.15, "actor": "development_agent"}
	assert revision.confirm_revision(proposal_dir, prices=PRICES, budget_path=tmp_path / "unused-budget.json", development_confirmation=True) == result
	assert len(calls) == 3  # Real transport replays this exact request; completed retry skips dispatch.
	assert revision.read(proposal_dir / "review-transport.json") == {"call_id": "offline-test-only"}
	assert calls[0]["package"] == "p11"
	assert revision.validate_version(base_version)["is_current"] is False
	assert new_version["is_current"] is True
	assert new_version["current_version"] == new_version["version"]
	assert revision.read(proposal_dir / "confirmation.json")["human_financial_approval"] is False


def test_proposal_only_tampering_is_rejected_and_growth_evidence_is_sent(base_version, tmp_path, monkeypatch):
	proposal_dir = tmp_path / "growth"
	proposal = revision.propose_revision(base_version, proposal_dir, control="terminal_growth", value=0.03, prices=PRICES)
	request = revision.read(proposal_dir / "review-request.json")
	payload = json.loads(request["input"].split("\n")[1])
	assert "AREA-PACKET:dcf_terminal" in payload["source_records"]
	monkeypatch.setattr(revision, "dispatch_request", lambda *args, **kwargs: pytest.fail("Tampered proposal cannot dispatch"))
	for key, value in {"proposed_value": 0.04, "current_value": 0.01, "control": "beta", "selection_id": "different", "base_version": "v0", "source_refs": ["MKT-BETA"], "financial_impact": {}}.items():
		(proposal_dir / "proposal.json").write_text(json.dumps({**proposal, key: value}))
		with pytest.raises(ValueError, match="STALE_CONTEXT"):
			revision.confirm_revision(proposal_dir, prices=PRICES, budget_path=tmp_path / "unused-budget.json", development_confirmation=True)
	assert not (proposal_dir / "confirmation.json").exists()
	assert not (proposal_dir / "reviewed-version").exists()


def test_version_metadata_and_user_choices_are_bound(base_version, tmp_path):
	copy = tmp_path / "copy"
	shutil.copytree(base_version, copy)
	version = revision.read(copy / "version.json")
	for name in ("model", "workbook", "snapshot"):
		version[f"{name}_path"] = str(copy / Path(version[f"{name}_path"]).name)
	(copy / "version.json").write_text(json.dumps(version))
	assert revision.validate_version(copy)["is_current"] is False
	for key, value in {"review_metadata_hash": "wrong", "prior_version": "v0", "user_choices": {"beta": {"value": 1.15, "actor": "cli_user"}}}.items():
		(copy / "version.json").write_text(json.dumps({**version, key: value}))
		with pytest.raises(ValueError, match="STALE_CONTEXT"):
			revision.validate_version(copy)
	model_path = Path(version["model_path"])
	original = revision.read(model_path)
	for binding in ("selected_model_sha256", "financial_snapshot_sha256", "source_context_sha256"):
		model = json.loads(json.dumps(original))
		model["review_metadata"]["bindings"][binding] = "wrong"
		model_path.write_text(json.dumps(model))
		(copy / "version.json").write_text(json.dumps({**version, "model_sha256": revision.digest(model_path), "review_metadata_hash": revision.content_hash(model["review_metadata"])}))
		with pytest.raises(ValueError, match="financial or source bindings"):
			revision.validate_version(copy)


def test_decline_and_stale_candidate_never_publish(base_version, tmp_path, monkeypatch):
	proposal_dir = tmp_path / "decline"
	revision.propose_revision(base_version, proposal_dir, control="beta", value=0.85, prices=PRICES)
	monkeypatch.setattr(revision, "dispatch_request", lambda *args, **kwargs: pytest.fail("Declined/stale proposals cannot dispatch"))
	result = revision.confirm_revision(proposal_dir, prices=PRICES, budget_path=tmp_path / "unused-budget.json", reject=True, development_confirmation=True)
	assert result["status"] == "DECLINED"
	assert not (proposal_dir / "reviewed-version/version.json").exists()
	path = proposal_dir / "candidate-model.json"
	model = revision.read(path)
	model["valuation_policy"]["beta"] = 1.2
	path.write_text(json.dumps(model))
	with pytest.raises(ValueError, match="STALE_CONTEXT"):
		revision.confirm_revision(proposal_dir, prices=PRICES, budget_path=tmp_path / "unused-budget.json")


def test_failed_rebuild_and_research_keep_prior_version(base_version, tmp_path, monkeypatch):
	prior = revision.validate_version(base_version)
	result = revision.propose_revision(base_version, tmp_path / "research", instruction="investigate leases: lease commencement timing", prices=PRICES)
	assert result["status"] == "QUEUED_NOT_ADOPTED"
	assert not (tmp_path / "research/review-request.json").exists()

	def fail_build(*args):
		raise ValueError("MECHANICAL_FAILURE: test-injected candidate build failure")

	monkeypatch.setattr(revision, "_build", fail_build)
	with pytest.raises(ValueError, match="MECHANICAL_FAILURE"):
		revision.propose_revision(base_version, tmp_path / "failed", control="beta", value=1.15, prices=PRICES)
	assert revision.read(tmp_path / "failed/outcome.json")["status"] == "FAILED_CANDIDATE"
	assert revision.validate_version(base_version) == prior
	with pytest.raises(ValueError, match="authoritative base version is already current"):
		revision.export_base(ANALYSIS, base_version)


def test_publication_lock_blocks_another_process(tmp_path):
	marker = tmp_path / "child-acquired.txt"
	ready = tmp_path / "child-ready.txt"
	script = (
		"import sys\n"
		"from pathlib import Path\n"
		f"sys.path.insert(0, {str(ROOT / 'src')!r})\n"
		"from smrik_fund import review_revision as revision\n"
		"revision.CURRENT = Path(sys.argv[1])\n"
		"Path(sys.argv[3]).write_text('ready')\n"
		"with revision._publication_lock():\n"
		"    Path(sys.argv[2]).write_text('acquired')\n"
	)
	with revision._publication_lock():
		process = subprocess.Popen(
			[sys.executable, "-c", script, str(revision.CURRENT), str(marker), str(ready)],
			cwd=ROOT,
		)
		deadline = time.monotonic() + 10
		while not ready.exists() and time.monotonic() < deadline and process.poll() is None:
			time.sleep(0.05)
		assert ready.exists(), "Child must reach the lock before checking exclusion"
		time.sleep(0.2)
		assert not marker.exists()
	assert process.wait(timeout=10) == 0
	assert marker.read_text() == "acquired"


def test_competing_revision_from_stale_head_never_dispatches(base_version, tmp_path, monkeypatch):
	first_dir = tmp_path / "first"
	second_dir = tmp_path / "second"
	first = revision.propose_revision(base_version, first_dir, control="beta", value=0.85, prices=PRICES)
	revision.propose_revision(base_version, second_dir, control="terminal_growth", value=0.03, prices=PRICES)
	calls = []

	def independent(request, **kwargs):
		calls.append(request)
		return {"verdict": "accept", "area": "dcf_terminal", "selection_id": first["selection_id"], "source_valid": True, "period_valid": True, "method_valid": True, "no_double_count": True, "cross_schedule_concerns_resolved": True, "concerns": [], "rationale": "Accepted test scenario."}, {"call_id": "offline-test-only"}

	monkeypatch.setattr(revision, "dispatch_request", independent)
	result = revision.confirm_revision(first_dir, prices=PRICES, budget_path=tmp_path / "unused-budget.json", development_confirmation=True)
	assert revision.validate_version(Path(result["version_dir"]))["is_current"] is True
	with pytest.raises(ValueError, match="expected prior version is no longer current"):
		revision.confirm_revision(second_dir, prices=PRICES, budget_path=tmp_path / "unused-budget.json", development_confirmation=True)
	assert len(calls) == 1
	assert not (second_dir / "independent-review.json").exists()
