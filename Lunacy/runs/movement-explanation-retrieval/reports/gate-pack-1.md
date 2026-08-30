# G0 gate pack — R1 final compression

## Control Block

- Scope: read-only compression of final R1 source/test/live state; no approval or rerun.
- Working tree: only tracked edits are `filing_investigation.py` and `test_filing_investigation.py`; three prior run dirs untracked.
- Final diff: 2 files, 246 insertions / 27 deletions; no commit or merge.
- Verification snapshot: focused 70 passed; adjustment/state/review 82 passed, 37 subtests; full 202 passed, 45 subtests.
- Ruff changed files and `git diff --check`: pass; 4 dependency warnings and unrelated repository Ruff B007 remain reported.
- Live filing: MSFT 10-K accession `0001193125-26-323660`, report period 2026-06-30, same across F1-F3.
- A1 P1/P2: demonstrably closed by final code, focused regressions, and selected live F2/P2 evidence.
- This pack compresses evidence; parent G1 retains PASS/DO NOT MERGE authority.

## Final changed surfaces

- [filing_investigation.py](../../../../src/smrik_fund/ingestion/filing_investigation.py): fixed movement cues/qualifiers at lines 332-348; deterministic initial derivation and static fallback at 434-529; seed metadata at 580.
- Same module: causal grounding now requires every non-generic token in cited text at 1710-1744; selection ranking, line-ref tracking, supersession, and query cap at 2068-2167.
- [test_filing_investigation.py](../../../../tests/test_filing_investigation.py): closed-world/qualifier/movement/static fallback/line-cap regressions at 208-315; mixed causal-token regression at 958-976; existing expectation updates only elsewhere.
- No retrieval API, prompts, arithmetic, scan, accounting, adjustment, history, or model-state surface changed.

## Retrieval and live comparison

- F1 [JSON](../../../../data/live-movement-explanation-retrieval-r1/MSFT/03_output/analysis/filing_investigation_01_20260828T142623370684Z.json) / [evidence](../../../../data/live-movement-explanation-retrieval-r1/MSFT/03_output/evidence/finding_01_20260828T142623370684Z.md): initial `Other income (expense), net included` (static fallback; no movement hit); one grounded expansion `dilution gain from the OpenAI Recapitalization`; 4 final items. Exact $6.5bn FY26 gain/$4.8bn FY25 loss disclosure; observed 15.598, known 11.3, residual 4.298 USD bn, `difference_is_reported_plug=false`.
- F2 [JSON](../../../../data/live-movement-explanation-retrieval-r1/MSFT/03_output/analysis/filing_investigation_02_20260828T143952146041Z.json) / [evidence](../../../../data/live-movement-explanation-retrieval-r1/MSFT/03_output/evidence/finding_02_20260828T143952146041Z.md): initial `Cost of revenue increased`, `Gross margin increased`, `Service and Other`; 12 initial and 14 final items. One grounded expansion captures AI infrastructure; E10/E11 retain the central L06 Service-and-other rows/static fallback. Other exact movement evidence covers efficiency, Azure/mix; qualitative only, no allocation, reconciliation `not_computable`.
- F3 [JSON](../../../../data/live-movement-explanation-retrieval-r1/MSFT/03_output/analysis/filing_investigation_03_20260828T144057144100Z.json) / [evidence](../../../../data/live-movement-explanation-retrieval-r1/MSFT/03_output/evidence/finding_03_20260828T144057144100Z.md): initial R&D/S&M/G&A movement queries (3 items); one grounded expansion for compute capacity/AI talent/data; final exact evidence covers commercial sales/Copilot advertising and legal/divestiture movement (4 items). Qualitative only, no allocation, reconciliation `not_computable`.
- Improvement versus prior r2 is concrete: F2 no longer starves L06 behind duplicate L04 movement hits; F3 covers all three named expense lines rather than static S&M only. F1 remains the positive control.

## A1 closure and gate notes

- P1 closed: `_select_initial_queries` records accepted line refs before applying the three-query cap, rejects overlap, and admits the L06 static fallback after L04/L07 movement hits; regression lines 300-315 plus live F2 initial/final evidence demonstrate it.
- P2 closed: `_validate_free_text_claims` uses `all(...)` over non-generic causal tokens; `test_mixed_supported_and_invented_causal_tokens_fail_closed` proves supported-plus-invented prose fails closed while prior neutral-word acceptance remains.
- Closed-world safety is evidenced by planner call count 0, finite generic initial seeds, exact first-pass refs/spans for expansions, one expansion pass, and no adjustment/history/state outputs in selected artifacts.
- Gate-only finding: `git status` also emits a pre-existing `.pytest_cache` permission warning; no source/test diff outside the two final files observed.

## Authoritative reports

- [repair-1.md](repair-1.md) is the terminal R1 verification and live comparison report; [reviewer.md](reviewer.md) records A1 defects that the repair addresses.
