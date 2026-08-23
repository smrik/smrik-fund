# User authority — stable economic-adjustment identity

Implement a bounded integrity correction. Architecture is settled; do not reopen it unless repository evidence disproves an assumption. Do not commit or merge.

## Preserve

- Sign primitive: positive `item_amount`; `increased_line -> -amount`, `decreased_line -> +amount`; `adjusted = reported + line_delta`; LLM never authors signed delta.
- State: latest approved version per adjustment ID is effective. Later proposed/rejected/human-review never displaces it. Later approved supersedes without stacking.

## Canonical separation

Economic identity only: `company + fiscal_period + target_row_key + item_key`, using the next version after `economic-adjustment-v1`. Identity version is independent of adjustment-history schema version.

Provenance/state must not influence identity: accession, evidence IDs/anchors/sections/locators/offsets/query/packet path/run/model/prompt/reason/uncertainty/topic/reviewer/origin/amount/direction/basis/sub-item prose. Keep these only as observations/history provenance when already useful.

`target_row_key` must reuse the actual deterministic unique analytical-P&L row selector. `standard_concept` alone is known non-unique for real MSFT. If no existing selector exists, derive the smallest local key from existing row-disambiguating fields; fail closed if insufficient. No taxonomy/registry/general mapping layer.

Analyst adds only `item_key: str | null`: lowercase hyphen slug, 1-6 short tokens, evidence-grounded specific subject+event. Reject generic keys (`adjustment`, `unusual-item`, `impairment`, `other-expense`), amount/year/rationale/target-padding. Null is valid and means `identity_unresolved`. Python computes identity.

Reviewer only checks that `item_key` is evidence-supported and not obviously generic, using existing verdict/concerns. Reviewer does not compare historical keys or resolve synonyms.

Proposal fingerprint is the smallest current state: amount + direction + basis. Evidence/accession/reason/sub-item/uncertainty/reviewer prose are excluded. Target/period may remain if removing them is not clearly simpler/safe.

## Conservative matching

- Exact key on same company/period/row => same identity, regardless of retrieval/provenance/prose.
- First valid key on an empty row-period => may mint one new canonical identity/ID.
- Any different key on an occupied row-period => `identity_unresolved`, even when a human would likely see a distinct event. No guess, ID allocation, history append, auto-approval, or P&L effect. Future manual attach/create workflow is out of scope.
- Exact means exact. No fuzzy/prefix/edit-distance/token/embedding/reason/amount matching.
- Same key on different period or target row => different identity.

`identity_unresolved` is an analysis/lifecycle outcome, not a history status. Trigger for null/invalid key, competing non-exact key on occupied row, and corrupted history unsafe for resolution. Preserve candidate/evidence/review in run artifacts and surface reason, but canonical history/effective approved state remain untouched.

Inspect `_possible_duplicate`: amount/reason/sub-item/evidence heuristics cannot decide identity. Demote to warning only if concretely useful; delete if redundant.

Legacy history missing new components remains fail-closed. Never guess/backfill, hash old evidence, or keep two active application identity schemes. No migration framework.

## Required deterministic proofs

1. Query/evidence refs/locators/offset drift => identical identity.
2. Different evidence excerpt => identical identity.
3. Sub-item prose drift with same key => identical identity.
4. Accession drift => identical identity.
5. Amount 900m -> 1.1bn => same ID, changed proposal/version path; v1 remains until v2 approval; no stacking.
6. First valid event on empty row-period may establish identity.
7. Null key => unresolved, no history/ID/application.
8. Existing `xbox-impairment`, candidate `gaming-asset-impairment` => unresolved; prior approval stays effective.
9. Existing `litigation-settlement`, candidate `restructuring-charge` => unresolved by deliberate V1 conservatism.
10. Same key, different period => different identity.
11. Same key, different target row => different identity.
12. Reviewer cannot accept generic `impairment` when evidence says Xbox impairment; prove contract with mocks if needed.
13. Preserve approved lifecycle regression and supersede-without-stack proof.

## Scope/complexity

No new service/class/repository/manager/provider/interface/DI/state-machine/fuzzy matcher/embedding/taxonomy/synonym/ontology/registry/database/migration/dedup/config engine/module for a few lines. No materiality, recurrence, retrieval/evidence format, UI/manual resolution, restatement/revalidation, EBITDA/tax, cross-company generalization, concurrency, or unrelated lint/test work.

Minimal docs update after proof: identity components, provenance exclusion, exact/first/occupied conservative rule; remove accession/evidence-anchor hashing descriptions without pretending future manual workflow exists.

Live MSFT: run twice only if credentials/network are actually available; exact-key repeats must converge, drift on occupied row must become unresolved. Do not fake proof.
