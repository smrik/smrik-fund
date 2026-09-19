# V1 Status

One page. Read this first in every session. Update it last.
Definition of done: Section 2 §2 of `ai_fund_v1_section_2_implementation_spec.md` (16 checkpoints).
Build order: Section 2 Part F (Tasks 1–12). Nothing outside Part F is V1 work.

Last updated: 2026-08-30

## Are we done? 13 of 16.

| # | Checkpoint | Status | Evidence |
|---|-----------|--------|----------|
| 1 | Load MSFT 10-K via EdgarTools | DONE | ingestion works, data/MSFT populated |
| 2 | Three-year analytical P&L | DONE | analytical_pnl.csv |
| 3 | Source reconciliation, visible warnings | DONE | reconciliation_checks.csv |
| 4 | One useful evidence packet | DONE | data/MSFT/03_output/evidence/ |
| 5 | Analyst finds expected adjustment in the first known case | **BLOCKED** | no known case ever chosen (spec §69 open item); human decision, not code |
| 6 | Reviewer reviews the candidate correctly | PARTIAL | eval harness tests reviewer; needs the known-case fixture from #5 |
| 7 | Deterministic validation + materiality runs | DONE | gate implemented, shadow mode per spec §25 |
| 8 | Safe auto-approve / uncertain to human review | DONE | mechanics work; auto-approval behind feature switch (spec M3, enable at M5) |
| 9 | adjustment_history.csv preserves history | DONE | 29 proposals recorded, 0 approved |
| 10 | Review: accept / reject / edit amount / edit period | DONE | review CLI |
| 11 | Manual adjustments use the same engine | DONE | |
| 12 | Current adjustments resolve from history | DONE | |
| 13 | Adjustments apply without mutating reported values | DONE | |
| 14 | Subtotals and metrics recalculate | DONE | |
| 15 | Adjusted reconciliation passes | DONE | adjusted_reconciliation_checks.csv |
| 16 | One golden MSFT end-to-end case passes | **MISSING** | no e2e test exists; depends on #5 |

## The plan (in order, nothing else)

1. **Patrik: pick the first known case.** Read the 29 proposals in
   `data/MSFT/03_output/adjustment_history.csv`. Approve or reject each with a
   one-line reason. The known case is the clearest disclosed one (spec §69:
   not the hardest judgment case). ~1–2 hours. Unblocks #5.
2. **Analyst eval passes on the known case** (#5, #6). Eval harness already exists.
3. **Golden end-to-end test** (Part F Task 12) (#16).
4. **V1 done. Stop.** Review the whole product before any new work.

## Off-spec code — frozen, not V1 work

Not in Part F. Do not extend. Fate decided after V1 (V2 candidates or deletion):

- `analytical_scan.py`
- `filing_investigation.py` (3,555 lines)
- `segments.py`
- `discovery.py` (overlaps with analytical_scan)
- eval cases that target these stages

## Rules

- Only tasks from Section 2 Part F are in scope.
- A task not on that list requires Patrik's explicit written approval, recorded here.
- Every session: read this file first, update it last.
- One task → one branch → focused test → commit (spec §51). No uncommitted piles on main.
- No autonomous/unattended runs without a named Part F task.
