# Plan

Mode: Full Implementation Hive (explicit user request).

Goal: extend the established real-filing evidence path with one bounded discovery call that independently produces up to five plausible normalization topics/queries from MSFT analytical P&L plus bounded actual-10-K context, then run each topic through deterministic exact retrieval and the existing resolution/Reviewer/gate/history-safe flow.

Authority: `AGENTS.md`; actual authority files `docs/ai_fund_v1_section_1_updated.md` and `docs/ai_fund_v1_section_2_implementation_spec.md` (the requested shorter filenames are absent); current automated filing-evidence implementation and live MSFT behavior; user request of 2026-08-20.

Established contracts to preserve:
- EdgarTools filing/search/text is the source; exact excerpts, stable IDs, accession/source/honest locators, strict evidence-reference validation.
- Existing Analyst, Reviewer, risk gate, adjustment arithmetic, and canonical-history transition.
- Unsupported amount stays null; unresolved candidate stays unapplied; exploratory artifacts do not enter canonical history.

Phases:
1. Three independent read-only Luna proposals. Each must compare bounded discovery context options (whole filing vs headings/sections vs deterministic P&L-linked passages), schema, retrieval reuse, duplicate handling, prompt independence, verification, and size.
2. One fresh max-effort Luna synthesizes, inspects actual EdgarTools/MSFT behavior, implements the smallest complete path, runs real MSFT, and terminal-verifies.
3. One fresh xhigh simplicity adversary attacks taxonomy/framework creep, excessive schemas, duplicated search/parsing, product-runtime orchestration, hidden Xbox/MSFT hints, loops, and history/evidence integrity.
4. Required read-only gate scout after the final write barrier, then parent Sol gate and bounded live/acceptance sample.

Non-negotiable behavior:
- Exactly one discovery model call; 3-5 maximum topics (fewer/zero allowed when warranted).
- Discovery receives analytical P&L plus bounded neutral filing context from the actual filing; no Xbox/candidate/evidence/gold hint hardcoded in discovery prompt, fixture, seed query, or context selection.
- Minimal topic contract: short name, optional likely target line, concise search query/query list, short normalization-research rationale only.
- Deterministic local duplicate collapse; no taxonomy/confidence/workflow framework.
- For each retained topic: one retrieval pass, exact source packet with stable IDs/provenance, one resolution Analyst call, one Reviewer per resolved candidate, existing deterministic gate. No retries/open loop.
- Search queries used for retrieval must originate from discovery output. Existing retrieval implementation is extended/reused, not replaced without concrete evidence.
- No embeddings/vector/RAG/web/custom SEC/search service/workflow engine/cross-company architecture.
- Persist discovery/research/run artifacts only; canonical history changes only through existing legitimate approval transition.
- No commit.

Verification owner: I1 runs focused discovery/retrieval/integration tests, Analyst/Reviewer/gate regressions, full practical suite, Ruff changed code, `git diff --check`, and live real-MSFT `analyze MSFT --adjustments`. Record all discoveries even when unresolved. Parent samples independence, bounded calls, exact evidence, null/history behavior.

Adversary: YES. Named risks: hidden hardcoding, agent-framework creep, duplicate/loop amplification, and exploratory-history pollution.

