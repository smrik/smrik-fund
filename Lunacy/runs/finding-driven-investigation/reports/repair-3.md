# Finding-driven investigation — R3 repair

Verdict: **PASS for bounded repair; parent gate remains authoritative**

## Changed

- src/smrik_fund/ingestion/filing_investigation.py: quantified driver claims
  now require one local amount/year temporal pattern with no sentence/clause
  boundary, reject unrelated-year spans, and enforce gain/benefit/income versus
  loss/expense/cost/decrease source polarity. Ambiguous claims downgrade to
  unquantified fields.
- Free-text validation now recognizes common spelled-out amounts, uses
  alphanumeric token boundaries for cited numerics, and rejects residual,
  remainder, unexplained, plug, and arithmetic amount claims in every result
  field. The prompt is v3; the structured schema remains v2.
- Added exact A3 regressions for unrelated year, positive loss, residual
  “five million”, 5 versus 15, valid gain/loss signs, and cited spelled
  numeric prose.

## Tests

- Targeted adversarial probes: **7/7 passed** (all four A3 bypasses rejected;
  local gain/loss and cited spelled amount accepted).
- Focused: PYTHONPATH=src C:\Users\patri\miniconda3\envs\ai-fund\python.exe
  -m pytest tests/test_filing_investigation.py -q — **24 passed**.
- Relevant regressions — **43 passed**; full suite — **178 passed, 45
  subtests passed**.
- Ruff check/format, production py_compile, and git diff --check — passed.

## Fresh MSFT proof

- [Investigation JSON](../../../../data/live-finding-proof-r3/MSFT/03_output/analysis/filing_investigation_01_20260827T144012022055Z.json)
- [Exact evidence packet](../../../../data/live-finding-proof-r3/MSFT/03_output/evidence/finding_01_20260827T144012022055Z.md)

Preview: status=completed, accession 0001193125-26-323660, query_count=3,
evidence_item_count=6, driver_count=2; both driver amount/period fields are
null with amount_basis=unquantified; reconciliation is not_computable,
residual null, difference_is_reported_plug=false.
Prior proof attempts and source outputs remain preserved in the proof root.

## Findings

- No new financial, lifecycle, adjustment, normalization, or analyst-review
  issue found in the repaired path.

## Not changed

No generic NLP, RAG/retrieval redesign, adjustment history, adjusted P&L,
Analytical Scan semantics, or CLI contract changes. No commit, merge, or push.
