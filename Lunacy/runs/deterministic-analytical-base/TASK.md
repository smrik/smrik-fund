# User task — deterministic analytical base

Build the smallest useful deterministic numerical-context layer for the existing three-year MSFT analytical P&L before any future Analytical Scan LLM calls. Do not add or modify LLM calls. Preserve all adjustment, identity, state, materiality, review, and reconciliation behavior. Do not commit or merge.

Read first: root `AGENTS.md`; `docs/ai_fund_v1_section_1_updated.md`; `docs/ai_fund_v1_section_2_implementation_spec.md`; current analytical P&L, reconciliation/adjustment code, tests, and current git status/diff.

## Required metrics

For every real source P&L line where meaningful: reported value by fiscal year; absolute YoY change; YoY growth; percent of revenue; YoY change in percent of revenue in bps; two-year CAGR. Preserve useful derived gross, operating, pre-tax, and net margins plus effective tax rate; expose levels and bps changes.

Math:

- Growth = current / prior - 1 only when both present, prior nonzero, no sign change, and not both negative. Absolute change still exists when both values exist.
- Common size = line / revenue using the displayed analytical magnitude. Null for missing/zero/invalid revenue and for EPS, share counts, ratios, or economically meaningless rows.
- Ratio movement = (current - prior) * 10,000.
- Two-year CAGR = (FY3 / FY1) ** 0.5 - 1 only for present positive endpoints; never use absolute values to force it.
- Missing stays null, never zero; reported source values remain unchanged.

Prefer extending current analytical output and one canonical calculation path. A separate derived table is allowed only if the existing wide shape would become materially confusing. Keep CSV/human/LLM formatting usability. Python provides numerical context only and must not judge unusualness, investigation value, recurrence, adjustments, or trend quality.

Do not add anomaly scores, thresholds, analytical materiality ranking, normalization, Reviewer fields, retrieval, segments, forecasts, LLM calls, classes/services/repositories/providers/managers/registries/DSLs/config/taxonomy/dependencies. Prefer explicit Pandas calculations in existing code. Stop with `DECISION_REQUIRED` before exceeding roughly 150–200 net new production lines.

Focused deterministic tests must prove:

1. positive growth;
2. zero denominator gives null growth;
3. negative-to-negative gives null growth but valid absolute change;
4. sign change gives null growth;
5. percent of revenue;
6. percent-of-revenue bps movement;
7. positive-endpoint two-year CAGR;
8. zero/negative/missing endpoints invalidate CAGR;
9. gross/operating margin bps movement;
10. missing remains null;
11. EPS/share rows have no meaningless common-size metrics;
12. reported source values unchanged.

Use a small synthetic fixture where possible and verify the real MSFT analytical P&L. Print a compact sample for Revenue, Cost of revenue, Gross profit, Research and development, Sales and marketing, General and administrative, Operating income, Other income (expense), net, Pretax income, Provision for income taxes, and Net income, showing FY24/FY25/FY26 values and relevant new metrics without interpretation.

Terminal verification: focused analytical-P&L tests; relevant reconciliation tests; full suite; Ruff on changed Python files; `git diff --check`; manual final diff inspection. Report exact commands/results, production added/deleted lines, simplicity decisions, real MSFT data-shape findings, and PASS / DO NOT MERGE.
