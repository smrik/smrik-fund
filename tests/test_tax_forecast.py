import copy
import json
import shutil
import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

import smrik_fund.tax_forecast as tax_forecast
from smrik_fund.analysis_budget import content_hash
from smrik_fund.tax_forecast import (
    MAX_ATTEMPTS,
    PERIODS,
    TaxForecastError,
    TaxProposal,
    TaxReview,
    _consequential,
    _context,
    _forecast_values,
    _payable_timing_anchors,
    _period_meta,
    _proposal_payload,
    _request,
    _review_payload,
    build_evidence_packet,
    default_proposal,
    prepare_live_handoff,
    review_proposal,
    run_reasoning,
    validate_proposal,
)

ROOT = Path(__file__).resolve().parents[1]
P7 = ROOT / "data" / "build-guide-p7" / "live-r4" / "model-input.json"
SOURCE = ROOT / "Lunacy" / "runs" / "three-statement-dcf" / "phases" / "taxes" / "P8A-source-table-R1.csv"


def oracle_packet():
    p7 = json.loads(P7.read_text(encoding="utf-8"))
    packet = build_evidence_packet(p7, SOURCE)
    packet = copy.deepcopy(packet)
    packet["p7_forecast"]["ebit"] = [120.0] * len(PERIODS)
    packet["opening_balances"]["current_tax_payable"]["value"] = 8.0
    packet["opening_balances"]["long_term_tax_liability"]["value"] = 12.0
    packet["opening_balances"]["deferred_tax_liability"]["value"] = 12.0
    return packet


def proposal(**overrides):
    values = {
        "outcome": "propose_forecast",
        "method_id": "linked_book_current_deferred_cash_tax",
        "method_version": "v2",
        "book_tax_rate": 0.25,
        "operating_tax_rate": 0.25,
        "deferred_share": [0.2] * len(PERIODS),
        "current_tax_payable_method": "explicit_closing_balance",
        "current_tax_payable_days": None,
        "current_tax_payable_closing": [10.0] * len(PERIODS),
        "long_term_tax_settlement": [0.0] * len(PERIODS),
        "dta_policy": "hold_flat_no_new_recognition",
        "nol_policy": "no_utilization_or_refund",
        "evidence_refs": ["book_tax_expense"],
        "rationale": "Fictional arithmetic fixture.",
        "alternatives": [],
        "uncertainty": ["Fixture only."],
        "follow_up_request": None,
    }
    values.update(overrides)
    return TaxProposal(**values)


def days_proposal(**overrides):
    values = {
        "current_tax_payable_method": "source_anchored_payable_days",
        "current_tax_payable_days": 91.25,
        "current_tax_payable_closing": None,
    }
    values.update(overrides)
    return proposal(**values)


def test_oracle_tax_bridge_and_interest_independence():
    packet = oracle_packet()
    candidate = proposal()
    base = _forecast_values(packet, candidate, interest_expense=[20.0] * len(PERIODS))
    shocked = _forecast_values(packet, candidate, interest_expense=[30.0] * len(PERIODS))

    assert base["pretax_income"][0] == 100.0
    assert base["book_tax_expense"][0] == 25.0
    assert base["current_tax_expense"][0] == 20.0
    assert base["deferred_tax_expense"][0] == 5.0
    assert base["current_tax_payment"][0] == 18.0
    assert base["deferred_tax_liability_closing"][0] == 17.0
    assert base["tax_cfo_adjustment"][0] == 7.0
    assert shocked["pretax_income"][0] == 90.0
    assert shocked["book_tax_expense"][0] == 22.5
    assert shocked["current_tax_expense"][0] == 18.0
    assert shocked["deferred_tax_expense"][0] == 4.5
    assert shocked["current_tax_payment"][0] == 16.0
    assert shocked["deferred_tax_liability_closing"][0] == 16.5
    assert shocked["tax_cfo_adjustment"][0] == 6.5
    assert base["operating_tax_expense"][0] == shocked["operating_tax_expense"][0] == 30.0


def test_r6_source_timing_anchors_and_actual_period_basis():
    p7 = json.loads(P7.read_text(encoding="utf-8"))
    packet = build_evidence_packet(p7, SOURCE)
    timing = packet["payable_timing"]
    direct_timing = _payable_timing_anchors(packet["source_facts"])
    assert timing["selected_method"] == "source_anchored_payable_days"
    assert direct_timing["baseline_days"] == timing["baseline_days"]
    assert timing["baseline_days"] == pytest.approx(7211 / 28851 * 365)
    assert timing["fy2024_alternative_days"] == pytest.approx(5017 / 24389 * 366)
    assert timing["baseline_source"]["actual_period_days"] == 365
    assert timing["fy2024_alternative_source"]["actual_period_days"] == 366
    metadata = _period_meta()
    assert [item["days"] for item in metadata] == [91, 365, 366, 365, 365, 365, 366, 365, 365, 365, 366]
    assert all(item["start"] and item["end"] for item in metadata)
    candidate = default_proposal(packet)
    preview = _forecast_values(packet, candidate)
    assert candidate.current_tax_payable_method == "source_anchored_payable_days"
    assert candidate.current_tax_payable_closing is None
    assert preview["current_tax_payable_closing"][0] == pytest.approx(8383.54950232781 / 91 * (7211 / 28851 * 365))
    assert preview["period_days"] == [item["days"] for item in metadata]


def test_r6_stub_and_annualized_day_basis_are_consistent():
    packet = oracle_packet()
    candidate = days_proposal(book_tax_rate=0.25, operating_tax_rate=0.25, deferred_share=[0.0] * len(PERIODS))
    daily_scaled_annual = 100.0 * 365 / 91
    leap_scaled_annual = 100.0 * 366 / 91
    preview = _forecast_values(
        packet,
        candidate,
        pretax_income=[100.0, daily_scaled_annual, leap_scaled_annual] + [100.0] * (len(PERIODS) - 3),
    )
    assert preview["current_tax_payable_closing"][0] == pytest.approx(25.0 * 91.25 / 91)
    assert preview["current_tax_payable_closing"][1] == pytest.approx(preview["current_tax_payable_closing"][0])
    assert preview["current_tax_payable_closing"][2] == pytest.approx(preview["current_tax_payable_closing"][0])


def test_r6_days_method_zero_missing_and_negative_cash_guards():
    packet = oracle_packet()
    zero = days_proposal(current_tax_payable_days=0)
    validate_proposal(zero, packet)
    zero_preview = _forecast_values(packet, zero)
    assert zero_preview["current_tax_payable_closing"] == [0.0] * len(PERIODS)
    with pytest.raises(ValidationError, match="requires current_tax_payable_days"):
        days_proposal(current_tax_payable_days=None)
    with pytest.raises(TaxForecastError, match="negative current tax payment"):
        validate_proposal(days_proposal(current_tax_payable_days=365), packet)


def test_r6_timing_revision_changes_active_effective_forecast():
    packet = oracle_packet()
    original = days_proposal()
    revised = days_proposal(current_tax_payable_days=92.25)
    _consequential(original, revised, "payable_timing", packet)
    inactive_only = original.model_copy(update={"current_tax_payable_closing": [11.0] * len(PERIODS)})
    with pytest.raises(TaxForecastError, match="did not change active current-payable timing"):
        _consequential(original, inactive_only, "payable_timing", packet)


def test_supported_deferred_reversal_preserves_book_and_operating_tax():
    packet = oracle_packet()
    base = proposal(deferred_share=[0.0] * len(PERIODS))
    reversal = proposal(deferred_share=[-0.1] + [0.0] * (len(PERIODS) - 1))
    base_preview = _forecast_values(packet, base, interest_expense=[20.0] * len(PERIODS))
    reversal_preview = _forecast_values(packet, reversal, interest_expense=[20.0] * len(PERIODS))

    assert reversal_preview["pretax_income"] == base_preview["pretax_income"]
    assert reversal_preview["book_tax_expense"] == base_preview["book_tax_expense"]
    assert reversal_preview["deferred_tax_expense"][0] == -2.5
    assert reversal_preview["deferred_tax_liability_closing"][0] == 9.5
    assert reversal_preview["deferred_tax_liability_closing"][1] == 9.5
    assert reversal_preview["current_tax_payment"][0] - base_preview["current_tax_payment"][0] == 2.5
    assert base_preview["operating_tax_expense"] == reversal_preview["operating_tax_expense"]
    assert reversal_preview["tax_cfo_adjustment"][0] - base_preview["tax_cfo_adjustment"][0] == -2.5


def test_loss_has_no_refund_or_automatic_deferred_benefit():
    packet = oracle_packet()
    candidate = proposal(
        deferred_share=[0.0] * len(PERIODS),
        current_tax_payable_closing=[8.0] * len(PERIODS),
    )
    loss = _forecast_values(packet, candidate, interest_expense=[130.0] * len(PERIODS))
    assert loss["pretax_income"][0] == -10.0
    assert loss["book_tax_expense"][0] == 0.0
    assert loss["current_tax_payment"][0] == 0.0
    assert loss["deferred_tax_liability_closing"][0] == 12.0
    assert loss["operating_tax_expense"][0] == 30.0


def test_invalid_settlement_and_dtl_underflow_are_rejected():
    packet = oracle_packet()
    with pytest.raises(TaxForecastError, match="exceeds booked liability"):
        validate_proposal(
            proposal(long_term_tax_settlement=[13.0] + [0.0] * 10),
            packet,
        )
    with pytest.raises(TaxForecastError, match="underflows reported DTL"):
        validate_proposal(
            proposal(deferred_share=[-1.0] * len(PERIODS)),
            packet,
        )
    with pytest.raises(TaxForecastError, match="negative current tax payment"):
        validate_proposal(
            proposal(current_tax_payable_closing=[40.0] * len(PERIODS)),
            packet,
        )
    with pytest.raises(TaxForecastError, match="underflows reported DTL"):
        validate_proposal(
            proposal(deferred_share=[0.0] * (len(PERIODS) - 1) + [-1.0]),
            packet,
        )
    with pytest.raises(TaxForecastError, match="exceeds booked liability"):
        validate_proposal(
            proposal(long_term_tax_settlement=[0.0] * (len(PERIODS) - 1) + [13.0]),
            packet,
        )
    with pytest.raises(TaxForecastError, match="negative current tax payment"):
        validate_proposal(
            proposal(current_tax_payable_closing=[10.0] * (len(PERIODS) - 1) + [35.0]),
            packet,
        )


def test_current_timing_and_long_term_settlement_are_one_time_movements():
    packet = oracle_packet()
    candidate = proposal(
        deferred_share=[0.2] * len(PERIODS),
        current_tax_payable_closing=[10.0] * len(PERIODS),
        long_term_tax_settlement=[2.0] + [0.0] * 10,
    )
    preview = _forecast_values(packet, candidate, interest_expense=[20.0] * len(PERIODS))
    assert preview["current_tax_payment"][0] == 18.0
    assert preview["current_tax_payable_movement"][0] == 2.0
    assert preview["long_term_tax_liability_closing"][0] == 10.0
    assert preview["current_tax_expense"][0] == 20.0
    assert preview["tax_cfo_adjustment"][0] == 5.0
    assert preview["cash_taxes"][0] == 20.0


def test_book_and_operating_rates_remain_independent_and_zero_is_supported():
    packet = oracle_packet()
    candidate = proposal(book_tax_rate=0.20, operating_tax_rate=0.30)
    preview = _forecast_values(packet, candidate, interest_expense=[20.0] * len(PERIODS))
    assert preview["book_tax_expense"][0] == 20.0
    assert preview["operating_tax_expense"][0] == 36.0
    assert proposal(deferred_share=[0.0] * len(PERIODS)).deferred_share[0] == 0.0


def test_required_numeric_fields_reject_coercion_and_bool():
    with pytest.raises(ValidationError):
        proposal(book_tax_rate="0.25")
    with pytest.raises(ValidationError):
        proposal(deferred_share=[False] + [0.2] * 10)


def test_tax_proposal_schema_declares_item_bounds_and_units():
    properties = TaxProposal.model_json_schema()["properties"]
    assert properties["book_tax_rate"]["description"].startswith("Decimal fraction")
    deferred_schema = next(item for item in properties["deferred_share"]["anyOf"] if item.get("type") == "array")
    closing_schema = next(item for item in properties["current_tax_payable_closing"]["anyOf"] if item.get("type") == "array")
    settlement_schema = next(item for item in properties["long_term_tax_settlement"]["anyOf"] if item.get("type") == "array")
    assert deferred_schema["items"] == {"maximum": 1, "minimum": -1, "type": "number"}
    assert closing_schema["items"] == {"minimum": 0, "type": "number"}
    assert settlement_schema["items"] == {"minimum": 0, "type": "number"}
    assert "USD millions" in closing_schema.get("description", properties["current_tax_payable_closing"]["description"])


def _assert_recursive_strict_schema(schema):
    if isinstance(schema, dict):
        if schema.get("type") == "object" or "properties" in schema:
            properties = schema.get("properties", {})
            assert schema["additionalProperties"] is False
            assert schema["required"] == list(properties)
        for value in schema.values():
            _assert_recursive_strict_schema(value)
    elif isinstance(schema, list):
        for value in schema:
            _assert_recursive_strict_schema(value)


def test_r7_provider_schemas_are_recursively_strict_and_hashed_as_sent():
    p7 = json.loads(P7.read_text(encoding="utf-8"))
    packet = build_evidence_packet(p7, SOURCE)
    context = _context(packet)
    candidate = default_proposal(packet)
    preview = _forecast_values(packet, candidate)
    requests = [
        (_request("analyst", _proposal_payload(packet, context, "analyst"), TaxProposal), "proposal_schema_hash"),
        (_request("reviewer", _review_payload(packet, context, candidate, preview), TaxReview), "review_schema_hash"),
    ]

    assert MAX_ATTEMPTS == 10
    for request, context_key in requests:
        format_spec = request["text"]["format"]
        assert format_spec["strict"] is True
        schema = format_spec["schema"]
        _assert_recursive_strict_schema(schema)
        assert content_hash(schema) == context[context_key]

    proposal_schema = requests[0][0]["text"]["format"]["schema"]
    required = set(proposal_schema["required"])
    assert {"method_id", "method_version", "current_tax_payable_days", "current_tax_payable_closing", "follow_up_request"} <= required
    for field in (
        "method_id",
        "method_version",
        "current_tax_payable_method",
        "current_tax_payable_days",
        "current_tax_payable_closing",
        "long_term_tax_settlement",
        "follow_up_request",
    ):
        assert any(item.get("type") == "null" for item in proposal_schema["properties"][field]["anyOf"])
    review_schema = requests[1][0]["text"]["format"]["schema"]
    assert any(item.get("type") == "null" for item in review_schema["properties"]["required_revision"]["anyOf"])


def test_r7_non_offline_dispatch_receives_strict_proposal_and_review_requests(monkeypatch):
    p7 = json.loads(P7.read_text(encoding="utf-8"))
    packet = build_evidence_packet(p7, SOURCE)
    candidate = default_proposal(packet)
    review = review_proposal(candidate, packet, {"status": "PASS"})
    requests = []

    def fake_dispatch(**kwargs):
        requests.append(kwargs["prepared_request"])
        return (candidate, {}) if kwargs["response_model"] is TaxProposal else (review, {})

    monkeypatch.setattr(tax_forecast, "_dispatch_structured", fake_dispatch)
    monkeypatch.setattr(tax_forecast, "_build_authority", lambda *args, **kwargs: {"status": "PASS", "snapshot": {}})
    run_dir = ROOT / f".tmp-p8a-schema-{uuid.uuid4().hex}"
    try:
        run_reasoning(packet, p7, run_dir, run_dir / "budget.json")

        assert [request["text"]["format"]["schema"]["required"] for request in requests] == [
            list(requests[0]["text"]["format"]["schema"]["properties"]),
            list(requests[1]["text"]["format"]["schema"]["properties"]),
        ]
        assert all(request["text"]["format"]["strict"] is True for request in requests)
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def test_live_handoff_is_exactly_reproducible():
    run_dir = ROOT / f".tmp-p8a-handoff-{uuid.uuid4().hex}"
    budget_path = run_dir / "budget.json"
    try:
        first = prepare_live_handoff(
            json.loads(P7.read_text(encoding="utf-8")),
            run_dir,
            source_table=SOURCE,
            output_path=run_dir / "model-input.json",
            budget_path=budget_path,
        )
        resumed = prepare_live_handoff(
            json.loads(P7.read_text(encoding="utf-8")),
            run_dir,
            source_table=SOURCE,
            output_path=run_dir / "model-input.json",
            budget_path=budget_path,
        )
        assert first == resumed
        assert first["status"] == "PREPARED_NO_DISPATCH"
        assert first["canonical_request_equal"] is True
        assert (run_dir / "attempts/01-analyst-initial.request.json").exists()
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def test_r6_declared_unresolved_is_terminal_before_publication(monkeypatch):
    p7 = json.loads(P7.read_text(encoding="utf-8"))
    packet = build_evidence_packet(p7, SOURCE)
    run_dir = ROOT / f".tmp-p8a-terminal-{uuid.uuid4().hex}"
    budget_path = run_dir / "budget.json"
    candidate = TaxProposal(
        outcome="unresolved",
        evidence_refs=["current_tax_expense"],
        rationale="Q3 current/deferred split is unavailable.",
        alternatives=[],
        uncertainty=["No forecast can be supported from the selected evidence."],
        follow_up_request="Obtain the jurisdictional current/deferred tax schedule.",
    )

    def fake_dispatch(**kwargs):
        return candidate, {"status": "FAKE"}

    monkeypatch.setattr(tax_forecast, "_dispatch_structured", fake_dispatch)
    try:
        with pytest.raises(TaxForecastError, match="declared unresolved"):
            tax_forecast.run_reasoning(packet, p7, run_dir, budget_path, offline=False)
        terminal = json.loads((run_dir / "terminal-outcome.json").read_text(encoding="utf-8"))
        assert terminal["status"] == "UNRESOLVED_NO_FORECAST"
        assert terminal["outcome"] == "unresolved"
        assert terminal["follow_up_request"].startswith("Obtain")
        assert not (run_dir / "model.json").exists()
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def test_r6_changed_context_cannot_reuse_prior_outputs():
    p7 = json.loads(P7.read_text(encoding="utf-8"))
    packet = build_evidence_packet(p7, SOURCE)
    run_dir = ROOT / f".tmp-p8a-context-{uuid.uuid4().hex}"
    budget_path = run_dir / "budget.json"
    try:
        tax_forecast.run_reasoning(packet, p7, run_dir, budget_path, offline=True)
        prior_model = (run_dir / "model.json").read_text(encoding="utf-8")
        changed = copy.deepcopy(packet)
        changed["p7_forecast"]["ebit"][0] += 1.0
        with pytest.raises(TaxForecastError, match="context changed"):
            tax_forecast.run_reasoning(changed, p7, run_dir, budget_path, offline=True)
        terminal = json.loads((run_dir / "terminal-outcome.json").read_text(encoding="utf-8"))
        assert terminal["status"] == "CONTEXT_STALE"
        assert (run_dir / "model.json").read_text(encoding="utf-8") == prior_model
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)
