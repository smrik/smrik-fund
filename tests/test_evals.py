"""Tests for the evaluation harness.

These exercise harness behaviour, not product quality: a case that fails is a
correct harness outcome as long as the failure is captured faithfully and kept
distinct from every other failure mode.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from smrik_fund.evals import cases as case_registry
from smrik_fund.evals import checks as mechanical
from smrik_fund.evals import judge as judging
from smrik_fund.evals import report, runner
from smrik_fund.evals.client import CallBudgetExceeded, RecordingClient
from smrik_fund.ingestion.filing_investigation import FinancialInvestigationResult

PACKET = """\
# MSFT finding-4 evidence

Ticker: MSFT
Topic: finding-4
Form: 10-K
Filing accession: 0001193125-26-323660
Filing date: 2026-07-29
Period of report: 2026-06-30
Primary document: msft-20260630.htm
Filing URL: https://www.sec.gov/Archives/edgar/data/789019/x/msft-20260630.htm
Source: https://www.sec.gov/Archives/edgar/data/789019/x/acc.txt
Text URL: https://www.sec.gov/Archives/edgar/data/789019/x/acc.txt
Retrieval method: EdgarTools EntityFiling.search literal section hits

## Filing excerpts

### E1
Query: Operating income increased
Source: https://www.sec.gov/Archives/edgar/data/789019/x/acc.txt
Section: EntityFiling search section loc 178
Locator: accession 0001193125-26-323660; search section loc(s) 178; source text lines 1162-1162; source text offsets 162928-162954

> Operating income increased driven by growth in Productivity and Business Processes and Intelligent Cloud.
"""


def _result(**overrides) -> FinancialInvestigationResult:
	base = {
		"disclosed_drivers": [
			{
				"description": "Segment operating performance improved.",
				"amount": None,
				"evidence_refs": ["E1"],
			}
		],
		"interpretation": "Margins expanded across segments.",
		"interpretation_evidence_refs": ["E1"],
		"unresolved_remainder": "The remaining movement is not disclosed.",
		"explanation": "Operating income rose on segment performance.",
		"explanation_evidence_refs": ["E1"],
	}
	base.update(overrides)
	return FinancialInvestigationResult.model_validate(base)


def _payload(status: str = "completed", **extra) -> dict:
	payload = {
		"status": status,
		"observed_movement": [
			{
				"periods": {"2026-06-30 (FY)": 1.0},
				"year_over_year": [
					{"period": "2026-06-30 (FY)", "previous_period": "2025-06-30 (FY)"}
				],
			}
		],
		"investigation": {"result": _result().model_dump(mode="json")},
		"retrieval": {"expansion": {"status": "accepted", "accepted_query_count": 2}},
	}
	payload.update(extra)
	return payload


@pytest.fixture
def pnl() -> pd.DataFrame:
	return pd.DataFrame(
		{"2026-06-30 (FY)": [281_724.0, 139_996.0], "2025-06-30 (FY)": [255_015.0, 120_810.0]}
	)


class _StubJudge:
	"""Return a fixed structured verdict without touching the network."""

	def __init__(self, verdict: str = "PASS", *, fail: bool = False) -> None:
		self.verdict, self.fail, self.calls = verdict, fail, 0
		self.responses = self

	def parse(self, **kwargs):
		self.calls += 1
		if self.fail:
			raise RuntimeError("judge transport failure")
		parsed = judging.JudgeResult(
			overall=self.verdict,
			dimensions=[
				{"dimension": "evidence_grounding", "verdict": self.verdict, "reason": "ok"}
			],
			summary="stub verdict",
		)
		return SimpleNamespace(output_parsed=parsed, usage=None)


def _run_case(
	tmp_path: Path,
	monkeypatch,
	case,
	*,
	product,
	judge_client=None,
	product_validator="PASS",
):
	monkeypatch.setattr(runner, "investigate_finding", product)
	# The product's own validator is exercised directly in the check-level tests
	# and in the offline dry-run; here we are testing lifecycle wiring, so its
	# verdict is supplied rather than re-derived from a synthetic packet.
	monkeypatch.setattr(
		runner.mechanical,
		"product_validator",
		lambda result, packet, periods: mechanical.check(
			"product_validator", product_validator, critical=True
		),
	)
	monkeypatch.setattr(
		runner.case_inputs,
		"load",
		lambda c, root: SimpleNamespace(
			pnl=pd.DataFrame({"2026-06-30 (FY)": [1.0]}),
			filing=None,
			finding=None,
			scan_context="",
			scan_metadata={},
			segments=None,
		),
	)
	monkeypatch.setattr(
		runner.mechanical,
		"source_integrity",
		lambda c, root: mechanical.check("source_integrity", "PASS", critical=True, verified=1),
	)
	return runner.run_case(
		case,
		case_dir=tmp_path / case["case_id"],
		repository_root=tmp_path,
		client_factory=lambda: SimpleNamespace(responses=SimpleNamespace(parse=None)),
		judge_client_factory=(lambda: judge_client) if judge_client else None,
		max_calls=None,
	)


@pytest.fixture
def ready_case() -> dict:
	return case_registry.discover(case_id="msft_segment_profitability_margin")[0]


# --- discovery and definition integrity ------------------------------------


def test_discovery_filters_by_suite_and_ticker():
	assert {c["case_id"] for c in case_registry.discover(suite="regression")} == {
		"msft_openai_nonoperating_quantified",
		"msft_operating_expense_multi_driver",
	}
	assert len(case_registry.discover(ticker="GOOGL")) == 1
	with pytest.raises(ValueError):
		case_registry.discover(suite="nonexistent")


def test_definition_hash_ignores_reference_output(ready_case):
	baseline = case_registry.case_hash(ready_case)
	drifted = dict(ready_case, reference_investigation="some/other/path.json")
	assert case_registry.case_hash(drifted) == baseline, (
		"a refreshed reference artifact must not make runs non-comparable"
	)


def test_definition_hash_tracks_inputs_and_judge_config(ready_case):
	cases = [ready_case]
	digest, _ = case_registry.definition_hash(
		cases, judge_prompt="p", judge_schema={"a": 1}
	)
	changed_prompt, _ = case_registry.definition_hash(
		cases, judge_prompt="different", judge_schema={"a": 1}
	)
	changed_input, _ = case_registry.definition_hash(
		[dict(ready_case, source_sha256="DEADBEEF")],
		judge_prompt="p",
		judge_schema={"a": 1},
	)
	assert digest != changed_prompt
	assert digest != changed_input


# --- lifecycle states -------------------------------------------------------


def test_completed_case_is_judged(tmp_path, monkeypatch, ready_case):
	stub = _StubJudge("PASS")

	def product(*args, **kwargs):
		Path(kwargs["output_root"]).mkdir(parents=True, exist_ok=True)
		evidence = Path(kwargs["output_root"]) / "packet.md"
		evidence.write_text(PACKET, encoding="utf-8")
		return _payload(evidence_path=str(evidence)), evidence

	record = _run_case(
		tmp_path, monkeypatch, ready_case, product=product, judge_client=stub
	)
	assert record["product_status"] == "COMPLETED"
	assert record["product_valid"] is True
	assert record["judge_status"] == "JUDGED"
	assert record["qualitative_verdict"] == "PASS"
	assert record["calls"]["judge"] == 1
	assert stub.calls == 1


def test_validation_rejected_preserves_raw_output_and_skips_judge(
	tmp_path, monkeypatch, ready_case
):
	stub = _StubJudge("PASS")

	def product(*args, **kwargs):
		# The recording client saw the model output before validation rejected it.
		kwargs["client"].calls.append(
			{
				"stage": "FinancialInvestigationResult",
				"model": "gpt-5.6-luna",
				"reasoning_effort": "high",
				"output": {"disclosed_drivers": []},
				"usage": None,
			}
		)
		return (
			_payload("failed", error_stage="investigation", error_message="rejected"),
			tmp_path / "artifact.json",
		)

	record = _run_case(
		tmp_path, monkeypatch, ready_case, product=product, judge_client=stub
	)
	assert record["product_status"] == "VALIDATION_REJECTED"
	assert record["product_valid"] is False
	assert record["judge_status"] == "JUDGE_SKIPPED"
	assert stub.calls == 0, "invalid output must never reach the judge"

	saved = json.loads(
		(tmp_path / ready_case["case_id"] / "rejected_output.json").read_text()
	)
	assert saved["trust"] == "UNTRUSTED"
	assert saved["disposition"] == "REJECTED"
	assert saved["calls"][0]["output"] == {"disclosed_drivers": []}


def test_execution_error_is_isolated_and_traced(tmp_path, monkeypatch, ready_case):
	def product(*args, **kwargs):
		raise RuntimeError("model transport exploded")

	record = _run_case(tmp_path, monkeypatch, ready_case, product=product)
	assert record["product_status"] == "EXECUTION_ERROR"
	assert record["judge_status"] == "JUDGE_SKIPPED"
	assert "exploded" in record["error"]
	assert (tmp_path / ready_case["case_id"] / "traceback.txt").is_file()


def test_judge_error_leaves_product_valid(tmp_path, monkeypatch, ready_case):
	def product(*args, **kwargs):
		Path(kwargs["output_root"]).mkdir(parents=True, exist_ok=True)
		evidence = Path(kwargs["output_root"]) / "packet.md"
		evidence.write_text(PACKET, encoding="utf-8")
		return _payload(evidence_path=str(evidence)), evidence

	record = _run_case(
		tmp_path,
		monkeypatch,
		ready_case,
		product=product,
		judge_client=_StubJudge(fail=True),
	)
	assert record["product_valid"] is True, (
		"a judge failure must not convert a valid product result into a failure"
	)
	assert record["judge_status"] == "JUDGE_ERROR"
	assert record["qualitative_verdict"] is None


def test_critical_check_failure_skips_the_judge(tmp_path, monkeypatch, ready_case):
	stub = _StubJudge("PASS")

	def product(*args, **kwargs):
		Path(kwargs["output_root"]).mkdir(parents=True, exist_ok=True)
		evidence = Path(kwargs["output_root"]) / "packet.md"
		evidence.write_text(PACKET, encoding="utf-8")
		return _payload(evidence_path=str(evidence)), evidence

	record = _run_case(
		tmp_path,
		monkeypatch,
		ready_case,
		product=product,
		judge_client=stub,
		product_validator="FAIL",
	)
	assert record["product_status"] == "COMPLETED"
	assert record["product_valid"] is False
	assert record["judge_status"] == "JUDGE_SKIPPED"
	assert stub.calls == 0


def test_blocked_case_records_prerequisite():
	case = case_registry.discover(case_id="amzn_capability_probe")[0]
	record = runner._blocked_record(case)
	assert record["case_status"] == "BLOCKED"
	assert record["capability"] == "UNAVAILABLE"
	assert record["product_status"] == "NOT_RUN"
	assert record["missing_prerequisite"]
	assert record["expected_workflow"]


# --- checks -----------------------------------------------------------------


def test_checks_are_independent(pnl):
	"""One failing validator must not mark unrelated checks as failed."""
	result = _result(
		disclosed_drivers=[
			{
				"description": "Segment revenue rose.",
				"amount": 139_996.0,
				"amount_unit": "dollars",
				"period": "2026-06-30 (FY)",
				"evidence_span": "Operating income increased",
				"evidence_refs": ["E1"],
			}
		]
	)
	verdicts = {
		c["id"]: c["status"]
		for c in (
			mechanical.evidence_refs(result, PACKET),
			mechanical.numeric_grounding(result, pnl, None),
			mechanical.amount_basis(result),
		)
	}
	assert verdicts == {
		"evidence_refs": "PASS",
		"numeric_grounding": "PASS",
		"amount_basis": "PASS",
	}
	assert len(set(verdicts)) == 3, "each check must have its own identity"


def test_numeric_grounding_rejects_an_invented_figure(pnl):
	result = _result(
		explanation="Operating income rose by 987.654 billion on segment strength."
	)
	verdict = mechanical.numeric_grounding(result, pnl, None)
	assert verdict["status"] == "FAIL"
	assert verdict["ungrounded"][0]["location"] == "explanation"


def test_numeric_grounding_accepts_a_computed_segment_margin(pnl):
	segments = pd.DataFrame({"operating_margin": [0.599153], "numeric_value": [1.0]})
	result = _result(interpretation="Segment margin reached 59.92%.")
	assert mechanical.numeric_grounding(result, pnl, segments)["status"] == "PASS"


def test_numeric_grounding_is_not_applicable_when_no_figures_are_stated(pnl):
	"""A figure-free output must not report a passing grounding check."""
	result = _result(
		interpretation="Margins expanded.",
		explanation="The packet reports the movement.",
		unresolved_remainder="No further detail is disclosed.",
	)
	verdict = mechanical.numeric_grounding(result, pnl, None)
	assert verdict["status"] == "NOT_APPLICABLE"
	assert verdict["checked"] == 0
	assert not mechanical.is_critical_failure([verdict])


def test_amount_basis_is_not_applicable_without_quantified_drivers():
	verdict = mechanical.amount_basis(_result())
	assert verdict["status"] == "NOT_APPLICABLE"
	assert verdict["quantified"] == 0


def test_summary_separates_vacuous_checks_from_passes():
	iteration = {
		"iteration_id": "i1",
		"definition_hash": "a" * 64,
		"judge": {"model": "gpt-5.6-sol", "reasoning_effort": "high"},
		"calls": {"product": 2, "judge": 1},
		"preflight": {"status": "PASS"},
		"repository": {"head_sha": "b" * 40, "dirty": False},
		"cases": [
			{
				"case_id": "c1",
				"case_status": "READY",
				"product_status": "COMPLETED",
				"product_valid": True,
				"judge_status": "JUDGED",
				"qualitative_verdict": "FAIL",
				"checks": [
					mechanical.check(
						"numeric_grounding",
						"NOT_APPLICABLE",
						critical=True,
						reason="output stated no figures to ground",
					)
				],
			}
		],
	}
	markdown = report.summarize(iteration)
	assert "Checks with nothing to examine" in markdown
	assert "no figures to ground" in markdown


def test_evidence_refs_rejects_unknown_reference():
	result = _result(explanation_evidence_refs=["E9"])
	verdict = mechanical.evidence_refs(result, PACKET)
	assert verdict["status"] == "FAIL"
	assert verdict["unknown_refs"] == ["E9"]


def test_amount_basis_requires_period_and_span():
	result = _result(
		disclosed_drivers=[
			{
				"description": "Quantified driver.",
				"amount": 6_500_000_000.0,
				"amount_unit": "dollars",
				"evidence_refs": ["E1"],
			}
		]
	)
	verdict = mechanical.amount_basis(result)
	assert verdict["status"] == "FAIL"
	assert set(verdict["incomplete"][0]["missing"]) == {"period", "evidence_span"}


def test_critical_failure_gates_the_judge():
	assert mechanical.is_critical_failure(
		[mechanical.check("numeric_grounding", "FAIL", critical=True)]
	)
	assert not mechanical.is_critical_failure(
		[mechanical.check("quantification", "FAIL", critical=False)]
	)


# --- analyst and scan checks ------------------------------------------------


def _candidate(**overrides):
	from smrik_fund.ingestion.adjustment_analysis import AnalystCandidate

	base = {
		"target_line": "Research and development",
		"period": "2026-06-30 (FY)",
		"item_amount": 1.4e9,
		"item_effect_on_line": "increased_line",
		"amount_basis": "disclosed",
		"reason": "One-off charge.",
		"evidence_refs": ["E1"],
	}
	base.update(overrides)
	return AnalystCandidate.model_validate(base)


@pytest.fixture
def candidate_pnl() -> pd.DataFrame:
	return pd.DataFrame(
		{
			"label": ["Research and development", "Revenue"],
			"2026-06-30 (FY)": [35_562.0, 331_839.0],
		}
	)


def test_candidate_fields_accepts_a_valid_candidate(candidate_pnl):
	verdicts = {
		c["id"]: c["status"]
		for c in mechanical.candidate_fields([_candidate()], candidate_pnl, PACKET)
	}
	assert verdicts["candidate_found"] == "PASS"
	assert verdicts["candidate_fields"] == "PASS"
	# No human-verified expected candidate exists, so this must not read as a pass.
	assert verdicts["candidate_matches_expected"] == "NOT_APPLICABLE"


def test_candidate_fields_rejects_no_candidates(candidate_pnl):
	verdict = mechanical.candidate_fields([], candidate_pnl, PACKET)[0]
	assert verdict["id"] == "candidate_found"
	assert verdict["status"] == "FAIL"


@pytest.mark.parametrize(
	("override", "field"),
	[
		({"target_line": "Invented line"}, "target_line"),
		({"period": "2099-06-30 (FY)"}, "period"),
		({"evidence_refs": ["E9"]}, "evidence_refs"),
		({"item_amount": -1.0}, "item_amount"),
	],
)
def test_candidate_fields_catches_each_bad_field(candidate_pnl, override, field):
	results = mechanical.candidate_fields(
		[_candidate(**override)], candidate_pnl, PACKET
	)
	failed = next(c for c in results if c["id"] == "candidate_fields")
	assert failed["status"] == "FAIL"
	assert failed["problems"][0]["field"] == field


def test_candidate_matches_expected(candidate_pnl):
	expected = {
		"target_line": "Research and development",
		"period": "2026-06-30 (FY)",
		"item_amount": 1.4e9,
	}
	results = mechanical.candidate_fields(
		[_candidate()], candidate_pnl, PACKET, expected=expected
	)
	assert results[-1]["status"] == "PASS"

	results = mechanical.candidate_fields(
		[_candidate(item_amount=9.9e9)], candidate_pnl, PACKET, expected=expected
	)
	assert results[-1]["status"] == "FAIL"


def test_scan_findings_requires_at_least_one_movement():
	assert mechanical.scan_findings([])["status"] == "FAIL"
	finding = SimpleNamespace(affected_line_refs=["L01", "S02"])
	verdict = mechanical.scan_findings([finding])
	assert verdict["status"] == "PASS"
	assert verdict["findings"] == 1 and verdict["refs_cited"] == 2


# --- adjustment set ---------------------------------------------------------


def _history_row(
	adjustment_id: str,
	target_row_key: str,
	item_key: str,
	period: str,
	line_delta: float,
	status: str,
) -> dict:
	identity = {
		"company": "MSFT",
		"fiscal_period": period,
		"identity_version": "economic-adjustment-v2",
		"item_key": item_key,
		"target_row_key": target_row_key,
	}
	state = {
		"amount_basis": "disclosed",
		"item_amount": abs(line_delta),
		"item_effect_on_line": "increased_line",
	}
	return {
		"adjustment_id": adjustment_id,
		"version": 1,
		"status": status,
		"identity_version": "economic-adjustment-v2",
		"candidate_identity": json.dumps(identity, sort_keys=True),
		"candidate_state": json.dumps(state, sort_keys=True),
		"company": "MSFT",
		"fiscal_period": period,
		"target_row_key": target_row_key,
		"item_key": item_key,
		"target_line": "Provision for income taxes",
		"period": period,
		"item_amount": abs(line_delta),
		"item_effect_on_line": "increased_line",
		"amount_basis": "disclosed",
		"line_delta": line_delta,
	}


TAX_KEY = "standard_concept:IncomeTaxes"
RD_KEY = "standard_concept:ResearchAndDevelopmentExpenses"
FY26 = "2026-06-30 (FY)"
EXPECTED_TAX = [{"target": TAX_KEY, "period": FY26, "line_delta": -1.4e9}]


def test_adjustment_set_accepts_the_expected_adjustment():
	history = pd.DataFrame(
		[_history_row("A0001", TAX_KEY, "utp-interest", FY26, -1.4e9, "approved")]
	)
	verdict = mechanical.adjustment_set(history, EXPECTED_TAX)
	assert verdict["status"] == "PASS"
	assert verdict["approved"] == 1


def test_adjustment_set_ignores_unapproved_versions():
	history = pd.DataFrame(
		[
			_history_row("A0001", TAX_KEY, "utp-interest", FY26, -1.4e9, "approved"),
			_history_row("A0002", RD_KEY, "rd-one-off", FY26, -5.0e8, "proposed"),
		]
	)
	assert mechanical.adjustment_set(history, EXPECTED_TAX)["status"] == "PASS"


def test_adjustment_set_catches_over_adjustment():
	"""An extra approved adjustment elsewhere is the failure this check exists for."""
	history = pd.DataFrame(
		[
			_history_row("A0001", TAX_KEY, "utp-interest", FY26, -1.4e9, "approved"),
			_history_row("A0002", RD_KEY, "rd-one-off", FY26, -5.0e8, "approved"),
		]
	)
	verdict = mechanical.adjustment_set(history, EXPECTED_TAX)
	assert verdict["status"] == "FAIL"
	assert verdict["unexpected"] == [
		{"target": RD_KEY, "period": FY26, "applied": -5.0e8}
	]


def test_adjustment_set_catches_a_wrong_amount():
	history = pd.DataFrame(
		[_history_row("A0001", TAX_KEY, "utp-interest", FY26, -9.9e9, "approved")]
	)
	verdict = mechanical.adjustment_set(history, EXPECTED_TAX)
	assert verdict["status"] == "FAIL"
	assert verdict["wrong_amount"][0]["applied"] == -9.9e9


def test_adjustment_set_catches_a_missing_adjustment():
	history = pd.DataFrame(
		[_history_row("A0002", RD_KEY, "rd-one-off", FY26, -5.0e8, "approved")]
	)
	verdict = mechanical.adjustment_set(history, EXPECTED_TAX)
	assert verdict["status"] == "FAIL"
	assert verdict["missing"] == [{"target": TAX_KEY, "period": FY26}]


def test_adjustment_set_is_not_applicable_without_approvals():
	history = pd.DataFrame(
		[_history_row("A0001", TAX_KEY, "utp-interest", FY26, -1.4e9, "rejected")]
	)
	verdict = mechanical.adjustment_set(history, EXPECTED_TAX)
	assert verdict["status"] == "NOT_APPLICABLE"
	assert verdict["approved"] == 0


def test_adjustment_set_fails_closed_on_unresolvable_history():
	"""Legacy or corrupted identity must not silently read as 'nothing applied'."""
	history = pd.DataFrame(
		[
			{
				"adjustment_id": "A0001",
				"version": 1,
				"status": "approved",
				"target_line": "Research and development",
				"period": FY26,
				"line_delta": -1.0e9,
			}
		]
	)
	verdict = mechanical.adjustment_set(history, EXPECTED_TAX)
	assert verdict["status"] == "FAIL"
	assert "unresolvable history" in verdict["reason"]


# --- recording client -------------------------------------------------------


def test_recording_client_counts_and_captures():
	class _Inner:
		def __init__(self):
			self.responses = SimpleNamespace(parse=self._parse)

		def _parse(self, **kwargs):
			return SimpleNamespace(
				output_parsed=judging.JudgeResult(
					overall="PASS",
					dimensions=[{"dimension": "d", "verdict": "PASS", "reason": "r"}],
					summary="s",
				),
				usage=None,
			)

	client = RecordingClient(_Inner())
	client.responses.parse(
		model="m", reasoning={"effort": "high"}, text_format=judging.JudgeResult
	)
	assert client.call_count == 1
	assert client.stage_counts() == {"JudgeResult": 1}
	assert client.raw_outputs()[0]["output"]["overall"] == "PASS"


def test_recording_client_enforces_budget():
	client = RecordingClient(SimpleNamespace(responses=None), max_calls=0)
	with pytest.raises(CallBudgetExceeded):
		client.responses.parse(model="m")


# --- comparison -------------------------------------------------------------


def _iteration(digest: str, verdict: str, dimension: str) -> dict:
	return {
		"iteration_id": f"iter-{verdict}",
		"definition_hash": digest,
		"cases": [
			{
				"case_id": "msft_segment_profitability_margin",
				"product_status": "COMPLETED",
				"product_valid": True,
				"qualitative_verdict": verdict,
				"judge": {
					"dimensions": [
						{"dimension": "margin_reuse", "verdict": dimension, "reason": "r"}
					]
				},
			}
		],
	}


def test_comparison_reports_dimension_deltas():
	delta = report.compare(
		_iteration("abc", "PASS", "PASS"), _iteration("abc", "PARTIAL", "FAIL")
	)
	assert delta["status"] == "COMPARABLE"
	case = delta["cases"][0]
	assert case["overall"]["direction"] == "improved"
	assert case["dimensions"][0] == {
		"dimension": "margin_reuse",
		"baseline": "FAIL",
		"current": "PASS",
		"direction": "improved",
	}
	assert "KEEP/REVERT" in delta["note"]


def test_comparison_refuses_a_different_definition():
	delta = report.compare(
		_iteration("abc", "PASS", "PASS"), _iteration("xyz", "PASS", "PASS")
	)
	assert delta["status"] == "NON_COMPARABLE"


def test_summary_markdown_lists_every_case():
	iteration = {
		"iteration_id": "i1",
		"definition_hash": "a" * 64,
		"judge": {"model": "gpt-5.6-sol", "reasoning_effort": "high"},
		"calls": {"product": 8, "judge": 4},
		"preflight": {"status": "PASS"},
		"repository": {"head_sha": "b" * 40, "dirty": True},
		"cases": [
			{
				"case_id": "c1",
				"case_status": "READY",
				"product_status": "COMPLETED",
				"product_valid": True,
				"judge_status": "JUDGED",
				"qualitative_verdict": "PARTIAL",
				"checks": [
					mechanical.check(
						"numeric_grounding", "FAIL", critical=True, reason="drift"
					)
				],
				"judge": {
					"dimensions": [
						{"dimension": "margin_reuse", "verdict": "FAIL", "reason": "r"}
					]
				},
			}
		],
	}
	markdown = report.summarize(iteration)
	assert "c1" in markdown
	assert "numeric_grounding" in markdown
	assert "margin_reuse" in markdown
