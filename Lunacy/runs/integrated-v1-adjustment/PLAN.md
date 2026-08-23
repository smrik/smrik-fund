# First integrated V1 adjustment-analysis pipeline

## Authority

- `AGENTS.md`
- `docs/ai_fund_v1_section_1_updated.md` and `docs/ai_fund_v1_section_2_implementation_spec.md` (the unsuffixed filenames named by the user are absent)
- current analytical P&L, reconciliation, Analyst, Reviewer, risk gate, and adjustment/history/application code/tests
- active user request for the integrated MSFT flow

## Execution shape

Full Implementation Hive, explicitly required:

1. three independent read-only Luna proposal/prerequisite scouts at `xhigh`;
2. one fresh Luna synthesis/implementation owner at `max`;
3. one fresh Luna simplicity adversary at `xhigh`;
4. Sol parent end-to-end gate, with a gate scout only if the deterministic Hive routing conditions require one.

## Hard prerequisite

Before implementation, establish whether the existing Task 4 adjustment-history/application engine exists and materially matches the V1 contract. If absent or materially incomplete, no integration code may invent replacement architecture. Return `DECISION_REQUIRED` with exact files and the smallest prerequisite.

## Integrated contract

Thin sequential path:

`analytical P&L + frozen evidence -> Analyst -> Reviewer per candidate -> deterministic risk gate -> existing history/application engine for auto-approved candidates only -> adjusted historical P&L`

Every candidate retains the exact Analyst proposal, Reviewer result, gate decision/reasons, and final applied/human-review status. Human-review candidates are preserved, reported, never assigned an invented amount, and never affect adjusted P&L. Use existing deterministic mechanics for application/subtotals/metrics. Integrate into `smrik-fund analyze MSFT --adjustments`; do not add a second command or workflow framework.

## Real MSFT acceptance

The Xbox candidate (`Research and development`, FY2026, amount null, basis unknown, E2) is reviewed as revise/unknown with no replacement amount, gated to human review, preserved, and not applied. With no other eligible candidate, adjusted and reported P&L remain equal. Persist the minimum run output needed to inspect proposal, review, gate reasons, final status, application status, and adjusted-P&L path.

## Boundaries

No human-review UI, retrieval/RAG, agent/workflow framework, service/repository/provider layers, new approval/materiality/Reviewer policy, new adjustment arithmetic, compatibility layer, or Task 10+ behavior. Mostly glue; implementation must be noticeably smaller than the stages it connects.

## Verification/gate

Implementation owner proves focused integration/regressions and real MSFT Analyst -> Reviewer -> gate -> unapplied/equal-P&L behavior. Simplicity adversary attacks duplicate stage logic, abstractions/state objects/frameworks/persistence/CLI and hypothetical surfaces. Sol inspects the actual command path, judgment/accounting boundaries, impossible human-review application, mechanism reuse, and Xbox outcome. No commit.
