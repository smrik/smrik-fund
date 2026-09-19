# Scout 1 — deterministic closed-world seed queries

## Finding

The current first pass is not closed-world. `run_search_plan()` in
`src/smrik_fund/ingestion/filing_investigation.py:340-405` calls
`responses.parse` with a context produced by `build_finding_plan_context()`.
That context calls `build_discovery_context()`, which reads filing text around
the affected labels. The planner can therefore copy an answer from the filing
into its initial query. The live plan did exactly that: before retrieval it
returned `dilution gain from the OpenAI Recapitalization` and other OpenAI
phrases (see `data/live-finding-proof-r4/MSFT/03_output/analysis/filing_investigation_01_20260827T152234074645Z.json`).
The existing `filing.py` literal search/evidence machinery is otherwise the
right provenance boundary and should remain unchanged.

## Recommended approach

Remove the initial planner model call. Build a deterministic seed plan from
the saved `AnalyticalScanFinding` and the exact affected source-line context
only. The seed builder must not receive filing text. A small function in the
existing module is sufficient, for example:

```text
build_initial_search_plan(finding, affected_source_context)
  -> FindingSearchPlan + seed derivation metadata
```

`affected_source_context` is a bounded, persisted-scan/P&L projection keyed by
the finding's `affected_line_refs`. Each entry contains only the bare ref,
`source_label`, and available accounting identity (`concept`,
`standard_concept`, and optionally the displayed parent path). Do not pass
`build_discovery_context()` passages, filing text, ticker, filing identity,
numeric values, observation prose, `why_it_matters`, or arbitrary question
text to this generator. Those fields remain in the artifact for lineage, but
are not query vocabulary.

Generate at most three stable, case-insensitively deduplicated literal seeds in
affected-ref order. Each seed is a source label copied from the supplied
context, optionally joined to one fixed generic accounting cue. The useful
MSFT seed is:

```text
source_label = "Other income (expense), net"
seed         = "Other income (expense), net included"
```

Use a tiny allowlist of generic cues (`included`, `consisted of`, `reflected
in`, `primarily`) and emit only label-plus-cue forms that the implementation
can handle as bounded candidates. Never tokenize or summarize finding prose;
never emit a ticker, company name, product, transaction, amount, year, or
answer-shaped phrase. If no safe source label exists, return an empty plan and
persist `no_queries`; never fall back to a broad noun or a known MSFT term.

The plan should carry auditable derivation, either as a strict
`query_derivations` field or metadata paired one-for-one with `queries`:

```json
{
  "query": "Other income (expense), net included",
  "line_refs": ["L12"],
  "source_label": "Other income (expense), net",
  "generic_cue": "included",
  "pass": "initial"
}
```

Set plan metadata to a deterministic strategy/version (and no planner model or
planner prompt). The first retrieval receives only these seeds. Existing
`retrieve_filing_evidence()` is still called with `regex=False`; no generated
seed may contain regex syntax. If a candidate has no exact filing hit, record
that candidate as rejected/no-hit and continue only with successful seed
queries, or use one seed per retrieval call and merge exact packets in a
bounded wrapper. Do not silently replace a failed seed with another term.
This is an interface point for the expansion owner: the first packet is
`pass=initial`; any later query must be a separate, once-only,
filing-grounded expansion with its own derivation chain.

## Exact affected surfaces

- `src/smrik_fund/ingestion/filing_investigation.py`: replace
  `build_finding_plan_context()`'s filing-text dependency; add the pure seed
  builder, derivation metadata, query-closure validator, and deterministic plan
  metadata; update `investigate_finding()` to build seeds before retrieval.
  Keep `run_financial_investigation()`, observed movement, and the existing
  filing evidence validator separate.
- `prompts/filing_search_plan.md`: remove it from the initial path. If retained,
  rename/version it as an expansion-only prompt whose input is exact retrieved
  packet text and whose output must be a contiguous packet substring. It must
  never generate initial seeds.
- `tests/test_filing_investigation.py`: replace the fake initial planner test
  with pure deterministic seed tests. Add a regression where the finding and
  source labels omit `OpenAI` while fixture filing text contains `OpenAI`; assert
  no initial query contains it and no LLM call occurs before retrieval. Assert
  derivation refs, stable order, dedupe, max-three/max-length bounds, cue
  allowlisting, punctuation preservation, and empty/no-safe-label fail-closed
  behavior.
- Artifact JSON: persist `seed_strategy`, `pass`, candidate/rejected counts,
  and per-query derivation. Retain the full saved finding and scan lineage,
  but do not persist filing passages as seed-generator input.
- No changes to `src/smrik_fund/ingestion/filing.py`, Analytical Scan schema or
  semantics, adjustment/history/review code, or the CLI beyond metadata/output
  wiring needed by the orchestration owner.

## Enforceable invariants

1. **Source closure:** every initial query is exactly a supplied affected
   `source_label` plus zero or one fixed generic cue. A machine validator checks
   this; prompt language is not a security boundary.
2. **No answer leakage:** query generation has no filing-text input and emits
   no free-form finding prose. Therefore a finding lacking `OpenAI` cannot
   produce `OpenAI`, even when the filing already contains it. A company/event
   token is legal in a seed only if it was already present in the supplied
   source-label context; this stronger builder normally emits labels only.
3. **No quantitative leakage:** amounts, years, percentages, signs, URLs,
   ticker, and observation-derived numbers never enter a seed.
4. **Determinism:** same finding/context yields byte-identical queries and
   derivations; affected-ref order is stable; duplicates collapse only by
   casefolded literal equality; max three queries and 240 characters each.
5. **Literal-only retrieval:** seeds are passed unchanged (aside from outer
   whitespace) to EdgarTools `search(regex=False)` and exact text occurrence
   extraction. No regex, fuzzy matching, embedding, or broad noun fallback.
6. **Bounded failure:** no safe seed means `no_queries`; a no-hit candidate is
   exposed in metadata, not replaced by a company-specific guess. No later LLM
   call occurs without an initial exact packet.
7. **Expansion boundary:** an expansion query may be admitted only after exact
   packet text contains it, with packet evidence IDs/offsets as derivation; at
   most one expansion pass. This is the S2 contract, not a seed exception.
8. **State isolation:** seed generation/retrieval writes only the investigation
   JSON and exact evidence packet; scan context, reported P&L, adjustments,
   history, lifecycle, and review state are untouched.

## Risks and verification

- Label-only queries can be too common and exceed the existing evidence-item
  budget. Prefer a generic cue for the selected line and record no-hit/overflow
  explicitly; do not make the cue a company-specific fallback. Verify the
  latest cached MSFT source has exact `Other income (expense), net included`
  occurrences and that the first packet contains the disclosure but no seed
  query contains OpenAI.
- Some affected rows have generic/duplicate labels (for example dimension
  members). Preserve exact source labels and aggregate refs; if they are not
  safe/distinctive, return no seed rather than inventing taxonomy.
- A multi-query call currently fails closed if any literal query has no exact
  section. Test the selected retrieval wrapper for partial seed success and
  packet ID/provenance preservation; keep any wrapper small or escalate scope
  rather than changing the general filing retriever.
- Regression tests should assert the old live leak is impossible, not merely
  that the current fake model behaves. A fake filing should contain a distractor
  sentence such as `OpenAI drove the result`; its text must never be passed to
  the seed builder or used to construct an initial query.
- Live proof should show the chain `Other income (expense), net included`
  (generic) -> exact filing packet -> one bounded packet-local expansion to
  `OpenAI`/the quantified disclosure. The quantification and +11.3bn versus
  +15.598bn bridge belong to the downstream extraction/reconciliation owner;
  seed generation must not pre-seed either.

## Size

Target one existing production module, approximately 50–90 net lines after
removing the initial LLM planner path; no new framework or provider. Prompt
change is small (or a rename to expansion-only), with roughly 80–140 focused
test lines. If safe partial retrieval/packet merging adds more than about 100
production lines or requires changing general `filing.py`, stop for a scope
decision. This keeps the seed correction well below the repository's
four-file/~200-line warning.

## Control Block

- Status: FINAL read-only proposal; only this proposal artifact may change.
- Defect: planner sees filing windows and leaks OpenAI before retrieval.
- Fix: pure seed builder from affected source labels + fixed generic cues.
- Input: `ScanFinding` refs and supplied P&L/source-label projection only.
- Limits: deterministic order, dedupe, <=3 literal queries, <=240 chars.
- Proof: finding/context omit OpenAI; filing distractor contains OpenAI; seed omits it.
- Retrieval: existing EdgarTools literal/evidence seam; no regex/fuzzy fallback.
- Expansion: packet-local, provenance-carrying, at most one pass (S2-owned).
- Surfaces: investigation module, expansion prompt, focused tests, artifact metadata.
- Non-goals: scan/accounting/adjustment/history/review changes, RAG, browsing.
- Size: ~50–90 production lines plus focused regressions.
- Parent decision: preserve existing retriever or approve a tiny partial-seed wrapper.
