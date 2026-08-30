# Finding-driven investigation — R1 repair

Verdict: **PASS for bounded repair; parent gate remains authoritative**

## Changed

- `filing_investigation.py`: removed model-owned residual amount/unit fields; rejects residual amounts in the qualitative remainder; reconciliation emits a residual only from a unique validated line/period bridge and otherwise returns `not_computable` with null amounts.
- Planner queries are filtered to case-insensitive literal occurrences in the bounded passages; rejected/all-invalid queries safely produce `no_queries`.
- Disclosed period/amount/unit claims are checked against supplied FY periods and cited excerpt magnitude/unit evidence; unsupported claims are preserved as null/`unknown` with `unquantified` basis.
- Explanations now require validated packet evidence IDs (`explanation_evidence_refs`). Removed unused duplicate investigation API aliases.
- Updated prompts and focused tests; no adjustment/history/scan lifecycle changes.

## Tests

- Focused: `tests/test_filing_investigation.py` — **12 passed**.
- Relevant regressions: analytical scan, discovery, filing, analytical P&L, reconciliation — **43 passed**.
- Full suite: `tests` — **166 passed, 45 subtests passed**.
- Ruff check + format on changed code — **passed**; `py_compile` — **passed**; `git diff --check` — **passed**.

## Fresh MSFT proof

- Scan: [analytical_scan_20260827T131624327070Z.json](C:\Projects\finance\smrik-fund\data\live-finding-proof-r1\MSFT\03_output\analysis\analytical_scan_20260827T131624327070Z.json)
- Investigation: [filing_investigation_01_20260827T132247363739Z.json](C:\Projects\finance\smrik-fund\data\live-finding-proof-r1\MSFT\03_output\analysis\filing_investigation_01_20260827T132247363739Z.json)
- Evidence: [finding_01_20260827T132247363739Z.md](C:\Projects\finance\smrik-fund\data\live-finding-proof-r1\MSFT\03_output\evidence\finding_01_20260827T132247363739Z.md)

Representative result: `status=completed`, `query_count=3`, `rejected_query_count=0`, `driver_count=4`, all four unsupported model period/amount claims preserved as `period=null`, `amount=null`, `amount_unit=unknown`, `reconciliation.status=not_computable`, `reconciliation.unresolved_difference=null`. Packet retains accession `0001193125-26-323660` and exact SEC source/excerpt locators.

## Findings

The live rank-1 finding affects five lines and has multiple FY deltas, so deterministic reconciliation is intentionally `not_computable`; no arbitrary movement or model residual is used. The live model returned free-form fiscal periods, which were safely downgraded to unknown rather than accepted.

## Not changed

Analytical Scan semantics, reported values, normalization/materiality/identity/lifecycle/review behavior, adjustment P&L/history, and legacy live artifacts remain unchanged.
