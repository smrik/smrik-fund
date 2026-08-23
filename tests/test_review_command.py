from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

import pandas as pd
from typer.testing import CliRunner

from smrik_fund.ingestion.statements import save_analytical_pnl
from smrik_fund.main import (
	IDENTITY_VERSION,
	_canonical_json,
	_pending_review_entries,
	app,
)

PERIOD = "2025-06-30 (FY)"
TICKER = "MSFT"


def make_pnl() -> pd.DataFrame:
	rows = [
		("Revenue", "Revenue", 1000.0),
		("Cost of revenue", "CostOfGoodsAndServicesSold", 600.0),
		("Gross profit", "GrossProfit", 400.0),
		("Research and development", "ResearchAndDevelopmentExpenses", 100.0),
		("Sales and marketing", "SellingGeneralAndAdminExpenses", 50.0),
		("General and administrative", "SellingGeneralAndAdminExpenses", 50.0),
		("Operating income", "OperatingIncomeLoss", 200.0),
		("Other income (expense), net", "NonoperatingIncomeExpense", 0.0),
		("Income before income taxes", "PretaxIncomeLoss", 200.0),
		("Provision for income taxes", "IncomeTaxes", 40.0),
		("Net income", "NetIncome", 160.0),
	]
	return pd.DataFrame(
		{
			"concept": [f"us-gaap_{concept}" for _, concept, _ in rows],
			"label": [label for label, _, _ in rows],
			"standard_concept": [concept for _, concept, _ in rows],
			PERIOD: [value for _, _, value in rows],
		}
	)


def _identity(period: str = PERIOD, key: str = "fixture-impairment") -> str:
	return _canonical_json(
		{
			"identity_version": IDENTITY_VERSION,
			"company": TICKER,
			"fiscal_period": period,
			"target_row_key": "standard_concept:ResearchAndDevelopmentExpenses",
			"item_key": key,
		}
	)


def _state(amount: float | None, basis: str = "disclosed") -> str:
	return _canonical_json(
		{
			"item_amount": amount,
			"item_effect_on_line": "increased_line",
			"amount_basis": basis,
		}
	)


def make_record(
	*,
	amount: float | None = 10.0,
	effect: str | None = "increased_line",
	key: str = "fixture-impairment",
	assessment: str = "eligible",
	recurrence: str = "single_period",
	mpe: bool = False,
) -> dict[str, object]:
	candidate = {
		"target_line": "Research and development",
		"sub_item": "Fixture impairment",
		"period": PERIOD,
		"item_amount": amount,
		"item_effect_on_line": effect,
		"item_key": key,
		"amount_basis": "disclosed" if amount is not None else "unknown",
		"reason": "Fixture reason.",
		"evidence_refs": ["E1"],
	}
	reasons = ["materiality_failed_or_unknown"]
	if assessment != "eligible" or recurrence != "single_period" or mpe:
		reasons.append("normalization_eligibility_failed_or_unknown")
	return {
		"adjustment_id": "A0001",
		"final_status": "human_review",
		"application_status": "not_applied",
		"candidate_identity": _identity(key=key),
		"candidate_state": _state(
			amount, "disclosed" if amount is not None else "unknown"
		),
		"candidate": candidate,
		"review": {
			"verdict": "accept",
			"evidence_strength": "strong",
			"judgment_level": "low",
			"concerns": [],
		},
		"normalization": {
			"assessment": assessment,
			"recurrence_class": recurrence,
			"multi_period_evidence": mpe,
		},
		"gate": {"decision": "human_review", "reasons": reasons},
		"materiality": {
			"passed": None,
			"metrics": {
				"pct_revenue": None if amount is None else amount / 1000.0,
				"pct_target_line": None if amount is None else amount / 100.0,
				"pct_operating_income": (
					None if amount is None else amount / 200.0
				),
			},
		},
	}


def setup_workspace(root: Path, records: list[dict[str, object]]) -> Path:
	save_analytical_pnl(TICKER, make_pnl(), str(root))
	manifest_path = (
		root / TICKER / "03_output" / "analysis" / "adjustment_run_run-review.json"
	)
	manifest_path.parent.mkdir(parents=True, exist_ok=True)
	manifest_path.write_text(
		json.dumps(
			{
				"metadata": {"ticker": TICKER, "run_id": "run-review"},
				"candidates": records,
			}
		),
		encoding="utf-8",
	)
	return root / TICKER / "03_output" / "adjustment_history.csv"


def read_history(path: Path) -> pd.DataFrame:
	return pd.read_csv(path)


def seed_approved_row() -> dict[str, object]:
	return {
		"adjustment_id": "A0001",
		"version": 1,
		"schema_version": 2,
		"identity_version": IDENTITY_VERSION,
		"candidate_identity": _identity(),
		"candidate_state": _state(10.0),
		"origin": "llm",
		"company": TICKER,
		"fiscal_period": PERIOD,
		"target_row_key": "standard_concept:ResearchAndDevelopmentExpenses",
		"item_key": "fixture-impairment",
		"target_line": "Research and development",
		"period": PERIOD,
		"item_amount": 10.0,
		"item_effect_on_line": "increased_line",
		"amount_basis": "disclosed",
		"line_delta": -10.0,
		"status": "approved",
	}


class ReviewCommandTests(TestCase):
	def test_accept_appends_human_approved_row_and_rebuilds(self) -> None:
		runner = CliRunner()
		with TemporaryDirectory() as temporary_directory:
			root = Path(temporary_directory)
			history_path = setup_workspace(root, [make_record()])

			result = runner.invoke(
				app, ["review", TICKER, "--output-root", str(root)], input="a\n"
			)

			self.assertEqual(result.exit_code, 0, result.output)
			self.assertIn("Approved as A0001 v1", result.output)
			history = read_history(history_path)
			self.assertEqual(len(history), 1)
			row = history.iloc[0]
			self.assertEqual(row["status"], "approved")
			self.assertEqual(row["origin"], "human")
			self.assertEqual(row["item_amount"], 10.0)
			self.assertEqual(row["line_delta"], -10.0)
			adjusted = pd.read_csv(root / TICKER / "03_output" / "adjusted_pnl.csv")
			rd = adjusted.loc[adjusted["label"] == "Research and development"].iloc[0]
			self.assertEqual(rd[PERIOD], 90.0)

	def test_reject_persists_reason_and_suppresses_rereview(self) -> None:
		runner = CliRunner()
		with TemporaryDirectory() as temporary_directory:
			root = Path(temporary_directory)
			history_path = setup_workspace(root, [make_record(amount=None)])

			result = runner.invoke(
				app,
				["review", TICKER, "--output-root", str(root)],
				input="r\nnot disclosed\n",
			)
			self.assertEqual(result.exit_code, 0, result.output)
			history = read_history(history_path)
			self.assertEqual(len(history), 1)
			self.assertEqual(history.iloc[0]["status"], "rejected")
			self.assertEqual(history.iloc[0]["reject_reason"], "not disclosed")

			second = runner.invoke(
				app, ["review", TICKER, "--output-root", str(root)]
			)
			self.assertEqual(second.exit_code, 0, second.output)
			self.assertIn("Nothing pending human review", second.output)

	def test_edit_amount_supersedes_without_stacking(self) -> None:
		runner = CliRunner()
		with TemporaryDirectory() as temporary_directory:
			root = Path(temporary_directory)
			history_path = setup_workspace(root, [make_record(amount=12.0)])
			pd.DataFrame([seed_approved_row()]).to_csv(history_path, index=False)

			result = runner.invoke(
				app,
				["review", TICKER, "--output-root", str(root)],
				input="e\n12\n",
			)

			self.assertEqual(result.exit_code, 0, result.output)
			self.assertIn("Approved edited amount as A0001 v2", result.output)
			history = read_history(history_path)
			self.assertEqual(len(history), 2)
			current = history.loc[history["status"] == "approved"].sort_values(
				"version"
			)
			self.assertEqual(current.iloc[-1]["item_amount"], 12.0)
			adjusted = pd.read_csv(root / TICKER / "03_output" / "adjusted_pnl.csv")
			rd = adjusted.loc[
				adjusted["label"] == "Research and development"
			].iloc[0]
			# v2 supersedes v1: 100 - 12, never 100 - 10 - 12.
			self.assertEqual(rd[PERIOD], 88.0)

	def test_zero_crossing_requires_explicit_confirmation(self) -> None:
		runner = CliRunner()
		with TemporaryDirectory() as temporary_directory:
			root = Path(temporary_directory)
			history_path = setup_workspace(root, [make_record(amount=150.0)])

			result = runner.invoke(
				app,
				["review", TICKER, "--output-root", str(root)],
				input="a\n\n",
			)
			self.assertEqual(result.exit_code, 0, result.output)
			self.assertIn("WARNING", result.output)
			self.assertIn("Not confirmed", result.output)
			self.assertFalse(history_path.exists())

	def test_not_eligible_accept_requires_override_reason(self) -> None:
		runner = CliRunner()
		with TemporaryDirectory() as temporary_directory:
			root = Path(temporary_directory)
			history_path = setup_workspace(
				root,
				[
					make_record(
						amount=10.0,
						assessment="not_eligible",
						recurrence="recurring_volatile",
						mpe=True,
					)
				],
			)

			result = runner.invoke(
				app,
				["review", TICKER, "--output-root", str(root)],
				input="a\ndeliberate analytical choice\n",
			)

			self.assertEqual(result.exit_code, 0, result.output)
			history = read_history(history_path)
			row = history.iloc[0]
			self.assertEqual(row["status"], "approved")
			self.assertEqual(
				row["human_override_reason"], "deliberate analytical choice"
			)

	def test_identity_less_candidate_cannot_be_accepted(self) -> None:
		runner = CliRunner()
		record = make_record()
		record["candidate_identity"] = None
		with TemporaryDirectory() as temporary_directory:
			root = Path(temporary_directory)
			history_path = setup_workspace(root, [record])

			result = runner.invoke(
				app, ["review", TICKER, "--output-root", str(root)], input="a\n"
			)

			self.assertEqual(result.exit_code, 0, result.output)
			self.assertIn("Refused", result.output)
			self.assertFalse(history_path.exists())


class PendingQueueTests(TestCase):
	def test_decided_identical_proposal_is_excluded_but_changed_one_is_not(self):
		decided = make_record(amount=10.0)
		changed = make_record(amount=12.0)
		unresolved = make_record(amount=None)
		unresolved["final_status"] = "unresolved"

		history = pd.DataFrame(
			[
				{
					**seed_approved_row(),
					"status": "rejected",
					"candidate_state": decided["candidate_state"],
					"item_amount": 10.0,
				}
			]
		)
		manifest = {"candidates": [decided, changed, unresolved]}

		pending = _pending_review_entries(manifest, history)

		self.assertEqual(len(pending), 2)
