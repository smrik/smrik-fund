# Phase 1 — independent scouts

Each scout reads identical authority/current committed code independently, edits no source/tests/config/external state, and writes one concise immutable proposal with approach, exact affected surfaces, invariants, non-goals, risks/verification, and estimated size.

| Step | Lane | Report | Status |
|---|---|---|---|
| S1 | Stable candidate/economic-adjustment identity and replay recognition; collision/change semantics | `reports/S1-identity-replay.md` | FINAL |
| S2 | Complete deterministic gate inputs and financial correctness for one auto-approved case without weakening policy | `reports/S2-gate-finance.md` | FINAL; D1 resolved |
| S3 | Canonical history append/application exactly-once semantics and faithful end-to-end replay test design | `reports/S3-persistence-application.md` | FINAL |
