from __future__ import annotations

from unittest import TestCase

from smrik_fund.ingestion.adjustment_analysis import AnalystCandidate
from smrik_fund.ingestion.reviewer import ReviewResult
from smrik_fund.ingestion.risk_gate import (
	RiskGateConditions,
	evaluate_risk_gate,
)

PERIOD = "2026-06-30 (FY)"


def candidate(
	*,
	amount: float | None = 100.0,
	effect: str | None = "increased_line",
	basis: str = "disclosed",
) -> AnalystCandidate:
	return AnalystCandidate(
		target_line="Research and development",
		period=PERIOD,
		item_amount=amount,
		item_effect_on_line=effect,
		amount_basis=basis,
		reason="Supported candidate.",
		evidence_refs=["E1"],
	)


def review(
	*,
	verdict: str = "accept",
	strength: str = "strong",
	basis: str = "disclosed",
	judgment: str = "low",
	calculation_valid: bool | None = None,
	target_valid: bool = True,
	period_valid: bool | None = True,
	effect: str | None = "increased_line",
	suggested_amount: float | None = None,
) -> ReviewResult:
	return ReviewResult(
		verdict=verdict,
		evidence_strength=strength,
		amount_basis=basis,
		judgment_level=judgment,
		calculation_valid=calculation_valid,
		target_valid=target_valid,
		item_effect_on_line=effect,
		period_valid=period_valid,
		concerns=[],
		suggested_amount=suggested_amount,
	)


def eligible_conditions() -> RiskGateConditions:
	return RiskGateConditions(
		materiality_eligible=True,
		normalization_eligible=True,
		reconciliation_clear=True,
		possible_duplicate=False,
		group_reconciles=True,
		aggregate_over_adjustment=False,
		source_target_available=True,
		individual_over_adjustment=False,
		zero_target_with_line_delta=False,
		deterministic_checks_pass=True,
	)


class NormalizationEligibilityTests(TestCase):
	def test_failed_or_unknown_normalization_eligibility_blocks(self) -> None:
		for value in (False, None):
			with self.subTest(normalization_eligible=value):
				conditions = RiskGateConditions(
					**{
						**eligible_conditions().__dict__,
						"normalization_eligible": value,
					}
				)
				result = evaluate_risk_gate(
					candidate(), review(), conditions
				)
				self.assertTrue(result.requires_human_review)
				self.assertIn(
					"normalization_eligibility_failed_or_unknown",
					result.reasons,
				)


class RiskGateTests(TestCase):
	def test_fully_eligible_candidate_is_auto_approved(self) -> None:
		result = evaluate_risk_gate(candidate(), review(), eligible_conditions())

		self.assertEqual(result.decision, "auto_approve")
		self.assertTrue(result.eligible_for_auto_approval)
		self.assertFalse(result.requires_human_review)
		self.assertEqual(result.reasons, ())

	def test_reviewer_revise_and_reject_require_human_review(self) -> None:
		for verdict in ("revise", "reject"):
			with self.subTest(verdict=verdict):
				result = evaluate_risk_gate(
					candidate(), review(verdict=verdict), eligible_conditions()
				)
				self.assertEqual(result.decision, "human_review")
				self.assertIn(f"reviewer_verdict_{verdict}", result.reasons)

	def test_null_amount_and_estimated_or_unknown_basis_fail_closed(self) -> None:
		for amount, basis in ((None, "unknown"), (100.0, "estimated")):
			with self.subTest(amount=amount, basis=basis):
				result = evaluate_risk_gate(
					candidate(amount=amount, basis=basis),
					review(basis=basis),
					eligible_conditions(),
				)
				self.assertTrue(result.requires_human_review)
				self.assertIn(
					"analyst_amount_basis_not_auto_approvable", result.reasons
				)
				self.assertIn(
					"reviewer_amount_basis_not_auto_approvable", result.reasons
				)
		result = evaluate_risk_gate(
			candidate(amount=None), review(basis="unknown"), eligible_conditions()
		)
		self.assertIn("item_amount_missing", result.reasons)

	def test_non_positive_item_amount_requires_human_review(self) -> None:
		for amount in (-100.0, 0.0):
			with self.subTest(amount=amount):
				result = evaluate_risk_gate(
					candidate(amount=amount), review(), eligible_conditions()
				)
				self.assertTrue(result.requires_human_review)
				self.assertIn("item_amount_not_positive", result.reasons)

	def test_amount_without_direction_cannot_derive_delta(self) -> None:
		result = evaluate_risk_gate(
			candidate(effect=None), review(effect=None), eligible_conditions()
		)

		self.assertTrue(result.requires_human_review)
		self.assertIn("line_delta_underived", result.reasons)

	def test_analyst_reviewer_effect_disagreement_fails_closed(self) -> None:
		result = evaluate_risk_gate(
			candidate(effect="decreased_line"),
			review(effect="increased_line"),
			eligible_conditions(),
		)

		self.assertTrue(result.requires_human_review)
		self.assertIn("item_effect_disagreement", result.reasons)

	def test_missing_reviewer_effect_fails_closed(self) -> None:
		result = evaluate_risk_gate(
			candidate(effect="increased_line"),
			review(effect=None),
			eligible_conditions(),
		)

		self.assertTrue(result.requires_human_review)
		self.assertIn("item_effect_disagreement", result.reasons)

	def test_matching_effect_direction_is_auto_approvable(self) -> None:
		result = evaluate_risk_gate(
			candidate(effect="decreased_line"),
			review(effect="decreased_line"),
			eligible_conditions(),
		)

		self.assertEqual(result.decision, "auto_approve")

	def test_dangerous_31bn_fixture_stays_human_review(self) -> None:
		result = evaluate_risk_gate(
			candidate(amount=3_100_000_000.0, basis="disclosed"),
			review(
				verdict="revise",
				basis="unknown",
				judgment="high",
				suggested_amount=None,
			),
			eligible_conditions(),
		)

		self.assertTrue(result.requires_human_review)
		self.assertIn("reviewer_verdict_revise", result.reasons)
		self.assertIn("reviewer_amount_basis_not_auto_approvable", result.reasons)
		self.assertIn("amount_basis_disagreement", result.reasons)

	def test_calculated_requires_valid_calculation_but_disclosed_does_not(self) -> None:
		calculated = evaluate_risk_gate(
			candidate(basis="calculated"),
			review(basis="calculated", calculation_valid=None),
			eligible_conditions(),
		)
		self.assertIn("calculation_invalid_or_unknown", calculated.reasons)

		disclosed = evaluate_risk_gate(
			candidate(basis="disclosed"),
			review(basis="disclosed", calculation_valid=False),
			eligible_conditions(),
		)
		self.assertTrue(disclosed.eligible_for_auto_approval)

	def test_each_reviewer_signal_blocks(self) -> None:
		cases = (
			("weak evidence", review(strength="weak"), "evidence_strength_not_strong"),
			("judgment", review(judgment="medium"), "judgment_level_not_low"),
			("target", review(target_valid=False), "target_invalid_or_unknown"),
			("period", review(period_valid=None), "period_invalid_or_unknown"),
		)
		for name, reviewed, reason in cases:
			with self.subTest(name=name):
				result = evaluate_risk_gate(
					candidate(), reviewed, eligible_conditions()
				)
				self.assertIn(reason, result.reasons)

	def test_each_mechanical_failure_and_unknown_blocks(self) -> None:
		cases = (
			(
				"materiality",
				{"materiality_eligible": False},
				"materiality_failed_or_unknown",
			),
			(
				"materiality unknown",
				{"materiality_eligible": None},
				"materiality_failed_or_unknown",
			),
			(
				"reconciliation",
				{"reconciliation_clear": False},
				"reconciliation_unresolved_or_unknown",
			),
			(
				"duplicate",
				{"possible_duplicate": True},
				"possible_duplicate_or_unknown",
			),
			(
				"group",
				{"group_reconciles": False},
				"group_reconciliation_failed_or_unknown",
			),
			(
				"aggregate",
				{"aggregate_over_adjustment": True},
				"aggregate_over_adjustment_or_unknown",
			),
			(
				"target missing",
				{"source_target_available": False},
				"source_target_missing_or_unknown",
			),
			(
				"individual over-adjustment",
				{"individual_over_adjustment": True},
				"individual_over_adjustment_or_unknown",
			),
			(
				"zero target with delta",
				{"zero_target_with_line_delta": True},
				"zero_target_with_line_delta_or_unknown",
			),
			(
				"deterministic",
				{"deterministic_checks_pass": False},
				"deterministic_checks_failed_or_unknown",
			),
		)
		for name, changes, reason in cases:
			with self.subTest(name=name):
				conditions = eligible_conditions()
				for field, value in changes.items():
					conditions = RiskGateConditions(
						**{**conditions.__dict__, field: value}
					)
				result = evaluate_risk_gate(candidate(), review(), conditions)
				self.assertTrue(result.requires_human_review)
				self.assertIn(reason, result.reasons)

	def test_unknown_required_conditions_fail_closed(self) -> None:
		result = evaluate_risk_gate(candidate(), review(), RiskGateConditions())

		self.assertTrue(result.requires_human_review)
		self.assertIn("materiality_failed_or_unknown", result.reasons)
		self.assertIn("deterministic_checks_failed_or_unknown", result.reasons)
