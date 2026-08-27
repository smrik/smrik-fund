from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

import pandas as pd

from smrik_fund.ingestion.statements import (
    build_analytical_pnl,
    get_statements,
    prepare_pnl,
    save_analytical_pnl,
)

PERIODS = (
    "2026-06-30 (FY)",
    "2025-06-30 (FY)",
    "2024-06-30 (FY)",
    "2023-06-30 (FY)",
)


def make_income_statement() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "concept": [
                "us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax",
                "us-gaap_CostOfGoodsAndServicesSold",
                "us-gaap_GrossProfit",
                "us-gaap_ResearchAndDevelopmentExpense",
                "us-gaap_OperatingIncomeLoss",
                "us-gaap_NonoperatingIncomeExpense",
                "us-gaap_IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                "us-gaap_IncomeTaxExpenseBenefit",
                "us-gaap_NetIncomeLoss",
                "us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax",
            ],
            "label": [
                "Revenue",
                "Cost of revenue",
                "Gross profit",
                "Research and development",
                "Operating income",
                "Other income (expense), net",
                "Income before income taxes",
                "Provision for income taxes",
                "Net income",
                "Product",
            ],
            "standard_concept": [
                "Revenue",
                "CostOfGoodsAndServicesSold",
                "GrossProfit",
                "ResearchAndDevelopmentExpenses",
                "OperatingIncomeLoss",
                "NonoperatingIncomeExpense",
                "PretaxIncomeLoss",
                "IncomeTaxes",
                "NetIncome",
                None,
            ],
            PERIODS[0]: [120.0, 60.0, 60.0, float("nan"), 30.0, 5.0, 35.0, 7.0, 28.0, 50.0],
            PERIODS[1]: [100.0, 50.0, 50.0, 10.0, 25.0, -3.0, 30.0, 6.0, 24.0, 40.0],
            PERIODS[2]: [80.0, 40.0, 40.0, 8.0, 20.0, -2.0, 24.0, 4.8, 19.2, 30.0],
            PERIODS[3]: [70.0, 35.0, 35.0, 7.0, 15.0, -1.0, 19.0, 3.8, 15.2, 25.0],
            "level": [4, 4, 3, 3, 3, 3, 3, 3, 3, 4],
            "abstract": [False] * 10,
            "dimension": [False] * 9 + [True],
            "is_breakdown": [False] * 9 + [True],
            "dimension_axis": [None] * 9 + ["srt:ProductOrServiceAxis"],
            "dimension_member": [None] * 9 + ["us-gaap:ProductMember"],
            "dimension_member_label": [None] * 9 + ["Product"],
            "dimension_label": [None] * 9 + ["Product or service: Product"],
            "balance": ["credit", "debit", "credit", "debit", "credit", "credit", "credit", "debit", "credit", "credit"],
            "weight": [1.0, -1.0, 1.0, -1.0, 1.0, 1.0, 1.0, -1.0, 1.0, 1.0],
            "preferred_sign": [1.0] * 10,
            "parent_concept": ["us-gaap_GrossProfit", "us-gaap_GrossProfit", "us-gaap_OperatingIncomeLoss", None, None, None, None, None, None, "us-gaap_GrossProfit"],
            "parent_abstract_concept": ["us-gaap_StatementLineItems"] * 10,
        }
    )


def metric_column(metric: str, period: str) -> str:
    return f"{metric}_{period}"


class GetStatementsTests(TestCase):
    def test_get_statements_loads_three_standard_views(self) -> None:
        frames = {
            "income_statement": pd.DataFrame({"concept": ["Revenue"]}),
            "balance_sheet": pd.DataFrame({"concept": ["Assets"]}),
            "cash_flow_statement": pd.DataFrame({"concept": ["Cash flow"]}),
        }
        company = Mock()
        filing = company.get_filings.return_value.latest.return_value
        xbrl = filing.xbrl.return_value
        methods = {
            "income_statement": xbrl.statements.income_statement,
            "balance_sheet": xbrl.statements.balance_sheet,
            "cash_flow_statement": xbrl.statements.cashflow_statement,
        }
        for name, method in methods.items():
            method.return_value.to_dataframe.return_value = frames[name]

        with patch("smrik_fund.ingestion.statements.Company", return_value=company):
            result = get_statements(" msft ")

        self.assertEqual(result, frames)
        company.get_filings.assert_called_once_with(form="10-K")
        for method in methods.values():
            method.assert_called_once_with()
            method.return_value.to_dataframe.assert_called_once_with(view="standard")


class PreparePnlTests(TestCase):
    def test_prepare_pnl_normalizes_bare_iso_annual_columns(self) -> None:
        source = make_income_statement().rename(
            columns={period: period.removesuffix(" (FY)") for period in PERIODS}
        )
        source_before = source.copy(deep=True)

        pnl = prepare_pnl(source, years=3)

        pd.testing.assert_frame_equal(source, source_before)
        self.assertEqual(
            [column for column in pnl.columns if column in PERIODS],
            list(PERIODS[:3]),
        )
        revenue = pnl.loc[pnl["standard_concept"] == "Revenue"].iloc[0]
        self.assertEqual(revenue[PERIODS[0]], 120.0)
        self.assertEqual(revenue[PERIODS[1]], 100.0)
        self.assertEqual(revenue[PERIODS[2]], 80.0)
        negative = pnl.loc[
            pnl["standard_concept"] == "NonoperatingIncomeExpense"
        ].iloc[0]
        self.assertEqual(negative[PERIODS[1]], -3.0)
        missing = pnl.loc[
            pnl["standard_concept"] == "ResearchAndDevelopmentExpenses"
        ].iloc[0]
        self.assertTrue(pd.isna(missing[PERIODS[0]]))

    def test_prepare_pnl_selects_periods_preserves_source_and_calculates_metrics(
        self,
    ) -> None:
        source = make_income_statement()
        source_before = source.copy(deep=True)

        pnl = prepare_pnl(source, years=3)

        pd.testing.assert_frame_equal(source, source_before)
        self.assertEqual(
            [column for column in pnl.columns if column in PERIODS],
            list(PERIODS[:3]),
        )
        self.assertNotIn(PERIODS[3], pnl.columns)
        for column in (
            "concept",
            "label",
            "standard_concept",
            "level",
            "abstract",
            "dimension",
            "is_breakdown",
            "parent_concept",
            "parent_abstract_concept",
        ):
            self.assertIn(column, pnl.columns)

        revenue = pnl.loc[pnl["standard_concept"] == "Revenue"].iloc[0]
        self.assertEqual(revenue[PERIODS[0]], 120.0)
        self.assertEqual(revenue[PERIODS[1]], 100.0)
        self.assertEqual(revenue[PERIODS[2]], 80.0)
        self.assertAlmostEqual(revenue[metric_column("yoy_change", PERIODS[0])], 0.2)
        self.assertAlmostEqual(revenue[metric_column("yoy_change", PERIODS[1])], 0.25)
        self.assertTrue(pd.isna(revenue[metric_column("yoy_change", PERIODS[2])]))

        negative = pnl.loc[pnl["standard_concept"] == "NonoperatingIncomeExpense"].iloc[0]
        self.assertEqual(negative[PERIODS[1]], -3.0)
        self.assertEqual(negative[PERIODS[2]], -2.0)

        missing = pnl.loc[pnl["standard_concept"] == "ResearchAndDevelopmentExpenses"].iloc[0]
        self.assertTrue(pd.isna(missing[PERIODS[0]]))
        self.assertTrue(pd.isna(missing[metric_column("yoy_change", PERIODS[0])]))

        breakdown = pnl.loc[pnl["label"] == "Product"].iloc[0]
        self.assertTrue(pd.isna(breakdown["standard_concept"]))
        self.assertTrue(pd.isna(breakdown[metric_column("percent_of_revenue", PERIODS[0])]))

        cost = pnl.loc[pnl["standard_concept"] == "CostOfGoodsAndServicesSold"].iloc[0]
        self.assertAlmostEqual(
            cost[metric_column("percent_of_revenue", PERIODS[0])],
            0.5,
        )
        gross_profit = pnl.loc[pnl["standard_concept"] == "GrossProfit"].iloc[0]
        self.assertAlmostEqual(gross_profit[metric_column("gross_margin", PERIODS[0])], 0.5)
        operating_income = pnl.loc[pnl["standard_concept"] == "OperatingIncomeLoss"].iloc[0]
        self.assertAlmostEqual(
            operating_income[metric_column("operating_margin", PERIODS[0])],
            0.25,
        )
        tax = pnl.loc[pnl["standard_concept"] == "IncomeTaxes"].iloc[0]
        self.assertAlmostEqual(
            tax[metric_column("effective_tax_rate", PERIODS[0])],
            0.2,
        )

    def test_prepare_pnl_calculates_guarded_changes_and_two_year_cagr(self) -> None:
        source = make_income_statement()
        pnl = prepare_pnl(source, years=3)

        revenue = pnl.loc[pnl["standard_concept"] == "Revenue"].iloc[0]
        self.assertAlmostEqual(
            revenue[metric_column("absolute_yoy_change", PERIODS[0])], 20.0
        )
        self.assertAlmostEqual(
            revenue[metric_column("yoy_growth", PERIODS[0])], 0.2
        )
        self.assertAlmostEqual(
            revenue["two_year_cagr"], (120.0 / 80.0) ** 0.5 - 1.0
        )

        negative = pnl.loc[
            pnl["standard_concept"] == "NonoperatingIncomeExpense"
        ].iloc[0]
        self.assertTrue(pd.isna(negative[metric_column("yoy_growth", PERIODS[1])]))
        self.assertEqual(
            negative[metric_column("absolute_yoy_change", PERIODS[1])], -1.0
        )
        self.assertTrue(pd.isna(negative[metric_column("yoy_growth", PERIODS[0])]))
        self.assertEqual(
            negative[metric_column("absolute_yoy_change", PERIODS[0])], 8.0
        )
        self.assertTrue(pd.isna(negative["two_year_cagr"]))

        zero_prior = source.copy(deep=True)
        zero_prior.loc[zero_prior["standard_concept"] == "Revenue", PERIODS[1]] = 0.0
        zero_pnl = prepare_pnl(zero_prior, years=3)
        zero_revenue = zero_pnl.loc[
            zero_pnl["standard_concept"] == "Revenue"
        ].iloc[0]
        self.assertTrue(pd.isna(zero_revenue[metric_column("yoy_growth", PERIODS[0])]))
        self.assertEqual(
            zero_revenue[metric_column("absolute_yoy_change", PERIODS[0])], 120.0
        )

        zero_endpoint = source.copy(deep=True)
        zero_endpoint.loc[
            zero_endpoint["standard_concept"] == "Revenue", PERIODS[2]
        ] = 0.0
        zero_endpoint_pnl = prepare_pnl(zero_endpoint, years=3)
        self.assertTrue(
            pd.isna(
                zero_endpoint_pnl.loc[
                    zero_endpoint_pnl["standard_concept"] == "Revenue"
                ].iloc[0]["two_year_cagr"]
            )
        )

        missing = pnl.loc[
            pnl["standard_concept"] == "ResearchAndDevelopmentExpenses"
        ].iloc[0]
        for metric in (
            "absolute_yoy_change",
            "yoy_growth",
            "percent_of_revenue",
            "percent_of_revenue_bps_change",
        ):
            self.assertTrue(pd.isna(missing[metric_column(metric, PERIODS[0])]))
        self.assertTrue(pd.isna(missing["two_year_cagr"]))

    def test_prepare_pnl_calculates_common_size_and_bps_movements(self) -> None:
        source = make_income_statement()
        source.loc[
            source["standard_concept"] == "CostOfGoodsAndServicesSold", PERIODS[0]
        ] = 66.0
        pnl = prepare_pnl(source, years=3)

        cost = pnl.loc[
            pnl["standard_concept"] == "CostOfGoodsAndServicesSold"
        ].iloc[0]
        self.assertAlmostEqual(
            cost[metric_column("percent_of_revenue", PERIODS[0])], 0.55
        )
        self.assertAlmostEqual(
            cost[metric_column("percent_of_revenue_bps_change", PERIODS[0])], 500.0
        )
        self.assertTrue(
            pd.isna(cost[metric_column("percent_of_revenue_bps_change", PERIODS[2])])
        )

    def test_prepare_pnl_excludes_eps_and_share_common_size_metrics(self) -> None:
        extra_rows = pd.DataFrame(
            {
                "concept": [
                    "us-gaap_EarningsPerShareBasic",
                    "us-gaap_WeightedAverageNumberOfSharesOutstandingBasic",
                    "custom_shares",
                    "custom_revenue_per_share",
                ],
                "label": [
                    "Basic EPS",
                    "Basic shares",
                    "Shares outstanding",
                    "Revenue per share",
                ],
                "standard_concept": [
                    None,
                    "SharesAverage",
                    "CustomMetric",
                    "CustomMetric",
                ],
                PERIODS[0]: [18.0, 7429.0, 7430.0, 2.0],
                PERIODS[1]: [13.7, 7433.0, 7431.0, 1.8],
                PERIODS[2]: [11.86, 7431.0, 7432.0, 1.6],
                "abstract": [False, False, False, False],
            }
        )
        pnl = prepare_pnl(
            pd.concat([make_income_statement(), extra_rows], ignore_index=True)
        )

        for label in ("Basic EPS", "Basic shares", "Shares outstanding", "Revenue per share"):
            row = pnl.loc[pnl["label"] == label].iloc[0]
            for period in PERIODS[:3]:
                self.assertTrue(pd.isna(row[metric_column("percent_of_revenue", period)]))
                self.assertTrue(
                    pd.isna(
                        row[metric_column("percent_of_revenue_bps_change", period)]
                    )
                )
            self.assertTrue(pd.notna(row[metric_column("yoy_growth", PERIODS[0])]))
            self.assertTrue(pd.notna(row["two_year_cagr"]))

    def test_prepare_pnl_preserves_monetary_gross_profit_with_margin_label(self) -> None:
        source = make_income_statement()
        source.loc[source["standard_concept"] == "GrossProfit", "label"] = "Gross margin"

        pnl = prepare_pnl(source)
        gross_profit = pnl.loc[pnl["standard_concept"] == "GrossProfit"].iloc[0]

        self.assertAlmostEqual(
            gross_profit[metric_column("percent_of_revenue", PERIODS[0])], 0.5
        )

    def test_prepare_pnl_exposes_all_margin_levels_and_bps_changes(self) -> None:
        source = make_income_statement()
        source.loc[
            source["standard_concept"] == "GrossProfit", PERIODS[0]
        ] = 66.0
        source.loc[
            source["standard_concept"] == "OperatingIncomeLoss", PERIODS[0]
        ] = 33.0
        pnl = prepare_pnl(source, years=3)

        expected = {
            "GrossProfit": ("gross_margin", 0.55, 500.0),
            "OperatingIncomeLoss": ("operating_margin", 0.275, 250.0),
            "PretaxIncomeLoss": ("pretax_margin", 35.0 / 120.0, (35.0 / 120.0 - 0.3) * 10_000),
            "NetIncome": ("net_margin", 28.0 / 120.0, (28.0 / 120.0 - 0.24) * 10_000),
            "IncomeTaxes": ("effective_tax_rate", 0.2, 0.0),
        }
        for concept, (metric, level, bps) in expected.items():
            row = pnl.loc[pnl["standard_concept"] == concept].iloc[0]
            self.assertAlmostEqual(row[metric_column(metric, PERIODS[0])], level)
            self.assertAlmostEqual(
                row[metric_column(f"{metric}_bps_change", PERIODS[0])], bps
            )

    def test_prepare_pnl_rejects_too_few_annual_periods(self) -> None:
        source = make_income_statement().drop(columns=[PERIODS[2], PERIODS[3]])

        with self.assertRaisesRegex(ValueError, "at least 3 annual periods"):
            prepare_pnl(source, years=3)


class SavePnlTests(TestCase):
    def test_save_analytical_pnl_writes_readable_csv(self) -> None:
        pnl = prepare_pnl(make_income_statement())

        with TemporaryDirectory() as temporary_directory:
            output_path = save_analytical_pnl(" msft ", pnl, temporary_directory)

            self.assertEqual(
                output_path,
                Path(temporary_directory)
                / "MSFT"
                / "03_output"
                / "analytical_pnl.csv",
            )
            saved = pd.read_csv(output_path)

        revenue = saved.loc[saved["standard_concept"] == "Revenue"].iloc[0]
        self.assertEqual(revenue[PERIODS[0]], 120.0)
        self.assertEqual(revenue[PERIODS[1]], 100.0)
        self.assertAlmostEqual(
            revenue[metric_column("yoy_change", PERIODS[0])],
            0.2,
        )

    def test_build_analytical_pnl_uses_income_statement_only(self) -> None:
        statements = {
            "income_statement": make_income_statement().rename(
                columns={period: period.removesuffix(" (FY)") for period in PERIODS}
            ),
            "balance_sheet": pd.DataFrame({"concept": ["Assets"]}),
            "cash_flow_statement": pd.DataFrame({"concept": ["Cash flow"]}),
        }

        with patch(
            "smrik_fund.ingestion.statements.get_statements",
            return_value=statements,
        ) as get_statements_mock:
            result = build_analytical_pnl("MSFT")

        get_statements_mock.assert_called_once_with("MSFT")
        self.assertEqual(len(result), len(statements["income_statement"]))
        self.assertNotIn("Assets", result["label"].tolist())
        self.assertIn(PERIODS[0], result.columns)
