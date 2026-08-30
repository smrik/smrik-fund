# Final financial/product review

Verdict: **DO NOT MERGE**

Scope: read-only review of the repaired code, prompts, tests, R1 reports, and fresh MSFT proof. No source, tests, config, live artifacts, or external systems changed.

## Findings

### P1 — quantified source-fact association is still unsafe

`validate_financial_investigation()` only checks that a driver period is in the allowed FY set and that its year appears somewhere in the concatenated cited excerpts (`src/smrik_fund/ingestion/filing_investigation.py:473-482`). `_amount_and_unit_supported()` accepts the absolute amount if it equals any numeric token and sees the unit anywhere (`:550-563`); `abs()` also permits sign inversion. The fresh packet's E4 contains `$6.5 billion` for FY2026 and `$4.8 billion` for FY2025 in one excerpt (`data/live-finding-proof-r1/MSFT/03_output/evidence/finding_01_20260827T132247363739Z.md:43-47`). A result claiming `4.8`, `usd_billions`, and `2026-06-30 (FY)` (or a year token as the amount) passes validation despite the source's “respectively” mapping; a loss can also pass with a positive amount. This leaves A1's period/unit/source-claim repair incomplete and violates exact periods, amounts, and signs. Live proof is safe only because all four drivers were downgraded to null (`...filing_investigation_...json:136-183`), not because the validator proves the claims.

### P2 — Python-only residual boundary does not cover free-text interpretation/explanation

The structured residual amount was removed and `_movement_reconciliation()` correctly refuses the live five-line/two-delta finding (`src/smrik_fund/ingestion/filing_investigation.py:913-934`; live JSON `:383-393`). However, residual-text rejection scans only `unresolved_remainder` (`:527-530`), while interpretation/explanation are checked only for existence of packet IDs (`:512-526`). A model can therefore put derived plug arithmetic in cited `explanation` or `interpretation`; it would be persisted even though Python reconciliation is `not_computable`. The live prose does not do this (`...json:185-204`), but the no-plug contract is not fully enforced.

## Checks that pass

- Provenance: scan, plan, retrieval, and packet all carry accession `0001193125-26-323660`; plan has 3 queries/0 rejected and retrieval has 13 exact literal items (`...json:21-34,72-124`). Packet E4/E9 retain SEC URL, accession, line ranges, offsets, and exact excerpts (`...evidence...md:43-47,81-87`).
- Financial separation: observed values/signs/deltas are preserved for L11-L15 (`...json:266-380`); the five-line finding is deliberately `not_computable`, with no arbitrary period or plug. Missingness is explicit (`null`, `unknown`, `unquantified`).
- Cause/explanation: OpenAI and dilution-gain claims are supported by E2/E4/E6; tax limitation and unresolved remainder are stated and cited (`...json:185-204`). This is useful analyst search-time reduction, although quantification still requires opening the packet because the live structured drivers are unquantified.
- State isolation: investigation writes analysis/evidence only (`src/smrik_fund/ingestion/filing_investigation.py:720-740,824-910`); R1 output contains only `analytical_pnl.csv` and `reconciliation_checks.csv`, no adjustment history/adjusted P&L. CLI summary is concise and cites drivers, interpretation, explanation, and remainder, but omits reconciliation status (`src/smrik_fund/ingestion/filing_investigation.py:937-992`).
- R1 reports focused 12, relevant 43, full 166 tests, Ruff, compile, and diff-check passing (`reports/repair-1.md:13-22`); no broad rerun here per review scope. Targeted adversarial validation reproduced the amount-token acceptance above without changing the repo.

## Required repair

Bind each quantified driver to an evidence-local amount/period/sign span (or downgrade it), and reject/model-strip derived residual arithmetic from every free-text field before persistence. Add focused regression tests for year-as-amount, cross-year “respectively” swaps, sign inversion, and prose residuals. Then refresh affected checks and MSFT proof.

## Control Block

Verdict: DO NOT MERGE
Blocking: P1 amount/period/sign association; P2 free-text residual bypass.
A1 residual fields/bridge/query/ref/alias repairs otherwise verified.
Fresh MSFT proof: accession-aligned; 3 literal queries; 13 exact evidence items.
Observed movement and signs preserved; multi-line reconciliation correctly not_computable.
Live result is useful for search time, but four quantified disclosures became unquantified.
No state/adjustment writes; no source/tests/config/live artifacts changed.
Report: `Lunacy/runs/finding-driven-investigation/reports/final-financial-review.md`
