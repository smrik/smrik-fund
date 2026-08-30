# I1 implementation evidence

## Live source and extraction

- Live `EdgarTools 5.45.1` extraction used the same current MSFT 10-K as the
  scan: accession `0001193125-26-323660`, filed `2026-07-29`, form `10-K`.
- Source disclosures: `data/MSFT/01_source/edgar/filings/0001193125-26-323660.txt`
  lines 1086-1090, 1172-1195, and 2781-2841. Raw facts retain dollars; the
  filing table presents millions. No segment name is in product logic/prompt.
- Live outputs: `data/live-segment-enrichment-i1/MSFT/03_output/segment_analytics.csv`
  (18 source-grain rows) and `segment_reconciliation_checks.csv` (6 checks).

## Analytical output (FY26 / FY25 / FY24; USD millions)

| Disclosed member | Revenue | Operating income | FY26 revenue growth | FY26 share | FY26 op margin | FY26 margin bps | Revenue growth contribution | Op-income contribution |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Intelligent Cloud | 137,791 / 106,265 / 87,464 | 56,972 / 44,589 / 37,813 | 29.7% | 41.5% | 41.3% | -61 | 62.9% | 46.4% |
| More Personal Computing | 54,052 / 54,649 / 50,838 | 14,386 / 14,166 / 11,959 | -1.1% | 16.3% | 26.6% | +69 | -1.2% | 0.8% |
| Productivity and Business Processes | 139,996 / 120,810 / 106,820 | 83,879 / 69,773 / 59,661 | 15.9% | 42.2% | 59.9% | +216 | 38.3% | 52.8% |

## Reconciliation

- Revenue: FY26 `331,839 - 331,839 = 0`; FY25 `281,724 - 281,724 = 0`; FY24
  `245,122 - 245,122 = 0`; all `PASS` with 3/3 member coverage.
- Operating income: FY26 `155,237 - 155,237 = 0`; FY25 `128,528 - 128,528 = 0`;
  FY24 `109,433 - 109,433 = 0`; all `PASS` with 3/3 coverage.
- Residual is explicit (`consolidated - reported segment total`); no plug,
  allocation, P&L mutation, or adjustment/history write was performed.

## Same-filing scan comparison

- Preserved consolidated-only: `data/live-closed-world-proof-r2/MSFT/03_output/analysis/analytical_scan_20260827T190654525200Z.json`;
  accession same, v2, 6 findings, 19 L refs, no S refs.
- Enriched: `data/live-segment-enrichment-i1/MSFT/03_output/analysis/analytical_scan_20260828T191302094324Z.json`;
  accession same, v3, 7 findings, 19 L + 6 S refs, `segment_enriched=true`.
- New segment finding ranks 2 and 4 combine revenue mix/growth and operating
  margin/contribution. Existing consolidated revenue, gross-margin,
  operating-leverage, non-operating, tax, and EPS themes remain; no duplicate
  segment table or filing-cause claim appeared. One additional focused finding
  is a useful attention slot; analyst-time savings is qualitative, not measured.
- Enriched context is compact derived text; raw fact IDs/context IDs stay only
  in the persisted artifact. `S##` refs are separate from and validated with
  existing `L##` refs.

## Verification evidence

- Focused synthetic segment suite: `8` tests passed; Analytical Scan suite: `11`
  passed. Focused P&L/reconciliation: `21` passed; adjustment/state/identity:
  `65` passed. Full unittest discovery: `210` passed.
- Ruff check on all changed source/tests: passed. `git diff --check`: passed.
- `pytest` could not run because `.venv` has no pytest and the global interpreter
  lacks pandas; `uv run pytest` was blocked by the existing uv-cache ACL.
