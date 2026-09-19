import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createWorkbook } from '@mog-sdk/sdk';
import {
  buildAssetWorkbook,
  inspectAssetWorkbook,
  readSnapshot,
  TOLERANCE,
  writeSheet,
} from './asset_model.mjs';
import { P9_METHOD_ID, P9_ROWS } from './valuation.mjs';

const [, , command = 'authority', inputArg, runArg] = process.argv;
const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const inputPath = resolve(inputArg ?? resolve(repoRoot, 'data/build-guide-p8d/parent-review-correction-r7/model-input.json'));
const runDir = resolve(runArg ?? resolve(repoRoot, 'data/build-guide-p9/offline-r1'));
const EXPECTED_INPUT_SHA256 = 'ee4975d393d6e7df4280bd1ec99fdf4b883221303e82cc5bdbc56c13fe978a00';
const historyPath = resolve(repoRoot, 'data/build-guide-p9/parent-history-bridge/history-bridge-packet.json');
const EXPECTED_HISTORY_SHA256 = '361af2e2b34070918d5131329f5fd8e5f38d4d76ece1c2eafa51754c52711fad';
const clone = (value) => JSON.parse(JSON.stringify(value));
const sha256 = async (path) => createHash('sha256').update(await readFile(path)).digest('hex');
const settle = () => new Promise((done) => setTimeout(done, 150));
const near = (actual, expected, label, tolerance = 1e-5) => assert.ok(Math.abs(Number(actual) - expected) <= tolerance, `${label}: expected ${expected}, got ${actual}`);

export function assertAcceptedInputHash(actual) {
  assert.equal(actual, EXPECTED_INPUT_SHA256, 'P9 upstream P8D artifact is stale or unauthorized');
}

function modelFromInput(wrapper) {
  const model = clone(wrapper.p8c);
  const decision = wrapper.decision ?? {};
  const review = wrapper.review ?? decision.review ?? {};
  model.other_balances_packet = wrapper.p8d_packet;
  model.other_balances_forecast = {
    schema_version: wrapper.p8d_packet.schema_version,
    case: wrapper.p8d_packet.case,
    information_cutoff: wrapper.p8d_packet.information_cutoff,
    measurement_date: wrapper.p8d_packet.measurement_date,
    method: { id: wrapper.candidate.method_id, version: wrapper.candidate.method_version },
    packet: wrapper.p8d_packet,
    inputs: wrapper.candidate,
    candidate: wrapper.candidate,
    forecast: wrapper.forecast,
    review,
    decision,
    limitations: wrapper.p8d_packet.unavailable,
  };
  model.other_balances_decision = { ...decision, review, review_verdict: review.verdict ?? decision.review_verdict };
  model.valuation_policy = {
    method_id: P9_METHOD_ID,
    method_version: 'v1',
    risk_free_rate: 0.043,
    equity_risk_premium: 0.0477,
    beta: 1,
    debt_spread: 0.004,
    debt_tax_shield_rate: 29287 / 154503,
    price: 370.17,
    debt_fair_value: 36600,
    finance_lease_claim: 62932,
    supplier_claim: 22600,
    long_term_tax_claim: 27941,
    current_tax_claim_switch: 0,
    current_tax_face: 3563,
    terminal_growth: 0.02,
    owned_life_years: 8,
    owned_first_year_fraction: 0.5,
    finance_life_years: 13,
    finance_first_year_fraction: 0,
  };
  model.historical_bridge = {
    source_label: 'Accepted P8D source packet and P9 historical bridge evidence',
    packet_path: 'data/build-guide-p9/parent-history-bridge/history-bridge-packet.json',
    packet_sha256: EXPECTED_HISTORY_SHA256,
    facts: {
      ttm_cfo: 170141,
      ttm_cash_ppe_payments: 97225,
      ttm_net_income: 125216,
      ttm_tax_expense: 29287,
      ttm_net_nonoperating_income: 5546,
      supported_ppe_depreciation: 30300,
      supported_intangible_amortization: 5200,
      broad_da_and_other: 41549,
      current_nine_month_finance_noncash_additions: 19486,
    },
  };
  return model;
}

async function saveWorkbook(model, path) {
  const handle = await buildAssetWorkbook(model);
  try {
    await handle.wb.save(path);
    await settle();
  } finally {
    await settle();
    handle.wb.dispose();
  }
}

async function calculateSnapshot(model) {
  const handle = await buildAssetWorkbook(model);
  try {
    return await readSnapshot(handle.wb);
  } finally {
    handle.wb.dispose();
  }
}

async function loadModel() {
  assertAcceptedInputHash(await sha256(inputPath));
  assert.equal(await sha256(historyPath), EXPECTED_HISTORY_SHA256, 'P9 historical bridge packet is stale or unauthorized');
  const model = modelFromInput(JSON.parse(await readFile(inputPath, 'utf8')));
  const history = JSON.parse(await readFile(historyPath, 'utf8'));
  assert.equal(history.upstream_sha256, EXPECTED_INPUT_SHA256, 'P9 historical bridge is not bound to accepted P8D');
  model.historical_bridge.facts = {
    ttm_cfo: history.facts.reported_cfo.value,
    ttm_cash_ppe_payments: history.facts.cash_ppe_payments.value,
    ttm_net_income: history.facts.net_income.value,
    ttm_tax_expense: history.facts.book_tax_expense.value,
    ttm_net_nonoperating_income: history.facts.nonoperating_income_net.value,
    supported_ppe_depreciation: history.facts.ppe_depreciation.value,
    supported_intangible_amortization: history.facts.finite_intangible_amortization.value,
    broad_da_and_other: history.facts.depreciation_amortization_and_other.value,
    current_nine_month_finance_noncash_additions: 19486,
  };
  return model;
}

function assertBase(snapshot) {
  assert.equal(snapshot.p9.status, 'PROVISIONAL_REVIEW_REQUIRED');
  assert.ok(snapshot.p9.formulas.reviewStatus?.startsWith('=IF('), 'Attached review comparison must remain a live formula');
  assert.equal(snapshot.p9.valuationGate, 'PASS');
  assert.equal(snapshot.p9.claimCheck, 'PASS');
  near(snapshot.p9.wacc, 0.08886239789334599, 'WACC');
  near(snapshot.p9.elapsedYears[0], 91 / 365, 'stub ACT/365');
  near(snapshot.p9.elapsedYears[10], 3744 / 365, 'FY2036 ACT/365');
  near(snapshot.p9.explicitPv, 610276.3055925138, 'explicit PV');
  near(snapshot.p9.terminal.openingCapital, 1153274.5596367985, 'terminal opening capital');
  near(snapshot.p9.terminal.prePpeProfit, 524980.7127429766, 'pre-PP&E terminal profit');
  near(snapshot.p9.terminal.grossAdditions, 279842.5408905271, 'terminal gross additions');
  near(snapshot.p9.terminal.depreciation, 258244.45680745185, 'terminal depreciation');
  near(snapshot.p9.terminal.nopat, 224684.09494805383, 'terminal NOPAT');
  near(snapshot.p9.terminal.netReinvestment, 23065.491192735997, 'terminal net reinvestment');
  near(snapshot.p9.terminal.ufcf, 201618.60375531783, 'terminal UFCF');
  near(snapshot.p9.terminal.value, 2927847.5615616012, 'terminal value');
  near(snapshot.p9.enterpriseValue, 1832910.7974719708, 'enterprise value');
  near(snapshot.p9.commonEquityValue, 1765851.387346382, 'common equity value');
  near(snapshot.p9.perShareValue, 237.69705038987507, 'value per share');
  near(snapshot.p9.taxTimingPv, 7718.512227681437, 'current-tax timing diagnostic');
  near(snapshot.p9.taxTimingPerShare, 1.0389705515791408, 'tax timing per share');
  near(snapshot.p9.history.cashFcf, 72916, 'historical cash FCF');
  near(snapshot.p9.history.unallocatedDaResidual, 6049, 'historical D&A residual');
  assert.equal(snapshot.p9.history.fullHistoricalUfcf, 'NOT_FULLY_ESTIMATED_SOURCE_LIMITATIONS');
  assert.equal(snapshot.p9.explicitUfcf.length, 11);
  assert.equal(snapshot.statements.income.length, 10);
  assert.equal(snapshot.statements.cashFlow.length, 13);
  assert.equal(snapshot.statements.balanceSheet.length, 27);
  for (const [statement, rows] of Object.entries(snapshot.statements)) {
    for (const row of rows) {
      assert.equal(row.values.length, 11, `${statement} row ${row.row} must include all 11 periods`);
      assert.ok(row.values.every((value) => value !== undefined), `${statement} row ${row.row} has an undefined period`);
    }
  }
}

async function authority() {
  const model = await loadModel();
  await mkdir(runDir, { recursive: true });
  await writeFile(resolve(runDir, 'selected-model.json'), `${JSON.stringify(model, null, 2)}\n`, 'utf8');
  const firstCalculated = await calculateSnapshot(clone(model));
  const secondCalculated = await calculateSnapshot(clone(model));
  assert.deepEqual(secondCalculated, firstCalculated, 'two independently built complete calculated snapshots must be deterministic');
  assertBase(firstCalculated);
  const workbookPath = resolve(runDir, 'p9-authority.xlsx');
  await saveWorkbook(model, workbookPath);
  const snapshot = await inspectAssetWorkbook(workbookPath);
  assertBase(snapshot);
  const verification = {
    status: 'PASS',
    mode: 'Mog P9 integrated statements and valuation authority',
    inputPath,
    inputSha256: await sha256(inputPath),
    workbookPath,
    publishedSha256: await sha256(workbookPath),
    deterministicFullSnapshotsEqual: true,
    snapshot,
    policy: model.valuation_policy,
    formulaAuthority: 'Mog formulas; JavaScript supplies frozen inputs and independent assertions only',
  };
  await writeFile(resolve(runDir, 'p9-verification.json'), `${JSON.stringify(verification, null, 2)}\n`, 'utf8');
  console.log(JSON.stringify(verification, null, 2));
}

async function workbookCase(model, mutate) {
  const handle = await buildAssetWorkbook(clone(model));
  try {
    await mutate(handle.wb);
    await handle.wb.calculate();
    return await readSnapshot(handle.wb);
  } finally {
    handle.wb.dispose();
  }
}

async function adverse() {
  const model = await loadModel();
  await mkdir(runDir, { recursive: true });
  const base = await calculateSnapshot(model);
  assertBase(base);
  const cases = [];

  const zero = clone(model);
  zero.valuation_policy.terminal_growth = 0;
  const zeroSnapshot = await calculateSnapshot(zero);
  near(zeroSnapshot.p9.terminal.grossAdditions, 262556.2424462213, 'g0 gross additions');
  near(zeroSnapshot.p9.terminal.depreciation, 262556.2424462213, 'g0 depreciation');
  near(zeroSnapshot.p9.terminal.netReinvestment, 0, 'g0 net reinvestment');
  near(zeroSnapshot.p9.terminal.ufcf, 212680.287584568, 'g0 UFCF');
  near(zeroSnapshot.p9.terminal.value, 2393366.515270386, 'g0 terminal value');
  near(zeroSnapshot.p9.perShareValue, 207.6535775704229, 'g0 per share');
  cases.push({ name: 'zero-growth', status: 'PASS', perShareValue: zeroSnapshot.p9.perShareValue });

  const fractional = clone(model);
  fractional.candidate.parameters.find((item) => item.name === 'new_addition_useful_life_years').value = 8.5;
  fractional.financing_forecast.forecast.policy.pipeline_finance_life_years = 12.25;
  const fractionalSnapshot = await calculateSnapshot(fractional);
  assert.equal(fractionalSnapshot.p9.terminalGate, 'PASS');
  near(fractionalSnapshot.p9.terminal.netReinvestment, 0.02 * fractionalSnapshot.p9.terminal.openingCapital, 'fractional-life reinvestment');
  cases.push({ name: 'fractional-lives', status: 'PASS' });

  const badWacc = await workbookCase(model, async (wb) => {
    await (await wb.getSheet('Valuation')).setValue('B27', 0.2);
  });
  assert.equal(badWacc.p9.inputGate, 'FAIL');
  assert.equal(badWacc.p9.enterpriseValue, 'BLOCKED');
  cases.push({ name: 'wacc-not-greater-than-g', status: 'PASS' });

  const missing = await workbookCase(model, async (wb) => {
    await (await wb.getSheet('Inputs')).clear('B176');
  });
  assert.equal(missing.p9.inputGate, 'FAIL');
  assert.equal(missing.p9.enterpriseValue, 'BLOCKED');
  cases.push({ name: 'missing-source-input', status: 'PASS' });

  const missingUpstream = await workbookCase(model, async (wb) => {
    await (await wb.getSheet('Inputs')).clear('B234');
  });
  assert.equal(missingUpstream.otherBalancesGateStatus, 'FAIL');
  assert.equal(missingUpstream.p9.valuationGate, 'FAIL');
  assert.equal(missingUpstream.p9.enterpriseValue, 'BLOCKED');
  assert.equal(missingUpstream.p9.perShareValue, 'BLOCKED');
  cases.push({ name: 'upstream-gate-blocks-canonical-valuation', status: 'PASS' });

  const badDomain = await workbookCase(model, async (wb) => {
    await (await wb.getSheet('Valuation')).setValue('B16', 1.5);
  });
  assert.equal(badDomain.p9.inputGate, 'FAIL');
  assert.equal(badDomain.p9.valuationGate, 'FAIL');
  assert.equal(badDomain.p9.enterpriseValue, 'BLOCKED');
  cases.push({ name: 'invalid-financial-domain-blocks-valuation', status: 'PASS' });

  const currentTax = clone(model);
  currentTax.valuation_policy.current_tax_claim_switch = 1;
  const currentTaxSnapshot = await calculateSnapshot(currentTax);
  near(currentTaxSnapshot.p9.commonEquityValue, base.p9.commonEquityValue - 3563, 'current tax claim once');
  near(currentTaxSnapshot.p9.perShareValue, base.p9.perShareValue - 3563 / 7429, 'current tax claim per share');
  cases.push({ name: 'current-tax-claim-once', status: 'PASS' });

  const yieldStress = clone(model);
  yieldStress.other_balances_forecast.inputs.cash_income_yield += 0.01;
  yieldStress.other_balances_forecast.candidate.cash_income_yield += 0.01;
  const yieldSnapshot = await calculateSnapshot(yieldStress);
  assert.notEqual(yieldSnapshot.stub.netIncome, base.stub.netIncome);
  assert.deepEqual(yieldSnapshot.p9.explicitUfcf, base.p9.explicitUfcf, 'cash/investment income must not enter operating UFCF');
  near(yieldSnapshot.p9.enterpriseValue, base.p9.enterpriseValue, 'cash-income yield financing-vs-UFCF exclusion');
  cases.push({ name: 'cash-income-financing-vs-ufcf', status: 'PASS' });

  const operatingEdit = await workbookCase(model, async (wb) => {
    const inputs = await wb.getSheet('Inputs');
    await inputs.setValue('B64', Number(await inputs.getValue('B64')) + 0.01);
  });
  assert.notEqual(operatingEdit.periodEnd.revenue, base.periodEnd.revenue);
  assert.notEqual(operatingEdit.p9.enterpriseValue, base.p9.enterpriseValue);
  assert.equal(operatingEdit.p9.reviewStatus, 'EDITED_UNREVIEWED');
  cases.push({ name: 'operating-driver-propagation-and-review-invalidation', status: 'PASS' });

  const lifeEdit = await workbookCase(model, async (wb) => {
    await (await wb.getSheet('Inputs')).setValue('B30', 9);
  });
  assert.notEqual(lifeEdit.p9.terminal.grossAdditions, base.p9.terminal.grossAdditions);
  assert.notEqual(lifeEdit.p9.terminal.depreciation, base.p9.terminal.depreciation);
  assert.notEqual(lifeEdit.p9.enterpriseValue, base.p9.enterpriseValue);
  assert.equal(lifeEdit.p9.reviewStatus, 'EDITED_UNREVIEWED');
  cases.push({ name: 'upstream-life-propagates-to-terminal', status: 'PASS' });

  const quoteEdit = await workbookCase(model, async (wb) => {
    await (await wb.getSheet('Inputs')).setValue('B176', 400);
  });
  near(quoteEdit.existingAwardClaim, 82 * 400, 'shared quote award claim');
  assert.notEqual(quoteEdit.p9.wacc, base.p9.wacc);
  assert.notEqual(quoteEdit.p9.enterpriseValue, base.p9.enterpriseValue);
  assert.equal(quoteEdit.p9.reviewStatus, 'EDITED_UNREVIEWED');
  cases.push({ name: 'shared-price-propagates-to-wacc-and-award-claim', status: 'PASS' });

  const negativeCash = clone(model);
  negativeCash.other_balances_packet.facts.source.cash = -100000;
  const negativeSnapshot = await calculateSnapshot(negativeCash);
  assert.equal(negativeSnapshot.otherBalances.fundingStatus[0], 'UNFUNDED_CASH');
  cases.push({ name: 'negative-cash-visible-unfunded', status: 'PASS' });

  const invalidMethod = clone(model);
  invalidMethod.valuation_policy.method_id = 'free_roic_plug';
  await assert.rejects(() => buildAssetWorkbook(invalidMethod), /Unsupported P9 terminal method/);
  cases.push({ name: 'invalid-method', status: 'PASS' });
  assert.throws(() => assertAcceptedInputHash('stale'), /stale or unauthorized/);
  cases.push({ name: 'stale-upstream-hash', status: 'PASS' });

  const result = { status: 'PASS', cases, base: { enterpriseValue: base.p9.enterpriseValue, commonEquityValue: base.p9.commonEquityValue, perShareValue: base.p9.perShareValue } };
  await writeFile(resolve(runDir, 'p9-adverse-verification.json'), `${JSON.stringify(result, null, 2)}\n`, 'utf8');
  console.log(JSON.stringify(result, null, 2));
}

const oraclePad = (row) => [...row, ...Array(Math.max(0, 5 - row.length)).fill(null)];

async function oracleCase(growth) {
  const wb = await createWorkbook({ userTimezone: 'UTC' });
  await wb.sheets.rename('Sheet1', 'Inputs');
  await wb.sheets.add('DCF');
  await writeSheet(wb, 'Inputs', [oraclePad(['Fictional P9 accounting bridge']), oraclePad([]), oraclePad(['Input', 'Value']), oraclePad(['Opening owned capital', 300]), oraclePad(['Opening finance capital', 100]), oraclePad(['Opening operating NWC', 100]), oraclePad(['Opening capital', 500]), oraclePad(['Pre-depreciation operating profit', 120]), oraclePad(['PP&E depreciation', 40]), oraclePad(['Operating tax rate', 0.25]), oraclePad(['Terminal growth', growth]), oraclePad(['WACC', 0.1])]);
  await writeSheet(wb, 'DCF', [oraclePad(['Fictional P9 formula bridge']), oraclePad([]), oraclePad(['Line', 'Value']), oraclePad(['EBIT', '=Inputs!B8-Inputs!B9']), oraclePad(['NOPAT', '=B4*(1-Inputs!B10)']), oraclePad(['Gross additions', '=Inputs!B9+Inputs!B11*(Inputs!B4+Inputs!B5)']), oraclePad(['Delta NWC', '=Inputs!B11*Inputs!B6']), oraclePad(['Net reinvestment', '=B6-Inputs!B9+B7']), oraclePad(['UFCF', '=B5-B8']), oraclePad(['Terminal value', '=B9/(Inputs!B12-Inputs!B11)'])]);
  await wb.calculate();
  const dcf = await wb.getSheet('DCF');
  const values = {};
  for (const [key, row] of Object.entries({ nopat: 5, gross: 6, deltaNwc: 7, netReinvestment: 8, ufcf: 9, terminalValue: 10 })) values[key] = await dcf.getValue(`B${row}`);
  wb.dispose();
  return values;
}

async function oracle() {
  await mkdir(runDir, { recursive: true });
  const g3 = await oracleCase(0.03);
  const g0 = await oracleCase(0);
  for (const [key, expected] of Object.entries({ nopat: 60, gross: 52, deltaNwc: 3, netReinvestment: 15, ufcf: 45, terminalValue: 642.8571428571429 })) near(g3[key], expected, `fictional g3 ${key}`);
  for (const [key, expected] of Object.entries({ nopat: 60, gross: 40, deltaNwc: 0, netReinvestment: 0, ufcf: 60, terminalValue: 600 })) near(g0[key], expected, `fictional g0 ${key}`);
  const result = { status: 'PASS', formulaAuthority: 'Mog formulas', g3, g0 };
  await writeFile(resolve(runDir, 'p9-fictional-core-oracle.json'), `${JSON.stringify(result, null, 2)}\n`, 'utf8');
  console.log(JSON.stringify(result, null, 2));
}

if (command === 'authority') await authority();
else if (command === 'adverse') await adverse();
else if (command === 'oracle') await oracle();
else throw new Error(`Unknown P9 command: ${command}`);
