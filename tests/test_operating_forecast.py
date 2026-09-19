import json
from pathlib import Path

import pytest

from smrik_fund.operating_forecast import (
	COST_LINES,
	PERIODS,
	SEGMENTS,
	OperatingForecastError,
	build_evidence_packet,
	build_operating_model,
	default_proposal,
	review_proposal,
	validate_proposal,
)

P2 = Path("data/build-guide-p2-r2/MSFT")


def test_frozen_packet_uses_three_reportable_segments_and_separate_alternatives():
	packet = build_evidence_packet(P2)
	assert tuple(packet["segment_history"]) == SEGMENTS
	assert set(packet["segment_history"][SEGMENTS[0]]["revenue"]) == {"FY2023", "FY2024", "FY2025", "CURRENT", "PRIOR"}
	assert packet["consolidated"]["revenue"]["CURRENT_YTD"] == 241832
	assert len(packet["evidence"]) >= 40
	assert len(packet["alternatives"]) == 2
	assert all(item["filing_date"] <= "2026-04-30" for item in packet["evidence"])


def test_default_proposal_reconciles_and_forecasts_from_fy26_actual_ytd_plus_stub():
	packet = build_evidence_packet(P2)
	proposal = default_proposal(packet)
	review = review_proposal(proposal, packet)
	model = build_operating_model(packet, proposal, review)
	assert review.verdict == "accept"
	assert len(model["forecast_revenue"]) == len(PERIODS)
	assert all(len(model["segments"][segment]["forecast_revenue"]) == len(PERIODS) for segment in SEGMENTS)
	assert model["segments"]["Intelligent Cloud"]["forecast_revenue"][0] == pytest.approx((106265 - 76387) * (98485 / 76387))
	assert model["reconciliation"]
	assert all(value == pytest.approx(0) for value in model["reconciliation"].values())
	assert set(model["costs"]) == set(COST_LINES)
	assert all(value > 0 for values in model["costs"].values() for value in values)


def test_p6_contract_rejects_missing_segment_and_segment_cost_allocation():
	packet = build_evidence_packet(P2)
	proposal = default_proposal(packet)
	missing = proposal.model_copy(update={"segment_trajectories": proposal.segment_trajectories[:-1]})
	with pytest.raises(OperatingForecastError, match="each disclosed segment"):
		validate_proposal(missing, packet)
	bad = proposal.model_copy(update={"method_id": "unsupported"})
	with pytest.raises(OperatingForecastError, match="supported method"):
		validate_proposal(bad, packet)
	assert "Segment-level cost allocation" in packet["unavailable"][0]


def test_packet_manifest_is_json_serializable():
	packet = build_evidence_packet(P2)
	proposal = default_proposal(packet)
	review = review_proposal(proposal, packet)
	model = build_operating_model(packet, proposal, review)
	assert json.loads(json.dumps(model))["schema_version"] == "p6-msft-operating-model-v1"
