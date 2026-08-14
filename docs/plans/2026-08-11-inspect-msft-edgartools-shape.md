# Inspect MSFT EdgarTools Output Shape Implementation Plan

> When execution is requested in a separate session, use the `executing-plans` skill to implement this plan task-by-task.

**Goal:** Inspect the real MSFT 10-K output returned by EdgarTools and record the exact statement shape needed before Task 2 introduces any derived analytical view.

**Architecture:** Add one direct, read-only inspection script that calls EdgarTools for MSFT, requests the `standard` view for the income statement, balance sheet, and cash-flow statement, and prints the observed DataFrame/XBRL metadata. Record the run in a short Markdown note. Do not route this through the existing parser, mutate frames, add mappings, or change the CLI.

**Tech Stack:** Python, EdgarTools, Pandas, `python-dotenv`, the repository `.venv`, and Ruff. Use EdgarTools’ native cache behavior.

---

## Scope and repository assumptions

- The user prompt names `docs/ai_fund_v1_section_1.md` and `docs/ai_fund_v1_section_2.md`; the actual files are `docs/ai_fund_v1_section_1_updated.md` and `docs/ai_fund_v1_section_2_implementation_spec.md`.
- Section 2 Task 1 requires only a small inspection script or focused test plus notes on the real DataFrame shape.
- The current repository contains both a newer artifact parser and an older `statements.py`/CLI surface. Task 1 should not repair that unrelated interface mismatch.
- The checked-in `.venv` has EdgarTools 5.45.1, Pandas 3.0.5, and Ruff 0.16.1. `uv run` currently fails against the global uv cache, so use the virtualenv directly or pass an explicit writable cache directory.

### Communication and design rule

Use Simple Technical English throughout the script output, Markdown note, comments, and execution report. Prefer short, concrete sentences and familiar finance terms; define an unfamiliar EdgarTools/XBRL term when it first appears. Keep the implementation visibly small and understandable to a finance-oriented Python user: direct functions, explicit control flow, and one bounded inspection script. Do not add an abstraction unless a concrete observed requirement and focused check justify it.

### Task 1: Create the direct MSFT inspection script

**Files:**
- Create: `scripts/inspect_msft_edgartools.py`
- Modify: none of `src/`, `tests/`, or the CLI

**Step 1: Add the minimal loader and reporting functions**

Implement a small script with this concrete flow:

```python
load_dotenv()
set_identity(os.getenv("SMRIK_EDGAR_USER_AGENT") or "SmrikFund research@example.com")
filing = Company("MSFT").get_filings(form="10-K").latest()
xbrl = filing.xbrl()

statements = {
    "income_statement": xbrl.statements.income_statement(),
    "balance_sheet": xbrl.statements.balance_sheet(),
    "cash_flow_statement": xbrl.statements.cashflow_statement(),
}
frames = {
    name: statement.to_dataframe(view="standard")
    for name, statement in statements.items()
}
facts = xbrl.facts.to_dataframe()
```

Print, without changing any returned object:

1. EdgarTools package version and filing metadata: ticker, accession, form, filing date, and period of report.
2. For each statement: DataFrame type, shape, index type/name/sample values, exact column names, dtypes, and the first few rows.
3. Date-bearing period columns, preserving their exact labels. Report when a statement exposes fewer than three annual/date-bearing columns; do not invent periods or fail solely because EdgarTools returns fewer comparative balance-sheet dates.
4. Per-period numeric sign counts for negative, positive, zero, and missing values; do not convert signs or fill missing values.
5. Hierarchy/subtotal evidence available directly in the statement frame, such as columns containing `level`, `abstract`, `parent`, `subtotal`, `balance`, `weight`, `sign`, or `role`. Report an explicit “none observed” result when no such columns exist.
6. Raw XBRL fact shape and columns, including any available `balance`, `weight`, `preferred_sign`, `statement_role`, context, and dimension fields. Print a bounded sample rather than the whole facts table.
7. Duplicate and dimensional indicators: count duplicate rows using the actual concept/period/context fields present, count non-empty dimension fields, and show only a small sample of ambiguous rows.

Use only standard-library helpers plus Pandas operations for reporting. Detect date-bearing columns from their labels rather than hard-coding the current fiscal years, because the latest MSFT 10-K may change. Do not add a reusable abstraction, canonical taxonomy, sign normalization, deduplication, or Task 2 analytical calculations.

**Step 2: Run syntax and lint checks**

Run:

```powershell
& .\.venv\Scripts\python.exe -m py_compile scripts\inspect_msft_edgartools.py
& .\.venv\Scripts\ruff.exe check scripts\inspect_msft_edgartools.py
```

Expected: syntax compilation succeeds and Ruff reports no violations.

### Task 2: Execute against real MSFT data and write the findings note

**Files:**
- Create: `docs/edgartools_msft_shape.md`
- Read only: `data/MSFT/01_source/edgar/` may be used as evidence of the cached filing, but do not rewrite generated artifacts

**Step 1: Run the inspection against the latest real 10-K**

Run:

```powershell
$env:PYTHONPATH = "src"
& .\.venv\Scripts\python.exe scripts\inspect_msft_edgartools.py
```

Expected: one successful report containing the actual accession and filing period, all three statement sections, the exact number of annual/date-bearing periods returned for each statement, exact frame columns/index details, sign statistics, raw-fact metadata, and duplicate/dimension findings. If the local cache is insufficient, allow EdgarTools’ normal native cache/download behavior; do not introduce a second cache layer.

**Step 2: Record the observed shape in the Markdown note**

Write a short note with these sections:

- Run metadata and EdgarTools version.
- One compact table per statement covering shape, index, exact columns, and the three annual periods.
- Source/XBRL metadata actually present, separated from fields that were not returned.
- Reported sign observations and missing-value observations, explicitly stating that source values were preserved.
- Subtotal/hierarchy information available, or the evidence that EdgarTools did not expose it in the inspected frame.
- Duplicate/dimensional facts observed, including a bounded example if present.
- Task 2 implications: preserve the three source DataFrames, use the observed period columns, do not normalize signs, treat missing values as missing, and defer custom mapping or source-selection logic unless this run demonstrates a concrete need.

Label observations as “observed” versus “implication”; do not turn the note into a proposed taxonomy or analytical P&L design.

### Task 3: Run the required project checks and close the scope boundary

**Files:**
- Verify: `scripts/inspect_msft_edgartools.py`, `docs/edgartools_msft_shape.md`
- Do not change: `src/smrik_fund/ingestion/statements.py`, `src/smrik_fund/ingestion/parser.py`, `src/smrik_fund/main.py`, or existing tests

**Step 1: Run the real-data script and Ruff again after writing the note**

Run:

```powershell
$env:PYTHONPATH = "src"
& .\.venv\Scripts\python.exe scripts\inspect_msft_edgartools.py
& .\.venv\Scripts\ruff.exe check scripts\inspect_msft_edgartools.py
```

Expected: the real-data inspection exits successfully and Ruff passes.

**Step 2: Run relevant existing tests if the test runner is available**

Run:

```powershell
uv --cache-dir .uv-cache run pytest tests\test_statements.py -q
```

Expected: record the exact result. If pytest is unavailable or the existing parser/statement import mismatch fails before tests execute, report that as a pre-existing repository/environment issue and do not expand Task 1 to fix it.

**Step 3: Review the final diff and completion report**

Run:

```powershell
git status --short
git diff -- scripts/inspect_msft_edgartools.py docs/edgartools_msft_shape.md
```

The only Task 1 deliverables should be the inspection script and findings note. Follow `@verification-before-completion` before claiming completion. Leave Task 2 ingestion, analytical P&L, mapping, reconciliation, and CLI work for later tasks.

## Completion criteria

- The real MSFT statement output was executed and its exact shape was recorded.
- The returned annual periods, including any statement-specific period-count difference, index/columns, metadata, signs, hierarchy/subtotal evidence, and duplicate/dimensional behavior are documented.
- No source DataFrame was mutated and no custom mapping or analytical P&L was introduced.
- The script passes syntax/lint checks; existing test results and any pre-existing blockers are reported exactly.
