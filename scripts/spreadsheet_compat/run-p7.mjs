import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { createWorkbook } from '@mog-sdk/sdk';
import { buildAssetWorkbook, inspectAssetWorkbook, readSnapshot, P7_DRIVER_ROWS, PERIODS, TOLERANCE } from './asset_model.mjs';

const [, , command = 'build', inputArg, runArg] = process.argv;
const inputPath = resolve(inputArg ?? 'data/build-guide-p7/model-input.json');
const runDir = resolve(runArg ?? 'data/build-guide-p7/live-r1');
const workbookPath = resolve(runDir, 'working-capital-model.xlsx');
const sha256 = async (path) => createHash('sha256').update(await readFile(path)).digest('hex');
const near = (actual, expected, label) => assert.ok(typeof actual === 'number' && Math.abs(actual - expected) <= TOLERANCE, `${label}: expected ${expected}, got ${actual}`);
const changed = (before, after, index, label) => assert.ok(Math.abs(Number(after[index]) - Number(before[index])) > TOLERANCE, `${label} did not change at ${PERIODS[index]}`);
const settle = () => new Promise((resolve) => setTimeout(resolve, 150));
const recalculate = async (wb) => { await wb.calculate(); await settle(); };

function expectedStatus(model) {
  return model.p7_decision?.status ?? model.working_capital_decision?.status ?? 'UNREVIEWED_PROVISIONAL';
}

async function save(path, model) {
  const handle = await buildAssetWorkbook(model);
  try { await handle.wb.save(path); await settle(); } finally { await settle(); handle.wb.dispose(); }
}

async function inspect(path) {
  const wb = await createWorkbook(path, { userTimezone: 'UTC' });
  try { return await readSnapshot(wb); } finally { wb.dispose(); }
}

const cloneModel = (model) => JSON.parse(JSON.stringify(model));

async function expectBuildRejection(model, label) {
  let handle;
  try {
    handle = await buildAssetWorkbook(model);
  } catch (error) {
    return { label, status: 'REJECTED', error: String(error?.message ?? error) };
  }
  handle.wb.dispose();
  throw new Error(`${label} unexpectedly accepted`);
}

async function guard() {
  const model = JSON.parse(await readFile(inputPath, 'utf8'));
  const cases = [
    ['parent-null-dso', (value) => { value.working_capital_forecast.inputs.current_ar_dso = null; }],
    ['blank-dso', (value) => { value.working_capital_forecast.inputs.current_ar_dso = ''; }],
    ['whitespace-dso', (value) => { value.working_capital_forecast.inputs.current_ar_dso = '  \t'; }],
    ['boolean-dso', (value) => { value.working_capital_forecast.inputs.current_ar_dso = false; }],
    ['missing-source-numerator', (value) => { delete value.working_capital_packet.contract_bridge.recognized_revenue; }],
    ['null-source-lock', (value) => { value.working_capital_forecast.inputs.contract_recognition_share = null; }],
    ['boolean-source-lock', (value) => { value.working_capital_forecast.inputs.contract_recognition_share = false; }],
    ['missing-compensation-multiplier', (value) => { delete value.working_capital_forecast.inputs.accrued_compensation_multiplier; }],
    ['null-compensation-multiplier', (value) => { value.working_capital_forecast.inputs.accrued_compensation_multiplier = null; }],
    ['blank-compensation-multiplier', (value) => { value.working_capital_forecast.inputs.accrued_compensation_multiplier = '  '; }],
    ['boolean-compensation-multiplier', (value) => { value.working_capital_forecast.inputs.accrued_compensation_multiplier = false; }],
    ['stale-compensation-baseline', (value) => { value.working_capital_forecast.inputs.accrued_compensation_baseline += 0.001; }],
    ['stale-compensation-effective-ratio', (value) => { value.working_capital_forecast.inputs.accrued_compensation_effective_ratio += 0.001; }],
    ['null-period-days', (value) => { value.working_capital_forecast.periods[0].days = null; }],
    ['blank-period-days', (value) => { value.working_capital_forecast.periods[0].days = '  '; }],
    ['null-opening-driver', (value) => { value.working_capital_forecast.inputs.opening_other_oca_residual = null; }],
  ];
  const rejected = [];
  for (const [label, mutate] of cases) {
    const value = cloneModel(model);
    if (label !== 'parent-null-dso') value.working_capital_forecast.inputs.current_ar_dso = 0;
    mutate(value);
    rejected.push(await expectBuildRejection(value, label));
  }

  const zeroModel = cloneModel(model);
  zeroModel.working_capital_forecast.inputs.current_ar_dso = 0;
  const zeroHandle = await buildAssetWorkbook(zeroModel);
  let zeroProof;
  try {
    const inputs = await zeroHandle.wb.getSheet('Inputs');
    zeroProof = { dso: await inputs.getValue(`B${P7_DRIVER_ROWS.dso}`), gate: await inputs.getValue(`B${P7_DRIVER_ROWS.gate}`) };
  } finally { zeroHandle.wb.dispose(); }
  assert.equal(zeroProof.dso, 0, 'numeric zero DSO must remain zero');
  assert.equal(zeroProof.gate, 'PASS', 'numeric zero DSO must pass P7 gate');

  const evidence = { status: 'PASS', inputPath, rejected, numericZero: zeroProof, formulaAuthority: 'Mog formulas; P7 boundary validation precedes workbook construction' };
  await mkdir(runDir, { recursive: true });
  await writeFile(resolve(runDir, 'p7-null-guard-verification.json'), `${JSON.stringify(evidence, null, 2)}\n`, 'utf8');
  console.log(JSON.stringify(evidence, null, 2));
}

async function authority() {
  const model = JSON.parse(await readFile(inputPath, 'utf8'));
  await mkdir(runDir, { recursive: true });
  const path = resolve(runDir, 'working-capital-authority.xlsx');
  await save(path, model);
  const snapshot = await inspectAssetWorkbook(path);
  await writeFile(resolve(runDir, 'working-capital-verification.json'), `${JSON.stringify({ status: 'PASS', mode: 'Mog calculation-only P7 preview', inputPath, workbookPath: path, snapshot, formulaAuthority: 'Mog formulas; Python fields are diagnostic only' }, null, 2)}\n`, 'utf8');
  console.log(JSON.stringify({ status: 'PASS', workbookPath: path, snapshot }, null, 2));
}

async function build() {
  const model = JSON.parse(await readFile(inputPath, 'utf8'));
  await mkdir(runDir, { recursive: true });
  const candidate = resolve(runDir, 'working-capital-candidate.xlsx');
  const rebuilt = resolve(runDir, 'working-capital-rebuild.xlsx');
  await save(candidate, model);
  const base = await inspectAssetWorkbook(candidate);
  const expected = expectedStatus(model);
  assert.equal(base.combinedDecisionStatus, expected, `combined status expected ${expected}`);
  assert.equal(base.p7DriverStatus, 'PASS', 'P7 driver gate');
  assert.ok(base.workingCapital, 'WorkingCapital sheet missing');
  assert.ok(base.workingCapital.cashConversionNwc.every((value) => Number.isFinite(Number(value))), 'operating NWC must remain numeric');
  await save(rebuilt, model);
  const rebuiltSnapshot = await inspectAssetWorkbook(rebuilt);
  assert.deepEqual(base, rebuiltSnapshot, 'P7 Mog rebuild snapshot');
  const handle = await buildAssetWorkbook(model);
  const proof = { baseStatus: { combined: base.combinedDecisionStatus, dcf: base.dcfStatus }, sourceLocks: null, accruedCompensationDriver: null, dsoEdit: null, billingEdit: null, compensationEdit: null, reviewBinding: null, missingRecovery: null, literalNarrative: null };
  try {
    const inputs = await handle.wb.getSheet('Inputs');
    const wc = await handle.wb.getSheet('WorkingCapital');
    const cash = await handle.wb.getSheet('CashFlow');
    const balanceSheet = await handle.wb.getSheet('BalanceSheet');
    const review = await handle.wb.getSheet('Review');
    const sourceLocks = model.working_capital_forecast.inputs.source_locked_parameters;
    near(await inputs.getValue(`B${P7_DRIVER_ROWS.contractBillingsRatio}`), Number(sourceLocks.contract_billings_to_recognition), 'application-locked billings base');
    near(await inputs.getValue(`B${P7_DRIVER_ROWS.contractRecognitionShare}`), Number(sourceLocks.contract_recognition_share), 'application-locked recognition share');
    near(await inputs.getValue(`B${P7_DRIVER_ROWS.currentContractShare}`), Number(sourceLocks.current_contract_presentation_share), 'application-locked presentation share');
    proof.sourceLocks = { billingsBase: await inputs.getValue(`B${P7_DRIVER_ROWS.contractBillingsRatio}`), recognitionShare: await inputs.getValue(`B${P7_DRIVER_ROWS.contractRecognitionShare}`), presentationShare: await inputs.getValue(`B${P7_DRIVER_ROWS.currentContractShare}`) };
    near(await inputs.getValue(`B${P7_DRIVER_ROWS.accruedCompensationBaseline}`), Number(model.working_capital_forecast.inputs.accrued_compensation_baseline), 'application-derived accrued compensation baseline');
    near(await inputs.getValue(`B${P7_DRIVER_ROWS.accruedCompensationEffectiveRatio}`), Number(model.working_capital_forecast.inputs.accrued_compensation_effective_ratio), 'effective accrued compensation ratio');
    const compensationFormula = await wc.getFormula('B28');
    assert.ok(compensationFormula.includes(`$B$${P7_DRIVER_ROWS.accruedCompensationBaseline}`) && compensationFormula.includes(`$B$${P7_DRIVER_ROWS.accruedCompensationMultiplier}`), 'accrued compensation formula binding');
    proof.accruedCompensationDriver = { baseline: await inputs.getValue(`B${P7_DRIVER_ROWS.accruedCompensationBaseline}`), multiplier: await inputs.getValue(`B${P7_DRIVER_ROWS.accruedCompensationMultiplier}`), effectiveRatio: await inputs.getValue(`B${P7_DRIVER_ROWS.accruedCompensationEffectiveRatio}`), units: 'baseline ratio; multiplier dimensionless; effective ratio' };
    const dsoAddress = `B${P7_DRIVER_ROWS.dso}`;
    const dso = await inputs.getValue(dsoAddress);
    const arBase = await wc.getValue('B10');
    const cashBase = await cash.getValue('B15');
    await inputs.setCell(dsoAddress, dso + 10); await recalculate(handle.wb);
    const arChanged = await wc.getValue('B10'); const cashChanged = await cash.getValue('B15');
    assert.ok(Math.abs(Number(arChanged) - Number(arBase)) > TOLERANCE, 'DSO edit did not change AR');
    assert.ok(Math.abs(Number(cashChanged) - Number(cashBase)) > TOLERANCE, 'DSO edit did not change cash');
    proof.dsoEdit = { address: dsoAddress, base: dso, arBase, arChanged, cashBase, cashChanged, status: await inputs.getValue(`B${P7_DRIVER_ROWS.gate}`) };
    await inputs.setCell(dsoAddress, dso); await recalculate(handle.wb);

    const billingAddress = `B${P7_DRIVER_ROWS.contractBillingMultiplier}`;
    const multiplier = await inputs.getValue(billingAddress); const contractBase = await wc.getValue('B33'); const billingCashBase = await cash.getValue('B15');
    await inputs.setCell(billingAddress, multiplier + 0.1); await recalculate(handle.wb);
    const contractChanged = await wc.getValue('B33'); const billingCashChanged = await cash.getValue('B15');
    assert.ok(Math.abs(Number(contractChanged) - Number(contractBase)) > TOLERANCE, 'billing edit did not change contract liability');
    assert.ok(Math.abs(Number(billingCashChanged) - Number(billingCashBase)) > TOLERANCE, 'billing edit did not change cash');
    proof.billingEdit = { address: billingAddress, base: multiplier, contractBase, contractChanged, billingCashBase, billingCashChanged };
    await inputs.setCell(billingAddress, multiplier); await recalculate(handle.wb);

    const compensationAddress = `B${P7_DRIVER_ROWS.accruedCompensationMultiplier}`;
    const compensationMultiplier = await inputs.getValue(compensationAddress);
    const accruedBase = await wc.getValue('B28'); const accruedCashBase = await cash.getValue('B15'); const accruedCfoBase = await cash.getValue('B9');
    await inputs.setCell(compensationAddress, 1.2); await recalculate(handle.wb);
    const accruedHigh = await wc.getValue('B28'); const accruedHighCash = await cash.getValue('B15'); const accruedHighCfo = await cash.getValue('B9');
    assert.ok(Number(accruedHigh) > Number(accruedBase), 'high compensation multiplier did not increase balance');
    assert.ok(Number(accruedHighCash) > Number(accruedCashBase), 'high compensation multiplier did not increase cash');
    assert.ok(Number(accruedHighCfo) > Number(accruedCfoBase), 'high compensation multiplier did not increase CFO');
    assert.ok(Math.abs(Number(await balanceSheet.getValue('B25'))) <= TOLERANCE, 'high compensation multiplier broke balance');
    assert.equal(await review.getValue('B3'), 'EDITED_UNREVIEWED', 'driver edit did not downgrade review binding');
    await inputs.setCell(compensationAddress, 0.8); await recalculate(handle.wb);
    const accruedLow = await wc.getValue('B28'); const accruedLowCash = await cash.getValue('B15'); const accruedLowCfo = await cash.getValue('B9');
    assert.ok(Number(accruedLow) < Number(accruedBase), 'low compensation multiplier did not decrease balance');
    assert.ok(Number(accruedLowCash) < Number(accruedCashBase), 'low compensation multiplier did not decrease cash');
    assert.ok(Number(accruedLowCfo) < Number(accruedCfoBase), 'low compensation multiplier did not decrease CFO');
    assert.ok(Math.abs(Number(await balanceSheet.getValue('B25'))) <= TOLERANCE, 'low compensation multiplier broke balance');
    proof.compensationEdit = { address: compensationAddress, base: compensationMultiplier, accruedBase, accruedHigh, accruedLow, cfoBase: accruedCfoBase, cfoHigh: accruedHighCfo, cfoLow: accruedLowCfo, cashBase: accruedCashBase, cashHigh: accruedHighCash, cashLow: accruedLowCash };
    await inputs.setCell(compensationAddress, compensationMultiplier); await recalculate(handle.wb);
    const restoredReviewStatus = await review.getValue('B3');
    assert.equal(restoredReviewStatus, base.dcfStatus === 'OFFLINE_FIXTURE' ? 'OFFLINE_FIXTURE' : 'SYSTEM_REVIEWED_PROVISIONAL', 'restored driver did not restore review binding');
    proof.reviewBinding = { edited: 'EDITED_UNREVIEWED', restored: restoredReviewStatus };

    await inputs.setCell(dsoAddress, null); await recalculate(handle.wb);
    assert.equal(await inputs.getValue(`B${P7_DRIVER_ROWS.gate}`), 'FAIL', 'missing DSO must fail P7 gate');
    assert.equal(await (await handle.wb.getSheet('DCF')).getValue('B18'), 'BLOCKED', 'missing DSO must block valuation');
    await inputs.setCell(dsoAddress, 0); await recalculate(handle.wb);
    assert.equal(await inputs.getValue(`B${P7_DRIVER_ROWS.gate}`), 'PASS', 'numeric zero DSO recovers');
    proof.missingRecovery = { address: dsoAddress, missing: 'FAIL/BLOCKED', zero: 'PASS' };
    await inputs.setCell(dsoAddress, dso); await recalculate(handle.wb);

    const note = await wc.getValue('B2'); await wc.setCell('B2', '=SUM(1,1)', { literal: true }); await recalculate(handle.wb);
    assert.equal(await wc.getFormula('B2'), null, 'P7 narrative must stay literal');
    assert.equal(await wc.getValue('B2'), '=SUM(1,1)', 'P7 narrative literal changed');
    proof.literalNarrative = { address: 'WorkingCapital!B2', value: await wc.getValue('B2'), formula: await wc.getFormula('B2') };
    await wc.setCell('B2', note, { literal: true }); await recalculate(handle.wb);
  } finally { await settle(); handle.wb.dispose(); }
  const publishedSha256 = await sha256(candidate); const rebuiltSha256 = await sha256(rebuilt);
  await rename(candidate, workbookPath);
  const verification = { status: 'PASS', inputPath, workbookPath, expectedStatus: expected, publishedSha256, rebuiltSha256, snapshot: base, rebuiltSnapshot, proof, checks: base.checks, formulaAuthority: 'Mog/Excel formulas; Python fields are diagnostic only' };
  await writeFile(resolve(runDir, 'working-capital-verification.json'), `${JSON.stringify(verification, null, 2)}\n`, 'utf8');
  console.log(JSON.stringify({ status: 'PASS', workbookPath, verificationPath: resolve(runDir, 'working-capital-verification.json'), workingCapital: base.workingCapital, proof }, null, 2));
}

if (command === 'authority') await authority();
else if (command === 'build') await build();
else if (command === 'guard') await guard();
else if (command === 'inspect') console.log(JSON.stringify(await inspect(workbookPath), null, 2));
else throw new Error(`Unknown P7 command: ${command}`);
process.exit(0);
