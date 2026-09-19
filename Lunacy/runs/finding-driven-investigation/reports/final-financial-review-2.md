# Final financial/product review — R2

Verdict: **DO NOT MERGE**

Scope: fresh read-only review of the R2 code, prompts, focused regressions, saved outputs, and current diff. No source, tests, config, live artifacts, or external systems changed.

## Findings

### P1 — quantified evidence spans still do not prove amount/period/sign binding

`_matching_support_span()` only proves that the submitted span is copied from one cited excerpt, and `_driver_claim_supported()` accepts any span with exactly one qualified amount and one four-digit year when their offsets are within 240 characters (`src/smrik_fund/ingestion/filing_investigation.py:670-718`). It does not establish that the year belongs to that amount or that the amount's sign is expressed by the filing semantics. A fresh read-only probe returned `True` for `amount=5`, FY2026, and the exact span `The company disclosed 5 million for a prior period. Results in fiscal 2026 improved.`; it also returned `True` for positive `5` in `The company disclosed 5 million loss in 2026.`. The former allows an unrelated-year period claim; the latter can invert a signed loss. This remains an evidence-local binding failure despite the R2 tests for year-as-amount, `respectively`, and parenthetical sign inversion (`tests/test_filing_investigation.py:376-454`).

The live packet is conservative because the `respectively` construction was downgraded to an unquantified driver (`data/live-finding-proof-r1/MSFT/03_output/analysis/filing_investigation_01_20260827T140053515105Z.json:136-148`), but that does not prove the validator is safe for other filings. Require a syntactically/semantically local amount-period-sign span or downgrade it; explicitly handle source words such as gain/loss when preserving signed amounts.

### P1 — free-text no-plug and numeric-support checks remain bypassable

`_validate_free_text_claims()` only rejects residual wording when it finds a qualified numeric amount or a digit token (`src/smrik_fund/ingestion/filing_investigation.py:721-758`). A fresh read-only probe accepted `The residual is five million.` against an excerpt with no such amount, so a model can persist a residual amount in words despite the Python-only residual boundary. The same function checks unqualified numeric support with raw substring membership (`:744-747`); a probe accepted `The filing disclosed 5.` against cited evidence `The filing disclosed 15 million in 2026.`, so unsupported numeric claims can pass by matching a digit substring. Existing regressions cover digit residuals and simple arithmetic but not word amounts or token boundaries (`tests/test_filing_investigation.py:456-490`). Reject residual/plug arithmetic in word and qualified forms and require token-boundary support for every free-text numeric claim before persistence.

## Checks that pass

- R2 records focused 19, relevant 43, full 173 tests, Ruff, production compile, and `git diff --check` passing (`Lunacy/runs/finding-driven-investigation/reports/repair-2.md:13-22`). Fresh targeted adversarial selection ran 7 tests: **7 passed, 12 deselected**; no broad suite rerun.
- Fresh proof is accession-aligned and provenance-rich: scan/investigation metadata carries `0001193125-26-323660` (`.../filing_investigation_01_20260827T140053515105Z.json:21-34`), retrieval has three literal queries and six evidence items (`:104-122`), and E1–E6 retain SEC source, accession, source lines, and offsets (`.../finding_01_20260827T140053515105Z.md:17-63`).
- Observed source values/signs and all five affected lines are preserved (`...json:200-315`). The live multi-line bridge is conservatively `not_computable` with null residual and `difference_is_reported_plug=false` (`:317-327`). No adjustment history or adjusted-P&L output appears in the isolated proof root; the orchestration only writes analysis/evidence artifacts (`src/smrik_fund/ingestion/filing_investigation.py:998-1120`).

## Acceptance reassessment

Evidence/provenance, bounded literal retrieval, reported-vs-analysis separation, missingness, and state/adjustment isolation pass on the live artifact. The output is partially useful for analyst time: it identifies the OpenAI-related disclosed cause with exact packet references, while correctly leaving tax items and the full bridge unresolved (`...json:150-170`). Quantified/unquantified handling is conservative for the current `respectively` disclosure, but the generic amount validator and free-text boundary are not safe enough to satisfy financial correctness. Python reconciliation is no-plug on this live result, yet the rejected-field bypass means the contract is not enforced for all model outputs. CLI/artifact surfaces are coherent; no unrelated lifecycle, normalization, adjustment, or scan semantics changed in the current diff.

## Control Block

Verdict: **DO NOT MERGE**
Blocking: P1 amount/period/sign span binding; P1 free-text residual and numeric-token validation.
R2 targeted regressions: 7 passed; R2 recorded 19 focused / 43 relevant / 173 full.
Fresh MSFT proof: accession `0001193125-26-323660`; 3 literal queries; 6 exact evidence items.
E1–E6 retain SEC URLs, accession, source lines, and offsets; observed signs/values are preserved.
Live reconciliation is `not_computable`; residual is null and no plug is reported.
State/adjustment/lifecycle surfaces remain isolated; CLI/artifact are analyst-useful but partial.
Current live result saves search time for OpenAI cause; tax/bridge remain unresolved and four amounts are unquantified.
Required: repair semantic span binding/sign handling and free-text word-amount/token-boundary checks, then refresh tests and live proof.
Report: `Lunacy/runs/finding-driven-investigation/reports/final-financial-review-2.md`
