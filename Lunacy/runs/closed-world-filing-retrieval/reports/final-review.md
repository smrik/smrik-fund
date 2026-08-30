# Closed-world progressive filing retrieval — A2 final review

Verdict: **PASS**

Scope: read-only final review of R1 code, prompts, tests, and fresh MSFT proof.
No source, test, config, live-artifact, or external-system changes.

## Review result

- Initial path is closed-world: `build_initial_search_plan` copies only affected source labels and a fixed generic cue (`src/smrik_fund/ingestion/filing_investigation.py:405-451`). `run_search_plan` records `planner_call_count=0` and makes no model call (`:485-510`). Prompt input excludes filing text (`build_finding_plan_context`, `:454-482`).
- Expansion is bounded and filing-local: one Structured Output call (`:661-734`), exact support span/ref checks, packet identity checks, and independent literal filing-text verification (`:520-658`). The orchestration has one expansion and, only when accepted, one final retrieval (`:2220-2309`); no retry/autonomous loop.
- Identity/provenance is consistent: `_validated_packet` requires every item `Source` to equal packet `Source` and every locator to retain the packet accession (`:288-303`). Fresh packet E1–E4 independently passes this check.
- Quantitative bridge is deterministic and fail-closed: exact two-period `respectively` extraction preserves signs/periods and maps the target label (`:1408-1605`); bridge conversion is Python-only (`:1773-1880`).
- Qualitative safety is materially repaired: narrative lexical support/numeric-free checks fail unsupported company-specific claims (`:1608-1692`); unquantified effect is derived from cited gain/loss polarity (`:1049-1078`).

## Fresh checks

Command: `PYTHONPATH=src C:\Users\patri\miniconda3\envs\ai-fund\python.exe -m pytest tests/test_filing_investigation.py -q -k "initial_seed or build_finding_plan_context or expansion_requires or end_to_end_expansion or exact_period_pair_bridge or period_pair_bridge_fails or unsupported_company_specific_narrative or unquantified_effect or packet_item_source or reconciliation_preserves or duplicate_api_aliases"`

Result: **13 passed, 26 deselected**. Custom no-write probes also passed: no `OpenAI` in initial seeds; expansion exact span/ref and filing-text verification; item-source mismatch rejected; loss polarity downgraded to `decreased_line`; unsupported “quantum teleportation” narrative rejected; bridge values exact.

CLI help exits 0 (`.venv\Scripts\smrik-fund.exe investigate --help`). CLI exposes ticker, finding rank, scan file, model/reasoning, and output root (`src/smrik_fund/main.py:2328-2352`); successful runs print the saved artifact path plus concise summary (`:2403-2410`).

## Fresh MSFT proof

Artifacts: `data/live-closed-world-proof-r1/MSFT/03_output/analysis/filing_investigation_01_20260827T182736421990Z.json`, initial packet `data/live-closed-world-proof-r1/MSFT/03_output/evidence/finding_01_20260827T175608460314Z_initial.md`, final packet `data/live-closed-world-proof-r1/MSFT/03_output/evidence/finding_01_20260827T182736421990Z.md`.

Representative JSON: `status=completed`, `planner_call_count=0`, initial query `Other income (expense), net included`, one expansion query `dilution gain from the OpenAI Recapitalization`, `filing_text_verification=performed` (`...182736421990Z.json:69-81,236-274`).

Financial proof: packet identity/accession and exact quoted filing spans are present (`...182736421990Z.md:6-47`). Deterministic facts map to L12: FY26 `+6.5`bn and FY25 `-4.8`bn, with `increased_line`/`decreased_line` effects (`...182736421990Z.json:314-343`). Python bridge reports observed `+15.598`bn, disclosed contribution `+11.3`bn, unresolved difference `+4.298`bn, `difference_is_reported_plug=false` (`...182736421990Z.json:486-499`).

State isolation: successful JSON has no adjustment/history/state output; fresh proof output contains no adjustment/history/state files. Model narrative remains qualitative and cited (`...182736421990Z.json:364-414`).

## Complexity assessment

The module is large (2,535 lines), but the size is not a merge blocker here: the code is a single bounded V1 path with explicit Pydantic boundary models and local deterministic helpers, not a service/framework stack. Two small apparently unused remnants remain (`_GENERIC_ACCOUNTING_CUES`, `:306`; `_amount_and_unit_supported`, `:1694-1706`), but they are immaterial and do not affect correctness, reachability, or the tested path. No further simplification is required before merge.

## Findings

No merge-blocking findings. R1’s A1 blockers (unsupported narrative, model-owned polarity, item-source/extra-ref provenance) are closed by the code paths and fresh probes above. Existing failed-attempt artifacts under the proof root are preserved per run instructions; the successful artifact is explicit and valid.

## Not changed

No edits to reported financial values, EdgarTools retrieval mechanics, scan/normalization/materiality, adjustment application/history, review, lifecycle, or shared `src/smrik_fund/ingestion/filing.py`.

## Control Block

Verdict: **PASS**
Blocking: none found in bounded final review.
Initial: deterministic source-label seeds; zero initial planner LLM.
Expansion: one call/pass max; accepted query exact filing span/ref; source-text verified.
Identity: all final packet items match packet Source and accession.
Bridge: L12; FY26 +6.5; FY25 -4.8; contribution +11.3; observed +15.598; residual +4.298.
Residual: explicit unresolved difference; `difference_is_reported_plug=false`.
Checks: 13 passed, 26 deselected; CLI help passed; no state mutation.
Complexity: 2,535 lines reviewed; no material removable blocker.
Report is immutable after FINAL.
