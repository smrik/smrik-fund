# Automatic company assessment

`company_run --live --assess` runs filing research, an analyst, calculated
statements, an independent reviewer and an IC summary. The application agents
select financial assumptions. Python and the spreadsheet engine apply supported
methods; the operator does not supply company-specific corrections.

```powershell
.venv/Scripts/python.exe -m smrik_fund.company_run BBWI `
  --case-dir data/history/20260919/BBWI/source --as-of 2026-09-16 `
  --output-dir data/workspace/runs/my-new-assessment `
  --price-dir data/pricing/2026-09-20 --live --assess
```

Use a new output folder, a current verified price snapshot, and an existing budget
ledger with sufficient remaining funds. The example reuses filings frozen through
September 16; the market observation has its own date. To capture a new SEC case,
omit `--case-dir` and provide the desired `--as-of` date. The date on the pricing
folder is illustrative, not automatically rolled forward. The free screener and
ordinary model runs never opt into paid analysis.

1. Validate the frozen SEC files and preserve five-year statement history.
2. Capture a USD quote with an explicit market timestamp. Missing, stale or
   mismatched quotes stop the assessment instead of becoming guessed prices.
3. Give the research agent the latest filing narrative, with source hashes and
   line ranges. It can request eight questions, each with up to three literal
   search phrases across the frozen filings.
4. The analyst chooses supported controls, records a basis for every control and
   assesses twelve financial areas. All citations must be supplied evidence IDs.
   Forecast tax can differ from the historical effective rate; the reported tax
   amounts remain unchanged. Forecast cost ratios are assumptions, not rewritten
   historical facts.
5. Build the linked statements and DCF. The independent reviewer sees the current
   calculated controls, source evidence and schedules. One complete revision and
   recalculation is allowed. An unresolved rejection stops publication.
6. Verify the accepted model in native Excel, then generate the IC brief from the
   saved evidence and calculated results. A separate reviewer corrects factual,
   accounting and citation errors in the brief. Neither IC stage changes controls.

Read `IC-reviewed.md` first, then `ASSESSMENT.md` for assumptions and coverage. The workbook
is under `reviewed/`. `research-packet.json` contains the exact source excerpts;
requests, raw responses, structured decisions and receipts record each paid
stage. `assessment-audit.json` binds the research and draft reports;
`ic-review-audit.json` binds the independent IC revision without overwriting the
original brief. Run
`smrik-fund daily audit <run-directory>` to verify saved artifacts.

Research is bounded: the latest narrative is capped at 105,000 characters, with
truncation disclosed; retrieval adds at most 30,000 characters and three windows
per question. A matching excerpt is not proof of exhaustive coverage. There are
no earnings-call transcripts, peer research, 8-K earnings releases or live
discount-rate research in this path. Rates and beta remain labeled estimates.
The model has constant annual growth and consolidated operating assumptions;
seasonal working capital, debt refinancing and asset lives remain simplified.
Agents must state these limits and reject consequential unsupported treatments.

Mechanical success, independent model acceptance and an IC research priority are
separate from human investment approval. A failed run retains its requests and
responses; it is not silently retried or relabeled as completed.
