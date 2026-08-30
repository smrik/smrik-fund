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

1. **DONE 2026-08-30 — known case chosen by Patrik: OpenAI recapitalization
   dilution gain.** Triage of adjustment_history.csv also done: 23 LLM
   proposals were amount-less R&D exhaust; the 3 quantified UTP-interest
   adjustments were correctly rejected as recurring.

   Known-case expected values (spec §41 analyst-eval fields), source: FY2026
   10-K, accession 0001193125-26-323660, Note 3 / MD&A:
   - target_line: Other income (expense), net (reported FY2026 total +$10,697M)
   - period: 2026-06-30 (FY)
   - item_amount: $6.5B — disclosed verbatim ("$6.5 billion of net gains ...
     from investments in OpenAI"); exact dilution-only figure is NOT separately
     disclosed (verified: all 3 filing occurrences say "primarily")
   - item_effect_on_line: increased_line → line_delta −$6.5B → adjusted +$4,197M
     (no zero-crossing)
   - amount_basis: disclosed
   - evidence packets already on disk: evidence/01_openai_* files
   - expected gate outcome: human review (materiality — $6.5B fails the 5%
     operating-income cap), then human approve. Auto-approve is NOT expected.

   Runner-up case (backlog): Xbox impairment — named in MD&A with no amount in
   current packets; needs the impairment note retrieved before usable.
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

## V2 backlog (parked ideas — recorded, NOT approved for V1)

- Segment-driven forecasting (raised 2026-08-30): add segment revenue /
  operating-income rows to the analytical model; LLM proposes per-segment
  forecast drivers (growth, margin) with evidence, through the same
  analyst → reviewer → gate pattern. Hard dependency: consumes the ADJUSTED
  P&L, which exists only after V1 closes. `segments.py` (frozen) is the
  starting material.

## Rules

- Only tasks from Section 2 Part F are in scope.
- A task not on that list requires Patrik's explicit written approval, recorded here.
- Every session: read this file first, update it last.
- One task → one branch → focused test → commit (spec §51). No uncommitted piles on main.
- No autonomous/unattended runs without a named Part F task.
