"""Frozen evaluation cases.

A case pins the *inputs* needed to reproduce one product execution: ticker,
accession, filing period, source text, analytical scan, segment analytics, and
the finding identity.  It never pins the product's own output.

That boundary is the reason this module exists.  An earlier harness folded the
frozen investigation artifact's hash into the definition hash, which made every
comparison NON_COMPARABLE the moment the product changed and its artifact was
refreshed.  Reference outputs are still recorded here for diagnosis, under
``reference_*`` keys, and are deliberately excluded from ``definition_hash``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

SUITES = ("development", "regression", "holdout")

JUDGE_MODEL = "gpt-5.6-sol"
JUDGE_REASONING_EFFORT = "high"

_SOURCE = "data/MSFT/01_source/edgar/filings/0001193125-26-323660.txt"
_SOURCE_SHA256 = "6DE4C42EBBF10AE75FCC6A5ED021823AADC6127D6471C84CB7A3BEAFAD1E1E68"
_SOURCE_MANIFEST = "data/MSFT/01_source/edgar/manifest.json"
_SOURCE_MANIFEST_SHA256 = (
	"3942859034A9DA686A26F657B79965F16D1A982F5390806145A3EFD4F65692B3"
)
_ACCESSION = "0001193125-26-323660"
_PERIOD = "2026-06-30"

_SEGMENT_ANALYTICS = (
	"data/live-segment-enrichment-i1/MSFT/03_output/segment_analytics.csv"
)
_SEGMENT_ANALYTICS_SHA256 = (
	"5E0EF5152A052E63B655817DF80741F30A99AF65FC1B237EF23710EF625C81FE"
)
_SEGMENT_RECONCILIATION = (
	"data/live-segment-enrichment-i1/MSFT/03_output/segment_reconciliation_checks.csv"
)
_SEGMENT_RECONCILIATION_SHA256 = (
	"B22983A66760E57B65A1980ECFC505B81D0CDF6847F61E2F59C38C02C310F3DC"
)

_PNL_HASHES = {
	"data/live-segment-enrichment-i1": (
		"0CC3C663056E3CF4DC1F3DEEE956566D849472742F822632614212EF2F0432E0",
		"E63747C2E1F64203934A097106D5053247A3C21E22D39F7445F0DE40EF14F0A9",
	),
	"data/live-closed-world-proof-r1": (
		"ED35DEA10A05072AE4434CFD1442E4BB0FFE87C4E2FFE386702DB75C2758AEAC",
		"E63747C2E1F64203934A097106D5053247A3C21E22D39F7445F0DE40EF14F0A9",
	),
	"data/live-closed-world-proof-r2": (
		"0CC3C663056E3CF4DC1F3DEEE956566D849472742F822632614212EF2F0432E0",
		"E63747C2E1F64203934A097106D5053247A3C21E22D39F7445F0DE40EF14F0A9",
	),
}


def _analytical(input_root: str) -> dict[str, Any]:
	"""Return the analytical P&L / reconciliation inputs for one frozen run root."""
	pnl_sha, reconciliation_sha = _PNL_HASHES[input_root]
	return {
		"analytical_pnl_artifact": f"{input_root}/MSFT/03_output/analytical_pnl.csv",
		"analytical_pnl_sha256": pnl_sha,
		"reconciliation_artifact": (
			f"{input_root}/MSFT/03_output/reconciliation_checks.csv"
		),
		"reconciliation_sha256": reconciliation_sha,
	}


def _msft(input_root: str) -> dict[str, Any]:
	"""Return the MSFT source/accession identity shared by every frozen case."""
	return {
		"ticker": "MSFT",
		"workflow": "filing",
		"case_status": "READY",
		"capability": "AVAILABLE",
		"input_root": input_root,
		"source_artifact": _SOURCE,
		"source_sha256": _SOURCE_SHA256,
		"source_manifest_artifact": _SOURCE_MANIFEST,
		"source_manifest_sha256": _SOURCE_MANIFEST_SHA256,
		"accession": _ACCESSION,
		"filing_period": _PERIOD,
		**_analytical(input_root),
	}


_SEGMENT_INPUTS = {
	"segment_analytics_artifact": _SEGMENT_ANALYTICS,
	"segment_analytics_sha256": _SEGMENT_ANALYTICS_SHA256,
	"segment_reconciliation_artifact": _SEGMENT_RECONCILIATION,
	"segment_reconciliation_sha256": _SEGMENT_RECONCILIATION_SHA256,
	"requires_segments": True,
}

# Every case runs the same mechanical checks.  ``critical`` gates the judge:
# a critical failure means PRODUCT INVALID and JUDGE_SKIPPED.
CHECKS: tuple[dict[str, Any], ...] = (
	{
		"id": "source_integrity",
		"critical": True,
		"description": "Every frozen input file matches its recorded SHA256.",
	},
	{
		"id": "result_schema",
		"critical": True,
		"description": "Product output parses as FinancialInvestigationResult.",
	},
	{
		"id": "evidence_refs",
		"critical": True,
		"description": "Every structured claim cites a ref present in the packet.",
	},
	{
		"id": "numeric_grounding",
		"critical": True,
		"description": (
			"Every amount and every figure in narrative prose reconciles to the "
			"frozen analytical P&L or segment analytics within tolerance."
		),
	},
	{
		"id": "amount_basis",
		"critical": True,
		"description": "Disclosed amounts carry a period, unit, and evidence span.",
	},
	{
		"id": "product_validator",
		"critical": True,
		"description": (
			"The product's own validate_financial_investigation verdict, "
			"reported as exactly one check."
		),
	},
	{
		"id": "quantification",
		"critical": False,
		"description": "Count of unquantified drivers, reported as a diagnostic.",
	},
	{
		"id": "expansion",
		"critical": False,
		"description": "Whether query expansion produced accepted queries.",
	},
)


def _rubric(*dimensions: str, acceptance: str) -> dict[str, Any]:
	return {"dimensions": list(dimensions), "acceptance": acceptance}


_CASES: tuple[dict[str, Any], ...] = (
	{
		"case_id": "msft_segment_growth_mix",
		"suites": ["development"],
		**_msft("data/live-segment-enrichment-i1"),
		**_SEGMENT_INPUTS,
		"scan_artifact": (
			"data/live-segment-enrichment-i1/MSFT/03_output/analysis/"
			"analytical_scan_20260828T191302094324Z.json"
		),
		"scan_sha256": (
			"68D884344368357E006CBF0ADDB538BBD9C8A43931F3305263B0D0B585914C77"
		),
		"finding_rank": 2,
		"finding_refs": ["L01", "L02", "L03", "S01", "S03", "S05"],
		"rubric": _rubric(
			"movement_scope",
			"segment_growth_mix",
			"evidence_grounding",
			"no_invented_allocation",
			acceptance=(
				"Growth and mix interpretation is grounded in the cited "
				"consolidated and segment refs."
			),
		),
		"reference_investigation": (
			"Lunacy/runs/segment-aware-investigation/phases/02-implementation/"
			"evidence/live-rank2/MSFT/03_output/analysis/"
			"filing_investigation_02_rank2-live-mini-v6.json"
		),
	},
	{
		"case_id": "msft_segment_profitability_margin",
		"suites": ["development"],
		**_msft("data/live-segment-enrichment-i1"),
		**_SEGMENT_INPUTS,
		"scan_artifact": (
			"data/live-segment-enrichment-i1/MSFT/03_output/analysis/"
			"analytical_scan_20260828T191302094324Z.json"
		),
		"scan_sha256": (
			"68D884344368357E006CBF0ADDB538BBD9C8A43931F3305263B0D0B585914C77"
		),
		"finding_rank": 4,
		"finding_refs": ["L11", "S02", "S04", "S06"],
		"rubric": _rubric(
			"movement_scope",
			"segment_profitability_margin",
			"margin_reuse",
			"evidence_grounding",
			"no_residual_plug",
			acceptance=(
				"Segment operating margins are taken from the deterministic "
				"segment analytics rather than re-derived or invented, and any "
				"residual stays explicit rather than being plugged."
			),
		),
		"reference_investigation": (
			"data/live-segment-enrichment-i1/MSFT/03_output/analysis/"
			"filing_investigation_04_20260830T082208881748Z.json"
		),
	},
	{
		"case_id": "msft_openai_nonoperating_quantified",
		"suites": ["regression"],
		**_msft("data/live-closed-world-proof-r1"),
		"scan_artifact": (
			"data/live-closed-world-proof-r1/MSFT/03_output/analysis/"
			"analytical_scan_20260827T175543203180Z.json"
		),
		"scan_sha256": (
			"D7FAA260B310ED4022E08F9C36FED1C0D124A8948135DEFBE631F1AB825997C4"
		),
		"finding_rank": 1,
		"finding_refs": ["L12", "L13", "L15"],
		"rubric": _rubric(
			"movement_scope",
			"quantified_disclosures",
			"residual_without_plug",
			"evidence_grounding",
			acceptance=(
				"Preserve the +15.598bn movement, the +6.5bn/-4.8bn disclosure, "
				"the +11.3bn known contribution, and the +4.298bn unresolved "
				"remainder."
			),
		),
		"reference_investigation": (
			"data/live-movement-explanation-retrieval-i1/MSFT/03_output/analysis/"
			"filing_investigation_01_movement-i1-1-control.json"
		),
	},
	{
		"case_id": "msft_operating_expense_multi_driver",
		"suites": ["regression"],
		**_msft("data/live-closed-world-proof-r2"),
		"scan_artifact": (
			"data/live-closed-world-proof-r2/MSFT/03_output/analysis/"
			"analytical_scan_20260827T190654525200Z.json"
		),
		"scan_sha256": (
			"666CFFAE478CEAD9D3FF6C17E6E32CFD5EA999B9388C4B515DD07544B2832F40"
		),
		"finding_rank": 3,
		"finding_refs": ["L01", "L08", "L09", "L10", "L11"],
		"rubric": _rubric(
			"movement_scope",
			"multiple_qualitative_drivers",
			"no_category_allocation",
			"evidence_grounding",
			acceptance=(
				"Retain at least three qualitative operating-expense drivers "
				"with null amounts and no unsupported category allocation."
			),
		),
		"reference_investigation": (
			"data/live-movement-explanation-retrieval-r1/MSFT/03_output/analysis/"
			"filing_investigation_03_20260828T144057144100Z.json"
		),
	},
	{
		# Spec 41: test the Analyst independently from retrieval, so the
		# evidence packet is frozen and only the Analyst call is live.
		"case_id": "msft_analyst_normalization_candidates",
		"suites": ["development"],
		**_msft("data/live-closed-world-proof-r1"),
		"workflow": "analyst",
		# The non-operating packet is used because it actually contains a
		# disclosed, quantified, arguably non-recurring item. The segment-margin
		# packet does not, so it tested nothing.
		"evidence_artifact": (
			"data/live-movement-explanation-retrieval-i1/MSFT/03_output/evidence/"
			"finding_01_movement-i1-1-control.md"
		),
		"evidence_sha256": (
			"63685B3412F9976578474976320B79F2D333E449B4332F28E99BC99F8F86A694"
		),
		# Human-verified known case (Patrik, 2026-08-30; see docs/V1_STATUS.md).
		# The packet discloses "$6.5 billion of net gains ... from investments
		# in OpenAI", primarily the dilution gain from the OpenAI
		# Recapitalization. The dilution-only figure is not separately
		# disclosed, so the disclosed net-gains amount is the expected amount.
		"expected_candidate": {
			"target_line": "Other income (expense), net",
			"period": "2026-06-30 (FY)",
			"item_amount": 6.5e9,
		},
		"rubric": _rubric(
			"normalization_judgment",
			"evidence_grounding",
			"amount_basis",
			acceptance=(
				"The packet contains a human-verified normalization item: the "
				"FY2026 OpenAI recapitalization dilution gain, disclosed as "
				"$6.5 billion of net gains in Other income (expense), net. "
				"Proposing it, grounded in cited evidence with magnitude and "
				"direction reported independently, is required; declining is "
				"a failure for this case."
			),
		),
	},
	{
		"case_id": "msft_scan_movement_detection",
		"suites": ["development"],
		**_msft("data/live-segment-enrichment-i1"),
		**_SEGMENT_INPUTS,
		"workflow": "scan",
		"rubric": _rubric(
			"movement_selection",
			"materiality_judgment",
			"no_invented_movements",
			acceptance=(
				"Findings identify real, material movements present in the "
				"supplied analytics, without manufacturing anomalies."
			),
		),
	},
	{
		"case_id": "amzn_capability_probe",
		"ticker": "AMZN",
		"suites": ["development"],
		"workflow": "filing",
		"case_status": "BLOCKED",
		"capability": "UNAVAILABLE",
		"blocked_reason": (
			"No frozen AMZN accession, source filing, analytical scan, or "
			"finding exists."
		),
		"missing_prerequisite": "data/AMZN/01_source/edgar + analytical scan",
		"expected_workflow": (
			"ingest AMZN -> build analytical P&L -> run analytical scan -> "
			"freeze a finding, then promote this probe to a READY filing case"
		),
		"rubric": _rubric(
			"capability",
			acceptance="Preserve unavailable capability without fabricating inputs.",
		),
	},
	{
		"case_id": "googl_holdout_capability_probe",
		"ticker": "GOOGL",
		"suites": ["holdout"],
		"workflow": "filing",
		"case_status": "BLOCKED",
		"capability": "UNAVAILABLE",
		"blocked_reason": (
			"No frozen GOOGL accession, source filing, analytical scan, or "
			"finding exists."
		),
		"missing_prerequisite": "data/GOOGL/01_source/edgar + analytical scan",
		"expected_workflow": (
			"ingest GOOGL -> build analytical P&L -> run analytical scan -> "
			"freeze a finding, then promote this probe to a READY filing case"
		),
		"rubric": _rubric(
			"capability",
			acceptance="Preserve unavailable holdout capability without model calls.",
		),
	},
)

# Keys recorded for diagnosis but excluded from the definition hash, because
# they describe product *output*, not the pinned input.
_UNHASHED_KEYS = frozenset({"reference_investigation"})


def discover(
	ticker: str | None = None,
	suite: str | None = None,
	case_id: str | None = None,
) -> list[dict[str, Any]]:
	"""Select frozen cases by ticker, suite, and/or case id."""
	if suite is not None and suite not in SUITES:
		raise ValueError(f"unknown suite: {suite}; expected one of {SUITES}")
	selected = [
		json.loads(json.dumps(case))
		for case in _CASES
		if (ticker is None or case["ticker"] == ticker.strip().upper())
		and (suite is None or suite in case.get("suites", []))
		and (case_id is None or case["case_id"] == case_id)
	]
	if not selected:
		raise ValueError(
			f"no cases matched ticker={ticker} suite={suite} case_id={case_id}"
		)
	return selected


def _sha256_json(value: Any) -> str:
	payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
	return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sha256_file(path: str | Path) -> str | None:
	"""Return the uppercase SHA256 of a file, or None when it is absent."""
	target = Path(path)
	if not target.is_file():
		return None
	digest = hashlib.sha256()
	with target.open("rb") as handle:
		for block in iter(lambda: handle.read(1 << 20), b""):
			digest.update(block)
	return digest.hexdigest().upper()


def case_hash(case: dict[str, Any]) -> str:
	"""Hash one case definition, excluding recorded product output."""
	return _sha256_json(
		{key: value for key, value in case.items() if key not in _UNHASHED_KEYS}
	)


def definition_hash(
	cases: list[dict[str, Any]],
	*,
	judge_prompt: str,
	judge_schema: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
	"""Return the aggregate definition hash and its components.

	Judge model and reasoning effort are part of the hash: the frozen contract
	says changing either makes qualitative results non-comparable, so a run
	under a different judge must not silently compare against this baseline.
	"""
	components = {
		"cases": {case["case_id"]: case_hash(case) for case in cases},
		"rubrics": {
			case["case_id"]: _sha256_json(case.get("rubric", {})) for case in cases
		},
		"checks": _sha256_json(list(CHECKS)),
		"judge": {
			"model": JUDGE_MODEL,
			"reasoning_effort": JUDGE_REASONING_EFFORT,
			"prompt_sha256": hashlib.sha256(
				judge_prompt.encode("utf-8")
			).hexdigest(),
			"schema_sha256": _sha256_json(judge_schema),
		},
	}
	return _sha256_json(components), components
