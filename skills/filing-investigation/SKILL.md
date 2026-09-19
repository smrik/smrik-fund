# Filing investigation skill

Investigate one saved movement using only the supplied reported observation and
the frozen SEC 10-K evidence packet. Keep accounting mechanics deterministic:
Python builds the observation, validates evidence identity, extracts exact
period-paired disclosures, and reconciles the bridge. Models provide bounded
judgment only.

## Procedural protocol

The procedural arm has exactly three sequential calls:

1. Decompose the movement into filing-testable driver hypotheses. Cite only
   evidence IDs present in the packet.
2. Assess each hypothesis as supported, unsupported, or uncertain. Preserve
   qualitative drivers when the filing gives no amount; do not allocate a
   consolidated movement across categories without an explicit disclosure.
3. Produce the existing `FinancialInvestigationResult` schema as the final
   conclusion. Keep all narrative fields numeric-free, cite every specific
   claim, and leave unsupported or ambiguous amounts null.

The packet is closed-world: do not search, retrieve, or use general knowledge.
Do not propose adjustments, forecasts, valuation, or actions. Do not turn a
computed residual into a model-authored amount or plug. The runner injects
Python-owned quantified facts and reconciliation into the trace; the final
conclusion must not invent them.

Every reference must be an exact packet ID. Quantified fields are valid only
when one cited contiguous span contains an unambiguous amount, unit, and source
period and passes the existing filing-investigation validator. A
`respectively` construction with multiple amounts is not a safe single-driver
span; retain it as deterministic paired disclosure evidence instead.
