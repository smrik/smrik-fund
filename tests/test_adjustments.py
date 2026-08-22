from __future__ import annotations

import json
from unittest import TestCase

import pandas as pd

from smrik_fund.ingestion.adjustments import (
    apply_adjustments,
    derive_line_delta,
    resolve_current_adjustments,
)

PERIODS = (
    "2025-06-30 (FY)",
    "2024-06-30 (FY)",
    "2023-06-30 (FY)",
)


def make_pnl() -> pd.DataFrame:
    rows = [
        ("Revenue", "Revenue", [1000.0, 900.0, 800.0]),
        (
            "Cost of revenue",
            "CostOfGoodsAndServicesSold",
            [600.0, 500.0, 400.0],
        ),
        ("Gross profit", "GrossProfit", [400.0, 400.0, 400.0]),
        (
            "Research and development",
            "ResearchAndDevelopmentExpenses",
            [100.0, 90.0, 80.0],
        ),
        (
            "Sales and marketing",
            "SellingGeneralAndAdminExpenses",
            [50.0, 45.0, 40.0],
        ),
        (
            "General and administrative",
            "SellingGeneralAndAdminExpenses",
            [50.0, 45.0, 40.0],
        ),
        ("Operating income", "OperatingIncomeLoss", [200.0, 220.0, 240.0]),
        (
            "Other income (expense), net",
            "NonoperatingIncomeExpense",
            [10.0, -5.0, 0.0],
        ),
        (
            "Income before income taxes",
            "PretaxIncomeLoss",
            [210.0, 215.0, 240.0],
        ),
        ("Provision for income taxes", "IncomeTaxes", [42.0, 43.0, 48.0]),
        ("Net income", "NetIncome", [168.0, 172.0, 192.0]),
    ]
    return pd.DataFrame(
        {
            "label": [row[0] for row in rows],
            "standard_concept": [row[1] for row in rows],
            PERIODS[0]: [row[2][0] for row in rows],
            PERIODS[1]: [row[2][1] for row in rows],
            PERIODS[2]: [row[2][2] for row in rows],
        }
    )


def adjustment(
    adjustment_id: str,
    version: int,
    target_line: str,
    period: str,
    item_amount: float | None,
    item_effect_on_line: str | None = "increased_line",
    status: str = "approved",
    origin: str = "llm",
) -> dict[str, object]:
    concepts = {
        "Cost of revenue": "CostOfGoodsAndServicesSold",
        "Research and development": "ResearchAndDevelopmentExpenses",
        "Sales and marketing": "SellingGeneralAndAdminExpenses",
        "General and administrative": "SellingGeneralAndAdminExpenses",
        "Other income (expense), net": "NonoperatingIncomeExpense",
        "Provision for income taxes": "IncomeTaxes",
    }
    concept = concepts[target_line]
    target_row_key = f"standard_concept:{concept}"
    if concept == "SellingGeneralAndAdminExpenses":
        target_row_key += f"|label:{target_line}"
    item_key = {
        "A0001": "fixture-charge-alpha",
        "A0002": "fixture-charge-beta",
    }[adjustment_id]
    identity = {
        "identity_version": "economic-adjustment-v2",
        "company": "MSFT",
        "fiscal_period": period,
        "target_row_key": target_row_key,
        "item_key": item_key,
    }
    state = {
        "item_amount": item_amount,
        "item_effect_on_line": item_effect_on_line,
        "amount_basis": "disclosed",
    }
    return {
        "adjustment_id": adjustment_id,
        "version": version,
        "run_id": f"run-{adjustment_id}-{version}",
        "origin": origin,
        "identity_version": "economic-adjustment-v2",
        "candidate_identity": json.dumps(identity, sort_keys=True, separators=(",", ":")),
        "candidate_state": json.dumps(state, sort_keys=True, separators=(",", ":")),
        "target_row_key": target_row_key,
        "target_line": target_line,
        "period": period,
        "item_amount": item_amount,
        "item_effect_on_line": item_effect_on_line,
        "line_delta": derive_line_delta(item_amount, item_effect_on_line),
        "status": status,
    }


class ResolveCurrentAdjustmentsTests(TestCase):
    def test_latest_approved_version_wins_without_stacking(self) -> None:
        history = pd.DataFrame(
            [
                adjustment("A0001", 1, "Cost of revenue", PERIODS[1], 400),
                adjustment(
                    "A0001",
                    2,
                    "Cost of revenue",
                    PERIODS[1],
                    350,
                    origin="human",
                ),
                adjustment(
                    "A0001",
                    3,
                    "Cost of revenue",
                    PERIODS[1],
                    300,
                    status="proposed",
                ),
                adjustment("A0002", 1, "Cost of revenue", PERIODS[1], 60),
                adjustment(
                    "A0002",
                    2,
                    "Cost of revenue",
                    PERIODS[1],
                    60,
                    status="rejected",
                ),
            ]
        )
        history_before = history.copy(deep=True)

        current = resolve_current_adjustments(history)

        self.assertEqual(current["adjustment_id"].tolist(), ["A0001", "A0002"])
        self.assertEqual(current["version"].tolist(), [2, 1])
        self.assertEqual(current["item_amount"].tolist(), [350, 60])
        pd.testing.assert_frame_equal(history, history_before)

    def test_later_rejection_does_not_remove_prior_approval(self) -> None:
        history = pd.DataFrame(
            [
                adjustment("A0001", 1, "Cost of revenue", PERIODS[1], 400),
                adjustment(
                    "A0001",
                    2,
                    "Cost of revenue",
                    PERIODS[1],
                    350,
                    status="rejected",
                ),
            ]
        )

        current = resolve_current_adjustments(history)

        self.assertEqual(current[["adjustment_id", "version"]].values.tolist(), [["A0001", 1]])


class ApplyAdjustmentsTests(TestCase):
    def test_one_adjustment_changes_only_target_period_and_recomputes_subtotals(self) -> None:
        source = make_pnl()
        source_before = source.copy(deep=True)
        history = pd.DataFrame(
            [adjustment("A0001", 1, "Cost of revenue", PERIODS[1], 100)]
        )
        history_before = history.copy(deep=True)

        adjusted = apply_adjustments(source, history)

        cost = adjusted.loc[adjusted["label"] == "Cost of revenue"].iloc[0]
        gross_profit = adjusted.loc[adjusted["standard_concept"] == "GrossProfit"].iloc[0]
        operating_income = adjusted.loc[
            adjusted["standard_concept"] == "OperatingIncomeLoss"
        ].iloc[0]
        self.assertEqual(cost[PERIODS[0]], 600.0)
        self.assertEqual(cost[PERIODS[1]], 400.0)
        self.assertEqual(cost[PERIODS[2]], 400.0)
        self.assertEqual(gross_profit[PERIODS[1]], 500.0)
        self.assertEqual(operating_income[PERIODS[1]], 320.0)
        self.assertAlmostEqual(gross_profit[f"gross_margin_{PERIODS[1]}"], 500 / 900)
        pd.testing.assert_frame_equal(source, source_before)
        pd.testing.assert_frame_equal(history, history_before)

    def test_multiple_adjustments_are_summed_once_and_order_independent(self) -> None:
        source = make_pnl()
        history = pd.DataFrame(
            [
                adjustment("A0001", 1, "Cost of revenue", PERIODS[1], 100),
                adjustment("A0002", 1, "Cost of revenue", PERIODS[1], 50),
            ]
        )

        current = resolve_current_adjustments(history)
        adjusted = apply_adjustments(source, current)
        reordered = apply_adjustments(source, current.iloc[::-1].reset_index(drop=True))

        cost = adjusted.loc[adjusted["label"] == "Cost of revenue"].iloc[0]
        self.assertEqual(len(current), 2)
        self.assertEqual(cost[PERIODS[1]], 350.0)
        self.assertEqual(
            adjusted.loc[adjusted["standard_concept"] == "GrossProfit", PERIODS[1]].iloc[0],
            550.0,
        )
        pd.testing.assert_frame_equal(adjusted, reordered)

    def test_non_positive_item_amount_fails_closed(self) -> None:
        history = pd.DataFrame(
            [adjustment("A0001", 1, "Cost of revenue", PERIODS[1], -100)]
        )

        with self.assertRaisesRegex(ValueError, "line_delta"):
            apply_adjustments(make_pnl(), history)

    def test_legacy_row_without_direction_fails_closed(self) -> None:
        history = pd.DataFrame(
            [
                {
                    "adjustment_id": "A0001",
                    "version": 1,
                    "run_id": "legacy",
                    "origin": "llm",
                    "target_line": "Cost of revenue",
                    "period": PERIODS[1],
                    "amount": 100.0,
                    "status": "approved",
                }
            ]
        )

        with self.assertRaisesRegex(ValueError, "fail closed"):
            apply_adjustments(make_pnl(), history)

    def test_unique_concept_row_key_applies_after_label_drift(self) -> None:
        source = make_pnl()
        source.loc[source["standard_concept"] == "ResearchAndDevelopmentExpenses", "label"] = "Engineering"
        history = pd.DataFrame(
            [adjustment("A0001", 1, "Research and development", PERIODS[0], 10.0)]
        )

        adjusted = apply_adjustments(source, history)

        engineering = adjusted.loc[
            adjusted["standard_concept"] == "ResearchAndDevelopmentExpenses"
        ].iloc[0]
        self.assertEqual(engineering[PERIODS[0]], 90.0)


class DeriveLineDeltaTests(TestCase):
    def test_expense_in_expense_line_derives_negative_delta(self) -> None:
        self.assertEqual(derive_line_delta(10.0, "increased_line"), -10.0)

    def test_gain_reducing_expense_line_derives_positive_delta(self) -> None:
        self.assertEqual(derive_line_delta(0.5, "decreased_line"), 0.5)

    def test_unsupported_fact_leaves_delta_underived(self) -> None:
        self.assertIsNone(derive_line_delta(0.5, None))
        self.assertIsNone(derive_line_delta(None, "decreased_line"))
        self.assertIsNone(derive_line_delta(None, None))

    def test_non_positive_or_unknown_effect_fails_closed(self) -> None:
        for amount, effect in (
            (-100.0, "increased_line"),
            (0.0, "decreased_line"),
            (10.0, "unknown"),
            (float("nan"), "increased_line"),
        ):
            with self.subTest(amount=amount, effect=effect):
                self.assertIsNone(derive_line_delta(amount, effect))


class SignDirectionArithmeticTests(TestCase):
    def test_proof_case_2_gain_inside_expense_line_increases_the_line(self) -> None:
        source = make_pnl()
        history = pd.DataFrame(
            [
                adjustment(
                    "A0001", 1, "General and administrative", PERIODS[0], 10.0,
                    item_effect_on_line="decreased_line",
                )
            ]
        )

        adjusted = apply_adjustments(source, history)

        ga = adjusted.loc[
            adjusted["label"] == "General and administrative"
        ].iloc[0]
        operating_income = adjusted.loc[
            adjusted["standard_concept"] == "OperatingIncomeLoss"
        ].iloc[0]
        # The gain reduced reported G&A, so removing it raises G&A back.
        self.assertEqual(ga[PERIODS[0]], 60.0)
        self.assertEqual(operating_income[PERIODS[0]], 190.0)

    def test_proof_case_3_gain_inside_positive_income_line_decreases_it(self) -> None:
        source = make_pnl()
        history = pd.DataFrame(
            [
                adjustment(
                    "A0001", 1, "Other income (expense), net", PERIODS[0], 6.5,
                    item_effect_on_line="increased_line",
                )
            ]
        )

        adjusted = apply_adjustments(source, history)

        oie = adjusted.loc[
            adjusted["label"] == "Other income (expense), net"
        ].iloc[0]
        pretax = adjusted.loc[
            adjusted["standard_concept"] == "PretaxIncomeLoss"
        ].iloc[0]
        self.assertEqual(oie[PERIODS[0]], 3.5)
        self.assertEqual(pretax[PERIODS[0]], 203.5)

    def test_proof_case_4_loss_inside_negative_income_line_raises_it(self) -> None:
        source = make_pnl()
        history = pd.DataFrame(
            [
                adjustment(
                    "A0001", 1, "Other income (expense), net", PERIODS[1], 4.8,
                    item_effect_on_line="decreased_line",
                )
            ]
        )

        adjusted = apply_adjustments(source, history)

        oie = adjusted.loc[
            adjusted["label"] == "Other income (expense), net"
        ].iloc[0]
        pretax = adjusted.loc[
            adjusted["standard_concept"] == "PretaxIncomeLoss"
        ].iloc[0]
        # Negative parent line alone must not block or flip the arithmetic.
        self.assertAlmostEqual(oie[PERIODS[1]], -0.2)
        self.assertAlmostEqual(pretax[PERIODS[1]], 219.8)

    def test_proof_case_5_tax_expense_removal_lowers_provision(self) -> None:
        source = make_pnl()
        history = pd.DataFrame(
            [
                adjustment(
                    "A0001", 1, "Provision for income taxes", PERIODS[0], 1.4,
                    item_effect_on_line="increased_line",
                )
            ]
        )

        adjusted = apply_adjustments(source, history)

        taxes = adjusted.loc[
            adjusted["label"] == "Provision for income taxes"
        ].iloc[0]
        net_income = adjusted.loc[
            adjusted["standard_concept"] == "NetIncome"
        ].iloc[0]
        self.assertAlmostEqual(taxes[PERIODS[0]], 40.6)
        self.assertAlmostEqual(net_income[PERIODS[0]], 169.4)

