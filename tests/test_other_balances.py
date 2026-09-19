import copy
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from openai import OpenAI

import smrik_fund.other_balances as other_balances
from smrik_fund.analysis_budget import initialize_budget

ROOT = Path(__file__).parents[1]
P8C_PATH = ROOT / "data/build-guide-p8c/live-r6/model-input.json"
BUDGET_PATH = ROOT / "data/build-guide-api-budget.json"
P8D_RUNNER = ROOT / "scripts/spreadsheet_compat/run-p8d.mjs"
P8D_LIVE_R1_INPUT = ROOT / "data/build-guide-p8d/live-r1/analyst-initial-model-input.json"


@pytest.fixture
def p8c() -> dict:
    return json.loads(P8C_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def budget(tmp_path: Path) -> Path:
    path = tmp_path / "budget.json"
    prices = json.loads(BUDGET_PATH.read_text(encoding="utf-8"))["prices"]
    initialize_budget(path, ceiling_eur=5.0, final_review_reserve_eur=0.5, prices=prices)
    return path


def _proposal(packet: dict) -> other_balances.OtherBalancesProposal:
    return other_balances.default_proposal(packet)


def _review(**changes: object) -> other_balances.OtherBalancesReview:
    values = {
        "verdict": "accept",
        "evidence_strength": "mixed",
        "method_valid": True,
        "source_valid": True,
        "period_valid": True,
        "investment_bridge_valid": True,
        "intangible_bridge_valid": True,
        "cash_noncash_separated": True,
        "residual_coverage_valid": True,
        "tax_effect_contained": True,
        "no_double_count": True,
        "concerns": ["Unknown OpenAI carrying amount remains visible."],
        "required_revision": None,
        "target": "none",
        "rationale": "Bounded review passed.",
    }
    values.update(changes)
    return other_balances.OtherBalancesReview.model_validate(values)


def _run_p8d_authority(input_path: Path, run_dir: Path) -> dict:
    result = subprocess.run(
        ["node", str(P8D_RUNNER), "authority", str(input_path), str(run_dir)],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr[-4000:]
    return json.loads((run_dir / "p8d-verification.json").read_text(encoding="utf-8"))


class FakeResponses:
    def __init__(self, outputs: list[object], *, fail: Exception | None = None) -> None:
        self.outputs = outputs
        self.calls: list[dict] = []
        self.fail = fail

    def create(self, **request: object) -> SimpleNamespace:
        self.calls.append(request)
        if self.fail:
            raise self.fail
        value = self.outputs.pop(0)
        usage = SimpleNamespace(model_dump=lambda **_: {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2})
        return SimpleNamespace(output_text=json.dumps(value), id=f"resp-{len(self.calls)}", model=other_balances.MODEL, usage=usage)


class FakeClient:
    def __init__(self, outputs: list[object], *, fail: Exception | None = None) -> None:
        self.responses = FakeResponses(outputs, fail=fail)


def test_source_locked_forecast_preserves_selected_arithmetic(p8c: dict) -> None:
    packet = other_balances.build_evidence_packet(p8c)
    proposal = _proposal(packet)
    forecast = other_balances.forecast_values(packet, proposal)

    assert packet["facts"]["calculated"]["opening_income_pool"] == 91218.0
    assert packet["facts"]["calculated"]["known_investment_value"] == 91436.0
    assert packet["facts"]["source"]["identified_long_term_debt_investments"] == 10346.0
    schedule = packet["facts"]["intangible_schedule"]
    assert schedule["stub"] == 1024.0
    assert schedule["annual_explicit"] == [3032.0, 2081.0, 1890.0, 1425.0]
    assert schedule["tail"] == 9873.0
    assert schedule["total"] == 19325.0
    assert forecast["forecast_authority"].startswith("Mog formulas")
    assert "net_income" not in forecast
    assert "cfo" not in forecast
    assert "closing_cash" not in forecast
    assert forecast["investment"]["value_bridge"]["total"] == 114555.0
    assert forecast["investment"]["value_bridge"]["commitment_net_measurement_adjustment"] == 0.0
    assert forecast["intangible"]["reported_schedule"]["total"] == 19325.0
    assert forecast["checks"]["unsupported_residual_movement"] == "requires_actual_mog_balance_check"
    assert forecast["all_pass"] is None


def test_actual_live_fraction_zero_candidate_passes_authority(tmp_path: Path) -> None:
    verification = _run_p8d_authority(P8D_LIVE_R1_INPUT, tmp_path / "live-r1")
    snapshot = verification["snapshot"]
    assert snapshot["otherBalances"]["investmentValue"][0] == pytest.approx(113367.5298744113)
    assert snapshot["otherBalances"]["commitmentNetMeasurementAdjustment"][0] == pytest.approx(-1187.470125588711)
    assert verification["selected"]["unfundedCommitmentValueFraction"] == 0


def test_actual_mog_builder_accepts_nondefault_multi_parameter_candidate(p8c: dict, tmp_path: Path) -> None:
    packet = other_balances.build_evidence_packet(p8c)
    context = other_balances._run_context(p8c, packet)
    base = _proposal(packet)
    nondefault = base.model_copy(update={
        "other_investment_value_multiplier": 1.5,
        "cash_income_yield": 0.045,
        "intangible_tail_life_years": 15,
        "goodwill_impairment": 10.0,
        "unfunded_commitment_value_fraction": 0.0,
        "legal_stress": 400.0,
        "incremental_net_dta_value": 26273.0,
        "unrealized_investment_gain": 14.0,
    })
    base_dir = tmp_path / "base"
    selected_dir = tmp_path / "nondefault"
    base_dir.mkdir()
    selected_dir.mkdir()
    base_authority = other_balances._actual_mog_candidate(p8c, packet, base, context, base_dir, "analyst-initial")
    selected_authority = other_balances._actual_mog_candidate(p8c, packet, nondefault, context, selected_dir, "analyst-initial")
    source = packet["facts"]["source"]
    selected_snapshot = selected_authority["snapshot"]
    expected_adjustment = -source["unfunded_commitment"] / (1.043 ** (91 / 365))
    expected_value = source["known_investment_value"] + source["other_investment_pool"] * 1.5 + source["financing_receivables"] + expected_adjustment
    assert selected_snapshot["otherBalances"]["investmentValue"][0] == pytest.approx(expected_value)
    assert selected_snapshot["otherBalances"]["investmentClosing"][0] == pytest.approx(34897.0)
    assert selected_snapshot["otherBalances"]["commitmentRightsValue"][0] == pytest.approx(0.0)
    assert selected_snapshot["otherBalances"]["commitmentNetMeasurementAdjustment"][0] == pytest.approx(expected_adjustment)
    assert selected_snapshot["otherBalances"]["intangibleClosing"][10] == pytest.approx(5923.8)
    expected_income = (
        max(selected_snapshot["otherBalances"]["actualOpeningCash"][1], 0)
        + selected_snapshot["otherBalances"]["eligibleNoncashPool"]
    ) * 0.045 * selected_snapshot["otherBalances"]["periodDays"][1] / 365
    assert selected_snapshot["otherBalances"]["cashIncome"][1] == pytest.approx(expected_income)
    assert selected_snapshot["stub"]["netIncome"] != base_authority["snapshot"]["stub"]["netIncome"]


def test_source_calibration_is_required_and_explicit(p8c: dict, tmp_path: Path) -> None:
    with pytest.raises(other_balances.OtherBalancesError, match="source calibration is missing"):
        other_balances.build_evidence_packet(p8c, source_calibration=tmp_path / "missing.json")

    calibration = json.loads(
        (ROOT / "data/build-guide-p8d/integrity-r2/source-calibration.json").read_text(encoding="utf-8")
    )
    calibration["values"].pop("identified_long_term_debt_investments")
    invalid = tmp_path / "incomplete-calibration.json"
    invalid.write_text(json.dumps(calibration), encoding="utf-8")
    with pytest.raises(other_balances.OtherBalancesError, match="calibration value identified_long_term_debt_investments"):
        other_balances.build_evidence_packet(p8c, source_calibration=invalid)


def test_strict_proposal_rejects_coercion_and_nonfinite(p8c: dict) -> None:
    packet = other_balances.build_evidence_packet(p8c)
    base = _proposal(packet).model_dump(mode="json")
    with pytest.raises(ValueError, match="must be numeric"):
        other_balances.OtherBalancesProposal.model_validate({**base, "cash_income_yield": "0.03"})
    with pytest.raises(ValueError, match="must be numeric"):
        other_balances.OtherBalancesProposal.model_validate({**base, "cash_income_yield": True})
    with pytest.raises(ValueError, match="finite"):
        other_balances.OtherBalancesProposal.model_validate({**base, "cash_income_yield": float("nan")})


def _assert_recursive_strict_schema(schema: object) -> None:
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


def test_sensitivity_schema_is_closed_and_nested_output_is_not_coercible(p8c: dict) -> None:
    packet = other_balances.build_evidence_packet(p8c)
    proposal = _proposal(packet)
    schema = other_balances._strict_schema(other_balances.OtherBalancesProposal)
    _assert_recursive_strict_schema(schema)
    sensitivity = schema["$defs"]["OtherBalancesSensitivity"]
    assert sensitivity["required"] == ["parameter", "low", "base", "high"]
    assert proposal.sensitivities[0].model_dump(mode="json") == {
        "parameter": "other_investment_value_multiplier",
        "low": 0.5,
        "base": 1.0,
        "high": 1.5,
    }

    for bad_value, message in (("0.5", "must be numeric"), (True, "must be numeric"), (float("nan"), "finite"), (float("inf"), "finite")):
        malformed = copy.deepcopy(proposal.model_dump(mode="json"))
        malformed["sensitivities"][0]["low"] = bad_value
        with pytest.raises(ValueError, match=message):
            other_balances.OtherBalancesProposal.model_validate(malformed)

    malformed = copy.deepcopy(proposal.model_dump(mode="json"))
    malformed["sensitivities"][0]["low"] = "0.5"
    with pytest.raises(other_balances.OtherBalancesError, match="semantic validation"):
        other_balances._parse_structured_response(
            {"output_text": json.dumps(malformed)}, other_balances.OtherBalancesProposal
        )

    malformed = copy.deepcopy(proposal.model_dump(mode="json"))
    malformed["sensitivities"][0]["unexpected"] = 1
    with pytest.raises(other_balances.OtherBalancesError, match="semantic validation"):
        other_balances._parse_structured_response(
            {"output_text": json.dumps(malformed)}, other_balances.OtherBalancesProposal
        )


def _sdk_response(value: object, ordinal: int) -> dict[str, object]:
    return {
        "id": f"resp-{ordinal}",
        "created_at": 0,
        "model": other_balances.MODEL,
        "object": "response",
        "output": [
            {
                "id": f"msg-{ordinal}",
                "content": [
                    {
                        "annotations": [],
                        "text": json.dumps(value),
                        "type": "output_text",
                    }
                ],
                "role": "assistant",
                "status": "completed",
                "type": "message",
            }
        ],
        "parallel_tool_calls": False,
        "tool_choice": "none",
        "tools": [],
        "status": "completed",
        "usage": {
            "input_tokens": 1,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": 1,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": 2,
        },
    }


def test_real_sdk_mock_transport_captures_all_four_strict_stage_wires(
    p8c: dict, budget: Path, tmp_path: Path
) -> None:
    packet = other_balances.build_evidence_packet(p8c)
    original = _proposal(packet)
    revised = original.model_copy(update={"cash_income_yield": original.cash_income_yield + 0.005})
    revise = _review(
        verdict="revise",
        required_revision="Use the supported yield anchor range.",
        target="yield",
    )
    outputs = [
        original.model_dump(mode="json"),
        revise.model_dump(mode="json"),
        revised.model_dump(mode="json"),
        _review().model_dump(mode="json"),
    ]
    captured: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, json=_sdk_response(outputs[len(captured) - 1], len(captured)), request=request)

    prepared_dir = tmp_path / "prepared"
    other_balances.prepare_live_handoff(p8c, prepared_dir)
    canonical = json.loads(
        (prepared_dir / "attempts/01-analyst-initial.request.json").read_text()
    )
    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as http_client:
        client = OpenAI(api_key="dummy-local-key", base_url="http://mock/v1", http_client=http_client)
        result = other_balances.run_reasoning(
            p8c,
            tmp_path / "run",
            budget,
            client=client,
            mog_builder=lambda *args: {"status": "PASS", "stage": args[-1]},
        )

    assert result["decision"]["selected_stage"] == "revision"
    assert len(captured) == 4
    assert captured[0] == canonical
    response_models = [
        other_balances.OtherBalancesProposal,
        other_balances.OtherBalancesReview,
        other_balances.OtherBalancesProposal,
        other_balances.OtherBalancesReview,
    ]
    for body, response_model in zip(captured, response_models, strict=True):
        assert body["model"] == other_balances.MODEL
        assert body["reasoning"] == {"effort": other_balances.REASONING_EFFORT}
        assert body["service_tier"] == "default"
        assert body["tools"] == []
        assert body["background"] is False
        assert body["max_output_tokens"] == other_balances.MAX_OUTPUT_TOKENS
        assert body["text"]["format"]["strict"] is True
        schema = body["text"]["format"]["schema"]
        _assert_recursive_strict_schema(schema)
        assert schema == other_balances._strict_schema(response_model)


def test_live_accept_uses_two_calls_and_exact_resume(p8c: dict, budget: Path, tmp_path: Path) -> None:
    packet = other_balances.build_evidence_packet(p8c)
    proposal = _proposal(packet)
    client = FakeClient([proposal.model_dump(mode="json"), _review().model_dump(mode="json")])
    mog_stages: list[str] = []

    def mog(*args: object) -> dict:
        mog_stages.append(str(args[-1]))
        return {"status": "PASS", "stage": args[-1]}

    result = other_balances.run_reasoning(p8c, tmp_path / "accept", budget, client=client, mog_builder=mog)
    assert result["decision"]["status"] == "SYSTEM_REVIEWED_PROVISIONAL"
    assert result["decision"]["selected_stage"] == "original"
    assert len(client.responses.calls) == 2
    assert mog_stages == ["analyst-initial"]
    resumed = other_balances.run_reasoning(p8c, tmp_path / "accept", budget, client=client, mog_builder=mog)
    assert resumed["decision"]["status"] == "SYSTEM_REVIEWED_PROVISIONAL"
    assert len(client.responses.calls) == 2


def test_revision_recalculates_only_consequential_target(p8c: dict, budget: Path, tmp_path: Path) -> None:
    packet = other_balances.build_evidence_packet(p8c)
    original = _proposal(packet)
    revised = original.model_copy(update={"cash_income_yield": original.cash_income_yield + 0.005})
    review = _review(verdict="revise", required_revision="Use the supported yield anchor range.", target="yield")
    client = FakeClient([original.model_dump(mode="json"), review.model_dump(mode="json"), revised.model_dump(mode="json"), _review().model_dump(mode="json")])
    stages: list[str] = []
    result = other_balances.run_reasoning(p8c, tmp_path / "revision", budget, client=client, mog_builder=lambda *args: stages.append(str(args[-1])) or {"status": "PASS", "stage": args[-1]})
    assert result["decision"]["selected_stage"] == "revision"
    assert stages == ["analyst-initial", "analyst-revision"]
    assert len(client.responses.calls) == 4


def test_unchanged_revision_preserves_no_effective_model(p8c: dict, budget: Path, tmp_path: Path) -> None:
    packet = other_balances.build_evidence_packet(p8c)
    original = _proposal(packet)
    review = _review(verdict="revise", required_revision="Change the supported yield.", target="yield")
    client = FakeClient([original.model_dump(mode="json"), review.model_dump(mode="json"), original.model_dump(mode="json")])
    with pytest.raises(other_balances.OtherBalancesError, match="revision"):
        other_balances.run_reasoning(p8c, tmp_path / "unchanged", budget, client=client, mog_builder=lambda *args: {"status": "PASS"})
    assert len(client.responses.calls) == 3
    assert not (tmp_path / "unchanged" / "model.json").exists()
    assert json.loads((tmp_path / "unchanged" / "decision-held.json").read_text())["status"] == "FAILED"


@pytest.mark.parametrize("stage", ["initial", "revision"])
def test_nonforecast_outcome_stops_before_forecast(p8c: dict, budget: Path, tmp_path: Path, stage: str) -> None:
    packet = other_balances.build_evidence_packet(p8c)
    candidate = _proposal(packet).model_dump(mode="json")
    candidate.update(dict.fromkeys(("method_id", "method_version", "other_investment_value_multiplier", "cash_income_yield", "intangible_tail_life_years", "goodwill_impairment", "unfunded_commitment_value_fraction", "legal_stress", "incremental_net_dta_value", "unrealized_investment_gain", "future_acquisitions", "commitment_timing")))
    candidate.update({"outcome": "capability_gap" if stage == "initial" else "unresolved", "follow_up_request": "Need evidence before forecasting."})
    initial_review = _review(verdict="revise", required_revision="Resolve evidence.", target="yield")
    outputs = [candidate] if stage == "initial" else [_proposal(packet).model_dump(mode="json"), initial_review.model_dump(mode="json"), candidate]
    client = FakeClient(outputs)
    mog_stages: list[str] = []
    result = other_balances.run_reasoning(p8c, tmp_path / stage, budget, client=client, mog_builder=lambda *args: mog_stages.append(str(args[-1])) or {"status": "PASS"})
    assert result["decision"]["status"] == ("CAPABILITY_GAP" if stage == "initial" else "UNRESOLVED")
    assert mog_stages == ([] if stage == "initial" else ["analyst-initial"])


def test_invalid_response_and_provider_failure_hold_attempt(p8c: dict, budget: Path, tmp_path: Path) -> None:
    invalid = FakeClient([{}])
    with pytest.raises(other_balances.OtherBalancesError, match="structured output"):
        other_balances.run_reasoning(p8c, tmp_path / "invalid", budget, client=invalid)
    assert json.loads((tmp_path / "invalid" / "decision-held.json").read_text())["status"] == "FAILED"

    failed_budget = tmp_path / "failed-budget.json"
    prices = json.loads(BUDGET_PATH.read_text(encoding="utf-8"))["prices"]
    initialize_budget(failed_budget, ceiling_eur=5.0, final_review_reserve_eur=0.5, prices=prices)
    failed = FakeClient([], fail=RuntimeError("network disabled"))
    with pytest.raises(other_balances.OtherBalancesError, match="provider call failed"):
        other_balances.run_reasoning(p8c, tmp_path / "failed", failed_budget, client=failed)
    assert json.loads((tmp_path / "failed" / "decision-held.json").read_text())["status"] == "BUDGET_HELD"


def test_prepare_wire_request_is_canonical_and_bounded(p8c: dict, tmp_path: Path) -> None:
    run_dir = tmp_path / "prepared"
    manifest = other_balances.prepare_live_handoff(p8c, run_dir)
    request = json.loads((run_dir / "attempts/01-analyst-initial.request.json").read_text())
    assert manifest["canonical_request_equal"] is True
    assert request["service_tier"] == "default"
    assert request["tools"] == []
    assert request["background"] is False
    assert len(json.dumps(request)) < 272000
