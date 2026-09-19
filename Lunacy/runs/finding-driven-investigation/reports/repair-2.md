# Finding-driven investigation — R2 repair

Verdict: **PASS for bounded repair; parent gate remains authoritative**

## Changed

- `src/smrik_fund/ingestion/filing_investigation.py`: quantified drivers now require an `evidence_span` copied literally from exactly one cited evidence item. The span must contain exactly one qualified amount, one source year, matching unit/period, and matching source sign. Ambiguous `respectively` passages, year-as-amount claims, sign inversions, missing spans, and non-literal spans downgrade to `amount=null`, `amount_unit=unknown`, `period=null`, `amount_basis=unquantified`.
- The same module now checks every persisted investigation free-text field (`description`, `interpretation`, `unresolved_remainder`, `explanation`). Numeric claims must occur in cited excerpts; unsupported arithmetic and residual/plug prose is rejected. Evidence-backed disclosed numbers remain allowed. Python reconciliation remains the only residual source and returns null residuals when `not_computable`.
- `prompts/financial_investigation.md`: v2 instructions require literal support spans and prohibit free-text residual arithmetic. Added focused regressions for valid spans, year-as-amount, respective cross-year swaps, sign inversion, bare/qualified prose residuals, prose arithmetic, and evidence-backed prose amounts.

## Tests

- Focused: `PYTHONPATH=src C:\Users\patri\miniconda3\envs\ai-fund\python.exe -m pytest tests/test_filing_investigation.py -q` — **19 passed**.
- Relevant regressions: analytical scan, discovery, filing, analytical P&L, reconciliation — **43 passed**.
- Full suite: `tests` — **173 passed, 45 subtests passed**.
- Ruff check/format, production `py_compile`, and `git diff --check` — **passed**. Test-bytecode compilation was not run because repository `__pycache__` ACL denies writes; pytest collection/ execution passed.

## Fresh MSFT proof

- [Investigation JSON](../../../../data/live-finding-proof-r1/MSFT/03_output/analysis/filing_investigation_01_20260827T140053515105Z.json)
- [Exact evidence packet](../../../../data/live-finding-proof-r1/MSFT/03_output/evidence/finding_01_20260827T140053515105Z.md)

Representative output: `status=completed`, accession `0001193125-26-323660`, `query_count=3`, `evidence_item_count=6`, `driver_count=1`, driver amount/period null and `amount_basis=unquantified` because the filing's `$6.5 billion` / `$4.8 billion` `respectively` disclosure is not an unambiguous single-value span; reconciliation `status=not_computable`, `unresolved_difference=null`, `difference_is_reported_plug=false`.

## Findings

- Fresh live run succeeded with SEC/OpenAI access and preserved exact SEC URLs, accession, source locators, and quoted excerpts. No seeded Microsoft-specific answers.
- Prior R1 live artifacts remain intact; the new run is timestamped `20260827T140053515105Z`.

## Not changed

Analytical Scan semantics, reported values/signs, normalization/materiality/identity/lifecycle/review behavior, adjustment history, adjusted P&L, reconciliation source rules, CLI contracts, and prior live artifacts.

No commit, merge, push, or external repository write performed.
