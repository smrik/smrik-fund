# I1 implementation report

## Control Block

- Scope: movement-first initial retrieval for the closed-world MSFT V1.
- Decision: adopt P1; reject P2/P3 as insufficient at the initial-selection bottleneck.
- Status: implementation complete; focused/regression/live checks pass; changed-file Ruff and diff pass.
- Live filing: MSFT accession `0001193125-26-323660`, identical across fresh Findings 1-3.
- Seed safety: deterministic source labels plus finite generic nouns/movement cues; no company cause seed.
- State safety: no accounting, adjustment, history, or financial-state writes.
- Reviewer: Phase 3 fresh read-only review remains the next gate.
- Verdict: PASS (I1; parent/Phase 3 gate pending).

## Changed

- `src/smrik_fund/ingestion/filing_investigation.py`: bounded candidates now combine source labels with unambiguous `revenue`, `costs`, `expenses`, or `income` metadata and five fixed movement cues.
- Literal filing-text selection ranks movement candidates before static fallbacks, preserves affected-line order, enforces the existing three-query/evidence budget, and records every rejection.
- Static fallback is retained only when its line has no accepted movement candidate; metadata seed strategy is now `deterministic_finding_source_label_movement_v2`.
- `tests/test_filing_investigation.py`: added qualifier, movement-priority, supersession, and static-only fallback coverage; updated end-to-end expectations.
- No changes to filing retrieval, expansion prompt, investigation prompt, arithmetic, scan, accounting, adjustments, or state handling.

## Findings

- F1 control: fresh completed artifact [filing_investigation_01_movement-i1-1-control.json](data/live-movement-explanation-retrieval-i1/MSFT/03_output/analysis/filing_investigation_01_movement-i1-1-control.json) starts with `Other income (expense), net included`; grounded expansion adds `dilution gain from the OpenAI Recapitalization`; bridge preview is observed `15.598`, known `11.3`, residual `4.298` USD bn, `difference_is_reported_plug=false`. Same 4-item/bridge result as prior r1; no regression.
- F2: fresh completed artifact [filing_investigation_02_movement-i1-2-retry.json](data/live-movement-explanation-retrieval-i1/MSFT/03_output/analysis/filing_investigation_02_movement-i1-2-retry.json) starts `Cost of revenue increased | Gross margin increased | Cost of revenue decreased` (8 initial evidence items); one bounded expansion grounds AI infrastructure, gross-margin percentage, and sales-mix movement (13 final items). Prior r2 started static `Service and Other` only; movement coverage improved. No unsupported amount allocation; reconciliation `not_computable`.
- F3: fresh completed artifact [filing_investigation_03_movement-i1-3-retry.json](data/live-movement-explanation-retrieval-i1/MSFT/03_output/analysis/filing_investigation_03_movement-i1-3-retry.json) starts `Research and development expenses increased | Sales and marketing expenses increased | General and administrative expenses increased` (3 initial evidence items); one bounded expansion grounds compute/AI talent/data, commercial sales/Copilot advertising, and legal/divestiture movement (7 final items). Prior r2 started static S&M only; causal coverage improved. No unsupported allocation; reconciliation `not_computable`.
- All selected live outputs completed with `planner_call_count=0`, same accession, no adjustment/history/state files, and no company-specific initial seed. Three earlier stochastic attempts failed validators and are retained; retries/control above are the selected proof.
- P1 is the smallest effective design: P2 only reorders evidence after retrieval; P3 expands after a packet that can already omit the movement disclosure.

## Tests

- `tests/test_filing_investigation.py`: 46 passed.
- Retrieval/scan/discovery focused set: 22 passed; adjustment/state/review set: 62 passed, 12 subtests.
- Full suite: 200 passed, 4 warnings, 45 subtests.
- `ruff check --no-cache src/smrik_fund/ingestion/filing_investigation.py tests/test_filing_investigation.py`: passed; `git diff --check`: passed. Repository-wide Ruff reports pre-existing B007 at `src/smrik_fund/ingestion/reconciliation.py:338` (unrelated; unchanged).
- Final tracked diff: 2 files, 195 insertions, 24 deletions; no commit/merge.

## Not changed

- Prior run directories and financial data remain untouched. Phase 3 reviewer findings and parent merge decision are intentionally pending.
