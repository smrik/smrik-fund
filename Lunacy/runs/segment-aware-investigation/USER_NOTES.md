# User authority

Implement segment-aware filing investigation for the existing Analytical Scan. Extend the existing consolidated `ScanFinding -> deterministic retrieval -> exact filing evidence -> at most one filing-grounded expansion -> Financial Investigation synthesis -> safe deterministic arithmetic` flow. Do not create a parallel pipeline or regress `L##` behavior.

## Required behavior

- Resolve persisted deterministic `S##` refs to reported segment name, metric, periods/values, deterministic growth/margin/contribution context, filing accession, and source identity. Never infer available identity from prose; never hard-code Microsoft segment names.
- Mixed `L##`/`S##` refs are valid only when every reference resolves safely. Unknown, stale, inconsistent, or non-reconstructable refs fail closed.
- Initial retrieval is closed-world and movement-first. It may use finding text plus deterministic context: segment name, metric/source labels, periods/change terms, generic financial movement language. Company-specific causes may enter only after exact filing evidence introduces them.
- Preserve at most one filing-grounded expansion pass and exact evidence support. Prefer MD&A movement explanation over static segment descriptions; never treat composition as a cause.
- Preserve observed movement / disclosed evidence / interpretation / unresolved remainder. Keep quantified and unquantified drivers distinct, preserve multi-driver ambiguity, never allocate unsupported amounts, never create a residual plug. Partial results are valid.
- Support actual scan metrics for segment revenue growth/contribution, operating-income growth/contribution, operating-margin divergence, and concentration without a new taxonomy.
- Reconstruct exactly from saved enriched scan/segment artifacts; do not silently regenerate context. Use the existing investigation artifact family unless a small compatible extension is necessary.
- Do not touch forecasting, valuation, geographic segments unless an actual finding requires it, multi-company ontology, segment-name normalization, 10-Q/multi-filing, guidance, consensus, adjustments, model actions, or add new LLM roles/retrieval frameworks/web/embeddings/vector/RAG/autonomous loops.

## Mandatory inspection

Read `AGENTS.md`; relevant product docs; current segment enrichment; Analytical Scan implementation/prompt; filing investigation/retrieval/evidence; latest real MSFT segment-enriched scan and investigation artifacts; relevant tests; current git status/diff.

## Live proof and evaluation

Run against actual findings in the current saved real segment-enriched MSFT scan: at least one revenue-growth-concentration finding and one operating-margin/profitability-divergence finding. Do not hand-write findings or seed Microsoft-specific causes. Capture scan finding, first-pass query, evidence-introduced vocabulary, expansion, strongest evidence, drivers, quantified status, reconciliation/unresolved remainder, and analyst usefulness. Honest `partial`/`weak` is acceptable.

Evaluate: actual movement explanation vs description; vocabulary provenance; claim grounding; quantified/unquantified discipline; multi-driver ambiguity; metric fidelity; no unjustified segment-to-consolidated causality; analyst time saved.

## Required tests and verification

Focused tests must cover deterministic `S##` resolution; unchanged `L##`; safe mixed refs; fail-closed invalid refs; closed-world segment seeds; no company-specific causes before evidence; exact-evidence expansion; movement-over-description ranking; quantified period/unit/exact-span safeguards; unquantified multi-driver no-allocation; no plug; consolidated positive control; no live LLM in normal tests; no adjustment/approved-state writes.

Terminal verification: focused segment-investigation tests; existing filing-investigation tests; Analytical Scan/segment tests; adjustment/state regressions; full suite; Ruff changed files; `git diff --check`; real MSFT live proof.

No commit or merge. Preserve all unrelated user changes and prior artifacts.

## Final review

After live proof, use a fresh read-only reviewer to inspect the saved scan, ref resolution, initial/expansion queries, evidence packets/results, filing excerpts, and consolidated regression. Correct only concrete findings. Final parent report must use the exact requested headings and verdict `PASS` or `DO NOT MERGE`.
