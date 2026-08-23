# Phase 2 steps

## A1 — Fresh read-only financial/state adversary

Status: COMPLETED — DO NOT MERGE; findings repaired in R1

Owner: fresh GPT-5.6 Luna xhigh, read-only except immutable report.

Attack the actual final diff and manifest comparison for: provenance changing identity; wording drift minting IDs; occupied-row false split/merge; unique/duplicate row-key stability; inert legacy authority; ignored effective/malformed history; unresolved history writes; approved-version displacement/stacking; sign/direction/application drift; docs mismatch; unnecessary production machinery; unrelated cleanup.

Report: `Lunacy/runs/identity-merge-pass/reports/A1.md`.

## A2 — Fresh post-repair re-gate

Status: COMPLETED — DO NOT MERGE; findings repaired in R2

Owner: fresh GPT-5.6 Luna xhigh, read-only except immutable report.

Reproduce A1-1 through A1-3 and re-attack the named financial/state/docs/simplicity risks on R1. No broad suite rerun.

Report: `Lunacy/runs/identity-merge-pass/reports/A2.md`.

## A3 — Final fresh read-only re-gate

Status: COMPLETED — PASS

Owner: fresh GPT-5.6 Luna xhigh, read-only except immutable report.

Reproduce A2-1/A2-2 and verify all prior manifest, financial/state, docs, and simplicity risks remain closed after R2. No broad suite rerun.

Report: `Lunacy/runs/identity-merge-pass/reports/A3.md`.

## A4 — Final application-authority re-gate

Status: COMPLETED — PASS

Owner: fresh GPT-5.6 Luna xhigh, read-only except immutable report.

Verify R3 makes approved/effective or corrupt unknown history stop final application while inert proposed/rejected legacy still yields an empty safe current set. Recheck prior gate closure without broad suite rerun.

Report: `Lunacy/runs/identity-merge-pass/reports/A4.md`.
