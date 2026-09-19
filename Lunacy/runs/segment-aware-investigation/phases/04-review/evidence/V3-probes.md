# V3 compact evidence

Scope: fresh read-only review of R4 terminal state; no source, test, scan,
filing, financial-state, or adjustment writes.

## V2 recheck

- Targeted `pytest tests/test_filing_investigation.py -q -k
  'uniform_persisted_source_identity_drift_fails_closed or
  sentence_initial_unsupported_named_entity_fails_closed or
  mixed_observed_movement_keeps_consolidated_scope'`: **3 passed, 8 subtests**.
- R4 evidence still covers all eight uniform source-identity mutations,
  sentence-initial `Contoso`, and consolidated L-row scope/type.
- Current deterministic projection of the saved MSFT scan maps rank 2 to
  `L01/L02/L03=consolidated`, `S01/S03/S05=segment`; rank 4 to
  `L11=consolidated`, `S02/S04/S06=segment`.

## Residual fail-open probes

- A synthetic packet whose excerpts contain no `azure` accepted
  `interpretation='azure'` with refs `E1,E2`; the named-entity regex only
  matches title-case/acronym tokens (`filing_investigation.py:2496-2503`).
- With `Azure` present only in `E1`, `interpretation='The Azure movement is
  reported.'` with refs `E1,E2` was accepted; named-entity support uses `any`
  cited excerpt, contrary to the every-cited-reference contract.
- With excerpt `Revenue increased driven by Azure`, paraphrase
  `Revenue was driven by Azure` was accepted; causal validation checks the
  matched causal words and token presence, not a complete verbatim causal
  clause (`filing_investigation.py:2504-2523`).

## Live boundary

- Saved rank-2 evidence is the movement-only packet with five unquantified
  drivers; rank 4 has one broad unquantified driver and exact expansion support.
- Both saved artifacts are `completed`, use accession `0001193125-26-323660`,
  preserve `not_computable` reconciliation, and set plug false. R4's focused
  and full verification remain authoritative for the unchanged terminal code.
