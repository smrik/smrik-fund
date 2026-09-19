# Closed-world filing retrieval — Phase 3 A1 adversary

Verdict: **DO NOT MERGE**

Scope: fresh read-only review of implementation code/prompts/tests and the
fresh MSFT proof. Only this report was written; no source, test, config, live artifact, or external-system changes.

## Findings

### P1 — Final qualitative output is not closed-world validated

`src/smrik_fund/ingestion/filing_investigation.py:1605-1651` checks narrative
number/arithmetic tokens and E-ID existence, but not whether nonnumeric claims
are supported by cited excerpts. A bounded probe passed a driver,
interpretation, and explanation asserting “quantum teleportation transaction”
against E1, whose excerpt only says investments had gains
(`UNSUPPORTED_NARRATIVE=ACCEPTED`). This permits unsupported company-specific
causes despite the packet-only prompt; generate prose from validated evidence
or add an entailment/lexical support gate.
### P1 — Unquantified effect polarity is model-owned and unchecked

Validation clears amount metadata but retains model `effect` without checking
cited semantics (`filing_investigation.py:867-913`). A probe accepted
`effect=increased_line` for an excerpt saying “net loss”
(`UNQUANTIFIED_WRONG_EFFECT=increased_line`). Require evidence-backed polarity
or downgrade it to `unknown`; deterministic bridge signs remain correct.
### P2 — Provenance validators allow wrong item source and extra refs

`src/smrik_fund/ingestion/filing.py:440-447` checks top identity/accession in
locators, not item `Source` equality or line/offset resolution. A forged packet
with top `source-a`, item `Source: source-b`, accession A1 was accepted.
`filing_investigation.py:648-674` also accepts an expansion citing E1 plus
unrelated E2 when only E1 contains the support span. Generated MSFT packets
are consistent, but “correct refs” is not enforced.
### P2 — Removable complexity/scope warning remains

Current `filing_investigation.py` is 2,506 lines; the prior gate recorded 1,450
lines and 1,546 production lines (`Lunacy/runs/finding-driven-investigation/
reports/gate-pack-2.md:26`). Dead bounds/aliases remain at
`filing_investigation.py:50-53,66-68,1588`; this exceeds the ~200-line warning
and 120–180-line proposal target (`.../proposals/scout-3.md:329-338`).
Reduce or explicitly justify before merge.
## Checks and proof

- Bounded selection: `pytest -q tests/test_filing_investigation.py -k ...` → **14 passed, 21 deselected**; four existing warnings; no broad suite. CLI `investigate --help` exits 0 and isolation test passes.
- Closed-world scan: no hardcoded answer amounts/company terms in source/prompts; `run_search_plan` makes no planner call (`filing_investigation.py:515-551`).
- Live chain: scan `data/live-closed-world-proof-i1/MSFT/03_output/analysis/analytical_scan_20260827T165101769956Z.json`; initial packet `.../evidence/finding_02_20260827T170843967812Z_initial.md:6-47` has generic seeds, final packet `.../evidence/finding_02_20260827T170843967812Z.md:33-63` introduces OpenAI only in filing text/expansion.
- Final metadata records `planner_call_count=0`, `expansion_call_count=1`, and `filing_text_verification=performed` (`...170843967812Z.json:82,257,304`); no retry/loop observed in bounded call/search counts.
- Deterministic facts (`...170843967812Z.json:346-390,573-604`): L12 FY26 `+6.5`, FY25 `-4.8`, contribution `+11.3`, observed raw `+15.598`, explicit dollars→USD billions, residual `+4.298`, `difference_is_reported_plug=false`; signs/`respectively` span retained.
- State: proof root has no adjustment/history output. Time savings **partial**: one generic seed plus one packet-local expansion surfaces the disclosure, but unrelated/duplicate first-pass hits still require triage.
## Control Block

Verdict: **DO NOT MERGE**
Blocking: P1 unsupported qualitative claims; P1 unvalidated unquantified effect polarity.
P2 item-source/extra-ref provenance gaps; P2 production size/dead-surface warning.
MSFT chain: zero initial planner calls; one expansion; generic seeds precede OpenAI.
Bridge: L12; FY26 +6.5; FY25 -4.8; contribution +11.3; observed +15.598; residual +4.298.
Units/signs/period order preserved; residual flag false; no adjustment/history mutation.
Bounded checks: 14 passed, 21 deselected; no broad suite.
Report is immutable after FINAL.
