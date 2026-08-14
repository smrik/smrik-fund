from __future__ import annotations

from unittest import TestCase

import pandas as pd

from smrik_fund.ingestion.adjustments import (
    apply_adjustments,
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
    amount: float,
    status: str = "approved",
    origin: str = "llm",
) -> dict[str, object]:
    return {
        "adjustment_id": adjustment_id,
        "version": version,
        "run_id": f"run-{adjustment_id}-{version}",
        "origin": origin,
        "target_line": target_line,
        "period": period,
        "amount": amount,
        "status": status,
    }


class ResolveCurrentAdjustmentsTests(TestCase):
    def test_latest_version_wins_and_latest_rejection_removes_approval(self) -> None:
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

        self.assertEqual(current["adjustment_id"].tolist(), ["A0001"])
        self.assertEqual(current.iloc[0]["version"], 2)
        self.assertEqual(current.iloc[0]["amount"], 350)
        pd.testing.assert_frame_equal(history, history_before)


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

    def test_negative_amount_is_not_an_alternate_sign_convention(self) -> None:
        history = pd.DataFrame(
            [adjustment("A0001", 1, "Cost of revenue", PERIODS[1], -100)]
        )

        with self.assertRaisesRegex(ValueError, "non-negative"):
            apply_adjustments(make_pnl(), history)

