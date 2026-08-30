# V1 read-only probes

- Current `.venv\Scripts\python.exe -B` validation rejects the saved completed
  rank-2 artifact at `investigation.result.disclosed_drivers[1]`: its `because
  of` wording is not present in cited E3 (`driven by`).
- The same validator rejects saved completed rank-4 at
  `investigation.result.interpretation`: `ties ... to` is not present in cited
  E1 (`driven by`).
- A synthetic cited packet containing `The filing reports movement.` accepts
  `interpretation=The filing explains movement.`. The broad causal regex lists
  `explain`, but the exact causal regex omits it; all other tokens are generic
  and therefore the claim passes.
- In-memory real MSFT segment replay with S05 `period_start` changed from
  `2025-07-01` to `2025-01-01` resolves and exposes the mutated date. The
  validator only checks prior-year ordering/year, not exact persisted start.
- Real scan replay inputs: `20260828T191302094324Z`; accession
  `0001193125-26-323660`; segment reconciliation is PASS for all six rows.
