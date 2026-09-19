# Iterative financial analysis: review and implementation plan

**2026-09-05 · Proposed design; implementation awaits feedback.**

Purpose: review `GOAL_HANDOUT.md` and plan the deeper financial-modeling workflow Patrik described: structured financial data, context from filing notes, iterative reasoning, and the depth of a substantial Excel model. Scope reviewed: the current dirty checkout and saved MSFT/GOOGL outputs. Financial examples below describe local artifacts; no new SEC download or live model run was performed.

## My assessment

The missing capability is **iterative model construction**. The current product can find a conspicuous movement, retrieve a packet, propose items to remove, and rebuild a P&L. Your intended analyst must also decide what it still needs to understand, follow a disclosure into another note, add useful recurring detail, and reassess the model after learning something.

Use a **financial-modeling question** as the unit of work. Examples: What explains this margin change? Which disclosed components belong under this expense? Does this amount describe a whole category or just one event? What remains unclear after the adjustment?

The financial model can become detailed while its Python implementation stays direct. Reuse EdgarTools, DataFrames, existing history and calculation functions. A stronger prompt alone cannot supply a missing feedback loop or durable workbook operations.

## What the review found

| Finding | Evidence and implication |
|---|---|
| The Analyst is constrained to normalization candidates. | [Prompt and result schema](../src/smrik_fund/ingestion/adjustment_analysis.py), `ANALYST_PROMPT`, `AnalystCandidate`, `AnalystResult`. There is no supported path for a newly discovered recurring note component to become a durable model detail without normalization. |
| Research is a single retrieval before analysis. | [Main orchestration](../src/smrik_fund/main.py), `_queries_from_finding` and `_run_adjustment_analysis`. Query selection depends on punctuation/line-label fallback; `research_request` does not drive another evidence turn on `run`. The Analyst receives reported-only context rather than the evolving workbook. |
| `revise` can apply the original, disputed proposal. | `_run_adjustment_analysis` derives the original candidate's delta and allows `accept` or `revise` through a shortcut. Reviewer corrections, target/period judgments and other gate facts are not required by that shortcut. |
| The saved MSFT result exposes that defect. | [Saved run](../data/e2e-live-apply2-20260904/MSFT/03_output/analysis/adjustment_run_20260903T231155670849Z.json): the Reviewer explicitly leaves the dilution-only amount unresolved, yet the original $6.5B proposal is approved/applied. The disclosed aggregate OpenAI investment gain and its dilution-only component require distinct identities and claims. |
| A displayed child has ambiguous meaning. | [Line-detail construction](../src/smrik_fund/ingestion/line_details.py), `build_line_details`, `_child_rows_by_parent`. Saved FY26 Other income shows an adjusted $4,197M parent followed by a removed +$6,500M child. This is a normalization bridge, not the adjusted parent's composition. |
| Completion evidence is too narrow. | MSFT saved adjusted reconciliation is 12/12 PASS; saved GOOGL has 6 PASS / 6 SKIPPED and no invented Gross Profit. GOOGL predates current auto-application. These establish particular arithmetic/source-shape behavior, not complete analysis or correct financial judgment. |

## The intended loop

```text
Inspect the current workbook and open questions
  → choose the next financially useful question
  → search the filing / read or expand the relevant note
  → interpret the evidence against the current model
  → propose detail, normalization, explanation, or a remaining gap
  → review the proposal; Python validates and rebuilds applicable changes
  → inspect the updated workbook and decide what to investigate next
```

The initial common-size/YoY scan seeds attention. The Analyst may introduce a material driver or disclosure question even when no ratio is an outlier. It should prioritize questions relevant to the analysis objective; reading every note mechanically is unnecessary.

Each turn receives a compact current model slice: reported and adjusted values, existing detail, effective adjustments, source periods, previous decisions, relevant evidence and checks. It can request a different slice. This avoids repeated reasoning from stale reported data and repeated removal of an already handled item.

Recommended initial analysis brief: **Explain historical performance, expose material disclosed components, and present supported analytical adjustments with their rationale and cross-period treatment. Preserve open questions. Forecasting follows the historical model.** Save this brief with the run. Any exclusion of recurring non-operating results must be an explicit, consistently applied judgment; the phrase “non-recurring” alone does not authorize it.

## Small contracts the loop needs

### Research and progress

- Keep the analytical question separate from `research_queries`: at most three literal phrases chosen by the Analyst. Python executes searches and returns source text; it does not compose issuer recipes.
- Allow expansion of a previously returned evidence locator into relevant note context, including adjacent tables, headings, units and period columns. Reuse EdgarTools and the existing text/offset machinery in [filing.py](../src/smrik_fund/ingestion/filing.py). Verify the installed EdgarTools read surface during implementation before adding any local fallback. Matching a P&L table stub is insufficient support for a normalization.
- Preserve immutable packet references with evidence IDs. `E1` from two different packets must remain distinguishable. Preserve exact source spans and filing identity; do not treat generated reasoning as a disclosed fact.
- Outcomes per question: **add reported detail**, **normalize**, **explained/no change**, or **unresolved**. A research request continues that question. A no-change conclusion is useful progress and does not end other queued questions.
- Stop normally when no material queued question remains under the stated scope. Repeated requests with no new evidence stop that inquiry. Exhausted evidence closes it as unresolved. A failed applicable accounting check blocks edits to the affected model scope.
- Use explicit retrieval/turn budgets. The pilot budget must permit an initial search, an evidence-directed follow-up, a decision and current-model reinspection. Count the optional reviewer correction/re-check explicitly. Budget exhaustion means **incomplete**, with remaining questions shown; an unchanged number is not a stopping rule.

### Final proposals and deterministic accounting

Reviewer `accept` means automatic application of the **final supported proposal**, subject to applicable deterministic checks. `revise` causes at most one corrected Analyst proposal and one Reviewer re-check; preserve both versions. A suggested amount alone does not approve an otherwise disputed target or economic identity. Unsupported revisions remain unresolved; rejects stay off the model.

Before any approved history row is persisted, validate the proposed state in memory: exact target and filing/period identity, finite supported amount, derivable signed effect, valid evidence references, final Reviewer agreement, no competing overlap/double count, valid application, and applicable subtotal reconciliation. Use existing `derive_line_delta`, `resolve_current_adjustments`, `apply_adjustments`, and `reconcile_pnl`. Trial validation failure leaves approved history and current outputs unchanged.

Separate invalid accounting from policy diagnostics. Materiality, judgment labels, recurrence, crossing zero, and an amount larger than a signed net line are not interchangeable with an invalid target or duplicate booking. Preserve these signals and require an evidence-backed judgment under the analysis brief. Do not blanket-approve through them or restore a human click solely because an item is large. The exact application-policy change needs explicit approval with this implementation scope; retain legacy command behavior until its consolidation is separately approved.

Reconciliation demonstrates arithmetic consistency for relationships actually tested. Show SKIPPED/unknown coverage. It cannot certify the economic case, note completeness, or correct attribution of an aggregate amount.

### Durable workbook detail

Keep these distinct:

| Representation | Meaning | Effect on parent |
|---|---|---|
| Reported parent | Source statement value, unchanged | Base value |
| Reported detail | Disclosed component, segment or note item | No normalization delta |
| Normalization bridge item | Supported adjustment to a reported item | Signed delta once |
| Adjusted parent | Reported parent plus approved deltas | Used in adjusted subtotals |
| Unallocated reported amount, when meaningful | Explicit difference within one compatible breakdown | Coverage diagnostic; no plug or assumed forecast driver |

Use existing `row_type`, `breakdown_group`, `amount`, `line_delta`, `adjusted_value` and provenance fields where they fit. Children remain excluded from subtotal calculations. Keep alternative breakdowns such as geography and product in separate groups; do not sum overlapping disclosures as independent costs. Show a remaining amount only when parent/detail scope, units and periods support that arithmetic.

`line_details.csv` is regenerated today from segments and adjustments, so it cannot itself be the durable input for newly learned note detail. Add one small **`reported_details.csv`** input; reuse existing detail fields plus filing/source identity as needed. Resolve rows by filing, parent, source period, breakdown group and detail identity, never display label alone. Reject ambiguous/conflicting replacements; repeated identical evidence is idempotent. Preserve prior source artifacts and record accepted detail references in the existing run manifest. Both rebuild paths must consume the same input. Do not encode descriptive facts as zero-delta normalization-history entries.

The workbook view should expose reported → signed bridge → adjusted values across years, separately from reported composition. Retain tax/share-count caveats: a pre-tax adjustment with unchanged reported taxes is not proof of a fully normalized after-tax earnings or EPS measure.

## Implementation order with Luna

Parent owns contracts and reviews the workbook at each milestone. Use one Luna `xhigh` owner per packet, serially where files overlap. Additional independent review is reserved for a named financial correctness risk. No framework-wide rewrite.

| Packet | Concrete delivery | Planned edits / reuse | Acceptance |
|---|---|---|---|
| 1. Final-proposal application | Correct revise/re-check; validate before approved-history persistence. | Edit `main.py`, `adjustment_analysis.py` only as needed for revised input, and focused adjustment-analysis tests. Reuse Reviewer result, adjustment engine and reconciliation. Any necessary Reviewer change triggers a scoped re-estimate. | Unsupported dilution-only revision leaves no approved row; a corrected, supported aggregate proposal applies once. Failed trial leaves history/output unchanged. |
| 2. Evidence-directed iteration | Analyst chooses literal queries and note expansion; reads current model; records no-change/gaps and progress-aware stopping. | Edit `main.py`, `adjustment_analysis.py`, focused analysis tests. If `filing.py` and filing tests need context-expansion work, first isolate that as its own bounded retrieval packet. Reuse existing scan/retrieval and manifest artifacts. | Second evidence request depends on the first result; a supported edit rebuilds; next turn sees adjusted state. A no-change result allows another question. Budget exhaustion is incomplete. |
| 3. Useful detail that survives | Persist a disclosed recurring note component and rebuild it without changing earnings. | Edit `line_details.py`, both rebuild call sites in `main.py`, and `test_line_details.py`; extend the Analyst external outcome boundary only where needed. One `reported_details.csv` input. | Parent unchanged, detail traceable, no subtotal double count; survives rebuild/rerun; incompatible filing/period rejected; overlapping groups stay separate. |
| 4. First integrated product gate | One historical inquiry demonstrates iterative research and useful workbook construction; transfer check on GOOGL. | Extend existing golden/analysis tests and use isolated output directories for later approved live runs. Reuse harness; do not build another one. | MSFT aggregate/component distinction, a recurring detail, a valid no-change and an unresolved case. GOOGL preserves its actual statement shape. Inspect actual workbook/evidence, not only CLI/test status. |
| 5. Readable Excel surface | Export the proven model and reasoning so a person can inspect it as a workbook. | Separate scoped exporter after the model contract is useful. | Reported, adjusted/bridge, detail, questions/decisions, evidence and checks agree with Python outputs. Explicit missing values, periods, units and unresolved gaps. |

Each packet should usually fit roughly 2–4 changed production/test files. Before a packet exceeds four files or about 200 new production lines, split by the actual contract dependency. These are scope limits to evaluate, not a verified LOC estimate. Packets 1–2 are the recommended first implementation authorization; they prove the feedback loop. Packets 3–4 complete the first useful enriched historical-workbook milestone. Do not claim that milestone after fixing approval alone.

Verification ownership: the implementing Luna writes focused behavioral tests, runs them and Ruff on changed code, then exercises the relevant real MSFT path when applicable and authorized. The integrated gate owns cross-ticker/live verification once. Parent inspects a representative final workbook and adverse case; no repeated broad suites without a new failure or changed state.

### Representative acceptance preview

All monetary figures here are **USD millions**, describing the saved MSFT FY2026 case or the proposed corrected behavior. Future tests must preserve exact source fiscal labels.

| Inquiry/outcome | Expected model result |
|---|---|
| FY26 OpenAI aggregate net gain, accurately identified and accepted under the brief | Other income: reported **10,697** + approved delta **−6,500** = adjusted **4,197**; reported composition and removal shown separately. |
| Dilution-only amount remains undisclosed | Unresolved component; no invented component amount and no booked delta for that identity. |
| Recurring note component supports useful breakdown | Add its disclosed amount as reported detail; parent and earnings unchanged; detail survives rebuild. |
| Growth/mix explains movement | Explanation/no change; do not subtract the YoY movement. Continue other useful questions. |
| FX percentage lacks a supported monetary bridge | Preserve the percentage/context and missing absolute amount; no normalization booking. |

## Path to the broader financial model

After the first enriched historical workbook proves useful:

1. Deepen material revenue/cost/segment histories and supporting note schedules, retaining comparable source periods and disclosed scope changes.
2. Add balance-sheet/cash-flow context and linked historical schedules. Quantify what reconciles and what remains missing before promising a complete three-statement model.
3. Let the Analyst propose forecast drivers and scenarios with evidence, assumptions and sensitivities. Python calculates their consequences from the historical model.
4. Add valuation using the explicitly defined forecast/cash-flow model. Present sensitivity and unresolved assumptions alongside the result.

These are separately scoped extensions. The intended depth comes from financial questions, schedules and explicit assumptions. Excel is the review/export surface; Python remains the calculation authority. Direct bidirectional Excel editing is a separate product decision.

## Changes I recommend to the handout

- State the iterative analyst/model objective at the top and show the feedback loop.
- Present the outlier scan as a starting point, with analyst-selected follow-up questions.
- Give reported detail, supported normalization, explanation and unresolved gaps equal legitimacy as outcomes.
- Replace blanket `accept/revise` application with automatic application of the final accepted, supported proposal.
- Replace “a session must change the workbook or reject a bad proposal” with evidence-backed progress on a material question. This avoids rewarding unnecessary adjustments.
- Define historical-workbook completeness, analytical gaps and budget exhaustion separately from reconciliation PASS.
- Keep current implementation/status evidence separate from the target product and broader roadmap.

The original handout and V1 status were left unchanged for review. Implementation beyond existing recorded extensions requires explicit approval under AGENTS.md; this document supplies the concrete scope to consider.

## Review evidence and limits

I inspected the handout, governing spec/status, relevant current functions and saved outputs before launching Luna. Three independent Luna `xhigh` proposals were followed by Luna `max` synthesis and Luna `xhigh` simplicity/integrity review. My final plan incorporates corrections to detail persistence, query semantics, stopping, policy/mechanics separation and packet sizes; it supersedes conflicting recommendations in the working reports.

- [Independent parent assessment](../Lunacy/runs/goal-handout-review-20260905/PARENT_ASSESSMENT.md)
- [P1: analyst workflow](../Lunacy/runs/goal-handout-review-20260905/proposals/P1.md), [P2: pipeline contracts](../Lunacy/runs/goal-handout-review-20260905/proposals/P2.md), [P3: workbook semantics](../Lunacy/runs/goal-handout-review-20260905/proposals/P3.md)
- [Synthesis](../Lunacy/runs/goal-handout-review-20260905/SYNTHESIS.md), [simplicity/integrity review](../Lunacy/runs/goal-handout-review-20260905/SIMPLICITY_REVIEW.md)
- [Verification record](../Lunacy/runs/goal-handout-review-20260905/evidence/VERIFICATION.md), [test log](../Lunacy/runs/goal-handout-review-20260905/evidence/pytest-focused.log)

Executed: `.venv/Scripts/python.exe -m pytest tests/test_msft_golden_run.py tests/test_line_details.py tests/test_filing.py -q -p no:cacheprovider --basetemp Lunacy/runs/goal-handout-review-20260905/evidence/pytest-temp` — **14 passed in 5.00s**. These existing tests prove their current assertions; no new behavior has been implemented or tested. No Ruff run was needed because no Python code changed. No live calls, source/test/config/financial-data edits, commits or pushes were made.
