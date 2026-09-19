import copy
import json
import subprocess
from pathlib import Path

import pandas as pd
import pytest

from smrik_fund.company_model import (
	DEFAULT_CONTROLS,
	prepare_model,
	source_value,
	validate_controls,
)
from smrik_fund.company_run import ENGINE, build

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "data/second-company/AAPL/frozen-20260910"


@pytest.fixture(scope="module")
def model():
	return prepare_model(CASE)


def test_actual_aapl_periods_and_source_values(model):
	assert model["history"]["revenue"]["ttm"] == 466823
	assert model["opening"]["assets"] == 383266
	assert model["opening"]["intangibles_current"] == 5075
	assert model["periods"][0]["end"] == "2026-09-26"
	assert model["periods"][0]["fraction"] == 0.25
	assert model["periods"][1]["end"] == "2027-09-25"
	assert model["review"]["human_approval"] is False
	assert model["history"]["capex_cash"]["ttm"] < 0


def test_ambiguous_or_missing_source_is_not_selected_or_zeroed():
	frame = pd.DataFrame({"concept": ["us-gaap_Example"]*2, "dimension": [False]*2, "abstract": [False]*2, "FY": [None, 0]})
	with pytest.raises(ValueError, match="ambiguous"):
		source_value(frame, "Example", "FY")
	with pytest.raises(ValueError, match="Missing"):
		source_value(frame.iloc[:1], "Example", "FY")
	assert source_value(frame.iloc[1:], "Example", "FY")[0] == 0


@pytest.mark.parametrize("changes", [{"beta": None}, {"beta": True}, {"ppe_life": 0}, {"terminal_growth": 0.5}])
def test_invalid_development_controls_block(changes):
	with pytest.raises(ValueError):
		validate_controls({**DEFAULT_CONTROLS, **changes})


def test_linked_aapl_model_and_beta_revision(model, tmp_path):
	base = build(model, tmp_path / "base")
	assert base["mechanical"] == "PASS"
	assert all(abs(v) < 1e-6 for v in base["schedules"]["Balance difference (no cash/equity plug)"])
	assert all(base["proof"].values())
	s = base["schedules"]
	tax = model["history"]["tax"]["ttm"] / model["history"]["pretax"]["ttm"]
	for i in range(11):
		# Independent bridge: cash FCF adds SBC and after-tax investment/financing income.
		expected = s["SBC cash-flow addback / equity contribution"][i] + (s["Investment income (scenario risk-free yield)"][i]-s["Interest expense on constant refinanced debt"][i])*(1-tax)
		assert s["Cash FCF"][i]-s["Economic UFCF (SBC remains expensed)"][i] == pytest.approx(expected)
	revision = copy.deepcopy(model)
	revision["controls"]["beta"] += 0.1
	changed = build(revision, tmp_path / "revision")
	assert changed["schedules"] == base["schedules"]
	assert changed["per_share_value"] < base["per_share_value"]
	result = subprocess.run(["node", str(ENGINE), str(tmp_path / "base/model.json"), str(tmp_path / "base/AAPL.xlsx"), str(tmp_path / "new-snapshot.json")], capture_output=True, text=True)
	assert result.returncode != 0
	assert "Refusing to overwrite" in result.stderr
	assert json.loads((tmp_path / "base/model.json").read_text())["controls"] == model["controls"]


def test_cli_forwards_company_and_rejects_stale_cutoff(tmp_path, monkeypatch):
	from typer.testing import CliRunner

	from smrik_fund import company_run
	from smrik_fund.main import app

	calls = []
	def capture(*args, **kwargs):
		calls.append((args, kwargs))
		return {"status": "PROVISIONAL_UNREVIEWED"}
	monkeypatch.setattr(company_run, "run_case", capture)
	args = ["dcf", "AAPL", "--as-of", "2026-09-10", "--case-dir", str(CASE), "--output-dir", str(tmp_path / "run")]
	assert CliRunner().invoke(app, args).exit_code == 0
	assert calls[0][0][0] == "AAPL"
	assert calls[0][1]["live"] is False
	args[3] = "2026-09-09"
	assert CliRunner().invoke(app, args).exit_code != 0
	assert len(calls) == 1


def test_wrong_company_and_incomplete_revision_arguments_stop_before_output(tmp_path):
	from smrik_fund.company_run import run_case

	with pytest.raises(ValueError, match="ticker differs"):
		run_case("MSFT", CASE, tmp_path / "wrong", native_excel=False)
	with pytest.raises(ValueError, match="supplied together"):
		run_case("AAPL", CASE, tmp_path / "revision", beta=1.2, native_excel=False)
	assert not (tmp_path / "wrong").exists()
	assert not (tmp_path / "revision").exists()


def test_free_operator_assumptions_are_applied_and_recorded(tmp_path, monkeypatch):
	from smrik_fund import company_run

	def no_paid_call(*args, **kwargs):
		raise AssertionError("Free assumptions invoked paid transport")
	monkeypatch.setattr(company_run, "call_model", no_paid_call)
	assumptions = {"controls": {**DEFAULT_CONTROLS, "share_price_proxy": 16.73, "payout_ratio": 0, "services_growth": 0, "intangible_additions_ratio": 0}, "rationale": "Explicit free scenario", "limitations": ["Research baseline"]}
	result = company_run.run_case("AAPL", CASE, tmp_path / "manual", assumptions=assumptions, native_excel=False)
	model = json.loads((tmp_path / "manual/reviewed/model.json").read_text())
	assert result["status"] == "PROVISIONAL_UNREVIEWED"
	assert model["controls"] == assumptions["controls"]
	assert model["analyst"] == assumptions
	assert json.loads((tmp_path / "manual/operator-assumptions.json").read_text()) == assumptions
	with pytest.raises(ValueError, match="new free run"):
		company_run.run_case("AAPL", CASE, tmp_path / "paid", assumptions=assumptions, live=True)
	with pytest.raises(ValueError, match="rationale"):
		company_run.run_case("AAPL", CASE, tmp_path / "bad", assumptions={**assumptions, "rationale": ""})
	assert not (tmp_path / "paid").exists()
	assert not (tmp_path / "bad").exists()
