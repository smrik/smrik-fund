# A1 integrity probes

Scope: current Phase 2 worktree; fixtures from `tests/test_filing_investigation.py`; no
production/state writes. Command used `PYTHONPATH=src;tests` with the ai-fund
Python environment.

## Terminal output

```
valid S01 PASS
stale REJECT unknown or stale persisted segment ref: S99
accession REJECT segment ref S01 accession does not match saved filing
reported_basis REJECT segment ref S01 is not on reported basis
yoy_growth ACCEPT 999.0
operating_margin ACCEPT 999.0
revenue_growth_contribution ACCEPT 999.0
reported_value ACCEPT 999.0
period_end ACCEPT 1900-01-01
period_start ACCEPT 1900-01-01
```

The probes mutate every row in S01 after `assign_segment_refs`; resolver accepts
the valid row and correctly rejects stale/accession/basis mutations. It does not
recompute or cross-check persisted deterministic values (`yoy_growth`, margin,
contribution, reported value) or source-period metadata (`period_end`,
`period_start`). Exact implementation boundary: `filing_investigation.py:129-223`.

## Safe simplification

Removed the one-use `_json_number` alias and called the existing `_finite`
conversion directly at resolver call sites. No API or output behavior changed.

## Live narrative-grounding probe

Rank 2 result (`live-rank2/.../filing_investigation_02_rank2-live-mini-v6.json:1467-1519`)
uses causal paraphrases `because of` and `linked to`; its cited E3/E7/E9 excerpts
use `driven by` (`finding_02_rank2-live-mini-v6_initial.md:39,71,87`). Rank 4
uses `ties ... to` (`live-rank4/.../filing_investigation_04_rank4-live-mini-v9.json:1173`),
while E1 says `driven by` (`finding_04_rank4-live-mini-v9_initial.md:23`).
The validator's causal vocabulary is only `cause/drive/due to/attribute/result/
stem/explain/associated with/related to` (`filing_investigation.py:1457-1463`),
so these live causal paraphrases pass despite the v6 prompt's exact-word rule.

Direct replay of `validate_financial_investigation` against both saved results
and their initial packets returned `rank2 VALIDATED 5` and `rank4 VALIDATED 0`.
