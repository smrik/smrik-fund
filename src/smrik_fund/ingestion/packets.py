from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.stage_00_data.filing_retrieval import _extract_numbered_note_sections


@dataclass(frozen=True, slots=True)
class PacketsResult:
    output_dir: Path
    packet_count: int
    canonical_keys: list[str]


def _normalize_for_search(text: str) -> str:
    # Lowercase, hyphens and underscores become spaces, collapse non-alphanum to space.
    lowered = text.lower().replace("-", " ").replace("_", " ")
    normalized = re.sub(r"[^a-z0-9]+", " ", lowered)
    return " ".join(normalized.split())


def _load_reconciliation(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _load_financial_facts(
    path: Path,
) -> tuple[dict[str, dict[str, str]], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    by_fact_id: dict[str, dict[str, str]] = {}
    for row in rows:
        fid = str(row.get("fact_id") or "").strip()
        if fid:
            # Keep first occurrence; duplicates with same fact_id are identical.
            by_fact_id.setdefault(fid, row)
    return by_fact_id, rows


def _extract_notes(filing_path: Path) -> tuple[list[tuple[str, str, str]], str]:
    text = filing_path.read_text(encoding="utf-8", errors="replace")
    notes_text, sections = _extract_numbered_note_sections(text)
    return sections, notes_text


def _most_common_label(rows: list[dict[str, str]], canonical_key: str) -> str:
    labels = [
        str(r.get("label") or "").strip()
        for r in rows
        if r.get("canonical_key") == canonical_key and str(r.get("label") or "").strip()
    ]
    if not labels:
        return ""
    counter = Counter(labels)
    return counter.most_common(1)[0][0]


def _note_mentions_key(
    note_body: str, note_heading: str, canonical_key: str, label: str
) -> bool:
    # Normalize note text once per check is done by caller; here we normalize inside for simplicity
    # but caller may pass already normalized strings.
    # Check key phrase and label phrase as substring search.
    key_phrase = _normalize_for_search(canonical_key.replace("_", " "))
    label_phrase = _normalize_for_search(label) if label else ""
    combined = _normalize_for_search(f"{note_heading} {note_body}")
    if key_phrase and key_phrase in combined:
        return True
    if label_phrase and label_phrase in combined:
        return True
    # Fallback: all tokens of key phrase appear individually (covers hyphenated labels)
    if key_phrase:
        tokens = key_phrase.split()
        if len(tokens) > 1 and all(tok in combined for tok in tokens):
            return True
    return False


def write_packets_artifacts(
    ticker: str,
    *,
    ingestion_root: str | Path = "data",
    filing_accession: str = "0000950170-25-100235",
    output_subdir: str = "packets",
) -> PacketsResult:
    """Build evidence packets that bundle CIQ and EDGAR without choosing between them."""
    normalized_ticker = ticker.strip().upper()
    if not normalized_ticker:
        raise ValueError("ticker is required")

    root = Path(ingestion_root)
    ticker_dir = root / normalized_ticker
    reconciliation_path = ticker_dir / "03_output" / "reconciliation_checks.csv"
    financial_facts_path = ticker_dir / "02_processing" / "financial_facts.csv"
    filing_path = (
        ticker_dir
        / "01_source"
        / "edgar"
        / "filings"
        / f"{filing_accession}.txt"
    )

    if not reconciliation_path.exists():
        raise FileNotFoundError(f"reconciliation.csv not found: {reconciliation_path}")
    if not financial_facts_path.exists():
        raise FileNotFoundError(
            f"financial_facts.csv not found: {financial_facts_path}"
        )
    if not filing_path.exists():
        raise FileNotFoundError(f"filing text not found: {filing_path}")

    reconciliation_rows = _load_reconciliation(reconciliation_path)
    fact_by_id, all_facts = _load_financial_facts(financial_facts_path)
    sections, _notes_text = _extract_notes(filing_path)

    # Build notes lookup for notes.json
    notes_by_key: dict[str, dict[str, str]] = {}
    for note_key, heading, body in sections:
        # Keep last block for duplicated key (already handled by _extract_numbered_note_sections)
        notes_by_key[note_key] = {
            "note_key": note_key,
            "heading": heading,
            "body": body,
        }

    # Distinct canonical keys present in reconciliation.csv
    canonical_keys = sorted(
        {
            str(r.get("canonical_key") or "").strip()
            for r in reconciliation_rows
            if str(r.get("canonical_key") or "").strip()
        }
    )

    # Group facts by canonical_key for orphan detection
    facts_by_key: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in all_facts:
        ck = str(row.get("canonical_key") or "").strip()
        if ck in set(canonical_keys):
            facts_by_key[ck].append(row)

    # Distinct reconciliation rows per (canonical_key, period_end, ciq_base_value, xbrl_base_value, status)
    # This collapses the cartesian product duplication.
    seen_distinct: dict[tuple[str, str, str, str, str], dict[str, str]] = {}
    for row in reconciliation_rows:
        identity = (
            str(row.get("canonical_key") or ""),
            str(row.get("period_end") or ""),
            str(row.get("ciq_base_value") or ""),
            str(row.get("xbrl_base_value") or ""),
            str(row.get("status") or ""),
        )
        seen_distinct.setdefault(identity, row)

    # Map canonical_key -> period_end -> representative row (first distinct for that period)
    period_map_by_key: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    conflict_unresolved: dict[str, list[str]] = defaultdict(list)
    for row in seen_distinct.values():
        ck = str(row.get("canonical_key") or "")
        period_end = str(row.get("period_end") or "")
        if not ck or not period_end:
            continue
        existing = period_map_by_key[ck].get(period_end)
        if existing is None:
            period_map_by_key[ck][period_end] = row
        else:
            # Same period with different values -> record as unresolved, keep first.
            if str(existing.get("ciq_base_value")) != str(
                row.get("ciq_base_value")
            ) or str(existing.get("xbrl_base_value")) != str(
                row.get("xbrl_base_value")
            ):
                conflict_unresolved[ck].append(
                    f"conflicting comparison for {period_end}: existing ciq={existing.get('ciq_base_value')} xbrl={existing.get('xbrl_base_value')} vs additional ciq={row.get('ciq_base_value')} xbrl={row.get('xbrl_base_value')} (fact_ids {existing.get('ciq_fact_id')}/{row.get('ciq_fact_id')})"
                )

    output_dir = ticker_dir / "03_output" / output_subdir
    output_dir.mkdir(parents=True, exist_ok=True)

    index_entries: list[dict[str, Any]] = []

    for canonical_key in canonical_keys:
        period_map = period_map_by_key.get(canonical_key, {})
        sorted_periods = sorted(period_map.keys())
        periods: list[dict[str, Any]] = []
        unresolved: list[str] = []
        # Seed with conflict entries
        unresolved.extend(conflict_unresolved.get(canonical_key, []))

        # Determine label for note matching
        label = _most_common_label(all_facts, canonical_key)

        # Build note references for this key
        note_references: list[dict[str, str]] = []
        for note_key, heading, body in sections:
            if _note_mentions_key(body, heading, canonical_key, label):
                note_references.append({"note_key": note_key, "heading": heading})
        # Deduplicate preserving order
        seen_note_keys: set[str] = set()
        deduped_refs: list[dict[str, str]] = []
        for ref in note_references:
            if ref["note_key"] not in seen_note_keys:
                deduped_refs.append(ref)
                seen_note_keys.add(ref["note_key"])
        note_references = deduped_refs

        # Collect fact ids used in periods for duplicate detection
        used_fact_ids: set[str] = set()

        for period_end in sorted_periods:
            row = period_map[period_end]
            ciq_fact_id = str(row.get("ciq_fact_id") or "").strip()
            xbrl_fact_id = str(row.get("xbrl_fact_id") or "").strip()
            used_fact_ids.add(ciq_fact_id)
            used_fact_ids.add(xbrl_fact_id)

            ciq_fact = fact_by_id.get(ciq_fact_id)
            edgar_fact = fact_by_id.get(xbrl_fact_id)

            # Preserve raw unit/currency as reported; do not normalize.
            ciq_unit = str(ciq_fact.get("unit") or "") if ciq_fact is not None else ""
            ciq_currency = (
                str(ciq_fact.get("currency") or "") if ciq_fact is not None else ""
            )
            ciq_locator = (
                str(ciq_fact.get("source_locator") or row.get("ciq_fact_id") or "")
                if ciq_fact is not None
                else str(row.get("ciq_fact_id") or "")
            )
            edgar_unit = (
                str(edgar_fact.get("unit") or "") if edgar_fact is not None else ""
            )
            edgar_currency = (
                str(edgar_fact.get("currency") or "") if edgar_fact is not None else ""
            )
            edgar_locator = (
                str(edgar_fact.get("source_locator") or row.get("xbrl_fact_id") or "")
                if edgar_fact is not None
                else str(row.get("xbrl_fact_id") or "")
            )

            # Parse numeric values
            def _parse_float(val: str) -> float | None:
                val = str(val or "").strip()
                if not val:
                    return None
                try:
                    return float(val)
                except ValueError:
                    return None

            ciq_value = _parse_float(str(row.get("ciq_base_value") or ""))
            edgar_value = _parse_float(str(row.get("xbrl_base_value") or ""))
            difference = _parse_float(str(row.get("difference") or ""))
            # If difference is empty in csv but we have both values, compute observation
            if difference is None and ciq_value is not None and edgar_value is not None:
                difference = edgar_value - ciq_value
            tolerance = _parse_float(str(row.get("tolerance") or ""))

            status = str(row.get("status") or "").strip() or "review_required"
            statement = str(row.get("statement") or "").strip()

            # Unresolved checks per period
            if not ciq_unit.strip():
                unresolved.append(
                    f"blank unit for ciq at {period_end} (fact_id={ciq_fact_id})"
                )
            if not edgar_unit.strip():
                unresolved.append(
                    f"blank unit for edgar at {period_end} (fact_id={xbrl_fact_id})"
                )
            if ciq_unit != edgar_unit:
                unresolved.append(
                    f"mismatched unit at {period_end}: ciq='{ciq_unit}' edgar='{edgar_unit}'"
                )
            if ciq_currency and edgar_currency and ciq_currency != edgar_currency:
                unresolved.append(
                    f"mismatched currency at {period_end}: ciq='{ciq_currency}' edgar='{edgar_currency}'"
                )
            if ciq_fact is None:
                unresolved.append(
                    f"ciq fact not found in financial_facts.csv for {period_end} fact_id={ciq_fact_id}"
                )
            if edgar_fact is None:
                unresolved.append(
                    f"edgar fact not found in financial_facts.csv for {period_end} fact_id={xbrl_fact_id}"
                )

            periods.append(
                {
                    "period_end": period_end,
                    "statement": statement,
                    "ciq": {
                        "value": ciq_value,
                        "unit": ciq_unit,
                        "currency": ciq_currency,
                        "fact_id": ciq_fact_id,
                        "source_locator": ciq_locator,
                    },
                    "edgar": {
                        "value": edgar_value,
                        "unit": edgar_unit,
                        "currency": edgar_currency,
                        "fact_id": xbrl_fact_id,
                        "source_locator": edgar_locator,
                    },
                    "difference": difference,
                    "tolerance": tolerance,
                    "status": status,
                }
            )

        # Orphan and duplicate detection from financial_facts
        # Build period sets per source for this key
        facts_for_key = facts_by_key.get(canonical_key, [])
        # Map period_end -> list of fact_ids per source
        ciq_periods_set: set[str] = set()
        edgar_periods_set: set[str] = set()
        fact_ids_by_period_source: dict[tuple[str, str], list[dict[str, str]]] = (
            defaultdict(list)
        )
        for f in facts_for_key:
            pe = str(f.get("period_end") or "").strip()
            src = str(f.get("source") or "").strip().lower()
            if not pe:
                continue
            if src == "ciq":
                ciq_periods_set.add(pe)
            elif src == "edgar":
                edgar_periods_set.add(pe)
            fact_ids_by_period_source[(pe, src)].append(f)

        recon_periods_set = set(sorted_periods)

        # Periods present in one source only (not in reconciliation)
        for pe in sorted(ciq_periods_set - recon_periods_set):
            # Find representative fact for message
            reps = fact_ids_by_period_source.get((pe, "ciq"), [])
            val_str = (
                str(reps[0].get("numeric_value") or reps[0].get("value") or "")
                if reps
                else ""
            )
            unresolved.append(
                f"period {pe} present in ciq only (value={val_str}) – no edgar counterpart, excluded from packet"
            )
        for pe in sorted(edgar_periods_set - recon_periods_set):
            reps = fact_ids_by_period_source.get((pe, "edgar"), [])
            val_str = (
                str(reps[0].get("numeric_value") or reps[0].get("value") or "")
                if reps
                else ""
            )
            unresolved.append(
                f"period {pe} present in edgar only (value={val_str}) – no ciq counterpart, excluded from packet"
            )

        # Duplicate facts per period per source that were not chosen
        for pe in sorted_periods:
            row = period_map[pe]
            ciq_chosen = str(row.get("ciq_fact_id") or "")
            edgar_chosen = str(row.get("xbrl_fact_id") or "")
            for src, chosen in [("ciq", ciq_chosen), ("edgar", edgar_chosen)]:
                candidates = fact_ids_by_period_source.get((pe, src), [])
                for cand in candidates:
                    fid = str(cand.get("fact_id") or "")
                    if fid and fid != chosen:
                        # Only report if not already covered by distinct reasoning; to avoid noise from tiny ratio facts,
                        # still report but state plainly.
                        unresolved.append(
                            f"additional {src} fact excluded at {pe}: fact_id={fid} value={cand.get('numeric_value')} unit={cand.get('unit')}"
                        )

        # Determine whether all periods agree (match or within_tolerance)
        all_agree = (
            all(p.get("status") in ("match", "within_tolerance") for p in periods)
            if periods
            else False
        )

        packet: dict[str, Any] = {
            "canonical_key": canonical_key,
            "ticker": normalized_ticker,
            "periods": periods,
            "note_references": note_references,
            "unresolved": unresolved,
        }

        packet_path = output_dir / f"{canonical_key}.json"
        packet_path.write_text(
            json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

        index_entries.append(
            {
                "canonical_key": canonical_key,
                "ticker": normalized_ticker,
                "period_count": len(periods),
                "all_agree": bool(all_agree),
            }
        )

    # Write notes.json once
    notes_payload = {
        "ticker": normalized_ticker,
        "filing_accession": filing_accession,
        "filing_path": str(filing_path),
        "notes": [
            {"note_key": k, "heading": v["heading"], "body": v["body"]}
            for k, v in sorted(notes_by_key.items())
        ],
    }
    (output_dir / "notes.json").write_text(
        json.dumps(notes_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    # Write index.json
    index_payload = {
        "ticker": normalized_ticker,
        "packet_count": len(index_entries),
        "packets": sorted(index_entries, key=lambda x: x["canonical_key"]),
    }
    (output_dir / "index.json").write_text(
        json.dumps(index_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    return PacketsResult(
        output_dir=output_dir,
        packet_count=len(index_entries),
        canonical_keys=sorted(canonical_keys),
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Build evidence packets for a ticker")
    parser.add_argument("--ticker", default="MSFT")
    parser.add_argument("--ingestion-root", default="data")
    parser.add_argument("--filing-accession", default="0000950170-25-100235")
    args = parser.parse_args()
    write_packets_artifacts(
        args.ticker,
        ingestion_root=args.ingestion_root,
        filing_accession=args.filing_accession,
    )
