import copy
import json
import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from smrik_fund.analysis_budget import initialize_budget
from smrik_fund.equity import (
    ANALYST_INSTRUCTION,
    PERIODS,
    EquityError,
    EquityProposal,
    _method_contract,
    _proposal_payload,
    _request,
    _run_context,
    build_equity_model,
    build_evidence_packet,
    default_proposal,
    forecast_values,
    prepare_live_handoff,
    review_proposal,
    run_offline,
)

ROOT = Path(__file__).resolve().parents[1]
P8B = ROOT / "data" / "build-guide-p8b" / "live-r5" / "model-input.json"
SOURCE = ROOT / "Lunacy" / "runs" / "three-statement-dcf" / "phases" / "equity" / "P8C-source-table-R1.csv"
PRICES = json.loads((ROOT / "docs" / "API_COST_SNAPSHOT.json").read_text(encoding="utf-8"))
INDEPENDENT_ORACLE = json.loads((ROOT / "data" / "build-guide-p8c" / "parent-gate-r1" / "parent-default-stub-oracle-r2.json").read_text(encoding="utf-8"))


def accepted_p8b() -> dict:
    return json.loads(P8B.read_text(encoding="utf-8"))


def packet_and_proposal() -> tuple[dict, EquityProposal]:
    packet = build_evidence_packet(accepted_p8b(), SOURCE)
    return packet, default_proposal(packet)


class FakeUsage:
    def model_dump(self, mode="json"):
        return {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}


class FakeResponse:
    def __init__(self, value):
        self.output_text = json.dumps(value)
        self.usage = FakeUsage()
        self.id = "fake-response"
        self.model = "gpt-5.6-luna"


class FakeResponses:
    def __init__(self, values):
        self.values = list(values)
        self.requests = []

    def create(self, **request):
        self.requests.append(request)
        return FakeResponse(self.values.pop(0))


class FakeClient:
    def __init__(self, values):
        self.responses = FakeResponses(values)


def fake_authority(*args):
    return {"status": "PASS", "engine": "captured fake Mog", "snapshot": {"status": "PASS"}}


def review_json(packet: dict, proposal: EquityProposal, *, verdict="accept", target="none", required_revision=None) -> dict:
    value = review_proposal(proposal, packet).model_dump(mode="json")
    value.update({"verdict": verdict, "target": target, "required_revision": required_revision})
    return value


def run_fake(root: Path, values: list[dict]) -> tuple[dict, FakeClient]:
    packet, proposal = packet_and_proposal()
    client = FakeClient(values)
    budget = root / "budget.json"
    initialize_budget(budget, ceiling_eur=5.0, final_review_reserve_eur=0.5, prices=PRICES)
    from smrik_fund.equity import run_reasoning

    model = run_reasoning(accepted_p8b(), root / "run", budget, source_table=SOURCE, client=client, mog_builder=fake_authority)
    return model, client


def test_source_packet_preserves_reported_equity_and_prices():
    packet, proposal = packet_and_proposal()
    facts = packet["facts"]

    assert {key: facts["opening_equity"][key] for key in ("common_apic", "retained_earnings", "aoci", "total_equity", "point_shares")} == {
        "common_apic": 115069,
        "retained_earnings": 302526,
        "aoci": -3228,
        "total_equity": 414367,
        "point_shares": 7429,
    }
    assert facts["market_quote"]["value"] == pytest.approx(370.17)
    assert facts["future_settlement_price"]["value"] == pytest.approx(13319 / 27)
    assert proposal.existing_award_units == pytest.approx(82)
    assert proposal.existing_unrecognized_cost == pytest.approx(21600)


def test_r5_method_contract_exposes_locked_calibration_and_supported_estimates():
    packet, proposal = packet_and_proposal()
    context = _run_context(accepted_p8b(), packet)
    contract = _method_contract(packet, context)

    assert context["schema_version"] == "p8c-equity-proposal-r5"
    assert context["contract_version"] == "p8c-equity-contract-r5"
    claim_contract = contract["fixed_application_fields"]["existing_claim_price"]
    assert claim_contract["value"] == pytest.approx(370.17)
    assert claim_contract["unit"] == "USD/share"
    assert claim_contract["classification"] == "source"
    assert claim_contract["locked"] is True
    assert claim_contract["source_date"] == "2026-03-31"
    assert "grant-date fair value" in claim_contract["basis"]
    assert contract["application_owned_arithmetic"]["repurchase_ratio"]["formula"] == "13319 / 241832"
    assert contract["judgment_constraints"]["timing"]["semantics"].startswith("0 means the movement occurs at period end")
    assert contract["revision_contract"]["repurchase_exception"].endswith("supported zero-program policy 0.0")
    assert contract["judgment_constraints"]["timing"]["base"] == pytest.approx(0.5)
    assert "settlement_price" in contract["changeable_judgment_fields"]
    assert "existing_claim_price" not in contract["changeable_judgment_fields"]
    assert contract["outcome_contract"]["propose_forecast"]["follow_up_request"] == "must be null"
    assert "method_id" in contract["nonforecast_inactive_fields_must_be_null"]

    payload = _proposal_payload(packet, context, purpose="R5 contract test")
    assert payload["contract"] == contract
    request = _request(ANALYST_INSTRUCTION, payload, EquityProposal)
    assert request["text"]["format"]["name"] == "equity_proposal_r5"
    assert json.loads(request["input"])["contract"]["contract_version"] == "p8c-equity-contract-r5"
    assert "13319/241832" in ANALYST_INSTRUCTION
    assert "0 means period end, 1 means period opening" in ANALYST_INSTRUCTION
    assert json.loads(request["input"])["contract"]["application_owned_arithmetic"]["repurchase_ratio"]["source_revenue"] == 241832.0


def test_r5_fixed_claim_price_rejects_historical_grant_date_fair_value():
    packet, proposal = packet_and_proposal()
    with pytest.raises(EquityError, match="dated market quote"):
        from smrik_fund.equity import validate_proposal

        validate_proposal(proposal.model_copy(update={"existing_claim_price": 413.9}), packet)


def test_r5_locked_claim_cannot_be_revision_target():
    from smrik_fund.equity import _revision_is_consequential

    packet, proposal = packet_and_proposal()
    changed = proposal.model_copy(update={"existing_claim_price": 413.9})
    with pytest.raises(EquityError, match="consequential"):
        _revision_is_consequential(proposal, changed, "pricing")


def test_forecast_separates_old_service_new_sbc_delivery_and_capital_returns():
    packet, proposal = packet_and_proposal()
    forecast = forecast_values(packet, proposal)

    sbc = forecast["sbc"]
    assert len(forecast["periods"]) == len(PERIODS)
    assert all(total == pytest.approx(old + new) for total, old, new in zip(sbc["total"], sbc["existing_service"], sbc["new"], strict=True))
    assert all(value >= 0 for value in sbc["new"])
    assert forecast["existing_claim"] == pytest.approx(82 * 370.17)
    assert forecast["withheld_units"][0] == pytest.approx((forecast["gross_new_units"][0] + forecast["gross_existing_units"][0]) / 3)
    assert forecast["dividend_cash_paid"][0] == pytest.approx(6760)
    assert forecast["dividend_declaration"][1] > 0
    assert forecast["program_authorization_remaining"][-1] == pytest.approx(0)
    assert forecast["checks"]["all_pass"] is True
    assert forecast["valuation_ufcf"] == pytest.approx(forecast["cfo_ufcf"])


def test_real_upstream_investment_and_service_calendar_are_required_and_preserved():
    packet, proposal = packet_and_proposal()
    forecast = forecast_values(packet, proposal)

    assert forecast["period_meta"][2]["days"] == 366
    assert forecast["sbc"]["total_service_days"] == 1096
    assert forecast["sbc"]["service_days"][:4] == [91, 365, 366, 274]
    assert sum(forecast["sbc"]["service_days"]) == 1096
    assert forecast["sbc"]["total_service_days"] == sum(forecast["sbc"]["service_days"])
    assert all(value > 0 for value in forecast["capex"])
    assert all(value > 0 for value in forecast["depreciation"])
    assert all(value > 0 for value in forecast["nwc"])
    assert forecast["capex"] == pytest.approx(forecast["recognized_ppe_additions"])

    missing = copy.deepcopy(packet)
    missing["upstream_model"]["operating_forecast"].pop("forecast_revenue")
    with pytest.raises(EquityError, match="forecast revenue"):
        forecast_values(missing, proposal)


def test_service_years_run_off_exactly_and_period_opening_apic_basis_rolls():
    packet, proposal = packet_and_proposal()
    for years, expected_days in ((2, [91, 365, 275, 0]), (3, [91, 365, 366, 274]), (4, [91, 365, 366, 365, 274])):
        forecast = forecast_values(packet, proposal.model_copy(update={"existing_service_years": years}))
        assert forecast["sbc"]["service_days"][:len(expected_days)] == expected_days
        assert sum(forecast["sbc"]["service_days"]) == forecast["sbc"]["total_service_days"]
        assert sum(forecast["sbc"]["existing_service"]) == pytest.approx(proposal.existing_unrecognized_cost)
        assert sum(forecast["sbc"]["existing_units_delivered"]) == pytest.approx(proposal.existing_award_units)
        first_zero = expected_days.index(0) if 0 in expected_days else len(expected_days)
        assert all(value == pytest.approx(0) for value in forecast["sbc"]["existing_service"][first_zero:])
        assert all(value == pytest.approx(0) for value in forecast["sbc"]["existing_units_delivered"][first_zero:])

    forecast = forecast_values(packet, proposal)
    assert forecast["program_apic_basis"][1] == pytest.approx(
        forecast["program_opening_apic"][1] / forecast["program_opening_point_shares"][1] * forecast["program_units"][1]
    )
    assert forecast["program_apic_basis"][1] != pytest.approx(
        forecast["source_claims"]["opening_apic"] / forecast["source_claims"]["opening_point_shares"] * forecast["program_units"][1]
    )


def test_real_default_stub_matches_independent_parent_arithmetic():
    packet, proposal = packet_and_proposal()
    forecast = forecast_values(packet, proposal)
    expected = INDEPENDENT_ORACLE["base_expectations"]

    assert forecast["book_ebit"][0] == pytest.approx(expected["ebit"])
    assert forecast["net_income"][0] == pytest.approx(expected["net_income"])
    assert forecast["cfo"][0] == pytest.approx(expected["cfo"])
    assert forecast["valuation_ufcf"][0] == pytest.approx(expected["economic_ufcf"])
    assert forecast["closing_cash"][0] == pytest.approx(expected["closing_cash"])
    assert forecast["point_shares_closing"][0] == pytest.approx(expected["closing_point_shares"])
    assert forecast["basic_weighted_shares"][0] == pytest.approx(expected["basic_weighted_shares"])
    assert forecast["existing_claim"] == pytest.approx(expected["gross_existing_claim"])


def test_distinct_timing_changes_eps_denominator_without_changing_point_shares():
    packet, proposal = packet_and_proposal()
    midpoint = forecast_values(packet, proposal)
    year_end = proposal.model_copy(update={"delivery_timing": 1.0, "issuance_timing": 1.0, "repurchase_timing": 1.0})
    changed = forecast_values(packet, year_end)

    assert changed["point_shares_closing"] == pytest.approx(midpoint["point_shares_closing"])
    assert changed["basic_weighted_shares"] != pytest.approx(midpoint["basic_weighted_shares"])


def test_r5_timing_endpoints_match_opening_and_closing_point_shares_only():
    packet, proposal = packet_and_proposal()
    opening = forecast_values(packet, proposal.model_copy(update={
        "delivery_timing": 0.0, "issuance_timing": 0.0, "repurchase_timing": 0.0,
    }))
    closing = forecast_values(packet, proposal.model_copy(update={
        "delivery_timing": 1.0, "issuance_timing": 1.0, "repurchase_timing": 1.0,
    }))

    assert opening["basic_weighted_shares"] == pytest.approx(opening["point_shares_opening"])
    assert closing["basic_weighted_shares"] == pytest.approx(closing["point_shares_closing"])
    for key in ("point_shares_closing", "cash_change", "net_income", "cfo", "valuation_ufcf"):
        assert opening[key] == pytest.approx(closing[key])


def test_r5_zero_repurchase_revision_is_supported_but_fixed_inputs_are_not():
    packet, proposal = packet_and_proposal()
    from smrik_fund.equity import _revision_is_consequential, validate_proposal

    zero_program = proposal.model_copy(update={"repurchase_ratio": 0.0})
    _revision_is_consequential(proposal, zero_program, "repurchase")
    validate_proposal(zero_program, packet)
    assert forecast_values(packet, zero_program)["program_cash"] == pytest.approx([0.0] * len(PERIODS))

    with pytest.raises(EquityError, match="application-resolved"):
        validate_proposal(proposal.model_copy(update={"cash_issuance_ratio": proposal.cash_issuance_ratio + 0.001}), packet)
    with pytest.raises(EquityError, match="selected dated market quote"):
        validate_proposal(proposal.model_copy(update={"existing_claim_price": proposal.existing_claim_price + 1}), packet)


def test_review_and_model_bind_the_full_equity_boundary():
    packet, proposal = packet_and_proposal()
    review = review_proposal(proposal, packet)
    model = build_equity_model(accepted_p8b(), packet, proposal, review)

    assert review.verdict == "accept"
    assert model["forecast"]["checks"]["all_pass"] is True
    assert model["decision"]["binding"]["candidate_hash"] == model["decision"]["candidate_hash"]
    assert model["decision"]["binding"]["source_packet_hash"] == model["decision"]["source_packet_hash"]
    assert model["provenance_contract"]["source_facts_locked"] is True
    assert model["provenance_contract"]["prices_are_exogenous"] is True


def test_live_wire_accepts_after_actual_authority_and_persists_strict_request():
    with tempfile.TemporaryDirectory(dir=ROOT / "data") as temp_dir:
        root = Path(temp_dir)
        packet, proposal = packet_and_proposal()
        model, client = run_fake(root, [proposal.model_dump(mode="json"), review_json(packet, proposal)])

        assert model["decision"]["status"] == "SYSTEM_REVIEWED_PROVISIONAL"
        request = client.responses.requests[0]
        assert set(request) == {"model", "reasoning", "service_tier", "input", "instructions", "text", "max_output_tokens", "tools", "background"}
        assert request["model"] == "gpt-5.6-luna"
        assert request["reasoning"] == {"effort": "medium"}
        assert request["text"]["format"]["strict"] is True
        assert request["text"]["format"]["schema"]["required"] == list(request["text"]["format"]["schema"]["properties"])
        assert json.loads((root / "run" / "attempts" / "01-analyst-initial.request.json").read_text()) == request
        review_payload = json.loads(client.responses.requests[1]["input"])
        assert review_payload["contract"]["fixed_application_fields"]["existing_claim_price"]["value"] == pytest.approx(370.17)
        assert review_payload["review_contract"]["fixed_fields_are_not_revision_choices"] is True
        assert review_payload["candidate_explanation_review"]["is_source_statement"] is False


def test_fake_responses_nondefault_cycle_uses_nested_actual_mog_authority():
    with tempfile.TemporaryDirectory(dir=ROOT / "data") as temp_dir:
        root = Path(temp_dir)
        packet, proposal = packet_and_proposal()
        nondefault = proposal.model_copy(update={"existing_service_years": 2, "delivery_timing": 0.75, "issuance_timing": 0.25, "repurchase_timing": 0.8})
        revised = nondefault.model_copy(update={"sbc_ratio": nondefault.sbc_ratio * 1.1})
        client = FakeClient([
            nondefault.model_dump(mode="json"),
            review_json(packet, nondefault, verdict="revise", target="sbc", required_revision="Update the SBC ratio."),
            revised.model_dump(mode="json"),
            review_json(packet, revised),
        ])
        budget = root / "budget.json"
        initialize_budget(budget, ceiling_eur=5.0, final_review_reserve_eur=0.5, prices=PRICES)
        from smrik_fund.equity import _actual_mog_candidate, run_reasoning

        model = run_reasoning(accepted_p8b(), root / "nested" / "run", budget, source_table=SOURCE, client=client, mog_builder=_actual_mog_candidate)

        initial_authority = root / "nested" / "run" / "mog-authority" / "analyst-initial" / "equity-verification.json"
        revised_authority = root / "nested" / "run" / "mog-authority" / "analyst-revision" / "equity-verification.json"
        assert model["decision"]["status"] == "SYSTEM_REVIEWED_PROVISIONAL"
        assert model["decision"]["binding"]["candidate_snapshot"]["existing_service_years"] == 2
        assert model["decision"]["binding"]["candidate_snapshot"]["sbc_ratio"] == pytest.approx(revised.sbc_ratio)
        for authority in (initial_authority, revised_authority):
            assert authority.exists()
            assert json.loads(authority.read_text())["status"] == "PASS"


def test_live_consequential_revision_rebuilds_and_rereviews():
    with tempfile.TemporaryDirectory(dir=ROOT / "data") as temp_dir:
        root = Path(temp_dir)
        packet, proposal = packet_and_proposal()
        revised = proposal.model_copy(update={"sbc_ratio": proposal.sbc_ratio * 1.1})
        model, client = run_fake(root, [
            proposal.model_dump(mode="json"),
            review_json(packet, proposal, verdict="revise", target="sbc", required_revision="Update the SBC ratio."),
            revised.model_dump(mode="json"),
            review_json(packet, revised),
        ])

        assert model["decision"]["status"] == "SYSTEM_REVIEWED_PROVISIONAL"
        assert len(client.responses.requests) == 4
        assert model["decision"]["binding"]["candidate_snapshot"]["sbc_ratio"] == pytest.approx(revised.sbc_ratio)
        assert (root / "run" / "revision-request.json").exists()


@pytest.mark.parametrize("outcome", ["unresolved", "capability_gap"])
def test_live_nonforecast_stops_before_mog_and_review(outcome):
    with tempfile.TemporaryDirectory(dir=ROOT / "data") as temp_dir:
        root = Path(temp_dir)
        _, proposal = packet_and_proposal()
        candidate = proposal.model_dump(mode="json")
        for field in ("method_id", "method_version", "sbc_ratio", "existing_award_units", "existing_unrecognized_cost", "existing_service_years", "existing_claim_price", "settlement_price", "withholding_rate", "cash_issuance_ratio", "repurchase_ratio", "repurchase_authorization", "dividend_per_share_quarter", "dividend_quarters_stub", "dividend_quarters_annual", "delivery_timing", "issuance_timing", "repurchase_timing", "repurchase_policy", "settlement_policy", "diluted_eps_policy"):
            candidate[field] = None
        candidate.update({"outcome": outcome, "follow_up_request": "Obtain the missing Q3 award inventory."})
        budget = root / "budget.json"
        initialize_budget(budget, ceiling_eur=5.0, final_review_reserve_eur=0.5, prices=PRICES)
        from smrik_fund.equity import run_reasoning

        with pytest.raises(EquityError, match=outcome.upper()):
            run_reasoning(accepted_p8b(), root / "run", budget, source_table=SOURCE, client=FakeClient([candidate]), mog_builder=lambda *args: pytest.fail("Mog must not run"))
        terminal = json.loads((root / "run" / "terminal-outcome.json").read_text())
        assert terminal["status"] == ("CAPABILITY_GAP" if outcome == "capability_gap" else "UNRESOLVED")
        assert terminal["candidate"]["outcome"] == outcome
        assert not (root / "run" / "model.json").exists()


def test_invalid_price_and_negative_new_compensation_are_rejected():
    packet, proposal = packet_and_proposal()
    invalid = proposal.model_dump()
    invalid["settlement_price"] = 0
    with pytest.raises(ValidationError):
        EquityProposal(**invalid)

    negative = proposal.model_copy(update={"sbc_ratio": 0.0, "existing_unrecognized_cost": 21600})
    with pytest.raises(ValueError, match="negative new compensation"):
        forecast_values(packet, negative)

    below_basis = proposal.model_copy(update={"settlement_price": 1.0})
    with pytest.raises(EquityError, match="below opening APIC retirement basis"):
        forecast_values(packet, below_basis)

    negative_apic = copy.deepcopy(packet)
    negative_apic["facts"]["opening_equity"]["common_apic"] = -1
    with pytest.raises(EquityError, match="opening APIC"):
        forecast_values(negative_apic, proposal)


def test_offline_run_and_prepare_hand_off_are_persisted_without_dispatch():
    p8b = accepted_p8b()
    with tempfile.TemporaryDirectory(dir=ROOT / "data") as temp_dir:
        root = Path(temp_dir)
        offline = run_offline(p8b, root / "offline", source_table=SOURCE)
        assert offline["decision"]["status"] == "OFFLINE_FIXTURE"
        assert (root / "offline" / "model.json").exists()

        manifest = prepare_live_handoff(p8b, root / "prepared", source_table=SOURCE, output_path=root / "prepared" / "model-input.json")
        assert manifest["status"] == "PREPARED_NO_DISPATCH"
        assert manifest["canonical_request_equal"] is True
        assert Path(manifest["request_path"]).exists()
