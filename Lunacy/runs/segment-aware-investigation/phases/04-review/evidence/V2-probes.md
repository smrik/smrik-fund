# V2 read-only probes

Scope: repaired source/test/live state; no source, test, config, live-artifact,
financial-state, or adjustment writes.

## V1 findings 1-4

- Fresh Luna rank 2 and rank 4 JSON/results revalidated against their saved
  evidence packets: both `PASS`, status `completed`, reconciliation
  `not_computable`, and `difference_is_reported_plug=false`.
- Synthetic `interpretation="The filing explains movement."` against the real
  rank-4 packet was rejected: `interpretation contains unsupported causal claim:
  wording is not verbatim`.
- Mutating a real persisted segment `period_start` to `2025-01-01` was rejected:
  `persisted segment period metadata drift for 2026-06-30 (FY)`.
- Fresh rank-2 plan contains only `S01`/`S03`/`S05` movement derivations; no
  `Revenue decreased` derivation is attributed to `L01`.

## New adversarial probes

Read-only in-memory mutations of every row in the real
`data/live-segment-enrichment-i1/MSFT/03_output/segment_analytics.csv`, then
`resolve_segment_references(..., expected_filing_accession="0001193125-26-323660")`:

```text
period_type=instant                 ACCEPTED
form_type=10-Q                      ACCEPTED
filing_date=2025-01-01              ACCEPTED
statement_role=other-role           ACCEPTED
unit=U_EUR                          ACCEPTED
currency=EUR                        ACCEPTED
source_url=https://evil.test/source  ACCEPTED
segment_label=Wrong label           ACCEPTED
```

These mutations are not compared to the filing or an immutable expected source
identity; only same-ref consistency and accession are checked. See
`filing_investigation.py:394-425,506-518`.
The actual saved-scan preflight also accepted uniform `period_type=instant`:
resolver/context checks `ACCEPT`; `format_analytical_pnl_for_scan(...) ==
scan_context` was `True`.

An unsupported sentence-initial narrative entity was also accepted:
`description="Contoso"` with a real cited packet returned `Contoso`; the
sentence-initial bypass is `filing_investigation.py:2452-2454`.

The fresh artifacts show the remaining scope presentation gap: `reference_resolution`
labels `L01/L02/L03/L11` as `consolidated`, but `observed_movement` omits
`scope`/`reference_type` for every L row; S rows carry both fields.
