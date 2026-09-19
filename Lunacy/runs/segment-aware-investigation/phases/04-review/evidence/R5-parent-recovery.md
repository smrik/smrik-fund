# R5 parent recovery evidence

R5 vanished without a mailbox event, report, or evidence file. Its partial worktree edits were inspected directly and retained only after parent verification.

## Recovered behavior

- Narrative content words are evidence-dependent regardless of capitalization; unsupported lowercase company/product vocabulary fails closed.
- Every cited excerpt must support every non-generic narrative term.
- Causal claims require one contiguous local source clause, not a causal token plus scattered vocabulary.
- Four focused regressions cover lowercase vocabulary, per-reference coverage, complete causal clause, and preserved consolidated neutral narrative.

## Terminal checks

- Filing investigation: `71 passed`, `39 subtests passed`.
- Analytical Scan, segments, adjustment analysis/state: `70 passed`, `7 subtests passed`.
- Full suite: `233 passed`, `84 subtests passed`.
- Ruff changed source/tests: PASS.
- `python -m compileall -q src`: PASS.
- `git diff --check`: PASS; only line-ending warnings.
- Fresh R3 rank-2 and rank-4 saved investigation result/packet pairs revalidated under final rules: PASS (`5` and `1` disclosed drivers).

No live artifact rewrite, filing/source-data rewrite, adjustment/approved-state write, commit, or merge.
