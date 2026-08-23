# Phase 2 steps

## A1 — Fresh read-only adversary

Status: COMPLETED — DO NOT MERGE; findings repaired in R1

## A2 — Fresh post-repair read-only adversary

Status: COMPLETED — DO NOT MERGE; finding repaired in R2

Owner: fresh GPT-5.6 Luna xhigh, read-only except immutable report.

Reproduce A1-1 through A1-4 against R1 and re-attack the original seven risks. Inspect whether shared validation is now the only canonical identity-history authority and whether the repair is proportionate. No broad suite rerun.

Report: `Lunacy/runs/identity-corrective-pass/reports/A2.md`.

## A3 — Final fresh read-only re-gate

Status: COMPLETED — PASS

Owner: fresh GPT-5.6 Luna xhigh, read-only except immutable report.

Reproduce A2's malformed-period/row-key authority paths and verify the original seven risks remain closed after R2. Inspect only targeted code/probes; no broad suite.

Report: `Lunacy/runs/identity-corrective-pass/reports/A3.md`.

Owner: fresh GPT-5.6 Luna xhigh, read-only except immutable report.

Attack:

1. Harmless legacy proposed rows still block v2.
2. Legacy rows can regain application authority.
3. Unknown approved legacy rows are silently ignored.
4. Malformed v2 rows are mislabeled harmless legacy.
5. Label drift changes a unique-concept key.
6. Duplicate-concept analytical rows collapse.
7. Correction added migration or row-identity infrastructure.

Report: `Lunacy/runs/identity-corrective-pass/reports/A1.md`.
