# Scout 3 — minimal CLI and analyst-useful finding investigation

## Recommendation

Add one standalone `investigate` CLI command that consumes an existing saved
Analytical Scan, one finding at a time. Do not make `analyze --scan` do the
investigation implicitly: the saved scan is the stable attention-allocation
artifact, and a standalone command lets an analyst select rank 1 (or another
rank) without rerunning the scan or entering the adjustment pipeline.

Proposed use:

```text
smrik-fund investigate MSFT --finding-rank 1
smrik-fund investigate MSFT --scan-file <scan.json> --finding-rank 2
```

If `--scan-file` is omitted, choose the newest
`data/MSFT/03_output/analysis/analytical_scan_*.json`. Require the persisted
scan's ticker, filing accession, context, and exact rank to validate. Load the
already saved analytical P&L and fetch one latest 10-K with the existing
`get_latest_filing()` seam; fail closed when the filing accession differs from
the scan. This avoids mixing a finding from one filing with evidence from
another.

The bounded path is:

```text
saved AnalyticalScanFinding
  -> one structured search-plan call (0..3 literal queries)
  -> existing retrieve_filing_evidence(..., regex=False)
  -> one structured financial-investigation call
  -> deterministic amount summary + concise renderer
  -> one inspectable JSON artifact and one Markdown evidence packet
```

The planner receives the selected finding plus a small context built with the
existing `build_discovery_context()` helper (bounded passages, no answer-shaped
topic). It must return exact, short contiguous phrases suitable for literal
EdgarTools search, never a cause, amount, citation, or recommendation. The
existing retrieval code already preserves exact filing text, section locators,
accession, source lines/offsets, stable `E#` IDs, and the 20-item budget.

Use a new local module, preferably
`src/smrik_fund/ingestion/filing_investigation.py`, with three small Pydantic
boundaries:

```text
FilingSearchPlan
  queries: list[str] (0..3, normalized/deduplicated)

DisclosedDriver
  description: str
  amount: float | None
  amount_unit: dollars | millions | billions | unknown
  period: exact supplied FY period | None
  evidence_refs: list[str] (non-empty)

FinancialInvestigation
  disclosed_drivers: list[DisclosedDriver] (max 8)
  interpretation: str | None + interpretation_evidence_refs
  unresolved_remainder: str + unresolved_evidence_refs
```

Keep the scan's existing `AnalyticalScanFinding` model and schema untouched;
if the implementation wants the requested name, add the harmless public alias
`ScanFinding = AnalyticalScanFinding`, not a schema rename or migration. Keep
the observed movement as the finding's exact saved `observation` plus its
affected refs. The investigator owns only disclosed drivers, interpretation,
and unresolved remainder. This prevents a second LLM from rewriting reported
movement.

For each driver, `amount=None` visibly means unquantified. Preserve sign as
reported in the numeric field (and source wording in the exact packet); require
an explicit unit before arithmetic. Python may sum finite, unit-normalized
disclosed amounts within the same period and report `complete`/`partial`/`not
reconcilable`. If periods, units, or drivers are incomplete, leave the status
partial and do not calculate a residual. Never turn a residual into a plug or
an adjustment candidate.

Render only four short sections to the terminal: Observed movement (copied from
the scan), Disclosed explanation (driver, amount/unquantified marker, `E#`),
Interpretation, and Unresolved remainder. Put long source text in the existing
Markdown packet and structured details in JSON, not in history CSVs.

## Exact affected surfaces

- `src/smrik_fund/ingestion/filing_investigation.py` (new): plan and
  investigation schemas, injected-client Responses API calls, persisted JSON
  payload, bounded-input validation, disclosed-amount arithmetic, and concise
  renderer. No provider abstraction.
- `prompts/filing_investigation.md` (new): versioned planner and investigator
  prompts. Planner requires literal phrases from bounded filing context;
  investigator requires every disclosed cause/interpretation claim to carry
  packet IDs and preserves unquantified drivers/ambiguity.
- `src/smrik_fund/main.py`: add only `investigate(...)`, latest/explicit scan
  loader, filing-accession guard, one planner/retrieval/investigator sequence,
  and output messages. Reuse `load_analytical_pnl`, `get_latest_filing`,
  `build_discovery_context`, `retrieve_filing_evidence`, and
  `validate_evidence_refs`.
- `src/smrik_fund/ingestion/analytical_scan.py`: no behavior change; optional
  `ScanFinding` alias only. Reuse `validate_analytical_scan_result` when
  reading a persisted artifact so edited/invalid ranks or refs fail closed.
- `tests/test_filing_investigation.py` (new): focused fake-filing, planner,
  investigator, arithmetic, persistence, and CLI-isolation tests. Existing
  scan/filing/adjustment tests should remain unchanged unless a narrowly
  required public import is added.

Do not change `filing.py`: its literal retrieval function is already the
required bounded EDGAR seam. Do not change `statements.py`, adjustment
history, Reviewer, risk gate, or `apply_adjustments()` for this read-only
investigation.

Suggested output names under the selected output root:

```text
data/MSFT/03_output/evidence/finding_01_<run_id>.md
data/MSFT/03_output/analysis/filing_investigation_01_<run_id>.json
```

JSON should retain scan path/run ID/finding rank and full finding payload,
filing identity, planner metadata and queries, retrieval metadata/evidence
path, investigator metadata/result, deterministic amount-reconciliation
summary, status/error stage, and no embedded replacement for quoted source
text. A no-query, retrieval failure, or invalid model reference should still
produce a short failed artifact where practical, without calling later stages.

## Non-negotiable invariants

1. Scan finding, periods, line refs, signs, and observed movement remain exact
   inputs. Validate persisted scan structure before any filing search.
2. Search-plan queries are bounded (maximum three), literal (`regex=False`),
   normalized only for surrounding whitespace, and never answer-shaped.
3. Filing text is sourced only through EdgarTools. Existing packet bytes are
   passed unchanged to the investigator and saved unchanged to disk.
4. Every company-specific disclosed cause, amount, interpretation, and
   unresolved claim has one or more valid `E#` refs. Unknown/empty refs fail
   closed before result persistence.
5. `amount=None` means unquantified, not zero. Unknown units/periods remain
   unknown. Python arithmetic only sums explicitly quantified compatible
   disclosed values; it never creates a residual, plug, adjustment, or
   normalized P&L number.
6. No adjustment candidate/history row is produced. `analytical_pnl.csv`,
   `reconciliation_checks.csv`, `adjusted_pnl.csv`, and approved state remain
   untouched. This command is read-only apart from new evidence/JSON artifacts.
7. One selected finding gives at most one planner call, one literal retrieval
   pass (subject to existing query/item bounds), and one investigator call.
   No autonomous browsing, retry loop, Analyst/Reviewer debate, or all-findings
   fan-out by default.
8. Outputs retain filing accession, source URL/path, section/locators, exact
   excerpt lines/offsets, scan run ID, model/prompt/schema versions, and
   processing errors; no provenance is invented.

## Explicit non-goals

- No change to Analytical Scan semantics, ranking, materiality, identity,
  lifecycle, adjustment history, adjusted P&L, risk gate, Reviewer, or review
  CLI semantics.
- No automatic adjustment discovery, normalization decision, approval,
  forecast, valuation, stock recommendation, or financial action.
- No generic retrieval framework, RAG, embeddings/vector search, web fallback,
  autonomous browser, custom SEC parser/cache, provider abstraction, or
  cross-company taxonomy.
- No broad scan rerun, multi-finding batching, endless research loop, or
  Analyst/Reviewer schema reuse merely to avoid a small new explanation schema.
- No full-filing prompt, answer-leaking fixture, Microsoft-specific expected
  cause/amount in code or prompts, or use of `tests/msft_restructuring_gold.md`
  at runtime.
- No broad statement/context redesign. If finding-specific passage filtering
  is needed, keep it a local bounded selection over the existing helper.

## Test and live-proof design

Normal tests inject a fake Responses client and a fake EdgarTools filing; no
credential lookup or live LLM call. Focused checks should prove:

- persisted scan with rank 1/2 loads and validates; wrong ticker/accession,
  missing rank, malformed context, and unknown line refs stop before calls;
- planner accepts 0..3 queries, rejects 4/blank queries, de-duplicates without
  regex semantics, and receives only selected finding + bounded context;
- fake filing receives exactly the planner's literal queries; existing packet
  excerpts retain punctuation/line breaks, stable IDs, accession, section loc,
  source lines/offsets; no best-hit selection;
- driver with `amount=None`, mixed units, signed amounts, and repeated periods
  is retained; deterministic sum is correct only for compatible finite values,
  and no `observed - disclosed` residual or plug appears;
- investigator `E99`/empty refs fail before JSON result save; all valid refs
  appear in the artifact and rendered explanation;
- CLI with a temporary `--output-root` writes only the new packet/JSON, prints
  the four finance-first sections, and leaves adjustment history/adjusted P&L
  absent or byte-for-byte unchanged;
- call counters prove one planner + one retrieval pass + one investigator for
  a normal finding; a zero-query/retrieval failure makes no later model call;
- no changes to existing scan output or adjustment pipeline tests.

Real proof, only if credentials/cache and SEC access permit:

```text
smrik-fund analyze MSFT --scan --output-root <proof-root>
smrik-fund investigate MSFT --finding-rank 1 --output-root <proof-root>
```

Inspect the saved JSON and Markdown manually: current accession must match the
scan; evidence must be exact filing text with honest locators; the explanation
must distinguish the FY26 non-operating movement from disclosed drivers (and
retain any unquantified remainder); terminal output must be concise; history
and adjusted outputs must not change. Do not seed the expected OpenAI-related
case or amount. If socket/credentials fail, record that limitation rather than
substituting fixture evidence for live proof.

Run focused investigation/scan/filing tests, relevant Analyst/Reviewer and
adjustment regressions, full pytest, Ruff on changed Python, and
`git diff --check`. Inspect `git status`, diff/stat, packet, JSON, and before/
after hashes of nearby financial-state files.

## Estimated size / complexity

Small, one-finding vertical slice: roughly 130–190 new Python lines in one
module, 25–50 CLI lines, one prompt file, and 150–250 focused test lines. Keep
production changes to the new module plus `main.py` (and an alias only if
needed). This is medium complexity because exact provenance and unit/period
ambiguity need tests, but no change to accounting mechanics. If implementation
requires edits to more than four production/test files or more than about 200
new production lines, stop and reassess for accidental workflow/framework
growth.

## Control Block

- Scope: one saved scan finding; one new `investigate` CLI command.
- Retrieval: existing EdgarTools literal packet; max 3 queries / 20 items.
- LLM: one structured plan call + one structured investigation call.
- Output: exact Markdown evidence + inspectable JSON; concise four-part CLI.
- Finance: preserve values/signs/periods/missingness; no inferred plug.
- State: no history, adjustment, reconciliation, or scan mutation.
- Evidence: every company-specific claim cites valid `E#`.
- Tests: all normal calls mocked; fake filing proves exact excerpts/locators.
- Live: run current MSFT only when credentials/SEC access permit.
- Verification: focused tests, regressions, full pytest, Ruff, diff check.
- Stop if scope exceeds 4 surfaces or ~200 production lines.
- Verdict target: evidence-backed analyst time savings, otherwise DO NOT MERGE.
