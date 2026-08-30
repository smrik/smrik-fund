# Decisions

- 2026-08-28: User explicitly selected full Hive; use three scouts, one max synthesis/implementation owner, one fresh read-only reviewer, then parent gate.
- 2026-08-28: Reviewer is also the Hive simplicity adversary and remains read-only to satisfy the explicit one-fresh-reviewer contract. No separate gate scout unless terminal evidence later conflicts.
- 2026-08-28: A1 found query-cap line starvation and a mixed-token causal-grounding bypass. Both are concrete, bounded, and inside existing contracts; authorize R1 only for those fixes plus invalidated proof refresh.
- 2026-08-28: R1 changed the reviewed state and supersedes A1's DO NOT MERGE blockers. Require one read-only gate scout because terminal reports now describe different code states; scout compresses evidence only and is not a second reviewer.
- 2026-08-28: Parent G1 inspected the three final code regions, ran targeted acceptance tests and live artifact/state probes, confirmed A1 P1/P2 closure, and issued PASS. No commit or merge.
