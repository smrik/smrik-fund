# R4 verification evidence

Scope: V2 findings 1–3 only. No commit, merge, financial-state, filing, or
adjustment writes.

## Focused adversarial probes

- Loaded the real persisted `data/live-segment-enrichment-i1/MSFT` segment
  artifact: 18 rows, 6 refs, and an 18-row immutable source-identity
  snapshot.
- Uniform in-memory mutations of `period_type`, `form_type`, `filing_date`,
  `statement_role`, `unit`, `currency`, `source_url`, and `segment_label` all
  rejected before S-ref resolution with
  `persisted segment source identity drift`.
- The saved-scan preflight also rejects uniform `period_type=instant` through
  the same snapshot check while the formatted scan context remains unchanged.
- Sentence-initial `Contoso` is rejected as an unsupported named entity;
  ordinary starts (`The`, `A`) remain accepted by the existing generic-word
  allowlist.
- Mixed `L##`/`S##` observed movement now carries explicit
  `reference_type=consolidated`, `scope=consolidated` on L rows; S rows remain
  `reference_type=segment`, `scope=segment`.

## Fresh R3 artifact revalidation

Current code revalidated both saved Luna artifacts against their saved packets,
the current P&L, and the current persisted segment artifact:

```text
rank=2 status=completed accession=0001193125-26-323660
refs=L01 L02 L03 S01 S03 S05 resolved=6 drivers=5
reconciliation=not_computable plug=False
current_L_scope=[(L01, consolidated, consolidated),
                 (L02, consolidated, consolidated),
                 (L03, consolidated, consolidated)]

rank=4 status=completed accession=0001193125-26-323660
refs=L11 S02 S04 S06 resolved=4 drivers=1
reconciliation=not_computable plug=False
current_L_scope=[(L11, consolidated, consolidated)]
```

The historical R3 JSON files predate the new L-row fields; the current
deterministic projection above is the revalidated final output contract.

## Automated checks

```text
pytest tests/test_filing_investigation.py -q
67 passed, 39 subtests passed

pytest tests/test_filing_investigation.py tests/test_segments.py tests/test_analytical_scan.py -q
86 passed, 39 subtests passed

pytest -q
229 passed, 84 subtests passed

ruff check --no-cache <changed source and tests>
All checks passed
python -m compileall -q src
passed
git diff --check
passed
```

Known environment noise: pytest cache ACL warnings and EdgarTools’ pre-existing
locale-corrupted cache cleanup warning; neither changed the checks above.
