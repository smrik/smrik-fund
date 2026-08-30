# Scout 2 — retrieval and structured-output proposal

## Recommended approach

Add one narrow `filing_investigation.py` role module. Keep the existing
Analytical Scan observational and keep adjustment discovery/review untouched.
For each validated `AnalyticalScanFinding` (optionally expose the exact alias
`ScanFinding`), build a small strict `FilingSearchPlan` with a maximum of three
literal queries. The plan should carry the finding rank, affected line refs,
the finding questions, and the exact bounded queries; it is a retrieval input,
not an explanation or adjustment proposal.

Use the existing `retrieve_filing_evidence()` unchanged as the retrieval seam.
It already calls EdgarTools literal search, preserves every exact text
occurrence, section locator, accession, source URL, line and offset metadata,
and writes a Markdown packet. Immediately validate the packet and all model
references through `validate_evidence_refs(..., require_identity=True)`. No
best-hit selection, regex expansion, fuzzy label matching, or second SEC cache.
If a query has no exact occurrence, retain a per-finding `retrieval_failed`
record and continue other findings; never invent a cause or fall back to a
different filing.

The query-plan boundary should be native Responses Structured Output/Pydantic,
using a small schema and bounded prompt. Give the planner only the finding,
the exact affected-line context/period values, filing identity, and a bounded
set of filing passages or search vocabulary. Require queries to be contiguous
literal phrases from supplied filing text where possible; unverifiable queries
fail closed at retrieval. This is safer than asking the existing adjustment
Analyst to emit search terms and avoids broad discovery over the entire P&L.
Use the same injected fake `responses.parse` seam as `analytical_scan.py`,
`discovery.py`, and `adjustment_analysis.py`; normal tests never construct a
live OpenAI client.

After retrieval, make a separate structured financial-investigation call. Its
schema should distinguish, at minimum:

- `observed_movement`: deterministic source-line/period movement copied from
  the supplied P&L, not model-invented;
- `disclosed_drivers`: zero or more evidence-backed driver objects with a
  description, positive disclosed amount or `null`, effect/direction,
  amount-basis (`disclosed` or `unquantified`), and non-empty exact
  `evidence_refs`;
- `interpretation`: clearly labeled inference, with evidence refs when it
  makes a company-specific claim;
- `unresolved_remainder`: explicit text plus a nullable numeric remainder;
- one short analyst-facing `explanation`.

Model output remains strict (`extra="forbid"`, small field/array limits). A
post-parse validator must reject unknown/empty evidence references and require
every disclosed/company-specific driver claim to point into the exact packet.
Python should calculate only the observed movement and the sum of known
disclosed contributions, preserving signed source values and missingness. It
may report `observed - known_disclosed` as an explicitly unresolved remainder,
but must never turn that difference into a synthetic driver, zero, plug, or
adjustment. Unquantified drivers stay visible as unquantified. If direction,
period, or target is ambiguous, preserve that ambiguity and mark the result
unresolved rather than selecting a fact.

Persist one inspectable run JSON under
`<output_root>/<ticker>/03_output/analysis/filing_investigation_<run_id>.json`.
For every finding, include the original finding, bounded plan, retrieval
metadata/evidence path, exact investigation result, deterministic movement
and reconciliation fields, status, and stage error when applicable. Packets
remain Markdown files under `03_output/evidence/`; do not put long excerpts in
CSV/history. Render a compact summary showing rank/title, target movement,
disclosed and unquantified drivers, unresolved remainder, and explanation.

The smallest CLI surface is an `--investigate` option on `analyze` that runs
the existing scan and then investigation in the same attached EdgarTools
filing/P&L context (or a dedicated `investigate` command that explicitly reads
the latest scan artifact, if implementation needs two stages). Prefer the
single `analyze MSFT --scan --investigate --output-root <dir>` path: it avoids
losing the in-memory filing and keeps output-root isolation. Reject
`--investigate` without scan input, and reject combinations with
`--adjustments`. Investigation-only must not call discovery/adjustment
analysis, write `adjustment_history.csv`, `adjusted_pnl.csv`, or alter scan
semantics.

## Exact affected surfaces

Production:

- `src/smrik_fund/ingestion/filing_investigation.py` (new): strict search-plan
  and investigation models, bounded plan/investigation prompts and Responses
  calls, finding-to-line lookup, deterministic movement/known-driver
  reconciliation, evidence-ref validation, orchestration, JSON persistence,
  concise rendering. Keep this a function module; no service/provider layer.
- `src/smrik_fund/ingestion/analytical_scan.py`: only a public ref/line lookup
  seam or `ScanFinding` compatibility alias if needed. Do not alter scan
  fields, rank/ref validation, formatter calculations, or saved scan shape.
- `src/smrik_fund/ingestion/filing.py`: ideally no changes; reuse
  `retrieve_filing_evidence`, `parse_evidence_packet`, and
  `validate_evidence_refs`. Only add a narrowly justified query-count bound
  if the plan cannot enforce it at its own schema boundary.
- `src/smrik_fund/main.py`: CLI glue and attached-filing handoff; preserve
  deterministic P&L/reconciliation ordering and the existing `--adjustments`
  path byte-for-byte in behavior.
- `prompts/filing_search_plan.md` and `prompts/financial_investigation.md`:
  short versioned prompts. Prompt instructions must prohibit outside company
  knowledge, answer leakage, adjustment recommendations, unsupported causes,
  and signed-delta authorship.

Tests:

- New focused `tests/test_filing_investigation.py`: strict plan bounds,
  injected Structured Outputs calls, exact query forwarding, packet identity
  and evidence-ref rejection, multiple exact hits/provenance, missing-query
  local failure, quantified plus unquantified drivers, sign-preserving
  reconciliation, explicit unresolved remainder/no plug, and JSON output-root
  isolation.
- Small additions to `tests/test_analytical_scan.py` or CLI tests only for
  the scan→investigate handoff, mutual exclusion, and no adjustment-state
  writes. Existing adjustment/reviewer/discovery tests remain the regression
  boundary.

## Non-negotiable invariants

- EdgarTools is the sole filing source; use its literal search/text and exact
  section, accession, URL, line, and offset provenance. Never silently select
  one result among multiple occurrences.
- Every company-specific disclosed cause and every quantified/unquantified
  driver is tied to one or more exact packet evidence IDs. Unknown refs,
  absent refs, malformed packets, missing accession, and query ambiguity fail
  closed.
- `observed_movement`, `disclosed_explanation`/drivers, `interpretation`, and
  `unresolved_remainder` are separate fields/sections. Numerical movement and
  disclosed-amount sums are Python facts; residuals are reported as
  unresolved, never plugs.
- Preserve source signs, periods, missing values, exact row identity and
  reported-vs-adjusted separation. Do not infer a target line or period from a
  label, and do not normalize financial values.
- At most three literal queries per finding and at most eight input findings;
  one bounded packet per finding. A failed topic is recorded locally without
  contaminating unrelated findings.
- Investigation is read-only: no adjustment candidates/history, risk gate,
  adjusted P&L, reconciliation acknowledgement, normalization eligibility,
  identity, lifecycle, or review-state changes.
- Normal pytest has zero live LLM/network calls. Native `responses.parse` with
  Pydantic schemas is the only model boundary; no loose JSON repair parser.

## Explicit non-goals

No RAG, embeddings, vector database, broad/generic retrieval framework,
autonomous browsing, regex scraping fallback, external data provider,
cross-filing search, semantic taxonomy, target-line normalization, adjustment
proposal/approval, forecasts, valuation, recommendations, reviewer workflow,
new database/UI, caching/provenance graph, or changes to existing Scan,
Analyst, Reviewer, risk-gate, history, or accounting mechanics.

## Risks and verification

Primary risks are planner queries that are not literal filing text, repeated
phrases, evidence overclaiming, line-ref-to-row drift, model-generated plugs,
and accidental state mutation. Verify with a fake Edgar filing whose search
returns multiple sections and text has multiple exact occurrences; assert all
occurrences/locators survive and no best hit is selected. Test query count,
empty/unknown refs, malformed identity, missing values, positive/negative line
movements, known-driver sums, and unquantified drivers separately. Snapshot
the JSON and Markdown and assert no history/adjusted files appear in a temp
root. Run focused tests, relevant existing scan/filing/adjustment tests,
full pytest, Ruff, `git diff --check`, and a live isolated MSFT proof if
credentials permit. Inspect output manually for exact filing excerpts and
clear observed/explained/unresolved separation; then obtain the required
fresh read-only reviewer on financial correctness and analyst time savings.

## Estimated size / complexity

Approximately 1 new role module (250–400 production lines), 2 short prompts,
a 30–60-line CLI handoff, and 250–400 focused test lines. Reuse of
`filing.py` should keep the change to 2–3 production files. If the planner
requires broad filing context, a second retrieval abstraction, or more than
four production files/~200 new lines beyond this estimate, stop and simplify
or request a scope decision.

## Control Block

```text
mode: read-only scout proposal
scope: finding -> bounded literal retrieval -> structured investigation
source: EdgarTools filing.py seam only
llm: Responses.parse + strict Pydantic; injected clients in tests
evidence: exact excerpts, IDs, accession, section, URL, lines, offsets
math: Python movement/known disclosed sums; residual is never a plug
state: no adjustments/history/adjusted P&L/review mutations
cli: analyze --scan --investigate, isolated output-root
limits: <=8 findings, <=3 literal queries/finding
non-goals: no RAG, embeddings, browsing, taxonomy, forecasts, valuation
verification: focused + regressions + full suite + Ruff + diff-check + live MSFT
verdict: synthesis must choose simplest sound implementation
```
