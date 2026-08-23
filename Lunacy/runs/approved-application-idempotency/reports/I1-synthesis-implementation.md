# I1 — synthesis and implementation

Baseline `736c239`; branch `codex/idempotent-approved-application`.

## Decision

S1/S2/S3 are compatible. Implemented the smallest direct CSV/functional design in `src/smrik_fund/main.py`:

- canonical exact `candidate_identity` JSON from ticker, filing accession, exact target/period/sub-item, and sorted evidence anchors;
- canonical `candidate_state` JSON for economic fields; exact replay reuses the persisted ID/version, state conflict appends a proposed next version, and unknown/legacy identity fails closed;
- deterministic scoped reconciliation, signed-source, over-adjustment, duplicate, group, aggregate, application-preview, and materiality-fact gate inputs;
- history append only for new auto-approval or an explicit state-conflict proposal; current application always resolves latest version first and starts from the reported P&L;
- no second applied ledger, fuzzy matching, numeric materiality policy, framework, UI, or CLI stage.

## Proof

`tests/test_adjustment_analysis.py` now proves:

- frozen first run: one `A0001 v1 approved` row, all gate facts known, R&D `100 -> 90`, adjusted reconciliation remains valid;
- identical second run against the same persisted CSV: same identity/ID, unchanged CSV bytes and row/version count, reviewer not rerun, R&D remains `90` rather than `80`;
- changed amount: same identity gets `A0001 v2 proposed`, prior approved row remains, latest-version resolution removes the unreviewed change from current application, and R&D returns to reported `100`;
- live-safe materiality: unset materiality remains unknown/human-review with no history append;
- builder negative/over-target/derived/missing/reconciliation cases fail closed.

## Verification

See [`evidence/I1-terminal-checks.md`](../evidence/I1-terminal-checks.md). Focused lifecycle tests: 22 passed. Full suite: 69 passed, 4 dependency warnings, 26 subtests. Ruff and `git diff --check`: pass.

## Findings / boundaries

- Live MSFT auto-approval remains intentionally unavailable until an approved materiality policy supplies the fact. The only `True` materiality input is the explicit frozen integration-test boundary.
- Sequential persisted CSV replay is proved; crash-safe concurrent writers remain out of scope per plan.
- Unrelated dirty/untracked `.vscode`, notes, codemap, annotation, and prior Lunacy artifacts were preserved.
