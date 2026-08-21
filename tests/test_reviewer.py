from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

import pandas as pd
from pydantic import ValidationError

from smrik_fund.ingestion.adjustment_analysis import AnalystCandidate
from smrik_fund.ingestion.reviewer import (
	ReviewerError,
	ReviewResult,
	run_reviewer,
	save_reviewer_result,
)

PERIOD = "2026-06-30 (FY)"
EVIDENCE_PACKET = """# MSFT operating-expense evidence

### E1
Source: MSFT 2026 10-K
Section: MD&A / Operating expenses
Locator: line 1266

> Operating expenses increased $940 million driven by impairment and other
> related expenses in our XBOX business.

### E2
Source: MSFT 2026 10-K
Section: MD&A / Operating expenses / Research and Development
Locator: line 1283

> Research and development expenses increased $3.1 billion, driven in part
> by impairment and other related expenses in our XBOX business.
"""


def make_pnl() -> pd.DataFrame:
	return pd.DataFrame(
		{
			"concept": [
				"us-gaap_Revenue",
				"us-gaap_ResearchAndDevelopmentExpense",
				"us-gaap_OperatingIncomeLoss",
			],
			"label": [
				"Revenue",
				"Research and development",
				"Operating income",
			],
			"standard_concept": [
				"Revenue",
				"ResearchAndDevelopmentExpenses",
				"OperatingIncomeLoss",
			],
			PERIOD: [300_000.0, 35_000.0, 100_000.0],
		}
	)


def xbox_candidate(
	*,
	amount: float | None = None,
	amount_basis: str = "unknown",
	period: str = PERIOD,
	target_line: str = "Research and development",
	evidence_refs: list[str] | None = None,
) -> AnalystCandidate:
	return AnalystCandidate(
		target_line=target_line,
		sub_item="XBOX impairment and other related expenses",
		period=period,
		adjustment_amount=amount,
		amount_basis=amount_basis,
		reason="The filing identifies an Xbox impairment-related item.",
		evidence_refs=evidence_refs or ["E1", "E2"],
		uncertainty="The amount is not separately disclosed.",
	)


def fake_client(result: ReviewResult) -> Mock:
	client = Mock()
	client.responses.parse.return_value = SimpleNamespace(output_parsed=result)
	return client


def accepted_xbox_result() -> ReviewResult:
	return ReviewResult(
		verdict="accept",
		evidence_strength="strong",
		amount_basis="unknown",
		judgment_level="medium",
		calculation_valid=None,
		target_valid=True,
		period_valid=True,
		concerns=["The filing does not separately disclose the Xbox amount."],
		note="Candidate identification is supported; amount remains unresolved.",
	)


class ReviewerInputTests(TestCase):
	def test_valid_xbox_null_amount_is_preserved_and_reviewed(self) -> None:
		candidate = xbox_candidate()
		client = fake_client(accepted_xbox_result())

		result, metadata = run_reviewer(
			" msft ",
			make_pnl(),
			candidate,
			EVIDENCE_PACKET,
			client=client,
			model="test-model",
			reasoning_effort="low",
			evidence_ref="restructuring.md",
			run_id="run-1",
		)

		self.assertEqual(result.verdict, "accept")
		self.assertIsNone(candidate.adjustment_amount)
		self.assertEqual(result.amount_basis, "unknown")
		self.assertIsNone(result.calculation_valid)
		self.assertEqual(metadata["ticker"], "MSFT")
		self.assertEqual(metadata["run_id"], "run-1")
		client.responses.parse.assert_called_once()

	def test_payload_contains_only_one_candidate_and_supplied_context(self) -> None:
		pnl = make_pnl()
		pnl.loc[1, PERIOD] = float("nan")
		candidate = xbox_candidate()
		client = fake_client(accepted_xbox_result())

		run_reviewer("MSFT", pnl, candidate, EVIDENCE_PACKET, client=client)

		call = client.responses.parse.call_args
		self.assertEqual(call.kwargs["text_format"], ReviewResult)
		self.assertEqual(call.kwargs["reasoning"], {"effort": "high"})
		self.assertEqual(len(call.kwargs["input"]), 2)
		payload = json.loads(call.kwargs["input"][1]["content"])
		self.assertEqual(
			set(payload), {"ticker", "candidate", "pnl", "evidence_packet"}
		)
		self.assertEqual(payload["ticker"], "MSFT")
		self.assertEqual(payload["candidate"], candidate.model_dump(mode="json"))
		self.assertEqual(payload["evidence_packet"], EVIDENCE_PACKET)
		self.assertIsNone(payload["pnl"][1][PERIOD])
		self.assertNotIn("NaN", call.kwargs["input"][1]["content"])
		system_prompt = call.kwargs["input"][0]["content"].casefold()
		for frozen_fact in ("msft", "e2", "$3.1 billion", "xbox"):
			with self.subTest(frozen_fact=frozen_fact):
				self.assertNotIn(frozen_fact, system_prompt)

	def test_unknown_evidence_reference_fails_before_client_call(self) -> None:
		candidate = xbox_candidate(evidence_refs=["E99"])
		client = Mock()

		with self.assertRaisesRegex(ReviewerError, "E99"):
			run_reviewer("MSFT", make_pnl(), candidate, EVIDENCE_PACKET, client=client)

		client.responses.parse.assert_not_called()


class ReviewerJudgmentContractTests(TestCase):
	def test_fabricated_31bn_amount_is_non_accepting_with_attribution_flaw(
		self,
	) -> None:
		candidate = xbox_candidate(amount=3_100_000_000.0, amount_basis="disclosed")
		result = ReviewResult(
			verdict="revise",
			evidence_strength="weak",
			amount_basis="unknown",
			judgment_level="high",
			calculation_valid=False,
			target_valid=True,
			period_valid=True,
			concerns=[
				"$3.1bn is the total R&D increase, not a separately supported Xbox amount."
			],
		)

		reviewed, _ = run_reviewer(
			"MSFT", make_pnl(), candidate, EVIDENCE_PACKET, client=fake_client(result)
		)

		self.assertIn(reviewed.verdict, {"revise", "reject"})
		self.assertTrue(
			any("total R&D increase" in concern for concern in reviewed.concerns)
		)
		self.assertIsNone(reviewed.suggested_amount)

	def test_wrong_target_period_and_basis_are_non_accepting(self) -> None:
		cases = [
			(
				xbox_candidate(target_line="Xbox impairment"),
				ReviewResult(
					verdict="reject",
					evidence_strength="weak",
					amount_basis="unknown",
					judgment_level="high",
					calculation_valid=None,
					target_valid=False,
					period_valid=True,
					concerns=["Target is not an exact supplied P&L line."],
				),
			),
			(
				xbox_candidate(period="2025-06-30 (FY)"),
				ReviewResult(
					verdict="revise",
					evidence_strength="medium",
					amount_basis="unknown",
					judgment_level="high",
					calculation_valid=None,
					target_valid=True,
					period_valid=False,
					concerns=["Candidate period is absent from supplied P&L."],
				),
			),
			(
				xbox_candidate(amount=100.0, amount_basis="calculated"),
				ReviewResult(
					verdict="reject",
					evidence_strength="weak",
					amount_basis="unknown",
					judgment_level="high",
					calculation_valid=False,
					target_valid=True,
					period_valid=True,
					concerns=[
						"The supplied evidence does not support a calculated amount."
					],
				),
			),
		]

		for candidate, expected in cases:
			with self.subTest(candidate=candidate):
				result, _ = run_reviewer(
					"MSFT",
					make_pnl(),
					candidate,
					EVIDENCE_PACKET,
					client=fake_client(expected),
				)
				self.assertIn(result.verdict, {"revise", "reject"})
				self.assertTrue(result.concerns)

	def test_review_schema_forbids_unknown_fields_and_preserves_nulls(self) -> None:
		with self.assertRaises(ValidationError):
			ReviewResult.model_validate(
				{
					"verdict": "accept",
					"evidence_strength": "strong",
					"amount_basis": "unknown",
					"judgment_level": "medium",
					"calculation_valid": None,
					"target_valid": True,
					"period_valid": True,
					"concerns": [],
					"status": "approved",
				}
			)

		result = accepted_xbox_result()
		round_trip = ReviewResult.model_validate(result.model_dump(mode="json"))
		self.assertIsNone(round_trip.calculation_valid)
		self.assertIsNone(round_trip.suggested_amount)


class ReviewerPersistenceTests(TestCase):
	def test_persistence_keeps_candidate_result_metadata_and_required_path(
		self,
	) -> None:
		candidate = xbox_candidate()
		result = accepted_xbox_result()
		metadata = {
			"ticker": "MSFT",
			"model": "test-model",
			"reasoning_effort": "high",
			"prompt_version": "reviewer-v1",
			"schema_version": "reviewer-result-v1",
			"evidence_ref": "restructuring.md",
			"run_id": "run-1",
		}

		with TemporaryDirectory() as temporary_directory:
			output_path = save_reviewer_result(
				" msft ", "A0001", candidate, result, metadata, temporary_directory
			)
			saved = json.loads(output_path.read_text(encoding="utf-8"))

		self.assertEqual(
			output_path,
			Path(temporary_directory)
			/ "MSFT"
			/ "03_output"
			/ "reviews"
			/ "A0001_run-1.json",
		)
		self.assertEqual(saved["metadata"], metadata)
		self.assertEqual(saved["candidate"], candidate.model_dump(mode="json"))
		self.assertIsNone(saved["candidate"]["adjustment_amount"])
		self.assertEqual(saved["result"], result.model_dump(mode="json"))
