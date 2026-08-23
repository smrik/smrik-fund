# S3 — Persistence/application exactly-once proposal

Baseline: `736c239` (`codex/idempotent-approved-application`). Read-only scout; no source, test, config, or external-state changes.

## Recommendation

Keep the application engine pure and make the history append conditional on a durable candidate identity supplied by the identity/replay lane. Treat the CSV as the only durable state:

```text
reported P&L + persisted history
    -> latest version per adjustment identity
    -> approved current rows
    -> apply_adjustments(reported P&L, current rows)
```

Do not persist a second “applied” ledger. Rebuilding from the immutable reported frame on every run gives exactly-once economic effect; duplicate approved history rows are the bug to prevent.

## Current implementation evidence

- `src/smrik_fund/ingestion/adjustments.py:25-50` already resolves latest version first, then filters `approved`. This is the correct version/status rule and must remain unchanged.
- `src/smrik_fund/ingestion/adjustments.py:53-99` copies the reported P&L, groups approved rows by `target_line + period`, subtracts once per group, and recalculates subtotals. It is pure with respect to both inputs. It will correctly subtract twice if replay creates two approved IDs for the same economic item.
- `src/smrik_fund/main.py:101-117` loads the CSV and allocates the next numeric ID, but has no replay lookup. Run metadata is not a stable identity.
- `src/smrik_fund/main.py:557-714` allocates a new ID before validation/review and appends every auto-approved result as `version=1`. No existing candidate is consulted.
- `src/smrik_fund/main.py:757-783` concatenates approved rows and writes the CSV, then resolves/applies the whole history to the original `pnl`. This is the right application boundary once append deduplication is fixed.
- `src/smrik_fund/main.py:841-889` exposes `analyze` and `reconcile`; the documented `run` command is not present at this baseline. S3 should not expand the CLI to implement the missing command.
- `tests/test_adjustment_analysis.py:306-373` proves one approved fixture only, using a fresh temporary directory. It asserts one history row and adjusted R&D `100 - 10 = 90`, but never calls the same path again against that CSV.
- `tests/test_adjustments.py:25-50,127-168` proves latest-version resolution, immutability, aggregation, and order independence in isolation. It does not prove append/application replay.

The current code therefore has the exact failure mode: first run writes `A0001 v1 approved`; identical rerun allocates `A0002 v1 approved`; application groups both rows and subtracts `10 + 10`.

## Minimal persistence contract

Consume the identity lane’s stable, opaque candidate identity (for example `candidate_identity`). S3 should not reconstruct identity with fuzzy text or financial judgment. Persist that identity on every canonical approved/proposed/rejected version that participates in replay decisions.

Add one small direct helper at the application boundary (in `main.py`, or a small local function in `adjustments.py`; no persistence class):

```text
record_candidate(history, identity, economic_state, approved_row)
    -> (history, adjustment_id, append_action)
```

Required behavior:

1. Load the existing CSV once; validate identity/version uniqueness and fail closed on missing or ambiguous identity.
2. Exact identity + unchanged economic state (`target_line`, canonical `period`, amount, group/sub-item fields relevant to the candidate) returns the existing ID and appends zero rows. Ignore run ID, timestamp, model/prompt, and per-run artifact paths when comparing state.
3. Exact identity + materially changed economic state never overwrites the reviewed row. Append the next version under that same ID with `status=proposed` (or an explicit human-review state mapped to proposed), preserving the old version. Because resolution is latest-version-first, the changed state is not applied until a human decision appends an approved version.
4. A genuinely different durable identity gets a new `A####`; it remains a separate economic adjustment and is subject to the ordinary deterministic gate/duplicate checks.
5. A candidate with no stable identity, ambiguous identity, invalid target/period/amount, unresolved evidence, or non-approval outcome appends no canonical approved row and cannot affect the adjusted P&L.
6. The manifest may report `application_status=applied` for an unchanged candidate found already approved, but this display field is derived; it is not a second source of truth.

The helper must return the existing ID on an identical replay so candidate records remain stable. Do not use `_next_adjustment_id()` as the replay decision; retain it only for genuinely new identities.

Application remains:

```text
history_after_candidate_recording
    -> resolve_current_adjustments(history_after)
    -> apply_adjustments(original_reported_pnl, current)
    -> adjusted reconciliation (hard failure on FAIL)
```

Never apply to the previously written `adjusted_pnl.csv`; that would make a future rerun order-dependent.

## Focused persisted-CSV proof

Extend the existing integrated adjustment test rather than creating a persistence framework. Use `TemporaryDirectory()` as `output_root`, one frozen MSFT-shaped reported P&L, one filing fixture with stable accession/report period, and patched/saved Analyst/Reviewer results. The normal test must make no live LLM or EDGAR call. The exact same `history_path` must survive both calls.

### First run / identical rerun

Use the existing safe fixture shape (`Research and development`, one annual period, disclosed amount `10`, accepted/strong/low review, all deterministic gate inputs true).

1. Call `_run_adjustment_analysis(...)` once. Assert `adjustment_history.csv` has exactly one row (`A0001`, version 1, approved), adjusted R&D is `90`, reported fixture R&D remains `100`, and adjusted reconciliation has no `FAIL`.
2. Save the CSV bytes and adjusted target value. Call the same function a second time with the same persisted `output_root`, same filing/candidate/economic adjustment, and a different generated `run_id` allowed. Assert history row count remains one, ID/version/status/amount remain unchanged, and no second row is appended. Prefer asserting CSV bytes are unchanged when no append is needed.
3. Assert the second adjusted P&L is still `90` (not `80`), `resolve_current_adjustments(pd.read_csv(history_path))` returns one row, and the original reported P&L remains unchanged. Assert derived subtotal/reconciliation outputs remain stable.

This is the required proof that the first approval is appended exactly once and its magnitude is applied exactly once from the same persisted CSV.

### Changed-candidate safety

After the first approved run, replay the same durable identity with a materially changed amount (or target/period where the identity contract says the event is the same). Assert:

- `A0001 v1` remains byte-for-byte represented in history;
- no old row is edited and no new ID silently replaces it;
- exactly one new version is appended, with the changed state non-approved/proposed;
- latest-version resolution therefore does not apply the changed candidate until review; and
- no duplicate subtraction occurs.

Separately, a genuinely new durable identity must receive a new ID, not collapse into `A0001`; it may only enter current adjustments after its own gate approval.

### Non-approval safety

Run the same fixture with reviewer `revise`/`reject`, unresolved evidence, missing amount, or failed/unknown gate conditions. Assert no approved history row is appended and adjusted P&L equals reported P&L. If this is tested after an existing approval, assert the prior reviewed state is not overwritten and the changed version is not applied.

## Real/frozen-MSFT boundary

The deterministic replay test should use a faithful frozen MSFT boundary: real MSFT period/line naming and filing metadata shape, frozen P&L/evidence/candidate/reviewer outputs, and no network/model calls in `pytest`. `tests/msft_restructuring_gold.md` is useful for the existing human-review/unknown-amount case, but cannot prove auto-approval by itself; use a separately frozen quantified positive-magnitude fixture for the approved replay proof.

The real live boundary remains an explicit manual/integration invocation of the existing `analyze MSFT --adjustments` path after implementation. It is not a normal test and must not be used to establish idempotency because Analyst/Reviewer output and run artifact names are nondeterministic. The missing `run MSFT` command is out of S3 scope.

## Affected surfaces

- `src/smrik_fund/main.py`: add direct history identity/state lookup; change the candidate loop around current `:576-714`; avoid appending on identical approval; record non-approved changed versions safely; derive manifest application status from resolved current history.
- `src/smrik_fund/ingestion/adjustments.py`: preserve the existing latest-version-first resolver and pure application contract; only add validation needed for the persisted identity column if the implementation puts that check here.
- `tests/test_adjustment_analysis.py`: add the two-call same-`TemporaryDirectory` integration proof, changed-state proof, and non-approval replay proof.
- `tests/test_adjustments.py`: retain existing pure mechanics tests; add only a small resolver assertion if identity metadata changes the input contract.

Expected size: roughly 40–90 production lines and 100–180 focused test lines across the existing surfaces. No new service, repository, database, cache framework, event log, or CLI command is required.

## Invariants / non-goals

Invariants:

- `adjustment_history.csv` remains append/version history and is never edited in place.
- Same filing + same economic adjustment has one stable identity and one current approved version.
- Latest version is selected before status; rejected/proposed latest state removes the item from current application.
- Application always starts from reported source values; reported data and history inputs are not mutated.
- Approved magnitude is subtracted once per target line-period, with deterministic subtotal recalculation and adjusted reconciliation.
- Missing/ambiguous identity or mechanics fail closed; no synthetic identity or balancing adjustment.

Non-goals:

- crash-safe multi-process transactions/file locks;
- a generic persistence abstraction, database, event sourcing, or migration framework;
- LLM/evidence caching beyond the existing run artifacts;
- human-review UI or the missing `run` CLI command;
- fuzzy entity resolution, cross-company identity, new approval/materiality policy, or changing the application sign convention.

## Risks and proof gaps

- A plain CSV cannot guarantee exactly-once under concurrent writers or a process crash between write and output generation. The acceptance proof should explicitly be sequential rerun against one persisted file; atomic replace/locking is deferred unless deployment requirements expand.
- Existing legacy CSV rows without the new identity field cannot be safely replay-matched. With no committed `data/` history at baseline, fail closed for such rows in the new append path rather than inventing a backfill; direct pure-application tests may continue using their minimal history fixtures.
- Identity/state comparison must exclude generated run metadata, otherwise every rerun appears changed. Conversely, it must include every economic field whose change could alter accounting application, otherwise a changed amount/period could silently reuse approval.
- If candidate processing allocates IDs before validation, unresolved candidates can consume in-memory offsets. This is harmless when not persisted, but ID allocation should occur only at the new-identity append decision to keep replay proofs and diagnostics deterministic.
