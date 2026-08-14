# MSFT EdgarTools Output Shape

## Run

Observed on 2026-08-11 with EdgarTools 5.45.1.

- Ticker: `MSFT`
- CIK: `789019`
- Form: `10-K`
- Accession: `0001193125-26-323660`
- Filing date: `2026-07-29`
- Period of report: `2026-06-30`
- View: `standard`
- Command: `python scripts/inspect_msft_edgartools.py`

## Observed statement shape

All three statement DataFrames use a `RangeIndex` with no index name. The first
three columns identify the row:

```text
concept, label, standard_concept
```

The remaining columns contain reported periods and EdgarTools metadata.

| Statement | Shape | Reported period columns |
| --- | ---: | --- |
| Income statement | 21 rows x 19 columns | `2026-06-30 (FY)`, `2025-06-30 (FY)`, `2024-06-30 (FY)` |
| Balance sheet | 40 rows x 18 columns | `2026-06-30`, `2025-06-30` |
| Cash-flow statement | 39 rows x 19 columns | `2026-06-30 (FY)`, `2025-06-30 (FY)`, `2024-06-30 (FY)` |

The income statement and cash-flow statement use duration periods and provide
three annual columns. The balance sheet uses instant periods and provides two
comparative dates. EdgarTools does not return a third balance-sheet date in
this MSFT standard view.

The statement metadata columns are:

```text
level, abstract, dimension, is_breakdown,
dimension_axis, dimension_member, dimension_member_label, dimension_label,
balance, weight, preferred_sign,
parent_concept, parent_abstract_concept
```

Breakdown rows can have a missing `standard_concept`. For example, product and
service revenue rows are present beside the total revenue row.

## Signs and missing values

These counts cover numeric values in each reported period column. They are
observations only; no values were changed.

| Statement / period | Negative | Positive | Zero | Missing |
| --- | ---: | ---: | ---: | ---: |
| Income 2026 | 0 | 19 | 0 | 2 |
| Income 2025 | 1 | 18 | 0 | 2 |
| Income 2024 | 1 | 18 | 0 | 2 |
| Balance 2026 | 1 | 33 | 0 | 6 |
| Balance 2025 | 1 | 33 | 0 | 6 |
| Cash flow 2026 | 19 | 13 | 2 | 5 |
| Cash flow 2025 | 16 | 17 | 1 | 5 |
| Cash flow 2024 | 16 | 18 | 0 | 5 |

The output contains both positive and negative reported values. Task 2 must
preserve these signs and must not treat missing values as zero.

## Hierarchy and XBRL metadata

The standard statement frames expose hierarchy information directly:

- `level` indicates row depth.
- `abstract` identifies abstract/header rows.
- `parent_concept` and `parent_abstract_concept` identify the hierarchy.
- `dimension` and `is_breakdown` identify dimensional or breakdown rows.
- `balance`, `weight`, and `preferred_sign` provide sign and calculation metadata.

The raw XBRL facts DataFrame contains 1,758 rows and 67 columns. Important
fields include:

```text
concept, context_ref, value, unit_ref, numeric_value,
period_type, period_start, period_end, period_instant,
fiscal_period, fiscal_year, is_dimensioned,
balance, preferred_sign, statement_type, statement_role, weight
```

It also contains dimension/member fields and many axis-specific columns. A
total of 948 raw facts have `is_dimensioned=True`. The raw facts therefore
contain more than the three primary statement tables and must not be treated
as a simple one-row-per-line-item table.

## Duplicate observations

There were no duplicate statement rows when checked by concept, label,
standard concept, and all reported period columns.

The raw facts contained 148 repeated concept/value/unit/period rows when
`context_ref` and dimensions were excluded from the check. Examples included
DEI facts and `us-gaap:NetIncomeLoss` facts. These are duplicate-risk signals,
not proof that the facts are interchangeable: different contexts and
dimensions can explain repeated values.

## Implications for Task 2

1. Keep the three EdgarTools statement DataFrames as the source view.
2. Handle duration statements and instant balance-sheet statements separately;
   do not assume one shared three-period column layout.
3. Preserve `level`, abstract, parent, balance, weight, preferred-sign, and
   dimension metadata in any derived view.
4. Do not assume `standard_concept` is populated for breakdown rows.
5. Preserve reported signs and missing values.
6. Do not deduplicate raw facts using concept and period alone. Context and
   dimension fields are part of the fact identity.

No mapping system, analytical P&L, or source-value transformation was added in
this task.
