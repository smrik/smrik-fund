# Phase 3 steps

| Step | Owner | State | Scope | Report |
|---|---|---|---|---|
| A1 | Fresh Luna adversary | FINAL_DO_NOT_MERGE | Attack removable complexity, financial/evidence correctness, residual arithmetic, provenance, and analyst time savings | `reports/adversary.md` |
| R1 | Fresh Luna repair owner | FINAL_PASS | Fix all six authorized A1 findings without redesign; refresh focused/regression/full/Ruff/diff/live proof | `reports/repair-1.md` |
| A2 | Fresh Luna read-only reviewer | FINAL_DO_NOT_MERGE | Review repaired code and fresh live proof for financial correctness and analyst time savings | `reports/final-financial-review.md` |
| R2 | Fresh Luna repair owner | FINAL_PASS | Bind quantified claims to unambiguous evidence-local support or downgrade; block unsupported arithmetic in all prose; refresh proof | `reports/repair-2.md` |
| A3 | Fresh Luna read-only reviewer | FINAL_DO_NOT_MERGE | Review R2 closure and fresh live result for financial correctness and analyst time savings | `reports/final-financial-review-2.md` |
| R3 | Fresh Luna repair owner | FINAL_PASS | Close semantic span/sign and word-amount/subtoken prose bypasses conservatively; refresh proof | `reports/repair-3.md` |
| A4 | Fresh Luna read-only reviewer | FINAL_DO_NOT_MERGE | Review R3 closure and final live result; issue financial/product verdict | `reports/final-financial-review-3.md` |
| R4 | Fresh Luna repair owner | FINAL_PASS | Eliminate numeric/arithmetic narrative attack surface and clear rejected amount metadata; refresh proof | `reports/repair-4.md` |

Read-only by default. May make only clear bounded behavior-preserving simplifications; correctness defects require a repair step or decision brief.
