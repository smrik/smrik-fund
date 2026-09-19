# Reading the company workbook

New captures request five annual 10-Ks and the latest subsequent 10-Q. Annual
history uses the latest available comparative presentation per statement and
period within the frozen cutoff. Missing and ambiguous observations stay blank;
older frozen cases need a fresh capture for more history.

Income, BalanceSheet and CashFlow own the forecast calculations. Percentages
appear alongside the projected amounts. Inputs remains the editable assumption
register. Assets and WorkingCapital contain supporting roll-forwards. There is
no generic Schedules tab. Black formulas calculate locally; green formulas link
between worksheets.

Flow statements compare annual history, TTM and full annual forecasts. Balance
sheets use dated balances. Stub contains only the future remainder of the current
fiscal year; DCF discounts it separately. The first full-year forecast grows the
current YTD plus that remainder, not TTM revenue. Historical DCF columns provide
context and are never discounted as future cash.

## BBWI example

Measurement: August 1, 2026. Information cutoff: September 16, 2026.
Amounts: USD millions, from frozen EdgarTools statement DataFrames.

| Issuer fiscal year | Revenue | EBIT | Reported net income |
| --- | ---: | ---: | ---: |
| FY2021 | 7,882 | 2,009 | 1,333 |
| FY2022 | 7,560 | 1,376 | 800 |
| FY2023 | 7,429 | 1,285 | 878 |
| FY2024 | 7,307 | 1,266 | 798 |
| FY2025 | 7,291 | 1,126 | 649 |

FY2023 has 53 weeks. FY2021-22 net income includes discontinued operations.
Reported components and exact dates remain visible; this is not a normalized,
constant-scope earnings series.

History retains source signs and the annual/current-YTD/prior-YTD bridge.
Comparable tax expense is derived from the checked earnings bridge; the original
signed tax remains separate. Evidence identifies the filing, CSV record, concept,
period, source URL and conversion to millions. Derived groups have explicit
calculation bases. Historical NWC movements do not claim to reconcile reported
CFO. Cash FCF in this model means CFO + CFI.

The operating forecast uses separate COGS, SG&A and R&D ratios when the available
components reconcile to EBIT in every FY/YTD period. A disclosed gross-profit
subtotal must also reconcile. Missing, ambiguous or incomplete detail selects
the aggregate expense method with an explicit reason; no residual cost is made
into a forecast driver. Reported signs remain in Evidence; expense magnitudes
and their sign conversions are recorded separately.

Income now shows revenue, COGS, gross profit, SG&A/R&D, total costs, embedded D&A,
EBITDA, scheduled D&A, EBIT, taxes and net income. Ratios sit beside the costs.
Blue `cogs_ratio`, `sga_ratio` and `research_ratio` cells in Inputs are editable
where supported; these keys also work in the existing free operator-assumptions
JSON. Existing assumption files inherit the new ratios from reconciled TTM.
Unsupported controls are rejected. Edits invalidate the attached review.

Gross profit retains the historical embedded-D&A allocation. The model removes
aggregate D&A once before EBITDA and deducts scheduled depreciation/amortization
once afterwards. It does not claim to know the split of D&A between cost lines.
EBITDA is an EBIT-plus-disclosed-D&A proxy, not issuer-adjusted EBITDA. SBC remains
expensed for valuation. These development policies remain provisional.

The rebuilt workbook is at:
data/workspace/runs/20260919-bbwi-cost-drivers/reviewed/BBWI.xlsx

Its 572 forecast values match the preceding BBWI model within tolerance, and its
provisional value remains $41.4706/share. Native Excel checked those values plus
90 operating-build values and 176 historical values, found zero formula errors
and passed beta and cost-driver edits/restoration. All eight source/workbook audit
checks passed. No paid calls were made.

| USD millions | TTM | FY2027 forecast |
| --- | ---: | ---: |
| Revenue | 7,209.00 | 6,980.21 |
| Cost of revenue | 4,028.00 | 3,900.16 |
| SG&A | 1,975.00 | 1,912.32 |
| EBITDA proxy | 1,452.00 | 1,405.92 |
| EBIT | 1,206.00 | 1,244.47 |

TTM expense ratios: COGS 55.8746%, SG&A 27.3963%. Increasing COGS by one
percentage point reduces FY2027 EBIT by $69.80m and changes cash flow, balance
sheet and DCF. Historical observations remain unchanged.

Frozen-case tests support separate costs for BBWI, NVDA and COST. LULU, HPQ and
GOOGL retain aggregate expenses because their selected face components are
incomplete or do not reconcile. The broader existing tests also cover AAPL,
AMZN, KO and HD. This is tested coverage, not a claim of universal modeling.

## Code map

- company_case.py freezes the annual and interim filings.
- company_history.py selects annual observations and source bindings.
- company_operating.py checks expense composition and records sign conversions.
- portable_model.py attaches history to the current financial model.
- company-workbook.mjs authors forecast equations, valuation and checks.
- company-statements.mjs places equations on their statements and aligns periods.
- format-company-workbook.ps1 formats and recalculates the saved XLSX, compares
  values, scans formula errors and verifies edit invalidation.

tests/test_company_history.py covers source editions, exact periods, missing
values, signed facts, tax reconciliation and five-year capture depth. Its local
BBWI test inspects exported XLSX formulas as well as in-memory calculations;
this catches missing driver cells in a sparse export.

## CFA reference and remaining financial detail

Reviewed the user-provided Blu Containers Model - Vertical Complete_Ex.xlsx
read-only. It places revenue/cost builds, three statements and depreciation,
tax, working-capital, debt/interest and equity schedules vertically on one Model
sheet, with consistent historical/forecast columns and local percentage/days
calculations. Its assumptions and scenario selector are separate.

The current workbook adopts aligned periods, visible drivers, local statement
formulas, linked balances/cash flows and explicit source/check tabs. It does not
yet implement the CFA example's price/volume production model, straight-line
capex vintages, detailed current/deferred tax, revolver repayment waterfall or
separate retained-earnings/share-capital schedules. Those require explicit
issuer-specific drivers and policies. The current financing and expense
simplifications remain labeled; the reference's company-specific assumptions
are not copied into other companies. No reference workbook was modified.


## Verification for the operating-cost increment

`pytest -q tests/test_company_operating.py tests/test_company_history.py
 tests/test_company_model.py tests/test_portable_model.py` produced 54 passes and
one outdated test assertion. The corrected sign-preservation assertion and three
other pure expense tests then passed (`-k 'not real_cost'`). There are 56 unique
passing tests after adding annual-only/control-bound coverage. No unresolved
failures. Ruff, JavaScript syntax and whitespace checks pass. Native proof and
source audit are beside the workbook; the exported Income and DCF were rendered
and visually inspected.

Cash-tax timing, fixed refinancing, aggregate working-capital balances and the
existing declining-balance asset method are unchanged in this increment.


## Editable Excel template (2026-09-19)

[Open the template guide](../templates/README.md). The reusable workbook is
`templates/company-model.xlsx`, paired with its original JSON contract. Excel row
insertions and forecast formula edits now feed future UI/CLI runs. Source history
and accounting/valuation checks stay generated. The default template has no
financial overrides; the example company data is replaced on each run.

Every run freezes the template/contract, records the changed cells, relocates
statement references and validates the final formulas in the formula engine and
native Excel. Source/audit edits, broken anchors, unavailable inputs and incompatible
forecast horizons stop rather than silently reuse another company's data.

Proof: two rows inserted in native Excel add an operating expense of 0.5% of
forecast sales. BBWI's FY2027 EBIT falls by $34.901m and its provisional value moves
from $41.4706 to $39.8646/share. The same file passed NVDA with shorter history;
AAPL's additional revenue rows also pass the regression. This scenario is only in
test copies, not the default template.

18 focused template tests pass, including a simulated analyst/reviewer revision
cycle. The broader initial history/model/workbench run had 43 other passes; its
one new negative-test failure exposed an unhelpful subprocess exception, now
replaced by a preserved blocked snapshot and a useful calculation error.
No live LLM call was made during this increment. LLMs still select supported
numeric controls; human-authored template edits change model formulas/structure.
