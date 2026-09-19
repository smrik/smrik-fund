# AI Fund repository baseline

Snapshot: 2026-09-05. P0 repository inspection only. Authority: `docs/AI_FUND_BUILD_GUIDE.md`, this run's `USER_NOTES.md`/`PLAN.md`, and repository instructions.

## Repository and runtime

- Branch: `codex/msft-golden-run`; HEAD: `369400cf144f4b4b2a2ab9c347c67e048a48025d`.
- Checkout is dirty before P0. Existing changes span `AGENTS.md`, `docs/V1_STATUS.md`, the evaluation harness, ingestion paths, tests, and untracked run/artifact files including `line_details.py`, `procedural_investigation.py`, and `skills/filing-investigation/SKILL.md`. Preserve them. `procedural-all-statement-research` claims the procedural/eval surfaces; no overlap was edited.
- `pyproject.toml` requires Python `>=3.13`; `.venv` is Python 3.13.5. Installed versions: EdgarTools 5.45.1, OpenAI 3.1.0, Pandas 3.0.5, Pydantic 2.13.4, Typer 0.27.1, pytest 9.1.1, Ruff 0.16.1. `uv.lock` pins the same relevant versions.
- Current CLI commands are `analyze`, `reconcile`, `run`, `investigate`, `eval`, and `review`. There is no `export` command and no `.xlsx`/workbook implementation in maintained Python source or tests.

## Observed data and control paths

| Area | Current implementation | Reusable boundary / gap |
|---|---|---|
| Source/cache | `data/MSFT/01_source/edgar/manifest.json` has 8 cached 10-K/10-Q filings; latest is accession `0001193125-26-323660`, report date `2026-06-30`. | Cached SEC evidence is useful; runtime `get_latest_filing()` (`statements.py:62-71`) always asks EdgarTools for latest 10-K and has no as-of cutoff. |
| Statements | `get_statements_from_filing()` (`statements.py:74-89`) requests EdgarTools standard income, balance-sheet, and cash-flow frames. Current cached shapes: income 21x19 with 3 FY duration periods; cash flow 39x19 with 3 FY duration periods; balance sheet 40x18 with 2 instant dates. | Keep statement-specific periods, signs, missing values, and metadata. No YTD/TTM or frozen source-selection contract is implemented. |
| Analytical P&L | `build_analytical_pnl()` (`statements.py:384-392`) sends only the income frame through `prepare_pnl()` (`statements.py:249-381`), preserving reported columns and adding deterministic ratios/change columns. | Existing P&L is a sound reported base; balance/cash-flow model use is still absent. |
| Filing evidence | `retrieve_filing_evidence()` (`filing.py:365-381`) uses literal queries and `_retrieve_filing_evidence()` (`filing.py:243-363`) records accession, source, section, line/offset locators, and exact excerpts. | Reuse bounded literal retrieval and packet validation. It is a single retrieval per current adjustment topic. |
| Adjustments/state | `_candidate_identity()` (`main.py:319-358`) uses economic identity with company, fiscal period, source row key, and item key. `_history_identity_lookup()` (`main.py:393-498`) detects state/selector/competing-key conflicts. `resolve_current_adjustments()` (`adjustments.py:272-313`) selects the latest approved version; `apply_adjustments()` (`adjustments.py:316-369`) applies signed deltas and recalculates subtotals. | Reuse one deterministic engine. Final Reviewer revisions still bypass this distinction (below). |
| Detail/model rows | `build_line_details()` and `attach_model_rows()` (`line_details.py:66-144`, `:183-307`) keep segment and normalization groups separate, exclude children from subtotals, and attach them during `_rebuild_adjusted_outputs()` (`main.py:2231-2286`). | Current `line_details.csv` is regenerated from `segment_analytics.csv` plus adjustment history. No durable `reported_details.csv` input exists for newly learned note detail. |
| Evaluation | Frozen case definitions/checks/runner live in `src/smrik_fund/evals/`; `docs/eval_harness.md` defines source hashes, independent checks, rejection isolation, and comparison. | Existing eval harness is the default reuse choice. The active procedural run owns procedural/eval edits; P0 made none. |

## September review claims checked against current code

1. **Reviewer revision applying the original proposal — confirmed.** `_run_adjustment_analysis()` (`main.py:1630-1643`) treats Reviewer verdict `accept` *or* `revise` as `reviewed_accept`, derives the signed delta from the original candidate, and can append it as approved. It never consumes a revised amount/direction or performs a correction/re-check. The maintained regression `test_scan_path_applies_reviewer_revise_after_notes_retrieve()` (`tests/test_adjustment_analysis.py:392-477`) asserts `revise` becomes `approved`/`applied`. The saved MSFT A0003 run records Reviewer `revise`, `amount_basis=unknown`, `suggested_amount=null`, and unresolved dilution-only support, yet history approves `$6.5B`; this is the highest-priority reuse defect.
2. **Aggregate/component identity — partly repaired, financially still open.** Identity includes `item_key` and a stable source row key; conflict tests cover amount drift (`tests/test_stable_identity.py:138-148`), competing keys (`:201-214`), row-key aggregate guards (`:216-245`), and distinct economic keys (`:247-256`). Detail tests keep segment and normalization groups separate and show the OpenAI parent/child bridge (`tests/test_line_details.py:110-161`). These mechanics do not make an aggregate OpenAI gain equal to its “primarily dilution” component; the A0003 run demonstrates the remaining semantic risk.
3. **Reported detail persistence — confirmed only for existing inputs.** Rebuild persistence and parent immutability pass in `tests/test_line_details.py:182-318`. The current rebuild consumes persisted segments and approved adjustments, but it has no durable source for a newly accepted recurring note component. The planned `reported_details.csv` extension belongs to P3, not P0.
4. **Rejected replacement leaves prior approval effective — confirmed for the resolver.** `resolve_current_adjustments()` explicitly ignores later rejected rows when choosing the effective approved version; `tests/test_adjustments.py:166-183` and `tests/test_stable_identity.py:501-514` prove this. This does not repair the separate `revise` shortcut, which approves the original candidate before a replacement exists.

## Reuse / fix / defer

| Decision | P0 result |
|---|---|
| Reuse | EdgarTools standard statement frames; immutable cached SEC artifacts; literal filing packets; `derive_line_delta`/identity/history/application/reconciliation; existing detail row contract; frozen eval harness. |
| Fix before automated final-proposal application | Reviewer `revise` must preserve the original, run at most one corrected proposal and one re-check, then apply only the final supported result. Keep rejected/unsupported replacements off history/current output. |
| Defer | Source/period freeze and YTD/TTM construction (P2); durable reported details and effective decisions (P3); three-statement model/forecast/valuation; `.xlsx` presentation until the P1 engine proof succeeds. |

## Smallest next P1 task

Parent-owned P1 should define one tiny calculation/export fixture and test the actual accessible engine plus Patrik's Excel environment: linked sheets, editable assumption, depreciation/tax/cash, balance check, small DCF, note, internal decision link, `.xlsx` export, full Excel recalculation, assumption edit, broken reference detection, and prior-fixture survival after interruption. Candidate new surfaces are one fixture script under `scripts/`, one focused test under `tests/`, and one P1 evidence/decision report; do not change valuation production code or add an engine adapter before that proof.

Parent P0 environment inspection: Node v24.10.0/npm 11.6.1; installed Excel x64 16.0.20326.20132 at `C:/Program Files/Microsoft Office/Root/Office16/EXCEL.EXE`; Excel COM class resolves. P1 subsequently proved actual recalculation as recorded in `SPREADSHEET_ENGINE_DECISION.md`.

**Installed-reference correction, 2026-09-06:** P0's Codex/Claude/personal/project skill searches missed the NVM installation. Current filesystem inspection confirms [ShortcutXL 0.3.90](C:/Users/patri/AppData/Local/nvm/v24.10.0/node_modules/shortcutxl/package.json). Its [MIT license](C:/Users/patri/AppData/Local/nvm/v24.10.0/node_modules/shortcutxl/LICENSE) requires retaining copyright/permission notices in copies or substantial portions and provides the software without warranty. No ShortcutXL source code was copied.

Its 16 installed skills include notes/comments, advanced COM/Mog, SEC retrieval and integrations; no dedicated financial-modeling skill appears in that catalog. The inspected [notes reference](C:/Users/patri/AppData/Local/nvm/v24.10.0/node_modules/shortcutxl/skills/notes-comments/SKILL.md) separates canonical sourced input notes from adjacent reasoning/uncertainty and calls for preserving exact source text. This supports the guide's source/decision separation; the guide controls the product's actual note and evidence contract. The separate personal `financial-modeling/SKILL.md` is not ShortcutXL provenance. No autonomous ShortcutXL run or permissions workflow was invoked; Mog remains selected from actual P1 tests.

Parent Git comparison: locally stored `origin/main` is `e82c487`, with 1 remote-only and 5 HEAD-only commits, plus dirty changes. This was not a network refresh; do not equate the local remote ref with current GitHub. Guide copy matches the supplied original. P0 gate passed; P1 may now test the specified fixture and deliberately pin a candidate engine.

## Verification

- `.venv/Scripts/smrik-fund.exe --help` exited 0; output is the command inventory above.
- Bounded offline sample: `tests/test_adjustments.py tests/test_reconciliation.py tests/test_line_details.py tests/test_stable_identity.py`; **63 passed, 12 subtests passed**. Full output: `Lunacy/runs/three-statement-dcf/phases/baseline/evidence/bounded-deterministic-tests.log`.
- Relevant extension including `tests/test_statements.py` was attempted once; that maintained file is absent, so pytest exited 1 before collection. Output: `.../evidence/bounded-deterministic-tests-full.log`.
- No paid calls, dependency upgrades, production/test/data edits, commits, pushes, or destructive Git operations were performed by P0.
