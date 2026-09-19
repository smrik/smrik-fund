# Finding-driven investigation — R4 repair

Verdict: **PASS for bounded repair; parent gate remains authoritative**

## Changed

- `src/smrik_fund/ingestion/filing_investigation.py`: model-authored narrative
  fields (`description`, `interpretation`, `unresolved_remainder`, and
  `explanation`) are now numeric-free. Digits, qualified numeric forms, and
  common cardinal/ordinal number words are rejected even when cited evidence
  contains them. Quantified facts remain in validated structured driver
  fields, evidence packets, and deterministic rendering/reconciliation.
- Invalid or unquantified drivers now atomically clear `amount`,
  `amount_unit`, `period`, and `evidence_span`, while retaining description,
  effect, and evidence refs. Deterministic summary rendering includes the
  structured source period for quantified drivers.
- `prompts/financial_investigation.md`: v4 directs qualitative prose and
  reserves quantities for structured/evidence fields; prompt metadata version
  updated to `financial-investigation-v4`.
- `tests/test_filing_investigation.py`: exact A4 arithmetic/residual,
  abbreviation, and spelled-number probes across all narrative fields;
  metadata-clearing, valid structured claim, qualitative prose, and rendering
  regressions.

## Tests

- A4 bounded selection: **3 passed, 25 deselected**.
- Focused `tests/test_filing_investigation.py -q`: **28 passed**.
- Full suite: **182 passed, 45 subtests passed** (four existing EdgarTools/
  pytest-cache warnings only).
- Ruff check + format check on changed code: passed.
- `py_compile` for changed production/test files: passed using a temporary
  workspace bytecode prefix.
- `git diff --check`: passed (existing LF/CRLF warnings only).

## Live proof

Fresh MSFT proof was attempted with the prior saved MSFT scan copied to a new
`data/live-finding-proof-r4` root. EdgarTools SEC retrieval failed before
investigation because the host denied socket access (`WinError 10013`); no
fresh model-seeded artifact was claimed. Prior R3 outputs remain untouched.

## Findings

- No new financial, lifecycle, adjustment, normalization, provenance, or
  analyst-review issue found in the bounded repair.

## Not changed

No retrieval redesign, adjustment/history state, scan semantics, or CLI
contract changes. No commit, merge, or push.
