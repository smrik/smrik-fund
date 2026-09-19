# Parent gate — closed-world progressive filing retrieval

Verdict: **PASS**

## Closed-world proof

- Initial plan is deterministic from persisted affected line/source labels. `planner_call_count=0`; accepted literals are `Operating income included` and `Other income (expense), net included`; neither contains `OpenAI`.
- First packet introduces OpenAI in exact filing text. One and only one expansion call admits `dilution gain from the OpenAI Recapitalization` because the literal and exact support span occur in initial E3/E4 and source text.
- Packet/item ticker, source, and exact accession are validated at every investigation boundary. `A1` cannot match `A10`; caller ticker/accession mismatches fail.
- No loop, retry planner, embeddings, RAG, vector search, autonomous browsing, or generic retrieval framework.

## Financial proof

- Exact two-period `respectively` disclosure maps unique target L12: FY26 `+6.5` USD billions; FY25 `-4.8` USD billions, with exact spans/refs.
- Python: `6.5 - (-4.8) = +11.3` disclosed YoY contribution.
- Reported P&L: `10.697 - (-4.901) = +15.598` observed movement after explicit dollars-to-billions conversion.
- Unresolved difference: `15.598 - 11.3 = +4.298`; `difference_is_reported_plug=false`.
- Qualitative narrative is numeric-free, citation/lexical-gated, and restrained. No adjustment/history/approved/adjusted-P&L/lifecycle/review output.

## Material outputs

- `data/live-closed-world-proof-r2/MSFT/03_output/analysis/filing_investigation_04_20260827T190709006849Z.json`
- `data/live-closed-world-proof-r2/MSFT/03_output/evidence/finding_04_20260827T190709006849Z_initial.md`
- `data/live-closed-world-proof-r2/MSFT/03_output/evidence/finding_04_20260827T190709006849Z.md`

## Verification

- R2 final owner: focused 42 passed; full 196 passed + 45 subtests; Ruff lint/format, py_compile, `git diff --check` passed.
- Parent: focused 42 passed; Ruff lint/format passed; `git diff --check 46ca750` passed; targeted source and final JSON/provenance/bridge sample passed.
- Only existing EdgarTools deprecation and `.pytest_cache` permission warnings remain.

## Proportionality decision

Current production footprint is 2,550 new module lines plus 105 tracked insertions, above the project scope-warning threshold. Accepted for this milestone because the module covers the already-authorized full investigation feature plus strict closed-world retrieval, exact provenance, conservative structured-output validation, deterministic period/sign/unit extraction, reconciliation, persistence, and CLI rendering. It remains one direct functional V1 path with no service/provider/framework hierarchy. Fresh simplicity and financial reviewers found no material removable blocker; confirmed dead remnants were removed. Size remains a maintainability finding, not a financial/merge blocker.

## Residuals

- Section 1/2 docs referenced by `AGENTS.md` remain absent from this checkout.
- Initial generic retrieval includes an operating-income hit before focusing on Other income; bounded evidence/provenance make this visible rather than hidden.
- No commit, merge, or push performed.
