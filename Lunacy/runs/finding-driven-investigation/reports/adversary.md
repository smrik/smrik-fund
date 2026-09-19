# Finding-driven filing investigation — adversary review

Verdict: **DO NOT MERGE**

Scope: read-only review of the Phase 2 final diff, implementation report, and the persisted MSFT scan/investigation/evidence packet. No source, test, config, or live artifact edits.

## Findings

### P1 — LLM-owned residual bypasses Python arithmetic

`src/smrik_fund/ingestion/filing_investigation.py:232-247` exposes `unresolved_remainder_amount`/`unresolved_remainder_unit` as model output. `run_financial_investigation()` only validates evidence IDs (`:438-460`, call at `:552`); `_movement_reconciliation()` computes a separate result (`:755-771`) but never verifies or replaces the model amount. The live artifact has a model-generated `4.298 usd_billions` residual and prose arithmetic at `data/live-finding-proof/MSFT/03_output/analysis/filing_investigation_01_20260827T124944739624Z.json:164-171`, while its deterministic reconciliation is `not_computable` with null observed/known/residual fields at `:280-290` (multi-line finding and dollar-vs-billion units). A bad LLM residual would be persisted identically. This violates Python-only arithmetic and the no-plug boundary. Remove/null the model residual, and emit a residual only from a Python-validated period/unit bridge; otherwise retain `not_computable`.

### P1 — Reconciliation selects an arbitrary movement period and disables the actual rank-1 bridge

`_movement_reconciliation()` takes `movement[0]` (`:762-770`) without a period selected by the finding; it returns no observed amount for every multi-line finding (`:760-761`). `build_observed_movement()` can expose multiple FY deltas (`:400-435`), but no code ties the selected delta to the finding's observation. Thus an FY24-to-FY26 finding can be reconciled against FY26-to-FY25, while the live rank-1 finding's three affected lines force deterministic reconciliation to `not_computable`; the narrative then supplies its own 15.598-versus-11.3 arithmetic. Require an explicit line/period mapping or do not reconcile.

### P1 — Disclosed-driver periods are free-form and not checked against supplied periods

`DisclosedDriver.period` is only stripped (`:174-199`); `validate_financial_investigation()` checks packet IDs but never checks the period, amount unit, or amount against the supplied observed FY labels/filing (`:438-460`). A model can cite valid E1 evidence while returning an invented period (for example `FY2027`) or an unsupported unit and the artifact accepts it. The live periods happen to be exact (`...json:134-151`), but this is not enforced. Pass allowed periods/units into validation and fail closed (or preserve null/unknown) when the packet does not establish them.

### P2 — Search-plan queries are not bounded to the supplied filing passages

`FindingSearchPlan` bounds only count, length, and duplicate strings (`:129-157`); `run_search_plan()` does not require each query to be a literal occurrence in `_bounded_context()` (`:344-390`). The prompt says to use only bounded passages and permits empty queries when no safe phrase exists (`prompts/filing_search_plan.md:3-13`), yet an arbitrary model query still reaches full-filing retrieval. Enforce literal membership in the bounded passages (or return `no_queries`) to keep the search contract closed.

### P2 — Free-text explanation has no citation validation

`FinancialInvestigationResult.explanation` is unconstrained by evidence refs (`:235`), and `validate_financial_investigation()` validates only driver, interpretation, and unresolved-remainder refs (`:446-457`). A model can append an unsupported company-specific cause or amount to `explanation` while every structured field passes. The live prose includes `[E1, E3, E4]` (`...json:171`), but that is not machine-checked. Add explanation refs or generate the explanation from validated fields.

### P2 — Removable API alias clutter conflicts with smallest V1

The new module adds unused duplicate aliases for the error, plan, result, run, and loader names (`:77`, `:160-161`, `:264-265`, `:774-776`, `:876`), while repository callers use the canonical names. Unless a documented external contract requires each alias, remove them; they create several names for one mechanism and enlarge the maintenance surface.

## Control Block

Verdict: **DO NOT MERGE**
Blocking: P1 residual ownership; P1 period/movement attribution; P1 source-period validation.
Read-only boundary held; no source/tests/config/live artifacts changed.
Implementer checks are recorded in `reports/implementation.md`; no broad suites rerun here.
Live evidence reviewed: `data/live-finding-proof/MSFT/03_output/analysis/filing_investigation_01_20260827T124944739624Z.json` and its packet.
Required repair: Python-only residual, explicit period bridge, fail-closed period/unit claims.
Report: `Lunacy/runs/finding-driven-investigation/reports/adversary.md`
