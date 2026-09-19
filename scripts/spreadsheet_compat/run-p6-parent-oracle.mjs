import assert from 'node:assert/strict';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { buildAssetWorkbook, inspectAssetWorkbook, PERIODS, TOLERANCE } from './asset_model.mjs';

const outputDir = resolve(process.argv[2] ?? 'data/build-guide-p6/offline-r3/p6-parent-oracle-r3');
const command = `node scripts/spreadsheet_compat/run-p6-parent-oracle.mjs ${process.argv[2] ?? 'data/build-guide-p6/offline-r3/p6-parent-oracle-r3'}`;
const near = (actual, expected, label) => assert.ok(typeof actual === 'number' && Math.abs(actual - expected) <= TOLERANCE, `${label}: expected ${expected}, got ${actual}`);

const parameter = (name, value) => ({ name, value, basis: 'fictional P6 parent oracle fixture', evidence_refs: [], rationale: 'Synthetic control input only.', uncertainty: 'Synthetic control input only.' });

const p5Candidate = {
  outcome: 'propose_forecast', method_id: 'aggregate_remaining_life_plus_additions', method_version: 'v2',
  parameters: [parameter('opening_remaining_life_years', 5), parameter('new_addition_useful_life_years', 4), parameter('new_addition_timing_fraction', 0.5), parameter('cash_ppe_additions_rate', 0.2), parameter('noncash_ppe_additions_ratio', 0.1), parameter('lease_additions_modeled', 0), parameter('tax_rate', 0.25), parameter('revenue_growth', 0.05), parameter('wacc', 0.08), parameter('terminal_growth', 0.02)],
  evidence_refs: [], rationale: 'Synthetic P5 linkage fixture.', alternatives: [], uncertainty: [], sensitivities: [], follow_up_request: null,
};

const p5Decision = {
  decision_id: 'P5-ORACLE-ASSET-DECISION-001', decision_version: 2, status: 'SYSTEM_REVIEWED_PROVISIONAL', human_approval: false,
  review_verdict: 'accept', candidate_hashes: { initial: 'oracle', followup: 'oracle' }, review_hashes: { original: 'oracle' },
  changed_parameter: 'opening_remaining_life_years', change_direction: 'fixture', review_rationale: 'Synthetic P5 linkage fixture.',
};

const segments = {
  A: { priorFy: 120, priorYtd: 90, currentYtd: 108 },
  B: { priorFy: 80, priorYtd: 50, currentYtd: 60 },
  C: { priorFy: 40, priorYtd: 25, currentYtd: 27.5 },
};
const names = ['Intelligent Cloud', 'More Personal Computing', 'Productivity and Business Processes'];
const costNames = ['cost_of_revenue', 'research_and_development', 'sales_and_marketing', 'general_and_administrative'];
const ratios = [0.4, 0.12, 0.08, 0.05];

function modelFor(aStubGrowth) {
  const driverInputs = {
    segment_growth: {
      [names[0]]: { stub: aStubGrowth, annual: Array(10).fill(0.1) },
      [names[1]]: { stub: 0.2, annual: Array(10).fill(0.05) },
      [names[2]]: { stub: 0, annual: Array(10).fill(0) },
    },
    cost_ratio: Object.fromEntries(costNames.map((line, index) => [line, { stub: ratios[index], annual: Array(10).fill(ratios[index]) }])),
    historical_anchors: Object.fromEntries(names.map((name, index) => {
      const value = segments[['A', 'B', 'C'][index]];
      return [name, { priorFy: value.priorFy, priorYtd: value.priorYtd, currentYtd: value.currentYtd }];
    })),
    source_observations_are_not_forecast_inputs: true,
  };
  const p6Review = { verdict: 'accept', evidence_strength: 'mixed', method_valid: true, source_valid: true, period_valid: true, segment_reconciliation_valid: true, cost_treatment_valid: true, no_double_count: true, concerns: ['Synthetic parent oracle.'], required_revision: null, target: 'none', rationale: 'Synthetic parent oracle.' };
  const p6Decision = { decision_id: 'P6-ORACLE-OPERATING-DECISION-R3', status: 'OFFLINE_FIXTURE', human_approval: false, review: p6Review };
  const historicalSegments = Object.fromEntries(names.map((name, index) => {
    const value = segments[['A', 'B', 'C'][index]];
    return [name, { historical_revenue: { FY2025: value.priorFy, PRIOR: value.priorYtd, CURRENT: value.currentYtd }, forecast_revenue: [], forecast_role: 'diagnostic_only_not_workbook_authority' }];
  }));
  return {
    schema_version: 'p6-msft-operating-input-v1', case: 'P6_PARENT_ORACLE', information_cutoff: 'fixture', measurement_date: 'fixture',
    packet: {
      facts: {
        opening_balance_sheet: { cash: { value: 20 }, short_term_investments: { value: 0 }, accounts_receivable: { value: 0 }, inventory: { value: 0 }, other_current_assets: { value: 0 }, operating_lease_rou: { value: 0 }, long_term_investments: { value: 0 }, goodwill: { value: 0 }, intangibles: { value: 0 }, other_noncurrent_assets: { value: 0 }, total_assets: { value: 90 }, accounts_payable: { value: 10 }, short_term_debt: { value: 20 }, long_term_debt: { value: 0 }, total_liabilities: { value: 30 }, total_equity: { value: 60 } },
        ppe_note: { net: 70, land: 10, finance_lease_net_included_in_ppe: 0 },
        calculated: { opening_depreciable_net_ppe: 60, ttm_ebit_margin: 0.5, ttm_ppe_depreciation: 8.4, ttm_cash_ppe_rate: 0.2 },
        ttm: { revenue: { value: 84 }, operating_income: { value: 42 }, dna_other: { value: 0 }, cash_ppe_payments: { value: 16.8 } },
        annual: { cash_ppe_payments: { value: 16.8 } },
        ppe_payables: { fy2025_06_30: 0, latest_2026_03_31: 0 },
      },
      evidence: [], unavailable: [],
    },
    candidate: p5Candidate,
    p5_decision: p5Decision,
    decision: { decision_id: 'P6-ORACLE-COMBINED-DECISION-R3', decision_version: 3, status: 'OFFLINE_FIXTURE', human_approval: false, p5_status: p5Decision.status, p6_status: p6Decision.status, coverage: 'Synthetic P6 parent oracle only' },
    p6_decision: p6Decision,
    operating_decision: { status: 'OFFLINE_FIXTURE', decision_id: p6Decision.decision_id, proposal: { segment_trajectories: [], cost_trajectories: [] }, review: p6Review },
    operating_forecast: {
      schema_version: 'p6-msft-operating-model-v1', repair_version: 'p6-repair-r3', forecast_authority: 'Mog formulas compiled by asset_model.mjs',
      method: { id: 'segment_revenue_growth_plus_consolidated_cost_ratios', version: 'v1' }, segments: historicalSegments,
      corporate_eliminations: { historical_revenue: {}, forecast_revenue: Array(PERIODS.length).fill(0) }, driver_inputs: driverInputs,
      embedded_ppe_baseline: { ttm_ppe_depreciation: 8.4, ttm_revenue: 84, ratio: 0.1, basis: 'fictional parent oracle', scope: 'aggregate fictional baseline' },
      decision: p6Decision, limitations: [], historical_residuals: {}, forecast_identity: {}, reconciliation: {},
    },
  };
}

const expected = {
  base: { growth: 0.1, stub: [33, 36, 15], nextRevenue: 298.4, gross: 54.6, embedded: 8.4, scheduled: 3.5775, expenses: 49.7775, op: 34.2225, ni: 25.666875, cfo: 29.244375, capex: 16.8, noncash: 1.68, cash: 32.444375, ppe: 84.9025, ap: 11.68, equity: 85.666875 },
  upside: { growth: 0.2, stub: [36, 36, 15], nextRevenue: 301.7, gross: 56.55, embedded: 8.7, scheduled: 3.598125, expenses: 51.448125, op: 35.551875, ni: 26.66390625, cfo: 30.26203125, capex: 17.4, noncash: 1.74, cash: 32.86203125, ppe: 85.541875, ap: 11.74, equity: 86.66390625 },
  downside: { growth: -0.1, stub: [27, 36, 15], nextRevenue: 291.8, gross: 50.7, embedded: 7.8, scheduled: 3.53625, expenses: 46.43625, op: 31.56375, ni: 23.6728125, cfo: 27.2090625, capex: 15.6, noncash: 1.56, cash: 31.6090625, ppe: 83.62375, ap: 11.56, equity: 83.6728125 },
};

async function runScenario(name, fixture) {
  const scenarioDir = resolve(outputDir, name);
  await mkdir(scenarioDir, { recursive: true });
  const workbookPath = resolve(scenarioDir, 'operating-model.xlsx');
  const modelPath = resolve(scenarioDir, 'model-input.json');
  await writeFile(modelPath, `${JSON.stringify(fixture, null, 2)}\n`, 'utf8');
  const handle = await buildAssetWorkbook(fixture);
  let actual;
  try {
    await handle.wb.save(workbookPath);
    const operating = await handle.wb.getSheet('Operating');
    const schedules = await handle.wb.getSheet('Schedules');
    const income = await handle.wb.getSheet('Income');
    const cash = await handle.wb.getSheet('CashFlow');
    const balance = await handle.wb.getSheet('BalanceSheet');
    const dcf = await handle.wb.getSheet('DCF');
    const value = async (sheet, address) => Number(await sheet.getValue(address));
    actual = {
      stubAmounts: await Promise.all(['B6', 'B7', 'B8'].map((address) => value(operating, address))),
      nextYearRevenue: await value(operating, 'C11'), gross: await value(operating, 'B17'), embedded: await value(operating, 'B18'), scheduled: await value(operating, 'B19'),
      expenses: await value(operating, 'B20'), op: await value(income, 'B11'), ni: await value(income, 'B15'), cfo: await value(cash, 'B9'), capex: await value(schedules, 'B12'), noncash: await value(schedules, 'B13'),
      cash: await value(cash, 'B15'), ppe: await value(balance, 'B11'), ap: await value(balance, 'B18'), equity: await value(balance, 'B23'), balanceDifference: await value(balance, 'B25'), dcf: await value(dcf, 'B7'),
      formulas: { segmentStub: await operating.getFormula('B6'), segmentNextYear: await operating.getFormula('C6'), costOfRevenue: await operating.getFormula('B13') },
    };
  } finally { handle.wb.dispose(); }
  const snapshot = await inspectAssetWorkbook(workbookPath);
  const e = expected[name];
  for (const [index, value] of actual.stubAmounts.entries()) near(value, e.stub[index], `${name} stub segment ${index}`);
  for (const [key, value] of Object.entries({ nextYearRevenue: e.nextRevenue, gross: e.gross, embedded: e.embedded, scheduled: e.scheduled, expenses: e.expenses, op: e.op, ni: e.ni, cfo: e.cfo, capex: e.capex, noncash: e.noncash, cash: e.cash, ppe: e.ppe, ap: e.ap, equity: e.equity, balanceDifference: 0 })) near(actual[key], value, `${name} ${key}`);
  assert.ok(actual.formulas.segmentStub && actual.formulas.segmentNextYear && actual.formulas.costOfRevenue, `${name} missing application-owned formula`);
  return { name, expected: e, actual, snapshot: { checks: snapshot.checks, combinedStatus: snapshot.combinedDecisionStatus, driverStatus: snapshot.p6DriverStatus }, workbookPath, modelPath };
}

await mkdir(outputDir, { recursive: true });
const results = [];
for (const [name, fixture] of [['base', modelFor(expected.base.growth)], ['upside', modelFor(expected.upside.growth)], ['downside', modelFor(expected.downside.growth)]]) results.push(await runScenario(name, fixture));
const base = results[0].actual;
const upside = results[1].actual;
const downside = results[2].actual;
for (const key of ['nextYearRevenue', 'gross', 'embedded', 'scheduled', 'expenses', 'op', 'ni', 'cfo', 'capex', 'noncash', 'cash', 'ppe', 'ap', 'equity', 'dcf']) {
  assert.ok(Math.abs(upside[key] - base[key]) > TOLERANCE, `upside ${key} did not change`);
  assert.ok(Math.abs(downside[key] - base[key]) > TOLERANCE, `downside ${key} did not change`);
}
const output = { status: 'PASS', authority: 'Mog SDK workbook formulas', oracle: 'Lunacy/runs/three-statement-dcf/phases/operating/P6_PARENT_ORACLE.md', command, scenarios: results };
await writeFile(resolve(outputDir, 'p6-parent-oracle.json'), `${JSON.stringify(output, null, 2)}\n`, 'utf8');
console.log(JSON.stringify({ status: output.status, output: resolve(outputDir, 'p6-parent-oracle.json'), scenarios: results.map((item) => ({ name: item.name, stub: item.actual.stubAmounts, nextYearRevenue: item.actual.nextYearRevenue, dcf: item.actual.dcf })) }, null, 2));
