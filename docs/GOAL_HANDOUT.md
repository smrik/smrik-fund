# What this product is for

Python is the workbook. The model is the analyst.

The analyst looks at common-size statements (vertical and horizontal), notices what actually stands out, opens the notes for those items only, and only then changes the workbook: adjust an existing line, add a line, or add segment detail. Totals have to keep reconciling. Reported numbers never get rewritten. Forecasting starts after that workbook exists. Not before.

That is the whole V1 loop. Not a second investigation engine. Not a review bureaucracy. Not a company-specific recipe for Microsoft.

Approval of a candidate, right now, is not the problem. If the reviewer already said the item is real and quantified, put it on the adjusted statement and move on.

## The loop, in order

1. Load the filing and build the reported P&L.
2. Compute common-size and year-over-year movements in Python.
3. The model flags outliers worth digging into.
4. Search the notes (filing prose), not just the statement tables.
5. Propose a change only from that evidence.
6. Apply the ones that survive review (accept, or revise with an amount). Leave rejects off.
7. Recalculate subtotals. Keep reported vs adjusted separate. Show new lines and segments as children, not as plugs.

If step 4 did not happen, step 6 must not happen.

## What is actually in the code now

`smrik-fund run TICKER` is the path: scan → literal notes retrieve → analyst → reviewer → apply accept/revise.

Retrieve no longer dies just because a common line label hits many times. It ranks longer note-like excerpts and keeps a bounded packet. Question-only scan findings search the affected line label, not a hardcoded issuer phrase.

The working statement (`adjusted_pnl.csv`) can hold:

- a changed parent line (reported copy stays in `analytical_pnl.csv`);
- a named added line under that parent (`is_breakdown`, not in subtotals);
- segment children under revenue / operating income.

Live MSFT (`data/e2e-live-apply2-20260904`): scan found the other-income swing without being told “OpenAI”; the packet contains the 10-K dilution sentence; Other income FY26 $10,697M → $4,197M; FY25/FY24 OpenAI losses also stripped; mix/YoY “adjustments” stayed off; recon 12/12.

Live GOOGL (`data/e2e-live-googl-20260904`): same loop, no Google-specific code. Scan found the other-income jump and the G&A spike. Notes named equity-securities gains (~$24B) and the EC fine / legal accruals. That run was before accept/revise auto-apply, so those items were still sitting in review. Alphabet has no Gross profit line, so GP/OI recon skips instead of inventing a row.

Frozen proof: `tests/test_msft_golden_run.py` drives `run` and now expects the OpenAI line to be applied without a human `review` click.

## Where the goal was most missed

The work kept sliding off the analyst loop and into software that feels like progress.

**The change never landed.** For a long time the loop stopped at “human review”. Materiality, shadow auto-approve, and the review CLI were treated as the product. They are not. The product is the adjusted workbook after notes. Approval is currently a formality.

**Notes search was replaced by a second novel.** `filing_investigation.py` (thousands of lines) tried to *explain* movements. Scan already said what moved. The missing tool was: go get the note. Two worklists still exist (`run` uses scan; `analyze --adjustments` still uses discovery).

**Scan writes questions. Retrieve needs filing phrases.** The model asks “what comprised other income?” Python then searches the line label. That can return the right note (it did for OpenAI), but it also returns tables and generic hits. The analyst is supposed to choose what to search. Python should not invent issuer queries, and it also should not pretend a P&L stub is a note.

**Not everything that stands out gets booked.** Mix-shift and pure YoY line changes are correctly rejected. Items with no dollar amount (FX “2%”) cannot be applied. That is fine. What was not fine: a disclosed, quantified OpenAI gain sitting unapplied because the reviewer said `revise` instead of `accept`. That is now applied on the scan path. Recurring mark-to-market (Google equity gains) vs a one-off fine is still a judgment call for the model, not a hardcoded list.

**Microsoft was treated as the taxonomy.** Golden amounts, Xbox search regex, “the known case” as architecture. The mechanics have to survive a ticker change. GOOGL already showed the statement shape is not MSFT: no Gross profit, different labels. Do not special-case Microsoft to make recon look clean.

**Infra ate the sessions.** Eval harness, procedural investigation, identity repairs, while the artifact (adjusted operating earnings with a few note-grounded lines) barely moved. If a session does not change the workbook or reject a bad proposal, it missed.

## What “done” looks like for this loop

For a new ticker, with no issuer recipe in Python:

- common-size outliers show up;
- the notes for those outliers are actual filing sentences;
- disclosed, quantified, non-recurring items are on the adjusted P&L as parent deltas and/or child lines;
- segments that exist in the filing sit under their parents;
- reported figures are untouched;
- recon does not plug;
- junk YoY “the line went up so strip it” does not get booked.

Forecasting is next, not now.
