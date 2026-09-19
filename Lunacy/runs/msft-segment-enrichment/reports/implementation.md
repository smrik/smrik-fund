# I1 implementation report

## Control Block

- Owner: I1; scope: MSFT reportable-segment enrichment + Analytical Scan.
- Source: current same-filing MSFT 10-K, accession `0001193125-26-323660`.
- Design: existing EdgarTools filing -> separate guarded segment artifact -> scan context.
- Facts: Revenue + OperatingIncomeLoss only; raw source/provenance preserved.
- Reconciliation: explicit residual; `PASS` / `NOT_DIRECTLY_COMPARABLE` / `UNRESOLVED`; no plug.
- Refs: consolidated `L##` unchanged; deterministic collision-safe `S##`; exact-set validation.
- State: canonical P&L and adjustment/history state untouched; no commit/merge.
- Verdict: PASS for I1 implementation; fresh Phase 3 reviewer remains pending.

## Changed

Added `src/smrik_fund/ingestion/segments.py` for generic business-segment fact extraction, guarded analytics, reconciliation, and CSV persistence. `analytical_scan.py` now accepts optional segment context, renders compact derived rows, and validates `L##`/`S##` refs. `main.py` enriches only `analyze --scan`; prompt is company-neutral v3.

## Source structure and analytical output

Live EdgarTools extraction found 3 disclosed members, 18 source-grain rows, and 6 deterministic refs across FY26/FY25/FY24. Revenue, operating income, revenue share/contribution, operating margin/bps, and guarded growth are shown in `reports/implementation-evidence.md`; raw facts remain in `data/live-segment-enrichment-i1/MSFT/03_output/segment_analytics.csv`.

## Reconciliation

All six Revenue/OperatingIncomeLoss checks PASS with 3/3 coverage and zero residual. The check artifact is `data/live-segment-enrichment-i1/MSFT/03_output/segment_reconciliation_checks.csv`.

## Scan integration and old vs new

The enriched context has 19 consolidated refs + 6 segment refs, no raw fact table, and no deterministic ranking/causal claims. Preserved v2 consolidated-only scan: 6 findings/19 L refs. Same-accession v3 enriched scan: 7 findings/19 L + 6 S refs; segment findings ranked 2 and 4, while consolidated revenue, gross-margin, operating-leverage, non-operating, tax, and EPS themes remained.

## Product assessment and safety

The added segment view gives the model direct growth/mix/contribution/margin comparisons and one useful additional attention slot; analyst-time savings is not measured. Missing, duplicate, multi-axis, label-drift, period-drift, unit-drift, zero, and sign-changing cases fail closed. No EBITDA, allocation, forecast, valuation, filing investigation, or adjustment behavior was added.

## Files changed

`src/smrik_fund/ingestion/segments.py`, `src/smrik_fund/ingestion/analytical_scan.py`, `src/smrik_fund/main.py`, `prompts/analytical_scan.md`, and `tests/test_segments.py`. `statements.py`, `filing.py`, `filing_investigation.py`, adjustment modules, and canonical state were not changed.

## Tests and production diff

Focused segment: 8 passed; Analytical Scan: 11; P&L/reconciliation: 21; adjustment/state/identity: 65; full unittest discovery: 210 passed. Ruff check and `git diff --check` passed. `pytest` was unavailable (`.venv` lacks pytest; global interpreter lacks pandas); `uv run pytest` hit the existing uv-cache ACL.

## Simplicity review and reviewer findings

Implementation is one data-oriented module plus bounded scan/CLI/prompt/test edits; no taxonomy, service, cache, or new LLM role. I1 did not perform the required fresh independent Phase 3 review; that review must assess fidelity, arithmetic, residuals, context, scan usefulness, redundancy, and scope.

## Verdict

PASS — ready for the fresh read-only Phase 3 reviewer and parent gate.
