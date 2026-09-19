# Scout 2 — one bounded filing-grounded expansion pass

## Recommendation

Keep first-pass seeds deterministic and finding-grounded (S1 scope). After
that exact retrieval has produced a validated packet, allow one optional
filing-local expansion stage. The expansion sees only the first packet and its
initial literal queries; it does not see outside company knowledge, a search
engine, a prior answer, or a second agent. A single small Structured Output
call is useful here: it can select a distinctive local phrase such as
`dilution gain from the OpenAI Recapitalization` from a long filing sentence.
It adds no authority, because every returned literal is accepted only after a
strict deterministic check against the first packet.

Use a narrow model, not a retrieval framework:

```python
class FilingGroundedQuery(BaseModel):
    query: str
    evidence_refs: list[str]       # first-pass E IDs
    support_span: str              # exact contiguous text containing query

class FilingQueryExpansion(BaseModel):
    queries: list[FilingGroundedQuery]  # max three
```

The expansion prompt must require zero to three short, distinctive, literal
phrases copied verbatim from one or more packet excerpts. It must return the
evidence IDs and the exact supporting span for each phrase. It must not return
amounts as calculations, explanations, answers, citations, adjustments, or
new terms inferred from the finding. This call is made once, with no retry and
no feedback loop.

Validate the output before EdgarTools is called:

1. Parse the first packet with `validate_evidence_refs(...,
   require_identity=True)` and resolve each supplied evidence ID.
2. Require `query == query.strip()`, no regex syntax, length at most the
   existing query bound, a non-empty phrase with at least two meaningful
   tokens, and case-sensitive contiguous containment of `query` in the cited
   excerpt. Require `support_span` itself to be an exact contiguous substring
   of that excerpt and to contain the query. A case or punctuation rewrite is
   rejected rather than silently normalized.
3. Require at least one cited first-pass E ID, reject unknown IDs, reject
   duplicate queries (case-insensitive), reject a query already in the initial
   seed set, and cap accepted expansion queries at three. Record every
   rejection and reason; never repair or invent a query.
4. Preserve an auditable record containing the initial packet path, E IDs,
   query, and support span. The expansion is safe even when the model returns
   a company-specific term: that term is now filing text, not model memory.

The orchestration is exactly two retrieval stages at most:

1. Retrieve deterministic initial seeds once with the existing
   `retrieve_filing_evidence`; validate and persist this packet as the
   first-pass source of truth.
2. Run the one expansion call against that packet. If accepted queries exist,
   call `retrieve_filing_evidence` once more with `initial_queries +
   expansion_queries`, writing a self-contained final packet. Repeating the
   initial literals in this bounded batch avoids a packet merge/re-numbering
   abstraction and keeps final E IDs usable by the existing investigator. If
   no query survives validation, use the initial packet as final evidence.
3. Never feed the second packet back into expansion. Send only the final
   exact packet to `run_financial_investigation`; query strings are not
   evidence unless they also occur in quoted packet text.

Expansion retrieval errors should preserve the valid initial packet and mark
`expansion.status = "failed"` with the error and rejected candidates. Do not
retry, fall back to an unvalidated term, or claim that expansion evidence was
found. The financial investigation may still report the first-pass evidence;
the artifact must expose that the optional pass was unavailable.

Example artifact shape (field names may be adapted to the current payload):

```json
{
  "retrieval": {
    "initial": {
      "queries": ["Other income (expense), net included"],
      "evidence_file": ".../finding_01_<run>_initial.md",
      "filing_accession": "..."
    },
    "expansion": {
      "status": "applied",
      "pass_count": 1,
      "source_evidence_file": "..._initial.md",
      "queries": [{
        "query": "dilution gain from the OpenAI Recapitalization",
        "evidence_refs": ["E1"],
        "support_span": "The net gains recorded for fiscal year 2026 primarily relate to the dilution gain from the OpenAI Recapitalization."
      }]
    },
    "final": {
      "queries": ["Other income (expense), net included", "dilution gain from the OpenAI Recapitalization"],
      "evidence_file": ".../finding_01_<run>_final.md",
      "filing_accession": "..."
    }
  }
}
```

The final packet remains the normal EdgarTools packet: exact source excerpt,
query, SEC source URL, accession, section locator, source lines, and offsets.
The first packet is retained as a separate inspectable artifact so an auditor
can prove the derivation chain. If the final packet has a different accession
or source identity, fail closed instead of combining packets.

## Files and surfaces

- `src/smrik_fund/ingestion/filing_investigation.py`: add the two narrow
  expansion models, one packet-only Structured Output call, deterministic
  containment/provenance validation, and the one-pass orchestration metadata.
  Keep this as local functions in the existing role module; no service,
  provider, or generic query abstraction.
- `prompts/filing_query_expansion.md`: versioned prompt whose only factual
  input is the first exact packet; require copied literals, E IDs, and spans.
  Tighten `prompts/filing_search_plan.md` separately (S1) so initial seeds
  cannot contain filing-local company/event terms.
- `src/smrik_fund/ingestion/filing.py`: no change. Reuse
  `retrieve_filing_evidence`, `validate_evidence_packet`, and
  `validate_evidence_refs`; do not add a second SEC cache or broad retrieval
  seam.
- `tests/test_filing_investigation.py`: add fake-filing tests for derivation,
  rejection, one-pass limits, identity preservation, and final packet refs.
  Existing investigator, adjustment-isolation, and evidence tests remain the
  regression boundary. `main.py` needs no semantic change; only update CLI
  rendering if nested retrieval metadata would otherwise be hidden.

## Invariants

- Before first retrieval, no initial query may contain a term absent from the
  structured finding, affected source-label context, or allowed generic
  accounting vocabulary. In particular, a finding without `OpenAI` cannot
  seed `OpenAI`.
- Exactly zero or one expansion pass per finding: one expansion model call and
  at most one expanded EdgarTools retrieval batch. No loop, retry, replanning,
  or expansion of expansion results.
- Every accepted follow-up is a verbatim contiguous substring of exact
  first-pass filing text, has non-empty first-pass E-ID provenance and an exact
  support span, and remains a literal search (never regex/fuzzy matching).
- Expansion query, cited E IDs, support span, source packet path, and both
  retrieval metadata records are persisted. E IDs are validated with filing
  identity; accession and source URL remain unchanged across stages.
- Accepted query count is bounded (three), total final query count remains
  bounded (initial cap plus three), and duplicate/broad/unsupported candidates
  are rejected without normalization.
- No model output from the expansion is a cause, amount, period mapping,
  residual, plug, adjustment, or recommendation. Quantified attribution still
  uses exact packet spans and the existing fail-closed validator; Python alone
  computes observed movement and any compatible disclosed sum.
- Missing or ambiguous evidence stays missing/ambiguous. A failed optional
  expansion exposes the gap and leaves the valid first packet intact.
- Filing investigation remains read-only: no adjustment candidates/history,
  adjusted P&L, review state, normalization, identity, or lifecycle changes.

## Non-goals

No RAG, embeddings, vector database, semantic index, generic retrieval
framework, autonomous browsing, external search, cross-filing search, second
SEC cache, agent loop, answer synthesis in the expander, taxonomy, fuzzy
matching, regex retrieval, amount extraction in query generation, forecast,
valuation, recommendation, adjustment proposal, or changes to Scan semantics.

## Risks and verification

- Leakage regression: build a finding/context without `OpenAI`; assert every
  initial query is generic. Put `OpenAI` only in fake filing text, then assert
  an exact post-packet expansion may contain it. A model-returned `OpenAI`
  without E-ID support, an absent support span, altered punctuation, or an
  unknown `E99` must be rejected.
- One-pass/provenance: count fake planner calls and filing searches. Initial
  retrieval occurs once, expansion once, and the final batch at most once;
  no call is made after the final packet. Assert the JSON chain maps the
  follow-up to first-pass E1 and the final packet preserves accession, locators,
  all exact occurrences, and usable E IDs.
- Failure safety: no initial hits, malformed packet, identity mismatch,
  expansion validation failure, or expanded retrieval failure must not trigger
  a guessed query or outside fallback. Assert initial evidence/status and the
  explicit expansion gap remain inspectable.
- MSFT live proof: initial query should be a generic Other-income phrase; the
  expansion metadata must derive any `OpenAI`/recapitalization literal from
  the initial E item. Final evidence must show the exact disclosure. Feed only
  final evidence to investigation and verify that clearly supported FY26
  gains and FY25 losses can reach Python as signed, period/unit-compatible
  disclosures; Python then reports +$11.3bn against +$15.598bn and retains the
  approximately $4.298bn residual. If the filing's `respectively` wording or
  line/period/unit bridge remains ambiguous, assert `not_computable` and an
  exposed gap instead of forcing the arithmetic.
- Run focused investigation tests, relevant regressions, Ruff, and
  `git diff --check`; manually inspect initial/expansion/final JSON and both
  Markdown packets. No new production abstraction should exceed roughly
  150–200 lines; if it does, simplify or stop for a scope decision.

## Estimated size

One existing production module change (roughly 100–180 lines including
validators/orchestration metadata), one short prompt (10–20 lines), and
roughly 120–220 focused test lines. `filing.py` remains unchanged; no new
framework or state model is justified.

## Control Block

```text
mode: read-only S2 proposal
scope: first packet -> exactly one bounded literal expansion -> final packet
input: validated first-pass excerpts only; no outside/company memory
llm: one strict Structured Output selector; no retry/loop
proof: query + exact support_span + first-pass E IDs persisted
retrieval: existing EdgarTools literal seam; initial + one final batch max
limits: <=3 expansion queries; bounded total; dedup/reject unsupported
identity: accession/source/locators preserved; no packet identity mixing
math: investigator/Python only; no expansion arithmetic or plugs
state: no adjustments/history/adjusted P&L/review mutation
non-goals: no RAG, embeddings, browsing, regex, generic framework
verdict: adopt only if deterministic containment tests and MSFT proof pass
```
