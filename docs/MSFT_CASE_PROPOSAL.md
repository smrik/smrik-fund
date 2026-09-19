# MSFT development acceptance case — selected 2026-09-06

Purpose: fix a reproducible interim-period case that exercises annual, YTD, TTM
and balance-sheet mechanics. Patrik authorized agent-selected dates for development
and testing on 2026-09-06. The agent selected the convention below. This date
decision is not yet a complete frozen source set, numerical forecast, or backtest.

| Setting | Selected development convention |
| --- | --- |
| Company | Microsoft; MSFT; CIK 0000789019 |
| Information cutoff | 2026-04-30; exclude later-published material |
| Financial measurement date | 2026-03-31 |
| Valuation date | 2026-03-31, informed by the later April filing |
| Historical annual flows | FY2023, FY2024, FY2025; July–June fiscal years |
| Current YTD flows | 2025-07-01 through 2026-03-31 |
| Comparable YTD flows | 2024-07-01 through 2025-03-31 |
| TTM flows | 2025-04-01 through 2026-03-31, when components are compatible |
| Opening forecast balance sheet | Actual included 2026-03-31 snapshot |
| Separate forecast remainder | 2026-04-01 through 2026-06-30 |
| Full forecast years | FY2027–FY2036; five detailed years plus linked transition |
| Reporting currency | USD; retain actual source units and scale |
| Display units | USD millions; shares/percentages explicitly separate |
| Initial product reasoning limit | EUR 5 ceiling from the build guide; no paid calls made |

The reporting-date valuation uses information published after that date. Label it
a later-informed analytical exercise. It cannot establish historical investability.
Discount timing and financial policies remain later required decisions; this
proposal selects no WACC, growth, useful life, tax, lease, SBC or funding treatment.

Alternative already offered: April 30 valuation, with an explicit estimate of the
intervening month. Do not invent that estimate or discount actual YTD as future.

## Observed local source inventory

Source: `data/MSFT/01_source/edgar/manifest.json`, inspected 2026-09-05. These are
local manifest observations, not newly retrieved SEC verification. Publication
dates are date-only here; exact timestamps must be retained when available.

| Accession | Report date | Filing date | Cutoff treatment |
| --- | --- | --- | --- |
| 0000950170-25-100235 | 2025-06-30 | 2025-07-30 | Candidate annual source |
| 0001193125-26-191507 | 2026-03-31 | 2026-04-29 | Candidate latest interim source |
| 0001193125-26-027207 | 2025-12-31 | 2026-01-28 | Candidate interim source |
| 0001193125-25-256321 | 2025-09-30 | 2025-10-29 | Candidate interim source |
| 0000950170-25-061046 | 2025-03-31 | 2025-04-30 | Candidate comparative source |
| 0000950170-25-010491 | 2024-12-31 | 2025-01-29 | Candidate comparative source |
| 0000950170-24-118967 | 2024-09-30 | 2024-10-30 | Candidate comparative source |
| 0001193125-26-323660 | 2026-06-30 | 2026-07-29 | Excluded: after cutoff |

The cache's eight text filings do not establish complete native statement/XBRL
availability. Earlier annual filings are still needed for older balance-sheet
snapshots. Source selection must preserve amendments, recasts and alternatives;
comparable facts and segment definitions have not yet been certified. A four-
quarter check is independent only to the extent its source inputs are independent.

## Authorized access

The supplied AGENTS instructions require explicit permission to read credential
files. On 2026-09-06 Patrik explicitly approved using `.env`. The application may
load required credentials for source retrieval and the EUR 5-bounded product
analysis without displaying contents. Offline tests should continue to use
`PYTHON_DOTENV_DISABLED=1` when credentials are unnecessary. Do not request this
permission again or expose secrets in output.
