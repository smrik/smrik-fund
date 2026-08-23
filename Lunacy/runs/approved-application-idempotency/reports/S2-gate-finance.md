# S2 — deterministic gate / finance

## Finding

The gate itself is conservative and should remain so. `RiskGateConditions` defaults every mechanical fact to `None`, and `evaluate_risk_gate()` rejects every unknown (`src/smrik_fund/ingestion/risk_gate.py:13-30,49-59,107-126`). The integration is not yet capable of auto-approval: `_gate_conditions()` populates only `reconciliation_clear`, `source_target_available`, and the signed `source_target_negative` (`src/smrik_fund/main.py:376-403`). Materiality, duplicate, group, aggregate, individual-over-adjustment, zero-target, and final deterministic checks therefore remain unknown. The current approved-path test hides this by patching `_gate_conditions` with all `True`/`False` values (`tests/test_adjustment_analysis.py:306-373`).

This is a real missing-input problem, not a gate-policy problem. The authoritative docs require all relevant inputs to be known, preserve signed source values, block missing/ambiguous facts, scope reconciliation warnings to affected lines, and never use plugs or fuzzy matches (`docs/ai_fund_v1_section_2_implementation_spec.md:400-442,460-481,1266-1335`).

## Smallest compliant approach

Keep `evaluate_risk_gate()` and `RiskGateConditions` unchanged. Replace the current three-field `_gate_conditions()` call with one small, deterministic builder (local to the integration unless reuse is proved necessary) that receives:

- the reported P&L and candidate;
- scoped source reconciliation checks;
- persisted current adjustments and same-run candidates;
- the stable identity/replay result from S1;
- explicit optional group facts for the proved fixture (group id / disclosed total, if any).

Do not make the builder infer financial judgment. It should only calculate facts and return `None` when a fact is unavailable.

For the one approved fixture, prove each condition as follows:

| Gate input | Deterministic proof |
|---|---|
| target / period / evidence | Exact unique `label`/`standard_concept`, annual period present, numeric finite source value; reject derived subtotal targets. Evidence identity/ref validation remains the existing filing contract. Reviewer `accept`, `strong`, `low`, matching `disclosed`/`calculated` basis remain required by the gate. |
| signed target / over-adjustment | Preserve the reported signed value. `source_target_negative` is `source < 0`; individual over-adjustment is `amount > positive source`; zero-target flag is `source == 0 and amount > 0`. Missing, non-finite, ambiguous, or negative amounts remain unsafe. |
| reconciliation | Evaluate only checks for the candidate period and target-affecting lines. `PASS` is clear; `FAIL` and `SKIPPED` are not clear. Do not use the current `all(status == PASS)` behavior as a global substitute: the spec says unrelated warnings must not block unrelated lines. |
| aggregate | Sum persisted approved plus same-run distinct candidates for exact target-line/period, excluding the S1-recognized replay identity. Compare the positive aggregate with the signed source. Multiple real adjustments on one line-period are valid; they are not duplicates merely because line/period match. |
| duplicate | Use S1's durable identity/replay outcome plus simple observable overlap (amount/evidence/sub-item/reason). Empty history + one known candidate proves `False`; same recognized identity is replay, not a second adjustment; uncertain/distinct overlap is `True` and human review. Do not auto-merge. |
| group | For an explicitly ungrouped fixture, record that no linked group/disclosed total exists. If a group/total exists, compare proposed group sum to the disclosed total; missing/ambiguous group facts stay `None`. Never fabricate a total or allocation. |
| deterministic checks | Preview the candidate through the existing `apply_adjustments()` on a copy and run `reconcile_pnl()` on the result. Require source-line targeting, present period/value, no application exception, and no adjusted `FAIL`; do not mutate reported P&L. |
| materiality | Calculate the documented ratios (`amount/revenue`, `amount/target`, and `amount/operating income` where denominators are known) from reported signed values and persist them. **Authority gap:** no numeric threshold exists in the docs, while the plan explicitly excludes a new approval/materiality policy. Do not silently choose one. The parent must either supply an approved provisional threshold/frozen-case materiality fact, or leave this case human-review (which cannot satisfy the auto-approval acceptance). |

The current fixture is suitable for the mechanical proof: one `Research and development` candidate, FY2025, amount 10, reported target 100, revenue 1,000, operating income 200, no linked group, and a fully passing reported tie-out. Its expected application is `100 - 10 = 90`; `apply_adjustments()` already preserves the input and recomputes subtotals (`src/smrik_fund/ingestion/adjustments.py:53-99`). The fixture is not the gold Analyst case (`tests/msft_restructuring_gold.md`), whose amount is intentionally unknown and therefore cannot auto-approve.

At the integration boundary, the builder must receive enough context to distinguish first-run empty history, replay of the same stable identity, and a materially changed candidate. This is needed before assigning a new ID at `main.py:576-579`; the current call has no history/candidate context (`main.py:557-565,654-658`). Persist the computed condition snapshot with the candidate/gate record (and canonical history fields where applicable) for audit; never alter reported rows.

## Focused proof

1. Replace the patched `_gate_conditions` in `test_auto_approved_fixture_reaches_existing_application_engine` with the real builder. Assert all ten condition fields are non-`None`, the decision is `auto_approve`, one approved history row exists, and adjusted R&D is 90 while the original P&L remains 100.
2. Use the same persisted history and same frozen candidate twice. Assert stable identity, no new history row/version, and adjusted R&D remains 90 (not 80). This overlaps S1/S3 but is required to prove the gate facts are not being fabricated on replay.
3. Add focused fail-closed cases for missing/ambiguous/negative/derived targets, missing period/value, `FAIL`/`SKIPPED` relevant reconciliation, duplicate overlap, absent group facts, aggregate and individual over-adjustment, zero target, and changed amount/evidence. Existing `test_risk_gate.py` already proves the pure evaluator rejects each supplied false/unknown condition (`tests/test_risk_gate.py:160-233`); new tests must prove the builder computes those conditions rather than patching them.
4. Assert adjusted reconciliation has no `FAIL`, signs are unchanged, and history/application remain separate. Run the focused lifecycle tests, Ruff on changed files, and `git diff --check`.

## Invariants / non-goals

- Fail closed on unknown or ambiguous target, period, evidence, amount, materiality, duplicate, group, reconciliation, or application facts.
- Positive approved amount remains a magnitude removed by `reported - amount`; negative reported source values remain negative and block this auto-approval path.
- Adjust only source lines; recompute derived subtotals; reported P&L is immutable; adjusted reconciliation is a hard check.
- Do not change reviewer verdict semantics, add a second adjustment engine, merge candidates, invent group totals, add a generic materiality/deduplication framework, or widen the MSFT case.

## Risks / decision required

The only authority-level blocker is materiality: the docs define metrics but deliberately leave thresholds pending real MSFT calibration (`docs/ai_fund_v1_section_1_updated.md:1119-1146,2181-2185`), while the lifecycle plan forbids a new materiality policy. Picking a numeric limit inside `_gate_conditions()` would violate the task’s “without inventing policy” constraint. Require an explicit parent decision or a frozen approved threshold/fact before claiming a real auto-approved case.

The second implementation risk is silently treating absent group/duplicate context as safe. Make “ungrouped” and “no duplicate” explicit facts from the bounded fixture/identity context; otherwise return `None` and preserve human review.

## Estimated size

Assuming the materiality authority decision and S1/S3 interfaces are available: 1 production integration file plus at most a small gate helper, 1–2 focused test files, roughly 80–150 new lines. No changes needed to the pure gate or application arithmetic. If a new materiality policy is required, stop and obtain approval rather than expanding this lane.
