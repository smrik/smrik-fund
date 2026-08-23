# S3 — Output simplicity / analyst-facing CLI

Status: READY  
Lane: Human-facing CLI usefulness, removable bloat, safe simplification  
Scope: read-only inspection; no source, test, config, or external-state edits.

## Approach

Read the required authority (`AGENTS.md`, Section 1, Section 2), the integrated
quality-pass plan and Phase 1 contract, then inspected the current dirty diff,
`src/smrik_fund/main.py`, related Analyst/Reviewer/discovery persistence code,
focused tests, and the latest real MSFT artifact:
`data/MSFT/03_output/analysis/adjustment_run_20260821T174220907587Z.json`.
No other current scout report was read.

## Conclusion

The latest run is broadly useful and state-safe at the artifact level: 4 topics,
8 candidates, all `human_review`/`not_applied`, reported and adjusted
reconciliation both `12 PASS / 0 FAIL / 0 SKIPPED`, and
`reported_equals_adjusted: true` (manifest lines 68–82 and 417 onward).
The CLI still has one acceptance-level output problem and two concrete sources of
avoidable noise/duplication. Keep the cleanup local to `main.py` and its focused
tests; do not decompose the 777-line orchestration module in this pass.

## Findings and proposals

### P0 — remove Python-created economic judgment from cross-period output

`build_normalization_summary()` synthesizes the sentence
`"this recurring pattern weakens a one-off normalization case"` from the mere
presence of multiple periods (`src/smrik_fund/main.py:197-204`), then renders it
(`main.py:244-245`). This violates the plan invariant that cross-period output
contains no Python-created economic judgment. A period recurrence can be shown as
a neutral deterministic fact, but whether recurrence weakens normalization is
Analyst/Reviewer judgment.

Smallest fix: delete `cross_period_observations` generation/rendering, or replace
it with neutral period-presence text only. Update the existing expectation in
`tests/test_adjustment_analysis.py:503-517`; do not replace it with another
policy sentence. This also removes a summary field that is only presentation
duplication.

### P1 — report history state based on this run, not file existence

Rows are appended only for auto-approved candidates (`main.py:572-607`) and are
written only when `history_rows` is non-empty (`main.py:650-658`). The final CLI
message instead checks only `history_path.is_file()` (`main.py:718-721`), so an
existing history file causes “preserved/updated” even when this run wrote nothing.
The latest run has 8 unapplied human-review candidates and the history file’s
filesystem timestamp predates the run; the message is therefore misleading.

Smallest fix: branch on `history_rows` (and optionally print the count), e.g.
“Adjustment history updated: 1 approved row” versus “Adjustment history unchanged
(0 approved rows).” Preserve the canonical CSV and all status distinctions.

### P1 — remove duplicate full candidate records from the manifest

Each topic record receives the complete candidate record list at
`main.py:608-610`, while the identical full list is also written at
`main.py:709-710`. In the latest manifest, `topics[*].candidates` and top-level
`candidates` each serialize to 21,325 characters; the manifest is 86,521 bytes.
Keep one canonical full list (top-level `candidates` is the clearest choice), and
retain per-topic status/count plus candidate IDs under `topics`. This is a safe
artifact-only simplification: no accounting mechanics or state changes. Update
the nested-list assertion in `tests/test_discovery.py:316-324` if this schema
choice is accepted. If manifest schema compatibility is prioritized, defer this
deletion and record it as known bloat rather than maintaining two copies.

### P2 — consolidate repeated artifact-path lines

The run prints one Analyst path per work item (`main.py:447-448`) and one Reviewer
path per reviewed candidate (`main.py:678-682`), then prints the integrated
manifest path (`main.py:718-724`). The latest run therefore emits 4 Analyst and 8
Reviewer path lines in addition to the canonical manifest path. The manifest and
topic records already preserve all paths. Replace the per-file lines with compact
counts (or suppress them and keep only the manifest path), retaining the final
artifact paths and the human-readable normalization summary.

### P2 — make the compact summary directly navigable

`build_normalization_summary()` already stores candidate IDs per period
(`main.py:174-179`), but `_render_normalization_summary()` omits them
(`main.py:239-243`). Show the ID beside each period/amount so an analyst can jump
from a grouped line to `reviews/<adjustment_id>_...json`. Add one neutral total
line (topics/candidates/approved/human-review/unresolved) if desired; do not print
evidence excerpts or duplicate Reviewer prose. Retrieval/Analyst failures are
currently persisted only in `topics` (`main.py:343-377`), so a compact failure
count would also improve CLI usefulness without adding a new stage.

### P3 — known CLI caveat: requested adjustment failure exits successfully

`analyze --adjustments` catches `AdjustmentAnalysisError`, prints an error, and
continues with exit code 0 (`main.py:754-766`). This may be intentional for the
optional flag, but it can look like a successful integrated run. Do not broaden
this scout into an exit-policy change; if left unchanged, keep it visible for the
gate/owner to decide.

## Affected surfaces

- Primary: `src/smrik_fund/main.py:120-268, 447-448, 608-724, 754-766`.
- Tests likely touched by accepted cleanup:
  `tests/test_adjustment_analysis.py:437-632` and
  `tests/test_discovery.py:316-324`.
- Evidence artifact inspected:
  `data/MSFT/03_output/analysis/adjustment_run_20260821T174220907587Z.json:68-82, 358-417, 1143+`.

## Invariants to preserve

- Reported signs, periods, missing values, cited evidence, locators, accession,
  and reported/adjusted separation remain unchanged.
- `Reviewer verdict`, risk-gate decision, final status, and application status
  remain separate and visible; all current human-review candidates remain
  `not_applied`.
- Null Xbox/divestiture amounts remain null/unresolved; no inferred amount or
  Python-created financial judgment is added.
- Only approved numeric rows can enter canonical history/application; exploratory,
  human-review, rejected, and unresolved candidates cannot alter adjusted P&L.
- Reconciliation warnings remain visible before adjustment output, per Section 2
  (`docs/ai_fund_v1_section_2_implementation_spec.md:517-532`).

## Non-goals

- No discovery/retrieval/Analyst/Reviewer/risk-gate redesign.
- No approval/materiality policy, human-review UI, new persistence/reporting
  framework, issuer generalization, or Task 10+ work.
- No broad `main.py` split/refactor; no source or test edits by this scout.
- No commit, push, or external write.

## Risks and verification

The cross-period change alters a presentation field and its test expectation;
verify that the final CLI contains no Python-authored economic conclusion while
Analyst/Reviewer text remains intact. If the duplicate manifest representation is
removed, verify all focused consumers use the retained canonical list.

Owner verification after implementation: focused adjustment/discovery tests;
latest MSFT fixture/live output inspection; `ruff` on changed Python; and
`git diff --check`. Confirm the final artifact still shows both reconciliation
summaries, `reported_equals_adjusted`, candidate IDs/paths, and distinct status
fields.

## Estimated size

Recommended bounded cleanup: 1 production file, 1–2 focused test files,
approximately 20–40 changed/removed lines. Manifest deduplication alone removes
about 21 KB from the latest run artifact; path consolidation reduces terminal
noise without affecting saved evidence. Defer any larger structural refactor.
