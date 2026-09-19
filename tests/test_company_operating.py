import copy
from pathlib import Path

import pytest

from smrik_fund.company_operating import operating_costs, reconcile_costs


def test_signed_expenses_require_complete_ebit_bridge():
	result = reconcile_costs(100, 20, {"cogs": -60, "sga": -20})
	assert result["values"] == {"cogs": 60, "sga": 20}
	assert result["sign_multipliers"] == {"cogs": -1, "sga": -1}
	assert result["difference"] == 0
	assert reconcile_costs(100, 20, {"cogs": -60, "sga": -20}, 39) is None
	assert reconcile_costs(100, 19, {"cogs": -60, "sga": -20}) is None
	for value in (None, float("nan"), float("inf"), True):
		assert reconcile_costs(100, 20, {"cogs": -60, "sga": value}) is None
	assert reconcile_costs(100, 20, {"sga": 80}) is None


def test_each_period_reconciles_before_ttm_and_raw_signs_are_preserved():
	flow = {
		"revenue": {"annual": 100, "current_ytd": 55, "prior_ytd": 50, "ttm": 105},
		"ebit": {"annual": 20, "current_ytd": 11, "prior_ytd": 10, "ttm": 21},
	}
	cogs = {"annual": -60, "current_ytd": 33, "prior_ytd": 30, "ttm": -57}
	sga = {"annual": -20, "current_ytd": 11, "prior_ytd": 10, "ttm": -19}

	def read(concepts):
		return (
			cogs
			if concepts[0] == "CostOfGoodsAndServicesSold"
			else sga
			if concepts[0] == "SellingGeneralAndAdministrativeExpense"
			else None
		)

	result = operating_costs(flow, read)
	assert result["status"] == "detailed"
	assert result["reported"]["cogs"] == {
		k: cogs[k] for k in ("annual", "current_ytd", "prior_ytd")
	}
	assert flow["cost_cogs"]["ttm"] == 63
	assert flow["cost_sga"]["ttm"] == 21
	assert [c["ttm_ratio"] for c in result["components"]] == pytest.approx([0.6, 0.2])
	bad = copy.deepcopy(flow)
	bad["ebit"].update(current_ytd=12, prior_ytd=11)
	assert operating_costs(bad, read)["status"] == "aggregate"


def test_bad_disclosures_do_not_become_zero_or_residual_drivers():
	def bad_source(concepts):
		raise ValueError("duplicate COGS")

	result = operating_costs({}, bad_source)
	assert result == {
		"status": "aggregate",
		"reason": "duplicate COGS",
		"components": [],
	}


ROOT = Path(__file__).resolve().parents[1]
CASES = {
	"BBWI": "data/history/20260919/BBWI/source",
	"NVDA": "data/multi-ticker/20260910/NVDA/attempt-r2/source",
	"COST": "data/multi-ticker/20260910/COST/attempt-r2/source",
	"LULU": "data/weekend/20260919/LULU/base-r1/source",
	"HPQ": "data/daily/20260916-hpq-deep/source",
	"GOOGL": "data/multi-ticker/portable/GOOGL/source",
}


@pytest.mark.parametrize("ticker", CASES)
def test_real_cost_coverage_and_default_equivalence(ticker, tmp_path):
	from smrik_fund.company_run import build
	from smrik_fund.portable_model import prepare_model

	case = ROOT / CASES[ticker]
	if not case.exists():
		pytest.skip("Local frozen acceptance case required")
	model = prepare_model(case)
	costs = model["operating_costs"]
	assert costs["status"] == (
		"detailed" if ticker in ("BBWI", "NVDA", "COST") else "aggregate"
	)
	base = build(model, tmp_path / "base")
	assert base["mechanical"] == base["valuation_gate"] == "PASS"
	if costs["status"] == "aggregate":
		assert costs["reason"] and not costs["components"]
		return
	# Original aggregate baseline must be financially identical at calibrated ratios.
	legacy = copy.deepcopy(model)
	legacy.pop("operating_costs")
	old = build(legacy, tmp_path / "aggregate")
	for metric, values in base["schedules"].items():
		assert values == pytest.approx(old["schedules"][metric], abs=1e-6)
	assert base["per_share_value"] == pytest.approx(old["per_share_value"], abs=1e-6)
	# A one-percentage-point cost increase changes operating profit by 1% of sales.
	changed = copy.deepcopy(model)
	changed["controls"]["cogs_ratio"] += 0.01
	revised = build(changed, tmp_path / "higher-costs")
	for i, revenue in enumerate(base["schedules"]["Revenue"]):
		assert base["schedules"]["EBIT"][i] - revised["schedules"]["EBIT"][
			i
		] == pytest.approx(revenue * 0.01)
		assert revised["schedules"]["Balance difference (no cash/equity plug)"][
			i
		] == pytest.approx(0, abs=1e-6)
	assert revised["per_share_value"] < base["per_share_value"]
	assert revised["historical_checks"] == base["historical_checks"]
	assert all(base["proof"].values())


def test_optional_controls_and_annual_only_costs():
	from smrik_fund.company_model import DEFAULT_CONTROLS, validate_controls

	validate_controls({**DEFAULT_CONTROLS, "cogs_ratio": 0.6})
	for value in (-0.1, 2.1, float("nan"), True):
		with pytest.raises(ValueError, match="Invalid forecast control"):
			validate_controls({**DEFAULT_CONTROLS, "cogs_ratio": value})
	flow = {
		"revenue": {"annual": 100, "current_ytd": 0, "prior_ytd": 0, "ttm": 100},
		"ebit": {"annual": 20, "current_ytd": 0, "prior_ytd": 0, "ttm": 20},
	}

	def read(concepts):
		if concepts[0] != "CostOfGoodsAndServicesSold":
			return None
		return {"annual": -80, "current_ytd": 0, "prior_ytd": 0, "ttm": -80}

	assert (
		operating_costs(copy.deepcopy(flow), read, has_interim=False)["status"]
		== "detailed"
	)
	# A disclosed zero-revenue interim period is not an absent interim period.
	assert operating_costs(flow, read)["status"] == "aggregate"
