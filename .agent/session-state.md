# Session State

**Updated:** 2026-08-06 22:26:00 +02:00
**Agent:** Codex CLI
**Project:** C:\Projects\04-Learning\smrik-fund

## Current Task
Align the EDGAR statement export with the machine-readable ingestion contract used by `C:\Projects\03-Finance\ai-fund`.

## Recent Actions
- Reviewed the current statement parser and Excel export in this repository.
- Reviewed the `ai-fund` artifact pipeline, fact-row schema, and XBRL evidence fields.
- Confirmed that a long-form CSV fact ledger is a better handoff than three wide statement CSV files.
- No source edits were made after the prior Excel implementation. Waiting for approval of the target layout.

## Next Steps
- After approval, add failing tests for the `ai-fund`-compatible files.
- Implement `facts.csv`, `manifest.json`, and `filings.jsonl` output under `data/ingestion/<TICKER>/`.
- Verify the output with more than one ticker and keep the default export machine-readable.

## Known Issues
- Focused tests and lint pass. Full `ruff check src tests` still reports pre-existing undefined `get_read_only_connection` and `load_statement_facts` references in `ingestion/edgar.py`.

## Notes
- The current default export is still Excel under `data/<TICKER>/`; it is pending replacement or demotion to an optional debug export.
- The `ai-fund` contract uses CSV for tables, JSON for metadata, and JSONL for filing records.
- SEC runs use `SMRIK_EDGAR_USER_AGENT` when set, otherwise the project default.
