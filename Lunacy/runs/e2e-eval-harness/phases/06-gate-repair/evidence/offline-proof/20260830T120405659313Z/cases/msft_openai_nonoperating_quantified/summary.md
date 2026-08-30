# msft_openai_nonoperating_quantified

Case: READY / AVAILABLE
Product: COMPLETED (valid=False)
Judge: JUDGE_SKIPPED
Calls: product=0, judge=0, retries=0

| Check | Critical | Status | Reason |
|---|---:|---|---|
| source_artifact | True | PASS |  |
| source_manifest_artifact | True | PASS |  |
| scan_artifact | True | PASS |  |
| investigation_artifact | True | PASS |  |
| evidence_artifact | True | PASS |  |
| analytical_pnl_artifact | True | PASS |  |
| reconciliation_artifact | True | PASS |  |
| packet_identity | True | PASS |  |
| accession | True | PASS |  |
| source_locator | True | PASS |  |
| payload_identity | True | PASS |  |
| payload_accession | True | PASS |  |
| period_identity | True | PASS |  |
| finding_identity | True | PASS |  |
| result_schema | True | PASS |  |
| evidence_refs | True | FAIL | driver description contains unsupported named entity: contributed |
| narrative_numeric_free | True | FAIL | driver description contains unsupported named entity: contributed |
| period_sign_span | True | FAIL | driver description contains unsupported named entity: contributed |
| observed_movement | True | FAIL | payload observed movement differs from deterministic context |
| reconciliation | True | FAIL | reconciliation does not match deterministic product calculation |
| expected_checkpoint | False | PASS | computable bridge exposes target, periods, and observed amount |
| quantification | False | NOT_RUN | no quantified driver was disclosed |
| expansion | False | NOT_RUN | query expansion was absent or not completed |
| normalized_result | True | FAIL | completed workflow returned no normalized result |
