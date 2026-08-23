# G0 — read-only gate pack

Status: fresh post-A1 inspection; write barrier respected; no approval issued.

Workspace `C:\Projects\finance\smrik-fund`; branch `codex/idempotent-approved-application`; baseline `736c239`.

## Authority and navigation

- Run contract: `Lunacy/runs/approved-application-idempotency/PLAN.md:19-41,43-49` and `DECISIONS.md:3-4`.
- Product/source rules: `docs/ai_fund_v1_section_1_updated.md:363-401,438-482,500-508`; implementation rules: `docs/ai_fund_v1_section_2_implementation_spec.md:883-998,1001-1109`.
- Claimed implementation proof: `reports/I1-synthesis-implementation.md:7-33`, `evidence/I1-terminal-checks.md:7-12`.
- Simplicity review: `reports/A1-simplicity.md:7-45`.
- Actual tracked delta from baseline: `.vscode/settings.json` 4/1, `src/smrik_fund/main.py` 589/49, `tests/test_adjustment_analysis.py` 235/0; unrelated dirty/untracked artifacts remain preserved.
- Fresh focused check: `PYTHONPATH=src C:\Users\patri\miniconda3\envs\ai-fund\python.exe -m pytest tests/test_adjustment_analysis.py -q -p no:cacheprovider` -> **22 passed, 3 warnings**. No broad suite rerun.

## Acceptance matrix (evidence status, not G1 verdict)

| Contract | Current evidence | G0 status / exact navigation |
|---|---|---|
| Stable exact identity | Canonical JSON uses ticker, accession, exact source target, annual period, sub-item, sorted `(source, section, locator)` anchors; amount/prose excluded. | **Supported** — `src/smrik_fund/main.py:180-230`; S1 contract `reports/S1-identity-replay.md:12-32`. Replay test sees `new` then `replay` and reuses `A0001`: `tests/test_adjustment_analysis.py:375-452`. |
| First append + auto-approval + application | Real `_gate_conditions()` populates all gate fields; first run writes approved v1 and final application resolves latest history. | **Code-supported, proof gap** — `main.py:1127-1254,1297-1322`; first test checks row/status and final 90, but does not snapshot adjusted P&L immediately after run 1 or assert run-1 `final_status=approved/application_status=applied` (`tests/test_adjustment_analysis.py:408-450`). |
| Identical replay: bytes/ID/version/amount; no double apply | Replay branch skips Reviewer/history append; CSV bytes are compared; `resolve_current_adjustments()` then applies one persisted row. | **Mostly supported** — `main.py:256-308,1040-1084,1297-1314`; test asserts bytes, one row, v1, same ID, reviewer called once (`tests/test_adjustment_analysis.py:431-452`). Amount is only indirect via byte equality; no explicit amount assertion and both output reads occur after run 2. |
| Changed state safety | Same identity + changed amount -> state conflict; preserves v1, appends proposed v2, latest-version resolution removes application. | **Supported for amount** — `main.py:286-307,1146-1201,1307-1314`; `tests/test_adjustment_analysis.py:454-509`. Period/target are identity changes per S1 and are not separately tested (`reports/S1-identity-replay.md:34-44`). |
| Distinct economic adjustments | Different exact identity gets a new candidate ID; overlap logic can mark same-line/period amount/sub-item/reason overlap. | **Code-reviewed; proof gap** — `main.py:118-125,330-407`; no focused test proves two genuinely distinct approved candidates stay separate, nor an overlap candidate becomes human review. |
| Legacy / ambiguous identity failure | Missing identity columns, malformed identity/state, invalid versions, or one key resolving to multiple IDs return `unknown`; integration records no canonical row and does not auto-approve. | **Code-reviewed fail-closed; proof gap** — `main.py:256-308,1034-1084`; no lifecycle test seeds legacy or ambiguous persisted CSV and asserts no reviewer/history/application. |
| Human-review / rejected / unresolved safety | Unknown live materiality, missing evidence, and unresolved review do not append; latest proposed/rejected state is not resurrected. | **Partial** — empty-history/live/unresolved paths tested: `tests/test_adjustment_analysis.py:511-552,610-676`; existing latest-version resolver is covered: `tests/test_adjustments.py:89-120`. No integrated replay-after-approved test with reviewer reject/revise or pre-existing rejected/proposed latest row. |
| Reported immutability and sign convention | Application copies P&L, subtracts positive magnitude once, recalculates derived rows; negative source/over-target/derived/missing cases block facts. | **Supported in unit mechanics + gate builder** — `src/smrik_fund/ingestion/adjustments.py:25-99`, `tests/test_adjustments.py:123-146`, `tests/test_adjustment_analysis.py:554-608`; lifecycle test uses fresh P&L objects, so same-object immutability is not asserted there. |
| All gate inputs known in proved case; frozen materiality only | Frozen fixture passes explicit `materiality_passed=True`; test requires every serialized condition non-null. Live omitted materiality remains `None` and no history file is created. | **Supported at frozen boundary** — `PLAN.md:43-45`; `main.py:640-800,1127-1177`; `tests/test_adjustment_analysis.py:415-442,511-552`. Public CLI does not pass the fact, so live path remains fail-closed. |
| Latest-version history semantics | Current set derives latest version first, then status; proposed v2 removes prior approval. | **Supported** — `src/smrik_fund/ingestion/adjustments.py:25-50`; authoritative spec `docs/ai_fund_v1_section_2_implementation_spec.md:974-998`. |
| Scope / simplicity | A1 found five removable copies/wrappers and no generic persistence framework. | **Residual scope warning** — actual delta is 589 added production lines + 235 test lines in two files, above AGENTS' ~200-line scope-warning heuristic and S1/S2/S3 estimates; review `reports/A1-simplicity.md:13-36` against `git diff --stat 736c239`. |

## Frozen-boundary and residual facts

- The only demonstrated auto-approval is the deterministic test fixture. No numeric materiality threshold was added; this matches D1 and is required for live safety.
- `adjustment_history.csv` remains the canonical store; `apply_adjustments()` starts from the supplied reported frame and never applies to the prior adjusted CSV (`main.py:1297-1322`, `ingestion/adjustments.py:53-99`).
- Sequential persisted-CSV replay is the only exactly-once claim. Crash-safe/concurrent writers remain explicitly out of scope (`reports/I1-synthesis-implementation.md:29-33`).
- Diagnostic text says `len(history_rows) approved rows` even when a changed-state proposed row is appended (`main.py:1368-1374`); non-functional but misleading.
- Existing `.vscode/settings.json` change and untracked `.codemap`, `.notes.local.md`, `.out-of-code-insights`, `.vscode/local-comment`, `Lunacy`, and `docs/annotations` are unrelated/preserved.

## Parent G1 navigation

1. Resolve whether the first-run proof gap (snapshot run-1 adjusted value, run-1 status, explicit history amount) is acceptable or requires a small test-only fix.
2. Decide whether missing legacy/ambiguity, distinct-candidate, and persisted non-approval tests are required for this acceptance, versus code-reviewed residuals.
3. Reconcile the 589-line production delta with the AGENTS scope warning and the simplicity report before any merge verdict.
4. Keep materiality frozen-only; do not add a threshold or make live MSFT auto-approval claim.
