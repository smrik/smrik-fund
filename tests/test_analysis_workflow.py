import copy
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

import pytest
from pydantic import ValidationError

from smrik_fund.analysis_workflow import (
	AREA_SEQUENCE,
	DEPENDENCIES,
	AnalystCorrection,
	EvidenceRequest,
	WholeModelReview,
	WorkflowError,
	checkpoint_analyst_correction,
	checkpoint_evidence,
	checkpoint_independent_recheck,
	checkpoint_whole_model_review,
	current_status,
	derive_status,
	prepare_from_documents,
	retrieve_evidence,
	run_stage,
	validate_correction,
	validate_current_context,
	validate_frozen_inputs,
	validate_review,
)

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "data/build-guide-p9/parent-repair/model/selected-model.json"
VERIFICATION_PATH = (
	ROOT / "data/build-guide-p9/parent-repair/model/p9-verification.json"
)
SOURCE_MANIFEST_PATH = ROOT / "data/build-guide-p2-r2/MSFT/source_manifest.json"
VALUATION_CONTEXT_PATH = (
	ROOT / "data/build-guide-p10/parent-preflight/financial-review-context-r2.json"
)
PRICES_PATH = ROOT / "data/build-guide-p10/parent-preflight/sol-price-snapshot.json"


def load(path: Path) -> dict:
	return json.loads(path.read_text(encoding="utf-8-sig"))


def prepare(tmp_path: Path) -> tuple[Path, dict]:
	model, verification, source_manifest, valuation_context = validate_frozen_inputs(
		MODEL_PATH,
		VERIFICATION_PATH,
		SOURCE_MANIFEST_PATH,
		VALUATION_CONTEXT_PATH,
	)
	calculated_path = tmp_path / "calculated.json"
	calculated = {"snapshot": verification["snapshot"], "sensitivities": {}}
	calculated_path.write_text(json.dumps(calculated), encoding="utf-8")
	paths = {
		"selected_model": MODEL_PATH,
		"accepted_p9_verification": VERIFICATION_PATH,
		"source_manifest": SOURCE_MANIFEST_PATH,
		"valuation_review_context": VALUATION_CONTEXT_PATH,
		"price_snapshot": PRICES_PATH,
		"calculated_context": calculated_path,
	}
	for accession in ("0000950170-25-100235", "0001193125-26-191507"):
		path = SOURCE_MANIFEST_PATH.parent / "evidence/original_source" / f"{accession}.txt"
		if path.exists():
			paths[f"original_source:{accession}"] = path
	run_dir = tmp_path / "run"
	result = prepare_from_documents(
		model=model,
		verification=verification,
		calculated=calculated,
		source_manifest=source_manifest,
		valuation_context=valuation_context,
		prices=load(PRICES_PATH),
		paths=paths,
		run_dir=run_dir,
	)
	return run_dir, result


def review_value(
	context: dict,
	*,
	verdict: str = "accept",
	revise_area: str | None = None,
) -> dict:
	areas = []
	for area in AREA_SEQUENCE:
		source_ref = next(key for key, record in context["source_records"].items() if record.get("kind") == "pinned_filing_excerpt" and area in record["areas"])
		outcome = "reassessment_required" if area == revise_area else "supported_no_change"
		areas.append(
			{
				"area": area,
				"outcome": outcome,
				"prior_decision_carried": True,
				"changed_dependencies_assessed": list(DEPENDENCIES[area]),
				"source_refs": [source_ref],
				"period_refs": ["FY2036"],
				"basis_type": "mixed",
				"basis": f"Fresh reassessment of {area} and its dependencies.",
				"concerns": ["Bounded correction required"] if area == revise_area else [],
				"evidence_request": None,
			}
		)
	return {
		"verdict": verdict,
		"areas": areas,
		"cross_schedule_concerns": [],
		"required_revision": None
		if verdict == "accept"
		else f"Resolve {revise_area} using a closed option.",
		"rationale": "Complete 12-area reassessment.",
	}


def test_real_case_prepare_contract(tmp_path: Path) -> None:
	run_dir, result = prepare(tmp_path)
	manifest = result["manifest"]
	queue = result["queue"]
	status = result["status"]

	assert queue["fixed_sequence"] == list(AREA_SEQUENCE)
	assert len(queue["areas"]) == 12
	assert all(item["fresh_reassessment_required"] for item in queue["areas"])
	request = load(run_dir / "requests/01-whole-model-review.request.json")
	assert request["model"] == "gpt-5.6-sol"
	assert request["reasoning"] == {"effort": "high"}
	assert request["tools"] == []
	assert request["background"] is False
	assert request["max_output_tokens"] == 16000
	assert manifest["reservation"]["reserved_eur"] < 2
	assert manifest["request_utf8_bytes"] == len(
		json.dumps(
			request, sort_keys=True, ensure_ascii=False, allow_nan=False
		).encode("utf-8")
	)
	assert queue["queue"][0]["final_review"] is True
	context = load(run_dir / "review-context.json")
	assert all(
		record["kind"] == "pinned_original_source"
		for key, record in context["source_records"].items()
		if key.startswith("SEC:")
	)
	assert all("sha256" in record for record in context["source_records"].values() if record["kind"] == "pinned_original_source")
	assert status == {
		"execution": "PREPARED_NOT_DISPATCHED",
		"mechanical": "PASS",
		"coverage": "PENDING_12_AREA_REVIEW",
		"analytical": "PENDING_WHOLE_MODEL_REVIEW",
		"budget": "ESTIMATED_NOT_RESERVED",
		"human": "NOT_APPROVED",
	}
	primary = [row for row in context["source_records"].values() if row["kind"] == "pinned_filing_excerpt"]
	assert len(primary) == 20
	assert any("Cost of revenue" in row["excerpt"] and "Operating expenses" in row["excerpt"] for row in primary if "revenue" in row["areas"])
	assert "prior_rationale_not_revalidated" in context["coverage"][0]["current_assumptions_and_treatments"]
	validate_current_context(run_dir)


def test_wrong_period_or_changed_filing_excerpt_fails_before_review(tmp_path: Path) -> None:
	for field, value in (("period", "2027-03-31"), ("excerpt", "Unsupported rewritten financial facts")):
		context = load(VALUATION_CONTEXT_PATH)
		context["filing_source_rows"][0][field] = value
		path = tmp_path / f"invalid-{field}.json"
		path.write_text(json.dumps(context))
		with pytest.raises(WorkflowError, match="content, source, or period"):
			validate_frozen_inputs(MODEL_PATH, VERIFICATION_PATH, SOURCE_MANIFEST_PATH, path)


def test_wrong_area_source_and_changed_prepared_context_cannot_dispatch(tmp_path: Path, monkeypatch) -> None:
	run_dir, _ = prepare(tmp_path)
	context = load(run_dir / "review-context.json")
	value = review_value(context)
	value["areas"][0]["source_refs"] = ["AREA-PACKET:revenue"]
	with pytest.raises(WorkflowError, match="original filing excerpt"):
		checkpoint_whole_model_review(run_dir, value)
	context["valuation"]["per_share_value"] = 999
	(run_dir / "review-context.json").write_text(json.dumps(context))
	dispatched = []
	monkeypatch.setattr("smrik_fund.analysis_transport.dispatch_request", lambda *args, **kwargs: dispatched.append(kwargs))
	with pytest.raises(WorkflowError, match="STALE_CONTEXT"):
		run_stage(run_dir=run_dir, stage="whole_model_review", budget_path=tmp_path / "unused-ledger", prices=load(PRICES_PATH))
	assert not dispatched
	assert current_status(run_dir)["status"]["execution"] == "BLOCKED"


def test_stale_model_and_calculation_are_blocked(tmp_path: Path) -> None:
	stale_model = tmp_path / "selected-model.json"
	stale_model.write_bytes(MODEL_PATH.read_bytes() + b"\n")
	with pytest.raises(WorkflowError, match="STALE_CONTEXT"):
		validate_frozen_inputs(
			stale_model,
			VERIFICATION_PATH,
			SOURCE_MANIFEST_PATH,
			VALUATION_CONTEXT_PATH,
		)


def test_analytical_identity_ignores_export_bytes_but_tracks_financial_context(
	tmp_path: Path,
) -> None:
	model, verification, source_manifest, valuation_context = validate_frozen_inputs(
		MODEL_PATH,
		VERIFICATION_PATH,
		SOURCE_MANIFEST_PATH,
		VALUATION_CONTEXT_PATH,
	)
	prices = load(PRICES_PATH)
	base_workbook = ROOT / "data/build-guide-p9/parent-repair/model/p9-authority.xlsx"
	workbook_a, workbook_b = tmp_path / "first.xlsx", tmp_path / "second.xlsx"
	workbook_a.write_bytes(base_workbook.read_bytes())
	workbook_b.write_bytes(base_workbook.read_bytes())
	with ZipFile(workbook_b, "a") as archive:
		archive.comment = b"Presentation/export metadata changed; financial cells identical"
	calculated_a = {
		"snapshot": verification["snapshot"],
		"sensitivities": {},
		"workbookPath": str(workbook_a),
		"workbookSha256": hashlib.sha256(workbook_a.read_bytes()).hexdigest(),
	}
	calculated_b = {
		**calculated_a,
		"workbookPath": str(workbook_b),
		"workbookSha256": hashlib.sha256(workbook_b.read_bytes()).hexdigest(),
	}
	calc_a = tmp_path / "calc-a.json"
	calc_b = tmp_path / "calc-b.json"
	calc_a.write_text(json.dumps(calculated_a), encoding="utf-8")
	calc_b.write_text(json.dumps(calculated_b), encoding="utf-8")
	base_paths = {
		"selected_model": MODEL_PATH,
		"accepted_p9_verification": VERIFICATION_PATH,
		"source_manifest": SOURCE_MANIFEST_PATH,
		"valuation_review_context": VALUATION_CONTEXT_PATH,
	}
	first = prepare_from_documents(
		model=model,
		verification=verification,
		calculated=calculated_a,
		source_manifest=source_manifest,
		valuation_context=valuation_context,
		prices=prices,
		paths={**base_paths, "calculated_context": calc_a},
		run_dir=tmp_path / "first",
	)
	second = prepare_from_documents(
		model=model,
		verification=verification,
		calculated=calculated_b,
		source_manifest=source_manifest,
		valuation_context=valuation_context,
		prices=prices,
		paths={**base_paths, "calculated_context": calc_b},
		run_dir=tmp_path / "second",
	)
	assert first["manifest"]["request_hash"] == second["manifest"]["request_hash"]
	assert (
		first["manifest"]["artifact_and_code_provenance"]["calculated_context"]
		!= second["manifest"]["artifact_and_code_provenance"]["calculated_context"]
	)

	changed_verification = copy.deepcopy(verification)
	changed_calculated = copy.deepcopy(calculated_a)
	changed_calculated["snapshot"]["p9"]["formulas"]["wacc"] += "+0"
	changed_verification["snapshot"] = changed_calculated["snapshot"]
	changed = prepare_from_documents(
		model=model,
		verification=changed_verification,
		calculated=changed_calculated,
		source_manifest=source_manifest,
		valuation_context=valuation_context,
		prices=prices,
		paths={**base_paths, "calculated_context": calc_a},
		run_dir=tmp_path / "changed-financial-context",
	)
	assert changed["manifest"]["request_hash"] != first["manifest"]["request_hash"]

	model, verification, source_manifest, valuation_context = validate_frozen_inputs(
		MODEL_PATH,
		VERIFICATION_PATH,
		SOURCE_MANIFEST_PATH,
		VALUATION_CONTEXT_PATH,
	)
	calculated = {"snapshot": {**verification["snapshot"], "allPeriodStatus": "EDITED"}}
	with pytest.raises(WorkflowError, match="fresh calculation differs"):
		prepare_from_documents(
			model=model,
			verification=verification,
			calculated=calculated,
			source_manifest=source_manifest,
			valuation_context=valuation_context,
			prices=load(PRICES_PATH),
			paths={"selected_model": MODEL_PATH},
			run_dir=tmp_path / "stale-run",
		)


def test_literal_manifest_retrieval_is_bounded_and_capped(tmp_path: Path) -> None:
	case_root = tmp_path / "case"
	source_root = case_root / "evidence/original_source"
	source_root.mkdir(parents=True)
	selected = "0000950170-25-100235"
	unselected = "0001193125-26-191507"
	manifest_path = case_root / "source_manifest.json"
	manifest_path.write_text(
		json.dumps({"selected_filings": [{"accession": selected}]}), encoding="utf-8"
	)
	(source_root / f"{selected}.txt").write_text(
		"prefix exact operating phrase suffix", encoding="utf-8"
	)
	(source_root / f"{unselected}.txt").write_text(
		"exact operating phrase outside", encoding="utf-8"
	)

	request = EvidenceRequest(
		question_id="../model-chosen-path",
		question="Find the phrase",
		literal_phrases=["exact operating phrase"],
		followup_index=0,
	)
	result = retrieve_evidence(manifest_path, request, excerpt_radius=4)
	assert result["status"] == "RESOLVED"
	assert {match["source_id"] for match in result["matches"]} == {f"SEC:{selected}"}
	assert result["matches"][0]["byte_start"] >= 0
	assert result["matches"][0]["byte_end"] > result["matches"][0]["byte_start"]

	run_dir = tmp_path / "run"
	for index, expected in enumerate(
		("PENDING_FOLLOWUP", "PENDING_FOLLOWUP", "CAPPED_NO_RESULT")
	):
		missing = EvidenceRequest(
			question_id="../model-chosen-path",
			question="Missing evidence",
			literal_phrases=[f"absent phrase {index}"],
			followup_index=index,
		)
		assert checkpoint_evidence(run_dir, manifest_path, missing)["status"] == expected
	assert not (tmp_path / "model-chosen-path-0.json").exists()
	with pytest.raises(WorkflowError, match="out of sequence"):
		checkpoint_evidence(run_dir, manifest_path, request)
	with pytest.raises(ValidationError):
		EvidenceRequest(
			question_id="q",
			question="Too many phrases",
			literal_phrases=["a", "b", "c", "d"],
			followup_index=0,
		)


def test_review_validation_and_status_are_separate(tmp_path: Path) -> None:
	run_dir, _ = prepare(tmp_path)
	context = load(run_dir / "review-context.json")
	value = review_value(context)
	review = validate_review(value, source_allowlist=set(context["source_ref_allowlist"]))
	assert derive_status(review) == {
		"execution": "ANALYTICAL_COMPLETE",
		"mechanical": "PASS",
		"coverage": "COMPLETE",
		"analytical": "REVIEW_ACCEPTED",
		"budget": "AVAILABLE",
		"human": "NOT_APPROVED",
	}
	assert derive_status(review, budget_state="EXHAUSTED")["execution"] == "BLOCKED"
	# A reviewer challenging a prior decision may decline carrying it.
	revision = review_value(context, verdict="revise", revise_area="operating_costs")
	revision["areas"][1]["prior_decision_carried"] = False
	revised = validate_review(revision, source_allowlist=set(context["source_ref_allowlist"]))
	assert derive_status(revised)["analytical"] != "REVIEW_ACCEPTED"
	unsupported_carry = review_value(context)
	unsupported_carry["areas"][1]["prior_decision_carried"] = False
	with pytest.raises(WorkflowError, match="carried prior decision"):
		validate_review(unsupported_carry, source_allowlist=set(context["source_ref_allowlist"]))
	# Required dependencies are a minimum; additional cross-schedule review is allowed.
	revision["areas"][1]["changed_dependencies_assessed"] += ["ppe_capex", "leases"]
	validate_review(revision, source_allowlist=set(context["source_ref_allowlist"]))

	wrong_order = review_value(context)
	wrong_order["areas"][0], wrong_order["areas"][1] = (
		wrong_order["areas"][1],
		wrong_order["areas"][0],
	)
	with pytest.raises(ValidationError, match="fixed order"):
		WholeModelReview.model_validate(wrong_order)
	bad_dependency = review_value(context)
	bad_dependency["areas"][-1]["changed_dependencies_assessed"] = []
	with pytest.raises(WorkflowError, match="bound dependencies"):
		validate_review(
			bad_dependency, source_allowlist=set(context["source_ref_allowlist"])
		)
	bad_source = review_value(context)
	bad_source["areas"][0]["source_refs"] = ["outside-source-universe"]
	with pytest.raises(WorkflowError, match="unsupported source"):
		validate_review(bad_source, source_allowlist=set(context["source_ref_allowlist"]))
	with pytest.raises(ValidationError):
		WholeModelReview.model_validate({**value, "published_value": 999})


def test_run_and_status_use_transport_then_business_validation(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	run_dir, _ = prepare(tmp_path)
	context = load(run_dir / "review-context.json")
	value = review_value(context)

	def fake_dispatch(request: dict, **kwargs: object) -> tuple[dict, dict]:
		assert request["model"] == "gpt-5.6-sol"
		assert kwargs["stage"] == "whole_model_review"
		assert kwargs["final_review"] is True
		return value, {"call_id": "test-call", "resumed": False}

	monkeypatch.setattr(
		"smrik_fund.analysis_transport.dispatch_request", fake_dispatch
	)
	result = run_stage(
		run_dir=run_dir,
		stage="whole_model_review",
		budget_path=tmp_path / "unused-budget.json",
		prices=load(PRICES_PATH),
	)
	assert result["transition"]["status"]["execution"] == "ANALYTICAL_COMPLETE"
	assert current_status(run_dir)["status"]["analytical"] == "REVIEW_ACCEPTED"


def test_revision_requires_analyst_correction_and_independent_recheck(
	tmp_path: Path,
) -> None:
	run_dir, _ = prepare(tmp_path)
	context = load(run_dir / "review-context.json")
	review = review_value(context, verdict="revise", revise_area="dcf_terminal")
	transition = checkpoint_whole_model_review(run_dir, review)
	assert transition["effective_prior_decisions_preserved"] is True
	assert transition["next"]["stage"] == "analyst_correction"
	assert transition["next"]["final_review"] is False

	source_ref = context["source_ref_allowlist"][0]
	correction = {
		"area": "dcf_terminal",
		"outcome": "select",
		"selection_id": "dcf_terminal:beta_high",
		"source_refs": [source_ref],
		"period_refs": ["TERMINAL_FY2037"],
		"basis": "Closed option retains the effective model after reassessment.",
		"follow_up_request": None,
	}
	correction_transition = checkpoint_analyst_correction(run_dir, correction)
	assert correction_transition["new_selection_not_yet_adopted"] is True
	assert correction_transition["candidate_recalculated_before_recheck"] is True
	assert correction_transition["next"]["stage"] == "independent_recheck"
	assert correction_transition["next"]["final_review"] is False
	assert not (run_dir / "transitions/03-after-recheck.json").exists()

	with pytest.raises(WorkflowError, match="unbound"):
		validate_correction(
			{**correction, "selection_id": "dcf_terminal:model-invented-number"},
			options=context["correction_options"],
			source_allowlist=set(context["source_ref_allowlist"]),
		)

	recheck = {
		"verdict": "accept",
		"area": "dcf_terminal",
		"selection_id": "dcf_terminal:beta_high",
		"source_valid": True,
		"period_valid": True,
		"method_valid": True,
		"no_double_count": True,
		"cross_schedule_concerns_resolved": True,
		"concerns": [],
		"rationale": "Independent recheck supports retaining the effective decision.",
	}
	final = checkpoint_independent_recheck(run_dir, recheck)
	assert final["correction_adopted"] is True
	assert final["effective_prior_decision_retained"] is False
	assert final["further_revision_allowed"] is False
	assert final["status"] == {
		"execution": "RECHECK_COMPLETE",
		"mechanical": "PASS",
		"coverage": "COMPLETE",
		"analytical": "RECHECK_ACCEPTED",
		"budget": "AVAILABLE",
		"human": "NOT_APPROVED",
	}
	candidate = load(run_dir / "candidates/02-corrected-calculation.json")
	assert candidate["snapshot"]["p9"]["wacc"] == pytest.approx(0.09576747852871702)
	assert candidate["snapshot"]["p9"]["enterpriseValue"] == pytest.approx(
		1627611.6529746132
	)
	assert candidate["snapshot"]["p9"]["perShareValue"] == pytest.approx(
		210.06222140921045
	)
	with pytest.raises(ValidationError):
		AnalystCorrection.model_validate({**correction, "new_numeric_value": 0.03})
