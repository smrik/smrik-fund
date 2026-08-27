# G1c final-state re-gate — deterministic analytical base

Read-only final-state re-gate after R3. No gate approval issued; G2/Sol remains
authoritative for the final decision.

## Snapshot and terminal proof

- Baseline `f2fd305`; task surfaces are `src/smrik_fund/ingestion/statements.py`
  (`208` additions / `46` deletions = `+162` net production lines) and
  `tests/test_analytical_pnl.py` (`+162` test lines). Production delta remains
  within the run's 150–200-line bound.
- Sol inspection slices: eligibility/text guards `statements.py:165-192`;
  numeric guards `:194-245`; canonical `prepare_pnl` path `:250-382`;
  preservation/current metrics tests `test_analytical_pnl.py:118-207`;
  growth/CAGR/missing `:209-271`; common-size/R3 eligibility `:273-345`;
  margin bps `:347-369`; save path `:378-400`.
- Bounded final check (no broad suite rerun):
  `$env:PYTHONPATH='src'; & 'C:\Users\patri\miniconda3\envs\ai-fund\python.exe' -m pytest tests/test_analytical_pnl.py -q -p no:cacheprovider`
  -> **11 passed**, 3 existing warnings. Targeted Ruff -> **All checks passed**;
  targeted `git diff --check` -> **exit 0** (existing line-ending warnings).

## Acceptance mapping (all 12)

1. Positive growth/absolute YoY: `statements.py:194-218`; tests `:213-222`.
2. Zero prior growth null/absolute retained: tests `:237-246`.
3. Negative-to-negative growth null/absolute retained: tests `:224-230`.
4. Sign-change growth null/absolute retained: tests `:231-235`.
5. Percent of revenue: `statements.py:313-325`; tests `:191-195`, `:280-285`.
6. Percent-of-revenue bps: `statements.py:326-334`; tests `:286-291`.
7. Positive-endpoint two-year CAGR: `statements.py:302-311`; tests `:213-222`.
8. Zero/negative/missing CAGR endpoints null: tests `:224-235`, `:248-271`.
9. Gross/operating margin bps: `statements.py:336-380`; tests `:347-369`.
10. Missing remains null: `statements.py:194-245`; tests `:261-271`.
11. EPS/share rows omit common-size metrics: `statements.py:171-192`; tests `:293-334`.
12. Reported values/source frame unchanged: `statements.py:264-281`; tests `:118-152`.

## Repairs, scope, and real MSFT evidence

- A1 is present: `_text()` separator stripping (`statements.py:165-168`) plus
  label-only `Shares outstanding` null assertions (`test_analytical_pnl.py:293-334`).
- R2 is present: explicit missing FY26 CAGR null assertion (`tests/test_analytical_pnl.py:261-271`).
- R3 is present: generic standard-concept share/EPS labels are excluded while
  monetary `GrossProfit` with label `Gross margin` remains eligible
  (`statements.py:175-191`; tests `:293-345`).
- No LLM, adjustment, identity, review, or reconciliation logic changed; source
  values/canonical input data remain untouched. Only bounded `prepare_pnl`
  derived-context code/tests changed; unrelated dirty `main.py`, adjustment-test,
  and annotation artifacts remain preserved.
- Read-only MSFT evidence: input `21x19`; output `21x65`; FY26/FY25/FY24; source
  unchanged; reconciliation **12/12 PASS**; GrossProfit label `Gross margin`;
  FY26 percent-of-revenue `0.6794409337`; probe `repair-3-report.md:24-38`;
  sample `terminal-verification.md:39-55`.

## Concrete residual for G2/Sol

`data/MSFT/03_output/analytical_pnl.csv` remains `21x34` with no new metric
headers, while current in-memory output is `21x65`. Therefore Task-2's
“analytical_pnl.csv written” acceptance is not evidenced by the persisted
artifact. Refresh was not authorized and remains out of scope; this is the only
concrete acceptance blocker/tension. Detailed prior evidence:
`phases/phase-4-gate/gate-pack-2.md:28-30` and `repair-3-report.md:33-42`.
