import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from smrik_fund import company_research as research
from smrik_fund.company_model import DEFAULT_CONTROLS, POLICY_CONTROL_BOUNDS
from smrik_fund.company_run import build
from smrik_fund.portable_model import prepare_model
from smrik_fund.workbook_template import compile_template

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "data/history/20260919/BBWI/source"


def answer():
	controls = {
		**DEFAULT_CONTROLS,
		"share_price_proxy": 17.4,
		"forecast_tax_rate": 0.25,
	}
	model = {"controls": controls, "evidence": [{"id": "E1"}]}
	packet = {"market": {"price": 17.4}, "excerpts": [{"id": "F1"}]}
	result = {
		"controls": dict(controls),
		"verdict": "accept",
		"decisions": [
			{
				"control": c,
				"basis": "estimate",
				"source_refs": [],
				"explanation": "Test estimate",
			}
			for c in controls
		],
		"coverage": [
			{
				"area": a,
				"status": "limitation",
				"source_refs": ["F1"],
				"finding": "Test limitation",
			}
			for a in research.AREAS
		],
	}
	return model, packet, result


@pytest.mark.parametrize(
	"fault",
	["quote", "citation", "duplicate", "coverage", "blocking", "missing_source", "tax"],
)
def test_invalid_financial_decisions_stop(fault):
	model, packet, result = answer()
	if fault == "quote":
		result["controls"]["share_price_proxy"] = 25
	elif fault == "citation":
		result["decisions"][0]["source_refs"] = ["invented"]
	elif fault == "duplicate":
		result["decisions"][0] = result["decisions"][1]
	elif fault == "coverage":
		result["coverage"].pop()
	elif fault == "blocking":
		result["coverage"][0]["status"] = "blocking_gap"
	elif fault == "missing_source":
		result["decisions"][0]["basis"] = "sourced"
	else:
		result["controls"]["forecast_tax_rate"] = float("nan")
	with pytest.raises(ValueError):
		research.validate_decisions(result, model, packet)


def test_valid_explicit_estimates_and_cited_limitations():
	model, packet, result = answer()
	research.validate_decisions(result, model, packet)


def test_response_schema_only_allows_real_evidence_ids():
	from smrik_fund.company_run import schema

	model, packet, _ = answer()
	allowed = research.evidence_ids(model, packet)
	contract = research.decision_schema(schema(False, model["controls"]), allowed)
	for field in ("decisions", "coverage"):
		assert contract["properties"][field]["items"]["properties"]["source_refs"][
			"items"
		]["enum"] == ["E1", "F1", "market_quote"]


def test_assessment_requires_explicit_live_opt_in(tmp_path):
	from smrik_fund.company_run import run_case

	with pytest.raises(ValueError, match="fresh --live"):
		run_case("TEST", tmp_path, tmp_path / "out", assess=True)
	assert not (tmp_path / "out").exists()


def test_independent_ic_revision_preserves_original_and_rejects_changed_evidence(
	tmp_path, monkeypatch
):
	from smrik_fund import company_run
	from smrik_fund.analysis_budget import content_hash
	from smrik_fund.daily_ic import ICAssessment

	packet = {"market": {"price": 5, "market_time": "test"}, "excerpts": [{"id": "E1"}]}
	model = {
		"case": "TEST",
		"case_hash": "synthetic-test-case",
		"evidence": [],
		"research_packet_hash": content_hash(packet),
	}
	draft = {
		"priority": "watch",
		"headline": "Original draft",
		"case_for": [{"text": "Conditional value", "fact_keys": ["per_share_value"]}],
		"case_against": [],
		"unknowns": ["Research incomplete"],
		"work_plan": [],
		"catalyst_to_verify": "Future results",
	}
	company_run.save(tmp_path / "research-packet.json", packet)
	company_run.save(tmp_path / "reviewed/model.json", model)
	company_run.save(tmp_path / "reviewed/snapshot.json", {})
	company_run.save(
		tmp_path / "version.json",
		{
			"model_sha256": company_run.fingerprint(tmp_path / "reviewed/model.json"),
			"snapshot_sha256": company_run.fingerprint(
				tmp_path / "reviewed/snapshot.json"
			),
		},
	)
	company_run.save(tmp_path / "ic.structured.json", draft)
	company_run.save(
		tmp_path / "ic.request.json",
		{
			"input": "{}",
			"text": {"format": {"schema": ICAssessment.model_json_schema()}},
		},
	)
	artifacts = [
		"version.json",
		"research-packet.json",
		"ic.structured.json",
		"ic.request.json",
	]
	company_run.save(
		tmp_path / "assessment-audit.json",
		{
			"metrics": {"market_price": 5, "per_share_value": 10},
			"artifacts": {
				name: company_run.fingerprint(tmp_path / name) for name in artifacts
			},
		},
	)
	company_run.save(
		tmp_path / "prices/sol-price-snapshot.json", {"model": "simulated"}
	)

	def simulated_call(output, name, payload, **kwargs):
		assert name == "ic-review" and payload["draft_ic"] == draft
		result = {
			**draft,
			"headline": "Corrected by simulated independent reviewer",
			"verdict": "revise",
			"review_notes": ["Corrected a draft claim"],
		}
		kwargs["validator"](result)
		return result

	monkeypatch.setattr(company_run, "call_model", simulated_call)
	research.review_ic(tmp_path, tmp_path / "unused-budget", tmp_path / "prices")
	assert company_run.read(tmp_path / "ic.structured.json") == draft
	assert "Corrected by simulated" in (tmp_path / "IC-reviewed.md").read_text(
		encoding="utf-8"
	)
	assert (tmp_path / "ic-review-audit.json").is_file()
	(tmp_path / "research-packet.json").write_text("{}")
	with pytest.raises(ValueError, match="artifacts changed"):
		research.review_ic(tmp_path, tmp_path / "unused-budget", tmp_path / "prices")


@pytest.mark.parametrize("fault", ["stale", "future", "currency", "symbol", "nan"])
def test_unusable_market_quotes_cannot_become_assumptions(monkeypatch, tmp_path, fault):
	data = {
		"symbol": "TEST",
		"currency": "USD",
		"regularMarketPrice": 20,
		"regularMarketTime": datetime.now(UTC).timestamp(),
	}
	if fault == "stale":
		data["regularMarketTime"] -= 8 * 86400
	elif fault == "future":
		data["regularMarketTime"] += 3600
	elif fault == "nan":
		data["regularMarketPrice"] = float("nan")
	else:
		data[fault] = "WRONG"
	monkeypatch.setattr(
		research,
		"get_detail",
		lambda *a, **kw: {
			"data": data,
			"error": None,
			"observed_at": datetime.now(UTC).isoformat(),
		},
	)
	with pytest.raises(ValueError):
		research.market_quote("TEST", tmp_path)


def test_search_records_no_match_and_exact_line_context(tmp_path):
	(tmp_path / "filing.txt").write_text(
		"before\nIncome taxes include a discrete benefit.\nafter\n", encoding="utf-8"
	)
	packet = {
		"sources": [
			{
				"form": "10-K",
				"file": "filing.txt",
				"accession": "test",
				"sha256": "testhash",
			}
		],
		"excerpts": [],
	}
	questions = {
		"questions": [
			{
				"area": "taxes",
				"question": "Discrete tax?",
				"phrases": ["discrete benefit"],
			},
			{
				"area": "leases",
				"question": "Lease terms?",
				"phrases": ["absent phrase"],
			},
		]
	}
	result = research.retrieve_questions(tmp_path, packet, questions)
	assert result["searches"][1]["status"] == "NO_MATCH"
	assert result["excerpts"][0]["line_start"] == 1
	assert result["excerpts"][0]["line_end"] == 3
	assert "Income taxes include" in result["excerpts"][0]["text"]


@pytest.mark.skipif(not CASE.exists(), reason="Local frozen financial case required")
def test_filing_packet_is_complete_bound_and_not_manually_curated():
	model = prepare_model(CASE)
	packet = research.initial_packet(CASE, model, {"price": 17.4})
	assert packet["latest_filing_complete"]
	assert len(packet["sources"]) == 6
	assert packet["sources"][0]["period"] == "2026-08-01"
	text = "\n".join(e["text"] for e in packet["excerpts"])
	assert "tariff" in text.lower() and "settlement" in text.lower()
	for item in packet["excerpts"]:
		lines = (CASE / item["file"]).read_text(encoding="utf-8").splitlines()
		source = next(s for s in packet["sources"] if s["file"] == item["file"])
		assert (
			research.excerpt(source, lines, item["line_start"] - 1, item["line_end"])
			== item
		)


@pytest.mark.skipif(not CASE.exists(), reason="Local frozen financial case required")
def test_forecast_tax_recalculates_statements_and_debt_shield_without_changing_history(
	tmp_path,
):
	model = prepare_model(CASE)
	model["workbook_template"] = compile_template()
	model["controls"]["forecast_tax_rate"] = 0.2
	model["control_bounds"].update(POLICY_CONTROL_BOUNDS)
	before = copy.deepcopy(model)
	low = build(model, tmp_path / "low")
	model["controls"]["forecast_tax_rate"] = 0.3
	high = build(model, tmp_path / "high")
	assert high["wacc"] < low["wacc"]  # Larger interest tax shield.
	assert high["schedules"]["Revenue"] == low["schedules"]["Revenue"]
	assert (
		high["schedules"]["Book/cash tax (same timing assumption)"][1]
		> low["schedules"]["Book/cash tax (same timing assumption)"][1]
	)
	assert high["schedules"]["Net income"][1] < low["schedules"]["Net income"][1]
	assert high["mechanical"] == low["mechanical"] == "PASS"
	assert high["historical_checks"] == low["historical_checks"]
	assert (
		model["history"] == before["history"]
		and model["evidence"] == before["evidence"]
	)
	assert any(
		"forecast_tax_rate" in line
		for line in json.dumps(high["input_rows"]).splitlines()
	)
