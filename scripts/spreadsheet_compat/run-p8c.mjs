import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { createWorkbook } from '@mog-sdk/sdk';
import { resolve } from 'node:path';
import {
  buildAssetWorkbook,
  cashFlowRows,
  combinedDecision,
  equityRows,
  incomeRows,
  inspectAssetWorkbook,
  readSnapshot,
  P8C_DRIVER_ROWS,
  PERIODS,
  periodColumn,
  TOLERANCE,
  writeSheet,
} from './asset_model.mjs';

const [, , command = 'authority', inputArg, runArg] = process.argv;
const inputPath = resolve(inputArg ?? 'data/build-guide-p8c/offline-r2/model-input.json');
const runDir = resolve(runArg ?? 'data/build-guide-p8c/offline-r2');
const clone = (value) => JSON.parse(JSON.stringify(value));
const near = (actual, expected, label) => assert.ok(Math.abs(Number(actual) - expected) <= TOLERANCE, `${label}: expected ${expected}, got ${actual}`);
const sha256 = async (path) => createHash('sha256').update(await readFile(path)).digest('hex');
const settle = () => new Promise((resolvePromise) => setTimeout(resolvePromise, 150));

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

async function saveTamperedWorkbook(model, path, mutate) {
  const handle = await buildAssetWorkbook(model);
  try {
    await mutate(handle.wb);
    await handle.wb.calculate();
    await handle.wb.save(path);
    await settle();
  } finally {
    await settle();
    handle.wb.dispose();
  }
}

function bindingRegressionCases(model) {
  const cases = [];
  const run = (name, mutate, expected = false) => {
    const candidate = clone(model);
    mutate(candidate);
    const decision = combinedDecision(candidate);
    assert.equal(decision.p8c_binding_valid, expected, `${name} binding result`);
    cases.push({ name, status: 'PASS', p8cBindingValid: decision.p8c_binding_valid, combinedStatus: decision.status });
  };
  run('changed settlement price', (candidate) => { candidate.equity_forecast.forecast.policy.settlement_price += 1; });
  run('changed source quote', (candidate) => { candidate.equity_packet.facts.market_quote.value += 1; });
  run('missing binding', (candidate) => { delete candidate.equity_decision.binding; delete candidate.p8c_decision.binding; });
  return cases;
}

async function authority() {
  const model = JSON.parse(await readFile(inputPath, 'utf8'));
  assert.ok(model.equity_forecast, 'P8C equity forecast is required');
  await mkdir(runDir, { recursive: true });
  const workbookPath = resolve(runDir, 'equity-authority.xlsx');
  await saveWorkbook(model, workbookPath);
  const snapshot = await inspectAssetWorkbook(workbookPath);
  assert.equal(snapshot.equityGateStatus, 'PASS', 'P8C equity input gate');
  assert.equal(snapshot.allPeriodStatus, 'PASS', 'all-period mechanical gate');
  const decision = combinedDecision(model);
  const verification = {
    status: 'PASS', mode: 'Mog P8C equity authority', inputPath, workbookPath,
    publishedSha256: await sha256(workbookPath), p8cBindingValid: decision.p8c_binding_valid,
    combinedDecisionStatus: decision.status, snapshot,
    providerHashes: { candidateHash: model.equity_decision?.candidate_hash, reviewHash: model.equity_decision?.review_hash, contextHash: model.equity_decision?.context_hash, sourcePacketHash: model.equity_decision?.source_packet_hash },
    formulaAuthority: 'Mog formulas; Python owns source arithmetic and policy inputs',
  };
  await writeFile(resolve(runDir, 'equity-verification.json'), `${JSON.stringify(verification, null, 2)}\n`, 'utf8');
  console.log(JSON.stringify(verification, null, 2));
}

async function binding() {
  const model = JSON.parse(await readFile(inputPath, 'utf8'));
  assert.ok(model.equity_forecast, 'P8C equity forecast is required');
  const decision = combinedDecision(model);
  assert.equal(decision.p8c_binding_valid, true, 'P8C decision binding');
  const regressions = bindingRegressionCases(model);
  await authority();
  const verification = JSON.parse(await readFile(resolve(runDir, 'equity-verification.json'), 'utf8'));
  verification.mode = 'Mog P8C export-binding proof';
  verification.regressions = regressions;
  await writeFile(resolve(runDir, 'equity-binding-verification.json'), `${JSON.stringify(verification, null, 2)}\n`, 'utf8');
  console.log(JSON.stringify(verification, null, 2));
}

async function integration() {
  const model = JSON.parse(await readFile(inputPath, 'utf8'));
  assert.ok(model.equity_forecast, 'P8C equity forecast is required');
  await mkdir(runDir, { recursive: true });
  const handle = await buildAssetWorkbook(model);
  const { wb } = handle;
  const inputs = await wb.getSheet('Inputs');
  const equity = await wb.getSheet('Equity');
  const read = async (sheet, address) => sheet.getValue(address);
  const periodValues = async (row) => Promise.all(PERIODS.map((_, index) => read(inputs, `${periodColumn(index)}${row}`)));
  const saveAndInspect = async (name) => {
    const path = resolve(runDir, name);
    await wb.save(path);
    await settle();
    const inspected = await inspectAssetWorkbook(path);
    return { path, inspected };
  };
  const checks = [];
  try {
    await wb.calculate();
    const base = await readSnapshot(wb);
    assert.equal(base.equityGateStatus, 'PASS', 'R3 base gate');
    assert.equal(base.existingAwardClaimBridgeCheck, 'PASS', 'R6 claim bridge check');
    assert.equal(base.pointShareDenominatorCheck, 'PASS', 'R6 point-share denominator check');
    assert.equal(base.partialPerShareArithmeticCheck, 'PASS', 'R6 partial per-share arithmetic check');
    near(base.existingAwardClaim, 82 * 370.17, 'R6 existing-award claim');
    near(base.equityValue, base.equityValueBeforeExistingClaim - base.existingAwardClaim, 'R6 displayed post-claim equity');
    near(base.pointShareDenominator, 7429, 'R6 measurement-date point shares');
    near(base.partialPerShareValue, Number(base.equityValue) / 7429, 'R6 partial value per point share');
    assert.deepEqual(base.equity.serviceDays.slice(0, 4), [91, 365, 366, 274], 'R3 three-year calendar');
    assert.equal(Number(base.equity.totalServiceDays), 1096, 'R3 three-year denominator');
    const baseWeightedShares = Number(base.equity.basicWeightedShares[0]);
    const baseEbit = Number(base.stub.ebit);
    const baseApicBasis = Number(base.equity.programApicBasis[1]);
    const baseMeasurementBasis = Number(await read(inputs, `B${P8C_DRIVER_ROWS.openingApic}`)) / Number(await read(inputs, `B${P8C_DRIVER_ROWS.openingPointShares}`)) * Number(base.equity.programUnits[1]);
    assert.notEqual(baseApicBasis, baseMeasurementBasis, 'R3 FY27 rolling APIC basis');
    assert.equal(Number(await read(equity, 'C18')), baseApicBasis, 'R3 Equity C18 basis');
    checks.push('base three-year calendar, full runoff and FY27 rolling APIC basis');
    await saveAndInspect('p8c-integration-base.xlsx');
    checks.push('base existing-award claim deducted once and partial value per 7429m point shares');

    const adverseClaim = clone(model);
    adverseClaim.equity_forecast.forecast.policy.existing_award_units += 1;
    const adverseClaimHandle = await buildAssetWorkbook(adverseClaim);
    try {
      await adverseClaimHandle.wb.calculate();
      const oneMoreAward = await readSnapshot(adverseClaimHandle.wb);
      assert.equal(oneMoreAward.equityGateStatus, 'PASS', 'R6 one-more-award gate');
      near(oneMoreAward.existingAwardClaim - base.existingAwardClaim, 370.17, 'R6 one-more-award claim movement');
      near(oneMoreAward.equityValue - base.equityValue, -370.17, 'R6 one-more-award equity movement');
      near(oneMoreAward.enterpriseValue, base.enterpriseValue, 'R6 EV invariant under claim movement');
      near(oneMoreAward.pointShareDenominator, base.pointShareDenominator, 'R6 point-share invariant under claim movement');
      near(oneMoreAward.partialPerShareValue - base.partialPerShareValue, -370.17 / 7429, 'R6 one-more-award per-share movement');
      near(oneMoreAward.stub.ebit, base.stub.ebit, 'R6 EBIT invariant under claim movement');
      near(oneMoreAward.stub.netIncome, base.stub.netIncome, 'R6 net income invariant under claim movement');
      near(oneMoreAward.stub.cfo, base.stub.cfo, 'R6 CFO invariant under claim movement');
      near(oneMoreAward.stub.economicUfcf, base.stub.economicUfcf, 'R6 UFCF invariant under claim movement');
      checks.push('one additional existing unit changed claim/equity/per-share by the expected 370.17 movement while EV/statements/UFCF/denominator stayed fixed');
    } finally {
      adverseClaimHandle.wb.dispose();
    }

    await inputs.setCell(`B${P8C_DRIVER_ROWS.existingServiceYears}`, 2);
    await wb.calculate();
    const two = await readSnapshot(wb);
    assert.equal(two.equityGateStatus, 'PASS', 'R3 two-year gate');
    assert.deepEqual(two.equity.serviceDays.slice(0, 4), [91, 365, 275, 0], 'R3 two-year calendar');
    assert.equal(Number(two.equity.totalServiceDays), 731, 'R3 two-year denominator');
    assert.notEqual(Number(two.equity.existingServiceCost[2]), Number(base.equity.existingServiceCost[2]), 'R3 two-year service cost changed');
    assert.notEqual(Number(two.equity.basicWeightedShares[0]), baseWeightedShares, 'R3 two-year EPS denominator changed');
    await saveAndInspect('p8c-integration-years2.xlsx');
    checks.push('years 3 to 2 changed service cost and weighted shares');

    await inputs.setCell(`B${P8C_DRIVER_ROWS.existingServiceYears}`, 4);
    await wb.calculate();
    const four = await readSnapshot(wb);
    assert.equal(four.equityGateStatus, 'PASS', 'R3 four-year gate');
    assert.deepEqual(four.equity.serviceDays.slice(0, 6), [91, 365, 366, 365, 274, 0], 'R3 four-year calendar');
    assert.equal(Number(four.equity.totalServiceDays), 1461, 'R3 four-year denominator');
    assert.notEqual(Number(four.equity.existingServiceCost[3]), Number(base.equity.existingServiceCost[3]), 'R3 four-year service cost changed');
    assert.notEqual(Number(four.equity.basicWeightedShares[0]), baseWeightedShares, 'R3 four-year EPS denominator changed');
    await saveAndInspect('p8c-integration-years4.xlsx');
    checks.push('years 2 to 4 changed service cost and weighted shares');

    await inputs.setCell(`B${P8C_DRIVER_ROWS.existingServiceYears}`, 3);
    await wb.calculate();
    const restored = await readSnapshot(wb);
    assert.equal(restored.equityGateStatus, 'PASS', 'R3 restored gate');
    assert.deepEqual(restored.equity.serviceDays.slice(0, 4), base.equity.serviceDays.slice(0, 4), 'R3 calendar restoration');
    assert.equal(Number(restored.stub.ebit), baseEbit, 'R3 restoration EBIT');
    await saveAndInspect('p8c-integration-restored.xlsx');
    checks.push('restored three-year base');

    await inputs.setCell(`B${P8C_DRIVER_ROWS.settlementPrice}`, 1);
    await wb.calculate();
    assert.equal(await read(inputs, `B${P8C_DRIVER_ROWS.gate}`), 'FAIL', 'R3 guarded price adverse');
    checks.push('below-basis settlement price blocked');
    const result = { status: 'PASS', mode: 'P8C R6 actual Mog integration proof', inputPath, checks, baseCalendar: base.equity.serviceDays, baseTotalServiceDays: base.equity.totalServiceDays, baseEnterpriseValue: base.enterpriseValue, baseEquityBeforeExistingClaim: base.equityValueBeforeExistingClaim, baseExistingAwardClaim: base.existingAwardClaim, basePartialEquity: base.equityValue, basePointShareDenominator: base.pointShareDenominator, basePartialPerShare: base.partialPerShareValue, years2Calendar: two.equity.serviceDays, years4Calendar: four.equity.serviceDays, rollingApicBasis: baseApicBasis, measurementBasis: baseMeasurementBasis };
    await writeFile(resolve(runDir, 'p8c-integration-verification.json'), `${JSON.stringify(result, null, 2)}\n`, 'utf8');
    console.log(JSON.stringify(result, null, 2));
  } finally {
    wb.dispose();
  }
}

const parentPad = (values) => [...values, ...Array(Math.max(13 - values.length, 0)).fill(null)];
const parentPeriodRow = (label, values, units = 'USD millions') => parentPad([label, ...values, units]);
const parentPeriods = PERIODS.map((period, index) => ({ ...period, days: index === 0 ? 365 : 365 }));

function parentGateFormula() {
  const e = P8C_DRIVER_ROWS;
  return `=IFERROR(IF(AND(COUNT(B${e.sbcRatio}:B${e.dividendQuartersAnnual})=13,COUNT(B${e.embeddedSbcRatio}:B${e.repurchaseTiming})=4,COUNT(B${e.totalServiceDays}:B${e.openingTotalEquity})=7,COUNT(B${e.periodDays}:L${e.periodDays})=11,COUNT(B${e.serviceDays}:L${e.serviceDays})=11,B${e.sbcRatio}>=0,B${e.sbcRatio}<=1,B${e.embeddedSbcRatio}>=0,B${e.embeddedSbcRatio}<=1,B${e.existingAwardUnits}>=0,B${e.existingUnrecognizedCost}>=0,B${e.existingServiceYears}=3,B${e.existingClaimPrice}>0,B${e.settlementPrice}>0,B${e.withholdingRate}>=0,B${e.withholdingRate}<=1,B${e.cashIssuanceRatio}>=0,B${e.repurchaseRatio}>=0,B${e.repurchaseAuthorization}=44000,B${e.dividendPerShareQuarter}>=0,B${e.dividendQuartersStub}=1,B${e.dividendQuartersAnnual}=4,B${e.openingApic}>=0,OR(B${e.repurchaseRatio}=0,B${e.settlementPrice}>=B${e.openingApic}/B${e.openingPointShares}-${TOLERANCE}),B${e.deliveryTiming}>=0,B${e.deliveryTiming}<=1,B${e.issuanceTiming}>=0,B${e.issuanceTiming}<=1,B${e.repurchaseTiming}>=0,B${e.repurchaseTiming}<=1,B${e.totalServiceDays}>0,B${e.openingPointShares}>0,MIN(B${e.periodDays}:L${e.periodDays})>0,MIN(B${e.serviceDays}:L${e.serviceDays})>=0,SUM(B${e.serviceDays}:L${e.serviceDays})<=B${e.totalServiceDays}+${TOLERANCE},COUNT(Equity!B6:L38)=363,MIN(Equity!B8:L8)>=-${TOLERANCE},MIN(Equity!B25:L26)>0,MIN(Equity!B27:L27)>=0,MIN(Equity!B34:L34)>=-${TOLERANCE},SUM(Equity!B18:L18)<=B${e.openingApic}+${TOLERANCE},MIN(Equity!B38:L38)>=-${TOLERANCE}),"PASS","FAIL"),"FAIL")`;
}

function parentModel(config) {
  const periodMeta = parentPeriods.map((period) => ({ id: period.id, days: period.days }));
  return {
    tax_forecast: { method: 'parent-fixture' },
    equity_forecast: {
      inputs: {
        embedded_sbc_ratio: config.sbcExpense / config.revenue,
        common_apic: config.openingApic,
        retained_earnings: config.openingRetainedEarnings,
        aoci: config.openingAoci,
        total_equity: config.openingTotalEquity,
        point_shares: config.openingPointShares,
        opening_dividend_payable: config.openingDividendPayable,
      },
      forecast: {
        policy: {
          sbc_ratio: config.sbcExpense / config.revenue,
          existing_award_units: config.existingAwardUnits,
          existing_unrecognized_cost: config.existingUnrecognizedCost,
          existing_service_years: 3,
          existing_claim_price: config.claimPrice,
          settlement_price: config.settlementPrice,
          withholding_rate: config.withholdingRate,
          cash_issuance_ratio: config.cashIssuanceRatio,
          repurchase_ratio: config.repurchaseRatio,
          repurchase_authorization: 44000,
          dividend_per_share_quarter: config.dividendPerShare,
          dividend_quarters_stub: 1,
          dividend_quarters_annual: 4,
          embedded_sbc_ratio: config.sbcExpense / config.revenue,
          delivery_timing: config.deliveryTiming,
          issuance_timing: config.issuanceTiming,
          repurchase_timing: config.repurchaseTiming,
        },
        period_meta: periodMeta,
        sbc: { service_days: config.serviceDays, total_service_days: config.totalServiceDays },
      },
    },
  };
}

function parentInputRows(config) {
  const rows = Array.from({ length: 231 }, () => Array(13).fill(null));
  rows[0] = parentPad(['P8C parent fictional oracle inputs']);
  rows[1] = parentPad(['All values are fictional USD millions except shares and prices; formula outputs are built by the shared Equity schedule.']);
  rows[2] = parentPad(['Input', 'Value', 'Units']);
  rows[5] = parentPad(['Opening cash', config.openingCash, 'USD millions']);
  rows[10] = parentPad(['Opening PP&E', config.openingPpe, 'USD millions']);
  rows[20] = parentPad(['Opening debt', config.openingDebt, 'USD millions']);
  rows[34] = parentPad(['Tax rate', config.taxRate, 'decimal fraction']);
  rows[42] = parentPad(['Fictional revenue source', config.revenue, 'USD millions']);
  rows[105] = parentPad(['Book tax rate', config.taxRate, 'decimal fraction']);
  rows[106] = parentPad(['Operating tax rate', config.taxRate, 'decimal fraction']);
  const e = P8C_DRIVER_ROWS;
  const scalar = new Map([
    [e.sbcRatio, config.sbcExpense / config.revenue],
    [e.existingAwardUnits, config.existingAwardUnits],
    [e.existingUnrecognizedCost, config.existingUnrecognizedCost],
    [e.existingServiceYears, 3],
    [e.existingClaimPrice, config.claimPrice],
    [e.settlementPrice, config.settlementPrice],
    [e.withholdingRate, config.withholdingRate],
    [e.cashIssuanceRatio, config.cashIssuanceRatio],
    [e.repurchaseRatio, config.repurchaseRatio],
    [e.repurchaseAuthorization, 44000],
    [e.dividendPerShareQuarter, config.dividendPerShare],
    [e.dividendQuartersStub, 1],
    [e.dividendQuartersAnnual, 4],
    [e.gate, parentGateFormula()],
    [e.embeddedSbcRatio, config.sbcExpense / config.revenue],
    [e.deliveryTiming, config.deliveryTiming],
    [e.issuanceTiming, config.issuanceTiming],
    [e.repurchaseTiming, config.repurchaseTiming],
    [e.totalServiceDays, config.totalServiceDays],
    [e.openingDividendPayable, config.openingDividendPayable],
    [e.openingPointShares, config.openingPointShares],
    [e.openingApic, config.openingApic],
    [e.openingRetainedEarnings, config.openingRetainedEarnings],
    [e.openingAoci, config.openingAoci],
    [e.openingTotalEquity, config.openingTotalEquity],
  ]);
  for (const [row, value] of scalar) rows[row - 1][1] = value;
  rows[e.periodDays - 1] = parentPeriodRow('P8C period days', config.periodDays, 'calendar days');
  rows[e.serviceDays - 1] = parentPeriodRow('P8C service-day overlap', config.serviceDays, 'calendar days');
  rows[e.periodDays - 1][0] = 'P8C period days';
  rows[e.serviceDays - 1][0] = 'P8C service-day overlap';
  return rows;
}

function parentScheduleRows(config) {
  const rows = Array.from({ length: 34 }, () => Array(13).fill(null));
  rows[0] = parentPad(['Parent fixture shared schedules']);
  rows[1] = parentPad(['Asset, cash and NWC values are visible source inputs for the shared P8C formulas.']);
  rows[2] = parentPeriodRow('Period ID', PERIODS.map((period) => period.id), '');
  rows[3] = parentPeriodRow('Period label', PERIODS.map((period) => period.label), '');
  rows[4] = parentPeriodRow('Year fraction', PERIODS.map((period) => period.yearFraction), 'years');
  rows[5] = parentPeriodRow('Cumulative forecast years', PERIODS.map((period) => period.cumulativeYears), 'years');
  rows[6] = parentPeriodRow('Discount factor', PERIODS.map(() => '=1'), 'factor');
  rows[8] = parentPad(['Asset and cross-statement schedules']);
  const zeros = Array(PERIODS.length).fill('=0');
  const active = (value) => [value, ...zeros.slice(1)];
  rows[9] = parentPeriodRow('Revenue', active('=Inputs!$B$43'));
  rows[10] = parentPeriodRow('Operating-cost proxy excluding PP&E depreciation', active(`=${config.sbcExpense}`));
  rows[11] = parentPeriodRow('Cash PP&E additions / payments', active('=15'));
  rows[12] = parentPeriodRow('Noncash PP&E additions in AP subset', zeros);
  rows[13] = parentPeriodRow('Recognized PP&E additions', PERIODS.map((_, i) => `=${periodColumn(i)}12+${periodColumn(i)}13+${periodColumn(i)}32`));
  rows[14] = parentPeriodRow('Original opening-pool depreciation', active('=10'));
  rows[15] = parentPeriodRow('Forecast-cohort depreciation', zeros);
  rows[16] = parentPeriodRow('Total depreciation', PERIODS.map((_, i) => `=${periodColumn(i)}15+${periodColumn(i)}16`));
  rows[17] = parentPeriodRow('Opening depreciable net PP&E', active('=Inputs!$B$11'));
  rows[18] = parentPeriodRow('Closing depreciable net PP&E', PERIODS.map((_, i) => `=${periodColumn(i)}18+${periodColumn(i)}12-${periodColumn(i)}17`));
  rows[19] = parentPeriodRow('Opening land', zeros);
  rows[20] = parentPeriodRow('Closing land', zeros);
  rows[21] = parentPeriodRow('Opening net PP&E', PERIODS.map((_, i) => i === 0 ? '=Inputs!$B$11' : `=${periodColumn(i - 1)}23`));
  rows[22] = parentPeriodRow('Closing net PP&E', PERIODS.map((_, i) => `=${periodColumn(i)}18+${periodColumn(i)}20`));
  rows[23] = parentPeriodRow('Opening PP&E payable subset', zeros);
  rows[24] = parentPeriodRow('Closing PP&E payable subset', PERIODS.map((_, i) => `=${periodColumn(i)}24+${periodColumn(i)}13`));
  rows[25] = parentPeriodRow('Increase in operating NWC', zeros);
  rows[26] = parentPeriodRow('Opening equity', PERIODS.map((_, i) => i === 0 ? '=Inputs!$B$231' : `=${periodColumn(i - 1)}28`));
  rows[27] = parentPeriodRow('Closing equity', PERIODS.map((_, i) => `=Equity!${periodColumn(i)}37`));
  rows[28] = parentPeriodRow('Opening cash', PERIODS.map((_, i) => i === 0 ? '=Inputs!$B$6' : `=${periodColumn(i - 1)}31`));
  rows[29] = parentPeriodRow('Net change in cash', PERIODS.map((_, i) => `=CashFlow!${periodColumn(i)}16`));
  rows[30] = parentPeriodRow('Closing cash', PERIODS.map((_, i) => `=CashFlow!${periodColumn(i)}18`));
  rows[31] = parentPeriodRow('Lease additions modeled', zeros);
  rows[32] = parentPeriodRow('Funding status', PERIODS.map(() => '="OK"'), 'status');
  rows[33] = parentPeriodRow('Tax status', PERIODS.map(() => '="PASS"'), 'status');
  return rows;
}

function parentTaxRows(config) {
  const rows = Array.from({ length: 30 }, () => Array(13).fill(null));
  rows[0] = parentPad(['Parent fixture tax schedule']);
  rows[1] = parentPad(['Taxes paid equal expense; no deferred or financing tax effects are modeled in this fictional fixture.']);
  rows[2] = parentPeriodRow('Period ID', PERIODS.map((period) => period.id), '');
  rows[3] = parentPeriodRow('Period label', PERIODS.map((period) => period.label), '');
  rows[4] = parentPeriodRow('Year fraction', PERIODS.map((period) => period.yearFraction), 'years');
  const zeros = Array(PERIODS.length).fill('=0');
  const row = (number, label, values, units = 'USD millions') => { rows[number - 1] = parentPeriodRow(label, values, units); };
  row(6, 'EBIT', PERIODS.map((_, i) => `=Income!${periodColumn(i)}11`));
  row(7, 'Interest expense', zeros);
  row(8, 'Pre-tax income', PERIODS.map((_, i) => `=${periodColumn(i)}6+${periodColumn(i)}7`));
  row(9, 'Positive pre-tax income', PERIODS.map((_, i) => `=MAX(0,${periodColumn(i)}8)`));
  row(10, 'Book tax rate', PERIODS.map(() => '=Inputs!$B$106'), 'decimal fraction');
  row(11, 'Book tax expense', PERIODS.map((_, i) => `=${periodColumn(i)}9*${periodColumn(i)}10`));
  row(12, 'Deferred tax expense share', zeros, 'dimensionless');
  row(13, 'Deferred tax expense', zeros);
  row(14, 'Current tax expense', PERIODS.map((_, i) => `=${periodColumn(i)}11-${periodColumn(i)}13`));
  row(15, 'Current tax payable opening', zeros);
  row(16, 'Current tax payable closing', zeros);
  row(17, 'Current tax payment', PERIODS.map((_, i) => `=${periodColumn(i)}15+${periodColumn(i)}14-${periodColumn(i)}16`));
  row(18, 'Long-term tax liability opening', zeros);
  row(19, 'Long-term tax settlement', zeros);
  row(20, 'Long-term tax liability closing', zeros);
  row(21, 'Deferred tax liability opening', zeros);
  row(22, 'Deferred tax liability closing', zeros);
  row(23, 'Deferred tax add-back', zeros);
  row(24, 'Current tax payable movement / CFO effect', zeros);
  row(25, 'Long-term tax settlement / CFO effect', zeros);
  row(26, 'Total tax CFO adjustment', zeros);
  row(27, 'Modeled company cash taxes', PERIODS.map((_, i) => `=${periodColumn(i)}17+${periodColumn(i)}19`));
  row(28, 'Operating tax rate', PERIODS.map(() => '=Inputs!$B$107'), 'decimal fraction');
  row(29, 'Normalized operating tax on positive EBIT', PERIODS.map((_, i) => `=MAX(0,${periodColumn(i)}6)*${periodColumn(i)}28`));
  row(30, 'Tax period check', PERIODS.map(() => '="PASS"'), 'status');
  return rows;
}

function parentBalanceRows() {
  return [
    parentPad(['Parent fixture balance sheet']),
    parentPad(['Cash and PP&E are linked to the shared cash flow and schedule; debt and equity are explicit fixture balances.']),
    parentPeriodRow('Period ID', PERIODS.map((period) => period.id), ''),
    parentPeriodRow('Period label', PERIODS.map((period) => period.label), ''),
    parentPeriodRow('Year fraction', PERIODS.map((period) => period.yearFraction), 'years'),
    parentPeriodRow('Cash and cash equivalents', PERIODS.map((_, i) => `=CashFlow!${periodColumn(i)}18`)),
    parentPeriodRow('Closing PP&E', PERIODS.map((_, i) => `=Inputs!$B$11+Schedules!${periodColumn(i)}12-Schedules!${periodColumn(i)}17`)),
    parentPeriodRow('Total assets', PERIODS.map((_, i) => `=${periodColumn(i)}6+${periodColumn(i)}7`)),
    parentPeriodRow('Debt', PERIODS.map(() => '=Inputs!$B$21')),
    parentPeriodRow('Total equity', PERIODS.map((_, i) => `=Equity!${periodColumn(i)}37`)),
    parentPeriodRow('Liabilities + equity', PERIODS.map((_, i) => `=${periodColumn(i)}9+${periodColumn(i)}10`)),
    parentPeriodRow('Balance difference', PERIODS.map((_, i) => `=${periodColumn(i)}8-${periodColumn(i)}11`)),
  ];
}

function parentDcfRows() {
  return [
    parentPad(['Parent fixture valuation']),
    parentPad(['UFCF is linked to the shared P8C valuation bridge.']),
    parentPeriodRow('Period ID', PERIODS.map((period) => period.id), ''),
    parentPeriodRow('Period label', PERIODS.map((period) => period.label), ''),
    parentPeriodRow('Year fraction', PERIODS.map((period) => period.yearFraction), 'years'),
    parentPeriodRow('Cumulative forecast years', PERIODS.map((period) => period.cumulativeYears), 'years'),
    parentPeriodRow('Economic UFCF', PERIODS.map((_, i) => `=Equity!${periodColumn(i)}32`)),
  ];
}

async function buildParentOracleWorkbook(overrides = {}) {
  const config = {
    openingCash: 100, openingPpe: 200, openingDebt: 50, openingApic: 120,
    openingRetainedEarnings: 130, openingAoci: 0, openingTotalEquity: 250,
    openingPointShares: 100, openingDividendPayable: 0, taxRate: 0.25,
    revenue: 80, sbcExpense: 20, existingAwardUnits: 0,
    existingUnrecognizedCost: 0, claimPrice: 6.5, settlementPrice: 5,
    withholdingRate: 0, cashIssuanceRatio: 10 / 80, repurchaseRatio: 30 / 80,
    dividendPerShare: 0.1, deliveryTiming: 0, issuanceTiming: 0.5,
    repurchaseTiming: 0, serviceDays: [365, ...Array(10).fill(0)],
    periodDays: Array(11).fill(365), totalServiceDays: 365,
    ...overrides,
  };
  const model = parentModel(config);
  const wb = await createWorkbook({ userTimezone: 'UTC' });
  await wb.sheets.rename('Sheet1', 'Inputs');
  for (const name of ['Schedules', 'Income', 'Taxes', 'CashFlow', 'Equity', 'BalanceSheet', 'DCF', 'Claims']) await wb.sheets.add(name);
  await writeSheet(wb, 'Inputs', parentInputRows(config));
  await writeSheet(wb, 'Schedules', parentScheduleRows(config));
  await writeSheet(wb, 'Income', incomeRows(model));
  await writeSheet(wb, 'Taxes', parentTaxRows(config));
  await writeSheet(wb, 'CashFlow', cashFlowRows(model));
  await writeSheet(wb, 'Equity', equityRows(model, { programApicBasisMode: 'cash', dividendPayableMode: 'settled' }));
  await writeSheet(wb, 'BalanceSheet', parentBalanceRows());
  await writeSheet(wb, 'DCF', parentDcfRows());
  await writeSheet(wb, 'Claims', [
    parentPad(['Existing-award claim bridge']),
    parentPad(['Fixture convention: gross claim is deducted once from equity value and not added to the current denominator.']),
    parentPad(['Equity before claims', 650, 'USD millions']),
    parentPad(['Gross existing claim', '=Equity!B40', 'USD millions']),
    parentPad(['Current point shares', '=Inputs!$B$227', 'shares millions']),
    parentPad(['Claim-adjusted value per share', '=(B3-B4)/B5', 'USD/share']),
  ]);
  await wb.calculate();
  return { wb, config };
}

async function parentValue(wb, sheetName, address) {
  return (await wb.getSheet(sheetName)).getValue(address);
}

async function parentSnapshot(wb) {
  return {
    netIncome: await parentValue(wb, 'Income', 'B15'),
    cfo: await parentValue(wb, 'CashFlow', 'B12'),
    cfi: await parentValue(wb, 'CashFlow', 'B14'),
    cff: await parentValue(wb, 'CashFlow', 'B15'),
    closingCash: await parentValue(wb, 'CashFlow', 'B18'),
    closingPpe: await parentValue(wb, 'BalanceSheet', 'B7'),
    closingApic: await parentValue(wb, 'Equity', 'B34'),
    closingRetainedEarnings: await parentValue(wb, 'Equity', 'B35'),
    closingEquity: await parentValue(wb, 'Equity', 'B37'),
    balanceDifference: await parentValue(wb, 'BalanceSheet', 'B12'),
    closingShares: await parentValue(wb, 'Equity', 'B25'),
    basicWeightedShares: await parentValue(wb, 'Equity', 'B26'),
    basicEps: await parentValue(wb, 'Equity', 'B28'),
    ufcf: await parentValue(wb, 'Equity', 'B32'),
    claimPerShare: await parentValue(wb, 'Claims', 'B6'),
    gate: await parentValue(wb, 'Inputs', `B${P8C_DRIVER_ROWS.gate}`),
  };
}

async function oracle() {
  await mkdir(runDir, { recursive: true });
  const base = await buildParentOracleWorkbook();
  const baseValues = await parentSnapshot(base.wb);
  const expected = {
    netIncome: 37.5, cfo: 67.5, cfi: -15, cff: -30, closingCash: 122.5,
    closingPpe: 205, closingApic: 120, closingRetainedEarnings: 157.5,
    closingEquity: 277.5, balanceDifference: 0, closingShares: 100,
    basicWeightedShares: 101, basicEps: 37.5 / 101, ufcf: 32.5,
  };
  for (const [key, value] of Object.entries(expected)) near(baseValues[key], value, `parent base ${key}`);
  assert.equal(baseValues.gate, 'PASS', 'parent base P8C gate');
  const claim = await buildParentOracleWorkbook({ existingAwardUnits: 4 });
  const claimPerShare = await parentValue(claim.wb, 'Claims', 'B6');
  near(claimPerShare, (650 - 26) / 100, 'parent existing-award claim');
  const addendum = await buildParentOracleWorkbook({ revenue: 100, sbcExpense: 30, existingUnrecognizedCost: 10, cashIssuanceRatio: 0, repurchaseRatio: 0, dividendPerShare: 0 });
  const addendumValues = await parentSnapshot(addendum.wb);
  for (const [key, value] of Object.entries({ netIncome: 45, cfo: 85, ufcf: 47.5 })) near(addendumValues[key], value, `parent addendum ${key}`);
  near(await parentValue(addendum.wb, 'Equity', 'B30'), 70, 'parent addendum valuation EBIT');
  near(await parentValue(addendum.wb, 'Equity', 'B31'), 17.5, 'parent addendum normalized tax');
  const addendumChanged = await buildParentOracleWorkbook({ revenue: 100, sbcExpense: 35, existingUnrecognizedCost: 15, cashIssuanceRatio: 0, repurchaseRatio: 0, dividendPerShare: 0 });
  const addendumChangedValues = await parentSnapshot(addendumChanged.wb);
  for (const [key, value] of Object.entries({ netIncome: 41.25, cfo: 86.25, ufcf: 47.5 })) near(addendumChangedValues[key], value, `parent changed-service addendum ${key}`);
  near(await parentValue(addendumChanged.wb, 'Equity', 'B30'), 70, 'parent changed-service valuation EBIT');
  const timing = await buildParentOracleWorkbook();
  const timingInputs = await timing.wb.getSheet('Inputs');
  const timingBasic = await parentValue(timing.wb, 'Equity', 'B26');
  await timingInputs.setCell(`B${P8C_DRIVER_ROWS.deliveryTiming}`, 1);
  await timingInputs.setCell(`B${P8C_DRIVER_ROWS.issuanceTiming}`, 1);
  await timingInputs.setCell(`B${P8C_DRIVER_ROWS.repurchaseTiming}`, 1);
  await timing.wb.calculate();
  const changedTimingBasic = await parentValue(timing.wb, 'Equity', 'B26');
  assert.notEqual(changedTimingBasic, timingBasic, 'parent timing edit propagated');
  const settlement = await buildParentOracleWorkbook();
  const settlementInputs = await settlement.wb.getSheet('Inputs');
  const baseGrossUnits = await parentValue(settlement.wb, 'Equity', 'B10');
  await settlementInputs.setCell(`B${P8C_DRIVER_ROWS.settlementPrice}`, 10);
  await settlement.wb.calculate();
  assert.notEqual(await parentValue(settlement.wb, 'Equity', 'B10'), baseGrossUnits, 'parent settlement-price edit propagated');
  const withholding = await buildParentOracleWorkbook();
  const withholdingInputs = await withholding.wb.getSheet('Inputs');
  const baseWithheld = await parentValue(withholding.wb, 'Equity', 'B11');
  await withholdingInputs.setCell(`B${P8C_DRIVER_ROWS.withholdingRate}`, 0.5);
  await withholding.wb.calculate();
  assert.ok(Number(await parentValue(withholding.wb, 'Equity', 'B11')) > Number(baseWithheld), 'parent withholding edit propagated');
  const returns = await buildParentOracleWorkbook();
  const returnsInputs = await returns.wb.getSheet('Inputs');
  const baseProgramCash = await parentValue(returns.wb, 'Equity', 'B16');
  const baseDividend = await parentValue(returns.wb, 'Equity', 'B23');
  await returnsInputs.setCell(`B${P8C_DRIVER_ROWS.repurchaseRatio}`, 0.2);
  await returnsInputs.setCell(`B${P8C_DRIVER_ROWS.dividendPerShareQuarter}`, 0.05);
  await returns.wb.calculate();
  assert.notEqual(await parentValue(returns.wb, 'Equity', 'B16'), baseProgramCash, 'parent program edit propagated');
  assert.notEqual(await parentValue(returns.wb, 'Equity', 'B23'), baseDividend, 'parent dividend edit propagated');
  const loss = await buildParentOracleWorkbook();
  const lossSchedules = await loss.wb.getSheet('Schedules');
  await lossSchedules.setCell('B11', 120);
  await loss.wb.calculate();
  near(await parentValue(loss.wb, 'Equity', 'B27'), 0, 'parent loss antidilution');
  const missing = await buildParentOracleWorkbook();
  const missingInputs = await missing.wb.getSheet('Inputs');
  await missingInputs.setCell(`B${P8C_DRIVER_ROWS.settlementPrice}`, null);
  await missing.wb.calculate();
  assert.equal(await parentValue(missing.wb, 'Inputs', `B${P8C_DRIVER_ROWS.gate}`), 'FAIL', 'parent missing price blocked');
  const zero = await buildParentOracleWorkbook();
  const zeroInputs = await zero.wb.getSheet('Inputs');
  await zeroInputs.setCell(`B${P8C_DRIVER_ROWS.cashIssuanceRatio}`, 0);
  await zeroInputs.setCell(`B${P8C_DRIVER_ROWS.repurchaseRatio}`, 0);
  await zero.wb.calculate();
  assert.equal(await parentValue(zero.wb, 'Inputs', `B${P8C_DRIVER_ROWS.gate}`), 'PASS', 'parent zero flows valid');
  const workbookPath = resolve(runDir, 'p8c-parent-oracle.xlsx');
  const claimWorkbookPath = resolve(runDir, 'p8c-parent-claim-oracle.xlsx');
  await base.wb.save(workbookPath);
  await claim.wb.save(claimWorkbookPath);
  base.wb.dispose();
  claim.wb.dispose(); addendum.wb.dispose(); addendumChanged.wb.dispose(); timing.wb.dispose(); settlement.wb.dispose(); withholding.wb.dispose(); returns.wb.dispose(); loss.wb.dispose(); missing.wb.dispose(); zero.wb.dispose();
  const result = {
    status: 'PASS', mode: 'P8C_PARENT_ORACLE', workbookPath, claimWorkbookPath,
    periods: [{ id: 'FY2026_STUB', days: 365, yearFraction: 1 }],
    actual: { ...baseValues, claimPerShare },
    expected: { ...expected, claimPerShare: (650 - 26) / 100, addendumNetIncome: 45, addendumCfo: 85, addendumUfcf: 47.5, changedServiceNetIncome: 41.25, changedServiceCfo: 86.25 },
    scenarios: {
      addendum: 'PASS; existing service cost 10 and future new SBC 20 reconcile to valuation UFCF 47.5',
      mixedTiming: 'PASS; year-end delivery/repurchase and midyear issuance changed the basic denominator',
      settlementPrice: 'PASS; live settlement price changed gross units',
      withholdingProgramDividend: 'PASS; live withholding, repurchase and dividend inputs changed outputs',
      lossAntidilution: 'PASS; loss zeroed diluted increment',
      missingPriceBlocks: 'PASS',
      zeroIssuanceOrRepurchaseValid: 'PASS',
    },
    formulaAuthority: 'Mog formulas from shared equityRows/incomeRows/cashFlowRows; expected values are assertions only',
  };
  await writeFile(resolve(runDir, 'p8c-parent-oracle-verification.json'), `${JSON.stringify(result, null, 2)}\n`, 'utf8');
  console.log(JSON.stringify(result, null, 2));
}

async function adverse() {
  const model = JSON.parse(await readFile(inputPath, 'utf8'));
  const cases = [];
  const fail = async (name, mutate) => {
    const candidate = clone(model);
    let error = null;
    mutate(candidate);
    try {
      const path = resolve(runDir, `adverse-${name.replaceAll(/[^a-z0-9]+/gi, '-').toLowerCase()}.xlsx`);
      await saveWorkbook(candidate, path);
      await inspectAssetWorkbook(path);
    } catch (caught) {
      error = caught;
    }
    assert.ok(error, `${name} unexpectedly passed`);
    cases.push({ name, status: 'PASS', message: String(error.message) });
  };
  const failTamperedFormula = async (name, mutate) => {
    const path = resolve(runDir, `adverse-${name.replaceAll(/[^a-z0-9]+/gi, '-').toLowerCase()}.xlsx`);
    let error = null;
    try {
      await saveTamperedWorkbook(model, path, mutate);
      await inspectAssetWorkbook(path);
    } catch (caught) {
      error = caught;
    }
    assert.ok(error, `${name} unexpectedly passed`);
    cases.push({ name, status: 'PASS', message: String(error.message) });
  };
  await fail('missing existing claim price', (candidate) => {
    candidate.equity_forecast.forecast.policy.existing_claim_price = null;
    candidate.equity_packet.facts.market_quote.value = null;
  });
  await fail('zero settlement price', (candidate) => { candidate.equity_forecast.forecast.policy.settlement_price = 0; });
  await fail('settlement price below APIC basis', (candidate) => { candidate.equity_forecast.forecast.policy.settlement_price = 1; });
  await fail('negative opening APIC', (candidate) => { candidate.equity_forecast.inputs.common_apic = -1; });
  await fail('negative new compensation', (candidate) => { candidate.equity_forecast.forecast.policy.sbc_ratio = 0; });
  await failTamperedFormula('omitted existing-award claim deduction', async (workbook) => {
    const dcf = await workbook.getSheet('DCF');
    await dcf.setCell('B27', '=B22');
  });
  await failTamperedFormula('duplicated existing-award claim deduction', async (workbook) => {
    const dcf = await workbook.getSheet('DCF');
    await dcf.setCell('B27', '=B22-B26-B26');
  });
  await failTamperedFormula('double-counted point-share denominator', async (workbook) => {
    const dcf = await workbook.getSheet('DCF');
    await dcf.setCell('B28', '=Inputs!$B$227+Inputs!$B$173');
  });
  const zero = clone(model);
  zero.equity_forecast.forecast.policy.cash_issuance_ratio = 0;
  zero.equity_forecast.forecast.policy.repurchase_ratio = 0;
  const zeroPath = resolve(runDir, 'adverse-zero-supported-flows.xlsx');
  await saveWorkbook(zero, zeroPath);
  const zeroSnapshot = await inspectAssetWorkbook(zeroPath);
  assert.equal(zeroSnapshot.equityGateStatus, 'PASS', 'supported zero flows gate');
  cases.push({ name: 'supported zero issuance and repurchase', status: 'PASS', equityGateStatus: zeroSnapshot.equityGateStatus, periodStatus: zeroSnapshot.allPeriodStatus });
  const restored = clone(model);
  const restoredPath = resolve(runDir, 'adverse-restored-base.xlsx');
  await saveWorkbook(restored, restoredPath);
  const restoredSnapshot = await inspectAssetWorkbook(restoredPath);
  assert.equal(restoredSnapshot.equityGateStatus, 'PASS', 'restored base gate');
  cases.push({ name: 'restored base', status: 'PASS', equityGateStatus: restoredSnapshot.equityGateStatus });
  await mkdir(runDir, { recursive: true });
  await writeFile(resolve(runDir, 'p8c-adverse-verification.json'), `${JSON.stringify({ status: 'PASS', cases }, null, 2)}\n`, 'utf8');
  console.log(JSON.stringify({ status: 'PASS', cases }, null, 2));
}

if (command === 'authority') await authority();
else if (command === 'binding') await binding();
else if (command === 'integration') await integration();
else if (command === 'oracle') await oracle();
else if (command === 'adverse') await adverse();
else throw new Error(`Unknown P8C command: ${command}`);

// Invalid workbook construction can leave the SDK's worker alive after the
// expected guard exception.  The adverse proof is terminal and already wrote
// its artifact, so release that worker explicitly before returning to the CLI.
if (command === 'adverse') process.exit(0);
