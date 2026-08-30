# Final financial/product review — R3 / A4

Verdict: **DO NOT MERGE**

Scope: fresh read-only review of the R3 final code, prompts, focused regressions, current diff, and fresh MSFT proof. No source, tests, config, live artifacts, or external systems changed.

## Findings

### P1 — Python-only no-plug boundary remains bypassable in free text

The prompt makes `unresolved_remainder` qualitative and prohibits residual arithmetic in every free-text field (`prompts/financial_investigation.md:22-31`). The validator only recognizes a narrow arithmetic vocabulary (`src/smrik_fund/ingestion/filing_investigation.py:620-643`) and only scans digit tokens or unit-qualified spelled amounts (`:870-903`). Fresh direct validation accepted all three fields (`interpretation`, `unresolved_remainder`, `explanation`) containing each of the following when the cited excerpt contained the same numbers: `5M + 2M`, `five million less two million`, `the difference between five million and two million`, and `five million divided by two million`. It also accepted bare spelled arithmetic, `five plus two`, with no numeric evidence. The first form is missed because `5M` is not in `_PROSE_NUMBER_PATTERN` and `M` is not handled by `_NUMERIC_ARITHMETIC_PATTERN`; the latter forms are not in `_TEXTUAL_ARITHMETIC_PATTERN`.

The same boundary accepts quantified remainder wording without the small residual lexicon: `The remaining amount is five million.`, `The leftover is $5 million.`, `The unresolved part is 5 million.`, and `The residual is five.`. These pass because `_RESIDUAL_WORD_PATTERN` contains only `residual|remainder|unexplained|plug|balancing` (`:630-632`), while bare spelled numbers are not identified. A model can therefore persist a derived amount or plug in the qualitative remainder or another result field, violating Python-only reconciliation and the no-plug contract.

### P1 — invalid quantified-driver downgrade leaks the rejected numeric span

When a quantified claim fails period/semantic-sign/span validation, the downgrade at `src/smrik_fund/ingestion/filing_investigation.py:510-531` clears `amount`, `amount_unit`, `period`, and sets `amount_basis=unquantified`, but does not clear a matching `evidence_span`. Fresh validation of `amount=5`, `period=FY2026`, and `evidence_span="5 million loss in 2026"` produced `amount=null`, `amount_unit=unknown`, `period=null`, `amount_basis=unquantified`, while retaining that numeric span. A driver submitted as `amount=null` with `period=FY2026`, `amount_unit=usd_millions`, and `evidence_span="5 million in 2026"` likewise retained the period and span after only unit cleanup (`:506-508`). This contradicts the prompt’s required “unknown/null, and omit the span” behavior (`prompts/financial_investigation.md:9-21`) and makes the persisted unquantified result misleading.

## Checks that pass

- Bounded adversarial pytest selection: **10 passed, 14 deselected** (unrelated year/clause, gain/loss signs, `respectively`, year-as-amount, digit boundary, spelled residual, and direct arithmetic regressions).
- R3 fresh MSFT artifact is complete and accession-aligned: `data/live-finding-proof-r3/MSFT/03_output/analysis/filing_investigation_01_20260827T144012022055Z.json` and `data/live-finding-proof-r3/MSFT/03_output/evidence/finding_01_20260827T144012022055Z.md` retain accession `0001193125-26-323660`, 3 literal queries, 6 evidence items, SEC URLs, source lines, and offsets.
- Live result preserves five observed signed lines (`L11`–`L15`), keeps both OpenAI drivers unquantified because of the `respectively` construction, and reports `reconciliation.status=not_computable`, null residual, and `difference_is_reported_plug=false`.
- Fresh proof root contains no `adjustment_history.csv` or `adjusted_pnl.csv`; CLI integration remains isolated to the investigation command (`src/smrik_fund/main.py:2329-2398`).
- `git diff --check` passed; no broad suite rerun per review scope. The repository’s required R3 repair report records focused/relevant/full/Ruff/compile checks as passing (`reports/repair-3.md:13-22`).

## Acceptance reassessment

Exact evidence/provenance, bounded literal retrieval, observed-vs-disclosed separation, missingness, state/adjustment isolation, and the current MSFT packet pass. The live result is analyst-useful for locating the OpenAI explanation, while correctly leaving quantification, tax detail, and the multi-line bridge unresolved. The whole acceptance gate fails because the generic validator still permits arithmetic/derived amounts in persisted free text and can expose a rejected numeric span as an unquantified driver.

## Control Block

Verdict: **DO NOT MERGE**
Blocking: P1 free-text arithmetic/residual bypass; P1 rejected quantified span leakage.
Exact R3 adversarial selection: 10 passed, 14 deselected.
Fresh probe: `5M + 2M`, `five million less two million`, and bare `five plus two` accepted in all three fields.
Fresh probe: `remaining amount five million`, `leftover $5 million`, and bare `residual five` accepted.
Fresh probe: bad-sign driver downgraded but retained `evidence_span="5 million loss in 2026"`.
MSFT proof: accession `0001193125-26-323660`; 3 literal queries; 6 exact evidence items.
Observed signed lines preserved; reconciliation is `not_computable`; no plug/residual emitted.
No adjustment/history files in proof root; no source/test/config/live edits by A4.
Required: close lexical/abbreviated/spelled no-plug bypasses and clear period/span whenever amount is unquantified.
Report: `Lunacy/runs/finding-driven-investigation/reports/final-financial-review-3.md`
