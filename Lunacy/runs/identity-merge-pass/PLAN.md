# Plan

Goal: compare the pre-correction and latest MSFT manifests, then prepare the stable-economic-identity milestone for commit and safe integration into `main`.

Authority: project `AGENTS.md`; current user request; completed identity-corrective-pass contracts; no identity redesign or new product functionality.

## Phase 1 — Manifest comparison and merge preparation

- One Luna xhigh owner compares `adjustment_run_20260822T145101565886Z.json` with latest `adjustment_run_20260822T183907711663Z.json` candidate-by-candidate, emphasizing identity status, keys, row keys, duplicate flags, history effects, OpenAI/Xbox/UTP behavior, and provenance exclusion.
- Inspect actual diff/status/docs. Perform only concrete milestone cleanup/docs fixes. Preserve unrelated user changes and canonical data. Do not commit/merge/push.
- Terminally verify focused identity/history/lifecycle/engine/Analyst/Reviewer/risk tests, full suite, Ruff changed Python, and `git diff --check`.

## Phase 2 — Independent integrity review

- Fresh read-only Luna xhigh attacks manifest interpretation, identity/provenance separation, target-row uniqueness, malformed/legacy authority, approved-version semantics, application arithmetic, unnecessary code, docs drift, and unrelated cleanup.
- Sol repairs only concrete failures, re-verifies invalidated checks, and gives PASS / DO NOT MERGE.

## Phase 3 — Commit and integrate

- On PASS only: create/switch to a scoped `codex/` feature branch while preserving the reviewed worktree, stage only milestone files, inspect cached stat/diff, commit conventionally, verify clean scoped state, inspect `main`/`origin/main`, and fast-forward `main` when safe.
- Inspect hooks/local/remote state before any push. Push only if needed. Do not delete the feature branch.
