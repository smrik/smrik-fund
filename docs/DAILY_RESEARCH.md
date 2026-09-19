# Daily research desk

Free US equity screen → free financial checks → up to 30 research candidates →
free company briefs → optional SEC/DCF work → explicitly requested paid IC synthesis.
No LLM runs during screening, ranking, brief generation or the `daily deep` command.

## Start here

From the repository in PowerShell:

```powershell
.venv/Scripts/smrik-fund.exe daily run
```

Open the reported `index.html`. Each run has a new timestamp directory under
`data/daily`, a searchable results table, HTML/Markdown company briefs, CSV export,
calculation/evidence JSON and a frozen raw market snapshot. The default shortlist
maximum is 20; fewer names are valid. Every value seed is enriched by default.
The first full run can take several minutes; fundamentals are cached for 20 hours.

```powershell
# Up to 30 names; still no paid calls.
.venv/Scripts/smrik-fund.exe daily run --shortlist 30

# Inspect particular US-listed tickers, including non-candidates/specialist cases.
.venv/Scripts/smrik-fund.exe daily run --tickers MSFT,JPM,HPQ,O,BABA

# Faster, explicitly incomplete fundamentals coverage.
.venv/Scripts/smrik-fund.exe daily run --max-enrich 200

# Broaden the initial screen; these are user-adjustable size/liquidity defaults.
.venv/Scripts/smrik-fund.exe daily run --min-cap 500000000 --min-price 2 --min-volume 50000

# Replay saved evidence offline, without provider requests; freshness gates still apply.
.venv/Scripts/smrik-fund.exe daily run --snapshot data/daily/20260916-release/snapshot.json --output-dir data/daily/my-replay

# Compare the shortlist to a previous report.
.venv/Scripts/smrik-fund.exe daily run --previous data/daily/20260916-release/report.json
```

`--refresh` bypasses the fundamentals cache. Output directories must be new/empty.
Failures and unfetched fundamentals stay visible. A cap, provider failure or
incomplete universe capture produces a partial-coverage status. There is no
scheduled task, trading connection or order placement.

## What the free screen means

| Stage | Provisional rule |
|---|---|
| Universe | Yahoo US-region equity listings in eleven sectors; USD quotes on supported US exchanges |
| First filter | Market cap ≥USD1bn; price ≥USD3; three-month average volume ≥100k shares/day |
| Fundamental fetch seed | Positive trailing P/E ≤20 **or** positive P/B ≤2 |
| Earnings value signal | P/E ≤15 and ≥25% below the screened sector reference |
| Operating-company second signal | Vendor FCF / market cap ≥8% |
| Bank/insurer second signal | P/B ≤1.5 and ≥25% below the screened sector reference |
| Operating quality | Positive vendor FCF and operating margin; net debt/EBITDA ≤3.5; revenue growth ≥−10% |
| Bank/insurer quality | Positive earnings/book and ROE ≥10%; industrial cash-flow/EV ratios excluded |
| Automatic shortlist | Two signals, all required quality/source checks, one listing per SEC issuer, max20–30 |

The priority score is `50 × signal count + 20 if quality passes + 30 × clipped
P/E discount`. Only eligible candidates can enter the shortlist. This is an
explainable research queue, not a probability of investment success.

Sector references come from the broader first-filter universe, before cheapness
selection. They exclude the same issuer and duplicate known share classes; require
five peers; and use positive P/E ≤100 or P/B ≤20. Sector peers are broader than
true business comparables. Share-class identity uses the SEC ticker reference.
Unknown SEC identity blocks automatic escalation.

Missing inputs remain missing. Negative denominators do not create attractive
multiples. Mixed financial/quote currencies suppress monetary valuation ratios.
Preferred/warrant/unit/debt security indicators prevent common issuer ratios from
being treated as that security's valuation. Quotes older than seven days or
financial-period indicators older than 200 days block automatic escalation.

P/E below3 and a vendor net margin exceeding operating margin by more than15
percentage points require manual reconciliation. This margin check is a warning
heuristic: vendor periods may differ, so it does **not** prove a one-off or error.

The earnings sensitivity uses `EPS × P/E`: reference multiple is the lower of the
sector reference and20; stress/reference/stronger EPS factors are0.8/1/1.1 and
multiple factors0.8/1/1.1. These unvalidated scenarios are **not** fair values or
price targets. Yahoo `freeCashflow` is a vendor aggregate, not independently
reconciled owner earnings or the DCF's unlevered cash flow. Forward P/E is displayed
as an estimate and never used to rank.

## Go deeper only when useful

```powershell
.venv/Scripts/smrik-fund.exe daily deep data/daily/20260916-release HPQ --output-dir data/daily/hpq-next-deep
```

This fetches SEC annual/interim filings and attempts the existing provisional
operating-company DCF and formatted Excel with native Excel checks. It makes no
paid calls. A bank/insurer/REIT/specialist case produces a source-only result, not
an industrial DCF. Unsupported filings/classifications remain explicit blocks.
Use `--case-dir PATH` to reuse an immutable source case with today's cutoff.
Native Excel and the existing Mog workbook dependencies are required for workbook
publication. Agent-independent review is not implied by a successful free build.

Free scenarios can supply `--assumptions PATH`. The JSON must contain the full
`controls` object, a nonempty `rationale`, and a list of text `limitations`.
The run records these inputs immutably and remains `PROVISIONAL_UNREVIEWED`.
They cannot accompany live analysis, review resumption or a prior-version revision.
See the [September 19–20 weekend pack](../data/weekend/20260919/index.html) for
LULU, HPQ and BBWI examples, fresh quotes, earnings-normalization bridges,
formatted workbooks and native Excel receipts. Those DCF baselines preserve
reported TTM history, including one-offs; the separate normalized EPS scenarios
are illustrative research cases, not certified targets.

```powershell
.venv/Scripts/smrik-fund.exe daily deep data/daily/20260916-release LULU --case-dir data/weekend/20260919/LULU/base-r1/source --assumptions data/weekend/20260919/LULU/assumptions.json --output-dir data/weekend/20260919/LULU/my-scenario
```

That frozen-case example requires the September 16 cutoff. On a later day, omit
`--case-dir` to fetch a new case and refresh the quote in the assumptions.

Attach existing company models to a new desk run with repeatable `--model-dir
PATH`. File hashes are checked. Briefs show source cutoff, provisional controls,
WACC, scenario value and limitations. Old DCF scenarios never contribute to the
screening score or an asserted current-market upside.

## IC only after the free work

Prepare the packet at no cost:

```powershell
.venv/Scripts/smrik-fund.exe daily ic data/daily/20260916-release HPQ --output-dir data/daily/hpq-ic-prepared --thesis "Explain the suspected mispricing after source checks" --question "Name the unresolved issue where interpretation would help"
```

Only a ticker in the saved shortlist is eligible. The command replays the raw
snapshot to validate the selected financial evidence and verifies any attached
model. Default output is `PREPARED_NO_PAID_CALL`.

To authorize **one paid call**, run the same command with a new output directory,
`--live` and `--price-snapshot PATH_TO_CURRENT_VERIFIED_MODEL_PRICES.json`.
The existing EUR5 ledger remains the default. Pricing/FX expiry, endpoint, token
cap, remaining budget and protected reserve are checked before dispatch. No
automatic retry, batch IC calls or increase in budget. Run paid workflows serially
against this shared ledger. An unknown transport outcome retains its reservation.

The IC agent returns case for/against, source-metric references, unknowns,
catalyst-to-verify and the next work plan. Its role is interpretation of the
supplied packet; it has no browsing tools and cannot invent missing external
evidence. Outputs are marked `UNREVIEWED_IC_SYNTHESIS`. Deterministic schema and
reference checks do not establish narrative truth. The paid path was tested with
mock responses, failures and usage accounting; no live IC call was authorized or
made in this implementation run. Historical September10 price snapshots are
expired and must not be reused for a new paid call.

## Verified run — 2026-09-16

[Open the daily desk](../data/daily/20260916-release/index.html).
[All rows CSV](../data/daily/20260916-release/screen.csv).
[Evidence/calculations](../data/daily/20260916-release/report.json).
[Frozen market data](../data/daily/20260916-release/snapshot.json).

```text
2,765 provider listings
2,486 first-filter passes
1,284 value seeds under the final safeguards
1,289 fundamentals fetched; 0 failures; 0 final seeds left unfetched
72 qualifying research candidates → 30 issuer-deduplicated shortlist names
0 paid calls; EUR0 additional API cost
```

Five extra fundamentals were fetched before preferred-security safeguards were
finalized. Their raw source records remain preserved. This is not a count of all
US stocks: size/liquidity filters, vendor classifications and availability limit
the universe. Snapshot pages were fetched over an interval, not atomically.

Illustrative report excerpt; **research leads, not buy recommendations**:

| Ticker | Route | Trailing P/E | Vendor FCF yield | What needs checking |
|---|---|---:|---:|---|
| BBWI | Operating | 4.39 |22.7%| Sustainable cash flow, retailer demand and balance-sheet claims |
| LNC | Insurance | 3.58 |Not applicable| Sustainable earnings/book, reserves and required capital |
| OTEX | Operating | 9.04 |24.1%| Vendor cash-flow normalization, debt and business durability |
| CRI | Operating | 5.45 |23.0%| Demand trajectory and maintenance capex |
| HPQ | Operating |12.51 |11.5%| Source reconciliation, hardware cyclicality and DCF assumptions |

[HPQ free brief](../data/daily/20260916-release/briefs/HPQ.html).
[HPQ formatted workbook](../data/daily/20260916-hpq-deep-r2/reviewed/HPQ.xlsx).
[Native Excel proof](../data/daily/20260916-hpq-deep-r2/native-excel-proof.json).
[Prepared IC packet](../data/daily/20260916-hpq-ic-packet/packet.json).

HPQ source measurement2026-07-31, cutoff2026-09-16. The new cash fallback requires
note-sourced unrestricted cash and **explicitly reported zero** restricted cash
reconciling to the balance-sheet aggregate. HPQ reports USD4,169m unrestricted
cash and zero restricted cash at that date. Missing, ambiguous, wrong-currency
or nonzero restrictions block this fallback.

HPQ's unreviewed default DCF scenario is USD60.4919/share, not a target. Native
Excel checked572 schedule values; max difference1.24e-10 USDm; beta edit/restoration
PASS. Existing MSFT/AAPL and reviewed multi-ticker workbooks were preserved.

Validation:78 focused tests and9 subtests PASS; changed-code Ruff PASS. Native
Excel and headless browser render checked. API ledger unchanged:67 historical
calls, EUR2.9363062497 committed including prior holds; zero daily IC calls.

## Coverage still to build

This broadens **screening** coverage; universal full valuation is not complete.
REIT AFFO/NAV, bank/insurer equity models, other financial businesses,
loss-making companies, foreign reporting forms/currencies and complex claims
need dedicated deep methods. The initial value seed can miss genuinely cheap
high-growth/high-multiple companies. Such tickers can still be inspected through
the explicit watchlist. Missing-source cases are visible rather than forced
through a generic DCF. No human investment-policy approval is claimed.

Provider implementation references:
[yfinance screening API](https://ranaroussi.github.io/yfinance/reference/api/yfinance.screen.html),
[supported query fields](https://ranaroussi.github.io/yfinance/reference/api/yfinance.EquityQuery.html),
[SEC developer resources](https://www.sec.gov/about/developer-resources).
