import copy
import json
from pathlib import Path

import pytest

from smrik_fund.analysis_budget import initialize_budget
from smrik_fund.operating_forecast import (
    COST_LINES,
    PERIODS,
    OperatingForecastError,
    OperatingProposal,
    OperatingReview,
    _build_mog_authority,
    _dispatch,
    build_evidence_packet,
    build_operating_model,
    default_proposal,
    run_reasoning,
)

ROOT = Path(__file__).resolve().parents[1]
P2 = ROOT / "data" / "build-guide-p2-r2" / "MSFT"
PRICES = json.loads((ROOT / "docs" / "API_COST_SNAPSHOT.json").read_text(encoding="utf-8"))


class Dumpable:
    def __init__(self, value):
        self.value = value

    def model_dump(self, mode="json"):
        return self.value


class NativeResponse:
    id = "resp-p6-test"
    model = "gpt-5.6-luna"

    def __init__(self, value):
        self.output_parsed = value
        self.usage = Dumpable({"input_tokens": 100, "output_tokens": 80, "total_tokens": 180, "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 20}})


class QueueResponses:
    def __init__(self, values):
        self.values = list(values)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        value = self.values.pop(0)
        if isinstance(value, Exception):
            raise value
        return NativeResponse(value)


class QueueClient:
    def __init__(self, values):
        self.responses = QueueResponses(values)


def budget(tmp_path):
    path = tmp_path / "budget.json"
    initialize_budget(path, ceiling_eur=5.0, final_review_reserve_eur=0.5, prices=PRICES)
    return path


def packet():
    return build_evidence_packet(P2)


def accepted_review():
    return OperatingReview(
        verdict="accept", evidence_strength="mixed", method_valid=True, source_valid=True,
        period_valid=True, segment_reconciliation_valid=True, cost_treatment_valid=True,
        no_double_count=True, concerns=["Bounded estimate."], required_revision=None,
        target="none", rationale="Accepted after independent review.",
    )


def revise_review(target="segment_growth"):
    return accepted_review().model_copy(update={
        "verdict": "revise", "target": target,
        "required_revision": f"Change the bounded {target} trajectory.",
    })


def test_p6_bridge_removes_embedded_baseline_and_adds_schedule_once():
    value = packet()
    value["embedded_ppe_baseline"] = {"ttm_ppe_depreciation": 10.0, "ttm_revenue": 100.0, "ratio": 0.1, "basis": "test baseline"}
    value["scheduled_depreciation"] = [1.0] * len(PERIODS)
    candidate = default_proposal(value)
    model = build_operating_model(value, candidate, accepted_review())
    for index in range(len(PERIODS)):
        gross = model["gross_cost_total"][index]
        embedded = model["embedded_ppe_depreciation"][index]
        assert model["expense_bridge"]["total_operating_expenses"][index] == pytest.approx(gross - embedded + 1.0)
        assert model["forecast_operating_income"][index] == pytest.approx(model["forecast_revenue"][index] - gross + embedded - 1.0)


def test_mog_failure_preserves_subprocess_output(tmp_path, monkeypatch):
    from smrik_fund import operating_forecast as module

    value = packet()
    candidate = default_proposal(value)
    command_seen = []

    def fail(*args, **kwargs):
        command_seen.append(args[0])
        raise module.subprocess.CalledProcessError(1, args[0], output="mog stdout", stderr="mog stderr")

    monkeypatch.setattr(module.subprocess, "run", fail)
    authority_dir = tmp_path / "mog-authority"
    with pytest.raises(OperatingForecastError, match="stdout=.*mog-preview.stdout.log.*stderr=.*mog-preview.stderr.log"):
        _build_mog_authority({}, value, candidate, authority_dir)
    assert command_seen[0][2] == "preview"
    model = json.loads((authority_dir / "model-input.json").read_text(encoding="utf-8"))
    assert model["operating_decision"]["status"] == "REVIEW_REQUIRED"
    assert model["operating_forecast"]["decision"]["status"] == "REVIEW_REQUIRED"
    assert (authority_dir / "mog-preview.stdout.log").read_text(encoding="utf-8") == "mog stdout"
    assert (authority_dir / "mog-preview.stderr.log").read_text(encoding="utf-8") == "mog stderr"


def test_zero_and_missing_prior_ytd_are_distinct():
    value = packet()
    missing = copy.deepcopy(value)
    missing["segment_history"]["Intelligent Cloud"]["revenue"]["PRIOR"] = None
    with pytest.raises(OperatingForecastError, match="Missing prior comparable YTD"):
        default_proposal(missing)
    zero = copy.deepcopy(value)
    zero["segment_history"]["Intelligent Cloud"]["revenue"]["PRIOR"] = 0
    with pytest.raises(OperatingForecastError, match="Zero prior comparable YTD"):
        default_proposal(zero)


def test_incompatible_comparability_blocks_source_packet(monkeypatch):
    from smrik_fund import operating_forecast as module

    original = module._fact

    def mismatched(rows, concept, period, *, segment=None):
        fact = original(rows, concept, period, segment=segment)
        if segment == "Intelligent Cloud" and period == "Current YTD":
            fact = {**fact, "segment_definition": (("us-gaap:StatementBusinessSegmentsAxis", "other_member", "Other"),)}
        return fact

    monkeypatch.setattr(module, "_fact", mismatched)
    with pytest.raises(OperatingForecastError, match="Incompatible segment period definition"):
        build_evidence_packet(P2)


def test_changed_source_context_cannot_reuse_a_prior_run(tmp_path):
    value = packet()
    run_dir = tmp_path / "run"
    run_reasoning(value, run_dir, budget(tmp_path), offline=True)
    changed = copy.deepcopy(value)
    changed["consolidated"]["revenue"]["CURRENT_YTD"] += 1
    with pytest.raises(OperatingForecastError, match="run context changed"):
        run_reasoning(changed, run_dir, budget(tmp_path / "second"), offline=True)


def test_exact_completed_request_resumes_once_and_unknown_request_is_held(tmp_path):
    value = packet()
    candidate = default_proposal(value)
    first_client = QueueClient([candidate])
    kwargs = {"instruction": "resume exact", "payload": {"packet": value}, "response_model": OperatingProposal, "run_dir": tmp_path / "resume", "budget_path": budget(tmp_path)}
    first, _ = _dispatch("p6-resume-1", client=first_client, **kwargs)
    second, metadata = _dispatch("p6-resume-1", client=first_client, **kwargs)
    assert first.model_dump() == second.model_dump()
    assert metadata["resumed"] is True
    assert len(first_client.responses.calls) == 1

    class Failing:
        def create(self, **kwargs):
            raise RuntimeError("unknown transport")

    failing = type("Client", (), {"responses": Failing()})()
    unknown_kwargs = {"instruction": "hold exact", "payload": {"packet": value}, "response_model": OperatingProposal, "run_dir": tmp_path / "unknown", "budget_path": budget(tmp_path / "unknown-budget")}
    with pytest.raises(OperatingForecastError, match="failed after admission"):
        _dispatch("p6-unknown-1", client=failing, **unknown_kwargs)
    with pytest.raises(OperatingForecastError, match="explicit recovery required"):
        _dispatch("p6-unknown-2", client=first_client, **unknown_kwargs)


def test_revise_runs_consequential_analyst_revision_and_independent_recheck(tmp_path):
    value = packet()
    value["embedded_ppe_baseline"] = {"ttm_ppe_depreciation": 10.0, "ttm_revenue": 100.0}
    original = default_proposal(value)
    revised = original.model_copy(update={"segment_trajectories": [item.model_copy(update={"stub_growth": item.stub_growth + 0.01}) if item.segment == "Intelligent Cloud" else item for item in original.segment_trajectories]})
    client = QueueClient([original, revise_review(), revised, accepted_review()])
    authority_calls = []
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    earlier_hold = {"candidate": original.model_dump(mode="json"), "decision": {"status": "MOG_AUTHORITY_INCOMPLETE", "selected_candidate": None}}
    (run_dir / "terminal-outcome.json").write_text(json.dumps(earlier_hold), encoding="utf-8")
    (run_dir / "decision-held.json").write_text(json.dumps(earlier_hold["decision"]), encoding="utf-8")

    def authority(candidate, stage):
        authority_calls.append((stage, candidate.model_dump()))
        return {"status": "PASS", "engine": "Mog SDK", "scheduled_depreciation": [1.0] * len(PERIODS)}

    proposal, review, model = run_reasoning(value, tmp_path / "run", budget(tmp_path), client=client, authoritative_builder=authority)
    assert proposal.model_dump() == revised.model_dump()
    assert review.verdict == "accept"
    assert model["decision"]["status"] == "SYSTEM_REVIEWED_PROVISIONAL"
    assert len(client.responses.calls) == 4
    assert [stage for stage, _ in authority_calls] == ["analyst-initial", "analyst-revision"]
    assert model["expense_bridge"]["status"] == "AUTHORITATIVE_MOG"
    assert (tmp_path / "run" / "candidate-revision.json").exists()
    terminal = json.loads((run_dir / "terminal-outcome.json").read_text(encoding="utf-8"))
    assert terminal["candidate"] == revised.model_dump(mode="json")
    assert terminal["review"] == review.model_dump(mode="json")
    assert terminal["decision"]["status"] == "SYSTEM_REVIEWED_PROVISIONAL"
    assert terminal["decision"]["context_hash"] == model["decision"]["context_hash"]
    assert terminal["decision"]["selected_candidate"] == terminal["candidate"]
    history = list((run_dir / "terminal-history").glob("*.json"))
    assert len(history) == 1
    assert json.loads(history[0].read_text(encoding="utf-8")) == earlier_hold
    assert json.loads((run_dir / "decision-held.json").read_text(encoding="utf-8")) == earlier_hold["decision"]


def test_incomplete_revision_preserves_prior_candidate_without_publication(tmp_path):
    value = packet()
    original = default_proposal(value)
    client = QueueClient([original, revise_review(), RuntimeError("incomplete revision")])
    with pytest.raises(OperatingForecastError, match="revision incomplete"):
        run_reasoning(value, tmp_path / "run", budget(tmp_path), client=client)
    assert (tmp_path / "run" / "terminal-outcome.json").exists()
    assert not (tmp_path / "run" / "model.json").exists()


def test_reject_preserves_no_new_publication(tmp_path):
    value = packet()
    original = default_proposal(value)
    rejected = accepted_review().model_copy(update={"verdict": "reject", "evidence_strength": "weak", "method_valid": False, "source_valid": False, "period_valid": False, "segment_reconciliation_valid": False, "cost_treatment_valid": False, "no_double_count": False, "concerns": ["Rejected."], "rationale": "Rejected."})
    client = QueueClient([original, rejected])
    with pytest.raises(OperatingForecastError, match="review failed"):
        run_reasoning(value, tmp_path / "run", budget(tmp_path), client=client)
    assert json.loads((tmp_path / "run" / "decision-held.json").read_text(encoding="utf-8"))["status"] == "REJECTED_BY_REVIEW"
    assert not (tmp_path / "run" / "model.json").exists()


def test_cost_lines_remain_consolidated():
    value = packet()
    model = build_operating_model(value, default_proposal(value), accepted_review())
    assert set(model["costs"]) == set(COST_LINES)
