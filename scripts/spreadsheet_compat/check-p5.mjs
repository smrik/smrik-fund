import assert from 'node:assert/strict';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { buildAssetWorkbook, readSnapshot, readPeriodValues, periodColumn, PERIODS } from './asset_model.mjs';

const inputPath = resolve(process.argv[2]);
const out = resolve(process.argv[3]);
await mkdir(out, { recursive: false });
const model = JSON.parse(await readFile(inputPath, 'utf8'));
const evidence = [];
const near = (actual, expected, label) => assert.ok(typeof actual === 'number' && Math.abs(actual - expected) < 1e-8, `${label}: expected ${expected}, got ${actual}`);
const { wb } = await buildAssetWorkbook(model);
try {
  const sheet = async (name) => wb.getSheet(name);
  const read = async (name, address) => (await sheet(name)).getValue(address);
  const set = async (name, address, value) => (await sheet(name)).setCell(address, value);
  const base = await readSnapshot(wb);
  near(base.annualRevenue, base.stub.revenue / 0.25 * (1 + await read('Inputs', 'B36')), 'annualization');
  near(base.sensitivityCenter, base.enterpriseValue, 'sensitivity center');
  near(await read('DCF', 'B16'), await read('DCF', 'B15') * await read('DCF', 'L10'), 'terminal discount');
  assert.equal(base.dcfStatus, 'OFFLINE_FIXTURE');
  evidence.push({ name: 'MSFT frozen-input calculation', result: 'PASS', base });

  for (const [address, bad] of [['B32', null], ['B33', 'missing'], ['L55', null], ['B29', 0]]) {
    const originalValue = await read('Inputs', address);
    const originalFormula = await (await sheet('Inputs')).getFormula(address);
    await set('Inputs', address, bad);
    await wb.calculate();
    assert.equal(await read('Checks', 'B22'), 'FAIL', address);
    for (const cell of ['B14', 'B15', 'B16', 'B17', 'B18', 'B22']) assert.equal(await read('DCF', cell), 'BLOCKED', `${address} -> ${cell}`);
    await set('Inputs', address, originalFormula || originalValue);
    await wb.calculate();
    assert.equal(await read('Checks', 'B22'), 'PASS');
    evidence.push({ name: `Reject missing/invalid ${address}, restore`, result: 'PASS' });
  }
  await set('BalanceSheet', 'L25', 1);
  await wb.calculate();
  assert.equal(await read('Checks', 'B20'), 'PASS');
  assert.equal(await read('Checks', 'L20'), 'FAIL');
  assert.equal(await read('DCF', 'B18'), 'BLOCKED');
  await set('BalanceSheet', 'L25', '=L17-L24');
  await wb.calculate();
  evidence.push({ name: 'Last forecast period failure blocks valuation', result: 'PASS' });

  const ratio = await read('Inputs', 'B33');
  await set('Inputs', 'B33', 0);
  await wb.calculate();
  const zero = await readSnapshot(wb);
  assert.equal(zero.allPeriodStatus, 'PASS');
  assert.equal(zero.dcfStatus, 'EDITED_UNREVIEWED');
  near(zero.stub.noncashPpeAdditions, 0, 'explicit zero');
  near(zero.stub.cashFcf, zero.stub.economicUfcf, 'zero financing difference');
  await set('Inputs', 'B33', ratio);
  await wb.calculate();
  evidence.push({ name: 'Explicit zero and edited decision context', result: 'PASS' });

  // Independent fictional oracle: these overrides are never persisted as MSFT evidence.
  const overrides = { B6: 20, B7: 0, B8: 0, B9: 0, B10: 0, B11: 110, B12: 10, B13: 100, B14: 0, B15: 0, B16: 0, B17: 0, B18: 0, B19: 130, B20: 30, B21: 0, B22: 0, B23: 30, B24: 100, B29: 5, B30: 4, B31: 0.5, B32: 0.4, B33: 1, B34: 0, B35: 0.25, B36: 0, B37: 0.1, B38: 0.02, B43: 100, B44: 20, B45: 0.2, B46: 20, B47: 40, B48: 0.4, B49: 40, B50: 30, B51: 30, B52: 0, B57: 20 };
  for (const [address, value] of Object.entries(overrides)) await set('Inputs', address, value);
  for (let i = 0; i < PERIODS.length; i += 1) {
    await set('Inputs', `${periodColumn(i)}55`, i === 0 ? 25 : 100);
    await set('Inputs', `${periodColumn(i)}58`, i === 0 ? 10 : 0);
  }
  await wb.calculate();
  const toy = await readSnapshot(wb);
  assert.equal(toy.allPeriodStatus, 'PASS');
  const expected = { totalDepreciation: 5.625, ebit: 4.375, netIncome: 3.28125, cfo: 8.90625, closingCash: 18.90625, closingNetPpe: 124.375, cashFcf: -1.09375, economicUfcf: -11.09375 };
  for (const [key, value] of Object.entries(expected)) near(toy.stub[key], value, key);
  const expectedOriginal = [5, 20, 20, 20, 20, 15, 0, 0, 0, 0, 0];
  const expectedTotal = [5.625, 25, 25, 25, 24.375, 15, 0, 0, 0, 0, 0];
  const expectedPpe = [124.375, 99.375, 74.375, 49.375, 25, 10, 10, 10, 10, 10, 10];
  const ppe = await readPeriodValues(wb, 'BalanceSheet', 11);
  for (let i = 0; i < PERIODS.length; i += 1) {
    near(toy.originalPoolDepreciation[i], expectedOriginal[i], `original pool ${i}`);
    near(toy.totalDepreciation[i], expectedTotal[i], `all cohorts ${i}`);
    near(ppe[i], expectedPpe[i], `PP&E ${i}`);
  }
  await set('Inputs', 'B29', 10);
  await wb.calculate();
  const changedLife = await readSnapshot(wb);
  near(changedLife.stub.totalDepreciation, 3.125, 'longer-life depreciation');
  near(changedLife.stub.netIncome - toy.stub.netIncome, 1.875, 'income sensitivity');
  near(changedLife.stub.cfo - toy.stub.cfo, -0.625, 'tax shield sensitivity');
  near(changedLife.enterpriseValue, changedLife.sensitivityCenter, 'edited scenario center');
  evidence.push({ name: 'Independent fictional cohort exhaustion and life sensitivity', result: 'PASS', toy, ppe, changedLife });
} finally { wb.dispose(); }

const missing = structuredClone(model);
missing.packet.facts.opening_balance_sheet.cash.value = null;
await assert.rejects(() => buildAssetWorkbook(missing), /Missing opening balance fact/);
evidence.push({ name: 'JSON null never coerced to zero', result: 'PASS' });
const wrongVersion = structuredClone(model);
wrongVersion.candidate.method_version = 'unsupported-version';
await assert.rejects(() => buildAssetWorkbook(wrongVersion), /Unsupported asset method version/);
evidence.push({ name: 'Method version must match executed formulas', result: 'PASS' });
const hostile = structuredClone(model);
hostile.packet.evidence[0].excerpt = '=1+1';
hostile.packet.evidence[1].source_file = '+SUM(1,2)';
hostile.decision.review_rationale = '@SUM(1,2)';
const { wb: literal } = await buildAssetWorkbook(hostile);
try {
  const source = await literal.getSheet('Evidence');
  assert.equal(await source.getValue('E4'), '=1+1');
  assert.ok(!(await source.getFormula('E4')));
  assert.equal(await source.getValue('F5'), '+SUM(1,2)');
  assert.ok(!(await (await literal.getSheet('Decisions')).getFormula('B10')));
  evidence.push({ name: 'Source/model formula-like text remains literal', result: 'PASS' });
} finally { literal.dispose(); }

const report = { status: 'PASS', purpose: 'P5 financial and adverse checks; fictional oracle is not an MSFT forecast', groupCount: evidence.length, evidence };
await writeFile(resolve(out, 'financial-checks.json'), JSON.stringify(report, null, 2) + '\n');
console.log(JSON.stringify({ status: report.status, groupCount: report.groupCount, reportPath: resolve(out, 'financial-checks.json'), tests: evidence.map((x) => x.name) }, null, 2));
process.exit(0);
