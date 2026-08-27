"""Deterministic context and structured attention scan for the reported P&L."""

from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

import pandas as pd
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

from .statements import ANNUAL_PERIOD_PATTERN

DEFAULT_MODEL = "gpt-5.6-luna"
DEFAULT_REASONING_EFFORT = "high"
PROMPT_VERSION = "analytical-scan-v2"
SCHEMA_VERSION = "analytical-scan-result-v2"
_LINE_REF_PATTERN = re.compile(r"^line_ref=(L\d+)\b", re.MULTILINE)
_PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts" / "analytical_scan.md"
ANALYTICAL_SCAN_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")
LineRef = Annotated[str, Field(pattern=r"^L\d+$")]


class AnalyticalScanError(RuntimeError):
	pass


class AnalyticalScanFinding(BaseModel):
	model_config = ConfigDict(extra="forbid")

	rank: int = Field(ge=1, le=8)
	title: str = Field(min_length=1, max_length=200)
	importance: Literal["high", "medium", "low"]
	affected_line_refs: list[LineRef] = Field(
		min_length=1,
		description="Bare exact source-row references copied from line_ref=L## markers.",
	)
	observation: str = Field(min_length=1, max_length=1200)
	why_it_matters: str = Field(min_length=1, max_length=1200)
	investigation_questions: list[str] = Field(default_factory=list, max_length=3)


# Public vocabulary for downstream finding-focused workflows.  The alias keeps
# the persisted scan schema and validation behavior unchanged.
ScanFinding = AnalyticalScanFinding


class AnalyticalScanResult(BaseModel):
	model_config = ConfigDict(extra="forbid")

	findings: list[AnalyticalScanFinding] = Field(default_factory=list, max_length=8)


def _clean(value: object) -> str:
	if value is None:
		return ""
	try:
		if bool(pd.isna(value)):
			return ""
	except (TypeError, ValueError):
		pass
	return " ".join(str(value).split())


def _normalized(value: object) -> str:
	return re.sub(r"[^a-z0-9]", "", _clean(value).casefold())


def _truthy(value: object) -> bool:
	if value is None:
		return False
	try:
		if bool(pd.isna(value)):
			return False
	except (TypeError, ValueError):
		pass
	if isinstance(value, str):
		return value.strip().casefold() in {"1", "true", "yes"}
	return bool(value)


def _number(value: object) -> float | None:
	try:
		candidate = float(value)
	except (TypeError, ValueError):
		return None
	return candidate if math.isfinite(candidate) else None


def _annual_periods(pnl: pd.DataFrame) -> list[str]:
	if not isinstance(pnl, pd.DataFrame):
		raise TypeError("pnl must be a pandas DataFrame")
	periods = [
		column
		for column in pnl.columns
		if isinstance(column, str) and ANNUAL_PERIOD_PATTERN.fullmatch(column)
	]
	if len(periods) < 3:
		raise ValueError("analytical P&L must contain at least 3 annual FY periods")
	return periods[:3]


def _period_label(period: str) -> str:
	return f"FY{period[:4][-2:]}"


def _value(row: pd.Series, period: str) -> float | None:
	return _number(row.get(period))


def _is_dimension(row: pd.Series) -> bool:
	return any(
		_truthy(row.get(column))
		for column in (
			"dimension",
			"is_breakdown",
			"dimension_axis",
			"dimension_member",
			"dimension_label",
		)
	)


def _source_label(row: pd.Series) -> str:
	return (
		_clean(row.get("label")) or _clean(row.get("concept")) or "Unnamed source line"
	)


def _role(row: pd.Series) -> str:
	raw_text = " ".join(
		_clean(row.get(column)).casefold()
		for column in ("concept", "standard_concept", "label")
	)
	text = " ".join(
		_normalized(row.get(column))
		for column in ("concept", "standard_concept", "label")
	)
	markers = (
		"earningspershare",
		"weightedaveragenumberofshares",
		"sharesaverage",
		"sharesfullydilutedaverage",
		"sharesoutstanding",
		"sharecount",
		"pershare",
	)
	if any(marker in text for marker in markers) or re.search(r"\beps\b", raw_text):
		return "shares" if "share" in text and "earningspershare" not in text else "eps"
	return "monetary"


def _is_noise(row: pd.Series) -> bool:
	text = " ".join(
		_normalized(row.get(column))
		for column in ("concept", "standard_concept", "label")
	)
	return (
		_truthy(row.get("abstract"))
		or _normalized(row.get("standard_concept")).endswith("abstract")
		or _normalized(row.get("concept")).endswith("abstract")
		or any(marker in text for marker in ("xbrlnoise", "xbrlonly"))
	)


def _is_ratio_line(row: pd.Series) -> bool:
	# GrossProfit stays monetary despite its possible "Gross margin" label.
	if _clean(row.get("standard_concept")) == "GrossProfit":
		return False
	fields = [
		_clean(row.get(column)).casefold()
		for column in ("concept", "standard_concept", "label")
	]
	text = " ".join(fields)
	standard = _normalized(row.get("standard_concept"))
	return any(
		re.search(rf"\b{marker}\b", text) is not None
		for marker in ("margin", "ratio", "rate", "percent", "percentage")
	) or any(
		standard.endswith(marker)
		for marker in ("margin", "ratio", "rate", "percent", "percentage")
	)


def _signature(row: pd.Series, role: str, periods: list[str]) -> tuple[object, ...]:
	"""Identify rows, ignoring only presentation labels used by aliases.

	Source concepts, dimensions, other lineage metadata, and reported values
	remain part of the identity so real repeated dimensions/concepts survive.
	"""
	fields = (
		"concept",
		"standard_concept",
		"abstract",
		"dimension",
		"is_breakdown",
		"dimension_axis",
		"dimension_member",
		"dimension_member_label",
		"dimension_label",
		"parent_concept",
		"parent_abstract_concept",
		"balance",
		"weight",
		"preferred_sign",
		*periods,
	)
	identity_fields = (
		"concept",
		"standard_concept",
		"dimension_axis",
		"dimension_member",
		"dimension_member_label",
		"dimension_label",
		"parent_concept",
		"parent_abstract_concept",
	)
	if not any(_clean(row.get(field)) for field in identity_fields):
		# Without source identity, different labels cannot be proven aliases.
		fields = ("label", *fields)
	return (
		role,
		*[
			("number", n)
			if (n := _number(row.get(field))) is not None
			else ("text", _clean(row.get(field)))
			for field in fields
		],
	)


def _compact_number(value: float | None) -> str:
	if value is None:
		return "N/A"
	return f"{value:,.6f}".rstrip("0").rstrip(".")


def _dollars(value: float | None, *, signed: bool = False) -> str:
	if value is None:
		return "N/A"
	amount = _compact_number(abs(value))
	if value < 0:
		return f"-${amount}"
	if signed and value > 0:
		return f"+${amount}"
	return f"${amount}"


def _ratio(value: float | None) -> str:
	return "N/A" if value is None else f"{value * 100:+.1f}%"


def _bps(value: float | None) -> str:
	return "N/A" if value is None else f"{value:+,.0f} bps"


def _shares(value: float | None) -> str:
	return _compact_number(value)


def _eps(value: float | None) -> str:
	return "N/A" if value is None else f"${_compact_number(value)}"


def _metric(row: pd.Series, metric: str, period: str, *aliases: str) -> float | None:
	for name in (metric, *aliases):
		if (value := _number(row.get(f"{name}_{period}"))) is not None:
			return value
	return None


def _scan_growth(
	row: pd.Series, period: str, previous_period: str | None
) -> float | None:
	"""Show growth only when both reported endpoints are strictly positive."""
	if previous_period is None:
		return None
	current = _value(row, period)
	previous = _value(row, previous_period)
	if current is None or previous is None or current <= 0 or previous <= 0:
		return None
	return _metric(row, "yoy_growth", period, "yoy_change")


def _scan_cagr(row: pd.Series, periods: list[str]) -> float | None:
	"""Hide CAGR when its two-year endpoints cross or touch zero."""
	if len(periods) < 3:
		return None
	newest = _value(row, periods[0])
	oldest = _value(row, periods[2])
	if newest is None or oldest is None or newest <= 0 or oldest <= 0:
		return None
	return _number(row.get("two_year_cagr"))


def _movement_text(
	row: pd.Series,
	periods: list[str],
	role: str = "monetary",
) -> str:
	previous_periods = [*periods[1:], None]
	parts: list[str] = []
	for period, previous_period in zip(periods, previous_periods, strict=True):
		movement = _metric(row, "absolute_yoy_change", period)
		if role == "shares":
			movement_text = _shares(movement)
			if movement is not None and movement > 0:
				movement_text = f"+{movement_text}"
			movement_text = f"{movement_text} shares"
		else:
			movement_text = _dollars(movement, signed=True)
		parts.append(
			f"{_period_label(period)} abs={movement_text}, "
			f"growth={_ratio(_scan_growth(row, period, previous_period))}"
		)
	return "; ".join(parts)


def _display_rows(pnl: pd.DataFrame, periods: list[str]) -> list[dict[str, Any]]:
	rows: list[dict[str, Any]] = []
	seen: set[tuple[object, ...]] = set()
	parent_label: str | None = None
	for position, (_, row) in enumerate(pnl.iterrows(), start=1):
		label = _source_label(row)
		is_abstract = _truthy(row.get("abstract"))
		is_dimension = _is_dimension(row)
		if not is_dimension and label and not is_abstract:
			parent_label = label
		path = f"{parent_label} > {label}" if is_dimension and parent_label else label
		if (
			_clean(row.get("standard_concept")) == "GrossProfit"
			and _normalized(label) == "grossmargin"
		):
			path = "Gross profit (reported label: Gross margin)"
		role = _role(row)
		if _is_noise(row) or not any(
			_value(row, period) is not None for period in periods
		):
			continue
		if role == "monetary" and _is_ratio_line(row):
			continue
		if (signature := _signature(row, role, periods)) in seen:
			continue
		seen.add(signature)
		rows.append(
			{
				"ref": f"L{position:02d}",
				"row": row,
				"path": path,
				"role": role,
			}
		)
	return rows


def _metadata_text(row: pd.Series) -> str:
	parts: list[str] = []
	for field in ("concept", "standard_concept"):
		value = _clean(row.get(field))
		parts.append(f"{field}={value or 'N/A'}")
	for field in ("dimension_axis", "dimension_member", "dimension_label"):
		value = _clean(row.get(field))
		if value:
			parts.append(f"{field}={value}")
	return "; ".join(parts)


def _line_text(record: dict[str, Any], periods: list[str]) -> str:
	row = record["row"]
	raw_label = _source_label(row)
	values = ", ".join(
		f"{_period_label(p)}={_dollars(_value(row, p))}" for p in periods
	)
	movements = _movement_text(row, periods)
	intensity = "; ".join(
		f"{_period_label(p)}={_ratio(_metric(row, 'percent_of_revenue', p))}, bps change={_bps(_metric(row, 'percent_of_revenue_bps_change', p))}"
		for p in periods
	)
	return (
		f"line_ref={record['ref']} | {record['path']} | source_label={raw_label} | "
		f"{_metadata_text(row)} | values: {values} | "
		f"movement: {movements} | common-size (% revenue): {intensity} | "
		f"2Y CAGR={_ratio(_scan_cagr(row, periods))}"
	)


def _margin_text(
	metric: str,
	label: str,
	standard_concept: str,
	rows: list[dict[str, Any]],
	periods: list[str],
) -> str:
	matches = [
		record
		for record in rows
		if _clean(record["row"].get("standard_concept")) == standard_concept
	]
	record = matches[0] if len(matches) == 1 else None
	row = pd.Series(dtype=object) if record is None else record["row"]
	ref = "N/A" if record is None else record["ref"]
	levels = "; ".join(
		f"{_period_label(p)}={_ratio(_metric(row, metric, p))}" for p in periods
	)
	changes = "; ".join(
		f"{_period_label(p)}={_bps(_metric(row, f'{metric}_bps_change', p))}"
		for p in periods
	)
	return (
		f"line_ref={ref} | {label} (source {standard_concept}) | "
		f"levels: {levels} | bps change: {changes}"
	)


def _format_context_and_refs(pnl: pd.DataFrame) -> tuple[str, set[str]]:
	periods = _annual_periods(pnl)
	rows = _display_rows(pnl, periods)
	period_header = ", ".join(f"{_period_label(p)}={p}" for p in periods)
	line_rows = [record for record in rows if record["role"] == "monetary"]
	eps_rows = [record for record in rows if record["role"] != "monetary"]
	lines = [
		"# Analytical Scan Context",
		f"Reported annual periods (newest to oldest): {period_header}",
		"Values preserve supplied signs; N/A means missing or mathematically undefined.",
		"Movement metrics show absolute changes (abs), guarded growth, intensity, bps, and CAGR where supplied.",
		"Each selectable source row has a line_ref=L## marker; copy only the bare L## token into affected_line_refs.",
		"Do not include brackets, line_ref=, or other decoration; line_ref=N/A is not a selectable row.",
		"",
		"## Line movements",
	]
	lines.extend(_line_text(record, periods) for record in line_rows)
	if not line_rows:
		lines.append("- No monetary source lines supplied.")
	lines += [
		"",
		"## Margins and rates",
		_margin_text(
			"gross_margin", "Gross margin ratio", "GrossProfit", rows, periods
		),
		_margin_text(
			"operating_margin", "Operating margin", "OperatingIncomeLoss", rows, periods
		),
		_margin_text(
			"pretax_margin", "Pretax margin", "PretaxIncomeLoss", rows, periods
		),
		_margin_text("net_margin", "Net margin", "NetIncome", rows, periods),
		_margin_text(
			"effective_tax_rate", "Effective tax rate", "IncomeTaxes", rows, periods
		),
		"",
		"## EPS and shares",
	]
	for record in eps_rows:
		row = record["row"]
		kind = "shares" if record["role"] == "shares" else "EPS"
		formatter = _shares if record["role"] == "shares" else _eps
		values = ", ".join(
			f"{_period_label(p)}={formatter(_value(row, p))}" for p in periods
		)
		movements = _movement_text(row, periods, record["role"])
		lines.append(
			f"line_ref={record['ref']} | {kind} {record['path']} | {_metadata_text(row)} | "
			f"values: {values} | movement: {movements}"
		)
	if not eps_rows:
		lines.append("- No EPS or share rows supplied.")
	context = "\n".join(lines) + "\n"
	return context, {record["ref"] for record in rows}


def format_analytical_pnl_for_scan(pnl: pd.DataFrame) -> str:
	return _format_context_and_refs(pnl)[0]


def _filing_metadata(filing: Any) -> dict[str, str | None]:
	if filing is None:
		return {"company_name": None, "filing_accession": None}

	def value(*names: str) -> str | None:
		for name in names:
			try:
				candidate = getattr(filing, name)
			except Exception:
				continue
			if not callable(candidate) and (text := _clean(candidate)):
				return text
		return None

	return {
		"company_name": value("company_name", "company", "name"),
		"filing_accession": value("accession_no", "accession_number"),
	}


def validate_analytical_scan_result(
	result: AnalyticalScanResult | dict[str, Any],
	supplied_line_refs: Iterable[str],
) -> AnalyticalScanResult:
	try:
		parsed = (
			result
			if isinstance(result, AnalyticalScanResult)
			else AnalyticalScanResult.model_validate(result)
		)
	except Exception as exc:
		raise AnalyticalScanError(f"invalid analytical scan result: {exc}") from exc
	findings = parsed.findings
	if len(findings) > 8:
		raise AnalyticalScanError("analytical scan returned more than 8 findings")
	if [finding.rank for finding in findings] != list(range(1, len(findings) + 1)):
		raise AnalyticalScanError(
			"analytical scan ranks must be unique and ordered from 1"
		)
	allowed = set(supplied_line_refs)
	for finding in findings:
		refs = finding.affected_line_refs
		if not refs:
			raise AnalyticalScanError(
				f"finding {finding.rank} has no affected line reference"
			)
		if len(refs) != len(set(refs)):
			raise AnalyticalScanError(
				f"finding {finding.rank} repeats an affected line reference"
			)
		if unknown := [ref for ref in refs if ref not in allowed]:
			raise AnalyticalScanError(
				f"finding {finding.rank} references unknown line(s): {', '.join(unknown)}"
			)
		if len(finding.investigation_questions) > 3:
			raise AnalyticalScanError(
				f"finding {finding.rank} has more than 3 questions"
			)
	return parsed


def run_analytical_scan(
	ticker: str,
	pnl: pd.DataFrame,
	*,
	filing: Any | None = None,
	client: Any | None = None,
	model: str = DEFAULT_MODEL,
	reasoning_effort: str = DEFAULT_REASONING_EFFORT,
	run_id: str | None = None,
	context: str | None = None,
) -> tuple[AnalyticalScanResult, dict[str, Any]]:
	if context is None:
		context, supplied_refs = _format_context_and_refs(pnl)
	elif isinstance(context, str):
		supplied_refs = set(_LINE_REF_PATTERN.findall(context))
	else:
		raise TypeError("context must be a string")
	if client is None:
		load_dotenv()
		if not os.getenv("OPENAI_API_KEY"):
			raise AnalyticalScanError("OPENAI_API_KEY is not set")
		try:
			from openai import OpenAI

			client = OpenAI()
		except Exception as exc:
			raise AnalyticalScanError(
				f"could not initialize OpenAI client: {exc}"
			) from exc
	try:
		response = client.responses.parse(
			model=model,
			reasoning={"effort": reasoning_effort},
			input=[
				{"role": "system", "content": ANALYTICAL_SCAN_PROMPT},
				{"role": "user", "content": context},
			],
			text_format=AnalyticalScanResult,
		)
		parsed = getattr(response, "output_parsed", None)
		result = (
			parsed
			if isinstance(parsed, AnalyticalScanResult)
			else AnalyticalScanResult.model_validate(parsed)
		)
		result = validate_analytical_scan_result(result, supplied_refs)
	except AnalyticalScanError:
		raise
	except Exception as exc:
		raise AnalyticalScanError(
			f"structured Analytical Scan call failed: {exc}"
		) from exc
	effective_run_id = run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
	metadata: dict[str, Any] = {
		"ticker": ticker.strip().upper(),
		**_filing_metadata(
			filing if filing is not None else pnl.attrs.get("edgar_filing")
		),
		"model": model,
		"reasoning_effort": reasoning_effort,
		"prompt_version": PROMPT_VERSION,
		"schema_version": SCHEMA_VERSION,
		"run_id": effective_run_id,
		"timestamp_utc": datetime.now(UTC).isoformat(),
		"finding_count": len(result.findings),
		"supplied_line_count": len(supplied_refs),
	}
	return result, metadata


def save_analytical_scan(
	ticker: str,
	result: AnalyticalScanResult,
	metadata: dict[str, Any],
	context: str,
	output_root: str | Path = "data",
) -> Path:
	if not isinstance(context, str):
		raise TypeError("context must be a string")
	if "run_id" not in metadata or not _clean(metadata["run_id"]):
		raise AnalyticalScanError("scan metadata must contain run_id")
	refs = set(_LINE_REF_PATTERN.findall(context))
	validated = validate_analytical_scan_result(result, refs)
	output_directory = (
		Path(output_root) / ticker.strip().upper() / "03_output" / "analysis"
	)
	output_directory.mkdir(parents=True, exist_ok=True)
	output_path = output_directory / f"analytical_scan_{metadata['run_id']}.json"
	payload = {
		"metadata": metadata,
		"context": context,
		"result": validated.model_dump(mode="json"),
	}
	output_path.write_text(
		json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
		encoding="utf-8",
	)
	return output_path


def render_analytical_scan_summary(result: AnalyticalScanResult) -> str:
	validated = (
		result
		if isinstance(result, AnalyticalScanResult)
		else AnalyticalScanResult.model_validate(result)
	)
	lines = [f"Analytical Scan: {len(validated.findings)} finding(s)"]
	for finding in validated.findings:
		lines.extend(
			[
				f"{finding.rank}. [{finding.importance}] {finding.title} ({', '.join(finding.affected_line_refs)})",
				f"   Observation: {finding.observation}",
				f"   Why it matters: {finding.why_it_matters}",
			]
		)
		for question in finding.investigation_questions:
			lines.append(f"   Question: {question}")
	return "\n".join(lines)
