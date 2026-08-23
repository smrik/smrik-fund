# T1 — existing manifest audit

Read-only audit; no pipeline/tests run and no source/canonical files changed.

## Scope/evidence

- Manifest: `data/MSFT/03_output/analysis/adjustment_run_20260822T145101565886Z.json`
- Manifest has 8 candidates; `reported_reconciliation` and `adjusted_reconciliation` are each 12 PASS / 0 FAIL / 0 SKIPPED; `reported_equals_adjusted=true`.
- Related files inspected only because manifest references them: `data/MSFT/03_output/adjustment_history.csv` and `data/MSFT/03_output/analytical_pnl.csv`.
- Local history has 23 rows, all `version=1`, `status=proposed`; it lacks both `candidate_identity` and `candidate_state` columns. No manifest candidate has a linked ID/version.

## Candidate output

The identity column below is the manifest's stored `candidate_identity`, parsed as JSON. `null / absent` means the manifest has no identity or version field.

| # | Topic / period / target | `item_key` | Economic identity | Parsed `target_row_key` | `identity_status` | ID / version | Final / application |
|---:|---|---|---|---|---|---|---|
| 1 | OpenAI recapitalization gain / 2026-06-30 (FY) / Other income (expense), net | `openai-recapitalization-dilution-gain` | `{"company":"MSFT","fiscal_period":"2026-06-30 (FY)","identity_version":"economic-adjustment-v2","item_key":"openai-recapitalization-dilution-gain","target_row_key":"label:Other income (expense), net"}` | `label:Other income (expense), net` | `identity_unresolved` | null / absent | `human_review` / `not_applied` |
| 2 | XBOX impairment expenses / 2026-06-30 (FY) / Research and development | `xbox-impairment-related-expenses` | `{"company":"MSFT","fiscal_period":"2026-06-30 (FY)","identity_version":"economic-adjustment-v2","item_key":"xbox-impairment-related-expenses","target_row_key":"label:Research and development"}` | `label:Research and development` | `identity_unresolved` | null / absent | `human_review` / `not_applied` |
| 3 | XBOX impairment expenses / 2026-06-30 (FY) / Operating income | `xbox-impairment-related-expenses` | `null` | none | `identity_unresolved` | null / absent | `human_review` / `not_applied` |
| 4 | AI infrastructure investments / 2026-06-30 (FY) / Research and development | `ai-infrastructure-investments` | `{"company":"MSFT","fiscal_period":"2026-06-30 (FY)","identity_version":"economic-adjustment-v2","item_key":"ai-infrastructure-investments","target_row_key":"label:Research and development"}` | `label:Research and development` | `identity_unresolved` | null / absent | `human_review` / `not_applied` |
| 5 | Legal costs and divestiture gains / 2026-06-30 (FY) / General and administrative | `legal-expenses-divestiture-gains` | `{"company":"MSFT","fiscal_period":"2026-06-30 (FY)","identity_version":"economic-adjustment-v2","item_key":"legal-expenses-divestiture-gains","target_row_key":"label:General and administrative"}` | `label:General and administrative` | `identity_unresolved` | null / absent | `human_review` / `not_applied` |
| 6 | Uncertain tax-position interest / 2026-06-30 (FY) / Provision for income taxes | `uncertain-tax-position-interest` | `{"company":"MSFT","fiscal_period":"2026-06-30 (FY)","identity_version":"economic-adjustment-v2","item_key":"uncertain-tax-position-interest","target_row_key":"label:Provision for income taxes"}` | `label:Provision for income taxes` | `identity_unresolved` | null / absent | `human_review` / `not_applied` |
| 7 | Uncertain tax-position interest / 2025-06-30 (FY) / Provision for income taxes | `uncertain-tax-position-interest` | `{"company":"MSFT","fiscal_period":"2025-06-30 (FY)","identity_version":"economic-adjustment-v2","item_key":"uncertain-tax-position-interest","target_row_key":"label:Provision for income taxes"}` | `label:Provision for income taxes` | `identity_unresolved` | null / absent | `human_review` / `not_applied` |
| 8 | Uncertain tax-position interest / 2024-06-30 (FY) / Provision for income taxes | `uncertain-tax-position-interest` | `{"company":"MSFT","fiscal_period":"2024-06-30 (FY)","identity_version":"economic-adjustment-v2","item_key":"uncertain-tax-position-interest","target_row_key":"label:Provision for income taxes"}` | `label:Provision for income taxes` | `identity_unresolved` | null / absent | `human_review` / `not_applied` |

## Required answers

### Identity-unresolved rows

Yes: all 8 rows are `identity_unresolved`.

- Rows 1, 2, 4–8: the manifest error is `history contains legacy or corrupted identity data`. The directly referenced history is the old schema: no `candidate_identity` or `candidate_state`, so the current resolver fails closed. This is the exact gap; it is not evidence that the item keys are invalid.
- Row 3: the manifest error is `candidate target line is missing, ambiguous, or derived`; `Operating income` is the derived `OperatingIncomeLoss` subtotal. No identity is emitted.

### UTP `possible_duplicate`

For all three UTP rows, the manifest gate has `conditions.possible_duplicate=null` and includes `possible_duplicate_or_unknown`. It does **not** say `possible_duplicate=true`.

The current gate sets `possible_duplicate=False` only for `replay`, `blocked_existing`, `state_conflict`, or `new`; any other identity status, including `identity_unresolved`, becomes `None` (`src/smrik_fund/main.py`, `_gate_conditions`). The history-schema failure above produced `identity_unresolved`, which mechanically produced the unknown duplicate condition. Other recorded UTP inputs are `reconciliation_clear=true`, `group_reconciles=true`, `aggregate_over_adjustment=false`, `source_target_available=true`, `individual_over_adjustment=false`, `zero_target_with_line_delta=false`, and `deterministic_checks_pass=true`; `materiality_eligible` is also null. Therefore this is a fail-closed identity-state consequence, not a duplicate match.

### OpenAI FY26/FY25/FY24

The FY26 key `openai-recapitalization-dilution-gain` is a specific, evidence-grounded subject/event slug and is economically sensible. This manifest emits no OpenAI FY25 or FY24 candidate, so it provides no FY25/FY24 keys and no cross-period distinctness proof. By construction, the same valid key would still be a different identity when fiscal period differs; that is an implementation inference, not observed output here. The FY26 candidate remains human review because the reviewer says the disclosed amount is aggregate OpenAI investment gain, not separately quantified recapitalization dilution gain.

### Xbox R&D vs Operating income

The manifest produces one valid identity for R&D (`target_row_key=label:Research and development`) and no identity for Operating income. Thus it does **not** create two identities. Structurally this is expected: the P&L has Operating income as a derived subtotal, and the implementation rejects derived targets and recalculates subtotals from source lines. Financially, treating the same Xbox impairment as both an R&D source-line adjustment and an Operating-income adjustment would risk double counting. The unresolved Operating-income row is therefore a deliberate fail-closed target rejection, not a second accepted event.

### Forbidden provenance in identity JSON

No non-null identity JSON contains accession, evidence IDs/anchors/sections/locators/offsets, query, packet path, run/model/prompt, reason/uncertainty/topic/reviewer/origin, amount/direction/basis, `sub_item`, or prose. Each non-null identity contains only `company`, `fiscal_period`, `target_row_key`, `item_key`, and `identity_version`. Those provenance/observation fields do appear elsewhere in the manifest (candidate, review, and review metadata), but not in the economic identity.

## Exact remaining gaps

1. Canonical history is still legacy and cannot resolve any current economic identity; therefore no ID allocation, version path, or application is observable in this manifest.
2. The Operating-income Xbox candidate is rejected before identity construction because it targets a derived subtotal.
3. This single manifest cannot establish OpenAI FY25/FY24 key output or cross-period convergence.
4. UTP's duplicate reason is an unknown safety flag caused by unresolved identity, not a detected duplicate.
