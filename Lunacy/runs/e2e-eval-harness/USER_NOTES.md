# User authority — E2E evaluation harness V1

- Build the harness only. Do not repair or optimize product behavior.
- No commit, merge, push, reset, checkout, or autonomous keep/revert decisions.
- Full Implementation Hive required.
- Generic core owns cases, lifecycle, metadata, artifacts, normalized results, comparisons, and iteration records; finance semantics stay in workflow-specific functions.
- Static functional dispatch only. No workflow framework, plugins, reflection, dynamic imports, DI, adapter hierarchy, or DSL.
- Filing investigation is the first complete workflow. Analytical Scan is a fixture/mock reuse proof only.
- Suites: development, regression, holdout. One case may belong to multiple suites.
- Companies: MSFT + AMZN development; GOOGL holdout. Preserve explicit BLOCKED/UNAVAILABLE capability records rather than inventing inputs.
- Required regression controls: MSFT quantified OpenAI/non-operating and multi-driver operating-expense cases. Required MSFT development controls: segment growth/mix and segment profitability/margin.
- Freeze ticker, accession, filing period, source/scan artifact, finding identity, and practical SHA256 hashes. Small inputs live with eval definitions; large source data is referenced/frozen once per accession when useful.
- One product execution per case. Record model, reasoning effort/config, product/judge call counts, source identity, HEAD SHA, dirty flag, tracked-diff fingerprint, and relevant-untracked fingerprint (excluding generated run dirs).
- Product statuses: EXECUTION_ERROR, VALIDATION_REJECTED, COMPLETED. Invalid output is PRODUCT INVALID; valid completed output continues even if partial/weak/no evidence/not computable/no expansion/unresolved.
- Preserve rejected structured output as UNTRUSTED/REJECTED under eval run only. Never bypass validation, score it, or make it canonical state. Critical failures skip judge.
- Mechanical checks are critical or diagnostic. Reuse product validators. Preflight runs once per invocation/suite.
- Judge: gpt-5.6-terra, high reasoning, native structured output, default sampling; ordinal PASS/PARTIAL/FAIL with fixed dimensions. Judge errors remain JUDGE_ERROR and do not invalidate mechanically valid product output.
- Definition integrity: aggregate hash plus case/rubric/check hashes. Comparisons use an explicit baseline definition; mismatch is NON_COMPARABLE. No prose similarity and no automatic keep/revert.
- Outputs: authoritative JSON plus compact Markdown. Per-case isolated directory; crash isolation; stdout/stderr/traceback and product artifacts retained or linked with hashes.
- Iterations: one JSON per iteration plus Markdown index; no database or repair controller.
- Setup live-call budget: maximum 6 model calls plus at most one transient retry. Only prove wiring / establish current baseline availability. Report exact count.
- Validate discovery, mocked lifecycle, crash isolation, judge gating, rejected-output capture, normalized output, comparison, definition drift, ledger resume, state isolation, optional real smoke, and Analytical Scan reuse.
- Run focused tests, product regressions, full suite, Ruff changed files, and git diff --check.

## State semantics

- HARNESS READY is independent of product case outcomes.
- CASE READY / CASE BLOCKED describe prerequisites.
- PRODUCT VALID means COMPLETED plus critical mechanics pass.
- PRODUCT INVALID means crash or critical validation rejection.
- QUALITATIVE PASS/PARTIAL/FAIL applies only to PRODUCT VALID.
- JUDGE SKIPPED follows critical mechanical failure; JUDGE ERROR is separate from product status.
