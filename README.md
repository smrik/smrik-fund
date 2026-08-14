# smrik-fund

Parse the latest 10-K for one ticker:

```powershell
smrik-fund parse MSFT
```

The command writes machine-readable files:

```text
data/MSFT/
  01_source/edgar/
    filing_index.csv
    manifest.json
    filings/<accession>.txt
  02_processing/edgar/
    facts.csv
    coverage.json
  03_output/
    analytical_pnl.csv
```

`facts.csv` has one row per numeric XBRL fact. It keeps both the original
`concept` and the cross-company `standard_concept`.

The command also prints the three standard-view statement dimensions and the
fact count.

Code structure:

- `ingestion/statements.py` is the small public interface.
- `ingestion/parser.py` loads EdgarTools and builds the statements.
- `ingestion/facts.py` creates one normalized row per numeric fact.
- `ingestion/artifacts.py` writes the CSV, JSON, and filing files.

Set `SMRIK_EDGAR_USER_AGENT` to use your SEC user-agent string.
