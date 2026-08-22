# AI Fund V1 — Section 2: Implementation Specification

Date: 2026-08-10  
Status: Approved V1 design after discovery questions 52–163  
Audience: Patrik and AI coding agents  
Depends on: Section 1 — Product and Architecture Decision Log

### How to use this document

For Patrik: use Parts A–F as the implementation and review map. The immediate build order is in Part F.

For a coding agent: read the project-wide rules once, then work on one bounded task from Part F. Do not reinterpret the full product scope for every task.

---

## 1. Purpose

This document defines the exact V1 data flow and implementation rules.

The objective is simple:

> Make one real MSFT adjustment flow work correctly from EDGAR evidence to an adjusted historical P&L.

Do not build a general finance platform first.
Do not design for hypothetical future requirements.
Do not add architecture because it might be useful later.

The code should remain easy for a finance-oriented Python user to read.

Core rule:

> Open financial reasoning. Closed accounting mechanics.

Use LLMs for financial judgment.
Use Python for deterministic calculations, validation, storage, and application of adjustments.

---

## 2. V1 completion definition

V1 is complete when all of the following work for MSFT:

1. Load the latest required 10-K data through EdgarTools.
2. Build a three-year analytical P&L.
3. Run source reconciliation checks and clearly show warnings.
4. Build one useful evidence packet from the filing.
5. Financial Analyst LLM finds the expected adjustment in the first known case.
6. Risk Reviewer LLM reviews the candidate correctly.
7. Deterministic validation and materiality logic runs.
8. Safe items can auto-approve. Uncertain items enter human review.
9. `adjustment_history.csv` preserves proposal and human decision history.
10. Human review supports accept, reject, edit amount, and edit period.
11. Manual human adjustments use the same adjustment engine.
12. Current approved adjustments resolve correctly from history.
13. Adjustments apply to the reported P&L without mutating reported values.
14. Derived subtotals and metrics recalculate correctly.
15. Adjusted reconciliation passes.
16. One golden MSFT end-to-end case passes.

V1 is **not** blocked by:

- more companies;
- quarterly data;
- five years of history;
- CIQ;
- canonical financial taxonomy;
- forecasting;
- valuation;
- balance-sheet normalization;
- cash-flow normalization;
- RAG or vector databases;
- web UI;
- database infrastructure;
- specialist agents;
- a large eval benchmark.

If a new idea is not required for the golden MSFT path, put it in the backlog.

---

## 3. Architecture

Approved architecture:

> Thin sequential functional pipeline.

The main flow should be obvious from `pipeline.py`.

Target shape:

```python
statements = get_statements(ticker)
pnl = prepare_pnl(statements["income_statement"])
checks = reconcile_reported_pnl(pnl)
evidence_packets = build_evidence(ticker=ticker, pnl=pnl)
candidates = discover_adjustments(pnl=pnl, evidence=evidence_packets)
reviews = review_adjustments(candidates=candidates, evidence=evidence_packets)
validated = validate_adjustments(candidates=candidates, reviews=reviews, pnl=pnl)
current_adjustments = resolve_current_adjustments(history)
adjusted_pnl = apply_adjustments(pnl=pnl, adjustments=current_adjustments)
validate_adjusted_pnl(adjusted_pnl)
```

This is conceptual. Do not create wrappers just to reproduce this exact syntax.

Preferred application objects:

- `pd.DataFrame`
- `dict`
- `list`
- `str`
- `float`
- `int`
- small Pydantic models only at LLM/schema boundaries

### V1 technical stack

Preferred stack:

```text
Python 3.12
Pandas
Pydantic
Typer
Rich
EdgarTools
official OpenAI Python SDK
pytest
Ruff
Pyright
uv
```

Use normal environment variables for secrets. Keep configuration in function arguments and simple defaults where possible. Do not add layered YAML profiles or a settings framework.

The OpenAI Agents SDK is not required for V1. The product LLM path is intentionally simple structured inference, not a tool-using agent runtime.

Avoid by default:

- service classes;
- repository classes;
- provider hierarchies;
- controller classes;
- manager classes;
- dependency injection;
- event buses;
- workflow engines;
- generic interfaces;
- custom domain-object hierarchies.

A class is allowed only when a current requirement is clearer with a class than with a function.

---

## 4. Source and storage strategy

### 4.1 EDGAR

EDGAR is the only required V1 financial source.

Use EdgarTools directly.

EdgarTools owns raw filing download and cache behavior.
Do not duplicate raw filing HTML or build a second SEC cache.

Preserve EdgarTools statement DataFrames as returned.
Do not mutate them to fit a custom schema.

### 4.2 File formats

Use simple, inspectable formats.

```text
Markdown  -> evidence packets and human-readable context
JSON      -> structured LLM Analyst and Reviewer outputs
CSV       -> financial tables, adjustment history, reconciliation results
```

Parquet is not required for V1.
Only reconsider it if CSV becomes a real performance or type-preservation problem.

### 4.3 Target folder layout

```text
data/
└── MSFT/
    ├── 01_source/
    │   └── edgar/
    ├── 02_processing/
    │   └── edgar/
    └── 03_output/
        ├── analytical_pnl.csv
        ├── adjusted_pnl.csv
        ├── adjustment_history.csv
        ├── reconciliation_checks.csv
        │
        ├── evidence/
        │   ├── restructuring.md
        │   └── income_tax.md
        │
        ├── analysis/
        │   └── <topic>_<run_id>.json
        │
        └── reviews/
            └── <adjustment_id>_<run_id>.json

prompts/
├── discover_adjustments.md
└── review_adjustment.md

src/smrik/
├── cli.py
├── pipeline.py
├── ingestion/
│   └── edgar.py
├── financials/
│   ├── analysis.py
│   ├── adjustments.py
│   └── reconciliation.py
├── evidence/
│   └── filing.py
└── llm/
    ├── analyst.py
    ├── reviewer.py
    └── schemas.py

tests/
```

This layout is a direction, not a sacred diagram.
Combine files if implementation becomes clearer.
Do not split files to satisfy an architecture picture.

Avoid generic folders such as `utils/`, `common/`, `base/`, or `interfaces/` unless a concrete repeated need exists.

---

# PART A — DATA FLOW

## 5. Stage 1 — EDGAR ingestion

### Input

For V1:

```text
ticker = MSFT
form = 10-K
years = 3
```

### Responsibility

`ingestion/edgar.py` should:

1. Load the required filing through EdgarTools.
2. Load income statement, balance sheet, and cash-flow statement DataFrames.
3. Preserve source values and source metadata.
4. Return simple Python/Pandas objects.

It should not:

- map to a canonical taxonomy;
- normalize signs;
- detect adjustments;
- call an LLM;
- reconcile CIQ;
- create a custom observation object model.

### Cache behavior

Use EdgarTools native caching.
Cached behavior is the default.
Explicit refresh is allowed when needed.
Do not create a custom cache framework.

### Failure behavior

If the required filing or primary statement cannot be loaded, stop the stage with a clear error.
Do not build fallback mazes.

---

## 6. Stage 2 — analytical P&L

### Input

The original EdgarTools income-statement DataFrame.

### Function responsibility

A function such as:

```python
def prepare_pnl(income_statement: pd.DataFrame, years: int = 3) -> pd.DataFrame:
    ...
```

should create a derived analytical view.

The function may:

- select three annual periods;
- keep source line labels and useful source metadata;
- calculate fixed analytical metrics;
- calculate simple anomaly indicators if useful;
- prepare a clean table for downstream logic.

It must not change the reported source values.

### Fixed analytical metrics

V1 may calculate:

- year-over-year change;
- percent of revenue;
- gross margin;
- operating margin;
- effective tax rate.

These metrics provide context only.
They do not decide that an adjustment exists.

### Saved output

```text
data/MSFT/03_output/analytical_pnl.csv
```

### LLM formatting

Use a separate function such as:

```python
def format_pnl_for_llm(pnl: pd.DataFrame) -> str:
    ...
```

Return compact Markdown.
Do not send the entire XBRL dataset when a small relevant table is enough.

---

## 7. Source values and sign convention

Do not invent a signed management-P&L convention in V1.

Preserve EdgarTools values.
Major expense concepts are commonly represented as positive magnitudes in the underlying XBRL/SEC data.

V1 adjustment convention (implementation-corrected 2026-08-22):

```text
item_amount         = positive magnitude of the item's effect on the target line
item_effect_on_line = increased_line | decreased_line   (evidence-backed; null if unsupported)
line_delta          = Python-derived: -item_amount when increased_line,
                      +item_amount when decreased_line
adjusted value      = reported value + sum of approved line deltas
```

The LLM never authors a signed number. Python derives and applies `line_delta`.

Example for an expense removed from an expense line:

```text
Reported SG&A            500
Impairment expense       400  (increased_line)
line_delta               -400
Adjusted SG&A            100
```

Example for a divestiture gain netted inside an expense line:

```text
Reported SG&A            500
Divestiture gain         400  (decreased_line: it reduced SG&A)
line_delta               +400
Adjusted SG&A            900
```

`item_amount` and `item_effect_on_line` are independently supportable facts:
either can be known while the other is unresolved. A signed delta exists only
when both are proven.

Preserve useful XBRL metadata when EdgarTools provides it, such as balance, calculation weight, or preferred sign.

### Direction bounds

Bounds are direction-aware and use `line_delta`, not the parent line's sign:

```text
delta pushes adjusted value through zero
-> removes more than the reported line holds
-> human review
```

A negative reported line alone is no longer a gate failure. Legacy rows that
store only a positive magnitude cannot prove direction and fail closed.

---

## 8. Missing values

Missing is not the same as zero.

Internal representation:

```text
0    = known zero
NaN  = no usable source fact
```

Display missing values as blank or `N/A`.

Do not let one missing value unnecessarily poison unrelated calculations.

Rules:

- aggregations may use available values when that is mathematically safe;
- a ratio or YoY calculation requiring the missing value stays blank;
- an adjustment cannot target a missing line-period value;
- if missing data causes a subtotal mismatch, the reconciliation layer surfaces it.

Missing data should reduce confidence, not automatically break the full model.

---

## 9. Cross-year concept continuity

Do not build custom cross-year XBRL semantic mapping yet.

First inspect real EdgarTools behavior for MSFT.
If EdgarTools already presents usable continuity, use it.

If a real problem appears later, solve the smallest concrete version.

The same rule applies to duplicate source facts returned by EdgarTools:

```text
ambiguous duplicate source fact
-> preserve the ambiguity
-> show it to the user
-> block affected auto-approval
-> do not silently choose or deduplicate
```

---

## 10. Stage 3 — source reconciliation

Reported EDGAR subtotals are useful checks.
They are not normal adjustment targets.

Example:

```text
Revenue          1,000
Cost of revenue    600
Gross profit       400
```

Python can verify:

```text
1,000 - 600 = 400
```

### Source reconciliation

Purpose:

> Check whether our reconstructed reported P&L agrees with reported EDGAR subtotals.

If a check fails:

```text
store failure
show failure clearly to the user
block auto-approval for affected lines
allow explicit human acknowledgement
never create an automatic plug
```

A human acknowledgement does not change `failed` into `passed`.
It records that the user chose to continue.

### Scoped warnings

A reconciliation problem should affect only the relevant part of the model.

Example:

```text
Gross Profit tie-out failed
-> Revenue / Cost of Revenue adjustments lose auto-approval eligibility

Operating Income ties
-> unrelated lines may continue normally
```

### Saved output

```text
data/MSFT/03_output/reconciliation_checks.csv
```

Suggested columns:

```text
check_id
run_id
period
subtotal
reported_value
calculated_value
difference
status
acknowledged
affected_lines
message
```

Keep strings human-readable.

### CLI presentation

Warnings must be visible before related adjustment review.
Do not hide them in logs.

Example:

```text
MSFT — P&L checks

[OK]   Revenue tie-out
[WARN] Gross Profit differs by 30
[OK]   Operating Income tie-out

2 adjustment candidates are affected by this warning.
```

---

## 11. Stage 4 — evidence packets

### Purpose

The evidence packet is the exact factual context sent to the Financial Analyst.

Save it as Markdown.

Example:

```text
data/MSFT/03_output/evidence/restructuring.md
```

### Topic-based design

Evidence packets are topic-based, not answer-based.

Good:

```text
restructuring.md
income_tax.md
stock_based_compensation.md
```

Bad:

```text
normalize_400m_sga.md
remove_one_time_tax_benefit.md
```

The packet must not leak the expected answer.
A packet may produce zero, one, or several candidates.

### Retrieval order

Use EdgarTools before custom retrieval infrastructure.

Preferred sources:

1. structured XBRL notes/disclosures where available;
2. filing search for relevant text;
3. filing sections for broader MD&A/context when necessary.

Do not build RAG or a vector database in V1.

### First case

For the first known MSFT case, manual confirmation of the evidence packet is allowed.
First prove the LLM reasoning path with correct evidence.
Then automate retrieval and test retrieval independently.

### Evidence linkage

Each downstream adjustment should retain simple references:

```text
evidence_file
filing_accession
topic
```

No provenance graph.
No cryptographic evidence store.

---

## 12. Stage 5 — Financial Analyst LLM

### Role

Agent 1 is the Financial Analyst.

Goal: high recall.

The Analyst should surface plausible adjustments even when some later fail review.

It should:

- inspect the evidence packet and financial context;
- identify unusual or economically relevant items;
- propose zero, one, or several candidates;
- target an actual reported P&L line;
- use `sub_item` for useful detail below the reported line;
- add `item_key` as a lowercase hyphen slug of one to six short tokens naming
  the evidence-grounded subject and event, or null when unresolved;
- identify the period;
- propose an amount when supported;
- state how the amount was obtained;
- give a short reason;
- cite evidence;
- state uncertainty.

### One packet per call

Use one topic evidence packet per Analyst call.
Do not batch many unrelated topics into one giant call.

### Structured output

Use the official OpenAI SDK + Responses API + native Structured Outputs/Pydantic when OpenAI is the runtime model.

Use equivalent native structured output support for other model providers when available.
Do not ask for loose JSON and repair it with custom parsing.

Conceptual schema:

```python
class AdjustmentCandidate(BaseModel):
    target_line: str
    sub_item: str | None = None
    item_key: str | None = None
    period: str
    item_amount: float | None = None
    item_effect_on_line: Literal["increased_line", "decreased_line"] | None = None
    amount_basis: Literal["disclosed", "calculated", "estimated", "unknown"]
    calculation: str | None = None
    reason: str
    evidence_refs: list[str]
    uncertainty: str | None = None


class DiscoveryResult(BaseModel):
    candidates: list[AdjustmentCandidate]
```

Keep the real schema minimal.
Do not add fields before they are used.

A discovery candidate may have a missing amount. An adjustment cannot enter the approved/current adjustment set until it has a numeric amount. A missing amount therefore requires human handling or rejection.

### Amount basis

Use:

```text
disclosed  = amount directly stated in filing
calculated = deterministic arithmetic from disclosed inputs
estimated  = financial judgment or assumption required
unknown    = basis cannot be established
```

Estimated adjustments may be proposed.
They always require human review in V1.

### Saved output

```text
data/MSFT/03_output/analysis/<topic>_<run_id>.json
```

Store at least:

```text
run_id
model
prompt_version
filing_accession
evidence_file
topic
status
structured_result
error_stage, if failed
error_message, if failed
```

---

## 13. Target-line rules

Every adjustment must ultimately target one real reported source line.

`sub_item` may describe detail that is not present on the face of the financial statements.

Example:

```text
target_line = Selling, General and Administrative
sub_item    = Restructuring costs
```

The sub-item does not become a fake reported row.
The adjustment is mathematically applied to the real parent line.

### Invalid target

If the Analyst proposes a line that cannot resolve to the actual P&L:

```text
target_valid = false
-> candidate cannot auto-approve
-> do not use fuzzy matching in V1
-> do not let Python guess the intended line
```

If the target is fundamentally wrong, human review should reject the candidate.
A new manual adjustment can be created separately if needed.

---

## 14. Period rules

Period normalization is allowed.
Period inference is not.

Allowed normalization example:

```text
2025 -> FY2025
```

when only one annual 2025 period exists.

Not allowed:

```text
2025
```

when the source contains both FY2025 and Q4 2025 and the intended period is unclear.

The adjustment period follows P&L recognition timing.
It does not follow cash payment timing or announcement date.

If recognition timing is unclear, no auto-approval.

---

## 15. Stage 6 — Risk Reviewer LLM

### Role

Agent 2 is the Risk Reviewer.

Goal: low false acceptance.

It checks:

- evidence support;
- target line;
- period;
- amount;
- calculation;
- amount basis;
- classification;
- contradictions;
- unsupported assumptions;
- evidence strength;
- judgment level.

It must not silently rewrite the Analyst proposal.

### One candidate per call

Review one adjustment candidate per Reviewer call.
Linked group context may also be provided when required.

### Verdict

```text
accept
revise
reject
```

Conceptual schema:

```python
class ReviewResult(BaseModel):
    verdict: Literal["accept", "revise", "reject"]
    evidence_strength: Literal["strong", "medium", "weak"]
    amount_basis: Literal["disclosed", "calculated", "estimated", "unknown"]
    judgment_level: Literal["low", "medium", "high"]
    calculation_valid: bool | None
    target_valid: bool
    item_effect_on_line: Literal["increased_line", "decreased_line"] | None = None
    concerns: list[str]
    suggested_amount: float | None = None
    note: str | None = None
```

The Reviewer independently judges `item_effect_on_line` from the evidence; it
does not echo the Analyst. Disagreement with the Analyst fails auto-approval
closed.

### Revision limit

Reviewer `revise`:

```text
one Analyst revision pass
-> one Reviewer re-check
-> if still unresolved, send to human review
```

Typical history shape:

```text
A0001 v1 proposed  -> reviewer asks revise
A0001 v2 proposed  -> revised Analyst proposal
A0001 v3 approved  -> only after Reviewer + deterministic gate accepts
```

No endless model debate.

### Reviewer context experiment

Still pending:

Compare:

1. candidate + full original evidence packet;
2. candidate + cited evidence only.

Choose based on eval quality.
Do not decide by intuition alone.

### Saved output

```text
data/MSFT/03_output/reviews/<adjustment_id>_<run_id>.json
```

---

# PART B — ADJUSTMENT ENGINE

## 16. One adjustment system, multiple origins

There is one adjustment engine.

An adjustment may originate from:

```text
llm
human
```

`origin` is metadata.
It must not create a second calculation system.

Manual adjustments use the same target, period, amount, validation, history, and application logic.

Human-created adjustments are approved by default because the human is already making the financial judgment.
They still pass hard deterministic mechanics checks.

Reason and evidence are recommended for manual adjustments but not required in V1.

This design is important for testing:

> Test whether adjustments work. Do not maintain one engine for machine adjustments and another for manual adjustments.

---

## 17. Adjustment identity and versioning

Adjustment IDs are simple and stable within a company:

```text
A0001
A0002
A0003
```

Revisions keep the same ID:

```text
A0001 v1
A0001 v2
A0001 v3
```

A genuinely new adjustment receives a new ID.

A refreshed LLM proposal should not overwrite a previously human-reviewed adjustment.

The identity version after `economic-adjustment-v1` is
`economic-adjustment-v2` and contains only:

```text
company + fiscal_period + target_row_key + item_key
```

`target_row_key` reuses the deterministic unique analytical-P&L row selector.
`item_key` is a lowercase hyphen slug of one to six short tokens naming the
specific subject and event. Accession, evidence anchors, query, retrieval,
prose, amount, and direction are provenance/state observations, not identity.

Matching is exact: same key and same company/period/row reuses the ID; the
first valid key on an empty row-period may mint one; a different key on an
occupied row-period, or a null/invalid key, is `identity_unresolved` with no ID,
history append, auto-approval, or P&L effect. Same key on a different period or
target row is a different identity. Legacy or corrupted history fails closed.
Persisted period, row-selector, and state snapshot fields must agree with the
identity payload; one identity assigned to multiple adjustment IDs is also
corrupt and fails closed.

The legacy rule distinguishes financial authority from inert workflow evidence:

- pre-v2 `proposed` or `rejected` rows without identity fields remain stored but
  are ignored for v2 matching and application;
- approved/effective legacy rows with unresolved identity fail closed;
- any row claiming v2 with malformed identity/state data fails closed.

No migration or rewrite occurs. An exact item key with a changed target-row
selector is `identity_unresolved`, preventing selector evolution from silently
minting a second adjustment ID.
For a label-qualified duplicate concept, any non-exact selector on an occupied
concept-period is also unresolved, regardless of item-key spelling. Python
cannot prove whether presentation drift or a genuinely separate analytical row
caused that selector change.

### Version rule

Create a new version only when the adjustment state changes meaningfully.

Examples:

- amount changes;
- group changes;
- status changes;
- revised proposal changes content.

Do **not** create a new version because:

- materiality was calculated;
- a duplicate check ran;
- a reconciliation check ran;
- reviewer metadata was written without changing adjustment state.

`version` means:

> A different state of this adjustment.

---

## 18. Status and human actions

Adjustment status has only three values:

```text
proposed
approved
rejected
```

Reviewer `revise` is workflow state, not a final adjustment status.

Human review actions:

```text
accept
reject
edit_amount
edit_period
```

Additional structured human actions used for history/analysis:

```text
change_group
manual_create
```

`skip` is not a status or history event.
It changes nothing and leaves the adjustment `proposed`.

---

## 19. Canonical adjustment store

`adjustment_history.csv` is the source of truth for adjustments.

It is append-style.
Do not edit old versions in place.

`adjustments.csv` is optional and derived.
It is never manually edited.

Current adjustments are resolved as:

```text
adjustment_history.csv
-> keep approved rows
-> latest approved version for each adjustment_id
-> current adjustment DataFrame
```

Important:

> Keep approved rows first. Then select the latest approved version per ID.

Do not let a newer non-approved workflow row hide the latest approved version.

Example:

```text
A0001 v1 approved
A0001 v2 rejected
```

Current state: A0001 v1 remains in current adjustments. A later approved
version replaces v1; the rejected row neither removes it nor stacks.

---

## 20. `adjustment_history.csv` design

Use a wide snapshot table.
Each row contains the current state of one adjustment version plus the main structured risk features.

Target fields:

```text
adjustment_id
version
run_id
timestamp

origin
group_id
company
target_line
sub_item
period
item_amount
item_effect_on_line
line_delta
status

amount_basis
evidence_strength
judgment_level
reviewer_verdict
model_confidence

pct_revenue
pct_target_line
pct_operating_income

target_valid
period_valid
calculation_valid
possible_duplicate
duplicate_group
duplicate_reason
group_total_disclosed
group_total_proposed
group_reconciles
line_period_total_adjustment
aggregate_over_adjustment
individual_over_adjustment
zero_target_with_line_delta
deterministic_checks_pass
reconciliation_warning
requires_human_review
review_flags

human_action

analyst_model
reviewer_model
analyst_prompt_version
reviewer_prompt_version

evidence_file
analysis_file
review_file
filing_accession
topic

reason
```

This list is deliberately useful for future analysis.
Storage cost is tiny.
Potential future information value is high.

Possible later analyses include:

- human approval rate;
- rejection rate by evidence strength;
- amount correction frequency;
- period correction frequency;
- reviewer vs human agreement;
- rejection probability by materiality;
- estimated vs disclosed amount performance;
- performance by model or prompt version;
- common missed adjustment types;
- manual adjustments with no prior LLM candidate.

Do not place full filing evidence or long LLM reasoning inside CSV cells.
Use file references for long content.

Use readable string categories, not numeric codes.

Field constraints should stay simple:

```text
adjustment_id       required string, e.g. A0001
version             required integer >= 1
run_id              required string
origin              llm | human
group_id            optional string
target_line         required reported source line for an approved adjustment
sub_item            optional string
period              required canonical annual period for an approved adjustment
item_amount         positive numeric magnitude; may be blank while proposed,
                    required before approval
item_effect_on_line increased_line | decreased_line; required before approval
line_delta          Python-derived signed value; required for approval
status              proposed | approved | rejected
amount_basis        disclosed | calculated | estimated | unknown
evidence_strength   strong | medium | weak
judgment_level      low | medium | high
reviewer_verdict    accept | revise | reject
human_action        optional structured action
```

Under the corrected V1 convention (schema version 2), approved rows store the
auditable derivation:

```text
item_amount          positive magnitude; never negative
item_effect_on_line  increased_line | decreased_line
line_delta           Python-derived signed delta (-amount / +amount)
```

Do not silently use a negative item_amount to create an alternate sign
convention. Legacy rows that store only a positive magnitude cannot prove
direction and fail closed rather than being converted.

Boolean/risk fields may be blank when a check has not run yet. Once a version reaches approval/rejection, save the relevant values that were known at that decision point.

---

## 21. Adjustment groups

One economic event may affect several reported lines.
Each line-period effect is a separate adjustment.

Example:

```text
G001 / A0001 -> SG&A             60
G001 / A0002 -> Cost of revenue  40
```

`group_id` is optional metadata.
`apply_adjustments()` does not need it.

Benefits:

- presentation;
- group materiality;
- disclosed-total reconciliation;
- human review context;
- later analysis.

Humans may create a manual adjustment and attach it to an existing group.
Changing `group_id` creates a new adjustment version.

### Disclosed group total

If a filing discloses a total event amount, deterministic code may compare:

```text
group_total_disclosed
group_total_proposed
group_difference
group_reconciles
```

If the group does not reconcile, require human review.

If no disclosed total exists, do not invent one.

If the human rejects one allocation and the remaining approved items no longer equal the disclosed total, show the unresolved difference.
Do not create a plug.

---

## 22. Multiple adjustments to one line-period

This is normal FDD behavior.

Example:

```text
Reported SG&A             1,000
Restructuring adjustment    100
Legal settlement adjustment  40
```

Each adjustment remains a separate record.

Calculation:

```text
Adjusted SG&A
= Reported SG&A
- sum(all current approved adjustments for SG&A / same period)
```

Adjustment order must not affect the result.

Presentation may show:

```text
Reported SG&A
  Restructuring adjustment
  Legal settlement adjustment
Total adjustments
Adjusted SG&A
```

Calculation uses the grouped total.
Presentation preserves individual rows.

---

## 23. Derived subtotals and reported subtotal checks

Adjust underlying source lines.
Do not normally target subtotals such as:

- Gross Profit;
- Operating Income;
- Pre-tax Income;
- Net Income;
- EBITDA;
- margins;
- ETR.

Even if EDGAR reports a subtotal fact, use it primarily as a reconciliation check when underlying components are available.

Example:

```text
Reported Revenue          1,000
Reported Cost of Revenue    600
Reported Gross Profit       400

Cost adjustment             100

Adjusted Revenue          1,000
Adjusted Cost                500
Adjusted Gross Profit        500
```

Do not create a second adjustment to Gross Profit.
Recompute it deterministically.

If the underlying affected line cannot be identified, require human review rather than guessing.

---

## 24. Duplicate-risk checks

Economic identity owns exact same-row matching. Amount, evidence, accession,
sub-item, reason, and other overlap heuristics cannot decide identity; an
occupied row-period with a competing key is `identity_unresolved`. Preserve
candidate/evidence/review artifacts while leaving canonical history and current
approved state untouched. No semantic duplicate subsystem is needed in V1.

---

## 25. Materiality

Materiality is deterministic.
Thresholds are conservative and provisional.

Calculate obvious ratios now.
Do not build a general materiality framework.

Possible metrics:

```text
adjustment / revenue
adjustment / affected line
adjustment / operating income or EBITDA proxy
```

Tax-specific context may include:

```text
adjustment / pre-tax income
ETR impact
```

Materiality must be evaluated at more than one level:

1. individual adjustment;
2. economic event/group;
3. aggregate adjustments for the same line-period.

A small individual adjustment loses auto-approval if its group or line-period aggregate is material. If one linked economic-event group is material, every adjustment in that group requires human review.

Exact thresholds remain pending real MSFT cases.

---

## 26. Deterministic risk and approval gate

The Risk Reviewer does not make the final approval decision alone.
Python owns the final approval gate.

A conservative V1 auto-approval candidate requires all relevant conditions to pass.

Baseline policy:

```text
reviewer verdict == accept
AND evidence_strength == strong
AND amount_basis in {disclosed, calculated}
AND judgment_level == low
AND materiality below provisional threshold
AND target valid
AND period valid
AND no unresolved relevant reconciliation warning
AND no possible duplicate conflict
AND no group reconciliation problem
AND no aggregate over-adjustment
AND Analyst and Reviewer agree on item_effect_on_line
AND the derived line delta does not push the adjusted value through zero
AND all deterministic checks pass
-> eligible for auto-approval
```

Otherwise:

```text
-> human review
```

Estimated amounts always require human review in V1.

The goal is a very low wrong-auto-approval rate.
It is acceptable to send too many items to human review.

---

## 27. Over-adjustment rules

Bounds are direction-aware and use `line_delta`:

```text
adjusted = reported + line_delta
```

### Individual adjustment

If the delta pushes the adjusted value through zero into the opposite sign,
the adjustment removes more than the reported line holds:

```text
reported > 0 and adjusted <= 0
or reported < 0 and adjusted >= 0
-> flag
-> never auto-approve
-> require human review
```

### Aggregate adjustment

The same rule applies to the combined deltas of all current approved
adjustments for the same target line and period, plus the candidate.

### Zero target

```text
reported value == 0
AND derived line_delta != 0
-> human review
```

### Adjusted value below zero

A zero-crossing result is a risk flag, not a universal hard-invalid state.
Some economic lines can legitimately cross zero.

If adjustments produce a zero-crossing result:

```text
-> require human review
-> show exact result
```

Do not universally prohibit it.
A negative reported line by itself is not a gate failure.

---

## 28. Applying adjustments

Core function should remain simple.

Conceptual signature:

```python
def apply_adjustments(
    pnl: pd.DataFrame,
    adjustments: pd.DataFrame,
) -> pd.DataFrame:
    ...
```

Core invariant:

```text
line_delta      = -item_amount when item_effect_on_line == increased_line
                = +item_amount when item_effect_on_line == decreased_line
adjusted_value  = reported_value + sum(current approved line deltas for target line and period)
```

The function must:

- never mutate reported source values;
- group adjustments by target line + period for calculation;
- keep individual adjustments available for presentation;
- recalculate derived subtotals and metrics;
- be order-independent.

---

## 29. Adjusted reconciliation

There are two different reconciliation concepts.

### Source reconciliation

Checks our interpretation of EDGAR.
May warn.
May be human-acknowledged.

### Adjusted reconciliation

Checks our own adjustment mechanics.
Must pass.

If adjusted subtotals do not reconcile after deterministic application:

```text
hard failure
```

Treat this as our code bug until proven otherwise.
Do not ask an LLM to explain it away.

---

# PART C — HUMAN REVIEW

## 30. Review queue

Command:

```bash
smrik review MSFT
```

Default queue:

- only adjustments requiring human attention;
- ordered approximately by risk/materiality;
- auto-approved items summarized separately and available on demand.

Do not clutter the queue with already safe items.

---

## 31. Review screen

Use Rich tables.
The review experience should look closer to financial analysis than to reading a model essay.

Example:

```text
A0042 — Restructuring

| Item                 | FY23 | FY24 | FY25 |
|----------------------|------|------|------|
| Revenue              | ...  | ...  | ...  |
| Gross Profit         | ...  | ...  | ...  |
| SG&A                 | 900  | 950  | 1000 |
| Proposed adjustment  | 0    | 0    | 420  |
| Adjusted SG&A        | 900  | 950  | 580  |
| Operating Income     | ...  | ...  | ...  |
```

Show a small local P&L slice around the target line.
Do not dump the full statement by default.

Then show compact structured information:

```text
Reviewer: accept
Evidence strength: strong
Judgment: medium
Materiality: 5.2% of SG&A
Flags: material, estimated amount
```

### Evidence

Show the cited evidence excerpt directly on the review screen.
Do not force the user to open another view for basic evidence.

If the packet is long, show the cited excerpt and provide an optional full-evidence view.

If an adjustment has a `group_id`, show the linked adjustments together for context. The human decision is still made per adjustment.

### Analyst reasoning

Show one short `reason` by default.
Keep full model reasoning available on demand.

### Reviewer reasoning

Show structured reviewer signals and one short note by default.
Keep full reasoning available on demand.

This reduces anchoring and keeps attention on numbers and evidence.

---

## 32. Human edit behavior

Allowed normal review actions:

```text
accept
reject
edit amount
edit period
skip
```

`skip` changes nothing.

When editing amount or period, show original and new values side-by-side before saving.
Prefer a year-column table.

Example:

```text
| Item            | FY23 | FY24 | FY25 |
|-----------------|------|------|------|
| LLM adjustment  | 0    | 0    | 420  |
| Human override  | 0    | 420  | 0    |
```

Saving a change creates a new adjustment version.
The original LLM proposal remains in history.

Humans do not repair a wrong target line in place.
If the target is wrong, reject the proposal.
Create a separate manual adjustment if needed.

---

## 33. Manual adjustments

Manual adjustments use the same data model and adjustment engine.

A human-created adjustment:

- gets a normal `adjustment_id`;
- has `origin = human`;
- may have a `group_id`;
- uses the same target/period/amount fields;
- passes hard deterministic structural checks;
- is approved by default after those checks;
- may contain optional reason/evidence.

This is important future training data.
A human adjustment with no matching prior LLM proposal is evidence of a possible discovery false negative.

---

## 34. End of review session

After the current review queue is processed:

```text
resolve latest adjustment versions
-> rebuild current approved adjustments
-> apply adjustments
-> recalculate subtotals and ratios
-> rerun aggregate checks
-> rerun adjusted reconciliation
-> show summary
```

Example:

```text
Review complete

Accepted: 5
Rejected: 2
Edited: 1
Skipped: 1

Adjusted P&L rebuilt successfully.
Adjusted reconciliation: PASS
2 source reconciliation warnings remain.
```

---

# PART D — CLI AND RUN BEHAVIOR

## 35. CLI commands

V1 should expose a small set of useful commands.

Recommended:

```bash
smrik ingest MSFT
smrik evidence MSFT
smrik analyze MSFT
smrik review MSFT
smrik export MSFT
smrik run MSFT
smrik eval MSFT
```

Suggested responsibilities:

### `smrik ingest MSFT`

- load filing/statements;
- build analytical P&L;
- run source reconciliation;
- save current deterministic outputs.

### `smrik evidence MSFT`

- build topic evidence packets from the current filing/P&L;
- save Markdown packets.

### `smrik analyze MSFT`

- run/reuse Analyst result;
- run/reuse Reviewer result;
- run deterministic candidate checks;
- update adjustment history with new proposal states;
- auto-approve eligible items;
- report items requiring human review.

### `smrik review MSFT`

- interactive human review;
- append human versions;
- rebuild adjusted model when review ends.

### `smrik export MSFT`

- optional review/export output only;
- no business logic in Excel.

### `smrik run MSFT`

Run the automated path:

```text
ingest
-> analytical P&L
-> source reconciliation
-> evidence
-> Analyst
-> Reviewer
-> deterministic checks
-> auto-approval
-> build current adjusted P&L
-> report remaining human-review queue
```

Do not suddenly become an interactive wizard in the middle of `run`.
If human decisions are required, finish the automated work and tell the user to run `smrik review MSFT`.

### `smrik eval MSFT`

Run explicit live LLM evals.
Normal `pytest` must not call live LLMs.

---

## 36. Failure behavior

Use simple fail-fast behavior by stage.

### Pipeline-breaking failures

Examples:

- required EDGAR filing missing;
- P&L cannot be built;
- adjusted reconciliation fails.

Stop with a clear error.

### Local failures

Examples:

- one evidence topic fails;
- one Analyst call fails;
- one Reviewer call fails.

Persist the failure and continue unrelated topics/candidates when safe.

Store processing failure metadata separately from adjustment status:

```text
processing_status = failed
error_stage
error_message
```

### Warnings

Examples:

- source reconciliation mismatch;
- ambiguous source fact;
- possible duplicate.

Show clearly.
Do not hide in logs.
Do not convert warnings into silent data changes.

### Retries

Avoid retry trees.
At most one simple retry for an obvious transient API/network failure is acceptable.
Do not build a retry framework in V1.

---

## 37. Run IDs and reproducibility

Every pipeline run gets a simple `run_id`.

Example:

```text
20260810_2250
```

Store it as metadata in generated results.
Do not duplicate the full data directory for each run.

Also preserve:

```text
analyst_model
reviewer_model
analyst_prompt_version
reviewer_prompt_version
filing_accession
evidence_file
```

This is enough to compare model/prompt behavior later.
Do not add an experiment-tracking platform.

---

## 38. Rerun and cache behavior

Deterministic stages are cheap.
Rebuild them on normal runs.

LLM calls may be reused when the relevant inputs/configuration have not changed.

Reuse condition conceptually:

```text
same filing
same topic/evidence
same model
same prompt version
-> reuse prior structured result
```

Rerun when:

- filing changes;
- evidence changes;
- model changes;
- prompt version changes;
- user passes explicit `--refresh`.

Do not build a general cache subsystem.
A simple file-based check is enough.
If evidence-change detection needs implementation, use the smallest reliable mechanism such as file metadata/content comparison.
Do not turn this into provenance infrastructure.

### Output preservation

Current deterministic outputs may be rewritten:

```text
analytical_pnl.csv
adjusted_pnl.csv
reconciliation_checks.csv
```

If a reconciliation check has a human acknowledgement, preserve that acknowledgement when the same filing/check remains unchanged. Do not silently lose the user's prior acknowledgement during a rebuild. If the underlying check changes materially, require a new acknowledgement.

`adjustment_history.csv` is append/version history and must not be overwritten.

LLM JSON outputs should preserve prior runs, usually with `run_id` in the filename.

---

# PART E — TESTING AND EVALS

## 39. Testing philosophy

Correct sequence:

```text
business requirement
-> observable acceptance criterion
-> representative example
-> failing test
-> minimal implementation
-> passing test
```

Do not optimize for coverage percentage.
Protect the financial invariants that matter.

Normal tests:

```bash
uv run pytest
```

must be:

- deterministic;
- fast;
- cheap;
- suitable for CI;
- free of live LLM calls.

Use saved LLM outputs as fixtures when deterministic downstream behavior needs them.

---

## 40. Deterministic golden tests

### Test 1 — simple normalization

```text
Reported SG&A
FY23 = 100
FY24 = 500
FY25 = 100

Approved adjustment
FY24 = 400

Expected adjusted SG&A
FY23 = 100
FY24 = 100
FY25 = 100
```

Verify:

- reported values unchanged;
- only FY24 changes;
- history not mutated;
- formula is `reported + approved line_delta`.

### Test 2 — multiple adjustments same line-period

```text
Reported SG&A FY24 = 1,000
A0001 line_delta = -100
A0002 line_delta = -50
Expected adjusted = 850
```

Verify:

- separate adjustment records remain;
- sum is 150;
- order does not matter.

### Test 3 — human amount override

```text
A0001 v1 llm   proposed 400
A0001 v2 human approved 350
```

Expected current item amount: 350.
History retains v1.

### Test 4 — later rejection does not revoke prior approval

```text
A0001 v1 approved 400
A0001 v2 rejected 400
```

Expected current adjustments: A0001 v1 remains effective at 400.

A rejected, proposed, or revise version does not revoke an approved version.
Only a newer approved version supersedes the earlier approved version.
Explicit withdrawal or revocation is a separate future action.

### Test 5 — aggregate over-adjustment

```text
Reported SG&A = 100
A0001 = 60
A0002 = 50
```

Expected:

```text
aggregate_over_adjustment = True
requires_human_review = True
```

### Test 6 — subtotal recomputation

```text
Revenue = 1,000
Cost of revenue = 600
Gross profit = 400
Cost adjustment = 100
```

Expected:

```text
Adjusted revenue = 1,000
Adjusted cost = 500
Adjusted gross profit = 500
```

Verify Gross Profit is recomputed, not directly adjusted.

### Test 7 — missing source value

```text
SG&A FY23 = 200
SG&A FY24 = NaN
SG&A FY25 = 250
```

Expected:

- FY24 remains missing;
- exact-value-dependent metrics are blank;
- unrelated calculations still work;
- no adjustment may target FY24 SG&A;
- tie-out warning appears if missing data prevents reconciliation.

### Test 8 — period normalization

Unambiguous:

```text
2025 -> FY2025
```

Ambiguous:

```text
FY2025 and Q4 2025 both exist
candidate says 2025
-> do not infer
-> require review
```

---

## 41. Analyst eval

Test the Financial Analyst independently from retrieval and adjustment mechanics.

Use one manually verified MSFT evidence packet with a clear expected case.

Expected fields should focus on financial correctness, not exact wording:

```text
candidate found
correct target line
correct period
correct amount or defined tolerance
correct amount basis
supporting evidence is sensible
```

Primary pass condition for the first case:

- candidate found;
- target correct;
- period correct;
- amount correct within agreed tolerance.

Reason text does not need exact-string equality.

---

## 42. Reviewer eval

Test Reviewer independently from Analyst.

Use fixed candidate fixtures.

Case A:

```text
correct candidate
-> reviewer should accept
```

Case B:

```text
deliberately flawed candidate
-> reviewer should detect the flaw
```

For a flawed candidate, either `revise` or `reject` can count as success if the real flaw is identified.
`accept` is a failure.

Score the detected flaw separately:

- wrong amount;
- wrong target;
- wrong period;
- unsupported evidence.

---

## 43. Retrieval eval

Test retrieval independently from Analyst success.

For the first MSFT topic, manually define:

- expected disclosure/note;
- expected relevant section;
- required key facts.

Pass condition:

```text
all required facts are present in the evidence packet
```

Nice-to-have:

- limited irrelevant text;
- useful nearby context.

Do not introduce precision@k, recall@k, embeddings metrics, or retrieval dashboards in V1.

---

## 44. Golden MSFT end-to-end case

The final V1 proof is one real MSFT path:

```text
EDGAR ingestion
-> analytical P&L
-> source reconciliation
-> evidence retrieval
-> Financial Analyst
-> Risk Reviewer
-> deterministic validation
-> approval/human-review path
-> adjustment history
-> current adjustments
-> adjusted P&L
-> adjusted reconciliation
```

The golden case should verify key checkpoints, not only the final number:

- correct filing loaded;
- correct evidence retrieved;
- correct candidate found;
- correct target;
- correct period;
- correct amount;
- reviewer behavior correct;
- deterministic gate correct;
- history row correct;
- adjusted P&L correct;
- adjusted reconciliation passes.

Start with one clear disclosed or mechanically calculable adjustment.
Do not start with the hardest judgment-heavy SBC or tax case.

---

# PART F — IMPLEMENTATION ORDER

## 45. Development sequence

Implement in thin vertical pieces.
Do not ask one coding agent to “build the AI Fund pipeline.”

### Task 1 — inspect and lock real EdgarTools MSFT shape

Goal:

> Confirm actual statement structure, columns, periods, source metadata, and sign behavior for MSFT.

Deliverable:

- small inspection script or focused test;
- notes on real DataFrame shape;
- no new abstraction layer.

Do not build custom mapping before this task.

### Task 2 — ingestion + analytical P&L

Goal:

> Load MSFT statements and create the three-year analytical P&L CSV without changing source values.

Acceptance:

- source DataFrame remains unchanged;
- three annual periods present;
- current analytical metrics calculate;
- `analytical_pnl.csv` written;
- focused tests pass.

### Task 3 — source reconciliation

Goal:

> Reconcile reconstructable reported subtotals and expose mismatches.

Acceptance:

- passing tie-outs recorded;
- failing tie-outs recorded with difference;
- affected lines identified;
- no automatic plug;
- CLI displays warnings clearly.

### Task 4 — adjustment history + deterministic engine

Goal:

> Given known approved adjustment fixtures, resolve current adjustments and produce the correct adjusted P&L.

Implement the deterministic tests in Section 40.

This task must work with no LLM calls.

### Task 5 — human/manual adjustment path

Goal:

> Manual and LLM-originated adjustments use the same engine and history format.

Acceptance:

- manual create;
- accept/reject;
- edit amount;
- edit period;
- version history preserved;
- current resolution correct.

### Task 6 — first frozen MSFT evidence packet

Goal:

> Create one neutral, manually verified evidence packet for a clear MSFT adjustment case.

Do not automate retrieval yet if that delays the first reasoning eval.

### Task 7 — Financial Analyst structured output

Goal:

> Given the frozen packet, Agent 1 returns the expected candidate through a minimal structured schema.

Acceptance:

- no loose JSON parsing;
- result persisted;
- first Analyst eval passes or failure is measurable.

### Task 8 — Risk Reviewer

Goal:

> Review one candidate at a time with structured output.

Acceptance:

- correct fixture accepted;
- planted bad fixture detected;
- one revision loop maximum;
- result persisted.

### Task 9 — deterministic risk gate

Goal:

> Convert reviewed candidates into auto-approved or human-review-required states.

Acceptance:

- amount basis rules;
- materiality signals;
- duplicate flags;
- group checks;
- reconciliation warning integration;
- conservative auto-approval.

Exact materiality thresholds may remain provisional until real cases exist.

### Task 10 — review CLI

Goal:

> Human can inspect evidence and local P&L context, then accept/reject/edit safely.

Use Rich tables.
Keep business logic outside `cli.py`.

### Task 11 — automated retrieval for the first topic

Goal:

> EdgarTools produces an evidence packet containing the facts from the manually verified fixture.

Acceptance:

- retrieval eval passes;
- no vector DB;
- no RAG framework;
- no broad retrieval abstraction.

### Task 12 — `smrik run MSFT` + golden end-to-end test

Goal:

> One command completes the automated path and produces a correct current adjusted model for the golden case.

Acceptance:

- golden checkpoints pass;
- `uv run pytest` passes;
- Ruff passes;
- Pyright passes at the project’s agreed strictness;
- relevant CLI command runs successfully.

Then stop.
Do not add another company before reviewing V1.

---

# PART G — CODING AGENT OPERATING CONTRACT

## 46. Why this section exists

This project previously failed because coding agents produced too much locally plausible software before proving one working path.

The operating contract is designed for current strong coding models such as GPT-5.6 and Claude Opus 5.

The contract follows current vendor guidance:

- give a complete task specification;
- use lean prompts;
- state each important instruction once;
- define autonomy and approval boundaries;
- constrain scope explicitly;
- do not force unnecessary verification loops;
- use subagents only for genuinely independent work;
- evaluate quality on representative tasks instead of assuming higher reasoning effort is always better.

---

## 47. Project-wide agent rules

Use these rules in `AGENTS.md`, `CLAUDE.md`, or the coding harness as appropriate.
Keep them in one place.
Do not duplicate them in every task prompt.

```text
PROJECT GOAL
Build the smallest working MSFT V1 described in the approved design documents.

CODE STYLE
Use simple Python functions and Pandas DataFrames.
Use Pydantic only at external structured-output boundaries.
Prefer explicit control flow over abstraction.
Use short technical English in comments and docstrings.
Use # region / # endregion only when they improve navigation.

SCOPE
Implement only the requested task.
Make routine in-scope decisions yourself.
Do not add unrelated refactors, abstractions, providers, frameworks, or future-facing infrastructure.
If a materially larger scope is required, stop and explain the concrete blocker.

SAFE AUTONOMY
You may read project files, inspect git status/diffs, edit in-scope local files, and run non-destructive tests/lint/type checks without asking first.
Do not perform destructive git actions, external writes, purchases, deployments, or material scope expansion without explicit approval.

ARCHITECTURE
Do not add service/repository/controller/manager/base-class architecture unless the current task cannot be implemented clearly without it.
Do not add RAG, vector databases, workflow engines, ORMs, dependency injection, or multi-provider frameworks in V1.
Do not migrate old directories wholesale. Reuse only proven small pieces when they fit the new design.

TESTING
Start from the task acceptance criteria.
Write or update the focused failing test first when practical.
Implement the minimum code required to pass it.
Run the focused test, then relevant project checks.
Do not create separate verifier agents or repeat successful checks without a reason.

FILES
Keep changes local.
If a small task unexpectedly requires broad changes across many files, stop and explain why before expanding scope.
Do not create helper modules merely to reduce line count.

SUBAGENTS
Do not use subagents for small tasks or for verification.
Use them only when there are genuinely independent, sizeable workstreams that can proceed without shared state.
Keep spawn count low.

COMPLETION
Do not claim completion from inspection alone.
Report:
Changed: what changed.
Tests: exact commands and results.
Not changed: relevant out-of-scope items you intentionally left alone.
```

---

## 48. Task prompt template for coding agents

Do not send vague prompts such as:

> Implement the adjustment pipeline.

Use this shape:

```text
Task
[One observable result.]

Context
[Only the design facts needed for this task. Reference the full spec instead of repeating it.]

Inputs
[Exact files/data/functions already available.]

Expected interface
[Function names or CLI behavior that later tasks rely on.]

Acceptance criteria
- [Observable condition 1]
- [Observable condition 2]
- [Observable condition 3]

Allowed scope
- [Expected files]
- Small supporting edits only when required by the acceptance criteria.

Out of scope
- [Specific nearby temptation]
- No unrelated refactoring.

Validation
Run:
- [focused test]
- [lint/type check if relevant]

Completion report
Changed: ...
Tests: ...
Not changed: ...
```

This is enough.
Do not paste the entire Section 2 document into every task if the agent can read it from the repository.

---

## 49. GPT-5.6-specific working notes

Current OpenAI model guidance is consistent with this project’s needs.

Use these defaults for coding-agent work:

- keep the system/project prompt lean;
- state each rule once;
- give the model the outcome, context, hard constraints, approval boundaries, required evidence, success criteria, and output format;
- let it perform safe local edits and tests without unnecessary confirmation;
- require approval only for destructive/external actions or material scope expansion;
- expose only the tools needed for the current task;
- use representative evals to choose reasoning effort;
- do not assume maximum reasoning or pro mode is always better.

For API-based project LLM calls, start with a measured baseline rather than the maximum effort level.
For difficult Analyst/Reviewer financial reasoning, compare quality across realistic cases before paying for higher reasoning settings.

Do not introduce Programmatic Tool Calling or multi-agent orchestration into V1 just because GPT-5.6 supports them.
The current Analyst/Reviewer flow is deliberately `prompt + evidence -> structured result`.

Keep prompts as normal version-controlled files. Use a small explicit prompt version string such as `v1`, `v2`, or a similarly simple identifier. Do not add a prompt-management platform.

---

## 50. Claude Opus 5-specific working notes

Current Anthropic guidance also matches the project’s failure-prevention rules.

For Opus 5 coding tasks:

- provide the complete bounded task specification up front;
- constrain narrow task scope explicitly;
- expect the model to self-correct and verify normal work without adding extra verifier loops;
- run the task’s required tests, but do not ask for redundant re-checks or separate verification agents;
- keep subagent delegation for genuinely independent, sizeable work only;
- do not use several subagents when one agent can finish the task;
- keep progress updates brief;
- specify document length when asking it to write files so it does not pad deliverables;
- evaluate lower effort levels on real tasks before defaulting everything to maximum effort.

For code review, ask it to find real issues first and filter by severity afterward if needed.
Avoid prompts that unintentionally suppress findings by telling it to report only severe issues when broad bug discovery is the goal.

---

## 51. Git workflow

Git is a containment mechanism.

Default:

```text
one bounded task
-> one small feature branch
-> one coding agent
-> focused test
-> relevant full checks
-> diff review
-> commit
-> merge
```

Do not run several agents against the same files unless there is a real reason.

Do not let an agent perform “while I am here” refactoring.
Report unrelated problems separately.

For a task expected to be small, touching more than roughly 5–8 files is a warning sign, not a hard limit. The agent should stop and explain why the scope expanded before continuing.

Suggested branch examples:

```text
feat/edgar-statements
feat/analytical-pnl
feat/pnl-reconciliation
feat/adjustment-engine
feat/review-cli
feat/msft-evidence
feat/analyst-eval
feat/reviewer-eval
feat/msft-golden-run
```

Exact names do not matter.
Small task boundaries do.

---

# PART H — OPEN ITEMS AND DEFERRED DECISIONS

## 52. Still pending real-data testing

The following are intentionally not fully designed yet.

### Exact materiality thresholds

Calculate the metrics now.
Set thresholds after inspecting real MSFT cases.
Use conservative provisional thresholds if needed for the golden path.

### Reviewer evidence scope

Compare full evidence packet vs cited evidence only.
Choose based on eval results.

### First MSFT adjustment case

Pick a clear disclosed or calculated case.
Do not start with the hardest judgment-heavy case.

### EdgarTools cross-year concept behavior

Inspect first.
Do not pre-build mapping.

### EdgarTools duplicate fact behavior

Inspect real output first.
Only add explicit selection logic if ambiguity actually appears.

### LLM cache key implementation

Need only a simple reliable mechanism.
Do not build cache/provenance infrastructure.

---

## 53. Explicit V1 non-goals

Do not add these unless the golden path cannot work without the smallest version of one of them:

- CIQ ingestion;
- CIQ/EDGAR reconciliation;
- cross-company taxonomy;
- semantic line mapping framework;
- five-year history;
- quarterly model;
- forecasting;
- valuation;
- portfolio construction;
- BS normalization;
- CF normalization;
- EV-to-equity bridge;
- web application;
- production database;
- ORM;
- event sourcing framework;
- cryptographic provenance;
- RAG;
- vector DB;
- agent tool loops;
- autonomous browsing agents;
- specialist adjustment agents;
- generic multi-agent orchestration;
- provider abstraction framework;
- large benchmark suite;
- arbitrary code-coverage target.

---

## 54. Final implementation principles

1. Make one real MSFT path work before broadening scope.
2. Preserve reported data.
3. Keep adjustment history separate from reported data.
4. Use one adjustment engine for both LLM and human adjustments.
5. Keep `adjustment_history.csv` as the adjustment source of truth.
6. Derive current adjustments from the latest approved version of each adjustment ID.
7. Apply adjustments to underlying source lines, not calculated subtotals.
8. Recompute subtotals and analytical metrics deterministically.
9. Use EDGAR-reported subtotals as checks where useful.
10. Show source-data problems to the user instead of hiding them.
11. Treat adjusted reconciliation failure as a code problem.
12. Keep auto-approval conservative.
13. Preserve cheap structured metadata because it can become valuable eval/training data later.
14. Keep long evidence and reasoning outside CSVs.
15. Prefer CSV/JSON/Markdown over infrastructure.
16. Prefer functions and DataFrames over object hierarchies.
17. Prefer one focused test over ten speculative abstractions.
18. Prefer one coding agent on one bounded task over several agents on overlapping work.
19. Do not confuse a sophisticated architecture with a working product.
20. When the golden MSFT path works and tests pass, V1 is done.

---

## 55. Immediate next action

Do not start with the LLM pipeline.

Start implementation with:

> **Task 1 — inspect and lock the actual MSFT EdgarTools output shape.**

Then implement the deterministic financial path before connecting the models.

The first important proof is not that an agent can explain the architecture.
It is that a small tested function can take known reported values and a known approved adjustment and produce the correct adjusted P&L.



---

## 56. External model-guidance references used for the agent contract

The agent rules above were checked against the current official guidance available on 2026-08-10:

- OpenAI: GPT-5.6 model guidance and prompting best practices.
- Anthropic: Prompting Claude Opus 5.

The project does not copy those guides wholesale. It uses only the parts relevant to this repository: lean prompts, explicit scope and autonomy boundaries, complete task specifications, controlled delegation, restrained verification, and representative evals.
