import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { createWorkbook } from '@mog-sdk/sdk';
import {
  buildAssetWorkbook,
  combinedDecision,
  inspectAssetWorkbook,
  readSnapshot,
  FINANCING_DRIVER_ROWS,
  PERIODS,
  TOLERANCE,
} from './asset_model.mjs';

const [, , command = 'authority', inputArg, runArg] = process.argv;
const inputPath = resolve(inputArg ?? 'data/build-guide-p8b/offline-r1/model-input.json');
const runDir = resolve(runArg ?? 'data/build-guide-p8b/offline-r1');
const priorVerificationPath = resolve(process.argv[5] ?? 'data/build-guide-p8b/live-r5/model-v1/financing-verification.json');
const settle = () => new Promise((resolvePromise) => setTimeout(resolvePromise, 150));
const near = (actual, expected, label) => assert.ok(Math.abs(Number(actual) - expected) <= TOLERANCE, `${label}: expected ${expected}, got ${actual}`);
const sha256 = async (path) => createHash('sha256').update(await readFile(path)).digest('hex');
const clone = (value) => JSON.parse(JSON.stringify(value));

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

function presentationOnlySnapshot(snapshot) {
  if (Array.isArray(snapshot)) return snapshot.map((item) => presentationOnlySnapshot(item));
  if (snapshot && typeof snapshot === 'object') {
    return Object.fromEntries(Object.entries(snapshot)
      .filter(([key]) => !['dcfStatus', 'combinedDecisionStatus'].includes(key))
      .map(([key, value]) => [key, presentationOnlySnapshot(value)]));
  }
  return snapshot;
}

function mutateP8bDecisions(model, mutate) {
  for (const decision of [model.financing_decision, model.p8b_decision]) {
    if (decision) mutate(decision);
  }
}

function bindingRegressionCases(model) {
  const cases = [];
  const run = (name, mutate, expected = false) => {
    const candidate = clone(model);
    mutate(candidate);
    const decision = combinedDecision(candidate);
    assert.equal(decision.p8b_binding_valid, expected, `${name} binding result`);
    if (!expected) assert.equal(decision.status, 'UNREVIEWED_PROVISIONAL', `${name} status`);
    cases.push({ name, status: 'PASS', p8bBindingValid: decision.p8b_binding_valid, combinedStatus: decision.status });
  };
  run('changed pipeline forward rate', (candidate) => {
    candidate.financing_forecast.forecast.policy.pipeline_finance_rate += 0.001;
  });
  run('changed source ratio', (candidate) => {
    candidate.financing_packet.facts.pipeline.finance_share_source += 0.001;
  });
  run('unknown source-mix reference', (candidate) => {
    mutateP8bDecisions(candidate, (decision) => {
      if (decision.binding?.candidate_snapshot) decision.binding.candidate_snapshot.pipeline_finance_share = 'unknown_source_mix';
    });
  });
  run('missing binding', (candidate) => {
    mutateP8bDecisions(candidate, (decision) => { delete decision.binding; });
  });
  return cases;
}

async function binding() {
  const model = JSON.parse(await readFile(inputPath, 'utf8'));
  assert.ok(model.financing_forecast, 'P8B financing forecast is required');
  const decision = combinedDecision(model);
  assert.equal(decision.p8b_binding_valid, true, 'live-r5 P8B binding');
  assert.equal(decision.status, 'SYSTEM_REVIEWED_PROVISIONAL', 'live-r5 combined status');
  const regressions = bindingRegressionCases(model);
  await mkdir(runDir, { recursive: true });
  const workbookPath = resolve(runDir, 'financing-authority.xlsx');
  await saveWorkbook(model, workbookPath);
  const snapshot = await inspectAssetWorkbook(workbookPath);
  assert.equal(snapshot.financingGateStatus, 'PASS', 'P8B financing input gate');
  assert.equal(snapshot.allPeriodStatus, 'PASS', 'all-period mechanical gate');
  assert.equal(snapshot.combinedDecisionStatus, 'SYSTEM_REVIEWED_PROVISIONAL', 'exported combined status');
  const priorVerification = JSON.parse(await readFile(priorVerificationPath, 'utf8'));
  const priorSnapshot = priorVerification.snapshot;
  const financialEquivalent = JSON.stringify(presentationOnlySnapshot(snapshot)) === JSON.stringify(presentationOnlySnapshot(priorSnapshot));
  assert.equal(financialEquivalent, true, 'R6 financial/period snapshot equivalence');
  const verification = {
    status: 'PASS',
    mode: 'Mog P8B export-binding R6 correction',
    inputPath,
    workbookPath,
    priorVerificationPath,
    publishedSha256: await sha256(workbookPath),
    p8bBindingValid: decision.p8b_binding_valid,
    combinedDecisionStatus: decision.status,
    providerHashes: {
      candidateHash: model.financing_decision.candidate_hash,
      reviewHash: model.financing_decision.review_hash,
      contextHash: model.financing_decision.context_hash,
      sourcePacketHash: model.financing_decision.source_packet_hash,
    },
    regressions,
    financialEquivalent,
    snapshot,
    formulaAuthority: 'Mog formulas; R6 changes only reviewed-reference/export binding comparison',
  };
  await writeFile(resolve(runDir, 'financing-verification.json'), `${JSON.stringify(verification, null, 2)}\n`, 'utf8');
  await writeFile(resolve(runDir, 'export-binding-verification.json'), `${JSON.stringify({
    status: 'PASS',
    mode: verification.mode,
    p8bBindingValid: decision.p8b_binding_valid,
    combinedDecisionStatus: decision.status,
    regressions,
    financialEquivalent,
    providerHashes: verification.providerHashes,
    publishedSha256: verification.publishedSha256,
    priorPublishedSha256: priorVerification.publishedSha256,
  }, null, 2)}\n`, 'utf8');
  console.log(JSON.stringify(verification, null, 2));
}

async function authority() {
  const model = JSON.parse(await readFile(inputPath, 'utf8'));
  assert.ok(model.financing_forecast, 'P8B financing forecast is required');
  await mkdir(runDir, { recursive: true });
  const workbookPath = resolve(runDir, 'financing-authority.xlsx');
  await saveWorkbook(model, workbookPath);
  let snapshot;
  try {
    snapshot = await inspectAssetWorkbook(workbookPath);
  } catch (error) {
    const debugWb = await createWorkbook(workbookPath, { userTimezone: 'UTC' });
    console.error(JSON.stringify(await readSnapshot(debugWb), null, 2));
    debugWb.dispose();
    throw error;
  }
  assert.equal(snapshot.financingGateStatus, 'PASS', 'P8B financing input gate');
  assert.equal(snapshot.allPeriodStatus, 'PASS', 'all-period mechanical gate');
  const verification = {
    status: 'PASS',
    mode: 'Mog calculation-only P8B preview',
    inputPath,
    workbookPath,
    publishedSha256: await sha256(workbookPath),
    snapshot,
    formulaAuthority: 'Mog formulas; Python proposal and calibration fields are diagnostic inputs only',
  };
  const verificationPath = resolve(runDir, 'financing-verification.json');
  await writeFile(verificationPath, `${JSON.stringify(verification, null, 2)}\n`, 'utf8');
  console.log(JSON.stringify({ status: 'PASS', workbookPath, verificationPath, snapshot }, null, 2));
}

function syntheticFinancing(model) {
  const result = clone(model);
  delete result.operating_forecast;
  delete result.operating_decision;
  delete result.p6_decision;
  delete result.working_capital_forecast;
  delete result.working_capital_decision;
  delete result.working_capital_packet;
  const financing = result.financing_forecast;
  financing.oracle_fixture = true;
  financing.inputs = {
    debt_face: 120, debt_carrying: 120, debt_fair_value: 120, debt_contra_total: 0,
    opening_operating_rou: 80, opening_operating_liability: 70,
    opening_finance_ppe: 60, opening_finance_liability: 50,
    opening_operating_book_cost: 15, opening_operating_rate: 0.05, opening_finance_rate: 0.08,
    opening_current_debt: 120, opening_noncurrent_debt: 0,
    opening_operating_current_liability: 70, opening_operating_noncurrent_liability: 0,
    opening_finance_current_liability: 50, opening_finance_noncurrent_liability: 0,
    pipeline_commitments: 35, period_days: Array(11).fill(365),
    opening_operating_payments: [16, ...Array(10).fill(0)],
    opening_finance_payments: [14, ...Array(10).fill(0)],
    embedded_operating_lease_cost_proxy: 0,
  };
  const zeroVisible = PERIODS.map((period, index) => ({
    period,
    operating_additions: index === 0 ? 20 : 0,
    finance_additions: index === 0 ? 15 : 0,
    operating_payment: 0,
    finance_payment: 0,
    operating_interest: 0,
    finance_interest: 0,
    operating_principal: 0,
    finance_principal: 0,
    operating_expense: 0,
    finance_depreciation: 0,
  }));
  financing.forecast = {
    policy: {
      debt_coupon_rate: 0.05, debt_refinance_policy: 'refinance_disclosed_maturities', debt_tail_policy: 'hold_through_fy2036',
      refinance_term_years: 30, refinance_fee_rate: 0, lease_bundle: 'operating_expense_finance_debt_like',
      pipeline_finance_share: 0, pipeline_operating_life_years: 6, pipeline_finance_life_years: 5,
      pipeline_operating_rate: 0.036, pipeline_finance_rate: 0.044, opening_finance_life_years: 5,
    },
    debt: {
      original_face_redemption: [30, ...Array(10).fill(0)],
      new_face_proceeds: Array(11).fill(0),
    },
    operating_opening_pool: {
      payments: [16, ...Array(10).fill(0)], payment: [16, ...Array(10).fill(0)], payment_dates: PERIODS.map((_, index) => `20${26 + index}-06-30`), full_runoff: PERIODS.map((_, index) => ({ closing: index === 0 ? 54 : 0 })), full_runoff_final_closing: 0,
    },
    finance_opening_pool: {
      payments: [14, ...Array(10).fill(0)], payment: [14, ...Array(10).fill(0)], payment_dates: PERIODS.map((_, index) => `20${26 + index}-06-30`), full_runoff: PERIODS.map((_, index) => ({ closing: index === 0 ? 36 : 0 })), full_runoff_final_closing: 0,
    },
    pipeline: { visible: zeroVisible, undiscounted_commitments: 35, finance_share: 0 },
  };
  financing.decision = {
    ...(financing.decision ?? {}),
    status: 'OFFLINE_FIXTURE',
    binding: { ...(financing.decision?.binding ?? {}), candidate_snapshot: financing.forecast.policy },
  };
  result.financing_decision = financing.decision;
  result.p8b_decision = financing.decision;
  return result;
}

async function configureOracleInputs(handle) {
  const inputs = await handle.wb.getSheet('Inputs');
  const set = async (address, value) => inputs.setCell(address, value);
  const synthetic = {
    B6: 100, B7: 0, B8: 0, B9: 0, B10: 0, B11: 260, B12: 0, B13: 260,
    B14: 80, B15: 0, B16: 0, B17: 0, B18: 0, B19: 440, B20: 0, B21: 120,
    B22: 0, B23: 240, B24: 200, B29: 2.5, B30: 100, B31: 0, B32: 0.25,
    B33: 0, B34: 0, B35: 0, B36: 0, B37: 0.08, B38: 0.02,
    B43: 100, B55: 100, B57: 0, B58: 25, B59: 0,
    B106: 0, B107: 0, B117: 0, B111: 0, B112: 0, B113: 0,
  };
  for (const [address, value] of Object.entries(synthetic)) await set(address, value);
  for (const column of ['B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L']) {
    await set(`${column}108`, 0);
    await set(`${column}110`, 0);
    await set(`${column}118`, 365);
  }
  const f = FINANCING_DRIVER_ROWS;
  await set(`B${f.pipelineFinanceLifeYears}`, 5);
  await set(`B${f.openingFinanceLifeYears}`, 5);
  await handle.wb.calculate();
  await settle();
}

async function oracle() {
  const source = JSON.parse(await readFile(inputPath, 'utf8'));
  const model = syntheticFinancing(source);
  await mkdir(runDir, { recursive: true });
  const handle = await buildAssetWorkbook(model);
  try {
    await configureOracleInputs(handle);
    const snapshot = await readSnapshot(handle.wb);
    near(snapshot.stub.ebit, 53, 'oracle EBIT');
    near(snapshot.stub.netIncome, 43, 'oracle net income');
    near(snapshot.stub.cfo, 74, 'oracle CFO');
    near(snapshot.stub.closingCash, 109, 'oracle closing cash');
    near(snapshot.stub.totalAssets, 465.5, 'oracle total assets');
    near(snapshot.stub.economicUfcf, 44, 'oracle UFCF');
    near(snapshot.stub.balanceDifference, 0, 'oracle balance difference');
    near(snapshot.financing.debtClosingFace[0], 90, 'oracle debt closing');
    near(snapshot.financing.financePpeClosing[0], 63, 'oracle finance PP&E closing');
    near(snapshot.financing.financeLiabilityClosing[0], 55, 'oracle finance liability closing');
    near(snapshot.financing.operatingRouClosing[0], 88.5, 'oracle operating ROU closing');

    const inputs = await handle.wb.getSheet('Inputs');
    const f = FINANCING_DRIVER_ROWS;
    await inputs.setCell(`B${f.pipelineFinanceAdditions}`, 25);
    await handle.wb.calculate();
    await settle();
    const additionShock = await readSnapshot(handle.wb);
    near(additionShock.financing.financePpeClosing[0], 73, 'finance-addition shock PP&E');
    near(additionShock.financing.financeLiabilityClosing[0], 65, 'finance-addition shock liability');
    near(additionShock.stub.closingCash, 109, 'finance-addition shock cash');
    near(additionShock.stub.economicUfcf, 34, 'finance-addition shock UFCF');
    near(additionShock.stub.balanceDifference, 0, 'finance-addition shock balance');
    await inputs.setCell(`B${f.pipelineFinanceAdditions}`, 15);

    await inputs.setCell(`B${f.debtCouponRate}`, 0.10);
    await handle.wb.calculate();
    await settle();
    const rateShock = await readSnapshot(handle.wb);
    near(rateShock.stub.netIncome, 37, 'debt-rate shock net income');
    near(rateShock.stub.cfo, 68, 'debt-rate shock CFO');
    near(rateShock.stub.closingCash, 103, 'debt-rate shock cash');
    near(rateShock.stub.economicUfcf, 44, 'debt-rate shock UFCF');
    await inputs.setCell(`B${f.debtCouponRate}`, 0.05);

    await inputs.setCell('B6', 10);
    await inputs.setCell('B24', 110);
    await inputs.setCell(`B${f.debtRedemption}`, 120);
    await handle.wb.calculate();
    await settle();
    const shortfall = await readSnapshot(handle.wb);
    near(shortfall.stub.closingCash, -71, 'funding shortfall cash');
    near(shortfall.financing.debtClosingFace[0], 0, 'funding shortfall debt');
    assert.equal(shortfall.financing.fundingStatus[0], 'UNFUNDED', 'funding shortfall status');
    await inputs.setCell('B6', 100);
    await inputs.setCell('B24', 200);
    await inputs.setCell(`B${f.debtRedemption}`, 30);

    await inputs.setCell(`B${f.operatingPayment}`, null);
    await handle.wb.calculate();
    await settle();
    const missing = await readSnapshot(handle.wb);
    assert.equal(missing.financingGateStatus, 'FAIL', 'missing required P8B payment');
    await inputs.setCell(`B${f.operatingPayment}`, 16);
    await handle.wb.calculate();
    await settle();
    const restored = await readSnapshot(handle.wb);
    assert.equal(restored.financingGateStatus, 'PASS', 'restored P8B payment');

    const workbookPath = resolve(runDir, 'p8b-parent-oracle.xlsx');
    await handle.wb.save(workbookPath);
    await settle();
    const result = {
      status: 'PASS',
      fixture: 'P8B_PARENT_ORACLE fictional units; never MSFT evidence',
      inputPath,
      workbookPath,
      base: { ebit: 53, netIncome: 43, debtClosing: 90, financePpeClosing: 63, financeLiabilityClosing: 55, operatingRouClosing: 88.5, cfo: 74, cash: 109, totalAssets: 465.5, ufcf: 44 },
      financeAddition25: { financePpeClosing: 73, financeLiabilityClosing: 65, cash: 109, ufcf: 34 },
      debtRate10: { netIncome: 37, cfo: 68, cash: 103, ufcf: 44 },
      shortfall: { closingCash: -71, closingDebt: 0, fundingStatus: 'UNFUNDED', noBorrowing: true },
      adverseChecks: { missingRequiredPayment: 'FAIL gate; restored to PASS', numericZeroPipelineInterest: 'PASS', noDebtPlug: 'PASS' },
      formulas: snapshot.formulas,
    };
    await writeFile(resolve(runDir, 'p8b-parent-oracle-verification.json'), `${JSON.stringify(result, null, 2)}\n`, 'utf8');
    console.log(JSON.stringify(result, null, 2));
  } finally {
    await settle();
    handle.wb.dispose();
  }
}

async function adverse() {
  const model = JSON.parse(await readFile(inputPath, 'utf8'));
  const cases = [];
  const f = FINANCING_DRIVER_ROWS;
  const runCase = async (name, mutate, expected) => {
    const handle = await buildAssetWorkbook(clone(model));
    try {
      const inputs = await handle.wb.getSheet('Inputs');
      await mutate(inputs);
      await handle.wb.calculate();
      await settle();
      const snapshot = await readSnapshot(handle.wb);
      assert.equal(snapshot.financingGateStatus, 'FAIL', `${name} gate`);
      cases.push({ name, status: 'PASS', expected, financingGateStatus: snapshot.financingGateStatus });
    } finally {
      await settle();
      handle.wb.dispose();
    }
  };
  await runCase('missing opening operating payment', async (inputs) => inputs.setCell(`B${f.operatingPayment}`, null), 'missing required source input blocks');
  await runCase('invalid opening rate', async (inputs) => inputs.setCell(`B${f.openingOperatingRate}`, null), 'missing calibrated rate blocks');
  const zeroHandle = await buildAssetWorkbook(clone(model));
  try {
    const inputs = await zeroHandle.wb.getSheet('Inputs');
    await inputs.setCell(`B${f.pipelineOperatingInterest}`, 0);
    await zeroHandle.wb.calculate();
    await settle();
    const zeroSnapshot = await readSnapshot(zeroHandle.wb);
    assert.equal(zeroSnapshot.financingGateStatus, 'PASS', 'numeric zero remains valid');
    cases.push({ name: 'numeric zero interest', status: 'PASS', expected: 'supported zero remains valid', financingGateStatus: zeroSnapshot.financingGateStatus });
  } finally {
    await settle();
    zeroHandle.wb.dispose();
  }
  const result = { status: 'PASS', mode: 'P8B adverse input guards', inputPath, cases };
  await writeFile(resolve(runDir, 'p8b-adverse-verification.json'), `${JSON.stringify(result, null, 2)}\n`, 'utf8');
  console.log(JSON.stringify(result, null, 2));
}

async function guard() {
  const model = JSON.parse(await readFile(inputPath, 'utf8'));
  const handle = await buildAssetWorkbook(model);
  try {
    const inputs = await handle.wb.getSheet('Inputs');
    const f = FINANCING_DRIVER_ROWS;
    const originalRate = await inputs.getValue(`B${f.debtCouponRate}`);
    await inputs.setCell(`B${f.debtCouponRate}`, Number(originalRate) * 0.8);
    await handle.wb.calculate();
    await settle();
    const edited = await readSnapshot(handle.wb);
    assert.equal(edited.financingGateStatus, 'PASS', 'bounded rate edit remains mechanical');
    assert.equal(edited.dcfStatus, 'EDITED_UNREVIEWED', 'rate edit invalidates review binding');
    await inputs.setCell(`B${f.debtCouponRate}`, originalRate);
    await handle.wb.calculate();
    await settle();
    const restored = await readSnapshot(handle.wb);
    assert.equal(restored.financingGateStatus, 'PASS', 'exact rate restore gate');
    const result = { status: 'PASS', mode: 'P8B review binding guard', inputPath, adverseChecks: { boundedRateEdit: 'EDITED_UNREVIEWED', exactRestore: restored.dcfStatus } };
    await writeFile(resolve(runDir, 'p8b-guard-verification.json'), `${JSON.stringify(result, null, 2)}\n`, 'utf8');
    console.log(JSON.stringify(result, null, 2));
  } finally {
    await settle();
    handle.wb.dispose();
  }
}

if (command === 'authority') await authority();
else if (command === 'binding') await binding();
else if (command === 'oracle') await oracle();
else if (command === 'adverse') await adverse();
else if (command === 'guard') await guard();
else throw new Error(`Unknown P8B command: ${command}`);
