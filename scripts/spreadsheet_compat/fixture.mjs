import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { createWorkbook, api } from '@mog-sdk/sdk';

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(SCRIPT_DIR, '..', '..');
const OUTPUT = resolve(ROOT, 'data', 'build-guide-p1');
const BASE = resolve(OUTPUT, 'mog-fixture-base.xlsx');
const BROKEN = resolve(OUTPUT, 'mog-fixture-broken.xlsx');
const EDITED = resolve(OUTPUT, 'excel-fixture-edited.xlsx');
const INTERRUPTED = resolve(OUTPUT, '.candidate-interrupted.xlsx');
const EXCEL_RESULTS = resolve(OUTPUT, 'excel-verification.json');
const EXCEL_LOG = resolve(OUTPUT, 'evidence', 'excel-verification.log');
const INTERRUPT_LOG = resolve(OUTPUT, 'evidence', 'interrupted-candidate.log');
const VERSION = '0.10.7';
const TOLERANCE = 1e-8;
const UNTRUSTED_LITERALS = Object.freeze({
  B19: '=1+1',
  B20: '+1+1',
  B21: '-1+1',
  B22: '@SUM(1,2)',
});

const EXPECTED_BASE = Object.freeze({
  ebit: 30,
  netIncome: 20.25,
  closingCash: 40.25,
  assets: 90.25,
  equity: 60.25,
  balanceDifference: 0,
  ufcf: 22.5,
  enterpriseValue: 281.25,
  equityValue: 271.25,
  perShareValue: 27.125,
});

const EXPECTED_EDITED = Object.freeze({
  ebit: 38,
  netIncome: 26.25,
  closingCash: 46.25,
  assets: 96.25,
  equity: 66.25,
  balanceDifference: 0,
  ufcf: 28.5,
  enterpriseValue: 356.25,
  equityValue: 346.25,
  perShareValue: 34.625,
});

function fixtureRows(revenue = 100) {
  return [
    ['P1 calculation/export compatibility fixture', null, null],
    [null, null, null],
    ['Assumption', 'Value', 'Units'],
    ['Revenue', revenue, 'USD millions'],
    ['Cash operating expense', 0.6, '% of revenue'],
    ['Opening cash', 20, 'USD millions'],
    ['Opening PP&E', 50, 'USD millions'],
    ['Opening debt', 30, 'USD millions'],
    ['Opening equity', 40, 'USD millions'],
    ['Cash capex', 10, 'USD millions'],
    ['Opening-asset depreciation', 0.2, '% of opening PP&E'],
    ['Opening debt interest', 0.1, '% of opening debt'],
    ['Tax rate', 0.25, '%'],
    ['WACC', 0.1, '%'],
    ['Terminal growth', 0.02, '%'],
    ['Shares outstanding', 10, 'millions'],
  ];
}

function modelRows() {
  return [
    ['Fictional linked model (USD millions except per share)', null, null],
    [null, null, null],
    ['Income statement', 'Value', 'Units'],
    ['Revenue', '=Inputs!B4', 'USD millions'],
    ['Cash operating expense', '=-B4*Inputs!B5', 'USD millions'],
    ['Depreciation', '=-Inputs!B7*Inputs!B11', 'USD millions'],
    ['EBIT', '=SUM(B4:B6)', 'USD millions'],
    ['Interest expense', '=-Inputs!B8*Inputs!B12', 'USD millions'],
    ['Pre-tax income', '=SUM(B7:B8)', 'USD millions'],
    ['Taxes', '=-B9*Inputs!B13', 'USD millions'],
    ['Net income', '=SUM(B9:B10)', 'USD millions'],
    [null, null, null],
    ['Cash flow', 'Value', 'Units'],
    ['Net income', '=B11', 'USD millions'],
    ['Depreciation add-back', '=-B6', 'USD millions'],
    ['Cash capex', '=-Inputs!B10', 'USD millions'],
    ['UFCF', '=B7*(1-Inputs!B13)-B6+B16', 'USD millions'],
    ['Closing cash', '=Inputs!B6+B14+B15+B16', 'USD millions'],
    [null, null, null],
    ['Balance sheet', 'Value', 'Units'],
    ['Closing cash', '=B18', 'USD millions'],
    ['Closing PP&E', '=Inputs!B7+Inputs!B10+B6', 'USD millions'],
    ['Total assets', '=SUM(B21:B22)', 'USD millions'],
    ['Debt', '=Inputs!B8', 'USD millions'],
    ['Closing equity', '=Inputs!B9+B11', 'USD millions'],
    ['Total liabilities + equity', '=SUM(B24:B25)', 'USD millions'],
    ['Balance difference', '=B23-B26', 'USD millions'],
    [null, null, null],
    ['DCF', 'Value', 'Units'],
    ['UFCF', '=B17', 'USD millions'],
    ['Enterprise value', '=B30/(Inputs!B14-Inputs!B15)', 'USD millions'],
    ['Debt', '=B24', 'USD millions'],
    ['Equity value', '=B31-B32+Inputs!B6', 'USD millions'],
    ['Shares', '=Inputs!B16', 'millions'],
    ['Per-share value', '=B33/B34', 'USD per share'],
  ];
}

async function makeWorkbook(revenue = 100, broken = false) {
  const wb = await createWorkbook({ userTimezone: 'UTC' });
  await wb.sheets.rename('Sheet1', 'Inputs');
  const inputs = wb.activeSheet;
  const model = await wb.sheets.add('Model');
  const checks = await wb.sheets.add('Checks');
  const decisions = await wb.sheets.add('Decisions');

  await inputs.setRange('A1:C16', fixtureRows(revenue));
  await model.setRange('A1:C35', modelRows());
  await checks.setRange('A1:B5', [
    ['Mechanical checks', 'Value'],
    [null, null],
    ['Balance difference', '=Model!B27'],
    ['Balance check', '=IF(B3=0,"PASS","FAIL")'],
    ['Fixture type', 'Fictional; no MSFT policy decision'],
  ]);
  await inputs.setRange('A18:C22', [
    ['Untrusted label/excerpt', 'Literal text', 'Units'],
    ['equals', null, 'literal text'],
    ['plus', null, 'literal text'],
    ['minus', null, 'literal text'],
    ['at-sign', null, 'literal text'],
  ]);
  for (const [address, value] of Object.entries(UNTRUSTED_LITERALS)) {
    await inputs.setCell(address, value, { literal: true });
  }
  await decisions.setRange('A1:B8', [
    ['P1 engine decision record', null],
    [null, null],
    ['Decision ID', 'P1-MOG-COMPATIBILITY'],
    ['Decision', 'Mog SDK candidate for fixture proof'],
    ['Scope', 'Fictional USD millions model; no MSFT policy decision.'],
    ['Literal untrusted text', 'untrusted text: <input> & "review"'],
    [null, null],
    ['Internal decision link', 'Open decision record'],
  ]);

  await inputs.formats.setRange('A3:C3', { bold: true, backgroundColor: '#D9EAF7' });
  await inputs.formats.setRange('A18:C18', { bold: true, backgroundColor: '#D9EAF7' });
  await model.formats.setRange('A3:C3', { bold: true, backgroundColor: '#D9EAF7' });
  await model.formats.setRange('A13:C13', { bold: true, backgroundColor: '#D9EAF7' });
  await model.formats.setRange('A20:C20', { bold: true, backgroundColor: '#D9EAF7' });
  await model.formats.setRange('A29:C29', { bold: true, backgroundColor: '#D9EAF7' });
  await inputs.formats.setRange('B4:B4', { numberFormat: '$#,##0.000000;($#,##0.000000);-' });
  await inputs.formats.setRange('B6:B10', { numberFormat: '$#,##0.000000;($#,##0.000000);-' });
  await inputs.formats.setRange('B16:B16', { numberFormat: '#,##0.000000;(#,##0.000000);-' });
  await inputs.formats.setRange('B5:B5', { numberFormat: '0.0%' });
  await inputs.formats.setRange('B11:B15', { numberFormat: '0.0%' });
  await model.formats.setRange('B4:B35', { numberFormat: '#,##0.000000;(#,##0.000000);-' });
  await model.formats.setRange('B35:B35', { numberFormat: '$#,##0.000000;($#,##0.000000);-' });
  await checks.formats.setRange('A1:B1', { bold: true, backgroundColor: '#D9EAF7' });
  await decisions.formats.setRange('A1:B1', { bold: true, backgroundColor: '#D9EAF7' });
  await inputs.comments.addNote('B4', {
    author: 'smrik-fund P1 fixture',
    text: 'Source: fictional acceptance fixture in run DECISIONS.md. Literal untrusted text: <Revenue input> & "review".',
  });
  await decisions.setCell('B8', '=HYPERLINK("#\'Decisions\'!A1","Open decision record")');
  if (broken) await checks.setCell('B3', '=#REF!');
  await wb.calculate();
  return wb;
}

async function saveWorkbook(path, revenue = 100, broken = false) {
  await mkdir(OUTPUT, { recursive: true });
  const wb = await makeWorkbook(revenue, broken);
  try {
    await wb.save(path);
  } finally {
    wb.dispose();
  }
}

async function criticalValues(wb) {
  const ws = await wb.getSheet('Model');
  const cells = {
    ebit: 'B7',
    netIncome: 'B11',
    closingCash: 'B18',
    assets: 'B23',
    equity: 'B25',
    balanceDifference: 'B27',
    ufcf: 'B30',
    enterpriseValue: 'B31',
    equityValue: 'B33',
    perShareValue: 'B35',
  };
  const values = {};
  for (const [name, cell] of Object.entries(cells)) values[name] = await ws.getValue(cell);
  return values;
}

function assertValues(actual, expected, label) {
  for (const [name, wanted] of Object.entries(expected)) {
    const got = Number(actual[name]);
    if (!Number.isFinite(got) || Math.abs(got - wanted) > TOLERANCE) {
      throw new Error(`${label} ${name}: expected ${wanted}, got ${actual[name]}`);
    }
  }
}

async function inspectMogExport() {
  const wb = await createWorkbook(BASE, { userTimezone: 'UTC' });
  try {
    const values = await criticalValues(wb);
    assertValues(values, EXPECTED_BASE, 'Mog base');
    const model = await wb.getSheet('Model');
    const inputs = await wb.getSheet('Inputs');
    const decisions = await wb.getSheet('Decisions');
    const formulas = {
      ebit: await model.getFormula('B7'),
      netIncome: await model.getFormula('B11'),
      balanceDifference: await model.getFormula('B27'),
      enterpriseValue: await model.getFormula('B31'),
      perShareValue: await model.getFormula('B35'),
    };
    const note = await inputs.comments.getNote('B4');
    const hyperlink = await decisions.hyperlinks.get('B8');
    const hyperlinkFormula = await decisions.getFormula('B8');
    const revenueFormat = await inputs.formats.get('B4');
    const valueFormat = await model.formats.get('B35');
    const literalReadback = {};
    for (const [address, expected] of Object.entries(UNTRUSTED_LITERALS)) {
      const value = await inputs.getValue(address);
      const formula = await inputs.getFormula(address);
      if (value !== expected || formula !== null) {
        throw new Error(`Mog changed untrusted literal ${address}: ${JSON.stringify({ value, formula })}`);
      }
      literalReadback[address] = { value, formula };
    }
    if (!Object.values(formulas).every((value) => typeof value === 'string' && value.startsWith('='))) {
      throw new Error(`Mog export lost linked formulas: ${JSON.stringify(formulas)}`);
    }
    if (!note?.content?.includes('<Revenue input>') || note.author !== 'smrik-fund P1 fixture') {
      throw new Error(`Mog export lost note: ${JSON.stringify(note)}`);
    }
    if (hyperlink !== "#'Decisions'!A1" || hyperlinkFormula !== '=HYPERLINK("#\'Decisions\'!A1","Open decision record")') {
      throw new Error(`Mog export lost trusted workbook hyperlink: ${JSON.stringify({ hyperlink, hyperlinkFormula })}`);
    }
    if (revenueFormat.numberFormat !== '$#,##0.000000;($#,##0.000000);-' || valueFormat.numberFormat !== '$#,##0.000000;($#,##0.000000);-') {
      throw new Error(`Mog export lost number formats: ${JSON.stringify({ revenueFormat, valueFormat })}`);
    }
    return { values, formulas, hyperlinkFormula, literalReadback, note, hyperlink, numberFormats: { revenue: revenueFormat.numberFormat, perShare: valueFormat.numberFormat } };
  } finally {
    wb.dispose();
  }
}

async function verifyBrokenReference() {
  const wb = await createWorkbook(BROKEN, { userTimezone: 'UTC' });
  try {
    const checks = await wb.getSheet('Checks');
    const value = await checks.getValue('B3');
    const cell = await checks.getCell('B3');
    if (!['#REF!', '#NAME?'].includes(value) || cell.value?.type !== 'error') {
      throw new Error(`Broken reference was not detected: ${JSON.stringify({ value, cell })}`);
    }
    return { value, errorType: cell.value.type, message: cell.value.message };
  } finally {
    wb.dispose();
  }
}

function sha256(path) {
  return readFile(path).then((bytes) => createHash('sha256').update(bytes).digest('hex'));
}

async function interruptedCandidate() {
  const wb = await makeWorkbook(120);
  try {
    await wb.save(INTERRUPTED);
  } finally {
    wb.dispose();
  }
  process.kill(process.pid, 'SIGTERM');
}

function runExcelVerifier() {
  const verifier = resolve(SCRIPT_DIR, 'verify-excel.ps1');
  const result = spawnSync('powershell.exe', [
    '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', verifier,
    '-WorkbookPath', BASE, '-EditedPath', EDITED, '-BrokenPath', BROKEN,
    '-ResultsPath', EXCEL_RESULTS,
  ], { encoding: 'utf8', timeout: 90000, windowsHide: true });
  const output = `${result.stdout ?? ''}${result.stderr ?? ''}`;
  return writeFile(EXCEL_LOG, output, 'utf8').then(() => {
    if (result.error) throw result.error;
    if (result.status !== 0) throw new Error(`Excel verifier failed (${result.status}): ${output}`);
    return readFile(EXCEL_RESULTS, 'utf8').then((text) => JSON.parse(text.replace(/^\uFEFF/, '')));
  });
}

async function verify() {
  await mkdir(resolve(OUTPUT, 'evidence'), { recursive: true });
  await saveWorkbook(BASE);
  await saveWorkbook(BROKEN, 100, true);
  const mog = await inspectMogExport();
  const broken = await verifyBrokenReference();
  const beforeInterrupt = await sha256(BASE);
  const interrupted = spawnSync(process.execPath, [fileURLToPath(import.meta.url), 'interrupt'], {
    cwd: SCRIPT_DIR, encoding: 'utf8', timeout: 30000, windowsHide: true,
  });
  await writeFile(INTERRUPT_LOG, `${interrupted.stdout ?? ''}${interrupted.stderr ?? ''}`, 'utf8');
  const afterInterrupt = await sha256(BASE);
  if (beforeInterrupt !== afterInterrupt) throw new Error('Interrupted candidate changed published fixture bytes');
  if (interrupted.signal !== 'SIGTERM' && interrupted.status === 0) throw new Error('Interrupted candidate did not interrupt');
  const baseFingerprint = await sha256(BASE);
  const excel = await runExcelVerifier();
  if (excel.publishedSha256Before !== baseFingerprint) {
    throw new Error(`Excel result fingerprint mismatch: expected ${baseFingerprint}, got ${excel.publishedSha256Before}`);
  }
  const report = {
    sdkVersion: VERSION,
    tolerance: TOLERANCE,
    verificationMode: 'fresh-mog-and-actual-excel',
    baseWorkbook: BASE,
    editedWorkbook: EDITED,
    brokenWorkbook: BROKEN,
    mog,
    independentExpectedBase: EXPECTED_BASE,
    independentExpectedEdited: EXPECTED_EDITED,
    brokenReference: broken,
    interruptedCandidate: { publishedSha256Before: beforeInterrupt, publishedSha256After: afterInterrupt, unchanged: true },
    excel,
  };
  await writeFile(resolve(OUTPUT, 'p1-verification.json'), JSON.stringify(report, null, 2), 'utf8');
  console.log(JSON.stringify(report, null, 2));
}

async function probe() {
  const descriptions = {
    createWorkbook: api.describe('createWorkbook'),
    addNote: api.describe('ws.comments.addNote'),
    hyperlink: api.describe('ws.hyperlinks.set'),
    format: api.describe('ws.formats.set'),
  };
  await saveWorkbook(BASE);
  console.log(JSON.stringify({ sdkVersion: VERSION, descriptions, workbook: BASE }, null, 2));
}

const command = process.argv[2] ?? 'verify';
if (command === 'build') await saveWorkbook(BASE);
else if (command === 'build-broken') await saveWorkbook(BROKEN, 100, true);
else if (command === 'interrupt') await interruptedCandidate();
else if (command === 'probe') await probe();
else if (command === 'verify') await verify();
else throw new Error(`Unknown command: ${command}`);
