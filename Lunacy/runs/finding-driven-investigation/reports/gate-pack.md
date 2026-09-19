# G0 gate pack — finding-driven filing investigation

Date: 2026-08-27  |  Workspace: `C:\Projects\finance\smrik-fund`  |  Baseline: `46ca750`

Gate position: **BLOCKED — do not approve this phase.** R4 code and bounded checks are terminal PASS, but the required final-state real MSFT proof was not produced: SEC retrieval stopped at host `WinError 10013` before investigation (`reports/repair-4.md:36-41`).

## Final-state navigation

The baseline has no `src/smrik_fund/ingestion/filing_investigation.py`; the new module is therefore a full 1,450-line addition. Tracked baseline diff is only 96 insertions, so `git diff --stat` does not show all new production/test files.

| Surface | Final symbols / regions | Contract carried |
|---|---|---|
| `src/smrik_fund/ingestion/filing_investigation.py` | `FindingSearchPlan` 116-152; `DisclosedDriver` 155-221; `FinancialInvestigationResult` 224-256 | bounded native structured outputs; explicit missingness and refs |
| same | `build_finding_plan_context` 309-337; `run_search_plan` 340-405 | only bounded passages; literal query filtering, max 3 |
| same | `build_observed_movement` 408-457; `validate_financial_investigation` 460-588 | Python-copied reported movement; evidence/accession-period validation; atomic downgrade |
| same | `_amount_mentions` 695-744; `_driver_claim_supported` 828-870; `_validate_free_text_claims` 887-934 | local amount/year/sign proof; numeric-free model narrative; no prose residual/arithmetic |
| same | `reconcile_disclosed_amounts` 951-1012; `_movement_reconciliation` 1298-1320 | Python-only disclosed sum; no plug; no arbitrary multi-line/multi-period bridge |
| same | `run_financial_investigation` 1015-1083; `investigate_finding` 1128-1295 | plan → existing literal EdgarTools evidence → structured investigation → JSON/evidence writes |
| same | `render_finding_investigation_summary` 1322-1379; `load_saved_scan` 1382-1427; `select_saved_finding` 1430-1440 | analyst CLI rendering; saved scan context/ticker/accession checks |
| `src/smrik_fund/ingestion/analytical_scan.py` | alias `ScanFinding = AnalyticalScanFinding` at 49-51 | vocabulary-only; persisted scan validation/schema unchanged |
| `src/smrik_fund/main.py` | investigation imports 53-66; `investigate` command 2328-2401 | smallest separate CLI; requires saved scan and matching latest accession |
| `prompts/filing_search_plan.md` | v1, 14 lines | bounded literal retrieval plan, no answer/cause output |
| `prompts/financial_investigation.md` | v4, 45 lines | exact spans for structured quantities; all model narrative numeric-free |
| `tests/test_filing_investigation.py` | 847 lines; 28 focused tests reported | bounds, provenance, signs, downgrade, no-plug, isolation, CLI |

## User acceptance mapping

| Acceptance | Final-state evidence / status |
|---|---|
| Exact filing excerpts + provenance; cause claims cited | R3 packet has E1-E6 with SEC URLs, accession, section locators, source lines/offsets, exact excerpts (`data/live-finding-proof-r3/MSFT/03_output/evidence/finding_01_20260827T144012022055Z.md:1-63`). Final code requires refs for every driver/interpretation/remainder/explanation. Final R4 live proof absent. |
| Quantified and unquantified drivers; ambiguity preserved | R4 validator clears amount/unit/period/span together on unsupported claims; valid structured claims require one local amount/year/sign span. R3 live OpenAI `respectively` disclosure is conservatively unquantified (`...r3...json:136-183`). |
| Observed vs disclosed vs interpretation vs unresolved | R3 JSON keeps separate `observed_movement`, `disclosed_explanation`, `interpretation`, `unresolved_remainder`, and `reconciliation` fields (`...r3...json:194-372`). |
| Python-only arithmetic; no balancing plug | `reconcile_disclosed_amounts` is the only residual calculator; `_movement_reconciliation` refuses multi-line/multi-period ambiguity. R3 shows `not_computable`, null residual, `difference_is_reported_plug=false` (`...r3...json:353-363`). R4 narrative is numeric-free. |
| Inspectable JSON + coherent CLI | `investigate_finding` writes `03_output/analysis/filing_investigation_*.json` and `03_output/evidence/finding_*.md`; `main.investigate` is isolated from adjustment flow and has a focused isolation test. |
| No scan/lifecycle/normalization/materiality/identity/review/adjustment changes | Baseline diff adds only the scan alias, investigation module/prompts/tests, and separate CLI imports/command. No adjustment/history source or output was added. |
| Normal tests do not call live LLM | Injected-client tests; R4 reports 28 focused and 182 full tests, all passing. |
| Current real MSFT proof and post-proof review | **BLOCKED for final R4 state.** R3 was successful but generated with `financial-investigation-v3`; R4 changed prompt/validation to v4 and could not retrieve SEC data. |

## Verification snapshot

- R4 bounded adversarial selection: **3 passed, 25 deselected** (`reports/repair-4.md:25-29`).
- R4 focused `tests/test_filing_investigation.py -q`: **28 passed**; full suite: **182 passed, 45 subtests passed** (`reports/repair-4.md:27-30`).
- R4 Ruff check + format check, temporary-prefix `py_compile`, and `git diff --check`: **passed** (`reports/repair-4.md:30-34`).
- R4 live attempt: copied scan/P&L under `data/live-finding-proof-r4`, then EdgarTools SEC socket access failed with `WinError 10013`; only the scan and P&L are present, no investigation/evidence artifact.
- Latest successful R3 artifact: `data/live-finding-proof-r3/MSFT/03_output/analysis/filing_investigation_01_20260827T144012022055Z.json`; status `completed`, accession `0001193125-26-323660`, 3 queries/0 rejected, 6 evidence items, 2 unquantified drivers, 5 observed lines, reconciliation `not_computable`, null residual, no plug.
- Latest successful R3 evidence preview: E1 line 23 gives the exact OpenAI `respectively` disclosure; E4 line 47 includes FY2024 as well. This explains why structured quantities were downgraded, not silently mapped.

G0 did not rerun broad tests or alter source/tests/config/live data. Current status includes modified tracked files `analytical_scan.py`, `main.py`, and untracked final implementation/prompts/tests/run artifacts; `.pytest_cache` permission warning is pre-existing/environmental.

## Prior findings: resolved vs stale

- A1 (`reports/adversary.md`) six findings—model residual, arbitrary movement selection, free-form periods/units, unbounded plan queries, uncited explanation, duplicate aliases—were addressed through R1/R2 and remain represented by the final validator/bridge/query/ref code.
- A2 (`reports/final-financial-review.md`) amount-period-sign association and free-text residual bypass were only partially addressed by R2; its findings are superseded by R3 local semantic checks and R4 numeric-free narrative enforcement.
- A3/R3 (`reports/final-financial-review-2.md`) unrelated-year/sign and token/spelled-number bypasses were repaired in R3; A4 then found broader lexical arithmetic/residual bypass plus rejected-span leakage.
- A4/R4 (`reports/final-financial-review-3.md`) is addressed in final code: all four model-authored narrative fields are numeric-free, and invalid/unquantified driver metadata is atomically cleared. R4 records no new financial/lifecycle/provenance issue (`reports/repair-4.md:43-51`).
- The historical DO NOT MERGE verdicts remain valid records for their respective code states, but are stale as direct findings against current R4 source. They do not establish final R4 live behavior.

## R3 evidence versus R4 code

R4 preserves the R3 raw filing packet, exact SEC provenance, accession, and deterministic five-line observed movement as historical evidence. It also preserves the finding's conservative ambiguity: R3 has two unquantified OpenAI drivers and no residual plug. However, R3 is **not final-state product proof**: its JSON metadata says `financial-investigation-v3` (`...r3...json:125-133`), while current code constant/prompt is v4. R3 narrative descriptions and interpretation/explanation contain fiscal-year digits (`...r3...json:138-183`, `194-235`), which current `_validate_free_text_claims` rejects as numeric-free. Replaying that model result through final validation would fail; no R4 investigation JSON exists. Therefore: packet/observed evidence preserved; R3 structured result/narrative logically invalidated as proof of R4 behavior.

## Exact bounded parent checks

Run only these bounded checks on the unchanged final tree (no broad-suite rerun required for G0):

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
& 'C:\Users\patri\miniconda3\envs\ai-fund\python.exe' -m pytest tests/test_filing_investigation.py -q
& 'C:\Users\patri\miniconda3\Scripts\ruff.exe' check src/smrik_fund/ingestion/filing_investigation.py src/smrik_fund/ingestion/analytical_scan.py src/smrik_fund/main.py tests/test_filing_investigation.py
& 'C:\Users\patri\miniconda3\Scripts\ruff.exe' format --check src/smrik_fund/ingestion/filing_investigation.py src/smrik_fund/ingestion/analytical_scan.py src/smrik_fund/main.py tests/test_filing_investigation.py
git diff --check 46ca750
git status --short
git diff --stat 46ca750
```

Pure artifact checks: confirm latest R3 fields above; confirm R4 contains no `filing_investigation_*.json`, `finding_*.md`, `adjustment_history.csv`, or `adjusted_pnl.csv`; inspect the current module's `validate_financial_investigation`, `_validate_free_text_claims`, `_movement_reconciliation`, and CLI regions listed above.

If SEC socket access is restored, the discoverable fresh final-state command is:

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
& 'C:\Users\patri\miniconda3\envs\ai-fund\python.exe' -c 'from smrik_fund.main import app; app()' investigate MSFT --scan-file data/live-finding-proof-r4/MSFT/03_output/analysis/analytical_scan_20260827T131624327070Z.json --output-root data/live-finding-proof-r4
```

Expected fresh output: new R4 investigation JSON + exact evidence packet, final metadata prompt `financial-investigation-v4`, accession `0001193125-26-323660`, narrative fields without digits/number words, and deterministic reconciliation outcome recorded. Do not treat a socket-blocked or failed artifact as proof.

## Production diff and residual scope

Final production addition is **1,546 lines**: new `filing_investigation.py` 1,450 + `main.py` 91 + `analytical_scan.py` 5. New test file is 847 lines; prompts are 59 lines. This exceeds the AGENTS.md “about 200 new production lines” scope-warning threshold, although the implementation uses one bounded module and no new framework. Parent should explicitly decide whether this size is justified by the acceptance criteria; no unrelated cleanup was attempted.

The AGENTS.md-referenced `docs/ai_fund_v1_section_1.md` and `docs/ai_fund_v1_section_2.md` are absent from this checkout, so that source-of-truth cross-check could not be independently refreshed. No docs were created or changed.

## Control Block

- Decision: **DO NOT MERGE / gate not approved**.
- Blocking: no successful real MSFT proof after R4 v4 validation/prompt changes.
- R4 SEC retrieval failed before investigation: `WinError 10013` socket denial.
- R3 packet/provenance/observed movement preserved, but R3 narrative is v3 and not final proof.
- R4 terminal checks: 3 adversarial; 28 focused; 182 full + 45 subtests; Ruff/compile/diff-check pass.
- No current source-level financial or lifecycle defect found in R4 reports.
- Residual scope warning: 1,546 new production lines versus AGENTS.md ~200-line guidance.
- Parent: run bounded checks, then rerun exact fresh command only with SEC access restored.
