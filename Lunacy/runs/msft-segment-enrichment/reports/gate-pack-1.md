# G0 gate pack 1 — final compression

## Control Block

- Owner: G0; fresh read-only compression; no approval or edits.
- State: R1 final source/test/live-proof state; write barrier remains CLOSED.
- Filing: MSFT 10-K accession `0001193125-26-323660`, filed 2026-07-29.
- Scope: segment fidelity, arithmetic, context/refs, old/new scan, R1 closure.
- Fresh check: `git diff --check` passed; no broad suites rerun by G0.
- Gate posture: parent G1 owns the acceptance sample and PASS/DO NOT MERGE verdict.

## Source structure and analytical output

- Filing identifies exactly three reportable segments at `data/MSFT/01_source/edgar/filings/0001193125-26-323660.txt:1086-1090`; Note 18 reports FY26/FY25/FY24 at `:2781-2841` and says operating income is the CODM profitability measure.
- All 18 persisted rows are annual duration facts (3 members x 2 metrics x 3 periods), same labels/signs/period starts, `U_USD` raw values, accession/concept/fact/context provenance retained; table below is display-only $m.

| Segment | Revenue FY26 / FY25 / FY24 ($m) | Operating income FY26 / FY25 / FY24 ($m) |
|---|---:|---:|
| Productivity and Business Processes | 139,996 / 120,810 / 106,820 | 83,879 / 69,773 / 59,661 |
| Intelligent Cloud | 137,791 / 106,265 / 87,464 | 56,972 / 44,589 / 37,813 |
| More Personal Computing | 54,052 / 54,649 / 50,838 | 14,386 / 14,166 / 11,959 |

- Source MD&A independently shows FY26/FY25 segment table and totals at `...txt:1172-1195`; Note 18 discloses allocation caveats at `:2814-2817`, preserved without adjustment.

## Calculations and reconciliation

- FY26 revenue: PBP +$19,186m/+15.9%/42.2% share/-69 bps/+38.3% growth contribution; IC +$31,526m/+29.7%/41.5%/+380 bps/+62.9%; MPC -$597m/-1.1%/16.3%/-311 bps/-1.2%; contributions = 100.0% of consolidated +$50,115m.
- FY26 operating income: PBP +$14,106m/+20.2%/59.9% margin/+216 bps/+52.8% contribution; IC +$12,383m/+27.8%/41.3%/-61 bps/+46.4%; MPC +$220m/+1.6%/26.6%/+69 bps/+0.8%; contributions = 100.0% of consolidated +$26,709m.
- `data/live-segment-enrichment-i1/MSFT/03_output/segment_reconciliation_checks.csv`: 6/6 PASS, 3/3 coverage each, residual 0 for Revenue and OperatingIncomeLoss in FY26/FY25/FY24; no balancing plug/allocation.

## Context, refs, and scan comparison

- Latest enriched context is `data/live-segment-enrichment-i1/MSFT/03_output/analysis/analytical_scan_20260828T191302094324Z.json`: 25 selectable refs = 19 unchanged L refs + 6 S refs; 54 context lines; raw `fact_id`/`context_ref` absent; reconciliation explicitly non-selectable.
- S map is deterministic: S01/S02=Intelligent Cloud Revenue/OperatingIncomeLoss; S03/S04=More Personal Computing Revenue/OperatingIncomeLoss; S05/S06=Productivity and Business Processes Revenue/OperatingIncomeLoss.
- Preserved old scan: `data/live-closed-world-proof-r2/MSFT/03_output/analysis/analytical_scan_20260827T190654525200Z.json` (v2, 6 findings, 19 L refs): product mix; cost/gross margin; operating leverage; non-operating; tax; EPS.
- New scan: same accession, v3, 7 findings, 19 L + 6 S refs: rank 1 non-operating; rank 2 consolidated+segment revenue mix; rank 3 gross margin; rank 4 segment operating margins; ranks 5-7 operating leverage, tax, EPS.
- No consolidated theme disappeared; two segment-aware findings expose IC growth/share vs MPC decline and PBP/IC/MPC margin/contribution divergence. No causal/forecast/valuation claim or obvious double count; time saved is unmeasured.

## R1 blocker closure and safety

- A1's exact saved-context guard defect is closed: `load_segment_analytics` reloads rows/checks and reassigns refs; `load_saved_scan`/`investigate_finding` format enriched context for L-ref exact matching; `main.investigate` passes persisted segments.
- S refs remain explicitly analytical-only: `_reject_segment_refs` fails before plan generation, source-label construction, P&L indexing, retrieval, or model calls with `S-ref filing investigation is unsupported...`; L refs remain investigable.
- No changes to canonical P&L, statement ingestion, adjustments/history/state, approved/adjusted values, retrieval architecture, or live scan artifacts.

## Final surfaces, verification, parent inspection map

- Production surfaces: new `src/smrik_fund/ingestion/segments.py` (837 lines); `analytical_scan.py` +136/-10; `filing_investigation.py` +51/-4; `main.py` +40/-2; prompt +10/-3. Tests: new `tests/test_segments.py` (273 lines), `test_filing_investigation.py` +102.
- Final symbols: `extract_segment_facts`, `assign_segment_refs`, `build_segment_analytics`, `build_segment_reconciliation`, `build_segment_enrichment`, `load_segment_analytics`; `_format_segment_context`, `format_analytical_pnl_for_scan`, `validate_analytical_scan_result`; `_reject_segment_refs`, `load_saved_scan`, `investigate_finding`; CLI `analyze`/`investigate`.
- Verification evidence: segments 8 passed; Analytical Scan 11; statements 11; reconciliation 10; filing investigation 50; adjustment analysis 36; adjustments 15; state/identity 29; full unittest discovery 212 passed; changed-file Ruff passed; full Ruff only pre-existing B007 at `reconciliation.py:338`; pytest unavailable in environment.
- Parent inspect order: source lines above -> `segment_analytics.csv` + `segment_reconciliation_checks.csv` -> latest/new and preserved/old JSON -> `segments.py:263-821`, `analytical_scan.py:419-734`, `filing_investigation.py:63-74,406-410,494-560,840-845,1994-1997,2224-2260,2636-2690`, `main.py:2301-2432` -> tests at `tests/test_segments.py:141-273` and `tests/test_filing_investigation.py:1373-1421`.
