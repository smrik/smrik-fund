import json
from pathlib import Path

import pytest

from smrik_fund import analysis_workflow as workflow
from smrik_fund.analysis_run import run_analysis


def write(path: Path, value: object) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(value), encoding="utf-8")


def prepared_run(tmp_path: Path) -> Path:
	run_dir = tmp_path / "prepared"
	write(
		run_dir / "workflow-manifest.json",
		{
			"bindings": {"selected_model": "a" * 64},
			"input_paths": {"source_manifest": str(tmp_path / "source_manifest.json")},
			"request_hash": "initial",
		},
	)
	write(
		run_dir / "review-context.json",
		{
			"mechanical_state": {"result": "PASS"},
			"bindings": {"selected_model": "a" * 64},
			"source_ref_allowlist": ["SEC:0001193125-26-191507"],
		},
	)
	write(
		run_dir / "requests/01-whole-model-review.request.json",
		{
			"model": "gpt-5.6-sol",
			"reasoning": {"effort": "high"},
			"service_tier": "default",
			"input": "original context",
			"text": {"format": {"type": "json_schema", "strict": True, "schema": {}}},
			"max_output_tokens": 8000,
			"tools": [],
			"background": False,
		},
	)
	write(tmp_path / "source_manifest.json", {"selected_filings": []})
	return run_dir


def evidence_request(index: int) -> dict:
	return {
		"question_id": "tax-note",
		"question": "Find current-tax detail",
		"literal_phrases": ["income taxes payable"],
		"followup_index": index,
	}


def initial_review(run_dir: Path, transition: dict) -> None:
	write(
		run_dir / "results/01-whole-model-review.structured.json",
		{"verdict": "revise", "areas": [], "rationale": "Needs evidence"},
	)
	write(run_dir / "transitions/01-after-review.json", transition)


def enable_context_validation(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
	calls = []

	def validate(path: Path) -> dict:
		calls.append(path)
		return {"status": "PASS"}

	monkeypatch.setattr(workflow, "validate_current_context", validate, raising=False)
	return calls


def test_resolved_evidence_gets_fresh_full_review_in_child_checkpoint(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	run_dir = prepared_run(tmp_path)
	initial_review(
		run_dir,
		{
			"evidence_queue": [{"area": "taxes", "request": evidence_request(0)}],
			"status": {"execution": "ACTION_REQUIRED"},
		},
	)
	validations = enable_context_validation(monkeypatch)
	monkeypatch.setattr(
		workflow,
		"checkpoint_evidence",
		lambda *_args, **_kwargs: {
			"status": "RESOLVED",
			"matches": [
				{
					"source_id": "SEC:0001193125-26-191507",
					"byte_start": 100,
					"byte_end": 160,
					"excerpt": "income taxes payable source excerpt",
				}
			],
		},
	)
	dispatches = []

	def dispatch(request: dict, **kwargs: object) -> tuple[dict, dict]:
		dispatches.append((request, kwargs))
		return {"verdict": "accept", "areas": []}, {"call_id": "review-02"}

	monkeypatch.setattr("smrik_fund.analysis_transport.dispatch_request", dispatch)
	monkeypatch.setattr(
		workflow,
		"checkpoint_whole_model_review",
		lambda *_args, **_kwargs: {
			"evidence_queue": [],
			"status": {
				"execution": "ANALYTICAL_COMPLETE",
				"mechanical": "PASS",
				"coverage": "COMPLETE",
				"analytical": "REVIEW_ACCEPTED",
				"budget": "AVAILABLE",
				"human": "NOT_APPROVED",
			},
		},
	)

	result = run_analysis(run_dir, tmp_path / "budget.json", {}, client=object())
	assert result["status"]["analytical"] == "REVIEW_ACCEPTED"
	assert result["effective_prior_model_preserved"] is True
	assert len(dispatches) == 1
	request, kwargs = dispatches[0]
	assert kwargs["stage"] == "evidence_reassessment"
	assert kwargs["final_review"] is False
	assert "income taxes payable source excerpt" in request["input"]
	child = run_dir / "analysis-run/evidence-review-01"
	assert (child / "workflow-manifest.json").exists()
	assert (run_dir / "results/01-whole-model-review.structured.json").exists()
	assert len(validations) >= 2


def test_capped_no_result_stops_without_another_paid_call(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	run_dir = prepared_run(tmp_path)
	initial_review(
		run_dir,
		{
			"evidence_queue": [{"area": "taxes", "request": evidence_request(2)}],
			"status": {"execution": "ACTION_REQUIRED"},
		},
	)
	for index in (0, 1):
		write(
			run_dir / "evidence" / f"tax-note-{index}.json",
			{
				"question_id": "tax-note",
				"followup_index": index,
				"status": "PENDING_FOLLOWUP",
				"matches": [],
			},
		)
	enable_context_validation(monkeypatch)
	monkeypatch.setattr(
		workflow,
		"checkpoint_evidence",
		lambda *_args, **_kwargs: {
			"status": "CAPPED_NO_RESULT",
			"matches": [],
			"no_result_scope": {"searched_source_ids": []},
		},
	)
	monkeypatch.setattr(
		"smrik_fund.analysis_transport.dispatch_request",
		lambda *_args, **_kwargs: pytest.fail("No paid reassessment after evidence cap"),
	)

	result = run_analysis(run_dir, tmp_path / "budget.json", {}, client=object())
	assert result["status"]["execution"] == "BLOCKED"
	assert result["status"]["coverage"] == "INCOMPLETE_SOURCE_LIMITATION"
	assert result["status"]["analytical"] == "UNRESOLVED"
	assert result["effective_prior_model_preserved"] is True


def test_one_correction_is_recalculated_then_independently_rechecked(
	tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	run_dir = prepared_run(tmp_path)
	initial_review(
		run_dir,
		{
			"evidence_queue": [],
			"next": {"stage": "analyst_correction"},
			"status": {"execution": "ACTION_REQUIRED"},
		},
	)
	validations = enable_context_validation(monkeypatch)
	stages = []

	def run_stage(**kwargs: object) -> dict:
		stage = kwargs["stage"]
		stages.append(stage)
		if stage == "analyst_correction":
			return {
				"transition": {
					"candidate_recalculated_before_recheck": True,
					"next": {"stage": "independent_recheck"},
					"status": {"execution": "AWAITING_INDEPENDENT_RECHECK"},
				}
			}
		return {
			"transition": {
				"correction_adopted": True,
				"status": {
					"execution": "RECHECK_COMPLETE",
					"mechanical": "PASS",
					"coverage": "COMPLETE",
					"analytical": "RECHECK_ACCEPTED",
					"budget": "AVAILABLE",
					"human": "NOT_APPROVED",
				}
			}
		}

	monkeypatch.setattr(workflow, "run_stage", run_stage)
	result = run_analysis(run_dir, tmp_path / "budget.json", {}, client=object())
	assert stages == ["analyst_correction", "independent_recheck"]
	assert result["status"]["analytical"] == "RECHECK_ACCEPTED"
	assert result["effective_prior_model_preserved"] is False
	assert len(validations) >= 3


@pytest.mark.parametrize(
	("message", "budget"),
	[
		("BUDGET_EXHAUSTED: cap reached", "EXHAUSTED"),
		("USAGE_UNKNOWN: unsettled call", "USAGE_UNKNOWN"),
		("STALE_CONTEXT: source changed", "STALE"),
		("INVALID_PROVIDER_OUTPUT: preserved raw response", "AVAILABLE"),
	],
)
def test_budget_stale_and_provider_failures_never_become_success(
	tmp_path: Path,
	monkeypatch: pytest.MonkeyPatch,
	message: str,
	budget: str,
) -> None:
	run_dir = prepared_run(tmp_path)
	enable_context_validation(monkeypatch)
	monkeypatch.setattr(
		workflow,
		"run_stage",
		lambda **_kwargs: (_ for _ in ()).throw(ValueError(message)),
	)

	result = run_analysis(run_dir, tmp_path / "budget.json", {}, client=object())
	assert result["status"]["execution"] == "BLOCKED"
	assert result["status"]["analytical"] == "NOT_ACCEPTED"
	assert result["status"]["budget"] == budget
	assert result["effective_prior_model_preserved"] is True
