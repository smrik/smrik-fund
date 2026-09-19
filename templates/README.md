# Editable company model

Open **company-model.xlsx** in Microsoft Excel. It contains BBWI example data so
you can see and calculate the model while editing. New runs replace those values
with the selected company's sources and use only your forecast edits.

1. Insert rows within **Income, BalanceSheet, CashFlow, Assets, WorkingCapital or
   Stub**. Keep the existing rows, their order and the first three header rows.
2. Edit forecast formulas and row labels. Add assumptions beside the calculations
   that use them. Use ordinary A1 formulas referencing these model tabs or Inputs.
   Fill your formula across all forecast years that should use it. Stub is a
   separate partial-year forecast; changing full years does not change Stub.
3. Save and close Excel. Validate from the project directory:

   ```powershell
   .venv/Scripts/python.exe -m smrik_fund.workbook_template check
   ```

4. Launch a new analysis from the website or CLI. The default template is loaded
   automatically. Existing outputs remain unchanged. Each run freezes its own
   `template.xlsx` and `template.json`; model/snapshot files record the edits and
   hashes. The workbook's Review tab identifies the template used.

Keep **company-model.json** beside the workbook. This is the original contract,
not an assumptions file to edit. Excel's `_smrik_...` defined names anchor the
original rows and follow row insertions. Do not delete or change those names.

Source history, Inputs, DCF valuation mechanics and audit tabs remain generated.
Edit forecast assumptions on the statement tabs; changing protected source or
audit cells is rejected. History length and Inputs references adapt to the next
ticker. A reference to an unavailable historical period or source input stops
the run. Edited templates also require the same forecast horizon as their example;
annual-only cases can need their own template. The model must retain its required control links and accounting checks.
Changing economic logic still requires financial review.

Supported edits are cell formulas, values, labels and number formats on changed
forecast cells. Extra sheets, deleted/reordered original rows, moved columns,
arrays/data tables, external links, macros and indirect/dynamic references are
outside this first version. Other visual formatting is regenerated consistently.
This is an editable forecast template, not support for arbitrary Excel models.

## Example

Insert two rows before EBITDA: an additional operating expense and its percentage
of sales. Set the percentage to `0.005`, calculate expense as revenue times that
percentage, and subtract it in EBITDA. The statements and DCF then recalculate.
The acceptance test does this in native Excel and reuses the resulting template
on BBWI and NVDA, which have different amounts of available historical data.
The example expense is **only in test copies**, not in the shipped default.

## Where the LLM acts

```
SEC sources -> company model + your template
            -> optional paid analyst proposes numeric controls
            -> formula engine calculates statements and DCF
            -> optional independent reviewer accepts / revises / rejects
            -> recalculation, native Excel verification, versioned output
```

The LLM currently changes supported numeric assumptions. It sees the template
edits and calculated formulas; it cannot insert rows or rewrite formulas itself.
An accepted revision is recalculated and reviewed again. Paid analysis remains
an explicit command; ordinary screening and free model runs make no LLM calls.
