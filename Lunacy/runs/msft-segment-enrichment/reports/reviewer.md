# A1 read-only financial and simplicity review

## Control Block

- Owner: A1; strict read-only review; only this report was written.
- Source: same MSFT 10-K, accession `0001193125-26-323660`, filed 2026-07-29.
- Live evidence: `data/live-segment-enrichment-i1/MSFT/03_output/` and `data/live-closed-world-proof-r2/MSFT/03_output/analysis/`.
- Reviewed chain: filing text -> XBRL extraction -> analytics -> reconciliation -> v3 context/refs -> v3/v2 scans.
- Financial result: source-faithful, comparable, arithmetic correct, residual honest.
- Product result: enriched scan adds useful segment attention without losing consolidated themes.
- Blocker: persisted enriched scans cannot pass the existing filing-investigation context guard.
- Verdict: DO NOT MERGE until that consumer boundary is explicitly repaired or explicitly rejected.

## Source fidelity and period comparability

- Filing states three reportable segments at lines 1086-1090; MD&A table gives FY26/FY25 at lines 1172-1195; Note 18 gives FY26/FY25/FY24 at lines 2781-2841 in `data/MSFT/01_source/edgar/filings/0001193125-26-323660.txt`.
- Artifact has exactly 18 rows (3 members x 2 metrics x 3 FY periods), labels and signs match Note 18. XBRL values are dollars (`U_USD`); filing presentation is millions; this scale difference is disclosed, not silently normalized.
- Accession, filing date/form, source URL, concept, fact ID, context ref, unit/currency, FY period and reported basis are retained. `source_locator` is blank, but source URL plus fact/context IDs are usable provenance.
- All rows are annual duration periods with starts 2025-07-01 / 2024-07-01 / 2023-07-01; no historical member/period drift appears. Six checks are `PASS` with 3/3 coverage.

## Calculation and reconciliation correctness

- FY26 revenue: Intelligent Cloud `137,791 / 106,265 - 1 = 29.7%`, 41.5% share, 62.9% of consolidated revenue growth; MPC `-1.1%`, -1.2% contribution; PBP `15.9%`, 38.3% contribution. These reconcile to 17.8% consolidated growth.
- FY26 operating income: PBP margin 59.9% (+216 bps), Intelligent Cloud 41.3% (-61 bps), MPC 26.6% (+69 bps); contributions 52.8% + 46.4% + 0.8% = 100.0% (rounding only).
- Six reconciliation rows (Revenue and OperatingIncomeLoss, FY26/FY25/FY24) show reported segment total = reported consolidated total and residual 0. No plug, allocation, or P&L mutation is present; allocation language in Note 18 remains a reported-source caveat.
- Guards preserve missing/zero/sign-changing values and suppress unsafe growth/contribution; focused tests cover these cases. No forecast, valuation, EBITDA, adjustment, or state write is present.

## Context, refs, and old/new observations

- Enriched context is compact derived text: 19 unchanged `L##` refs + 6 deterministic `S##` refs; raw fact/context IDs are excluded from the model context; reconciliation is non-selectable. Unknown refs are rejected by the v3 validator.
- Same-accession v2 scan: 6 findings / 19 L refs. v3 scan: 7 findings / 19 L + 6 S refs. Existing revenue, gross-margin, operating-leverage, non-operating, tax, and EPS themes remain; the new segment finding covers growth/mix and divergent operating margins. No double-counted segment table or filing-cause claim appears.
- Financially better: direct view of Intelligent Cloud growth/contribution and margin compression versus PBP/MPC mix and margins. No clearly misleading live finding; qualitative analyst-time saving is unmeasured.

## Concrete defect and smallest correction

- `src/smrik_fund/ingestion/filing_investigation.py:2635-2642` and `:2217-2224` recompute `format_analytical_pnl_for_scan(pnl)` without segments, then require exact equality. Every v3 saved context contains `## Reportable segment results`, so `investigate` fails before retrieval even for L-only findings; S refs would additionally fail the L-only boundary at `:542-544` / `:830-835`.
- Smallest safe correction: explicitly plumb the persisted segment artifact (including reconciliation attrs) into both context checks and observed/source-label construction, or explicitly reject v3/S-ref investigation with a clear boundary error. Do not silently treat S refs as P&L rows.

## Simplicity review and verdict

- Architecture is otherwise proportionate: one data-oriented module plus bounded scan/CLI/prompt/test edits; no service, taxonomy, database, retrieval layer, or new LLM role.
- Minor cleanup only: duplicated derived aliases (`*_bps_change`, `*_growth_contribution`) at `segments.py:25-37`, duplicated reconciliation fields at `:698-704`, and the compatibility save alias at `:751-754` enlarge the artifact without current consumers. Remove only after consumer audit; not the financial blocker.
- I1 evidence reports focused segment 8, Analytical Scan 11, P&L/reconciliation 21, state/identity 65, full unittest 210 passed; Ruff and `git diff --check` passed; pytest was unavailable. No tests were rerun in this read-only review.
- Verdict: DO NOT MERGE pending the explicit filing-investigation compatibility decision/correction; segment financials and scan usefulness otherwise PASS.
