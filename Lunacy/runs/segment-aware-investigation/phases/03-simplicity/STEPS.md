# Phase 3 steps

| Step | Status | Owner | Scope | Report |
|---|---|---|---|---|
| A1 | FINAL — DO NOT MERGE | `/root/a1_simplicity_integrity` | Attack removable complexity and evidence/financial integrity; bounded behavior-preserving simplifications only | `reports/A1.md` |
| R1 | INCOMPLETE | `/root/r1_integrity_repair` | Worker vanished; no terminal report/evidence; partial worktree edits possible | `reports/R1.md` missing |
| R2 | FINAL — PASS | `/root/r2_integrity_recovery` | Recover current worktree; finish/correct only A1 P1 integrity repairs; impacted/full verification and live proof | `reports/R2.md` |

A1 must inspect the implementation diff and live proof. It may delete/simplify only when behavior and acceptance stay unchanged, then verify the impacted final state. Any functional, financial, evidence-integrity, leakage, allocation/plug, persistence, or regression defect becomes a concrete finding for a fresh repair step; do not silently fix correctness under this mandate.
