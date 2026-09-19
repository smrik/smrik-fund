import assert from 'node:assert/strict';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { createWorkbook } from '@mog-sdk/sdk';
import { buildAssetWorkbook, P7_DRIVER_ROWS, readSnapshot, TOLERANCE } from './asset_model.mjs';

// This fixture is deliberately fictional and never supplies MSFT evidence or
// production assumptions. It exercises the formula-owned P7 consequences.
const [, , inputArg = 'data/build-guide-p7/offline-r4/model-input.json', runArg = 'data/build-guide-p7/offline-r4/compensation-oracle-terminal'] = process.argv;
const inputPath = resolve(inputArg);
const runDir = resolve(runArg);
const workbookPath = resolve(runDir, 'p7-parent-oracle.xlsx');
const verificationPath = resolve(runDir, 'p7-parent-oracle-verification.json');
const settle = () => new Promise((resolvePromise) => setTimeout(resolvePromise, 150));
const recalculate = async (wb) => { await wb.calculate(); await settle(); };
const near = (actual, expected, label) => assert.ok(Math.abs(Number(actual) - expected) <= TOLERANCE, `${label}: expected ${expected}, got ${actual}`);

const model = JSON.parse(await readFile(inputPath, 'utf8'));
assert.ok(Object.values(model.working_capital_packet?.historical_bridge ?? {}).some((item) => Math.abs(Number(item.unexplained_difference)) > TOLERANCE), 'unresolved historical bridge must remain visible');
await mkdir(runDir, { recursive: true });

const handle = await buildAssetWorkbook(model);
const inputs = await handle.wb.getSheet('Inputs');
const wc = await handle.wb.getSheet('WorkingCapital');
const income = await handle.wb.getSheet('Income');
const cash = await handle.wb.getSheet('CashFlow');
const bs = await handle.wb.getSheet('BalanceSheet');
const dcf = await handle.wb.getSheet('DCF');

const set = async (address, value) => { await inputs.setCell(address, value); };
const synthetic = {
  // P5/P6 controls produce revenue 90, COGS 54, NI 12, depreciation 4,
  // cash capex 8 and opening cash/PP&E/equity/debt from the parent oracle.
  'B6': 30, 'B7': 0, 'B8': 15, 'B9': 5, 'B10': 8, 'B11': 100, 'B12': 0, 'B13': 100,
  'B14': 0, 'B15': 0, 'B16': 0, 'B17': 0, 'B18': 0, 'B19': 158, 'B20': 16, 'B21': 40,
  'B22': 0, 'B23': 83, 'B24': 75, 'B29': 6.25, 'B30': 8, 'B31': 0, 'B32': 8 / 90, 'B51': 0,
  'B33': 0, 'B34': 0, 'B35': 0.25, 'B36': 0, 'B37': 0.08, 'B38': 0.02, 'B43': 90, 'B57': 4,
  'B64': 0, 'B65': 0, 'B66': 0, 'B68': 0.6, 'B69': 20 / 90, 'B70': 0, 'B71': 0,
  'B75': 90, 'C75': 90, 'D75': 90, 'B76': 60, 'C76': 60, 'D76': 60, 'B77': 60, 'C77': 60, 'D77': 60,
  [`B${P7_DRIVER_ROWS.dso}`]: 20, [`B${P7_DRIVER_ROWS.dio}`]: 10, [`B${P7_DRIVER_ROWS.dpo}`]: 30,
  [`B${P7_DRIVER_ROWS.accruedCompensationMultiplier}`]: 1, [`B${P7_DRIVER_ROWS.serverReceivableShock}`]: 0,
  // The 1.2 fictional billing ratio is intentionally outside the production
  // bounded shock and causes the fixture input gate to fail; formulas remain
  // inspectable for this independent oracle.
  [`B${P7_DRIVER_ROWS.contractBillingsRatio}`]: 1.2, [`B${P7_DRIVER_ROWS.contractBillingMultiplier}`]: 1,
  [`B${P7_DRIVER_ROWS.contractRecognitionShare}`]: 1, [`B${P7_DRIVER_ROWS.otherOcaResidual}`]: 8,
  [`B${P7_DRIVER_ROWS.otherOclResidual}`]: 7, [`B${P7_DRIVER_ROWS.longTermAr}`]: 0,
  [`B${P7_DRIVER_ROWS.contractCurrent}`]: 20, [`B${P7_DRIVER_ROWS.contractNoncurrent}`]: 0,
  [`B${P7_DRIVER_ROWS.serverReceivables}`]: 0, [`B${P7_DRIVER_ROWS.operatingAp}`]: 16,
  [`B${P7_DRIVER_ROWS.accruedCompensation}`]: 0, [`B${P7_DRIVER_ROWS.periodDays}`]: 90,
  [`C${P7_DRIVER_ROWS.periodDays}`]: 365, [`D${P7_DRIVER_ROWS.periodDays}`]: 365, [`E${P7_DRIVER_ROWS.periodDays}`]: 365,
  [`F${P7_DRIVER_ROWS.periodDays}`]: 365, [`G${P7_DRIVER_ROWS.periodDays}`]: 365, [`H${P7_DRIVER_ROWS.periodDays}`]: 365,
  [`I${P7_DRIVER_ROWS.periodDays}`]: 365, [`J${P7_DRIVER_ROWS.periodDays}`]: 365, [`K${P7_DRIVER_ROWS.periodDays}`]: 365,
  [`L${P7_DRIVER_ROWS.periodDays}`]: 365, [`B${P7_DRIVER_ROWS.currentContractShare}`]: 1,
};
for (const [address, value] of Object.entries(synthetic)) await set(address, value);
await recalculate(handle.wb);

const base = await readSnapshot(handle.wb);
near(await wc.getValue('B10'), 20, 'base AR');
near(await wc.getValue('B13'), 6, 'base inventory');
near(await wc.getValue('B16'), 18, 'base operating AP');
near(await wc.getValue('B33'), 38, 'base contract liability');
near(await wc.getValue('B41'), -29, 'base cash-conversion NWC');
near(await wc.getValue('B42'), -14, 'base NWC change');
near(await wc.getValue('B43'), 14, 'base CFO contribution');
near(await income.getValue('B15'), 12, 'base net income');
near(await cash.getValue('B9'), 30, 'base CFO');
near(await cash.getValue('B15'), 52, 'base cash');
near(await bs.getValue('B11'), 104, 'base closing PP&E');
near(await bs.getValue('B25'), 0, 'base balance difference');

await set(`B${P7_DRIVER_ROWS.dso}`, 30); await recalculate(handle.wb);
const dsoShock = await readSnapshot(handle.wb);
near(await wc.getValue('B10'), 30, 'DSO AR');
near(await wc.getValue('B41'), -19, 'DSO NWC');
near(await cash.getValue('B9'), 20, 'DSO CFO');
near(await cash.getValue('B15'), 42, 'DSO cash');
await set(`B${P7_DRIVER_ROWS.dso}`, 20); await recalculate(handle.wb);

await set(`B${P7_DRIVER_ROWS.contractBillingsRatio}`, 1.0); await recalculate(handle.wb);
const billingShock = await readSnapshot(handle.wb);
near(await wc.getValue('B33'), 20, 'billing contract liability');
near(await wc.getValue('B41'), -11, 'billing NWC');
near(await cash.getValue('B9'), 12, 'billing CFO');
near(await cash.getValue('B15'), 34, 'billing cash');

await set(`B${P7_DRIVER_ROWS.dso}`, null); await recalculate(handle.wb);
assert.equal(await inputs.getValue(`B${P7_DRIVER_ROWS.gate}`), 'FAIL', 'missing DSO must fail oracle gate');
assert.equal(await dcf.getValue('B18'), 'BLOCKED', 'missing DSO must block oracle valuation');
await set(`B${P7_DRIVER_ROWS.dso}`, 0); await recalculate(handle.wb);
assert.equal(await inputs.getValue(`B${P7_DRIVER_ROWS.gate}`), 'PASS', 'supported zero DSO must recover the gate');

// Independent compensation oracle: the cloned packet supplies the intended
// synthetic TTM denominator/opening balance; B101 remains its workbook formula.
const compensationModel = JSON.parse(JSON.stringify(model));
const syntheticTtmRevenue = 365;
const syntheticOpeningAccruedCompensation = 10;
const syntheticBaseline = syntheticOpeningAccruedCompensation / syntheticTtmRevenue;
compensationModel.packet.facts.ttm.revenue.value = syntheticTtmRevenue;
compensationModel.working_capital_packet.ttm_revenue = syntheticTtmRevenue;
compensationModel.working_capital_packet.balances.accrued_compensation.Q3FY2026 = syntheticOpeningAccruedCompensation;
compensationModel.working_capital_forecast.inputs.accrued_compensation_baseline = syntheticBaseline;
compensationModel.working_capital_forecast.inputs.accrued_compensation_effective_ratio = syntheticBaseline;

const compensationHandle = await buildAssetWorkbook(compensationModel);
const compensationInputs = await compensationHandle.wb.getSheet('Inputs');
const compensationWc = await compensationHandle.wb.getSheet('WorkingCapital');
const compensationBs = await compensationHandle.wb.getSheet('BalanceSheet');
const setCompensation = async (address, value) => { await compensationInputs.setCell(address, value); };
const compensationSynthetic = {
  ...synthetic,
  'B19': 158, 'B23': 93, 'B24': 65,
  'B43': syntheticTtmRevenue, 'B57': 4 * syntheticTtmRevenue / 90,
  [`B${P7_DRIVER_ROWS.accruedCompensation}`]: syntheticOpeningAccruedCompensation,
};
for (const [address, value] of Object.entries(compensationSynthetic)) {
  if (address !== `B${P7_DRIVER_ROWS.accruedCompensationBaseline}`) await setCompensation(address, value);
}
await recalculate(compensationHandle.wb);
near(await compensationInputs.getValue('B43'), syntheticTtmRevenue, 'synthetic TTM revenue input');
near(await compensationInputs.getValue('B14'), 0, 'synthetic opening other noncurrent asset');
near(await compensationInputs.getValue('B19'), 158, 'synthetic opening total assets anchor');
near(await compensationInputs.getValue('B23'), 93, 'synthetic opening total liabilities anchor');
near(await compensationInputs.getValue('B24'), 65, 'synthetic opening equity anchor');
near(await compensationInputs.getValue('B19'), 30 + 0 + 15 + 5 + 8 + 100 + 0 + 0 + 0 + 0 + 0, 'synthetic opening assets arithmetic');
near(await compensationInputs.getValue('B23') + await compensationInputs.getValue('B24'), 158, 'synthetic opening liabilities plus equity');
near(await compensationInputs.getValue(`B${P7_DRIVER_ROWS.accruedCompensation}`), syntheticOpeningAccruedCompensation, 'synthetic opening accrued compensation input');
near(await compensationInputs.getValue(`B${P7_DRIVER_ROWS.accruedCompensationBaseline}`), syntheticBaseline, 'formula-derived source baseline');
assert.equal(String(await compensationInputs.getFormula(`B${P7_DRIVER_ROWS.accruedCompensationBaseline}`)).replaceAll(' ', ''), '=B97/B43', 'source baseline must remain formula-owned');
assert.match(String(await compensationWc.getFormula('B28')), /Inputs!\$B\$101.*Inputs!\$B\$85/, 'accrued compensation closing must use baseline and multiplier');

const compensationCases = [
  { name: 'multiplier-1.0', multiplier: 1, accrued: 10, nwc: -39, nwcChange: -14, cfo: 30, cash: 52, equity: 77, liabilities: 113, assets: 190 },
  { name: 'multiplier-1.2', multiplier: 1.2, accrued: 12, nwc: -41, nwcChange: -16, cfo: 32, cash: 54, equity: 77, liabilities: 115, assets: 192 },
  { name: 'multiplier-0.8', multiplier: 0.8, accrued: 8, nwc: -37, nwcChange: -12, cfo: 28, cash: 50, equity: 77, liabilities: 111, assets: 188 },
];
const compensationResults = {};
for (const scenario of compensationCases) {
  await setCompensation(`B${P7_DRIVER_ROWS.accruedCompensationMultiplier}`, scenario.multiplier);
  await recalculate(compensationHandle.wb);
  const snapshot = await readSnapshot(compensationHandle.wb);
  const assets = await compensationBs.getValue('B17');
  near(snapshot.workingCapital.accruedCompensationClosing[0], scenario.accrued, `${scenario.name} accrued compensation`);
  near(snapshot.workingCapital.cashConversionNwc[0], scenario.nwc, `${scenario.name} NWC`);
  near(snapshot.workingCapital.cashConversionNwcChange[0], scenario.nwcChange, `${scenario.name} NWC change`);
  near(snapshot.stub.netIncome, 12, `${scenario.name} net income`);
  near(snapshot.stub.cfo, scenario.cfo, `${scenario.name} CFO`);
  near(snapshot.stub.closingCash, scenario.cash, `${scenario.name} closing cash`);
  near(await compensationHandle.wb.getSheet('Schedules').then((sheet) => sheet.getValue('B28')), scenario.equity, `${scenario.name} closing equity`);
  near(await compensationBs.getValue('B22'), scenario.liabilities, `${scenario.name} closing liabilities`);
  near(Number(await compensationBs.getValue('B22')) + Number(await compensationBs.getValue('B23')), scenario.assets, `${scenario.name} closing liabilities plus equity`);
  near(assets, scenario.assets, `${scenario.name} total assets`);
  near(snapshot.stub.balanceDifference, 0, `${scenario.name} balance difference`);
  compensationResults[scenario.name] = {
    multiplier: scenario.multiplier,
    accruedCompensation: snapshot.workingCapital.accruedCompensationClosing[0],
    nwc: snapshot.workingCapital.cashConversionNwc[0],
    nwcChange: snapshot.workingCapital.cashConversionNwcChange[0],
    cfo: snapshot.stub.cfo,
    cash: snapshot.stub.closingCash,
    netIncome: snapshot.stub.netIncome,
    liabilities: await compensationBs.getValue('B22'),
    equity: await compensationHandle.wb.getSheet('Schedules').then((sheet) => sheet.getValue('B28')),
    assets,
    balanceDifference: snapshot.stub.balanceDifference,
  };
}
await setCompensation(`B${P7_DRIVER_ROWS.accruedCompensationMultiplier}`, 1);
await recalculate(compensationHandle.wb);

const result = {
  status: 'PASS',
  fixture: 'P7_PARENT_ORACLE fictional 90-day case; never MSFT evidence',
  inputPath,
  workbookPath,
  historicalBridge: { unresolved: true, sample: model.working_capital_packet.historical_bridge.current_accounts_receivable },
  base: { ar: base.workingCapital.currentArClosing[0], inventory: base.workingCapital.inventoryClosing[0], ap: base.workingCapital.operatingApClosing[0], contract: base.workingCapital.contractLiabilityClosing[0], nwc: base.workingCapital.cashConversionNwc[0], nwcChange: base.workingCapital.cashConversionNwcChange[0], cfoContribution: base.workingCapital.cfoContribution[0], cfo: base.stub.cfo, cash: base.stub.closingCash, ppe: base.stub.closingNetPpe, balanceDifference: base.stub.balanceDifference },
  dsoShock: { nwc: dsoShock.workingCapital.cashConversionNwc[0], cfo: dsoShock.stub.cfo, cash: dsoShock.stub.closingCash },
  billingShock: { contract: billingShock.workingCapital.contractLiabilityClosing[0], nwc: billingShock.workingCapital.cashConversionNwc[0], cfo: billingShock.stub.cfo, cash: billingShock.stub.closingCash },
  missingAndZero: 'missing DSO FAIL/BLOCKED; zero DSO PASS after restoring bounded fixture ratio',
  compensationOracle: {
    sourceTtmRevenue: syntheticTtmRevenue,
    openingAccruedCompensation: syntheticOpeningAccruedCompensation,
    sourceBaseline: syntheticBaseline,
    baselineFormula: await compensationInputs.getFormula(`B${P7_DRIVER_ROWS.accruedCompensationBaseline}`),
    effectiveRatioFormula: await compensationInputs.getFormula(`B${P7_DRIVER_ROWS.accruedCompensationEffectiveRatio}`),
    closingFormula: await compensationWc.getFormula('B28'),
    cases: compensationResults,
  },
  formulaAuthority: 'Mog formulas; synthetic fixture inputs only',
};
const compensationWorkbookPath = resolve(runDir, 'p7-compensation-oracle.xlsx');
await handle.wb.save(workbookPath); await settle(); handle.wb.dispose();
await compensationHandle.wb.save(compensationWorkbookPath); await settle(); compensationHandle.wb.dispose();
await writeFile(verificationPath, `${JSON.stringify(result, null, 2)}\n`, 'utf8');
console.log(JSON.stringify(result, null, 2));
