import copy
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
from openai import OpenAI

from smrik_fund.analysis_budget import content_hash, initialize_budget
from smrik_fund.analysis_transport import dispatch_request


class AnalysisTransportTests(unittest.TestCase):
	def setUp(self):
		self.temporary = tempfile.TemporaryDirectory()
		self.addCleanup(self.temporary.cleanup)
		self.root = Path(self.temporary.name)
		self.ledger = self.root / "budget.json"
		self.prices = json.loads((Path(__file__).parents[1] / "data/build-guide-p10/parent-preflight/sol-price-snapshot.json").read_text())
		self.today = date.fromisoformat(self.prices["observed_date"])
		initialize_budget(self.ledger, ceiling_eur=5, final_review_reserve_eur=0.5, prices=self.prices)
		self.request = {
			"model": "gpt-5.6-sol", "reasoning": {"effort": "high"},
			"service_tier": "default", "input": "Frozen financial evidence",
			"max_output_tokens": 16000, "tools": [], "background": False,
			"text": {"format": {"type": "json_schema", "strict": True,
				"name": "test_review", "schema": {"type": "object", "additionalProperties": False,
					"required": ["value"], "properties": {"value": {"type": "number"}}}}},
		}
		self.raw = {
			"id": "response-test", "status": "completed", "model": "gpt-5.6-sol",
			"output": [{"type": "message", "content": [{"type": "output_text", "text": '{"value": 1}'}]}],
			"usage": {"input_tokens": 1000, "input_tokens_details": {"cached_tokens": 0},
				"output_tokens": 100, "output_tokens_details": {"reasoning_tokens": 50}, "total_tokens": 1100},
		}
		self.create = Mock(return_value=self.raw)
		self.client = SimpleNamespace(responses=SimpleNamespace(create=self.create))

	def dispatch(self, **kwargs):
		request = self.request
		if kwargs.get("stage") in {"analyst_correction", "independent_recheck"}:
			request = self.request | {"max_output_tokens": 8000}
		options = {"request": request, "run_dir": self.root / "run", "stage": "whole_model_review",
			"budget_path": self.ledger, "prices": self.prices, "final_review": True,
			"client": self.client, "today": self.today}
		return dispatch_request(**(options | kwargs))

	def calls(self):
		return json.loads(self.ledger.read_text())["calls"]

	def artifacts(self):
		return self.root / "build-guide-p10/calls" / content_hash(self.request)

	def test_full_raw_usage_and_replay_across_presentation_directories(self):
		value, metadata = self.dispatch()
		self.assertEqual(value, {"value": 1})
		self.assertFalse(metadata["resumed"])
		self.assertEqual(json.loads((self.artifacts() / "response.json").read_text()), self.raw)
		call = self.calls()[0]
		self.assertEqual(call["price_snapshot"], self.prices)
		self.assertEqual(call["latest_outcome"]["usage"], self.raw["usage"])
		self.assertGreater(call["cost"]["priced_eur"], 0)
		value, replay = self.dispatch(run_dir=self.root / "reexport")
		self.assertTrue(replay["resumed"])
		self.assertEqual(value, {"value": 1})
		self.assertEqual(self.create.call_count, 1)
		self.assertEqual(len(self.calls()), 1)

	def test_installed_sdk_response_is_captured_before_business_validation(self):
		captured = []

		def handle(request):
			captured.append(json.loads(request.content))
			return httpx.Response(200, json=self.raw, request=request)

		with (
			httpx.Client(transport=httpx.MockTransport(handle)) as http_client,
			OpenAI(api_key="dummy-local-key", base_url="http://mock/v1", http_client=http_client, max_retries=0) as client,
		):
			value, metadata = self.dispatch(client=client)
		self.assertEqual(value, {"value": 1})
		self.assertEqual(captured, [self.request])
		self.assertEqual(metadata["status"], "completed")
		saved = json.loads((self.artifacts() / "response.json").read_text())
		self.assertEqual(saved["id"], "response-test")
		self.assertEqual(saved["output"][0]["content"][0]["text"], '{"value": 1}')
		self.assertEqual(saved["usage"]["input_tokens"], 1000)

	def test_malformed_response_is_preserved_and_charged_before_parse(self):
		self.raw["output"][0]["content"][0]["text"] = "malformed JSON"
		with self.assertRaisesRegex(ValueError, "INVALID_PROVIDER_OUTPUT"):
			self.dispatch()
		self.assertEqual(self.calls()[0]["status"], "completed")
		self.assertEqual(json.loads((self.artifacts() / "response.json").read_text()), self.raw)
		with self.assertRaises(ValueError):
			self.dispatch()
		self.assertEqual(self.create.call_count, 1)

	def test_refusal_and_incomplete_are_not_analytical_outputs(self):
		for kind in ("refusal", "incomplete"):
			with self.subTest(kind=kind):
				request = {**self.request, "input": kind}
				raw = copy.deepcopy(self.raw)
				if kind == "refusal":
					raw["output"][0]["content"] = [{"type": "refusal", "refusal": "declined"}]
				else:
					raw["status"] = "incomplete"
				self.create.return_value = raw
				with self.assertRaisesRegex(ValueError, "INVALID_PROVIDER_OUTPUT"):
					self.dispatch(request=request)
		self.assertEqual([c["status"] for c in self.calls()], ["completed", "completed"])

	def test_transport_failure_holds_reservation_and_never_logs_secret_string(self):
		self.create.side_effect = RuntimeError("Authorization: SECRET-FIXTURE")
		with self.assertRaisesRegex(ValueError, "USAGE_UNKNOWN"):
			self.dispatch()
		self.assertEqual(self.calls()[0]["status"], "usage_unknown")
		with self.assertRaisesRegex(ValueError, "unsettled admission"):
			self.dispatch()
		self.assertEqual(self.create.call_count, 1)
		self.assertNotIn("SECRET-FIXTURE", "".join(p.read_text() for p in self.root.rglob("*.json")))

	def test_wrong_returned_model_preserves_raw_and_holds_unpriced_usage(self):
		self.raw["model"] = "unexpected-model"
		with self.assertRaisesRegex(ValueError, "USAGE_UNKNOWN"):
			self.dispatch()
		self.assertEqual(self.calls()[0]["status"], "usage_unknown")
		self.assertTrue((self.artifacts() / "response.json").exists())
		self.assertNotIn("cost", self.calls()[0])

	def test_different_returned_tier_cannot_use_standard_prices(self):
		self.raw["service_tier"] = "priority"
		with self.assertRaisesRegex(ValueError, "USAGE_UNKNOWN"):
			self.dispatch()
		self.assertEqual(self.calls()[0]["status"], "usage_unknown")
		self.assertNotIn("cost", self.calls()[0])

	def test_tampered_replay_rejected_without_new_call(self):
		self.dispatch()
		self.raw["output"][0]["content"][0]["text"] = '{"value": 999}'
		(self.artifacts() / "response.json").write_text(json.dumps(self.raw))
		with self.assertRaisesRegex(ValueError, "Replay artifacts differ"):
			self.dispatch()
		self.assertEqual(self.create.call_count, 1)

	def test_uncontrolled_settings_or_final_reserve_misuse_cannot_dispatch(self):
		for change in ({"tools": [{"type": "web_search"}]}, {"background": True},
			{"model": "another-model"}, {"previous_response_id": "hidden-context"}):
			with self.subTest(change=change), self.assertRaisesRegex(ValueError, "runtime settings"):
				self.dispatch(request=self.request | change)
		with self.assertRaisesRegex(ValueError, "ineligible"):
			self.dispatch(stage="analyst_correction")
		self.assertEqual(self.create.call_count, 0)
		self.assertEqual(self.calls(), [])

	def test_call_cap_counts_all_run_directories_and_preserves_prior_calls(self):
		for ordinal in range(4):
			self.dispatch(request=self.request | {"input": str(ordinal)}, run_dir=self.root / str(ordinal))
		before = self.ledger.read_bytes()
		with self.assertRaisesRegex(ValueError, "BUDGET_EXHAUSTED"):
			self.dispatch()
		self.assertEqual(self.create.call_count, 4)
		self.assertEqual(self.ledger.read_bytes(), before)

	def test_shared_final_review_reserve_and_p10_cost_cap_are_enforced(self):
		state = json.loads(self.ledger.read_text())
		state["ceiling_eur"] = 0.6
		self.ledger.write_text(json.dumps(state))
		with self.assertRaisesRegex(ValueError, "BUDGET_EXHAUSTED"):
			self.dispatch(stage="analyst_correction", final_review=False)
		self.assertEqual(self.create.call_count, 0)
		self.dispatch()  # Actual whole-model review may use the protected reserve.
		state = json.loads(self.ledger.read_text())
		state["ceiling_eur"] = 5
		state["calls"][0]["cost"]["priced_eur"] = 1.99
		self.ledger.write_text(json.dumps(state))
		with self.assertRaisesRegex(ValueError, "P10 call or committed-cost cap"):
			self.dispatch(request=self.request | {"input": "next-review"})
		self.assertEqual(self.create.call_count, 1)

	def test_p11_uses_shared_ledger_with_its_own_bounded_recheck_allowance(self):
		self.dispatch()  # Existing P10 charge stays recorded.
		for ordinal in range(2):
			request = self.request | {"input": f"P11 revision {ordinal}", "max_output_tokens": 8000}
			self.dispatch(request=request, package="p11", stage="independent_recheck", final_review=False)
		state = json.loads(self.ledger.read_text())
		self.assertEqual([call["task_id"] for call in state["calls"]], ["p10-msft-analysis", "p11-msft-revision", "p11-msft-revision"])
		with self.assertRaisesRegex(ValueError, "P11 call or committed-cost cap"):
			self.dispatch(request=self.request | {"input": "third revision", "max_output_tokens": 8000}, package="p11", stage="independent_recheck", final_review=False)
		with self.assertRaisesRegex(ValueError, "P11 only permits"):
			self.dispatch(package="p11")
		self.assertEqual(self.create.call_count, 3)
