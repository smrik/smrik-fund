"""Pure deterministic approval gate for one reviewed adjustment candidate."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from .adjustment_analysis import AnalystCandidate
from .reviewer import ReviewResult


@dataclass(frozen=True)
class RiskGateConditions:
	"""Precomputed mechanical facts required by the Task 9 gate.

	``None`` means that a required check was not run or cannot be established.
	The gate deliberately treats that state as unsafe for auto-approval.
	"""

	materiality_eligible: bool | None = None
	reconciliation_clear: bool | None = None
	possible_duplicate: bool | None = None
	group_reconciles: bool | None = None
	aggregate_over_adjustment: bool | None = None
	source_target_available: bool | None = None
	source_target_negative: bool | None = None
	individual_over_adjustment: bool | None = None
	zero_target_with_positive_adjustment: bool | None = None
	deterministic_checks_pass: bool | None = None


@dataclass(frozen=True)
class RiskGateResult:
	"""The explicit decision and ordered mechanical failure reasons."""

	decision: Literal["auto_approve", "human_review"]
	reasons: tuple[str, ...]

	@property
	def eligible_for_auto_approval(self) -> bool:
		return self.decision == "auto_approve"

	@property
	def requires_human_review(self) -> bool:
		return self.decision == "human_review"


def evaluate_risk_gate(
	candidate: AnalystCandidate,
	review: ReviewResult,
	conditions: RiskGateConditions,
) -> RiskGateResult:
	"""Evaluate the documented V1 auto-approval policy without model calls.

	The caller supplies all materiality, reconciliation, duplicate, group, and
	target-value facts. This function does not calculate those facts or infer a
	materiality threshold.
	"""

	if not isinstance(candidate, AnalystCandidate):
		raise TypeError("candidate must be an AnalystCandidate")
	if not isinstance(review, ReviewResult):
		raise TypeError("review must be a ReviewResult")
	if not isinstance(conditions, RiskGateConditions):
		raise TypeError("conditions must be RiskGateConditions")

	reasons: list[str] = []

	if review.verdict != "accept":
		reasons.append(f"reviewer_verdict_{review.verdict}")
	if review.evidence_strength != "strong":
		reasons.append("evidence_strength_not_strong")

	amount = candidate.adjustment_amount
	if amount is None:
		reasons.append("adjustment_amount_missing")
	else:
		try:
			amount_number = float(amount)
			amount_is_finite = math.isfinite(amount_number)
		except (TypeError, ValueError):
			amount_number = 0.0
			amount_is_finite = False
		if not amount_is_finite:
			reasons.append("adjustment_amount_not_finite")
		elif amount_number < 0:
			reasons.append("adjustment_amount_negative")

	allowed_basis = {"disclosed", "calculated"}
	if candidate.amount_basis not in allowed_basis:
		reasons.append("analyst_amount_basis_not_auto_approvable")
	if review.amount_basis not in allowed_basis:
		reasons.append("reviewer_amount_basis_not_auto_approvable")
	if candidate.amount_basis != review.amount_basis:
		reasons.append("amount_basis_disagreement")

	if review.judgment_level != "low":
		reasons.append("judgment_level_not_low")
	if review.target_valid is not True:
		reasons.append("target_invalid_or_unknown")
	if review.period_valid is not True:
		reasons.append("period_invalid_or_unknown")
	if candidate.amount_basis == "calculated" and review.calculation_valid is not True:
		reasons.append("calculation_invalid_or_unknown")

	if conditions.materiality_eligible is not True:
		reasons.append("materiality_failed_or_unknown")
	if conditions.reconciliation_clear is not True:
		reasons.append("reconciliation_unresolved_or_unknown")
	if conditions.possible_duplicate is not False:
		reasons.append("possible_duplicate_or_unknown")
	if conditions.group_reconciles is not True:
		reasons.append("group_reconciliation_failed_or_unknown")
	if conditions.aggregate_over_adjustment is not False:
		reasons.append("aggregate_over_adjustment_or_unknown")
	if conditions.source_target_available is not True:
		reasons.append("source_target_missing_or_unknown")
	if conditions.source_target_negative is not False:
		reasons.append("source_target_negative_or_unknown")
	if conditions.individual_over_adjustment is not False:
		reasons.append("individual_over_adjustment_or_unknown")
	if conditions.zero_target_with_positive_adjustment is not False:
		reasons.append("zero_target_positive_adjustment_or_unknown")
	if conditions.deterministic_checks_pass is not True:
		reasons.append("deterministic_checks_failed_or_unknown")

	return RiskGateResult(
		decision="human_review" if reasons else "auto_approve",
		reasons=tuple(reasons),
	)
