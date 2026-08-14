# smrik-fund

Small MSFT V1 pipeline for EdgarTools statements, analytical P&L, and source
reconciliation.

Run the current paths:

```powershell
smrik-fund analyze MSFT
smrik-fund reconcile MSFT
```

Outputs:

```text
data/MSFT/03_output/
  analytical_pnl.csv
  reconciliation_checks.csv
```

The statement loader uses EdgarTools' standard DataFrames and preserves source
periods, signs, missing values, and statement metadata. Reconciliation records
reported subtotals, differences, and skipped checks without creating plugs.

Set `SMRIK_EDGAR_USER_AGENT` to use your SEC user-agent string.
