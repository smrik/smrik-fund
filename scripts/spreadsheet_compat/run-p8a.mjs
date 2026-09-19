import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { createWorkbook } from '@mog-sdk/sdk';
import {
  buildAssetWorkbook,
  inspectAssetWorkbook,
  readSnapshot,
  TAX_DRIVER_ROWS,
  TOLERANCE,
  PERIODS,
} from './asset_model.mjs';

const [, , command = 'authority', inputArg, runArg] = process.argv;
const inputPath = resolve(inputArg ?? 'data/build-guide-p8a/model-input.json');
const runDir = resolve(runArg ?? 'data/build-guide-p8a/mog-authority');
const settle = () => new Promise((resolvePromise) => setTimeout(resolvePromise, 150));
const near = (actual, expected, label) => assert.ok(Math.abs(Number(actual) - expected) <= TOLERANCE, `${label}: expected ${expected}, got ${actual}`);
const sha256 = async (path) => createHash('sha256').update(await readFile(path)).digest('hex');

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
  const model = JSON.parse(await readFile(inputPath, 'utf8'));
  assert.ok(model.tax_forecast, 'P8A tax forecast is required');
  await mkdir(runDir, { recursive: true });
  const workbookPath = resolve(runDir, 'tax-authority.xlsx');
  await saveWorkbook(model, workbookPath);
  const snapshot = await inspectAssetWorkbook(workbookPath);
  assert.equal(snapshot.taxGateStatus, 'PASS', 'P8A tax input gate');
  assert.equal(snapshot.allPeriodStatus, 'PASS', 'all-period mechanical gate');
  assert.ok(snapshot.tax, 'Taxes schedule missing');
  const oldFlatClosing = Number(model.tax_forecast.inputs.payable_timing.flat_alternative.closing_balance);
  const selectedClosing = Number(snapshot.tax.currentTaxPayableClosing[0]);
  const timingDelta = selectedClosing - oldFlatClosing;
  const verification = {
    status: 'PASS',
    mode: 'Mog calculation-only P8A preview',
    inputPath,
    workbookPath,
    publishedSha256: await sha256(workbookPath),
    timingComparison: {
      selectedMethod: snapshot.tax.currentTaxPayableMethod,
      selectedClosing,
      oldFlatClosing,
      firstStubCfoIncreaseVsOldFlat: timingDelta,
      firstStubClosingCashIncreaseVsOldFlat: timingDelta,
      oldFlatFirstStubCfo: Number(snapshot.stub.cfo) - timingDelta,
      oldFlatFirstStubClosingCash: Number(snapshot.stub.closingCash) - timingDelta,
      basis: 'same linked model with Q3FY2026 reported current-tax payable held flat as a diagnostic alternative; no source value is rewritten',
    },
    snapshot,
    formulaAuthority: 'Mog formulas; Python proposal fields are diagnostic inputs only',
  };
  const verificationPath = resolve(runDir, 'tax-verification.json');
  await writeFile(verificationPath, `${JSON.stringify(verification, null, 2)}\n`, 'utf8');
  console.log(JSON.stringify({ status: 'PASS', workbookPath, verificationPath, snapshot }, null, 2));
}

async function oracle() {
  const model = JSON.parse(await readFile(inputPath, 'utf8'));
  assert.ok(model.tax_forecast, 'P8A tax forecast is required');
  // Keep this oracle focused on P8A mechanics. The production P6/P7 overlays
  // are intentionally removed from the fictional fixture so their drivers do
  // not alter the stated EBIT, cash-capex or opening-balance identities.
  delete model.operating_forecast;
  delete model.operating_decision;
  delete model.p6_decision;
  delete model.working_capital_forecast;
  delete model.working_capital_decision;
  delete model.working_capital_packet;
  await mkdir(runDir, { recursive: true });
  const handle = await buildAssetWorkbook(model);
  try {
    const inputs = await handle.wb.getSheet('Inputs');
    const taxes = await handle.wb.getSheet('Taxes');
    const income = await handle.wb.getSheet('Income');
    const cashFlow = await handle.wb.getSheet('CashFlow');
    const balanceSheet = await handle.wb.getSheet('BalanceSheet');
    const dcf = await handle.wb.getSheet('DCF');
    const setInput = async (address, value) => inputs.setCell(address, value);

    // The fixture uses the real linked schedules, but its values are fictional
    // and are supplied through Inputs. No MSFT source fact is changed.
    const synthetic = {
      B6: 100, B7: 0, B8: 0, B9: 0, B10: 0, B11: 200, B12: 0, B13: 200,
      B14: 0, B15: 0, B16: 0, B17: 0, B18: 0, B19: 300, B20: 0, B21: 100,
      B22: 0, B23: 120, B24: 180, B29: 5, B30: 100, B31: 0, B32: 1 / 6,
      B33: 0, B34: 0, B35: 0.25, B36: 0, B37: 0.08, B38: 0.02,
      B43: 520, B55: 130, B57: 10, B58: 20, B59: 0,
      [`B${TAX_DRIVER_ROWS.bookTaxRate}`]: 0.25,
      [`B${TAX_DRIVER_ROWS.operatingTaxRate}`]: 0.25,
      [`B${TAX_DRIVER_ROWS.deferredShare}`]: 0.2,
      // The parent oracle intentionally exercises the supported explicit
      // closing-balance control. The production fixture uses source-anchored
      // days, so make this fictional fixture's active method explicit first.
      [`B${TAX_DRIVER_ROWS.currentTaxPayableMethod}`]: 'explicit_closing_balance',
      [`B${TAX_DRIVER_ROWS.currentTaxPayableDays}`]: null,
      [`B${TAX_DRIVER_ROWS.currentTaxPayableClosing}`]: 10,
      [`B${TAX_DRIVER_ROWS.longTermTaxSettlement}`]: 0,
      [`B${TAX_DRIVER_ROWS.openingCurrentTaxPayable}`]: 8,
      [`B${TAX_DRIVER_ROWS.openingLongTermTaxLiability}`]: 12,
      [`B${TAX_DRIVER_ROWS.openingDeferredTaxLiability}`]: 12,
      [`B${TAX_DRIVER_ROWS.interestExpense}`]: 20,
    };
    for (const [address, value] of Object.entries(synthetic)) await setInput(address, value);
    for (const column of ['C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L']) {
      await setInput(`${column}${TAX_DRIVER_ROWS.deferredShare}`, 0.2);
      await setInput(`${column}${TAX_DRIVER_ROWS.currentTaxPayableClosing}`, 10);
      await setInput(`${column}${TAX_DRIVER_ROWS.longTermTaxSettlement}`, 0);
    }
    await handle.wb.calculate();
    await settle();

    // Parent oracle assertions are read from calculated cells, never written
    // into the result. The upstream fixture must expose exactly the stated
    // 120 EBIT/20 interest/100 PBT case before tax checks are evaluated.
    near(await income.getValue('B11'), 120, 'oracle EBIT');
    near(await income.getValue('B12'), -20, 'oracle interest expense sign');
    near(await taxes.getValue('B7'), 20, 'oracle interest expense magnitude');
    near(await income.getValue('B13'), 100, 'oracle pretax income');
    near(await taxes.getValue('B11'), 25, 'oracle book tax');
    near(await taxes.getValue('B13'), 5, 'oracle deferred tax');
    near(await taxes.getValue('B14'), 20, 'oracle current tax');
    near(await taxes.getValue('B17'), 18, 'oracle current cash tax');
    near(await taxes.getValue('B22'), 17, 'oracle closing DTL');
    near(await cashFlow.getValue('B12'), 92, 'oracle CFO');
    near(await cashFlow.getValue('B18'), 172, 'oracle closing cash');
    near(await balanceSheet.getValue('B28'), 0, 'oracle balance difference');
    near(await dcf.getValue('B7'), 80, 'oracle UFCF');

    await setInput(`B${TAX_DRIVER_ROWS.interestExpense}`, 30);
    await handle.wb.calculate();
    await settle();
    const financingShock = await readSnapshot(handle.wb);
    near(await income.getValue('B13'), 90, 'interest shock pretax income');
    near(await taxes.getValue('B11'), 22.5, 'interest shock book tax');
    near(await taxes.getValue('B13'), 4.5, 'interest shock deferred tax');
    near(await taxes.getValue('B17'), 16, 'interest shock cash tax');
    near(await taxes.getValue('B22'), 16.5, 'interest shock closing DTL');
    near(await cashFlow.getValue('B12'), 84, 'interest shock CFO');
    near(await cashFlow.getValue('B18'), 164, 'interest shock closing cash');
    near(await balanceSheet.getValue('B28'), 0, 'interest shock balance difference');
    near(await dcf.getValue('B7'), 80, 'operating UFCF independent of interest');
    assert.equal(financingShock.taxGateStatus, 'PASS', 'interest shock tax gate');

    const result = {
      status: 'PASS',
      fixture: 'P8A_PARENT_ORACLE fictional USD millions; never MSFT evidence',
      inputPath,
      workbookPath: resolve(runDir, 'p8a-parent-oracle.xlsx'),
      base: {
        ebit: 120,
        interest: 20,
        pretaxIncome: 100,
        bookTax: 25,
        currentTax: 20,
        deferredTax: 5,
        currentCashTax: 18,
        closingDtl: 17,
        cfo: 92,
        ufcf: 80,
      },
      interest30: {
        ebit: 120,
        interest: 30,
        pretaxIncome: 90,
        bookTax: 22.5,
        currentTax: 18,
        deferredTax: 4.5,
        currentCashTax: 16,
        closingDtl: 16.5,
        cfo: 84,
        ufcf: 80,
      },
      formulaAuthority: {
        tax: await taxes.getFormula('B11'),
        currentPayment: await taxes.getFormula('B17'),
        deferredLiability: await taxes.getFormula('B22'),
        operatingTax: await taxes.getFormula('B29'),
      },
      tolerance: TOLERANCE,
      periods: PERIODS.length,
      adverseChecks: 'Interest shock preserved operating UFCF at 80 while changing book/current/deferred/cash tax effects.',
    };
    await handle.wb.save(result.workbookPath);
    await settle();
    await writeFile(resolve(runDir, 'p8a-parent-oracle-verification.json'), `${JSON.stringify(result, null, 2)}\n`, 'utf8');
    console.log(JSON.stringify(result, null, 2));
  } finally {
    await settle();
    handle.wb.dispose();
  }
}

async function timing() {
  const model = JSON.parse(await readFile(inputPath, 'utf8'));
  assert.ok(model.tax_forecast, 'P8A tax forecast is required');
  // Keep this oracle focused on the current-tax timing method. The synthetic
  // EBIT fixture gives a known current-tax expense while the workbook remains
  // the formula authority for the closing payable and cash bridge.
  delete model.operating_forecast;
  delete model.operating_decision;
  delete model.p6_decision;
  delete model.working_capital_forecast;
  delete model.working_capital_decision;
  delete model.working_capital_packet;
  await mkdir(runDir, { recursive: true });
  const handle = await buildAssetWorkbook(model);
  try {
    const inputs = await handle.wb.getSheet('Inputs');
    const taxes = await handle.wb.getSheet('Taxes');
    const income = await handle.wb.getSheet('Income');
    const setInput = async (address, value) => inputs.setCell(address, value);
    const synthetic = {
      B6: 100, B7: 0, B8: 0, B9: 0, B10: 0, B11: 200, B12: 0, B13: 200,
      B14: 0, B15: 0, B16: 0, B17: 0, B18: 0, B19: 300, B20: 0, B21: 100,
      B22: 0, B23: 120, B24: 180, B29: 5, B30: 100, B31: 0, B32: 1 / 6,
      B33: 0, B34: 0, B35: 0.25, B36: 0, B37: 0.08, B38: 0.02,
      B43: 520, B55: 130, B57: 10, B58: 20, B59: 0,
      [`B${TAX_DRIVER_ROWS.bookTaxRate}`]: 0.25,
      [`B${TAX_DRIVER_ROWS.operatingTaxRate}`]: 0.25,
      [`B${TAX_DRIVER_ROWS.deferredShare}`]: 0,
      [`B${TAX_DRIVER_ROWS.currentTaxPayableMethod}`]: 'source_anchored_payable_days',
      [`B${TAX_DRIVER_ROWS.currentTaxPayableDays}`]: 91.25,
      [`B${TAX_DRIVER_ROWS.longTermTaxSettlement}`]: 0,
      [`B${TAX_DRIVER_ROWS.openingCurrentTaxPayable}`]: 8,
      [`B${TAX_DRIVER_ROWS.openingLongTermTaxLiability}`]: 12,
      [`B${TAX_DRIVER_ROWS.openingDeferredTaxLiability}`]: 12,
      [`B${TAX_DRIVER_ROWS.interestExpense}`]: 20,
      B109: null,
    };
    for (const [address, value] of Object.entries(synthetic)) await setInput(address, value);
    for (const column of ['C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L']) {
      await setInput(`${column}${TAX_DRIVER_ROWS.deferredShare}`, 0);
      await setInput(`${column}${TAX_DRIVER_ROWS.longTermTaxSettlement}`, 0);
      await setInput(`${column}${TAX_DRIVER_ROWS.currentTaxPayableClosing}`, null);
    }
    await handle.wb.calculate();
    await settle();

    // B is a 91-day stub. The fixture EBIT is 120 and interest is 20, so
    // PBT/current tax are 100/25 and the source-days formula gives 25.06868.
    near(await income.getValue('B13'), 100, 'timing annualized PBT');
    near(await taxes.getValue('B14'), 25, 'timing current tax expense');
    near(await taxes.getValue('B16'), 25 * 91.25 / 91, 'timing stub closing payable');
    near(await taxes.getValue('B17'), 8 + 25 - (25 * 91.25 / 91), 'timing stub cash tax');
    const annualCurrentTax = Number(await taxes.getValue('C14'));
    const leapCurrentTax = Number(await taxes.getValue('D14'));
    near(await taxes.getValue('C16'), annualCurrentTax / 365 * 91.25, 'timing annual closing payable');
    near(await taxes.getValue('D16'), leapCurrentTax / 366 * 91.25, 'timing leap-year closing payable');
    const baseStubClosing = Number(await taxes.getValue('B16'));
    await setInput(`B${TAX_DRIVER_ROWS.currentTaxPayableDays}`, 90.25);
    await handle.wb.calculate();
    await settle();
    const editedStubClosing = Number(await taxes.getValue('B16'));
    assert.ok(Math.abs(editedStubClosing - baseStubClosing) > TOLERANCE, 'timing driver edit must change active closing payable');
    await setInput(`B${TAX_DRIVER_ROWS.currentTaxPayableDays}`, 91.25);
    await handle.wb.calculate();
    await settle();
    const workbookPath = resolve(runDir, 'p8a-timing-oracle.xlsx');
    await handle.wb.save(workbookPath);
    await settle();
    const result = {
      status: 'PASS',
      mode: 'Mog formula-owned P8A source-anchored payable-days timing oracle',
      inputPath,
      workbookPath,
      method: 'source_anchored_payable_days',
      selectedPayableDays: 91.25,
      periodDays: [91, 365, 366],
      base: {
        pretaxIncome: 100,
        currentTaxExpense: 25,
        stubClosingPayable: baseStubClosing,
        stubCashTax: 8 + 25 - baseStubClosing,
        fy2027CurrentTaxExpense: annualCurrentTax,
        fy2027ClosingPayable: Number(await taxes.getValue('C16')),
        fy2028CurrentTaxExpense: leapCurrentTax,
        fy2028ClosingPayable: Number(await taxes.getValue('D16')),
      },
      edited: { selectedPayableDays: 90.25, stubClosingPayable: editedStubClosing },
      formulas: {
        currentPayableClosing: await taxes.getFormula('B16'),
        currentPayment: await taxes.getFormula('B17'),
      },
      formulaAuthority: 'Mog formulas; Python proposal fields are diagnostic inputs only',
    };
    await writeFile(resolve(runDir, 'p8a-timing-oracle-verification.json'), `${JSON.stringify(result, null, 2)}\n`, 'utf8');
    console.log(JSON.stringify(result, null, 2));
  } finally {
    await settle();
    handle.wb.dispose();
  }
}

async function guard() {
  const model = JSON.parse(await readFile(inputPath, 'utf8'));
  assert.ok(model.tax_forecast, 'P8A tax forecast is required');
  await mkdir(runDir, { recursive: true });
  const handle = await buildAssetWorkbook(model);
  try {
    const inputs = await handle.wb.getSheet('Inputs');
    const dcf = await handle.wb.getSheet('DCF');
    const review = await handle.wb.getSheet('Review');
    const originalCurrentMethod = await inputs.getValue(`B${TAX_DRIVER_ROWS.currentTaxPayableMethod}`);
    const originalCurrentDays = await inputs.getValue(`B${TAX_DRIVER_ROWS.currentTaxPayableDays}`);
    const originalBookRate = await inputs.getValue(`B${TAX_DRIVER_ROWS.bookTaxRate}`);
    const recalculate = async () => { await handle.wb.calculate(); await settle(); };
    await inputs.setCell(`B${TAX_DRIVER_ROWS.currentTaxPayableDays}`, null);
    await recalculate();
    assert.equal(await inputs.getValue(`B${TAX_DRIVER_ROWS.gate}`), 'FAIL', 'missing payable days must fail gate');
    assert.equal(await dcf.getValue('B18'), 'BLOCKED', 'missing payable days must block valuation');
    await inputs.setCell(`B${TAX_DRIVER_ROWS.currentTaxPayableDays}`, originalCurrentDays);
    await inputs.setCell(`B${TAX_DRIVER_ROWS.deferredShare}`, 0);
    await recalculate();
    assert.equal(await inputs.getValue(`B${TAX_DRIVER_ROWS.gate}`), 'PASS', 'numeric zero deferred share must pass gate');
    await inputs.setCell(`B${TAX_DRIVER_ROWS.bookTaxRate}`, Number(originalBookRate) * 0.9);
    await recalculate();
    assert.equal(await review.getValue('B3'), 'EDITED_UNREVIEWED', 'tax edit must invalidate review binding');
    await inputs.setCell(`B${TAX_DRIVER_ROWS.bookTaxRate}`, originalBookRate);
    await recalculate();
    assert.equal(await review.getValue('B3'), model.tax_forecast.decision.status, 'exact restore must recover review binding');
    await inputs.setCell(`B${TAX_DRIVER_ROWS.currentTaxPayableDays}`, Number(originalCurrentDays) + 1);
    await recalculate();
    assert.equal(await review.getValue('B3'), 'EDITED_UNREVIEWED', 'timing edit must invalidate review binding');
    await inputs.setCell(`B${TAX_DRIVER_ROWS.currentTaxPayableDays}`, originalCurrentDays);
    await inputs.setCell(`B${TAX_DRIVER_ROWS.currentTaxPayableMethod}`, originalCurrentMethod);
    await recalculate();
    const workbookPath = resolve(runDir, 'p8a-guard.xlsx');
    await handle.wb.save(workbookPath);
    await settle();
    const result = {
      status: 'PASS',
      inputPath,
      workbookPath,
      adverseChecks: {
        missingCurrentPayableDays: 'FAIL gate / BLOCKED valuation',
        numericZeroDeferredShare: 'PASS gate',
        editedBookRate: 'EDITED_UNREVIEWED',
        timingDaysEdit: 'EDITED_UNREVIEWED',
        exactRestore: model.tax_forecast.decision.status,
      },
    };
    await writeFile(resolve(runDir, 'p8a-guard-verification.json'), `${JSON.stringify(result, null, 2)}\n`, 'utf8');
    console.log(JSON.stringify(result, null, 2));
  } finally {
    await settle();
    handle.wb.dispose();
  }
}

async function reversal() {
  const model = JSON.parse(await readFile(inputPath, 'utf8'));
  assert.ok(model.tax_forecast, 'P8A tax forecast is required');
  await mkdir(runDir, { recursive: true });
  const handle = await buildAssetWorkbook(model);
  try {
    const inputs = await handle.wb.getSheet('Inputs');
    const taxes = await handle.wb.getSheet('Taxes');
    const income = await handle.wb.getSheet('Income');
    const cashFlow = await handle.wb.getSheet('CashFlow');
    const dcf = await handle.wb.getSheet('DCF');
    const base = await readSnapshot(handle.wb);
    assert.equal(base.taxGateStatus, 'PASS', 'base P8A tax gate');
    assert.equal(base.allPeriodStatus, 'PASS', 'base all-period mechanical gate');
    assert.equal(base.dcfStatus, model.tax_forecast.decision.status, 'base review binding');
    const baseBookTax = Number(base.tax.bookTaxExpense[0]);
    const baseDeferred = Number(base.tax.deferredTaxExpense[0]);
    const baseNetIncome = Number(base.stub.netIncome);
    const baseCfo = Number(base.stub.cfo);
    const baseCash = Number(base.stub.closingCash);
    const baseCurrentClose = Number(base.tax.currentTaxPayableClosing[0]);
    const baseOperatingTax = Number(base.tax.operatingTaxExpense[0]);
    const baseUfcf = Number(base.stub.economicUfcf);
    assert.ok(Number.isFinite(baseBookTax) && baseBookTax > 0, 'base book tax must be positive');
    assert.equal(baseDeferred, 0, 'R1 base deferred tax must be zero');

    await inputs.setCell(`B${TAX_DRIVER_ROWS.deferredShare}`, -0.1);
    for (const column of ['C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L']) await inputs.setCell(`${column}${TAX_DRIVER_ROWS.deferredShare}`, 0);
    await handle.wb.calculate();
    await settle();
    const reversalSnapshot = await readSnapshot(handle.wb);
    assert.equal(reversalSnapshot.taxGateStatus, 'PASS', 'reversal P8A tax gate');
    assert.equal(reversalSnapshot.allPeriodStatus, 'PASS', 'reversal all-period mechanical gate');
    assert.ok(reversalSnapshot.checks.every((value) => value === 'PASS'), 'reversal mechanical checks');
    assert.ok(reversalSnapshot.tax.status.every((value) => value === 'PASS'), 'reversal tax period checks');
    near(reversalSnapshot.tax.bookTaxExpense[0], baseBookTax, 'reversal preserves book tax');
    near(reversalSnapshot.stub.netIncome, baseNetIncome, 'reversal preserves net income');
    near(reversalSnapshot.tax.deferredTaxExpense[0], -0.1 * baseBookTax, 'reversal deferred benefit');
    near(reversalSnapshot.tax.deferredTaxLiabilityClosing[0], base.tax.deferredTaxLiabilityClosing[0] - 0.1 * baseBookTax, 'reversal closes existing DTL');
    assert.ok(Number(reversalSnapshot.tax.deferredTaxLiabilityClosing[0]) > 0, 'reversal DTL remains positive');
    for (let index = 1; index < PERIODS.length; index += 1) {
      near(reversalSnapshot.tax.deferredTaxExpense[index], 0, `later deferred expense ${index}`);
      near(reversalSnapshot.tax.deferredTaxLiabilityClosing[index], reversalSnapshot.tax.deferredTaxLiabilityClosing[0], `later DTL ${index}`);
    }
    const expectedCurrentCashTaxDelta = base.tax.currentTaxPayableMethod === 'source_anchored_payable_days'
      ? 0.1 * (baseBookTax - baseCurrentClose)
      : 0.1 * baseBookTax;
    near(reversalSnapshot.tax.currentTaxPayment[0] - base.tax.currentTaxPayment[0], expectedCurrentCashTaxDelta, 'reversal current cash tax effect');
    near(reversalSnapshot.stub.cfo - baseCfo, -expectedCurrentCashTaxDelta, 'reversal CFO effect');
    near(reversalSnapshot.stub.closingCash - baseCash, -expectedCurrentCashTaxDelta, 'reversal closing cash effect');
    near(reversalSnapshot.tax.operatingTaxExpense[0], baseOperatingTax, 'reversal operating tax independence');
    near(reversalSnapshot.stub.economicUfcf, baseUfcf, 'reversal UFCF independence');
    const result = {
      status: 'PASS',
      mode: 'Mog formula-owned P8A deferred reversal',
      inputPath,
      workbookPath: resolve(runDir, 'p8a-reversal.xlsx'),
      base: {
        bookTax: baseBookTax,
        deferredTax: baseDeferred,
        netIncome: baseNetIncome,
        currentCashTax: Number(base.tax.currentTaxPayment[0]),
        closingDtl: Number(base.tax.deferredTaxLiabilityClosing[0]),
        cfo: baseCfo,
        closingCash: baseCash,
        operatingTax: baseOperatingTax,
        ufcf: baseUfcf,
      },
      reversal: {
        deferredShare: [-0.1, ...Array(PERIODS.length - 1).fill(0)],
        bookTax: Number(reversalSnapshot.tax.bookTaxExpense[0]),
        deferredTax: Number(reversalSnapshot.tax.deferredTaxExpense[0]),
        netIncome: Number(reversalSnapshot.stub.netIncome),
        currentCashTax: Number(reversalSnapshot.tax.currentTaxPayment[0]),
        currentCashTaxDelta: expectedCurrentCashTaxDelta,
        closingDtl: Number(reversalSnapshot.tax.deferredTaxLiabilityClosing[0]),
        cfo: Number(reversalSnapshot.stub.cfo),
        closingCash: Number(reversalSnapshot.stub.closingCash),
        operatingTax: Number(reversalSnapshot.tax.operatingTaxExpense[0]),
        ufcf: Number(reversalSnapshot.stub.economicUfcf),
      },
      checks: ['book tax and net income unchanged', 'negative deferred expense reverses positive DTL', 'current cash tax/CFO/cash move by reversal', 'operating tax and UFCF unchanged', 'all-period mechanical and tax checks PASS'],
    };
    await handle.wb.save(result.workbookPath);
    await settle();
    await writeFile(resolve(runDir, 'p8a-reversal-verification.json'), `${JSON.stringify(result, null, 2)}\n`, 'utf8');
    console.log(JSON.stringify(result, null, 2));
  } finally {
    await settle();
    handle.wb.dispose();
  }
}

async function adverse() {
  const sourceModel = JSON.parse(await readFile(inputPath, 'utf8'));
  assert.ok(sourceModel.tax_forecast, 'P8A tax forecast is required');
  await mkdir(runDir, { recursive: true });
  const cases = [];
  const runCase = async (name, mutate, expectedLabel) => {
    const handle = await buildAssetWorkbook(JSON.parse(JSON.stringify(sourceModel)));
    try {
      const inputs = await handle.wb.getSheet('Inputs');
      const taxes = await handle.wb.getSheet('Taxes');
      await mutate(inputs, taxes);
      await handle.wb.calculate();
      await settle();
      const snapshot = await readSnapshot(handle.wb);
      assert.equal(snapshot.taxGateStatus, 'FAIL', `${name} tax gate`);
      assert.equal(snapshot.dcfStatus, 'BLOCKED', `${name} DCF status`);
      cases.push({ name, status: 'PASS', expected: expectedLabel, taxGateStatus: snapshot.taxGateStatus, dcfStatus: snapshot.dcfStatus, checks: snapshot.checks, taxStatus: snapshot.tax.status });
    } finally {
      await settle();
      handle.wb.dispose();
    }
  };
  await runCase('cross-period DTL underflow', async (inputs) => {
    await inputs.setCell(`B${TAX_DRIVER_ROWS.deferredShare}`, -1);
  }, 'closing DTL below zero is blocked');
  await runCase('final-period over-settlement', async (inputs) => {
    const openingLongTerm = Number(await inputs.getValue(`B${TAX_DRIVER_ROWS.openingLongTermTaxLiability}`));
    await inputs.setCell(`L${TAX_DRIVER_ROWS.longTermTaxSettlement}`, openingLongTerm + 1);
  }, 'final closing long-term liability below zero is blocked');
  await runCase('unsupported negative current cash payment', async (inputs, taxes) => {
    // Increasing selected payable days above the stub period creates a
    // closing balance greater than opening plus current expense, which the
    // linked cash payment formula correctly rejects as an unsupported refund.
    await inputs.setCell(`B${TAX_DRIVER_ROWS.currentTaxPayableDays}`, 365);
  }, 'negative current cash payment is blocked');
  const result = { status: 'PASS', mode: 'Mog formula-owned P8A adverse guards', inputPath, cases };
  await writeFile(resolve(runDir, 'p8a-adverse-verification.json'), `${JSON.stringify(result, null, 2)}\n`, 'utf8');
  console.log(JSON.stringify(result, null, 2));
}

if (command === 'authority') await authority();
else if (command === 'oracle') await oracle();
else if (command === 'timing') await timing();
else if (command === 'guard') await guard();
else if (command === 'reversal') await reversal();
else if (command === 'adverse') await adverse();
else throw new Error(`Unknown P8A command: ${command}`);
