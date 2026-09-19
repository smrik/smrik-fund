import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import {
  DEFAULT_INPUTS,
  ENGINE_VERSION,
  MODEL_ROWS,
  MODEL_VERSION,
  PERIODS,
  REQUIRED_INPUT_ADDRESSES,
  REQUIRED_INPUT_COUNT,
  TOLERANCE,
  buildFictionalWorkbook,
  periodCell,
  readCriticalValues,
  readPeriodValues,
  readValuation,
  validateFixtureInputs,
  validatePeriods,
} from './fictional_model.mjs';

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(SCRIPT_DIR, '..', '..');
const OUTPUT = resolve(ROOT, 'data', 'build-guide-p4');
const RUN_ID = process.env.P4_R1_RUN_ID ?? `run-r1-${new Date().toISOString().replace(/[-:.]/g, '').replace(/Z$/, 'Z')}`;
const RUN_DIR = resolve(OUTPUT, RUN_ID);
const BASE = resolve(RUN_DIR, 'fictional-linked-model.xlsx');
const EDITED = resolve(RUN_DIR, 'fictional-linked-model-excel-edited.xlsx');
const BROKEN = resolve(RUN_DIR, 'fictional-linked-model-broken.xlsx');
const INPUT_MANIFEST = resolve(RUN_DIR, 'fictional-fixture-input.json');
const EXPECTATIONS = resolve(RUN_DIR, 'excel-expectations.json');
const VERIFICATION = resolve(RUN_DIR, 'p4-r1-verification.json');
const EXCEL_RESULTS = resolve(RUN_DIR, 'excel-verification.json');
const EVIDENCE = resolve(RUN_DIR, 'evidence');
const EXCEL_LOG = resolve(EVIDENCE, 'excel-verification.log');
const INTERRUPT_LOG = resolve(EVIDENCE, 'interrupted-candidate.log');

const EXPECTED_STUB = Object.freeze({
  revenue: 25,
  cashOperatingCosts: -15,
  depreciation: -2.5,
  ebit: 7.5,
  interestExpense: -0.75,
  netIncome: 5.0625,
  capex: 2.5,
  closingCash: 23.796875,
  closingNetPPE: 50,
  closingEquity: 50.796875,
  assets: 88.796875,
  balanceDifference: 0,
  closingAR: 10,
  closingInventory: 5,
  closingAP: 8,
  increaseNWC: 0,
  cfo: 7.5625,
  dividends: 1.265625,
  ufcf: 5.625,
});

const EXPECTED_FIRST_FULL = Object.freeze({
  revenue: 110,
  cashOperatingCosts: -66,
  depreciation: -10,
  ebit: 34,
  interestExpense: -3,
  netIncome: 23.25,
  capex: 11,
  closingAR: 11,
  closingInventory: 5.5,
  closingAP: 8.8,
  increaseNWC: 0.7,
  cfo: 32.55,
  dividends: 5.8125,
  closingCash: 39.534375,
  closingNetPPE: 51,
  closingEquity: 68.234375,
  assets: 107.034375,
  balanceDifference: 0,
  ufcf: 23.8,
});

function assertClose(actual, expected, label) {
  const got = Number(actual);
  const wanted = Number(expected);
  if (!Number.isFinite(got) || Math.abs(got - wanted) > TOLERANCE) {
    throw new Error(`${label}: expected ${wanted}, got ${actual}`);
  }
}

function assertSnapshot(actual, expected, label) {
  for (const key of Object.keys(expected)) assertClose(actual[key], expected[key], `${label}.${key}`);
}

function sha256(path) {
  return readFile(path).then((bytes) => createHash('sha256').update(bytes).digest('hex'));
}

async function saveWorkbook(path, inputOverrides = {}, brokenReference = false) {
  const { wb } = await buildFictionalWorkbook({ inputOverrides, brokenReference });
  try {
    await wb.save(path);
  } finally {
    wb.dispose();
  }
}

async function snapshot(wb, index) {
  const values = await readCriticalValues(wb, index);
  const valuation = await readValuation(wb);
  return {
    ...values,
    enterpriseValue: valuation.enterpriseValue,
    equityValue: valuation.equityValue,
    perShareValue: valuation.perShareValue,
  };
}

async function inspectMog(path) {
  const { createWorkbook } = await import('@mog-sdk/sdk');
  const wb = await createWorkbook(path, { userTimezone: 'UTC' });
  try {
    const stub = await snapshot(wb, 0);
    const firstFull = await snapshot(wb, 1);
    assertSnapshot(stub, EXPECTED_STUB, 'Mog stub anchor');
    assertSnapshot(firstFull, EXPECTED_FIRST_FULL, 'Mog first-full anchor');
    const checks = await readPeriodValues(wb, 'Checks', 20);
    if (checks.some((value) => value !== 'PASS')) throw new Error(`Mog overall checks failed: ${JSON.stringify(checks)}`);
    const balanceDifferences = await readPeriodValues(wb, 'BalanceSheet', MODEL_ROWS.balanceSheet.difference);
    if (balanceDifferences.some((value) => Math.abs(Number(value)) > TOLERANCE)) throw new Error(`Mog balance checks failed: ${JSON.stringify(balanceDifferences)}`);

    const income = await wb.getSheet('Income');
    const dcf = await wb.getSheet('DCF');
    const review = await wb.getSheet('Review');
    const inputs = await wb.getSheet('Inputs');
    const decisions = await wb.getSheet('Decisions');
    const formulas = {
      ebit: await income.getFormula(periodCell(0, MODEL_ROWS.income.ebit)),
      netIncome: await income.getFormula(periodCell(1, MODEL_ROWS.income.netIncome)),
      ufcf: await dcf.getFormula(periodCell(0, MODEL_ROWS.dcf.ufcf)),
      enterpriseValue: await dcf.getFormula('B15'),
      perShareValue: await dcf.getFormula('B20'),
    };
    if (!Object.values(formulas).every((value) => typeof value === 'string' && value.startsWith('='))) {
      throw new Error(`Mog lost linked formulas: ${JSON.stringify(formulas)}`);
    }
    const literalReadback = {};
    for (const [address, expected] of Object.entries({ B39: '=fictional source excerpt', B40: '+untrusted source note', B41: '@reviewer text' })) {
      const value = await inputs.getValue(address);
      const formula = await inputs.getFormula(address);
      if (value !== expected || formula !== null) throw new Error(`Untrusted literal changed at Inputs!${address}`);
      literalReadback[address] = { value, formula };
    }
    const decisionLiteral = { value: await decisions.getValue('B7'), formula: await decisions.getFormula('B7') };
    if (decisionLiteral.value !== '=untrusted decision excerpt; literal text' || decisionLiteral.formula !== null) throw new Error('Untrusted decision excerpt was evaluated');
    const note = await inputs.comments.getNote('B17');
    if (!note?.content?.includes('Fictional annualized opening revenue')) throw new Error('Input note missing after Mog export');
    const hyperlinkFormula = await review.getFormula('B12');
    if (hyperlinkFormula !== '=HYPERLINK("#\'Inputs\'!A1","Open Inputs")') throw new Error(`Workbook navigation formula mismatch: ${hyperlinkFormula}`);
    return { stub, firstFull, valuation: await readValuation(wb), formulas, literalReadback, decisionLiteral, note, hyperlinkFormula, checks };
  } finally {
    wb.dispose();
  }
}

async function readInputGate(wb) {
  const inputs = await wb.getSheet('Inputs');
  const review = await wb.getSheet('Review');
  const dcf = await wb.getSheet('DCF');
  return {
    count: await inputs.getValue('B34'),
    status: await inputs.getValue('B33'),
    formula: await inputs.getFormula('B34'),
    reviewStatus: await review.getValue('B3'),
    overall: await readPeriodValues(wb, 'Checks', 20),
    requiredCondition: await dcf.getValue('B23'),
    valuationStatus: await dcf.getValue('B24'),
    enterpriseValue: await dcf.getValue('B15'),
    equityValue: await dcf.getValue('B18'),
    perShareValue: await dcf.getValue('B20'),
    requiredChecks: await readPeriodValues(wb, 'Checks', 21),
  };
}

function assertGateStatus(gate, expectedStatus, label) {
  if (gate.status !== expectedStatus) throw new Error(`${label}: expected Inputs!B33=${expectedStatus}, got ${gate.status}`);
  if (gate.requiredCondition !== expectedStatus) throw new Error(`${label}: expected DCF!B23=${expectedStatus}, got ${gate.requiredCondition}`);
  if (gate.reviewStatus !== (expectedStatus === 'PASS' ? 'READY' : 'BLOCKED')) throw new Error(`${label}: unexpected Review!B3=${gate.reviewStatus}`);
  if (gate.valuationStatus !== (expectedStatus === 'PASS' ? 'AVAILABLE' : 'BLOCKED')) throw new Error(`${label}: unexpected DCF!B24=${gate.valuationStatus}`);
  const expectedOverall = expectedStatus === 'PASS' ? 'PASS' : 'FAIL';
  if (gate.overall.some((value) => value !== expectedOverall)) throw new Error(`${label}: unexpected overall checks ${JSON.stringify(gate.overall)}`);
  if (gate.requiredChecks.some((value) => value !== expectedOverall)) throw new Error(`${label}: unexpected required checks ${JSON.stringify(gate.requiredChecks)}`);
}

async function inspectMogR1(path) {
  const { createWorkbook } = await import('@mog-sdk/sdk');
  const wb = await createWorkbook(path, { userTimezone: 'UTC' });
  try {
    const stub = await snapshot(wb, 0);
    const firstFull = await snapshot(wb, 1);
    assertSnapshot(stub, EXPECTED_STUB, 'Mog R1 stub anchor');
    assertSnapshot(firstFull, EXPECTED_FIRST_FULL, 'Mog R1 first-full anchor');
    const checks = await wb.getSheet('Checks');
    const toleranceFormula = await checks.getFormula('B6');
    if (!String(toleranceFormula).includes(`ABS(B5)<=${TOLERANCE}`)) throw new Error(`Mog R1 identity tolerance formula mismatch: ${toleranceFormula}`);
    const gate = await readInputGate(wb);
    if (Number(gate.count) !== REQUIRED_INPUT_COUNT) throw new Error(`Mog R1 input count mismatch: ${gate.count}`);
    const missingFormulaAddresses = REQUIRED_INPUT_ADDRESSES.filter((address) => !String(gate.formula).includes(`ISNUMBER(${address})`));
    if (missingFormulaAddresses.length > 0) throw new Error(`Mog R1 required-input formula omitted: ${missingFormulaAddresses.join(', ')}`);
    assertGateStatus(gate, 'PASS', 'Mog R1 valid build');
    return { stub, firstFull, valuation: await readValuation(wb), gate, toleranceFormula };
  } finally {
    wb.dispose();
  }
}

async function inspectMogLiveInputs(path, base) {
  const { createWorkbook } = await import('@mog-sdk/sdk');
  const wb = await createWorkbook(path, { userTimezone: 'UTC' });
  try {
    const inputs = await wb.getSheet('Inputs');
    const schedules = await wb.getSheet('Schedules');
    const records = {};

    await inputs.setCell('B21', null);
    await wb.calculate();
    records.clearCapex = { gate: await readInputGate(wb), capex: await schedules.getValue('B12'), ufcf: (await readCriticalValues(wb, 0)).ufcf };
    assertGateStatus(records.clearCapex.gate, 'FAIL', 'Mog clear capex');
    if (Number(records.clearCapex.gate.count) !== REQUIRED_INPUT_COUNT - 1) throw new Error(`Mog clear capex count mismatch: ${records.clearCapex.gate.count}`);
    assertClose(records.clearCapex.capex, 0, 'Mog clear capex schedule');
    assertClose(records.clearCapex.ufcf, 8.125, 'Mog clear capex stub UFCF');
    if (records.clearCapex.gate.enterpriseValue !== 'BLOCKED' || records.clearCapex.gate.equityValue !== 'BLOCKED' || records.clearCapex.gate.perShareValue !== 'BLOCKED') {
      throw new Error(`Mog clear capex valuation was not blocked: ${JSON.stringify(records.clearCapex.gate)}`);
    }

    await inputs.setCell('B21', 0);
    await wb.calculate();
    records.zeroCapex = { gate: await readInputGate(wb), capex: await schedules.getValue('B12') };
    assertGateStatus(records.zeroCapex.gate, 'PASS', 'Mog valid zero capex');
    assertClose(records.zeroCapex.capex, 0, 'Mog valid zero capex schedule');
    if (!Number.isFinite(Number(records.zeroCapex.gate.enterpriseValue))) throw new Error('Mog valid zero capex valuation is not numeric');

    await inputs.setCell('B21', DEFAULT_INPUTS.capexRate);
    await inputs.setCell('B24', null);
    await wb.calculate();
    records.clearTax = { gate: await readInputGate(wb), tax: await schedules.getValue('B28'), ufcf: (await readCriticalValues(wb, 0)).ufcf };
    assertGateStatus(records.clearTax.gate, 'FAIL', 'Mog clear tax');
    if (Number(records.clearTax.gate.count) !== REQUIRED_INPUT_COUNT - 1) throw new Error(`Mog clear tax count mismatch: ${records.clearTax.gate.count}`);
    assertClose(records.clearTax.tax, 0, 'Mog clear tax schedule');
    assertClose(records.clearTax.ufcf, 7.5, 'Mog clear tax stub UFCF');

    await inputs.setCell('B24', DEFAULT_INPUTS.taxRate);
    await inputs.setCell('C35', '0', { literal: true });
    await wb.calculate();
    records.textRevenue = { gate: await readInputGate(wb), input: await inputs.getValue('C35'), formula: await inputs.getFormula('C35'), revenue: await (await wb.getSheet('Income')).getValue('C6') };
    assertGateStatus(records.textRevenue.gate, 'FAIL', 'Mog text revenue');
    if (records.textRevenue.formula !== null || String(records.textRevenue.input) !== '0') throw new Error(`Mog text revenue was not preserved as text: ${JSON.stringify(records.textRevenue)}`);
    assertClose(records.textRevenue.revenue, 0, 'Mog text revenue link');

    await inputs.setCell('C35', '=B35/B18*(1+B20)');
    await inputs.setCell('B21', DEFAULT_INPUTS.capexRate);
    await wb.calculate();
    records.recovered = { gate: await readInputGate(wb), stub: await snapshot(wb, 0), firstFull: await snapshot(wb, 1), valuation: await readValuation(wb) };
    assertGateStatus(records.recovered.gate, 'PASS', 'Mog recovered inputs');
    assertSnapshot(records.recovered.stub, EXPECTED_STUB, 'Mog recovered stub anchor');
    assertSnapshot(records.recovered.firstFull, EXPECTED_FIRST_FULL, 'Mog recovered first-full anchor');
    assertClose(records.recovered.valuation.perShareValue, base.valuation.perShareValue, 'Mog recovered per-share value');
    return records;
  } finally {
    wb.dispose();
  }
}

async function inspectBroken(path) {
  const { createWorkbook } = await import('@mog-sdk/sdk');
  const wb = await createWorkbook(path, { userTimezone: 'UTC' });
  try {
    const schedule = await wb.getSheet('Schedules');
    const value = await schedule.getValue('B38');
    const cell = await schedule.getCell('B38');
    if (!['#REF!', '#NAME?'].includes(value) || cell.value?.type !== 'error') throw new Error(`Broken reference not detected: ${JSON.stringify({ value, cell })}`);
    return { value, errorType: cell.value.type, message: cell.value.message };
  } finally {
    wb.dispose();
  }
}

function gitFingerprint() {
  const statusResult = spawnSync('git', ['status', '--porcelain', '--untracked-files=all'], { cwd: ROOT, encoding: 'utf8', windowsHide: true });
  const headResult = spawnSync('git', ['rev-parse', 'HEAD'], { cwd: ROOT, encoding: 'utf8', windowsHide: true });
  const status = statusResult.stdout ?? '';
  return {
    head: (headResult.stdout ?? '').trim() || null,
    dirty: status.length > 0,
    changedPathCount: status ? status.trimEnd().split(/\r?\n/).length : 0,
    statusSha256: createHash('sha256').update(status).digest('hex'),
  };
}

async function codeFingerprints() {
  const files = ['fictional_model.mjs', 'fictional_fixture.mjs', 'verify-fictional-excel.ps1'];
  const result = {};
  for (const name of files) result[name] = await sha256(resolve(SCRIPT_DIR, name));
  return result;
}

async function expectThrows(action, fragment, label) {
  try {
    await action();
  } catch (error) {
    if (!String(error.message).includes(fragment)) throw new Error(`${label}: wrong error: ${error.message}`);
    return { label, status: 'PASS', message: error.message };
  }
  throw new Error(`${label}: expected failure`);
}

async function runExcelVerifier(expectationsPath) {
  const verifier = resolve(SCRIPT_DIR, 'verify-fictional-excel.ps1');
  const result = spawnSync('powershell.exe', [
    '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', verifier,
    '-WorkbookPath', BASE, '-EditedPath', EDITED, '-BrokenPath', BROKEN,
    '-ResultsPath', EXCEL_RESULTS, '-ExpectationsPath', expectationsPath,
  ], { cwd: SCRIPT_DIR, encoding: 'utf8', timeout: 120000, windowsHide: true });
  const output = `${result.stdout ?? ''}${result.stderr ?? ''}`;
  await writeFile(EXCEL_LOG, output, 'utf8');
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`Excel verifier failed (${result.status}): ${output}`);
  return JSON.parse((await readFile(EXCEL_RESULTS, 'utf8')).replace(/^\uFEFF/, ''));
}

async function interruptedCandidate(runDir) {
  const candidate = resolve(runDir, '.candidate-interrupted.xlsx');
  await saveWorkbook(candidate, { stubRevenue: 99 });
  process.kill(process.pid, 'SIGTERM');
}

async function verifyR1() {
  await mkdir(EVIDENCE, { recursive: true });
  const runFingerprint = gitFingerprint();
  await writeFile(INPUT_MANIFEST, JSON.stringify({
    fixtureId: MODEL_VERSION,
    verification: 'P4-R1 live editable-input gate',
    fictional: true,
    purpose: 'Prove missing or text editable inputs cannot pass model checks or valuation status; no MSFT policy decision',
    informationCutoff: '2026-04-30',
    measurementDate: '2026-03-31',
    valuationDate: '2026-03-31',
    currency: 'USD',
    displayUnits: 'USD millions; shares millions; per-share USD',
    engine: { package: '@mog-sdk/sdk', version: ENGINE_VERSION },
    modelVersion: MODEL_VERSION,
    periods: PERIODS,
    inputs: DEFAULT_INPUTS,
    requiredInputAddresses: REQUIRED_INPUT_ADDRESSES,
    requiredInputCount: REQUIRED_INPUT_COUNT,
    tolerance: TOLERANCE,
    source: 'fictional fixture policy and supplied arithmetic anchors in fictional/STEPS.md; appended P4-R1 acceptance',
    expectedAnchors: { stub: EXPECTED_STUB, firstFull: EXPECTED_FIRST_FULL },
    codeFingerprint: await codeFingerprints(),
    git: runFingerprint,
    outputRunId: RUN_ID,
  }, null, 2), 'utf8');

  await saveWorkbook(BASE);
  await saveWorkbook(BROKEN, {}, true);
  const mog = await inspectMogR1(BASE);
  const liveInputs = await inspectMogLiveInputs(BASE, mog);
  const brokenReference = await inspectBroken(BROKEN);
  await writeFile(EXPECTATIONS, JSON.stringify({
    requiredInputCount: REQUIRED_INPUT_COUNT,
    base: { stub: mog.stub, firstFull: mog.firstFull, valuation: mog.valuation },
  }, null, 2), 'utf8');

  const excel = await runExcelVerifier(EXPECTATIONS);
  const baseHash = await sha256(BASE);
  if (excel.publishedSha256Before !== baseHash) throw new Error(`Excel verifier hash mismatch: ${excel.publishedSha256Before} vs ${baseHash}`);
  const report = {
    fixtureId: MODEL_VERSION,
    verification: 'P4-R1 live editable-input gate',
    engineVersion: ENGINE_VERSION,
    tolerance: TOLERANCE,
    verificationMode: 'fresh-Mog-rebuild-plus-native-invisible-Excel-clear-and-recover',
    runId: RUN_ID,
    outputs: { baseWorkbook: BASE, recoveredWorkbook: EDITED, brokenWorkbook: BROKEN, inputManifest: INPUT_MANIFEST, excelExpectations: EXPECTATIONS, excelVerification: EXCEL_RESULTS },
    requiredInputGate: { count: REQUIRED_INPUT_COUNT, addresses: REQUIRED_INPUT_ADDRESSES, formula: mog.gate.formula },
    anchors: { stub: mog.stub, firstFull: mog.firstFull },
    valuation: mog.valuation,
    mog: { baseGate: mog.gate, liveInputs },
    brokenReference,
    excel,
    codeFingerprint: await codeFingerprints(),
    git: runFingerprint,
  };
  await writeFile(VERIFICATION, JSON.stringify(report, null, 2), 'utf8');
  console.log(JSON.stringify(report, null, 2));
}

async function verifyLegacyP4() {
  await mkdir(EVIDENCE, { recursive: true });
  const runFingerprint = gitFingerprint();
  await writeFile(INPUT_MANIFEST, JSON.stringify({
    fixtureId: MODEL_VERSION,
    fictional: true,
    purpose: 'P4 linked three-statement and DCF mechanics proof; no MSFT policy decision',
    informationCutoff: '2026-04-30',
    measurementDate: '2026-03-31',
    valuationDate: '2026-03-31',
    currency: 'USD',
    displayUnits: 'USD millions; shares millions; per-share USD',
    engine: { package: '@mog-sdk/sdk', version: ENGINE_VERSION },
    modelVersion: MODEL_VERSION,
    periods: PERIODS,
    inputs: DEFAULT_INPUTS,
    policies: {
      interest: 'opening debt x interest rate x period fraction; no new debt',
      taxes: '25% of positive pretax income for book/cash tax; same-period payment; no loss benefit or deferred tax; UFCF taxes only positive EBIT',
      dividends: '25% of positive net income; no dividend on losses',
      ppAndE: 'opening net PP&E depreciation at 20% annually, pro-rated by period fraction; capex = 10% of revenue',
      workingCapital: 'AR = 10% of annualized revenue; inventory = 1/12 annualized cash costs; AP = 2/15 annualized cash costs',
      dcf: 'period-end discounting and simple perpetual UFCF growth; terminal g < WACC',
    },
    expectedAnchors: { stub: EXPECTED_STUB, firstFull: EXPECTED_FIRST_FULL },
    source: 'fictional fixture policy and supplied arithmetic anchors in fictional/STEPS.md',
    codeFingerprint: await codeFingerprints(),
    git: runFingerprint,
    outputRunId: RUN_ID,
  }, null, 2), 'utf8');

  await saveWorkbook(BASE);
  await saveWorkbook(BROKEN, {}, true);
  const mog = await inspectMog(BASE);
  const brokenReference = await inspectBroken(BROKEN);
  const editedInputs = { stubRevenue: 30 };
  const editedHandle = await buildFictionalWorkbook({ inputOverrides: editedInputs });
  let editedEngine;
  try {
    editedEngine = { stub: await snapshot(editedHandle.wb, 0), firstFull: await snapshot(editedHandle.wb, 1), valuation: await readValuation(editedHandle.wb) };
  } finally {
    editedHandle.wb.dispose();
  }
  await writeFile(EXPECTATIONS, JSON.stringify({ base: mog, edited: editedEngine }, null, 2), 'utf8');

  const propagation = {};
  const basePerShare = Number(mog.valuation.perShareValue);
  const sensitivityCases = {
    revenue: { stubRevenue: 30 },
    costRate: { cashCostRate: 0.7 },
    capexRate: { capexRate: 0.2 },
    wacc: { wacc: 0.12 },
    terminalGrowth: { terminalGrowth: 0.03 },
    openingDebt: { openingDebt: 40, openingEquity: 37 },
  };
  for (const [name, overrides] of Object.entries(sensitivityCases)) {
    const handle = await buildFictionalWorkbook({ inputOverrides: overrides });
    try {
      const first = await snapshot(handle.wb, 1);
      const value = Number(first.perShareValue);
      if (Math.abs(value - basePerShare) <= TOLERANCE) throw new Error(`sensitivity did not propagate: ${name}`);
      const checks = await readPeriodValues(handle.wb, 'Checks', 20);
      if (checks.some((item) => item !== 'PASS')) throw new Error(`sensitivity broke checks: ${name}`);
      propagation[name] = { status: 'PASS', firstFullPerShare: value };
    } finally {
      handle.wb.dispose();
    }
  }

  const adverse = await buildFictionalWorkbook({ inputOverrides: { stubRevenue: 0 } });
  let adverseValues;
  try {
    const negativeIncome = await readPeriodValues(adverse.wb, 'Income', MODEL_ROWS.income.netIncome);
    const dividends = await readPeriodValues(adverse.wb, 'Schedules', MODEL_ROWS.schedules.dividends);
    const taxes = await readPeriodValues(adverse.wb, 'Schedules', MODEL_ROWS.schedules.cashTaxes);
    const funding = await readPeriodValues(adverse.wb, 'Schedules', MODEL_ROWS.schedules.fundingStatus);
    if (!negativeIncome.some((value) => Number(value) < 0)) throw new Error('negative-earnings stress did not reach a loss');
    if (dividends.some((value) => Number(value) < 0 || Number(value) !== 0)) throw new Error(`loss stress manufactured dividends: ${JSON.stringify(dividends)}`);
    if (taxes.some((value) => Number(value) < 0 || Number(value) !== 0)) throw new Error(`loss stress manufactured tax refund: ${JSON.stringify(taxes)}`);
    if (!funding.includes('FUNDING_DEFICIT')) throw new Error('loss stress did not expose a later funding deficit');
    adverseValues = { negativeIncome, dividends, taxes, funding }; 
  } finally {
    adverse.wb.dispose();
  }

  const invalidCases = [];
  invalidCases.push(await expectThrows(() => validateFixtureInputs({ ...DEFAULT_INPUTS, openingDebt: undefined }), 'openingDebt', 'missing required input'));
  invalidCases.push(await expectThrows(() => validatePeriods(PERIODS.slice(0, 10)), '11 forecast periods', 'invalid period count'));
  invalidCases.push(await expectThrows(() => validateFixtureInputs({ ...DEFAULT_INPUTS, terminalGrowth: DEFAULT_INPUTS.wacc }), 'terminalGrowth', 'terminal growth >= WACC'));
  const beforeFailedHash = await sha256(BASE);
  const failedBuild = await expectThrows(() => buildFictionalWorkbook({ inputOverrides: { terminalGrowth: DEFAULT_INPUTS.wacc } }), 'terminalGrowth', 'failed candidate build');
  const afterFailedHash = await sha256(BASE);
  if (beforeFailedHash !== afterFailedHash) throw new Error('failed candidate changed valid workbook');
  const beforeInterruptHash = await sha256(BASE);
  const interrupted = spawnSync(process.execPath, [fileURLToPath(import.meta.url), 'interrupt', RUN_DIR], {
    cwd: SCRIPT_DIR, encoding: 'utf8', timeout: 30000, windowsHide: true,
  });
  await writeFile(INTERRUPT_LOG, `${interrupted.stdout ?? ''}${interrupted.stderr ?? ''}`, 'utf8');
  const afterInterruptHash = await sha256(BASE);
  if (beforeInterruptHash !== afterInterruptHash) throw new Error('interrupted candidate changed valid workbook');
  const interruption = { status: 'PASS', publishedSha256Before: beforeInterruptHash, publishedSha256After: afterInterruptHash, unchanged: true, childStatus: interrupted.status, childSignal: interrupted.signal };

  const excel = await runExcelVerifier(EXPECTATIONS);
  const baseHash = await sha256(BASE);
  if (excel.publishedSha256Before !== baseHash) throw new Error(`Excel verifier hash mismatch: ${excel.publishedSha256Before} vs ${baseHash}`);
  const report = {
    fixtureId: MODEL_VERSION,
    engineVersion: ENGINE_VERSION,
    tolerance: TOLERANCE,
    verificationMode: 'fresh-Mog-rebuild-plus-native-invisible-Excel-recalculation',
    runId: RUN_ID,
    outputs: { baseWorkbook: BASE, editedWorkbook: EDITED, brokenWorkbook: BROKEN, inputManifest: INPUT_MANIFEST, excelExpectations: EXPECTATIONS, excelVerification: EXCEL_RESULTS },
    anchors: { stub: mog.stub, firstFull: mog.firstFull },
    valuation: mog.valuation,
    mog: { formulas: mog.formulas, checks: mog.checks, literalReadback: mog.literalReadback, hyperlinkFormula: mog.hyperlinkFormula },
    brokenReference,
    propagation,
    adverse: adverseValues,
    invalidCases,
    failedBuild,
    interruption,
    excel,
    codeFingerprint: await codeFingerprints(),
    git: runFingerprint,
  };
  await writeFile(VERIFICATION, JSON.stringify(report, null, 2), 'utf8');
  console.log(JSON.stringify(report, null, 2));
}

async function build() {
  await mkdir(RUN_DIR, { recursive: true });
  await saveWorkbook(BASE);
  console.log(JSON.stringify({ status: 'PASS', modelVersion: MODEL_VERSION, workbook: BASE }));
}

const command = process.argv[2] ?? 'verify';
if (command === 'verify') await verifyR1();
else if (command === 'verify-legacy-p4') await verifyLegacyP4();
else if (command === 'build') await build();
else if (command === 'interrupt') await interruptedCandidate(process.argv[3] ?? RUN_DIR);
else throw new Error(`Unknown command: ${command}`);
