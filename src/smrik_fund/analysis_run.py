"""Fixed P10 analysis controller over immutable workflow checkpoints."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from smrik_fund import analysis_workflow as workflow
from smrik_fund.analysis_budget import content_hash


class AnalysisRunError(ValueError):
	pass


def _load(path: Path) -> dict[str, Any]:
	value = json.loads(path.read_text(encoding="utf-8-sig"))
	if not isinstance(value, dict):
		raise AnalysisRunError(f"Expected JSON object: {path}")
	return value


def _write(path: Path, value: object) -> None:
	payload = json.dumps(
		value, sort_keys=True, ensure_ascii=False, allow_nan=False
	).encode("utf-8") + b"\n"
	path.parent.mkdir(parents=True, exist_ok=True)
	if path.exists():
		if path.read_bytes() != payload:
			raise AnalysisRunError(f"Immutable analysis-run checkpoint differs: {path}")
		return
	path.write_bytes(payload)


def _validate_current_context(run_dir: Path) -> dict[str, Any] | None:
	validator = getattr(workflow, "validate_current_context", None)
	if validator is None:
		raise AnalysisRunError("analysis_workflow.validate_current_context is required")
	result = validator(run_dir)
	if result is False:
		raise AnalysisRunError("STALE_CONTEXT: workflow context validation failed")
	return result


def _status(
	*,
	execution: str,
	coverage: str,
	analytical: str,
	budget: str,
	mechanical: str = "PASS",
) -> dict[str, str]:
	return {
		"execution": execution,
		"mechanical": mechanical,
		"coverage": coverage,
		"analytical": analytical,
		"budget": budget,
		"human": "NOT_APPROVED",
	}


def _terminal(
	run_dir: Path,
	*,
	status: dict[str, str],
	reason: str,
	effective_prior_preserved: bool,
	extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
	manifest = _load(run_dir / "workflow-manifest.json")
	value = {
		"status": status,
		"reason": reason,
		"effective_prior_model_preserved": effective_prior_preserved,
		"effective_prior_model_sha256": manifest["bindings"]["selected_model"],
		**(extra or {}),
	}
	checkpoint = Path((extra or {}).get("review_checkpoint", run_dir))
	effective = checkpoint / "effective-model.json"
	if effective.exists() and status["analytical"] in {"REVIEW_ACCEPTED", "RECHECK_ACCEPTED"}:
		value["effective_model"] = _load(effective)
	_write(run_dir / "analysis-run" / "terminal.json", value)
	return value


def _failure_status(exc: Exception, mechanical: str) -> dict[str, str]:
	message = str(exc)
	if "BUDGET_EXHAUSTED" in message:
		budget = "EXHAUSTED"
	elif "USAGE_UNKNOWN" in message:
		budget = "USAGE_UNKNOWN"
	elif "STALE_CONTEXT" in message:
		budget = "STALE"
	else:
		budget = "AVAILABLE"
	return _status(
		execution="BLOCKED",
		mechanical="FAIL" if "MECHANICAL_FAILURE" in message else mechanical,
		coverage="INCOMPLETE",
		analytical="NOT_ACCEPTED",
		budget=budget,
	)


def _request_evidence(
	run_dir: Path,
	transition: dict[str, Any],
	attempts: dict[str, int],
) -> list[dict[str, Any]]:
	manifest = _load(run_dir / "workflow-manifest.json")
	input_paths = manifest.get("input_paths") or {}
	source_manifest_value = input_paths.get("source_manifest")
	if not source_manifest_value:
		raise AnalysisRunError("Workflow manifest has no pinned source_manifest input path")
	source_manifest = Path(source_manifest_value)
	results = []
	for queued in transition.get("evidence_queue", []):
		request = workflow.EvidenceRequest.model_validate(queued["request"])
		expected = attempts.get(request.question_id, 0)
		if request.followup_index != expected:
			raise AnalysisRunError("Evidence follow-up is stale or skips an attempt")
		if expected >= 3:
			raise AnalysisRunError("Evidence question exceeded initial plus two follow-ups")
		result = workflow.checkpoint_evidence(run_dir, source_manifest, request)
		attempts[request.question_id] = expected + 1
		results.append({"area": queued["area"], "request": queued["request"], "result": result})
	return results


def _existing_evidence(run_dir: Path) -> tuple[dict[str, int], list[dict[str, Any]]]:
	attempts: dict[str, int] = {}
	history = []
	for path in sorted((run_dir / "evidence").glob("*.json")):
		result = _load(path)
		question_id = result.get("question_id")
		index = result.get("followup_index")
		if not isinstance(question_id, str) or not isinstance(index, int):
			raise AnalysisRunError(f"Malformed evidence checkpoint: {path}")
		if index != attempts.get(question_id, 0):
			raise AnalysisRunError("Existing evidence checkpoints are stale or out of sequence")
		attempts[question_id] = index + 1
		history.append({"area": None, "request": None, "result": result})
	return attempts, history


def _evidence_review_request(
	root: Path,
	*,
	prior_review: dict[str, Any],
	evidence_history: list[dict[str, Any]],
) -> dict[str, Any]:
	request = copy.deepcopy(
		_load(root / "requests" / "01-whole-model-review.request.json")
	)
	context = _load(root / "review-context.json")
	payload = {
		"original_review_context": context,
		"prior_whole_model_review": prior_review,
		"bounded_retrieval_history": evidence_history,
	}
	request["input"] = (
		"Freshly reassess all twelve areas after the bounded application-owned source "
		"retrieval below. Preserve prior questions and no-result scope. A still-pending "
		"question may request its next sequential follow-up with one to three literal "
		"phrases; resolved evidence must be cited using its pinned source_id and byte "
		"offsets. Do not choose paths, tools, code, formulas, or unlisted numeric inputs. "
		"Return the complete strict whole-model review.\n"
		+ json.dumps(payload, sort_keys=True, ensure_ascii=False)
	)
	return request


def _make_review_child(
	root: Path,
	*,
	ordinal: int,
	request: dict[str, Any],
) -> Path:
	child = root / "analysis-run" / f"evidence-review-{ordinal:02d}"
	context = _load(root / "review-context.json")
	manifest = copy.deepcopy(_load(root / "workflow-manifest.json"))
	manifest["execution"] = "EVIDENCE_REASSESSMENT_PREPARED"
	manifest["request_hash"] = content_hash(request)
	_write(child / "review-context.json", context)
	_write(child / "workflow-manifest.json", manifest)
	_write(child / "requests" / "01-whole-model-review.request.json", request)
	return child


def _dispatch_evidence_review(
	root: Path,
	child: Path,
	*,
	request: dict[str, Any],
	budget_path: Path,
	prices: dict[str, Any],
	client: Any,
) -> dict[str, Any]:
	from smrik_fund.analysis_transport import dispatch_request

	_validate_current_context(root)
	structured, metadata = dispatch_request(
		request,
		run_dir=child,
		stage="evidence_reassessment",
		budget_path=budget_path,
		prices=prices,
		final_review=False,
		client=client,
	)
	transition = workflow.checkpoint_whole_model_review(child, structured)
	return {"structured": structured, "metadata": metadata, "transition": transition}


def _initial_review(
	run_dir: Path,
	*,
	budget_path: Path,
	prices: dict[str, Any],
	client: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
	transition_path = run_dir / "transitions" / "01-after-review.json"
	result_path = run_dir / "results" / "01-whole-model-review.structured.json"
	if transition_path.exists() and result_path.exists():
		return _load(result_path), _load(transition_path)
	_validate_current_context(run_dir)
	result = workflow.run_stage(
		run_dir=run_dir,
		stage="whole_model_review",
		budget_path=budget_path,
		prices=prices,
		client=client,
	)
	return _load(result_path), result["transition"]


def run_analysis(
	run_dir: Path,
	budget_path: Path,
	prices: dict[str, Any],
	client: Any = None,
) -> dict[str, Any]:
	"""Run the fixed P10 review/evidence/correction/recheck state machine."""
	run_dir = run_dir.resolve()
	budget_path = budget_path.resolve()
	terminal_path = run_dir / "analysis-run" / "terminal.json"
	if terminal_path.exists():
		_validate_current_context(run_dir)
		return _load(terminal_path)
	context = _load(run_dir / "review-context.json")
	mechanical = context["mechanical_state"]["result"]
	if mechanical != "PASS":
		return _terminal(
			run_dir,
			status=_status(
				execution="BLOCKED",
				mechanical=mechanical,
				coverage="INCOMPLETE",
				analytical="NOT_ACCEPTED",
				budget="NOT_DISPATCHED",
			),
			reason="Mechanical model state is not valid for review",
			effective_prior_preserved=True,
		)
	try:
		_validate_current_context(run_dir)
		review, transition = _initial_review(
			run_dir, budget_path=budget_path, prices=prices, client=client
		)
		attempts, evidence_history = _existing_evidence(run_dir)
		current_dir = run_dir
		for ordinal in range(1, 4):
			queue = transition.get("evidence_queue", [])
			if not queue:
				break
			batch = _request_evidence(run_dir, transition, attempts)
			evidence_history.extend(batch)
			if any(item["result"]["status"] == "CAPPED_NO_RESULT" for item in batch):
				return _terminal(
					run_dir,
					status=_status(
						execution="BLOCKED",
						coverage="INCOMPLETE_SOURCE_LIMITATION",
						analytical="UNRESOLVED",
						budget="AVAILABLE",
					),
					reason="Bounded manifest evidence search exhausted without support",
					effective_prior_preserved=True,
					extra={"evidence_history": evidence_history},
				)
			request = _evidence_review_request(
				run_dir, prior_review=review, evidence_history=evidence_history
			)
			current_dir = _make_review_child(
				run_dir, ordinal=ordinal, request=request
			)
			result = _dispatch_evidence_review(
				run_dir,
				current_dir,
				request=request,
				budget_path=budget_path,
				prices=prices,
				client=client,
			)
			review = result["structured"]
			transition = result["transition"]
			if not transition.get("evidence_queue"):
				break
		else:
			return _terminal(
				run_dir,
				status=_status(
					execution="BLOCKED",
					coverage="INCOMPLETE_SOURCE_LIMITATION",
					analytical="UNRESOLVED",
					budget="EXHAUSTED",
				),
				reason="Evidence review cycle cap reached",
				effective_prior_preserved=True,
				extra={"evidence_history": evidence_history},
			)

		if review["verdict"] == "accept" and transition["status"]["execution"] == "ANALYTICAL_COMPLETE":
			return _terminal(
				run_dir,
				status=transition["status"],
				reason="Whole-model review accepted all twelve areas",
				effective_prior_preserved=True,
				extra={"review_checkpoint": str(current_dir)},
			)
		if (transition.get("next") or {}).get("stage") != "analyst_correction":
			return _terminal(
				run_dir,
				status=transition["status"],
				reason="Review remains rejected, unresolved, or unsupported",
				effective_prior_preserved=True,
				extra={"review_checkpoint": str(current_dir)},
			)

		_validate_current_context(run_dir)
		correction = workflow.run_stage(
			run_dir=current_dir,
			stage="analyst_correction",
			budget_path=budget_path,
			prices=prices,
			client=client,
		)
		if (correction["transition"].get("next") or {}).get("stage") != "independent_recheck":
			return _terminal(
				run_dir,
				status=correction["transition"]["status"],
				reason="Analyst correction did not produce a recalculated candidate",
				effective_prior_preserved=True,
			)
		_validate_current_context(run_dir)
		recheck = workflow.run_stage(
			run_dir=current_dir,
			stage="independent_recheck",
			budget_path=budget_path,
			prices=prices,
			client=client,
		)
		accepted = recheck["transition"]["status"]["analytical"] == "RECHECK_ACCEPTED"
		return _terminal(
			run_dir,
			status=recheck["transition"]["status"],
			reason="Bounded correction independently accepted"
			if accepted
			else "Bounded correction rejected",
			effective_prior_preserved=not recheck["transition"].get("correction_adopted", False),
			extra={"review_checkpoint": str(current_dir)},
		)
	except Exception as exc:
		return _terminal(
			run_dir,
			status=_failure_status(exc, mechanical),
			reason=f"{type(exc).__name__}: {exc}",
			effective_prior_preserved=True,
		)
