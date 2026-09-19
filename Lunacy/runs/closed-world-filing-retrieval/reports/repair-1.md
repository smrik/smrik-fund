# Closed-world progressive filing retrieval — repair 1

Status: **PASS**. Bounded repair of all A1 P1/P2 findings; no retrieval
redesign, commit, merge, push, or state mutation.

## Changed

- `src/smrik_fund/ingestion/filing_investigation.py`
  - Added an investigation-boundary packet validator. Every item now matches
    packet `Source` and filing accession, not only the top-level locator.
  - Expansion candidates are admitted only when every cited first-pass item
    contains the exact support span; unrelated extra refs are rejected.
  - Added a deterministic lexical closed-world gate for narrative fields.
    Numeric/spelled-number/arithmetic/residual checks remain. Unsupported
    company-specific terms fail closed; no entailment/NLP was added.
  - Unquantified effect is derived only from unambiguous cited gain/loss
    polarity; mixed or unsupported polarity becomes `unknown`. Quantified
    effect remains deterministic from the signed validated amount.
  - Removed unused bounds, legacy aliases/properties, the obsolete planner
    client path, and the first-pass planner prompt. `filing.py` was untouched.
- `prompts/financial_investigation.md`: requires exact contiguous cited
  phrases plus neutral grammar; forbids invented filing relationships.
- `prompts/filing_search_plan.md`: removed with the obsolete LLM planner.
- `tests/test_filing_investigation.py`: regressions for quantum leakage,
  wrong/mixed unquantified polarity, item-source mismatch, unrelated
  expansion refs, and removed aliases.

Production source size: 2,506 lines in the A1 baseline → 2,535 lines after
repair (**+29 net**). The net increase is the smallest local implementation of
the required packet identity, support-span, polarity, and narrative gates;
dead bounds/aliases/planner machinery were removed in the same edit.

## Tests

Using `C:\Users\patri\miniconda3\envs\ai-fund\python.exe` with `PYTHONPATH=src`:

- focused: `pytest tests/test_filing_investigation.py -q` — **39 passed**;
- full: `pytest tests -q` — **193 passed, 45 subtests passed**;
- Ruff check — **All checks passed**;
- Ruff format check — **2 files already formatted**;
- no-write `py_compile` for source/test — **passed**;
- `git diff --check` and explicit added-file whitespace scan — **passed**.

## Fresh MSFT proof

Fresh SEC/OpenAI run root:
`data/live-closed-world-proof-r1/MSFT/03_output`

- scan: `analysis/analytical_scan_20260827T175543203180Z.json`;
- successful investigation: `analysis/filing_investigation_01_20260827T182736421990Z.json`;
- initial packet: `evidence/finding_01_20260827T175608460314Z_initial.md`;
- final packet: `evidence/finding_01_20260827T182736421990Z.md`.

Representative proof facts:

```text
initial query: Other income (expense), net included
OpenAI absent from initial query; first appears in quoted filing text
expansion calls: 1; accepted query: dilution gain from the OpenAI Recapitalization
expansion support refs: E1; filing-text verification: performed
packet identity: accession 0001193125-26-323660; item Source matches packet Source
bridge: L12, FY2026 +6.5, FY2025 -4.8 USD billions
observed: +15.598; disclosed contribution: +11.3; unresolved difference: +4.298
difference_is_reported_plug: false
```

The successful JSON has status `completed`, exact pair reason
`exact_two_period_respectively_pair`, and no adjustment/history/state output
under the fresh proof root. Initial/final packets were independently parsed
with the new identity validator.

## Findings

No in-scope findings remain. The successful live investigator emitted only
filing-supported narrative terms; unsupported probe terms are rejected before
completion.

## Not changed

Reported P&L values, filing ingestion/retrieval mechanics, scan calculations,
normalization, materiality, adjustment application/history, review, lifecycle,
and shared `src/smrik_fund/ingestion/filing.py` remain untouched.
