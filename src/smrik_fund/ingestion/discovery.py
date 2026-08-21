"""Bounded, filing-grounded discovery of research topics."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, field_validator

DEFAULT_MODEL = "gpt-5.6-luna"
DEFAULT_REASONING_EFFORT = "high"
PROMPT_VERSION = "discovery-v1"
SCHEMA_VERSION = "discovery-result-v1"
MAX_TOPICS = 5
MAX_QUERIES_PER_TOPIC = 3
MAX_CONTEXT_CHARS = 12000
MAX_CONTEXT_PASSAGES = 12

DISCOVERY_PROMPT = """You review a reported financial statement and a bounded set of
passages from its filing. Identify up to five distinct topics that merit direct
source-text research for normalization analysis.

Return only short topic names, an optional exact reported line label, one to
three concise literal filing search phrases, and a short reason why each topic
deserves research. Prefer a distinctive contiguous phrase from the supplied
passages rather than a generic line label or a broad company/product name.
Each phrase will be used once as an exact filing search and must be distinctive
enough to have one source match; return one phrase unless additional distinct
passages are necessary. Include enough neighboring wording to disambiguate a
repeated phrase; do not reduce a query to a short noun phrase.
Do not return amounts, calculations, citations, identifiers, approval decisions,
confidence scores, categories, or workflow state. Do not invent a topic or
search phrase that is unsupported by the supplied input.
"""


class DiscoveryTopic(BaseModel):
	"""The minimal model output needed to start one exact retrieval pass."""

	model_config = ConfigDict(extra="forbid")

	name: str = Field(min_length=1, max_length=120)
	likely_target_line: str | None = Field(default=None, max_length=160)
	queries: list[str] = Field(
		min_length=1,
		max_length=MAX_QUERIES_PER_TOPIC,
	)
	rationale: str = Field(min_length=1, max_length=400)

	@field_validator("queries")
	@classmethod
	def _validate_queries(cls, value: list[str]) -> list[str]:
		if any(not isinstance(query, str) or not query.strip() for query in value):
			raise ValueError("queries must be non-empty strings")
		if any(len(query.strip()) > 240 for query in value):
			raise ValueError("queries must be concise")
		return value


class DiscoveryResult(BaseModel):
	"""One bounded discovery response; zero topics is a valid result."""

	model_config = ConfigDict(extra="forbid")

	topics: list[DiscoveryTopic] = Field(max_length=MAX_TOPICS)


class DiscoveryError(RuntimeError):
	"""The one-call discovery boundary could not produce a safe result."""


def _clean_text(value: object) -> str:
	return " ".join(str(value).split())


def _truthy(value: object) -> bool:
	if value is None or pd.isna(value):
		return False
	if isinstance(value, str):
		return value.strip().casefold() in {"1", "true", "yes"}
	return bool(value)


def _pnl_labels(pnl: pd.DataFrame) -> list[str]:
	"""Return non-dimensional displayed source labels in stable row order."""
	if not isinstance(pnl, pd.DataFrame):
		raise TypeError("pnl must be a pandas DataFrame")
	labels: list[str] = []
	for _, row in pnl.iterrows():
		if any(_truthy(row.get(column)) for column in ("abstract", "dimension", "is_breakdown")):
			continue
		value = row.get("label")
		if value is None or pd.isna(value):
			continue
		label = _clean_text(value)
		if label and label.casefold() not in {item.casefold() for item in labels}:
			labels.append(label)
	return labels


def _filing_identity(filing: Any) -> dict[str, str | None]:
	def value(*names: str) -> str | None:
		for name in names:
			try:
				candidate = getattr(filing, name)
			except Exception:
				continue
			if candidate is not None and str(candidate).strip():
				return str(candidate).strip()
		return None

	return {
		"accession": value("accession_no", "accession_number"),
		"form": value("form"),
		"filing_date": value("filing_date"),
		"period_of_report": value("report_date", "period_of_report"),
		"primary_document": value("primary_document"),
		"source_url": value("text_url", "filing_url", "url", "source_path"),
	}


def build_discovery_context(
	pnl: pd.DataFrame,
	filing: Any,
	*,
	max_chars: int = MAX_CONTEXT_CHARS,
	max_passages: int = MAX_CONTEXT_PASSAGES,
	line_radius: int = 1,
) -> dict[str, Any]:
	"""Build bounded context from filing text around every supplied source label.

	The selector uses only row labels, stable source order, and fixed offsets. It
	never searches for a known topic or uses a prior packet.
	"""
	if filing is None:
		raise DiscoveryError("an EdgarTools filing is required")
	if max_chars < 1 or max_passages < 1 or line_radius < 0:
		raise ValueError("context bounds must be positive")
	try:
		filing_text = filing.text()
	except Exception as exc:
		raise DiscoveryError(f"filing text failed: {exc}") from exc
	if not isinstance(filing_text, str):
		raise DiscoveryError("filing text must be a string")

	lines = filing_text.splitlines()
	labels = _pnl_labels(pnl)
	neutral_cues = (
		"increased",
		"decreased",
		"included",
		"rate",
		"margin",
		"percent",
		"compared",
		"year over year",
	)
	passages: list[dict[str, Any]] = []
	seen: set[tuple[int, int, str]] = set()
	for label in labels:
		pattern = re.compile(re.escape(label), flags=re.IGNORECASE)
		matches = [
			(line_number, line)
			for line_number, line in enumerate(lines)
			if pattern.search(line) is not None
		]
		if len(matches) > 1:
			preferred = [
				match
				for match in matches
				if any(
					re.search(rf"\b{re.escape(cue)}\b", match[1], re.IGNORECASE)
					for cue in neutral_cues
				)
			]
			prefix_matches = [
				match
				for match in preferred
				if re.match(
					rf"\s*{re.escape(label)}\b",
					match[1],
					re.IGNORECASE,
				)
			]
			preferred = prefix_matches or preferred
			matches = preferred or matches
		for line_number, _line in matches[:1]:
			start = max(0, line_number - line_radius)
			end = min(len(lines), line_number + line_radius + 1)
			text = "\n".join(lines[start:end]).strip()
			key = (start + 1, end, text)
			if not text or key in seen:
				continue
			seen.add(key)
			passages.append(
				{
					"label": label,
					"source_line_start": start + 1,
					"source_line_end": end,
					"text": text,
				}
			)
			if len(passages) >= max_passages:
				break
		if len(passages) >= max_passages:
			break

	selected: list[dict[str, Any]] = []
	used_chars = 0
	for passage in passages:
		serialized_size = len(passage["text"]) + len(passage["label"]) + 80
		if selected and used_chars + serialized_size > max_chars:
			break
		if not selected and serialized_size > max_chars:
			passage = {**passage, "text": passage["text"][:max_chars]}
		selected.append(passage)
		used_chars += serialized_size

	return {
		"filing_identity": _filing_identity(filing),
		"context_method": "fixed windows around supplied statement labels",
		"source_text_available": bool(filing_text),
		"source_line_count": len(lines),
		"passages": selected,
	}


def _normalise_topic(topic: DiscoveryTopic) -> DiscoveryTopic:
	name = _clean_text(topic.name)
	target = None if topic.likely_target_line is None else _clean_text(topic.likely_target_line)
	queries: list[str] = []
	seen_queries: set[str] = set()
	for query in topic.queries:
		clean_query = _clean_text(query)
		if clean_query and clean_query.casefold() not in seen_queries:
			seen_queries.add(clean_query.casefold())
			queries.append(clean_query)
	if not name or not all(queries) or not _clean_text(topic.rationale):
		raise DiscoveryError("discovery topics must contain non-empty text")
	return topic.model_copy(
		update={
			"name": name,
			"likely_target_line": target or None,
			"queries": queries,
			"rationale": _clean_text(topic.rationale),
		}
	)


def discovery_topic_key(topic: DiscoveryTopic) -> tuple[str, str, tuple[str, ...]]:
	"""Return the documented exact key used for local first-occurrence collapse."""
	normalized = _normalise_topic(topic)
	return (
		normalized.name.casefold(),
		(normalized.likely_target_line or "").casefold(),
		tuple(query.casefold() for query in normalized.queries),
	)


def deduplicate_topics(
	topics: Iterable[DiscoveryTopic],
) -> tuple[list[DiscoveryTopic], list[dict[str, Any]]]:
	"""Collapse only exact normalized topic duplicates, preserving order."""
	retained: list[DiscoveryTopic] = []
	records: list[dict[str, Any]] = []
	seen: dict[tuple[str, str, tuple[str, ...]], int] = {}
	for index, raw_topic in enumerate(topics):
		topic = _normalise_topic(raw_topic)
		key = discovery_topic_key(topic)
		if key in seen:
			records.append(
				{
					"input_index": index,
					"status": "duplicate",
					"topic": topic.model_dump(mode="json"),
					"collapsed_into": seen[key],
				}
			)
			continue
		seen[key] = index
		retained.append(topic)
		records.append(
			{
				"input_index": index,
				"status": "retained",
				"topic": topic.model_dump(mode="json"),
			}
		)
	return retained, records


def run_discovery(
	ticker: str,
	pnl: pd.DataFrame,
	filing_context: dict[str, Any],
	*,
	client: Any | None = None,
	model: str = DEFAULT_MODEL,
	reasoning_effort: str = DEFAULT_REASONING_EFFORT,
	run_id: str | None = None,
) -> tuple[DiscoveryResult, dict[str, Any]]:
	"""Make exactly one structured discovery call over supplied context."""
	if not isinstance(filing_context, dict):
		raise TypeError("filing_context must be a dictionary")
	if client is None:
		load_dotenv()
		if not os.getenv("OPENAI_API_KEY"):
			raise DiscoveryError("OPENAI_API_KEY is not set")
		try:
			from openai import OpenAI

			client = OpenAI()
		except Exception as exc:
			raise DiscoveryError(f"could not initialize OpenAI client: {exc}") from exc

	pnl_records = pnl.astype(object).where(pd.notna(pnl), None).to_dict(orient="records")
	payload = {
		"ticker": ticker.strip().upper(),
		"pnl": pnl_records,
		"filing_context": filing_context,
	}
	try:
		response = client.responses.parse(
			model=model,
			reasoning={"effort": reasoning_effort},
			input=[
				{"role": "system", "content": DISCOVERY_PROMPT},
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
			text_format=DiscoveryResult,
		)
		parsed = getattr(response, "output_parsed", None)
		result = parsed if isinstance(parsed, DiscoveryResult) else DiscoveryResult.model_validate(parsed)
		if len(result.topics) > MAX_TOPICS:
			raise DiscoveryError(f"discovery returned more than {MAX_TOPICS} topics")
		result = DiscoveryResult(topics=[_normalise_topic(topic) for topic in result.topics])
	except DiscoveryError:
		raise
	except Exception as exc:
		raise DiscoveryError(f"structured discovery call failed: {exc}") from exc

	effective_run_id = run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
	metadata = {
		"ticker": payload["ticker"],
		"model": model,
		"reasoning_effort": reasoning_effort,
		"prompt_version": PROMPT_VERSION,
		"schema_version": SCHEMA_VERSION,
		"run_id": effective_run_id,
		"timestamp_utc": datetime.now(UTC).isoformat(),
		"topic_count": len(result.topics),
	}
	return result, metadata


def save_discovery_result(
	ticker: str,
	result: DiscoveryResult,
	metadata: dict[str, Any],
	*,
	context: dict[str, Any],
	topics: list[dict[str, Any]],
	output_root: str | Path = "data",
) -> Path:
	"""Persist raw discovery output and deterministic topic decisions."""
	output_directory = Path(output_root) / ticker.strip().upper() / "03_output" / "analysis"
	output_directory.mkdir(parents=True, exist_ok=True)
	output_path = output_directory / f"discovery_{metadata['run_id']}.json"
	output_path.write_text(
		json.dumps(
			{
				"metadata": metadata,
				"context": context,
				"result": result.model_dump(mode="json"),
				"topics": topics,
			},
			indent=2,
			ensure_ascii=False,
		)
		+ "\n",
		encoding="utf-8",
	)
	return output_path
