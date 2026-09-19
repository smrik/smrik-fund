# G0 gate pack — closed-world progressive filing retrieval

Date: 2026-08-27 | Workspace: `C:\Projects\finance\smrik-fund` | Baseline: `46ca750`

Gate position: **BLOCKED — DO NOT MERGE.** This is a fresh read-only scout pack,
not approval. The live R1 path is materially correct, but the provenance
validator has a concrete accession-boundary defect; parent G1 must wait for its
repair and bounded recheck.

## Final-state navigation / diff

`git diff --stat 46ca750` shows only tracked edits because the investigation
surfaces are untracked: `analytical_scan.py` +5 lines and `main.py` +100 lines
(+105 tracked lines). Current untracked target implementation surfaces are:

| File | Final symbols / regions | Size |
|---|---|---:|
| `src/smrik_fund/ingestion/filing_investigation.py` | `FilingGroundedQuery`, `FilingQueryExpansion`, `FindingSearchPlan`, `DisclosedDriver`, `FinancialInvestigationResult` (62–255); packet identity (288–303); deterministic seeds (405–517); expansion (520–734); validation/observed movement (737–929); exact pair extraction (1408–1605); Python bridge (1709–1880); orchestration/persistence (1883–2370); summary/saved-scan helpers (2407–2535) | 2,535 lines |
| `prompts/filing_query_expansion.md` | packet-only literal expansion contract | 11 lines |
| `prompts/financial_investigation.md` | v4 numeric-free investigator contract | 53 lines |
| `tests/test_filing_investigation.py` | 39 focused test methods, fake filing/client, bridge and isolation regressions | 1,192 lines |
| `src/smrik_fund/ingestion/analytical_scan.py` | `ScanFinding = AnalyticalScanFinding` at 49–51 | +5 tracked |
| `src/smrik_fund/main.py` | investigation imports 53–66; `investigate()` 2329–2413 | +100 tracked |

Target process artifacts are also untracked: `DECISIONS.md`, `PLAN.md`,
`STATE.md`, `USER_NOTES.md`, four phase `STEPS.md` files, three proposals, and
the four target reports. Prior finding-investigation process artifacts remain
untouched. The live proof is under ignored `data/` and therefore absent from
Git status.

The prior completed finding-investigation milestone is represented by
`Lunacy/runs/finding-driven-investigation/reports/repair-4.md` and
`gate-pack-2.md`; no committed pre-R1 snapshot exists. Its recorded source
delta is 2,506 → 2,535 lines (**+29 net**). Against baseline, the current
production footprint is 2,535 untracked module lines +105 tracked lines =
**2,640 production lines**, with 1,192 test lines and 64 prompt lines. This is
well above the AGENTS.md ~200-line scope warning and remains a parent decision.

## Acceptance mapping

| Acceptance | Gate assessment |
|---|---|
| Initial queries closed-world | Pass in code/proof: deterministic source-label seeds; no initial planner call; initial query is `Other income (expense), net included`, with no `OpenAI`. |
| One filing-grounded expansion | Pass in proof: one expansion call/pass; accepted query `dilution gain from the OpenAI Recapitalization` has exact E1 support span and filing-text verification. |
| Exact evidence/provenance | **Blocked by accession check below.** Normal generated packets are internally consistent, but malformed/forged accession substrings are accepted. |
| Quantified bridge | Pass in R1 artifact: deterministic exact two-year parser maps unique L12 and computes signed contribution/residual. |
| No-plug / separation | Pass for proof: narrative has no numeric tokens; reconciliation is explicit unresolved difference with plug flag false; no adjustment/history output. |
| State/lifecycle/CLI isolation | Pass by diff and live root: separate `investigate` command/module; no normalization, review, adjustment, lifecycle, or reported-value mutation. |
| Verification | Recorded checks pass below; no broad suite or live rerun performed by G0. |

## Fresh MSFT discovery chain

Successful R1 artifacts:

- [scan JSON](../../../../data/live-closed-world-proof-r1/MSFT/03_output/analysis/analytical_scan_20260827T175543203180Z.json)
- [initial packet](../../../../data/live-closed-world-proof-r1/MSFT/03_output/evidence/finding_01_20260827T175608460314Z_initial.md)
- [final investigation JSON](../../../../data/live-closed-world-proof-r1/MSFT/03_output/analysis/filing_investigation_01_20260827T182736421990Z.json)
- [final packet](../../../../data/live-closed-world-proof-r1/MSFT/03_output/evidence/finding_01_20260827T182736421990Z.md)

Persisted chain preview:

```text
scan accession/form/period: 0001193125-26-323660 / 10-K / 2026-06-30
initial candidates: 3; accepted: 1; rejected no-hit: 2; planner calls: 0
initial literal: Other income (expense), net included
expansion calls/passes: 1/1; accepted: dilution gain from the OpenAI Recapitalization
expansion support: E1 exact span; filing_text_verification=performed
final packet: 4 exact items (E1-E4), same accession/source identity
investigation: status=completed; prompt=financial-investigation-v4; schema=filing-investigation-v3
```

Initial packet E1/E2 exposes the two-year disclosure; final E1/E2 are the
two-year occurrences and E3/E4 retain the three-year occurrence. The initial
query contains no company/event term; `OpenAI` first enters through quoted
retrieved filing text and the validated expansion. Failed attempts remain in
the proof root; the successful JSON above is the only completed result.

## Quantitative bridge / outputs

The successful JSON retains the reported P&L and exact evidence separately:

```json
{
  "target_line_ref": "L12",
  "period": "2026-06-30 (FY)",
  "previous_period": "2025-06-30 (FY)",
  "observed_amount": 15598000000.0,
  "observed_amount_comparable": 15.598,
  "known_disclosed_contribution": 11.3,
  "unresolved_difference": 4.298,
  "difference_is_reported_plug": false
}
```

Bridge facts are exact source-signed `+6.5 usd_billions` for FY26 and `-4.8
usd_billions` for FY25; Python computes `6.5 - (-4.8) = +11.3`, versus raw
reported `10,697,000,000 - (-4,901,000,000) = +15.598bn`, leaving `+4.298bn`
unresolved. [Reported analytical P&L](../../../../data/live-closed-world-proof-r1/MSFT/03_output/analytical_pnl.csv),
[reconciliation checks](../../../../data/live-closed-world-proof-r1/MSFT/03_output/reconciliation_checks.csv),
and both evidence packets are preserved.

## Blocking findings / residuals

### P1 — accession identity is substring-matched

`src/smrik_fund/ingestion/filing.py:440-446` and
`src/smrik_fund/ingestion/filing_investigation.py:288-303` use
`accession in locator`, not an exact parsed accession/token match. Fresh
no-write probe:

```text
packet top: Filing accession: A1
item locator: Locator: accession A10; line 1
result: ACCEPTED substring accession mismatch
```

This violates the packet identity contract: an item from accession `A10` can
pass a packet claiming `A1`. Live MSFT uses the full exact accession and is not
shown to be wrong, but the validator is not fail-closed. Repair with exact
accession-token/field matching and add a regression before parent approval.

### P2 — caller identity is not bound at the investigation helper boundary

`run_financial_investigation()` validates packet self-consistency but receives
no expected ticker/accession and does not compare packet metadata to its
`ticker`/filing context. A fresh no-write probe passed a packet declaring
`Ticker: OTHER` to `run_financial_investigation("MSFT", ...)` and returned
`ACCEPTED Unknown.` The CLI/orchestration path currently obtains packets from
the checked filing, so this is not a live-artifact mismatch; the public helper
boundary should still bind identity or be made explicitly private.

### P2 — production scope warning remains unresolved

The final module is 2,535 lines and the baseline-visible production addition is
2,640 lines, versus AGENTS.md’s ~200-line warning. `final-review.md` calls this
immaterial, but no parent proportionality decision is recorded. Dead remnants
`_GENERIC_ACCOUNTING_CUES` (306) and `_amount_and_unit_supported` (1694–1706)
are still present. This is a merge-gating scope decision, not a claim that the
MSFT arithmetic is incorrect.

Other residuals: the exact filenames named by AGENTS.md
(`docs/ai_fund_v1_section_1.md` / `_section_2.md`) are absent; updated
equivalents were inspected. Full changed-file `ruff format --check` remains
red only for pre-existing formatting in tracked `analytical_scan.py` and
`main.py`; new module/tests pass format check. EdgarTools deprecation/cache
permission warnings are pre-existing environment noise.

## Recorded verification snapshot

From `Lunacy/runs/closed-world-filing-retrieval/reports/repair-1.md` and
`final-review.md`:

- focused `tests/test_filing_investigation.py -q`: **39 passed**;
- full `tests -q`: **193 passed, 45 subtests passed**;
- selected adversarial final review: **13 passed, 26 deselected**;
- Ruff check: **passed**; new investigation source/tests format: **passed**;
- changed-source/test compile and `git diff --check`: **passed**;
- CLI `.venv\Scripts\smrik-fund.exe investigate --help`: **exit 0**;
- live JSON/evidence identity, narrative, bridge, and state-isolation probes:
  **passed for the generated MSFT packet**.

G0 did not rerun broad suites or regenerate live artifacts. The two no-write
probes above emitted only the existing Edgar cache-clear `WinError 5` warning.

## Exact bounded parent checks

Run only after the accession repair, on the unchanged final tree:

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
& 'C:\Users\patri\miniconda3\envs\ai-fund\python.exe' -m pytest tests/test_filing_investigation.py -q
& 'C:\Users\patri\miniconda3\Scripts\ruff.exe' check src/smrik_fund/ingestion/filing_investigation.py src/smrik_fund/ingestion/filing.py src/smrik_fund/ingestion/analytical_scan.py src/smrik_fund/main.py tests/test_filing_investigation.py
& 'C:\Users\patri\miniconda3\Scripts\ruff.exe' format --check src/smrik_fund/ingestion/filing_investigation.py tests/test_filing_investigation.py
git diff --check 46ca750
git status --short
git diff --stat 46ca750
```

Pure acceptance sample (no rerun): reopen the linked successful JSON/packets;
confirm accession exactness after repair, generic initial seed, one expansion,
E1–E4 provenance, zero narrative numeric hits, signed L12 facts, `11.3`/`15.598`
bridge, `4.298` unresolved difference, false plug, and no adjustment/history
files. Parent must then issue the required final `PASS` or `DO NOT MERGE`.

## Control Block

- Decision: **DO NOT MERGE; parent gate blocked on G0 P1 provenance defect.**
- P1: accession checks accept substring mismatch (`A1` vs locator `A10`).
- P2: helper boundary does not bind packet ticker/accession to caller context.
- P2: 2,640 production lines vs ~200 scope warning; parent proportionality decision missing.
- Live: MSFT accession `0001193125-26-323660`; initial generic query; planner calls 0.
- Expansion: one call/pass; accepted OpenAI phrase has E1 exact support and filing-text verification.
- Bridge: L12; +6.5 FY26, -4.8 FY25; +11.3 contribution; +15.598 observed; +4.298 residual.
- Isolation: no adjustment/history output; narrative numeric-free; plug flag false.
- Recorded checks: focused 39/full 193; Ruff/diff-check/CLI passed; no G0 broad rerun.
- Required next: exact accession repair + regression, bounded checks, parent verdict.

Report is immutable after FINAL.
