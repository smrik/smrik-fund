# Spreadsheet engine compatibility decision

Status: P1 passed after R1 and parent acceptance. Select Mog 0.10.7 for the
tested code-defined formula subset; new modeling capabilities still need tests.

The bounded proof pins `@mog-sdk/sdk` **0.10.7** in
`scripts/spreadsheet_compat/package.json` and uses the native Node entrypoint.
The fixture is fictional USD millions data and makes no MSFT policy decision.
The generated workbook contains linked income, cash-flow, balance-sheet and
perpetual-growth DCF formulas, editable revenue, a cell note, a trusted
workbook-local `HYPERLINK("#'Decisions'!A1",...)` formula, units, and number
formats. Formula-shaped source labels are written through Mog's literal path.

The installed Excel acceptance environment is Microsoft Excel x64, version
16.0.20326.20132 (COM reports `16.0`). A newly created invisible Excel
instance opened a disposable copy, ran `CalculateFullRebuild` with iteration
disabled, edited revenue from 100 to 120, and saved a separate edited copy.
Mog and Excel agreed with the independent fixture values at tolerance `1e-8`:

| case | EBIT | Net income | Closing cash | Balance difference | UFCF | EV | Equity value | Per share |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| base | 30 | 20.25 | 40.25 | 0 | 22.5 | 281.25 | 271.25 | 27.125 |
| revenue = 120 | 38 | 26.25 | 46.25 | 0 | 28.5 | 356.25 | 346.25 | 34.625 |

The proof also confirmed formula retention after XLSX export, cell notes,
Excel navigation from the workbook-local formula target to `Decisions!A1`,
literal `=1+1`, `+1+1`, `-1+1`, and `@SUM(1,2)` labels with `HasFormula=false`,
number formats, absence of formula errors in the base model, detection of a
broken reference (`#REF!`), and byte-identical publication after an
interrupted candidate build. No production valuation code or paid LLM calls
were used.

The initial custom `internal://decision/P1` URI was rejected because it did not
navigate to workbook evidence. R1 replaces it with the tested workbook-local
formula target. Excel COM does not expose formula hyperlinks in its
`Hyperlinks` collection; the verifier derives the target from the trusted
formula and uses Excel workbook navigation to confirm `Decisions!A1`. The parent
then independently used native `Workbook.FollowHyperlink` with the same workbook
and formula destination, reaching `Decisions!A1` from the Inputs sheet. A fresh
revenue=110 edit produced per-share value 30.875 and balance difference zero;
literal source text stayed literal and the published fixture stayed unchanged.
Evidence: `data/build-guide-p1/parent-sample.json`; reproducible bounded sample:
`Lunacy/runs/three-statement-dcf/phases/engine/parent-sample.ps1`.

Use application-authored HYPERLINK formulas for workbook navigation and
`setCell(..., { literal: true })` for source labels/excerpts. Direct Mog hyperlink
metadata with a workbook-local target was not compatible with this Excel export.
The SDK is the calculation engine; Excel is the local acceptance/review target.
Actual COM validation needs the user's Windows desktop session; sandbox startup
returned 80070520, while the bounded authorized desktop run passed.

Primary references: [Mog README](https://github.com/fundamental-research-labs/mog),
[Mog SDK guide](https://github.com/fundamental-research-labs/mog/blob/main/docs/guides/sdk.md).
