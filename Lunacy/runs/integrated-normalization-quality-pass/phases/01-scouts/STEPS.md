# Phase 1 — independent scouts

All scouts read the same authority and current repo/diff independently. They must not read each other's reports or edit source/tests/config/external state. Each writes one concise immutable report with approach, affected surfaces, invariants, non-goals, risks/verification, and estimated size.

| Step | Lane | Report | Status |
|---|---|---|---|
| S1 | Financial correctness and LLM/Python judgment boundary; verify signs, periods, attribution, grouping, tax/non-operating semantics | `reports/S1-financial.md` | FINAL |
| S2 | Evidence integrity, Reviewer/gate separation, adjustment history/application persistence, repeat-run safety | `reports/S2-evidence-state.md` | FINAL |
| S3 | Human-facing CLI usefulness plus simplicity/bloat inventory and safe removals | `reports/S3-output-simplicity.md` | FINAL |
