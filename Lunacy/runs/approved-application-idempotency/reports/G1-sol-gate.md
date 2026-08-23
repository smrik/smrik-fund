# G1 — Sol final gate

Verdict: PASS

## Acceptance

- Stable identity: PASS. Exact canonical identity uses ticker, filing accession, target, annual period, sub-item, and sorted evidence anchors; amount/prose/run metadata excluded.
- Known gate facts: PASS at the authorized frozen boundary. All gate conditions are non-null with explicit `materiality_passed=True`; live callers leave it unknown and fail closed.
- First approval: PASS. Frozen MSFT-shaped run records `A0001 v1 approved`, amount 10, `final_status=approved`, `application_status=applied`, and R&D `100 -> 90`.
- Identical replay: PASS. Same persisted CSV bytes, ID, version, status, and amount; Reviewer is not rerun; adjusted R&D remains 90, not 80.
- Changed state: PASS. Same identity/new amount appends `A0001 v2 proposed`; v1 is preserved; latest-version-first removes application until reviewed.
- Collision/failure safety: PASS. Legacy/ambiguous identity returns unknown; distinct exact identities remain distinct; unresolved/live-materiality paths remain unapplied.
- Accounting/state: PASS. History is the sole durable state; application always starts from reported P&L; no second applied ledger or double subtraction.
- Scope/simplicity: PASS with noted size. Delta is concentrated in direct functions and one test file; A1 removed five redundancies and found no safe machinery to delete. No framework, database, fuzzy matcher, new stage, UI, or numeric policy.

## Verification

- Final writer: focused 24 passed; full 71 passed / 26 subtests; Ruff pass; `git diff --check` pass.
- Parent bounded sample: four lifecycle/identity/conflict tests passed.
- Final delta from `736c239`: `main.py` +599/-50; `test_adjustment_analysis.py` +347/-0.

## Residual boundaries

- Live MSFT auto-approval remains unavailable until materiality policy is authorized.
- Exactly-once proof is sequential rerun against one CSV; crash/concurrent-writer atomicity is out of scope.
- Existing legacy history without identity fails closed rather than being migrated or guessed.

No commit or push.
