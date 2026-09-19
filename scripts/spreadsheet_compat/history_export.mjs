import { readFile } from 'node:fs/promises';
import { createWorkbook } from '@mog-sdk/sdk';

const payloadPath = process.argv[2];
const outputPath = process.argv[3];
if (!payloadPath || !outputPath) throw new Error('usage: node history_export.mjs payload.json output.xlsx');

function columnName(number) {
  let result = '';
  let value = number;
  while (value > 0) {
    const remainder = (value - 1) % 26;
    result = String.fromCharCode(65 + remainder) + result;
    value = Math.floor((value - 1) / 26);
  }
  return result;
}

function address(row, column) {
  return `${columnName(column)}${row}`;
}

async function writeTable(sheet, rows) {
  const width = Math.max(...rows.map((row) => row.length), 1);
  const normalized = rows.map((row) => [...row, ...Array(width - row.length).fill(null)]);
  await sheet.setRange(`A1:${address(normalized.length, width)}`, normalized);
  for (let row = 0; row < normalized.length; row += 1) {
    for (let column = 0; column < width; column += 1) {
      const value = normalized[row][column];
      if (typeof value === 'string' && /^[=+\-@]/.test(value)) {
        await sheet.setCell(address(row + 1, column + 1), value, { literal: true });
      }
    }
  }
  if (normalized.length > 0) {
    await sheet.formats.setRange(`A1:${address(1, width)}`, { bold: true, backgroundColor: '#D9EAF7' });
  }
}

function findTableRow(data, criteria) {
  const headers = data[0] || [];
  const indexes = Object.fromEntries(headers.map((header, index) => [String(header), index]));
  return data.slice(1).find((row) => Object.entries(criteria).every(([column, wanted]) => {
    const index = indexes[column];
    if (index === undefined) return false;
    return String(row[index]) === String(wanted);
  }));
}

function tableCell(data, row, column) {
  const index = (data[0] || []).findIndex((header) => String(header) === column);
  if (index < 0) throw new Error(`workbook verification column missing: ${column}`);
  return row[index];
}

function assertClose(actual, expected, label) {
  const got = Number(actual);
  const wanted = Number(expected);
  if (!Number.isFinite(got) || !Number.isFinite(wanted) || Math.abs(got - wanted) > 1e-6) {
    throw new Error(`${label}: expected ${expected}, got ${actual}`);
  }
}

const payload = JSON.parse(await readFile(payloadPath, 'utf8'));
const wb = await createWorkbook({ userTimezone: 'UTC' });
try {
  await wb.sheets.rename('Sheet1', 'Readme');
  const readme = await wb.getSheet('Readme');
  const sheets = {};
  for (const [name, rows] of Object.entries(payload.sheets || {})) {
    const sheet = name === 'Readme' ? readme : await wb.sheets.add(name);
    sheets[name] = sheet;
    await writeTable(sheet, rows);
  }
  const links = ['Annual', 'YTD_TTM', 'BalanceSheet', 'Periods', 'Sources', 'Checks', 'Evidence'];
  for (let index = 0; index < links.length; index += 1) {
    const sheetName = links[index];
    await readme.setCell(`B${10 + index}`, `=HYPERLINK("#'${sheetName}'!A1","Open ${sheetName}")`);
  }
  await wb.calculate();
  await wb.save(outputPath);
} finally {
  wb.dispose();
}

const reopened = await createWorkbook(outputPath, { userTimezone: 'UTC' });
try {
  const sheetNames = Object.keys(payload.sheets || {});
  const headers = {};
  for (const name of sheetNames) {
    const sheet = await reopened.getSheet(name);
    headers[name] = await sheet.getValue('A1');
  }
  if (headers.Readme !== 'MSFT frozen historical view (P2)') throw new Error('Readme header missing after export');
  const navFormula = await (await reopened.getSheet('Readme')).getFormula('B10');
  if (!navFormula || !navFormula.startsWith('=HYPERLINK')) throw new Error('navigation formula missing after export');
  const verifiedNumeric = [];
  for (const item of payload.verification?.numeric || []) {
    const data = await (await reopened.getSheet(item.sheet)).getData();
    const row = findTableRow(data, item.criteria || {});
    if (!row) throw new Error(`workbook verification row missing: ${item.sheet} ${JSON.stringify(item.criteria)}`);
    assertClose(tableCell(data, row, item.valueColumn), item.expectedValue, `${item.sheet} ${item.valueColumn}`);
    if (item.unitColumn) {
      const actualUnit = tableCell(data, row, item.unitColumn);
      if (String(actualUnit) !== String(item.expectedUnit)) {
        throw new Error(`${item.sheet} unit mismatch: expected ${item.expectedUnit}, got ${actualUnit}`);
      }
    }
    verifiedNumeric.push({ sheet: item.sheet, criteria: item.criteria, valueColumn: item.valueColumn });
  }
  const verifiedEvidence = [];
  for (const item of payload.verification?.evidence || []) {
    const data = await (await reopened.getSheet(item.sheet)).getData();
    const found = data.flat().some((value) => String(value).includes(item.contains));
    if (!found) throw new Error(`workbook evidence text missing: ${item.sheet} ${item.contains}`);
    verifiedEvidence.push({ sheet: item.sheet, contains: item.contains });
  }
  console.log(JSON.stringify({ status: 'PASS', version: '0.10.7', sheets: sheetNames, headers, navigationFormula: navFormula, verifiedNumeric, verifiedEvidence }));
} finally {
  reopened.dispose();
}
