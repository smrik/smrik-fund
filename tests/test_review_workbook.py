import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "data" / "build-guide-p9" / "parent-repair" / "model" / "selected-model.json"
P9_PROOF_PATH = ROOT / "data" / "build-guide-p9" / "parent-repair" / "model" / "p9-verification.json"
AREAS = [
    "revenue",
    "operating_costs",
    "ppe_capex",
    "intangibles",
    "working_capital",
    "taxes",
    "debt_interest",
    "leases",
    "sbc_equity",
    "nonoperating",
    "cash_flow_cash",
    "dcf_terminal",
]


def _annotated_model() -> dict:
    model = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    candidate_values = {item["name"]: item["value"] for item in model["candidate"]["parameters"]}
    sources = [
        {
            "source_id": f"SRC-{area}",
            "period": "FY2025-Q3FY2026",
            "cutoff": "2026-04-30",
            "kind": "review_test_source",
            "excerpt": f"Pinned test evidence for {area}",
            "source_file": "data/test-source.json",
            "locator": f"facts.{area}",
            "sha256": "a" * 64,
        }
        for area in AREAS
    ]
    areas = [
        {
            "area": area,
            "outcome": "supported_no_change",
            "basis": f"Current selected treatment reviewed for {area}.",
            "changed_dependencies": ["P9 integrated model"],
            "decision_refs": [f"P10-{area}"],
            "source_refs": [f"SRC-{area}"],
            "limitations": [],
        }
        for area in AREAS
    ]
    policy = model["valuation_policy"]
    input_specs = [
        ("Valuation!B12", "Risk-free rate", policy["risk_free_rate"], "decimal", "dcf_terminal"),
        ("Valuation!B13", "Equity risk premium", policy["equity_risk_premium"], "decimal", "dcf_terminal"),
        ("Valuation!B14", "Beta", policy["beta"], "x", "dcf_terminal"),
        ("Valuation!B15", "Debt spread", policy["debt_spread"], "decimal", "debt_interest"),
        ("Valuation!B16", "Debt shield", policy["debt_tax_shield_rate"], "decimal", "taxes"),
        ("Valuation!B27", "Terminal growth", policy["terminal_growth"], "decimal", "dcf_terminal"),
        ("Inputs!B32", "Cash PP&E additions rate", candidate_values["cash_ppe_additions_rate"], "decimal", "ppe_capex"),
    ]
    material_inputs = [
        {
            "address": address,
            "label": label,
            "exported_value": value,
            "units": units,
            "classification": "selected_estimate",
            "area": area,
            "decision_refs": [f"P10-{area}"],
            "source_refs": [f"SRC-{area}"],
            "rationale": f"Exported-base rationale for {label}.",
            "caveat": "Sensitivity remains visible.",
        }
        for address, label, value, units, area in input_specs
    ]
    model["review_metadata"] = {
        "schema_version": "p11-review-metadata-v1",
        "review": {
            "id": "P10-MSFT-review",
            "version": "R6",
            "verdict": "accept",
            "completed_at": "2026-09-08T12:00:00Z",
            "independent_recheck_id": "P10-recheck-03",
        },
        "states": {
            "execution": "COMPLETED",
            "mechanical": "PASS",
            "coverage": "COMPLETE",
            "analytical": "INDEPENDENTLY_REVIEWED",
            "budget": "WITHIN_CAP",
            "human": False,
        },
        "bindings": {
            "selected_model_sha256": "24ecc22c7a213f1959dfd50bd77fc34803af8883e658806cf64e64e1ec13d630",
            "financial_snapshot_sha256": "b" * 64,
            "review_request_sha256": "6ae83ac7fa98adadb2f0b5235d82a708784a3f924f6c167ef156d4efa18f92cf",
            "review_response_sha256": "201adf9914a237103b0c6eb6dddcae844c937391fe415f6f2447f0e98fda18c2",
            "source_context_sha256": "c" * 64,
        },
        "provenance": {
            "run_id": "parent-final-r6",
            "authoritative_version": "MSFT-P11-R1",
            "prior_version": "MSFT-P9",
            "exported_at": "2026-09-08T12:00:00Z",
        },
        "narrative": {
            "summary": "Accepted exported-base whole-model review.",
            "key_drivers": ["Cloud growth", "WACC", "terminal growth"],
            "cash_vs_ufcf": "Economic UFCF includes recognized noncash investment; cash FCF is CFO less cash PP&E payments.",
            "limitations": ["Later-informed analysis", "No human approval"],
        },
        "areas": areas,
        "sources": sources,
        "material_inputs": material_inputs,
    }
    return model


def test_review_export_is_live_bound_and_preserves_financials(tmp_path: Path) -> None:
    model_path = tmp_path / "annotated-model.json"
    workbook_path = tmp_path / "review.xlsx"
    snapshot_path = tmp_path / "review-snapshot.json"
    model_path.write_text(json.dumps(_annotated_model()), encoding="utf-8")

    command = [
        "node",
        "scripts/spreadsheet_compat/export-review.mjs",
        str(model_path),
        str(workbook_path),
        str(snapshot_path),
    ]
    exported = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    assert json.loads(exported.stdout)["reviewVersion"] == "R6"
    assert workbook_path.exists()

    result = json.loads(snapshot_path.read_text(encoding="utf-8"))
    accepted = json.loads(P9_PROOF_PATH.read_text(encoding="utf-8"))["snapshot"]
    assert result["snapshot"]["p9"]["perShareValue"] == pytest.approx(237.69705038987507)
    cell_count = 0
    for statement, expected_rows in accepted["statements"].items():
        actual_rows = result["snapshot"]["statements"][statement]
        for actual, expected in zip(actual_rows, expected_rows, strict=True):
            assert actual["values"] == pytest.approx(expected["values"])
            cell_count += len(actual["values"])
    assert cell_count == 550

    audit_script = r"""
import assert from 'node:assert/strict';
import { createWorkbook } from '@mog-sdk/sdk';
const wb = await createWorkbook(process.argv[1], { userTimezone: 'UTC' });
try {
  const review = await wb.getSheet('Review');
  const valuation = await wb.getSheet('Valuation');
  const inputs = await wb.getSheet('Inputs');
  const checks = await wb.getSheet('Checks');
  const saved = await wb.getSheet('SavedInputs');
  assert.equal(await review.getValue('C14'), 'PASS');
  assert.equal(await review.getValue('C15'), 'COMPLETE');
  assert.equal(await review.getValue('C16'), 'INDEPENDENTLY_REVIEWED');
  assert.ok(Math.abs(Number(await review.getValue('B23')) - 237.69705038987507) <= 1e-8);
  assert.ok((await review.getFormula('B23')).startsWith('=Valuation!'));
  assert.ok((await review.getFormula('B44')).startsWith('=HYPERLINK'));
  assert.ok((await review.getFormula('F52')).startsWith('=HYPERLINK'));
  assert.ok((await review.getFormula('G63')).startsWith('=HYPERLINK'));
  assert.match((await valuation.comments.getNote('B14')).content, /Exported base: 1 x/);
  assert.match((await valuation.comments.getNote('B27')).content, /Exported base: 0.02 decimal/);
  assert.match((await inputs.comments.getNote('B32')).content, /Local edits invalidate/);

  let betaSavedRow = null;
  for (let row = 4; row <= 800; row += 1) {
    if (await saved.getValue(`A${row}`) === 'Valuation!B14') betaSavedRow = row;
  }
  assert.ok(betaSavedRow);
  assert.equal(await saved.getValue(`B${betaSavedRow}`), 1);
  assert.equal(await saved.getValue(`D${betaSavedRow}`), 1);
  assert.equal(await saved.getValue(`C${betaSavedRow}`), 0);

  await valuation.setValue('B14', 1.15);
  assert.equal(await valuation.getValue('B41'), 'EDITED_UNREVIEWED');
  assert.equal(await review.getValue('C15'), 'STALE_AFTER_EDIT');
  assert.equal(await review.getValue('C16'), 'EDITED_UNREVIEWED');
  assert.equal(await saved.getValue(`C${betaSavedRow}`), 1);
  await valuation.setValue('B14', 1);
  assert.equal(await review.getValue('C16'), 'INDEPENDENTLY_REVIEWED');

  const originalCapex = Number(await inputs.getValue('B32'));
  await inputs.setValue('B32', originalCapex + 0.01);
  assert.equal(await checks.getValue('B23'), 'EDITED');
  assert.equal(await review.getValue('C16'), 'EDITED_UNREVIEWED');
  await inputs.setValue('B32', originalCapex);
  assert.equal(await review.getValue('C16'), 'INDEPENDENTLY_REVIEWED');
  process.stdout.write(JSON.stringify({ areas: 12, betaSavedRow, currentAnalytical: await review.getValue('C16') }));
} finally {
  await new Promise((resolve) => setTimeout(resolve, 150));
  wb.dispose();
}
"""
    audited = subprocess.run(
        ["node", "--input-type=module", "-e", audit_script, str(workbook_path)],
        cwd=ROOT / "scripts" / "spreadsheet_compat",
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    assert json.loads(audited.stdout)["areas"] == 12

    refused = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert refused.returncode != 0
    assert "refuses to overwrite" in refused.stderr
