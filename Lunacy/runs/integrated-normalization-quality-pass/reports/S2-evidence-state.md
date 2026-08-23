# S2 — evidence/state scout

## Scope / approach

Read `AGENTS.md`, the two V1 authority docs, this run's `PLAN.md`/S2 steps, current source/tests/diff, and the latest MSFT run artifacts. Did not read other scout reports. Read-only except this report.

## Findings

### Evidence integrity and pointers — mostly PASS

- `src/smrik_fund/ingestion/filing.py:239-357` retrieves from `filing.text()`, renders exact contiguous source lines, and records source line/character offsets plus EdgarTools section locators. `:414-472` requires packet identity, item source/section/locator/excerpt, and accession retention; `:508-522` rejects unknown candidate evidence IDs.
- Latest packet preserves one accession and exact quoted text:
  - OpenAI: `data/MSFT/03_output/evidence/01_openai_investment_gains_20260821T174220907587Z.md:17-31` (E1/E2; FY2026 gain, FY2025/FY2024 losses; locators/offsets retained).
  - XBOX: `.../02_xbox_impairment_expenses_20260821T174220907587Z.md:17-39` (E1-E3; qualitative only, no invented amount).
  - Divestiture: `.../03_divestiture_gains_20260821T174220907587Z.md:17-23` (E1; prior-period wording only).
  - Tax interest: `.../04_uncertain_tax_position_interest_20260821T174220907587Z.md:17-23` (E1; FY2026/25/24 amounts, net of tax benefits).
- Latest candidate records retain the required fields and IDs: `data/MSFT/03_output/analysis/adjustment_run_20260821T174220907587Z.json:419-484` (A0024), `:687-756` (A0027), `:821-889` (A0028), and `:954-1137` (A0029-A0031). Per-topic Analyst metadata retains accession/source/evidence file at `data/MSFT/03_output/analysis/01_openai_investment_gains_20260821T174220907587Z.json:2-26`; candidate schema is `src/smrik_fund/ingestion/adjustment_analysis.py:37-58`.
- Residual integrity gap: packet validation checks structure and accession text but does not re-derive each locator/offset/excerpt from the filing on later reads (`filing.py:414-472`). Integrated flow validates the freshly retrieved packet before Reviewer (`main.py:461-490`), so the current run is bounded; mutated/stale packet files are not content-verified. No new provenance mechanism is warranted in this pass.

### Prompt neutrality — PASS for integrated path

- Discovery receives only bounded statement-label windows (`src/smrik_fund/ingestion/discovery.py:129-232`) and its prompt forbids amounts, citations, approval decisions, and workflow state (`:26-41`). No MSFT/golden-case hint is embedded in that prompt. Analyst/Reviewer prompts only instruct use of supplied P&L/evidence (`adjustment_analysis.py:20-34`, `reviewer.py:23-42`). Reviewer fixture asserts frozen facts do not leak into the system prompt (`tests/test_reviewer.py:130-155`).
- The fixed `RESTRUCTURING_SEARCH_QUERIES` seam (`filing.py:14-19`, `:379-397`) remains a legacy direct API, but `_run_adjustment_analysis` uses discovery-supplied literal queries (`main.py:328-370`); no hardcoded candidate path was observed in the integrated run.

### Reviewer / gate / application separation — PASS, with a conservative gap

- `ReviewResult` is explicitly non-final (`reviewer.py:45-60`); the pure gate returns only `auto_approve|human_review` (`risk_gate.py:49-129`). Main keeps `review`, `gate`, `final_status`, and `application_status` as separate manifest fields (`main.py:547-570`).
- Latest run has 8 candidates (A0024-A0031), all `final_status=human_review`, `application_status=not_applied`, and `reported_equals_adjusted=true` (`adjustment_run_20260821T174220907587Z.json:78`, candidate blocks `:419-1677`). Tax candidates A0029-A0031 have Reviewer `accept` but remain gate `human_review`; this is not hardcoded tax rejection.
- `_gate_conditions` only establishes reconciliation and source availability (`main.py:271-296`); all other `RiskGateConditions` remain `None`, so live integrated candidates cannot auto-approve because the gate fail-closes (`risk_gate.py:107-126`). This is safe but means the real path has no demonstrated auto-approval without a test patch; existing fixture coverage patches conditions (`tests/test_adjustment_analysis.py:300-367`).
- Separation is weaker in the human-facing summary: `main.py:248-255` concatenates Reviewer concerns, Analyst uncertainty, Reviewer notes, and processing errors under `Unresolved issue / Reviewer concern`. The manifest preserves separate arrays, but CLI provenance of the displayed sentence is ambiguous.

### History / repeat-run state — current exploratory run safe; rerun risk remains

- Main appends canonical history only for gate-approved rows (`main.py:572-607`) and writes only when `history_rows` is non-empty (`:650-658`). Current run candidates start at A0024 while `data/MSFT/03_output/adjustment_history.csv` ends at A0023 (23 rows; file timestamp `2026-08-20`, run manifest timestamp `2026-08-21`); SHA-256 at inspection: `4C15AC69286E85C1BB828BB7E0BB04CC3967F8022EE57053DB49CAE6483704D8`. Thus this exploratory run left canonical history unchanged and no human-review/null candidate affected adjusted P&L.
- Deterministic state resolution is correct: latest version per ID is selected before `status == approved` (`src/smrik_fund/ingestion/adjustments.py:25-50`), and application copies/recomputes without mutating reported input (`:53-99`).
- Repeat-run/cache safety is unimplemented: each run gets a fresh ID (`main.py:84-85`, `:319`), fresh evidence/analysis/review filenames (`:346-400`, `reviewer.py:171-188`), and fresh candidate IDs (`main.py:469-471`); no same-filing/topic/model/prompt reuse check exists. A rerun that auto-approves can append duplicate economic rows under new IDs. Existing tests cover one run's human-review and auto-approval paths (`tests/test_adjustment_analysis.py:179-240`, `:300-367`) but no rerun/approved-history idempotence.

### Cross-period state warning

- `build_normalization_summary` emits the Python-authored sentence “this recurring pattern weakens a one-off normalization case” (`main.py:197-204`), visible for OpenAI and tax groups in the latest manifest (`adjustment_run_...json:113-114`, `:315-316`). This is economic judgment generated outside Analyst/Reviewer, contrary to the plan invariant that cross-period output contain no Python-created judgment. It does not feed the gate/application, but should be removed or reduced to a neutral deterministic observation by the owner.

## Verification / scope

- Structural tests are well-targeted: evidence exact text/locator and fail-closed refs (`tests/test_filing.py:53-123`), Reviewer payload/neutrality (`tests/test_reviewer.py:130-163`), gate signals (`tests/test_risk_gate.py:67-229`), and non-application of human-review candidates (`tests/test_adjustment_analysis.py:179-248`).
- Focused pytest could not execute in this shell: `uv run pytest ...` hit `C:\Users\patri\AppData\Local\uv\cache` ACL denial; plain `python -m pytest ...` lacked installed `pandas`/editable package. No source/test/config changes made.
- Affected surfaces: `filing.py`, `adjustment_analysis.py`, `reviewer.py`, `risk_gate.py`, `adjustments.py`, `main.py`, associated tests and `data/MSFT/03_output` artifacts. Non-goals: no cache/provenance framework, approval-policy redesign, human-review UI, or source edits. Estimated fix size: small (summary wording + focused rerun/state tests); cache/idempotence would be a separate bounded change.
