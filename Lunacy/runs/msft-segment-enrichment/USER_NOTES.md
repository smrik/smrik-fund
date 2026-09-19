# User authority

Implement MSFT reportable operating-segment enrichment and integrate it into the existing Analytical Scan. Do not redesign financial-statement architecture. Do not commit or merge.

Read first: `AGENTS.md`; current statement ingestion/analytical P&L; Analytical Scan implementation/prompt; MSFT filing utilities; relevant tests; latest real MSFT scan artifacts; current git status/diff.

## Goal and source discipline

Use only reportable segment information disclosed in the actual current MSFT 10-K used by the run. Do not hard-code Microsoft segment names in product logic or live prompts. Preserve source labels, periods, values, signs, accession/provenance. Use comparable/recast historical values actually disclosed; fail closed on unsafe comparability. Never invent or allocate missing segment facts.

Keep target flow: consolidated + segment financials -> deterministic analytical base -> existing Analytical Scan. This is analytical context, not filing investigation. No forecasting, valuation, normalization/adjustments, 10-Q support, multi-company taxonomy/ontology, geography unless required, restatement engine, database, dimensional model, retrieval framework, new agent/LLM role.

## Required deterministic segment analytics

Per reported segment, where supported:

- Revenue by annual period; absolute YoY; guarded YoY growth using existing semantics; consolidated revenue share and share change; contribution to same-period consolidated revenue growth.
- Operating income by period; absolute YoY; guarded growth; operating margin; YoY margin movement in bps; contribution to consolidated operating-income growth where comparable.
- No EBITDA or undisclosed profit metric.

Add transparent reconciliation where structure supports it: reported segment total, reported consolidated total, explicit residual/reconciliation item, and status pass/not directly comparable/unresolved. Never plug; preserve eliminations/corporate/unallocated/measurement differences.

Persist the smallest coherent inspectable segment artifact. A compact separate artifact is preferred if segment rows would confuse canonical `analytical_pnl.csv`. No generic dimensional model.

## Scan integration

Add a compact deterministic segment section, not a raw table. Model can compare segment growth, mix/contribution, operating margins and concentration against consolidated performance. Python establishes facts; LLM chooses attention. No deterministic anomaly/materiality/ranking rules.

Every selectable segment financial item needs a deterministic unique ref that cannot collide with consolidated refs; model cannot invent refs; validation rejects unknown refs; existing consolidated refs remain compatible. Make only the prompt change needed to expose segment context. No causes, filing retrieval, forecast, valuation, adjustments, or recommendation; never seed expected MSFT conclusions.

## Live proof and comparison

Run segment extraction/analytics and the real segment-enriched scan against the same current MSFT filing. Preserve prior consolidated-only artifact. Compare ranked old/new outputs for new invisible facts, improper loss of consolidated findings, growth/margin understanding, slot noise, double-counting, and analyst time saved. Fewer better findings are acceptable.

## Tests and verification

Focused synthetic tests must prove exact values, guarded growth, revenue share, contribution, zero/missing/sign-change fail-closed behavior, operating margin/bps, plug-free residual reconciliation, deterministic unique segment refs, unknown-ref rejection, consolidated-ref compatibility, compact context, no live LLM in normal tests, and no adjustment/history/approved/adjusted-P&L changes. Run focused segment, Analytical Scan, statement/reconciliation, adjustment/state, full suite, Ruff, and `git diff --check`.

After live proof use one fresh read-only reviewer inspecting source disclosures, extracted values, calculations, reconciliation, exact model context, old/new scans. It answers: fidelity; period comparability; calculation correctness; honest residuals; improved observations; redundancy/misleading findings; unnecessary architecture. Make only concrete bounded corrections.

Final report sections: Changed; Source structure; Analytical output (real segment revenue/operating-income table); Reconciliation; Scan integration; Old vs new scan; Product assessment; Safety; Files changed; Tests; Production diff; Simplicity review; Reviewer findings; Verdict PASS/DO NOT MERGE.
