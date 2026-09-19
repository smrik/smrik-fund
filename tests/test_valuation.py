import hashlib
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "data" / "build-guide-p9" / "parent-repair" / "model"
UPSTREAM = (
    ROOT
    / "data"
    / "build-guide-p8d"
    / "parent-review-correction-r7"
    / "model-input.json"
)
EXPECTED_UPSTREAM_SHA256 = (
    "ee4975d393d6e7df4280bd1ec99fdf4b883221303e82cc5bdbc56c13fe978a00"
)


def load(name: str) -> dict:
    return json.loads((RUN / name).read_text(encoding="utf-8-sig"))


def test_authority_is_bound_to_accepted_input_and_full_statements() -> None:
    proof = load("p9-verification.json")

    assert hashlib.sha256(UPSTREAM.read_bytes()).hexdigest() == EXPECTED_UPSTREAM_SHA256
    assert proof["inputSha256"] == EXPECTED_UPSTREAM_SHA256
    assert proof["status"] == "PASS"
    assert proof["deterministicFullSnapshotsEqual"] is True
    assert proof["snapshot"]["p9"]["status"] == "PROVISIONAL_REVIEW_REQUIRED"
    assert proof["snapshot"]["p9"]["valuationGate"] == "PASS"
    assert proof["snapshot"]["p9"]["formulas"]["reviewStatus"].startswith("=IF(")

    expected_rows = {"income": 10, "cashFlow": 13, "balanceSheet": 27}
    for statement, row_count in expected_rows.items():
        rows = proof["snapshot"]["statements"][statement]
        assert len(rows) == row_count
        assert all(len(row["values"]) == 11 for row in rows)


def test_formula_authority_matches_independent_financial_oracles() -> None:
    p9 = load("p9-verification.json")["snapshot"]["p9"]

    assert p9["wacc"] == pytest.approx(0.08886239789334599)
    assert p9["explicitPv"] == pytest.approx(610276.3055925138)
    assert p9["terminal"]["openingCapital"] == pytest.approx(1153274.5596367985)
    assert p9["terminal"]["ufcf"] == pytest.approx(201618.60375531783)
    assert p9["enterpriseValue"] == pytest.approx(1832910.7974719708)
    assert p9["commonEquityValue"] == pytest.approx(1765851.387346382)
    assert p9["perShareValue"] == pytest.approx(237.69705038987507)
    assert p9["taxTimingPv"] == pytest.approx(7718.512227681437)

    sensitivities = {row["growth"]: row for row in p9["terminalGrowthSensitivity"]}
    assert sensitivities[0]["terminalValue"] == pytest.approx(2393366.515270386)
    assert sensitivities[0.03]["perShareValue"] == pytest.approx(260.26827413872076)


def test_adverse_and_fictional_formula_cases_pass() -> None:
    adverse = load("p9-adverse-verification.json")
    names = {case["name"] for case in adverse["cases"] if case["status"] == "PASS"}
    required = {
        "zero-growth",
        "fractional-lives",
        "wacc-not-greater-than-g",
        "missing-source-input",
        "upstream-gate-blocks-canonical-valuation",
        "invalid-financial-domain-blocks-valuation",
        "current-tax-claim-once",
        "cash-income-financing-vs-ufcf",
        "operating-driver-propagation-and-review-invalidation",
        "upstream-life-propagates-to-terminal",
        "shared-price-propagates-to-wacc-and-award-claim",
        "negative-cash-visible-unfunded",
        "invalid-method",
        "stale-upstream-hash",
    }
    assert adverse["status"] == "PASS"
    assert required <= names

    oracle = load("p9-fictional-core-oracle.json")
    assert oracle["status"] == "PASS"
    assert oracle["g3"]["ufcf"] == pytest.approx(45)
    assert oracle["g3"]["terminalValue"] == pytest.approx(642.8571428571429)
    assert oracle["g0"]["netReinvestment"] == pytest.approx(0)
    assert oracle["g0"]["terminalValue"] == pytest.approx(600)


def test_unsupported_method_rejects_before_allocating_workbook() -> None:
    script = """
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
import { buildAssetWorkbook } from './scripts/spreadsheet_compat/asset_model.mjs';
const model = JSON.parse(await readFile('data/build-guide-p9/parent-repair/model/selected-model.json', 'utf8'));
model.valuation_policy.method_id = 'unsupported';
await assert.rejects(() => buildAssetWorkbook(model), /Unsupported P9 terminal method/);
console.log('Rejected without leaving a workbook handle open');
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT, capture_output=True, text=True, timeout=20, check=True,
    )
    assert "Rejected without leaving a workbook handle open" in result.stdout


def test_live_spread_floor_gate_recovery_and_cfo_adjustment_identity() -> None:
    script = r"""
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { buildAssetWorkbook, readSnapshot } from './scripts/spreadsheet_compat/asset_model.mjs';

const model = JSON.parse(await readFile('data/build-guide-p9/parent-repair/model/selected-model.json', 'utf8'));
const accepted = JSON.parse(await readFile('data/build-guide-p9/parent-repair/model/p9-verification.json', 'utf8')).snapshot;
const near = (actual, expected, label) => assert.ok(
  Math.abs(Number(actual) - Number(expected)) <= 1e-8,
  `${label}: ${actual} != ${expected}`,
);
const statementValues = (snapshot) => Object.fromEntries(
  Object.entries(snapshot.statements).map(([name, rows]) => [name, rows.map((row) => row.values)]),
);
const compareStatements = (actual, expected, label) => {
  let count = 0;
  for (const [statement, rows] of Object.entries(statementValues(expected))) {
    const actualRows = statementValues(actual)[statement];
    assert.equal(actualRows.length, rows.length, `${label} ${statement} row count`);
    rows.forEach((row, rowIndex) => row.forEach((value, periodIndex) => {
      near(actualRows[rowIndex][periodIndex], value, `${label} ${statement} row ${rowIndex} period ${periodIndex}`);
      count += 1;
    }));
  }
  return count;
};

const handle = await buildAssetWorkbook(model);
try {
  const base = await readSnapshot(handle.wb);
  near(base.p9.perShareValue, 237.69705038987507, 'base value/share');
  const statementCells = compareStatements(base, accepted, 'base');
  assert.equal(statementCells, 550);

  const adjustmentRow = base.statements.cashFlow.find((row) => row.row === 7);
  assert.ok(adjustmentRow, 'CashFlow row 7 missing');
  for (let index = 0; index < 11; index += 1) {
    const components = [
      base.totalDepreciation[index],
      base.financing.operatingAmortization[index],
      base.financing.debtContraRelease[index],
      -Number(base.financing.operatingPrincipal[index]),
      base.equity.bookSbc[index],
      base.otherBalances.intangibleAmortization[index],
      base.otherBalances.goodwillImpairment[index],
      -Number(base.otherBalances.noncashGain[index]),
    ];
    near(adjustmentRow.values[index], components.reduce((sum, value) => sum + Number(value), 0), `CFO adjustment period ${index}`);
  }

  const sensitivity = await handle.wb.getSheet('P9Sensitivity');
  const downsideSpread = await sensitivity.getValue('C14');
  const downsideEnterpriseValue = await sensitivity.getValue('H14');
  const downsidePerShare = await sensitivity.getValue('I14');
  near(downsideSpread, 0, 'debt-spread downside floor');
  assert.ok(Number.isFinite(Number(downsideEnterpriseValue)), 'downside enterprise value must calculate');
  assert.ok(Number.isFinite(Number(downsidePerShare)), 'downside per-share value must calculate');
  assert.ok(Number(downsidePerShare) > Number(base.p9.perShareValue), 'zero spread should increase value/share');

  const valuation = await handle.wb.getSheet('Valuation');
  await valuation.setValue('B15', -0.001);
  const blocked = await readSnapshot(handle.wb);
  assert.equal(blocked.p9.inputGate, 'FAIL');
  assert.equal(blocked.p9.valuationGate, 'FAIL');
  assert.equal(blocked.p9.enterpriseValue, 'BLOCKED');
  assert.equal(blocked.p9.perShareValue, 'BLOCKED');
  compareStatements(blocked, base, 'blocked spread edit');

  await valuation.setValue('B15', model.valuation_policy.debt_spread);
  const recovered = await readSnapshot(handle.wb);
  assert.equal(recovered.p9.inputGate, 'PASS');
  assert.equal(recovered.p9.valuationGate, 'PASS');
  near(recovered.p9.perShareValue, 237.69705038987507, 'recovered value/share');
  compareStatements(recovered, base, 'recovered spread');

  process.stdout.write(JSON.stringify({
    statementCells,
    cfoAdjustmentPeriods: adjustmentRow.values.length,
    downsideSpread,
    downsideEnterpriseValue,
    downsidePerShare,
    blockedValue: blocked.p9.perShareValue,
    recoveredValue: recovered.p9.perShareValue,
  }));
} finally {
  handle.wb.dispose();
}
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT, capture_output=True, text=True, timeout=60, check=True,
    )
    proof = json.loads(result.stdout)
    assert proof["statementCells"] == 550
    assert proof["cfoAdjustmentPeriods"] == 11
    assert proof["downsideSpread"] == pytest.approx(0)
    assert proof["downsideEnterpriseValue"] > 1_832_910
    assert proof["downsidePerShare"] > 237.697
    assert proof["blockedValue"] == "BLOCKED"
    assert proof["recoveredValue"] == pytest.approx(237.69705038987507)
