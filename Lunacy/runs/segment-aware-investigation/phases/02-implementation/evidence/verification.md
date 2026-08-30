# I1 verification log

Environment: `C:\Users\patri\miniconda3\envs\ai-fund\python.exe`, `PYTHONPATH=src`.

## Automated

- `python -m pytest -q` -> **218 passed, 4 warnings, 45 subtests passed** (11.33s).
- `python -m ruff check --no-cache src/smrik_fund/ingestion/filing_investigation.py src/smrik_fund/ingestion/segments.py tests/test_filing_investigation.py tests/test_segments.py` -> **All checks passed**.
- `python -m compileall -q src` -> **passed**.
- `git diff --check` -> **passed**; pytest cache ACL warning is environmental.

## Live saved MSFT proof

Source scan: `data/live-segment-enrichment-i1/MSFT/03_output/analysis/analytical_scan_20260828T191302094324Z.json`; accession `0001193125-26-323660`; actual saved rank 2 and rank 4 findings.

| proof | resolved S refs | initial queries / refs | final status | accounting guard |
|---|---|---|---|---|
| [rank2 JSON](live-rank2/MSFT/03_output/analysis/filing_investigation_02_rank2-live-mini-v6.json) | S01,S03,S05 | Intelligent Cloud revenue increased; Productivity and Business Processes revenue increased; Revenue decreased / S01, S05, L01 | completed; 12 initial items; expansion `no_valid_queries`, 0 accepted | quantified/reconciliation `not_computable` (`no_exact_two_period_pair`); no plug |
| [rank4 JSON](live-rank4/MSFT/03_output/analysis/filing_investigation_04_rank4-live-mini-v9.json) | S02,S04,S06 | Operating income increased / S02,S04,S06,L11 | completed; 4 initial items; expansion `no_valid_queries`, 0 accepted | quantified/reconciliation `not_computable` (`no_exact_two_period_pair`); no plug |

Both artifacts retain `scope=segment`, accession identity, persisted source rows, and no hand-written causes. Rank 2 returned only evidence-backed disclosures; rank 4 used neutral unresolved wording when no specific bridge survived validation.
