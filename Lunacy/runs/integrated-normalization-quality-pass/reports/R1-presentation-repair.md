# R1 presentation repair

Status: FINAL

## Changed

- Group labels now prefer the existing candidate sub-item (then target line),
  so a mixed-sign multi-period series is not titled as a gain/loss from its
  discovery topic.
- Display labels positive adjustment values as `candidate magnitude`; signed
  reported values retain their source sign.
- Summary period rows retain candidate ID plus Reviewer, gate, final, and
  application state; the renderer prints those states per period/candidate.
- Main output translates existing gate reason codes to concise factual wording;
  manifest records retain the full codes/reasons.

## Verification

Focused/full tests, Ruff, diff-check, real saved MSFT rendering, and history
hash proof are recorded in
`Lunacy/runs/integrated-normalization-quality-pass/evidence/R1-terminal-20260821T2105.md`.

No Analyst, Reviewer, gate policy, accounting, history, discovery, evidence, or
non-display schema behavior was changed. No commit or push.
