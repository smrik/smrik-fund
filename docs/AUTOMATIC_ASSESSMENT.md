# Automatic company assessment

`company_run --live --assess` runs free financial diagnostics, Sol research
planning, isolated Luna investigations, Sol synthesis, calculated statements,
independent review and an IC summary. The application agents
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
3. Compute historical ratios and a provisional DCF using the same workbook engine
   as the final model. Stress each driver separately. Rank the maximum absolute
   change per share relative to the market price. Historical ranges, minimum
   stresses, blocked cases and unsupported mechanisms remain explicit. Ranges are
   exploratory, not confidence intervals; effects must not be added together.
4. Sol receives the company model, historical trends, calculated diagnostics and
   the full latest frozen 10-K and 10-Q narratives, with hashes and line ranges.
   Missing forms are explicit. It chooses up to eight ranked questions and explains
   why each matters; every remaining driver/gap requires an omission reason.
5. A separate Luna request investigates each question. It receives a short company
   context, its brief, selected diagnostics and relevant source excerpts. It cannot
   see other investigators' findings. Deterministic literal retrieval diversifies
   phrases/source editions and avoids overlapping windows. Each investigator may
   request one follow-up search; unmet research needs remain recorded. The calls
   execute serially under the existing budget ledger; context isolation does not
   require concurrent execution.
6. Sol synthesizes findings, reconciles contradictions and overlapping adjustments,
   chooses supported controls, records a basis for every control and
   assesses twelve financial areas. All citations must be supplied evidence IDs.
   Forecast tax can differ from the historical effective rate; the reported tax
   amounts remain unchanged. Forecast cost ratios are assumptions, not rewritten
   historical facts.
   Every question receives an adoption/rejection/unresolved decision with affected
   controls. Sol also supplies explicit downside/upside control scenarios.
7. Build the linked statements, DCF and selected scenarios. The independent Sol
   reviewer sees current controls, evidence, schedules and scenario results. One revision and
   recalculation is allowed. An unresolved rejection stops publication.
8. Verify the accepted model in native Excel, then Sol generates the IC brief from
   saved evidence and calculated results. A separate Sol review corrects factual,
   accounting and citation errors in the brief. Neither IC stage changes controls.

Read `IC-reviewed.md` first, then `ASSESSMENT.md` for assumptions and coverage. The workbook
is under `reviewed/`. `research-packet.json` contains the exact source excerpts;
requests, raw responses, structured decisions and receipts record each paid
stage. `assessment-audit.json` binds the research and draft reports;
`ic-review-audit.json` binds the independent IC revision without overwriting the
original brief. Run
`smrik-fund daily audit <run-directory>` to verify saved artifacts.

Read `diagnostics/DIAGNOSTICS.md` for the initial ranking. `research.structured.json`
contains Sol's agenda; `question-NN.evidence.json` and `question-NN.result.json`
preserve each investigation. `ASSESSMENT.md` connects questions, findings, synthesis
decisions and scenario outcomes. The assessment audit binds these files, diagnostic
workbooks and scenario calculations, in addition to requests, responses and receipts.

Run just the free diagnostics:

```powershell
.venv/Scripts/python.exe -m smrik_fund.company_diagnostics `
  --case-dir data/history/20260919/BBWI/source `
  --output-dir data/diagnostics/my-bbwi-check
```

Use a new output directory. This command captures a dated quote and does not load
an API key or invoke an LLM. The default model is an explicitly provisional starting
point, not a normalized investment case. Diagnostic SBC/capex/working-capital and
aggregate-expense stresses affect forecasts only and restore to zero before export;
they do not silently add new analyst controls or rewrite historical facts.

Research is bounded: each retrieval pass supplies up to six nonoverlapping windows
and 20,000 characters per question; individual windows above 12,000 characters are
excluded with a count. A matching excerpt is not proof of exhaustive coverage. Full
annual/interim narratives are not silently truncated: oversized byte estimates use
the provider's token-count endpoint, saved and bound to the exact request. Admission
still enforces the current context/price tier and reserves the output allowance.
There are
no earnings-call transcripts, peer research, 8-K earnings releases or live
discount-rate research in this path. Rates and beta remain labeled estimates.
The model has constant annual growth and consolidated operating assumptions;
seasonal working capital, debt refinancing and asset lives remain simplified.
Agents must state these limits and reject consequential unsupported treatments.

Mechanical success, independent model acceptance and an IC research priority are
separate from human investment approval. A failed run retains its requests and
responses; it is not silently retried or relabeled as completed.
