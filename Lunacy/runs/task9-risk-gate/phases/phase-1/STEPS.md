# Phase 1 — implement deterministic risk gate

## S1

Status: COMPLETE — PASS

Owner: one fresh `gpt-5.6-luna` worker at `xhigh`.

Read full project authority, full current Analyst/Reviewer production and tests, and relevant callers before editing. Inventory reuse first. Treat Tasks 7/8 as established.

Implement one small direct module/pure function and focused deterministic tests. Consume `AnalystCandidate`, `ReviewResult`, and the minimum explicit mechanical condition inputs needed by Section 2. Return an explicit decision plus ordered/inspectable failure reasons. Use exact documented policy only; keep financial judgment out of Python. Materiality thresholds are provisional, so do not invent one. Fail closed when any required mechanical eligibility fact is absent/unknown.

Required tests: fully eligible; Reviewer revise; Reviewer reject; null amount; dangerous $3.1bn with revise/Reviewer basis unknown/no suggested amount; all explicit reconciliation/materiality/evidence/judgment/target/period/calculation/duplicate/group/aggregate/source-target/deterministic-check rules. Keep tests focused, not combinatorial framework.

Boundaries: no model, Reviewer/Analyst changes, evidence retrieval, persistence unless the existing Task 9 spec explicitly requires it, human CLI, adjustment application, revision workflow, generic framework, Task 10+. Consequential upstream mismatch or material scope expansion requires `DECISION_REQUIRED` before editing.

Terminal verification: focused Task 9 tests; relevant Task 7/8 regression tests if touched/integrated; Ruff check/format on changed code; `git diff --check`; diff/stat self-review. Report immutable `Lunacy/runs/task9-risk-gate/reports/S1.md` with <=12-line Control Block and design, rule-to-Section-2 mapping, files, exact checks, deferred work, and separate production/test line counts.
