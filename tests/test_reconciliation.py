from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import pandas as pd
from typer.testing import CliRunner

from smrik_fund.ingestion.reconciliation import (
    reconcile_pnl,
    save_reconciliation_checks,
)
from smrik_fund.main import app

PERIODS = (
    "2026-06-30 (FY)",
    "2025-06-30 (FY)",
    "2024-06-30 (FY)",
)


def make_analytical_pnl() -> pd.DataFrame:
    rows = [
        ("Revenue", "Revenue", [120.0, 100.0, 80.0]),
        (
            "Cost of revenue",
            "CostOfGoodsAndServicesSold",
            [30.0, 25.0, 20.0],
        ),
        ("Gross profit", "GrossProfit", [90.0, 75.0, 60.0]),
        (
            "Research and development",
            "ResearchAndDevelopmentExpenses",
            [20.0, 18.0, 16.0],
        ),
        (
            "Sales and marketing",
            "SellingGeneralAndAdminExpenses",
            [10.0, 9.0, 8.0],
        ),
        (
            "General and administrative",
            "SellingGeneralAndAdminExpenses",
            [5.0, 4.0, 3.0],
        ),
        ("Operating income", "OperatingIncomeLoss", [55.0, 44.0, 33.0]),
        (
            "Other income (expense), net",
            "NonoperatingIncomeExpense",
            [5.0, -2.0, -1.0],
        ),
        ("Income before income taxes", "PretaxIncomeLoss", [60.0, 42.0, 32.0]),
        ("Provision for income taxes", "IncomeTaxes", [12.0, 8.4, 6.4]),
        ("Net income", "NetIncome", [48.0, 33.6, 25.6]),
        ("Product", None, [60.0, 50.0, 40.0]),
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


class ReconcilePnlTests(TestCase):
    def test_reconcile_pnl_records_passing_checks_for_each_period(self) -> None:
        source = make_analytical_pnl()
        source_before = source.copy(deep=True)

        checks = reconcile_pnl(source)

        pd.testing.assert_frame_equal(source, source_before)
        self.assertEqual(checks["period"].unique().tolist(), list(PERIODS))
        self.assertEqual(
            set(checks["check_id"]),
            {"gross_profit", "operating_income", "pretax_income", "net_income"},
        )
        self.assertEqual(len(checks), 12)
        self.assertTrue((checks["status"] == "PASS").all())
        self.assertTrue(checks["acknowledged"].eq(False).all())

        gross_profit = checks[
            (checks["check_id"] == "gross_profit")
            & (checks["period"] == PERIODS[0])
        ].iloc[0]
        self.assertEqual(gross_profit["reported_value"], 90.0)
        self.assertEqual(gross_profit["calculated_value"], 90.0)
        self.assertEqual(gross_profit["difference"], 0.0)
        self.assertIn("Revenue", gross_profit["affected_lines"])
        self.assertIn("Gross profit", gross_profit["affected_lines"])

    def test_reconcile_pnl_records_failed_check_without_a_plug(self) -> None:
        source = make_analytical_pnl()
        source.loc[source["standard_concept"] == "GrossProfit", PERIODS[0]] = 91.0

        checks = reconcile_pnl(source)

        gross_profit = checks[
            (checks["check_id"] == "gross_profit")
            & (checks["period"] == PERIODS[0])
        ].iloc[0]
        self.assertEqual(gross_profit["status"], "FAIL")
        self.assertEqual(gross_profit["reported_value"], 91.0)
        self.assertEqual(gross_profit["calculated_value"], 90.0)
        self.assertEqual(gross_profit["difference"], -1.0)
        self.assertIn("difference", gross_profit["message"])
        self.assertIn("Cost of revenue", gross_profit["affected_lines"])

    def test_reconcile_pnl_skips_check_when_required_value_is_missing(self) -> None:
        source = make_analytical_pnl()
        source.loc[
            source["standard_concept"] == "CostOfGoodsAndServicesSold",
            PERIODS[1],
        ] = float("nan")

        checks = reconcile_pnl(source)

        gross_profit = checks[
            (checks["check_id"] == "gross_profit")
            & (checks["period"] == PERIODS[1])
        ].iloc[0]
        self.assertEqual(gross_profit["status"], "SKIPPED")
        self.assertTrue(pd.isna(gross_profit["calculated_value"]))
        self.assertTrue(pd.isna(gross_profit["difference"]))
        self.assertIn("missing", gross_profit["message"].lower())

    def test_reconcile_pnl_respects_negative_other_income_sign(self) -> None:
        checks = reconcile_pnl(make_analytical_pnl())

        pretax = checks[
            (checks["check_id"] == "pretax_income")
            & (checks["period"] == PERIODS[1])
        ].iloc[0]
        self.assertEqual(pretax["reported_value"], 42.0)
        self.assertEqual(pretax["calculated_value"], 42.0)
        self.assertEqual(pretax["difference"], 0.0)
        self.assertEqual(pretax["status"], "PASS")

    def test_reconcile_pnl_tolerance_is_recorded_and_enforced(self) -> None:
        source = make_analytical_pnl()
        source.loc[source["standard_concept"] == "GrossProfit", PERIODS[0]] = 90.005

        passing = reconcile_pnl(source, tolerance=0.01)
        failing = reconcile_pnl(source, tolerance=0.001)

        passing_gross_profit = passing[
            (passing["check_id"] == "gross_profit")
            & (passing["period"] == PERIODS[0])
        ].iloc[0]
        failing_gross_profit = failing[
            (failing["check_id"] == "gross_profit")
            & (failing["period"] == PERIODS[0])
        ].iloc[0]
        self.assertEqual(passing_gross_profit["status"], "PASS")
        self.assertEqual(passing_gross_profit["tolerance"], 0.01)
        self.assertEqual(failing_gross_profit["status"], "FAIL")

    def test_reconcile_pnl_distinguishes_duplicate_standard_concepts(self) -> None:
        checks = reconcile_pnl(make_analytical_pnl())

        operating = checks[checks["check_id"] == "operating_income"]
        self.assertTrue((operating["status"] == "PASS").all())
        self.assertIn("Sales and marketing", operating.iloc[0]["affected_lines"])
        self.assertIn(
            "General and administrative",
            operating.iloc[0]["affected_lines"],
        )

    def test_reconcile_pnl_uses_statement_hierarchy_not_expense_labels(self) -> None:
        source = make_analytical_pnl()
        source["concept"] = source["standard_concept"].map(
            lambda concept: (
                f"us-gaap_{concept}" if pd.notna(concept) else None
            )
        )
        source["parent_concept"] = None
        source.loc[
            source["standard_concept"].isin(
                {
                    "GrossProfit",
                    "ResearchAndDevelopmentExpenses",
                    "SellingGeneralAndAdminExpenses",
                }
            ),
            "parent_concept",
        ] = "us-gaap_OperatingIncomeLoss"
        source["weight"] = 1.0
        source.loc[
            source["standard_concept"].isin(
                {
                    "ResearchAndDevelopmentExpenses",
                    "SellingGeneralAndAdminExpenses",
                }
            ),
            "weight",
        ] = -1.0
        source.loc[
            source["standard_concept"] == "ResearchAndDevelopmentExpenses",
            "label",
        ] = "Engineering"
        source.loc[
            source["standard_concept"] == "SellingGeneralAndAdminExpenses",
            "label",
        ] = ["Go-to-market", "Corporate"]

        checks = reconcile_pnl(source)
        operating = checks[checks["check_id"] == "operating_income"]
        self.assertTrue((operating["status"] == "PASS").all())


class SaveReconciliationChecksTests(TestCase):
    def test_save_reconciliation_checks_writes_and_reads_csv(self) -> None:
        checks = reconcile_pnl(make_analytical_pnl())

        with TemporaryDirectory() as temporary_directory:
            output_path = save_reconciliation_checks(
                " msft ",
                checks,
                temporary_directory,
            )

            self.assertEqual(
                output_path,
                Path(temporary_directory)
                / "MSFT"
                / "03_output"
                / "reconciliation_checks.csv",
            )
            saved = pd.read_csv(output_path)

        self.assertEqual(len(saved), 12)
        for column in (
            "check_id",
            "period",
            "subtotal",
            "reported_value",
            "calculated_value",
            "difference",
            "status",
            "acknowledged",
            "affected_lines",
            "message",
        ):
            self.assertIn(column, saved.columns)
        self.assertEqual(saved.iloc[0]["status"], "PASS")


class ReconcileCommandTests(TestCase):
    def test_analyze_command_writes_pnl_and_reconciliation(self) -> None:
        runner = CliRunner()
        source = make_analytical_pnl()

        with (
            patch("smrik_fund.main.build_analytical_pnl", return_value=source),
            patch(
                "smrik_fund.main.save_analytical_pnl",
                return_value=Path("data/MSFT/03_output/analytical_pnl.csv"),
            ) as save_pnl,
            patch(
                "smrik_fund.main.save_reconciliation_checks",
                return_value=Path("data/MSFT/03_output/reconciliation_checks.csv"),
            ) as save_checks,
        ):
            result = runner.invoke(app, ["analyze", "MSFT"])

        self.assertEqual(result.exit_code, 0, result.output)
        save_pnl.assert_called_once()
        save_checks.assert_called_once()
        self.assertIn("Saved analytical P&L", result.output)
        self.assertIn("Saved reconciliation checks", result.output)

    def test_reconcile_command_prints_warning_for_failed_check(self) -> None:
        runner = CliRunner()
        source = make_analytical_pnl()
        source.loc[source["standard_concept"] == "GrossProfit", PERIODS[0]] = 91.0

        with (
            patch(
                "smrik_fund.main.load_analytical_pnl",
                return_value=source,
            ),
            patch(
                "smrik_fund.main.save_reconciliation_checks",
                return_value=Path("data/MSFT/03_output/reconciliation_checks.csv"),
            ),
        ):
            result = runner.invoke(app, ["reconcile", "MSFT"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("WARNING", result.output)
        self.assertIn("gross_profit", result.output)
        self.assertIn("FAIL", result.output)
        self.assertIn("difference", result.output)
