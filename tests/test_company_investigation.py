import copy
import json
from pathlib import Path

import pytest

from smrik_fund.company_investigation import (
	finding_schema,
	investigate,
	validate_finding,
	validate_plan,
)
from smrik_fund.company_research import excerpt, retrieve_questions


def test_range_schema_binds_parent_driver_and_retains_metric_context():
	schema = finding_schema(["E1"], ["products_growth"])
	fields = schema["properties"]["ranges"]["items"]["properties"]
	assert fields["driver_id"]["enum"] == ["products_growth"]
	assert {"metric", "units", "period", "interpretation"} <= set(fields)


def test_retrieval_diversifies_filings_and_avoids_duplicate_context(tmp_path):
	sources = []
	for key, form in (("latest", "10-Q"), ("annual", "10-K")):
		(tmp_path / f"{key}.txt").write_text(
			"\n".join(
				f"Line {i}: common costs"
				+ (" rare settlement" if key == "annual" and i == 20 else "")
				for i in range(100)
			)
		)
		sources.append(
			{"accession": key, "file": f"{key}.txt", "sha256": "fixture", "form": form}
		)
	packet = {"sources": sources, "excerpts": []}
	result = retrieve_questions(
		tmp_path,
		packet,
		{
			"questions": [
				{
					"area": "operating_costs",
					"phrases": ["common costs", "rare settlement"],
				}
			]
		},
	)
	excerpts = result["excerpts"]
	assert len(excerpts) <= 6
	assert {e["file"] for e in excerpts} == {"latest.txt", "annual.txt"}
	assert "rare settlement" in excerpts[0]["text"]
	for i, a in enumerate(excerpts):
		for b in excerpts[i + 1 :]:
			assert (
				a["file"] != b["file"]
				or a["line_start"] > b["line_end"]
				or b["line_start"] > a["line_end"]
			)


def test_large_request_counts_exact_input_and_replays_without_dispatch(tmp_path):
	from datetime import date
	from types import SimpleNamespace

	from smrik_fund.analysis_budget import initialize_budget
	from smrik_fund.company_run import call_model, read

	prices = json.loads(
		(Path(__file__).parents[1] / "docs/API_COST_SNAPSHOT.json").read_text()
	)
	prices.update(
		observed_date=date.today().isoformat(),
		valid_through=date.today().isoformat(),
		max_input_tokens=3000,
	)
	budget = tmp_path / "budget.json"
	initialize_budget(
		budget, ceiling_eur=5, final_review_reserve_eur=0.5, prices=prices
	)
	calls = []

	def response(value):
		return SimpleNamespace(model_dump=lambda **kw: value)

	def count(**kwargs):
		calls.append(("count", kwargs))
		return response({"input_tokens": 1000, "object": "response.input_tokens"})

	def create(**kwargs):
		calls.append(("create", kwargs))
		return response(
			{
				"id": "fixture",
				"model": prices["model"],
				"status": "completed",
				"usage": {
					"input_tokens": 1000,
					"output_tokens": 20,
					"total_tokens": 1020,
				},
				"output": [
					{
						"type": "message",
						"content": [{"type": "output_text", "text": '{"ok":true}'}],
					}
				],
			}
		)

	client = SimpleNamespace(
		base_url="https://api.openai.com/v1",
		responses=SimpleNamespace(
			create=create, input_tokens=SimpleNamespace(count=count)
		),
	)
	options = {
		"review": False,
		"budget_path": budget,
		"prices": prices,
		"client": client,
		"response_schema": {
			"type": "object",
			"properties": {"ok": {"type": "boolean"}},
			"required": ["ok"],
			"additionalProperties": False,
		},
	}
	for _ in range(2):
		assert call_model(tmp_path, "large", {"evidence": "x" * 6000}, **options) == {
			"ok": True
		}
	assert [c[0] for c in calls] == ["count", "create"]
	assert calls[0][1]["input"] == calls[1][1]["input"]
	assert calls[0][1]["text"] == calls[1][1]["text"]
	assert (
		read(tmp_path / "large.tokens.json")["request_hash"]
		== read(budget)["calls"][0]["request_hash"]
	)


def plan_and_diagnostics():
	d = {
		"ranked_drivers": [
			{"id": "cost", "area": "operating_costs"},
			{"id": "tax", "area": "taxes"},
		],
		"gaps": [],
		"history": [],
	}
	questions = [
		{
			"rank": i,
			"area": area,
			"question": key + " question",
			"decision": "Forecast policy",
			"priority_reason": "Material uncertain valuation driver",
			"driver_ids": [key],
			"source_refs": [f"{key}:L1-2"],
			"phrases": [key],
		}
		for i, key, area in ((1, "cost", "operating_costs"), (2, "tax", "taxes"))
	]
	plan = {
		"questions": questions,
		"initial_findings": "Global private agenda",
		"normalization_principles": ["Avoid overlapping adjustments"],
		"omitted_topics": [],
		"company_context": "A retailer",
	}
	return plan, d


def finding(ref, phrase=False):
	return {
		"status": "answered",
		"conclusion": "Supported finding",
		"findings": [{"claim": "Question-specific fact", "source_refs": [ref]}],
		"proposed_treatment": "Investigate sustainable cost",
		"ranges": [],
		"uncertainties": [],
		"overlap_risks": [],
		"additional_phrases": ["extra"] if phrase else [],
	}


@pytest.mark.parametrize("fault", ["rank", "gap", "driver", "source"])
def test_plan_must_account_for_priorities_and_sources(fault):
	p, d = plan_and_diagnostics()
	refs = ["cost:L1-2", "tax:L1-2"]
	validate_plan(p, d, refs)
	if fault == "rank":
		p["questions"][1]["rank"] = 1
	elif fault == "gap":
		d["gaps"].append({"id": "unresearched"})
	elif fault == "driver":
		p["questions"][0]["driver_ids"] = ["invented"]
	else:
		p["questions"][0]["source_refs"] = ["invented"]
	with pytest.raises(ValueError):
		validate_plan(p, d, refs)


def test_workers_are_isolated_with_one_bounded_followup(tmp_path, monkeypatch):
	from smrik_fund import company_run

	plan, diagnostics = plan_and_diagnostics()
	sources, excerpts = [], []
	for key, form in (("cost", "10-K"), ("tax", "10-Q")):
		lines = [key + " disclosure", "extra detail"]
		(tmp_path / f"{key}.txt").write_text("\n".join(lines))
		s = {"accession": key, "file": f"{key}.txt", "sha256": "fixture", "form": form}
		sources.append(s)
		excerpts.append(excerpt(s, lines, 0, 2))
	packet = {
		"case_hash": "frozen",
		"sources": sources,
		"market": {"price": 10},
		"scope": "Frozen fixture",
		"excerpts": excerpts,
	}
	model = {"case": "TEST", "evidence": [{"id": "E1", "value": 10}]}
	for name in ("sol", "luna"):
		(tmp_path / f"{name}-price-snapshot.json").write_text(
			json.dumps({"model": name})
		)
	seen = []

	def fake_call(output, name, payload, **kwargs):
		seen.append((name, copy.deepcopy(payload), kwargs["prices"]["model"]))
		if name == "research":
			assert payload["diagnostics"] == diagnostics
			assert len(payload["research"]["excerpts"]) == 2
			assert kwargs["reasoning_effort"] == "high"
			answer = plan
		else:
			assert "research_plan" not in payload["research"]
			assert "investigations" not in payload["research"]
			assert "initial_findings" not in payload
			assert len(payload["diagnostics"]) == 1
			if name.startswith("question-02"):
				assert "prior_investigation" not in payload
			ref = payload["research"]["excerpts"][0]["id"]
			answer = finding(ref, name == "question-01")
		kwargs["validator"](answer)
		return answer

	monkeypatch.setattr(company_run, "call_model", fake_call)
	result = investigate(
		tmp_path,
		model,
		packet,
		diagnostics,
		tmp_path,
		tmp_path / "unused-budget",
		tmp_path,
	)
	assert [n for n, _, _ in seen] == [
		"research",
		"question-01",
		"question-01-followup",
		"question-02",
	]
	assert [m for _, _, m in seen] == ["sol", "luna", "luna", "luna"]
	assert len(result["investigations"]) == 2
	assert "investigations" not in packet
	assert (tmp_path / "question-01.evidence.json").exists()


@pytest.mark.parametrize("fault", ["citation", "empty", "range", "phrases"])
def test_invalid_investigation_stops(fault):
	r = finding("E1")
	if fault == "citation":
		r["findings"][0]["source_refs"] = ["invented"]
	elif fault == "empty":
		r["findings"] = []
	elif fault == "range":
		r["ranges"] = [
			{
				"driver_id": "cost",
				"low": 2,
				"high": 1,
				"source_refs": [],
				"basis": "estimate",
			}
		]
	else:
		r["additional_phrases"] = ["a"] * 4
	with pytest.raises(ValueError):
		validate_finding(r, ["E1"], ["cost"])


CASE = Path(__file__).resolve().parents[1] / "data/history/20260919/BBWI/source"


@pytest.mark.skipif(not CASE.exists(), reason="Local frozen SEC case required")
def test_full_assessment_research_synthesis_revision_and_scenarios(
	tmp_path, monkeypatch
):
	from smrik_fund import company_research, company_run

	for name in ("sol", "luna"):
		(tmp_path / f"{name}-price-snapshot.json").write_text(
			json.dumps({"model": name})
		)
	monkeypatch.setattr(
		company_research,
		"market_quote",
		lambda *a: {"price": 17.4, "market_time": "2026-09-18", "ticker": "BBWI"},
	)
	finished = []
	monkeypatch.setattr(
		company_research, "finish_assessment", lambda *a: finished.append(a)
	)
	seen = []

	def fake_call(output, name, payload, **kwargs):
		seen.append((name, copy.deepcopy(payload), kwargs["prices"]["model"]))
		if name == "research":
			assert (output / "diagnostics/diagnostics.json").exists()
			d = payload["diagnostics"]
			drivers = [x["id"] for x in d["ranked_drivers"] + d["gaps"]]
			refs = [payload["research"]["excerpts"][0]["id"]]
			answer = {
				"questions": [
					{
						"rank": 1,
						"area": "operating_costs",
						"question": "Sustainable operating costs?",
						"decision": "Cost assumptions",
						"priority_reason": "Material",
						"driver_ids": ["cogs_ratio"],
						"source_refs": refs,
						"phrases": ["cost"],
					}
				],
				"omitted_topics": [
					{"driver_id": x, "reason": "Simulated test omission"}
					for x in drivers
					if x != "cogs_ratio"
				],
				"initial_findings": "TEST",
				"normalization_principles": [],
				"company_context": "TEST",
			}
		elif name.startswith("question"):
			answer = finding(payload["research"]["excerpts"][0]["id"])
		else:
			controls = dict(payload["model"]["controls"])
			if name == "review-0":
				controls["cogs_ratio"] += 0.005
			answer = {
				"controls": controls,
				"rationale": "SIMULATED TEST",
				"limitations": [],
				"decisions": [
					{
						"control": c,
						"basis": "estimate",
						"source_refs": [],
						"explanation": "Test",
					}
					for c in controls
				],
				"coverage": [
					{
						"area": a,
						"status": "limitation",
						"source_refs": [],
						"finding": "Test",
					}
					for a in company_research.AREAS
				],
			}
			if name == "analyst":
				assert kwargs["prices"]["model"] == "sol"
				assert len(payload["research"]["investigations"]) == 1
				answer["research_reconciliation"] = [
					{
						"rank": 1,
						"outcome": "adopted",
						"reason": "Test",
						"controls": ["cogs_ratio"],
					}
				]
				answer["scenarios"] = [
					{
						"name": n,
						"rationale": "TEST",
						"question_ranks": [1],
						"changes": [
							{
								"control": "products_growth",
								"value": controls["products_growth"] + delta,
							}
						],
					}
					for n, delta in (("downside", -0.01), ("upside", 0.01))
				]
			else:
				answer["verdict"] = "revise" if name == "review-0" else "accept"
		kwargs["validator"](answer)
		return answer

	monkeypatch.setattr(company_run, "call_model", fake_call)
	out = tmp_path / "assessment"
	result = company_run.run_case(
		"BBWI",
		CASE,
		out,
		live=True,
		assess=True,
		price_dir=tmp_path,
		native_excel=False,
	)
	assert [x[0] for x in seen] == [
		"research",
		"question-01",
		"analyst",
		"review-0",
		"review-1",
	]
	assert [x[2] for x in seen] == ["sol", "luna", "sol", "sol", "sol"]
	assert result["status"] == "SYSTEM_REVIEWED_DEVELOPMENT"
	model = company_run.read(out / "reviewed/model.json")
	assert (
		model["scenario_results"][0]["per_share_value"]
		< result["per_share_value"]
		< model["scenario_results"][1]["per_share_value"]
	)
	assert (
		model["scenario_results"][0]["controls"]["cogs_ratio"]
		== model["controls"]["cogs_ratio"]
	)
	assert len(finished) == 1
	assert "Research decisions" in (out / "ASSESSMENT.md").read_text(encoding="utf-8")
