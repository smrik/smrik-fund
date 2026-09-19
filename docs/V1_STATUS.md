# V1 Status

The pre-merge remote status is preserved verbatim in [the August 30 archive](history/20260830-main-status.md). Later verified work below supersedes that snapshot.

## Automatic BBWI assessment — verified 2026-09-20

- Added explicit `company_run --live --assess`: bounded filing research, dated
  market quote, source-cited analyst controls, independent model review/revision,
  native Excel, IC synthesis and independent IC correction. [Run guide](AUTOMATIC_ASSESSMENT.md).
  Free screening/default runs remain free. No company-specific financial override.
- Agents identified tariff refunds, settlement gains and discrete tax benefits.
  They selected forecast COGS 57.5%, SG&A 28.5% and tax 25%. The model reviewer
  changed depreciation from eight to five years and payout from zero to 25%; the
  application recalculated and obtained acceptance. Reported history is unchanged.
- Live output: `data/workspace/runs/20260920-bbwi-automatic-assessment-r2/`.
  Read `IC-reviewed.md`, `ASSESSMENT.md` and `reviewed/BBWI.xlsx`.
  IC priority: investigate. $58.1567/share is a conditional development scenario,
  versus the September 18 $17.40 quote; it is not a verified investment price target.
  Valuation-date alignment, detailed earnings normalization, downside scenarios,
  capital-market evidence and debt/lease detail remain material limitations.
- Native Excel: 572 forecast, 90 operating and 176 historical values checked;
  zero formula errors; beta/cost edit-restoration passed. All 43 source/artifact
  checks passed after the independent IC addendum. Model and IC revisions are
  recorded separately; the original draft remains available.
- Earlier baseline stopped on an ambiguous original-versus-revised control
  presentation; the first researched attempt stopped on invalid citation IDs.
  Both are preserved. Current prompts identify active controls, and output
  schemas constrain citations to actual supplied IDs.
- Cumulative budget: EUR 5.0966 of the authorized EUR 10, conservatively including
  earlier unknown-call reservations. This session added 11 calls; spending remains
  recorded in the existing ledger rather than reset for each attempt.

## Editable Excel template - verified 2026-09-19

- `templates/company-model.xlsx` supports inserted forecast rows and formula edits
  on the statements/support tabs. [Editing instructions](../templates/README.md).
  New UI/CLI company runs automatically use it; unchanged cells are regenerated
  from each issuer's sources. Default template has no financial overrides.
- Runs freeze template/contract files and hashes. Original row anchors preserve
  cross-sheet formulas; source/audit modifications and incompatible layouts stop.
  The run audit verifies both frozen template artifacts.
- Native Excel insertion proof: an additional 0.5% sales expense reduces BBWI's
  provisional value from $41.4706 to $39.8646/share. BBWI and NVDA pass native
  recalculation with zero formula errors. AAPL's extra revenue rows pass too.
- 18 focused tests pass; 43 other history/model/workbench regressions passed.
  The free simulated analyst -> reviewer revision -> recalculation cycle passes.
  Live LLM validation and PR-stack merges remain awaiting explicit approval.
- Latest BBWI output: `data/workspace/runs/20260919-bbwi-template-verified/reviewed/BBWI.xlsx`.
  LLM authority remains supported numeric controls, not arbitrary formula edits.

## Operating cost drivers - verified 2026-09-19

- Separate COGS/SG&A/R&D forecasts require reconciled FY/YTD expense composition;
  raw signs and explicit conversions are preserved. Incomplete detail keeps an
  explained aggregate forecast. No residual cost driver is invented.
- Income shows gross profit, EBITDA, margins and local cost formulas. Source-bound
  ratios are editable in Inputs or the free assumptions JSON; edits propagate
  through the linked statements and DCF and invalidate review.
- BBWI, NVDA and COST passed detailed-cost and one-point cost-change tests.
  LULU, HPQ and GOOGL passed explicit aggregate fallback tests. Existing AAPL,
  AMZN, KO and HD accounting regressions passed too.
- New BBWI output: `data/workspace/runs/20260919-bbwi-cost-drivers/reviewed/BBWI.xlsx`.
  Base forecast unchanged ($41.4706/share). Native Excel: 572 forecast, 90 cost-build
  and 176 historical values; zero formula errors; beta/cost edits restored exactly.
  All eight artifact/source audit checks passed. No paid calls.
- 56 unique relevant tests pass across the regression run and corrected focused
  follow-up; Ruff and JS syntax pass. [Model guide and scope](FINANCIAL_HISTORY.md).
- Current/deferred tax, financing, working-capital disaggregation and depreciation
  vintages remain subsequent financial-method work.

## Financial history and statement formulas - verified 2026-09-19

- New captures request five annual filings plus the latest subsequent interim.
  BBWI shows FY2021-FY2025, TTM and full annual forecasts; balances use exact
  dates. The initial future remainder stays separate for DCF timing.
- Removed the generic Schedules sheet. Forecast equations and visible drivers
  sit on Income, BalanceSheet and CashFlow; supporting Assets and WorkingCapital
  retain their roll-forwards. Source editions, signs, gaps, tax bridges and
  discontinued operations remain auditable. [Reading guide](FINANCIAL_HISTORY.md).
- BBWI: all 572 forecast values unchanged within tolerance; provisional DCF
  $41.4706/share. Native Excel checked 161 historical values, found no formula
  errors and passed beta edit/restoration. Eight source/workbook audit checks
  passed. The assumptions remain provisional; no paid calls were made.
- Regression command: `pytest -q tests/test_company_case.py
  tests/test_company_history.py tests/test_company_model.py
  tests/test_portable_model.py tests/test_daily_research.py
  tests/test_research_workspace.py`: 102 passed, four execution timeouts.
  Isolated retry of AMZN, KO, HD and the HTTP contract: all four passed
  (202.71s). Real workbook coverage includes BBWI, AAPL, LULU, HPQ, NVDA,
  COST, GOOGL, AMZN, KO and HD; this is not universal issuer coverage.
  Final history/export tests: 10 passed (14.96s). Ruff, JavaScript syntax and
  whitespace checks passed. Statement and DCF previews were inspected.
- Forecast expense detail remains consolidated. COGS/SG&A are reported as
  historical detail where available, without invented forecasts. The user-supplied
  CFA workbook was reviewed as a reference; remaining financial-method differences
  are recorded in the reading guide.

## Screener and optional watchlist — verified 2026-09-19

- [x] Added `/screener` and `/watchlist` to the local website. Screener opens the
  latest saved broad universe: 2,765 companies, 2,486 passing initial filters,
  72 candidates and a 30-stock shortlist in the September 16 capture. Includes
  company/sector/valuation filters, sortable columns, pagination and CSV export.
  This provider-filtered universe is not every US listing or universal model coverage.
- [x] Company detail links to the selected screen/ticker in Research and the
  latest saved attempt. Dates, missing inputs, source issues and original screen
  decisions remain visible; financial evidence is verified before use.
- [x] Optional watchlist starts empty. Up to 30 active companies, persistent notes,
  research stages, archive/restore and manual USD review prices. Freshness/currency
  guards suppress invalid price flags; revision checks prevent lost edits. Notes
  remain separate from reported data and model assumptions.
- [x] **74 tests PASS (14.33s)** across `test_research_watchlist.py`,
  `test_research_workspace.py` and `test_daily_research.py`. Changed-code Ruff,
  both pages' JavaScript syntax and Git whitespace checks passed. New watchlist
  contracts are included in portable GitHub CI.
- [x] Browser: universe/subset counts, numeric filters, sorting, pagination,
  LULU analysis handoff, persistence, archive/restore and a free META watchlist
  screen passed. Persistence tests used an isolated local workspace; the user's
  watchlist remains empty. Verified actual viewport widths 320/375/414/768/1280,
  contained table scrolling, phone editor fit and Escape returning focus.
  No browser console errors. [Preview](images/screener.png),
  [usage and code guide](WORKBENCH.md#screener-and-watchlist).
- [x] No paid calls. Financial calculations and native Excel were unchanged;
  prior real-model/Excel evidence remains below.

## Workbench editorial redesign — verified 2026-09-19

- [x] Installed project-local `no-ai-slop` from petergyang/no-ai-slop and the
  supplied `anti-slop-design` skill. The supplied main file is an exact copy;
  its three referenced documents were not attached.
- [x] Applied Hallmark's editorial direction: compact masthead, serif headings,
  shared local CSS tokens, controls beside the selected result, expandable
  evidence and run records. Removed the slogan, feature strip, statistic cards
  and repeated explanatory subtitles. Financial calculations are unchanged.
- [x] **52 tests PASS (11.82s)** across `test_research_workspace.py` and
  `test_daily_research.py`; the HTTP test passed again after the final CSS-policy
  change. Ruff, JavaScript syntax and Git whitespace checks passed.
- [x] Browser: requested widths 320/375/414/768 and laptop 1280; no page overflow.
  Checked keyboard disclosures/focus, run filtering, stopped-run limitations,
  execution logs and invalid-JSON recovery. Text contrast >=6.09:1 on the tested
  surfaces; focus contrast >=3:1. [Updated preview](images/workbench.png).
- [x] Fresh free UI screen for META/HD/KO completed with 3 companies and 1/1 audit
  checks passing: `data/workspace/runs/20260919T134944-17455ced`. No paid calls.
  This verifies the redesigned screen controls; native Excel was not rerun for
  this visual change. Prior Excel evidence remains below.

## Local workbench and broader coverage — verified 2026-09-19

- [x] Working baseline merged to `main` through [PR #4](https://github.com/smrik/smrik-fund/pull/4),
  with both status histories preserved. New work is on `codex/research-workbench`.
  Generated annotations and local run notes were removed from Git tracking and
  preserved on disk; caches, data, secrets and one-off probes remain ignored.
- [x] `smrik-fund daily serve` opens a loopback website on port8787: free screens,
  company analysis, job receipts, run history, candidate metrics, assumptions,
  source evidence, failure stages and Excel downloads. No paid action is exposed.
  [Usage and code walkthrough](WORKBENCH.md); [actual UI preview](images/workbench.png).
- [x] Shared free CLI/UI workflow; immutable run directories and timestamped
  stages. Screening decisions are recomputed before use. Audit verifies frozen
  source files, selected screen, source/model bindings, published file hashes,
  accounting gates and native Excel receipts. Worker crashes remain visible.
- [x] Additional10-ticker coverage: META, HD and KO complete through formatted
  native Excel; JPM/O retain sources and require specialist methods; MSFT, JNJ,
  PG, XOM and CAT stop on documented statement-classification gaps.
  [Coverage and financial limitations](COVERAGE_20260919.md).
- [x] Fixed HD's double-counted finance-lease debt components and KO's consolidated
  earnings/tax bridge. Reported source values remain intact. Supported-case
  regression tests include the previous AAPL/AMZN/COST/LULU/HPQ/BBWI paths.
- [x] Actual browser buttons tested: six-company screen → new META SEC capture →
  DCF → formatted native Excel. Nine audit checks PASS; downloaded workbook hash
  equals the published original. UI receipt: `data/workspace/validation.json`.
- [x] Focused regression: **107 tests +9 subtests PASS (49.12s)**:
  `tests/test_analysis_budget.py`, `tests/test_company_case.py`,
  `tests/test_daily_research.py`, `tests/test_company_model.py`,
  `tests/test_portable_model.py`, `tests/test_research_workspace.py`.
  Changed-code Ruff, browser JavaScript syntax, CLI help and Git whitespace checks PASS.
  Each new workbook verified572 cells and beta edit/restoration; three coverage
  workbooks plus the UI-created META workbook total2,288 checked schedule cells.
- [x] No new paid calls: ledger remains67 calls (64 completed,3 historical
  usage-unknown). Existing committed budget remains approximately EUR2.9363 of5.

Known limits: universal generic valuation coverage remains unfinished. These
are provisional reported-TTM scenarios, not normalized investment targets. Native
Excel needs normal Windows desktop permissions; restricted sandbox attempts were
retained as failures before fresh successful runs. Historical whole-suite diagnostic
was595 passed,101 subtests passed,45 failed; failures include expired dated price
fixtures and older integration expectations. The full legacy suite is not clean
and was not repaired as part of this feature. GitHub CI runs the portable free
contracts; optional downloaded KO/HD cases skip on a clean checkout.

## Weekend valuation pack — completed 2026-09-16

Prepared LULU, HPQ and BBWI for September 19–20:
[research desk](../data/weekend/20260919/index.html),
[comparison](../data/weekend/20260919/comparison.csv),
[validation receipt](../data/weekend/20260919/validation.json).

- [x] All three frozen SEC cases → editable provisional DCF → formatted native
  Excel, with fresh September 16 price inputs and recorded free assumptions.
  Workbooks: [LULU](../data/weekend/20260919/LULU/base-r2/reviewed/LULU.xlsx),
  [HPQ](../data/weekend/20260919/HPQ/base-r2/reviewed/HPQ.xlsx),
  [BBWI](../data/weekend/20260919/BBWI/base-r2/reviewed/BBWI.xlsx).
- [x] Real blockers fixed: source-caption-bound cash classification for LULU;
  fiscal-year label/calendar-year separation and unique date-bound quarter columns;
  BBWI consolidated equity/NCI reconciliation, NCI claim deducted in DCF and
  sensitivity; liability hierarchy excludes consolidated equity.
- [x] Optional free `daily deep --assumptions PATH`: complete validated controls,
  rationale and limitations recorded; explicit scenario values including prices
  below USD50. No paid transport or independent runtime-agent review.
- [x] Earnings bridges from company releases: LULU guidance less USD0.86 tariff
  benefit; HPQ GAAP/non-GAAP guidance separately less USD0.19; BBWI adjusted
  guidance less an approximate USD0.31 quarterly tariff EPS benefit. BBWI share
  denominator approximation and other management addbacks remain explicit.
- [x]85 tests +9 subtests PASS50.07s; changed-code Ruff/Node syntax PASS.
  Native Excel572 cells per workbook/1,716 total, beta edit/restoration PASS;
  maximum difference1.21e-10 USDm. Model/workbook/source-code hashes verified;
  report layout inspected and19 local desk links checked.

The DCFs retain reported TTM history, including one-offs; earnings normalization
and illustrative EPS/multiple cases are separate. Baselines USD123.3981 LULU,
USD42.4509 HPQ, USD41.4706 BBWI are **not normalized price targets**. All are
PROVISIONAL_UNREVIEWED. None meets the pack's illustrative25% discount-to-value
research hurdle in the base EPS case. No paid calls; budget ledger still67 calls
and EUR2.9363062497 committed. Original reviewed models preserved; no commit/push;
full legacy suite not rerun. Universal valuation coverage remains unfinished.

## Free daily research funnel — verified 2026-09-16

User chose US-listed companies first, free work by default, and explicit paid
analysis only after identifying a worthwhile research case.
[Daily desk](../data/daily/20260916-release/index.html);
[usage, methodology, outputs and limitations](DAILY_RESEARCH.md).

- [x] Agent-free US screen, free fundamentals and sector references, explained
  value/quality gates, issuer-deduplicated shortlist of up to30 names.
- [x] HTML dashboard and company briefs, CSV/JSON/raw snapshots, cache/replay,
  optional previous-run comparison and hash-verified existing DCF summaries.
- [x] Live free run:2,765 provider listings;2,486 first-filter passes;1,284 final
  value seeds;1,289 fundamentals fetched (five later excluded), zero failures;
  72 qualifying candidates →30 shortlisted. Zero final seeds left unfetched.
- [x] Preferred-security ratio misuse, currency differences, missing/stale data,
  suspicious earnings margins and unsupported methods remain explicit gates.
- [x] Optional IC packet/agent: explicit ticker, thesis and unresolved question;
  paid call requires `--live`, current verified pricing and the existing budget.
  Default packet preparation is free. Transport/accounting tested with mocks;
  no live IC call made. Ledger unchanged at67 calls/EUR2.9363062497 committed.
- [x] Free on-demand deep path: HPQ frozen SEC sources → provisional DCF →
  [formatted Excel](../data/daily/20260916-hpq-deep-r2/reviewed/HPQ.xlsx).
  Combined face cash accepted only after notes prove explicitly zero restricted
  cash and reconcile.572 native Excel values, beta edit/restoration PASS;
  max difference1.24e-10 USDm. Scenario USD60.4919/share; unreviewed, not a target.
- [x]78 focused tests +9 subtests PASS19.66s; changed-code Ruff PASS;
  dashboard/brief browser render and local artifact links checked.

Broad screening coverage is operational; universal full valuation is not.
REIT/financial/loss-making methods, unsupported foreign filings/currencies,
missing classifications and complex claims still require dedicated deep work.
Free heuristics identify research candidates, not proven mispricings. Existing
reviewed MSFT/AAPL/multi-ticker artifacts preserved. No schedule, paid batch,
commit or push; full legacy suite not rerun; no human investment approval.

## Reusable multi-ticker DCF — tested 2026-09-10

User authorized broader ticker support and provisional defaults for E2E testing.
[Results, workbooks and receipts](../data/multi-ticker/portable/RESULTS.md);
[CLI instructions and coverage limits](../data/multi-ticker/portable/README.md).

- [x] CIK-bound ticker aliases; source-based consolidated financial inputs;
  date-based fiscal windows, including first quarter/36-week YTD/annual-only.
- [x] Signed tax reconciliation, source-hierarchy liabilities, frozen native
  note facts, explicit finance-lease and nonmarketable investment classifications.
- [x] NVDA, GOOGL, COST and AMZN independently reviewed and published to formatted
  Excel. Native Excel checks all572 schedule cells per accepted workbook; beta
  edits invalidate review and restoration passes. Source/model/workbook hashes checked.
- [x] Fresh ticker-only NVDA/GOOGL/COST source-to-Excel runs pass with frozen notes.
- [x]43 focused tests+9subtests PASS18.36s; changed-code Ruff/JS PASS.
- [x] Bounded review completion can reuse a verified completed analyst; interrupted
  transport is not silently retried. Mid-run implementation changes block publication.

Amazon's first review rejected incomplete lease/investment claims. Sourced fixes
were freshly accepted; one intermediate response exhausted its output cap and
remains recorded. New cost EUR1.0136301 across11 calls; total committed
EUR2.9363062/EUR5, including preserved prior holds. No new unknown-usage holds.
Original MSFT/AAPL outputs preserved; no commit/push. Full legacy suite not rerun.

Coverage is broader, not universal: JPM is explicitly blocked for a financial-
sector valuation method. Unsupported forms/currencies, unresolved classifications,
missing/ambiguous facts or unfunded forecasts still block. No human financial approval.

## Initial ticker portability tests — historical, 2026-09-10

Executed NVDA, GOOGL and COST through `dcf --no-live`: **0/3 E2E complete**.
[Report, source proofs and logs](../data/multi-ticker/20260910/PORTABILITY_REPORT.md).
NVDA/COST frozen sources each validate ten hashes. NVDA stops at AAPL-specific
balance mappings; COST at unlabeled 36-week YTD selection. GOOGL stops at strict
filing-ticker equality despite matching annual company CIK; GOOG control also
fails within the filing pair. No paid calls or new workbooks; production unchanged.
Next: CIK-bound aliases, date-aware period selection, then company-specific
source coverage and one full reviewed model. Provisional defaults remain authorized.

## Second-company extension — development E2E complete, 2026-09-10

Patrik authorized provisional financial defaults and simplifications during E2E
testing; financial-policy approval follows a working system. Assumptions remain
visible; human financial approval remains false.
[Acceptance report](../data/second-company/AAPL/acceptance/ACCEPTANCE_REPORT.md).

- [x] Refresh dated pricing without changing historical costs or expiry gates.
- [x] Repair historical revision-test clock dependence: 8 tests PASS.
- [x] Freeze/validate AAPL SEC annual/interim sources: 2026-06-27 measurement,
  2026-09-10 cutoff, ten bound artifacts.
- [x] Reconcile source history/TTM; build 11 linked forecast periods and DCF using
  explicit AAPL mappings and documented provisional methods.
- [x] Execute live analyst, independent review, formatted formula-linked Excel,
  beta revision and live independent re-review; both reviews accept.
- [x] Execute fresh ticker-only CLI source-to-native-Excel run without inference.

[Final AAPL workbook](../data/second-company/AAPL/beta-revision-r1/reviewed/AAPL.xlsx):
beta1.20, WACC9.8593%, USD128.3185/share; base beta1.10 USD136.9249.
All572 schedule cells unchanged by beta revision; native Excel agreement within
4.66e-10 USDm, edit invalidation/recovery PASS.28 focused tests+9subtests, final
CLI test, changed-code Ruff/JS PASS; visual review PASS.
Full-suite diagnostic stopped after older failures; one reproduced MSFT fixture
uses expired historical pricing. Unrelated fixtures left unchanged.
Three new paid calls EUR0.3794922; cumulative ledger EUR1.9226761/EUR5 including
three preserved unknown holds. Original MSFT version still current and valid.
AAPL is proven; arbitrary ticker modeling and a new global publication pointer
are not claimed. Historical MSFT acceptance and its dated costs follow below.

## Current build — three-statement DCF (authorized 2026-09-05)

Main authority: [AI_FUND_BUILD_GUIDE.md](AI_FUND_BUILD_GUIDE.md). Patrik authorized
all required packages, replacing the older P&L-only completion boundary and Part F
scope restriction. Existing source data, financial history, and unrelated dirty
work remain preserved. No commits/pushes authorized.

Completion requires a frozen real MSFT case through sourced history, bounded
research, linked forecasts, DCF, whole-model review, formula-linked Excel export,
and an authoritative revision. Mechanical, evidence, analytical, and human-review
states remain separate. Tick a package only after its mandatory evidence passes.

- [x] P0 — baseline and scope: [baseline](AI_FUND_BASELINE.md); 63 tests + 12 subtests; parent gate passed.
- [x] P1 — [Mog/Excel compatibility](SPREADSHEET_ENGINE_DECISION.md); base/edit/error/literal checks and native hyperlink sample passed.
- [x] P2 — [frozen history and source evidence](../Lunacy/runs/three-statement-dcf/phases/history/P2-complete-R2-report.md): 733 rows, 40 TTM; 1253 PASS/449 NOT_TESTED/0 FAIL; independent adverse financial, actual XLSX and eight exact-source excerpt checks passed. Explicit cash-definition/component limitations retained.
- [x] P3 — [safe detail and effective history](../Lunacy/runs/three-statement-dcf/phases/interpretation/P3-integration-report.md): correction/re-check and prior-approval safeguards; frozen-source validation; two identical FY23–FY25 rebuilds, 12 reconciliation PASS; 1.3bn detail preserves 21.795bn parent.
- [x] P4 — [complete fictional model](../Lunacy/runs/three-statement-dcf/phases/fictional/P4-R1-report.md): 11 linked periods, anchors/propagation/adverse/recovery checks; native Excel16 recalculation; missing inputs block valuation, numeric zero stays valid.
- [x] P5 — [live asset reasoning and revision](../Lunacy/runs/three-statement-dcf/phases/assets/P5-live-R3-report.md): actual analyst + review + 9→10-year development revision + re-review; two 11-period models/rebuilds/native Excel PASS; 30 tests + 9 subtests, Ruff, 11 adverse groups. Five calls including first held case cost EUR0.0313591. Terminal normalization and full equity bridge are covered by P9.
- [x] P6 — [segment revenue and operating costs](../Lunacy/runs/three-statement-dcf/phases/operating/P6-live-R5-report.md): saved analyst resumed, independent review accepted actual Mog forecast; final 11-period rebuild and native Excel 8/8 PASS; 14 focused tests/Ruff/JS PASS. Review-bound editable drivers; gross-minus-embedded-plus-scheduled expenses; P6 EUR0.0863168 known + EUR0.0236755 held.
- [x] P7 — [working capital and cash conversion](../Lunacy/runs/three-statement-dcf/phases/working-capital/P7-live-R4-report.md): actual live analyst/reviewer accepted the source-baseline/multiplier model; 14 focused tests/Ruff/JS, corrected independent oracle, 11-period numerical rebuild and native Excel PASS. Missing inputs block; supported zero remains valid; edits invalidate review. Ten P7 records, EUR0.0727454 priced + EUR0.0125998 held; prior rejections preserved.
- [x] P8A — [taxes](../Lunacy/runs/three-statement-dcf/phases/taxes/P8A-live-R5-report.md): actual analyst07/reviewer08 accepted the source-anchored payable-days policy; final11-period Mog rebuilds identical and native Excel10 checks PASS.17 focused tests/Ruff; strict provider schema repaired. Eight P8A records: EUR0.0259149 priced + EUR0.0223270 held; prior failures preserved.
- [x] P8B — [debt, leases and funding](../Lunacy/runs/three-statement-dcf/phases/financing/P8B-live-R6-report.md): actual analyst04/reviewer05 accepted; source/provenance gate, 30 focused tests/Ruff, four adverse binding regressions, two identical 11-period final rebuilds and eight native Excel checks PASS. Review status preserved; no financial change in export repair. Five calls, EUR0.0361645 known.
- [x] P8C — [SBC, shares and equity](../Lunacy/runs/three-statement-dcf/phases/equity/P8C-live-R6-accepted-report.md): actual analyst04/reviewer05 accept;19 focused tests/Ruff, genuine Mog claim/timing/adverse checks, identical final11-period rebuilds and native Excel18 PASS. Existing awards deducted once; current7429m denominator separate from EPS shares. Five calls EUR0.0292113 known; prior invalid output/rejection preserved. Complete valuation is covered by P8D/P9.
- [x] P8D — [investments, intangibles and remaining balances](../Lunacy/runs/three-statement-dcf/phases/other-balances/P8D-live-R7-accepted-report.md): actual analyst02/fresh reviewer06 accepted; parent corrected a false review tax premise using all11 actual UFCF comparisons.14 focused tests/Ruff, identical final snapshots and9 native Excel checks PASS. Six calls EUR0.0525609. Mixed evidence/estimates remain explicit; no human approval.
- [x] P9 — [integrated real-company statements and DCF](../Lunacy/runs/three-statement-dcf/phases/valuation/P9-parent-accepted-report.md):50 statement rows ×11 periods, two equal full snapshots,14 adverse financial cases and9 native Excel checks PASS. Parent repaired review-formula construction order and invalid-method handle lifetime;4 focused tests/Ruff PASS. Complete base USD237.697050/share; whole-model analytical review completed in P10.
- [x] P10 — [controlled workflow and independent whole-model review](../data/build-guide-p10/parent-final-r6/P10-accepted-report.md): actual Sol accept across12 areas/all11 periods after four targeted corrections; 550 financial values unchanged.27 workflow tests+6subtests,5 valuation tests, final dependency regression/Ruff PASS. Three calls EUR1.0270408; human approval remains separate.
- [x] P11 — [usable Excel review and CLI revisions](../data/build-guide-p11/P11-accepted-report.md): final base and beta1.15 revision;12 reachable decisions,37 native links,7 notes; actual independent recheck accepted USD210.062221/share with all550 statement values unchanged. Company lock/expected-prior check/atomic current-version update and interrupted-publication recovery pass all8 revision tests. Paid review reused without new calls.
- [x] P12 — [complete acceptance evidence](../data/build-guide-p12/acceptance/ACCEPTANCE_REPORT.md):566 tests+101subtests PASS315.00s, changed-code Ruff/JS,20 original excerpts, exact repeat snapshot and native local-edit/CLI comparison PASS. All19 guide adverse cases mapped. Workflow accepted under the recorded user reply; one authorized [calibration](../data/build-guide-p12/calibration-low/CALIBRATION_REPORT.md) completed, no model adoption.

Open the final [review workbook](../data/build-guide-p11/beta-final-revision/reviewed-version/MSFT-review.xlsx) and [review/revision instructions](../data/build-guide-p11/review-final-v1/READ_ME.md). [Current company version](../data/MSFT/current-review.json):`v2-70f81a4d8f77`; prior versions remain inspectable, while new CLI revisions require the current version. The [latest approval](../data/build-guide-p12/approval-2026-09-08.json) extends authority through goal completion. Final ledger53 records:50 completed EUR1.4845817 plus three unknown-usage holds EUR0.0586022 = **EUR1.5431839 committed** of EUR5; EUR0.50 final-review reserve remains protected. [Final cost receipt](../data/build-guide-p12/acceptance/final-cost-receipt.json). No call occurred during publication hardening or the final regression. All prior artifacts and holds remain preserved.
Selected [development case](MSFT_CASE_PROPOSAL.md): 2026-04-30 information cut-off, 2026-03-31
measurement/valuation, Apr–Jun FY2026 stub then FY2027–FY2036. Patrik authorized
agent-selected development dates and .env use on 2026-09-06. Confirmed P3 repair: Reviewer `revise` must not
approve/apply the original candidate. Paid LLM usage at P5 handoff: EUR0; current calls/cost/reservations live in `data/build-guide-api-budget.json` (EUR5 ceiling).
Execution ownership: `Lunacy/runs/three-statement-dcf/STATE.md`.
Goal status: **COMPLETE — P0–P12**,2026-09-08. Patrik's “okay, approved until goal is achieved. Proceed” was recorded as contextual acceptance of the demonstrated review workflow and approval of the prepared calibration. Human financial approval remains false. Both reasoning settings accepted the fixed calibration task; the single pair does not justify changing general routing. Final publication proof and full regression pass. No required V1 implementation or acceptance decision remains. Second-company support, broader research and synchronization remain later backlog. No commit/push; unrelated dirty work preserved.

## Historical P&L milestone — retained for context

The entries below describe the earlier completed scope and are not completion
claims or scope restrictions for the newly authorized build.

One page. Read this first in every session. Update it last.
Definition of done: Section 2 §2 of `ai_fund_v1_section_2_implementation_spec.md` (16 checkpoints).
Build order: Section 2 Part F (Tasks 1–12). Nothing outside Part F is V1 work.

Last updated: 2026-09-04

## Are we done? 16 of 16 functional checkpoints.

| # | Checkpoint | Status | Evidence |
|---|-----------|--------|----------|
| 1 | Load MSFT 10-K via EdgarTools | DONE | ingestion works, data/MSFT populated |
| 2 | Three-year analytical P&L | DONE | analytical_pnl.csv |
| 3 | Source reconciliation, visible warnings | DONE | reconciliation_checks.csv |
| 4 | One useful evidence packet | DONE | data/MSFT/03_output/evidence/ |
| 5 | Analyst finds expected adjustment in the first known case | **DONE** | eval run 20260830T151122042664Z: candidate_matches_expected PASS, judge PASS; case msft_analyst_normalization_candidates |
| 6 | Reviewer reviews the candidate correctly | **DONE** | live run 20260830T154157325260Z: OpenAI candidate reviewer verdict `accept` |
| 7 | Deterministic validation + materiality runs | DONE | gate implemented, shadow mode per spec §25 |
| 8 | Safe auto-approve / uncertain to human review | DONE | mechanics work; auto-approval behind feature switch (spec M3, enable at M5) |
| 9 | adjustment_history.csv preserves history | DONE | 30 rows; 1 approved (A0030 OpenAI $6.5B); 6 rejected; 23 leftover proposed |
| 10 | Review: accept / reject / edit amount / edit period | DONE | review CLI |
| 11 | Manual adjustments use the same engine | DONE | |
| 12 | Current adjustments resolve from history | DONE | |
| 13 | Adjustments apply without mutating reported values | DONE | |
| 14 | Subtotals and metrics recalculate | DONE | |
| 15 | Adjusted reconciliation passes | DONE | adjusted_reconciliation_checks.csv |
| 16 | One golden MSFT end-to-end case passes | **DONE** | live run + human review: A0030 approved; adjusted Other income $4,197M; reconciliation 12 PASS / 0 FAIL |

Task 12 validation: full pytest passes (314 tests, 84 subtests); changed-file
Ruff and golden-test Pyright pass. Repository-wide Ruff still has one pre-existing
error and Pyright has 318 pre-existing errors; left unchanged per scope rules.

## The plan (in order, nothing else)

1. **DONE 2026-08-30 — known case chosen by Patrik: OpenAI recapitalization
   dilution gain.** Triage of adjustment_history.csv also done: 23 LLM
   proposals were amount-less R&D exhaust; the 3 quantified UTP-interest
   adjustments were correctly rejected as recurring.

   Known-case expected values (spec §41 analyst-eval fields), source: FY2026
   10-K, accession 0001193125-26-323660, Note 3 / MD&A:
   - target_line: Other income (expense), net (reported FY2026 total +$10,697M)
   - period: 2026-06-30 (FY)
   - item_amount: $6.5B — disclosed verbatim ("$6.5 billion of net gains ...
     from investments in OpenAI"); exact dilution-only figure is NOT separately
     disclosed (verified: all 3 filing occurrences say "primarily")
   - item_effect_on_line: increased_line → line_delta −$6.5B → adjusted +$4,197M
     (no zero-crossing)
   - amount_basis: disclosed
   - evidence packets already on disk: evidence/01_openai_* files
   - expected gate outcome: human review (materiality — $6.5B fails the 5%
     operating-income cap), then human approve. Auto-approve is NOT expected.

   Runner-up case (backlog): Xbox impairment — named in MD&A with no amount in
   current packets; needs the impairment note retrieved before usable.
2. **DONE — Analyst eval and Reviewer pass on the known case** (#5, #6).
3. **DONE — Golden end-to-end test and live run** (Part F Task 12) (#16).
4. **V1 functional scope done. Stop.** Review the whole product before new work.

## Off-spec code — frozen, not V1 work

Not in Part F. Do not extend. Fate decided after V1 (V2 candidates or deletion):

- `analytical_scan.py`
- `filing_investigation.py` (3,555 lines)
- `segments.py`
- `discovery.py` (overlaps with analytical_scan)
- eval cases that target these stages

## V2 backlog (parked ideas — recorded, NOT approved for V1)

- Segment-driven forecasting (raised 2026-08-30): add segment revenue /
  operating-income rows to the analytical model; LLM proposes per-segment
  forecast drivers (growth, margin) with evidence, through the same
  analyst → reviewer → gate pattern. Hard dependency: consumes the ADJUSTED
  P&L, which exists only after V1 closes. `segments.py` (frozen) is the
  starting material.

## Explicit post-V1 extension (approved 2026-08-30)

- Shared line-detail mechanics: `line_details.py` provides a small DataFrame
  view for reported parents, segment details, normalization details, and
  derived remaining amounts. It remains outside Part F/V1, is persisted by the
  adjusted-output rebuild as `line_details.csv`, and reuses segment filing
  identity plus adjustment resolution/application mechanics. Authorized live E2E
  `20260830T192905674546Z` completed; the final rebuild produced 7 parent, 19
  detail, and 7 remaining rows, with segment reconciliation 6/6 and adjusted
  P&L reconciliation 12/12. A0030 remains the effective human-approved
  adjustment: Other income $10,697M reported, $4,197M adjusted.
- First-class model rows (approved 2026-09-03): segment and added-line children
  sit in `adjusted_pnl.csv` under their parents as `is_breakdown` rows. They
  are not included in subtotals. Reported `analytical_pnl.csv` is unchanged.
  Recon still runs on consolidated parents before the children are attached.
- Scan → notes → analyst join (approved 2026-09-03): `smrik-fund run` uses
  Analytical Scan findings as the worklist. Literal non-question scan phrases
  (else the finding title) retrieve an existing notes packet; the existing
  analyst/review/apply path is unchanged. Discovery remains only on
  `analyze --adjustments`. Frozen proof: OpenAI $6.5B from the scan finding
  through the gold packet. No new modules. `filing_investigation.py` unused.
- Apply reviewer-accept on the scan/run path (approved 2026-09-04): after notes
  retrieve, a reviewer `accept` with a derivable delta is written to history and
  applied. Rejects stay off the statement. Interactive approval is not required
  to see standout items on the adjusted workbook. `analyze --adjustments` still
  uses shadow auto-approval.

## Rules

- Only tasks from Section 2 Part F are in scope.
- A task not on that list requires Patrik's explicit written approval, recorded here.
- Every session: read this file first, update it last.
- One task → one branch → focused test → commit (spec §51). No uncommitted piles on main.
- No autonomous/unattended runs without a named Part F task.
