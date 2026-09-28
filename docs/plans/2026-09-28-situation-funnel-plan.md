# Situation funnel — development plan

**Status:** PROPOSED, not approved (AGENTS.md scope gate). **Date:** 2026-09-28.
**Goal:** move Patrik's time from building models to judgement. smrik-fund finds
special-situation, low-coverage and local small-cap candidates, compresses each into
a one-page brief, and hands over only the questions that need judgement.

## 1. Decisions

**Keep this inside smrik-fund as a new workflow. Don't start a new repo.**

It reuses the parts that were hard to build:
- point-in-time freezing (`company_case`);
- five-year history (`company_history`, PR #7);
- the DCF engine and diagnostics (`company_diagnostics`, PR #11);
- the budget ledger, LLM transport and the audit/hash trail;
- the workbench and watchlist.

A new repo would duplicate all of that, and it would split the budget ledger.

**Boundary:** the funnel *calls* the model; it doesn't extend it. There is no new
DCF machinery beyond §3's reverse DCF and one WACC fix.

**The preliminary model stays, but as a draft rather than a verdict.** It is used
for three things:
1. **Implied expectations:** solve for the growth and margin the price implies.
2. **Driver sensitivities:** tell the brief which assumptions matter.
3. **A starting workbook** for the few names that reach a deep dive.

The full `--live --assess` path is reserved for those survivors.

## 2. Target flow

```
triggers ──► filters ──► implied expectations + capital-allocation scorecard ──► LLM brief ──► Patrik: kill / deep dive ──► decision log ──► forward scoring
 (daily)     (free)             (free, deterministic)                      (~1 call)      (30–60 min)          (thesis, kill criteria)
                                                                                              │
                                                                                              └─► existing --live --assess (survivors only)
```

**Weekly budget:** about 10 briefs and about 2 hours of reading. Expect to kill 8–9.

## 3. Packages

### F0 — Prerequisites (1–2 days)

1. **Decide on the open PR stack (#5–#11).** The funnel builds on #7 (history) and
   #11 (diagnostics), so merge them or rebase onto them.
2. **Fix WACC so it stops flattering levered, beaten-down names.**
   - Re-lever beta with market D/E.
   - Derive the cost of debt from reported interest expense over average debt,
     with an explicit floor.
   - Test with the BBWI numbers: at a $16.45 price and 52% debt weight, the
     current code gives a 6.45% WACC and $144.63 per share. After the fix,
     WACC must rise with leverage.

### F1 — US trigger feed (EDGAR; free)

Build a daily table of events from forms that EdgarTools already reads:

| Trigger | Source |
|---|---|
| Spin-off | Form 10-12B / 10-12G |
| Tender offer, going-private | SC TO-T, SC TO-I, SC 13E-3 |
| Activist stake | SC 13D, and amendments |
| Insider cluster buying | Form 4: ≥2 insiders buying on the open market within 30 days |
| Asset sale, material agreement | 8-K items 1.01 and 2.01 |
| CEO or CFO change | 8-K item 5.02 |
| Balance-sheet anomaly | Net cash > 50% of market cap, or price below tangible book, from the existing screen |

- **Output:** `data/situations/<date>/triggers.csv` with ticker, trigger, filing link and date.
- **Acceptance:** one real day processed; every row links to its filing.

### F2 — Filters and a one-page quant sheet (free, deterministic)

- **Filters:** liquidity bounds, and a coverage proxy (analyst count from the price
  provider; missing counts as low coverage and is flagged).
- **Implied expectations (reverse DCF):** solve `products_growth` so that value equals
  price, holding all other controls. Report the solved growth next to 5-year
  history. Then do the same for margin.
- **Capital-allocation scorecard (5 years):**
  - ROIC and incremental ROIC;
  - reinvestment rate;
  - share-count change, buybacks and dividends;
  - M&A spend versus the resulting EBIT;
  - net-debt trend.
- **Acceptance:** fixed-input tests for the reverse DCF (solve, then recompute,
  gives the same price). Real run on 3 triggered names.

### F3 — LLM brief (paid, one Luna call per name, target < €0.30)

**Input:** the F2 sheet, the trigger filing excerpt, and the latest 10-K/10-Q
sections on business, risks and MD&A.

**Output:** a one-page `BRIEF.md` with:
1. the situation;
2. what the price implies;
3. the capital-allocation record;
4. the industry structure;
5. **2–3 questions only judgement can answer**;
6. obvious kill reasons.

All claims cite evidence IDs. The brief makes no valuation and gives no
recommendation.

**Acceptance:** 5 real briefs, with cost logged through the ledger. Patrik rates
each on usefulness (1–5).

### F4 — Decision log and forward scoring (free)

Each record holds:
- decision: kill or deep dive;
- the implied expectation;
- Patrik's view;
- kill criteria;
- date and price.

For deep dives, also record 4-quarter forecasts of revenue and margin.

**Scoring:**
- **Fundamentals:** score forecasts against actual 10-Qs, versus a naive
  carry-forward.
- **Returns:** score at 6, 12 and 24 months, against the market and against the
  names that were killed.

This record is the track record, so start it as early as possible.

### F5 — CEE ingestion (the real edge; highest effort)

- **ESEF from filings.xbrl.org:** xBRL-JSON, IFRS. The probe found 26 Slovenian
  and 88+ Croatian issuers, but recent years are thin: for Slovenia, FY2024 has 19
  filings and FY2025 only 8. Treat it as *history*, not a timely feed.
- **Timely source:** exchange announcement feeds (SEOnet for Ljubljana, the Zagreb
  exchange), polled for the same trigger types as F1, plus annual and interim
  report PDFs.
- **IFRS mapping:** the portable model reads `us-gaap` concepts. Map about 20
  `ifrs-full` concepts for F2's scorecard. No full DCF port until F2 proves useful.
- **Prices:** verify a source for LJSE/ZSE quotes before building. This is unknown.
- **Acceptance:** 10 Ljubljana/Zagreb issuers with 3-year history and scorecards.

### F6 — Deep dive (existing)

Run `company_run --live --assess` for survivors only. It is unchanged except for
the F0 WACC fix.

## 4. Stop doing

- Automating full three-statement DCFs for every candidate.
- Excel and UI polish beyond what reviewing a brief needs.
- Adding US universe coverage for its own sake.

## 5. Order and success criteria

**Order:** F0, then F1, F2 and F4 together (the free core, about 1–2 weeks), then F3,
then F5.

**Success after 8 weeks:**
- briefs arrive weekly without manual model work;
- the median time to kill is under 30 minutes;
- the decision log has 60 or more entries with scored forecasts running.

## 6. Risks

- **Triggers are noisy.** Tune thresholds against Patrik's kill rate, not returns.
- **Brief quality depends on retrieval.** Keep retrieval bounded and cite everything.
- **CEE data gaps** (timeliness, prices, IFRS mapping) may cap F5. Confirm sources before coding.
- **Personal trading.** Check the Forvis Mazars independence and personal-trading policy, and Capital IQ licence terms, before using either for this.
