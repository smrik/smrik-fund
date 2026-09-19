# Development API cost snapshot — 2026-09-06

Purpose: dated price inputs for P5's future cost admission and usage ledger. No paid call is authorized to run before those controls and P4's model gate exist. The guide's total authorized development API ceiling remains EUR5; development Codex agent usage is a separate account surface.

Existing runtime default: `gpt-5.6-luna` (`ingestion/adjustment_analysis.py`). Keep it for the first measured reasoning slice unless the fixed evaluation demonstrates a concrete quality problem. The official model page supports Responses structured output and reasoning efforts through max. It currently lists an alias without a separate dated snapshot; record the requested and returned model IDs and exact prompt/schema versions rather than inventing a snapshot suffix. [OpenAI model documentation](https://developers.openai.com/api/docs/models/gpt-5.6-luna)

Account access verified 2026-09-06 by one successful authenticated, read-only `models.retrieve('gpt-5.6-luna')`: returned ID `gpt-5.6-luna`, endpoint `api.openai.com/v1/`, elapsed 1.26s. The prior sandbox attempt had an APIConnectionError and no HTTP status; the bounded request succeeded outside the network sandbox. No inference call or token spend occurred. Credentials were application-loaded from the explicitly authorized local `.env`; no credential value was displayed. This confirms metadata access, not a completed inference or account-specific invoiced price.

| Standard API text usage | USD per1M tokens |
|---|---:|
| Uncached input |0.20|
| Cached input read |0.02|
| Cache write |0.25|
| Output, including reported reasoning usage |1.20|

The model documentation specifies cache writes at1.25 times uncached input. Above272,000 input tokens, full-request input/output pricing multipliers are2 and1.5 respectively. Initial bounded text-only packets should stay below that threshold; admission must reject an unsupported pricing/context tier rather than silently under-price it. Standard processing is the intended mode. Regional processing has an additional uplift; inspect the configured endpoint without exposing its credentials before live execution. [OpenAI model documentation](https://developers.openai.com/api/docs/models/gpt-5.6-luna), [API pricing](https://developers.openai.com/api/docs/pricing)

EUR conversion reference: ECB2026-09-04, EUR1=USD1.1622. Reference USD cost divided by1.1622 gives indicative EUR cost. This is a dated budgeting conversion, not a promised bank/card or invoice exchange rate. [ECB reference rates](https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html)

Planned admission policy: use a conservative known input-size bound that includes system/user payload and structured schema; reserve all input at the cache-write rate, capped output including reasoning, applicable endpoint uplift, and25% headroom. Reserve final-review capacity before exploratory work. Count each dispatched attempt and keep its reservation if transport failure leaves usage unknown; disable hidden SDK retries or account for every attempt. No hosted tool charges apply only when no hosted tools are requested. Persist the full provider usage record, elapsed time, prices, conversion, estimated reservation and reconciled charge; distinguish measured usage from estimates and unknown invoice fields.

This document is preparation only. P5 implements and tests budget admission, context hashing, persistence and restart behavior before its first paid call. Recheck prices/conversion when a later actual run crosses the snapshot's validity policy. Never raise the EUR5 ceiling automatically.
