# Evaluation harness

The loop this exists to close:

```
change the product  ->  re-execute frozen cases  ->  read the delta  ->  decide
```

Harness health is independent of product results. A run where every case fails
is a healthy harness reporting a real product state. Do not repair product
behaviour to make the benchmark look better.

## Running it

```bash
smrik-fund eval --preflight tests/test_evals.py
```

`smrik_fund.main` has no `__main__` guard, so `python -m smrik_fund.main` exits
silently without running anything. Use the installed `smrik-fund` script, or
invoke the Typer app directly:

```bash
python -c "import sys; from smrik_fund.main import app; sys.argv=['smrik-fund','eval']; app()"
```

| Flag | Effect |
|---|---|
| `TICKER` | Positional; restrict to one ticker |
| `--suite` | `development`, `regression`, or `holdout` |
| `--case` | Run a single case id |
| `--baseline` | Iteration JSON or run directory to diff against |
| `--no-judge` | Mechanical checks only; no judge calls |
| `--max-calls` | Hard ceiling on live product calls |
| `--preflight` | Pytest target run once per invocation, not per case |
| `--output-root` | Artifact root, default `data/evals` |

Each case costs **2 product model calls** (query expansion, then synthesis) plus
**1 judge call** when it reaches the judge.

## What a case pins

A case freezes the *inputs* needed to reproduce one execution: ticker,
accession, filing period, source filing text, the analytical scan, the
analytical P&L, segment analytics, and the finding identity — each with a
SHA256.

It does **not** pin the product's output. `reference_investigation` records a
prior artifact for diagnosis and is deliberately excluded from the definition
hash. Folding an output hash into the definition makes every comparison
`NON_COMPARABLE` the moment the product changes, which silently disables the
one thing the harness is for.

The filing text comes from the frozen snapshot rather than a network fetch, so
two runs of the same case differ only by model sampling — not by source drift.

## Result states

These stay separate on purpose.

| State | Meaning |
|---|---|
| `CASE READY` / `CASE BLOCKED` | Whether frozen prerequisites exist |
| `COMPLETED` | Product ran and returned a result |
| `VALIDATION_REJECTED` | Model produced output; deterministic validation rejected it |
| `EXECUTION_ERROR` | Execution did not complete |
| `PRODUCT VALID` | `COMPLETED` **and** every critical check passed |
| `JUDGED` → `PASS` / `PARTIAL` / `FAIL` | Qualitative verdict, valid cases only |
| `JUDGE_SKIPPED` | A critical mechanical failure gated the judge |
| `JUDGE_ERROR` | The product was valid; the judge itself failed |

A judge failure never converts a mechanically valid product result into a
product failure. It means qualitative evaluation is unavailable for that run.

## Mechanical checks

Every check is evaluated **independently**. A single validator is never reported
as several checks — that makes one signal look like several.

| Check | Critical | Asserts |
|---|---|---|
| `source_integrity` | yes | Every frozen input matches its recorded hash |
| `result_schema` | yes | Output parses as `FinancialInvestigationResult` |
| `evidence_refs` | yes | Every cited ref exists in the evidence packet |
| `numeric_grounding` | yes | Every stated figure reconciles to the frozen analytics |
| `amount_basis` | yes | Quantified drivers carry period, unit, and span |
| `product_validator` | yes | The product's own validator verdict, as one check |
| `quantification` | no | Count of unquantified drivers |
| `expansion` | no | Whether query expansion produced accepted queries |

`numeric_grounding` carries the segment-margin contract. The deterministic
pipeline already computes `operating_margin` and its bps change into
`segment_analytics.csv`, so a margin the model states must match that
computation rather than being re-derived or invented.

### `NOT_APPLICABLE`

A check that had nothing to examine reports `NOT_APPLICABLE`, never `PASS`.

This matters more than it sounds. The product currently emits outputs with no
amounts and no figures at all, so `numeric_grounding` and `amount_basis` would
otherwise report a passing critical check while examining zero items — which
reads as evidence of correctness when it is the absence of evidence.
`NOT_APPLICABLE` does not gate the judge, and the Markdown summary lists these
separately from real passes.

## Rejected output

When validation rejects a result, the raw structured model output is written to
`rejected_output.json`, marked `UNTRUSTED` / `REJECTED`.

This needs no product-side diagnostic hook. The harness injects a
`RecordingClient` into the product's existing `client` parameter, which captures
the parsed output *before* the product's validators run. The same proxy provides
per-stage call accounting and optional budget enforcement.

Rejected output is never scored, never shown to the judge, and never becomes
product state.

## Comparison

```bash
smrik-fund eval --baseline data/evals/<earlier-iteration>
```

Comparison reports deltas only — per case and per rubric dimension, each marked
`improved` / `regressed` / `unchanged` / `unavailable`. It never decides whether
a change should be kept. Conflicting dimensions are reported as they are:

```yaml
margin_reuse:        FAIL -> PASS      # improved
evidence_grounding:  PASS -> PARTIAL   # regressed
movement_scope:      FAIL -> FAIL      # unchanged
```

KEEP or REVERT is a human or repair-agent decision.

If the definition hash differs from the baseline's, the result is
`NON_COMPARABLE` and no deltas are computed. The definition hash covers case
inputs, rubrics, check definitions, the judge prompt and schema, and the judge
model plus reasoning effort.

## Output layout

```
data/evals/
  iterations/<id>.json          # ledger, one record per iteration
  iterations.md                 # compact human index
  <id>/
    iteration.json              # authoritative record
    summary.md                  # human/agent-readable summary
    preflight.json
    comparison.json             # when --baseline was given
    cases/<case_id>/
      case.json
      payload.json              # full product payload
      judge_input.json
      judge.json
      rejected_output.json      # only when validation rejected the output
      traceback.txt             # only on execution error
      product/                  # the product's own writes, isolated here
```

Each case writes only inside its own directory. The product's `output_root` is
redirected there, so an evaluation never mutates `data/<TICKER>/03_output`.

## Judge

Frozen: `gpt-5.6-sol`, reasoning effort `high`, native structured output,
default sampling. Deliberately a different model from the product.

Changing the judge model or effort changes the definition hash, which makes
prior baselines `NON_COMPARABLE` rather than silently comparable.

Ordinal verdicts only. There is no numeric composite score: we care why an
output improved or regressed, not whether a synthetic number moved from 7.4
to 7.8.

## Blocked coverage

AMZN and GOOGL are recorded as `CASE BLOCKED` / `UNAVAILABLE` with a reason, a
missing prerequisite, and the expected workflow to unblock them. They are
visible in every run rather than silently omitted.

To promote one to `READY`: ingest the filing, build the analytical P&L, run the
analytical scan, freeze a finding, then replace the probe with a full case
definition.
