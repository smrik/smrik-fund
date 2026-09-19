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

The forecast still uses consolidated operating expenses. Historical COGS/SG&A
detail is shown where available, but no separate future allocation is invented.
Other existing development assumptions remain provisional.

The rebuilt workbook is at:
data/workspace/runs/20260919-bbwi-history-final/reviewed/BBWI.xlsx

Its 572 forecast values match the preceding BBWI model within tolerance, and its
provisional value remains $41.4706/share. Native Excel checked those values plus
161 historical values, found zero formula errors and passed beta edit/restoration.
The source/workbook audit passed eight checks. No paid calls were made.

## Code map

- company_case.py freezes the annual and interim filings.
- company_history.py selects annual observations and source bindings.
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
