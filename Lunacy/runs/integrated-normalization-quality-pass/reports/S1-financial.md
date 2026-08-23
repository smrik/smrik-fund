# S1 — financial correctness / judgment boundary

Status: FINAL. Read-only scout; no source, test, config, or external-state edits.

## Approach

- Read `AGENTS.md`, the approved Section 1/2 docs, the run plan, and Phase 1 steps.
- Inspected the dirty diff and current surfaces in `src/smrik_fund/ingestion/{statements,adjustment_analysis,discovery,filing,reviewer,risk_gate}.py`, `src/smrik_fund/ingestion/adjustments.py`, `src/smrik_fund/main.py`, and focused tests.
- Audited the latest real MSFT run `data/MSFT/03_output/analysis/adjustment_run_20260821T174220907587Z.json` plus its four evidence packets and P&L artifacts.

## Affected surfaces

- Grouped output: `src/smrik_fund/main.py:120-205,208-268`.
- Gate inputs/application boundary: `src/smrik_fund/main.py:271-296,547-570,650-682`; `src/smrik_fund/ingestion/risk_gate.py:107-130`; `src/smrik_fund/ingestion/adjustments.py:53-98`.
- Regression lock-in: `tests/test_adjustment_analysis.py:505-517`.

## Verified invariants / live evidence

- Edgar signs and periods are preserved: `data/MSFT/03_output/analytical_pnl.csv:13` has Other income (expense), net = `+10.697bn`, `-4.901bn`, `-1.646bn` for FY26/FY25/FY24. Exact filing evidence says gain/loss/loss at `data/MSFT/03_output/evidence/01_openai_investment_gains_20260821T174220907587Z.md:23,31`; it explicitly says the FY26 gain only “primarily” relates to the dilution gain.
- Xbox is qualitative only, with no attributable amount (`.../evidence/02_xbox_impairment_expenses_20260821T174220907587Z.md:23,31,39`; manifest candidate amount null at `.../adjustment_run_...json:694-701`). Divestiture is likewise qualitative only (`.../evidence/03_divestiture_gains_20260821T174220907587Z.md:23`; manifest amount null at `...json:828-835`). Both remain human-review/not-applied.
- State separation is present in the real run: `.../adjustment_run_...json:78` reports `reported_equals_adjusted: true`; candidate records show `final_status=human_review` and `application_status=not_applied` (e.g. `...json:484-485`). `adjustment_history.csv` has 23 existing `proposed` rows and no approved rows; `main.py:650-658` writes no history row for this exploratory run.
- Ruff passed on all changed production files; `git diff --check` passed. Focused pytest was blocked by environment: `uv run pytest ...` could not initialize the protected default cache; with `UV_CACHE_DIR=.uv-cache-task8`, uv selected a dependency-empty Python 3.11 (`pandas`/`smrik_fund` missing); repo `.venv` has no pytest.

## Findings / smallest supported fixes

1. **P1 — Python emits an economic judgment in cross-period grouping.** `main.py:197-204` creates “this recurring pattern weakens a one-off normalization case.” The same text appears for OpenAI and tax interest in the real manifest (`...json:113-114,315-316`), and the test hardcodes it (`tests/test_adjustment_analysis.py:511-516`). This violates the plan’s no-Python-judgment invariant and can look like a hardcoded tax rejection. Remove the judgment (and stale test expectation); retaining factual period presence is safe.
2. **P1 — signed OpenAI direction is not explicit in the grouped amount display, and the live Analyst rationale is wrong for negative source facts.** Summary periods are positive adjustment magnitudes (`main.py:174-178`; live `...json:91-107`), while FY25/FY24 source values are losses. The FY25/FY24 candidates say “removing the loss would increase normalized income under the V1 positive-magnitude convention” (`...json:503,571`), but the engine applies `reported - positive_amount` (`adjustments.py:88-98`), which would make a negative source line more negative. The current gate safely blocks these because `_gate_conditions` leaves `source_target_negative=None` (`main.py:288-296`) and the gate fails unknown/negative sign (`risk_gate.py:117-120`), but output should clearly distinguish signed reported fact from positive proposed magnitude and never imply the loss is currently removable.
3. **P1 — “primarily related to” is guarded by Reviewer but still rendered as a candidate amount.** Evidence only supports the FY26 gain’s primary relation to the dilution gain (`...evidence/01_openai...md:23,31`); the live candidate proposes the full `$6.5bn` (`...json:426-434`) and the Reviewer correctly says the entire amount is unsupported (`...json:445-449`). Preserve this as Analyst assessment + uncertainty/reviewer concern; do not let grouped “supported amounts” wording imply full attribution or approval.
4. **P2 — real gate inputs are mostly unknown, so even accepted tax-interest candidates are necessarily human review.** `_gate_conditions` supplies only reconciliation and source availability (`main.py:293-296`); the generic gate rejects unknown materiality/duplicate/group/sign/etc (`risk_gate.py:107-126`). This is conservative and not tax-specific, but do not add a tax-specific rejection while removing finding 1. Scope warning only; no new policy in this pass.

## Non-goals

No new sign framework for negative source facts, materiality/approval policy, retrieval/LLM stage, human UI, issuer generalization, or redesign. Keep candidate/reviewer/gate/application states distinct and preserve exact evidence.

## Estimated size

Small: one direct production deletion/wording adjustment plus focused test expectation updates; any explicit signed display should remain local to grouped rendering. No new mechanism.

