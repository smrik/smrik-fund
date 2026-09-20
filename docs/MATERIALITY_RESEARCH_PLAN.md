# Materiality-led research implementation

Approved 2026-09-20. New development API allowance: EUR 20 beyond previously
committed spending. Preserve the existing ledger and record the starting balance.

## Acceptance plan

- [x] Free, source-bound multi-year ratios and trends; missing values stay missing.
- [x] Provisional DCF and one-driver sensitivities calculated by the existing
  workbook engine. Rank plausible valuation effects; disclose ranges, assumptions,
  model gaps and interactions. Preserve reported history and restore baseline.
- [x] Sol receives the company picture, latest 10-K and 10-Q coverage, diagnostics
  and model limitations; selects up to eight ranked, justified questions.
- [x] A separate Luna request investigates each question. Each receives only its
  brief, relevant diagnostics and source evidence; findings cite exact IDs.
- [x] Sol reconciles findings and selects supported controls/scenarios. No worker
  edits shared controls. Preserve conflicts, uncertain findings and omitted topics.
- [x] Recalculate, independently review, verify native Excel, and publish the IC
  summary with question-to-evidence-to-assumption audit links.
- [x] Focused financial, retrieval, isolation, failure and audit tests; free real
  cases including BBWI and other tickers; one complete live BBWI validation within
  the allowance. Inspect artifacts, relevant regressions and final Git diff.

## Implementation boundaries

Use small Python functions and the existing calculation, budget and request
checkpoint paths. No workflow framework, vector database, second DCF engine,
arbitrary generated formulas or automatic investment approval. Sensitivity ranges
are exploratory stresses, not statistical confidence intervals. An unsupported
driver is an explicit research gap, never a measured zero-impact result.

Implement diagnostics first, then focused research and synthesis, then end-to-end
validation and documentation. Keep free diagnostics usable independently of paid
analysis. Existing free screening and ordinary model runs remain free.

## Verification

- Free real diagnostics: BBWI, NVDA and LULU under `data/diagnostics/20260920/`.
- Initial diagnostics/isolation/template suite: 31 passed; budget/isolation suite:
  21 passed plus nine subtests. Exact provider counting/replay tests added later.
- Related regression suite: 103 passed, nine subtests; four daily-IC tests expose
  an existing midnight UTC/local-date fixture mismatch. Unchanged HEAD reproduces
  it. All four pass with the test clock aligned; production behavior unchanged.
- Live attempt r1 stopped at a strict driver-ID validation gate. Detailed channel
  measures now carry explicit metric, units, period and interpretation under a
  supported parent driver ID. The failed response and its cost are preserved.
- R2 completed the eight-question investigation, synthesis, model review, scenarios,
  native Excel and IC draft. The final IC reviewer initially encountered an old
  flat-file-only audit rule. Added contained-path validation and tamper/escape tests,
  then resumed only that final review against unchanged financial artifacts.
- Final focused suite: 49 passed plus nine subtests. Native Excel: zero errors;
  572 forecast + 90 operating + 176 historical values. Final audit: 119/119 PASS.
- Final live evidence: `data/workspace/runs/20260920-bbwi-materiality-r2/VALIDATION.md`.
  Nineteen paid calls including R1; new goal cost EUR 5.493652 of EUR 20.
- New allowance begins at 78 calls / EUR 5.0965963457 committed; ledger ceiling
  EUR 25.0965963457, preserving all earlier unknown-call reservations.
