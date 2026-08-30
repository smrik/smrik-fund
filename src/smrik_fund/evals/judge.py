"""Qualitative judge.

Ordinal only.  Per the frozen contract there is no numeric composite score: we
care why an output improved or regressed, not whether a synthetic number moved
from 7.4 to 7.8.

The judge is deliberately a different model from the product.  A judge failure
produces JUDGE_ERROR and never converts a mechanically valid product result into
a product failure - it means qualitative evaluation is unavailable for that run.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .cases import JUDGE_MODEL, JUDGE_REASONING_EFFORT

Verdict = Literal["PASS", "PARTIAL", "FAIL"]

JUDGE_PROMPT = """\
You are evaluating one automated financial-filing investigation produced by a
separate system. You are not writing analysis of your own and you are not
correcting the work.

You receive:
- the movement being explained, rebuilt deterministically from audited data;
- the deterministic analytics available to the system, including any segment
  operating margins it was given;
- the evidence packet excerpts the system retrieved from the filing;
- the structured explanation the system produced.

Judge each rubric dimension independently and return an ordinal verdict:

- PASS    - the dimension is fully satisfied.
- PARTIAL - materially satisfied but with a real, specific weakness.
- FAIL    - not satisfied.

Rules:
- Judge only what is present. An honest "unresolved remainder" is correct
  behaviour, not a failure; silently plugging a residual is a failure.
- An unquantified qualitative driver is acceptable when the filing does not
  disclose an amount. Inventing an amount is not.
- Where deterministic analytics already supply a figure (for example a segment
  operating margin), the system should reuse that figure. Re-deriving it,
  restating it inconsistently, or inventing one is a failure of that dimension.
- Ground every verdict in specific content. Quote the phrase you are judging.
- The overall verdict is the weakest dimension verdict, unless a dimension's
  weakness is immaterial to the acceptance statement.
"""


class DimensionVerdict(BaseModel):
	model_config = ConfigDict(extra="forbid")

	dimension: str = Field(min_length=1)
	verdict: Verdict
	reason: str = Field(min_length=1, max_length=600)
	quoted_evidence: str | None = Field(default=None, max_length=400)


class JudgeResult(BaseModel):
	model_config = ConfigDict(extra="forbid")

	overall: Verdict
	dimensions: list[DimensionVerdict] = Field(min_length=1, max_length=12)
	summary: str = Field(min_length=1, max_length=800)


def schema() -> dict[str, Any]:
	return JudgeResult.model_json_schema()


def build_input(
	case: dict[str, Any],
	*,
	system_output: dict[str, Any],
	evidence_packet: str,
	observed_movement: Any = None,
	segment_margins: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
	"""Bound the judge's input to exactly what the rubric needs."""
	return {
		"case_id": case["case_id"],
		"ticker": case["ticker"],
		"filing": {
			"accession": case.get("accession"),
			"period": case.get("filing_period"),
		},
		"rubric": case.get("rubric", {}),
		"observed_movement": observed_movement,
		"deterministic_segment_margins": segment_margins or [],
		"evidence_packet": evidence_packet,
		"system_output": system_output,
	}


def run(
	judge_input: dict[str, Any],
	*,
	client: Any,
	model: str = JUDGE_MODEL,
	reasoning_effort: str = JUDGE_REASONING_EFFORT,
) -> JudgeResult:
	"""Call the judge and return its validated structured verdict."""
	response = client.responses.parse(
		model=model,
		reasoning={"effort": reasoning_effort},
		input=[
			{"role": "system", "content": JUDGE_PROMPT},
			{
				"role": "user",
				"content": json.dumps(
					judge_input, ensure_ascii=False, allow_nan=False, default=str
				),
			},
		],
		text_format=JudgeResult,
	)
	parsed = getattr(response, "output_parsed", None)
	if parsed is None:
		raise ValueError("judge returned no parsed structured output")
	return parsed
