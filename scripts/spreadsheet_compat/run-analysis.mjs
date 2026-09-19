import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { buildAssetWorkbook, inspectAssetWorkbook, readSnapshot } from './asset_model.mjs';

const EXPECTED_MODEL_SHA256 = '24ecc22c7a213f1959dfd50bd77fc34803af8883e658806cf64e64e1ec13d630';
const [, , command, modelArg, verificationArg, outputArg, workbookArg] = process.argv;
const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const modelPath = resolve(modelArg ?? resolve(repoRoot, 'data/build-guide-p9/parent-repair/model/selected-model.json'));
const verificationPath = resolve(verificationArg ?? resolve(repoRoot, 'data/build-guide-p9/parent-repair/model/p9-verification.json'));
const outputPath = resolve(outputArg ?? resolve(repoRoot, 'data/build-guide-p10/offline-r1/calculated-context.json'));
const workbookPath = resolve(workbookArg ?? resolve(repoRoot, 'data/build-guide-p10/offline-r1/p10-calculated.xlsx'));
const sha256 = async (path) => createHash('sha256').update(await readFile(path)).digest('hex');
const columnName = (number) => {
  let value = number;
  let result = '';
  while (value > 0) {
    value -= 1;
    result = String.fromCharCode(65 + (value % 26)) + result;
    value = Math.floor(value / 26);
  }
  return result;
};

async function sensitivitySnapshot(wb) {
  const sheet = await wb.getSheet('P9Sensitivity');
  const readRows = async (start, end, width) => {
    const rows = [];
    for (let row = start; row <= end; row += 1) {
      const values = [];
      const formulas = [];
      for (let column = 1; column <= width; column += 1) {
        const address = `${columnName(column)}${row}`;
        values.push(await sheet.getValue(address));
        formulas.push(await sheet.getFormula(address));
      }
      rows.push({ row, values, formulas });
    }
    return rows;
  };
  return {
    terminal: await readRows(4, 8, 15),
    wacc: await readRows(11, 17, 9),
    liveOperatingDriver: await readRows(20, 20, 7),
    sourceEstimate: await readRows(22, 27, 5),
  };
}

function assertFinancialSnapshot(actual, expected, label) {
  const statements = structuredClone(actual.statements);
  const baseline = structuredClone(expected.statements);
  // The P10 reviewer corrected this presentation label; every value stays bound.
  for (const version of [statements, baseline]) {
    for (const row of version.cashFlow) {
      if (row.row === 7 && row.label === 'Noncash and operating-lease CFO adjustments') row.label = 'Depreciation add-back';
    }
  }
  assert.deepEqual(statements, baseline, `${label}: all 550 statement values differ`);
  assert.deepEqual(actual.checks, expected.checks, `${label}: statement checks differ`);
  assert.equal(actual.allPeriodStatus, expected.allPeriodStatus, `${label}: all-period status differs`);
  assert.deepEqual(actual.p9, expected.p9, `${label}: P9 DCF/terminal/claim values differ`);
}

async function snapshot() {
  assert.equal(await sha256(modelPath), EXPECTED_MODEL_SHA256, 'P10 selected P9 model is stale or unauthorized');
  const model = JSON.parse(await readFile(modelPath, 'utf8'));
  const accepted = JSON.parse(await readFile(verificationPath, 'utf8'));
  assert.equal(accepted.status, 'PASS', 'Accepted P9 calculated evidence did not pass');
  assert.equal(accepted.snapshot?.p9?.valuationGate, 'PASS', 'Accepted P9 valuation gate did not pass');
  assert.equal(accepted.snapshot?.p9?.status, 'PROVISIONAL_REVIEW_REQUIRED', 'P10 requires the accepted provisional P9 review state');

  const handle = await buildAssetWorkbook(model);
  let calculated;
  let sensitivities;
  try {
    calculated = await readSnapshot(handle.wb);
    sensitivities = await sensitivitySnapshot(handle.wb);
    assertFinancialSnapshot(calculated, accepted.snapshot, 'Fresh P10 calculation');
    await mkdir(dirname(workbookPath), { recursive: true });
    await handle.wb.save(workbookPath);
    await new Promise((done) => setTimeout(done, 150));
  } finally {
    handle.wb.dispose();
  }
  const inspected = await inspectAssetWorkbook(workbookPath);
  assertFinancialSnapshot(inspected, calculated, 'Saved P10 workbook');

  const implementationPaths = [
    resolve(repoRoot, 'scripts/spreadsheet_compat/asset_model.mjs'),
    resolve(repoRoot, 'scripts/spreadsheet_compat/valuation.mjs'),
    fileURLToPath(import.meta.url),
  ];
  const implementation = [];
  for (const path of implementationPaths) implementation.push({ path, sha256: await sha256(path) });
  const result = {
    status: 'PASS',
    formulaAuthority: 'Mog formulas; P10 reads calculated outputs and does not implement a second financial calculation engine',
    modelPath,
    modelSha256: await sha256(modelPath),
    acceptedVerificationPath: verificationPath,
    acceptedVerificationSha256: await sha256(verificationPath),
    workbookPath,
    workbookSha256: await sha256(workbookPath),
    fullSnapshotMatchesAcceptedP9: true,
    savedSnapshotMatchesFreshCalculation: true,
    implementation,
    snapshot: inspected,
    sensitivities,
  };
  await mkdir(dirname(outputPath), { recursive: true });
  await writeFile(outputPath, `${JSON.stringify(result, null, 2)}\n`, 'utf8');
  process.stdout.write(`${JSON.stringify({ status: result.status, outputPath, workbookPath, modelSha256: result.modelSha256 })}\n`);
}

async function correction() {
  const model = JSON.parse(await readFile(modelPath, 'utf8'));
  const authorization = model._p10_correction;
  assert.equal(authorization?.base_model_sha256, EXPECTED_MODEL_SHA256, 'Correction is not bound to the accepted P9 model');
  assert.match(authorization?.selection_id ?? '', /^(ppe_capex|taxes|nonoperating|dcf_terminal):[a-z0-9_]+$/, 'Invalid closed correction selection ID');
  const accepted = JSON.parse(await readFile(verificationPath, 'utf8'));
  assert.equal(accepted.status, 'PASS', 'Accepted P9 calculated evidence did not pass');

  const handle = await buildAssetWorkbook(model);
  let calculated;
  let sensitivities;
  try {
    calculated = await readSnapshot(handle.wb);
    sensitivities = await sensitivitySnapshot(handle.wb);
    assert.equal(calculated.allPeriodStatus, 'PASS', 'Corrected model all-period checks failed');
    assert.ok(calculated.checks.every((value) => value === 'PASS'), 'Corrected model statement checks failed');
    assert.equal(calculated.p9.inputGate, 'PASS', 'Corrected model valuation input gate failed');
    assert.equal(calculated.p9.terminalGate, 'PASS', 'Corrected model terminal gate failed');
    assert.equal(calculated.p9.claimCheck, 'PASS', 'Corrected model claim check failed');
    assert.equal(calculated.p9.valuationGate, 'PASS', 'Corrected model valuation gate failed');
    await mkdir(dirname(workbookPath), { recursive: true });
    await handle.wb.save(workbookPath);
    await new Promise((done) => setTimeout(done, 150));
  } finally {
    handle.wb.dispose();
  }
  const inspected = await inspectAssetWorkbook(workbookPath);
  assert.deepEqual(inspected.statements, calculated.statements, 'Saved correction statement values differ');
  assert.deepEqual(inspected.p9, calculated.p9, 'Saved correction valuation values differ');
  const result = {
    status: 'PASS',
    formulaAuthority: 'Mog formulas; bounded correction recalculated before independent recheck',
    baseModelSha256: EXPECTED_MODEL_SHA256,
    correctionModelSha256: await sha256(modelPath),
    selectionId: authorization.selection_id,
    workbookPath,
    workbookSha256: await sha256(workbookPath),
    snapshot: inspected,
    sensitivities,
  };
  await mkdir(dirname(outputPath), { recursive: true });
  await writeFile(outputPath, `${JSON.stringify(result, null, 2)}\n`, 'utf8');
  process.stdout.write(`${JSON.stringify({ status: result.status, outputPath, workbookPath, selectionId: result.selectionId })}\n`);
}

if (command === 'snapshot') await snapshot();
else if (command === 'correction') await correction();
else throw new Error(`Unsupported P10 adapter command: ${command}`);
