# Finding-driven investigation implementation

Status: PASS for Phase 2 I1 implementation. The implementation adds a standalone `investigate` CLI that consumes a saved Analytical Scan finding, asks for a bounded literal search plan, retrieves exact filing evidence, and asks for a cited financial explanation. Existing scan, normalization, materiality, identity, lifecycle, review, adjustment, and history semantics are unchanged.

## Synthesis decision

The simplest coherent design was the majority proposal: `filing_investigation.py` owns the plan/retrieve/investigate orchestration; existing `retrieve_filing_evidence` remains the literal, provenance-preserving retrieval boundary; native `responses.parse` Pydantic models constrain both LLM outputs; and no adjusted P&L or adjustment-history write is performed. The CLI is intentionally a separate `investigate` command so saved-scan lineage and accession checks are explicit.

## Changed

- `src/smrik_fund/ingestion/filing_investigation.py`: bounded search-plan and investigation schemas, deterministic observed movement/reconciliation, evidence-reference validation, failure persistence, rendering, and saved-scan loading.
- `prompts/filing_search_plan.md`, `prompts/financial_investigation.md`: versioned bounded prompts.
- `src/smrik_fund/main.py`: smallest CLI surface, `investigate MSFT --finding-rank 1 [--scan-file ...]`.
- `src/smrik_fund/ingestion/analytical_scan.py`: non-semantic `ScanFinding` vocabulary alias.
- `tests/test_filing_investigation.py`: injected-client tests for bounds, exact packet lineage, signed/unquantified amounts, accession/context checks, and CLI isolation.

## Verification

Using `C:\Users\patri\miniconda3\envs\ai-fund\python.exe` with `PYTHONPATH=src`:

- focused: `tests/test_filing_investigation.py` — **6 passed**;
- relevant regressions — **75 passed, 11 subtests passed**;
- full suite — **160 passed, 45 subtests passed**;
- Ruff on changed Python/tests — **All checks passed**;
- `py_compile` on changed Python — **passed**;
- `git diff --check` — **passed**.

## Live MSFT proof

The live SEC/OpenAI run completed without seeded company answers:

- scan: [analytical_scan_20260827T124024717605Z.json](C:\Projects\finance\smrik-fund\data\live-finding-proof\MSFT\03_output\analysis\analytical_scan_20260827T124024717605Z.json);
- investigation: [filing_investigation_01_20260827T124944739624Z.json](C:\Projects\finance\smrik-fund\data\live-finding-proof\MSFT\03_output\analysis\filing_investigation_01_20260827T124944739624Z.json);
- exact evidence packet: [finding_01_20260827T124944739624Z.md](C:\Projects\finance\smrik-fund\data\live-finding-proof\MSFT\03_output\evidence\finding_01_20260827T124944739624Z.md).

Artifact metadata records finding rank 1, scan run `20260827T124024717605Z`, accession `0001193125-26-323660`, prompt versions `filing-search-plan-v1` and `financial-investigation-v1`, and 3 literal queries. The packet contains E1–E6 with SEC source URL, accession, section locators, source line/offset ranges, and exact excerpts. The result records two disclosed OpenAI drivers (+$6.5bn FY26 and -$4.8bn FY25), a cited unresolved remainder, and no adjustment/history output.

Representative packet preview:

```text
# MSFT finding-1 evidence
Filing accession: 0001193125-26-323660
### E1
Query: Other income (expense), net included
Locator: accession ...; source text lines 1332-1332; source text offsets 174742-174778
```

Deterministic reconciliation is `not_computable` for this live result because the Analytical P&L movement is in dollars while the filing disclosures are explicitly in USD billions. The code preserves both units and does not silently scale, invent a plug, or overwrite reported values; the model's cited narrative still identifies the unresolved portion.

## Not changed

No changes were made to scan generation/validation, normalization, materiality, company identity, filing lifecycle, reviewer flow, adjustment analysis, adjusted outputs, or adjustment history.
