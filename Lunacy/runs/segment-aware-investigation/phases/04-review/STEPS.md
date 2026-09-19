# Phase 4 steps

| Step | Status | Owner | Scope | Report |
|---|---|---|---|---|
| V1 | FINAL — DO NOT MERGE | `/root/v1_readonly_product_review` | Required read-only review of saved scan, S resolution, queries, evidence/expansion/result, underlying filing excerpts, and consolidated regression | `reports/V1.md` |
| R3 | FINAL — PASS | `/root/r3_product_repair` | Repair exactly V1 findings 1-4; focused/full verification; fresh post-repair rank 2/rank 4 live proof | `reports/R3.md` |
| V2 | FINAL — DO NOT MERGE | `/root/v2_readonly_rereview` | Fresh read-only re-review of repaired state and new live proof | `reports/V2.md` |
| R4 | FINAL — PASS | `/root/r4_final_failclosed_repair` | Repair exactly V2 findings 1-3; focused/full verification; revalidate fresh live proof | `reports/R4.md` |
| V3 | FINAL — DO NOT MERGE | `/root/v3_final_readonly_check` | Focused read-only recheck of V2 findings and final acceptance boundary | `reports/V3.md` |
| R5 | INCOMPLETE | `/root/r5_narrative_grounding_repair` | Worker vanished; partial edits recovered and verified by parent | `reports/R5.md` missing; `evidence/R5-parent-recovery.md` |
| G1 | FINAL — PASS | parent | Targeted final diff/code/proof gate on recovered final state | `reports/G1.md` |

V1 is read-only except its unique report/evidence. It does not rerun broad suites or edit implementation/live artifacts. It must judge faithful reconstruction, closed-world first pass, filing-introduced vocabulary, movement disclosure quality, causal/quantified support, ambiguity, segment-vs-consolidated separation, unnecessary complexity, and analyst usefulness. Concrete findings only.
