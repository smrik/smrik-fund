"""Bounded EdgarTools filing-evidence retrieval for discovered topics."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


class FilingEvidenceError(RuntimeError):
	"""The filing or its evidence packet does not satisfy the V1 contract."""


RESTRUCTURING_SEARCH_QUERIES = (
	r"Operating\s+expenses\s+increased\s+\$940\s+million[\s\S]*?"
	r"impairment\s+and\s+other\s+related\s+expenses\s+in\s+our\s+XBOX\s+business",
	r"Research\s+and\s+development\s+expenses\s+increased\s+\$3\.1\s+billion[\s\S]*?"
	r"impairment\s+and\s+other\s+related\s+expenses\s+in\s+our\s+XBOX\s+business",
)

MAX_EVIDENCE_ITEMS = 20

_ITEM_HEADER = re.compile(r"^###\s+(E[1-9]\d*)\s*$")
_ANY_ITEM_HEADER = re.compile(r"^###\s+E\S*\s*$")
_ITEM_METADATA = re.compile(r"^(Query|Source|Section|Locator):\s?(.*)$")
_TOP_METADATA = re.compile(r"^([A-Za-z][A-Za-z ]+):\s?(.*)$")


def _filing_value(filing: Any, *names: str) -> str | None:
	for name in names:
		try:
			value = getattr(filing, name)
		except Exception:
			continue
		if value is None:
			continue
		text = str(value).strip()
		if text:
			return text
	return None


def _search_sections(filing: Any, query: str) -> list[Any]:
	try:
		results = filing.search(query, regex=True)
	except Exception as exc:
		raise FilingEvidenceError(f"EdgarTools search failed: {exc}") from exc
	sections = getattr(results, "sections", None)
	if sections is None:
		try:
			sections = list(results)
		except TypeError as exc:
			raise FilingEvidenceError("EdgarTools search returned no sections") from exc
	return list(sections)


def _literal_occurrences(text: str, query: str) -> list[tuple[int, int]]:
	"""Return every case-insensitive literal occurrence without regex semantics."""
	folded_query = query.casefold()
	occurrences: list[tuple[int, int]] = []
	for start in range(max(0, len(text) - len(query) + 1)):
		if text[start : start + len(query)].casefold() == folded_query:
			occurrences.append((start, start + len(query)))
	return occurrences


def _source_matches(
	text: str, query: str
) -> list[tuple[str, int, int, int, int]]:
	"""Return exact source excerpts and offsets for every literal occurrence."""
	occurrences = _literal_occurrences(text, query)
	if not occurrences:
		raise FilingEvidenceError(
			"filing text contains no exact literal occurrence for evidence query"
		)
	return _source_matches_by_offsets(text, occurrences)


def _source_matches_regex(
	text: str, query: str
) -> list[tuple[str, int, int, int, int]]:
	"""Preserve the fixed legacy regex fixture contract."""
	matches = list(re.finditer(query, text, flags=re.IGNORECASE))
	if len(matches) != 1:
		raise FilingEvidenceError(
			"filing text must contain exactly one match for each evidence query; "
			f"query produced {len(matches)} matches"
		)
	match = matches[0]
	return _source_matches_by_offsets(text, [(match.start(), match.end())])


def _source_matches_by_offsets(
	text: str, occurrences: list[tuple[int, int]]
) -> list[tuple[str, int, int, int, int]]:
	"""Render source line/offset metadata for precomputed spans."""
	lines = text.splitlines(keepends=True)
	line_starts: list[int] = []
	offset = 0
	for line in lines:
		line_starts.append(offset)
		offset += len(line)

	def line_number(position: int) -> int:
		for number in range(len(line_starts), 0, -1):
			if line_starts[number - 1] <= position:
				return number
		return 1

	matches: list[tuple[str, int, int, int, int]] = []
	for start, end in occurrences:
		start_line = line_number(start)
		end_line = line_number(end - 1)
		line_start_offset = line_starts[start_line - 1]
		line_end_offset = (
			line_starts[end_line] if end_line < len(line_starts) else len(text)
		)
		excerpt = text[line_start_offset:line_end_offset].rstrip("\r\n")
		if not excerpt:
			raise FilingEvidenceError("filing search produced an empty source excerpt")
		matches.append((excerpt, start_line, end_line, start, end))
	return matches


def _literal_search_sections(filing: Any, query: str) -> list[Any]:
	"""Find every honest EdgarTools section locator for a literal query.

	EdgarTools' non-regex search is a ranked token search. We retain every
	returned section whose source document contains the complete literal phrase;
	no section is selected as a best hit.
	"""
	try:
		results = filing.search(query, regex=False)
	except Exception as exc:
		raise FilingEvidenceError(f"EdgarTools literal search failed: {exc}") from exc
	sections = getattr(results, "sections", None)
	if sections is None:
		try:
			sections = list(results)
		except TypeError as exc:
			raise FilingEvidenceError("EdgarTools literal search returned no sections") from exc
	matched: list[Any] = []
	for section in list(sections):
		loc = getattr(section, "loc", None)
		document = getattr(section, "doc", None)
		if loc is None or not isinstance(document, str):
			continue
		if _literal_occurrences(document, query):
			matched.append(section)
	if not matched:
		raise FilingEvidenceError(
			"EdgarTools literal search returned no section with an exact query occurrence"
		)
	return matched


def _section_name(section: Any, loc: object) -> str:
	for name in ("section", "title", "name"):
		value = getattr(section, name, None)
		if value is not None and str(value).strip():
			return str(value).strip()
	return f"EntityFiling search section loc {loc}"


def _render_packet(
	metadata: dict[str, Any],
	items: list[dict[str, Any]],
) -> str:
	lines = [
		f"# {metadata['ticker']} {metadata['topic']} evidence",
		"",
		f"Ticker: {metadata['ticker']}",
		f"Topic: {metadata['topic']}",
		f"Form: {metadata['form']}",
		f"Filing accession: {metadata['filing_accession']}",
		f"Filing date: {metadata['filing_date']}",
		f"Period of report: {metadata['period_of_report']}",
		f"Primary document: {metadata['primary_document']}",
		*(
			[f"Filing URL: {metadata['filing_url']}"]
			if metadata.get("filing_url")
			else []
		),
		f"Source: {metadata['source_url']}",
		f"Text URL: {metadata['text_url']}",
		f"Retrieval method: {metadata['retrieval_method']}",
		"",
		"## Filing excerpts",
		"",
	]
	for item in items:
		lines.extend(
			[
				f"### {item['evidence_id']}",
				f"Query: {item['query']}",
				f"Source: {metadata['source_url']}",
				f"Section: {item['section']}",
				(
					"Locator: accession "
					f"{metadata['filing_accession']}; search section loc(s) "
					f"{item['search_locs']}; source text lines "
					f"{item['source_line_start']}-{item['source_line_end']}; "
					f"source text offsets {item['source_offset_start']}-"
					f"{item['source_offset_end']}"
				),
				"",
			]
		)
		lines.extend(f"> {line}" for line in item["excerpt"].split("\n"))
		lines.append("")
	return "\n".join(lines).rstrip() + "\n"


def _retrieve_filing_evidence(
	filing: Any,
	ticker: str,
	topic: str,
	queries: list[str] | tuple[str, ...],
	*,
	literal: bool,
	output_path: str | Path | None = None,
) -> tuple[str, dict[str, Any]]:
	"""Retrieve one topic with either literal discovery or fixed legacy regex."""
	if filing is None:
		raise FilingEvidenceError("an EdgarTools filing is required")
	ticker = ticker.strip().upper()
	if not ticker:
		raise FilingEvidenceError("ticker is required")
	if not isinstance(topic, str) or not topic.strip():
		raise FilingEvidenceError("topic is required")
	if isinstance(queries, str) or not queries:
		raise FilingEvidenceError("at least one retrieval query is required")
	queries = tuple(queries)
	if any(not isinstance(query, str) or not query.strip() for query in queries):
		raise FilingEvidenceError("retrieval queries must be non-empty strings")
	try:
		filing_text = filing.text()
	except Exception as exc:
		raise FilingEvidenceError(f"EdgarTools filing text failed: {exc}") from exc
	if not isinstance(filing_text, str) or not filing_text:
		raise FilingEvidenceError("EdgarTools filing text is empty")

	accession = _filing_value(filing, "accession_no", "accession_number")
	form = _filing_value(filing, "form")
	filing_date = _filing_value(filing, "filing_date")
	period_of_report = _filing_value(filing, "report_date", "period_of_report")
	primary_document = _filing_value(filing, "primary_document")
	text_url = _filing_value(filing, "text_url")
	filing_url = _filing_value(filing, "filing_url", "url")
	source_url = text_url or filing_url or _filing_value(filing, "source_path")
	if not accession or not source_url:
		raise FilingEvidenceError(
			"filing identity must include an accession and an honest source URL/path"
		)

	items: list[dict[str, Any]] = []
	for query_index, query in enumerate(queries):
		sections = (
			_literal_search_sections(filing, query)
			if literal
			else _search_sections(filing, query)
		)
		search_locs = sorted(
			{section.loc for section in sections}, key=str
		)
		if not search_locs:
			raise FilingEvidenceError("EdgarTools search hit has no honest section locator")
		section_names = list(
			dict.fromkeys(
				_section_name(section, section.loc) for section in sections
			)
		)
		match_renderer = _source_matches if literal else _source_matches_regex
		for excerpt, start_line, end_line, start_offset, end_offset in match_renderer(
			filing_text, query
		):
			items.append(
				{
					"query": query,
					"query_index": query_index,
					"excerpt": excerpt,
					"source_line_start": start_line,
					"source_line_end": end_line,
					"source_offset_start": start_offset,
					"source_offset_end": end_offset,
					"search_locs": ", ".join(str(loc) for loc in search_locs),
					"section": " | ".join(section_names),
				}
			)
			if literal and len(items) > MAX_EVIDENCE_ITEMS:
				raise FilingEvidenceError(
					f"literal retrieval exceeded {MAX_EVIDENCE_ITEMS} evidence items"
				)

	items.sort(
		key=lambda item: (
			item["source_offset_start"],
			item["query_index"],
			str(item["search_locs"]),
		)
	)
	for number, item in enumerate(items, start=1):
		item["evidence_id"] = f"E{number}"
	topic = " ".join(topic.split())
	metadata: dict[str, Any] = {
		"ticker": ticker,
		"topic": topic,
		"queries": list(queries),
		"form": form or "unknown",
		"filing_accession": accession,
		"filing_date": filing_date or "unknown",
		"period_of_report": period_of_report or "unknown",
		"primary_document": primary_document or "unknown",
		"filing_url": filing_url,
		"text_url": text_url or source_url,
		"source_url": source_url,
		"retrieval_method": (
			"EdgarTools EntityFiling.search(regex=False) literal section hits + "
			"EntityFiling.text() literal occurrences"
			if literal
			else "EdgarTools EntityFiling.search(regex=True) + EntityFiling.text()"
		),
		"evidence_item_count": len(items),
	}
	packet = _render_packet(metadata, items)
	validate_evidence_packet(packet, require_identity=True)
	if output_path is not None:
		path = Path(output_path)
		path.parent.mkdir(parents=True, exist_ok=True)
		path.write_text(packet, encoding="utf-8")
		metadata["evidence_file"] = str(path)
	return packet, metadata


def retrieve_filing_evidence(
	filing: Any,
	ticker: str,
	topic: str,
	queries: list[str] | tuple[str, ...],
	*,
	output_path: str | Path | None = None,
) -> tuple[str, dict[str, Any]]:
	"""Retrieve one discovery topic using literal model-supplied queries."""
	return _retrieve_filing_evidence(
		filing,
		ticker,
		topic,
		queries,
		literal=True,
		output_path=output_path,
	)


def retrieve_restructuring_evidence(
	filing: Any,
	ticker: str,
	*,
	output_path: str | Path | None = None,
) -> tuple[str, dict[str, Any]]:
	"""Retrieve the fixed restructuring topic from one EdgarTools filing.

	The search strings are retrieval inputs only. Excerpts come from the exact
	contiguous source-text lines returned by ``EntityFiling.text()``.
	"""
	return _retrieve_filing_evidence(
		filing,
		ticker,
		"restructuring",
		RESTRUCTURING_SEARCH_QUERIES,
		literal=False,
		output_path=output_path,
	)


def retrieve_legacy_filing_evidence(
	filing: Any,
	ticker: str,
	*,
	output_path: str | Path | None = None,
) -> tuple[str, dict[str, Any]]:
	"""Keep the fixed fixture seam available to direct legacy callers only."""
	return retrieve_restructuring_evidence(
		filing,
		ticker,
		output_path=output_path,
	)


def parse_evidence_packet(
	packet: str,
	*,
	require_identity: bool = False,
) -> dict[str, Any]:
	"""Parse and validate packet structure without changing quoted text."""
	if not isinstance(packet, str) or not packet:
		raise FilingEvidenceError("evidence packet must be a non-empty string")
	metadata: dict[str, str] = {}
	items: dict[str, dict[str, str]] = {}
	current: dict[str, Any] | None = None
	for line in packet.splitlines():
		if _ANY_ITEM_HEADER.fullmatch(line):
			if current is not None:
				_finalize_item(items, current, strict=require_identity)
			match = _ITEM_HEADER.fullmatch(line)
			if match is None:
				raise FilingEvidenceError(f"malformed evidence item header: {line!r}")
			current = {
				"evidence_id": match.group(1),
				"excerpt_lines": [],
			}
			continue
		if current is None:
			match = _TOP_METADATA.fullmatch(line)
			if match:
				metadata[match.group(1).strip().lower().replace(" ", "_")] = match.group(2)
			continue
		if line.startswith("> "):
			current["excerpt_lines"].append(line[2:])
			continue
		if not line.strip():
			continue
		match = _ITEM_METADATA.fullmatch(line)
		if match:
			key = match.group(1).lower()
			if key in current:
				raise FilingEvidenceError(
					f"duplicate {key} metadata for {current['evidence_id']}"
				)
			current[key] = match.group(2)
			continue
		if line.startswith("###"):
			raise FilingEvidenceError(f"malformed evidence item header: {line!r}")
		raise FilingEvidenceError(
			f"malformed evidence item line for {current['evidence_id']}: {line!r}"
		)
	if current is not None:
		_finalize_item(items, current, strict=require_identity)
	if not items:
		raise FilingEvidenceError("evidence packet contains no evidence items")
	if require_identity:
		for key in ("ticker", "filing_accession", "source"):
			if not metadata.get(key):
				raise FilingEvidenceError(f"evidence packet missing filing identity: {key}")
		accession = metadata["filing_accession"]
		if any(accession not in item["locator"] for item in items.values()):
			raise FilingEvidenceError("evidence locator does not retain filing accession")
	return {"metadata": metadata, "items": items}


def _finalize_item(
	items: dict[str, dict[str, str]],
	current: dict[str, Any],
	*,
	strict: bool,
) -> None:
	evidence_id = current["evidence_id"]
	if evidence_id in items:
		raise FilingEvidenceError(f"duplicate evidence ID: {evidence_id}")
	for key in (("source", "section", "locator") if strict else ("source",)):
		if not str(current.get(key, "")).strip():
			raise FilingEvidenceError(f"{evidence_id} missing {key} metadata")
	excerpt = "\n".join(current["excerpt_lines"])
	if not excerpt.strip():
		raise FilingEvidenceError(f"{evidence_id} has an empty excerpt")
	items[evidence_id] = {
		"query": str(current.get("Query", current.get("query", ""))),
		"source": str(current.get("source", "")),
		"section": str(current.get("section", "")),
		"locator": str(current.get("locator", "")),
		"excerpt": excerpt,
	}


def validate_evidence_packet(
	packet: str,
	*,
	require_identity: bool = False,
) -> dict[str, Any]:
	"""Validate packet and return stable ID-to-evidence metadata."""
	return parse_evidence_packet(packet, require_identity=require_identity)


def validate_evidence_refs(
	packet: str,
	evidence_refs: list[str],
	*,
	require_identity: bool = False,
) -> dict[str, Any]:
	"""Fail closed when a candidate cites an unknown packet ID."""
	parsed = validate_evidence_packet(packet, require_identity=require_identity)
	unknown = sorted(set(evidence_refs).difference(parsed["items"]))
	if unknown:
		raise FilingEvidenceError(
			"candidate references evidence not in supplied packet: "
			+ ", ".join(unknown)
		)
	return parsed
