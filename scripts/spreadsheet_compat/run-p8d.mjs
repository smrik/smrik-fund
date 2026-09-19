import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { createWorkbook } from '@mog-sdk/sdk';
import { resolve } from 'node:path';
import {
  buildAssetWorkbook,
  inspectAssetWorkbook,
  P8D_DRIVER_ROWS,
  PERIODS,
  readSnapshot,
  TOLERANCE,
  writeSheet,
} from './asset_model.mjs';

const [, , command = 'authority', inputArg, runArg] = process.argv;
const inputPath = resolve(inputArg ?? 'data/build-guide-p8d/offline-r1/model-input.json');
const runDir = resolve(runArg ?? 'data/build-guide-p8d/offline-r1');
const clone = (value) => JSON.parse(JSON.stringify(value));
const sha256 = async (path) => createHash('sha256').update(await readFile(path)).digest('hex');
const settle = () => new Promise((done) => setTimeout(done, 150));
const near = (actual, expected, label) => assert.ok(Math.abs(Number(actual) - expected) <= TOLERANCE, `${label}: expected ${expected}, got ${actual}`);
const selectedP8DExpectations = (wrapper) => {
  const source = wrapper.p8d_packet?.facts?.source ?? {};
  const schedule = wrapper.p8d_packet?.facts?.intangible_schedule ?? {};
  const candidate = wrapper.candidate ?? {};
  const sourceNumber = (name) => {
    const value = source[name];
    assert.equal(typeof value, 'number', `P8D source ${name} must be numeric`);
    assert.ok(Number.isFinite(value), `P8D source ${name} must be finite`);
    return value;
  };
  const selectedNumber = (name) => {
    const value = candidate[name];
    assert.equal(typeof value, 'number', `P8D selected ${name} must be numeric`);
    assert.ok(Number.isFinite(value), `P8D selected ${name} must be finite`);
    return value;
  };
  const funding = sourceNumber('unfunded_commitment');
  const fraction = selectedNumber('unfunded_commitment_value_fraction');
  const commitmentDiscount = 1.043 ** (91 / 365);
  return {
    selectedYield: selectedNumber('cash_income_yield'),
    selectedMultiplier: selectedNumber('other_investment_value_multiplier'),
    selectedTailLife: selectedNumber('intangible_tail_life_years'),
    selectedGain: selectedNumber('unrealized_investment_gain'),
    expectedInvestmentCarrying: sourceNumber('equity_other_investments') + funding + selectedNumber('unrealized_investment_gain'),
    expectedInvestmentValue: sourceNumber('known_investment_value')
      + sourceNumber('other_investment_pool') * selectedNumber('other_investment_value_multiplier')
      + sourceNumber('financing_receivables')
      + funding * (fraction - 1) / commitmentDiscount,
    expectedTailClosing: schedule.tail * Math.max(selectedNumber('intangible_tail_life_years') - 6, 0) / selectedNumber('intangible_tail_life_years'),
    expectedRightsValue: funding * fraction,
    expectedCommitmentAdjustment: funding * (fraction - 1) / commitmentDiscount,
  };
};
const assertCashReference = (snapshot, label = 'P8D cash reference') => {
  const d = snapshot.otherBalances;
  assert.equal(d.actualOpeningCash.length, PERIODS.length, `${label}: opening cash must cover all periods`);
  assert.equal(d.actualClosingCash.length, PERIODS.length, `${label}: closing cash must cover all periods`);
  assert.equal(d.cashIncome.length, PERIODS.length, `${label}: income must cover all periods`);
  assert.equal(d.fundingStatus.length, PERIODS.length, `${label}: funding status must cover all periods`);
  for (let index = 0; index < PERIODS.length; index += 1) {
    const openingCash = Number(d.actualOpeningCash[index]);
    const closingCash = Number(d.actualClosingCash[index]);
    const expectedIncome = (Math.max(openingCash, 0) + Number(d.eligibleNoncashPool)) * Number(d.cashIncomeYield) * Number(d.periodDays[index]) / 365;
    near(d.cashIncome[index], expectedIncome, `${label} income period ${index}`);
    const expectedStatus = openingCash < 0 || closingCash < 0 ? 'UNFUNDED_CASH' : 'OK';
    assert.equal(d.fundingStatus[index], expectedStatus, `${label} funding status period ${index}`);
    if (index > 0) near(openingCash, d.actualClosingCash[index - 1], `${label} opening roll period ${index}`);
  }
};

function modelFromInput(wrapper) {
  const model = clone(wrapper.p8c);
  const candidate = wrapper.candidate;
  const forecast = wrapper.forecast;
  const decision = wrapper.decision ?? {};
  const review = wrapper.review ?? decision.review ?? {};
  model.other_balances_packet = wrapper.p8d_packet;
  model.other_balances_forecast = {
    schema_version: wrapper.p8d_packet.schema_version,
    case: wrapper.p8d_packet.case,
    information_cutoff: wrapper.p8d_packet.information_cutoff,
    measurement_date: wrapper.p8d_packet.measurement_date,
    method: { id: candidate.method_id, version: candidate.method_version },
    packet: wrapper.p8d_packet,
    inputs: candidate,
    candidate,
    forecast,
    review,
    decision,
    limitations: wrapper.p8d_packet.unavailable,
  };
  model.other_balances_decision = { ...decision, review, review_verdict: review.verdict ?? decision.review_verdict };
  return model;
}

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

async function authority() {
  const wrapper = JSON.parse(await readFile(inputPath, 'utf8'));
  const model = modelFromInput(wrapper);
  await mkdir(runDir, { recursive: true });
  const workbookPath = resolve(runDir, 'p8d-authority.xlsx');
  await saveWorkbook(model, workbookPath);
  const snapshot = await inspectAssetWorkbook(workbookPath);
  assert.equal(snapshot.otherBalancesGateStatus, 'PASS', 'P8D input gate');
  assert.equal(snapshot.allPeriodStatus, 'PASS', 'all-period mechanical gate');
  assert.equal(snapshot.otherBalances.coverage.every((value) => value === 'PASS'), true, 'P8D coverage');
  assertCashReference(snapshot, 'P8D actual cash reference');
  const expected = selectedP8DExpectations(wrapper);
  near(snapshot.otherBalances.cashIncomeYield, expected.selectedYield, 'P8D selected cash-income yield');
  const source = wrapper.p8d_packet.facts.source;
  const expectedFy27Income = (Math.max(snapshot.otherBalances.actualOpeningCash[1], 0)
    + Number(source.short_term_investments)
    + Number(source.identified_long_term_debt_investments)
    + Number(source.financing_receivables))
    * expected.selectedYield * Number(snapshot.otherBalances.periodDays[1]) / 365;
  near(snapshot.otherBalances.cashIncome[1], expectedFy27Income, 'P8D FY2027 cash income uses selected prior closing cash');
  near(snapshot.otherBalances.investmentClosing[0], expected.expectedInvestmentCarrying, 'P8D selected investment carrying');
  near(snapshot.otherBalances.intangibleClosing[10], expected.expectedTailClosing, 'P8D selected FY2036 intangible closing');
  near(snapshot.otherBalances.investmentValue[0], expected.expectedInvestmentValue, 'P8D selected investment value bridge');
  near(snapshot.otherBalances.commitmentRightsValue[0], expected.expectedRightsValue, 'P8D selected commitment rights value');
  near(snapshot.otherBalances.commitmentNetMeasurementAdjustment[0], expected.expectedCommitmentAdjustment, 'P8D selected commitment net measurement adjustment');
  near(snapshot.stub.cashFcf, snapshot.stub.cfo - snapshot.stub.cashPpePayments, 'P8D cash FCF is CFO less cash PP&E payments');
  const verification = {
    status: 'PASS', mode: 'Mog P8D other-balances authority', inputPath, workbookPath,
    publishedSha256: await sha256(workbookPath), snapshot,
    sourcePacketHash: model.other_balances_packet.source_table_sha256,
    selected: {
      otherInvestmentMultiplier: expected.selectedMultiplier,
      cashIncomeYield: expected.selectedYield,
      intangibleTailLifeYears: expected.selectedTailLife,
      unrealizedInvestmentGain: expected.selectedGain,
      unfundedCommitmentValueFraction: wrapper.candidate.unfunded_commitment_value_fraction,
      commitmentFunding: wrapper.p8d_packet.facts.source.unfunded_commitment,
    },
    formulaAuthority: 'Mog formulas; Python owns source arithmetic and policy inputs',
  };
  await writeFile(resolve(runDir, 'p8d-verification.json'), `${JSON.stringify(verification, null, 2)}\n`, 'utf8');
  console.log(JSON.stringify(verification, null, 2));
}

async function binding() {
  const wrapper = JSON.parse(await readFile(inputPath, 'utf8'));
  const model = modelFromInput(wrapper);
  const base = clone(model);
  const changed = clone(model);
  changed.other_balances_forecast.inputs.other_investment_value_multiplier = 1.5;
  changed.other_balances_forecast.candidate.other_investment_value_multiplier = 1.5;
  const { combinedDecision } = await import('./asset_model.mjs');
  const baseDecision = combinedDecision(base);
  const changedDecision = combinedDecision(changed);
  assert.equal(baseDecision.p8d_binding_valid, true, 'P8D base binding');
  assert.equal(changedDecision.p8d_binding_valid, false, 'P8D altered candidate invalidates attached decision binding');
  await writeFile(resolve(runDir, 'p8d-binding-verification.json'), `${JSON.stringify({ status: 'PASS', baseBindingValid: baseDecision.p8d_binding_valid, alteredCandidateBindingValid: changedDecision.p8d_binding_valid, alteredField: 'other_investment_value_multiplier' }, null, 2)}\n`, 'utf8');
  await authority();
}

async function adverse() {
  const wrapper = JSON.parse(await readFile(inputPath, 'utf8'));
  const model = modelFromInput(wrapper);
  const basePath = resolve(runDir, 'scenario-base.xlsx');
  await mkdir(runDir, { recursive: true });
  await saveWorkbook(model, basePath);
  const base = await inspectAssetWorkbook(basePath);
  const cases = [];
  const pass = async (name, mutate, verify) => {
    const candidate = clone(model);
    mutate(candidate);
    const path = resolve(runDir, `scenario-${name.replaceAll(/[^a-z0-9]+/gi, '-').toLowerCase()}.xlsx`);
    await saveWorkbook(candidate, path);
    const snapshot = await inspectAssetWorkbook(path, { allowSensitivityCenterDrift: true });
    verify(snapshot);
    cases.push({ name, status: 'PASS', kind: 'calculated-perturbation', snapshot: { stub: snapshot.stub, periodEnd: snapshot.periodEnd, otherBalances: snapshot.otherBalances } });
    return snapshot;
  };
  const fail = async (name, mutate) => {
    const candidate = clone(model);
    mutate(candidate);
    let error = null;
    try {
      await saveWorkbook(candidate, resolve(runDir, `adverse-${name.replaceAll(/[^a-z0-9]+/gi, '-').toLowerCase()}.xlsx`));
      await inspectAssetWorkbook(resolve(runDir, `adverse-${name.replaceAll(/[^a-z0-9]+/gi, '-').toLowerCase()}.xlsx`));
    } catch (caught) {
      error = caught;
    }
    assert.ok(error, `${name} unexpectedly passed`);
    cases.push({ name, status: 'PASS', message: String(error.message) });
  };
  await pass('yield-edit', (candidate) => {
    candidate.other_balances_forecast.inputs.cash_income_yield += 0.01;
    candidate.other_balances_forecast.candidate.cash_income_yield += 0.01;
  }, (snapshot) => {
    assert.notEqual(snapshot.otherBalances.cashIncome[0], base.otherBalances.cashIncome[0], 'yield edit must flow into Mog income');
    assert.notEqual(snapshot.stub.netIncome, base.stub.netIncome, 'yield edit must flow into Mog net income');
  });
  await pass('tail-six', (candidate) => {
    candidate.other_balances_forecast.inputs.intangible_tail_life_years = 6;
    candidate.other_balances_forecast.candidate.intangible_tail_life_years = 6;
  }, (snapshot) => near(snapshot.otherBalances.intangibleClosing[10], 0, 'six-year tail closes FY2036'));
  await pass('tail-fifteen', (candidate) => {
    candidate.other_balances_forecast.inputs.intangible_tail_life_years = 15;
    candidate.other_balances_forecast.candidate.intangible_tail_life_years = 15;
  }, (snapshot) => near(snapshot.otherBalances.intangibleClosing[10], 5923.8, 'fifteen-year tail FY2036 balance'));
  await pass('gain-fourteen', (candidate) => {
    candidate.other_balances_forecast.inputs.unrealized_investment_gain = 14;
    candidate.other_balances_forecast.candidate.unrealized_investment_gain = 14;
  }, (snapshot) => {
    assert.notEqual(snapshot.stub.netIncome, base.stub.netIncome, 'gain changes book net income');
    near(snapshot.stub.cfo, base.stub.cfo, 'gain leaves CFO unchanged');
    near(snapshot.stub.economicUfcf, base.stub.economicUfcf, 'gain leaves UFCF unchanged');
    assert.notEqual(snapshot.tax.deferredTaxLiabilityClosing[0], base.tax.deferredTaxLiabilityClosing[0], 'gain changes deferred tax liability');
  });
  await pass('goodwill-impairment', (candidate) => {
    candidate.other_balances_forecast.inputs.goodwill_impairment = 10;
    candidate.other_balances_forecast.candidate.goodwill_impairment = 10;
  }, (snapshot) => {
    assert.notEqual(snapshot.stub.netIncome, base.stub.netIncome, 'impairment changes net income');
    near(snapshot.stub.cfo, base.stub.cfo, 'impairment leaves CFO unchanged');
    near(snapshot.stub.economicUfcf, base.stub.economicUfcf, 'impairment leaves UFCF unchanged');
    near(snapshot.otherBalances.goodwillClosing[0], base.otherBalances.goodwillClosing[0] - 10, 'impairment reduces goodwill once');
  });
  await pass('legal-stress', (candidate) => {
    candidate.other_balances_forecast.inputs.legal_stress = 400;
    candidate.other_balances_forecast.candidate.legal_stress = 400;
  }, (snapshot) => {
    assert.notEqual(snapshot.stub.netIncome, base.stub.netIncome, 'legal stress changes net income');
    assert.notEqual(snapshot.stub.closingCash, base.stub.closingCash, 'legal stress changes cash');
    near(snapshot.tax.bookTaxExpense[0], base.tax.bookTaxExpense[0], 'legal stress has no automatic tax shield');
  });
  await pass('commitment-zero-value', (candidate) => {
    candidate.other_balances_forecast.inputs.unfunded_commitment_value_fraction = 0;
    candidate.other_balances_forecast.candidate.unfunded_commitment_value_fraction = 0;
  }, (snapshot) => {
    near(snapshot.otherBalances.commitmentRightsValue[0], 0, 'zero commitment rights value');
    const expectedAdjustment = -1200 / (1.043 ** (91 / 365));
    near(snapshot.otherBalances.commitmentNetMeasurementAdjustment[0], expectedAdjustment, 'dated commitment funding adjustment');
    near(snapshot.otherBalances.investmentValue[0], base.otherBalances.investmentValue[0] + expectedAdjustment, 'commitment adjustment appears once in bridge');
    near(snapshot.stub.cfo, base.stub.cfo, 'commitment valuation fraction leaves CFO unchanged');
  });
  await pass('multiplier-half', (candidate) => {
    candidate.other_balances_forecast.inputs.other_investment_value_multiplier = 0.5;
    candidate.other_balances_forecast.candidate.other_investment_value_multiplier = 0.5;
  }, (snapshot) => near(snapshot.otherBalances.investmentValue[0], base.otherBalances.investmentValue[0] - 20519 * 0.5, 'half multiplier bridge'));
  await pass('multiplier-zero', (candidate) => {
    candidate.other_balances_forecast.inputs.other_investment_value_multiplier = 0;
    candidate.other_balances_forecast.candidate.other_investment_value_multiplier = 0;
  }, (snapshot) => near(snapshot.otherBalances.investmentValue[0], base.otherBalances.investmentValue[0] - 20519, 'zero multiplier bridge'));
  await pass('multiplier-one-point-five', (candidate) => {
    candidate.other_balances_forecast.inputs.other_investment_value_multiplier = 1.5;
    candidate.other_balances_forecast.candidate.other_investment_value_multiplier = 1.5;
  }, (snapshot) => near(snapshot.otherBalances.investmentValue[0], base.otherBalances.investmentValue[0] + 20519 * 0.5, 'one-point-five multiplier bridge'));
  await pass('cash-flow-capex-stress', (candidate) => {
    const parameter = candidate.candidate.parameters.find((item) => item.name === 'cash_ppe_additions_rate');
    assert.ok(parameter, 'cash PP&E additions rate parameter is present');
    parameter.value = 0.8;
  }, (snapshot) => {
    assertCashReference(snapshot, 'P8D capex stress cash reference');
    near(snapshot.otherBalances.actualClosingCash[0], -7389.101845858007, 'capex stress closing cash');
    assert.equal(snapshot.otherBalances.fundingStatus[0], 'UNFUNDED_CASH', 'capex stress flags unfunded cash');
    assert.notEqual(snapshot.otherBalances.cashIncome[1], base.otherBalances.cashIncome[1], 'earlier cash-flow edit changes later cash income');
    near(snapshot.otherBalances.cashIncome[1], Number(snapshot.otherBalances.eligibleNoncashPool) * Number(snapshot.otherBalances.cashIncomeYield) * Number(snapshot.otherBalances.periodDays[1]) / 365, 'negative prior closing cash earns no cash yield');
  });
  await pass('negative-cash-unfunded', (candidate) => {
    candidate.other_balances_packet.facts.source.cash = -100000;
  }, (snapshot) => {
    assert.equal(snapshot.otherBalances.fundingStatus[0], 'UNFUNDED_CASH', 'negative cash remains visible as unfunded');
    near(snapshot.otherBalances.cashIncome[0], (46167 + 10346 + 2600) * wrapper.candidate.cash_income_yield * 91 / 365, 'negative cash excluded only from yield eligibility');
  });
  await fail('missing investment value', (candidate) => { candidate.other_balances_forecast.inputs.other_investment_value_multiplier = null; candidate.other_balances_forecast.candidate.other_investment_value_multiplier = null; });
  await fail('unsupported tail life', (candidate) => { candidate.other_balances_forecast.inputs.intangible_tail_life_years = 7; candidate.other_balances_forecast.candidate.intangible_tail_life_years = 7; });
  await fail('negative commitment funding', (candidate) => { candidate.other_balances_packet.facts.source.unfunded_commitment = -1; });
  await fail('missing coverage', (candidate) => { candidate.other_balances_forecast.forecast.coverage = null; });
  await fail('unsupported residual movement', (candidate) => { candidate.other_balances_packet.facts.source.other_long_term_assets += 3; });
  const result = { status: 'PASS', mode: 'P8D Mog perturbation and guard verification', inputPath, cases, base: { stub: base.stub, otherBalances: base.otherBalances, periodEnd: base.periodEnd } };
  await writeFile(resolve(runDir, 'p8d-adverse-verification.json'), `${JSON.stringify(result, null, 2)}\n`, 'utf8');
  console.log(JSON.stringify(result, null, 2));
}

const oraclePad = (values) => [...values, ...Array(Math.max(13 - values.length, 0)).fill(null)];
const oracleRow = (label, value, units = 'USD millions') => oraclePad([label, value, units]);

function oracleInputRows(config) {
  const rows = Array.from({ length: 12 }, () => oraclePad([]));
  rows[0] = oraclePad(['P8D parent fictional oracle inputs']);
  rows[1] = oraclePad(['One-period accounting case; all financial outputs below are Mog formulas driven by these inputs.']);
  rows[2] = oraclePad(['Input', 'Value', 'Units']);
  rows[5] = oracleRow('Opening cash', 100);
  rows[6] = oracleRow('Opening PP&E', 200);
  rows[7] = oracleRow('Opening goodwill', 50);
  rows[8] = oracleRow('Opening intangible', 40);
  rows[9] = oracleRow('Opening investment carrying', 60);
  rows[10] = oracleRow('Opening other operating asset', config.residual ? 13 : 10);
  rows[11] = oracleRow('Opening debt / other liability / equity', '100 / 20 / 340');
  return rows;
}

function oracleOtherRows(config) {
  return [
    oraclePad(['P8D parent other-balances formula schedule']),
    oraclePad(['Investment value is separate from carrying; gain, purchase, amortization and impairment are explicit movements.']),
    oracleRow('Investment opening carrying', '=Inputs!B10'),
    oracleRow('Investment purchase in CFI', `=${config.purchase}`),
    oracleRow('Cash investment income', '=6'),
    oracleRow('Noncash unrealized gain', `=${config.gain}`),
    oracleRow('Investment closing carrying', '=B3+B4+B6'),
    oracleRow('Investment measurement value', '=75'),
    oracleRow('Intangible opening carrying', '=Inputs!B9'),
    oracleRow('Intangible amortization', `=${config.amort}`),
    oracleRow('Intangible closing carrying', '=B9-B10'),
    oracleRow('Goodwill opening carrying', '=Inputs!B8'),
    oracleRow('Goodwill impairment', `=${config.impairment}`),
    oracleRow('Goodwill closing carrying', '=B12-B13'),
    oracleRow('Coverage', '="PASS"', 'status'),
  ];
}

function oracleIncomeRows() {
  return [
    oraclePad(['P8D parent income formula schedule']), oraclePad(['']), oraclePad(['Line', 'Value', 'Units']),
    oracleRow('Profit before PP&E depreciation / intangible amortization', '=80'),
    oracleRow('PP&E depreciation', '=-10'),
    oracleRow('Intangible amortization', '=-OtherBalances!B10'),
    oracleRow('EBIT', '=B4+B5+B6'),
    oracleRow('Cash investment income', '=OtherBalances!B5'),
    oracleRow('Noncash unrealized gain', '=OtherBalances!B6'),
    oracleRow('Goodwill impairment', '=-OtherBalances!B13'),
    oracleRow('Pre-tax income', '=SUM(B7:B10)'),
    oracleRow('Taxes', '=0'),
    oracleRow('Net income', '=B11+B12'),
  ];
}

function oracleCashRows() {
  return [
    oraclePad(['P8D parent cash-flow formula schedule']), oraclePad(['']), oraclePad(['Line', 'Value', 'Units']),
    oracleRow('Net income', '=Income!B13'),
    oracleRow('PP&E depreciation add-back', '=-Income!B5'),
    oracleRow('Intangible amortization add-back', '=OtherBalances!B10'),
    oracleRow('Noncash gain reversal', '=-OtherBalances!B6'),
    // Goodwill impairment is noncash and nondeductible. The income statement
    // expenses it once, so cash flow adds it back once.
    oracleRow('Cash from operations', '=SUM(B4:B7)+OtherBalances!B13'),
    oracleRow('Operating cash capex', '=-15'),
    oracleRow('Cash flow from investing', '=B9-OtherBalances!B4'),
    oracleRow('Net change in cash', '=B8+B10'),
    oracleRow('Opening cash', '=Inputs!B6'),
    oracleRow('Closing cash', '=B12+B11'),
  ];
}

function oracleBalanceRows() {
  return [
    oraclePad(['P8D parent balance-sheet formula schedule']), oraclePad(['']), oraclePad(['Line', 'Value', 'Units']),
    oracleRow('Cash', '=CashFlow!B13'),
    oracleRow('PP&E', '=Inputs!B7+15-10'),
    oracleRow('Intangibles', '=OtherBalances!B11'),
    oracleRow('Goodwill', '=OtherBalances!B14'),
    oracleRow('Investment', '=OtherBalances!B7'),
    oracleRow('Other operating asset', '=Inputs!B11'),
    oracleRow('Total assets', '=SUM(B4:B9)'),
    oracleRow('Debt', '=100'),
    oracleRow('Other operating liability', '=20'),
    oracleRow('Equity', '=340+Income!B13'),
    oracleRow('Liabilities + equity', '=SUM(B11:B13)'),
    oracleRow('Balance difference', '=B10-B14'),
  ];
}

function oracleDcfRows() {
  return [
    oraclePad(['P8D parent valuation formula schedule']), oraclePad(['']), oraclePad(['Line', 'Value', 'Units']),
    oracleRow('Operating EV', '=500'),
    oracleRow('Opening cash', '=Inputs!B6'),
    oracleRow('Investment measurement value', '=OtherBalances!B8'),
    oracleRow('Debt deduction', '=-100'),
    oracleRow('Common equity value', '=SUM(B4:B7)'),
    oracleRow('UFCF', '=Income!B7-Income!B5+OtherBalances!B10-15'),
  ];
}

async function buildOracleCase(config = {}) {
  const values = { purchase: 10, gain: 4, impairment: 0, amort: 8, residual: false, ...config };
  const wb = await createWorkbook({ userTimezone: 'UTC' });
  await wb.sheets.rename('Sheet1', 'Inputs');
  for (const name of ['OtherBalances', 'Income', 'CashFlow', 'BalanceSheet', 'DCF']) await wb.sheets.add(name);
  await writeSheet(wb, 'Inputs', oracleInputRows(values));
  await writeSheet(wb, 'OtherBalances', oracleOtherRows(values));
  await writeSheet(wb, 'Income', oracleIncomeRows());
  await writeSheet(wb, 'CashFlow', oracleCashRows());
  await writeSheet(wb, 'BalanceSheet', oracleBalanceRows());
  await writeSheet(wb, 'DCF', oracleDcfRows());
  await wb.calculate();
  return wb;
}

async function oracle() {
  await mkdir(runDir, { recursive: true });
  const base = await buildOracleCase();
  const read = async (sheet, address) => (await base.getSheet(sheet)).getValue(address);
  const baseValues = { netIncome: await read('Income', 'B13'), cfo: await read('CashFlow', 'B8'), cfi: await read('CashFlow', 'B10'), closingCash: await read('CashFlow', 'B13'), closingPpe: await read('BalanceSheet', 'B5'), closingIntangible: await read('BalanceSheet', 'B6'), closingGoodwill: await read('BalanceSheet', 'B7'), closingInvestment: await read('BalanceSheet', 'B8'), closingEquity: await read('BalanceSheet', 'B13'), totalAssets: await read('BalanceSheet', 'B10'), balanceDifference: await read('BalanceSheet', 'B15'), ufcf: await read('DCF', 'B9'), equityValue: await read('DCF', 'B8') };
  const expected = { netIncome: 72, cfo: 86, cfi: -25, closingCash: 161, closingPpe: 205, closingIntangible: 32, closingGoodwill: 50, closingInvestment: 74, closingEquity: 412, totalAssets: 532, balanceDifference: 0, ufcf: 65, equityValue: 575 };
  for (const [key, value] of Object.entries(expected)) near(baseValues[key], value, `parent base ${key}`);
  const scenarios = [];
  const scenario = async (name, config, checks) => {
    const wb = await buildOracleCase(config);
    const result = {};
    for (const [key, [sheet, address]] of Object.entries(checks)) result[key] = await (await wb.getSheet(sheet)).getValue(address);
    for (const [key, value] of Object.entries(result)) near(value, checks[key][2], `parent ${name} ${key}`);
    scenarios.push({ name, status: 'PASS', values: result });
    wb.dispose();
  };
  await scenario('purchase-zero', { purchase: 0 }, { closingCash: ['CashFlow', 'B13', 171], closingInvestment: ['BalanceSheet', 'B8', 64], ufcf: ['DCF', 'B9', 65], totalAssets: ['BalanceSheet', 'B10', 532] });
  await scenario('gain-fourteen', { gain: 14 }, { netIncome: ['Income', 'B13', 82], cfo: ['CashFlow', 'B8', 86], closingCash: ['CashFlow', 'B13', 161], closingInvestment: ['BalanceSheet', 'B8', 84], closingEquity: ['BalanceSheet', 'B13', 422], totalAssets: ['BalanceSheet', 'B10', 542], ufcf: ['DCF', 'B9', 65] });
  await scenario('goodwill-impairment', { impairment: 10 }, { netIncome: ['Income', 'B13', 62], cfo: ['CashFlow', 'B8', 86], closingCash: ['CashFlow', 'B13', 161], closingGoodwill: ['BalanceSheet', 'B7', 40], closingEquity: ['BalanceSheet', 'B13', 402], totalAssets: ['BalanceSheet', 'B10', 522], ufcf: ['DCF', 'B9', 65] });
  await scenario('intangible-amortization', { amort: 12 }, { netIncome: ['Income', 'B13', 68], cfo: ['CashFlow', 'B8', 86], closingCash: ['CashFlow', 'B13', 161], closingIntangible: ['BalanceSheet', 'B6', 28], closingEquity: ['BalanceSheet', 'B13', 408], totalAssets: ['BalanceSheet', 'B10', 528], ufcf: ['DCF', 'B9', 65] });
  const residual = await buildOracleCase({ residual: true });
  const residualDifference = await (await residual.getSheet('BalanceSheet')).getValue('B15');
  assert.equal(residualDifference, 3, 'unsupported residual movement remains an explicit difference');
  scenarios.push({ name: 'unsupported-residual', status: 'PASS', balanceDifference: residualDifference });
  base.dispose(); residual.dispose();
  const result = { status: 'PASS', mode: 'P8D_PARENT_ORACLE', base: baseValues, expected, scenarios, formulaAuthority: 'Mog formulas in the executable one-period parent oracle; assertions only compare calculated outputs.' };
  await writeFile(resolve(runDir, 'p8d-parent-oracle-verification.json'), `${JSON.stringify(result, null, 2)}\n`, 'utf8');
  console.log(JSON.stringify(result, null, 2));
}

if (command === 'authority') await authority();
else if (command === 'binding') await binding();
else if (command === 'adverse') await adverse();
else if (command === 'oracle') await oracle();
else throw new Error(`Unknown P8D command: ${command}`);
