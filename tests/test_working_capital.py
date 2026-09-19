import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from smrik_fund.analysis_budget import initialize_budget
from smrik_fund.working_capital import (
    INITIAL_ANALYST_INSTRUCTION,
    MAX_OUTPUT_TOKENS,
    MODEL,
    REASONING_EFFORT,
    WorkingCapitalError,
    WorkingCapitalProposal,
    WorkingCapitalReview,
    _consequential,
    _context,
    _proposal_payload,
    _request,
    _review_payload,
    build_evidence_packet,
    build_working_capital_model,
    default_proposal,
    prepare_live_handoff,
    review_proposal,
    run_reasoning,
)

ROOT = Path(__file__).resolve().parents[1]
P6 = ROOT / "data" / "build-guide-p6" / "live-r4-20260906" / "model-input.json"
SOURCE = ROOT / "Lunacy" / "runs" / "three-statement-dcf" / "phases" / "working-capital" / "P7-source-table-R1.csv"
PRICES = json.loads((ROOT / "docs" / "API_COST_SNAPSHOT.json").read_text(encoding="utf-8"))


class Dumpable:
    def __init__(self, value):
        self.value = value

    def model_dump(self, mode="json"):
        return self.value


class NativeResponse:
    id = "resp-p7-test"
    model = MODEL

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


def accepted_review():
    return WorkingCapitalReview(
        verdict="accept", evidence_strength="mixed", method_valid=True, source_valid=True,
        period_valid=True, cash_sign_valid=True, exclusions_valid=True, no_double_count=True,
        concerns=["Bounded estimate."], required_revision=None, target="none",
        rationale="Accepted after independent review.",
    )


def revise_review(target="days_driver"):
    return accepted_review().model_copy(update={"verdict": "revise", "target": target, "required_revision": f"Change the bounded {target} driver."})


def make_packet():
    p6 = json.loads(P6.read_text(encoding="utf-8"))
    return build_evidence_packet(p6, SOURCE)


@pytest.fixture
def packet():
    return make_packet()


def p6_model():
    return json.loads(P6.read_text(encoding="utf-8"))


def test_default_policy_preserves_contract_identity_and_actual_period_days(packet):
    candidate = default_proposal(packet)
    assert candidate.accrued_compensation_multiplier == 1.0
    model = build_working_capital_model(
        {**packet, "p6_forecast": {"consolidated_revenue": [90.0] * 11, "cost_of_revenue": [54.0] * 11}},
        candidate,
        review_proposal(candidate, packet),
    )

    assert [period["days"] for period in model["periods"]] == [91, 365, 366, 365, 365, 365, 366, 365, 365, 365, 366]
    assert model["contract_bridge"]["identity_difference"] == 0
    assert model["forecast"]["contract_liability_closing"][0] == pytest.approx(53677)
    assert model["forecast"]["cfo_contribution"][0] == pytest.approx(-model["forecast"]["cash_conversion_nwc_change"][0])
    assert model["inputs"]["accrued_compensation_baseline"] == pytest.approx(11270 / 318273)
    assert model["inputs"]["accrued_compensation_multiplier"] == pytest.approx(1.0)
    assert model["inputs"]["accrued_compensation_effective_ratio"] == pytest.approx(11270 / 318273)
    assert model["forecast"]["accrued_compensation_closing"][0] == pytest.approx(90 / 91 * 365 * (11270 / 318273))


def test_dividend_payable_is_excluded_from_operating_nwc_but_preserved_in_ocl(packet):
    assert packet["ocl_bridge"]["reported_other_current_liabilities"] == pytest.approx(24552)
    assert packet["ocl_bridge"]["dividend_payable_financing"] == pytest.approx(6760)
    assert packet["ocl_bridge"]["unclassified_operating_residual"] == pytest.approx(8194)
    candidate = default_proposal(packet)
    model = build_working_capital_model(
        {**packet, "p6_forecast": {"consolidated_revenue": [90.0] * 11, "cost_of_revenue": [54.0] * 11}},
        candidate,
        review_proposal(candidate, packet),
    )
    assert model["inputs"]["opening_other_ocl_residual"] == pytest.approx(8194)
    assert model["inputs"]["opening_dividend_payable_financing"] == pytest.approx(6760)


def test_missing_denominator_is_blocked_but_supported_zero_balance_is_valid(packet):
    missing = copy.deepcopy(packet)
    missing["ttm_revenue"] = 0
    with pytest.raises(WorkingCapitalError, match="TTM revenue"):
        default_proposal(missing)

    zero_balance = copy.deepcopy(packet)
    zero_balance["balances"]["current_accounts_receivable"]["Q3FY2026"] = 0
    candidate = default_proposal(zero_balance)
    assert candidate.current_ar_dso == 0


def test_unresolved_historical_movement_stays_diagnostic(packet):
    item = packet["historical_bridge"]["current_accounts_receivable"]
    assert item["balance_change_fy25_to_q3"] == pytest.approx(-9864)
    assert item["reported_cfs_contribution_9m"] == pytest.approx(8347)
    assert item["stock_implied_cash_effect_9m"] == pytest.approx(9864)
    assert item["unexplained_difference"] == pytest.approx(-1517)
    inventory = packet["historical_bridge"]["inventory"]
    assert inventory["balance_change_fy25_to_q3"] == pytest.approx(281)
    assert inventory["reported_cfs_contribution_9m"] == pytest.approx(-283)
    assert inventory["stock_implied_cash_effect_9m"] == pytest.approx(-281)
    assert inventory["unexplained_difference"] == pytest.approx(-2)
    payable = packet["historical_bridge"]["accounts_payable_reported"]
    assert payable["balance_change_fy25_to_q3"] == pytest.approx(9789)
    assert payable["reported_cfs_contribution_9m"] == pytest.approx(2903)
    assert payable["stock_implied_cash_effect_9m"] == pytest.approx(9789)
    assert payable["unexplained_difference"] == pytest.approx(-6886)


def test_source_locked_contract_parameters_are_derived_outside_candidate(packet):
    candidate = default_proposal(packet)
    assert "contract_recognition_share" not in candidate.model_dump()
    assert "current_contract_presentation_share" not in candidate.model_dump()
    assert "contract_billings_to_recognition" not in candidate.model_dump()
    assert "accrued_compensation_baseline" not in candidate.model_dump()
    assert "accrued_compensation_effective_ratio" not in candidate.model_dump()
    model = build_working_capital_model(
        {**packet, "p6_forecast": {"consolidated_revenue": [90.0] * 11, "cost_of_revenue": [54.0] * 11}},
        candidate,
        review_proposal(candidate, packet),
    )
    assert model["inputs"]["contract_billings_to_recognition"] == 1.0
    assert model["inputs"]["contract_recognition_share"] == pytest.approx(157030 / 241832)
    assert model["inputs"]["current_contract_presentation_share"] == pytest.approx(50924 / 53677)
    assert model["inputs"]["accrued_compensation_baseline"] == pytest.approx(11270 / 318273)
    assert model["inputs"]["source_locked_parameters"]["basis"]["contract_recognition_share"]


def test_structured_schema_keeps_judgment_bounds_and_excludes_locked_fields(packet):
    candidate = default_proposal(packet)
    with pytest.raises(ValidationError):
        WorkingCapitalProposal.model_validate({**candidate.model_dump(), "server_receivable_change_first_stub": 0.21})
    with pytest.raises(ValidationError):
        WorkingCapitalProposal.model_validate({**candidate.model_dump(), "contract_billing_multiplier_first_stub": 0.89})
    context = _context(packet)
    payload = _proposal_payload(packet, context, "initial analyst selection")
    schema = _request(INITIAL_ANALYST_INSTRUCTION, payload, WorkingCapitalProposal)["text"]["format"]["schema"]
    assert "contract_recognition_share" not in schema["properties"]
    assert "current_contract_presentation_share" not in schema["properties"]
    assert "accrued_compensation_baseline" not in schema["properties"]
    assert "accrued_compensation_multiplier" in schema["properties"]
    assert schema["properties"]["accrued_compensation_multiplier"]["minimum"] == 0.8
    assert schema["properties"]["accrued_compensation_multiplier"]["maximum"] == 1.2
    assert schema["properties"]["server_receivable_change_first_stub"]["minimum"] == -0.2
    assert schema["properties"]["contract_billing_multiplier_first_stub"]["maximum"] == 1.1


def test_compensation_units_reject_coercible_values_and_bind_review_payload(packet):
    candidate = default_proposal(packet)
    for raw in (False, True, None, "", "  "):
        with pytest.raises(ValidationError):
            WorkingCapitalProposal.model_validate({**candidate.model_dump(), "accrued_compensation_multiplier": raw})
    with pytest.raises(ValidationError):
        WorkingCapitalProposal.model_validate({**candidate.model_dump(), "accrued_compensation_multiplier": 0.0})
    payload = _review_payload(packet, _context(packet), candidate, {"status": "PASS"})
    assert payload["accrued_compensation_driver"]["source_baseline"] == pytest.approx(11270 / 318273)
    assert payload["accrued_compensation_driver"]["multiplier"] == pytest.approx(1.0)
    assert payload["accrued_compensation_driver"]["effective_ratio"] == pytest.approx(11270 / 318273)
    assert payload["accrued_compensation_driver"]["multiplier_units"] == "dimensionless"


def test_compensation_multiplier_changes_are_consequential(packet):
    candidate = default_proposal(packet)
    _consequential(candidate, candidate.model_copy(update={"accrued_compensation_multiplier": 1.2}), "accrued_compensation")
    with pytest.raises(WorkingCapitalError, match="multiplier"):
        _consequential(candidate, candidate, "accrued_compensation")

    p7 = {**packet, "p6_forecast": {"consolidated_revenue": [90.0] * 11, "cost_of_revenue": [54.0] * 11}}
    high = build_working_capital_model(p7, candidate.model_copy(update={"accrued_compensation_multiplier": 1.2}), review_proposal(candidate, packet))
    low = build_working_capital_model(p7, candidate.model_copy(update={"accrued_compensation_multiplier": 0.8}), review_proposal(candidate, packet))
    assert high["forecast"]["accrued_compensation_closing"][0] > low["forecast"]["accrued_compensation_closing"][0]
    assert high["forecast"]["cfo_contribution"][0] > low["forecast"]["cfo_contribution"][0]


def test_source_locked_presentation_cannot_be_revised(packet):
    candidate = default_proposal(packet)
    with pytest.raises(WorkingCapitalError, match="application-locked"):
        _consequential(candidate, candidate.model_copy(update={"current_ar_dso": candidate.current_ar_dso + 1}), "presentation")


def test_recovery_metadata_is_not_added_to_exact_request(monkeypatch, packet):
    monkeypatch.setenv("P7_RECOVERY_REASON", "must not alter request identity")
    request = _request(INITIAL_ANALYST_INSTRUCTION, {"packet": packet}, WorkingCapitalProposal)
    assert "metadata" not in request
    assert request["model"] == MODEL
    assert request["reasoning"] == {"effort": REASONING_EFFORT}
    assert request["max_output_tokens"] == MAX_OUTPUT_TOKENS


def test_prepare_live_handoff_writes_exact_request_and_context(tmp_path):
    run_dir = tmp_path / "live-r3"
    manifest = prepare_live_handoff(
        p6_model(),
        run_dir,
        source_table=SOURCE,
        output_path=run_dir / "model-input.json",
        budget_path=tmp_path / "shared-budget.json",
    )
    request = json.loads((run_dir / "attempts" / "01-analyst-initial.request.json").read_text(encoding="utf-8"))
    context = json.loads((run_dir / "run-context.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "PREPARED_NO_DISPATCH"
    assert manifest["canonical_request_equal"] is True
    assert manifest["request_hash"] == manifest["request_rebuilt_hash"]
    assert request["model"] == MODEL
    assert request["reasoning"] == {"effort": "medium"}
    assert request["service_tier"] == "default"
    assert request["max_output_tokens"] == 12000
    assert context["reasoning_effort"] == "medium"
    assert context["max_output_tokens"] == 12000
    assert "--run-dir" in manifest["cli"]


def test_all_p7_stages_use_same_explicit_request_settings(tmp_path, monkeypatch):
    import smrik_fund.working_capital as module

    value = make_packet()
    original = default_proposal(value)
    revised = original.model_copy(update={"current_ar_dso": original.current_ar_dso + 1.0})
    client = QueueClient([original, revise_review(), revised, accepted_review()])
    monkeypatch.setattr(module, "_build_authority", lambda *args, **kwargs: {"status": "PASS", "snapshot": {"status": "PASS"}})
    proposal, review, model = run_reasoning(value, p6_model(), tmp_path / "run", budget(tmp_path), client=client)
    assert proposal.model_dump() == revised.model_dump()
    assert review.verdict == "accept"
    assert model["decision"]["status"] == "SYSTEM_REVIEWED_PROVISIONAL"
    assert len(client.responses.calls) == 4
    for call in client.responses.calls:
        assert call["model"] == MODEL
        assert call["reasoning"] == {"effort": "medium"}
        assert call["service_tier"] == "default"
        assert call["max_output_tokens"] == 12000
        assert call["tools"] == []
        assert call["background"] is False
        assert "metadata" not in call


def test_rejected_review_preserves_candidate_and_publishes_terminal_state(tmp_path, monkeypatch):
    import smrik_fund.working_capital as module

    value = make_packet()
    rejected = accepted_review().model_copy(update={"verdict": "reject", "evidence_strength": "weak", "method_valid": False, "source_valid": False, "period_valid": False, "cash_sign_valid": False, "exclusions_valid": False, "no_double_count": False, "concerns": ["Rejected by review."]})
    client = QueueClient([default_proposal(value), rejected])
    monkeypatch.setattr(module, "_build_authority", lambda *args, **kwargs: {"status": "PASS", "snapshot": {"status": "PASS"}})
    with pytest.raises(WorkingCapitalError, match="review did not accept"):
        run_reasoning(value, p6_model(), tmp_path / "run", budget(tmp_path), client=client)
    run_dir = tmp_path / "run"
    assert (run_dir / "candidate-initial.json").exists()
    assert (run_dir / "review-original.json").exists()
    assert json.loads((run_dir / "terminal-outcome.json").read_text(encoding="utf-8"))["status"] == "REJECTED_BY_REVIEW"
    assert not (run_dir / "model.json").exists()


def test_completed_analyst_result_resumes_after_local_mog_interruption(tmp_path, monkeypatch):
    import smrik_fund.working_capital as module

    value = make_packet()
    run_dir = tmp_path / "run"
    first_client = QueueClient([default_proposal(value)])
    monkeypatch.setattr(module, "_build_authority", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("local Mog interruption")))
    with pytest.raises(RuntimeError, match="local Mog interruption"):
        run_reasoning(value, p6_model(), run_dir, budget(tmp_path), client=first_client)
    assert len(first_client.responses.calls) == 1
    assert json.loads((run_dir / "terminal-outcome.json").read_text(encoding="utf-8"))["status"] == "MOG_AUTHORITY_INCOMPLETE"

    second_client = QueueClient([accepted_review()])
    monkeypatch.setattr(module, "_build_authority", lambda *args, **kwargs: {"status": "PASS", "snapshot": {"status": "PASS"}})
    _proposal, review, _model = run_reasoning(value, p6_model(), run_dir, tmp_path / "budget.json", client=second_client)
    assert review.verdict == "accept"
    assert len(second_client.responses.calls) == 1
    assert (run_dir / "model.json").exists()
