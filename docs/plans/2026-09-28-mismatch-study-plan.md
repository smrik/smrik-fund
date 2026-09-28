# Mismatch study: coding plan

> **One question:** among apparently cheap, neglected companies, what visible
> signals separated the ones where the gap closed from the value traps?
>
> **Rules for working through this:**
> - Do one step at a time. Each step fits in one sitting.
> - Every step ends with something you can *see*: a file, a table or a number.
> - If you're stuck for more than 20 minutes, write the blocker in `NOTES.md` and move to the next ☐.
> - Don't polish anything. Ugly is fine until Step 6.

---

## Map (read this once, then only look at the current step)

```
0 Setup ─► 1 Capital IQ export ─► 2 Load ─► 3 Quadrants ─► 4 Lift table ─► 5 Case studies ─► 6 Holdout test
  30 min     2 × 1 h (manual)     1 h      1 h           1–2 h          3 × 1 h          1 h
```

🎯 **First win is Step 3:** a 2×2 table of real companies. Everything before it
is plumbing.

---

## Step 0: Setup (30 min)

☐ **0.1** Create the folder `data/mismatch/` (git-ignored). Raw exports go in `raw/`, outputs in `out/`.

☐ **0.2** Create two empty files:
- `src/smrik_fund/mismatch.py`
- `tests/test_mismatch.py`

☐ **0.3** Create `data/mismatch/NOTES.md` with today's date and the one question above.

✅ **Done when:** `uv run pytest tests/test_mismatch.py` runs (0 tests is fine).

---

## Step 1: Capital IQ export (manual, 2 sessions × 1 h)

**Session A: build the screen once and save it.**

☐ **1.1** Company status: **include inactive** companies (acquired, out of business).
This is the most important setting. Without it, the whole study is biased.

☐ **1.2** Filters, fixed as of the start date:
- Exchanges: start with the **US** list. CEE comes later.
- Market cap: $50m–$2bn.
- Exclude financials and REITs.

☐ **1.3** Fields to export (one row per company):

| Field | Why |
|---|---|
| Capital IQ ID, ticker, name, exchange, country | join keys |
| Company status and status date | acquired or bankrupt |
| Market cap at start date | size |
| TEV / EBIT at start date | cheapness |
| Price / tangible book at start date | cheapness |
| Net debt / EBITDA at start date | survivability |
| # analyst estimates at start date | neglect |
| EBIT margin, ROIC: start year and start + 3 | business outcome |
| Total return, start → start + 3 years | price outcome |

**Session B: export.**

☐ **1.4** Export start years **2012–2019**, one file per year: `raw/us_2012.csv` and so on.

☐ **1.5** Export Key Developments (events) for the same companies, 2011–2022: `raw/us_events.csv`.
Event types: spin-off, buyback, executive change, activist, asset sale, M&A target.

☐ **1.6** Write in `NOTES.md` the exact screen name, date exported, and any row limits you hit.

✅ **Done when:** 8 year files and 1 events file are in `raw/`.

⚠️ If an export hits a row cap, split by market-cap band (for example $50m–$300m and $300m–$2bn).
Don't reduce the universe.

---

## Step 2: Load (1 h)

☐ **2.1** `load_cohort(path, start_year) -> DataFrame`:
- one row per company;
- rename columns to snake_case;
- add a `start_year` column;
- **keep missing values missing** (no `fillna(0)`).

☐ **2.2** `load_events(path) -> DataFrame` with columns
`company_id, event_type, event_date`.

☐ **2.3** One test: a tiny hand-made CSV (3 rows) loads with the right columns, and a
missing value stays `NaN`.

✅ **Done when:** a notebook cell prints the row counts per year and the share of
inactive companies. Write both numbers in `NOTES.md`.

---

## Step 3: Quadrants (1 h) 🎯

☐ **3.1** `cheap_cohort(df)`: keep the cheapest 20% by TEV/EBIT within each start year.
Drop negative EBIT, and count how many you dropped.

☐ **3.2** `outcome(df)` adds two booleans:
- `business_improved`: ROIC or EBIT margin at start + 3 is higher than at start.
- `rerated`: the 3-year return beats that year's median cohort return.

☐ **3.3** `quadrant(df)` labels each company using those two booleans:

| `business_improved` | `rerated` | Label |
|---|---|---|
| True | True | `closed` |
| False | False | `trap` |
| True | False | `unrewarded` |
| False | True | `lucky` |

☐ **3.4** Status rules:
- Bankrupt counts as `trap`.
- Acquired counts as `rerated = True` only if the deal price beat the median.
  Otherwise mark it `unknown` and count it.

☐ **3.5** Tests: 4 hand-made companies, one per quadrant, get the right labels.
One bankrupt company becomes `trap`.

✅ **Done when:** `out/quadrants.csv` exists, and you've written the 2×2 counts in
`NOTES.md`. 🎉

---

## Step 4: Lift table (1–2 h)

☐ **4.1** `features(df, events)` adds true/false columns, each **as of the start date only**:

| Feature | Rule |
|---|---|
| `spinoff` | spin-off event in the 12 months before start |
| `buyback` | buyback event in the 12 months before start |
| `exec_change` | CEO or CFO change in the 12 months before start |
| `activist` | activist event in the 12 months before start |
| `asset_sale` | asset sale in the 12 months before start |
| `neglected` | 0–1 analysts |
| `net_cash` | net debt below 0 |
| `high_leverage` | net debt / EBITDA above 4 |

☐ **4.2** `lift(df, feature)` computes two ratios:
- winner lift = `P(feature | closed) / P(feature | cohort)`;
- trap lift = `P(feature | trap) / P(feature | cohort)`.

Also report counts (n), so small samples are visible.

☐ **4.3** Test: a synthetic cohort where the feature appears only in `closed` gets
a winner lift above 1 and a trap lift of 0.

☐ **4.4** Use **2012–2017 only**. Don't look at 2018–2019 yet. That's Step 6.

✅ **Done when:** `out/lift.csv` exists. Write the top 3 and bottom 3 features in
`NOTES.md`, with n.

---

## Step 5: Case studies (3 sessions × 1 h)

☐ **5.1** Pick 10 `closed` and 10 `trap` companies that share a strong feature
from Step 4, so the pairs are contrasting.

☐ **5.2** For each company, have the LLM (or you) fill **one** row:

| Company | What changed in the 3 years | Was it visible at the start? (source) | What judgement call would have caught it |
|---|---|---|---|

Hindsight is fine *here*. You're generating hypotheses, not testing them.

☐ **5.3** Group the rows into 3–5 patterns, for example "capex hiding improving economics."

✅ **Done when:** `out/patterns.md` lists the patterns, each with examples.

---

## Step 6: Holdout test (1 h)

☐ **6.1** Turn each pattern into a rule that uses only Step 4 features.

☐ **6.2** Run the rules on the **2018–2019** start years, which you haven't looked at.

☐ **6.3** For each rule, compare the share landing in `closed` against the cohort's base rate.

✅ **Done when:** `out/holdout.csv` exists. Write a one-line verdict per rule: holds or fails.

---

## Later (don't start these yet)

- Rerun Steps 1–6 for **CEE** (Ljubljana, Zagreb, Warsaw, Prague). The same code
  should work with new raw files.
- Surviving rules become triggers in the situation funnel
  (`2026-09-28-situation-funnel-plan.md`, F1).
- Thesis: this is its methods chapter.

## Guardrails

- The Capital IQ academic licence is for research only. This study qualifies; a
  live fund feed probably doesn't.
- Missing values stay missing. Unknowns are counted, never dropped silently.
- Leave 2018–2019 untouched until Step 6.
