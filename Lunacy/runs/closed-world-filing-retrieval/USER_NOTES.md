# User authority

Continue the uncommitted finding-investigation milestone, but do not merge until the live proof is closed-world.

## Required correction

1. Initial filing searches must be grounded only in the structured `ScanFinding`, supplied affected-line/source-label context, and directly implied generic accounting vocabulary.
2. Initial retrieval must not contain company/event-specific answer terms absent from that supplied context. Regression: finding lacks `OpenAI` -> initial queries cannot contain `OpenAI`.
3. Company-specific follow-up terms may enter search only after they appear in exact text retrieved from the filing.
4. Permit at most one bounded filing-grounded expansion pass. Every follow-up query must be deterministically supported by already-retrieved filing text and retain derivation provenance.
5. Prefer deterministic initial query generation; retain an LLM only where it adds measurable value after filing-local vocabulary exists.
6. Rerun the real MSFT Other-income investigation and prove the filing itself leads from generic Other-income searches to OpenAI and exact quantified disclosures.
7. If exact retrieved evidence supports FY26 gains of $6.5bn and FY25 losses of $4.8bn, Python should calculate the +$11.3bn YoY disclosed contribution against the observed +$15.598bn movement and retain the approximately $4.298bn unexplained residual. If support or mapping is ambiguous, fail closed and expose the gap.

## Preserved constraints

Reuse EdgarTools literal retrieval/evidence provenance. No embeddings, RAG, vector search, autonomous browsing, generic retrieval framework, fabricated causes/amounts, plugs, adjustments, forecasts, valuation, recommendations, or state/lifecycle changes. Normal tests make no live LLM calls. Persist inspectable JSON and concise CLI. Run focused/relevant/full tests, Ruff, `git diff --check`, final live proof, then one fresh read-only financial/product reviewer. Do not commit/merge/push.

Final verdict: `PASS` or `DO NOT MERGE`.
