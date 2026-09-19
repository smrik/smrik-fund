# Repair 1 — bounded A1 repair

## Control Block

- Scope: only A1 P1 line-ref starvation and P2 mixed-token causal grounding.
- Status: repaired; focused, regression, full, Ruff, and diff checks pass.
- Live accession: `0001193125-26-323660` for all selected MSFT artifacts.
- F1 control: observed `15.598`, disclosed `11.3`, residual `4.298` USD bn; plug `false`.
- Verdict: **PASS** for R1; parent gate remains pending.

## Changed

- Initial selection now tracks every accepted line ref; overlapping later candidates are rejected before the three-query cap. Movement-over-movement duplicates and superseded static fallbacks remain explicit in rejection metadata.
- Causal prose now requires every non-generic token to occur in cited evidence; generic neutral analytical words retain the prior relaxation.
- Focused regressions cover fallback survival under the cap and a supported-plus-invented lower-case causal claim.

## Retrieval design

Selection remains deterministic, filing-local, literal, one-pass, and bounded. F2 now selects `Cost of revenue increased`, `Gross margin increased`, and `Service and Other`; the latter preserves the central L06 static fallback.

## Live comparison

- F1 [artifact](C:/Projects/finance/smrik-fund/data/live-movement-explanation-retrieval-r1/MSFT/03_output/analysis/filing_investigation_01_20260828T142623370684Z.json): initial `Other income (expense), net included`; expansion `dilution gain from the OpenAI Recapitalization`; strongest evidence is the exact respective $6.5bn/$4.8bn disclosure. Drivers are OpenAI investment gains/losses and dilution gain; deterministic bridge is partial (`+15.598 = +11.3 + 4.298`, no plug).
- F2 [artifact](C:/Projects/finance/smrik-fund/data/live-movement-explanation-retrieval-r1/MSFT/03_output/analysis/filing_investigation_02_20260828T143952146041Z.json): initial `Cost of revenue increased` / `Gross margin increased` / `Service and Other`; grounded expansion `driven by investments in AI infrastructure`; strongest evidence includes AI infrastructure, efficiency gains, Azure mix, and the L06 cost row. Qualitative only; no allocation; reconciliation `not_computable`.
- F3 [artifact](C:/Projects/finance/smrik-fund/data/live-movement-explanation-retrieval-r1/MSFT/03_output/analysis/filing_investigation_03_20260828T144057144100Z.json): initial R&D/S&M/G&A movement queries; grounded expansion `driven by continued investments in compute capacity, AI talent, and data`; strongest evidence covers compute/AI/data, commercial sales/Copilot advertising, and legal/divestiture expenses. Qualitative only; reconciliation `not_computable`.

## Finding 1 regression

`test_mixed_supported_and_invented_causal_tokens_fail_closed` rejects the mixed causal claim; the existing neutral-word acceptance test remains green.

## Safety and files changed

No adjustment, history, adjusted-P&L, accounting, model-state, retrieval architecture, or grounding-contract changes. Source: `src/smrik_fund/ingestion/filing_investigation.py`; tests: `tests/test_filing_investigation.py`.

## Tests

- Focused retrieval/investigation/scan/discovery: `70 passed`.
- Adjustment/state/review regressions: `82 passed`, `37 subtests passed`.
- Full suite: `202 passed`, `45 subtests passed`, 4 pre-existing dependency warnings.
- `ruff check --no-cache` on changed files: passed; `git diff --check`: passed.

## Production diff and simplicity review

Working-tree diff is 2 files, `246 insertions / 27 deletions` including the prior I1 implementation; R1 is local state tracking plus one validator quantifier and two focused tests. No new abstraction or second retrieval path.

## Reviewer findings

A1 P1 and P2 are resolved. F1 remains the positive control; F2 includes the previously starved L06 evidence; F2/F3 remain conservative and do not allocate mixed drivers.

## Not changed

Prior reports, run artifacts, user files, and commits/merges were not modified.
