# Parent gate — finding-driven filing investigation

Verdict: **PASS**

## Acceptance

- Starts from persisted structured `ScanFinding`; separate `investigate` CLI selects finding rank and enforces same-filing accession.
- Two bounded Structured Output calls: at most three literal filing queries, then evidence-cited investigation.
- Reuses existing EdgarTools retrieval/evidence packet machinery; exact excerpts, URLs, accession, sections, lines, and offsets preserved.
- Observed movement, disclosed drivers, interpretation, explanation, and unresolved remainder are separate. Unsupported quantities/periods/signs downgrade atomically; partial explanations remain valid.
- Deterministic reconciliation computes only an unambiguous single-line/single-period compatible-unit bridge. Otherwise amounts/residual stay null; no model plug.
- JSON/evidence artifacts are inspectable; CLI is concise; no adjustment history, approved state, adjusted P&L, normalization, materiality, identity, lifecycle, review, or Scan semantic change.

## Final proof

- Live command exited 0 on final v4 code.
- JSON: `data/live-finding-proof-r4/MSFT/03_output/analysis/filing_investigation_01_20260827T152234074645Z.json`
- Evidence: `data/live-finding-proof-r4/MSFT/03_output/evidence/finding_01_20260827T152234074645Z.md`
- MSFT 10-K accession `0001193125-26-323660`; three literal queries; six exact evidence items.
- Result: two evidence-backed OpenAI drivers, conservatively unquantified; five signed observed lines; reconciliation `not_computable`; residual null; plug false; tax/component bridge explicitly unresolved.

## Verification

- Final owner: focused 28 passed; full 182 passed + 45 subtests; Ruff lint/format for added files, py_compile, and `git diff --check` passed.
- Parent: focused 28 passed; Ruff lint passed; `git diff --check 46ca750` passed; direct JSON/evidence/state-isolation sample passed.
- Full-file Ruff format remains red only for baseline `analytical_scan.py` and `main.py`; both baseline versions also return exit 1. No unrelated reformat.

## Scope judgment

Production footprint is 1,546 added lines (1,450-line investigation module plus 96 tracked insertions), above the project warning threshold. Accepted because the requested milestone combines bounded planning, strict schemas, filing retrieval/provenance, claim validation, deterministic reconciliation, persistence, rendering, CLI, and fail-closed financial safeguards; it remains one direct functional module with no new framework/service/provider hierarchy. Test footprint is 847 lines; prompts 59 lines.

## Residuals

- Section 1/2 docs referenced by `AGENTS.md` are absent from this checkout; repository contracts/tests were used.
- Live explanation is intentionally partial. The filing evidence identifies OpenAI investment accounting and the recapitalization dilution gain, but does not provide an unambiguous complete tax/component bridge for this multi-line finding.
