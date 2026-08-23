"""Minimal structured Risk Reviewer call for one Analyst candidate."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict

from .adjustment_analysis import AnalystCandidate, valid_item_key
from .filing import FilingEvidenceError, validate_evidence_refs

DEFAULT_MODEL = "gpt-5.6-luna"
DEFAULT_REASONING_EFFORT = "high"
PROMPT_VERSION = "reviewer-v3"
SCHEMA_VERSION = "reviewer-result-v3"

REVIEWER_PROMPT = """You are the Risk Reviewer for a financial adjustment candidate.
Your goal is low false acceptance. Use only the one candidate, the supplied
reported P&L, and the exact supplied evidence packet in the user payload.
Do not use filing knowledge, retrieval, files, other candidates, or hidden
evidence.

The candidate target_line and period must exactly match a real supplied P&L
line and period. Set target_valid or period_valid to false when they do not.
Do not use fuzzy matching, invent a mapping, or silently rewrite the candidate.

The candidate item_key is an economic subject-and-event slug, not provenance.
Accept it only when the supplied evidence supports that specific key and it is
not a generic key such as adjustment, unusual-item, impairment, or
other-expense. Do not compare it with historical keys or resolve synonyms.

The candidate's amount, amount_basis, and item_effect_on_line are inputs to
review, not facts to copy. Independently assess from the evidence whether the
item made the reported target-line value larger or smaller, and set
item_effect_on_line to increased_line or decreased_line only when the supplied
evidence establishes that direction; otherwise null. Do not echo the Analyst's
direction claim. A null amount is unresolved, never zero. A disclosed amount
must be separately supported by the supplied evidence; do not infer a sub-item
amount from a parent-line or year-over-year change. A suggested_amount is
advisory only and must remain null unless the supplied evidence supports it.

You must also answer the normalization question: even if this item is real and
correctly quantified, does removing it from normalized earnings make financial
sense? Set normalization_assessment to eligible, not_eligible, or uncertain,
and recurrence_class to single_period (one discrete event in one period),
multi_period_discrete (the same kind of discrete event recurs across periods),
recurring_volatile (a recurring item whose size swings), structural (an ongoing
cost of doing business), or uncertain. A one-period item can still be normal
operating expenditure; recurrence alone does not decide eligibility, and a
recurring item can still be non-core. Judge from the supplied evidence only.
When uncertain, say so; uncertainty blocks automatic approval and that is
acceptable.

Return a non-accepting verdict with a concrete concern for unsupported
evidence, a wrong target or period, an unsupported amount, an amount-basis
misrepresentation, an unsupported effect direction, or weak justification for
removing the item from normalized earnings. Never apply an adjustment, approve
it deterministically, start a revision loop, or retrieve more evidence.
"""


class ReviewResult(BaseModel):
	"""Structured review output; this is not the final approval state."""

	model_config = ConfigDict(extra="forbid")

	verdict: Literal["accept", "revise", "reject"]
	evidence_strength: Literal["strong", "medium", "weak"]
	amount_basis: Literal["disclosed", "calculated", "estimated", "unknown"]
	judgment_level: Literal["low", "medium", "high"]
	calculation_valid: bool | None
	target_valid: bool
	item_effect_on_line: Literal["increased_line", "decreased_line"] | None = None
	# This small extension makes the required wrong-period case explicit.
	period_valid: bool | None = None
	# Normalization judgment: should this item leave normalized earnings at all?
	# Defaults are fail-closed so legacy persisted reviews cannot auto-approve.
	normalization_assessment: Literal[
		"eligible", "not_eligible", "uncertain"
	] = "uncertain"
	recurrence_class: Literal[
		"single_period",
		"multi_period_discrete",
		"recurring_volatile",
		"structural",
		"uncertain",
	] = "uncertain"
	concerns: list[str]
	suggested_amount: float | None = None
	note: str | None = None


class ReviewerError(RuntimeError):
	"""The Reviewer call, input contract, or persistence step failed."""


def run_reviewer(
	ticker: str,
	pnl: pd.DataFrame,
	candidate: AnalystCandidate,
	evidence_packet: str,
	*,
	client: Any | None = None,
	model: str = DEFAULT_MODEL,
	reasoning_effort: str = DEFAULT_REASONING_EFFORT,
	evidence_ref: str = "frozen evidence packet",
	run_id: str | None = None,
) -> tuple[ReviewResult, dict[str, Any]]:
	"""Review exactly one candidate against one caller-supplied packet."""

	if not isinstance(pnl, pd.DataFrame):
		raise TypeError("pnl must be a pandas DataFrame")
	if not isinstance(candidate, AnalystCandidate):
		raise TypeError("candidate must be an AnalystCandidate")
	if not isinstance(evidence_packet, str):
		raise TypeError("evidence_packet must be a string")

	try:
		validate_evidence_refs(
			evidence_packet,
			candidate.evidence_refs,
			require_identity=False,
		)
	except FilingEvidenceError as exc:
		raise ReviewerError(str(exc)) from exc

	payload = {
		"ticker": ticker.strip().upper(),
		"candidate": candidate.model_dump(mode="json"),
		"pnl": pnl.astype(object).where(pd.notna(pnl), None).to_dict(orient="records"),
		"evidence_packet": evidence_packet,
	}
	if client is None:
		load_dotenv()
		if not os.getenv("OPENAI_API_KEY"):
			raise ReviewerError("OPENAI_API_KEY is not set")
		try:
			from openai import OpenAI

			client = OpenAI()
		except Exception as exc:
			raise ReviewerError(f"could not initialize OpenAI client: {exc}") from exc

	try:
		response = client.responses.parse(
			model=model,
			reasoning={"effort": reasoning_effort},
			input=[
				{"role": "system", "content": REVIEWER_PROMPT},
				{
					"role": "user",
					"content": json.dumps(
						payload,
						ensure_ascii=False,
						default=str,
						allow_nan=False,
					),
				},
			],
			text_format=ReviewResult,
		)
		result = getattr(response, "output_parsed", None)
		if not isinstance(result, ReviewResult):
			result = ReviewResult.model_validate(result)
	except Exception as exc:
		raise ReviewerError(f"structured Reviewer call failed: {exc}") from exc
	if (
		result.verdict == "accept"
		and candidate.item_key is not None
		and not valid_item_key(candidate.item_key)
	):
		raise ReviewerError("Reviewer accepted an invalid or generic item_key")

	metadata = {
		"ticker": payload["ticker"],
		"model": model,
		"reasoning_effort": reasoning_effort,
		"prompt_version": PROMPT_VERSION,
		"schema_version": SCHEMA_VERSION,
		"evidence_ref": evidence_ref,
		"run_id": run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ"),
		"timestamp_utc": datetime.now(UTC).isoformat(),
		"candidate_count": 1,
	}
	return result, metadata


def save_reviewer_result(
	ticker: str,
	adjustment_id: str,
	candidate: AnalystCandidate,
	result: ReviewResult,
	metadata: dict[str, Any],
	output_root: str | Path = "data",
) -> Path:
	"""Persist the unchanged candidate, structured review, and run metadata."""

	if not isinstance(candidate, AnalystCandidate):
		raise TypeError("candidate must be an AnalystCandidate")
	if not isinstance(result, ReviewResult):
		raise TypeError("result must be a ReviewResult")
	if not adjustment_id or Path(adjustment_id).name != adjustment_id:
		raise ReviewerError("adjustment_id must be a non-empty path component")
	if "run_id" not in metadata:
		raise ReviewerError("review metadata must contain run_id")

	output_directory = (
		Path(output_root) / ticker.strip().upper() / "03_output" / "reviews"
	)
	output_directory.mkdir(parents=True, exist_ok=True)
	output_path = output_directory / f"{adjustment_id}_{metadata['run_id']}.json"
	output_path.write_text(
		json.dumps(
			{
				"metadata": metadata,
				"candidate": candidate.model_dump(mode="json"),
				"result": result.model_dump(mode="json"),
			},
			indent=2,
			ensure_ascii=False,
		)
		+ "\n",
		encoding="utf-8",
	)
	return output_path
