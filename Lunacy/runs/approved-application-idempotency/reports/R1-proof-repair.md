# R1 — proof repair

Status: FINAL  
Baseline `736c239`; branch `codex/idempotent-approved-application`.

## Changed

- Expanded the persisted-CSV replay proof with a first-run adjusted-value snapshot, first-run `approved`/`applied` statuses, and explicit first-run history ID/version/status/amount. The replay now explicitly checks unchanged amount/ID/version/status and CSV bytes, plus `90` after both runs.
- Added focused helper proofs that legacy rows missing identity and rows with one identity mapped to multiple IDs return `unknown`; distinct exact source anchors/sub-items produce separate identities and a `new` lookup.
- Made the history CLI message count `approved` and `proposed` rows separately; a proposed conflict is no longer called approved. Added a regression assertion.

## Verification

Terminal snapshot is immutable at [`evidence/R1-terminal-20260821T232159.md`](../evidence/R1-terminal-20260821T232159.md): focused **24 passed**, full **71 passed / 26 subtests**, Ruff pass, `git diff --check` pass.

## Scope / boundaries

- No production policy, materiality threshold, identity architecture, application arithmetic, or framework added.
- Existing baseline implementation and unrelated dirty/untracked artifacts were preserved; no commit/push.
