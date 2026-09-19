"""One optional P12 fixed-task comparison. Default execution is a free preflight."""

from __future__ import annotations

import argparse
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
from smrik_fund.analysis_transport import _structured_response
from smrik_fund.other_balances import OtherBalancesReview, _review_eligible
from smrik_fund.review_revision import read, write_new

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "data/build-guide-p12/prepared-calibration/outbound-manifest.json"
BUDGET = ROOT / "data/build-guide-api-budget.json"
OUTPUT = ROOT / "data/build-guide-p12/calibration-low"
TASK_ID = "p12-fixed-task-calibration"


def prepare(*, manifest_path: Path = MANIFEST, budget_path: Path = BUDGET, prices: dict | None = None, today: date | None = None) -> tuple[dict, dict, dict]:
	manifest, ledger = read(manifest_path), read(budget_path)
	baseline = read(ROOT / manifest["baseline"]["request_path"])
	request = read(ROOT / manifest["alternative"]["request_path"])
	expected = {**baseline, "reasoning": {"effort": "low"}}
	if baseline["reasoning"] != {"effort": "medium"} or request != expected or content_hash(baseline) != manifest["baseline"]["request_hash"] or content_hash(request) != manifest["alternative"]["request_hash"]:
		raise ValueError("Calibration must change only the reasoning setting of the pinned baseline")
	if request["model"] != "gpt-5.6-luna" or request["tools"] != [] or request["background"] is not False or request["service_tier"] != "default" or request["max_output_tokens"] != 12000:
		raise ValueError("Calibration request differs from the approved-transfer preparation")
	matched = [call for call in ledger["calls"] if call["call_id"] == manifest["baseline"]["call_id"] and call["request_hash"] == manifest["baseline"]["request_hash"]]
	if len(matched) != 1 or matched[0]["status"] != "completed":
		raise ValueError("The fixed baseline must be a completed recorded call")
	if any(call["task_id"] == TASK_ID for call in ledger["calls"]):
		raise ValueError("Calibration's single attempt is already admitted; preserve its outcome/hold")
	prices = prices or manifest["price_snapshot"]
	estimate = reservation(request, prices, today=today or date.today())
	committed = sum(call.get("cost", {}).get("priced_eur", call["reserved_eur"]) for call in ledger["calls"])
	if ledger["admission_locked"] or ledger["ceiling_eur"] > 5 or estimate["reserved_eur"] > 0.10 or committed + estimate["reserved_eur"] + ledger["final_review_reserve_eur"] > ledger["ceiling_eur"]:
		raise ValueError("BUDGET_EXHAUSTED: calibration cannot fit its cap and the protected program budget")
	preflight = {"status": "PREPARED_NO_CALL", "requires_explicit_P12_transfer_approval": True, "request_hash": content_hash(request), "baseline_call_id": matched[0]["call_id"], "baseline_cost_eur": matched[0]["cost"]["priced_eur"], "baseline_usage": matched[0]["latest_outcome"]["usage"], "baseline_elapsed_seconds": matched[0]["latest_outcome"]["elapsed_seconds"], "admission_estimate": estimate, "committed_before_eur": committed, "max_attempts": 1, "cap_eur": 0.10, "price_snapshot": prices, "model_adoption": False}
	return request, prices, preflight


def run(*, execute_approved_transfer: bool = False, manifest_path: Path = MANIFEST, budget_path: Path = BUDGET, output_dir: Path = OUTPUT, prices: dict | None = None, today: date | None = None, client: Any = None) -> dict:
	request, prices, preflight = prepare(manifest_path=manifest_path, budget_path=budget_path, prices=prices, today=today)
	if not execute_approved_transfer:
		return preflight
	if output_dir.exists() and any(output_dir.iterdir()):
		raise ValueError("Calibration output is not empty; preserve prior artifacts")
	if client is None:
		from dotenv import load_dotenv
		from openai import OpenAI

		load_dotenv(ROOT / ".env")
		client = OpenAI(base_url="https://api.openai.com/v1", max_retries=0, timeout=180)
	write_new(output_dir / "request.json", request)
	write_new(output_dir / "preflight.json", preflight)
	call_id = TASK_ID + "-01-low"
	admission = reserve_call(budget_path, call_id=call_id, task_id=TASK_ID, request=request, endpoint_host="api.openai.com", prices=prices, today=today or date.today())
	write_new(output_dir / "reservation.json", admission)
	started = time.perf_counter()
	try:
		response = client.responses.create(**request)
		raw = response if isinstance(response, dict) else response.model_dump(mode="json")
	except Exception as exc:
		write_new(output_dir / "transport-error.json", {"error_type": type(exc).__name__})
		outcome = record_outcome(budget_path, call_id=call_id, usage=None, elapsed_seconds=time.perf_counter() - started)
		write_new(output_dir / "outcome.json", outcome)
		raise ValueError("Calibration usage unknown; single attempt held and no retry permitted") from None
	elapsed = time.perf_counter() - started
	write_new(output_dir / "response.json", raw)
	try:
		if raw.get("service_tier") not in {None, "default"}:
			raise ValueError("Returned service tier differs from priced request")
		outcome = record_outcome(budget_path, call_id=call_id, usage=raw.get("usage"), elapsed_seconds=elapsed, response_id=raw.get("id"), returned_model=raw.get("model"))
	except ValueError as exc:
		write_new(output_dir / "accounting-error.json", {"error_type": type(exc).__name__})
		outcome = record_outcome(budget_path, call_id=call_id, usage=None, elapsed_seconds=elapsed, response_id=raw.get("id"), returned_model=raw.get("model"))
	write_new(output_dir / "outcome.json", outcome)
	if outcome["status"] != "completed":
		raise ValueError("Calibration usage unresolved; preserve hold without retry")
	try:
		review = OtherBalancesReview.model_validate(_structured_response(raw))
	except ValueError as exc:
		write_new(output_dir / "parse-error.json", {"error_type": type(exc).__name__})
		raise ValueError("Invalid calibration output; raw response and measured cost preserved") from None
	write_new(output_dir / "structured.json", review.model_dump(mode="json"))
	result = {"status": "RECORDED_AWAITING_PARENT_COMPARISON", "request_hash": content_hash(request), "response_hash": content_hash(raw), "baseline": preflight, "alternative": {"call_id": call_id, "reasoning": "low", "outcome": outcome, "review": review.model_dump(mode="json"), "business_flags_pass": _review_eligible(review)}, "model_adoption": False, "human_approval": False, "comparison_required": "Assess source/period support, company taxes versus operating UFCF, caveats, quality, cost and latency. One observed pair; no statistical reliability claim."}
	write_new(output_dir / "comparison-inputs.json", result)
	return result


def main(argv: list[str] | None = None) -> int:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--execute-approved-transfer", action="store_true", help="Only after explicit P12 transfer approval; admits at most one paid call")
	parser.add_argument("--prices", type=Path, help="Verified current dated snapshot; does not reprice existing ledger entries")
	args = parser.parse_args(argv)
	try:
		print(json.dumps(run(execute_approved_transfer=args.execute_approved_transfer, prices=read(args.prices) if args.prices else None), indent=2))
		return 0
	except (ValueError, KeyError, OSError) as exc:
		print(json.dumps({"status": "BLOCKED", "reason": str(exc), "model_adoption": False}))
		return 2


if __name__ == "__main__":
	raise SystemExit(main())
