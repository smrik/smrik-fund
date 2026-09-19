# AI Fund — Evidence-Based Three-Statement DCF
## Build guide for Patrik and AI coding agents

Date: 5 September 2026  
Repository: `smrik/smrik-fund`  
Proposed repository location: `docs/AI_FUND_BUILD_GUIDE.md`  
Status: The product and architecture decisions below were agreed in the design interview. The implementation sequence is a proposed delivery plan. No application implementation, local repository changes, or paid analysis runs were performed when preparing this guide.

## Start here

Build a controlled financial-modeling workflow. Do not build an autonomous computer agent.

The product should prepare a linked three-statement forecast and DCF for MSFT. It should use reported financial data and filing notes, select supported forecasting methods, explain material assumptions, and export a working Excel model. Patrik should spend his review time challenging the financial decisions, not reconstructing the spreadsheet.

The central rule is:

> The application controls the work. Reasoning models make bounded financial judgments. Tested code supplies every executable modeling method and workbook formula.

Read Sections 1–6 for the product contract. Then implement one work package from Section 7. Do not give an agent the entire document and ask it to build everything.

The immediate task is **P0: inspect the real local checkout and establish the implementation baseline**. Do not restart ingestion, migrate a directory, or choose Mog before that inspection.

### How to use the later questions

Each package includes questions to resolve when that package starts. These are implementation choices, not requests to reopen the agreed product. The coding agent must first inspect files, dependencies, and disclosures to answer factual questions. Patrik decides financial policies, acceptable simplifications, and scope changes.

“Proposed default” means a recommendation that has not yet been approved as a financial policy. A package must record the answer to a consequential open question before encoding it. Routine implementation details can be decided by the coding agent within the agreed boundaries.

Keep the live package, completed gates, and remaining decisions in one short status file. Do not create a new architecture document after each session.

---

## 1. What V1 must deliver

### 1.1 Agreed scope

V1 is a personal CLI application for Patrik. A web interface, customer accounts, and commercial deployment are not required.

The first complete company case is MSFT. The Palantir university workbook is a reference for analytical depth and review experience, not a source of unquestionable financial treatments. Passing a second company is a later portability test.

The historical model contains three annual periods, current and comparative year-to-date periods where relevant, TTM flows, and the latest included balance sheet. Forecasts are annual. An unfinished fiscal year has a separate forecast remainder. Do not build a long quarterly forecast.

The forecast includes all three financial statements. The agreed direction is five detailed annual forecast years, plus a transition toward terminal assumptions when required, with ten years as the default total horizon. Proposed period-counting default: treat a partial current year as a separate stub, followed by the full fiscal forecast years. Confirm that convention and lock exact year labels in P2; lock discount dates in P9. The statements remain linked during the transition years, even when their methods become more aggregated.

The system prepares a first pass without asking Patrik to supply every modeling judgment. This autonomy is implemented through scheduled, bounded reasoning tasks, not model control of the computer.

Filings are the main evidence source. A small external-input step is allowed for dated valuation inputs. Paid financial databases are not a prerequisite. Supplied exports may be used where their interpretation is clear, but a broad CapIQ-to-EDGAR reconciliation system is not part of V1.

The Excel export contains working formulas. Designated assumptions can be changed locally and the workbook recalculates. Local Excel changes do not synchronize to the application.

Material decisions, evidence, uncertainty, and unresolved issues must be reviewable inside Excel. Short cell notes lead to fuller decision and evidence records.

A €5 budget is the provisional authorized limit for an initial product analysis. A substantial bounded run, rather than an instant response, is acceptable; roughly an hour was the proposed pilot tolerance, not a measured runtime guarantee. The €5 limit is not a demonstrated cost estimate. The architecture and measured usage determine whether it is sufficient. Exhaustion produces an incomplete result and a resumable checkpoint, not a weaker analysis labelled complete.

### 1.2 What counts as complete

V1 is complete only when a frozen real MSFT case can move through source ingestion, historical reconstruction, filing research, method selection, linked forecasts, valuation, review, Excel export, and a reviewer-requested revision.

The result must meet four separate standards:

1. **Mechanical correctness.** Required statements and schedules reconcile within documented tolerances. Formula errors and invalid references do not pass.
2. **Evidence integrity.** Material sourced inputs are traceable. Estimates are not represented as disclosures. Source identity, periods, units, and relevant context are preserved.
3. **Analytical coverage.** Every required financial area has an explicit outcome. The final reviewer examines the combined business and cash-flow story.
4. **Useful review.** Patrik can inspect a material assumption, find its support and weakness, change a designated input in Excel, and request an authoritative revision through the CLI.

A forecast can be ready for review while containing explicit estimates. A material unresolved historical error, unsupported accounting treatment, unimplemented required method, missing mandatory review, or exhausted budget prevents an unqualified completion label.

A working normalization loop, an attractive workbook, a successful API call, and a balanced balance sheet are each insufficient on their own.

### 1.3 Explicit non-goals

Do not implement bidirectional Excel synchronization, a universal company taxonomy, automatic securities trading, portfolio construction, a treasury optimizer, an enterprise data platform, a general model-building language, or an unrestricted web-research agent.

Do not introduce agent swarms, runtime-generated code, a vector database, a generic workflow engine, or several interchangeable calculation engines without a demonstrated blocker in this scope.

---

## 2. Precedence and the existing project

This guide records a changed product boundary. It must not be combined indiscriminately with older V1 specifications.

| Earlier rule | Agreed rule for this build |
|---|---|
| V1 ends with an adjusted historical P&L. | V1 ends with a complete three-statement DCF and reviewable Excel output. |
| Quarterly information and forecasting are deferred. | Interim filings support YTD/TTM history and a forecast stub. The forward model is annual. |
| Every financial calculation must run directly in Python. | Python owns application control and source/decision state. One code-defined set of model formulas is evaluated by the selected spreadsheet engine and exported to Excel. |
| Excel is optional or only a values report. | A formula-linked, locally editable Excel export is required. |
| The analyst can propose normalization candidates only. | A bounded task can propose detail, a treatment, a supported method, an explanation, an evidence request, or an unresolved issue. |
| Rejecting the latest version removes the previous approval. | Rejecting a proposed replacement does not revoke the currently approved decision. Withdrawal is explicit. |
| A model may invent executable schedule logic. | The model selects and configures implemented methods. Arbitrary code and arbitrary Excel formulas are prohibited at runtime. |

The August documents remain useful for their emphasis on immutable source data, simple functions, inspectable storage, independent tests, and bounded coding work. Their old completion boundary does not govern this expanded product. [S1]

The September 5 review adds useful concepts: question-led research, current-model context, durable reported detail, aggregate-versus-component discipline, and validation before application. Its historical-only milestone and broader model-directed sequencing are not the final scope or control model agreed here. [S2]

### What was actually checked for this guide

The GitHub copy of `docs/V1_STATUS.md` still describes the older P&L-only scope and is dated 30 August 2026. The fetched `pyproject.toml` declares Python `>=3.13` and the console command `smrik-fund`. Do not downgrade Python to 3.12 or rename the command because an older design sketch used those names. Check the local lockfile and environment first. [S3]

The supplied September review describes a later dirty local checkout. Its findings are evidence about that reviewed checkout, not proof of the current GitHub code or proof that a listed defect still exists. P0 must distinguish checked-in code, uncommitted local work, source observations, and planned behavior. [S2]

Public Mog documentation describes a headless spreadsheet SDK and Excel export. Mog is a candidate, not a selected or tested dependency for this project. The public ShortcutXL integration skill is not the same as the complete installed financial-modeling skills directory. This guide does not claim that the local directory was inspected. [S4, S5]

Do not overwrite old specifications or financial artifacts automatically. P0 proposes the minimum documentation changes needed to establish this guide as the product direction. Repository safety instructions remain in force.

---

## 3. The architecture

### 3.1 The application owns the workflow

```text
Analysis brief, source cut-off, and budget
    -> Fetch and freeze permitted source references
    -> Build comparable historical periods and statement views
    -> Run mechanical checks and establish financial coverage
    -> Build or update the provisional model
    -> Execute the next permitted financial reasoning task
         -> provide relevant current-model context and evidence
         -> receive a structured decision or evidence request
         -> retrieve additional permitted evidence if required
         -> validate the final proposal
         -> review consequential judgments
    -> Apply supported decisions to a candidate model
    -> Build formulas using tested methods
    -> Calculate, reconcile, and run sensitivities
    -> Perform final whole-model analytical review
    -> Publish a versioned Excel workbook and run record
```

Implement this as visible Python control flow. A small task list and a few explicit task states are enough. Do not build a declarative orchestration language.

The application determines prerequisites and scheduling. A task can suggest a related question. That suggestion becomes a proposal for the permitted work queue; it does not give the model authority to run arbitrary tools or change unrelated model areas.

### 3.2 Three different responsibilities

| Responsibility | Owner | Allowed work |
|---|---|---|
| Application and accounting mechanics | Tested application code | Fetching, period arithmetic, identity checks, history, method execution, formula generation, calculation, reconciliation, budgets, exports. |
| Financial judgment | Bounded reasoning calls | Interpret disclosures, identify components, select allowed methods, propose assumptions, explain alternatives, request evidence, challenge material decisions. |
| New software capability | Coding agent during development | Implement a missing method or feature under a separate approved task, with tests and code review. |

The runtime analyst must not receive shell access, unrestricted filesystem access, application-editing tools, or direct Excel/Mog mutation tools. The application executes known retrieval and model-building functions on its behalf.

Treat filing text, uploaded documents, and retrieved skill text as data or reference material, not authority to change these permissions. Delimit source excerpts in prompts. Validate all model-selected identifiers against the current case and permitted methods. Write labels, notes, and excerpts as literal spreadsheet text, including strings that begin with formula-like characters; only application-generated formula fields are executable.

“Small task” means a bounded financial responsibility, not one API call per cell. A depreciation task can receive capex, assets, revenue context, and the relevant policies. It cannot modify the revenue forecast just because it sees a possible improvement.

### 3.3 Tested methods, not model-written formulas

Use a small explicit mapping from method IDs to implemented functions. Examples might include segment growth, receivable days, straight-line asset depreciation, a debt roll-forward, or a forecast transition. These are proposed names, not existing repository APIs.

A method specifies required inputs, units, period behavior, supported parameters, outputs, statement connections, and checks. Its executable formulas are authored in application code.

A runtime proposal contains an allowed method ID, existing input references, categories, parameters, evidence references, and rationale. It cannot contain a Python expression, JavaScript expression, arbitrary spreadsheet formula, shell command, executable path, or method implementation.

Descriptive reasoning may discuss an equation. That text is not executable. The application never evaluates it.

When a method is missing, return a capability gap with its financial consequence. Do not silently replace a necessary asset schedule with a revenue ratio. A simpler implemented method can be proposed openly, with its limitations and the required review.

Avoid creating an abstract syntax tree, generic formula interpreter, or plugin platform. A handful of normal functions with explicit configuration is the starting point.

### 3.4 One authoritative set of model formulas

The stored source snapshot, effective decisions, configuration, and versioned method code must reproduce the workbook. The workbook is not the only place where the model exists.

The methods generate workbook formulas. A selected engine evaluates those formulas. The export carries the same formulas into Excel. Do not maintain a second full valuation engine in Python and try to keep it synchronized manually.

Python can still calculate historical transformations, validation statistics, cost estimates, and independent expected answers for small test fixtures. This is not a duplicate financial model.

Use a simple cell map to connect stable financial IDs to generated workbook ranges. Do not make an LLM reason about column letters or repair broken addresses. Changing presentation must not change the identity of an assumption or decision.

If Mog passes P1, a small application-owned Node runner can call its SDK. That runner is trusted development code, not code generated by a model during an analysis. Use only the operations required by the chosen methods. No generic provider architecture is needed. [S4]

### 3.5 Model-building is staged and recoverable

Create candidate outputs separately from the last published model. Apply a decision bundle, calculate, validate, and save the candidate before changing the pointer to the current model.

A failed calculation, invalid proposal, interrupted run, or failed export must leave the previous valid version available. Only one process may publish to a company model at a time; a simple local lock and an expected prior-version check are sufficient for V1. Use ordinary temporary files, immutable run records, and one atomic pointer replacement where the filesystem supports it. A database or event-sourcing framework is unnecessary for a single user.

Mog's CLI guidance says that an execution can leave earlier mutations in a live handle after an error. Do not treat an engine call as an application transaction. Rebuild or discard the candidate rather than continuing from uncertain partial state. [S4]

---

## 4. Minimum data and decision contracts

These are logical records, not instructions to create a class or module for every row. Final field names should reuse valid existing contracts where practical.

### 4.1 Analysis brief

Store company identity, objective, source cut-off, financial measurement date, valuation date, reporting currency, display units, historical periods, forecast periods, permitted sources, required financial areas, budget, and selected versions.

Keep the dates separate. A quarter-end balance sheet is not a balance sheet dated on the later filing publication date. A model using information published after its valuation date is not a point-in-time backtest.

### 4.2 Source and financial input

Preserve filing accession, form, publication timestamp when available, period start/end or instant date, original source concept and label, value, unit, scale, dimensions, and locator. Preserve raw extracts separately from analytical views.

A source selector must account for restatements, recast segments, filing amendments, dimensions, and overlapping period facts. Select a consistent basis and keep the alternatives visible. Do not average conflicting source values.

Missing, zero, not applicable, and estimated are different states. Each method must define whether its inputs are complete enough to calculate. Do not let a spreadsheet `SUM` hide a required missing component by ignoring an empty cell.

### 4.3 Evidence item

Store a stable ID that includes or resolves to packet identity, source identity, exact locator, relevant excerpt, table headings, units, periods, and nearby qualifications.

An `E1` in one packet is not the `E1` in another packet. Model-written summaries are interpretations, not replacement source excerpts. A valid locator proves the source exists; it does not prove that the excerpt supports the selected treatment.

### 4.4 Financial question

Store question ID, financial area, objective, relevant model slice, prerequisite decisions, status, evidence requests, evidence already seen, calls used, cost, outcome, and unresolved reason.

Proposed outcomes: `propose_detail`, `propose_treatment`, `propose_forecast`, `explained_no_change`, `unresolved`, and `capability_gap`. `request_evidence` continues a task; it is not a completed conclusion.

A factual explanation without a model change can be successful work. No task should be rewarded merely for adding an adjustment or a row. [S2]

### 4.5 Decision and method configuration

Store stable decision ID and version, affected schedule or input IDs, selected method/version, parameters or assumption references, evidence references, short rationale, alternatives, uncertainty, evidence strength, judgment level, reviewer outcome, and authority.

Keep these distinctions separate:

- Basis: disclosed, calculated, estimated, or unknown.
- Authority: system proposal, system-reviewed provisional decision, or human-approved decision.
- Applicability: current or needs reassessment because the source/model context changed.
- Effectiveness: included in the selected model version or not included.

The initial model can use validated, system-reviewed provisional assumptions. That must not be presented as human approval. Patrik's approved decisions take precedence until explicitly replaced or withdrawn.

A model's explanation is a concise financial justification. Do not request hidden internal reasoning traces.

### 4.6 Effective decisions and history

Preserve proposals, revisions, reviews, and human actions without overwriting prior records.

For the same decision identity, a proposed or rejected replacement does not erase the currently effective approved version. An approved and validated replacement supersedes it. An explicit withdrawal ends its effect.

New source data can make a decision stale. Preserve the old version for its original source snapshot, flag reassessment for the new snapshot, and prevent a new model from silently presenting it as freshly validated.

Separate proposal status from the selection of effective decisions in a published model. Do not implement this by taking the latest row and filtering for `approved`. Migration tests must specifically protect this rule.

### 4.7 Check and run manifest

A check records scope, period, expected and observed values, difference, tolerance, status, and consequence. Distinguish PASS, FAIL, NOT_TESTED, and NOT_APPLICABLE. Record reasons for the last two.

A manifest records the brief, input references, source and decision versions, code version and dirty status, method versions, calculation-engine version, prompts, runtime models, call usage, outputs, checks, coverage, and review state.

Use small JSON records for structured decisions, CSV for financial tables/checks, and Markdown for longer evidence or explanations. Reuse existing caches. Save immutable manifests and changed decisions rather than copying every raw filing into every run folder.

### 4.8 Coverage and completion

Coverage outcomes should include supported model, explicit estimate, explained without extra detail, justified not-applicable, unresolved, and not investigated.

Use separate run fields for execution completion, mechanical validity, analytical review, and human approval. Derive any summary label from them. A run can be mechanically valid but analytically incomplete; a reviewed forecast can contain uncertain assumptions without being mechanically invalid.

“Not found,” “not disclosed,” and “does not exist” are not interchangeable. When a search finds nothing, record what was searched and the limit of the conclusion.

---

## 5. Required financial coverage

This is the initial coverage specification, not a requirement for a separate tab or API call for every item. Details and financial policies must be selected from the actual case. Unsupported granularity is not a success criterion.

| Area | Minimum model requirement | Main failure to prevent |
|---|---|---|
| Revenue | Comparable disclosed segment history, segment-level forecast, drivers or explicit growth assumptions, and reconciliation to consolidated revenue. | Invented product economics, overlapping segment totals, or unsupported customer/volume detail. |
| Operating costs | Forecast methods for material cost lines, links to D&A and SBC where applicable, and a visible margin explanation. | Subtracting D&A or SBC twice when already included in an expense forecast. |
| PP&E and capex | Opening assets, supported categories, additions, depreciation, disposals/other movements, and cash-investment bridge. | Treating all asset additions as cash capex; inventing an asset-age profile. |
| Intangibles | Separate identifiable amortizing assets, relevant additions/amortization, and goodwill treatment. | Forecasting all noncash charges as one percentage or routinely amortizing goodwill without a valid basis. |
| Working capital | Relevant operating balances and drivers, including receivables, payables, deferred revenue, and other material operating balances. | One unexplained net working-capital percentage; double-counting cash movements. |
| Taxes | Book tax, deferred/current tax where material, tax balances, cash-tax bridge, and an operating-tax treatment for UFCF. | Using reported effective tax as cash tax without explanation or double-counting tax balances in working capital. |
| Debt and interest | Opening debt, maturity/cash movements, assumptions on refinancing, interest, and current/noncurrent presentation. | Debt inserted as an unexplained balancing number or a hidden interest/cash circularity. |
| Leases | Consistent treatment of lease balances, additions, expense, payments, cash-flow classification, and valuation. | Counting a lease obligation or cash cost twice. |
| SBC and equity | SBC expense/CFO/equity links; share issuance and repurchases; retained earnings; explicit dilution and valuation policy. | Treating SBC as economically free or charging the same future award twice through inconsistent valuation methods. |
| Non-operating items | Classification of cash, investments and other material items; income treatment; enterprise-to-equity bridge. | Removing investment income and then forgetting the related asset value, or adding an asset twice. |
| Cash flow and cash | Indirect CFO, investing and financing flows, FX/restricted-cash bridge where applicable, and opening-to-closing cash. | Defining cash as “the amount needed to balance” rather than the result of modeled cash flows. |
| DCF and terminal | Unlevered operating cash flow, discount dates, WACC inputs, transition assumptions, terminal reinvestment, and equity bridge. | Discounting historical cash flows, inconsistent terminal economics, or counting financing flows in UFCF. |

### Financial method safeguards

Use actual reported balances as the starting point. Analytical normalization does not erase historical cash payments, liabilities, assets, or equity.

Keep reported composition separate from normalization bridges. Adding a disclosed child does not change its parent. Alternative breakdowns, such as geography and product, are not additive to each other. An arithmetic unallocated balance can be shown only within a compatible scope; it is a coverage diagnostic, not evidence for an invented forecast driver. [S2]

A three-statement forecast needs a complete treatment of opening balances. Material lines require an explicit schedule or policy. Small residual categories may use an explicit aggregate method with an explanation; they may not be an unexplained balancing plug.

Use a signed adjustment effect derived from validated economic direction and source convention. Do not apply an indiscriminate “subtract a positive number” rule to every signed net line. Preserve existing tested sign mechanics when they implement this correctly; migration is a bounded task, not a new sign framework by default.

For required judgments that remain uncertain, use a visible assumption and a sensitivity where useful. A simplification is acceptable only when its financial consequences are explained. A technically balanced model does not establish that its economic assumptions are sound.

---

## 6. How bounded reasoning should work

### 6.1 One task cycle

1. The workflow checks prerequisites and builds the task's current-model slice.
2. Deterministic retrieval obtains the first relevant filing context. A bounded query-planning call can be used where needed; do not force an LLM call for a known source location.
3. The reasoning model receives the question, source context, applicable prior decisions, implemented method options, and output schema.
4. It returns a proposal, explanation, explicit gap, or bounded evidence request.
5. The application validates requests and executes permitted searches or note expansions. It can refuse irrelevant requests and record why.
6. Once a final proposal exists, run schema, source, method, period, dependency, and mechanical checks. Review consequential financial judgments separately.
7. Build a candidate, calculate the effects, and record what changed. Only then make the candidate effective in the applicable model version.

Proposed pilot bounds: up to three literal phrases per search request, an initial retrieval plus up to two follow-ups per question, and one reviewer-requested revision with one re-check. These are operating defaults to measure, not an excuse to truncate an unresolved inquiry and mark it complete.

An unchanged value does not imply no progress. Stop a question when it reaches a supported outcome, exhausts relevant available evidence, repeats without new information, hits its bound, or requires a capability outside the method library. State which happened.

### 6.2 Native structured outputs

Use the installed official SDK and native schema support where available. Validate the returned business meaning after validating its shape. Native Structured Outputs can enforce response structure; they do not establish financial truth. Handle refusal, incomplete output, unsupported methods, and API failure explicitly. [S6]

Do not hard-code a runtime model name or reasoning setting from an old document. At the paid pilot gate, verify availability and pricing for the account and record the actual choice. Compare quality on the same frozen task before optimizing cost.

### 6.3 Cross-schedule reasoning

A task receives related facts without gaining control of every related schedule. A proposed revenue change can invalidate the context of capex, working-capital, and tax decisions. Numeric propagation and reasoning reassessment are separate operations.

Use declared schedule dependencies to identify potentially stale decisions. Recalculate formulas deterministically. Re-run only reasoning tasks whose justification may have changed. A pure presentation edit should trigger neither financial re-reasoning nor paid calls.

### 6.4 Review and publication

Use deterministic checks throughout, targeted financial review of consequential decisions, and a final whole-model review. The final reviewer receives a calculated model summary, key schedules, assumption records, source caveats, coverage gaps, and sensitivities. It must not see only the analyst's persuasive explanation.

The review should challenge consistency between growth, cost structure, investment, funding, taxes, and terminal conditions. It should also challenge unsupported “not applicable” conclusions.

Schema failure, wrong source period, unavailable required input, and invalid accounting mechanics are not merely low-confidence judgments. They require a repair or an explicit blocked scope.

A financial disagreement can remain visible for Patrik. It cannot be resolved automatically in favor of the answer that allows the run to finish.

---

## 7. Implementation work packages

Implement these serially by default. A package may need several coding sessions. Split by a tested behavior, not by arbitrary file count. Each session has one observable result and a stopping point.

```text
P0 Baseline and scope
 -> P1 Calculation/export proof
 -> P2 Sources and periods
 -> P3 Historical interpretation and decision state
 -> P4 Small complete deterministic model
 -> P5 First evidence-to-forecast reasoning slice
 -> P6 Revenue and operating costs
 -> P7 Working capital
 -> P8 Remaining statements and material policies
 -> P9 Full integration and valuation
 -> P10 Full controlled workflow and review
 -> P11 Excel review and authoritative revisions
 -> P12 Live acceptance and cost calibration
```

Evidence records begin in P2. Basic notes begin in P1/P4. Cost controls exist before P5 makes a paid call. Do not postpone these foundations until their final polish packages.

### P0 — Inspect the checkout and establish the baseline

**Outcome:** a reliable map of what exists, what is defective, what can be reused, and which next change is permitted.

**Steps**

1. Read `AGENTS.md`, the active design/status files, `pyproject.toml`, lockfiles, current commands, and relevant tests. Inspect branch, commit, and dirty files before running anything that writes outputs.
2. Trace the real ingestion, period handling, filing retrieval, adjustment application, effective-state resolver, export, and evaluation paths. Do not infer implementation status from a checklist.
3. Compare the September review's claimed defects with the current local code. Confirm or reject each claim with exact function/test evidence. Focus on disputed revisions, aggregate/component identity, reported detail persistence, and rejected replacements.
4. Inspect the user's installed ShortcutXL skill directory if accessible in that coding environment. Record relevant methodology and mechanics, package version, and license conditions. Do not launch an autonomous ShortcutXL run or copy its permissions-bypass instructions into this product.
5. Produce a short reuse/fix/defer table. Identify the existing eval harness; do not plan a replacement unless it is demonstrably unusable.
6. Propose the minimum scope/status update. Preserve old documents as historical context and make the new completion boundary explicit when authorized.

**Deliverable:** a baseline note in the existing status/planning area. Reuse that area rather than creating another report hierarchy.

**Pass conditions:** local versus remote differences are identified; current interfaces and test commands are observed; proposed next files are named; no production edits, financial-data changes, paid calls, destructive Git actions, or dependency upgrades occur in this inspection task.

**Questions at this stage:** Does any uncommitted work belong to another unfinished task? Which confirmed defects must be repaired before reuse? Should the new path coexist with the old command during migration? Proposed default: preserve old behavior until the new path is demonstrated, then consolidate deliberately.

### P1 — Prove the spreadsheet calculation and export route

**Outcome:** select one engine using a tiny real compatibility test rather than a feature list.

**Steps**

1. Define the narrow acceptance fixture before installing or adopting an engine: a few linked sheets, editable assumptions, depreciation, tax, cash, a balance-sheet check, a small DCF, a note, and a decision hyperlink.
2. Evaluate Mog first because it is the identified candidate. Verify the installed/pinned package's actual API. Use application-written code only. Do not create an agent operating Mog.
3. Build and calculate the fixture; export to `.xlsx`; open and fully recalculate it in the Excel environment Patrik will use.
4. Change a key assumption in Excel. Verify downstream formulas, notes, internal links, number formats, and cached/exported values. Compare critical figures with independent small expected calculations.
5. Inject a broken reference and interrupt a candidate build. Confirm the error is detected and the prior published fixture survives.
6. Record limitations and select the engine. If a required feature fails, stop for a narrow alternative assessment. Do not silently switch to values-only export or implement several adapters in parallel.

**Deliverable:** one small compatibility fixture, a focused test/script, and a short recorded engine decision. No production valuation yet.

**Pass conditions:** formulas survive export; actual Excel recalculation agrees within defined tolerances; notes and links survive; failures are detectable; the runner needs no runtime-generated code. Reading XLSX cached values alone is not a recalculation test.

**Questions at this stage:** Which Excel installation is the acceptance environment? Can its recalculation check be automated locally, or will Patrik perform this one manual check? Does Mog meet every mandatory requirement? These are environment observations first, not guesses or product questions.

### P2 — Freeze the case and construct correct historical periods

**Outcome:** traceable annual, YTD, TTM, and opening-balance data.

**Steps**

1. Select a source cut-off and enumerate filings available by that cut-off. For the TTM acceptance fixture, choose a real historical cut-off where an interim filing is the latest reporting update. Normal runtime selection should still use the latest qualified reporting data for the requested cut-off.
2. Inspect EdgarTools' real statements and metadata. Use existing/native retrieval and caching where they meet the requirement. Fetch enough earlier filings to obtain the required balance-sheet snapshots and comparative periods. [S7]
3. Preserve the original data and create a small source-to-model mapping for actual required lines. No universal taxonomy. Ambiguous line interpretation can be routed to a bounded review; it is not silently guessed by a label match.
4. Build the additive-flow transformation `TTM = latest full FY + current YTD - prior comparable YTD` only for compatible scopes, units, periods, and definitions. Independently check against four non-overlapping quarters where those are available.
5. Use the latest included balance sheet as an instant snapshot. Do not “TTM” it. Do not add EPS, margins, growth rates, or weighted-average share counts as though they were monetary flows. Reconstruct such measures from their proper components or omit them with an explanation.
6. Record source-selection decisions for restatements, amendments, dimensional facts, and recast segments. Preserve earlier-as-filed values when relevant to an as-of case.
7. Build first evidence records with note context and locators. Run historical statement, cash, and period checks.

**Deliverable:** frozen source manifest; historical statement tables; period table; source/check records; a basic historical Excel view.

**Pass conditions:** sources can be traced; annual/YTD/TTM identities tie where valid; no duplicate periods; latest cash reconciles to the correct cash-flow definition; missing facts do not become zeros; no data published after the information cut-off enters silently.

**Questions at this stage:** What exact case dates exercise the TTM requirement? Are segment histories restated on a comparable basis? How will reporting date, information cut-off, and valuation date differ? Proposed default: use a frozen case rather than a moving “today”; choose and document the dating convention before P9. Do not label a later-information valuation as a historical backtest.

### P3 — Make historical interpretation and effective state safe

**Outcome:** historical detail and analytical treatments survive rebuilds without changing reported facts or corrupting prior approvals.

**Steps**

1. Implement or repair the minimum decision/evidence records. Reuse valid existing schemas and append-style history where possible.
2. Keep reported composition, analytical normalization, operating/non-operating classification, and forecast assumptions distinct. Do not put descriptive information into zero-value adjustment rows.
3. Repair confirmed final-proposal application defects. A reviewer revision must produce a revised proposal and re-check; it cannot approve the original disputed amount by shortcut. [S2]
4. Implement the agreed effective-state semantics with explicit replacement and withdrawal. Test legacy migration before changing the resolver.
5. Validate candidate history, source references, scopes, signs, overlaps, and affected accounting checks before publishing the new version.
6. Preserve a disclosed recurring component in durable detail input. Rebuild it without changing the parent total. Keep overlapping breakdown groups separate.

**Deliverable:** a safe decision/history path and a useful reported-to-analytical bridge.

**Pass conditions:** a rejected replacement leaves the prior approval effective; a failed revision leaves history/current output unchanged; an approved replacement applies once; adding detail does not inflate totals; new-source decisions are flagged for reassessment; an aggregate disclosure cannot be booked as an unsupported component.

**Questions at this stage:** Which existing records can be migrated without losing meaning? Which old `rejected` rows meant proposal rejection versus withdrawal? When that cannot be inferred, preserve ambiguity and ask Patrik rather than rewriting financial history. Which financial normalization policy applies to the first historical cases? Recurrence and source reliability alone do not settle eligibility.

### P4 — Build a small complete model without any LLM

**Outcome:** one linked three-statement DCF on clearly labelled fictional data.

**Steps**

1. Create a compact fixture with opening balance sheet, one short forecast stub if needed, annual revenue/cost assumptions, working capital, PP&E/depreciation, debt/interest, tax, equity, and cash.
2. Implement only the tested methods required for this fixture. Generate formulas from code. Use simple provisional fixture policies, not implied MSFT recommendations.
3. Build income statement, balance sheet, and indirect cash flow from shared schedules. Cash comes from cash flows; equity comes from its movements. Neither is an unexplained plug.
4. Build a simple UFCF bridge, DCF, terminal calculation, and enterprise-to-equity bridge. Keep policy assumptions visible.
5. Add input cells, short notes, an assumptions/decisions sheet, and checks. Exercise both application rebuilds and Excel-only input edits.
6. Add small independent expected-value tests and intentionally broken cases. Avoid a second complete Python implementation of the same model.

**Deliverable:** a small but complete reproducible workbook and its tested method functions.

**Pass conditions:** all forecast years balance; cash-flow and balance-sheet cash agree; expected input changes propagate; invalid references/periods fail; no LLM is needed to reproduce the calculations.

**Questions at this stage:** Which non-circular interest convention should the fixture use? Proposed default: opening-balance interest with any dated material financing movements handled explicitly. Which residual historical categories need explicit policies before moving to real data? Which fixture checks will later become production checks? Confirm per-step execution timeouts so a stalled engine or external call cannot run indefinitely.

This package proves the mechanics and gives Patrik a tangible workbook early. It does not prove real financial research, forecast quality, or V1 completion.

### P5 — Prove one real evidence-to-forecast reasoning task

**Outcome:** the first useful financial-reasoning slice, from filing evidence to an editable forecast schedule and valuation effect.

**Recommended first area:** capex and depreciation. It tests disclosure interpretation, assumptions, linked balances, cash effects, and economic sensitivity without requiring the whole company analysis to be solved at once.

**Steps**

1. Inspect the real case's asset, useful-life, investment, cash-spend, and relevant lease disclosures. Define the financial question before choosing a desired answer.
2. Implement the specific supported asset methods the case needs. Separate opening assets from forecast additions. Do not infer a precise remaining-life profile from a net asset balance without evidence.
3. Prepare one manually inspected evidence packet and fixed expected checks. This is a test baseline, not a hand-authored answer hidden in the analyst prompt.
4. Add budget admission, usage recording, input hashing, and resumable task records before the first paid call.
5. Run a bounded analyst task that selects implemented methods, proposes categories and assumptions, explains limitations, and can request a follow-up note expansion.
6. Review consequential decisions, build the candidate schedule, link it to the provisional statements and DCF, and show sensitivities.
7. Ask for one targeted revision and demonstrate the stored decision, schedule, numbers, and explanation all change consistently.

**Deliverable:** a real, sourced schedule with an auditable decision record and a measured call cost.

**Pass conditions:** at least one evidence-directed follow-up is tested where needed; source facts and estimates remain distinguishable; the runtime emits no executable logic; cash additions and noncash additions are not conflated; unsupported detail stays explicit; the reviewer can challenge a life or investment assumption without rebuilding the schedule manually.

**Questions at this stage:** Which asset categories are truly supported? What proxy is acceptable for opening-asset depreciation when ages are missing? Can an aggregate method represent the economics adequately, or is a new tested method required? Does the reasoning task deliver enough depth at its measured cost?

**Stop/go gate:** inspect the actual output before adding more reasoning tasks. If this slice is shallow, fix retrieval, task scope, method capability, or review. Do not respond by adding more agents.

### P6 — Add segment revenue and operating-cost forecasts

**Outcome:** a reconciled, evidence-informed operating forecast.

**Steps**

1. Build comparable disclosed segment histories. Separate alternative segment/geographic/product views and document recasts or scope changes.
2. Offer a short list of implemented methods suited to actual disclosures. Use volume/price or customer-based methods only when the required definitions and inputs exist. Segment growth assumptions are allowed when honestly labeled and reasoned.
3. Run bounded method/assumption selection tasks. Require a proposed trajectory, support, economic interpretation, and meaningful downside/upside variation for material drivers.
4. Forecast material operating costs. Identify which lines already include depreciation, amortization, and SBC. Link schedules without adding those expenses twice.
5. Reconcile segment totals and any corporate/elimination items to consolidated figures. Send cross-schedule implications to the application for scheduled reassessment.

**Deliverable:** segment forecast and operating P&L schedules connected to the existing model.

**Pass conditions:** segment totals reconcile; no invented operating statistics; margins are explained by modeled inputs rather than overridden as a second answer; embedded D&A/SBC is not duplicated; a revenue revision changes its declared dependants.

**Questions at this stage:** What is the narrowest useful revenue breakdown? How should unsupported segment cost allocations be treated? Proposed default: retain aggregate costs rather than manufacture segment margins. Which management statements are usable as assumptions rather than facts about the future?

### P7 — Add working-capital balances and cash conversion

**Outcome:** a balance-based operating working-capital schedule connected to the statements and UFCF.

**Steps**

1. Classify relevant operating balances. Keep debt, cash, and separately modeled tax/lease/investment items out of overlapping working-capital definitions.
2. Reconcile historical changes to cash-flow disclosures where possible. Distinguish acquisitions, FX, write-offs, reclassifications, and other noncash movements from operating cash movements.
3. Implement appropriate methods for receivables, payables, inventory if material, deferred revenue, contract balances, and other material categories.
4. State denominator and timing definitions. A payable-days method based on cost of sales rather than credit purchases is a proxy and must be labeled. Deferred revenue requires an explicit billing/recognition assumption, not a generic liability-growth rule disguised as evidence.
5. Model the forecast stub using compatible periods and stated seasonality assumptions. Do not multiply annualized ratios by the wrong period length.
6. Connect balance movements once to CFO and the operating cash-flow bridge. Test increases/decreases and negative operating working capital without blanket invalidation.

**Deliverable:** historical and forecast working-capital schedules with explanations and checks.

**Pass conditions:** opening-to-closing balances link; cash-flow signs are correct; unknown noncash movements are not silently classified as operating cash; current tax/lease items are not counted twice; sales revisions propagate to the intended balances.

**Questions at this stage:** Which balances materially affect cash conversion? Do billing or seasonality disclosures justify a more specific method? What remaining historical bridge difference is attributable and what is unresolved? No unsupported residual becomes a balancing cash flow.

### P8 — Complete taxes, financing, equity, and other material balances

**Outcome:** every material opening balance and forecast flow has a defined treatment.

Do not give this entire package to one agent as one coding task. Complete the following packets serially, with explicit financial policy decisions before implementation.

#### P8A — Taxes

Separate book tax expense, current/deferred tax effects, cash taxes, and the operating tax measure used for UFCF. Reconcile their connections to the actual relevant balance-sheet accounts. Preserve unusual historical tax items without automatically excluding recurring items.

**Pass:** the tax expense/cash/balance bridge reconciles; financing tax effects are not imported incorrectly into operating UFCF; no tax movement is also counted in working capital.

**Questions:** Is a simplified effective-rate/current-tax method adequate for this case? Are loss carryforwards, uncertain tax positions, or deferred tax movements material enough to require a specific schedule? What supported assumptions govern their use or settlement? Do not implement broad jurisdictional tax planning.

#### P8B — Debt, leases, and funding

Model disclosed debt obligations and assumed financing movements. Choose an explicit non-circular interest convention. For leases, agree the accounting and valuation policy as a bundle: balances, noncash additions, expense, cash payments, and whether/how obligations enter the equity bridge.

**Pass:** liability roll-forwards tie; cash payments and noncash additions stay separate; no circularity is hidden by spreadsheet iteration settings; an unfunded cash shortfall remains visible unless an explicit financing policy applies.

**Questions:** What refinancing policy is acceptable? How are operating and finance leases handled consistently in UFCF and the equity bridge? Do not select a lease policy merely because it balances the model more easily.

#### P8C — SBC, share counts, and equity

Connect SBC expense, the noncash CFO reconciliation, and equity movements. Model share issuance/repurchases through declared policies. Reconcile retained earnings and other equity movements. Distinguish point-in-time shares, weighted-average shares for EPS, and potential dilution.

Choose one coherent valuation policy for future compensation and dilution. Distinguish existing outstanding awards from future awards. Do not blindly combine an economic expense deduction with a second charge for the same future compensation, and do not treat an accounting noncash add-back as proof that compensation has no economic cost.

**Pass:** statement accounting is correct; EPS uses an appropriate denominator; the equity bridge and per-share value use the selected consistent policy; repurchases cannot create value merely through a mechanical double count of cash and share reduction.

**Questions:** How will future SBC's economic cost enter valuation? How will existing awards be treated? What price assumption is used when converting repurchase cash into shares, and does it create a circular dependency? These are mandatory financial decisions, not developer defaults.

#### P8D — Investments, intangibles, goodwill, and residual balances

Complete material non-operating assets and income, intangibles, goodwill, commitments relevant to the forecast, and other opening balances. Link identifiable asset and liability movements explicitly. Do not assume a carrying value equals realizable or market value without documenting that choice.

**Pass:** the model does not lose an asset's value after excluding its income from operations; no item is counted in both operating value and the equity bridge; unexplained residuals cannot absorb accounting differences.

**Questions:** Which investment values require an explicit valuation assumption or range? What future acquisition policy is assumed? Proposed default: no invented acquisitions; explain how the organic growth forecast and existing acquired assets are treated.

### P9 — Integrate the full three statements and DCF

**Outcome:** one complete deterministic real-company model from approved/provisional decisions, with no paid reasoning required merely to recalculate it.

**Steps**

1. Complete all statement links and opening-to-closing schedules, including cash/FX/restricted-cash reconciliation where applicable. Use all detailed schedules through year five and connected aggregate transition methods thereafter.
2. Run cross-statement checks. Prevent double counting from overlapping schedules. Confirm every material opening balance has a forecast treatment.
3. Build the bridge from reported historical CFO/FCF to the defined modeled UFCF. Separate accounting reclassification, normalization, financing, and valuation adjustments. Do not claim a universal exact bridge where evidence leaves a residual.
4. Build forecast UFCF from operating profit, the selected operating tax treatment, allowable noncash adjustments, and operating reinvestment. Debt proceeds, repayments, dividends, and repurchases are financing/capital-allocation flows, not operating UFCF.
5. Lock discount timing and the handling of the unfinished year. Include only cash flows after the valuation date. A full fiscal-year display column that includes actual YTD cannot also be discounted as wholly future cash flow.
6. Supply WACC and market inputs through a small dated snapshot. Record source, currency, nominal/real basis, observation date, and selected assumption. Do not use defaults silently.
7. Implement transition and terminal assumptions. Check consistency between growth, margins, taxes, capital needs, and return assumptions. For a perpetual-growth method, validate its mathematical conditions; do not hide an inconsistent terminal reinvestment requirement. [S8]
8. Build the enterprise-to-equity and per-share bridges using the selected cash, debt, lease, investment, minority-interest, and award policies.
9. Add parameterized sensitivities on important operating assumptions, plus discount rate and terminal assumptions. Use recalculating formulas or supported scenario methods, not a frozen table masquerading as live output.

**Deliverable:** a complete calculated MSFT model and a check/coverage report.

**Pass conditions:** all mandatory statements reconcile through the forecast; historical flows are not discounted twice; changes in operating assumptions propagate; terminal conditions are coherent; valuation bridges count each item once; unresolved limitations remain visible.

**Questions at this stage:** Is valuation at the latest balance-sheet date or a later information date? For the latter, what explicit estimate bridges the intervening period? What discount convention applies to the stub? How will terminal reinvestment be connected to asset/working-capital schedules rather than duplicated? Which market inputs are unavailable and need a user-selected assumption?

A reporting-date valuation informed by later filings may be acceptable as an analytical exercise, but it must be labeled accordingly. It is not evidence of historical investability.

### P10 — Wire the complete controlled workflow and final review

**Outcome:** one command runs the bounded first-pass analysis and reports its true completion state.

**Steps**

1. Assemble a fixed dependency-aware sequence of the implemented financial tasks. Establish a provisional model before deeper tasks so they can see financial consequences. Keep provisional assumptions clearly labeled.
2. Add the explicit coverage pass across required financial areas. No ratio anomaly is required before an area can deserve attention. [S2]
3. Add bounded evidence follow-ups, supported no-change outcomes, unresolved results, and capability-gap results. A related question enters the application-owned queue only under a permitted financial area and resource limit.
4. Apply consequential decision reviews before adoption into the reviewed candidate. Use the limited revision/re-check path. Preserve all failed and rejected outputs for diagnosis.
5. Calculate the complete model and reserve a final whole-model analytical review. Let that reviewer challenge inconsistencies and omissions, not alter the workbook directly.
6. Implement bounded corrections and affected-task reassessment. Do not create an open-ended agent debate.
7. Make resume/reuse depend on relevant input content, decisions, source snapshot, prompt/schema/model settings, and method versions. A reused result must match the current analytical context.
8. Derive the final status from coverage, mechanical checks, review completion, and budget state. Human approval remains separate.

**Deliverable:** the CLI's first complete analysis workflow, with checkpointed output and an explicit review queue.

**Pass conditions:** no runtime executable code from models; no uncontrolled tools; no unbounded loops; first-pass assumptions are provisional rather than falsely human-approved; budget exhaustion does not become success; stale context does not produce a falsely fresh decision.

**Questions at this stage:** Which decisions always deserve targeted review, regardless of monetary size? What context should the final reviewer receive to detect cross-schedule problems without rereading every packet? What measured task bounds preserve useful investigation? Do not set review policy from one confidence score.

### P11 — Make Excel and CLI review usable

**Outcome:** Patrik can inspect and revise the analysis without reconstructing its reasoning or editing application code.

**Steps**

1. Create a readable workbook with a front review sheet, three statements, required supporting schedules, DCF/sensitivities, input controls, decisions, evidence, and checks. Combine tabs when useful; do not target a sheet count.
2. Put concise notes on sourced inputs and material assumptions. Include source/decision IDs and short caveats. Put full decision records and relevant evidence excerpts on navigable workbook sheets.
3. Show base-case exported assumptions separately from current editable inputs. A formula-based difference indicator identifies local changes. Label static explanations as the rationale for the exported base case.
4. Ensure designated input edits update the live statements, valuation, checks, and formula-driven sensitivities without an application session. Structural redesigns still require the CLI and an implemented method.
5. Implement numeric revisions through an explicit CLI path. Add a bounded natural-language instruction parser that proposes a known change or research request. It cannot execute free-form commands.
6. Show affected decisions and expected changed scope; ask for confirmation before authoritative adoption. Rebuild a candidate, re-check affected financial decisions, and publish a new version only when valid.
7. Preserve approved user choices and clearly display proposals to replace them. An Excel-edited copy is never silently imported or overwritten by a subsequent export.

**Deliverable:** a self-contained review workbook and a controlled revision path.

**Pass conditions:** every material decision is reachable; notes/links survive Excel; visible local-input changes do not pretend the old reasoning was revalidated; a CLI instruction can change a supported assumption/treatment or request investigation; rejected proposals and failed rebuilds do not change the prior model.

**Questions at this stage:** Which notes are useful while hovering and which belong in the decision sheet? Which inputs must be immediately accessible? Proposed default: source histories and formula areas are visually distinct from editable assumptions, with no required macros or external-workbook formulas. Which review command wording feels natural to Patrik?

### P12 — Run acceptance, measure cost, and stop

**Outcome:** an evidence-backed decision that V1 works, or an exact list of remaining product failures.

**Steps**

1. Run the existing deterministic suite and the new financial invariants without paid API calls. Reuse the existing eval harness for live cases and artifact capture where it fits.
2. Run the frozen MSFT case with explicit paid-run authorization and the recorded budget. Save cost, prompts, model settings, source/decision versions, mechanical checks, review output, and workbook.
3. Inspect representative material areas against their original filing context. Patrik judges financial usefulness; an LLM judge cannot certify itself.
4. Perform one full review task: select a consequential assumption, inspect its evidence and alternative, change it locally in Excel, then request an authoritative CLI revision and compare the result.
5. Run adverse cases: incomplete disclosure, wrong period, overlapping detail, unsupported method, rejected replacement, stale cache, budget exhaustion, and a failed candidate build.
6. Compare at least one alternative reasoning setting on a fixed task if budget is authorized. Report observed quality/cost rather than claiming statistical reliability from a single run.
7. Record all outstanding gaps. Close V1 only if the agreed product standard is met. Put second-company support, broader research, and synchronization into the later backlog.

**Deliverable:** one final workbook, reproducible case inputs, acceptance evidence, measured cost, and a short outstanding-issues report.

**Pass conditions:** all mandatory gates pass; useful review has been demonstrated; no hidden balancing plugs or unsupported source claims; actual costs are recorded; repeated deterministic builds from the same selected inputs agree within tolerance.

**Questions at this stage:** Is the €5 ceiling sufficient at the required depth? If not, which measured task is expensive, and is the proper response better context/caching, a different runtime model, or an explicitly higher ceiling? Does Patrik still need to reconstruct a material analysis to review it? If yes, that is a product gap, even when the workbook calculates correctly.

---

## 8. The first reasoning task in concrete terms

This is an illustrative task contract, not a prompt to run before P5.

**Question:** What is a defensible depreciation forecast for the included assets, and what can the disclosures not establish?

**Application supplies:** the frozen case; relevant asset/capex/lease excerpts; historical PP&E and D&A; current revenue/capex assumptions; applicable user decisions; implemented method IDs and parameter definitions; source and mechanical warnings.

**Reasoning model returns:** selected supported method; supported category breakdown; values or assumptions for required parameters; source references; a short financial justification; an important alternative/sensitivity; unresolved facts; or a bounded evidence request.

**Application rejects:** formula strings, program code, unknown method IDs, unresolvable input IDs, wrong source periods, unsupported claimed disclosures, and changes outside the task's permitted schedule.

**Application then does:** method validation; targeted financial review; formula generation; calculation; statement checks; valuation sensitivity; decision and Excel-note update.

For a fictional asset category, a useful explanation might be: “The filing discloses the accounting policy range, but not the age distribution of opening assets. The opening-asset depreciation profile is estimated. Forecast additions use the selected implemented straight-line method. Test a shorter remaining life separately.”

That is more useful than making up asset vintages or reporting an unsupported confidence percentage. The explanatory text does not have to reveal internal model reasoning traces; it has to state a defensible financial basis.

---

## 9. Budget, caching, and run controls

### 9.1 Measure the right cost

Record input tokens, cached input where billed differently, output/reasoning usage as reported by the provider, tool charges if any, retries, price snapshot, currency conversion used for the EUR limit, elapsed time, and total cost by task and run.

Do not equate few calls with low cost. Context size, output/ reasoning tokens, repeated packets, corrections, and model choice all affect spend. Treat the price schedule as dated configuration, not a constant copied from an old chat.

### 9.2 Admission and stopping

Before a paid call, reserve its estimated upper cost from known input size, output limits, and the dated price schedule. Include final-review capacity in the run plan before spending on exploratory tasks. Refuse a call that cannot fit the remaining authorized allowance under the selected reserve policy.

After the call, reconcile the estimate against reported usage. Count failed/retried calls when billed. If usage is unknown after a transport failure, retain the reservation and flag uncertainty rather than assuming the call was free.

Application reservations are cost controls, not a guarantee of the provider's final invoice. Use a safety margin and provider-side limits where available. Do not authorize a higher ceiling automatically.

### 9.3 Reuse

Reuse unchanged filing data and evidence. Cache a reasoning result only when its relevant evidence, model slice, previous effective decisions, method options, prompt, schema, and runtime model/settings match. A whole-model revision does not necessarily invalidate every task, but a changed dependency must not be ignored.

Recalculate formulas without model calls. Re-export presentation without model calls. Resume from the last valid stage rather than rerun ingestion and research unnecessarily.

### 9.4 Optimization order

First remove redundant calls and irrelevant context. Then improve evidence slicing and reuse. Then compare task grouping and model/effort choices on fixed cases. Change the budget or analytical scope only through an explicit product decision.

Do not save money by removing final review, suppressing uncertainty, accepting malformed output, or silently switching a detailed method to a crude ratio.

---

## 10. Testing and evaluation

### 10.1 Separate the failure sources

Test data retrieval, period construction, financial methods, decision state, reasoning quality, spreadsheet export, and the full workflow separately. A failed end-to-end run should tell us which boundary failed.

A native structured response only demonstrates its shape. A reconciliation PASS only demonstrates the relationships actually checked. Neither establishes source completeness or correct economic judgment. [S2, S6]

### 10.2 Required adverse tests

| Case | Required behavior |
|---|---|
| FY, YTD, and TTM overlap | Correct periods selected; no double counting. |
| Balance sheet supplied to TTM transformer | Reject the flow transformation for instant facts. |
| Restatement or segment recast | Preserve source basis and prevent mixed incomparable series. |
| Missing required fact | Mark affected calculation unavailable; do not fill with zero. |
| Disclosed aggregate but unknown component | Preserve aggregate support; do not invent a component amount. |
| Recurring detail added | Parent unchanged; detail persists; no subtotal duplication. |
| Proposed replacement rejected | Prior approved decision remains effective. |
| Final proposal fails validation | No new effective model/history selection; prior output remains. |
| New source invalidates context | Mark related decisions for reassessment. |
| Unknown method or executable payload | Reject; no code execution or implicit fallback. |
| D&A already in costs | Do not deduct it a second time. |
| Noncash asset addition | Do not equate it automatically with cash capex. |
| Negative operating working capital | Calculate signs correctly; no generic positivity constraint. |
| Funding shortfall | Flag or apply an explicit funding policy, not an accounting plug. |
| Stub includes actual YTD | Only future cash flows enter present value. |
| Terminal policy inconsistent | Block or flag the specified valuation check; do not hide it with a plug. |
| Budget reaches limit | Save incomplete state and remaining questions. |
| Excel-only input changed | Recalculate designated outputs; show divergence from base-case inputs. |
| Broken export or Excel recalculation mismatch | Fail export acceptance; do not rely on cached values. |

Add tolerances based on source precision, units, and purpose of the tested arithmetic. Arithmetic tolerances are not economic materiality thresholds. Do not use a universal dollar tolerance for both dollar and million-dollar tables. Check exact structural identities separately from rounded disclosure differences.

### 10.3 Reasoning evaluation

Use frozen cases with observable expected behavior. Score method validity, evidence attribution, period correctness, distinction between disclosed and assumed inputs, relevant alternatives, detection of contradictions, and willingness to report no-change or insufficient evidence.

Do not demand one exact prose answer or one unique valuation. Financial forecasts can legitimately differ. The unacceptable behavior is unsupported certainty, an incoherent method, a concealed omission, or a result that cannot be challenged from its evidence.

Keep expected answers outside runtime prompts and evidence packets. Do not use the evaluator to repair product outputs. Invalid mechanical results should be retained for diagnosis and excluded from claims of successful financial analysis. [S9]

---

## 11. Workbook specification

### 11.1 Opening review sheet

Show company, source cut-off, financial measurement date, valuation date, model version, run status, analyst/reviewer completion, and human approval state.

Show the valuation result/range where valid, important assumptions, material unresolved issues, and navigation to schedules, decisions, evidence, and checks. Do not present an invalid valuation prominently with its blocker hidden on another sheet.

### 11.2 Model and supporting schedules

Use clear period labels for actual, YTD, TTM, stub forecast, and full-year forecasts. Put units and currency in headers. Distinguish inputs from formulas. Do not mix source-currency amounts, display-scaled amounts, percentages, days, and shares without explicit labels.

Keep historical reported facts, analytical bridges, and forecast values visually and structurally distinct. Reference source inputs rather than copying the same hardcoded number into several schedules.

### 11.3 Notes and decisions

A cell note should identify the source or assumption basis, main caveat, and decision/evidence ID. Do not place the only complete explanation in a hover box.

The decision sheet should include selected treatment, rationale, alternatives, evidence quality, judgment level, effective authority, affected inputs, and sensitivity or materiality where available. The evidence sheet should hold useful exact excerpts and filing locators, not only homepage links.

Public Mog APIs document notes and comments, but their behavior in the pinned engine and exported workbook must pass P1. [S4]

### 11.4 Excel edit boundaries

Designated numerical assumptions are local what-if controls. A user can edit arbitrary Excel formulas physically, but the application cannot certify those changes without importing/rebuilding them, which is outside V1.

Preserve an exported-base input table. Compare current input cells to that base and display a local-change flag. Do not claim to detect every possible workbook modification.

Formulas, sensitivities, and checks should recalculate. Narrative justification and embedded evidence remain those of the exported version. Label that explicitly. A new authoritative explanation requires a CLI revision and export.

Never overwrite an edited workbook path automatically. Use versioned outputs and a clear current-model reference.

---

## 12. Proposed CLI and simple storage

The observed repository console entry point is `smrik-fund`. The commands below are target behavior, not claims that these commands or flags already exist. [S3]

```text
smrik-fund run MSFT --as-of <information-cutoff> --budget-eur 5
smrik-fund status <run-id>
smrik-fund review <run-id>
smrik-fund revise <run-id> --instruction "Reassess the server useful-life assumption"
smrik-fund resume <run-id> --additional-budget-eur <approved-amount>
smrik-fund export <model-version>
```

Keep the default run noninteractive. It should finish permitted work, preserve gaps, and report the next review action rather than block unexpectedly on a prompt. Confirmation belongs in an explicit review/revision command.

Reuse the existing project layout where reasonable. A logical storage arrangement is company source references and historical data, stable decision/evidence records, per-run manifests and changed call results, and versioned output workbooks. Avoid a full copy of all files for every run.

Do not make one giant history CSV the source of truth for unrelated future assumptions, source facts, and all workbook logic. Reuse adjustment history for adjustments, and add only the small records needed for forecast decisions and model manifests.

The physical module layout should follow real dependencies. Likely areas are ingestion/periods, evidence, decisions, financial methods, workbook building, checks, reasoning boundaries, and the CLI/pipeline. These are responsibilities, not a required directory scaffold.

---

## 13. Coding-agent operating contract

Give a coding agent one bounded packet with its acceptance criteria. It may read and implement normal in-scope application code during development. This permission does not give the product's runtime reasoning model code-execution authority.

Use normal Python functions, DataFrames where appropriate, and small schema models at boundaries. Use application-owned workbook code. Keep dependency versions deliberate. Do not upgrade packages simply because a newer example uses a different API.

Start with a focused failing test when practical. Test the financial invariant, not only the existence of a function or output file. Use frozen data and mocked/replayed model responses for ordinary tests. Paid calls require a named case and explicit budget authorization.

Do not perform unrelated refactoring, destructive Git actions, wholesale migrations, global installs, external writes, or broader feature work under a narrow task. Preserve dirty local work. Stop and explain a concrete blocker when the task cannot fit its permitted scope.

Use one coding agent at a time for overlapping files. Do not create verifier agents by default. A required product financial-review call is different from a second coding agent repeating tests.

The completion report must include changed behavior/files, exact tests and results, a representative artifact or before/after value, unresolved problems, paid usage if any, and nearby work not changed.

### Reusable task prompt

```text
Read AGENTS.md, docs/AI_FUND_BUILD_GUIDE.md, and the current status file.

Implement only work packet [ID / specific substep].

Goal:
[One observable financial or application behavior.]

Inputs already available:
[Exact observed files, functions, fixture, and approved decisions.]

Decisions to settle before editing:
[Only questions that this packet actually depends on.]
Inspect the environment and sources yourself for factual answers.
Ask Patrik only for a consequential financial/scope decision.

Acceptance:
[Concrete expected values, state invariants, source requirements, and errors.]

Allowed scope:
[Named files or a narrow area identified after inspection.]

Out of scope:
[Specific nearby temptations.]
No runtime-generated code or formulas from the reasoning model.
No unrelated refactor. No implementation of the next packet.

Validation:
[Focused deterministic tests and relevant lint/type/integration checks.]
Paid calls: [none, or exact authorized case and maximum spend].

Stop when the acceptance criteria pass or a real blocker is found.
Report Changed / Tests / Artifact / Open issues / Cost / Not changed.
Update the existing status file with the next prerequisite, not a new roadmap.
```

### First task to give an agent

```text
Read AGENTS.md and docs/AI_FUND_BUILD_GUIDE.md.
Perform P0: baseline inspection only.

Inspect the actual local checkout of smrik-fund, including dirty files,
active commands, source/period handling, evidence retrieval, adjustment
application, effective decision state, workbook export, and eval harness.

Compare the supplied September review findings with the code that exists.
Do not assume the GitHub status file represents the current local checkout.

Inspect the installed ShortcutXL skills directory if present. Read relevant
skills as reference material; do not run ShortcutXL or copy its autonomous
permissions model into this project.

Deliver one short baseline note containing:
- observed branch/commit/dirty state and package/runtime versions;
- reusable components with exact file/function references;
- confirmed defects and evidence, separated from unverified claims;
- conflicts with the newly agreed product boundary;
- the smallest proposed P1 calculation/export compatibility task;
- any factual blocker or financial decision needed before that task.

No production code edits, no financial-data changes, no dependency changes,
no paid calls, no commits or pushes, and no implementation of P1.
Do not create a new architecture document.
```

---

## 14. How Patrik should review progress

At each package, ask to see the artifact first. Then inspect the evidence and tests supporting it. A long explanation of why the architecture is elegant is not a deliverable.

For P1, inspect a small workbook and an actual Excel recalculation. For P2, inspect source identities, periods, and a historical table. For P4, change an input in the fictional complete model. For P5, challenge the first real forecast assumption. For later schedules, inspect both the ordinary case and an adverse case. For P12, complete the review-and-revision experience end to end.

Judge progress by useful verified behavior, not lines of code, number of agents, tabs, API calls, or approved adjustments.

Keep one next packet active. When a new idea appears, record it in a later backlog unless the current acceptance criterion cannot be met without it. When a needed method is missing, add one tested method, not a framework to generate all future methods.

The final product should make the distinction between fact and judgment easier to inspect. It should not promise to remove judgment from valuation.

---

## 15. Reference basis and verification limits

The product decisions in this guide come from the design interview in this conversation. Package ordering, record names, method examples, and explicitly marked defaults are implementation recommendations. They are not claims about code already present.

**[S1] Earlier approved project specifications.** User-supplied `ai_fund_v1_section_1_updated.md` and `ai_fund_v1_section_2_implementation_spec.md`, dated 10 August 2026. Used for source preservation, simple architecture, testing separation, and coding-task discipline. Old scope and conflicting state semantics are explicitly superseded here.

**[S2] Iterative financial analysis: review and implementation plan.** User-supplied `Pasted markdown(5).md`, dated 5 September 2026. Used for the reported local findings and the distinction between questions, details, normalization, explanations, and gaps. Financial values and defects described there were not independently rerun for this guide.

**[S3] Repository files checked through GitHub on 5 September 2026.** `docs/V1_STATUS.md` and `pyproject.toml`. The former is dated 30 August; the latter declares Python `>=3.13` and the `smrik-fund` console entry point. This was a limited read, not a full repository audit.

Locations: `https://github.com/smrik/smrik-fund/blob/main/docs/V1_STATUS.md` and `https://github.com/smrik/smrik-fund/blob/main/pyproject.toml`.

**[S4] Fundamental Research Labs, Mog.** Official README, SDK guide, CLI skill, and notes/comments API described in the conversation. Support includes headless workbook operations, formula calculation, and XLSX export. The CLI warns about partial mutations; the SDK is not a security boundary for untrusted code. The project must validate its pinned version and actual Excel behavior.

Locations: `https://github.com/fundamental-research-labs/mog`, `https://github.com/fundamental-research-labs/mog/blob/main/docs/guides/sdk.md`, `https://github.com/fundamental-research-labs/mog/blob/main/cli/skill/SKILL.md`, and `https://github.com/fundamental-research-labs/mog/blob/main/types/api/src/api/worksheet/comments.ts`.

**[S5] Fundamental Research Labs, ShortcutXL public integration skill.** This describes invoking ShortcutXL and is not a substitute for inspecting the full local financial-modeling skill collection. No local installation was accessed for this guide.

Location: `https://github.com/fundamental-research-labs/shortcutxl-plugins/blob/master/shortcutxl/SKILL.md`.

**[S6] OpenAI, Structured model outputs.** Official documentation checked on 5 September 2026. Used only for the narrow structured-output boundary; no particular model price, capability level, or financial correctness is assumed.

Location: `https://developers.openai.com/api/docs/guides/structured-outputs`.

**[S7] SEC developer/API documentation and EdgarTools period reference.** These inform source handling and inspection. Follow current access requirements and verify installed library behavior; do not assume a period type guarantees every desired transformation.

Locations: `https://www.sec.gov/search-filings/edgar-application-programming-interfaces`, `https://www.sec.gov/about/developer-resources`, and `https://github.com/dgunning/edgartools/blob/main/docs/PeriodType-Quick-Reference.md`.

**[S8] Aswath Damodaran, The Stable Growth Rate.** Used for the narrow principle that stable growth must be accompanied by consistent reinvestment and return assumptions. Detailed case-specific valuation policies remain decisions for the relevant packages.

Location: `https://pages.stern.nyu.edu/~adamodar/New_Home_Page/valquestions/stablegrowthrate.htm`.

**[S9] Prior project evaluation-harness discussion supplied in the conversation.** Used for separating artifact capture and evaluation from product repairs. P0 must inspect the actual harness before proposing reuse or changes.

No live company valuation was performed. No current MSFT numerical forecast was selected. No spreadsheet-engine compatibility test, full local repository inspection, or runtime-cost benchmark was performed in preparing this plan.
