import copy
import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from smrik_fund.analysis_budget import content_hash, initialize_budget
from smrik_fund.financing import (
    PERIODS,
    FinancingError,
    FinancingProposal,
    _proposal_payload,
    _review_payload,
    _run_context,
    _strict_schema,
    build_evidence_packet,
    build_financing_model,
    calibrate_rate,
    default_proposal,
    forecast_values,
    prepare_live_handoff,
    review_proposal,
    run_offline,
    run_reasoning,
)

ROOT = Path(__file__).resolve().parents[1]
P8A = ROOT / "data" / "build-guide-p8a" / "live-r5" / "model-input.json"
PRICES = json.loads((ROOT / "docs" / "API_COST_SNAPSHOT.json").read_text(encoding="utf-8"))


def accepted_p8a() -> dict:
    return json.loads(P8A.read_text(encoding="utf-8"))


def packet_and_proposal():
    packet = build_evidence_packet(accepted_p8a())
    return packet, default_proposal(packet)


def test_source_packet_preserves_opening_containment_and_source_shape():
    packet, _ = packet_and_proposal()

    assert packet["source_row_count"] == 84
    assert packet["facts"]["debt"]["face"] == 46156
    assert packet["facts"]["debt"]["carrying"] == 40262
    assert sum(packet["facts"]["debt"]["contra"].values()) == -5894
    assert packet["facts"]["operating_lease"]["liability"] == pytest.approx(22238)
    assert packet["facts"]["operating_lease"]["current_liability"] + packet["facts"]["operating_lease"]["noncurrent_liability"] == pytest.approx(22238)
    assert packet["facts"]["finance_lease"]["current_liability"] + packet["facts"]["finance_lease"]["noncurrent_liability"] == pytest.approx(62932)
    assert packet["facts"]["pipeline"]["undiscounted_commitments"] == 196600
    assert packet["accepted_upstream"]["model_sha256"] == content_hash(accepted_p8a())
    commercial_paper = next(row for row in packet["source_rows"] if row["line_item"] == "commercial_paper_historical")
    assert "28-152 days" in commercial_paper["limitation"]


def test_calibration_is_bounded_and_hits_the_opening_liability():
    rate = calibrate_rate([100, 110], ["2027-03-31", "2028-03-31"], 190)
    assert 0 <= rate <= 0.25
    pv = 100 / (1 + rate) ** (365 / 365) + 110 / (1 + rate) ** (731 / 365)
    assert pv == pytest.approx(190, abs=1e-7)
    with pytest.raises(FinancingError, match="outside bounded"):
        calibrate_rate([1], ["2027-03-31"], 1000)


def test_forecast_contains_debt_contra_release_and_full_opening_runoff():
    packet, proposal = packet_and_proposal()
    forecast = forecast_values(packet, proposal)
    debt = forecast["debt"]
    assert debt["closing_face"] == [46156.0] * len(PERIODS)
    assert debt["cash_repayment"][1] == 9250
    assert debt["cash_repayment"][3] == 2016
    assert debt["contra_release_expense"][1] == pytest.approx(1181.2007106335038)
    assert debt["closing_contra"][3] == pytest.approx(-4455.361383135453)

    operating = forecast["operating_opening_pool"]
    finance = forecast["finance_opening_pool"]
    assert forecast["opening_calibration"]["operating_rate"] == pytest.approx(0.03023893501492514)
    assert forecast["opening_calibration"]["finance_rate"] == pytest.approx(0.04293296045256223)
    assert operating["full_runoff_final_closing"] == pytest.approx(0, abs=1e-5)
    assert operating["closing_asset"][-1] == pytest.approx(0, abs=1e-5)
    assert finance["full_runoff_final_closing"] == pytest.approx(0, abs=1e-5)
    assert len(finance["full_runoff"]) == 15
    tail = forecast["debt_tail_alternative"]
    assert tail["redemption"][5:] == pytest.approx([34890 / 6] * 6)
    assert tail["proceeds"][5:] == pytest.approx([0] * 6)
    assert tail["closing_face"][-1] == pytest.approx(11266)
    names = {item["name"] for item in forecast["pipeline_sensitivities"]["scenarios"]}
    assert names == {
        "finance_share_50pct", "finance_share_90pct",
        "front_loaded_commencement", "back_loaded_commencement",
        "new_rates_minus_100bp", "new_rates_plus_100bp",
    }
    front_loaded = next(item for item in forecast["pipeline_sensitivities"]["scenarios"] if item["name"] == "front_loaded_commencement")
    assert front_loaded["operating_expense"][1:7] == pytest.approx([front_loaded["operating_expense"][1]] * 6)
    assert front_loaded["operating_expense"][7:] == pytest.approx([0] * 4)
    life_names = {item["name"] for item in forecast["opening_finance_life_sensitivities"]}
    assert life_names == {"opening_finance_life_10y", "opening_finance_life_13y", "opening_finance_life_16y"}


def test_pipeline_is_day_weighted_and_has_no_commencement_period_service():
    packet, proposal = packet_and_proposal()
    pipeline = forecast_values(packet, proposal)["pipeline"]

    assert sum(pipeline["weights"]) == pytest.approx(1)
    assert sum(pipeline["cohort_totals"]) == pytest.approx(196600)
    first = pipeline["visible"][0]
    assert first["operating_additions"] > 0
    assert first["finance_additions"] > 0
    assert first["operating_payment"] == 0
    assert first["finance_payment"] == 0
    assert first["operating_expense"] == 0
    assert first["finance_depreciation"] == 0
    assert all(set(item) >= {"operating_interest", "finance_interest", "operating_principal", "finance_principal"} for item in pipeline["visible"])
    for cohort in pipeline["cohorts"]:
        for kind in ("operating", "finance"):
            flows = cohort[kind]["flows"]
            assert flows[-1]["closing"] == pytest.approx(0, abs=1e-6)
            for flow in flows:
                assert flow["closing"] == pytest.approx(flow["opening"] + flow["interest"] - flow["payment"])


def test_model_hashes_and_offline_run_are_reproducible(tmp_path):
    p8a = accepted_p8a()
    packet, proposal = packet_and_proposal()
    review = review_proposal(proposal, packet)
    model = build_financing_model(p8a, packet, proposal, review)
    assert model["context"]["source_packet_hash"]
    assert model["decision"]["binding"]["source_packet_hash"] == model["context"]["source_packet_hash"]
    assert model["forecast"]["periods"] == list(PERIODS)

    output = run_offline(p8a, tmp_path)
    assert output["decision"]["status"] == "OFFLINE_FIXTURE"
    assert (tmp_path / "candidate.json").exists()
    assert (tmp_path / "review.json").exists()
    assert (tmp_path / "model.json").exists()


def test_prepare_handoff_writes_a_canonical_no_dispatch_request(tmp_path):
    manifest = prepare_live_handoff(accepted_p8a(), tmp_path, output_path=tmp_path / "model-input.json")
    assert manifest["status"] == "PREPARED_NO_DISPATCH"
    assert manifest["canonical_request_equal"] is True
    assert manifest["request_path"].endswith("01-analyst-initial.request.json")
    assert (tmp_path / "prepared-manifest.json").exists()
    assert (tmp_path / "evidence-packet.json").exists()


def test_p8a_acceptance_and_strict_numeric_boundaries():
    invalid = accepted_p8a()
    invalid["p8a_decision"] = copy.deepcopy(invalid["p8a_decision"])
    invalid["p8a_decision"]["status"] = "REVIEW_REQUIRED"
    with pytest.raises(FinancingError, match="not accepted"):
        build_evidence_packet(invalid)

    packet, proposal = packet_and_proposal()
    with pytest.raises(ValidationError):
        proposal.__class__(**{**proposal.model_dump(), "debt_coupon_rate": "0.05"})


def test_fixed_method_contract_is_literal_and_source_mix_is_application_resolved():
    packet, proposal = packet_and_proposal()
    schema = _strict_schema(FinancingProposal)

    def const(field):
        choices = schema["properties"][field]["anyOf"]
        return next(item["const"] for item in choices if "const" in item)

    assert const("debt_tail_policy") == "hold_through_fy2036"
    assert const("refinance_term_years") == 30
    assert const("refinance_fee_rate") == 0.0
    assert const("pipeline_finance_share") == "source_mix_disclosed_recent_additions"
    assert const("pipeline_operating_life_years") == 6
    assert const("pipeline_finance_life_years") == 13
    assert const("opening_finance_life_years") == 13

    context = _run_context(accepted_p8a(), packet)
    payload = _proposal_payload(packet, context, purpose="initial analyst selection")
    contract = payload["contract"]
    fixed = contract["fixed_application_fields"]
    assert fixed["pipeline_finance_share"]["reference"] == proposal.pipeline_finance_share
    assert fixed["pipeline_finance_share"]["resolved_value"] == pytest.approx(
        packet["facts"]["pipeline"]["finance_share_source"]
    )
    assert set(contract["changeable_judgment_fields"]) == {
        "debt_coupon_rate", "pipeline_operating_rate", "pipeline_finance_rate",
    }
    assert contract["nonforecast_inactive_fields_must_be_null"]


def test_shared_provenance_contract_distinguishes_source_calculation_and_policy():
    packet, proposal = packet_and_proposal()
    context = _run_context(accepted_p8a(), packet)
    analyst_payload = _proposal_payload(packet, context, purpose="initial analyst selection")
    provenance = analyst_payload["contract"]["provenance_contract"]

    assert provenance["version"] == "p8b-provenance-r5"
    assert provenance["owner"] == "application"
    assert provenance["reported_original_measures"]["status"] == "reported_original"
    assert provenance["reported_original_measures"]["fields"]["debt_face"]["value"] == 46156
    assert provenance["reported_original_measures"]["fields"]["debt_contra"]["value"] == {
        "discount_and_issuance_costs": -1098.0,
        "hedge_fv_adjustment": -17.0,
        "premium_on_debt_exchange": -4779.0,
    }

    calculated = provenance["calculated_existing_pool_measures"]
    assert calculated["status"] == "calculated_existing_pool"
    assert calculated["fields"]["opening_operating_calibrated_rate"]["value"] == pytest.approx(
        context["opening_calibration"]["operating_rate"]
    )
    assert calculated["fields"]["pipeline_finance_share_source_ratio"]["value"] == pytest.approx(
        packet["facts"]["pipeline"]["finance_share_source"]
    )
    assert provenance["selected_prospective_policy_estimates"]["status"] == "selected_prospective_estimate"
    selected = provenance["selected_prospective_policy_estimates"]["fields"]
    assert selected["debt_coupon_rate"]["value"] == 0.045
    assert selected["refinance_term_years"]["value"] == 30
    assert selected["refinance_fee_rate"]["value"] == 0.0
    assert selected["opening_finance_life_years"]["value"] == 13
    assert selected["pipeline_lives_years"]["value"] == {"operating": 6, "finance": 13}
    assert selected["pipeline_timing_policy"]["value"] == "actual_day_weighted_fy2026_fy2031"
    assert provenance["rate_attribution_rules"]["opening_calibrated_rates_are_not"] == [
        "disclosed weighted rates", "automatic forward cohort rates",
    ]
    assert provenance["rate_attribution_rules"]["default_future_rate_proxies"] == pytest.approx({"operating": 0.036, "finance": 0.044})
    assert "substantive forward-looking financial basis" in provenance["rate_attribution_rules"]["override_requirement"]
    assert provenance["bundle_a"] == {
        "operating_lease": {
            "cost": "operating",
            "payments": "operating CFO/UFCF",
            "statement_treatment": "ROU asset and liability remain on the statements",
            "equity_bridge_claim": "none",
        },
        "finance_lease": {
            "interest": "financing",
            "principal": "financing CFF",
            "additions": "economic investment once in UFCF",
            "equity_bridge_claim": "finance liability once as a later debt-like claim",
        },
    }
    assert proposal.pipeline_operating_rate == pytest.approx(selected["pipeline_rates"]["value"]["operating"])


def test_reviewer_payload_keeps_bad_rationale_as_untrusted_correction_concern():
    packet, proposal = packet_and_proposal()
    context = _run_context(accepted_p8a(), packet)
    retained_bad_rationale = json.loads(
        (ROOT / "data" / "build-guide-p8b" / "live-r4" / "candidate-initial.json").read_text(encoding="utf-8")
    )["rationale"]
    bad = proposal.model_copy(update={"rationale": retained_bad_rationale})
    payload = _review_payload(
        packet,
        context,
        bad,
        purpose="independent original review",
        authority=fake_authority(),
    )

    assert payload["contract"]["provenance_contract"] == _proposal_payload(
        packet, context, purpose="initial analyst selection"
    )["contract"]["provenance_contract"]
    explanation = payload["candidate_explanation_review"]
    assert explanation["rationale"] == retained_bad_rationale
    assert explanation["is_source_statement"] is False
    assert explanation["source_validity"] == "review_required"
    assert "correction concern" in explanation["correction_concern_if_mismatch"]
    assert payload["review_contract"]["candidate_explanation_is_not_source_evidence"] is True
    assert payload["review_contract"]["source_valid_is_reviewer_assessed"] is True


def test_retained_bad_refinancing_proposal_is_rejected_by_wire_semantics(tmp_path):
    bad = retained_bad_proposal_json()
    assert bad["refinance_fee_rate"] == 0.005
    with pytest.raises(FinancingError, match="semantic validation"):
        run_fake(tmp_path, [bad])
    assert (tmp_path / "run" / "attempts" / "01-analyst-initial.parse-error.json").exists()
    assert not (tmp_path / "run" / "model.json").exists()


def test_nonforecast_proposal_rejects_populated_inactive_field(tmp_path):
    candidate = candidate_json()
    candidate.update({"outcome": "capability_gap", "follow_up_request": "Provide supported terms."})
    with pytest.raises(FinancingError, match="semantic validation"):
        run_fake(tmp_path, [candidate])
    assert not (tmp_path / "run" / "model.json").exists()


def test_source_mutation_is_rejected(tmp_path):
    source = ROOT / "Lunacy" / "runs" / "three-statement-dcf" / "phases" / "financing" / "P8B-source-table-R1.csv"
    mutated = tmp_path / source.name
    mutated.write_text(source.read_text(encoding="utf-8").replace("debt_face_value,debt_balance,Q3 FY2026,46156", "debt_face_value,debt_balance,Q3 FY2026,46157"), encoding="utf-8")
    with pytest.raises(FinancingError, match="opening debt source identity"):
        build_evidence_packet(accepted_p8a(), mutated)


class FakeUsage:
    def model_dump(self, mode="json"):
        return {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}


class FakeResponse:
    def __init__(self, value, *, model="gpt-5.6-luna"):
        self.output_text = json.dumps(value)
        self.usage = FakeUsage()
        self.id = "fake-response"
        self.model = model


class FakeResponses:
    def __init__(self, values):
        self.values = list(values)
        self.requests = []

    def create(self, **request):
        self.requests.append(request)
        value = self.values.pop(0)
        if isinstance(value, Exception):
            raise value
        return FakeResponse(value)


class FakeClient:
    def __init__(self, values):
        self.responses = FakeResponses(values)


def isolated_budget(tmp_path, *, ceiling=5.0, reserve=0.5):
    path = tmp_path / "budget.json"
    initialize_budget(path, ceiling_eur=ceiling, final_review_reserve_eur=reserve, prices=PRICES)
    return path


def fake_authority(*args):
    return {"status": "PASS", "engine": "captured fake Mog", "snapshot": {"status": "PASS"}}


def candidate_json():
    packet, proposal = packet_and_proposal()
    return proposal.model_dump(mode="json")


def retained_bad_proposal_json():
    response_path = ROOT / "data" / "build-guide-p8b" / "live-r3" / "attempts" / "01-analyst-initial.response.json"
    response = json.loads(response_path.read_text(encoding="utf-8"))
    for item in response.get("output", []):
        for content in item.get("content", []):
            text = content.get("text") if isinstance(content, dict) else None
            if not isinstance(text, str):
                continue
            try:
                value = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict) and value.get("refinance_term_years") == 5:
                return value
    raise AssertionError(f"retained bad P8B proposal not found in {response_path}")


def review_json(*, verdict="accept", target="none", required_revision=None):
    packet, proposal = packet_and_proposal()
    review = review_proposal(proposal, packet).model_dump(mode="json")
    review.update({"verdict": verdict, "target": target, "required_revision": required_revision})
    return review


def run_fake(tmp_path, values, *, authority=fake_authority):
    client = FakeClient(values)
    model = run_reasoning(
        accepted_p8a(),
        tmp_path / "run",
        isolated_budget(tmp_path),
        client=client,
        mog_builder=authority,
    )
    return model, client


def test_live_default_is_real_responses_wire_and_accepts_with_actual_context(tmp_path):
    model, client = run_fake(tmp_path, [candidate_json(), review_json()])
    assert model["decision"]["status"] == "SYSTEM_REVIEWED_PROVISIONAL"
    assert model["decision"]["human_approval"] is False
    request = client.responses.requests[0]
    assert set(request) == {"model", "reasoning", "service_tier", "input", "instructions", "text", "max_output_tokens", "tools", "background"}
    assert request["model"] == "gpt-5.6-luna"
    assert request["reasoning"] == {"effort": "medium"}
    assert request["text"]["format"]["strict"] is True
    assert request["text"]["format"]["schema"]["required"] == list(request["text"]["format"]["schema"]["properties"])
    assert "temperature" not in request
    persisted = json.loads((tmp_path / "run" / "attempts" / "01-analyst-initial.request.json").read_text())
    assert request == persisted


def test_live_candidate_uses_actual_mog_authority_before_review(tmp_path):
    client = FakeClient([candidate_json(), review_json()])
    model = run_reasoning(
        accepted_p8a(),
        tmp_path / "run",
        isolated_budget(tmp_path),
        client=client,
    )
    assert model["authoritative_mog"]["engine"] == "Mog SDK"
    assert model["decision"]["authoritative_mog_attached"] is True
    assert len(client.responses.requests) == 2


def test_live_revision_rebuilds_and_rereviews_only_consequential_change(tmp_path):
    original = candidate_json()
    revised = {**original, "debt_coupon_rate": 0.05}
    model, client = run_fake(
        tmp_path,
        [original, review_json(verdict="revise", target="debt_policy", required_revision="Update the coupon proxy."), revised, review_json()],
    )
    assert model["decision"]["status"] == "SYSTEM_REVIEWED_PROVISIONAL"
    assert len(client.responses.requests) == 4
    assert model["decision"]["binding"]["candidate_snapshot"]["debt_coupon_rate"] == 0.05
    assert (tmp_path / "run" / "candidate-revision.json").exists()


def test_live_refuses_unchanged_revision_and_does_not_adopt_original(tmp_path):
    original = candidate_json()
    with pytest.raises(FinancingError, match="consequential"):
        run_fake(tmp_path, [original, review_json(verdict="revise", target="debt_policy", required_revision="Change debt assumption."), original])
    terminal = json.loads((tmp_path / "run" / "terminal-outcome.json").read_text())
    assert terminal["status"] == "FAILED"
    assert not (tmp_path / "run" / "model.json").exists()


def test_live_reject_preserves_previous_effective_publication(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    sentinel = b'{"previous":"effective"}\n'
    (run_dir / "model.json").write_bytes(sentinel)
    with pytest.raises(FinancingError, match="rejected"):
        run_reasoning(accepted_p8a(), run_dir, isolated_budget(tmp_path), client=FakeClient([candidate_json(), review_json(verdict="reject")]), mog_builder=fake_authority)
    assert (run_dir / "model.json").read_bytes() == sentinel
    assert json.loads((run_dir / "terminal-outcome.json").read_text())["status"] == "REJECTED_BY_REVIEW"


@pytest.mark.parametrize("outcome", ["unresolved", "capability_gap"])
def test_live_revision_nonforecast_preserves_prior_and_stops_before_rebuild(tmp_path, outcome):
    original = candidate_json()
    revised = {**original, "outcome": outcome, "follow_up_request": "Obtain the missing financing detail."}
    for key in (
        "method_id", "method_version", "debt_coupon_rate", "debt_refinance_policy", "debt_tail_policy",
        "refinance_term_years", "refinance_fee_rate", "lease_bundle", "pipeline_finance_share",
        "pipeline_operating_life_years", "pipeline_finance_life_years", "pipeline_operating_rate",
        "pipeline_finance_rate", "pipeline_timing_policy", "opening_finance_life_years",
    ):
        revised[key] = None
    builder_stages = []

    def authority(*args):
        builder_stages.append(args[-1])
        return fake_authority(*args)

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    sentinel = b'{"previous":"effective"}\n'
    (run_dir / "model.json").write_bytes(sentinel)
    client = FakeClient([
        original,
        review_json(verdict="revise", target="debt_policy", required_revision="Reassess the debt policy."),
        revised,
    ])
    with pytest.raises(FinancingError, match="terminated"):
        run_reasoning(accepted_p8a(), run_dir, isolated_budget(tmp_path), client=client, mog_builder=authority)

    terminal = json.loads((run_dir / "terminal-outcome.json").read_text())
    assert terminal["status"] == outcome.upper()
    assert terminal["candidate"] == revised
    assert terminal["decision"]["candidate_hash"] == content_hash(revised)
    assert terminal["decision"]["previous_effective_model_sha256"] == hashlib.sha256(sentinel).hexdigest()
    held = json.loads((run_dir / "decision-held.json").read_text())
    assert held["candidate_hash"] == content_hash(revised)
    revision_outcome = terminal["decision"]["metadata"]["revision_outcome"]
    assert revision_outcome["stage"] == "analyst-revision"
    assert revision_outcome["outcome"] == outcome
    assert revision_outcome["candidate"] == revised
    assert revision_outcome["reason"] == revised["rationale"]
    assert revision_outcome["follow_up_request"] == revised["follow_up_request"]
    assert json.loads((run_dir / "revision-outcome.json").read_text()) == revision_outcome
    assert len(client.responses.requests) == 3
    assert builder_stages == ["analyst-initial"]
    assert not (run_dir / "mog-authority" / "analyst-revision").exists()
    assert (run_dir / "model.json").read_bytes() == sentinel


@pytest.mark.parametrize("outcome", ["unresolved", "capability_gap"])
def test_live_nonforecast_outcomes_stop_before_forecast_or_review(tmp_path, outcome):
    candidate = candidate_json()
    candidate.update({"outcome": outcome, "follow_up_request": "Obtain the missing financing detail."})
    for key in (
        "method_id", "method_version", "debt_coupon_rate", "debt_refinance_policy", "debt_tail_policy",
        "refinance_term_years", "refinance_fee_rate", "lease_bundle", "pipeline_finance_share",
        "pipeline_operating_life_years", "pipeline_finance_life_years", "pipeline_operating_rate",
        "pipeline_finance_rate", "pipeline_timing_policy", "opening_finance_life_years",
    ):
        candidate[key] = None
    with pytest.raises(FinancingError, match="terminated"):
        run_fake(tmp_path, [candidate])
    assert json.loads((tmp_path / "run" / "terminal-outcome.json").read_text())["status"] == outcome.upper()
    assert not (tmp_path / "run" / "model.json").exists()


def test_live_malformed_output_is_recorded_and_not_published(tmp_path):
    malformed = candidate_json()
    malformed.pop("follow_up_request")
    with pytest.raises(FinancingError, match="strict schema"):
        run_fake(tmp_path, [malformed])
    assert (tmp_path / "run" / "attempts" / "01-analyst-initial.parse-error.json").exists()
    assert json.loads((tmp_path / "run" / "terminal-outcome.json").read_text())["status"] == "FAILED"


def test_live_budget_hold_and_provider_failure_leave_no_effective_model(tmp_path):
    with pytest.raises(FinancingError):
        run_reasoning(
            accepted_p8a(), tmp_path / "run", isolated_budget(tmp_path, ceiling=0.500001, reserve=0.5),
            client=FakeClient([candidate_json()]), mog_builder=fake_authority,
        )
    assert json.loads((tmp_path / "run" / "terminal-outcome.json").read_text())["status"] == "BUDGET_HELD"

    failed_dir = tmp_path / "failed"
    with pytest.raises(FinancingError, match="provider call failed"):
        run_reasoning(accepted_p8a(), failed_dir, isolated_budget(tmp_path / "budget-failure"), client=FakeClient([RuntimeError("transport")]), mog_builder=fake_authority)
    assert not (failed_dir / "model.json").exists()
    assert json.loads((failed_dir / "terminal-outcome.json").read_text())["status"] == "FAILED"


def test_live_exact_completed_request_resumes_without_second_provider_call(tmp_path):
    run_dir = tmp_path / "run"
    budget = isolated_budget(tmp_path)
    first = FakeClient([candidate_json(), review_json()])
    first_model = run_reasoning(accepted_p8a(), run_dir, budget, client=first, mog_builder=fake_authority)
    second = FakeClient([])
    second_model = run_reasoning(accepted_p8a(), run_dir, budget, client=second, mog_builder=fake_authority)
    assert first_model["decision"]["status"] == second_model["decision"]["status"] == "SYSTEM_REVIEWED_PROVISIONAL"
    assert second.responses.requests == []


def test_live_stale_context_refuses_reuse(tmp_path):
    run_dir = tmp_path / "run"
    budget = isolated_budget(tmp_path)
    run_reasoning(accepted_p8a(), run_dir, budget, client=FakeClient([candidate_json(), review_json()]), mog_builder=fake_authority)
    stale = accepted_p8a()
    stale["schema_version"] = "changed-upstream"
    with pytest.raises(FinancingError, match="context changed"):
        run_reasoning(stale, run_dir, budget, client=FakeClient([]), mog_builder=fake_authority)


def test_live_context_binds_calculation_files_and_refuses_changed_reuse(tmp_path):
    run_dir = tmp_path / "run"
    budget = isolated_budget(tmp_path)
    run_reasoning(accepted_p8a(), run_dir, budget, client=FakeClient([candidate_json(), review_json()]), mog_builder=fake_authority)
    context_path = run_dir / "run-context.json"
    context = json.loads(context_path.read_text(encoding="utf-8"))
    expected_files = {
        "src/smrik_fund/financing.py",
        "scripts/spreadsheet_compat/asset_model.mjs",
        "scripts/spreadsheet_compat/run-p8b.mjs",
    }
    assert set(context["implementation_files"]) == expected_files
    assert context["implementation_hash"] == context["implementation_files"]["src/smrik_fund/financing.py"]
    assert context["implementation_aggregate_sha256"] == content_hash(context["implementation_files"])
    context["implementation_files"]["scripts/spreadsheet_compat/asset_model.mjs"] = "changed-calculation"
    context_path.write_text(json.dumps(context, indent=2) + "\n", encoding="utf-8")
    second = FakeClient([])
    with pytest.raises(FinancingError, match="context changed"):
        run_reasoning(accepted_p8a(), run_dir, budget, client=second, mog_builder=fake_authority)
    assert second.responses.requests == []


def test_live_missing_model_setting_is_rejected_as_failure(tmp_path):
    with pytest.raises(FinancingError):
        run_reasoning(accepted_p8a(), tmp_path / "run", isolated_budget(tmp_path), client=FakeClient([candidate_json()],), mog_builder=lambda *args: (_ for _ in ()).throw(RuntimeError("Mog unavailable")))
    assert json.loads((tmp_path / "run" / "terminal-outcome.json").read_text())["status"] == "FAILED"


def test_prepare_r2_binds_settings_schema_and_read_only_ledger(tmp_path):
    manifest = prepare_live_handoff(accepted_p8a(), tmp_path / "live-r2", output_path=tmp_path / "model-input.json", budget_path=isolated_budget(tmp_path))
    assert manifest["status"] == "PREPARED_NO_DISPATCH"
    assert manifest["canonical_request_equal"] is True
    assert manifest["settings"]["endpoint"] == "https://api.openai.com/v1/responses"
    assert manifest["caps"]["max_attempts"] == 6
    assert (tmp_path / "live-r2" / "schema-proof.json").exists()


def test_prepare_handoff_exposes_calculation_implementation_binding(tmp_path):
    manifest = prepare_live_handoff(accepted_p8a(), tmp_path / "live-r3", output_path=tmp_path / "model-input.json")
    assert set(manifest["implementation_files"]) == {
        "src/smrik_fund/financing.py",
        "scripts/spreadsheet_compat/asset_model.mjs",
        "scripts/spreadsheet_compat/run-p8b.mjs",
    }
    assert manifest["implementation_aggregate_sha256"] == content_hash(manifest["implementation_files"])
