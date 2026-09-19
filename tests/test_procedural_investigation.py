from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from smrik_fund.evals import cases, checks
from smrik_fund.ingestion.analytical_scan import AnalyticalScanFinding
from smrik_fund.ingestion.procedural_investigation import (
	DriverAssessment,
	DriverAssessmentItem,
	DriverHypothesis,
	InvestigationDecomposition,
	run_procedural_investigation,
)
from smrik_fund.ingestion.statements import prepare_pnl


PACKET = """\
Ticker: MSFT
Filing accession: A1
Source: https://example.test/filing.txt

### E1
Source: https://example.test/filing.txt
Section: MD&A
Locator: accession A1; line 1

> Demand increased the reported line.
"""


def _pnl() -> pd.DataFrame:
	return prepare_pnl(
		pd.DataFrame(
			{
				"concept": ["Revenue"],
				"label": ["Revenue"],
				"standard_concept": ["Revenue"],
				"2026-06-30 (FY)": [110.0],
				"2025-06-30 (FY)": [100.0],
				"2024-06-30 (FY)": [90.0],
			}
		)
	)


def _finding() -> AnalyticalScanFinding:
	return AnalyticalScanFinding(
		rank=1,
		title="Revenue movement",
		importance="high",
		affected_line_refs=["L01"],
		observation="The reported line moved.",
		why_it_matters="The movement merits filing review.",
	)


class _Client:
	def __init__(self) -> None:
		self.calls: list[dict[str, object]] = []
		self.responses = SimpleNamespace(parse=self.parse)

	def parse(self, **kwargs: object) -> object:
		self.calls.append(kwargs)
		if len(self.calls) == 1:
			parsed = InvestigationDecomposition(
				hypotheses=[
					DriverHypothesis(
						name="Demand",
						question="Does the filing describe demand?",
						evidence_refs=["E1"],
					)
				]
			)
		elif len(self.calls) == 2:
			parsed = DriverAssessment(
				assessments=[
					DriverAssessmentItem(
						hypothesis="Demand",
						status="supported",
						description="Demand",
						evidence_refs=["E1"],
					)
				]
			)
		else:
			from smrik_fund.ingestion.filing_investigation import (
				FinancialInvestigationResult,
			)

			parsed = FinancialInvestigationResult(
				disclosed_drivers=[],
				interpretation="The supplied passage reports the movement.",
				interpretation_evidence_refs=["E1"],
				unresolved_remainder="Other components remain unresolved.",
				unresolved_remainder_evidence_refs=["E1"],
				explanation="The supplied passage reports the movement.",
				explanation_evidence_refs=["E1"],
			)
		return SimpleNamespace(output_parsed=parsed)


def test_procedural_arm_makes_three_calls_and_persists_trace(tmp_path: Path) -> None:
	client = _Client()
	trace_path = tmp_path / "trace.json"
	result, metadata, trace = run_procedural_investigation(
		"MSFT",
		_finding(),
		_pnl(),
		PACKET,
		expected_filing_accession="A1",
		client=client,
		run_id="case-1",
		trace_path=trace_path,
	)

	assert len(client.calls) == 3
	assert [call["text_format"].__name__ for call in client.calls] == [
		"InvestigationDecomposition",
		"DriverAssessment",
		"FinancialInvestigationResult",
	]
	assert metadata["call_count"] == 3
	assert trace["call_count"] == 3
	assert trace["deterministic_reconciliation"]["status"] == "not_computable"
	assert trace_path.is_file()
	assert json.loads(trace_path.read_text(encoding="utf-8"))["final_result"] == (
		result.model_dump(mode="json")
	)


def test_procedural_cases_are_a_paired_new_suite() -> None:
	selected = cases.discover(suite="procedural")
	assert {case["arm"] for case in selected} == {"one_shot", "procedural"}
	assert len(selected) == 4
	assert all(case.get("evidence_artifact") and case.get("evidence_sha256") for case in selected)


def test_evidence_hash_is_a_mechanical_frozen_input() -> None:
	case = {
		"evidence_artifact": "missing.md",
		"evidence_sha256": "ABC",
	}
	result = checks.source_integrity(case, ".")
	assert result["status"] == "FAIL"
	assert result["mismatches"][0]["input"] == "evidence_artifact"
