# Closed-world progressive filing retrieval — repair 2

Status: **PASS**. Narrow G0 identity/provenance repair; no commit, merge, push,
shared `filing.py` edit, retrieval redesign, or state/lifecycle mutation.

## Changed

- `src/smrik_fund/ingestion/filing_investigation.py`
  - Investigation packet validation now parses the accession token at the
    start of each locator field and requires exact equality. `A1` cannot match
    `A10`.
  - `run_financial_investigation` now requires `expected_filing_accession` and
    validates both packet ticker and accession against its caller boundary.
    `investigate_finding` passes the actual filing accession.
  - Removed confirmed-dead `_GENERIC_ACCOUNTING_CUES` and
    `_amount_and_unit_supported`; no additional dead adjacent surface was
    found.
- `tests/test_filing_investigation.py`
  - Added regressions for locator-token mismatch, caller accession mismatch,
    and wrong packet ticker (`OTHER` for `MSFT`). Updated the maintained direct
    helper caller with the required accession.

## Tests

Using `C:\Users\patri\miniconda3\envs\ai-fund\python.exe` and `PYTHONPATH=src`:

- `pytest tests/test_filing_investigation.py -q` — **42 passed**;
- `pytest tests -q` — **196 passed, 45 subtests passed**;
- Ruff check on changed/relevant source and tests — **passed**;
- Ruff format check on investigation source/tests — **2 files already formatted**;
- no-write-target `py_compile` for source/test — **passed**;
- `git diff --check 46ca750` — **passed** (Git emitted only existing
  LF/CRLF and `.pytest_cache` permission warnings).

## Fresh MSFT proof

Fresh SEC/LLM output root:
[`data/live-closed-world-proof-r2/MSFT/03_output`](../../../../data/live-closed-world-proof-r2/MSFT/03_output)

- scan: [`analytical_scan_20260827T190654525200Z.json`](../../../../data/live-closed-world-proof-r2/MSFT/03_output/analysis/analytical_scan_20260827T190654525200Z.json);
- investigation: [`filing_investigation_04_20260827T190709006849Z.json`](../../../../data/live-closed-world-proof-r2/MSFT/03_output/analysis/filing_investigation_04_20260827T190709006849Z.json);
- initial packet: [`finding_04_20260827T190709006849Z_initial.md`](../../../../data/live-closed-world-proof-r2/MSFT/03_output/evidence/finding_04_20260827T190709006849Z_initial.md);
- final packet: [`finding_04_20260827T190709006849Z.md`](../../../../data/live-closed-world-proof-r2/MSFT/03_output/evidence/finding_04_20260827T190709006849Z.md).

Representative persisted proof:

```text
status=completed; filing_accession=0001193125-26-323660
initial queries: Operating income included | Other income (expense), net included
initial OpenAI leakage: false; expansion calls/passes: 1/1
accepted expansion: dilution gain from the OpenAI Recapitalization
final packet locators: accession 0001193125-26-323660 (all six items)
bridge: FY26 +6.5, FY25 -4.8 USD billions; observed +15.598
known contribution +11.3; unresolved difference +4.298; plug=false
state-like outputs: none (no adjustment/history/state/lifecycle/review files)
```

## Findings

No in-scope G0 identity/dead-code findings remain. Parent gate may perform its
bounded acceptance sample and issue the final merge verdict. Existing process
scope warning and unrelated tracked formatting/permission warnings remain
parent-owned residuals.

## Not changed

Reported P&L values, EdgarTools retrieval, shared
`src/smrik_fund/ingestion/filing.py`, scan calculations, normalization,
materiality, adjustment application/history, review, lifecycle, and state
semantics.
