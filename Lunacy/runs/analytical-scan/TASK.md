# Analytical Scan milestone

Implement the first end-to-end Analytical Scan for the current real MSFT analytical P&L.

## Product contract

Flow: canonical analytical P&L -> compact deterministic context -> Analytical Scan LLM -> ranked investigation topics.

The scan allocates analyst attention. It identifies material numerical movements, why they deserve investigation, and questions for later filing research. It must not invent causes, propose adjustments/normalization, forecast, value, recommend the stock, or change financial state.

## Required design

- Read `AGENTS.md`, `docs/ai_fund_v1_section_1_updated.md`, `docs/ai_fund_v1_section_2_implementation_spec.md`, current statement/analytical-P&L, Analyst/Reviewer, Responses API structured-output pattern, CLI, output/run-manifest conventions, tests, git status/diff, and real MSFT analytical P&L shape.
- Existing analytical P&L remains canonical. Do not build another calculation system.
- Add one deterministic compact formatter, preferably `format_analytical_pnl_for_scan(pnl: pd.DataFrame) -> str` or the smallest equivalent fitting current modules.
- Preserve actual hierarchy so Revenue/Product and Cost of revenue/Product are unambiguous. Use actual metadata/row ordering; no generic taxonomy.
- Presentation-only disambiguate EdgarTools monetary `GrossProfit` labelled `Gross margin` from the gross-margin ratio.
- Operating lines: show FY24/FY25/FY26 values plus existing useful growth, absolute change, common-size, bps, and CAGR metrics when applicable. Sign-crossing lines show absolute movements and N/A for meaningless growth/CAGR. Exclude abstract/empty/XBRL-noise/duplicate alias fields.
- Dedicated margins/rates section: gross, operating, pretax, net margins and ETR for FY24/FY25/FY26 with bps changes.
- Supplemental EPS/share section without fake common-size metrics.
- Add a separate Analytical Scan LLM role using the existing OpenAI Responses API, native Structured Outputs/Pydantic, runtime/model conventions, and a version-controlled substantive prompt (suggested `prompts/analytical_scan.md`). No provider/framework abstraction.
- Result schema: 0-8 ranked findings; each has rank, title, high/medium/low importance, affected actual supplied line references, observation, why it matters, and at most 3 investigation questions. Forbid extras. Validate counts, unique ordered ranks, and row references mechanically; do not validate financial judgment in Python.
- Prompt: only supplied deterministic context; compare periods/growth/intensity/margins/mix/sign swings/non-operating/tax/EPS relationships; prioritize economic materiality; distinguish observation from explanation; omit filler; no outside Microsoft knowledge, causes, adjustments, normalization, forecasts, valuation, recommendations.
- Persist normal inspectable JSON under existing output-root/run conventions, approximately `data/MSFT/03_output/analysis/analytical_scan_<run_id>.json`, with available ticker/company/accession/run/model/prompt/timestamp metadata and structured result. Do not add to adjustment history.
- Extend the existing `analyze` command with `--scan` if coherent. Scan-only must build/reuse analytical P&L, format, call, persist, and render a concise finance-first ranked summary. It must not run adjustment discovery or mutate adjustment history/adjusted P&L. No new command hierarchy.
- Tests use mocked/frozen outputs; pytest never calls a live LLM.

## Acceptance tests

Prove: all three periods; R&D-style value/growth/common-size/bps/CAGR; sign-crossing absolute movement with no invented growth; Product hierarchy disambiguation; GrossProfit vs gross margin; abstract/empty exclusion; EPS/shares lack common-size; 0-8 valid; >8 rejected; duplicate/non-ordered ranks rejected; unknown affected lines rejected; no live LLM in normal pytest; output-root isolation; scan-only does not write adjustment history/change adjusted P&L; adjustment pipeline unchanged.

## Verification

- Focused scan/formatter tests.
- Relevant analytical-P&L tests.
- Relevant Analyst/Reviewer tests.
- Adjustment/lifecycle regression tests.
- Full suite.
- Ruff changed Python.
- `git diff --check` and final diff/stat inspection.
- If credentials are available, run real `analyze MSFT --scan`, preserve JSON, and manually compare context/result/P&L. Human sanity checks only: large FY26 other-income swing; gross-margin compression vs operating-margin expansion; declining R&D/S&M intensity; Product vs Service mix; pretax vs operating-margin expansion; higher FY26 ETR. Never seed these expected answers into the prompt.
- After live proof, a fresh read-only Luna financial reviewer inspects exact context, structured result, CLI rendering, and source P&L for representation, distortion, hallucination, priority, noise, duplicates, question usefulness, and complexity. Reviewer makes no edits; Sol decides repairs.

## Scope limits

No filing retrieval/explanations, normalization/model actions, segment-report extraction, new statement architecture, forecasting, valuation, recommendations, scoring formulas, RAG, UI/database/taxonomy/provider/agent framework/background orchestration. Do not alter M1/M2/M3 financial-state semantics. Do not commit or merge. Preserve all unrelated dirty work.

Production scope warning: if more than roughly 4 production files or 450 net new production lines are actually required, stop with a concrete decision brief before expanding.

