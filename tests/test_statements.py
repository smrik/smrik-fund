from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

import pandas as pd
from typer.testing import CliRunner

from smrik_fund.ingestion.edgar_import import FilingRow, import_edgar_filings
from smrik_fund.ingestion.statements import (
    FilingMetadata,
    StatementArtifacts,
    parse_statement_artifacts,
    parse_statements,
    save_statement_artifacts,
)
from smrik_fund.main import app

STATEMENT_NAMES = (
    "income_statement",
    "balance_sheet",
    "cash_flow_statement",
)


def make_frames() -> dict[str, pd.DataFrame]:
    return {
        "income_statement": pd.DataFrame(
            {
                "concept": ["us-gaap_Revenue"],
                "label": ["Revenue"],
                "standard_concept": ["Revenue"],
                "2024-12-31 (FY)": [100.0],
            }
        ),
        "balance_sheet": pd.DataFrame(
            {
                "concept": ["us-gaap_Assets"],
                "label": ["Assets"],
                "standard_concept": ["Assets"],
                "2024-12-31": [200.0],
            }
        ),
        "cash_flow_statement": pd.DataFrame(
            {
                "concept": ["us-gaap_NetCashProvidedByUsedInOperatingActivities"],
                "label": ["Operating cash flow"],
                "standard_concept": ["OperatingCashFlow"],
                "2024-12-31 (FY)": [50.0],
            }
        ),
    }


def make_facts() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "fact_id": "fact-revenue",
                "concept": "us-gaap:Revenue",
                "label": "Revenue",
                "original_label": "Net sales",
                "value": 100.0,
                "numeric_value": 100.0,
                "unit_ref": "USD",
                "currency": "USD",
                "period_type": "duration",
                "period_start": "2024-01-01",
                "period_end": "2024-12-31",
                "period_key": "duration_2024-01-01_2024-12-31",
                "context_ref": "ctx-revenue",
                "statement_type": "IncomeStatement",
            },
            {
                "fact_id": "fact-assets",
                "concept": "us-gaap:Assets",
                "label": "Assets",
                "original_label": "Total assets",
                "value": 200.0,
                "numeric_value": 200.0,
                "unit_ref": "USD",
                "currency": "USD",
                "period_type": "instant",
                "period_instant": "2024-12-31",
                "period_key": "instant_2024-12-31",
                "context_ref": "ctx-assets",
                "statement_type": "BalanceSheet",
            },
            {
                "fact_id": "fact-cash-flow",
                "concept": "us-gaap:NetCashProvidedByUsedInOperatingActivities",
                "label": "Operating cash flow",
                "original_label": "Net cash from operating activities",
                "value": 50.0,
                "numeric_value": 50.0,
                "unit_ref": "USD",
                "currency": "USD",
                "period_type": "duration",
                "period_start": "2024-01-01",
                "period_end": "2024-12-31",
                "period_key": "duration_2024-01-01_2024-12-31",
                "context_ref": "ctx-cash-flow",
                "statement_type": "CashFlowStatement",
                "dim_us-gaap_ProductOrServiceAxis": "us-gaap:ServiceMember",
            },
        ]
    )


def make_artifacts() -> StatementArtifacts:
    facts = make_facts()
    facts["ingestion_fingerprint"] = ["fingerprint-1", "fingerprint-2", "fingerprint-3"]
    facts["ticker"] = "MSFT"
    facts["source"] = "edgar"
    facts["statement"] = [
        "income_statement",
        "balance_sheet",
        "cash_flow_statement",
    ]
    facts["standard_concept"] = ["Revenue", "Assets", "OperatingCashFlow"]
    facts["canonical_key"] = ["revenue", "assets", "operating_cash_flow"]
    facts["label"] = facts["original_label"]
    facts["unit"] = facts["unit_ref"]
    facts["scale_factor"] = 1.0
    facts["period"] = facts["period_key"]
    facts["period_kind"] = "reported"
    facts["filing_date"] = "2025-01-30"
    facts["form_type"] = "10-K"
    facts["accession"] = "0000000000-24-000001"
    facts["source_locator"] = "edgar:0000000000-24-000001:fact"
    facts["statement_role"] = ""
    facts["metadata"] = [{}, {}, {}]
    facts["dimensions"] = [
        {},
        {},
        {"us-gaap_ProductOrServiceAxis": "us-gaap:ServiceMember"},
    ]
    facts["is_derived"] = False
    facts["derivation"] = None
    facts["original_source"] = "edgar_xbrl"
    return StatementArtifacts(
        ticker="MSFT",
        cik="0000789019",
        filing=FilingMetadata(
            accession="0000000000-24-000001",
            filing_date="2025-01-30",
            form_type="10-K",
            period_of_report="2024-12-31",
            source_url="https://www.sec.gov/Archives/example.txt",
        ),
        statements=make_frames(),
        facts=facts,
        filing_text="Example 10-K filing text\n",
    )


class ParseStatementsTests(TestCase):
    def test_parse_statements_returns_standard_views_and_preserves_concepts(
        self,
    ) -> None:
        frames = make_frames()
        company = Mock()
        filing = company.get_filings.return_value.latest.return_value
        xbrl = filing.xbrl.return_value
        statement_methods = {
            "income_statement": xbrl.statements.income_statement,
            "balance_sheet": xbrl.statements.balance_sheet,
            "cash_flow_statement": xbrl.statements.cashflow_statement,
        }
        for name, method in statement_methods.items():
            method.return_value.to_dataframe.return_value = frames[name]

        with patch("smrik_fund.ingestion.parser.Company", return_value=company):
            result = parse_statements(" msft ")

        self.assertEqual(result, frames)
        company.get_filings.assert_called_once_with(form="10-K")
        company.get_filings.return_value.latest.assert_called_once_with()
        filing.xbrl.assert_called_once_with()
        for method in statement_methods.values():
            method.assert_called_once_with()
            method.return_value.to_dataframe.assert_called_once_with(view="standard")
        for frame in result.values():
            self.assertIn("concept", frame.columns)
            self.assertIn("standard_concept", frame.columns)

    def test_parse_statement_artifacts_adds_filing_metadata_and_long_facts(
        self,
    ) -> None:
        frames = make_frames()
        company = Mock()
        company.cik = "789019"
        filing = company.get_filings.return_value.latest.return_value
        filing.accession_number = "0000000000-24-000001"
        filing.filing_date = "2025-01-30"
        filing.form = "10-K"
        filing.period_of_report = "2024-12-31"
        filing.filing_url = "https://www.sec.gov/Archives/example.txt"
        filing.text.return_value = "Example 10-K filing text\n"
        xbrl = filing.xbrl.return_value
        for name, frame in frames.items():
            statement_method = getattr(
                xbrl.statements,
                "cashflow_statement" if name == "cash_flow_statement" else name,
            )
            statement_method.return_value.to_dataframe.return_value = frame
        xbrl.facts.to_dataframe.return_value = make_facts()

        with patch("smrik_fund.ingestion.parser.Company", return_value=company):
            result = parse_statement_artifacts(" msft ")

        self.assertEqual(result.ticker, "MSFT")
        self.assertEqual(result.cik, "0000789019")
        self.assertEqual(result.filing.accession, "0000000000-24-000001")
        self.assertEqual(len(result.facts), 3)
        self.assertEqual(
            set(result.facts["statement"]),
            set(STATEMENT_NAMES),
        )
        self.assertIn("standard_concept", result.facts.columns)
        self.assertEqual(
            result.facts.loc[
                result.facts["concept"] == "us-gaap:Revenue", "label"
            ].iloc[0],
            "Net sales",
        )
        filing.xbrl.assert_called_once_with()
        xbrl.facts.to_dataframe.assert_called_once_with()
        filing.text.assert_called_once_with()


class SaveStatementArtifactsTests(TestCase):
    def test_save_statement_artifacts_writes_ai_fund_layout(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            output_dir = save_statement_artifacts(make_artifacts(), temporary_directory)

            expected_dir = Path(temporary_directory) / "MSFT"
            self.assertEqual(output_dir, expected_dir)
            source_dir = expected_dir / "01_source" / "edgar"
            edgar_dir = expected_dir / "02_processing" / "edgar"
            index_path = source_dir / "filing_index.csv"
            manifest_path = source_dir / "manifest.json"
            filing_path = source_dir / "filings" / "0000000000-24-000001.txt"
            facts_path = edgar_dir / "facts.csv"
            coverage_path = edgar_dir / "coverage.json"

            for path in (
                index_path,
                manifest_path,
                filing_path,
                facts_path,
                coverage_path,
            ):
                self.assertTrue(path.is_file(), path)

            self.assertEqual(
                filing_path.read_text(encoding="utf-8"), "Example 10-K filing text\n"
            )
            facts = pd.read_csv(facts_path)
            self.assertEqual(len(facts), 3)
            for column in (
                "concept",
                "standard_concept",
                "statement",
                "numeric_value",
                "period_end",
                "accession",
                "source_locator",
                "dimensions",
            ):
                self.assertIn(column, facts.columns)
            self.assertEqual(
                json.loads(
                    facts.loc[
                        facts["concept"]
                        == "us-gaap:NetCashProvidedByUsedInOperatingActivities",
                        "dimensions",
                    ].iloc[0]
                ),
                {"us-gaap_ProductOrServiceAxis": "us-gaap:ServiceMember"},
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["ticker"], "MSFT")
            self.assertEqual(manifest["filing_count"], 1)
            coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
            self.assertEqual(coverage["fact_count"], 3)
            self.assertEqual(coverage["by_statement"]["balance_sheet"], 1)


class EdgarImportLayoutTests(TestCase):
    def test_edgar_import_uses_ticker_source_stage(self) -> None:
        company = Mock()
        company.cik = "789019"
        filing = Mock(
            form="10-K",
            accession_number="0000000000-26-000001",
            filing_date="2026-07-29",
            period_of_report="2026-06-30",
            filing_url="https://www.sec.gov/Archives/example.txt",
        )
        company.get_filings.return_value = [filing]
        expected_row = FilingRow(
            accession="0000000000-26-000001",
            filing_date="2026-07-29",
            form_type="10-K",
            period_of_report="2026-06-30",
            source_url="https://www.sec.gov/Archives/example.txt",
            output_path="filings/0000000000-26-000001.txt",
        )

        with TemporaryDirectory() as temporary_directory:
            with (
                patch(
                    "smrik_fund.ingestion.edgar_import.Company",
                    return_value=company,
                ),
                patch(
                    "smrik_fund.ingestion.edgar_import._download_filing",
                    return_value=expected_row,
                ) as download_filing,
            ):
                result = import_edgar_filings(
                    " msft ",
                    forms=("10-K",),
                    output_root=temporary_directory,
                )

            expected_root = Path(temporary_directory) / "MSFT"
            expected_source = expected_root / "01_source" / "edgar"
            self.assertEqual(result.output_dir, expected_root)
            download_filing.assert_called_once_with(
                filing,
                expected_source,
                refresh=False,
            )
            self.assertTrue((expected_source / "filing_index.csv").is_file())
            self.assertTrue((expected_source / "manifest.json").is_file())


class ParseCommandTests(TestCase):
    def test_parse_command_prints_artifact_path_and_dimensions(self) -> None:
        runner = CliRunner()
        artifacts = make_artifacts()
        output_dir = Path("data/MSFT")

        with (
            patch("smrik_fund.main.parse_statement_artifacts", return_value=artifacts),
            patch("smrik_fund.main.save_statement_artifacts", return_value=output_dir),
        ):
            result = runner.invoke(app, ["parse", "MSFT"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Saved: data\\MSFT", result.output)
        self.assertIn("facts: 3 rows", result.output)
        for name in STATEMENT_NAMES:
            self.assertIn(f"{name}: 1 rows x 4 columns", result.output)
