# I1 proposal judgment

Date: 2026-08-29

- P1 is the core: resolve every affected ref from persisted analytical rows, fail closed on stale or ambiguous refs, and carry the resolved segment scope through the existing plan, retrieval, observation, disclosure, and reconciliation flow.
- P2 is adopted where it strengthens the same contract: preserve source-period/fact/context identity and persisted derived context; use metric-qualified segment queries and exact pair matching; keep L-only behavior compatible.
- P3 is adopted only for safety boundaries: segment evidence cannot explain consolidated mix or profitability without exact support, and no balancing plug/recomputed segment context is introduced. Its blanket prohibition on safe scope-labeled bridge use is rejected as unnecessarily lossy.
- Result: one strict persisted-row resolver plus existing flow threading; no new retriever, artifact, provider, or forecast/valuation role.
