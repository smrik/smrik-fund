# Plan

Mode: Full Implementation Hive (user-requested).

Goal: Add the smallest real-MSFT filing-evidence retrieval path and exactly one Analyst resolution pass to `analyze MSFT --adjustments`, preserving exact excerpts/provenance and keeping unresolved candidates out of canonical history/application.

Authority: `AGENTS.md`; `docs/ai_fund_v1_section_1_updated.md`; `docs/ai_fund_v1_section_2_implementation_spec.md`; current dirty Task 7/8/9/integrated path; user request of 2026-08-20.

Phases:
1. Three independent read-only Luna proposals covering EdgarTools retrieval, integration, evidence integrity, history hygiene, tests, and minimal diff.
2. One fresh max-effort Luna synthesizes proposals, inspects the actual EdgarTools API/real MSFT filing, implements and terminal-verifies the bounded flow.
3. One fresh xhigh Luna simplicity adversary attacks generic retrieval layers, schemas, loops, duplicated evidence/persistence, prompt hardcoding, and correctness gaps; only bounded behavior-preserving simplification edits allowed.
4. Required read-only gate scout (cross-cutting shared contracts), then parent Sol gate and bounded acceptance proof.

Non-negotiable behavior:
- Actual filing content via EdgarTools; no web/RAG/vector/search framework/custom SEC stack.
- Exact source text; stable evidence IDs; filing identity and honest locator/provenance; no paraphrase/reconstruction.
- Unknown evidence IDs fail closed.
- No gold/eval leakage into prompts.
- Analyst remains high-recall and may request research; schema change only if strictly minimal.
- At most one retrieval plus follow-up Analyst call; unsupported amount remains null.
- Reviewer/gate stay conservative; unresolved candidates remain unapplied; adjusted P&L unchanged.
- Exploratory runs do not append candidates to `adjustment_history.csv`; history only changes at the existing authorized state transition.
- No commit.

Verification owner: implementation worker runs focused retrieval/Analyst/Reviewer/gate tests, real `analyze MSFT --adjustments`, Ruff changed code, and `git diff --check`. Parent samples exact-evidence/one-pass/history behavior after gate scout.

Adversary: YES. Named risks: overengineering and evidence/history integrity.

