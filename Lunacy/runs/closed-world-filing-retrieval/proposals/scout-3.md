# Scout 3 — deterministic quantified disclosure bridge

## Finding

The current R4 path is correctly conservative but cannot close the requested
MSFT bridge. The final live packet contains the exact sentence in E1–E3:

```text
Other income (expense), net included $6.5 billion of net gains and $4.8
billion of net losses for fiscal years 2026 and 2025, respectively, from
investments in OpenAI ...
```

The persisted R4 result leaves both drivers unquantified and reports
`reconciliation.status=not_computable`, because `respectively` is rejected and
the finding contains five affected rows/three annual periods. This is safer
than trusting the old model amounts, but it misses a provable bridge. A plain
sum is also wrong: these are signed period-level amounts, so the contribution
to the year-over-year movement is `+6.5 - (-4.8) = +11.3` billion, not
`+6.5 + (-4.8) = +1.7` billion.

The old live artifacts show the exact failure boundary: the pre-R4 model
returned `+6.5` for FY26 and `-4.8` for FY25, but the generic reconciliation
rejected the different periods/units. The current R4 packet is the preferred
source of truth:

- JSON: `data/live-finding-proof-r4/MSFT/03_output/analysis/filing_investigation_01_20260827T152234074645Z.json`
- packet: `data/live-finding-proof-r4/MSFT/03_output/evidence/finding_01_20260827T152234074645Z.md`
- accession: `0001193125-26-323660`
- target row: `L12`, `Other income (expense), net`
- observed values: FY26 `$10.697bn`, FY25 `-$4.901bn`
- observed movement: `+$15.598bn`

## Recommendation

Keep all narrative/model output qualitative and add one small deterministic
post-retrieval extractor. It reads only validated exact packet excerpts and a
validated affected-line/P&L projection. It emits structured
`QuantifiedDisclosure` facts; Python, not the investigator, computes the
period-pair contribution and unresolved difference.

Do not retrofit the existing single-period `reconcile_disclosed_amounts()`
sum to this case. Preserve it for its existing tests/callers, and route the
MSFT-style path through a period-pair bridge whose formula is explicit:

```text
current_disclosed_effect = +$6.5bn       (FY26 gain)
prior_disclosed_effect   = -$4.8bn       (FY25 loss)
disclosed_contribution   = current - prior = +$11.3bn
observed_line_delta      = $10.697bn - (-$4.901bn) = +$15.598bn
unresolved_difference    = observed - contribution = +$4.298bn
```

The residual is an unresolved difference, never a balancing plug or an
adjustment. Preserve both raw reported dollars and the explicitly converted
comparison value in the artifact.

## Safe extraction contract

### 1. Deterministic target-line mapping

Build a local target projection from `finding.affected_line_refs` and the
current P&L. For each affected ref, retain the original row position, exact
`source_label`, `concept`, `standard_concept`, and annual columns. Do not parse
the finding's prose observation to select a line or period.

For each exact packet excerpt, require one affected row's exact source label to
occur in the disclosure lead-in (for the live case,
`Other income (expense), net included`). Require exactly one matching affected
row and exactly one matching lead-in. A broad substring, fuzzy label,
standard-concept guess, row order, or first affected row is insufficient. If
zero or multiple rows match, return `not_computable` with a machine-readable
mapping gap and no amounts.

This maps the five-row finding to `L12` only. It does not treat L11, L13, L14,
or L15 as alternative targets and does not change the saved finding.

### 2. Strict two-period source grammar

Scan quoted `excerpt` bytes only; never query strings, model prose, or a
concatenation of evidence items. Accept a disclosure group only when all of
these hold:

1. the exact target-label lead-in is present;
2. one contiguous clause contains exactly two explicitly qualified monetary
   amounts with the same explicit USD scale (`$... million` or `$... billion`);
3. each amount has exactly one local polarity descriptor (`gain`, `income`, or
   equivalent positive term; `loss`, `expense`, or equivalent negative term);
4. the same clause contains exactly two source years in the grammatical form
   `for fiscal years YEAR and YEAR, respectively`;
5. amount count equals year count, source order is the only mapping, and no
   clause/sentence boundary or conflicting polarity intervenes;
6. each year maps to exactly one supplied annual P&L period by its four-digit
   year prefix; both target-row values are finite; and
7. the packet item has valid E-ID, accession, source URL, line, and offset
   provenance.

The parser may use a generic amount/year regex and a small local polarity
allowlist. It must not contain `OpenAI`, `6.5`, `4.8`, or other expected-answer
tokens. It should intentionally support only the two-amount/two-year grammar
for this milestone. The packet's three-year E4–E6 `respectively` sentence is
preserved as evidence but does not silently become a FY26/FY25 pair; if E1–E3
are absent, the bridge stays closed.

For each accepted amount, emit a derived fact with:

```json
{
  "target_line_ref": "L12",
  "source_label": "Other income (expense), net",
  "amount": 6.5,
  "amount_unit": "usd_billions",
  "period": "2026-06-30 (FY)",
  "effect": "increased_line",
  "evidence_span": "<exact contiguous source excerpt>",
  "evidence_refs": ["E1"],
  "extraction_basis": "exact_two_period_respectively_pair"
}
```

The loss fact is `amount=-4.8`, `period=2025-06-30 (FY)`, and
`effect=decreased_line`. The sign is derived from the source polarity while
retaining any explicit source sign; a contradictory explicit sign rejects the
whole group. Do not let the LLM amount, period, effect, or evidence span enter
this structure.

### 3. Duplicate/conflict handling

E1, E2, and E3 quote the same source sentence for different literal queries.
Deduplicate accepted groups by exact source text/provenance plus the signed
amount-period tuple, while retaining the union of valid E refs for audit. Do
not add E1/E2/E3 amounts three times. A distinct group with the same target and
periods but different amounts is a conflict, not another contribution; fail
closed. E4–E6 cannot be used to complete the two-period group under the strict
grammar above.

Extraction should be limited to evidence refs attached to a validated
qualitative disclosed driver, or to a deterministic target-matching packet
item when the investigator returned a qualitative driver with valid refs. In
either case the derived fact must retain the packet E refs. Evidence text is
the authority; model descriptions only establish analyst relevance.

### 4. Python bridge

Add a local bridge function that accepts the P&L, finding, validated packet,
and derived disclosure facts. It must:

- require exactly one target row and exactly one unique two-period disclosure
  group;
- require the source periods to map to the current/prior pair in that order;
- read target-row values directly from the reported P&L, preserving dollars;
- compute `current_value - prior_value` without missing-to-zero behavior;
- convert dollars to `usd_billions` only through an explicit `1_000_000_000`
  scale, retaining both original and comparison units;
- compute each contribution as `current_effect - prior_effect`, then sum only
  facts in this one validated group; and
- emit `partial` with an explicit residual when all gates pass, otherwise
  `not_computable` with null amounts/difference and a reason code.

For the live case, persisted reconciliation should include at minimum:

```json
{
  "status": "partial",
  "target_line_ref": "L12",
  "target_source_label": "Other income (expense), net",
  "period": "2026-06-30 (FY)",
  "previous_period": "2025-06-30 (FY)",
  "observed_amount": 15598000000,
  "observed_unit": "dollars",
  "observed_amount_comparable": 15.598,
  "comparison_unit": "usd_billions",
  "known_disclosed_contribution": 11.3,
  "known_disclosed_unit": "usd_billions",
  "unresolved_difference": 4.298,
  "difference_is_reported_plug": false,
  "disclosed_facts": ["... +6.5 FY26 ...", "... -4.8 FY25 ..."]
}
```

`partial` means the exact OpenAI disclosure explains only part of the
reported Other-income swing; it does not imply a plug or claim that the
remaining components are absent. If unit provenance is not available for the
observed P&L, do not assume dollars merely to make the result tie.

## Affected surfaces

- `src/smrik_fund/ingestion/filing_investigation.py`: add local target mapping,
  strict two-period extractor, duplicate/conflict guard, and Python bridge;
  pass the final packet into `_movement_reconciliation()` and persist derived
  facts/reason codes. Keep the existing literal packet validator and generic
  single-period helper intact where possible.
- `prompts/financial_investigation.md`: state that amounts/periods/effects are
  supplied by deterministic extraction; investigator may return only
  evidence-backed qualitative drivers and refs. Keep numeric-free narrative and
  no-plug instructions.
- `tests/test_filing_investigation.py`: add focused source-pattern and bridge
  regressions below. Existing scan, filing, adjustment, and lifecycle tests
  remain unchanged.
- Artifact rendering/JSON only: show the derived facts and bridge formula in
  the investigation artifact/summary. No changes to `filing.py`,
  `analytical_scan.py`, `statements.py`, or adjustment/history surfaces are
  required beyond orchestration wiring in the module.

The deterministic seed and one-pass expansion are owned by S1/S2. Their final
packet must preserve initial/expansion provenance and accession identity before
this extractor runs. Company terms such as OpenAI may enter only via exact
post-seed packet text; they must not be placed in this extractor's code,
prompt, or initial query generation.

## Invariants

1. Exact packet excerpts are the only source for disclosed amounts, signs,
   years, target labels, and causes; query text never proves a fact.
2. Target mapping is unique and evidence-local; no affected-row order,
   standard-concept alias, finding prose, or model period selects the target.
3. Period mapping is exact four-digit FY-to-column matching with one match per
   year; no invented period, nearest year, or arbitrary first delta.
4. `amount=None`, unknown unit/period, missing P&L values, mismatched counts,
   mixed units, conflicting signs, and ambiguous groups remain unknown and
   block the bridge.
5. Signed period effects are preserved. Year-over-year contribution is
   `sum(current effects) - sum(prior effects)`, never a raw sum of period
   values.
6. Explicit dollar/billion conversion is comparison-only; original reported
   P&L values and source units remain intact.
7. The residual is Python-derived only after all gates pass, is labeled
   unresolved, and always has `difference_is_reported_plug=false`.
8. No model-authored numeric narrative, model residual, or model amount can
   override a failed deterministic check.
9. Duplicate evidence copies are one fact; conflicting facts fail closed.
10. Investigation remains read-only apart from its JSON/Markdown artifacts;
    no scan, P&L, adjustment, history, review, identity, lifecycle, or state
    output is mutated.

## Required regressions

Use a fake packet modeled on E1 with generic fixture amounts/years in addition
to the real-shape sample; do not seed Microsoft/OpenAI answer terms in prompts
or query-generation fixtures.

- Exact two-amount/two-year `respectively` sentence extracts two signed facts,
  preserves exact span/E refs, maps target `L12`, and computes contribution
  `current - prior`.
- MSFT-shaped fixture asserts `+6.5` FY26 gain, `-4.8` FY25 loss, `+11.3`
  contribution, `+15.598` observed comparable movement, and `+4.298`
  unresolved difference; explicitly guard against `+1.7`.
- Three-year E4-shaped sentence is retained but does not produce a two-year
  bridge; no silent first-two truncation.
- E1/E2/E3 duplicate excerpts deduplicate to one disclosure group; distinct
  conflicting amount groups fail closed.
- Swapped years, absent `respectively`, amount/year count mismatch, adjacent
  sentence association, mixed units/currencies, missing polarity, conflicting
  explicit sign, and unsupported target label all return no bridge.
- Multi-line finding with target L12 proves the code does not select L11 or
  `year_over_year[0]`; duplicate target labels and missing target values fail.
- Wrong/unknown E refs, accession mismatch, forged query-only amount, and a
  model-returned residual cannot create a derived fact or residual.
- Missing/unknown observed unit blocks conversion; dollar raw values remain
  byte/value-identical in the artifact.
- Existing unquantified-driver, numeric-free narrative, single-period sum,
  scan, adjustment-isolation, and CLI tests remain green.

## Live-proof criteria

Run the current MSFT flow in a fresh proof root only after S1/S2 changes:

```text
smrik-fund analyze MSFT --scan --output-root <proof-root>
smrik-fund investigate MSFT --finding-rank 1 --output-root <proof-root>
```

Accept the quantitative result only if all of the following are directly
visible in JSON and packet files:

- initial query contains only the deterministic Other-income label/cue and no
  company/event answer term; any OpenAI/recapitalization expansion query has
  exact first-pass E-ID/span provenance and occurs in at most one expansion;
- final packet retains accession `0001193125-26-323660`, honest SEC URL,
  source line/offset locators, and the exact E1-shaped two-year disclosure;
- target mapping is uniquely `L12` and periods are exactly
  `2026-06-30 (FY)`/`2025-06-30 (FY)`; no model prose selected them;
- derived facts show source-signed `+6.5`/`-4.8` `usd_billions`, exact spans,
  and validated E refs; no duplicate E1/E2/E3 contribution;
- Python reports observed raw `15,598,000,000` dollars, comparable `15.598`,
  disclosed contribution `11.3`, unresolved difference approximately `4.298`,
  and `difference_is_reported_plug=false`;
- narrative remains numeric-free; the residual is absent from narrative and
  model fields; no `adjustment_history.csv`, `adjusted_pnl.csv`, or other
  adjustment/state output is created or changed.

If the live packet contains only the three-year E4-style sentence, lacks the
exact target/period mapping, or has unit/provenance ambiguity, the correct
proof is `not_computable` with the gap exposed; do not force the requested
numbers merely because they are expected. A successful proof must be manually
checked against the exact packet and independently recomputed from the saved
raw P&L values.

## Risks and controls

- **Respectively overreach:** ordinary prose often puts multiple amounts and
  periods near one another. The exact grammar and cardinality gate prevent
  cross-year swaps; narrow two-period support is preferable to a general
  natural-language parser.
- **Sign convention drift:** adjustment docs use positive magnitude plus
  effect, while this investigation must preserve source signed period effects.
  Name fields `amount`/`effect` clearly and do not feed derived facts into
  adjustment application.
- **Duplicate notes:** the same disclosure appears in multiple packet items.
  Canonical group dedupe and conflicting-group rejection prevent double count.
- **Unit mismatch:** P&L dollars versus filing billions is safe only with an
  explicit scale and retained raw values. Unknown unit blocks the bridge.
- **Target drift:** labels may differ or repeat in other filings. Exact local
  label matching fails closed rather than adding taxonomy/fuzzy mapping.
- **Scope creep:** supporting arbitrary n-period lists, full-filing extraction,
  tax/component semantic mapping, or generic reconciliation would create a
  framework. Keep this case bounded and report unsupported variants.

## Non-goals

No hardcoded MSFT/OpenAI terms or expected amounts; no answer-shaped initial
queries; no free-form numeric claim repair; no arbitrary period inference; no
three-year truncation; no RAG, embeddings, browsing, regex retrieval, custom
SEC parser, or packet-merging framework; no tax bridge, forecast, valuation,
recommendation, adjustment candidate, approval, history, or lifecycle change;
no rewriting of reported P&L values; no balancing plug; no broad scan schema or
source taxonomy redesign.

## Size / decision rule

Target one existing production module, approximately 120–180 net lines for
the target mapper/extractor/bridge and orchestration wiring; one small prompt
edit; approximately 180–280 focused test lines. Reuse packet parsing and
existing validation. Do not touch `filing.py` or add a new service/model
hierarchy. If supporting the requested proof exceeds roughly 200 new
production lines or four changed production/test surfaces, stop and request a
scope decision. The existing 1,546-line uncommitted milestone already exceeds
the repository warning threshold; this proposal must reduce ambiguity without
another generic layer.

## Control Block

- Mode: read-only S3 proposal; only this artifact may change.
- Defect: exact signed period facts are currently discarded; generic sum is wrong.
- Fix: packet-only strict two-year extractor plus Python period-pair bridge.
- Target: unique exact affected source label; live target `L12` only.
- Facts: source-signed `+6.5` FY26 and `-4.8` FY25 with exact E refs/spans.
- Math: `current - prior = +11.3`; observed `+15.598`; residual `+4.298`.
- Units: preserve raw dollars; explicit comparison conversion to USD billions.
- Fail closed: ambiguity, duplicates/conflicts, missingness, units, provenance.
- Retrieval: S1/S2 generic seed then one packet-grounded expansion; no answer leakage.
- State: JSON/Markdown only; no scan/P&L/adjustment/history/review mutation.
- Verification: focused regressions plus fresh live MSFT packet/artifact inspection.
- Verdict: merge only if exact evidence and unambiguous target/period mapping prove bridge.
