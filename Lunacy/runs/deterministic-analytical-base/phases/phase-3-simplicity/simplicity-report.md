# Phase 3 A1 simplicity/correctness adversary

Verdict: **DO NOT MERGE** pending one contract-correctness repair. No production,
test, docs, config, or data edits made by A1.

## Findings

1. **P1 — share-count common-size leak.** `_common_size_eligible()` only recognizes
   share text after compact marker matching (`statements.py:161-176`). A source row
   with `standard_concept=None`, `concept="custom_shares"`, and label
   `"Shares outstanding"` receives `percent_of_revenue=0.1` in the current code;
   the label's space prevents the `sharesoutstanding` marker from matching. This
   violates the required null common-size/bps result for share counts. Real MSFT's
   two share rows are currently protected by `SharesAverage`/
   `SharesFullyDilutedAverage`, so this is a real contract edge, not a current-MSFT
   failure. Repair: normalize label tokens (or add explicit share-count matching)
   and add this label-only case to the focused test.

2. **P2 — persisted MSFT artifact is stale (operational).** Phase 2 evidence says
   `prepare_pnl` on local MSFT input yields 21x65 (`.../phase-2-implementation/evidence/terminal-verification.md:31-36`),
   but the ignored `data/MSFT/03_output/analytical_pnl.csv` is still 34 columns and
   has no new metric columns. `load_analytical_pnl`/`reconcile` therefore consume
   the old shape until `analyze MSFT` is rerun. Phase 2 explicitly did no data
   refresh (`implementation-report.md:7-9`); A1 did not mutate data.

## Audit result

- Math is correct on inspected paths: guarded growth, signed absolute change,
  signed common-size, ratio bps, positive-endpoint CAGR, and margin/ETR bps;
  negative-negative and sign-crossing growth are null, while absolute change stays.
- Source preservation: `source.equals(source_before)` true on local MSFT check;
  adjustment/reconciliation tests pass (25, 4 subtests). Focused analytical tests
  pass (10); Ruff passes. Phase 2 full suite evidence: 142 passed.
- One canonical `prepare_pnl` path; no LLM judgment, extra dependency, parallel
  table, or framework. `+147` net production lines is within the 150-200 gate and
  justified by required metrics/guards. The exact `SHARE_CONCEPTS` branch at
  `statements.py:167-168` is redundant with the marker tuple, but is only an
  optional low-value deletion.

