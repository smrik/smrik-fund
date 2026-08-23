# Phase 3 steps

| Step | Owner | Status | Scope | Report |
|---|---|---|---|---|
| S1 | Luna simplicity adversary | COMPLETE; acceptance finding repaired by D1/R1 | Xbox discovered but ambiguous search produced no exact packet; other findings recorded | `reports/S1.md` |
| R1 | Luna repair | COMPLETE except live external proof | Literal multi-occurrence repair and local Xbox chain complete; live CLI requires explicit external-LLM approval | `reports/R1.md` |
| S2 | Luna repaired-state adversary | COMPLETE; boundedness repaired by D2/R2, policy findings deferred | Read-only simplicity and acceptance attack on D1/final repaired state | `reports/S2.md` |
| R2 | Luna repair | COMPLETE | Always persist zero-topic discovery; cap per-topic candidate fan-out before Reviewer loop | `reports/R2.md` |
| R3 | Luna simplification repair | COMPLETE | Remove obsolete no-filing/frozen-packet/manual-seed integrated runtime branch; preserve actual-filing discovery path | `reports/R3.md` |

Only clear bounded behavior-preserving simplifications may be edited. Correctness defects or material choices become `DECISION_REQUIRED`.
