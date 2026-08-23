# Exact manifest comparison

Compared without changing either live manifest:

- old: `data/MSFT/03_output/analysis/adjustment_run_20260822T145101565886Z.json`
  (`SHA256 1C80E0C62DF22E57DC1633DDDBC476418860EEC8F7A766772B3184D587E64005`)
- new: `data/MSFT/03_output/analysis/adjustment_run_20260822T183907711663Z.json`
  (`SHA256 8A73B6EE0D30660AA364F9641C0B320EF04614E48CD4271D820CEC89AA088CBA`)

Both runs are MSFT, use filing accession `0001193125-26-323660`, report 12
passed / 0 failed / 0 skipped reported checks and adjusted checks, and have
`reported_equals_adjusted=true`. The old run has 5 retained topics and 8
candidate records; the new run has 4 retained topics and 9 candidate records.
No manifest or canonical data file was modified.

## Candidate-by-candidate comparison

The old run is shown first in each row. Identity is the parsed
`candidate_identity`; an empty ID means no canonical history row was written.

| old candidate | new candidate | economic identity / target row key | status, duplicate, application | meaningful change |
|---|---|---|---|---|
| OpenAI recapitalization gain; FY2026; `openai-recapitalization-dilution-gain`; `label:Other income (expense), net`; amount 6.5bn, `increased_line`; identity_unresolved; human_review/not_applied | OpenAI investment gains and losses #1; FY2026; `openai-investment-dilution-gain`; `standard_concept:NonoperatingIncomeExpense`; A0024; amount 6.5bn, `increased_line`; new; human_review/not_applied | Same economic topic and amount, but the key is refined and row selector is concept-stable. Both reviewer `revise`; duplicate is unknown in old and false in new. | New run allocates A0024 because old history contains only legacy/proposed rows. No P&L effect. The evidence still does not quantify dilution gain separately from the 6.5bn aggregate OpenAI gain. |
| no old counterpart | OpenAI investment gains and losses #2; FY2025; `openai-investment-net-loss`; `standard_concept:NonoperatingIncomeExpense`; A0025; amount 4.8bn, `decreased_line`; new; human_review/not_applied | New evidence surfaces the FY2025 net loss. Reviewer `accept`; duplicate false; materiality unknown. | Positive line delta is +4.8bn against reported -4.901bn, but it is only a candidate preview; no history row/P&L application because materiality is not established. |
| no old counterpart | OpenAI investment gains and losses #3; FY2024; same identity row key; A0026; amount 1.5bn, `decreased_line`; new; human_review/not_applied | New evidence surfaces the FY2024 net loss. Reviewer `accept`; duplicate false; materiality unknown. | Positive line delta is +1.5bn against reported -1.646bn, preview only; no application. |
| XBOX impairment expenses #1; FY2026; `xbox-impairment-related-expenses`; `label:Research and development`; no amount, `increased_line`; identity_unresolved; human_review/not_applied | Xbox impairment expenses #1; FY2026; `xbox-impairment-expenses`; `standard_concept:ResearchAndDevelopmentExpenses`; A0027; no amount, `increased_line`; new; human_review/not_applied | Same R&D concept, more specific key and stable concept selector. Both reviewer `revise`; duplicate old unknown/new false. | New run can allocate A0027 but still cannot apply: Xbox-specific amount is not disclosed. |
| XBOX impairment expenses #2; FY2026; no usable identity; target `Operating income`; no amount, `decreased_line`; identity_unresolved; human_review/not_applied | Xbox impairment expenses #2; FY2026; invalid for identity because `Operating income` is derived; no ID; no amount, `decreased_line`; identity_unresolved; human_review/not_applied | Target remains a derived subtotal and is rejected before identity allocation. Reviewer changed `revise` to `accept`, but deterministic identity/application remains blocked. | No history row and no P&L effect in either run. This is the intended LLM/Python boundary: qualitative review cannot authorize a derived target. |
| AI infrastructure investments; FY2026; `ai-infrastructure-investments`; `label:Research and development`; no amount, `increased_line`; identity_unresolved; human_review/not_applied | no new counterpart | New discovery no longer retains this topic/candidate. | No history row or P&L effect in either run. The new manifest does not silently preserve or apply it. |
| Legal costs and divestiture gains; FY2026; `legal-expenses-divestiture-gains`; `label:General and administrative`; amount 733m, `increased_line`; identity_unresolved; human_review/not_applied | Divestiture gains; FY2025; `divestiture-gain-prior-period`; `standard_concept:SellingGeneralAndAdminExpenses|label:General and administrative`; A0028; amount unresolved, `decreased_line`; new; human_review/not_applied | New run separates the prior-period divestiture gain from current-period legal costs, shifts recognition to FY2025, and uses a concept+label selector. | Old combined 733m claim was reviewer `revise`; new gain is reviewer `revise` with no attributable amount. No history/P&L effect. |
| UTP #1; FY2026; `uncertain-tax-position-interest`; `label:Provision for income taxes`; A absent/identity_unresolved; 1.4bn, `increased_line`; human_review/not_applied | UTP #1; FY2026; same key; `standard_concept:IncomeTaxes`; A0029; 1.4bn, `increased_line`; new; human_review/not_applied | Same economic identity and amount; only selector changed from presentation label to unique standard concept. Reviewer `accept`; duplicate old unknown/new false. | Materiality remains unknown, so the new row is not approved or applied. |
| UTP #2; FY2025; same key; `label:Provision for income taxes`; identity_unresolved; 1.3bn, `increased_line`; human_review/not_applied | UTP #2; FY2025; same key; `standard_concept:IncomeTaxes`; A0030; 1.3bn, `increased_line`; new; human_review/not_applied | Same economic identity/amount; stable selector and fresh ID. Reviewer `accept`; duplicate false in new. | Materiality unknown; no history/P&L effect. |
| UTP #3; FY2024; same key; `label:Provision for income taxes`; identity_unresolved; 1.5bn, `increased_line`; human_review/not_applied | UTP #3; FY2024; same key; `standard_concept:IncomeTaxes`; A0031; 1.5bn, `increased_line`; new; human_review/not_applied | Same economic identity/amount; stable selector and fresh ID. Reviewer `accept`; duplicate false in new. | Materiality unknown; no history/P&L effect. |

## Identity, provenance, history, and arithmetic findings

- `candidate_identity` contains only `identity_version`, company, fiscal period,
  `target_row_key`, and `item_key`. Filing accession, evidence file/query,
  prose, amount, and direction are not identity. The accession is equal across
  both runs and does not affect matching.
- The old manifest's label-only identities are not current authority because
  the canonical history is legacy/proposed and lacks v2 identity rows. The
  new run therefore allocates A0024-A0031 only for valid new keys on empty
  row-periods. The derived Operating income candidate gets no ID; the two
  missing-amount R&D/Xbox candidates receive IDs but cannot be applied.
- New approved history writes: 0. Current effective approved rows: 0. All
  candidate `application_status` values are `not_applied`; the adjusted P&L is
  unchanged in both manifests. The `adjusted_value` values in the
  normalization summaries are candidate previews only, not applied output.
- Direction algebra is preserved: `increased_line` yields a negative delta;
  `decreased_line` yields a positive delta. The new OpenAI loss previews move
  the negative Other income line toward zero, while no preview is persisted.
- Reconciliation is unchanged and clean: 12 PASS, 0 FAIL, 0 SKIPPED for both
  reported and adjusted checks. No provenance field was used as identity and
  no canonical/live data was edited.
