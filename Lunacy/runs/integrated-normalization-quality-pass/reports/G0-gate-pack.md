# G0 gate pack

Status: FINAL, read-only scout. No approval recommendation. Write barrier was closed.

## Authority and navigation

- `AGENTS.md`: preserve reported values/signs/missingness; Python owns mechanics; scope and validation rules.
- `docs/ai_fund_v1_section_1_updated.md:143-168`: MSFT V1 completion; `:275-335`: immutable reported data and one adjustment engine; `:471-532`: positive-magnitude sign convention and missing values; `:1087-1115`: conservative human-review gate.
- `docs/ai_fund_v1_section_2_implementation_spec.md:39-58`: V1 completion definition; `:344-389`: signed source rule; `:762-830`: Reviewer contract; `:1301-1335`: deterministic gate; `:1398-1449`: application and adjusted reconciliation; `:1649-1687`: CLI run behavior; `:1748-1821`: reproducibility/history preservation.
- `PLAN.md:9-29`: run goal/invariants; `PLAN.md:31-41`: ten gate acceptance criteria.
- `STATE.md:1-11`: Phase 4 active, barrier closed, G0 ready.

## Acceptance matrix (evidence status only; parent decides verdict)

| # | Acceptance | Evidence | G0 observation |
|---|---|---|---|
| 1 | Real MSFT run and concise output | `evidence/I1-terminal-20260821T183152.md:12-25`; manifest below | PASS evidence: logical `analyze MSFT --adjustments`, exit 0, 4 topics/8 candidates. Full raw CLI transcript is not stored; excerpt below is reconstructed from the current renderer plus captured facts. |
| 2 | OpenAI signs/periods/attribution | `data/MSFT/03_output/analysis/adjustment_run_20260821T183152175247Z.json:84-138,430-491,495-560,564-593` | PASS: FY2026 `+$10.697bn`, FY2025 `-$4.901bn`, FY2024 `-$1.646bn`; evidence retains primarily—not-exclusively attribution; losses remain human review. |
| 3 | Xbox/divestiture null amounts unresolved | same manifest `:1366-1433,1437-1502`; evidence `:24` | PASS: Xbox A0027 and divestiture A0028 amounts are JSON `null`, not zero, and `not_applied`. |
| 4 | No Python-created cross-period economic judgment | `src/smrik_fund/main.py:148-231`; manifest `:25` / evidence `:25` | PASS: summary carries per-period source/candidate facts; no `cross_period_observations` field. |
| 5 | Tax-position grouping does not hardcode rejection | manifest tax records around `:1600-1703` | PASS behaviorally: each tax candidate is Reviewer `revise` with evidence/policy concerns; gate includes `reviewer_verdict_revise`, not a tax-topic rule. |
| 6 | Reviewer, gate, application states distinct | `main.py:591-651`; manifest `:430-491` and `:495-560` | PASS: `review.verdict`, `gate.decision`, `final_status`, and `application_status` remain separate fields. |
| 7 | Human-review candidates do not affect adjusted P&L | manifest `:68-78` and all candidate records | PASS: all 8 are `human_review`/`not_applied`; `reported_equals_adjusted=true`; both reconciliations 12/0/0. |
| 8 | Exploratory run leaves canonical history unchanged | evidence `:27-29`; manifest `:65` | PASS: SHA-256 `4C15AC69286E85C1BB828BB7E0BB04CC3967F8022EE57053DB49CAE6483704D8`, 23 rows before/after; CLI says `Adjustment history unchanged (0 approved rows)`. |
| 9 | Relevant tests pass | evidence `:5-10`; `A1-simplicity.md:33-39` | PASS inherited evidence: focused 25 passed; full 64 passed, 3 warnings, 26 subtests. No broad rerun in G0. |
| 10 | Ruff and `git diff --check` pass | evidence `:7-10`; `A1-simplicity.md:35-40` | PASS inherited evidence; line-ending warnings only. |

## Final artifact and CLI navigation

Primary manifest:
`data/MSFT/03_output/analysis/adjustment_run_20260821T183152175247Z.json`

Manifest paths/summary: `:65-80` (`adjustment_history.csv`, `adjusted_pnl.csv`, adjusted reconciliation, 12/0/0 both sides, `reported_equals_adjusted=true`). OpenAI grouped periods: `:84-138`. Xbox/divestiture: `:1366-1502`. Tax topic/candidates: `:1600-1703`. Top-level candidates repeat the same state records after `:1160`.

Related final artifacts:

- `data/MSFT/03_output/adjusted_pnl.csv` (last write 2026-08-21 20:41:56 +02:00)
- `data/MSFT/03_output/adjusted_reconciliation_checks.csv` (last write 2026-08-21 20:41:56 +02:00)
- `data/MSFT/03_output/adjustment_history.csv` (canonical; unchanged SHA/23 rows)
- `Lunacy/runs/integrated-normalization-quality-pass/evidence/I1-terminal-20260821T183152.md`

Concise final CLI excerpt (the evidence file stores the facts, not a raw transcript):

```text
Reconciliation: 12 passed, 0 failed, 0 skipped
Saved Analyst JSON files: 4 (see integrated manifest)
Saved Reviewer JSON files: 8 (see integrated manifest)
Normalization summary (display groups; candidate mechanics unchanged):
Item: OpenAI investment dilution gain | Target line: Other income (expense), net
  Periods / reported vs candidate amounts: 2026-06-30 (FY)=reported +$10.7bn, candidate $6.5bn (disclosed) [A0024]; 2025-06-30 (FY)=reported -$4.9bn, candidate $4.8bn (disclosed) [A0025]; 2024-06-30 (FY)=reported -$1.6bn, candidate $1.5bn (disclosed) [A0026]
...
Adjustment history unchanged (0 approved rows): data\MSFT\03_output\adjustment_history.csv
Saved adjusted P&L: data\MSFT\03_output\adjusted_pnl.csv
Saved adjusted reconciliation: data\MSFT\03_output\adjusted_reconciliation_checks.csv
Saved integrated adjustment run: data\MSFT\03_output\analysis\adjustment_run_20260821T183152175247Z.json
```

## Exact targeted diff regions

I1 behavior surface:

- `src/smrik_fund/ingestion/adjustment_analysis.py:17-37,58-62`: Analyst prompt/schema v2; positive-magnitude mechanics, signed-loss handling, null amount/research request.
- `src/smrik_fund/main.py:148-231`: display-only grouped summary; exact source lookup; no authored cross-period assessment.
- `src/smrik_fund/main.py:234-307`: compact summary renderer; signed reported values, candidate amount/basis/IDs, distinct Reviewer/gate/final/application labels.
- `src/smrik_fund/main.py:310-337`: `_gate_conditions` records exact signed-source availability/negative fact.
- `src/smrik_fund/main.py:340-772`: integrated discovery/retrieval/Analyst/Reviewer/gate persistence, history protection, adjusted P&L/reconciliation, manifest and final paths.
- `tests/test_adjustment_analysis.py:442-588,590-660`: grouping/state, signed-source gate, null amount, compact CLI/history regressions.

A1 behavior-preserving deletion:

- `src/smrik_fund/ingestion/filing.py:67-76`: `_source_matches` retains literal no-match error and delegates span rendering to `_source_matches_by_offsets`; regex/literal rendering now shares one renderer.

Current new integration surfaces (full-file additions visible in the dirty worktree): `src/smrik_fund/ingestion/discovery.py`, `filing.py`, `reviewer.py`, `risk_gate.py`, plus `tests/test_discovery.py`, `test_filing.py`, `test_reviewer.py`, `test_risk_gate.py`. Unrelated/pre-existing dirty surfaces observed and not audited by this gate: `.vscode/settings.json`, `src/smrik_fund/ingestion/statements.py`, `tests/test_analytical_pnl.py`, `.codemap/`, `.notes.local.md`, `.out-of-code-insights/`, `.vscode/local-comment/`, and other local artifacts.

## Verification freshness

- I1 terminal evidence saved 2026-08-21 20:36:06 +02:00; artifact manifest last write 20:35:11; adjusted outputs last write 20:41:56.
- A1 snapshot 2026-08-21 20:43:13 (+02:00), report last write 20:43:37; it records 11 filing/discovery tests, full 64-test run, Ruff, diff-check, and unchanged artifact state.
- G0 performed read-only inspection only. No source/test/config edits and no broad test rerun.

## Contradictions / residuals for parent G1

1. `main.py:310-337` only sets reconciliation/source availability/negative facts. Materiality, duplicate, group reconciliation, aggregate/individual over-adjustment, zero-target, and deterministic-check fields remain `None`; the real artifact therefore shows generic `*_failed_or_unknown` reasons and no candidate reaches `auto_approve`. This is conservative/state-safe, but it does not demonstrate a real approved application and is a residual against the broader Section 2 auto-approval path.
2. `topics[*].candidates` plus top-level `candidates` duplication remains deferred (`A1-simplicity.md:23-25`; I1 `:28-30`) because current focused consumers assert the nested shape.
3. Compact CLI combines Reviewer concerns, Analyst uncertainty, Reviewer notes, and processing errors under `Unresolved issue / Reviewer concern` (`A1-simplicity.md:26-29`); presentation semantics were intentionally not changed.
4. Fresh run/candidate IDs are non-idempotent across reruns (`A1-simplicity.md:30-31`; I1 `:28-30`).
5. `reported_equals_adjusted=true` is correct for this exploratory run because no candidate was applied; actual approved-adjustment arithmetic is covered by focused fixture tests, not exercised by this final real artifact.

No approval, merge, commit, or push recommendation is made by G0.
