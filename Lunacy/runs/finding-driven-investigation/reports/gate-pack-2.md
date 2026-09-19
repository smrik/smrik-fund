# G0b final R4 gate pack — finding-driven filing investigation

Date: 2026-08-27  |  Workspace: `C:\Projects\finance\smrik-fund`  |  Baseline: `46ca750`

Gate position: **READY FOR PARENT GATE; not an approval.** The successful final R4 MSFT artifact is present and passes bounded structural/financial checks. No current acceptance blocker was found below. Parent G1 remains responsible for the required final `PASS` or `DO NOT MERGE` verdict.

## Final-state changed surfaces

`git diff --stat 46ca750` reports only tracked changes (2 files, 96 insertions) because the new files are untracked. Final changed source/test/prompt surfaces are:

| File | Final symbols/regions | Size / contract |
|---|---|---|
| `src/smrik_fund/ingestion/filing_investigation.py:116-256` | `FindingSearchPlan`, `DisclosedDriver`, `FinancialInvestigationResult` | Native structured plan/result models; explicit null/missingness and evidence refs |
| same `:284-405` | `_bounded_context`, `build_finding_plan_context`, `run_search_plan` | Max 8 passages/8,000 chars; max 3 literal queries; finding refs preserved |
| same `:408-588` | `build_observed_movement`, `validate_financial_investigation` | Python-copied reported rows; period/sign/span/evidence validation; atomic unquantified downgrade |
| same `:591-1012` | amount/token/semantic helpers, `_validate_free_text_claims`, `reconcile_disclosed_amounts` | Local amount/year/sign proof; numeric-free narrative; Python-only sum; no plug |
| same `:1015-1083` | `run_financial_investigation` | One structured investigator call against unchanged evidence packet |
| same `:1086-1320` | filing identity, save/orchestration, `_movement_reconciliation` | Plan → literal EdgarTools evidence → structured investigation → JSON/evidence; conservative multi-line/period handling |
| same `:1322-1450` | summary/load/select/latest-scan helpers | Analyst rendering; saved scan context/accession validation |
| `src/smrik_fund/ingestion/analytical_scan.py:49-51` | `ScanFinding = AnalyticalScanFinding` | Vocabulary alias only; persisted scan schema/semantics unchanged |
| `src/smrik_fund/main.py:53-66,2328-2401` | investigation imports and `investigate` command | Separate saved-scan finding CLI; latest filing accession gate; no adjustment path |
| `prompts/filing_search_plan.md:1-14` | v1 search-plan prompt | Retrieval-only, contiguous literal phrases, bounded 0–3 query list |
| `prompts/financial_investigation.md:1-45` | v4 investigator prompt | Exact spans for structured quantities; narrative strictly numeric-free; no plug/forecast/recommendation |
| `tests/test_filing_investigation.py:1-847` | 28 focused tests | Bounds, provenance, signs, ambiguity, no-plug, metadata clearing, rendering, saved-scan/CLI isolation |

Line counts: new production module 1,450; `main.py` addition 91; scan alias 5 = **1,546 production lines**. New focused test file 847; prompts 59. This exceeds the AGENTS.md ~200-line production scope-warning threshold; parent must decide whether the bounded acceptance surface justifies it.

## Final live proof

Artifact: [filing investigation JSON](../../../../data/live-finding-proof-r4/MSFT/03_output/analysis/filing_investigation_01_20260827T152234074645Z.json)

Evidence: [exact filing evidence packet](../../../../data/live-finding-proof-r4/MSFT/03_output/evidence/finding_01_20260827T152234074645Z.md)

Observed final artifact facts:

- `status=completed`; ticker `MSFT`; investigation run `20260827T152234074645Z`; scan run `20260827T131624327070Z`.
- Saved scan, retrieval, and evidence all align to accession `0001193125-26-323660` (`10-K`, period `2026-06-30`, primary document `msft-20260630.htm`).
- Plan metadata: `filing-search-plan-v1`, `filing-investigation-v2`, 3 queries, 0 rejected. Retrieval method explicitly records EdgarTools `search(regex=False)` literal section hits plus `text()` literal occurrences; 6 evidence items.
- Investigator metadata: `financial-investigation-v4`, `filing-investigation-v2`, model `gpt-5.6-luna`, reasoning `high`.
- Evidence packet has E1–E6, SEC filing/text URLs, accession on every locator, source lines/offsets, and exact quoted filing excerpts. E1–E3 are the 2026/2025 OpenAI disclosure; E4–E6 retain the three-year disclosure including 2024.

Representative structured preview:

```text
drivers=2; both amount=null, amount_unit=unknown, period=null,
amount_basis=unquantified, evidence_span=null; refs=[E1,E2] and [E3]
observed_movement=5 signed source lines (L11–L15), three FY periods retained
reconciliation=status=not_computable; observed_amount=null;
  unresolved_difference=null; difference_is_reported_plug=false
```

The two unquantified drivers preserve the `respectively` ambiguity rather than assigning values across years. The numeric-free check found 0 digit hits and 0 spelled-number hits across both driver descriptions plus interpretation, remainder, and explanation. The final validator re-accepted the saved structured result against the saved evidence packet (`artifact_validation=PASS`, 2 drivers, 15 cited refs, 3 allowed periods).

Representative packet preview (`E1`, lines 17–23): exact SEC excerpt states that other income included OpenAI net gains/losses for fiscal years 2026 and 2025, respectively, and that the latest-year gains primarily related to the OpenAI Recapitalization. The model leaves the tax bridge and complete component bridge unresolved with E1–E6 citations.

## Acceptance mapping

| Acceptance | Final-state assessment |
|---|---|
| Exact excerpts/provenance; causes evidence-backed | **Pass in artifact.** E1–E6 are exact source lines with URLs, accession, section locators, lines, offsets; every driver/narrative field has valid packet refs. |
| Quantified/unquantified drivers; ambiguity preserved | **Pass by code + live conservative result.** Tests retain a valid quantified structured claim; live `respectively` claims remain unquantified and clear all quantitative metadata. |
| Observed / disclosed / interpretation / unresolved separation | **Pass.** Separate top-level JSON fields and deterministic five-line observed movement. |
| Python-only arithmetic; no balancing plug | **Pass for this finding.** Three-year/five-line bridge is not selected; reconciliation is `not_computable`, null residual, plug flag false. No free-text arithmetic or residual amount. |
| Inspectable JSON + coherent finance-first CLI | **Pass.** Artifact and evidence paths are stable; `investigate` validates saved scan/context/latest accession and renders observed/disclosed/interpretation/unresolved sections. |
| No lifecycle/adjustment/normalization/materiality/identity/review changes | **Pass by diff and isolation test.** Only scan alias, separate investigation module/prompts/tests, and separate CLI command/imports; R4 proof root has no `adjustment_history.csv` or `adjusted_pnl.csv`. |
| Normal tests avoid live LLM calls | **Pass.** Focused tests inject fake clients; no live LLM call in test path. |
| Current real MSFT proof + fresh review | **Pass for proof; parent decision pending.** Final R4 artifact is real current MSFT output with v4 metadata; this G0b review is read-only and does not approve. |

## Terminal verification

Run by G0b on the unchanged final source state:

- `$env:PYTHONPATH=(Resolve-Path src).Path; & 'C:\Users\patri\miniconda3\envs\ai-fund\python.exe' -m pytest tests/test_filing_investigation.py -q` → **28 passed**, 4 warnings (EdgarTools deprecations and pre-existing `.pytest_cache` permission warning).
- `ruff check src/smrik_fund/ingestion/filing_investigation.py src/smrik_fund/ingestion/analytical_scan.py src/smrik_fund/main.py tests/test_filing_investigation.py` → **passed**.
- `ruff format --check src/smrik_fund/ingestion/filing_investigation.py tests/test_filing_investigation.py` → **2 files already formatted**.
- Full changed-file `ruff format --check ... analytical_scan.py ... main.py ...` → **fails only because those 2 tracked files would reformat**. Baseline stdin checks for both files from `46ca750` also exit 1; this is pre-existing formatting drift, not a final-R4 behavior defect. No formatting changes made.
- `git diff --check 46ca750` → **passed** (only existing LF/CRLF warnings).
- Ad hoc final JSON/evidence validator and invariant checks → **passed**; import emits a pre-existing Edgar cache-clear `WinError 5` warning but does not affect output.
- R4 terminal report also records: focused 28 passed; full suite 182 passed + 45 subtests; Ruff/compile/diff-check passed at repair time. G0b did not rerun broad suites per scope.

## Current blockers and residuals

- **No current functional, financial, provenance, narrative, state-isolation, or CLI blocker found in final R4 proof.**
- **Parent-only residual:** production addition is 1,546 lines versus the AGENTS.md ~200-line scope warning; parent must make an explicit proportionality decision.
- **Pre-existing check residual:** full changed-file Ruff format check is red for baseline formatting in `analytical_scan.py` and `main.py`; added module/tests pass format check. Do not conflate with requested behavior.
- `docs/ai_fund_v1_section_1.md` and `docs/ai_fund_v1_section_2.md` are absent from this checkout, so source-of-truth cross-check remains unavailable; no docs were changed.
- Test/import environment warnings: EdgarTools deprecations, `.pytest_cache` permission, and Edgar `_tcache` permission. All bounded checks and artifact validation completed successfully.

## Exact bounded parent checks

Parent G1 should run these only on the unchanged final tree, then issue the required final verdict:

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
& 'C:\Users\patri\miniconda3\envs\ai-fund\python.exe' -m pytest tests/test_filing_investigation.py -q
& 'C:\Users\patri\miniconda3\Scripts\ruff.exe' check src/smrik_fund/ingestion/filing_investigation.py src/smrik_fund/ingestion/analytical_scan.py src/smrik_fund/main.py tests/test_filing_investigation.py
& 'C:\Users\patri\miniconda3\Scripts\ruff.exe' format --check src/smrik_fund/ingestion/filing_investigation.py src/smrik_fund/ingestion/analytical_scan.py src/smrik_fund/main.py tests/test_filing_investigation.py
git diff --check 46ca750
git status --short
git diff --stat 46ca750
```

Pure acceptance sample: re-open the final JSON/evidence links above; confirm metadata v4/schema/accession, E1–E6 provenance, 0 narrative numeric hits, two unquantified drivers, five signed observed lines, `not_computable` reconciliation/null residual/false plug, and zero adjustment/history files. Do not rerun broad suites or regenerate the live artifact unless the final tree changes.

## Control Block

- Decision: **PARENT GATE REQUIRED; this pack is not approval.**
- Current blocker: **none found** in final R4 source/live proof.
- Final proof: completed MSFT artifact, accession `0001193125-26-323660`, prompt `financial-investigation-v4`.
- Retrieval: 3 literal queries, 0 rejected, 6 exact E1–E6 evidence items.
- Narrative: 0 digit hits, 0 spelled-number hits; 2 drivers conservatively unquantified.
- Reconciliation: `not_computable`, null residual, `difference_is_reported_plug=false`.
- Isolation: no adjustment/history outputs in final proof root; CLI command remains separate.
- Verification: 28 focused tests passed; Ruff lint passed; added files formatted; diff-check passed.
- Residual: baseline formatting check red plus ~1,546-line production scope warning; parent decision required.
- Required outcome: parent issue final `PASS` or `DO NOT MERGE` after bounded checks.
