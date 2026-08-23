# Decisions

## D1 — multi-occurrence discovered queries

Authority: user requires discovered Xbox topic to produce exact filing evidence without manual seeding; evidence integrity outranks selecting a convenient hit.

Decision: discovery-originated queries are literal, not arbitrary regex. One bounded retrieval pass may preserve every exact occurrence (with stable IDs, source offsets/lines, accession and honest EdgarTools locators) rather than failing merely because the same phrase appears in several filing passages. No relevance ranking or best-hit selection. A small hard evidence-item cap may fail an excessively broad topic closed. Existing fixed regex wrapper may remain for direct legacy compatibility but is forbidden from the real discovery branch.

Reason: all exact occurrences are source evidence; retaining them avoids both silent selection and a retry/query-expansion loop while satisfying the bounded exact-evidence chain.

## D2 — terminal boundedness and out-of-scope gate policy

Decision: always persist the discovery result even when it contains zero topics. Add a small explicit maximum on candidates returned by each topic-resolution call and fail that topic closed before Reviewer fan-out when exceeded.

Decision: do not complete currently unknown risk-gate inputs or add approved-rerun matching/deduplication. The user explicitly excludes new approval and materiality policy; real unsupported discoveries already route conservatively to human review and do not append history. Record these existing limitations as deferred.

Reason: zero-topic auditability and finite Reviewer fan-out are direct bounded-workflow requirements. Approval-policy completion and canonical matching are separate milestones.

## D3 — remove obsolete seeded runtime fallback

Decision: remove the no-filing/frozen-packet/manual-seed branch from the integrated `analyze --adjustments` runtime and require the actual EdgarTools filing carried by the analytical P&L. Keep the established parameterized exact retrieval implementation; direct legacy wrapper compatibility may remain only if it adds no runtime branching.

Reason: the active V1 contract is actual-filing discovery. Retaining two orchestration paths duplicates logic, preserves a hidden seeded path, and materially weakens the requested simplicity/independence result.
