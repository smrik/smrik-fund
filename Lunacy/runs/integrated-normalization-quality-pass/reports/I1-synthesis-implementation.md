# I1 synthesis and implementation

Status: FINAL

## Judgement

Implemented the smallest supported fixes from S1-S3. No decision required.

## Changed

- Removed Python-authored cross-period economic judgment from `build_normalization_summary`; stale test expectation removed.
- Grouped output now shows exact signed reported value, positive candidate magnitude, amount basis, and candidate IDs. Ambiguous/missing source values stay undisclosed.
- `_gate_conditions` now records the deterministic negative-source fact, so signed losses remain explicitly blocked from auto-approval.
- Analyst prompt v2 makes signed-loss treatment and positive-magnitude mechanics explicit; OpenAI “primarily” attribution remains Analyst/Reviewer-owned.
- Compact Analyst/Reviewer artifact counts replace repeated path lines; the manifest retains paths. History output now distinguishes this run's `0` approved rows from an actual update.
- Added focused signed-source/gate regression coverage.

## Verification

- Focused tests: `25 passed`; full tests: `64 passed, 3 warnings, 26 subtests passed`.
- Ruff on changed surfaces: pass. `git diff --check`: pass.
- Real `analyze MSFT --adjustments`: exit 0; final manifest has `4` topics/`8` candidates, both reconciliations `12 PASS / 0 FAIL / 0 SKIPPED`, `reported_equals_adjusted=true`, and all candidates `human_review`/`not_applied`.
- OpenAI FY2026/FY2025/FY2024 reported values render `+10.697bn/-4.901bn/-1.646bn`; null Xbox/divestiture amounts stay unresolved; “primarily—not exclusively” attribution is retained.
- Canonical history SHA-256 and row count unchanged: `4C15AC69286E85C1BB828BB7E0BB04CC3967F8022EE57053DB49CAE6483704D8`, `23` rows.

Evidence: `Lunacy/runs/integrated-normalization-quality-pass/evidence/I1-terminal-20260821T183152.md`.

## Deferred / not changed

Manifest topic candidate-list duplication and repeat-run idempotence remain deferred; no new policy, cache, reporting framework, discovery stage, or approval behavior was added. No commit/push.
