# Closed-world progressive filing retrieval — implementation report

Status: PASS for Phase 2 I1. S1/S2/S3 were synthesized into the existing
finding-investigation path. No commit, merge, push, adjustment, history, or
lifecycle write was performed.

## Changed

- `src/smrik_fund/ingestion/filing_investigation.py`
  - Initial seeds are deterministic and bounded: affected finding refs plus
    supplied source labels and the fixed generic `included` cue only. The
    initial stage makes zero LLM calls, filters no-hit/over-budget literals
    against source text, and persists candidate/accepted/rejected derivations.
  - Added one packet-only Structured Output expansion pass. Each candidate
    carries exact `support_span` and first-pass E refs; validation rejects
    unknown refs, rewrites, regex/numeric terms, duplicates, and candidates
    absent from the filing text. Final retrieval is at most one bounded batch
    and preserves accession/source identity.
  - Added strict exact two-amount/two-year `respectively` extraction and a
    Python-only signed bridge. It selects the unique affected source label and
    supplied current/prior FY pair, preserves raw values/signs/spans/refs,
    scales dollars to USD billions explicitly, deduplicates evidence copies,
    and fails closed on ambiguity, conflicts, missingness, or unknown units.
  - Investigation defaults to unknown observed units; the CLI passes the
    explicit raw-USD standard-statement unit at its boundary.
- `prompts/filing_search_plan.md`: initial-plan prompt is documentation for
  the deterministic path and contains no answer vocabulary.
- `prompts/filing_query_expansion.md`: packet-only literal expansion contract.
- `tests/test_filing_investigation.py`: closed-world/no-OpenAI leakage,
  literal filing verification, one-pass expansion, duplicate/conflict,
  period/sign/unit/mapping, and +11.3bn bridge regressions.
- `src/smrik_fund/main.py`: saved-scan `investigate` command and explicit
  observed-unit boundary; `src/.../analytical_scan.py` retains the prior
  `ScanFinding` vocabulary alias.

## Verification

Using `C:\Users\patri\miniconda3\envs\ai-fund\python.exe` with
`PYTHONPATH=src`:

- focused: `tests/test_filing_investigation.py` — **35 passed**;
- full: `tests` — **189 passed, 45 subtests passed**;
- `ruff check` on changed Python — **All checks passed**;
- `ruff format --check` on new investigation source/tests — **2 files already
  formatted**;
- no-write `py_compile` equivalent on changed source/tests — **passed**;
- `git diff --check` — **passed** (only existing CRLF warnings).

## Fresh MSFT proof

Fresh real SEC/OpenAI run in
`data/live-closed-world-proof-i1/MSFT/03_output`:

- scan: `analysis/analytical_scan_20260827T165101769956Z.json`;
- investigation JSON:
  `analysis/filing_investigation_02_20260827T170843967812Z.json`;
- initial packet:
  `evidence/finding_02_20260827T170843967812Z_initial.md`;
- final packet: `evidence/finding_02_20260827T170843967812Z.md`.

The JSON records accession `0001193125-26-323660`, zero initial planner calls,
two deterministic initial queries (`Operating income included` and `Other
income (expense), net included`), one expansion call, filing-text verification
`performed`, and one accepted filing-local expansion. The initial query set
contains no `OpenAI`; the word first appears in quoted retrieved filing text
and the accepted expansion query/support span.

Representative persisted bridge preview:

```json
{
  "target_line_ref": "L12",
  "period": "2026-06-30 (FY)",
  "previous_period": "2025-06-30 (FY)",
  "observed_amount": 15598000000.0,
  "observed_amount_comparable": 15.598,
  "known_disclosed_contribution": 11.3,
  "unresolved_difference": 4.298,
  "difference_is_reported_plug": false
}
```

The saved facts are `+6.5` and `-4.8` `usd_billions`, both from the exact
target-labelled disclosure with preserved evidence refs/spans. The three-year
disclosure is retained as packet evidence but is not truncated into a pair.
No `adjustment_history.csv` or `adjusted_pnl.csv` exists in the proof output.

## Findings

- Pytest emitted four existing EdgarTools deprecation warnings and a local
  `.pytest_cache` permission warning; no test failed.
- The model's qualitative investigation remains numeric-free/unquantified;
  quantitative facts and residual are deterministic JSON fields only.

## Not changed

`src/smrik_fund/ingestion/filing.py`, scan calculations/semantics, reported
P&L values, normalization, materiality, adjustment application/history,
review, lifecycle, and all prior run artifacts remain untouched.
