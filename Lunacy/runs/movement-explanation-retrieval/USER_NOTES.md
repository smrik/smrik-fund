# User authority

Improve the existing closed-world filing investigation so it retrieves period-over-period explanatory disclosure more reliably without redesigning the architecture.

Read before design: `AGENTS.md`; Analytical Scan; `filing_investigation.py`; filing retrieval/evidence code; investigation and expansion prompts; relevant tests; latest live MSFT Findings 1-3 artifacts; current status/diff.

Target remains: ScanFinding -> deterministic closed-world initial retrieval -> filing-local vocabulary -> at most one grounded expansion -> exact evidence -> existing Financial Investigation -> cited explanation.

Required behavior:

- Prefer movement explanations such as increased/decreased/driven/due/offset over static includes/consists/classification passages when both exist.
- Initial queries use only finding, affected rows/source labels/concepts, periods, and generic financial change language. Never seed company-specific causes absent from the finding.
- Company-specific vocabulary may enter only from exact first-pass filing evidence; every expansion phrase retains exact first-pass refs/span; at most one expansion pass.
- Preserve accession/source/provenance/exact excerpts; quantified exact-span/period/sign/unit checks; multi-driver ambiguity; Python arithmetic; no plug; narrative refs; no adjustment/model-state writes.
- Static definitions remain usable when no stronger explanation exists. Never force causality or allocate aggregate/multi-driver amounts.
- No embeddings, RAG, web search, repeated loops, taxonomy/framework/service/provider/manager, second architecture, normalization/forecast/valuation/action logic.

Live proof: rerun real MSFT Findings 1-3 on the same filing without Microsoft-specific seeding. Finding 1 is the OpenAI positive control and must preserve approximately observed +15.598bn, disclosed +11.3bn, residual +4.298bn, plug false. Compare Findings 2/3 against prior evidence and explicitly report stronger movement evidence or absence.

Tests must cover closed-world initial queries, forbidden company seed, allowed generic change-language, exact grounded expansion, explanatory-over-static preference with static fallback, multi-driver no allocation, OpenAI reconciliation, no live LLM in tests, and no adjustment/history/adjusted-P&L writes. Run focused investigation/retrieval, Analytical Scan, adjustment/state regressions, full suite, Ruff, and `git diff --check`.

After live proof use one fresh read-only reviewer answering the seven requested financial/retrieval/simplicity questions. Make only small concrete repairs through a fresh authorized repair step. Do not commit or merge.

Final report sections: Changed; Retrieval design; Live comparison (initial query, grounded expansion, strongest evidence, drivers, quantification, reconciliation, improvement) for Findings 1-3; Finding 1 regression; Findings 2/3 quality; Safety; Files changed; Tests; Production diff; Simplicity review; Reviewer findings; Verdict PASS/DO NOT MERGE.
