# Task 9 — deterministic risk gate

## Authority

- `AGENTS.md`
- `docs/ai_fund_v1_section_1_updated.md` (canonical filenames named by the user are absent)
- `docs/ai_fund_v1_section_2_implementation_spec.md`
- established Task 7 Analyst and Task 8 Reviewer implementations/tests
- active user request for Task 9

## Shape

Ordinary Lunacy path: one phase, one fresh `gpt-5.6-luna` owner at `xhigh`. No proposal scouts. No adversary or gate scout unless the worker reports a concrete integrity risk that cannot be judged directly by the parent.

## Goal

Implement the smallest pure deterministic Python gate that consumes the existing Analyst candidate, existing Reviewer result, and only the explicit mechanical Task 9 condition inputs required by Section 2. Return an explicit result identifying auto-approval eligibility versus human review and the mechanical reasons.

No model call and no financial judgment in Python. Do not invent materiality thresholds: Section 2 says they remain provisional, so enforce an explicit precomputed/known materiality eligibility signal or an equivalently small contract. Unknown/unrun required conditions must fail closed to human review.

## Acceptance

- all documented eligibility conditions must pass for auto-approval;
- Reviewer revise/reject, null amount, estimated/unknown basis, dangerous $3.1bn fixture, unresolved reconciliation, materiality failure/unknown, duplicate/group/aggregate/negative-target/deterministic-check failures all block eligibility as Section 2 requires;
- calculated basis requires valid calculation; disclosed basis does not invent a calculation requirement;
- no generic rules engine, policy DSL, upstream redesign, persistence/workflow/application, or Task 10+ behavior;
- focused tests, relevant Task 7/8 regressions if integration warrants, Ruff, `git diff --check`, and final diff review pass.

## Gate

The worker owns terminal verification. Parent reads its terminal Control Block, inspects the targeted diff, and runs one bounded acceptance sample. No redundant gate scout by default.
