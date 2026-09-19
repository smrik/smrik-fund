import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createWorkbook } from '@mog-sdk/sdk';
import {
  buildAssetWorkbook,
  readSnapshot,
  P6_DRIVER_ROWS,
  PERIODS,
  periodColumn,
  TOLERANCE,
} from './asset_model.mjs';

const [, , command = 'build', inputArg, runArg] = process.argv;
const inputPath = resolve(inputArg ?? fileURLToPath(new URL('../../data/build-guide-p6/model-input.json', import.meta.url)));
const runDir = resolve(runArg ?? fileURLToPath(new URL('../../data/build-guide-p6/mog-run', import.meta.url)));
const workbookPath = resolve(runDir, 'operating-model.xlsx');

const sha256 = async (path) => createHash('sha256').update(await readFile(path)).digest('hex');
const near = (actual, expected, label) => assert.ok(typeof actual === 'number' && Math.abs(actual - expected) <= TOLERANCE, `${label}: expected ${expected}, got ${actual}`);
const changed = (before, after, index, label) => assert.ok(Math.abs(Number(after[index]) - Number(before[index])) > TOLERANCE, `${label} did not change at ${periodColumn(index)}`);
const releaseWorkbook = () => new Promise((resolvePromise) => setTimeout(resolvePromise, 1000));

function modelDecisionStatus(model) {
  const p6 = model.p6_decision ?? model.operating_decision ?? model.operating_forecast?.decision;
  return p6?.status ?? 'UNREVIEWED_PROVISIONAL';
}

function verifySnapshot(snapshot, expectedStatus = null) {
  assert.ok(snapshot.checks.every((value) => value === 'PASS'), `P5 checks failed: ${JSON.stringify(snapshot.checks)}`);
  assert.ok(Math.abs(Number(snapshot.stub.balanceDifference)) <= TOLERANCE, `P5 stub balance failed: ${snapshot.stub.balanceDifference}`);
  assert.equal(snapshot.allPeriodStatus, 'PASS', 'P5 global mechanical/input gate failed');
  assert.ok(Math.abs(Number(snapshot.stub.recognizedPpeAdditions) - Number(snapshot.stub.cashPpePayments) - Number(snapshot.stub.noncashPpeAdditions)) <= TOLERANCE, 'P5 recognized additions do not tie cash plus noncash');
  assert.ok(Math.abs(Number(snapshot.stub.cashFcf) - Number(snapshot.stub.economicUfcf) - Number(snapshot.stub.noncashPpeAdditions)) <= TOLERANCE, 'P5 cash/noncash UFCF bridge failed');
  assert.ok(Math.abs(Number(snapshot.enterpriseValue) - Number(snapshot.sensitivityCenter)) <= TOLERANCE, 'P5 sensitivity center does not tie base EV');
  if (expectedStatus !== null) {
    assert.equal(snapshot.combinedDecisionStatus, expectedStatus, `combined status expected ${expectedStatus}`);
    assert.equal(snapshot.dcfStatus, expectedStatus, `DCF status expected ${expectedStatus}`);
  }
  if (snapshot.operatingBridge) {
    assert.equal(snapshot.p6DriverStatus, 'PASS', `P6 driver input gate failed: ${snapshot.p6DriverStatus}`);
    for (const [segment, formulas] of Object.entries(snapshot.operatingBridge.formulas.segments)) {
      assert.ok(formulas[0] && formulas[1], `P6 segment formula missing for ${segment}`);
    }
    for (const [line, formula] of Object.entries(snapshot.operatingBridge.formulas.costs)) {
      assert.ok(formula, `P6 cost formula missing for ${line}`);
    }
    for (let index = 0; index < PERIODS.length; index += 1) {
      const gross = Number(snapshot.operatingBridge.grossCosts[index]);
      const embedded = Number(snapshot.operatingBridge.embeddedPpeRemoved[index]);
      const scheduled = Number(snapshot.operatingBridge.scheduledPpeAdded[index]);
      const total = Number(snapshot.operatingBridge.totalOperatingExpenses[index]);
      const excluding = Number(snapshot.operatingBridge.costsExcludingEmbeddedPpe[index]);
      assert.ok(Math.abs(gross - embedded + scheduled - total) <= TOLERANCE, `P6 operating bridge failed in period ${index}`);
      assert.ok(Math.abs(gross - embedded - excluding) <= TOLERANCE, `P6 embedded-cost removal failed in period ${index}`);
    }
  }
  return snapshot;
}

async function inspectSavedWorkbook(path, expectedStatus = null) {
  const wb = await createWorkbook(path, { userTimezone: 'UTC' });
  try {
    const snapshot = await readSnapshot(wb);
    return verifySnapshot(snapshot, expectedStatus);
  } finally { wb.dispose(); }
}

async function saveWorkbook(path, model) {
  const handle = await buildAssetWorkbook(model);
  try { await handle.wb.save(path); } finally { handle.wb.dispose(); await releaseWorkbook(); }
}

async function series(sheet, row) {
  return Promise.all(PERIODS.map((_, index) => sheet.getValue(`${periodColumn(index)}${row}`)));
}

async function readOperating(wb) {
  const operating = await wb.getSheet('Operating');
  const income = await wb.getSheet('Income');
  const schedules = await wb.getSheet('Schedules');
  const cashFlow = await wb.getSheet('CashFlow');
  const balanceSheet = await wb.getSheet('BalanceSheet');
  const dcf = await wb.getSheet('DCF');
  const revenue = await series(operating, 11);
  const incomeRevenue = await series(income, 6);
  const segmentTotal = await series(operating, 10);
  const corp = await series(operating, 9);
  const segmentRevenue = Object.fromEntries(await Promise.all([
    ['Intelligent Cloud', 6],
    ['More Personal Computing', 7],
    ['Productivity and Business Processes', 8],
  ].map(async ([name, row]) => [name, await series(operating, row)])));
  const costs = Object.fromEntries(await Promise.all([
    ['cost_of_revenue', 13],
    ['research_and_development', 14],
    ['sales_and_marketing', 15],
    ['general_and_administrative', 16],
  ].map(async ([name, row]) => [name, await series(operating, row)])));
  const grossCosts = await series(operating, 17);
  const embeddedRemoved = await series(operating, 18);
  const scheduledAdded = await series(operating, 19);
  const totalExpenses = await series(operating, 20);
  const exEmbedded = await series(operating, 21);
  const grossRatio = await series(operating, 22);
  const margin = await series(operating, 23);
  const downstream = {
    capex: await series(schedules, 12),
    depreciation: await series(schedules, 17),
    ebit: await series(income, 11),
    netIncome: await series(income, 15),
    cfo: await series(cashFlow, 9),
    closingCash: await series(cashFlow, 15),
    closingPpe: await series(balanceSheet, 11),
    dcfUfcf: await series(dcf, 7),
  };
  const formulas = {
    segments: Object.fromEntries(await Promise.all([
      ['Intelligent Cloud', 6],
      ['More Personal Computing', 7],
      ['Productivity and Business Processes', 8],
    ].map(async ([name, row]) => [name, [await operating.getFormula(`B${row}`), await operating.getFormula(`C${row}`)]]))),
    costs: Object.fromEntries(await Promise.all([
      ['cost_of_revenue', 13],
      ['research_and_development', 14],
      ['sales_and_marketing', 15],
      ['general_and_administrative', 16],
    ].map(async ([name, row]) => [name, await operating.getFormula(`B${row}`)]))),
    revenue: await operating.getFormula('B11'),
    totalExpenses: await operating.getFormula('B20'),
    schedulesPpe: await schedules.getFormula('B23'),
    incomeEbit: await income.getFormula('B11'),
    dcf: await dcf.getFormula('B7'),
  };
  for (let i = 0; i < PERIODS.length; i += 1) {
    const c = periodColumn(i);
    near(revenue[i], incomeRevenue[i], `${c} revenue linked to Income`);
    near(segmentTotal[i] + corp[i], revenue[i], `${c} segment plus corporate revenue`);
    near(grossCosts[i] - embeddedRemoved[i] + scheduledAdded[i], totalExpenses[i], `${c} gross minus embedded plus scheduled expense bridge`);
    near(grossCosts[i] - embeddedRemoved[i], exEmbedded[i], `${c} embedded PP&E depreciation removal`);
    near(revenue[i] - totalExpenses[i], downstream.ebit[i], `${c} EBIT tied to substituted expense`);
    near(scheduledAdded[i], downstream.depreciation[i], `${c} scheduled PP&E depreciation linked`);
    assert.ok(Number.isFinite(Number(grossRatio[i])), `${c} gross cost ratio is numeric`);
    assert.ok(Number.isFinite(Number(margin[i])), `${c} operating margin is numeric`);
    assert.ok(Number.isFinite(Number(downstream.dcfUfcf[i])), `${c} DCF output is numeric`);
  }
  for (const [name, pair] of Object.entries(formulas.segments)) assert.ok(pair[0] && pair[1], `${name} forecast formula missing`);
  for (const [name, formula] of Object.entries(formulas.costs)) assert.ok(formula, `${name} cost formula missing`);
  return { revenue, segmentTotal, corp, segmentRevenue, costs, grossCosts, embeddedRemoved, scheduledAdded, totalExpenses, exEmbedded, grossRatio, margin, downstream, formulas };
}

async function readStatus(wb) {
  const review = await wb.getSheet('Review');
  const decisions = await wb.getSheet('Decisions');
  const checks = await wb.getSheet('Checks');
  const inputs = await wb.getSheet('Inputs');
  const dcf = await wb.getSheet('DCF');
  return {
    headline: await review.getValue('B3'), decision: await decisions.getValue('B28'), p5: await decisions.getValue('B4'),
    saved: await checks.getValue('B23'), gate: await checks.getValue('B22'), input: await inputs.getValue('B54'), driver: await inputs.getValue('B78'),
    dcf: await dcf.getValue('B24'), dcfValue: await dcf.getValue('B18'),
  };
}

async function statusVariant(model, mutation, expected, label) {
  const variant = structuredClone(model);
  mutation(variant);
  const handle = await buildAssetWorkbook(variant);
  try {
    await handle.wb.calculate();
    const status = await readStatus(handle.wb);
    assert.equal(status.decision, expected, `${label} combined status`);
    assert.equal(status.p5, 'SYSTEM_REVIEWED_PROVISIONAL', `${label} preserves P5 detail`);
    return status;
  } finally { handle.wb.dispose(); await releaseWorkbook(); }
}

async function preview() {
  const model = JSON.parse(await readFile(inputPath, 'utf8'));
  assert.ok(model.operating_forecast, 'P6 operating forecast missing');
  const expectedStatus = modelDecisionStatus(model);
  assert.equal(expectedStatus, 'REVIEW_REQUIRED', 'P6 pre-review preview must be explicitly review-required');
  await mkdir(runDir, { recursive: true });
  const previewPath = resolve(runDir, 'operating-preview.xlsx');
  await saveWorkbook(previewPath, model);
  const snapshot = await inspectSavedWorkbook(previewPath, expectedStatus);
  const handle = await buildAssetWorkbook(model);
  let operating;
  let status;
  try {
    operating = await readOperating(handle.wb);
    status = await readStatus(handle.wb);
  } finally { handle.wb.dispose(); await releaseWorkbook(); }
  assert.equal(status.headline, expectedStatus, 'pre-review headline state');
  assert.equal(status.decision, expectedStatus, 'pre-review combined decision state');
  assert.equal(status.dcf, expectedStatus, 'pre-review DCF state');
  const verification = {
    status: 'PASS',
    mode: 'pre-review-Mog-calculation',
    expectedStatus,
    inputPath,
    workbookPath: previewPath,
    snapshot,
    operating,
    checks: snapshot.checks,
    formulaAuthority: 'Mog/Excel formulas; Python fields marked diagnostic only',
  };
  await writeFile(resolve(runDir, 'operating-verification.json'), `${JSON.stringify(verification, null, 2)}\n`, 'utf8');
  await writeFile(resolve(runDir, 'asset-verification.json'), `${JSON.stringify(verification, null, 2)}\n`, 'utf8');
  console.log(JSON.stringify({ status: 'PASS', mode: verification.mode, expectedStatus, workbookPath: previewPath, verificationPath: resolve(runDir, 'operating-verification.json'), checks: snapshot.checks, stubRevenue: snapshot.stub.revenue, terminalRevenue: snapshot.operatingForecast.consolidatedRevenue.at(-1), grossCosts: snapshot.operatingBridge.grossCosts[0], scheduledPpeAdded: snapshot.operatingBridge.scheduledPpeAdded[0], totalOperatingExpenses: snapshot.operatingBridge.totalOperatingExpenses[0] }, null, 2));
}

async function build() {
  const model = JSON.parse(await readFile(inputPath, 'utf8'));
  assert.ok(model.operating_forecast, 'P6 operating forecast missing');
  const expectedStatus = modelDecisionStatus(model);
  await mkdir(runDir, { recursive: true });
  const candidatePath = resolve(runDir, 'operating-candidate.xlsx');
  const rebuiltPath = resolve(runDir, 'operating-rebuild.xlsx');
  await saveWorkbook(candidatePath, model);
  const snapshot = await inspectSavedWorkbook(candidatePath, expectedStatus);
  const handle = await buildAssetWorkbook(model);
  const proof = { status: 'PASS', driverRows: P6_DRIVER_ROWS, baseStatus: null, growthEdit: null, costRatioEdit: null, negativeGrowth: null, lifeSensitivity: null, missingRecovery: null, literalNarrative: null, statusAdverse: null };
  let operating;
  try {
    operating = await readOperating(handle.wb);
    const baseStatus = await readStatus(handle.wb);
    proof.baseStatus = baseStatus;
    assert.equal(baseStatus.headline, expectedStatus, 'base headline state');
    assert.equal(baseStatus.dcf, expectedStatus, 'base DCF state');
    assert.equal(baseStatus.decision, expectedStatus, 'base combined decision state');
    assert.equal(baseStatus.p5, 'SYSTEM_REVIEWED_PROVISIONAL', 'P5 detail remains system reviewed');

    const inputs = await handle.wb.getSheet('Inputs');
    const growthAddress = `B${P6_DRIVER_ROWS.segmentGrowth['Intelligent Cloud']}`;
    const baseGrowth = await inputs.getValue(growthAddress);
    await inputs.setCell(growthAddress, baseGrowth + 0.01);
    await handle.wb.calculate();
    const changedGrowth = await readOperating(handle.wb);
    for (const index of [0, 1]) changed(operating.segmentRevenue['Intelligent Cloud'], changedGrowth.segmentRevenue['Intelligent Cloud'], index, 'segment growth revenue');
    for (const name of Object.keys(operating.costs)) for (const index of [0, 1]) changed(operating.costs[name], changedGrowth.costs[name], index, `${name} cost`);
    for (const [name, values] of Object.entries(operating.downstream)) for (const index of [0, 1]) changed(values, changedGrowth.downstream[name], index, `${name} downstream`);
    const growthStatus = await readStatus(handle.wb);
    assert.equal(growthStatus.saved, 'EDITED', 'growth edit saved-input state');
    assert.equal(growthStatus.headline, 'EDITED_UNREVIEWED', 'growth edit headline state');
    assert.equal(growthStatus.dcf, 'EDITED_UNREVIEWED', 'growth edit DCF state');
    proof.growthEdit = { address: growthAddress, base: baseGrowth, changed: changedGrowth, status: growthStatus };
    await inputs.setCell(growthAddress, baseGrowth);
    await handle.wb.calculate();

    const costAddress = `B${P6_DRIVER_ROWS.costRatio.cost_of_revenue}`;
    const baseCostRatio = await inputs.getValue(costAddress);
    await inputs.setCell(costAddress, baseCostRatio + 0.01);
    await handle.wb.calculate();
    const changedCost = await readOperating(handle.wb);
    changed(operating.costs.cost_of_revenue, changedCost.costs.cost_of_revenue, 0, 'cost-ratio edit cost of revenue');
    changed(operating.downstream.ebit, changedCost.downstream.ebit, 0, 'cost-ratio edit EBIT');
    changed(operating.downstream.netIncome, changedCost.downstream.netIncome, 0, 'cost-ratio edit net income');
    const costStatus = await readStatus(handle.wb);
    assert.equal(costStatus.headline, 'EDITED_UNREVIEWED', 'cost-ratio edit headline state');
    proof.costRatioEdit = { address: costAddress, base: baseCostRatio, changed: changedCost, status: costStatus };
    await inputs.setCell(costAddress, baseCostRatio);
    await handle.wb.calculate();

    const negativeGrowth = -0.05;
    await inputs.setCell(growthAddress, negativeGrowth);
    await handle.wb.calculate();
    const negativeStatus = await readStatus(handle.wb);
    assert.equal(negativeStatus.input, 'PASS', 'negative allowed growth remains valid');
    assert.equal(negativeStatus.driver, 'PASS', 'negative driver remains valid');
    proof.negativeGrowth = { address: growthAddress, value: negativeGrowth, status: negativeStatus };
    await inputs.setCell(growthAddress, baseGrowth);
    await handle.wb.calculate();

    const schedules = await handle.wb.getSheet('Schedules');
    const income = await handle.wb.getSheet('Income');
    const cashFlow = await handle.wb.getSheet('CashFlow');
    const baseLife = await inputs.getValue('B29');
    const baseDep = await schedules.getValue('B17');
    const baseEbit = await income.getValue('B11');
    const baseNetIncome = await income.getValue('B15');
    const baseCfo = await cashFlow.getValue('B9');
    const baseClosingCash = await cashFlow.getValue('B15');
    await inputs.setCell('B29', baseLife + 1);
    await handle.wb.calculate();
    const changedLife = {
      depreciation: await schedules.getValue('B17'), ebit: await income.getValue('B11'), netIncome: await income.getValue('B15'),
      cfo: await cashFlow.getValue('B9'), closingCash: await cashFlow.getValue('B15'),
    };
    assert.notEqual(changedLife.depreciation, baseDep, 'asset-life edit changes depreciation with gross costs fixed');
    assert.notEqual(changedLife.ebit, baseEbit, 'asset-life edit changes EBIT with gross costs fixed');
    assert.notEqual(changedLife.netIncome, baseNetIncome, 'asset-life edit changes net income with gross costs fixed');
    assert.notEqual(changedLife.cfo, baseCfo, 'asset-life edit changes CFO with tax effects');
    assert.notEqual(changedLife.closingCash, baseClosingCash, 'asset-life edit changes closing cash');
    proof.lifeSensitivity = { baseLife, baseDep, baseEbit, baseNetIncome, baseCfo, baseClosingCash, changedLife };
    await inputs.setCell('B29', baseLife);
    await handle.wb.calculate();

    await inputs.setCell(growthAddress, null);
    await handle.wb.calculate();
    const missingStatus = await readStatus(handle.wb);
    assert.equal(missingStatus.input, 'FAIL', 'missing growth driver fails required inputs');
    assert.equal(missingStatus.driver, 'FAIL', 'missing growth driver fails P6 driver gate');
    assert.equal(missingStatus.gate, 'FAIL', 'missing growth driver fails all-period gate');
    assert.equal(missingStatus.dcfValue, 'BLOCKED', 'missing growth driver blocks DCF');
    await inputs.setCell(growthAddress, 0);
    await handle.wb.calculate();
    const zeroStatus = await readStatus(handle.wb);
    assert.equal(zeroStatus.input, 'PASS', 'numeric zero growth driver recovers');
    assert.equal(zeroStatus.driver, 'PASS', 'numeric zero P6 driver recovers');
    assert.equal(zeroStatus.gate, 'PASS', 'numeric zero P6 driver restores mechanical gate');
    proof.missingRecovery = { address: growthAddress, missing: missingStatus, zero: zeroStatus };
    await inputs.setCell(growthAddress, baseGrowth);
    await handle.wb.calculate();

    const operatingSheet = await handle.wb.getSheet('Operating');
    const limitation = await operatingSheet.getValue('B32');
    await operatingSheet.setCell('B32', '=SUM(1,1)', { literal: true });
    await handle.wb.calculate();
    assert.equal(await operatingSheet.getFormula('B32'), null, 'formula-like Operating narrative remains literal');
    assert.equal(await operatingSheet.getValue('B32'), '=SUM(1,1)', 'formula-like Operating narrative value is preserved');
    proof.literalNarrative = { address: 'Operating!B32', formula: await operatingSheet.getFormula('B32'), value: await operatingSheet.getValue('B32') };
    await operatingSheet.setCell('B32', limitation, { literal: true });
    await handle.wb.calculate();

    proof.statusAdverse = {
      missing: await statusVariant(model, (variant) => { variant.p6_decision = { ...variant.p6_decision, status: 'P6_REVIEW_MISSING' }; }, 'P6_REVIEW_MISSING', 'missing P6 review'),
      rejected: await statusVariant(model, (variant) => { variant.p6_decision = { ...variant.p6_decision, status: 'REJECTED_BY_REVIEW' }; }, 'REJECTED_BY_REVIEW', 'rejected P6 review'),
      stale: await statusVariant(model, (variant) => { variant.p6_decision = { ...variant.p6_decision, status: 'SYSTEM_REVIEWED_PROVISIONAL', stale: true }; }, 'UNREVIEWED_PROVISIONAL', 'stale P6 review'),
    };
  } finally { handle.wb.dispose(); await releaseWorkbook(); }

  await saveWorkbook(rebuiltPath, model);
  const rebuiltSnapshot = await inspectSavedWorkbook(rebuiltPath, expectedStatus);
  const rebuiltHash = await sha256(rebuiltPath);
  const publishedHash = await sha256(candidatePath);
  const verification = {
    status: JSON.stringify(snapshot) === JSON.stringify(rebuiltSnapshot) ? 'PASS' : 'FAIL',
    inputPath, workbookPath, expectedStatus, publishedSha256: publishedHash, rebuiltSha256: rebuiltHash,
    snapshot, rebuiltSnapshot, p5Snapshot: snapshot, rebuiltP5Snapshot: rebuiltSnapshot,
    operating, proof, checks: snapshot.checks,
    formulaAuthority: 'Mog/Excel formulas; Python fields marked diagnostic only',
  };
  assert.equal(verification.status, 'PASS', 'Mog rebuild snapshot');
  await rename(candidatePath, workbookPath);
  await writeFile(resolve(runDir, 'operating-verification.json'), `${JSON.stringify(verification, null, 2)}\n`, 'utf8');
  await writeFile(resolve(runDir, 'asset-verification.json'), `${JSON.stringify(verification, null, 2)}\n`, 'utf8');
  await writeFile(resolve(runDir, 'operating-rebuild-verification.json'), `${JSON.stringify({ status: verification.status, publishedSha256: publishedHash, rebuiltSha256: rebuiltHash, snapshot, rebuiltSnapshot }, null, 2)}\n`, 'utf8');
  console.log(JSON.stringify({ status: 'PASS', workbookPath, verificationPath: resolve(runDir, 'operating-verification.json'), checks: snapshot.checks, stubRevenue: operating.revenue[0], terminalRevenue: operating.revenue.at(-1), baseHeadline: proof.baseStatus.headline, growthEdit: proof.growthEdit.address, costRatioEdit: proof.costRatioEdit.address }, null, 2));
}

if (command === 'build') await build();
else if (command === 'preview') await preview();
else if (command === 'inspect') console.log(JSON.stringify(await inspectSavedWorkbook(workbookPath), null, 2));
else throw new Error(`Unknown P6 command: ${command}`);
process.exit(0);
