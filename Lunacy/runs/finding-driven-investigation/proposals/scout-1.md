# Scout 1 — finance/data-integrity proposal

## Repository facts

- `AnalyticalScanFinding`/rank-ref validation/persistence live in
  `src/smrik_fund/ingestion/analytical_scan.py:34,415,504`; scan context is
  deterministic and refs are presentation IDs, not financial mappings.
- `filing.py:125,335` already performs literal (`regex=False`) EdgarTools
  search, exact source-text occurrence extraction, line/offset locators, and
  accession/source validation. Reuse it unchanged.
- `discovery.py:129` already creates bounded filing windows. Analyst and
  Reviewer (`adjustment_analysis.py:79,109`; `reviewer.py:68,103`) are
  adjustment-specific; reusing their schemas would leak adjustment semantics.
- `main.py:2239` has scan-only CLI isolation; `_run_adjustment_analysis` at
  `1122` must remain untouched. Cached MSFT filing text uses `(In millions)`
  while the analytical P&L stores dollar values, so amount units are a real
  integrity boundary.

## Recommended approach

Add one small role module, e.g. `src/smrik_fund/ingestion/finding_investigation.py`,
with two strict Pydantic boundaries and plain functions:

1. `FindingSearchPlan`: exact `finding_rank`, selected line refs, and 1–3
   literal query phrases (bounded length). One planner call per selected
   finding uses the finding plus a bounded `build_discovery_context` window;
   prompt requires phrases copied from supplied filing passages, no answers,
   causes, amounts, or new topics. Validate query count/length and let the
   existing literal retriever fail closed if a phrase is not present.
2. `FinancialInvestigationResult`: disclosed drivers (each with description,
   exact source period, signed amount or null, explicit unit, and non-empty
   evidence refs), interpretation plus interpretation evidence refs, and a
   required unresolved-remainder statement. A null amount is retained as
   unquantified; never coerce it to zero. Use a dedicated Responses.parse role
   and prompt, not Analyst/Reviewer models.

Keep observed movement immutable: carry the original finding and the exact
scan context into the artifact; do not ask the second model to rewrite the
observation. Validate every driver/interpretation ref with
`validate_evidence_refs(..., require_identity=True)`. Compute a small Python
reconciliation only when a disclosed total and all participating driver
amounts have matching source period and explicit currency unit. Preserve
signed values, report the arithmetic difference as an unresolved difference,
and return `not_computable` for missing/mixed units; never allocate a plug.

Use a top-level `smrik-fund investigate MSFT` command with an explicit
`--scan-file` (latest scan may be a convenience fallback) and optional
`--finding-rank`/bounded top-N. It loads a fresh P&L/filing, verifies scan
ticker and accession and (preferably) exact formatted-context equality before
retrieval. Write one run JSON under the existing `03_output/analysis`
convention, with scan path, finding, plan, evidence metadata/path, structured
result, reconciliation, run/model/prompt/accession metadata; write one exact
Markdown packet per finding under `evidence/`. Keep `analyze --scan` behavior
unchanged and never call adjustment discovery, history, or adjusted-P&L code.

## Exact affected surfaces

- New `finding_investigation.py`; new versioned prompts for plan and financial
  investigation.
- `main.py`: one finance-first command and output-root/run-id plumbing only.
- Add a tiny public ref/row snapshot helper in `analytical_scan.py` only if
  needed to scope filing windows; do not change scan schema, metrics, or refs.
  Prefer reusing `build_discovery_context` before adding selector machinery.
- New focused `tests/test_finding_investigation.py`; leave adjustment/history
  tests and `filing.py` production behavior unchanged. Run existing scan,
  filing, Analyst/Reviewer, and lifecycle regressions.

## Non-negotiable invariants

- Exact excerpts, accession, source URL/path, search section locators, source
  lines, and offsets remain in the existing packet; no paraphrased evidence.
- Every company-specific driver/interpretation claim has valid packet refs;
  unsupported causes remain unresolved/qualified. Preserve ambiguity.
- Preserve source signs, missingness, periods, and units. Never infer a period,
  silently scale millions/billions into P&L dollars, or turn null into zero.
- `observed_movement`, `disclosed_explanation`, `interpretation`, and
  `unresolved_remainder` are distinct fields/CLI sections. Reconciliation is
  Python arithmetic only and never changes reported data.
- No adjustment candidate, normalization, materiality, identity, approval,
  review, adjusted P&L, or adjustment-history writes; no scan semantic changes.
- Normal tests inject frozen scan/planner/investigation clients and filing
  fixtures; no live LLM/EDGAR dependency in pytest.

## Risks and verification

- **Literal-query drift:** assert plan phrases are exact occurrences in fixture
  text; verify 1–3 query bound, duplicate handling, and retrieval failures are
  persisted per finding without hiding other findings.
- **Stale/mismatched scan:** mutate accession/context/ticker fixtures and assert
  fail-closed; verify refs still resolve to the supplied context/P&L snapshot.
- **Financial hallucination/unit error:** fixture signed `(3,051)`/`4,385`,
  `usd_millions` totals, null drivers, mixed periods/units; assert only matching
  amounts reconcile and differences remain visible.
- **Evidence attribution:** unknown refs, empty driver refs, and unsupported
  interpretation refs must fail before persistence; packet identity is required.
- **CLI/state safety:** temporary output-root snapshot proves only evidence,
  analysis, and investigation run JSON change; history and adjusted P&L are
  absent/byte-identical. Live MSFT proof inspects the current scan's top finding
  without seeded queries/answers, then a fresh read-only finance reviewer checks
  representation and analyst time saved.
- Run focused tests, relevant regressions, full pytest, Ruff, and
  `git diff --check` on the final implementation.

## Size / complexity

Target 2–3 production Python files, 2 prompts, and 1 focused test module;
roughly 180–300 net production lines. Keep the planner bounded (at most three
findings by default, one plan/investigation pair per finding). If a selector,
cache, retrieval framework, or >4 production files/~200 new production lines
becomes necessary, stop for a parent decision brief rather than expanding.

## Explicit non-goals

No RAG/vector search, autonomous browsing, generic retrieval/provider/agent
framework, taxonomy or fuzzy line mapping, segment extraction, forecasts,
valuation/recommendations, adjustment proposals, normalization, auto-approval,
history/lifecycle changes, database/UI, or broad refactor of existing scan,
discovery, filing, Analyst, or Reviewer roles.

## Control Block

- Status: FINAL — read-only proposal; no source/test/config/external writes.
- Recommendation: dedicated finding-investigation role + bounded literal plans.
- Reuse: existing `filing.py` provenance/retrieval and `discovery.py` windows.
- Structured outputs: strict search plan and evidence-attributed investigation.
- Observations stay scan-derived; nulls/signs/periods/units stay explicit.
- Python reconciles only comparable disclosed amounts; no plug ever.
- CLI: new isolated `investigate`, preserve `analyze --scan` and adjustments.
- Artifact: one run JSON + exact Markdown packet(s), output-root isolated.
- Scope target: 2–3 production files, 2 prompts, 1 focused test module.
- Verification: mocked tests, regressions/full pytest, Ruff, diff check, live MSFT.
- Parent gate: fresh reviewer checks financial integrity and analyst time saved.
