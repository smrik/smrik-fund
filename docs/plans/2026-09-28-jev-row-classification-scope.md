# Jev row classification for `portable_model` — scope

**Status:** PROPOSED, not approved. This package is outside the current checklist in `docs/V1_STATUS.md`, so it needs Patrik's explicit written approval before any implementation.
**Date:** 2026-09-28
**Question this package answers:** Can Jev reliably do the component identification that `portable_model` currently does with fixed concept lists? The answer must be measured on a labelled set before anything is wired in.

---

## 1. Evidence from a 22-case probe

**How the probe was run.**
- Fresh cases were frozen with `freeze_company(ticker, "2026-09-16", …)` in a sandbox. Nothing came from the local `data/` folder.
- `prepare_model` was run on each case.
- Every balance-sheet face row was placed exactly the way `portable_model` places it: named concept lists first, then parent-minus-component residual groups.
- To reproduce it, run `probe_row_placement.py` (attached) against any folder of frozen cases.

**Outcome.** 9 of 22 cases pass. The 13 failures split into three kinds:

| Failure kind | Cases | Can Jev address it? |
|---|---|---|
| Row identification: the fact is presented, but under a concept the lists don't contain, or twice | CAT (only total equity including NCI), F (`ProfitLoss` / net income available to common), MSFT (`msft_DepreciationAmortizationAndOther`), PFE (rows labelled "Revenues" and "Total revenues" both match), TGT (cash tagged `CashCashEquivalentsAndShortTermInvestments`), UPS (`DepreciationAndAmortization`) | **Yes (6)** |
| Method gap | NKE and XOM (no operating-income line); DE (unclassified balance sheet, financial services) | No (3) |
| Reconciliation or note logic | GIS and KO (tax bridge); HD and MDT (finance-lease split) | No (4) |

**Silent misplacement in a passing case.**
- NVDA reports `nvda_NonMarketableSecurities` of USD51,157m.
- It falls into *remaining noncurrent assets*, which are held flat, while `long_investments = 0`. The equity bridge therefore omits it.
- AMZN's note path (`company_notes.note_claims`) moves the same kind of asset into the investment bridge. The treatment is inconsistent across tickers, and nothing fails.

**Size of the population.**
- 306 *leaf* residual balance-sheet rows, covering 79 distinct concepts and 177 distinct concept+label pairs.
- 14 rows use extension tags. None of the 14 has an edgartools `standard_concept`.
- A keyword screen finds about 62 claim-like rows. 29 of them are operating-lease rows, which are operating under current policy. That leaves roughly 25–30 rows in the classes that actually matter.

**What this means.** The main risk is not the `ValueError`s. It is rows that land silently in revenue-scaled or held-flat residuals when they are really claims. Most of those are us-gaap rows that edgartools already labels. Jev's marginal value is concentrated in extension tags and in rows whose label and tag disagree.

## 2. Objective

Measure two things on a labelled holdout set. This package ends in a go/no-go decision and does **not** change the model.

- **Q1 — Row nature.** For each residual leaf balance-sheet row, can Jev assign its economic nature from a closed set, with usable confidence, and beat free baselines?
- **Q2 — Slot identification.** When a required named concept is missing or matches twice, can Jev pick the correct face row, and answer `not_presented` when no such row exists?

## 3. Non-goals

- No change to `prepare_model` outputs, evidence, allocations or valuation.
- No automatic application of any Jev proposal.
- No fixes for method gaps (NKE, XOM, DE) or reconciliation failures (GIS, KO, HD, MDT).
- No forecast, reviewer, discovery or daily-funnel work.
- No policy changes (operating leases, pensions, equity-method investments). These are raised as decisions in §7.

## 4. Design

### 4.1 Who does what (Build guide §3.2)

| Owner | Work |
|---|---|
| Jev | Identify components: one label from a closed set, plus probabilities. It never outputs numbers, formulas or row moves. |
| Python | Prefiltering, all numbers, the mapping from nature to model policy, reconciliation checks, and provenance. |
| Patrik | Gold labels, policy decisions, approval. |

### 4.2 Jev answers economic nature; code owns policy

Jev classifies *what the row is*. A dictionary in code decides *where portable_model puts it*. A later policy change (for example, treating pensions as debt-like) then changes one line and needs no new calls.

### 4.3 Deterministic prefilter

Jev is asked only about **leaf residual rows**. The prefilter excludes:
- totals;
- rows that are parents of other face rows (subtotals);
- equity components;
- rows already matched by the named lists.

The probe shows why subtotals must go. The cash-plus-short-term-investment subtotals at GOOGL, KO and MSFT look claim-like but are harmless, because their children are already named.

### 4.4 State (all numbers computed in Python)

Jev doesn't do arithmetic or dates reliably, so every numeric field is computed in Python and passed as text:
- statement, concept, label, extension-tag flag;
- parent concept and parent label, sibling labels;
- current or noncurrent position;
- debit or credit balance and sign;
- share of the parent as a rounded percentage.

### 4.5 Questions (v1)

Each question asks one thing, following TypeSafe's guidance. Boundary cases are written into the criteria text, because Jev reads it literally.

**Row nature** (asked per leaf row):
- `nature` (Choice) over the classes in §4.6.
- `mixes_categories` (Noul): *does the caption or tag combine more than one class?* A `true` answer is never auto-eligible. This keeps ambiguity visible, as `AGENTS.md` requires.

**Slot identification** (asked per failed required read):
- `row` (Choice): options are the statement's face-row IDs plus `not_presented`. The limit is 255 options per question.
- `slot_contains_other_items` (Noul): for example, MSFT's "Depreciation, amortization, and other".

### 4.6 Classes and the v1 policy mapping (mirrors current behaviour)

| Class (`nature`) | Boundary text, abridged | v1 placement in `portable_model` |
|---|---|---|
| `cash_and_equivalents` | Unrestricted cash and equivalents; excludes restricted cash and securities | cash |
| `restricted_cash` | Legally or contractually restricted cash | residual; counts as cash only with note proof (current rule) |
| `marketable_investment` | Market-priced debt or equity securities, current or noncurrent | short or long investments |
| `nonmarketable_investment` | Private equity, equity-method and other non-traded investments | long investments, following the AMZN note precedent — **decision** |
| `borrowing` | Bank debt, bonds, notes or loans payable, commercial paper, securitisation borrowings, current portions | current or long debt |
| `finance_lease_liability` | Finance-lease obligations | debt (current note rule) |
| `operating_lease_liability` | Operating-lease liabilities | operating residual (current policy) |
| `pension_postretirement` | Net defined-benefit or OPEB balances | remaining noncurrent — **decision** (debt-like?) |
| `temporary_equity` | Redeemable NCI, redeemable preferred | capability gap |
| `financing_receivable` | Captive-finance receivables; a lessor's net investment in leases | capability gap (needs a financial-services method) |
| `operating_working_capital` | Receivables, inventory, prepaids, payables, accruals, deferred revenue, customer liabilities | operating residual |
| `tax_balance` | Current or deferred income-tax assets and liabilities | operating residual (current) / remaining (noncurrent) |
| `other_operating_noncurrent` | Goodwill, ROU assets, unnamed intangibles, other noncurrent | remaining noncurrent |

### 4.7 Provenance recorded for every answer

- pinned model `jev-1.13.0`;
- question and criteria version;
- state hash;
- all class probabilities;
- request ID and usage.

## 5. Work plan

### Phase A — Gold set (free)

1. **Export rows.** `scripts/jev_mapping/export_rows.py` is built from the probe. It writes the leaf rows and the 9 slot cases to `data/jev_mapping/gold/rows.csv`. It also writes a **blind** labelling copy without the `edgartools_standard` and `model_slot` columns.
2. **Label.** Patrik fills in `gold_nature` and `gold_mixes` for each distinct concept+label pair (177 pairs), and the labels propagate to all 306 rows. Expected effort: about 60–90 minutes, plus the 9 slot cases. `ambiguous` is an allowed answer.
3. **Fix the dev/holdout split before any call.** Split 11/11 by ticker, stratified so both halves contain claim-class rows (spread NVDA, KO, DE and F across the halves). Criteria wording is tuned on dev only.
4. **Compute free baselines.**
   - **B0:** current `portable_model` placement.
   - **B1:** a fixed lookup from edgartools `standard_concept` to class. It covers every us-gaap row and gives nothing for extension tags.

**Gate A:** the holdout must contain at least 20 rows in non-operating classes. If it doesn't, freeze more tickers with complex claims before any paid call.

### Phase B — Harness (free; no network in tests)

1. **Module.** `src/smrik_fund/jev_mapping.py` holds plain functions: `leaf_rows`, `build_state`, `questions`, `parse_answers`, `POLICY` (dict), `proposal_record`. A single function makes the call as a direct `httpx` POST to `/v1/systemone`. `httpx` is already present through `openai`, so no new dependency is needed.
2. **Tests.** `tests/test_jev_mapping.py` checks that:
   - the prefilter drops subtotals (GOOGL, KO and MSFT fixtures);
   - numbers are computed in Python;
   - an unknown label is rejected;
   - a `mixes=true` answer is never auto-eligible;
   - `POLICY` covers every class;
   - provenance fields are present;
   - a recorded response fixture replays correctly.
3. **Scoring.** `scripts/jev_mapping/score.py` reports per-class precision and recall, a confusion matrix against gold, accuracy by confidence bucket, and the comparison with B0 and B1.

### Phase C — Budget admission (free)

`analysis_budget.py` cannot admit Jev today. These blockers were verified in the code:
- `_prices` requires a positive `output_usd_per_million`, and Jev's output price is USD0.
- `reservation` requires OpenAI Responses fields (`input` as a string, `max_output_tokens > 0`, `service_tier`).
- `reserve_call` accepts one `endpoint_host` per ledger.

There are two options:
- **(a) Recommended:** extend the ledger to hold a second dated price snapshot keyed by endpoint host. Allow a zero output price for that host, bound Jev input by the UTF-8 bytes of state plus questions plus a wrapper allowance, and keep the same EUR ceiling and committed total.
- **(b)** A separate Jev ledger with its own small cap.

Option (a) keeps a single authorised ceiling. Add tests for admission, zero output pricing, the shared ceiling and the overrun lock.

### Phase D — One measured run (paid, tiny)

1. **Access.** Patrik supplies a key (TypeSafe console, or OpenRouter `typesafe/jev-1.13`) and a dated price snapshot taken from official docs.
2. **Cost.** About 306 rows × roughly 700 input tokens is about 0.21M tokens per pass. Up to 3 dev iterations plus one holdout run comes to under 0.6M tokens. At the published USD0.042/M input price, with free output, that is about USD0.03. Reserve €0.10. The ledger currently stands at 67 calls and €2.94 of the €5 ceiling.
3. **Run.** Run the dev iterations, then one holdout run. Store the raw responses and score them.

**Gate D — go/no-go, judged on holdout only.** Go only if all of these hold:
1. **Precision and recall on claim classes** (cash, marketable, nonmarketable, borrowing, finance lease, pension, temporary equity, financing receivable): at the chosen threshold, auto-eligible precision is at least 0.98, and overall recall (auto plus review) is at least 0.90.
2. **Beats the baseline:** better claim-class F1 than B1 on extension-tag rows, and no worse elsewhere.
3. **Named must-hits:**
   - NVDA non-marketable securities → `nonmarketable_investment`;
   - DE long-term borrowings (extension tag) → `borrowing`;
   - DE financing receivables → `financing_receivable`;
   - LULU gift-card liability → `operating_working_capital`;
   - XOM "investments, advances and long-term receivables" → `mixes=true`.
4. **Slot identification:**
   - UPS D&A, PFE total revenues and CAT total equity are identified correctly;
   - TGT's cash row is flagged, because its tag includes short-term investments while its label does not;
   - MSFT D&A-and-other gets `slot_contains_other_items=true`;
   - NKE and XOM operating income, and DE current assets, get `not_presented`;
   - no rows are invented.
5. **Calibration:** accuracy rises with the confidence bucket, within noise.

**No-go:** keep the named lists. Adopt the free B1 lookup only if it helps on its own, then stop.

## 6. Follow-on package (not in scope)

If the gate passes, run a shadow mode inside `prepare_model`:
- Residual rows whose proposed nature disagrees with their placement become a `REVIEW_REQUIRED` allocation and a limitation.
- Approved decisions persist through the existing decision state (P3).
- Reconciliation checks stay unchanged.
- A row moves only after human approval.

## 7. Decisions for Patrik

1. Approve this as a new package (scope gate).
2. Choose ledger option (a) or (b).
3. Set policy for three cases:
   - Do non-marketable and equity-method investments go into the bridge (as with AMZN)?
   - Are pensions debt-like?
   - Are temporary equity and financing receivables capability gaps?
4. Set the precision and recall targets.
5. Choose who labels gold: you, blind, or Claude pre-labels that you review. Pre-labelling is faster but risks anchoring. At minimum, label the holdout blind.

## 8. Risks

- **Small minority classes** (about 25–30 rows) mean wide confidence intervals. The named checks carry weight; add tickers if Gate A is thin.
- **Criteria overfitting** is controlled by the dev/holdout split. Jev's literal reading means wording matters.
- **Model drift** is controlled by pinning the version.
- **Vendor speed and accuracy claims** are self-reported. Only the holdout counts.
- **Tag/label conflicts** (TGT) must be surfaced, never resolved silently.
- **Data exposure:** the inputs are public SEC filings only, with no client data.

## 9. Files

| File | Status | Phase |
|---|---|---|
| `scripts/jev_mapping/export_rows.py`, `scripts/jev_mapping/score.py` | new | A, B |
| `src/smrik_fund/jev_mapping.py`, `tests/test_jev_mapping.py` | new | B |
| `src/smrik_fund/analysis_budget.py`, `tests/test_analysis_budget.py` | changed | C |
| `data/jev_mapping/` | new, gitignored | A–D |

## Appendix — reproduce the probe

```bash
uv run python -c "from pathlib import Path; from smrik_fund.company_case import freeze_company; \
[freeze_company(t, '2026-09-16', Path('tmp/cases')/t) for t in ['NVDA','KO','DE']]"
uv run python probe_row_placement.py tmp/cases
```
