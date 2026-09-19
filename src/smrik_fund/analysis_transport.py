"""Serial, checkpointed transport for the bounded P10 MSFT review calls."""

import json
import time
from datetime import date
from pathlib import Path
from typing import Any

from smrik_fund.analysis_budget import (
	content_hash,
	record_outcome,
	reservation,
	reserve_call,
)

TASK_ID = "p10-msft-analysis"
MAX_CALLS = 4
MAX_COMMITTED_EUR = 2.00
STAGES = {
	"whole_model_review",
	"analyst_correction",
	"independent_recheck",
	"evidence_reassessment",
}


def _save(path: Path, value: Any) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	if path.exists():
		if json.loads(path.read_text(encoding="utf-8")) != value:
			raise ValueError(f"Conflicting existing transport artifact: {path.name}")
		return
	with path.open("x", encoding="utf-8") as stream:
		json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
		stream.write("\n")


def _structured_response(raw: dict) -> dict:
	if raw.get("status") != "completed":
		raise ValueError("Provider response is incomplete or failed")
	texts = []
	for item in raw.get("output", []):
		if item.get("type") not in {"reasoning", "message"}:
			raise ValueError("Unexpected provider output type")
		for part in item.get("content", []):
			if part.get("type") == "refusal":
				raise ValueError("Provider refused the request")
			if part.get("type") == "output_text":
				texts.append(part["text"])
	value = json.loads("".join(texts))
	if not isinstance(value, dict):
		raise ValueError("Provider output must be a structured object")
	return value


def _validate_settings(request: dict, stage: str, final_review: bool) -> None:
	if stage not in STAGES or (final_review and stage != "whole_model_review"):
		raise ValueError("Unknown stage or ineligible final-review reservation")
	expected = {
		"model", "reasoning", "service_tier", "input", "text",
		"max_output_tokens", "tools", "background",
	}
	if set(request) != expected or not all((
		request["model"] == "gpt-5.6-sol",
		request["reasoning"] == {"effort": "high"},
		request["service_tier"] == "default",
		request["max_output_tokens"] == (16000 if stage in {"whole_model_review", "evidence_reassessment"} else 8000),
		request["tools"] == [],
		request["background"] is False,
		isinstance(request["input"], str),
		request["text"].get("format", {}).get("type") == "json_schema",
		request["text"].get("format", {}).get("strict") is True,
	)):
		raise ValueError("Request differs from the admitted P10 runtime settings")


def dispatch_request(
	request: dict,
	*,
	run_dir: Path,
	stage: str,
	budget_path: Path,
	prices: dict,
	final_review: bool = False,
	client: Any = None,
	today: date | None = None,
	package: str = "p10",
) -> tuple[dict, dict]:
	"""Persist admission and raw output before parsing; never retry implicitly.

	Only the serial parent workflow calls this function. Business/schema validation
	remains the workflow's responsibility, including on a returned cached response.
	"""
	_validate_settings(request, stage, final_review)
	if package not in {"p10", "p11"}:
		raise ValueError("Unsupported analysis package")
	if package == "p11" and (stage != "independent_recheck" or final_review):
		raise ValueError("P11 only permits an affected-decision recheck")
	task_id = TASK_ID if package == "p10" else "p11-msft-revision"
	max_calls, cap_eur = (MAX_CALLS, MAX_COMMITTED_EUR) if package == "p10" else (2, 1.0)
	request_hash = content_hash(request)
	state = json.loads(budget_path.read_text(encoding="utf-8"))
	calls = [c for c in state["calls"] if c["task_id"] == task_id]
	matched = [c for c in calls if c["request_hash"] == request_hash]
	# Shared artifacts allow presentation-only exports to reuse the same call.
	artifacts = budget_path.parent / f"build-guide-{package}" / "calls" / request_hash
	if matched:
		if len(matched) != 1 or matched[0]["status"] != "completed":
			raise ValueError("USAGE_UNKNOWN: exact request has an unsettled admission")
		if not (artifacts / "metadata.json").exists():
			raise ValueError("Completed request has no verified replay artifacts")
		metadata = json.loads((artifacts / "metadata.json").read_text())
		raw = json.loads((artifacts / "response.json").read_text())
		saved_request = json.loads((artifacts / "request.json").read_text())
		call = matched[0]
		if (
			content_hash(saved_request) != request_hash
			or content_hash(raw) != metadata["raw_response_hash"]
			or metadata["call_id"] != call["call_id"]
			or raw.get("id") != call["latest_outcome"]["response_id"]
			or raw.get("model") != call["latest_outcome"]["returned_model"]
			or raw.get("usage") != call["latest_outcome"]["usage"]
		):
			raise ValueError("Replay artifacts differ from the admitted provider result")
		value = _structured_response(raw)
		metadata = {**metadata, "resumed": True}
	else:
		estimate = reservation(request, prices, today=today or date.today())
		committed = sum(c.get("cost", {}).get("priced_eur", c["reserved_eur"]) for c in calls)
		if len(calls) >= max_calls or committed + estimate["reserved_eur"] > cap_eur:
			raise ValueError(f"BUDGET_EXHAUSTED: {package.upper()} call or committed-cost cap reached")
		if client is None:
			from dotenv import load_dotenv
			from openai import OpenAI

			load_dotenv(Path(__file__).resolve().parents[2] / ".env")
			client = OpenAI(
				base_url="https://api.openai.com/v1", max_retries=0, timeout=300,
			)
		call_id = f"{task_id}-{len(calls) + 1:02d}-{stage}"
		_save(artifacts / "request.json", request)
		admission = reserve_call(
			budget_path, call_id=call_id, task_id=task_id, request=request,
			endpoint_host="api.openai.com", final_review=final_review,
			prices=prices, today=today or date.today(),
		)
		_save(artifacts / "reservation.json", admission)
		started = time.perf_counter()
		try:
			response = client.responses.create(**request)
			raw = response if isinstance(response, dict) else response.model_dump(mode="json")
		except Exception as exc:
			# Exception strings can contain credentials or headers; persist type only.
			elapsed = time.perf_counter() - started
			_save(artifacts / "transport-error.json", {"error_type": type(exc).__name__})
			outcome = record_outcome(budget_path, call_id=call_id, usage=None, elapsed_seconds=elapsed)
			_save(artifacts / "outcome.json", outcome)
			raise ValueError(f"USAGE_UNKNOWN: {call_id}; {type(exc).__name__}") from None
		elapsed = time.perf_counter() - started
		_save(artifacts / "response.json", raw)
		try:
			if raw.get("service_tier") not in {None, "default"}:
				raise ValueError("Returned service tier differs from admitted prices")
			outcome = record_outcome(
				budget_path, call_id=call_id, usage=raw.get("usage"),
				elapsed_seconds=elapsed, response_id=raw.get("id"),
				returned_model=raw.get("model"),
			)
		except ValueError as exc:
			_save(artifacts / "accounting-error.json", {"error_type": type(exc).__name__})
			outcome = record_outcome(
				budget_path, call_id=call_id, usage=None, elapsed_seconds=elapsed,
				response_id=raw.get("id"), returned_model=raw.get("model"),
			)
		_save(artifacts / "outcome.json", outcome)
		metadata = {
			"call_id": call_id, "stage": stage, "request_hash": request_hash,
			"raw_response_hash": content_hash(raw), "status": outcome["status"],
			"artifact_dir": str(artifacts.resolve()), "resumed": False,
			"final_review": final_review, "elapsed_seconds": elapsed,
		}
		_save(artifacts / "metadata.json", metadata)
		if outcome["status"] != "completed":
			raise ValueError(f"USAGE_UNKNOWN: {call_id}; provider usage not reconciled")
		try:
			value = _structured_response(raw)
		except (ValueError, KeyError, TypeError) as exc:
			_save(artifacts / "parse-error.json", {"error_type": type(exc).__name__})
			raise ValueError(f"INVALID_PROVIDER_OUTPUT: {call_id}; see preserved response") from None
		_save(artifacts / "structured.json", value)
	_save(run_dir / "transport" / f"{stage}-{request_hash}.json", {
		"call_id": metadata["call_id"], "artifact_dir": metadata["artifact_dir"],
		"request_hash": request_hash,
	})
	return value, metadata
