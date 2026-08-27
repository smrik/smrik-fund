# G1b final-state re-gate — deterministic analytical base

## Snapshot

- Baseline `f2fd305`; current final diff is limited in-scope to `src/smrik_fund/ingestion/statements.py` (`+193/-46`, `+147` net) and `tests/test_analytical_pnl.py` (`+140/-0`). No edits made by G1b.
- Exact Sol inspection slices: source guards/eligibility `statements.py:131-229`; canonical `prepare_pnl` metric path `:235-367`; tests `test_analytical_pnl.py:118-207` and `:209-353`.
- Final bounded check (no broad suite): `PYTHONPATH=src; & 'C:\Users\patri\miniconda3\envs\ai-fund\python.exe' -m pytest tests/test_analytical_pnl.py -q -p no:cacheprovider -k 'excludes_eps_and_share_common_size_metrics or calculates_guarded_changes_and_two_year_cagr'` -> **2 passed, 8 deselected, 3 warnings**.

## Acceptance mapping

1. Positive growth + absolute YoY: `statements.py:179-203`; tests `:213-222`.
2. Zero prior growth null, absolute retained: tests `:237-246`.
3. Negative-to-negative growth null, absolute retained: tests `:224-230`.
4. Sign-change growth null, absolute retained: tests `:231-235`.
5. Percent of revenue: `statements.py:298-310`; tests `:191-195`, `:280-285`.
6. Percent-of-revenue bps: `statements.py:311-319`; tests `:286-291`.
7. Positive-endpoint two-year CAGR: `statements.py:287-296`; tests `:213-222`.
8. Zero/negative/missing CAGR endpoints null: tests `:224-235`, `:248-259`, `:261-271`.
9. Gross/operating margin bps: `statements.py:321-365`; tests `:325-347`.
10. Missing values remain null: `statements.py:179-229`; tests `:261-271`.
11. EPS/share rows lack common-size metrics: `statements.py:161-176`; tests `:293-323`.
12. Reported values/source frame unchanged: `statements.py:249-266`; tests `:118-152`.

## Re-gate findings

- **A1 P1 resolved:** `_text()` strips separators at `statements.py:155-158`; the label-only `Shares outstanding` fixture is present and asserts null level/bps fields at `test_analytical_pnl.py:293-323`. Fresh bounded check passes.
- **G1 missing-CAGR proof gap resolved:** explicit null assertion for missing FY26 endpoint is at `test_analytical_pnl.py:261-271`; R2 final matrix reports 10 analytical tests, 25 adjustment/reconciliation tests, 142 full-suite tests, Ruff clean, and `git diff --check` clean (`phases/phase-4-gate/repair-2-report.md:8-21`).
- **Concrete residual / acceptance tension:** ignored `data/MSFT/03_output/analytical_pnl.csv` is still 21 rows x 34 columns with zero new-metric headers; current in-memory `prepare_pnl` shape is 21 x 65. Task-2’s “analytical_pnl.csv written” acceptance is therefore not evidenced by the persisted artifact. Refresh was explicitly out of scope (`phases/phase-3-simplicity/repair-report.md:41-45`).
- Real-MSFT final evidence remains: input 21 x 19, output 21 x 65 (FY26/FY25/FY24), source unchanged, reconciliation 12/12 PASS (`phases/phase-4-gate/repair-2-report.md:23-27`; detailed sample `phases/phase-2-implementation/evidence/terminal-verification.md:31-63`).
- Existing unrelated dirty files and annotation/run artifacts remain preserved. Gate decision is not issued; G2/Sol owns PASS / DO NOT MERGE.
