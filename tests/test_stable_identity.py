from __future__ import annotations

import json
from unittest import TestCase

import pandas as pd

from smrik_fund.ingestion.adjustment_analysis import AnalystCandidate
from smrik_fund.ingestion.adjustments import resolve_current_adjustments
from smrik_fund.ingestion.filing import FilingEvidenceError
from smrik_fund.main import (
	_candidate_identity,
	_candidate_state,
	_canonical_json,
	_gate_conditions,
	_history_identity_complete,
	_history_identity_lookup,
	_target_row_key,
)

PERIOD = "2025-06-30 (FY)"


def make_pnl() -> pd.DataFrame:
	return pd.DataFrame(
		{
			"concept": [
				"us-gaap_Revenue",
				"us-gaap_ResearchAndDevelopmentExpense",
				"us-gaap_SellingAndMarketingExpense",
				"us-gaap_GeneralAndAdministrativeExpense",
			],
			"label": [
				"Revenue",
				"Research and development",
				"Sales and marketing",
				"General and administrative",
			],
			"standard_concept": [
				"Revenue",
				"ResearchAndDevelopmentExpenses",
				"SellingGeneralAndAdminExpenses",
				"SellingGeneralAndAdminExpenses",
			],
			PERIOD: [1000.0, 100.0, 50.0, 50.0],
			"2024-06-30 (FY)": [900.0, 90.0, 45.0, 45.0],
		}
	)


def candidate(
	*,
	item_key: str | None = "xbox-impairment",
	target_line: str = "Research and development",
	period: str = PERIOD,
	amount: float | None = 900_000_000.0,
	sub_item: str | None = "Xbox impairment",
	reason: str = "Supported fixture.",
	evidence_refs: list[str] | None = None,
) -> AnalystCandidate:
	return AnalystCandidate(
		target_line=target_line,
		period=period,
		item_key=item_key,
		item_amount=amount,
		item_effect_on_line="increased_line",
		amount_basis="disclosed",
		sub_item=sub_item,
		reason=reason,
		evidence_refs=evidence_refs or ["E1"],
	)


def identity_for(value: AnalystCandidate, packet: object = None) -> str:
	return _candidate_identity("MSFT", make_pnl(), value, packet or {})


def history_row(value: AnalystCandidate, identity: str, *, status: str = "approved") -> dict[str, object]:
	identity_parts = json.loads(identity)
	return {
		"adjustment_id": "A0001",
		"version": 1,
		"status": status,
		"identity_version": "economic-adjustment-v2",
		"candidate_identity": identity,
		"candidate_state": _canonical_json(_candidate_state(value)),
		"target_row_key": identity_parts["target_row_key"],
		"target_line": value.target_line,
		"period": value.period,
		"item_amount": value.item_amount,
		"item_effect_on_line": value.item_effect_on_line,
	}


class StableEconomicIdentityTests(TestCase):
	def test_provenance_and_prose_drift_keep_identity(self) -> None:
		base = candidate()
		variants = (
			base.model_copy(update={"evidence_refs": ["E9"]}),
			base.model_copy(update={"sub_item": "Xbox asset charge"}),
			base.model_copy(update={"reason": "Reworded evidence explanation."}),
		)
		identity = identity_for(base, {"accession": "old", "query": "old"})
		for variant in variants:
			with self.subTest(variant=variant):
				self.assertEqual(
					identity,
					identity_for(variant, {"accession": "new", "query": "new"}),
				)

	def test_unique_standard_concept_survives_label_drift(self) -> None:
		base = make_pnl()
		renamed = base.copy()
		renamed.loc[
			renamed["standard_concept"] == "ResearchAndDevelopmentExpenses", "label"
		] = "Engineering"
		self.assertEqual(
			_target_row_key(base, "Research and development"),
			"standard_concept:ResearchAndDevelopmentExpenses",
		)
		self.assertEqual(
			_target_row_key(renamed, "Engineering"),
			"standard_concept:ResearchAndDevelopmentExpenses",
		)

	def test_duplicate_standard_concept_uses_label_metadata(self) -> None:
		self.assertEqual(
			_target_row_key(make_pnl(), "Sales and marketing"),
			"standard_concept:SellingGeneralAndAdminExpenses|label:Sales and marketing",
		)

	def test_missing_standard_concept_falls_back_to_unique_label(self) -> None:
		pnl = make_pnl().drop(columns=["standard_concept"])
		self.assertEqual(
			_target_row_key(pnl, "Research and development"),
			"label:Research and development",
		)

	def test_amount_drift_is_same_id_but_state_conflict_and_no_stack(self) -> None:
		v1 = candidate(amount=900_000_000.0)
		v2 = candidate(amount=1_100_000_000.0)
		identity = identity_for(v1)
		history = pd.DataFrame([history_row(v1, identity)])
		lookup = _history_identity_lookup(
			history, identity_for(v2), _canonical_json(_candidate_state(v2))
		)
		self.assertEqual(lookup["status"], "state_conflict")
		self.assertEqual(lookup["adjustment_id"], "A0001")
		self.assertEqual(lookup["version"], 1)

	def test_history_period_mismatch_fails_closed(self) -> None:
		value = candidate()
		row = history_row(value, identity_for(value))
		row["period"] = "2024-06-30 (FY)"
		history = pd.DataFrame([row])

		self.assertFalse(_history_identity_complete(history))
		with self.assertRaisesRegex(ValueError, "fail closed"):
			resolve_current_adjustments(history)

	def test_history_state_snapshot_mismatch_fails_closed(self) -> None:
		value = candidate()
		row = history_row(value, identity_for(value))
		row["candidate_state"] = _canonical_json(
			_candidate_state(value.model_copy(update={"item_amount": 999.0}))
		)
		history = pd.DataFrame([row])

		self.assertFalse(_history_identity_complete(history))
		with self.assertRaisesRegex(ValueError, "fail closed"):
			resolve_current_adjustments(history)

	def test_identity_assigned_to_two_ids_fails_closed_before_application(self) -> None:
		value = candidate()
		first = history_row(value, identity_for(value))
		second = dict(first)
		second["adjustment_id"] = "A0002"
		history = pd.DataFrame([first, second])

		self.assertFalse(_history_identity_complete(history))
		with self.assertRaisesRegex(ValueError, "fail closed"):
			resolve_current_adjustments(history)

	def test_first_valid_key_on_empty_row_period_mints(self) -> None:
		value = candidate()
		identity = identity_for(value)
		self.assertEqual(
			_history_identity_lookup(
				pd.DataFrame(), identity, _canonical_json(_candidate_state(value))
			)["status"],
			"new",
		)

	def test_null_key_is_unresolved(self) -> None:
		with self.assertRaisesRegex(FilingEvidenceError, "item_key"):
			identity_for(candidate(item_key=None))

	def test_generic_key_is_rejected_before_application(self) -> None:
		with self.assertRaisesRegex(FilingEvidenceError, "item_key"):
			identity_for(candidate(item_key="impairment"))

	def test_competing_key_on_occupied_row_is_unresolved_without_id(self) -> None:
		prior = candidate(item_key="xbox-impairment")
		prior_identity = identity_for(prior)
		history = pd.DataFrame([history_row(prior, prior_identity)])
		candidate_value = candidate(item_key="gaming-asset-impairment")
		before = history.copy(deep=True)
		lookup = _history_identity_lookup(
			history,
			identity_for(candidate_value),
			_canonical_json(_candidate_state(candidate_value)),
		)
		self.assertEqual(lookup["status"], "identity_unresolved")
		self.assertIsNone(lookup["adjustment_id"])
		pd.testing.assert_frame_equal(history, before)

	def test_aggregate_guard_uses_row_key_after_label_drift(self) -> None:
		base = make_pnl()
		renamed = base.copy()
		renamed.loc[
			renamed["standard_concept"] == "ResearchAndDevelopmentExpenses", "label"
		] = "Engineering"
		prior = candidate(
			item_key="prior-charge",
			target_line="Research and development",
			amount=80.0,
		)
		current = candidate(
			item_key="current-charge",
			target_line="Engineering",
			amount=30.0,
		)
		history = pd.DataFrame([history_row(prior, identity_for(prior))])
		identity = _candidate_identity("MSFT", renamed, current, {})

		conditions = _gate_conditions(
			renamed,
			current,
			pd.DataFrame({"status": ["PASS"]}),
			history=history,
			candidate_identity=identity,
			identity_status="identity_unresolved",
			materiality_passed=True,
		)

		self.assertTrue(conditions.aggregate_over_adjustment)

	def test_litigation_and_restructuring_keys_do_not_merge(self) -> None:
		prior = candidate(item_key="litigation-settlement")
		history = pd.DataFrame([history_row(prior, identity_for(prior))])
		competing = candidate(item_key="restructuring-charge")
		lookup = _history_identity_lookup(
			history,
			identity_for(competing),
			_canonical_json(_candidate_state(competing)),
		)
		self.assertEqual(lookup["status"], "identity_unresolved")

	def test_same_key_different_period_or_target_is_different_identity(self) -> None:
		base = candidate()
		other_period = candidate(period="2024-06-30 (FY)")
		other_target = candidate(target_line="Sales and marketing")
		self.assertNotEqual(identity_for(base), identity_for(other_period))
		self.assertNotEqual(identity_for(base), identity_for(other_target))

	def test_same_item_key_with_selector_evolution_fails_closed(self) -> None:
		value = candidate()
		identity = identity_for(value)
		history = pd.DataFrame([history_row(value, identity)])
		changed = json.loads(identity)
		changed["target_row_key"] = "label:Research and development"

		lookup = _history_identity_lookup(
			history,
			_canonical_json(changed),
			_canonical_json(_candidate_state(value)),
		)

		self.assertEqual(lookup["status"], "identity_unresolved")
		self.assertIsNone(lookup["adjustment_id"])

	def test_qualified_selector_drift_with_competing_key_fails_closed(self) -> None:
		prior = candidate(
			item_key="marketing-restructuring",
			target_line="Sales and marketing",
		)
		prior_identity = identity_for(prior)
		history = pd.DataFrame([history_row(prior, prior_identity)])
		changed = json.loads(prior_identity)
		changed["target_row_key"] = (
			"standard_concept:SellingGeneralAndAdminExpenses|label:Marketing"
		)
		changed["item_key"] = "marketing-asset-impairment"

		lookup = _history_identity_lookup(
			history,
			_canonical_json(changed),
			_canonical_json(_candidate_state(prior)),
		)

		self.assertEqual(lookup["status"], "identity_unresolved")
		self.assertIsNone(lookup["adjustment_id"])

	def test_noncanonical_company_case_fails_closed(self) -> None:
		value = candidate()
		identity = json.loads(identity_for(value))
		identity["company"] = "msft"
		history = pd.DataFrame(
			[history_row(value, _canonical_json(identity), status="proposed")]
		)

		self.assertFalse(_history_identity_complete(history))
		self.assertEqual(
			_history_identity_lookup(
				history,
				identity_for(value),
				_canonical_json(_candidate_state(value)),
			)["status"],
			"identity_unresolved",
		)

	def test_legacy_history_fails_closed(self) -> None:
		value = candidate()
		identity = identity_for(value)
		legacy = pd.DataFrame(
			[{"adjustment_id": "A0001", "version": 1, "status": "approved", "amount": 10}]
		)
		lookup = _history_identity_lookup(
			legacy, identity, _canonical_json(_candidate_state(value))
		)
		self.assertEqual(lookup["status"], "identity_unresolved")

	def test_inert_legacy_rows_do_not_block_v2_matching_or_resolution(self) -> None:
		value = candidate()
		identity = identity_for(value)
		legacy = {
			"adjustment_id": "A0009",
			"version": 1,
			"status": "proposed",
			"target_line": value.target_line,
			"period": value.period,
			"amount": 10.0,
		}
		history = pd.DataFrame([legacy, history_row(value, identity)])
		before = history.copy(deep=True)
		lookup = _history_identity_lookup(
			history, identity, _canonical_json(_candidate_state(value))
		)
		self.assertEqual(lookup["status"], "replay")
		self.assertTrue(_history_identity_complete(history))
		self.assertEqual(
			resolve_current_adjustments(history)["adjustment_id"].tolist(),
			["A0001"],
		)
		pd.testing.assert_frame_equal(history, before)

	def test_effective_legacy_authority_fails_closed(self) -> None:
		value = candidate()
		history = pd.DataFrame(
			[
				{
					"adjustment_id": "A0009",
					"version": 1,
					"status": "approved",
					"target_line": value.target_line,
					"period": value.period,
					"amount": 10.0,
				}
			]
		)
		identity = identity_for(value)
		self.assertFalse(_history_identity_complete(history))
		self.assertEqual(
			_history_identity_lookup(
				history, identity, _canonical_json(_candidate_state(value))
			)["status"],
			"identity_unresolved",
		)

	def test_malformed_v2_row_fails_closed_even_when_rejected(self) -> None:
		value = candidate()
		malformed_identity = _canonical_json(
			{
				"identity_version": "economic-adjustment-v2",
				"company": "MSFT",
				"fiscal_period": value.period,
				"target_row_key": "standard_concept:ResearchAndDevelopmentExpenses",
			}
		)
		history = pd.DataFrame(
			[
				{
					"adjustment_id": "A0001",
					"version": 1,
					"status": "rejected",
					"identity_version": "economic-adjustment-v2",
					"candidate_identity": malformed_identity,
					"candidate_state": _canonical_json(_candidate_state(value)),
				}
			]
		)
		self.assertFalse(_history_identity_complete(history))
		self.assertEqual(
			_history_identity_lookup(
				history, identity_for(value), _canonical_json(_candidate_state(value))
			)["status"],
			"identity_unresolved",
		)

	def test_unknown_identity_version_fails_closed_even_when_inert(self) -> None:
		value = candidate()
		row = history_row(value, identity_for(value), status="proposed")
		row["identity_version"] = "economic-adjustment-v3"
		row["candidate_identity"] = str(row["candidate_identity"]).replace(
			"economic-adjustment-v2", "economic-adjustment-v3"
		)
		history = pd.DataFrame([row])

		self.assertFalse(_history_identity_complete(history))
		self.assertEqual(
			_history_identity_lookup(
				history, identity_for(value), _canonical_json(_candidate_state(value))
			)["status"],
			"identity_unresolved",
		)

	def test_v2_identity_with_extra_field_fails_closed(self) -> None:
		value = candidate()
		identity = json.loads(identity_for(value))
		identity["surprise"] = "provenance"
		row = history_row(value, _canonical_json(identity))
		history = pd.DataFrame([row])

		self.assertFalse(_history_identity_complete(history))
		with self.assertRaisesRegex(ValueError, "fail closed"):
			resolve_current_adjustments(history)

	def test_v2_identity_with_invalid_period_or_row_key_fails_closed(self) -> None:
		value = candidate()
		for field, invalid in (
			("fiscal_period", "not-annual"),
			("target_row_key", "not-a-selector"),
		):
			with self.subTest(field=field):
				identity = json.loads(identity_for(value))
				identity[field] = invalid
				row = history_row(value, _canonical_json(identity))
				row.pop("target_row_key", None)
				history = pd.DataFrame([row])

				self.assertFalse(_history_identity_complete(history))
				with self.assertRaisesRegex(ValueError, "fail closed"):
					resolve_current_adjustments(history)

	def test_v2_identity_requires_persisted_target_row_snapshot(self) -> None:
		value = candidate()
		row = history_row(value, identity_for(value))
		row.pop("target_row_key")
		history = pd.DataFrame([row])

		self.assertFalse(_history_identity_complete(history))
		with self.assertRaisesRegex(ValueError, "fail closed"):
			resolve_current_adjustments(history)

	def test_mixed_identities_under_one_adjustment_id_fail_closed(self) -> None:
		first = candidate(item_key="xbox-impairment")
		competing = candidate(item_key="gaming-asset-impairment")
		v1 = history_row(first, identity_for(first))
		v2 = history_row(competing, identity_for(competing), status="rejected")
		v2["version"] = 2
		history = pd.DataFrame([v1, v2])

		self.assertFalse(_history_identity_complete(history))
		lookup = _history_identity_lookup(
			history,
			identity_for(first),
			_canonical_json(_candidate_state(first)),
		)
		self.assertEqual(lookup["status"], "identity_unresolved")
		self.assertIsNone(lookup["adjustment_id"])

	def test_malformed_canonical_history_fails_closed_before_application(self) -> None:
		value = candidate()
		identity = identity_for(value)
		row = history_row(value, identity)
		missing_status = dict(row)
		del missing_status["status"]
		invalid_version = {**row, "version": "invalid"}
		duplicate_versions = [row, dict(row)]

		for rows in ([missing_status], [invalid_version], duplicate_versions):
			with self.subTest(rows=rows):
				history = pd.DataFrame(rows)
				self.assertFalse(_history_identity_complete(history))
				lookup = _history_identity_lookup(
					history,
					identity,
					_canonical_json(_candidate_state(value)),
				)
				self.assertEqual(lookup["status"], "identity_unresolved")

	def test_latest_approved_remains_effective_when_later_version_rejected(self) -> None:
		value = candidate(amount=900.0)
		identity = identity_for(value)
		v1 = history_row(value, identity)
		v2 = dict(v1)
		v2.update({"version": 2, "status": "rejected"})
		history = pd.DataFrame([v1, v2])
		current = resolve_current_adjustments(history.assign(
			target_line="Research and development",
			period=PERIOD,
			item_amount=900.0,
			item_effect_on_line="increased_line",
		))
		self.assertEqual(current["version"].tolist(), [1])
