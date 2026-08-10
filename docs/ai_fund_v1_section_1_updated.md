# AI Fund V1 — Section 1: Product and Architecture Decision Log

Date: 2026-08-10  
Status: Approved product and architecture direction, updated after Section 2 discovery  
Audience: Patrik and AI coding agents  
Supersedes: `ai_fund_v1_section_1_findings.md` dated 2026-08-08  
Companion document: `ai_fund_v1_section_2_implementation_spec.md`

## How to use this document

This document defines **what the project is, why it exists, and which architecture rules are fixed for V1**.

Section 2 defines the exact implementation flow, file schemas, review workflow, tests, and build order.

For Patrik:

- use this document to judge whether implementation is still solving the intended product;
- use Section 2 for the detailed build sequence;
- treat items marked **DEFERRED** as backlog, not missing V1 work.

For a coding agent:

- read this document once for product and architecture boundaries;
- read the relevant Section 2 task before coding;
- implement one bounded task at a time;
- do not reinterpret or expand V1 scope.

Core rule:

> Open financial reasoning. Closed accounting mechanics.

---

# PART A — WHY THE PROJECT EXISTS

## 1. Why the project was reset

The previous AI Fund implementation became complex before it produced a reliable end-to-end result.

The main problem was not that LLMs could not discuss the project. They often appeared to understand the idea well.

The implementation failed because too much software was created before the core path worked.

Observed failure modes included:

- hundreds of Python files;
- too many classes and helper abstractions;
- several agent-created layers that were locally plausible but globally inconsistent;
- data engineering, reconciliation, LLM reasoning, agent orchestration, and infrastructure mixed together;
- long implementation sessions without one reliable end-to-end path;
- agents explaining architecture convincingly without executable proof that the system worked;
- large refactors and “future-proofing” before the first product hypothesis was proven.

The new V1 is therefore a lean rebuild.

The old repository is a **code quarry**, not the architecture for the new project.

A proven old function may be copied or adapted when it solves a current need.
Whole directories, class hierarchies, frameworks, and abstractions should not be migrated by default.

The objective is:

> Build the smallest real version of the financial reasoning product that works end to end.

---

## 2. Core product hypothesis

The product is not simply an EDGAR data pipeline.

The core hypothesis is:

> Can an LLM read reported financial statements and related disclosures, identify economically relevant distortions, and propose sensible analytical adjustments that improve a historical financial model?

Examples include:

- restructuring costs hidden inside a larger operating expense line;
- a one-time tax benefit that distorts the effective tax rate;
- unusual gains or losses;
- non-recurring operating costs;
- stock-based compensation that appears abnormally high relative to surrounding periods;
- relevant sub-items disclosed below the level visible on the face of the financial statements.

The LLM should be able to reason about any reported P&L line or disclosed sub-item when evidence supports an adjustment.

V1 does not require a rigid adjustment taxonomy.

Principle:

> Constrain the accounting mechanics. Do not unnecessarily constrain the financial judgment.

---

## 3. Product objective for V1

V1 uses Microsoft (`MSFT`) as the reference company.

The target user experience is eventually:

```bash
smrik run MSFT
```

The automated path should produce:

```text
EDGAR filing
    ↓
reported statements
    ↓
analytical P&L
    ↓
source reconciliation checks
    ↓
filing evidence
    ↓
Financial Analyst LLM
    ↓
adjustment candidates
    ↓
Risk Reviewer LLM
    ↓
deterministic validation and materiality
    ↓
auto-approval or human review
    ↓
adjustment history
    ↓
current approved adjustments
    ↓
adjusted historical P&L
    ↓
adjusted reconciliation
```

The system should produce inspectable files and readable CLI output.

Excel may be added as a review/export surface.
Python remains the source of truth.

---

## 4. V1 completion definition

V1 is complete when one known MSFT case works through the full path.

Required outcome:

1. Load the required MSFT 10-K data through EdgarTools.
2. Build a three-year analytical P&L.
3. Run source reconciliation checks and clearly show warnings.
4. Build one useful evidence packet.
5. Financial Analyst finds the expected adjustment in the known case.
6. Risk Reviewer evaluates the candidate correctly.
7. Deterministic validation and materiality logic runs.
8. Safe candidates may auto-approve.
9. Uncertain or risky candidates enter human review.
10. `adjustment_history.csv` preserves proposal and decision history.
11. Human review can accept, reject, edit amount, and edit period.
12. Human-created adjustments use the same adjustment engine.
13. Current approved adjustments resolve correctly from history.
14. Reported data remains unchanged.
15. Adjusted subtotals and metrics recalculate correctly.
16. Adjusted reconciliation passes.
17. One golden MSFT end-to-end test passes.

When these conditions are met, V1 is done.

Do not delay V1 because a broader platform would be useful later.

---

# PART B — CORE PRODUCT AND DATA PRINCIPLES

## 5. Separate the three hypotheses

The project contains three separate technical questions.

### 5.1 LLM reasoning

Question:

> Given the correct evidence, can the Financial Analyst identify a useful adjustment?

Test independently with a fixed evidence packet.

```text
known evidence packet
    ↓
Financial Analyst
    ↓
expected candidate
```

### 5.2 Evidence retrieval

Question:

> Can the system construct an evidence packet that contains the facts the Analyst needs?

Test independently from the model.

```text
known filing
    ↓
retrieval
    ↓
evidence packet
    ↓
required facts present?
```

### 5.3 Adjustment mechanics

Question:

> Given a known valid adjustment, can the deterministic software process it correctly?

Test without an LLM.

```text
known adjustment fixture
    ↓
validation
    ↓
approval state
    ↓
adjustment history
    ↓
adjusted P&L
```

Only connect all three after they work independently.

This split is required because otherwise an end-to-end failure does not tell us whether retrieval, LLM reasoning, or accounting mechanics failed.

---

## 6. Factual data and financial judgment are different layers

### Deterministic factual layer

Use Python and EdgarTools for:

- reported financial statements;
- periods;
- source line items;
- arithmetic;
- reconciliations;
- materiality metrics;
- duplicate-risk flags;
- approval rules;
- adjustment version resolution;
- adjusted-model calculations.

### Financial judgment layer

Use LLMs for:

- identifying unusual items;
- interpreting disclosures;
- deciding whether an item may be non-recurring or analytically distorting;
- proposing adjustments;
- explaining the financial reasoning;
- challenging proposals through the Risk Reviewer.

Principle:

> Use LLMs for judgment. Use Python for deterministic mechanics.

Do not ask an LLM to solve a data-engineering problem that Python can solve reliably.

---

## 7. Reported data is immutable

Reported financial data remains separate from analytical adjustments.

Never overwrite source values to make the model easier to work with.

Conceptual structure:

```text
Reported
+ Adjustment layer
= Adjusted analytical model
```

Example under the V1 positive-magnitude convention:

```text
                    FY23    FY24    FY25
Reported SG&A        100     500     100
Adjustments            0     400       0
Adjusted SG&A         100     100     100
```

The original reported value remains available after the adjustment is applied.

This separation is a product requirement, not an implementation preference.

---

## 8. One adjustment engine, multiple origins

There is one adjustment system.

An adjustment may originate from:

```text
llm
human
```

`origin` is metadata.
It does not create different calculation logic.

Both LLM and human adjustments use the same:

- target-line rules;
- period rules;
- amount representation;
- deterministic validation;
- history/versioning model;
- application logic;
- adjusted-model calculation.

Human-created adjustments are approved by default because the human is making the financial judgment.
They still pass hard deterministic mechanics checks.

Reason and evidence are recommended for manual adjustments but are not mandatory in V1.

This architecture is important for testing:

> Test whether an adjustment works. Do not maintain one adjustment engine for the model and another for the human.

---

## 9. Adjustment history is first-class data

The system should not keep only the final accepted number.

The history of proposals and human decisions can become useful evaluation and training data.

Examples of useful observations:

- LLM proposal accepted unchanged;
- LLM proposal rejected;
- human corrected the amount;
- human corrected the period;
- Risk Reviewer disagreed with the human;
- human created an adjustment that the LLM never proposed;
- rejection rate by evidence strength;
- rejection rate by materiality;
- performance by prompt or model version;
- common adjustment categories that the LLM misses.

Storage cost is small.
Potential future information value is high.

Therefore:

> `adjustment_history.csv` is the canonical adjustment store.

Current adjustments are derived from the latest version of each adjustment ID.

Do not build an event-sourcing framework.
A plain append-style CSV is enough.

---

## 10. Adjustment identity and versioning

Use simple adjustment IDs within a company:

```text
A0001
A0002
A0003
```

Use integer versions:

```text
A0001 v1
A0001 v2
A0001 v3
```

Create a new version only when the actual state changes materially, such as:

- amount changed;
- period changed;
- group changed;
- status changed;
- Analyst revised the proposal.

Do not create a new version because a materiality check ran or metadata was recalculated.

A refreshed LLM run must not overwrite a human-reviewed adjustment.
If matching is uncertain, create a new adjustment ID and let duplicate-risk logic flag possible overlap.

---

## 11. Adjustment status and human actions

Final adjustment status has three values:

```text
proposed
approved
rejected
```

Reviewer `revise` is workflow state, not a final adjustment status.

Human review supports:

```text
accept
reject
edit_amount
edit_period
```

Additional history actions may include:

```text
change_group
manual_create
```

`skip` changes nothing.
The adjustment remains proposed and stays in the review queue.

---

## 12. Current adjustments are derived, not independently maintained

Resolution rule:

```text
adjustment_history.csv
    ↓
latest version for each adjustment_id
    ↓
keep status == approved
    ↓
current adjustments
```

Important:

> Select the latest version first. Then check the status.

Example:

```text
A0001 v1 approved
A0001 v2 rejected
```

Current state: A0001 is not applied.

Do not search for the latest historical approved version.

A separate `adjustments.csv` may be written as a convenience view, but it is derived and never edited directly.

---

## 13. Sign convention is locked for V1

Preserve EdgarTools source values as returned.

Do not create a custom signed management-P&L convention just to support adjustments.

V1 adjustment convention:

```text
adjustment amount = positive magnitude being removed
adjusted value    = reported value - total approved adjustment
```

Example:

```text
Reported SG&A     500
Adjustment        400
Adjusted SG&A     100
```

Example for unusual revenue:

```text
Reported revenue  1,000
Adjustment          100
Adjusted revenue    900
```

Negative source facts can occur.
They are outside the simple auto-approval path.

Rule:

```text
reported target value < 0
-> require human review
```

Do not add a second sign framework until a real case proves that it is needed.

---

## 14. Missing values are not zero

Use this distinction:

```text
0    = known zero
NaN  = no usable source fact
```

Display missing values as blank or `N/A`.

Do not let one missing value unnecessarily break unrelated calculations.

Rules:

- ratios or YoY calculations that require a missing value stay blank;
- safe aggregations may use available values;
- an adjustment cannot target a missing line-period value;
- reconciliation checks show the effect when missing data prevents a subtotal from tying.

Principle:

> Missing data should reduce confidence, not automatically break the whole model.

---

## 15. Multiple adjustments to one line-period are normal

Several economic adjustments may affect the same reported line and year.

Example:

```text
Reported SG&A              1,000
Restructuring adjustment     100
Legal settlement adjustment   40
Total adjustments             140
Adjusted SG&A                 860
```

Each adjustment stays separate.

Calculation is:

```text
adjusted value
= reported value
- sum(all current approved adjustments for that line and period)
```

Order does not matter.

Presentation may show each adjustment individually.
Calculation uses the total.

---

## 16. One adjustment targets one line and one period

If one economic event affects several reported lines, create separate linked adjustments.

Example:

```text
G001 / A0001 -> SG&A             60
G001 / A0002 -> Cost of revenue  40
```

Use optional `group_id` to link adjustments from the same underlying event.

`group_id` supports:

- presentation;
- group materiality;
- disclosed-total checks;
- human review context;
- later analysis.

It does not change `apply_adjustments()` mechanics.

A human-created adjustment may join an existing group.

---

## 17. Adjust underlying source lines, not calculated subtotals

Normal adjustment targets are underlying reported source lines.

Do not directly adjust analytical subtotals or ratios such as:

- Gross Profit;
- Operating Income;
- Pre-tax Income;
- Net Income;
- EBITDA;
- margins;
- ETR.

If EDGAR reports a subtotal fact, use it primarily as a reconciliation check when underlying components are available.

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

Do not also create a Gross Profit adjustment.

If the affected underlying line cannot be identified, require human review rather than guessing.

---

# PART C — SOURCES, EVIDENCE, AND FINANCIAL SCOPE

## 18. EDGAR is the only required V1 financial source

Use EdgarTools directly for:

- filing access;
- XBRL statements;
- financial statement DataFrames;
- notes/disclosures where available;
- filing text/sections/search where useful.

Do not build a custom SEC/XBRL framework unless EdgarTools lacks a capability required by the golden MSFT path.

EdgarTools owns raw filing download/cache behavior.
Do not duplicate raw filing HTML just to create another cache.

---

## 19. CIQ is explicitly out of scope for V1

The previous project spent substantial time on Capital IQ ↔ EDGAR reconciliation before proving the core product.

V1 excludes:

- CIQ ingestion;
- CIQ ↔ EDGAR line reconciliation;
- large alias tables;
- semantic matching systems between CIQ and XBRL;
- reconciliation agents for the two sources.

CIQ may return later if it solves a demonstrated problem.

---

## 20. Preserve EdgarTools output

Keep EdgarTools statement DataFrames as returned.

Do not immediately transform them into a large custom financial-observation model.

Create derived analytical views separately.

Principle:

> Never mutate source data to make downstream analysis convenient. Create a derived view.

Do not design cross-year semantic mapping until real EdgarTools MSFT output shows a concrete need.

If EdgarTools returns ambiguous duplicate facts:

```text
preserve ambiguity
-> show user
-> block affected auto-approval
-> do not silently choose
```

---

## 21. Financial scope

V1 loads all three primary statements:

- income statement;
- balance sheet;
- cash-flow statement.

Adjustment discovery focuses on the P&L.

Balance-sheet and cash-flow data may be used as context.

Balance-sheet normalization, cash-flow normalization, and EV-to-equity bridge work are deferred.

---

## 22. Historical period

V1 uses three annual historical periods.

Three years are enough for the first anomaly and normalization use cases while keeping the model small.

Five years may be added later.

Quarterly data is not required for V1.

---

## 23. Deterministic analytical context

Python may calculate a small fixed set of context metrics:

- year-over-year change;
- percent of revenue;
- gross margin;
- operating margin;
- effective tax rate;
- simple anomaly indicators when useful.

These metrics provide context only.

An anomaly flag is not an adjustment.

Dynamic LLM-created ratios are not part of V1.

---

## 24. No canonical financial taxonomy in V1

Stay with source line items.

Do not create:

- universal chart of accounts;
- broad canonical taxonomy;
- large alias tables;
- semantic line-item hierarchy;
- LLM-assisted mapping framework.

An LLM candidate must resolve to a real reported target line before it can enter the approved adjustment set.

For V1:

```text
period normalization = allowed
period inference      = not allowed
fuzzy target matching = not allowed
```

Cross-company normalization can be added after the MSFT path works and a real requirement appears.

---

## 25. Evidence packets are exact factual LLM input

An evidence packet is the factual context sent to the Financial Analyst.

Save it as Markdown.

Examples:

```text
restructuring.md
income_tax.md
stock_based_compensation.md
```

Evidence packets are topic-based, not answer-based.

Good:

```text
restructuring.md
```

Bad:

```text
remove_100m_restructuring_charge.md
```

The packet must not leak the expected answer.

One packet may produce zero, one, or several adjustment candidates.

---

## 26. Evidence retrieval stays simple first

Use EdgarTools before custom retrieval infrastructure.

Preferred order:

1. structured notes/disclosures where available;
2. filing search;
3. broader filing sections or MD&A when needed.

The first known MSFT evidence packet may be manually verified.

Test retrieval separately from LLM reasoning.

Do not add RAG or a vector database unless simple retrieval repeatedly fails on real cases.

---

## 27. Source reconciliation is a user-visible product feature

EDGAR-reported subtotals can act as checks on our reconstructed reported P&L.

Example:

```text
Revenue          1,000
Cost of revenue    600
Gross profit       400
```

Python can verify the relationship where appropriate.

If a source reconciliation check fails:

```text
store the failure
show it clearly to the user
block auto-approval for affected lines
allow explicit human acknowledgement
never create an automatic plug
```

A human acknowledgement means:

> Continue despite the known mismatch.

It does not change the check from failed to passed.

Warnings should be scoped to the affected part of the model.

Do not stop unrelated areas if they remain valid.

---

## 28. Adjusted reconciliation is different from source reconciliation

There are two different checks.

### Source reconciliation

Question:

> Did we interpret the reported EDGAR model correctly?

A mismatch may be caused by source hierarchy, missing facts, dimensions, or our reconstruction.
It can be shown as a warning and acknowledged by the user.

### Adjusted reconciliation

Question:

> After applying our own adjustments, does our deterministic adjusted model calculate correctly?

This should always pass.

An adjusted reconciliation failure is a code or mechanics problem.
Treat it as a hard failure.

---

# PART D — LLM PRODUCT ARCHITECTURE

## 29. The product LLM workflow is intentionally simple

V1 does not require autonomous tool-using agents.

The core model pattern is:

```text
prompt + evidence
    ↓
model
    ↓
structured output
```

No V1 requirement for:

- tool loops;
- autonomous browsing;
- persistent agent memory;
- agent handoffs;
- generic orchestration framework;
- specialist adjustment agents.

The intelligence being tested is financial reasoning.

Do not add an agent framework because current frontier models support one.

### Product model and SDK direction

For the initial implementation, use strong models for both Analyst and Reviewer roles and optimize for correctness before API cost.

When OpenAI is used as the runtime model:

- use the official OpenAI Python SDK;
- use the Responses API;
- use native Structured Outputs with small Pydantic schemas;
- do not ask for loose JSON and then build repair/parsing logic.

The OpenAI Agents SDK is not required for V1 because there are no product tool loops, handoffs, or persistent agent sessions.

Different providers may be tested later when evals show a reason.
Do not build a generic provider-abstraction framework in advance.

### Product prompt management

Keep product prompts as normal version-controlled files:

```text
prompts/
    discover_adjustments.md
    review_adjustment.md
```

Use a simple prompt version such as `v1`, `v2`, or another short explicit identifier.
Store model and prompt version with results.

Prompt design should follow the same lean principles used for coding agents:

- state each important rule once;
- define the financial role and objective clearly;
- give the exact evidence/context needed for that call;
- define the structured output contract;
- avoid repeated generic warnings and long boilerplate;
- add examples only when they encode a product requirement or fix a measured eval gap;
- tune reasoning/effort using representative financial eval cases.

Do not create a prompt-management platform for V1.

---

## 30. Financial Analyst role

Agent 1 is the Financial Analyst.

Goal: **high recall**.

It should:

- inspect the financial context and evidence;
- identify economically relevant or unusual items;
- surface plausible adjustment candidates;
- identify sub-items hidden within larger reported lines;
- identify target line and period;
- propose an amount when evidence supports one;
- classify how the amount was obtained;
- show the calculation or method when relevant;
- cite supporting evidence;
- state uncertainty;
- return zero candidates when no adjustment is supported.

It is acceptable for the Analyst to surface candidates that the Risk Reviewer or human later rejects.

The main Analyst failure to minimize is a meaningful adjustment that is never surfaced.

---

## 31. Risk Reviewer role

Agent 2 is the Risk Reviewer.

Goal: **low false acceptance**.

It checks:

- evidence support;
- target line;
- period;
- amount;
- arithmetic/calculation;
- amount basis;
- classification;
- contradictions;
- unsupported assumptions;
- evidence strength;
- judgment level.

Reviewer verdict:

```text
accept
revise
reject
```

The Reviewer must not silently rewrite the Analyst proposal.

If it returns `revise`:

```text
one Analyst revision pass
-> one Reviewer re-check
-> unresolved case goes to human review
```

No endless model debate.

---

## 32. Reviewer context remains an experiment

Two reviewer-input approaches remain valid candidates:

```text
proposal + full original evidence packet
```

versus:

```text
proposal + cited/relevant evidence only
```

Too much context may distract the Reviewer.
Too little context may hide contradictions.

Choose using eval results.

Status: **PENDING REAL EVAL**.

---

## 33. Amount basis is explicit

Use simple categories:

```text
disclosed
calculated
estimated
unknown
```

Definitions:

- `disclosed`: amount is directly stated in the filing;
- `calculated`: deterministic arithmetic from disclosed inputs;
- `estimated`: financial judgment or assumption is required;
- `unknown`: basis cannot be established.

Estimated adjustments may be proposed.
They always require human review in V1.

Calculated amounts may be eligible for auto-approval if the calculation is independently valid and all other gates pass.

---

## 34. Do not trust one numeric confidence score

Do not make approval decisions from one model confidence number.

Prefer observable structured signals:

```text
evidence_strength = strong | medium | weak
amount_basis      = disclosed | calculated | estimated | unknown
judgment_level    = low | medium | high
reviewer_verdict  = accept | revise | reject
```

A numeric model confidence value may be stored as a weak signal for later analysis.
It is not the approval engine.

---

## 35. Risk-based approval is conservative

The Risk Reviewer does not make the final approval decision alone.

Python owns the deterministic approval gate.

Baseline V1 auto-approval requires all relevant conditions to be safe, including:

- Reviewer accepts;
- evidence is strong;
- amount basis is disclosed or calculated;
- judgment is low;
- materiality is below the provisional threshold;
- target is valid;
- period is valid;
- calculation is valid where applicable;
- no unresolved relevant source-reconciliation warning;
- no duplicate conflict;
- no group-reconciliation problem;
- no aggregate over-adjustment;
- source target is not negative;
- all other hard mechanics checks pass.

If the system cannot establish that an adjustment is safe to auto-accept:

> Send it to human review.

The V1 priority is to minimize wrong auto-approved adjustments.
Extra human review is acceptable.

---

## 36. Materiality is deterministic but thresholds remain provisional

Calculate obvious materiality measures such as:

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

Evaluate materiality at:

1. individual adjustment level;
2. economic-event/group level;
3. aggregate line-period level.

Several individually small adjustments may become material together.

Exact thresholds should be set after inspecting real MSFT cases.

Status: **PENDING REAL CASE CALIBRATION**.

---

## 37. Duplicate risk is a flag, not an automatic merge

Two proposals may describe the same underlying item.

V1 may flag likely overlap using simple observable features such as:

- same target line;
- same period;
- same or similar amount;
- same evidence;
- similar sub-item or reason.

Store duplicate-risk metadata.

Do not automatically merge or delete candidates.

Possible duplicates require human review before both can be applied.

Do not build a semantic deduplication framework in V1.

---

## 38. Group reconciliation may use disclosed event totals

If several linked adjustments belong to one event and the filing discloses the total event amount, Python may compare:

```text
group total disclosed
group total proposed
difference
reconciles?
```

If the group does not reconcile, require human review.

If the human later rejects one allocation, show any unresolved difference.
Do not invent a plug to force the group to tie.

---

## 39. Human review is part of the product, not a failure mode

No web UI is required for V1.

Use Typer + Rich.

Default review queue:

- only items that need human attention;
- highest-risk or most material items first;
- auto-approved items summarized separately.

The review screen should be finance-first and table-first.

Example:

```text
| Item                | FY23 | FY24 | FY25 |
|---------------------|------|------|------|
| Reported SG&A       | 900  | 950  | 1000 |
| Proposed adjustment | 0    | 0    | 420  |
| Human override      | 0    | 0    | 350  |
| Adjusted SG&A       | 900  | 950  | 650  |
```

Show a small local P&L slice around the target line.

Default review context should also show:

- short Analyst reason;
- structured Reviewer signals;
- materiality;
- risk flags;
- cited evidence excerpt;
- source reconciliation warning when relevant.

Do not lead with long LLM reasoning essays.
The user should judge the evidence and numbers, not be anchored by model prose.

---

# PART E — STORAGE AND TECHNICAL ARCHITECTURE

## 40. Use simple inspectable file formats

V1 file-format rule:

```text
Markdown -> evidence and human-readable LLM context
JSON     -> structured Analyst and Reviewer outputs
CSV      -> financial tables, adjustment history, reconciliation results
```

Parquet is not required for V1.

Reconsider Parquet only if CSV creates a real performance or type-preservation problem.

Do not choose a storage format because it sounds more “production ready.”
Use the simplest format that preserves the required information.

---

## 41. Canonical files

Target processed outputs include:

```text
data/MSFT/processed/
    analytical_pnl.csv
    adjusted_pnl.csv
    adjustment_history.csv
    reconciliation_checks.csv

    evidence/
        <topic>.md

    analysis/
        <topic>_<run_id>.json

    reviews/
        <adjustment_id>_<run_id>.json
```

`adjustment_history.csv` is canonical for adjustment state.

`adjustments.csv`, if created, is only a derived convenience output.

Long evidence and LLM reasoning stay out of CSV cells.
Store references to Markdown/JSON files instead.

---

## 42. Preserve cheap structured metadata

The adjustment history should preserve useful structured features when they are cheap to store.

Examples:

- model and prompt version;
- evidence strength;
- amount basis;
- judgment level;
- Reviewer verdict;
- materiality metrics;
- duplicate-risk fields;
- group fields;
- source-reconciliation warnings;
- human action;
- evidence file;
- filing accession;
- topic;
- run ID.

This data may later support:

- model evaluation;
- prompt comparisons;
- human-vs-model agreement analysis;
- rejection prediction;
- discovery false-negative analysis;
- eventual learned risk scoring.

Do not build that later system now.
Only preserve the low-cost data needed to make it possible.

---

## 43. Python is the source of truth

Financial calculations live in Python.

Excel is optional output.

Do not put required business logic only in an Excel workbook.

Principle:

> If a number cannot be reproduced from code and stored data, it is not part of the model.

---

## 44. Approved application architecture

Architecture:

> Thin sequential functional pipeline.

Preferred application objects:

- Pandas DataFrames;
- normal Python functions;
- dictionaries;
- lists;
- strings;
- numbers;
- small Pydantic models at external schema boundaries.

The high-level flow should remain visible in `pipeline.py`.

Conceptual shape:

```python
statements = get_statements(ticker)
pnl = prepare_pnl(statements["income_statement"])
checks = reconcile_reported_pnl(pnl)
evidence = build_evidence(ticker=ticker, pnl=pnl)
candidates = discover_adjustments(pnl=pnl, evidence=evidence)
reviews = review_adjustments(candidates=candidates, evidence=evidence)
validated = validate_adjustments(candidates=candidates, reviews=reviews, pnl=pnl)
current = resolve_current_adjustments(history)
adjusted = apply_adjustments(pnl=pnl, adjustments=current)
validate_adjusted_pnl(adjusted)
```

This is conceptual.
Do not create wrapper functions merely to reproduce this exact syntax.

---

## 45. Domain-heavy architecture is rejected

Do not create by default:

```text
FinancialStatement
FinancialDataset
ObservationStore
AdjustmentRepository
AdjustmentManager
EvidencePacketService
FinancialModelService
BaseProvider
BaseRepository
GenericReconciliationService
```

Avoid unnecessary:

- service classes;
- repositories;
- controllers;
- managers;
- provider hierarchies;
- base classes;
- interfaces;
- dependency injection;
- generic domain frameworks.

A class is allowed only when a current requirement is clearly easier to understand with a class than with a function.

Principle:

> Complexity is a defect unless the current task requires it.

---

## 46. Pydantic is a boundary tool

Pydantic is approved for structured LLM outputs and other clear schema boundaries.

It is not the central application architecture.

Good use:

```python
class AdjustmentCandidate(BaseModel):
    target_line: str
    period: str
    adjustment_amount: float | None
```

Bad direction:

```text
Turn every row, statement, metric, adjustment, event, and repository into a Pydantic/domain object.
```

Use DataFrames for financial tables.

---

## 47. Pandas is canonical for V1

Use Pandas throughout application-level financial logic.

Do not mix Pandas, Polars, DuckDB relation objects, PyArrow tables, and custom wrappers without a concrete reason.

The data size is small.
Readability and familiarity matter more than theoretical performance.

---

## 48. File-count discipline

### Communication style in code and agent output

Use simple technical English in:

- comments;
- docstrings;
- CLI messages;
- change summaries;
- coding-agent completion reports.

Preferred style is close to ASD-STE100 Simplified Technical English:

- short sentences;
- direct terms;
- one idea per sentence when practical;
- no decorative introductions;
- separate fact, judgment, and uncertainty.

Code identifiers should still use normal clear Python names.

Adding a module is a cost.

Aim for roughly 10–25 meaningful source files during V1.
The exact count is not a target.

Avoid generic dumping grounds such as:

```text
utils/
common/
base.py
interfaces.py
helpers.py
```

unless a real repeated need appears.

Current direction:

```text
src/smrik/
    cli.py
    pipeline.py

    ingestion/
        edgar.py

    financials/
        analysis.py
        adjustments.py
        reconciliation.py

    evidence/
        filing.py

    llm/
        analyst.py
        reviewer.py
        schemas.py
```

Combine files when that is clearer.
Do not split code merely to protect an architecture diagram.

---

## 49. Dependencies

Preferred V1 stack:

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

The OpenAI Agents SDK is not required for V1.

Explicitly avoid unless a real requirement appears:

- LangChain;
- generic agent frameworks;
- workflow engines;
- vector databases;
- RAG frameworks;
- ORMs;
- event buses;
- dependency-injection frameworks;
- unnecessary provider abstractions.

---

## 50. CLI is a convenience layer

Typer is required for V1.
Rich is used for readable terminal output.

Possible commands:

```bash
smrik ingest MSFT
smrik evidence MSFT
smrik analyze MSFT
smrik review MSFT
smrik export MSFT
smrik run MSFT
```

Each CLI command calls normal Python functions.

Do not put finance logic directly inside CLI callbacks.

`smrik run MSFT` should run the automated path and report items that require human review.
It should not unexpectedly become an interactive wizard halfway through.

`smrik review MSFT` handles the human review queue.

---

## 51. Configuration stays minimal

Use:

- function arguments;
- normal Python defaults;
- environment variables for secrets;
- a small number of explicit CLI options where needed.

Avoid:

- layered YAML profiles;
- provider registries;
- elaborate settings classes;
- configuration frameworks.

Add configuration only when a real variable needs configuration.

---

# PART F — TESTING AND EVALUATION

## 52. Testing follows the business requirement

Correct sequence:

```text
business requirement
    ↓
observable acceptance criterion
    ↓
representative example
    ↓
test
    ↓
implementation
```

The coding agent may write the test.

The product/design process defines what correct financial behavior means.

Do not let a coding agent invent the business rule from whatever test is easiest to implement.

---

## 53. Four lightweight test layers

### Unit tests

Examples:

- adjustment arithmetic;
- latest-version resolution;
- period normalization;
- materiality;
- aggregation;
- duplicate-risk flags;
- over-adjustment checks.

### Component tests

Examples:

- EdgarTools statement -> analytical P&L;
- source P&L -> reconciliation checks;
- known adjustment -> adjusted P&L.

### LLM evals

Examples:

- Analyst finds known adjustment from fixed evidence;
- Reviewer accepts a correct candidate;
- Reviewer catches a deliberately flawed candidate.

### Golden end-to-end test

One known MSFT case through the complete pipeline.

Do not hide all correctness behind the end-to-end test.

---

## 54. Normal tests must be deterministic and cheap

Default:

```bash
uv run pytest
```

should not make live LLM calls.

Use saved/frozen outputs as fixtures for downstream deterministic tests.

Real model evaluation should be explicit, for example:

```bash
smrik eval MSFT
```

or an equivalent dedicated command.

This keeps normal development fast and reproducible.

---

## 55. Do not chase code coverage percentage

No arbitrary code-coverage target is required for V1.

Protect the business invariants that can make the financial output wrong.

Examples:

- reported values remain unchanged;
- latest rejected version removes an earlier approved adjustment;
- multiple adjustments to one line are summed once;
- adjustment order does not matter;
- derived subtotals are recalculated, not double-adjusted;
- source-reconciliation failure is visible;
- adjusted reconciliation must pass.

One focused test around a real invariant is better than many tests around speculative abstractions.

---

## 56. LLM evals test fields, not wording

Do not require exact natural-language equality.

For the first Analyst case, score the important financial fields separately:

- candidate found;
- target line correct;
- period correct;
- amount correct within the defined tolerance;
- amount basis correct;
- evidence support sensible.

For a flawed Reviewer fixture:

- `accept` should fail;
- `revise` or `reject` may both pass if the flaw is identified correctly.

The purpose of the eval is to test financial behavior, not prose similarity.

---

## 57. Benchmark strategy

Do not build a large benchmark before the first MSFT case works.

Start with:

- one manually verified retrieval case;
- one known Analyst case;
- one correct Reviewer case;
- one deliberately flawed Reviewer case;
- one golden end-to-end case.

After V1 works, turn these into regression cases and expand the manually curated validation set.

---

# PART G — CODING-AGENT OPERATING RULES

## 58. Why coding-agent rules matter

The previous implementation failed partly because strong coding agents were allowed to expand scope and architecture faster than correctness could be verified.

Modern frontier coding models can complete large tasks and make many reasonable local decisions.
That is useful only when the product boundary is clear.

The project therefore gives agents:

- enough autonomy for safe local work;
- complete task specifications;
- explicit scope boundaries;
- clear acceptance criteria;
- fewer unnecessary verification and delegation loops.

These rules were updated after reviewing current GPT-5.6 and Claude Opus 5 guidance.

---

## 59. Project-wide coding-agent contract

Use one compact project contract.
Do not repeat the same rule in many prompts.

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
You may read project files, inspect git status and diffs, edit in-scope local files, and run non-destructive tests, lint, and type checks without asking first.
Do not perform destructive git actions, external writes, deployments, purchases, or material scope expansion without explicit approval.

ARCHITECTURE
Do not add service/repository/controller/manager/base-class architecture unless the current task cannot be implemented clearly without it.
Do not add RAG, vector databases, workflow engines, ORMs, dependency injection, or multi-provider frameworks in V1.
Do not migrate old directories wholesale. Reuse only proven small pieces when they fit the new design.

TESTING
Start from the task acceptance criteria.
Write or update the focused failing test first when practical.
Implement the minimum code required to pass it.
Run the focused test and the relevant project checks.
Do not create separate verifier agents or repeat successful checks without a reason.

FILES
Keep changes local.
If a small task unexpectedly requires broad changes across many files, stop and explain why before expanding scope.
Do not create helper modules merely to reduce line count.

SUBAGENTS
Do not use subagents for small tasks or for verification.
Use them only for genuinely independent, sizeable workstreams that can proceed without shared state.
Keep spawn count low.

COMPLETION
Do not claim completion from inspection alone.
Report:
Changed: what changed.
Tests: exact commands and results.
Not changed: relevant out-of-scope items intentionally left alone.
```

This is the default contract for GPT-5.6, Claude Opus 5, and other strong coding agents.
Model-specific tuning should be small.

---

## 60. Task prompts must be complete but lean

Do not write:

> Implement the adjustment pipeline.

Use a bounded task specification:

```text
Task
[One observable result.]

Context
[Only design facts required for this task.]

Inputs
[Exact files, data, or functions already available.]

Expected interface
[Function names or CLI behavior required by later tasks.]

Acceptance criteria
- [Observable condition 1]
- [Observable condition 2]
- [Observable condition 3]

Allowed scope
- [Expected files]
- Small supporting edits required by the acceptance criteria.

Out of scope
- [Specific nearby temptation]
- No unrelated refactoring.

Validation
Run:
- [focused test]
- [relevant lint/type/full checks]

Completion report
Changed: ...
Tests: ...
Not changed: ...
```

A strong model needs a complete task specification.
It does not need the full project document pasted into every task.

---

## 61. GPT-5.6 working rules

Use these defaults when GPT-5.6 is the coding agent or product model.

### Prompt design

- keep project prompts lean;
- state each important rule once;
- define the required outcome;
- define scope and approval boundaries;
- define success criteria;
- expose only tools relevant to the task;
- keep tool descriptions precise;
- preserve examples only when they encode a real product requirement or correct a measured gap.

### Autonomy

Allow safe in-scope local work without repeated confirmation.

The agent may normally:

- read files;
- inspect logs and git state;
- edit requested local code;
- run non-destructive tests and checks.

Require approval for:

- destructive actions;
- external writes;
- deployments;
- purchases;
- material expansion of scope.

### Reasoning effort

Do not assume maximum reasoning is always better.

Start from a sensible baseline and compare effort settings on representative tasks.
Use higher effort only when it produces a measured quality gain that justifies cost and latency.

For the product Analyst and Reviewer, evaluate reasoning settings on real financial cases rather than choosing the maximum setting by default.

### Advanced model capabilities

GPT-5.6 supports more advanced tool and agent workflows.
That does not create a V1 requirement to use them.

Do not add Programmatic Tool Calling, multi-agent orchestration, or complex tool loops unless the current product path needs them.

---

## 62. Claude Opus 5 working rules

Use these defaults when Claude Opus 5 is the coding agent.

### Give the full bounded task up front

Opus 5 is strong at completing multi-file and end-to-end coding tasks when it has the complete task specification.

For this project, that means:

- give one bounded implementation task;
- include all acceptance criteria needed to finish it;
- let it complete normal in-scope work;
- do not feed it one tiny instruction at a time when the task can be safely specified once.

### Constrain scope explicitly

Opus 5 may expand a narrow task if the boundaries are vague.

State the intended scope clearly.

If a better architecture idea appears, the agent should mention it briefly and continue with the requested task unless the current approach cannot work.

### Avoid redundant verification prompts

Opus 5 already self-corrects and verifies normal work well.

Do not add generic instructions such as:

- “double-check everything”;
- “re-verify before responding”;
- “always launch a verifier agent.”

Run the required tests once after implementation.
Repeat or expand verification only when there is a concrete reason.

### Control subagent use

Use subagents only for genuinely independent, sizeable workstreams.

Do not use subagents:

- for a small task;
- to double-check the main agent;
- because subagents are available;
- for several overlapping edits to the same files.

If one agent can finish the task, use one agent.

### Control written deliverable length

When asking Opus 5 to write a document or report, specify the intended length and substance.
Do not encourage filler sections or repeated summaries.

### Effort

Evaluate lower and higher effort settings on representative tasks.
Do not automatically use the most expensive setting for every coding task.

---

## 63. Progress updates should be useful, not constant narration

For long agent tasks:

- one short sentence before work begins is enough;
- update only when an important finding appears or direction changes;
- final response should lead with the outcome;
- avoid narrating every file read, command, or internal correction.

This is especially useful with Opus 5, which otherwise tends to narrate agentic work more heavily.

---

## 64. Code review prompts should seek real issues first

When asking a coding model to review code, do not over-constrain the first pass with wording such as:

> Only report severe issues and be conservative.

That can suppress real findings.

Prefer:

```text
Find concrete correctness, data-integrity, and maintainability issues introduced by this change.
Report supported findings.
Then rank them by severity.
```

For this project, finance/data-integrity bugs are more important than stylistic preferences.

---

## 65. Git is a containment mechanism

Default development flow:

```text
one bounded task
    ↓
one small feature branch
    ↓
one coding agent
    ↓
focused test
    ↓
relevant project checks
    ↓
diff review
    ↓
commit
    ↓
merge
```

Avoid parallel agents against the same files.

Do not allow “while I am here” refactoring.

If a task expected to be small unexpectedly touches roughly more than 5–8 files, treat that as a warning sign.
The agent should explain why the scope expanded before continuing.

The number is not a hard limit.
The principle is local change.

---

## 66. Completion requires executable evidence

A task is not complete because the agent says it is complete.

Completion should include the relevant executable evidence.

Example:

```text
Changed:
- added current-adjustment resolution
- added rejection regression test

Tests:
- uv run pytest tests/financials/test_adjustments.py -q
- 8 passed
- uv run ruff check .
- All checks passed

Not changed:
- no CLI changes
- no LLM changes
```

For integration work, run the relevant CLI command too.

Do not add separate verification agents just to produce more certainty theater.

---

# PART H — EXPLICIT NON-GOALS AND REJECTED APPROACHES

## 67. Explicit V1 non-goals

Do not add these unless the golden MSFT path cannot work without the smallest version of one of them:

- CIQ ingestion;
- CIQ ↔ EDGAR reconciliation;
- cross-company taxonomy;
- semantic line-mapping framework;
- five-year history;
- quarterly model;
- forecasting;
- valuation;
- portfolio construction;
- balance-sheet normalization;
- cash-flow normalization;
- EV-to-equity bridge;
- web application;
- production database;
- ORM;
- event-sourcing framework;
- cryptographic provenance;
- RAG;
- vector database;
- autonomous browsing agents;
- tool-using agent loops;
- specialist tax/SBC/etc. agents;
- generic multi-agent orchestration;
- provider-abstraction framework;
- large benchmark suite;
- arbitrary code-coverage target;
- enterprise software architecture.

These are deferred, not necessarily rejected forever.

A deferred feature returns only when a real need demonstrates its value.

---

## 68. Explicitly rejected architecture patterns

### Domain-heavy object model

Rejected because it hides financial logic behind software structure.

### Large class hierarchies

Rejected because they create unnecessary indirection.

### Generic service/repository/provider layers

Rejected because V1 has no current requirement that justifies them.

### Agent-framework-first architecture

Rejected because the product LLM path is structured inference, not autonomous orchestration.

### Tool-using autonomous agents for adjustment discovery

Rejected for V1 because the hypothesis is financial judgment from bounded evidence.

### Full CIQ/EDGAR reconciliation

Rejected for V1 because it consumed large implementation effort without proving the core idea.

### RAG/vector infrastructure

Rejected until simple retrieval repeatedly fails on real cases.

### Web application

Rejected until terminal review is demonstrably insufficient.

### Database-first design

Rejected because simple files are sufficient for V1.

### Premature cross-company taxonomy

Rejected because MSFT can use source line items.

### Framework-driven code reduction

Rejected when explicit Python is easier to understand.

### Separate manual-adjustment subsystem

Rejected because human and LLM adjustments should use one mechanics path.

### Mutation of reported data

Rejected because reported values must remain independently inspectable.

---

# PART I — CURRENT OPEN ITEMS

## 69. Still pending real-data testing

The following decisions are intentionally not fully fixed.

### Exact materiality thresholds

Metrics are fixed in principle.
Thresholds are not.

Calibrate using real MSFT cases.

### Reviewer evidence scope

Compare full packet vs relevant/cited evidence.
Choose based on eval results.

### First MSFT adjustment case

Choose a clear disclosed or mechanically calculated case first.
Do not start with the hardest judgment-heavy case.

### EdgarTools cross-year behavior

Inspect actual MSFT output before adding mapping logic.

### EdgarTools duplicate-fact behavior

Inspect actual output before adding source-selection logic.

### LLM cache key implementation

Use a simple reliable key based on the relevant filing/evidence/model/prompt inputs.
Do not build a provenance platform.

---

## 70. Decisions that are no longer pending

The original Section 1 left several items open.
They are now resolved.

### Sign convention

Resolved:

```text
preserve EdgarTools source values
adjustment = positive magnitude removed
adjusted = reported - approved adjustments
```

### Storage format

Resolved for V1:

```text
Markdown + JSON + CSV
```

Parquet is not required.

### Human review actions

Resolved:

```text
accept
reject
edit amount
edit period
skip without state change
```

### Adjustment source of truth

Resolved:

```text
adjustment_history.csv
```

### Manual adjustments

Resolved:

> Same mechanics path as LLM adjustments, approved by default subject to hard deterministic checks.

### Reconciliation

Resolved:

- source reconciliation is visible and may be human-acknowledged;
- adjusted reconciliation must pass.

---

# PART J — FINAL PROJECT PRINCIPLES

## 71. Core principles

1. Make one real MSFT path work before broadening scope.
2. Complexity must come from the financial problem, not the software architecture.
3. Open financial reasoning. Closed accounting mechanics.
4. Preserve reported data.
5. Keep adjustments separate from reported data.
6. Use one adjustment engine for both LLM and human adjustments.
7. Keep `adjustment_history.csv` as the adjustment source of truth.
8. Use LLMs for financial judgment.
9. Use Python for deterministic accounting mechanics.
10. Adjust underlying source lines, not calculated subtotals.
11. Recompute subtotals and analytical metrics deterministically.
12. Use EDGAR-reported subtotals as checks where useful.
13. Show source-data problems to the user instead of hiding them.
14. Never create automatic plugs to force reconciliation.
15. Treat adjusted reconciliation failure as a code problem.
16. Keep auto-approval conservative.
17. Preserve cheap structured metadata with future eval value.
18. Keep long evidence and reasoning outside CSVs.
19. Prefer CSV, JSON, and Markdown over infrastructure.
20. Prefer functions and DataFrames over object hierarchies.
21. Pydantic is a boundary tool, not the application architecture.
22. Every major capability must be independently testable.
23. Executable evidence is more important than an agent explanation.
24. Prefer one focused test over speculative abstraction.
25. Prefer one coding agent on one bounded task over several overlapping agents.
26. Give strong coding models complete tasks with explicit scope boundaries.
27. Do not add redundant verifier loops when normal tests already prove the task.
28. Do not confuse model capability with a requirement to use every capability.
29. Do not confuse sophisticated architecture with a working product.
30. When the golden MSFT path works and tests pass, V1 is done.

---

## 72. Immediate implementation direction

Do not start implementation with the LLM orchestration layer.

Start with:

> Inspect and lock the actual MSFT EdgarTools output shape.

Then build and test the deterministic financial path.

The first important proof is:

```text
known reported values
+ known approved adjustment
-> correct adjusted P&L
```

Only then connect evidence retrieval, the Financial Analyst, and the Risk Reviewer.

This order is not because LLMs are secondary to the product.
LLM reasoning is core to the product hypothesis.

The order exists because deterministic mechanics are easier to verify independently and give us a stable system in which to evaluate the models.

---

## 73. Relationship to Section 2

Section 1 defines:

- product objective;
- architecture boundaries;
- accepted and rejected design directions;
- coding-agent rules;
- V1 non-goals.

Section 2 defines:

- exact data flow;
- detailed schemas;
- adjustment-history fields;
- reconciliation files;
- human-review CLI behavior;
- deterministic edge cases;
- test fixtures;
- LLM eval design;
- implementation sequence.

If a detailed implementation question is already answered in Section 2, do not invent a second answer in Section 1.

If the two documents appear to conflict, the newer explicit Section 2 implementation rule controls the implementation, while the product principles in Section 1 still control scope.

---

## 74. External model guidance used for this update

The coding-agent guidance in this document was updated after reviewing the official current guidance available on 2026-08-10 for:

- OpenAI GPT-5.6 model guidance;
- Anthropic Claude Opus 5 prompting guidance.

Relevant principles used here:

- state each important instruction once;
- keep project prompts lean;
- give complete bounded task specifications;
- define safe autonomy and approval boundaries;
- let agents perform normal local edits and tests without unnecessary permission requests;
- constrain narrow task scope explicitly;
- expose only relevant tools;
- avoid redundant self-check and verifier loops;
- use subagents only for genuinely independent sizeable work;
- control document/output length explicitly when needed;
- choose reasoning/effort settings using representative evals instead of assuming the maximum setting is always best.

These model capabilities support the lean architecture.
They do not justify adding more orchestration to V1.

