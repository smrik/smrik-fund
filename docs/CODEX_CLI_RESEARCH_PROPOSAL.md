# Codex CLI research transport — implemented 17 October 2026

Company research now defaults to Codex CLI using the existing ChatGPT login.
Planning, isolated investigations, synthesis, model review/revision, IC synthesis
and independent IC review receive the selected transport. Financial calculations,
source/citation validation, assumption bounds, scenario checks and Excel gates
remain in the application. No automatic API fallback exists.

See [commands and failure recovery](AUTOMATIC_ASSESSMENT.md). `--live` enables
model calls; `--transport codex` selects the subscription explicitly. The API
remains available only through explicit `--transport api` and its existing
pricing/budget checks. CLI execution does not consume/reset that euro ledger.

## Execution and evidence

- The CLI verifies a saved ChatGPT login; no authentication file is read/copied by
  the application. API-key environment overrides are removed and ChatGPT login is
  forced. Missing executable/login stops before model dispatch.
- Every request starts a fresh ephemeral process in a temporary directory,
  read-only sandbox, ignoring user provider/MCP configuration. Tools are disabled;
  unexpected tool events are rejected. The supplied frozen packet is the evidence.
- Schema-constrained JSON enters the same application validators as API output.
  Analyst and reviewer use separate contexts. The CLI default model is used;
  legacy Sol/Luna task labels do not promise subscription model identities.
- Prompts, schemas, event logs, stderr, version/authentication/usage metadata,
  responses and receipts remain beside each request. Receipts bind their hashes.
  Replay validates those bindings without another model invocation.
- Quota failures, invalid responses and a ten-minute process timeout stop the
  stage. An incomplete attempt cannot silently redispatch; keep its evidence and
  deliberately choose a new output directory after resolving the cause.

## Verified locally

Direct Windows `codex.exe`: `0.162.0-alpha.17.2`; login status: ChatGPT.
The npm PowerShell shim reports a different version; the adapter uses the direct
executable. No entitlement or model identity is inferred beyond CLI evidence.

- Live schema smoke passed: `data/codex-cli-validation/20261017-smoke-r2/`.
- Live frozen BBWI analyst + independent review + accounting + native Excel cycle
  passed: `data/codex-cli-validation/20261017-bbwi-live-r2/`. The analyst was reused
  from the hash-bound r1 response; r2 obtained a fresh independent review.
- Native Excel: 572 forecast, 90 operating and 176 historical values checked;
  zero formula errors; beta/cost edit-restoration passed. Read-only audit: 10/10
  checks passed. These are development scenarios, not investment approval.
- 49 focused tests passed across checks: transport replay/failures/tampering,
  both API/Codex full-assessment routing, source/financial validators and independent
  IC review. Final settled checks: 35 transport/research tests and one Codex
  full-cycle test; the other 13 passed in the preceding focused run. Ruff passed.
- Earlier validation changed implementation during execution; the version guard
  correctly stopped publication. Settled-code reruns passed. Failed attempts are
  retained rather than overwritten.

Full planning/investigation/IC routing was tested with simulated responses; live
subscription verification covered analyst/reviewer and the resulting workbook.
Subscription capacity limits still apply. Windows is the verified platform; CLI
flag support must be rechecked when upgrading or using another installation.

Official references checked 17 October 2026:
[non-interactive execution](https://learn.chatgpt.com/docs/non-interactive-mode),
[configuration](https://learn.chatgpt.com/docs/config-file/config-reference), and
[forced authentication](https://learn.chatgpt.com/docs/enterprise/managed-configuration#manage-authentication-locally).
