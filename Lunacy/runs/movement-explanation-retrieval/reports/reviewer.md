# Phase 3 A1 — Read-only financial/retrieval review

## Control Block

- Scope: final I1 source/test/live state; no source, test, config, or live-output edits.
- Verdict: **DO NOT MERGE** pending one small query-selection repair (P1) and one safety hardening (P2).
- Movement preference works for direct R&D/S&M/G&A disclosures; F1 remains a static-fallback control.
- No initial company-cause leakage observed; expansion phrases are packet/span grounded.
- F1 bridge remains observed `15.598`, disclosed `11.3`, residual `4.298` USD bn; plug false.
- F2 currently omits its central L06 target line because the query cap is consumed by duplicate L04 coverage.
- Multi-driver amounts remain null; F2/F3 reconciliation is correctly `not_computable`.
- Report immutable; parent should authorize a fresh repair if accepting the correction.

## Findings

### P1 — F2 selection starves the central affected line

The F2 finding explicitly affects L04/L05/L06/L07 and asks about Service-and-Other cost (JSON lines 37–53). Its accepted initial queries are `Cost of revenue increased`, `Gross margin increased`, and `Cost of revenue decreased` (JSON lines 646–673). The rejection log says `Service and Other` was rejected only for `initial query limit exceeded` (JSON lines 126–133 and 114–153). Thus the final packet contains no `Service and Other` evidence (`finding_02_movement-i1-2-retry.md` has zero such lines), although the filing has the target cost row at source line 1637 and the static definition at 1831. The new result is better than prior r2 static definitions, but still does not explain the finding’s named driver.

Smallest correction: track accepted line refs and reject a later candidate overlapping an already covered line, including movement-over-movement duplicates; this allows the L06 static fallback after L04/L07 movement hits. Add one four-line regression asserting the fallback survives the three-query cap. No retriever/architecture change.

### Causal support and leakage

- F1’s initial `included` packet and grounded expansion are exact; OpenAI enters only from first-pass filing text, and the deterministic bridge uses the paired source disclosure (JSON lines 449–484, 805–854).
- F3’s three initial sentences and one-pass expansions are exact FY26 expense explanations (JSON lines 716–843; evidence lines 17–71). Drivers are qualitative and cited; no allocation is attempted.
- F2 listed causes are literal filing phrases, but include broad/segment disclosures and no direct L06 evidence; treat them as side evidence, not a complete target bridge.
- No seed leakage observed: initial F1–F3 queries contain no OpenAI/company cause; the unit test deliberately places OpenAI only in filing text and asserts it absent (tests lines 208–235).
- P2 defense gap: `_validate_free_text_claims` accepts a causal sentence when *any* concrete token matches cited text (`filing_investigation.py:1734–1745`); a supported token plus an invented lower-case cause could pass. Existing test covers only wholly unsupported quantum text (tests `:922–938`). Require every non-generic causal token to match, and add that mixed-token regression.

### Ambiguity, regression, and usefulness

- Multi-driver handling is conservative: F2/F3 amounts/periods are null, effects are mostly unknown where cited clauses mix positive/negative semantics, and no residual/plug is model-authored. F1’s Python-only partial bridge is unchanged and numerically correct.
- F1 is not regressed versus prior live control: same accession, four final evidence items, `+15.598/+11.3/+4.298` USD bn and `difference_is_reported_plug=false`.
- F2 is materially more useful than prior r2 (AI infrastructure, cloud growth, mix, efficiency); usefulness remains incomplete until L06 fallback is admitted. F3 is analyst-useful for all three expense lines, though it omits noisy Revenue/Operating-income context by budget.

### Simplicity

The I1 delta is local (118 production / 77 test added lines; one module, finite cue list, no framework or second retrieval architecture) and proportionate. The global cue-tier sort plus three-query cap is the unnecessary complexity/risk: it creates duplicate-line starvation. Per-line coverage tracking is simpler and makes the intended fallback invariant explicit.

