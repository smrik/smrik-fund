# G0b gate pack 2 — closed-world progressive filing retrieval

Date: 2026-08-27 | Workspace: `C:\Projects\finance\smrik-fund` | Baseline: `46ca750`

Gate position: **BLOCKED — DO NOT MERGE.** This is a fresh read-only replacement
scout pack, not approval. The R2 identity/provenance repair is present and the
bounded MSFT proof passes. Parent G1 still needs an explicit proportionality
decision for the very large new production surface before issuing the required
final verdict.

## Scope and final-state navigation

Read: project `AGENTS.md`; `USER_NOTES.md`, `PLAN.md`, `STATE.md`, and gate
`phases/04-gate/STEPS.md`; prior `reports/gate-pack.md`; `reports/repair-2.md`;
`reports/final-review.md`; final source, prompts, tests, and R2 output. The
requested source-of-truth filenames are absent; current equivalents are
`docs/ai_fund_v1_section_1_updated.md` and
`docs/ai_fund_v1_section_2_implementation_spec.md`.

Current status is dirty `main`; no source, test, config, live artifact, or
external-system edits were made. Only this report is new. `git diff --stat
46ca750` sees tracked additions of 5 lines in `analytical_scan.py` and 100 in
`main.py`; the new investigation module/tests/prompts and Lunacy artifacts are
untracked.

## Identity/provenance repair

The prior G0 P1/P2 findings are closed in the final tree:

- `filing_investigation.py:288-327` calls shared packet parsing, then requires
  every item `Source` to equal packet `Source` and parses the locator's leading
  `accession <token>` field for exact equality. `A1` therefore cannot pass a
  locator containing `A10`.
- `filing_investigation.py:1888-1946` makes
  `expected_filing_accession` required at the investigator helper boundary and
  validates packet ticker and accession against the caller before any model
  call. `investigate_finding` checks saved-scan accession against the filing
  (`:2107-2115`) and passes the actual accession (`:2336`).
- Regressions are in `tests/test_filing_investigation.py:508-550`: locator
  substring mismatch, wrong caller accession, and wrong packet ticker all
  reject. `repair-2.md` records 42 focused tests and the same repair.

Bounded no-write identity probe (fresh, no artifact writes; Edgar emitted its
existing cache-clear `WinError 5` warning):

```text
exact: ACCEPTED
locator-substring: REJECTED: E1 locator does not match packet accession
wrong-ticker: REJECTED: evidence packet ticker does not match investigation ticker
wrong-accession: REJECTED: evidence packet accession does not match investigation filing
expected_filing_accession_required=True
```

Bounded packet recheck against R2: `_validated_packet` accepted initial 4-item
and final 6-item packets only with `MSFT` and accession
`0001193125-26-323660`; all locator prefixes matched that exact token. The
final model result also revalidated successfully against the final packet,
and the expansion support span is literal in the final packet.

## Closed-world MSFT chain

Artifacts (fresh R2 root):

- [scan JSON](../../../../data/live-closed-world-proof-r2/MSFT/03_output/analysis/analytical_scan_20260827T190654525200Z.json)
- [initial packet](../../../../data/live-closed-world-proof-r2/MSFT/03_output/evidence/finding_04_20260827T190709006849Z_initial.md)
- [final investigation JSON](../../../../data/live-closed-world-proof-r2/MSFT/03_output/analysis/filing_investigation_04_20260827T190709006849Z.json)
- [final packet](../../../../data/live-closed-world-proof-r2/MSFT/03_output/evidence/finding_04_20260827T190709006849Z.md)
- [reported analytical P&L](../../../../data/live-closed-world-proof-r2/MSFT/03_output/analytical_pnl.csv)
- [reconciliation checks](../../../../data/live-closed-world-proof-r2/MSFT/03_output/reconciliation_checks.csv)

Persisted chain preview from the final JSON:

```text
filing: MSFT / 10-K / accession 0001193125-26-323660 / period 2026-06-30
initial: Operating income included | Other income (expense), net included
planner_call_count=0; initial OpenAI leakage=false; candidate_count=3; accepted=2
rejected initial candidate: Income before income taxes included (no literal source hit)
expansion: calls=1, passes=1, filing_text_verification=performed, accepted=1
accepted expansion: dilution gain from the OpenAI Recapitalization
final packet: 6 items, same source URL and exact accession on every locator
status=completed; prompt=financial-investigation-v4; schema=filing-investigation-v3
```

The initial plan is built from affected `ScanFinding` source labels and one
fixed generic `included` cue (`filing_investigation.py:405-471`); plan context
excludes filing text (`:474-503`). The initial packet contains OpenAI only as
retrieved filing text; neither initial literal contains `OpenAI`. Expansion is
one packet-only Structured Output call (`:540-758`) and accepts the phrase only
with initial E3/E4 refs and the exact support span below. The final retrieval
adds that literal once; no retry/autonomous loop exists.

```text
support span: The net gains recorded for fiscal year 2026 primarily relate to
the dilution gain from the OpenAI Recapitalization.
initial refs: E3, E4 | filing_text_verification: performed
```

## Quantified bridge / no plug

The final JSON's deterministic extraction and bridge are under
`filing_investigation.py:1428-1605` and `:1778-1888`. The packet's exact
target-labelled `respectively` disclosure maps uniquely to L12 and the first
two supplied annual periods. It preserves source polarity as FY26 `+6.5`
`usd_billions` (`increased_line`) and FY25 `-4.8` `usd_billions`
(`decreased_line`). The observed raw P&L values remain separate:

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

Fresh no-write arithmetic probe recomputed `(6.5 - (-4.8),
(10,697,000,000 - (-4,901,000,000))/1e9, 15.598 - 11.3, false)` as
`(11.3, 15.598, 4.298, False)`. Ambiguous year/unit cases remain
fail-closed (`extract_period_paired_disclosures` / `reconcile_period_pair_bridge`).

## Narrative, state isolation, CLI

`filing_investigation.py:809-929` and `:1628-1715` enforce packet refs,
numeric-free narrative fields, cited-token support, local amount/year/sign
checks, and no residual arithmetic in prose. Fresh validation of the final
R2 result passed; both structured drivers are unquantified in model prose, so
the exact numeric facts stay in deterministic `quantified_disclosures` and
`reconciliation`.

The R2 output root contains exactly 6 files: `analytical_pnl.csv`,
`reconciliation_checks.csv`, one scan JSON, one investigation JSON, and the
initial/final evidence packets. A bounded filename check found zero
adjustment/history/state/lifecycle/review files. The new path imports only
filing, scan, and statement boundaries; it does not call adjustment,
normalization, review, lifecycle, or state writers. The CLI command is isolated
at `main.py:2329-2415`; `investigate --help` exits 0 and exposes ticker,
finding rank, scan file, model/reasoning, and output root. A renderer preview
is concise and useful:

```text
Finding 4: A sign reversal in other income materially lifted pretax and net results
Observed movement: Other income (expense), net changed from a $4.901 billion expense in FY25 to $10.697 billion of income in FY26, a $15.598 billion improvement ...
Disclosed explanation:
  - ... equity method investment reflected in Other, net: unquantified [E3]
  - dilution gain from the OpenAI Recapitalization: unquantified [E4]
Interpretation: The net gains recorded for the latest fiscal year primarily relate to the dilution gain from the OpenAI Recapitalization. [E4]
Unresolved remainder: The cited excerpts do not identify further details. [E3, E4, E5]
```

## Verification snapshot

Fresh bounded checks run in this gate:

- `PYTHONPATH=src ... -m pytest tests\\test_filing_investigation.py -q` —
  **42 passed**, 4 pre-existing Edgar/degraded-cache warnings;
- Ruff check on final relevant source/test set — **passed**;
- Ruff format check on new investigation source/tests — **2 files already
  formatted**;
- `git diff --check 46ca750` — **passed**, with existing LF/CRLF and
  `.pytest_cache` permission warnings;
- `.venv\\Scripts\\smrik-fund.exe investigate --help` — **exit 0**;
- no-write identity, packet, narrative, chain, arithmetic, and output-root
  probes — **passed**.

`repair-2.md` additionally records, but this scout did not rerun, full
`tests -q` **196 passed, 45 subtests passed**, no-write compile success, and
the fresh R2 SEC/LLM proof. No broad suite or live model/SEC investigation was
rerun here, per gate scope.

## Changed surfaces and proportionality blocker

Measured current files:

| Surface | Current lines | Gate note |
|---|---:|---|
| `src/smrik_fund/ingestion/filing_investigation.py` | 2,550 | new module; deterministic retrieval, validation, extraction, bridge, orchestration |
| `src/smrik_fund/ingestion/analytical_scan.py` | +5 vs baseline | public `ScanFinding` alias |
| `src/smrik_fund/main.py` | +100 vs baseline | isolated `investigate` CLI |
| `tests/test_filing_investigation.py` | 1,235 | focused fake/live-contract regressions |
| prompts | 11 + 53 | expansion and investigator contracts |

Thus the target implementation adds approximately **2,655 production lines**
(2,550 new module + 105 tracked additions), plus 1,235 test lines and 64
prompt lines. This exceeds `AGENTS.md`'s approximately 200-line scope warning
by an order of magnitude. The prior final review called 2,535 lines
immaterial; current measured size is 2,550 after the repair, and `repair-2.md`
leaves proportionality parent-owned. This is the outstanding gate blocker,
not a claim that the R2 MSFT arithmetic/provenance path is wrong. Parent G1
must explicitly decide whether this one-company V1 surface is proportionate,
or require decomposition/reduction before merge.

## Not changed

No changes to reported P&L values, EdgarTools retrieval mechanics, shared
`filing.py`, scan calculations, normalization, materiality, adjustment
application/history, review, lifecycle, or state semantics. No commit, merge,
push, or broad test rerun.

## Exact bounded parent checks

Use the unchanged final tree and R2 artifacts only:

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
& 'C:\Users\patri\miniconda3\envs\ai-fund\python.exe' -m pytest tests\test_filing_investigation.py -q
& 'C:\Users\patri\miniconda3\Scripts\ruff.exe' check src\smrik_fund\ingestion\filing_investigation.py src\smrik_fund\ingestion\filing.py src\smrik_fund\ingestion\analytical_scan.py src\smrik_fund\main.py tests\test_filing_investigation.py
& 'C:\Users\patri\miniconda3\Scripts\ruff.exe' format --check src\smrik_fund\ingestion\filing_investigation.py tests\test_filing_investigation.py
git diff --check 46ca750
git status --short
git diff --stat 46ca750
```

Acceptance sample: reopen the linked R2 scan/JSON/packets; confirm initial
generic literals contain no OpenAI, planner calls are zero, expansion is one
pass with E3/E4 exact support and filing-text verification, all packet items
match ticker/source/accession, L12 facts are signed `+6.5`/`-4.8`, bridge is
`+11.3` versus `+15.598`, residual is `+4.298`, plug is false, narrative is
numeric-free, and output-root state files are absent. Then record the explicit
proportionality decision and final `PASS` or `DO NOT MERGE`.

## Control Block

- Decision: **BLOCKED; DO NOT MERGE; parent proportionality decision required.**
- R2 identity repair: exact locator accession token; required caller accession; ticker/accession mismatch rejects.
- Live accession: `0001193125-26-323660`; initial planner calls `0`; initial OpenAI leakage `false`.
- Expansion: one call/pass; accepted OpenAI phrase cites initial E3/E4; filing-text verification `performed`.
- Final packet: 6 items; same MSFT/source URL/exact accession; result revalidation passed.
- Bridge: L12; FY26 `+6.5`; FY25 `-4.8`; contribution `+11.3`; observed `+15.598`; residual `+4.298`.
- No plug: `difference_is_reported_plug=false`; no adjustment/history/state/lifecycle/review outputs.
- Narrative: numeric-free and citation-validated; CLI help exit `0`; focused tests `42 passed`.
- Surface: 2,550-line new module +105 tracked production lines = ~2,655 production lines; ~200-line AGENTS warning unresolved.
- Parent action: run bounded checks above, decide proportionality, then issue final `PASS` or `DO NOT MERGE`.

Report is immutable after FINAL.
