# S1 — stable candidate identity and replay

Baseline: `736c239` (`codex/idempotent-approved-application`). Read-only scout; no source/test changes.

## Recommendation

Keep two explicit concepts:

1. `economic_key`: immutable identity of the supported adjustment.
2. `candidate_state`: the small mutable state used to distinguish a replay from a revision.

For V1, build `economic_key` as a canonical, exact tuple:

```text
identity_version = economic-adjustment-v1
company          = normalized output ticker
filing_accession = exact packet accession
target_line      = exact candidate target line
period           = exact annual P&L column
sub_item         = exact candidate sub-item, or empty
evidence_anchors = sorted exact (source, section, locator) for cited packet items
```

`validate_evidence_refs(..., require_identity=True)` already exposes the packet metadata/items needed for this. Use the locator, not `E1`/`E2`, query order, run ID, evidence filename, topic, model, reason, or uncertainty. Require exactly one deterministic source-row match and a real period before constructing a key. Persist the canonical key (readable JSON is sufficient; no hash/provenance subsystem).

Do not put amount in the economic key. Amount and `amount_basis` are candidate state, for example:

```text
candidate_state = {amount, amount_basis}
```

This allows a deliberate amount revision to retain the economic adjustment ID and get a new history version, while prose/model changes do not turn an identical replay into a new adjustment. The exact candidate and review JSON still preserve that run's prose and metadata.

## Replay and collision contract

- Missing/ambiguous accession, evidence anchor, target row, period, or key fields: unresolved/human review; no history row and no application.
- No matching `economic_key`: allocate the next `A####` only after validation; on gate `auto_approve`, append version 1 and apply through the existing current-history path.
- Same key and same candidate state, with latest history status `approved`: replay. Reuse the existing ID/version, append zero rows, and apply the one persisted current adjustment to a fresh reported P&L. Mark the manifest record as replay/already persisted (do not claim a new approval).
- Same key and changed candidate state: state conflict, never silent overwrite. An explicit human/Analyst revision may append `version + 1` under the same ID; an unlabelled fresh run should fail closed to human review. A latest human/rejected/proposed state is never resurrected by an LLM replay.
- Different key (including accession, period, exact target, sub-item, or source locator change): new candidate identity; do not fuzzy-match or merge. If exact observable overlap exists, retain a possible-duplicate/human-review outcome.
- More than one history ID resolves to a key, or a legacy row has no persisted key: ambiguous/unknown identity; do not auto-approve or apply based on it.
- Identical keys produced twice in one run follow the same lookup; only the first can append. A state mismatch is a conflict, not a second adjustment.

History remains append-only. Latest-version selection must happen before status selection, preserving the existing `resolve_current_adjustments()` rule. A rejected latest row therefore removes application; an older approved row must not be resurrected.

## Current baseline and affected surfaces

The defect is concentrated in the integrated path:

- `src/smrik_fund/main.py:101-117` only loads history and creates a fresh ID from `A####` values.
- `main.py:565-579` assigns an ID to every candidate before recognition.
- `main.py:679-765` appends every approved candidate without checking identity, so a replay creates `A0002` and `apply_adjustments()` sums both rows.
- `main.py:767-779` correctly derives current approvals and applies them to the supplied reported P&L; it should remain unchanged.
- `src/smrik_fund/ingestion/filing.py:389-497` already validates identity and returns stable item locators; no fuzzy retrieval or new filing abstraction is needed.
- `src/smrik_fund/ingestion/adjustments.py:25-50` already implements latest-version-then-status resolution; do not alter its accounting semantics.
- `AnalystCandidate` (`adjustment_analysis.py:41-56`) need not gain an ID; identity is derived after the packet and deterministic P&L checks.
- Add one focused persisted-history integration test (prefer a new `tests/test_idempotent_approved_application.py`, or the existing integrated test module): invoke the real integrated function twice with the same frozen filing/candidate/review and the same temporary output root, then inspect the same CSV and both adjusted outputs.

The minimal production change is local lookup/key/append branching in `main.py`, plus only a small filing-parser change if a stable parsed-anchor helper is genuinely needed. Expected size: one or two production files, one focused test, roughly 100–160 new lines. Do not change `apply_adjustments()` or introduce a repository/service/deduplication framework.

## Required proof/invariants

- Same accession + same exact economic anchors => stable key and stable `adjustment_id` across runs.
- Distinct anchors never collapse; same-key state conflicts never overwrite reviewed state.
- Candidate recognition uses only exact durable source identity; no financial judgment/fuzzy similarity in Python.
- First auto-approved run: one history row (`A0001`, v1), adjusted target `reported - amount`.
- Identical replay: history row count and max version unchanged; adjusted target remains exactly `reported - amount`, not `reported - 2*amount`.
- Reported input frame remains unchanged; each run starts from that reported frame.
- Human-review, rejected, unresolved, missing/ambiguous identity, and legacy-unknown paths remain unapplied and history-safe.
- Multiple genuinely distinct approved adjustments on one line-period remain separate and continue to sum once in the existing engine.

## Risks and non-goals

Evidence IDs are packet-local and can reorder; using their locators is essential. Filing text/statement labels can change; fail closed rather than normalize or fuzzy-match. Two indistinguishable proposals citing the same exact anchors cannot be safely separated; surface a collision for human review. Amount changes need an explicit revision path so a changed LLM result cannot silently replace a human decision. Existing history created before this key exists cannot prove replay identity and must be treated as unknown.

Out of scope: fuzzy/semantic entity resolution, embeddings, generic deduplication, cross-company/global IDs, cryptographic provenance, event sourcing, reviewer caching, human-review UI, new approval policy, or changing accounting/application formulas.
