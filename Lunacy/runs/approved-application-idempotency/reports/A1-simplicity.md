# A1 simplicity adversary

Status: FINAL
Lane: Fresh post-I1 removable-complexity review
Terminal snapshot: 2026-08-21 23:05:32 +02:00

## Judgement

Three clear behavior-preserving removals were made. No identity-collision,
append-only versioning, materiality-boundary, reported-P&L, or replay-proof
behavior was changed. No correctness or policy defect was silently repaired.

## Changed

- `src/smrik_fund/main.py:180-201`: removed the one-line `_is_derived_target`
  wrapper; identity validation calls the existing `_is_derived_line` directly.
- `src/smrik_fund/main.py:275`: removed an unused `.copy()` when selecting
  identity matches; the selection is read-only and later version-row copying is
  retained where mutation occurs.
- `src/smrik_fund/main.py:684-687`: removed duplicate source-line matching in
  `_gate_conditions`; `_reported_source_value` already performs the exact,
  ambiguity-safe lookup.
- `src/smrik_fund/main.py:721`: removed an unnecessary deep copy of empty
  history in aggregate checking; no mutation occurs on that path.
- `src/smrik_fund/main.py:1159`: removed duplicate reviewer serialization;
  the existing `review_data` snapshot is reused for manifest and history.

## Findings / deferred

- Identity, candidate-state, overlap, same-run, and pending-history machinery
  remains necessary for exact collision safety and append-only replay/version
  semantics. No generic persistence or compatibility layer was found to delete.
- The focused replay/changed-state/live-materiality/gate-builder tests are
  acceptance proof, not speculative over-testing; retained.
- Existing unrelated dirty/untracked `.vscode`, notes, codemap, annotation,
  and prior Lunacy artifacts were preserved.

## Terminal verification

- `PYTHONPATH=src C:\Users\patri\miniconda3\envs\ai-fund\python.exe -m pytest tests/test_adjustment_analysis.py -q -p no:cacheprovider` — **22 passed**.
- `PYTHONPATH=src C:\Users\patri\miniconda3\envs\ai-fund\python.exe -m pytest -q -p no:cacheprovider` — **69 passed, 3 warnings, 26 subtests**.
- `ruff check src/smrik_fund/main.py tests/test_adjustment_analysis.py` — **pass**.
- `git diff --check` — **pass** (only existing LF/CRLF warnings).

No commit or push.
