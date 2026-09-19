# R1 compatibility repair report

## Control Block

- Owner: R1; bounded saved-context / S-ref filing-investigation repair only.
- Authority: parent decision in `DECISIONS.md`; no segment filing investigation.
- Source proof: same MSFT accession `0001193125-26-323660` persisted I1 artifacts.
- State: no commit or merge; prior reports and live outputs preserved.
- Result: enriched context reloads exactly; L refs remain investigable.
- Safety: S refs fail before any P&L indexing with an explicit boundary error.
- Verification: focused matrix, full unittest, changed-file Ruff, diff check, live proof.

## Changed

`load_segment_analytics` reloads persisted segment rows plus reconciliation checks,
reattaches formatter metadata, and deterministically reassigns S refs. Saved-scan
validation now parses L/S refs and formats enriched contexts with the reloaded
artifact. The CLI passes that artifact through to `load_saved_scan` and
`investigate_finding`; old consolidated scans continue to use consolidated context.

Filing investigation rejects any S ref before plan generation, source-label
construction, observed movement, evidence validation, or model calls. The error is:
`S-ref filing investigation is unsupported: segment refs are analytical-only and
cannot be indexed as P&L rows (S##)`.

## Regressions and proof

- `test_filing_investigation.py`: 50 passed, including enriched L-ref compatibility
  and S-ref fail-closed regressions.
- `test_segments.py`: 8 passed; Analytical Scan 11; statements 11; reconciliation 10.
- Adjustment analysis 36; adjustments 15; state/identity 29; full suite 212 passed.
- Changed-file Ruff passed; `git diff --check` passed.
- Full Ruff has one pre-existing unrelated B007 at `reconciliation.py:338`.
- Same-filing proof: `format_analytical_pnl_for_scan` exactly matched the saved scan;
  18 persisted segment rows and 6 segment context rows; `load_saved_scan` accepted
  7 findings, first refs `L11,L12,L13,L15`.

## Not changed

No segment filing investigation, retrieval architecture, source extraction,
analytics, canonical P&L, adjustment/history/state, prompts, or live scan outputs.

## Verdict

PASS — bounded R1 repair complete; parent gate remains authoritative.
