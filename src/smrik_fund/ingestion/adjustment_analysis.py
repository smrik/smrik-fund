"""Minimal structured Financial Analyst call."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict

DEFAULT_MODEL = "gpt-5.6-luna"
DEFAULT_REASONING_EFFORT = "high"
PROMPT_VERSION = "analyst-v2"
SCHEMA_VERSION = "analyst-result-v2"

ANALYST_PROMPT = """You are a financial analyst identifying normalization candidates.
Use only the supplied P&L context and evidence packet.
Adjustment amounts are absolute USD magnitudes. Use the V1 convention that an
adjustment amount is the positive magnitude being removed. If the attributable
amount is not supported by the supplied evidence, return adjustment_amount as
null; do not invent or infer an unsupported amount.
Preserve the signed P&L values in your reasoning. If the reported target line is
negative, describe it as a loss and do not claim that subtracting a positive
adjustment would increase normalized income; leave that treatment for human
review under V1.
The target_line and period must exactly match the supplied P&L values. Do not
paraphrase, normalize, or substitute them.
Return plausible candidates with the target line, period, amount basis, reason,
evidence references, and uncertainty. Use the evidence IDs exactly as written
in the packet (for example, E1 or E2).
When the packet explicitly says that filing evidence has not yet been
retrieved, return at most one short research_request and do not cite evidence
IDs or invent an amount. A research request is a retrieval need, not a fact.
"""


class AnalystCandidate(BaseModel):
	"""One raw candidate; unresolved amounts are valid Analyst output."""

	model_config = ConfigDict(extra="forbid")

	# These fields mirror the small Task 7 schema. They are not approval fields.
	target_line: str
	sub_item: str | None = None
	period: str
	adjustment_amount: float | None = None
	amount_basis: Literal["disclosed", "calculated", "estimated", "unknown"]
	calculation: str | None = None
	reason: str
	evidence_refs: list[str]
	uncertainty: str | None = None


class AnalystResult(BaseModel):
	model_config = ConfigDict(extra="forbid")

	candidates: list[AnalystCandidate]
	research_request: str | None = None


class AdjustmentAnalysisError(RuntimeError):
	"""The Analyst call or persistence step could not complete."""


def run_analyst(
	ticker: str,
	pnl: pd.DataFrame,
	evidence_packet: str,
	*,
	client: Any | None = None,
	model: str = DEFAULT_MODEL,
	reasoning_effort: str = DEFAULT_REASONING_EFFORT,
	evidence_ref: str = "frozen evidence packet",
	run_id: str | None = None,
) -> tuple[AnalystResult, dict[str, Any]]:
	"""
	Call the configured model with frozen evidence and P&L context.

	Flow: load the client, build the two inputs, parse native structured output,
	then attach only basic run metadata.
	"""

	# Tests can inject a client; real runs load the key from the project .env.
	if client is None:
		load_dotenv()
		if not os.getenv("OPENAI_API_KEY"):
			raise AdjustmentAnalysisError("OPENAI_API_KEY is not set")
		try:
			from openai import OpenAI

			client = OpenAI()
		except Exception as exc:
			raise AdjustmentAnalysisError(
				f"could not initialize OpenAI client: {exc}"
			) from exc

	# The model receives the frozen packet and the reported analytical P&L only.
	pnl_records = (
		pnl.astype(object).where(pd.notna(pnl), None).to_dict(orient="records")
	)
	payload = {
		"ticker": ticker.strip().upper(),
		"pnl": pnl_records,
		"evidence_packet": evidence_packet,
	}

	# Responses.parse validates the response directly into AnalystResult.
	try:
		response = client.responses.parse(
			model=model,
			reasoning={"effort": reasoning_effort},
			input=[
				{
					"role": "system",
					"content": ANALYST_PROMPT,
				},
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
			text_format=AnalystResult,
		)
		parsed = getattr(response, "output_parsed", None)
		result = (
			parsed
			if isinstance(parsed, AnalystResult)
			else AnalystResult.model_validate(parsed)
		)
	except Exception as exc:
		raise AdjustmentAnalysisError(f"structured Analyst call failed: {exc}") from exc

	# Metadata makes the saved result reproducible without changing the result.
	effective_run_id = run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
	metadata = {
		"ticker": payload["ticker"],
		"model": model,
		"reasoning_effort": reasoning_effort,
		"prompt_version": PROMPT_VERSION,
		"schema_version": SCHEMA_VERSION,
		"evidence_ref": evidence_ref,
		"run_id": effective_run_id,
		"timestamp_utc": datetime.now(UTC).isoformat(),
		"candidate_count": len(result.candidates),
	}
	return result, metadata


def save_analyst_result(
	ticker: str,
	result: AnalystResult,
	metadata: dict[str, Any],
	output_root: str | Path = "data",
) -> Path:
	"""
	Persist the structured result and run metadata as one JSON artifact.
	"""

	# Keep the result in the documented per-company analysis directory.
	output_directory: Path = (
		Path(output_root) / ticker.strip().upper() / "03_output" / "analysis"
	)
	output_directory.mkdir(
		parents=True,
		exist_ok=True,
	)
	output_path: Path = output_directory / f"analyst_{metadata['run_id']}.json"

	# Store the exact structured result beside its basic run metadata.
	output_path.write_text(
		json.dumps(
			{"metadata": metadata, "result": result.model_dump(mode="json")},
			indent=2,
		)
		+ "\n",
		encoding="utf-8",
	)

	# return the output path
	return output_path
