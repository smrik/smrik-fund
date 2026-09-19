"""Serial, resumable API admission; no API calls or financial model calculations."""

import hashlib
import json
import math
import os
import tempfile
from datetime import date
from pathlib import Path


def content_hash(value: object) -> str:
	return hashlib.sha256(_encoded(value)).hexdigest()


def _encoded(value: object) -> bytes:
	return json.dumps(
		value, sort_keys=True, ensure_ascii=False, allow_nan=False
	).encode("utf-8")


def _number(value: object, name: str, *, positive: bool = False) -> float:
	if isinstance(value, bool) or not isinstance(value, (int, float)):
		raise ValueError(f"{name} must be numeric")
	if not math.isfinite(value) or value < 0 or (positive and value == 0):
		raise ValueError(f"{name} is outside its supported range")
	return float(value)


def _tokens(value: object, name: str) -> int:
	if not isinstance(value, int) or isinstance(value, bool) or value < 0:
		raise ValueError(f"{name} must be a nonnegative integer")
	return value


def _write(path: Path, value: dict) -> None:
	"""Atomic replacement; prior reservations survive serialization/write failures."""
	payload = _encoded(value)
	path.parent.mkdir(parents=True, exist_ok=True)
	temporary = None
	try:
		with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
			temporary = Path(stream.name)
			stream.write(payload)
			stream.flush()
			os.fsync(stream.fileno())
		os.replace(temporary, path)
	finally:
		if temporary is not None:
			temporary.unlink(missing_ok=True)


def _prices(prices: dict, today: date) -> None:
	if (
		not date.fromisoformat(prices["observed_date"])
		<= today
		<= date.fromisoformat(prices["valid_through"])
	):
		raise ValueError("Price snapshot is not current for this call")
	for key in (
		"input_usd_per_million",
		"cached_read_usd_per_million",
		"cache_write_usd_per_million",
		"output_usd_per_million",
		"usd_per_eur",
		"endpoint_uplift",
		"reservation_headroom",
	):
		_number(prices[key], key, positive=True)
	if prices["reservation_headroom"] < 1 or prices["endpoint_uplift"] < 1:
		raise ValueError("Reservation multipliers cannot discount the price")
	_tokens(prices["input_wrapper_allowance_tokens"], "wrapper allowance")
	_tokens(prices["max_input_tokens"], "input tier limit")


def reservation(request: dict, prices: dict, *, today: date | None = None) -> dict:
	"""UTF-8 byte count bounds text tokens; full JSON/schema plus wrapper allowance."""
	_prices(prices, today or date.today())
	if request.get("model") != prices["model"]:
		raise ValueError("Requested model has no matching price snapshot")
	if request.get("tools") or request.get("background"):
		raise ValueError("This budget supports bounded text-only foreground calls")
	if request.get("service_tier") != prices["service_tier"]:
		raise ValueError("Explicit standard service tier is required")
	if not isinstance(request.get("input"), str) or not request["input"]:
		raise ValueError("Complete text input is required before admission")
	output = _tokens(request.get("max_output_tokens"), "max_output_tokens")
	if output == 0:
		raise ValueError("A positive output cap is required")
	input_bound = len(_encoded(request)) + prices["input_wrapper_allowance_tokens"]
	if input_bound > prices["max_input_tokens"]:
		raise ValueError("Input bound exceeds the supported price/context tier")
	input_rate = max(
		prices[key]
		for key in (
			"input_usd_per_million",
			"cached_read_usd_per_million",
			"cache_write_usd_per_million",
		)
	)
	usd = (
		input_bound * input_rate + output * prices["output_usd_per_million"]
	) / 1_000_000
	eur = (
		usd
		* prices["endpoint_uplift"]
		* prices["reservation_headroom"]
		/ prices["usd_per_eur"]
	)
	return {
		"input_token_upper_bound": input_bound,
		"output_token_cap": output,
		"reserved_eur": eur,
		"request_hash": content_hash(request),
	}


def price_usage(usage: dict, prices: dict) -> dict:
	"""Reasoning is included in output tokens; never charge it twice."""
	input_tokens = _tokens(usage.get("input_tokens"), "input_tokens")
	output_tokens = _tokens(usage.get("output_tokens"), "output_tokens")
	if (
		_tokens(usage.get("total_tokens"), "total_tokens")
		!= input_tokens + output_tokens
	):
		raise ValueError("Usage token totals do not reconcile")
	details = usage.get("input_tokens_details") or {}
	cached = details.get("cached_tokens")
	write = details.get("cache_write_tokens")
	cache_known = cached is not None and write is not None
	if cache_known:
		cached = _tokens(cached, "cached_tokens")
		write = _tokens(write, "cache_write_tokens")
		if cached + write > input_tokens:
			raise ValueError("Cache token subdivisions exceed total input")
		input_cost = (
			(input_tokens - cached - write) * prices["input_usd_per_million"]
			+ cached * prices["cached_read_usd_per_million"]
			+ write * prices["cache_write_usd_per_million"]
		)
	else:
		input_cost = input_tokens * max(
			prices[key]
			for key in (
				"input_usd_per_million",
				"cached_read_usd_per_million",
				"cache_write_usd_per_million",
			)
		)
	reasoning = (usage.get("output_tokens_details") or {}).get("reasoning_tokens")
	if reasoning is not None and _tokens(reasoning, "reasoning_tokens") > output_tokens:
		raise ValueError("Reasoning tokens exceed total output")
	usd = (
		(input_cost + output_tokens * prices["output_usd_per_million"])
		/ 1_000_000
		* prices["endpoint_uplift"]
	)
	return {
		"priced_usd": usd,
		"priced_eur": usd / prices["usd_per_eur"],
		"cache_subdivision_known": cache_known,
		"basis": "reported_usage_dated_prices"
		if cache_known
		else "reported_usage_conservative_cache_upper_estimate",
	}


def initialize_budget(
	path: Path, *, ceiling_eur: float, final_review_reserve_eur: float, prices: dict
) -> dict:
	_number(ceiling_eur, "ceiling_eur", positive=True)
	_number(final_review_reserve_eur, "final_review_reserve_eur", positive=True)
	if final_review_reserve_eur >= ceiling_eur:
		raise ValueError("Final review reserve must leave task capacity")
	if path.exists():
		raise ValueError("Existing budget must be resumed; never reset automatically")
	state = {
		"version": 1,
		"ceiling_eur": ceiling_eur,
		"final_review_reserve_eur": final_review_reserve_eur,
		"prices": prices,
		"calls": [],
		"admission_locked": False,
	}
	_write(path, state)
	return state


def reserve_call(
	path: Path,
	*,
	call_id: str,
	task_id: str,
	request: dict,
	endpoint_host: str,
	final_review: bool = False,
	prices: dict | None = None,
	today: date | None = None,
) -> dict:
	"""Persist before dispatch. One serial application owns this ledger."""
	state = json.loads(path.read_text(encoding="utf-8"))
	if state["admission_locked"]:
		raise ValueError("Admission locked after a reservation overrun")
	if (
		not call_id
		or not task_id
		or any(call["call_id"] == call_id for call in state["calls"])
	):
		raise ValueError("Each dispatched attempt needs a unique call/task identity")
	admitted_prices = state["prices"] if prices is None else prices
	if (
		endpoint_host != state["prices"]["endpoint_host"]
		or endpoint_host != admitted_prices["endpoint_host"]
	):
		raise ValueError("Endpoint does not match the dated pricing configuration")
	item = reservation(request, admitted_prices, today=today)
	committed = sum(
		call.get("cost", {}).get("priced_eur", call["reserved_eur"])
		for call in state["calls"]
	)
	protected = 0 if final_review else state["final_review_reserve_eur"]
	if item["reserved_eur"] + committed + protected > state["ceiling_eur"]:
		raise ValueError(
			"BUDGET_EXHAUSTED: candidate cannot fit the remaining allowance"
		)
	item.update(
		{
			"call_id": call_id,
			"task_id": task_id,
			"final_review": final_review,
			"price_snapshot": admitted_prices,
			"status": "reserved",
			"events": [{"status": "reserved"}],
		}
	)
	state["calls"].append(item)
	_write(path, state)
	return item


def record_outcome(
	path: Path,
	*,
	call_id: str,
	usage: dict | None,
	elapsed_seconds: float,
	response_id: str | None = None,
	returned_model: str | None = None,
) -> dict:
	state = json.loads(path.read_text(encoding="utf-8"))
	call = next((item for item in state["calls"] if item["call_id"] == call_id), None)
	if call is None or call["status"] == "completed":
		raise ValueError("No unsettled reservation for this call")
	_number(elapsed_seconds, "elapsed_seconds")
	event = {
		"status": "usage_unknown",
		"usage": usage,
		"elapsed_seconds": elapsed_seconds,
		"response_id": response_id,
		"returned_model": returned_model,
	}
	if usage is not None:
		admitted_prices = call.get("price_snapshot", state["prices"])
		cost = price_usage(usage, admitted_prices)
		if returned_model != admitted_prices["model"]:
			raise ValueError("Returned model differs from the admitted price model")
		call["cost"] = cost
		event["status"] = "completed"
		if cost["priced_eur"] > call["reserved_eur"]:
			state["admission_locked"] = True
			event["reservation_exceeded"] = True
	call.update({"status": event["status"], "latest_outcome": event})
	call["events"].append(event)
	_write(path, state)
	return call
