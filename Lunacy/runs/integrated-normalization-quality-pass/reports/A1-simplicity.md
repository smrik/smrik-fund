# A1 simplicity adversary

Status: FINAL
Lane: Fresh post-I1 removable-complexity review
Terminal snapshot: 2026-08-21 20:43:13 +02:00

## Judgement

One clear behavior-preserving simplification was made. No correctness, evidence,
financial-sign, state-separation, or acceptance defect was silently changed.

## Changed

- `src/smrik_fund/ingestion/filing.py:67-76`: `_source_matches` now keeps its
  literal no-match error and delegates span rendering to the existing
  `_source_matches_by_offsets`. This removes the duplicate line-start,
  line-number, and excerpt-rendering implementation shared with regex retrieval.
  Literal and regex paths now use one renderer; source text, line numbers, and
  offsets remain unchanged.

## Findings / deferred

- Manifest candidate duplication (`topics[*].candidates` plus top-level
  `candidates`) remains deferred per I1: deleting one copy could break the
  current focused consumer/schema contract (`tests/test_discovery.py:316-324`).
- The compact CLI still labels mixed Reviewer concerns, Analyst uncertainty,
  Reviewer notes, and processing errors as `Unresolved issue / Reviewer concern`.
  Separating provenance would change presentation semantics; escalated, not
  silently rewritten.
- Fresh-run IDs and candidate IDs remain non-idempotent across reruns. This is
  state/policy scope, not a simplicity deletion; deferred per I1.

## Terminal verification

- `PYTHONPATH=src C:\Users\patri\miniconda3\python.exe -m pytest tests/test_filing.py tests/test_discovery.py -q -p no:cacheprovider` — **11 passed**.
- `PYTHONPATH=src C:\Users\patri\miniconda3\python.exe -m pytest tests -q -p no:cacheprovider` — **64 passed, 26 subtests passed**.
- `ruff check` on all current changed production/test surfaces — **pass**.
- `git diff --check` — **pass** (line-ending warnings only).
- Current real MSFT artifact remains state-safe: `data/MSFT/03_output/analysis/adjustment_run_20260821T183152175247Z.json` has 4 topics, 8 candidates, 12/0/0 reported and adjusted reconciliation, `reported_equals_adjusted=true`, all 8 `human_review`/`not_applied`; canonical history SHA-256 remains `4C15AC69286E85C1BB828BB7E0BB04CC3967F8022EE57053DB49CAE6483704D8`.
- Simplified filing module SHA-256: `DFC066FB6E09E4571BF27C8DB9CDEBE61C5B2350DF61715EF5BEC5BBC649427F`.

No commit or push.
