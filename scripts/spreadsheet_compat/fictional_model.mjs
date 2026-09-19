import { createWorkbook } from '@mog-sdk/sdk';

export const ENGINE_VERSION = '0.10.7';
export const MODEL_VERSION = 'p4-fictional-three-statement-v1';
export const TOLERANCE = 1e-8;

export const PERIODS = Object.freeze([
  { id: 'FY2026_STUB', label: 'Apr-Jun FY2026 (stub)', yearFraction: 0.25, cumulativeYears: 0.25 },
  { id: 'FY2027', label: 'FY2027', yearFraction: 1, cumulativeYears: 1.25 },
  { id: 'FY2028', label: 'FY2028', yearFraction: 1, cumulativeYears: 2.25 },
  { id: 'FY2029', label: 'FY2029', yearFraction: 1, cumulativeYears: 3.25 },
  { id: 'FY2030', label: 'FY2030', yearFraction: 1, cumulativeYears: 4.25 },
  { id: 'FY2031', label: 'FY2031', yearFraction: 1, cumulativeYears: 5.25 },
  { id: 'FY2032', label: 'FY2032', yearFraction: 1, cumulativeYears: 6.25 },
  { id: 'FY2033', label: 'FY2033', yearFraction: 1, cumulativeYears: 7.25 },
  { id: 'FY2034', label: 'FY2034', yearFraction: 1, cumulativeYears: 8.25 },
  { id: 'FY2035', label: 'FY2035', yearFraction: 1, cumulativeYears: 9.25 },
  { id: 'FY2036', label: 'FY2036', yearFraction: 1, cumulativeYears: 10.25 },
]);

export const DEFAULT_INPUTS = Object.freeze({
  openingCash: 20,
  openingAR: 10,
  openingInventory: 5,
  openingNetPPE: 50,
  openingAP: 8,
  openingDebt: 30,
  openingEquity: 47,
  annualizedOpeningRevenue: 100,
  stubYearFraction: 0.25,
  cashCostRate: 0.6,
  revenueGrowth: 0.1,
  capexRate: 0.1,
  depreciationRate: 0.2,
  interestRate: 0.1,
  taxRate: 0.25,
  dividendPayout: 0.25,
  arRate: 0.1,
  inventoryAnnualizedCostFraction: 1 / 12,
  apAnnualizedCostFraction: 2 / 15,
  wacc: 0.1,
  terminalGrowth: 0.02,
  shares: 10,
});

export const REQUIRED_INPUT_ADDRESSES = Object.freeze([
  'B6', 'B7', 'B8', 'B9', 'B10', 'B11', 'B12',
  'B17', 'B18', 'B19', 'B20', 'B21', 'B22', 'B23', 'B24', 'B25', 'B26', 'B27', 'B28', 'B29', 'B30', 'B31',
  'B35', 'C35', 'D35', 'E35', 'F35', 'G35', 'H35', 'I35', 'J35', 'K35', 'L35',
]);
export const REQUIRED_INPUT_COUNT = REQUIRED_INPUT_ADDRESSES.length;

export const MODEL_ROWS = Object.freeze({
  income: Object.freeze({ revenue: 6, costs: 7, depreciation: 8, ebit: 9, interest: 10, pretax: 11, taxes: 12, netIncome: 13 }),
  schedules: Object.freeze({ revenue: 10, costs: 11, capex: 12, depreciation: 13, openingPPE: 14, closingPPE: 15, openingDebt: 16, closingDebt: 17, interest: 18, openingAR: 19, closingAR: 20, openingInventory: 21, closingInventory: 22, openingAP: 23, closingAP: 24, openingNWC: 25, closingNWC: 26, increaseNWC: 27, cashTaxes: 28, dividends: 29, openingEquity: 30, closingEquity: 31, openingCash: 32, netChangeCash: 33, closingCash: 34, fundingStatus: 35, taxStatus: 36 }),
  cashFlow: Object.freeze({ netIncome: 6, depreciation: 7, increaseNWC: 8, cfo: 9, capex: 10, cfi: 11, dividends: 12, debtMovement: 13, cff: 14, netChangeCash: 15, openingCash: 16, closingCash: 17 }),
  balanceSheet: Object.freeze({ cash: 6, ar: 7, inventory: 8, netPPE: 9, assets: 10, ap: 11, debt: 12, equity: 13, liabilitiesEquity: 14, difference: 15 }),
  dcf: Object.freeze({ ufcf: 7, cumulativeYears: 6, discountFactor: 8, pvUfcf: 9, terminalUfcf: 11, terminalValue: 12, pvTerminal: 13, pvExplicit: 14, enterpriseValue: 15, bridgeCash: 16, bridgeDebt: 17, equityValue: 18, shares: 19, perShare: 20, terminalCheck: 21, fundingCondition: 22, requiredInputCondition: 23, valuationStatus: 24 }),
});

const AMOUNT_FORMAT = '#,##0.000000;(#,##0.000000);-';
const CURRENCY_FORMAT = '$#,##0.000000;($#,##0.000000);-';
const PERIOD_START_COLUMN = 2;

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

export function periodColumn(index) {
  return columnName(PERIOD_START_COLUMN + index);
}

export function periodCell(index, row) {
  return `${periodColumn(index)}${row}`;
}

function padRow(values, width = 13) {
  return [...values, ...Array(Math.max(width - values.length, 0)).fill(null)];
}

function periodRow(label, values, units = 'USD millions') {
  return padRow([label, ...values, units]);
}

function periodHeader() {
  return periodRow('Period ID', PERIODS.map((period) => period.id), '');
}

function periodLabels() {
  return periodRow('Period label', PERIODS.map((period) => period.label), '');
}

function periodFractions() {
  return periodRow('Year fraction', PERIODS.map((period) => period.yearFraction), 'years');
}

function requiredNumericCountFormula() {
  return `=${REQUIRED_INPUT_ADDRESSES.map((address) => `IF(ISNUMBER(${address}),1,0)`).join('+')}`;
}

export function mergeInputs(overrides = {}) {
  return { ...DEFAULT_INPUTS, ...overrides };
}

export function validatePeriods(periods = PERIODS) {
  if (!Array.isArray(periods) || periods.length !== 11) {
    throw new Error(`fixture requires exactly 11 forecast periods; got ${periods?.length ?? 'missing'}`);
  }
  let cumulative = 0;
  periods.forEach((period, index) => {
    if (!period || typeof period.id !== 'string' || typeof period.label !== 'string') {
      throw new Error(`invalid period metadata at index ${index}`);
    }
    if (!Number.isFinite(period.yearFraction) || period.yearFraction <= 0) {
      throw new Error(`invalid year fraction for ${period.id}`);
    }
    cumulative += period.yearFraction;
    if (Math.abs(cumulative - period.cumulativeYears) > TOLERANCE) {
      throw new Error(`invalid cumulative period reference for ${period.id}`);
    }
  });
  if (Math.abs(periods[0].yearFraction - 0.25) > TOLERANCE || periods.slice(1).some((period) => period.yearFraction !== 1)) {
    throw new Error('fixture period shape must be a 0.25-year stub followed by ten one-year periods');
  }
}

export function validateFixtureInputs(inputs) {
  for (const key of Object.keys(DEFAULT_INPUTS)) {
    if (!Number.isFinite(inputs[key])) throw new Error(`required input missing or invalid: ${key}`);
  }
  if (inputs.stubYearFraction <= 0 || inputs.stubYearFraction > 1) throw new Error('stubYearFraction must be in (0, 1]');
  if (Math.abs(inputs.stubYearFraction - PERIODS[0].yearFraction) > TOLERANCE) throw new Error('stubYearFraction must match the fixed 0.25-year fixture period');
  if (inputs.wacc <= 0) throw new Error('wacc must be positive');
  if (inputs.terminalGrowth < 0 || inputs.terminalGrowth >= inputs.wacc) throw new Error('terminalGrowth must satisfy 0 <= g < WACC');
  if (inputs.shares <= 0) throw new Error('shares must be positive');
  const openingAssets = inputs.openingCash + inputs.openingAR + inputs.openingInventory + inputs.openingNetPPE;
  const openingLiabilitiesEquity = inputs.openingAP + inputs.openingDebt + inputs.openingEquity;
  if (Math.abs(openingAssets - openingLiabilitiesEquity) > TOLERANCE) {
    throw new Error(`opening balance sheet does not balance: ${openingAssets} vs ${openingLiabilitiesEquity}`);
  }
  if (Object.hasOwn(inputs, 'stubRevenue') && (!Number.isFinite(inputs.stubRevenue) || inputs.stubRevenue < 0)) {
    throw new Error('stubRevenue must be a non-negative number when supplied');
  }
}

function inputRows(inputs) {
  const stubRevenue = Object.hasOwn(inputs, 'stubRevenue') ? inputs.stubRevenue : '=B17*B18';
  const revenueValues = [stubRevenue];
  for (let index = 1; index < PERIODS.length; index += 1) {
    const previous = periodColumn(index - 1);
    const formula = index === 1 ? `=${previous}35/B18*(1+B20)` : `=${previous}35*(1+B20)`;
    revenueValues.push(formula);
  }
  return [
    padRow(['P4 fictional linked three-statement DCF inputs']),
    padRow(['Synthetic USD millions fixture; all assumptions are visible and fictional.']),
    padRow([]),
    padRow(['Opening balance sheet', null, null, 'Opening values at fictional 2026-03-31 measurement date']),
    padRow(['Input', 'Value', 'Units', 'Basis / note']),
    padRow(['Opening cash', inputs.openingCash, 'USD millions', 'Opening balance; bridge cash']),
    padRow(['Opening accounts receivable', inputs.openingAR, 'USD millions', 'Opening balance']),
    padRow(['Opening inventory', inputs.openingInventory, 'USD millions', 'Opening balance']),
    padRow(['Opening net PP&E', inputs.openingNetPPE, 'USD millions', 'Opening balance; depreciation base']),
    padRow(['Opening accounts payable', inputs.openingAP, 'USD millions', 'Opening balance']),
    padRow(['Opening debt', inputs.openingDebt, 'USD millions', 'Opening balance; opening-balance interest']),
    padRow(['Opening equity', inputs.openingEquity, 'USD millions', 'Opening balance; no plug']),
    padRow(['Opening balance difference', '=B6+B7+B8+B9-B10-B11-B12', 'USD millions', 'Must be zero']),
    padRow([]),
    padRow(['Operating and DCF assumptions', null, null, 'Provisional fictional policy; not an MSFT recommendation']),
    padRow(['Input', 'Value', 'Units', 'Basis / note']),
    padRow(['Annualized opening revenue', inputs.annualizedOpeningRevenue, 'USD millions', 'Annual run rate used for stub and balance drivers']),
    padRow(['Stub year fraction', inputs.stubYearFraction, 'years', 'Apr-Jun FY2026 = 0.25; never annualize the quarter itself']),
    padRow(['Cash operating cost rate', inputs.cashCostRate, '% of revenue', 'Cash costs include all modeled operating costs']),
    padRow(['Annual revenue growth', inputs.revenueGrowth, '%', 'Visible synthetic growth assumption for FY2027 onward']),
    padRow(['Capex rate', inputs.capexRate, '% of revenue', 'Cash capex at period end']),
    padRow(['Opening net-PPE depreciation rate', inputs.depreciationRate, '% of opening net PP&E', 'Opening asset base only; pro-rated by year fraction']),
    padRow(['Opening-debt interest rate', inputs.interestRate, '% of opening debt', 'Non-circular interest on opening debt']),
    padRow(['Tax rate', inputs.taxRate, '%', 'Positive pretax income only; same-period cash tax']),
    padRow(['Dividend payout ratio', inputs.dividendPayout, '% of positive net income', 'No dividend on losses']),
    padRow(['Receivables rate', inputs.arRate, '% of annualized revenue', 'Stub uses revenue / year fraction']),
    padRow(['Inventory cost fraction', inputs.inventoryAnnualizedCostFraction, 'fraction of annualized cash costs', 'One-twelfth of annualized cash operating costs']),
    padRow(['Payables cost fraction', inputs.apAnnualizedCostFraction, 'fraction of annualized cash costs', 'Two-fifteenths of annualized cash operating costs']),
    padRow(['WACC', inputs.wacc, '%', 'Per-period discounting; visible synthetic assumption']),
    padRow(['Terminal UFCF growth', inputs.terminalGrowth, '%', 'Simple perpetual growth; must be below WACC']),
    padRow(['Shares outstanding', inputs.shares, 'millions', 'Fixed shares in this fixture']),
    padRow([]),
    padRow(['Required input check', `=IF(B34=${REQUIRED_INPUT_COUNT},"PASS","FAIL")`, '', 'Every editable assumption and revenue driver cell must be numeric; zero is valid']),
    padRow(['Required numeric input count', requiredNumericCountFormula(), 'count', `${REQUIRED_INPUT_COUNT} mandatory cells; live formula gate for Excel edits`]),
    periodRow('Revenue forecast input / driver', revenueValues, 'USD millions'),
    padRow(['Revenue row note', 'B35 is editable in Excel; later years link to prior revenue and the visible growth assumption.']),
    padRow([]),
    padRow(['Untrusted source-like text', 'Literal text', 'Status', 'These values must remain literal in the workbook']),
    padRow(['Formula-like excerpt', null, 'literal', 'Untrusted text is never evaluated']),
    padRow(['Plus-like excerpt', null, 'literal', 'Untrusted text is never evaluated']),
    padRow(['At-sign excerpt', null, 'literal', 'Untrusted text is never evaluated']),
  ];
}

function scheduleRows(brokenReference) {
  const rows = [
    padRow(['Shared schedules (application-owned formulas)']),
    padRow(['All balances and flows are USD millions; opening balances and policies are fictional.']),
    periodHeader(),
    periodLabels(),
    periodFractions(),
    periodRow('Cumulative discount years', PERIODS.map((period) => period.cumulativeYears), 'years'),
    periodRow('Discount factor', PERIODS.map((_, index) => `=1/(1+Inputs!B29)^${periodColumn(index)}6`), 'factor'),
    padRow([]),
    padRow(['Operating and balance schedules', null, null, 'Shared source for the three statements and DCF']),
  ];
  const rowValues = (row, generator, units = 'USD millions') => rows.push(periodRow(row, PERIODS.map((_, index) => generator(index)), units));
  rowValues('Revenue', (index) => `=Inputs!${periodColumn(index)}35`);
  rowValues('Cash operating costs', (index) => `=${periodColumn(index)}10*Inputs!B19`);
  rowValues('Capex', (index) => `=${periodColumn(index)}10*Inputs!B21`);
  rowValues('Depreciation', (index) => `=Inputs!B9*Inputs!B22*${periodColumn(index)}5`);
  rowValues('Opening net PP&E', (index) => index === 0 ? '=Inputs!B9' : `=${periodColumn(index - 1)}15`);
  rowValues('Closing net PP&E', (index) => `=${periodColumn(index)}14+${periodColumn(index)}12-${periodColumn(index)}13`);
  rowValues('Opening debt', (index) => index === 0 ? '=Inputs!B11' : `=${periodColumn(index - 1)}17`);
  rowValues('Closing debt', (index) => `=${periodColumn(index)}16`);
  rowValues('Interest expense', (index) => `=${periodColumn(index)}16*Inputs!B23*${periodColumn(index)}5`);
  rowValues('Opening accounts receivable', (index) => index === 0 ? '=Inputs!B7' : `=${periodColumn(index - 1)}20`);
  rowValues('Closing accounts receivable', (index) => `=${periodColumn(index)}10/${periodColumn(index)}5*Inputs!B26`);
  rowValues('Opening inventory', (index) => index === 0 ? '=Inputs!B8' : `=${periodColumn(index - 1)}22`);
  rowValues('Closing inventory', (index) => `=${periodColumn(index)}11/${periodColumn(index)}5*Inputs!B27`);
  rowValues('Opening accounts payable', (index) => index === 0 ? '=Inputs!B10' : `=${periodColumn(index - 1)}24`);
  rowValues('Closing accounts payable', (index) => `=${periodColumn(index)}11/${periodColumn(index)}5*Inputs!B28`);
  rowValues('Opening operating NWC', (index) => index === 0 ? '=Inputs!B7+Inputs!B8-Inputs!B10' : `=${periodColumn(index - 1)}26`);
  rowValues('Closing operating NWC', (index) => `=${periodColumn(index)}20+${periodColumn(index)}22-${periodColumn(index)}24`);
  rowValues('Increase in operating NWC', (index) => `=${periodColumn(index)}26-${periodColumn(index)}25`);
  rowValues('Cash tax payment', (index) => `=IF(Income!${periodColumn(index)}11>0,Income!${periodColumn(index)}11*Inputs!B24,0)`);
  rowValues('Dividends', (index) => `=IF(Income!${periodColumn(index)}13>0,Income!${periodColumn(index)}13*Inputs!B25,0)`);
  rowValues('Opening equity', (index) => index === 0 ? '=Inputs!B12' : `=${periodColumn(index - 1)}31`);
  rowValues('Closing equity', (index) => `=${periodColumn(index)}30+Income!${periodColumn(index)}13-${periodColumn(index)}29`);
  rowValues('Opening cash', (index) => index === 0 ? '=Inputs!B6' : `=${periodColumn(index - 1)}34`);
  rowValues('Net change in cash', (index) => `=CashFlow!${periodColumn(index)}15`);
  rowValues('Closing cash', (index) => `=CashFlow!${periodColumn(index)}17`);
  rowValues('Funding status', (index) => `=IF(${periodColumn(index)}34<0,"FUNDING_DEFICIT","OK")`, 'status');
  rowValues('Tax/refund status', (index) => `=IF(${periodColumn(index)}28<0,"UNEXPLAINED_TAX_REFUND","OK")`, 'status');
  rows.push(padRow(['Schedule note', 'Closing cash is the cash-flow result; no balancing plug or new debt is modeled.']));
  rows.push(padRow(['Broken reference harness', brokenReference ? '=MissingSheet!B1' : 'Disabled for the valid fixture.', '', 'Intentional invalid candidate only.']));
  return rows;
}

function statementRows(title, subtitle, formulas) {
  return [
    padRow([title]),
    padRow([subtitle]),
    periodHeader(),
    periodLabels(),
    periodFractions(),
    ...formulas.map(([label, values, units]) => periodRow(label, values, units)),
  ];
}

function incomeRows() {
  return statementRows('Income statement (linked)', 'Formula rows link to shared schedules; expenses display with negative signs.', [
    ['Revenue', PERIODS.map((_, index) => `=Schedules!${periodColumn(index)}10`), 'USD millions'],
    ['Cash operating costs', PERIODS.map((_, index) => `=-Schedules!${periodColumn(index)}11`), 'USD millions'],
    ['Depreciation', PERIODS.map((_, index) => `=-Schedules!${periodColumn(index)}13`), 'USD millions'],
    ['EBIT', PERIODS.map((_, index) => `=${periodColumn(index)}6+${periodColumn(index)}7+${periodColumn(index)}8`), 'USD millions'],
    ['Interest expense', PERIODS.map((_, index) => `=-Schedules!${periodColumn(index)}18`), 'USD millions'],
    ['Pre-tax income', PERIODS.map((_, index) => `=${periodColumn(index)}9+${periodColumn(index)}10`), 'USD millions'],
    ['Taxes', PERIODS.map((_, index) => `=-Schedules!${periodColumn(index)}28`), 'USD millions'],
    ['Net income', PERIODS.map((_, index) => `=${periodColumn(index)}11+${periodColumn(index)}12`), 'USD millions'],
  ]);
}

function cashFlowRows() {
  return statementRows('Indirect cash flow statement (linked)', 'Cash is rolled from CFO, CFI and CFF; the balance sheet reads closing cash here.', [
    ['Net income', PERIODS.map((_, index) => `=Income!${periodColumn(index)}13`), 'USD millions'],
    ['Depreciation add-back', PERIODS.map((_, index) => `=Schedules!${periodColumn(index)}13`), 'USD millions'],
    ['Increase in operating NWC', PERIODS.map((_, index) => `=-Schedules!${periodColumn(index)}27`), 'USD millions'],
    ['Cash from operations', PERIODS.map((_, index) => `=${periodColumn(index)}6+${periodColumn(index)}7+${periodColumn(index)}8`), 'USD millions'],
    ['Cash capex', PERIODS.map((_, index) => `=-Schedules!${periodColumn(index)}12`), 'USD millions'],
    ['Cash from investing', PERIODS.map((_, index) => `=${periodColumn(index)}10`), 'USD millions'],
    ['Dividends', PERIODS.map((_, index) => `=-Schedules!${periodColumn(index)}29`), 'USD millions'],
    ['Debt issuance / (repayment)', PERIODS.map((_, index) => `=Schedules!${periodColumn(index)}17-Schedules!${periodColumn(index)}16`), 'USD millions'],
    ['Cash from financing', PERIODS.map((_, index) => `=${periodColumn(index)}12+${periodColumn(index)}13`), 'USD millions'],
    ['Net change in cash', PERIODS.map((_, index) => `=${periodColumn(index)}9+${periodColumn(index)}11+${periodColumn(index)}14`), 'USD millions'],
    ['Opening cash', PERIODS.map((_, index) => `=Schedules!${periodColumn(index)}32`), 'USD millions'],
    ['Closing cash', PERIODS.map((_, index) => `=${periodColumn(index)}16+${periodColumn(index)}15`), 'USD millions'],
  ]);
}

function balanceSheetRows() {
  return statementRows('Balance sheet (linked)', 'Closing cash is sourced from the indirect cash flow statement; equity is a retained-earnings roll-forward.', [
    ['Cash', PERIODS.map((_, index) => `=CashFlow!${periodColumn(index)}17`), 'USD millions'],
    ['Accounts receivable', PERIODS.map((_, index) => `=Schedules!${periodColumn(index)}20`), 'USD millions'],
    ['Inventory', PERIODS.map((_, index) => `=Schedules!${periodColumn(index)}22`), 'USD millions'],
    ['Net PP&E', PERIODS.map((_, index) => `=Schedules!${periodColumn(index)}15`), 'USD millions'],
    ['Total assets', PERIODS.map((_, index) => `=${periodColumn(index)}6+${periodColumn(index)}7+${periodColumn(index)}8+${periodColumn(index)}9`), 'USD millions'],
    ['Accounts payable', PERIODS.map((_, index) => `=Schedules!${periodColumn(index)}24`), 'USD millions'],
    ['Debt', PERIODS.map((_, index) => `=Schedules!${periodColumn(index)}17`), 'USD millions'],
    ['Equity', PERIODS.map((_, index) => `=Schedules!${periodColumn(index)}31`), 'USD millions'],
    ['Total liabilities + equity', PERIODS.map((_, index) => `=${periodColumn(index)}11+${periodColumn(index)}12+${periodColumn(index)}13`), 'USD millions'],
    ['Balance difference', PERIODS.map((_, index) => `=${periodColumn(index)}10-${periodColumn(index)}14`), 'USD millions'],
  ]);
}

function dcfRows() {
  const ufcf = PERIODS.map((_, index) => {
    const column = periodColumn(index);
    return `=Income!${column}9-IF(Income!${column}9>0,Income!${column}9*Inputs!B24,0)+Schedules!${column}13-Schedules!${column}12-Schedules!${column}27`;
  });
  return [
    padRow(['DCF and enterprise-to-equity bridge']),
    padRow(['Simple period-end discounting; terminal value is based on final fictional UFCF.']),
    periodHeader(),
    periodLabels(),
    periodFractions(),
    periodRow('Cumulative discount years', PERIODS.map((period) => period.cumulativeYears), 'years'),
    periodRow('UFCF', ufcf, 'USD millions'),
    periodRow('Discount factor', PERIODS.map((_, index) => `=Schedules!${periodColumn(index)}7`), 'factor'),
    periodRow('PV of UFCF', PERIODS.map((_, index) => `=${periodColumn(index)}7*${periodColumn(index)}8`), 'USD millions'),
    padRow([]),
    padRow(['Terminal UFCF', `=IF(Inputs!B34=${REQUIRED_INPUT_COUNT},L7*(1+Inputs!B30),"BLOCKED")`, 'USD millions', 'Simple perpetual growth basis; blocked if an editable input is missing']),
    padRow(['Terminal value', `=IF(Inputs!B34=${REQUIRED_INPUT_COUNT},B11/(Inputs!B29-Inputs!B30),"BLOCKED")`, 'USD millions', 'g < WACC required']),
    padRow(['PV of terminal value', `=IF(Inputs!B34=${REQUIRED_INPUT_COUNT},B12*L8,"BLOCKED")`, 'USD millions', 'Discounted at final period end']),
    padRow(['PV of explicit UFCF', `=IF(Inputs!B34=${REQUIRED_INPUT_COUNT},SUM(B9:L9),"BLOCKED")`, 'USD millions', 'All 11 forecast periods']),
    padRow(['Enterprise value', `=IF(Inputs!B34=${REQUIRED_INPUT_COUNT},B13+B14,"BLOCKED")`, 'USD millions', 'UFCF plus terminal value; required-input gate']),
    padRow(['Opening cash bridge', '=Inputs!B6', 'USD millions', 'Cash at measurement date']),
    padRow(['Opening debt bridge', '=Inputs!B11', 'USD millions', 'Debt at measurement date']),
    padRow(['Equity value', `=IF(Inputs!B34=${REQUIRED_INPUT_COUNT},B15+B16-B17,"BLOCKED")`, 'USD millions', 'Enterprise-to-equity bridge; required-input gate']),
    padRow(['Shares', '=Inputs!B31', 'millions', 'Fixed shares']),
    padRow(['Per-share value', `=IF(Inputs!B34=${REQUIRED_INPUT_COUNT},B18/B19,"BLOCKED")`, 'USD per share', 'Synthetic output; required-input gate']),
    padRow(['Terminal condition', '=IF(Inputs!B30<Inputs!B29,"PASS","FAIL")', 'status', 'Terminal growth must be below WACC']),
    padRow(['Funding condition', '=IF(Schedules!L35="OK","PASS","FUNDING_DEFICIT")', 'status', 'Stress cases remain visible']),
    padRow(['Required input condition', `=IF(Inputs!B34=${REQUIRED_INPUT_COUNT},"PASS","FAIL")`, 'status', 'All mandatory editable assumptions and revenue cells must be numeric']),
    padRow(['Valuation status', `=IF(Inputs!B34=${REQUIRED_INPUT_COUNT},IF(Inputs!B13=0,IF(Inputs!B30<Inputs!B29,"AVAILABLE","BLOCKED"),"BLOCKED"),"BLOCKED")`, 'status', 'Valuation outputs are blocked when required inputs or core gates fail']),
  ];
}

function checksRows() {
  const checks = [
    ['Balance difference', (column) => `=BalanceSheet!${column}15`, 'USD millions'],
    ['Balance check', (column) => `=IF(ABS(${column}5)<=${TOLERANCE},"PASS","FAIL")`, 'status'],
    ['Cash agreement difference', (column) => `=CashFlow!${column}17-BalanceSheet!${column}6`, 'USD millions'],
    ['Cash agreement check', (column) => `=IF(ABS(${column}7)<=${TOLERANCE},"PASS","FAIL")`, 'status'],
    ['Equity movement difference', (column) => `=Schedules!${column}31-(Schedules!${column}30+Income!${column}13-Schedules!${column}29)`, 'USD millions'],
    ['Equity movement check', (column) => `=IF(ABS(${column}9)<=${TOLERANCE},"PASS","FAIL")`, 'status'],
    ['PP&E movement difference', (column) => `=Schedules!${column}15-(Schedules!${column}14+Schedules!${column}12-Schedules!${column}13)`, 'USD millions'],
    ['PP&E movement check', (column) => `=IF(ABS(${column}11)<=${TOLERANCE},"PASS","FAIL")`, 'status'],
    ['Working-capital movement difference', (column) => `=Schedules!${column}27-(Schedules!${column}26-Schedules!${column}25)`, 'USD millions'],
    ['Working-capital movement check', (column) => `=IF(ABS(${column}13)<=${TOLERANCE},"PASS","FAIL")`, 'status'],
    ['Debt movement difference', (column) => `=Schedules!${column}17-Schedules!${column}16`, 'USD millions'],
    ['Debt movement check', (column) => `=IF(ABS(${column}15)<=${TOLERANCE},"PASS","FAIL")`, 'status'],
    ['Tax/refund check', (column) => `=IF(Schedules!${column}36="OK","PASS","FAIL")`, 'status'],
    ['Funding status', (column) => `=IF(Schedules!${column}35="OK","PASS","FUNDING_DEFICIT")`, 'status'],
    ['Terminal condition', () => '=IF(DCF!B21="PASS","PASS","FAIL")', 'status'],
    ['Overall mechanical check', (column) => `=IF(${column}6="PASS",IF(${column}8="PASS",IF(${column}10="PASS",IF(${column}12="PASS",IF(${column}14="PASS",IF(${column}16="PASS",IF(${column}17="PASS",IF(${column}19="PASS",IF(${column}21="PASS","PASS","FAIL"),"FAIL"),"FAIL"),"FAIL"),"FAIL"),"FAIL"),"FAIL"),"FAIL")`, 'status'],
    ['Required input check', () => `=IF(Inputs!B34=${REQUIRED_INPUT_COUNT},"PASS","FAIL")`, 'status'],
  ];
  return [
    padRow(['Financial checks']),
    padRow(['Checks expose identities and adverse-case flags; no check supplies a balancing plug.']),
    periodHeader(),
    periodLabels(),
    ...checks.map(([label, generator, units]) => periodRow(label, PERIODS.map((_, index) => generator(periodColumn(index))), units)),
    padRow([]),
    padRow(['Fixture classification', 'Fictional; no MSFT policy decision.']),
  ];
}

function reviewRows() {
  return [
    padRow(['AI Fund P4 — fictional linked three-statement DCF']),
    padRow(['Purpose', 'Synthetic mechanics proof; no MSFT policy decision.']),
    padRow(['Status', `=IF(Inputs!B34=${REQUIRED_INPUT_COUNT},IF(Inputs!B13=0,IF(Inputs!B30<Inputs!B29,"READY","BLOCKED"),"BLOCKED"),"BLOCKED")`]),
    padRow(['Information cut-off', '2026-04-30']),
    padRow(['Measurement / valuation date', '2026-03-31']),
    padRow(['Currency / units', 'USD millions; shares millions; per-share USD']),
    padRow(['Forecast shape', '3-month FY2026 stub + FY2027-FY2036']),
    padRow(['Calculation engine', `Mog SDK ${ENGINE_VERSION}`]),
    padRow(['Formula authority', 'Application-owned JavaScript generator; Excel is review/recalculation target.']),
    padRow(['Policy status', 'Visible provisional fictional policy; not an MSFT recommendation.']),
    padRow([]),
    padRow(['Workbook navigation', '=HYPERLINK("#\'Inputs\'!A1","Open Inputs")']),
    padRow(['Workbook navigation', '=HYPERLINK("#\'Schedules\'!A1","Open Schedules")']),
    padRow(['Workbook navigation', '=HYPERLINK("#\'DCF\'!A1","Open DCF")']),
    padRow(['Workbook navigation', '=HYPERLINK("#\'Checks\'!A1","Open Checks")']),
  ];
}

function decisionsRows() {
  return [
    padRow(['P4 fictional policy and method record']),
    padRow(['Decision ID', 'P4-FICTIONAL-MODEL-V1']),
    padRow(['Authority', 'System-reviewed provisional fixture policy']),
    padRow(['Method version', MODEL_VERSION]),
    padRow(['Interest', 'Opening-balance debt interest; no new debt']),
    padRow(['Taxes / UFCF tax', '25% of positive pretax income for book/cash tax; UFCF taxes only positive EBIT; no loss benefit']),
    padRow(['Untrusted excerpt', null]),
    padRow(['Internal decision link', 'Open decision record']),
    padRow(['Working capital', 'AR = 10% annualized revenue; inventory = 1/12 annualized cash costs; AP = 2/15 annualized cash costs']),
    padRow(['Terminal', 'Simple perpetual UFCF growth; period-end discounting; g must remain below WACC']),
  ];
}

async function writeSheet(wb, name, rows) {
  const sheet = await wb.getSheet(name);
  const width = 13;
  const normalized = rows.map((row) => padRow(row, width));
  await sheet.setRange(`A1:${columnName(width)}${normalized.length}`, normalized);
  return sheet;
}

async function applyFormatting(wb) {
  const inputs = await wb.getSheet('Inputs');
  await inputs.formats.setRange('A4:M5', { bold: true, backgroundColor: '#D9EAF7' });
  await inputs.formats.setRange('A15:M16', { bold: true, backgroundColor: '#D9EAF7' });
  await inputs.formats.setRange('A38:M38', { bold: true, backgroundColor: '#D9EAF7' });
  await inputs.formats.setRange('B6:B13', { numberFormat: AMOUNT_FORMAT });
  await inputs.formats.setRange('B17:B17', { numberFormat: AMOUNT_FORMAT });
  await inputs.formats.setRange('B18:B18', { numberFormat: '0.000' });
  await inputs.formats.setRange('B19:B30', { numberFormat: '0.0%' });
  await inputs.formats.setRange('B31:B31', { numberFormat: '#,##0.000000;(#,##0.000000);-' });
  await inputs.formats.setRange('B34:B34', { numberFormat: '0' });
  await inputs.formats.setRange('B35:L35', { numberFormat: AMOUNT_FORMAT });
  await inputs.comments.addNote('B17', { author: 'smrik-fund P4 fixture', text: 'Fictional annualized opening revenue. The stub uses the explicit 0.25-year fraction.' });
  await inputs.comments.addNote('B29', { author: 'smrik-fund P4 fixture', text: 'Fictional WACC used only for this mechanical P4 proof. Terminal growth must remain below WACC.' });

  for (const name of ['Schedules', 'Income', 'CashFlow', 'BalanceSheet', 'DCF', 'Checks']) {
    const sheet = await wb.getSheet(name);
    await sheet.formats.setRange('A3:M5', { bold: true, backgroundColor: '#D9EAF7' });
    await sheet.formats.setRange('B6:L36', { numberFormat: AMOUNT_FORMAT });
  }
  for (const name of ['Schedules', 'Income', 'CashFlow', 'BalanceSheet', 'DCF', 'Checks']) {
    const sheet = await wb.getSheet(name);
    await sheet.formats.setRange('A9:M9', { bold: true, backgroundColor: '#EAF2F8' });
  }
  const schedules = await wb.getSheet('Schedules');
  await schedules.formats.setRange('B5:L7', { numberFormat: '0.000000' });
  const dcf = await wb.getSheet('DCF');
  await dcf.formats.setRange('B7:L9', { numberFormat: AMOUNT_FORMAT });
  await dcf.formats.setRange('B20:B20', { numberFormat: CURRENCY_FORMAT });
  await dcf.formats.setRange('B19:B19', { numberFormat: '#,##0.000000;(#,##0.000000);-' });
  const checks = await wb.getSheet('Checks');
  await checks.formats.setRange('A1:M1', { bold: true, backgroundColor: '#D9EAF7' });
}

export async function buildFictionalWorkbook({ inputOverrides = {}, brokenReference = false } = {}) {
  validatePeriods(PERIODS);
  const inputs = mergeInputs(inputOverrides);
  validateFixtureInputs(inputs);
  const wb = await createWorkbook({ userTimezone: 'UTC' });
  await wb.sheets.rename('Sheet1', 'Review');
  for (const name of ['Inputs', 'Schedules', 'Income', 'CashFlow', 'BalanceSheet', 'DCF', 'Checks', 'Decisions']) await wb.sheets.add(name);
  await writeSheet(wb, 'Review', reviewRows());
  await writeSheet(wb, 'Inputs', inputRows(inputs));
  await writeSheet(wb, 'Schedules', scheduleRows(brokenReference));
  await writeSheet(wb, 'Income', incomeRows());
  await writeSheet(wb, 'CashFlow', cashFlowRows());
  await writeSheet(wb, 'BalanceSheet', balanceSheetRows());
  await writeSheet(wb, 'DCF', dcfRows());
  await writeSheet(wb, 'Checks', checksRows());
  await writeSheet(wb, 'Decisions', decisionsRows());

  const inputsSheet = await wb.getSheet('Inputs');
  await inputsSheet.setCell('B33', `=IF(B34=${REQUIRED_INPUT_COUNT},"PASS","FAIL")`);
  await inputsSheet.setCell('B34', requiredNumericCountFormula());
  const checksSheet = await wb.getSheet('Checks');
  for (let index = 0; index < PERIODS.length; index += 1) {
    await checksSheet.setCell(periodCell(index, 21), `=IF(Inputs!B34=${REQUIRED_INPUT_COUNT},"PASS","FAIL")`);
  }

  for (const [address, value] of Object.entries({ B39: '=fictional source excerpt', B40: '+untrusted source note', B41: '@reviewer text' })) {
    await inputsSheet.setCell(address, value, { literal: true });
  }
  const decisions = await wb.getSheet('Decisions');
  await decisions.setCell('B7', '=untrusted decision excerpt; literal text', { literal: true });
  await decisions.setCell('B8', '=HYPERLINK("#\'Decisions\'!A1","Open decision record")');
  const review = await wb.getSheet('Review');
  await review.setCell('B3', `=IF(Inputs!B34=${REQUIRED_INPUT_COUNT},IF(Inputs!B13=0,IF(Inputs!B30<Inputs!B29,"READY","BLOCKED"),"BLOCKED"),"BLOCKED")`);
  for (const [address, sheetName, label] of [['B12', 'Inputs', 'Open Inputs'], ['B13', 'Schedules', 'Open Schedules'], ['B14', 'DCF', 'Open DCF'], ['B15', 'Checks', 'Open Checks']]) {
    await review.setCell(address, `=HYPERLINK("#'${sheetName}'!A1","${label}")`);
  }
  await applyFormatting(wb);
  await wb.calculate();
  return { wb, inputs, periods: PERIODS, modelVersion: MODEL_VERSION, engineVersion: ENGINE_VERSION };
}

export async function readPeriodValues(wb, sheetName, row) {
  const sheet = await wb.getSheet(sheetName);
  const values = [];
  for (let index = 0; index < PERIODS.length; index += 1) values.push(await sheet.getValue(periodCell(index, row)));
  return values;
}

export async function readCriticalValues(wb, index = 0) {
  const column = periodColumn(index);
  const dcf = await wb.getSheet('DCF');
  const income = await wb.getSheet('Income');
  const cashFlow = await wb.getSheet('CashFlow');
  const balanceSheet = await wb.getSheet('BalanceSheet');
  const checks = await wb.getSheet('Checks');
  const read = async (sheet, address) => sheet.getValue(address);
  return {
    period: PERIODS[index].id,
    revenue: await read(income, `${column}${MODEL_ROWS.income.revenue}`),
    cashOperatingCosts: await read(income, `${column}${MODEL_ROWS.income.costs}`),
    depreciation: await read(income, `${column}${MODEL_ROWS.income.depreciation}`),
    ebit: await read(income, `${column}${MODEL_ROWS.income.ebit}`),
    interestExpense: await read(income, `${column}${MODEL_ROWS.income.interest}`),
    netIncome: await read(income, `${column}${MODEL_ROWS.income.netIncome}`),
    capex: await read(await wb.getSheet('Schedules'), `${column}${MODEL_ROWS.schedules.capex}`),
    closingCash: await read(cashFlow, `${column}${MODEL_ROWS.cashFlow.closingCash}`),
    closingNetPPE: await read(balanceSheet, `${column}${MODEL_ROWS.balanceSheet.netPPE}`),
    closingEquity: await read(balanceSheet, `${column}${MODEL_ROWS.balanceSheet.equity}`),
    assets: await read(balanceSheet, `${column}${MODEL_ROWS.balanceSheet.assets}`),
    balanceDifference: await read(balanceSheet, `${column}${MODEL_ROWS.balanceSheet.difference}`),
    closingAR: await read(await wb.getSheet('Schedules'), `${column}${MODEL_ROWS.schedules.closingAR}`),
    closingInventory: await read(await wb.getSheet('Schedules'), `${column}${MODEL_ROWS.schedules.closingInventory}`),
    closingAP: await read(await wb.getSheet('Schedules'), `${column}${MODEL_ROWS.schedules.closingAP}`),
    increaseNWC: await read(await wb.getSheet('Schedules'), `${column}${MODEL_ROWS.schedules.increaseNWC}`),
    cfo: await read(cashFlow, `${column}${MODEL_ROWS.cashFlow.cfo}`),
    dividends: await read(await wb.getSheet('Schedules'), `${column}${MODEL_ROWS.schedules.dividends}`),
    ufcf: await read(dcf, `${column}${MODEL_ROWS.dcf.ufcf}`),
    fundingStatus: await read(await wb.getSheet('Schedules'), `${column}${MODEL_ROWS.schedules.fundingStatus}`),
    taxStatus: await read(await wb.getSheet('Schedules'), `${column}${MODEL_ROWS.schedules.taxStatus}`),
    overallCheck: await read(checks, `${column}20`),
    requiredInputCheck: await read(checks, `${column}21`),
  };
}

export async function readValuation(wb) {
  const dcf = await wb.getSheet('DCF');
  return {
    terminalUfcf: await dcf.getValue('B11'),
    terminalValue: await dcf.getValue('B12'),
    pvTerminal: await dcf.getValue('B13'),
    pvExplicit: await dcf.getValue('B14'),
    enterpriseValue: await dcf.getValue('B15'),
    equityValue: await dcf.getValue('B18'),
    perShareValue: await dcf.getValue('B20'),
    terminalCheck: await dcf.getValue('B21'),
    fundingCondition: await dcf.getValue('B22'),
    requiredInputCondition: await dcf.getValue('B23'),
    valuationStatus: await dcf.getValue('B24'),
  };
}
