import copy
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from smrik_fund.analysis_budget import initialize_budget, reserve_call
from smrik_fund.asset_forecast import (
    ENDPOINT_HOST,
    P5_TASK_ID,
    AssetForecastError,
    AssetProposal,
    AssetReview,
    _call_request,
    build_evidence_packet,
    default_offline_candidate,
    expand_evidence,
    run_reasoning,
    validate_proposal,
)


@pytest.mark.parametrize("needs_correction", [False, True])
def test_independent_review_and_explicit_development_revision(tmp_path, needs_correction):
    value = packet()
    candidate = default_offline_candidate(value, remaining_life=8.0)
    request = candidate.model_copy(update={
        "outcome": "request_evidence", "method_id": None, "method_version": None,
        "parameters": [], "evidence_refs": ["E1"], "sensitivities": [],
        "follow_up_request": "lease_treatment", "rationale": "Need the lease disclosure context.",
    })
    accepted = AssetReview(
        verdict="accept", evidence_strength="mixed", method_valid=True,
        source_valid=True, period_valid=True, cash_noncash_separated=True,
        depreciation_base_valid=True, concerns=["Remaining life is an uncertain proxy."],
        required_revision=None, target_parameter="none", target_direction="none",
        rationale="Valid provisional estimate with visible uncertainty.",
    )
    first_review = accepted.model_copy(update={
        "verdict": "revise", "method_valid": False,
        "required_revision": "Reduce the remaining-life estimate using the evidence.",
        "target_parameter": "opening_remaining_life_years", "target_direction": "lower",
    }) if needs_correction else accepted
    revised = default_offline_candidate(value, remaining_life=7.0)
    client = QueueClient([request, candidate, first_review, revised, accepted])
    run_dir = tmp_path / "run"
    result = run_reasoning(packet=value, run_dir=run_dir, budget_path=budget(tmp_path), client=client)
    original = json.loads((run_dir / "review-original.json").read_text())
    revision_request = json.loads((run_dir / "revision-request.json").read_text())
    assert original["verdict"] == ("revise" if needs_correction else "accept")
    assert revision_request["requested_by"] == ("system_review" if needs_correction else "development_controller")
    assert result["decision"]["revision"]["kind"] == ("correction" if needs_correction else "development_what_if")
    assert result["decision"]["mechanical_validation_status"] == "PENDING_MODEL_BUILD"
    assert "all_periods_validated" not in result["decision"]
    assert result["decision"]["status"] == "SYSTEM_REVIEWED_PROVISIONAL"
    assert len(client.responses.calls) == 5


def test_cli_reports_nonadoptable_status_without_false_pass(tmp_path, monkeypatch, capsys):
    import smrik_fund.asset_forecast as module

    monkeypatch.setattr(module, "run_reasoning", lambda **kwargs: {
        "attempt_count": 1, "committed_eur": 0.01,
        "decision": {"status": "CAPABILITY_GAP", "selected_candidate": None},
    })
    module._run_cli(SimpleNamespace(
        p2_root=P2, legacy_source=LEGACY, budget=tmp_path / "unused-budget.json",
        run_dir=tmp_path / "run", offline=False,
    ))
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "CAPABILITY_GAP"
    assert result["decision"]["selected_candidate"] is None


@pytest.mark.parametrize("change,message", [
    ({"base": 9.0}, "base differs"),
    ({"low": 0.0}, "supported method range"),
    ({"low": 8.0, "high": 8.0}, "no variation"),
])
def test_sensitivity_matches_selected_method_and_has_real_variation(change, message):
    value = packet()
    candidate = default_offline_candidate(value, remaining_life=8.0)
    candidate.sensitivities[0] = candidate.sensitivities[0].model_copy(update=change)
    with pytest.raises(AssetForecastError, match=message):
        validate_proposal(candidate, value)


ROOT = Path(__file__).resolve().parents[1]
P2 = ROOT / "data" / "build-guide-p2-r2" / "MSFT"
LEGACY = ROOT / "data" / "MSFT" / "01_source" / "edgar" / "filings" / "0000950170-25-100235.txt"
PRICES = json.loads((ROOT / "docs" / "API_COST_SNAPSHOT.json").read_text(encoding="utf-8"))


def packet():
    return build_evidence_packet(P2, LEGACY)


def budget(tmp_path):
    path = tmp_path / "budget.json"
    initialize_budget(path, ceiling_eur=5.0, final_review_reserve_eur=0.5, prices=PRICES)
    return path


def test_asset_task_receives_fixed_development_context_without_false_filing_sources():
    from smrik_fund.asset_forecast import _proposal_payload, _review_payload

    value = packet()
    candidate = default_offline_candidate(value)
    payload = _proposal_payload(value, instruction="Estimate assets")
    supplied = payload["provided_development_parameters"]
    assert set(supplied) == {"lease_additions_modeled", "tax_rate", "revenue_growth", "wacc", "terminal_growth"}
    assert "opening_remaining_life_years" not in supplied
    assert supplied["wacc"]["evidence_refs"] == []
    assert supplied["wacc"]["basis"] == "estimated"
    assert payload["contract"]["implemented_methods"][candidate.method_id]["version"] == candidate.method_version
    assert _review_payload(value, candidate, purpose="Review")["provided_development_parameters"] == supplied
    assert validate_proposal(candidate, value) == candidate
    changed = copy.deepcopy(candidate)
    next(p for p in changed.parameters if p.name == "wacc").value = 0.09
    with pytest.raises(AssetForecastError, match="Application-supplied development parameter changed"):
        validate_proposal(changed, value)
    false_citation = copy.deepcopy(candidate)
    next(p for p in false_citation.parameters if p.name == "wacc").evidence_refs = ["E3"]
    with pytest.raises(AssetForecastError, match="Application-supplied development parameter changed"):
        validate_proposal(false_citation, value)
    unsourced_asset = copy.deepcopy(candidate)
    unsourced_asset.parameters[0].evidence_refs = []
    with pytest.raises(AssetForecastError, match="Asset estimate lacks supporting context"):
        validate_proposal(unsourced_asset, value)


def test_asset_citations_cover_asset_evidence_without_forcing_unused_balance_sheet_citation():
    value = packet()
    candidate = default_offline_candidate(value)
    candidate.evidence_refs.remove("E2")
    assert validate_proposal(candidate, value) == candidate
    candidate.evidence_refs.remove("E6")
    with pytest.raises(AssetForecastError, match="required latest"):
        validate_proposal(candidate, value)


def test_source_packet_preserves_latest_asset_facts_and_policy_hash():
    value = packet()
    assert value["measurement_date"] == "2026-03-31"
    assert value["facts"]["ppe_note"] == {
        "gross": 394951.0,
        "accumulated_depreciation": 111723.0,
        "net": 283228.0,
        "land": 9813.0,
        "finance_lease_net_included_in_ppe": 44015.0,
    }
    assert value["facts"]["calculated"]["opening_depreciable_net_ppe"] == 273415.0
    assert value["facts"]["ttm"]["cash_ppe_payments"]["value"] == 97225.0
    assert value["facts"]["calculated"]["ttm_ppe_depreciation"] == 30300.0
    assert "stock" in value["facts"]["ppe_payables"]["basis"]
    assert "fy25_ppe_payable_stock_to_cash_flow_ratio" in value["facts"]["calculated"]
    assert "noncash_to_cash" not in " ".join(value["facts"]["calculated"])
    evidence = {item["evidence_id"]: item for item in value["evidence"]}
    assert "Land is not depreciated." in evidence["E6"]["excerpt"]
    assert evidence["E7"]["source_sha256"] == "0fcd3d977b4a3312e97e5a6bc69eac11d267bb1390d325cf19136bab1782ce5e"
    assert "opening asset age profile by category" in value["unavailable"]


def test_followup_allowlist_uses_real_packets_and_rejects_arbitrary_paths():
    value = packet()
    expansion = expand_evidence(value, "useful_life_policy")
    assert expansion["status"] == "fulfilled"
    assert [item["evidence_id"] for item in expansion["evidence"]] == ["E6"]
    with pytest.raises(AssetForecastError, match="outside the allowlist"):
        expand_evidence(value, "C:\\secrets\\anything")


def test_candidate_validation_rejects_unsupported_or_duplicated_financial_methods():
    value = packet()
    candidate = default_offline_candidate(value)
    assert validate_proposal(candidate, value) == candidate
    bad_method = candidate.model_copy(update={"method_id": "invented_age_profile"})
    with pytest.raises(AssetForecastError, match="Unsupported asset method"):
        validate_proposal(bad_method, value)
    bad_lease = copy.deepcopy(candidate)
    bad_lease.parameters[5].value = 1.0
    with pytest.raises(AssetForecastError, match="lease additions"):
        validate_proposal(bad_lease, value)
    missing_source = copy.deepcopy(candidate)
    missing_source.evidence_refs = ["E1", "E2", "E3"]
    with pytest.raises(AssetForecastError, match="required latest"):
        validate_proposal(missing_source, value)
    duplicate = copy.deepcopy(candidate)
    duplicate.parameters.append(copy.deepcopy(duplicate.parameters[0]))
    with pytest.raises(AssetForecastError, match="repeats"):
        validate_proposal(duplicate, value)
    mislabelled_noncash = copy.deepcopy(candidate)
    noncash = next(
        item
        for item in mislabelled_noncash.parameters
        if item.name == "noncash_ppe_additions_ratio"
    )
    noncash.basis = "calculated"
    with pytest.raises(AssetForecastError, match="period-addition flow"):
        validate_proposal(mislabelled_noncash, value)


class Dumpable:
    def __init__(self, value):
        self.value = value

    def model_dump(self, mode="json"):
        return self.value


class NativeResponse:
    id = "resp_test"
    model = "gpt-5.6-luna"

    def __init__(self, parsed):
        self.output_parsed = parsed
        self.usage = Dumpable({"input_tokens": 100, "output_tokens": 80, "total_tokens": 180, "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 20}})

    def model_dump(self, mode="json"):
        return {"id": self.id, "model": self.model, "output_parsed": self.output_parsed.model_dump(mode=mode), "usage": self.usage.model_dump(mode=mode)}


class QueueResponses:
    def __init__(self, values):
        self.values = list(values)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return NativeResponse(self.values.pop(0))


class QueueClient:
    def __init__(self, values):
        self.responses = QueueResponses(values)


def test_native_structured_dispatch_records_usage_and_full_schema(tmp_path):
    value = packet()
    candidate = default_offline_candidate(value)
    client = QueueClient([candidate])
    from smrik_fund.asset_forecast import _dispatch

    parsed, metadata = _dispatch(
        stage="native-test",
        run_dir=tmp_path / "run",
        budget_path=budget(tmp_path),
        system_prompt="test structured prompt",
        payload={"packet": value, "schema_version": "test"},
        client=client,
    )
    assert isinstance(parsed, AssetProposal)
    assert metadata["usage"]["total_tokens"] == 180
    request = client.responses.calls[0]
    assert request["reasoning"] == {"effort": "high"}
    assert request["service_tier"] == "default"
    assert request["tools"] == []
    assert request["background"] is False
    assert request["text"]["format"]["type"] == "json_schema"
    assert request["text"]["format"]["strict"] is True
    assert request["text"]["format"]["name"] == "asset_proposal"
    assert json.loads((tmp_path / "run" / "attempts" / "01-native-test.request.json").read_text()) == request
    assert metadata["endpoint"] == "https://api.openai.com/v1/responses"
    assert (tmp_path / "run" / "attempts" / "01-native-test.request.json").exists()
    state = json.loads((tmp_path / "budget.json").read_text(encoding="utf-8"))
    assert state["calls"][0]["status"] == "completed"
    assert state["calls"][0]["latest_outcome"]["usage"]["total_tokens"] == 180


def test_unknown_provider_failure_is_held_in_budget_ledger(tmp_path):
    class FailingResponses:
        def create(self, **kwargs):
            raise RuntimeError("transport test failure")

    client = SimpleNamespace(responses=FailingResponses())
    from smrik_fund.asset_forecast import _dispatch

    with pytest.raises(AssetForecastError, match="failed after admission"):
        _dispatch(
            stage="transport-test",
            run_dir=tmp_path / "run",
            budget_path=budget(tmp_path),
            system_prompt="test prompt",
            payload={"packet": packet()},
            client=client,
        )
    state = json.loads((tmp_path / "budget.json").read_text(encoding="utf-8"))
    assert state["calls"][0]["status"] == "usage_unknown"
    assert state["calls"][0]["latest_outcome"]["usage"] is None


def test_raw_response_and_usage_are_saved_before_structured_validation(tmp_path):
    class InvalidResponse:
        id = "resp_invalid"
        model = "gpt-5.6-luna"
        output_text = '{"outcome":"propose_forecast"}'
        usage = Dumpable(
            {
                "input_tokens": 20,
                "output_tokens": 10,
                "total_tokens": 30,
                "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                "output_tokens_details": {"reasoning_tokens": 0},
            }
        )

        def model_dump(self, mode="json"):
            return {
                "id": self.id,
                "model": self.model,
                "output_text": self.output_text,
                "usage": self.usage.model_dump(mode=mode),
            }

    class Responses:
        def create(self, **kwargs):
            return InvalidResponse()

    client = SimpleNamespace(responses=Responses())
    from smrik_fund.asset_forecast import _dispatch

    with pytest.raises(AssetForecastError, match="invalid structured output"):
        _dispatch(
            stage="invalid-structured",
            run_dir=tmp_path / "run",
            budget_path=budget(tmp_path),
            system_prompt="invalid output test",
            payload={"packet": packet()},
            client=client,
        )
    attempt = tmp_path / "run" / "attempts"
    assert (attempt / "01-invalid-structured.response.json").exists()
    assert (attempt / "01-invalid-structured.outcome.json").exists()
    state = json.loads((tmp_path / "budget.json").read_text(encoding="utf-8"))
    assert state["calls"][0]["status"] == "completed"


def test_completed_stage_resumes_exact_request_without_a_second_dispatch(tmp_path):
    value = packet()
    candidate = default_offline_candidate(value)
    client = QueueClient([candidate])
    from smrik_fund.asset_forecast import _dispatch

    kwargs = {
        "stage": "resumable-test",
        "run_dir": tmp_path / "run",
        "budget_path": budget(tmp_path),
        "system_prompt": "resume me",
        "payload": {"packet": value},
        "client": client,
    }
    first, first_meta = _dispatch(**kwargs)
    second, second_meta = _dispatch(**kwargs)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first_meta.get("resumed") is not True
    assert second_meta["resumed"] is True
    assert len(client.responses.calls) == 1
    state = json.loads((tmp_path / "budget.json").read_text(encoding="utf-8"))
    assert len(state["calls"]) == 1


def test_reserved_ledger_admission_without_local_outcome_is_held(tmp_path):
    value = packet()
    path = tmp_path / "run"
    attempts = path / "attempts"
    attempts.mkdir(parents=True)
    budget_path = budget(tmp_path)
    payload = {"packet": value}
    request = _call_request("crash window", payload)
    (attempts / "01-crash-window.request.json").write_text(
        json.dumps(request), encoding="utf-8"
    )
    reserve_call(
        budget_path,
        call_id=f"{P5_TASK_ID}-01-crash-window",
        task_id=P5_TASK_ID,
        request=request,
        endpoint_host=ENDPOINT_HOST,
        today=date.today(),
    )
    client = QueueClient([default_offline_candidate(value)])
    from smrik_fund.asset_forecast import _dispatch

    with pytest.raises(AssetForecastError, match="held ledger admission"):
        _dispatch(
            stage="crash-window",
            run_dir=path,
            budget_path=budget_path,
            system_prompt="crash window",
            payload=payload,
            client=client,
        )
    assert client.responses.calls == []


def test_capability_gap_is_retained_without_forced_review_or_followup(tmp_path):
    value = packet()
    outcome = AssetProposal(
        outcome="capability_gap",
        method_id=None,
        method_version=None,
        parameters=[],
        evidence_refs=["E1", "E2", "E3"],
        rationale="The packet has no defensible asset age profile.",
        alternatives=[],
        uncertainty=["A category allocation is unavailable."],
        sensitivities=[],
        follow_up_request=None,
    )
    client = QueueClient([outcome])
    result = run_reasoning(
        packet=value,
        run_dir=tmp_path / "run",
        budget_path=budget(tmp_path),
        client=client,
    )
    assert result["decision"]["status"] == "CAPABILITY_GAP"
    assert result["decision"]["selected_candidate"] is None
    assert len(client.responses.calls) == 1
    assert (tmp_path / "run" / "terminal-outcome.json").exists()


def test_revision_direction_is_checked_before_final_review(tmp_path):
    value = packet()
    initial = AssetProposal(
        outcome="request_evidence",
        method_id=None,
        method_version=None,
        parameters=[],
        evidence_refs=["E1", "E2", "E3", "E4", "E5"],
        rationale="The disclosed policy detail is needed.",
        alternatives=[],
        uncertainty=["The remaining-life proxy is not disclosed."],
        sensitivities=[],
        follow_up_request="useful_life_policy",
    )
    base = default_offline_candidate(value, remaining_life=8.0)
    bad_revision = default_offline_candidate(value, remaining_life=9.0)
    review = AssetReview(
        verdict="revise",
        evidence_strength="mixed",
        method_valid=True,
        source_valid=True,
        period_valid=True,
        cash_noncash_separated=True,
        depreciation_base_valid=True,
        concerns=["Life remains a proxy."],
        required_revision="Lower the life proxy.",
        target_parameter="opening_remaining_life_years",
        target_direction="lower",
        rationale="Use one lower bounded what-if.",
    )
    client = QueueClient([initial, base, review, bad_revision])
    with pytest.raises(AssetForecastError, match="did not move lower"):
        run_reasoning(
            packet=value,
            run_dir=tmp_path / "run",
            budget_path=budget(tmp_path),
            client=client,
        )
    assert (tmp_path / "run" / "candidate-revision-v2.json").exists()
    assert len(client.responses.calls) == 4


def test_reviewed_revision_preserves_candidates_and_changes_one_target(tmp_path):
    value = packet()
    initial = AssetProposal(
        outcome="request_evidence",
        method_id=None,
        method_version=None,
        parameters=[],
        evidence_refs=["E1", "E2", "E3", "E4", "E5"],
        rationale="Lease policy detail is needed before selecting a method.",
        alternatives=[],
        uncertainty=["Future lease additions remain unresolved."],
        sensitivities=[],
        follow_up_request="lease_treatment",
    )
    followup = default_offline_candidate(value, remaining_life=8.0)
    revision = default_offline_candidate(value, remaining_life=7.0)
    review = AssetReview(
        verdict="revise",
        evidence_strength="mixed",
        method_valid=True,
        source_valid=True,
        period_valid=True,
        cash_noncash_separated=True,
        depreciation_base_valid=True,
        concerns=["Remaining life is an estimate."],
        required_revision="Lower the remaining-life proxy by one bounded year.",
        target_parameter="opening_remaining_life_years",
        target_direction="lower",
        rationale="A targeted life sensitivity is required before provisional selection.",
    )
    final_review = AssetReview(
        verdict="accept",
        evidence_strength="mixed",
        method_valid=True,
        source_valid=True,
        period_valid=True,
        cash_noncash_separated=True,
        depreciation_base_valid=True,
        concerns=["P8B lease policy remains open."],
        required_revision=None,
        target_parameter="none",
        target_direction="none",
        rationale="The bounded revision is internally consistent and remains provisional.",
    )
    client = QueueClient([initial, followup, review, revision, final_review])
    result = run_reasoning(packet=value, run_dir=tmp_path / "run", budget_path=budget(tmp_path), client=client)
    assert result["decision"]["status"] == "SYSTEM_REVIEWED_PROVISIONAL"
    assert result["decision"]["changed_parameter"] == "opening_remaining_life_years"
    assert (tmp_path / "run" / "candidate-initial.json").exists()
    assert (tmp_path / "run" / "candidate-followup.json").exists()
    assert (tmp_path / "run" / "candidate-revision-v2.json").exists()
    assert (tmp_path / "run" / "review-original.json").exists()
    assert (tmp_path / "run" / "review-revision.json").exists()
    assert result["candidate"].parameters[0].value == 7.0
    assert len(client.responses.calls) == 5


def test_request_hash_includes_schema_and_payload():
    first = _call_request("prompt", {"a": 1})
    second = _call_request("prompt", {"a": 2})
    assert first["text"]["format"]["schema"] == second["text"]["format"]["schema"]
    assert first["input"] != second["input"]


def test_native_review_schema_requires_nullable_revision_field():
    request = _call_request(
        "review prompt", {"candidate": 1}, response_model=AssetReview
    )
    review_format = request["text"]["format"]
    assert review_format["name"] == "asset_review"
    assert "required_revision" in review_format["schema"]["required"]
    assert review_format["schema"]["properties"]["required_revision"]["anyOf"][-1] == {
        "type": "null"
    }
