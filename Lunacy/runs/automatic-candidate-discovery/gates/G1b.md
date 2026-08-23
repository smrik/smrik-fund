# G1b — refreshed final read-only gate scout

## Control
- Status: **TERMINAL**; write barrier **CLOSED**; only this gate note is written.
- Read: `AGENTS.md`; `docs/ai_fund_v1_section_1_updated.md`; `docs/ai_fund_v1_section_2_implementation_spec.md`; Phase-4 `PLAN/DECISIONS/STATE/STEPS`; I1/S1/R1/S2/R2/R3; stale G1.
- Verdict: post-repair user-supplied live artifacts now provide the positive Xbox chain; parent owns G2.

## Exact navigation
- Filing attachment: `statements.py:223-231`; active runtime: `main.py:148-185,620-645`.
- Discovery: `discovery.py:20-72,129-232,267-286,299-368`; retrieval: `filing.py:150-179,281-348,360-398`.
- Orchestration/caps/persistence: `main.py:98,267-283,343-538,540-604`; Analyst/Reviewer/gate/application: `adjustment_analysis.py`, `reviewer.py`, `risk_gate.py`, `adjustments.py`.
- Focused proof: `tests/test_discovery.py:187-254`; `tests/test_filing.py:86-123`; `tests/test_adjustment_analysis.py:170-293`.
- Live evidence: `data/MSFT/03_output/analysis/discovery_20260821T152219572413Z.json`; `adjustment_run_20260821T152219572413Z.json`; Xbox packet `evidence/02_xbox_impairment_and_related_expenses_20260821T152219572413Z.md`.

## Twelve verification points
1. **PASS** Actual MSFT 10-K attached to P&L; accession `0001193125-26-323660`.
2. **PASS** Neutral bounded context: fixed label windows, ≤12 passages/12,000 chars; no active discovery seed.
3. **PASS** One structured discovery call; ≤5 topics/≤3 queries; live result has 4 topics.
4. **PASS** Deterministic dedupe and zero-topic persistence; over-cap candidate response closes before Reviewer.
5. **PASS** Retrieval forwards model queries literally; no seed, expansion, retry, or best-hit selection.
6. **PASS** Xbox independently appears in neutral context and discovery output; no active-branch Xbox literal.
7. **PASS** Literal exact packet uses `regex=False`, honest accession/locator/lines/offsets; Xbox live packet has E1, loc 201, source line 1283.
8. **PASS** Bounded fan-out: one retrieval/Analyst/topic, one Reviewer/candidate, max 3 candidates/topic; live total 6 candidates.
9. **PASS** Null/unsupported/uncertain cases fail closed; live gate is human review, not auto-approval.
10. **PASS** Evidence refs validate; only approved rows apply/append; live candidates are all `not_applied`.
11. **PASS** Live topics/candidates: OpenAI A0024 $6.5bn FY26; Xbox A0025 null FY26 R&D; divestiture A0026 null FY25 G&A; tax-interest A0027/A0028/A0029 $1.4bn/$1.3bn/$1.5bn FY26/25/24.
12. **PASS with defer** Live recon is 12/0/0 reported and adjusted, equal=true; simplicity stays minimal, policy gaps remain explicitly deferred.

## Xbox independence/evidence chain
- Filing context line 1282-1284 → model topic/query → `regex=False` retrieval → E1 exact excerpt/loc 201/source line 1283 → A0025 target R&D, amount null → Reviewer revise → gate `human_review` → `not_applied`; no history/P&L mutation.
- This is now post-repair live evidence, not the stale pre-repair `got 3` artifact; the packet preserves the amount as unknown rather than using the $3.1bn parent-line delta.

## Eight final Sol answers
1. Xbox independent? **Yes, live output-to-packet chain.**
2. Query lineage exact? **Yes, literal model-supplied query.**
3. Evidence exact/bounded? **Yes, E1/loc/line metadata; cap 20.**
4. Calls/fan-out bounded? **Yes, one discovery and finite downstream fan-out.**
5. Null/reviewer/gate fail closed? **Yes.**
6. Can unresolved discoveries alter history/P&L? **No; all six not applied.**
7. Extra discoveries/simple scope handled? **Yes; four topics persisted; no taxonomy/RAG/workflow layer.**
8. Final live acceptance terminal? **Yes for discovery/Xbox evidence; auto-approval remains deferred.**

## D3, deferred policy, sizing
- R3 **touched the live entry contract** (requires attached/explicit EdgarTools filing; removes frozen/manual-seed fallback), but **did not change downstream filing-branch mechanics**; this is the sole active path (`R3.md`, `main.py:148-185`).
- D2 defers unknown risk-gate/materiality inputs and approved-rerun matching/deduplication; no policy expansion authorized.
- Live history: 23 existing rows, all `proposed` (`A0001–A0023`); no `A0024–A0029` append. Current tracked worktree diff: 6 files, `+1126/-303`; `main.py +565/-98`, adjustment tests `+310/-46`; R3 report removes ~149 obsolete runtime lines; untracked discovery surfaces remain user-owned.

**Terminal disposition:** G1b complete; parent may run G2.
