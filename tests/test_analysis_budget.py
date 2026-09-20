import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from smrik_fund.analysis_budget import (
	content_hash,
	initialize_budget,
	price_usage,
	record_outcome,
	reservation,
	reserve_call,
)


class AnalysisBudgetTests(unittest.TestCase):
	def setUp(self):
		self.temporary = tempfile.TemporaryDirectory()
		self.addCleanup(self.temporary.cleanup)
		self.path = Path(self.temporary.name) / "budget.json"
		self.prices = json.loads(
			(Path(__file__).parents[1] / "docs/API_COST_SNAPSHOT.json").read_text()
		)
		self.today = date.fromisoformat(self.prices["observed_date"])
		self.request = {
			"model": "gpt-5.6-luna",
			"service_tier": "default",
			"input": "Financial evidence: €1.3bn",
			"max_output_tokens": 2000,
			"text": {
				"format": {
					"type": "json_schema",
					"name": "decision",
					"schema": {"type": "object"},
				}
			},
		}
		self.usage = {
			"input_tokens": 1000,
			"input_tokens_details": {"cached_tokens": 200, "cache_write_tokens": 300},
			"output_tokens": 100,
			"output_tokens_details": {"reasoning_tokens": 60},
			"total_tokens": 1100,
		}

	def initialize(self, ceiling=5.0, review=0.5):
		return initialize_budget(
			self.path,
			ceiling_eur=ceiling,
			final_review_reserve_eur=review,
			prices=self.prices,
		)

	def reserve(self, call_id="one", **kwargs):
		return reserve_call(
			self.path,
			call_id=call_id,
			task_id="capex",
			request=self.request,
			endpoint_host="api.openai.com",
			today=self.today,
			**kwargs,
		)

	def test_cache_subdivisions_and_reasoning_charged_once(self):
		cost = price_usage(self.usage, self.prices)
		self.assertAlmostEqual(cost["priced_usd"], 0.000299)
		self.assertAlmostEqual(cost["priced_eur"], 0.000299 / 1.1622)
		self.assertTrue(cost["cache_subdivision_known"])

	def test_provider_token_count_is_bound_and_reserves_full_output(self):
		count = {"request_hash": content_hash(self.request), "input_tokens": 1500}
		result = reservation(
			self.request, self.prices, today=self.today, token_count=count
		)
		self.assertEqual(
			result["input_token_upper_bound"],
			1500 + self.prices["input_wrapper_allowance_tokens"],
		)
		self.assertEqual(result["output_token_cap"], 2000)
		for invalid in (
			{**count, "request_hash": "wrong"},
			{**count, "input_tokens": -1},
			{**count, "input_tokens": 9999999},
		):
			with self.assertRaises(ValueError):
				reservation(
					self.request, self.prices, today=self.today, token_count=invalid
				)

	def test_model_specific_prices_preserve_legacy_holds_and_shared_budget(self):
		self.initialize()
		self.reserve("legacy")
		state = json.loads(self.path.read_text())
		state["calls"][0].pop("price_snapshot")  # Existing saved ledger format.
		self.path.write_text(json.dumps(state))
		legacy = state["calls"][0]
		sol_prices = {
			**self.prices,
			"snapshot_id": "sol-test",
			"model": "gpt-5.6-sol",
			"input_usd_per_million": 4.0,
			"cached_read_usd_per_million": 0.4,
			"cache_write_usd_per_million": 5.0,
			"output_usd_per_million": 20.0,
		}
		reserve_call(
			self.path,
			call_id="sol",
			task_id="whole-model-review",
			request={**self.request, "model": "gpt-5.6-sol"},
			endpoint_host="api.openai.com",
			final_review=True,
			prices=sol_prices,
			today=self.today,
		)
		state = json.loads(self.path.read_text())
		self.assertEqual(state["prices"], self.prices)
		self.assertEqual(state["calls"][0], legacy)
		self.assertEqual(state["ceiling_eur"], 5.0)
		self.assertEqual(state["final_review_reserve_eur"], 0.5)
		for call_id, model, expected_usd in [
			("legacy", "gpt-5.6-luna", 0.000299),
			("sol", "gpt-5.6-sol", 0.00558),
		]:
			settled = record_outcome(
				self.path,
				call_id=call_id,
				usage=self.usage,
				elapsed_seconds=1,
				returned_model=model,
			)
			self.assertAlmostEqual(settled["cost"]["priced_usd"], expected_usd)

	def test_late_outcome_uses_admitted_rates_after_price_refresh(self):
		self.initialize()
		self.reserve()
		state = json.loads(self.path.read_text())
		state["prices"]["output_usd_per_million"] *= 10
		self.path.write_text(json.dumps(state))
		settled = record_outcome(
			self.path,
			call_id="one",
			usage=self.usage,
			elapsed_seconds=1,
			returned_model="gpt-5.6-luna",
		)
		self.assertAlmostEqual(settled["cost"]["priced_usd"], 0.000299)

	def test_unknown_cache_is_explicit_upper_estimate(self):
		cost = price_usage(
			{**self.usage, "input_tokens_details": {"cached_tokens": 200}}, self.prices
		)
		self.assertAlmostEqual(cost["priced_usd"], 0.000370)
		self.assertFalse(cost["cache_subdivision_known"])

	def test_inconsistent_usage_keeps_reservation(self):
		self.initialize()
		self.reserve()
		before = self.path.read_bytes()
		for changes in [
			{"total_tokens": 999},
			{"input_tokens_details": {"cached_tokens": 900, "cache_write_tokens": 200}},
			{"output_tokens_details": {"reasoning_tokens": 101}},
		]:
			with self.subTest(changes=changes), self.assertRaises(ValueError):
				record_outcome(
					self.path,
					call_id="one",
					usage={**self.usage, **changes},
					elapsed_seconds=1,
					returned_model="gpt-5.6-luna",
				)
			self.assertEqual(self.path.read_bytes(), before)

	def test_final_review_capacity_and_restart(self):
		amount = reservation(self.request, self.prices, today=self.today)[
			"reserved_eur"
		]
		self.initialize(ceiling=amount * 1.5, review=amount * 0.75)
		before = self.path.read_bytes()
		with self.assertRaisesRegex(ValueError, "BUDGET_EXHAUSTED"):
			self.reserve()
		self.assertEqual(self.path.read_bytes(), before)
		self.reserve(final_review=True)
		with self.assertRaises(ValueError):
			self.initialize()
		with self.assertRaisesRegex(ValueError, "BUDGET_EXHAUSTED"):
			self.reserve("second", final_review=True)

	def test_unknown_usage_stays_reserved_and_attempt_id_unique(self):
		amount = reservation(self.request, self.prices, today=self.today)[
			"reserved_eur"
		]
		self.initialize(ceiling=amount * 1.5, review=amount * 0.1)
		reserved = self.reserve()
		outcome = record_outcome(
			self.path, call_id="one", usage=None, elapsed_seconds=20
		)
		self.assertEqual(outcome["reserved_eur"], reserved["reserved_eur"])
		self.assertEqual(outcome["status"], "usage_unknown")
		with self.assertRaisesRegex(ValueError, "unique"):
			self.reserve()
		with self.assertRaisesRegex(ValueError, "BUDGET_EXHAUSTED"):
			self.reserve("retry")

	def test_success_preserves_events_and_settles_once(self):
		self.initialize()
		self.reserve()
		result = record_outcome(
			self.path,
			call_id="one",
			usage=self.usage,
			elapsed_seconds=3,
			response_id="response-test",
			returned_model="gpt-5.6-luna",
		)
		self.assertEqual(
			[event["status"] for event in result["events"]], ["reserved", "completed"]
		)
		self.assertEqual(result["latest_outcome"]["usage"], self.usage)
		with self.assertRaises(ValueError):
			record_outcome(
				self.path, call_id="one", usage=self.usage, elapsed_seconds=3
			)

	def test_failed_atomic_write_preserves_ledger(self):
		self.initialize()
		before = self.path.read_bytes()
		with (
			patch(
				"smrik_fund.analysis_budget.os.replace",
				side_effect=OSError("write failed"),
			),
			self.assertRaises(OSError),
		):
			self.reserve()
		self.assertEqual(self.path.read_bytes(), before)
		self.assertEqual(list(self.path.parent.iterdir()), [self.path])

	def test_hash_covers_schema_and_input_and_modes_are_bounded(self):
		self.assertNotEqual(
			content_hash(self.request),
			content_hash({**self.request, "text": {"format": "changed"}}),
		)
		self.assertNotEqual(
			content_hash(self.request),
			content_hash({**self.request, "input": "new source"}),
		)
		for changes in [
			{"model": "different"},
			{"service_tier": "auto"},
			{"tools": [{"type": "web_search"}]},
			{"input": [{"type": "input_image"}]},
			{"max_output_tokens": None},
			{"input": "x" * 272000},
		]:
			with self.subTest(changes=changes), self.assertRaises(ValueError):
				reservation({**self.request, **changes}, self.prices, today=self.today)
		with self.assertRaisesRegex(ValueError, "not current"):
			reservation(
				self.request,
				self.prices,
				today=date.fromisoformat(self.prices["valid_through"])
				+ timedelta(days=1),
			)

	def test_overrun_locks_further_admission(self):
		self.initialize()
		self.reserve()
		usage = {"input_tokens": 1000000, "output_tokens": 0, "total_tokens": 1000000}
		outcome = record_outcome(
			self.path,
			call_id="one",
			usage=usage,
			elapsed_seconds=1,
			returned_model="gpt-5.6-luna",
		)
		self.assertTrue(outcome["latest_outcome"]["reservation_exceeded"])
		with self.assertRaisesRegex(ValueError, "locked"):
			self.reserve("second")


if __name__ == "__main__":
	unittest.main()
