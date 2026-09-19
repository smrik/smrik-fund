# R2 integrity recovery evidence

Scope: only A1 P1 repairs in the current worktree; no filing, adjustment, or
approved-state writes.

## Persisted S context

`resolve_segment_references` now checks source triplets (`value`,
`reported_value`, `numeric_value`), annual period metadata, and every exposed
derived field against direct deterministic formulas. The check compares only;
it never calls the segment builder, assigns replacement refs, or replaces
persisted values. `tests/test_filing_investigation.py` covers all canonical
source/derived fields plus a patch proving `build_segment_analytics` is not
called.

Focused result:

```
69 passed, 4 warnings, 15 subtests passed
```

The warning is the pre-existing Windows ACL failure writing `.pytest_cache`.

## Causal evidence

The validator now requires each detected causal wording/inflection to occur
verbatim in every cited excerpt. It covers `because of`, `linked to`,
`ties ... to`, `driving`, and `led to`; tests cover mismatched inflections and
the multi-excerpt rule.

Saved real MSFT scan replay (scan run `20260828T191302094324Z`, accession
`0001193125-26-323660`) resolved all affected refs without regeneration:

```
rank2: L01 L02 L03 S01 S03 S05 -> resolved all six
rank4: L11 S02 S04 S06       -> resolved all four
```

The saved pre-repair live result artifacts are correctly rejected by the
repaired validator because they contain unsupported causal paraphrases:

```
filing_investigation_02_rank2-live-mini-v6.json
  REJECT driver description: causal wording is not verbatim
filing_investigation_04_rank4-live-mini-v9.json
  REJECT interpretation: causal wording is not verbatim
```

This is intentional fail-closed behavior; the old artifacts were not edited
or rewritten. Exact causal wording acceptance and inflection rejection are
covered by focused tests.
