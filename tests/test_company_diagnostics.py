import copy
from pathlib import Path

import pytest

from smrik_fund.company_diagnostics import (
	historical_ratios,
	rank_drivers,
	run_diagnostics,
)
from smrik_fund.company_model import POLICY_CONTROL_BOUNDS
from smrik_fund.company_run import build
from smrik_fund.portable_model import prepare_model
from smrik_fund.workbook_template import compile_template


def test_ratios_preserve_missing_and_signs():
	m = {
		"annual_history": {
			"periods": [
				{
					"label": "FY1",
					"start": "2024-01-01",
					"end": "2024-12-31",
					"values": {
						"revenue": 100,
						"capex_cash": -5,
						"sbc": 4,
						"cost_cogs": 80,
					},
				},
				{
					"label": "FY2",
					"start": "2025-01-01",
					"end": "2025-12-31",
					"values": {"revenue": 110, "sbc": None},
				},
			]
		}
	}
	r = historical_ratios(m)
	assert r[0]["capex_ratio"] == 0.05
	assert r[0]["sbc_to_cogs"] == 0.05
	assert r[0]["growth"] is None
	assert r[1]["growth"] == pytest.approx(0.1)
	assert r[1]["sbc_ratio"] is None and r[1]["capex_ratio"] is None


def test_rank_impact_not_volatility_and_preserve_blocked_stress():
	drivers = [
		{
			"id": key,
			"historical_stddev": volatility,
			"scenarios": [{"id": key + ":low"}, {"id": key + ":high"}],
		}
		for key, volatility in (("tiny", 0.5), ("large", 0.02), ("unknown", 0))
	]
	snapshot = {
		"per_share_value": 0,
		"diagnostics": [
			{"id": "tiny:low", "per_share_value": -0.1},
			{"id": "tiny:high", "per_share_value": 0.1},
			{"id": "large:low", "per_share_value": -5},
			{"id": "large:high", "per_share_value": 6},
			{"id": "unknown:low", "per_share_value": None},
			{"id": "unknown:high", "per_share_value": None},
		],
	}
	r = rank_drivers(drivers, snapshot, 10)
	assert [d["id"] for d in r] == ["unknown", "large", "tiny"]
	assert r[0]["impact_fraction_of_market_price"] is None
	assert r[1]["impact_fraction_of_market_price"] == 0.6


CASE = Path(__file__).resolve().parents[1] / "data/history/20260919/BBWI/source"


@pytest.mark.skipif(not CASE.exists(), reason="Local frozen SEC case required")
def test_real_diagnostics_same_dcf_restores_history_and_exposes_materiality(tmp_path):
	m = prepare_model(CASE)
	m["workbook_template"] = compile_template()
	m["controls"].update(
		share_price_proxy=17.4, forecast_tax_rate=m["normalized_tax_rate"]
	)
	m["control_bounds"].update(POLICY_CONTROL_BOUNDS)
	original = copy.deepcopy(m)
	base = build(m, tmp_path / "plain")
	r = run_diagnostics(
		m, tmp_path / "diagnostics", {"price": 17.4, "basis": "Frozen test observation"}
	)
	assert r["baseline"]["per_share_value"] == pytest.approx(
		base["per_share_value"], abs=1e-9
	)
	assert m == original
	by_id = {d["id"]: d for d in r["ranked_drivers"]}
	assert (
		by_id["sbc_ratio"]["outcomes"][0]["per_share_value"] > base["per_share_value"]
	)
	assert (
		by_id["sbc_ratio"]["outcomes"][1]["per_share_value"] < base["per_share_value"]
	)
	assert (
		by_id["cogs_ratio"]["impact_fraction_of_market_price"]
		> by_id["sbc_ratio"]["impact_fraction_of_market_price"]
	)
	assert all(
		by_id[k]["max_absolute_change_per_share"] > 0
		for k in ("capex_ratio", "nwc_ratio")
	)
