import { createWorkbook } from '@mog-sdk/sdk';
import {
  historicalBridgeRows,
  P9_ROWS,
  p9SensitivityRows,
  readP9Snapshot,
  terminalCohortRows,
  validateValuationPolicy,
  valuationRows,
} from './valuation.mjs';

export const ENGINE_VERSION = '0.10.7';
export const MODEL_VERSION = 'p8b-msft-three-statement-v1';
export const METHOD_VERSION = 'v2';
export const TOLERANCE = 1e-8;
const OPERATING_SEGMENTS = ['Intelligent Cloud', 'More Personal Computing', 'Productivity and Business Processes'];
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

const AMOUNT_FORMAT = '#,##0.000000;(#,##0.000000);-';
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

// P6 driver cells are deliberately fixed and small enough to audit in an
// exported workbook.  B is the FY2026 stub estimate; C:L are FY2027-FY2036
// annual estimates.  Historical anchors sit in B:D, one column per segment.
export const P6_DRIVER_ROWS = Object.freeze({
  segmentGrowth: Object.freeze({
    'Intelligent Cloud': 64,
    'More Personal Computing': 65,
    'Productivity and Business Processes': 66,
  }),
  costRatio: Object.freeze({
    cost_of_revenue: 68,
    research_and_development: 69,
    sales_and_marketing: 70,
    general_and_administrative: 71,
  }),
  anchors: Object.freeze({ priorFy: 75, priorYtd: 76, currentYtd: 77 }),
});

export const OPERATING_FORMULA_ROWS = Object.freeze([6, 7, 8, 9, 10, 11, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23]);

export const P6_REQUIRED_INPUTS = Object.freeze([
  ...Object.values(P6_DRIVER_ROWS.segmentGrowth).flatMap((row) => PERIODS.map((_, index) => periodCell(index, row))),
  ...Object.values(P6_DRIVER_ROWS.costRatio).flatMap((row) => PERIODS.map((_, index) => periodCell(index, row))),
  ...Object.values(P6_DRIVER_ROWS.anchors).flatMap((row) => [`B${row}`, `C${row}`, `D${row}`]),
]);

// P7 driver cells are kept in a visible, fixed block on Inputs so source
// values, estimates and workbook what-ifs remain auditable.  B is the first
// Apr-Jun FY2026 stub; C:L are the later fiscal periods for day counts.
export const P7_DRIVER_ROWS = Object.freeze({
  dso: 82,
  dio: 83,
  dpo: 84,
  accruedCompensationMultiplier: 85,
  serverReceivableShock: 86,
  contractBillingsRatio: 87,
  contractBillingMultiplier: 88,
  contractRecognitionShare: 89,
  otherOcaResidual: 90,
  otherOclResidual: 91,
  longTermAr: 92,
  contractCurrent: 93,
  contractNoncurrent: 94,
  serverReceivables: 95,
  operatingAp: 96,
  accruedCompensation: 97,
  periodDays: 98,
  currentContractShare: 99,
  gate: 100,
  accruedCompensationBaseline: 101,
  accruedCompensationEffectiveRatio: 102,
});

export const P7_REQUIRED_INPUTS = Object.freeze([
  ...Array.from({ length: 16 }, (_, i) => `B${P7_DRIVER_ROWS.dso + i}`),
  ...PERIODS.map((_, index) => periodCell(index, P7_DRIVER_ROWS.periodDays)),
  `B${P7_DRIVER_ROWS.currentContractShare}`,
  `B${P7_DRIVER_ROWS.accruedCompensationBaseline}`,
  `B${P7_DRIVER_ROWS.accruedCompensationEffectiveRatio}`,
]);

// P8A tax drivers are deliberately visible beside the accepted P7 drivers.
// B is the scalar source/analyst anchor; B:L are the eleven reviewed paths.
export const TAX_DRIVER_ROWS = Object.freeze({
  bookTaxRate: 106,
  operatingTaxRate: 107,
  deferredShare: 108,
  currentTaxPayableClosing: 109,
  longTermTaxSettlement: 110,
  openingCurrentTaxPayable: 111,
  openingLongTermTaxLiability: 112,
  openingDeferredTaxLiability: 113,
  gate: 114,
  interestExpense: 115,
  currentTaxPayableMethod: 116,
  currentTaxPayableDays: 117,
  periodDays: 118,
});

// P8B financing drivers are kept in a separate fixed block.  Source balances,
// disclosed payment buckets and application-calibrated rates are visible here;
// workbook formulas below own all subsequent roll-forwards.
export const FINANCING_DRIVER_ROWS = Object.freeze({
  debtFace: 122,
  debtCarrying: 123,
  debtFairValue: 124,
  debtCouponRate: 125,
  debtRefinancePolicy: 126,
  debtTailPolicy: 127,
  refinanceTermYears: 128,
  refinanceFeeRate: 129,
  openingOperatingRou: 130,
  openingOperatingLiability: 131,
  openingFinancePpe: 132,
  openingFinanceLiability: 133,
  openingOperatingBookCost: 134,
  openingOperatingRate: 135,
  openingFinanceRate: 136,
  operatingWeightedRate: 137,
  financeWeightedRate: 138,
  pipelineCommitments: 139,
  pipelineFinanceShare: 140,
  pipelineOperatingLifeYears: 141,
  pipelineFinanceLifeYears: 142,
  pipelineOperatingRate: 143,
  pipelineFinanceRate: 144,
  embeddedOperatingLeaseCostProxy: 145,
  gate: 146,
  periodDays: 147,
  debtRedemption: 148,
  debtProceeds: 149,
  operatingPayment: 150,
  financePayment: 151,
  pipelineOperatingAdditions: 152,
  pipelineFinanceAdditions: 153,
  pipelineOperatingExpense: 154,
  pipelineFinanceDepreciation: 155,
  debtContraTotal: 156,
  openingCurrentDebt: 157,
  openingNoncurrentDebt: 158,
  openingOperatingCurrentLiability: 159,
  openingOperatingNoncurrentLiability: 160,
  openingFinanceCurrentLiability: 161,
  openingFinanceNoncurrentLiability: 162,
  pipelineOperatingInterest: 163,
  pipelineFinanceInterest: 164,
  pipelineOperatingPrincipal: 165,
  pipelineFinancePrincipal: 166,
  leaseBundle: 167,
  pipelineTimingPolicy: 168,
  openingFinanceLifeYears: 169,
});

// P8C equity drivers are kept after the accepted P8B block.  Policy/source
// inputs live on Inputs; calculated outputs are formula links to Equity.
export const P8C_DRIVER_ROWS = Object.freeze({
  sbcRatio: 172,
  existingAwardUnits: 173,
  existingUnrecognizedCost: 174,
  existingServiceYears: 175,
  existingClaimPrice: 176,
  settlementPrice: 177,
  withholdingRate: 178,
  cashIssuanceRatio: 179,
  repurchaseRatio: 180,
  repurchaseAuthorization: 181,
  dividendPerShareQuarter: 182,
  dividendQuartersStub: 183,
  dividendQuartersAnnual: 184,
  gate: 185,
  periodDays: 186,
  bookSbc: 187,
  existingServiceCost: 188,
  newSbc: 189,
  grossExistingUnits: 190,
  grossNewUnits: 191,
  withheldUnits: 192,
  netDeliveredUnits: 193,
  cashIssuance: 194,
  issuanceUnits: 195,
  programTarget: 196,
  programCash: 197,
  programUnits: 198,
  programApicBasis: 199,
  dividendDeclaration: 200,
  dividendPayableOpening: 201,
  dividendPayableClosing: 202,
  dividendCashPaid: 203,
  pointSharesOpening: 204,
  pointSharesClosing: 205,
  basicWeightedShares: 206,
  dilutedIncrement: 207,
  basicEps: 208,
  dilutedEps: 209,
  valuationEbit: 210,
  normalizedTax: 211,
  valuationUfcf: 212,
  cfoUfcf: 213,
  withholdingCash: 214,
  apicClosing: 215,
  retainedEarningsClosing: 216,
  aociClosing: 217,
  totalEquity: 218,
  authorizationRemaining: 219,
  embeddedSbcRatio: 220,
  deliveryTiming: 221,
  issuanceTiming: 222,
  repurchaseTiming: 223,
  serviceDays: 224,
  totalServiceDays: 225,
  openingDividendPayable: 226,
  openingPointShares: 227,
  openingApic: 228,
  openingRetainedEarnings: 229,
  openingAoci: 230,
  openingTotalEquity: 231,
});

// P8D remaining-balance inputs.  The block is intentionally visible after
// P8C so the source pools, selected estimates and all period mechanics remain
// auditable in the exported workbook.
export const P8D_DRIVER_ROWS = Object.freeze({
  otherInvestmentMultiplier: 234,
  cashIncomeYield: 235,
  intangibleTailLifeYears: 236,
  goodwillImpairment: 237,
  unfundedCommitmentValueFraction: 238,
  legalStress: 239,
  incrementalNetDtaValue: 240,
  unrealizedInvestmentGain: 241,
  openingCash: 242,
  openingShortTermInvestments: 243,
  openingEquityOtherInvestments: 244,
  openingFinancingReceivables: 245,
  openingGoodwill: 246,
  openingIntangibles: 247,
  openingOtherCurrentAssetsResidual: 248,
  openingOtherLongTermAssets: 249,
  openingOtherCurrentLiabilityResidual: 250,
  openingOtherLongTermLiabilityResidual: 251,
  openingDeferredTaxLiability: 252,
  gate: 253,
  investmentCarrying: 254,
  investmentAdditions: 255,
  cashIncome: 256,
  noncashGain: 257,
  investmentValue: 258,
  intangibleOpening: 259,
  intangibleAmortization: 260,
  intangibleClosing: 261,
  goodwillClosing: 262,
  dtaValue: 263,
  commitmentFundingCfi: 264,
  coverage: 265,
  embeddedIntangibleRatio: 266,
  unidentifiedDnaOther: 267,
  otherInvestmentPool: 268,
  knownInvestmentValue: 269,
  unfundedCommitment: 270,
  intangibleStubAmortization: 271,
  intangibleFy27Amortization: 272,
  intangibleFy28Amortization: 273,
  intangibleFy29Amortization: 274,
  intangibleFy30Amortization: 275,
  intangibleTailPool: 276,
  identifiedLongTermDebtInvestments: 277,
  periodDays: 278,
});

export const P8D_OUTPUT_ROWS = Object.freeze({
  investmentOpening: 6,
  investmentAdditions: 7,
  cashIncome: 8,
  noncashGain: 9,
  investmentClosing: 10,
  investmentValue: 11,
  embeddedAmortizationRemoved: 12,
  intangibleOpening: 13,
  intangibleAmortization: 14,
  intangibleClosing: 15,
  goodwillOpening: 16,
  goodwillImpairment: 17,
  goodwillClosing: 18,
  dtaValue: 19,
  commitmentFunding: 20,
  legalStress: 21,
  coverage: 22,
  unidentifiedDnaOther: 23,
  commitmentRightsValue: 24,
  commitmentNetMeasurementAdjustment: 25,
  fundingStatus: 26,
  residualMovementDifference: 27,
});

const P8D_REQUIRED_INPUTS = Object.freeze([
  ...['otherInvestmentMultiplier', 'cashIncomeYield', 'intangibleTailLifeYears', 'goodwillImpairment', 'unfundedCommitmentValueFraction', 'legalStress', 'incrementalNetDtaValue', 'unrealizedInvestmentGain', 'openingCash', 'openingShortTermInvestments', 'openingEquityOtherInvestments', 'openingFinancingReceivables', 'openingGoodwill', 'openingIntangibles', 'openingOtherCurrentAssetsResidual', 'openingOtherLongTermAssets', 'openingOtherCurrentLiabilityResidual', 'openingOtherLongTermLiabilityResidual', 'openingDeferredTaxLiability'].map((name) => `B${P8D_DRIVER_ROWS[name]}`),
  ...['otherInvestmentPool', 'knownInvestmentValue', 'unfundedCommitment'].map((name) => `B${P8D_DRIVER_ROWS[name]}`),
  ...['intangibleStubAmortization', 'intangibleFy27Amortization', 'intangibleFy28Amortization', 'intangibleFy29Amortization', 'intangibleFy30Amortization', 'intangibleTailPool', 'identifiedLongTermDebtInvestments'].map((name) => `B${P8D_DRIVER_ROWS[name]}`),
  ...PERIODS.map((_, index) => `${periodColumn(index)}${P8D_DRIVER_ROWS.periodDays}`),
  ...['investmentCarrying', 'investmentAdditions', 'cashIncome', 'noncashGain', 'investmentValue', 'intangibleOpening', 'intangibleAmortization', 'intangibleClosing', 'goodwillClosing', 'dtaValue', 'commitmentFundingCfi'].flatMap((name) => PERIODS.map((_, index) => `${periodColumn(index)}${P8D_DRIVER_ROWS[name]}`)),
  `B${P8D_DRIVER_ROWS.gate}`, `B${P8D_DRIVER_ROWS.embeddedIntangibleRatio}`, `B${P8D_DRIVER_ROWS.unidentifiedDnaOther}`,
]);

const P8C_LINKED_ROWS = Object.freeze([
  'bookSbc', 'existingServiceCost', 'newSbc', 'grossExistingUnits',
  'grossNewUnits', 'withheldUnits', 'netDeliveredUnits', 'cashIssuance',
  'issuanceUnits', 'programTarget', 'programCash', 'programUnits',
  'programApicBasis', 'dividendDeclaration', 'dividendPayableOpening',
  'dividendPayableClosing', 'dividendCashPaid', 'pointSharesOpening',
  'pointSharesClosing', 'basicWeightedShares', 'dilutedIncrement', 'basicEps',
  'dilutedEps', 'valuationEbit', 'normalizedTax', 'valuationUfcf', 'cfoUfcf',
  'withholdingCash', 'apicClosing', 'retainedEarningsClosing', 'aociClosing',
  'totalEquity', 'authorizationRemaining',
]);

const P8C_REQUIRED_INPUTS = Object.freeze([
  ...['sbcRatio', 'existingAwardUnits', 'existingUnrecognizedCost', 'existingServiceYears', 'existingClaimPrice', 'settlementPrice', 'withholdingRate', 'cashIssuanceRatio', 'repurchaseRatio', 'repurchaseAuthorization', 'dividendPerShareQuarter', 'dividendQuartersStub', 'dividendQuartersAnnual', 'embeddedSbcRatio', 'deliveryTiming', 'issuanceTiming', 'repurchaseTiming', 'totalServiceDays', 'openingDividendPayable', 'openingPointShares', 'openingApic', 'openingRetainedEarnings', 'openingAoci', 'openingTotalEquity'].map((name) => `B${P8C_DRIVER_ROWS[name]}`),
  ...['periodDays', 'serviceDays'].flatMap((name) => PERIODS.map((_, index) => `${periodColumn(index)}${P8C_DRIVER_ROWS[name]}`)),
]);

const FINANCING_REQUIRED_INPUTS = Object.freeze([
  ...[
    'debtFace', 'debtCarrying', 'debtFairValue', 'debtCouponRate',
    'debtRefinancePolicy', 'debtTailPolicy', 'refinanceTermYears',
    'refinanceFeeRate', 'openingOperatingRou', 'openingOperatingLiability',
    'openingFinancePpe', 'openingFinanceLiability', 'openingOperatingBookCost',
    'openingOperatingRate', 'openingFinanceRate', 'operatingWeightedRate',
    'financeWeightedRate', 'pipelineCommitments', 'pipelineFinanceShare',
    'pipelineOperatingLifeYears', 'pipelineFinanceLifeYears',
    'pipelineOperatingRate', 'pipelineFinanceRate',
    'embeddedOperatingLeaseCostProxy', 'leaseBundle', 'pipelineTimingPolicy',
    'openingFinanceLifeYears',
    'debtContraTotal', 'openingCurrentDebt',
    'openingNoncurrentDebt', 'openingOperatingCurrentLiability',
    'openingOperatingNoncurrentLiability', 'openingFinanceCurrentLiability',
    'openingFinanceNoncurrentLiability',
  ].map((name) => `B${FINANCING_DRIVER_ROWS[name]}`),
  ...[
    'periodDays', 'debtRedemption', 'debtProceeds', 'operatingPayment',
    'financePayment', 'pipelineOperatingAdditions', 'pipelineFinanceAdditions',
    'pipelineOperatingExpense', 'pipelineFinanceDepreciation',
    'pipelineOperatingInterest', 'pipelineFinanceInterest',
    'pipelineOperatingPrincipal', 'pipelineFinancePrincipal',
  ].flatMap((name) => PERIODS.map((_, index) => `${periodColumn(index)}${FINANCING_DRIVER_ROWS[name]}`)),
]);

const TAX_COMMON_REQUIRED_INPUTS = Object.freeze([
  `B${TAX_DRIVER_ROWS.bookTaxRate}`,
  `B${TAX_DRIVER_ROWS.operatingTaxRate}`,
  ...PERIODS.flatMap((_, index) => [`${periodColumn(index)}${TAX_DRIVER_ROWS.deferredShare}`, `${periodColumn(index)}${TAX_DRIVER_ROWS.longTermTaxSettlement}`]),
  `B${TAX_DRIVER_ROWS.openingCurrentTaxPayable}`,
  `B${TAX_DRIVER_ROWS.openingLongTermTaxLiability}`,
  `B${TAX_DRIVER_ROWS.openingDeferredTaxLiability}`,
  `B${TAX_DRIVER_ROWS.interestExpense}`,
  `B${TAX_DRIVER_ROWS.currentTaxPayableMethod}`,
  ...PERIODS.map((_, index) => `${periodColumn(index)}${TAX_DRIVER_ROWS.periodDays}`),
]);

export const TAX_REQUIRED_INPUTS = Object.freeze([
  ...TAX_COMMON_REQUIRED_INPUTS,
  `B${TAX_DRIVER_ROWS.currentTaxPayableDays}`,
  ...PERIODS.map((_, index) => `${periodColumn(index)}${TAX_DRIVER_ROWS.currentTaxPayableClosing}`),
]);

const DEFAULT_TAX_PERIOD_DAYS = Object.freeze([91, 365, 366, 365, 365, 365, 366, 365, 365, 365, 366]);

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

function asParameters(candidate) {
  const result = {};
  for (const parameter of candidate.parameters ?? []) {
    if (Object.hasOwn(result, parameter.name)) throw new Error(`Duplicate parameter: ${parameter.name}`);
    if (typeof parameter.value !== 'number' || !Number.isFinite(parameter.value)) throw new Error(`Missing/nonnumeric parameter: ${parameter.name}`);
    result[parameter.name] = parameter.value;
  }
  return result;
}

function factValue(packet, key) {
  const fact = packet.facts.opening_balance_sheet[key];
  if (!fact || typeof fact.value !== 'number' || !Number.isFinite(fact.value)) throw new Error(`Missing opening balance fact: ${key}`);
  return fact.value;
}

function ttmValue(packet, key) {
  const fact = packet.facts.ttm[key];
  if (!fact || typeof fact.value !== 'number' || !Number.isFinite(fact.value)) throw new Error(`Missing TTM fact: ${key}`);
  return fact.value;
}

function inputsFromModel(model) {
  const packet = model.packet;
  const params = asParameters(model.candidate);
  const ppe = packet.facts.ppe_note;
  const calculated = packet.facts.calculated;
  const values = {
    openingCash: factValue(packet, 'cash'),
    shortTermInvestments: factValue(packet, 'short_term_investments'),
    accountsReceivable: factValue(packet, 'accounts_receivable'),
    inventory: factValue(packet, 'inventory'),
    otherCurrentAssets: factValue(packet, 'other_current_assets'),
    openingNetPPE: ppe.net,
    openingLand: ppe.land,
    openingDepreciableNetPPE: calculated.opening_depreciable_net_ppe,
    operatingLeaseRou: factValue(packet, 'operating_lease_rou'),
    longTermInvestments: factValue(packet, 'long_term_investments'),
    goodwill: factValue(packet, 'goodwill'),
    intangibles: factValue(packet, 'intangibles'),
    otherNoncurrentAssets: factValue(packet, 'other_noncurrent_assets'),
    totalAssets: factValue(packet, 'total_assets'),
    accountsPayable: factValue(packet, 'accounts_payable'),
    shortTermDebt: factValue(packet, 'short_term_debt'),
    longTermDebt: factValue(packet, 'long_term_debt'),
    totalLiabilities: factValue(packet, 'total_liabilities'),
    totalEquity: factValue(packet, 'total_equity'),
    remainingLife: params.opening_remaining_life_years,
    newUsefulLife: params.new_addition_useful_life_years,
    timingFraction: params.new_addition_timing_fraction,
    cashPpeRate: params.cash_ppe_additions_rate,
    noncashRatio: params.noncash_ppe_additions_ratio,
    leaseAdditions: params.lease_additions_modeled,
    taxRate: params.tax_rate,
    revenueGrowth: params.revenue_growth,
    wacc: params.wacc,
    terminalGrowth: params.terminal_growth,
    ttmRevenue: ttmValue(packet, 'revenue'),
    ttmEbit: ttmValue(packet, 'operating_income'),
    ttmEbitMargin: calculated.ttm_ebit_margin,
    ttmDnaOther: ttmValue(packet, 'dna_other'),
    ttmPpeDepreciation: calculated.ttm_ppe_depreciation,
    ttmCashPpe: ttmValue(packet, 'cash_ppe_payments'),
    ttmCashPpeRate: calculated.ttm_cash_ppe_rate,
    fy25CashPpe: packet.facts.annual.cash_ppe_payments.value,
    fy25PpePayables: packet.facts.ppe_payables.fy2025_06_30,
    q3PpePayables: packet.facts.ppe_payables.latest_2026_03_31,
    financeLeaseNet: ppe.finance_lease_net_included_in_ppe,
  };
  if (model.financing_forecast) values.financing = financingForecast(model);
  for (const [key, value] of Object.entries(values)) {
    if (key === 'financing') continue;
    if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error(`Model input is missing/nonnumeric: ${key}`);
  }
  if (values.openingNetPPE - values.openingLand !== values.openingDepreciableNetPPE) throw new Error('Opening PP&E base does not reconcile');
  if (values.leaseAdditions !== 0) throw new Error('P5 lease additions must remain zero pending P8B');
  if (values.terminalGrowth >= values.wacc) throw new Error('Terminal growth must be below WACC');
  if (values.remainingLife <= 0 || values.newUsefulLife <= 0) throw new Error('Asset lives must be positive');
  if (model.candidate.method_id !== 'aggregate_remaining_life_plus_additions') throw new Error('Unsupported asset method');
  if (model.candidate.method_version !== METHOD_VERSION) throw new Error('Unsupported asset method version');
  return values;
}

const REQUIRED_SCALARS = [...Array.from({ length: 19 }, (_, i) => `B${i + 6}`), ...Array.from({ length: 10 }, (_, i) => `B${i + 29}`), ...Array.from({ length: 10 }, (_, i) => `B${i + 43}`), 'B57', 'B59'];
const BASE_REQUIRED_INPUTS = [...REQUIRED_SCALARS, ...PERIODS.flatMap((_, i) => [`${periodColumn(i)}55`, `${periodColumn(i)}58`])];
export const REQUIRED_INPUTS = BASE_REQUIRED_INPUTS;

function requiredInputs(model) {
  const required = [...BASE_REQUIRED_INPUTS];
  if (model?.operating_forecast) required.push(...P6_REQUIRED_INPUTS);
  if (model?.working_capital_forecast) required.push(...P7_REQUIRED_INPUTS);
  if (model?.tax_forecast) required.push(...taxRequiredInputs(model));
  if (model?.financing_forecast) required.push(...FINANCING_REQUIRED_INPUTS);
  if (model?.equity_forecast) required.push(...P8C_REQUIRED_INPUTS);
  if (model?.other_balances_forecast) required.push(...P8D_REQUIRED_INPUTS);
  return required;
}

const P11_REVIEW_SCHEMA = 'p11-review-metadata-v1';
const P11_AREAS = Object.freeze([
  'revenue', 'operating_costs', 'ppe_capex', 'intangibles',
  'working_capital', 'taxes', 'debt_interest', 'leases',
  'sbc_equity', 'nonoperating', 'cash_flow_cash', 'dcf_terminal',
]);
const P11_VALUATION_INPUTS = Object.freeze(Array.from({ length: 21 }, (_, index) => `Valuation!B${index + 12}`));
const P11_DECISION_AREA_START = 14;
const P11_EVIDENCE_SOURCE_START = 4;

function reviewText(value, field, { allowEmpty = false } = {}) {
  if (typeof value !== 'string' || (!allowEmpty && value.trim().length === 0)) throw new Error(`P11 review metadata missing ${field}`);
  return value;
}

function reviewTextList(value, field, { allowEmpty = true } = {}) {
  if (!Array.isArray(value) || (!allowEmpty && value.length === 0) || value.some((item) => typeof item !== 'string')) throw new Error(`P11 review metadata invalid ${field}`);
  return value;
}

function reviewNarrative(value, field) {
  if (typeof value === 'string') return reviewText(value, field);
  return reviewTextList(value, field, { allowEmpty: false }).join('; ');
}

function validatedReviewMetadata(model) {
  const metadata = model.review_metadata;
  if (metadata == null) return null;
  if (metadata.schema_version !== P11_REVIEW_SCHEMA) throw new Error('Unsupported P11 review metadata schema');
  const review = metadata.review ?? {};
  const states = metadata.states ?? {};
  const bindings = metadata.bindings ?? {};
  const provenance = metadata.provenance ?? {};
  const narrative = metadata.narrative ?? {};
  for (const field of ['id', 'version', 'verdict']) reviewText(review[field], `review.${field}`);
  if (review.verdict !== 'accept') throw new Error('P11 published review metadata must be accepted');
  for (const field of ['execution', 'mechanical', 'coverage', 'analytical', 'budget']) reviewText(states[field], `states.${field}`);
  if (states.human !== false) throw new Error('P11 human approval must remain false');
  for (const field of ['selected_model_sha256', 'financial_snapshot_sha256', 'review_request_sha256', 'review_response_sha256', 'source_context_sha256']) {
    if (!/^[a-f0-9]{64}$/.test(reviewText(bindings[field], `bindings.${field}`))) throw new Error(`P11 review metadata invalid bindings.${field}`);
  }
  for (const field of ['run_id', 'authoritative_version', 'exported_at']) reviewText(provenance[field], `provenance.${field}`);
  for (const field of ['summary', 'key_drivers', 'cash_vs_ufcf', 'limitations']) reviewNarrative(narrative[field], `narrative.${field}`);

  if (!Array.isArray(metadata.sources) || metadata.sources.length === 0) throw new Error('P11 review metadata requires sources');
  const sourceIds = new Set();
  for (const source of metadata.sources) {
    const sourceId = reviewText(source.source_id, 'sources.source_id');
    if (sourceIds.has(sourceId)) throw new Error(`P11 duplicate source ID: ${sourceId}`);
    sourceIds.add(sourceId);
    for (const field of ['period', 'cutoff', 'kind', 'excerpt', 'source_file', 'locator']) reviewText(source[field], `sources.${sourceId}.${field}`, { allowEmpty: field === 'excerpt' });
    if (!/^[a-f0-9]{64}$/.test(reviewText(source.sha256, `sources.${sourceId}.sha256`))) throw new Error(`P11 review metadata invalid source hash: ${sourceId}`);
  }

  if (!Array.isArray(metadata.areas) || metadata.areas.length !== P11_AREAS.length) throw new Error('P11 review metadata must cover exactly 12 areas');
  const areaIds = new Set();
  for (const area of metadata.areas) {
    const areaId = reviewText(area.area, 'areas.area');
    if (!P11_AREAS.includes(areaId) || areaIds.has(areaId)) throw new Error(`P11 invalid or duplicate review area: ${areaId}`);
    areaIds.add(areaId);
    reviewText(area.outcome, `areas.${areaId}.outcome`);
    reviewText(area.basis, `areas.${areaId}.basis`);
    reviewTextList(area.changed_dependencies, `areas.${areaId}.changed_dependencies`);
    reviewTextList(area.decision_refs, `areas.${areaId}.decision_refs`, { allowEmpty: false });
    const refs = reviewTextList(area.source_refs, `areas.${areaId}.source_refs`, { allowEmpty: false });
    reviewTextList(area.limitations, `areas.${areaId}.limitations`);
    if (refs.some((sourceId) => !sourceIds.has(sourceId))) throw new Error(`P11 unresolved source reference for area: ${areaId}`);
  }
  if (P11_AREAS.some((area) => !areaIds.has(area))) throw new Error('P11 review metadata area coverage incomplete');

  const allowedInputs = new Set([...requiredInputs(model).map((address) => `Inputs!${address}`), ...P11_VALUATION_INPUTS]);
  const materialInputs = metadata.material_inputs ?? [];
  if (!Array.isArray(materialInputs)) throw new Error('P11 review metadata invalid material_inputs');
  const materialAddresses = new Set();
  for (const input of materialInputs) {
    const address = reviewText(input.address, 'material_inputs.address');
    if (!allowedInputs.has(address) || materialAddresses.has(address)) throw new Error(`P11 invalid or duplicate material input address: ${address}`);
    materialAddresses.add(address);
    for (const field of ['label', 'units', 'classification', 'area', 'rationale', 'caveat']) reviewText(input[field], `material_inputs.${address}.${field}`, { allowEmpty: field === 'caveat' });
    if (!P11_AREAS.includes(input.area)) throw new Error(`P11 invalid material input area: ${input.area}`);
    reviewTextList(input.decision_refs, `material_inputs.${address}.decision_refs`, { allowEmpty: false });
    const refs = reviewTextList(input.source_refs, `material_inputs.${address}.source_refs`, { allowEmpty: false });
    if (refs.some((sourceId) => !sourceIds.has(sourceId))) throw new Error(`P11 unresolved material input source: ${address}`);
    if (!['number', 'string', 'boolean'].includes(typeof input.exported_value)) throw new Error(`P11 invalid exported input value: ${address}`);
  }
  return metadata;
}

function taxRequiredInputs(model) {
  const method = model?.tax_forecast?.inputs?.current_tax_payable_method;
  const required = [...TAX_COMMON_REQUIRED_INPUTS];
  if (method === 'source_anchored_payable_days') required.push(`B${TAX_DRIVER_ROWS.currentTaxPayableDays}`);
  else if (method === 'explicit_closing_balance') required.push(...PERIODS.map((_, index) => `${periodColumn(index)}${TAX_DRIVER_ROWS.currentTaxPayableClosing}`));
  else required.push(`B${TAX_DRIVER_ROWS.currentTaxPayableDays}`, ...PERIODS.map((_, index) => `${periodColumn(index)}${TAX_DRIVER_ROWS.currentTaxPayableClosing}`));
  return required;
}

function p6DriverConditions() {
  return [
    'COUNT(B64:L66)=33', 'COUNT(B68:L71)=44', 'COUNT(B75:D77)=9',
    'MIN(B64:L66)>=-1', 'MAX(B64:L66)<=1', 'MIN(B68:L71)>=0', 'MAX(B68:L71)<=1', 'MIN(B75:D77)>=0',
  ];
}

function p6DriverGate() {
  return `=IFERROR(IF(AND(${p6DriverConditions().join(',')}),"PASS","FAIL"),"FAIL")`;
}

function inputGate(model) {
  const required = requiredInputs(model);
  const numeric = ['COUNT(B6:B24)=19', 'COUNT(B29:B38)=10', 'COUNT(B43:B52)=10', 'COUNT(B57)=1', 'COUNT(B59)=1', 'COUNT(B55:L55)=11', 'COUNT(B58:L58)=11'];
  const valid = ['B29>0', 'B30>0', 'B31>=0', 'B31<=1', 'B32>=0', 'B33>=0', 'B33<=1', 'B34=0', 'B35>=0', 'B35<=1', 'B37>0', 'B38>=0', 'B38<B37', 'B11>=B12', 'B12>=0', 'B43>0', 'B57>=0', 'B59>=0', 'MIN(B55:L55)>=0', 'MIN(B58:L58)>=0'];
  const conditions = [...valid];
  if (model?.operating_forecast) conditions.push(...p6DriverConditions());
  if (model?.working_capital_forecast) conditions.push(...p7DriverConditions());
  if (model?.tax_forecast) conditions.push(`B${TAX_DRIVER_ROWS.gate}="PASS"`);
  if (model?.financing_forecast) conditions.push(`B${FINANCING_DRIVER_ROWS.gate}="PASS"`);
  if (model?.equity_forecast) conditions.push(`B${P8C_DRIVER_ROWS.gate}="PASS"`);
  if (model?.other_balances_forecast) conditions.push(`B${P8D_DRIVER_ROWS.gate}="PASS"`);
  return `=IFERROR(IF(AND(${[...numeric, ...conditions].join(',')}),"PASS","FAIL"),"FAIL")`;
}

function numericDriver(value, name) {
  if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error(`P6 required driver ${name} is missing/non-numeric`);
  return value;
}

function driverArray(value, name, minimum, maximum) {
  if (!Array.isArray(value) || value.length !== 10) throw new Error(`P6 required driver ${name} must contain ten annual values`);
  return value.map((item, index) => {
    const number = numericDriver(item, `${name}[${index}]`);
    if (number < minimum || number > maximum) throw new Error(`P6 required driver ${name}[${index}] is outside [${minimum},${maximum}]`);
    return number;
  });
}

function operatingDriverInputs(model) {
  const operating = model.operating_forecast;
  if (!operating) throw new Error('P6 operating forecast is missing');
  const proposal = model.operating_decision?.proposal ?? model.p6_decision?.proposal;
  const proposalSegments = new Map((proposal?.segment_trajectories ?? []).map((item) => [item.segment, item]));
  const proposalCosts = new Map((proposal?.cost_trajectories ?? []).map((item) => [item.cost_line, item]));
  const configured = operating.driver_inputs ?? {};
  const configuredSegments = configured.segment_growth ?? {};
  const configuredCosts = configured.cost_ratio ?? {};
  const configuredAnchors = configured.historical_anchors ?? {};
  const segmentGrowth = {};
  const anchors = {};
  for (const [index, segment] of OPERATING_SEGMENTS.entries()) {
    const trajectory = proposalSegments.get(segment) ?? {};
    const input = configuredSegments[segment] ?? {};
    const stub = numericDriver(input.stub ?? trajectory.stub_growth, `${segment} stub growth`);
    if (stub < -1 || stub > 1) throw new Error(`P6 required driver ${segment} stub growth is outside [-1,1]`);
    const annual = driverArray(input.annual ?? trajectory.annual_growth, `${segment} annual growth`, -1, 1);
    segmentGrowth[segment] = { stub, annual };
    const history = configuredAnchors[segment] ?? operating.segments?.[segment]?.historical_revenue ?? {};
    anchors[segment] = {
      priorFy: numericDriver(history.priorFy ?? history.FY2025, `${segment} prior FY2025 revenue`),
      priorYtd: numericDriver(history.priorYtd ?? history.PRIOR, `${segment} prior comparable YTD revenue`),
      currentYtd: numericDriver(history.currentYtd ?? history.CURRENT, `${segment} current comparable YTD revenue`),
      column: columnName(2 + index),
    };
  }
  const costRatio = {};
  for (const line of ['cost_of_revenue', 'research_and_development', 'sales_and_marketing', 'general_and_administrative']) {
    const trajectory = proposalCosts.get(line) ?? {};
    const input = configuredCosts[line] ?? {};
    const stub = numericDriver(input.stub ?? trajectory.stub_ratio, `${line} stub ratio`);
    if (stub < 0 || stub > 1) throw new Error(`P6 required driver ${line} stub ratio is outside [0,1]`);
    const annual = driverArray(input.annual ?? trajectory.annual_ratio, `${line} annual ratio`, 0, 1);
    costRatio[line] = { stub, annual };
  }
  return { segmentGrowth, costRatio, anchors };
}

function p7SourceLockedParameters(model) {
  const packet = model.working_capital_packet;
  const bridge = packet?.contract_bridge;
  const balances = packet?.balances;
  const number = (value, name) => {
    if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error(`P7 source-locked parameter ${name} is missing/non-numeric`);
    return value;
  };
  const recognized = number(bridge?.recognized_revenue, 'recognized revenue');
  const comparable = number(bridge?.comparable_nine_month_revenue, 'comparable nine-month revenue');
  const ttmRevenue = number(packet?.ttm_revenue, 'TTM revenue');
  const accruedCompensation = number(balances?.accrued_compensation?.Q3FY2026, 'opening accrued compensation');
  const current = number(balances?.contract_liability_current?.Q3FY2026, 'current contract liability');
  const total = number(balances?.contract_liability_total_calculated?.Q3FY2026, 'total contract liability');
  if (comparable <= 0 || total <= 0 || ttmRevenue <= 0) throw new Error('P7 source-locked denominators must be positive');
  return {
    contractBillingsRatio: 1,
    contractRecognitionShare: recognized / comparable,
    currentContractShare: current / total,
    accruedCompensationBaseline: accruedCompensation / ttmRevenue,
  };
}

function workingCapitalInputs(model) {
  const workingCapital = model.working_capital_forecast;
  if (!workingCapital) throw new Error('P7 working-capital forecast is missing');
  const input = workingCapital.inputs ?? {};
  const locked = p7SourceLockedParameters(model);
  const suppliedLocks = {
    contract_billings_to_recognition: locked.contractBillingsRatio,
    contract_recognition_share: locked.contractRecognitionShare,
    current_contract_presentation_share: locked.currentContractShare,
    accrued_compensation_baseline: locked.accruedCompensationBaseline,
  };
  for (const [name, expected] of Object.entries(suppliedLocks)) {
    if (Object.hasOwn(input, name)) {
      const supplied = input[name];
      if (typeof supplied !== 'number' || !Number.isFinite(supplied)) throw new Error(`P7 source-locked parameter ${name} is missing/non-numeric`);
      if (Math.abs(supplied - expected) > TOLERANCE) throw new Error(`P7 source-locked parameter ${name} differs from the packet-derived value`);
    }
  }
  const number = (name, minimum = null, maximum = null) => {
    const value = input[name];
    if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error(`P7 required driver ${name} is missing/non-numeric`);
    if (minimum !== null && value < minimum) throw new Error(`P7 required driver ${name} is below its bound`);
    if (maximum !== null && value > maximum) throw new Error(`P7 required driver ${name} is above its bound`);
    return value;
  };
  const effectiveRatio = locked.accruedCompensationBaseline * number('accrued_compensation_multiplier', 0.8, 1.2);
  if (Object.hasOwn(input, 'accrued_compensation_effective_ratio')) {
    const supplied = input.accrued_compensation_effective_ratio;
    if (typeof supplied !== 'number' || !Number.isFinite(supplied)) throw new Error('P7 accrued_compensation_effective_ratio is missing/non-numeric');
    if (Math.abs(supplied - effectiveRatio) > TOLERANCE) throw new Error('P7 accrued_compensation_effective_ratio differs from baseline times multiplier');
  }
  const periods = workingCapital.periods ?? [];
  if (periods.length !== PERIODS.length) throw new Error('P7 period metadata must contain eleven periods');
  const days = periods.map((period, index) => {
    const value = period?.days;
    if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error(`P7 period days are invalid at ${index}`);
    if (!Number.isInteger(value) || value <= 0) throw new Error(`P7 period days are invalid at ${index}`);
    return value;
  });
  return {
    dso: number('current_ar_dso', 0), dio: number('inventory_dio', 0), dpo: number('operating_ap_dpo', 0),
    accruedCompensationBaseline: locked.accruedCompensationBaseline, accruedCompensationMultiplier: number('accrued_compensation_multiplier', 0.8, 1.2), accruedCompensationEffectiveRatio: effectiveRatio, serverReceivableShock: number('server_receivable_change_first_stub', -0.2, 0.2),
    contractBillingsRatio: locked.contractBillingsRatio, contractBillingMultiplier: number('contract_billing_multiplier_first_stub', 0.9, 1.1),
    contractRecognitionShare: locked.contractRecognitionShare, otherOcaResidual: number('opening_other_oca_residual', 0), otherOclResidual: number('opening_other_ocl_residual', 0),
    longTermAr: number('opening_long_term_ar', 0), contractCurrent: number('opening_contract_current', 0), contractNoncurrent: number('opening_contract_noncurrent', 0),
    serverReceivables: number('opening_server_receivables', 0), operatingAp: number('opening_operating_ap', 0), accruedCompensation: number('opening_accrued_compensation', 0),
    days, currentContractShare: locked.currentContractShare,
  };
}

function p7DriverConditions() {
  return [
    `COUNT(B${P7_DRIVER_ROWS.dso}:B${P7_DRIVER_ROWS.accruedCompensation})=16`,
    `COUNT(B${P7_DRIVER_ROWS.periodDays}:L${P7_DRIVER_ROWS.periodDays})=11`,
    `COUNT(B${P7_DRIVER_ROWS.currentContractShare})=1`,
    `COUNT(B${P7_DRIVER_ROWS.accruedCompensationBaseline})=1`,
    `COUNT(B${P7_DRIVER_ROWS.accruedCompensationEffectiveRatio})=1`,
    `MIN(B${P7_DRIVER_ROWS.periodDays}:L${P7_DRIVER_ROWS.periodDays})>0`,
    `B${P7_DRIVER_ROWS.dso}>=0`, `B${P7_DRIVER_ROWS.dio}>=0`, `B${P7_DRIVER_ROWS.dpo}>=0`,
    `B${P7_DRIVER_ROWS.accruedCompensationMultiplier}>=0.8`, `B${P7_DRIVER_ROWS.accruedCompensationMultiplier}<=1.2`,
    `B${P7_DRIVER_ROWS.accruedCompensationBaseline}>=0`, `B${P7_DRIVER_ROWS.accruedCompensationEffectiveRatio}>=0`,
    `B${P7_DRIVER_ROWS.serverReceivableShock}>=-0.2`, `B${P7_DRIVER_ROWS.serverReceivableShock}<=0.2`,
    `B${P7_DRIVER_ROWS.contractBillingsRatio}>=0.9`, `B${P7_DRIVER_ROWS.contractBillingsRatio}<=1.1`,
    `B${P7_DRIVER_ROWS.contractBillingMultiplier}>=0.9`, `B${P7_DRIVER_ROWS.contractBillingMultiplier}<=1.1`,
    `B${P7_DRIVER_ROWS.contractRecognitionShare}>0`, `B${P7_DRIVER_ROWS.contractRecognitionShare}<=1`,
    `B${P7_DRIVER_ROWS.currentContractShare}>0`, `B${P7_DRIVER_ROWS.currentContractShare}<=1`,
  ];
}

function p7DriverGate() {
  return `=IFERROR(IF(AND(${p7DriverConditions().join(',')}),"PASS","FAIL"),"FAIL")`;
}

function taxForecastInputs(model) {
  const tax = model.tax_forecast;
  if (!tax) throw new Error('P8A tax forecast is missing');
  const input = tax.inputs ?? {};
  const source = model.packet?.facts?.opening_balance_sheet ?? {};
  const sourceNumber = (key, name) => {
    const item = source[key];
    if (!item || typeof item.value !== 'number' || !Number.isFinite(item.value)) throw new Error(`P8A source opening fact ${name} is missing/non-numeric`);
    return item.value;
  };
  const numeric = (value, name) => {
    if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error(`P8A required input ${name} is missing/non-numeric`);
    return value;
  };
  const array = (value, name) => {
    if (!Array.isArray(value) || value.length !== PERIODS.length) throw new Error(`P8A required input ${name} must contain eleven values`);
    return value.map((item, index) => numeric(item, `${name}[${index}]`));
  };
  const openingCurrent = sourceNumber('short_term_taxes', 'current tax payable');
  const openingLongTerm = sourceNumber('long_term_taxes', 'long-term tax liability');
  const openingDeferred = sourceNumber('deferred_taxes', 'deferred tax liability');
  for (const [name, expected] of [['opening_current_tax_payable', openingCurrent], ['opening_long_term_tax_liability', openingLongTerm], ['opening_deferred_tax_liability', openingDeferred]]) {
    const supplied = numeric(input[name], name);
    if (Math.abs(supplied - expected) > TOLERANCE) throw new Error(`P8A source-locked opening ${name} differs from packet`);
  }
  const bookTaxRate = numeric(input.book_tax_rate, 'book_tax_rate');
  const operatingTaxRate = numeric(input.operating_tax_rate, 'operating_tax_rate');
  if (bookTaxRate < 0 || bookTaxRate > 1 || operatingTaxRate < 0 || operatingTaxRate > 1) throw new Error('P8A tax rates must be decimal fractions within [0,1]');
  const deferredShare = array(input.deferred_share, 'deferred_share');
  const longTermTaxSettlement = array(input.long_term_tax_settlement, 'long_term_tax_settlement');
  if (deferredShare.some((value) => value < -1 || value > 1)) throw new Error('P8A deferred share is outside [-1,1]');
  if (longTermTaxSettlement.some((value) => value < 0)) throw new Error('P8A long-term settlement cannot be negative');
  if (longTermTaxSettlement.reduce((sum, value) => sum + value, 0) > openingLongTerm + TOLERANCE) throw new Error('P8A long-term settlement exceeds booked liability');
  const currentTaxPayableMethod = input.current_tax_payable_method ?? 'explicit_closing_balance';
  if (currentTaxPayableMethod !== 'source_anchored_payable_days' && currentTaxPayableMethod !== 'explicit_closing_balance') throw new Error('P8A current-tax payable timing method is unsupported');
  const periodMetadata = Array.isArray(tax.periods) ? tax.periods.map((period) => period.days) : [];
  const periodDaySource = input.period_days
    ?? (periodMetadata.length === PERIODS.length && periodMetadata.every((value) => typeof value === 'number' && Number.isFinite(value)) ? periodMetadata : DEFAULT_TAX_PERIOD_DAYS);
  const periodDays = array(periodDaySource, 'period_days');
  if (periodDays.some((value) => value <= 0)) throw new Error('P8A period days must be positive');
  let currentTaxPayableDays = null;
  let currentTaxPayableClosing = null;
  if (currentTaxPayableMethod === 'source_anchored_payable_days') {
    currentTaxPayableDays = numeric(input.current_tax_payable_days, 'current_tax_payable_days');
    if (currentTaxPayableDays < 0 || currentTaxPayableDays > 365) throw new Error('P8A current-tax payable days must be within [0,365]');
    if (input.current_tax_payable_closing !== null && input.current_tax_payable_closing !== undefined) throw new Error('P8A days method cannot carry explicit closing balances');
  } else {
    currentTaxPayableClosing = array(input.current_tax_payable_closing, 'current_tax_payable_closing');
    if (currentTaxPayableClosing.some((value) => value < 0)) throw new Error('P8A current tax payable cannot be negative');
    if (input.current_tax_payable_days !== null && input.current_tax_payable_days !== undefined) throw new Error('P8A explicit closing method cannot carry payable days');
  }
  return { bookTaxRate, operatingTaxRate, deferredShare, currentTaxPayableMethod, currentTaxPayableDays, currentTaxPayableClosing, periodDays, longTermTaxSettlement, openingCurrent, openingLongTerm, openingDeferred };
}

function dateDays(start, end) {
  return (Date.parse(end) - Date.parse(start)) / 86400000;
}

function calibrateOpeningRate(payments, dates, liability) {
  if (!Array.isArray(payments) || !Array.isArray(dates) || payments.length === 0 || payments.length !== dates.length) throw new Error('P8B opening calibration cash/date arrays are invalid');
  if (typeof liability !== 'number' || !Number.isFinite(liability) || liability <= 0) throw new Error('P8B opening calibration liability is missing/nonpositive');
  const measurement = Date.parse('2026-03-31');
  if (dates.some((value) => typeof value !== 'string' || Date.parse(value) <= measurement)) throw new Error('P8B opening calibration dates are invalid');
  const pv = (rate) => payments.reduce((sum, amount, index) => sum + amount / ((1 + rate) ** ((Date.parse(dates[index]) - measurement) / 86400000 / 365)), 0);
  let low = 0;
  let high = 0.25;
  if (pv(low) < liability - 1e-7 || pv(high) > liability + 1e-7) throw new Error('P8B opening calibration target is outside bounds');
  for (let index = 0; index < 120; index += 1) {
    const middle = (low + high) / 2;
    if (pv(middle) > liability) low = middle;
    else high = middle;
  }
  const result = (low + high) / 2;
  if (Math.abs(pv(result) - liability) > 1e-7) throw new Error('P8B opening calibration did not converge');
  return result;
}

function financingForecast(model) {
  const financing = model.financing_forecast;
  if (!financing) throw new Error('P8B financing forecast is missing');
  const packet = model.financing_packet ?? financing.packet;
  const inputs = financing.inputs ?? {};
  const forecast = financing.forecast ?? {};
  const debt = forecast.debt ?? {};
  const operating = forecast.operating_opening_pool ?? {};
  const finance = forecast.finance_opening_pool ?? {};
  const pipeline = forecast.pipeline ?? {};
  const fixture = financing.oracle_fixture === true;
  const sourceNumber = (value, name, minimum = null) => {
    if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error(`P8B required input ${name} is missing/non-numeric`);
    if (minimum !== null && value < minimum) throw new Error(`P8B required input ${name} is below its bound`);
    return value;
  };
  const sourceArray = (value, name, length = PERIODS.length) => {
    if (!Array.isArray(value) || value.length !== length) throw new Error(`P8B required input ${name} must contain ${length} values`);
    return value.map((item, index) => sourceNumber(item, `${name}[${index}]`));
  };
  const text = (value, name) => {
    if (typeof value !== 'string' || !value.trim()) throw new Error(`P8B required input ${name} is missing`);
    return value;
  };
  const debtFace = sourceNumber(inputs.debt_face ?? packet?.facts?.debt?.face, 'debt_face', 0);
  const debtCarrying = sourceNumber(inputs.debt_carrying ?? packet?.facts?.debt?.carrying, 'debt_carrying', 0);
  const debtFairValue = sourceNumber(inputs.debt_fair_value ?? packet?.facts?.debt?.fair_value, 'debt_fair_value', 0);
  const openingOperatingRou = sourceNumber(inputs.opening_operating_rou ?? packet?.facts?.operating_lease?.rou, 'opening_operating_rou', 0);
  const openingOperatingLiability = sourceNumber(inputs.opening_operating_liability ?? packet?.facts?.operating_lease?.liability, 'opening_operating_liability', 0);
  const openingFinancePpe = sourceNumber(inputs.opening_finance_ppe ?? packet?.facts?.finance_lease?.ppe_net, 'opening_finance_ppe', 0);
  const openingFinanceLiability = sourceNumber(inputs.opening_finance_liability ?? packet?.facts?.finance_lease?.liability, 'opening_finance_liability', 0);
  const openingOperatingPayments = sourceArray((inputs.opening_operating_payments ?? operating.payments).slice(0, PERIODS.length), 'opening_operating_payments');
  const openingFinancePayments = sourceArray((inputs.opening_finance_payments ?? finance.payments).slice(0, PERIODS.length), 'opening_finance_payments');
  const operatingDates = operating.payment_dates;
  const financeDates = finance.payment_dates;
  const calculatedOperatingRate = fixture ? sourceNumber(inputs.opening_operating_rate ?? 0, 'opening_operating_rate', 0) : calibrateOpeningRate(operating.payments, operatingDates, openingOperatingLiability);
  const calculatedFinanceRate = fixture ? sourceNumber(inputs.opening_finance_rate ?? 0, 'opening_finance_rate', 0) : calibrateOpeningRate(finance.payments, financeDates, openingFinanceLiability);
  if (!fixture && typeof forecast.opening_calibration?.operating_rate === 'number' && Math.abs(forecast.opening_calibration.operating_rate - calculatedOperatingRate) > TOLERANCE) throw new Error('P8B operating calibration binding is stale');
  if (!fixture && typeof forecast.opening_calibration?.finance_rate === 'number' && Math.abs(forecast.opening_calibration.finance_rate - calculatedFinanceRate) > TOLERANCE) throw new Error('P8B finance calibration binding is stale');
  const policy = forecast.policy ?? {};
  const debtCouponRate = sourceNumber(policy.debt_coupon_rate ?? packet?.facts?.debt?.coupon_proxy, 'debt_coupon_rate', 0);
  const debtRefinancePolicy = text(policy.debt_refinance_policy ?? 'refinance_disclosed_maturities', 'debt_refinance_policy');
  const debtTailPolicy = text(policy.debt_tail_policy ?? 'hold_through_fy2036', 'debt_tail_policy');
  const leaseBundle = text(policy.lease_bundle ?? 'operating_expense_finance_debt_like', 'lease_bundle');
  const pipelineTimingPolicy = text(policy.pipeline_timing_policy ?? 'actual_day_weighted_fy2026_fy2031', 'pipeline_timing_policy');
  const openingFinanceLifeYears = sourceNumber(policy.opening_finance_life_years ?? 13, 'opening_finance_life_years', 1);
  if (!fixture && debtRefinancePolicy !== 'refinance_disclosed_maturities') throw new Error('P8B debt refinancing policy is unsupported');
  if (!fixture && debtTailPolicy !== 'hold_through_fy2036') throw new Error('P8B base debt tail policy is unsupported');
  if (!fixture && leaseBundle !== 'operating_expense_finance_debt_like') throw new Error('P8B lease bundle is unsupported');
  if (!fixture && pipelineTimingPolicy !== 'actual_day_weighted_fy2026_fy2031') throw new Error('P8B pipeline timing policy is unsupported');
  if (!fixture && openingFinanceLifeYears !== 13) throw new Error('P8B selected opening finance service life is 13 years');
  const refinanceTermYears = sourceNumber(policy.refinance_term_years ?? 30, 'refinance_term_years', 1);
  const refinanceFeeRate = sourceNumber(policy.refinance_fee_rate ?? 0, 'refinance_fee_rate', 0);
  const pipelineCommitments = sourceNumber(inputs.pipeline_commitments ?? pipeline.undiscounted_commitments ?? packet?.facts?.pipeline?.undiscounted_commitments, 'pipeline_commitments', 0);
  const pipelineFinanceShare = sourceNumber(policy.pipeline_finance_share ?? pipeline.finance_share ?? packet?.facts?.pipeline?.finance_share_source, 'pipeline_finance_share', 0);
  const pipelineOperatingLifeYears = sourceNumber(policy.pipeline_operating_life_years ?? 6, 'pipeline_operating_life_years', 1);
  const pipelineFinanceLifeYears = sourceNumber(policy.pipeline_finance_life_years ?? 13, 'pipeline_finance_life_years', 1);
  const pipelineOperatingRate = sourceNumber(policy.pipeline_operating_rate ?? 0.036, 'pipeline_operating_rate', 0);
  const pipelineFinanceRate = sourceNumber(policy.pipeline_finance_rate ?? 0.044, 'pipeline_finance_rate', 0);
  const embeddedCostProxy = sourceNumber(inputs.embedded_operating_lease_cost_proxy ?? packet?.facts?.operating_lease?.embedded_cost_proxy, 'embedded_operating_lease_cost_proxy', 0);
  const debtRedemption = sourceArray(debt.original_face_redemption, 'debt_redemption');
  const debtProceeds = sourceArray(debt.new_face_proceeds, 'debt_proceeds');
  const operatingPayment = sourceArray(operating.payment, 'operating_payment');
  const financePayment = sourceArray(finance.payment, 'finance_payment');
  const visible = pipeline.visible;
  if (!Array.isArray(visible) || visible.length !== PERIODS.length) throw new Error('P8B pipeline visible schedule must contain eleven periods');
  const visibleValues = (key) => visible.map((item, index) => sourceNumber(item?.[key], `pipeline.${key}[${index}]`, 0));
  const periodDays = sourceArray(inputs.period_days ?? forecast.period_meta?.map((item) => item.days), 'period_days', PERIODS.length);
  const contraTotal = sourceNumber(inputs.debt_contra_total ?? Object.values(packet?.facts?.debt?.contra ?? {}).reduce((sum, value) => sum + value, 0), 'debt_contra_total');
  if (!fixture && Math.abs(debtFace + contraTotal - debtCarrying) > TOLERANCE) throw new Error('P8B debt face/contra/carrying identity failed');
  if (!fixture && Math.abs(openingOperatingLiability - (sourceNumber(packet?.facts?.operating_lease?.current_liability, 'opening_operating_current_liability') + sourceNumber(packet?.facts?.operating_lease?.noncurrent_liability, 'opening_operating_noncurrent_liability'))) > TOLERANCE) throw new Error('P8B operating opening liability containment failed');
  if (!fixture && Math.abs(openingFinanceLiability - (sourceNumber(packet?.facts?.finance_lease?.current_liability, 'opening_finance_current_liability') + sourceNumber(packet?.facts?.finance_lease?.noncurrent_liability, 'opening_finance_noncurrent_liability'))) > TOLERANCE) throw new Error('P8B finance opening liability containment failed');
  const runoffPass = fixture || (Math.abs(Number(operating.full_runoff_final_closing)) <= 1e-5 && Math.abs(Number(finance.full_runoff_final_closing)) <= 1e-5);
  if (!runoffPass) throw new Error('P8B opening lease runoff does not settle');
  return {
    debtFace, debtCarrying, debtFairValue, debtCouponRate, debtRefinancePolicy, debtTailPolicy, leaseBundle, pipelineTimingPolicy, refinanceTermYears, refinanceFeeRate,
    openingOperatingRou, openingOperatingLiability, openingFinancePpe, openingFinanceLiability,
    openingOperatingBookCost: sourceNumber(inputs.opening_operating_book_cost ?? packet?.facts?.operating_lease?.book_cost, 'opening_operating_book_cost', 0),
    openingOperatingRate: calculatedOperatingRate, openingFinanceRate: calculatedFinanceRate,
    operatingWeightedRate: sourceNumber(packet?.facts?.operating_lease?.disclosed_weighted_rate ?? 0.036, 'operating_weighted_rate', 0),
    financeWeightedRate: sourceNumber(packet?.facts?.finance_lease?.disclosed_weighted_rate ?? 0.044, 'finance_weighted_rate', 0),
    pipelineCommitments, pipelineFinanceShare, pipelineOperatingLifeYears, pipelineFinanceLifeYears, pipelineOperatingRate, pipelineFinanceRate,
    openingFinanceLifeYears,
    embeddedCostProxy, debtContraTotal: contraTotal,
    openingCurrentDebt: sourceNumber(inputs.opening_current_debt ?? packet?.facts?.debt?.current, 'opening_current_debt', 0),
    openingNoncurrentDebt: sourceNumber(inputs.opening_noncurrent_debt ?? packet?.facts?.debt?.noncurrent, 'opening_noncurrent_debt', 0),
    openingOperatingCurrentLiability: sourceNumber(inputs.opening_operating_current_liability ?? packet?.facts?.operating_lease?.current_liability, 'opening_operating_current_liability', 0),
    openingOperatingNoncurrentLiability: sourceNumber(inputs.opening_operating_noncurrent_liability ?? packet?.facts?.operating_lease?.noncurrent_liability, 'opening_operating_noncurrent_liability', 0),
    openingFinanceCurrentLiability: sourceNumber(inputs.opening_finance_current_liability ?? packet?.facts?.finance_lease?.current_liability, 'opening_finance_current_liability', 0),
    openingFinanceNoncurrentLiability: sourceNumber(inputs.opening_finance_noncurrent_liability ?? packet?.facts?.finance_lease?.noncurrent_liability, 'opening_finance_noncurrent_liability', 0),
    periodDays, debtRedemption, debtProceeds, operatingPayment, financePayment,
    pipelineOperatingAdditions: visibleValues('operating_additions'), pipelineFinanceAdditions: visibleValues('finance_additions'),
    pipelineOperatingExpense: visibleValues('operating_expense'), pipelineFinanceDepreciation: visibleValues('finance_depreciation'),
    pipelineOperatingInterest: visibleValues('operating_interest'), pipelineFinanceInterest: visibleValues('finance_interest'),
    pipelineOperatingPrincipal: visibleValues('operating_principal'), pipelineFinancePrincipal: visibleValues('finance_principal'),
    runoffPass,
  };
}

function equityForecast(model) {
  const equity = model.equity_forecast;
  if (!equity) throw new Error('P8C equity forecast is missing');
  const packet = model.equity_packet ?? equity.packet;
  const inputs = equity.inputs ?? {};
  const forecast = equity.forecast ?? {};
  const sourceNumber = (value, name, minimum = null, allowZero = true) => {
    if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error(`P8C required input ${name} is missing/non-numeric`);
    if (minimum !== null && value < minimum) throw new Error(`P8C required input ${name} is below its bound`);
    if (!allowZero && value === 0) throw new Error(`P8C required input ${name} must be nonzero`);
    return value;
  };
  const own = (object, name) => object && Object.hasOwn(object, name);
  const supplied = (name, ...sources) => {
    for (const source of sources) if (own(source, name)) return source[name];
    throw new Error(`P8C required input ${name} is missing`);
  };
  const packetFacts = packet?.facts ?? {};
  const policy = forecast.policy;
  if (!policy || typeof policy !== 'object') throw new Error('P8C policy is missing');
  const policyNumber = (name, minimum = null, allowZero = true, ...fallbacks) => sourceNumber(supplied(name, policy, inputs, ...fallbacks), name, minimum, allowZero);
  const packetFact = (section, name) => packetFacts?.[section]?.[name];
  const policyFromFact = (name, section, factName, minimum = null, allowZero = true) => policyNumber(name, minimum, allowZero, { [name]: packetFact(section, factName) });
  const forecastArray = (value, name, minimum = null) => {
    if (!Array.isArray(value) || value.length !== PERIODS.length) throw new Error(`P8C required input ${name} must contain ${PERIODS.length} values`);
    return value.map((item, index) => sourceNumber(item, `${name}[${index}]`, minimum));
  };
  const opening = packetFacts.opening_equity ?? {};
  const ttm = packetFacts.ttm ?? {};
  const sbcRatio = policyFromFact('sbc_ratio', 'ttm', 'sbc_ratio', 0);
  const existingAwardUnits = policyNumber('existing_award_units', 0, true);
  const existingUnrecognizedCost = policyNumber('existing_unrecognized_cost', 0, true);
  const existingServiceYears = policyNumber('existing_service_years', 1, false);
  const existingClaimPrice = policyFromFact('existing_claim_price', 'market_quote', 'value', 0, false);
  const settlementPrice = policyFromFact('settlement_price', 'future_settlement_price', 'value', 0, false);
  const withholdingRate = policyFromFact('withholding_rate', 'withholding', 'rate', 0);
  const cashIssuanceRatio = policyFromFact('cash_issuance_ratio', 'cash_issuance', 'ratio', 0);
  const repurchaseRatio = policyNumber('repurchase_ratio', 0, true);
  const repurchaseAuthorization = policyNumber('repurchase_authorization', 0, true);
  const dividendPerShareQuarter = policyNumber('dividend_per_share_quarter', 0, true);
  const dividendQuartersStub = policyNumber('dividend_quarters_stub', 1, false);
  const dividendQuartersAnnual = policyNumber('dividend_quarters_annual', 1, false);
  const embeddedSbcRatio = sourceNumber(supplied('embedded_sbc_ratio', inputs, { embedded_sbc_ratio: ttm.sbc_ratio }), 'embedded_sbc_ratio', 0);
  const deliveryTiming = policyNumber('delivery_timing', 0, true);
  const issuanceTiming = policyNumber('issuance_timing', 0, true);
  const repurchaseTiming = policyNumber('repurchase_timing', 0, true);
  const periodMeta = forecast.period_meta;
  if (!Array.isArray(periodMeta) || periodMeta.length !== PERIODS.length) throw new Error(`P8C required period metadata must contain ${PERIODS.length} values`);
  const periodDays = periodMeta.map((item, index) => sourceNumber(item?.days, `period_days[${index}]`, 1, false));
  const serviceDays = forecast.sbc?.service_days;
  if (!Array.isArray(serviceDays) || serviceDays.length !== PERIODS.length) throw new Error(`P8C required service-day overlap must contain ${PERIODS.length} values`);
  const serviceDayValues = serviceDays.map((item, index) => sourceNumber(item, `service_days[${index}]`, 0));
  const totalServiceDays = sourceNumber(forecast.sbc?.total_service_days, 'total_service_days', 1, false);
  const openingApic = sourceNumber(supplied('common_apic', inputs, { common_apic: opening.common_apic }), 'common_apic', 0);
  const openingRetained = sourceNumber(supplied('retained_earnings', inputs, { retained_earnings: opening.retained_earnings }), 'retained_earnings');
  const openingAoci = sourceNumber(supplied('aoci', inputs, { aoci: opening.aoci }), 'aoci');
  const openingTotalEquity = sourceNumber(supplied('total_equity', inputs, { total_equity: opening.total_equity }), 'total_equity');
  const openingPointShares = sourceNumber(supplied('point_shares', inputs, { point_shares: opening.point_shares }), 'point_shares', 0, false);
  const openingDividendPayable = sourceNumber(supplied('opening_dividend_payable', inputs, { opening_dividend_payable: packetFacts.dividend?.opening_payable }), 'opening_dividend_payable');
  const gate = {
    source: [openingApic, openingRetained, openingAoci, openingTotalEquity, openingDividendPayable].every(Number.isFinite),
    price: existingClaimPrice > 0 && settlementPrice > 0,
    timing: [deliveryTiming, issuanceTiming, repurchaseTiming].every((value) => value >= 0 && value <= 1),
    periods: periodDays.every((value) => value > 0) && serviceDayValues.every((value) => value >= 0) && Math.abs(serviceDayValues.reduce((sum, value) => sum + value, 0) - totalServiceDays) <= TOLERANCE,
  };
  return { sbcRatio, existingAwardUnits, existingUnrecognizedCost, existingServiceYears, existingClaimPrice, settlementPrice, withholdingRate, cashIssuanceRatio, repurchaseRatio, repurchaseAuthorization, dividendPerShareQuarter, dividendQuartersStub, dividendQuartersAnnual, embeddedSbcRatio, deliveryTiming, issuanceTiming, repurchaseTiming, totalServiceDays, openingDividendPayable, openingApic, openingRetained, openingAoci, openingTotalEquity, openingPointShares, periodDays, serviceDays: serviceDayValues, gate, existingClaim: existingAwardUnits * existingClaimPrice };
}

function otherBalancesForecastInputs(model) {
  const forecast = model.other_balances_forecast;
  if (!forecast) throw new Error('P8D other-balances forecast is missing');
  const packet = model.other_balances_packet ?? forecast.packet ?? {};
  const source = packet.facts?.source ?? {};
  const candidate = forecast.inputs ?? forecast.candidate ?? forecast.forecast?.policy ?? {};
  const number = (value, name, minimum = null, maximum = null) => {
    if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error(`P8D required input ${name} is missing/non-numeric`);
    if (minimum !== null && value < minimum) throw new Error(`P8D input ${name} is below its bound`);
    if (maximum !== null && value > maximum) throw new Error(`P8D input ${name} is above its bound`);
    return value;
  };
  const required = (value, name, minimum = null, maximum = null) => number(value, name, minimum, maximum);
  const from = (key, minimum = null, maximum = null) => {
    if (!Object.prototype.hasOwnProperty.call(candidate, key) || candidate[key] === null) throw new Error(`P8D selected input ${key} is missing`);
    return number(candidate[key], `candidate.${key}`, minimum, maximum);
  };
  const src = (key, minimum = null, maximum = null) => {
    if (!Object.prototype.hasOwnProperty.call(source, key) || source[key] === null) throw new Error(`P8D source.${key} is missing`);
    return required(source[key], `source.${key}`, minimum, maximum);
  };
  const calculated = packet.facts?.calculated;
  const schedule = packet.facts?.intangible_schedule;
  if (!calculated || typeof calculated !== 'object') throw new Error('P8D calculated source facts are missing');
  if (!schedule || typeof schedule !== 'object') throw new Error('P8D intangible schedule source facts are missing');
  const sourceCash = src('cash');
  const sourceShortTerm = src('short_term_investments', 0);
  const sourceEquityOther = src('equity_other_investments', 0);
  const sourceFinancingReceivables = src('financing_receivables', 0);
  const sourceGoodwill = src('goodwill', 0);
  const sourceIntangibles = src('intangibles', 0);
  const sourceOcaResidual = src('other_current_assets_residual', 0);
  const sourceOlta = src('other_long_term_assets', 0);
  const sourceOclResidual = src('other_current_liability_residual', 0);
  const sourceOlTlResidual = src('other_long_term_liability_residual', 0);
  const sourceDtl = src('deferred_tax_liability', 0);
  const sourceOtherInvestmentPool = src('other_investment_pool', 0);
  const sourceKnownInvestmentValue = src('known_investment_value', 0);
  const sourceUnfundedCommitment = src('unfunded_commitment', 0);
  const sourceIdentifiedLongTermDebt = src('identified_long_term_debt_investments', 0);
  const sourceRestriction = src('restricted_total', 0);
  const periodDays = calculated.period_days;
  if (!Array.isArray(periodDays) || periodDays.length !== PERIODS.length) throw new Error('P8D source period days must contain eleven values');
  const periodDayValues = periodDays.map((item, index) => required(item, `period_days[${index}]`, 1));
  const annualExplicit = schedule.annual_explicit;
  if (!Array.isArray(annualExplicit) || annualExplicit.length !== 4) throw new Error('P8D disclosed intangible schedule is incomplete');
  const scheduleValues = [required(schedule.stub, 'intangible_schedule.stub', 0), ...annualExplicit.map((item, index) => required(item, `intangible_schedule.annual_explicit[${index}]`, 0)), required(schedule.tail, 'intangible_schedule.tail', 0), required(schedule.total, 'intangible_schedule.total', 0)];
  if (Math.abs(scheduleValues.slice(0, 6).reduce((sum, item) => sum + item, 0) - scheduleValues[6]) > 1e-8 || Math.abs(scheduleValues[6] - sourceIntangibles) > 1e-8) throw new Error('P8D disclosed intangible schedule does not tie opening carrying value');
  const selected = {
    otherInvestmentMultiplier: from('other_investment_value_multiplier', 0, 10),
    cashIncomeYield: from('cash_income_yield', 0, 0.1),
    intangibleTailLifeYears: from('intangible_tail_life_years', 0, 15),
    goodwillImpairment: from('goodwill_impairment', 0, sourceGoodwill),
    unfundedCommitmentValueFraction: from('unfunded_commitment_value_fraction', 0, 1),
    legalStress: from('legal_stress', 0, 400),
    incrementalNetDtaValue: from('incremental_net_dta_value', 0, 26273),
    unrealizedInvestmentGain: from('unrealized_investment_gain', 0),
  };
  if (![6, 10, 15].includes(selected.intangibleTailLifeYears)) throw new Error('P8D intangible tail life must be 6, 10 or 15');
  const pForecast = forecast.forecast ?? forecast;
  const coverage = pForecast.coverage;
  const coverageKeys = ['cash', 'short_term_investments', 'equity_other_investments', 'identified_long_term_debt_investments', 'financing_receivables', 'intangibles', 'goodwill', 'other_current_assets_residual', 'other_long_term_assets_residual', 'other_current_liability_residual', 'other_long_term_liability_residual', 'deferred_tax'];
  if (!coverage || typeof coverage !== 'object' || !coverageKeys.every((key) => coverage[key] && typeof coverage[key].policy === 'string')) throw new Error('P8D required coverage record is missing/incomplete');
  const embeddedIntangibleRatio = required(calculated.embedded_intangible_ratio, 'embedded_intangible_ratio', 0, 1);
  const unidentifiedDnaOther = required(calculated.unidentified_dna_other, 'unidentified_dna_other', 0);
  const linked = (row) => PERIODS.map((_, index) => `=OtherBalances!${periodColumn(index)}${row}`);
  return {
    ...selected,
    openingCash: sourceCash,
    openingShortTermInvestments: sourceShortTerm,
    openingEquityOtherInvestments: sourceEquityOther,
    openingFinancingReceivables: sourceFinancingReceivables,
    openingGoodwill: sourceGoodwill,
    openingIntangibles: sourceIntangibles,
    openingOtherCurrentAssetsResidual: sourceOcaResidual,
    openingOtherLongTermAssets: sourceOlta,
    openingOtherCurrentLiabilityResidual: sourceOclResidual,
    openingOtherLongTermLiabilityResidual: sourceOlTlResidual,
    openingDeferredTaxLiability: sourceDtl,
    intangibleSchedule: { stub: scheduleValues[0], annualExplicit: scheduleValues.slice(1, 5), tail: scheduleValues[5], total: scheduleValues[6] },
    periodDays: periodDayValues,
    identifiedLongTermDebtInvestments: sourceIdentifiedLongTermDebt,
    sourceOtherInvestmentPool,
    sourceKnownInvestmentValue,
    sourceUnfundedCommitment,
    sourceRestriction,
    embeddedIntangibleRatio,
    unidentifiedDnaOther,
    linked,
  };
}

function p8dDriverConditions() {
  const d = P8D_DRIVER_ROWS;
  return [
    `COUNT(B${d.otherInvestmentMultiplier}:B${d.openingDeferredTaxLiability})=19`,
    `COUNT(B${d.otherInvestmentPool}:B${d.unfundedCommitment})=3`,
    `COUNT(B${d.intangibleStubAmortization}:B${d.identifiedLongTermDebtInvestments})=7`,
    `COUNT(B${d.periodDays}:L${d.periodDays})=11`,
    `COUNT(B${d.investmentCarrying}:L${d.investmentCarrying})=11`,
    `COUNT(B${d.investmentAdditions}:L${d.investmentAdditions})=11`,
    `COUNT(B${d.cashIncome}:L${d.cashIncome})=11`,
    `COUNT(B${d.noncashGain}:L${d.noncashGain})=11`,
    `COUNT(B${d.investmentValue}:L${d.investmentValue})=11`,
    `COUNT(B${d.intangibleOpening}:L${d.intangibleClosing})=33`,
    `COUNT(B${d.goodwillClosing}:L${d.goodwillClosing})=11`,
    `COUNT(B${d.dtaValue}:L${d.dtaValue})=11`,
    `COUNT(B${d.commitmentFundingCfi}:L${d.commitmentFundingCfi})=11`,
    `COUNT(B${d.embeddedIntangibleRatio})=1`,
    `COUNT(B${d.unidentifiedDnaOther})=1`,
    `B${d.otherInvestmentMultiplier}>=0`, `B${d.otherInvestmentMultiplier}<=10`,
    `B${d.cashIncomeYield}>=0`, `B${d.cashIncomeYield}<=0.1`,
    `OR(B${d.intangibleTailLifeYears}=6,B${d.intangibleTailLifeYears}=10,B${d.intangibleTailLifeYears}=15)`,
    `B${d.goodwillImpairment}>=0`, `B${d.unfundedCommitmentValueFraction}>=0`, `B${d.unfundedCommitmentValueFraction}<=1`,
    `B${d.legalStress}>=0`, `B${d.legalStress}<=400`, `B${d.incrementalNetDtaValue}>=0`, `B${d.incrementalNetDtaValue}<=26273`,
    `B${d.unrealizedInvestmentGain}>=0`, `B${d.embeddedIntangibleRatio}>=0`, `B${d.embeddedIntangibleRatio}<=1`, `B${d.unidentifiedDnaOther}>=0`,
    `B${d.otherInvestmentPool}>=0`, `B${d.knownInvestmentValue}>=0`, `B${d.unfundedCommitment}>=0`, `B${d.intangibleStubAmortization}>=0`, `B${d.intangibleFy27Amortization}>=0`, `B${d.intangibleFy28Amortization}>=0`, `B${d.intangibleFy29Amortization}>=0`, `B${d.intangibleFy30Amortization}>=0`, `B${d.intangibleTailPool}>=0`, `B${d.identifiedLongTermDebtInvestments}>=0`,
    `MIN(B${d.periodDays}:L${d.periodDays})>0`,
    `MIN(B${d.investmentAdditions}:L${d.investmentAdditions})>=0`, `MIN(B${d.cashIncome}:L${d.cashIncome})>=0`,
    `MIN(B${d.investmentValue}:L${d.investmentValue})>=0`, `MIN(B${d.intangibleOpening}:L${d.intangibleOpening})>=0`,
    `MIN(B${d.intangibleAmortization}:L${d.intangibleAmortization})>=0`, `MIN(B${d.intangibleClosing}:L${d.intangibleClosing})>=0`,
    `MIN(B${d.goodwillClosing}:L${d.goodwillClosing})>=0`, `MIN(B${d.dtaValue}:L${d.dtaValue})>=0`, `B${d.coverage}="PASS"`,
  ];
}

function p8dDriverGate() {
  return `=IFERROR(IF(AND(${p8dDriverConditions().filter((value) => value !== `B${P8D_DRIVER_ROWS.coverage}="PASS"`).join(',')}),"PASS","FAIL"),"FAIL")`;
}

function p8cDriverConditions() {
  const e = P8C_DRIVER_ROWS;
  const periodOpeningApic = (index) => index === 0 ? `B${e.openingApic}` : `Equity!${periodColumn(index - 1)}34`;
  const periodOpeningShares = (index) => `Equity!${periodColumn(index)}24`;
  const periodBasisGuards = PERIODS.map((_, index) => {
    const column = periodColumn(index);
    const openingApic = periodOpeningApic(index);
    const openingShares = periodOpeningShares(index);
    return `OR(Equity!${column}17=0,AND(Equity!${column}18>=0,Equity!${column}18<=${openingApic}+${TOLERANCE},B${e.settlementPrice}>=${openingApic}/${openingShares}-${TOLERANCE}))`;
  });
  const runoffGuards = PERIODS.map((_, index) => {
    const column = periodColumn(index);
    return `OR(${column}${e.serviceDays}>0,AND(ABS(Equity!${column}7)<=${TOLERANCE},ABS(Equity!${column}9)<=${TOLERANCE},ABS(Equity!${column}27)<=${TOLERANCE}))`;
  });
  return [
    `COUNT(B${e.sbcRatio}:B${e.dividendQuartersAnnual})=13`,
    `COUNT(B${e.embeddedSbcRatio}:B${e.repurchaseTiming})=4`,
    `COUNT(B${e.totalServiceDays}:B${e.openingTotalEquity})=7`,
    `COUNT(B${e.periodDays}:L${e.periodDays})=11`, `COUNT(B${e.serviceDays}:L${e.serviceDays})=11`,
    `B${e.sbcRatio}>=0`, `B${e.sbcRatio}<=1`, `B${e.embeddedSbcRatio}>=0`, `B${e.embeddedSbcRatio}<=1`, `B${e.existingAwardUnits}>=0`, `B${e.existingUnrecognizedCost}>=0`, `OR(B${e.existingServiceYears}=2,B${e.existingServiceYears}=3,B${e.existingServiceYears}=4)`, `B${e.existingClaimPrice}>0`, `B${e.settlementPrice}>0`, `B${e.withholdingRate}>=0`, `B${e.withholdingRate}<=1`, `B${e.cashIssuanceRatio}>=0`, `B${e.repurchaseRatio}>=0`, `B${e.repurchaseAuthorization}=44000`, `B${e.dividendPerShareQuarter}>=0`, `B${e.dividendQuartersStub}=1`, `B${e.dividendQuartersAnnual}=4`, `B${e.openingApic}>=0`, `OR(B${e.repurchaseRatio}=0,B${e.settlementPrice}>=B${e.openingApic}/B${e.openingPointShares}-${TOLERANCE})`,
    `B${e.deliveryTiming}>=0`, `B${e.deliveryTiming}<=1`, `B${e.issuanceTiming}>=0`, `B${e.issuanceTiming}<=1`, `B${e.repurchaseTiming}>=0`, `B${e.repurchaseTiming}<=1`, `B${e.totalServiceDays}>0`, `B${e.openingPointShares}>0`, `MIN(B${e.periodDays}:L${e.periodDays})>0`, `MIN(B${e.serviceDays}:L${e.serviceDays})>=0`, `ABS(SUM(B${e.serviceDays}:L${e.serviceDays})-B${e.totalServiceDays})<=${TOLERANCE}`,
    `ABS(SUM(Equity!B7:L7)-B${e.existingUnrecognizedCost})<=${TOLERANCE}`, `ABS(SUM(Equity!B9:L9)-B${e.existingAwardUnits})<=${TOLERANCE}`,
    ...runoffGuards, ...periodBasisGuards,
    `COUNT(Equity!B6:L38)=363`, `MIN(Equity!B8:L8)>=-${TOLERANCE}`, `MIN(Equity!B25:L26)>0`, `MIN(Equity!B27:L27)>=0`, `MIN(Equity!B34:L34)>=-${TOLERANCE}`, `MIN(B${e.programApicBasis}:L${e.programApicBasis})>=-${TOLERANCE}`, `MIN(B${e.authorizationRemaining}:L${e.authorizationRemaining})>=-${TOLERANCE}`,
  ];
}

function equityDriverGate() {
  const e = P8C_DRIVER_ROWS;
  return `=IFERROR(IF(AND(${p8cDriverConditions().join(',')}),"PASS","FAIL"),"FAIL")`;
}

function financingDriverConditions() {
  const f = FINANCING_DRIVER_ROWS;
  return [
    `COUNT(B${f.debtFace}:B${f.debtFairValue})=3`, `COUNT(B${f.debtCouponRate})=1`, `COUNT(B${f.refinanceTermYears}:B${f.refinanceFeeRate})=2`,
    `COUNT(B${f.openingOperatingRou}:B${f.openingOperatingRate})=6`, `COUNT(B${f.openingFinanceRate}:B${f.financeWeightedRate})=3`, `COUNT(B${f.openingFinanceLifeYears})=1`,
    `COUNT(B${f.pipelineCommitments}:B${f.pipelineFinanceShare})=2`, `COUNT(B${f.pipelineOperatingLifeYears}:B${f.pipelineFinanceRate})=4`,
    `COUNT(B${f.embeddedOperatingLeaseCostProxy})=1`, `COUNT(B${f.leaseBundle})=0`, `COUNT(B${f.pipelineTimingPolicy})=0`,
    `COUNT(B${f.debtContraTotal}:B${f.openingFinanceNoncurrentLiability})=7`,
    ...['periodDays', 'debtRedemption', 'debtProceeds', 'operatingPayment', 'financePayment', 'pipelineOperatingAdditions', 'pipelineFinanceAdditions', 'pipelineOperatingExpense', 'pipelineFinanceDepreciation', 'pipelineOperatingInterest', 'pipelineFinanceInterest', 'pipelineOperatingPrincipal', 'pipelineFinancePrincipal'].map((name) => `COUNT(B${f[name]}:L${f[name]})=11`),
    `B${f.debtFace}>=0`, `B${f.debtCarrying}>=0`, `B${f.debtFairValue}>=0`, `B${f.debtCouponRate}>0`, `B${f.refinanceTermYears}>0`, `B${f.refinanceFeeRate}=0`,
    `B${f.openingOperatingRou}>=0`, `B${f.openingOperatingLiability}>=0`, `B${f.openingFinancePpe}>=0`, `B${f.openingFinanceLiability}>=0`, `B${f.openingOperatingBookCost}>=0`,
    `B${f.openingOperatingRate}>=0`, `B${f.openingFinanceRate}>=0`, `B${f.pipelineCommitments}>=0`, `B${f.pipelineFinanceShare}>=0`, `B${f.pipelineFinanceShare}<=1`,
    `B${f.pipelineOperatingLifeYears}>0`, `B${f.pipelineFinanceLifeYears}>0`, `B${f.pipelineOperatingRate}>0`, `B${f.pipelineFinanceRate}>0`, `B${f.embeddedOperatingLeaseCostProxy}>=0`, `B${f.openingFinanceLifeYears}>0`, `B${f.openingFinanceLifeYears}<=50`,
    `B${f.openingCurrentDebt}>=0`, `B${f.openingNoncurrentDebt}>=0`, `B${f.openingOperatingCurrentLiability}>=0`, `B${f.openingOperatingNoncurrentLiability}>=0`, `B${f.openingFinanceCurrentLiability}>=0`, `B${f.openingFinanceNoncurrentLiability}>=0`,
    `B${f.debtRefinancePolicy}="refinance_disclosed_maturities"`, `B${f.debtTailPolicy}="hold_through_fy2036"`, `B${f.leaseBundle}="operating_expense_finance_debt_like"`, `B${f.pipelineTimingPolicy}="actual_day_weighted_fy2026_fy2031"`,
    `ABS(B${f.debtFace}+B${f.debtContraTotal}-B${f.debtCarrying})<=${TOLERANCE}`, `ABS(B${f.openingCurrentDebt}+B${f.openingNoncurrentDebt}-B${f.debtCarrying})<=${TOLERANCE}`,
    `ABS(B${f.openingOperatingCurrentLiability}+B${f.openingOperatingNoncurrentLiability}-B${f.openingOperatingLiability})<=${TOLERANCE}`, `ABS(B${f.openingFinanceCurrentLiability}+B${f.openingFinanceNoncurrentLiability}-B${f.openingFinanceLiability})<=${TOLERANCE}`,
    `B${f.openingFinancePpe}<=B11+${TOLERANCE}`,
    `MIN(B${f.operatingPayment}:L${f.operatingPayment})>=0`, `MIN(B${f.financePayment}:L${f.financePayment})>=0`,
    `MIN(B${f.periodDays}:L${f.periodDays})>0`, `MIN(B${f.debtRedemption}:L${f.debtRedemption})>=0`, `MIN(B${f.debtProceeds}:L${f.debtProceeds})>=0`,
    ...['pipelineOperatingAdditions', 'pipelineFinanceAdditions', 'pipelineOperatingExpense', 'pipelineFinanceDepreciation', 'pipelineOperatingInterest', 'pipelineFinanceInterest', 'pipelineOperatingPrincipal', 'pipelineFinancePrincipal'].map((name) => `MIN(B${f[name]}:L${f[name]})>=0`),
    ...PERIODS.map((_, index) => `Financing!${periodColumn(index)}27="PASS"`),
    `B${f.gate}="PASS"`,
  ];
}

function financingDriverGate() {
  const f = FINANCING_DRIVER_ROWS;
  const conditions = financingDriverConditions().filter((condition) => condition !== `B${f.gate}="PASS"`);
  return `=IFERROR(IF(AND(${conditions.join(',')}),"PASS","FAIL"),"FAIL")`;
}

function taxDriverConditions() {
  const tax = TAX_DRIVER_ROWS;
  return [
    `COUNT(B${tax.bookTaxRate}:B${tax.operatingTaxRate})=2`,
    `COUNT(B${tax.deferredShare}:L${tax.deferredShare})=11`,
    `COUNT(B${tax.longTermTaxSettlement}:L${tax.longTermTaxSettlement})=11`,
    `COUNT(B${tax.openingCurrentTaxPayable}:B${tax.openingDeferredTaxLiability})=3`,
    `COUNT(B${tax.interestExpense})=1`,
    `OR(B${tax.currentTaxPayableMethod}="source_anchored_payable_days",B${tax.currentTaxPayableMethod}="explicit_closing_balance")`,
    `B${tax.bookTaxRate}>=0`, `B${tax.bookTaxRate}<=1`, `B${tax.operatingTaxRate}>=0`, `B${tax.operatingTaxRate}<=1`,
    `MIN(B${tax.deferredShare}:L${tax.deferredShare})>=-1`, `MAX(B${tax.deferredShare}:L${tax.deferredShare})<=1`,
    `MIN(B${tax.longTermTaxSettlement}:L${tax.longTermTaxSettlement})>=0`,
    `SUM(B${tax.longTermTaxSettlement}:L${tax.longTermTaxSettlement})<=B${tax.openingLongTermTaxLiability}+${TOLERANCE}`,
    `Inputs!$B$${tax.openingCurrentTaxPayable}>=0`, `Inputs!$B$${tax.openingLongTermTaxLiability}>=0`, `Inputs!$B$${tax.openingDeferredTaxLiability}>=0`,
    `Inputs!$B$${tax.interestExpense}>=0`,
    `IF(B${tax.currentTaxPayableMethod}="source_anchored_payable_days",AND(COUNT(B${tax.currentTaxPayableDays})=1,B${tax.currentTaxPayableDays}>=0,B${tax.currentTaxPayableDays}<=365,COUNT(B${tax.periodDays}:L${tax.periodDays})=11,MIN(B${tax.periodDays}:L${tax.periodDays})>0),IF(B${tax.currentTaxPayableMethod}="explicit_closing_balance",AND(COUNT(B${tax.currentTaxPayableClosing}:L${tax.currentTaxPayableClosing})=11,MIN(B${tax.currentTaxPayableClosing}:L${tax.currentTaxPayableClosing})>=0),FALSE))`,
    `IF(B${tax.currentTaxPayableMethod}="source_anchored_payable_days",COUNT(B${tax.currentTaxPayableClosing}:L${tax.currentTaxPayableClosing})=0,IF(B${tax.currentTaxPayableMethod}="explicit_closing_balance",COUNT(B${tax.currentTaxPayableDays})=0,FALSE))`,
    `MIN(Taxes!B16:L16)>=0`, `MIN(Taxes!B17:L17)>=0`, `MIN(Taxes!B19:L19)>=0`, `MIN(Taxes!B20:L20)>=0`, `MIN(Taxes!B22:L22)>=0`, `MIN(Taxes!B27:L27)>=0`,
    ...PERIODS.map((_, index) => `Taxes!${periodColumn(index)}30="PASS"`),
  ];
}

function taxDriverGate() {
  return `=IFERROR(IF(AND(${taxDriverConditions().join(',')}),"PASS","FAIL"),"FAIL")`;
}

function sourceRows(values, model) {
  const c = model.candidate;
  const source = (basis, refs) => `${basis}; ${refs.join(', ')}`;
  const rows = [
    padRow([model.operating_forecast ? 'P6 operating overlay with P5 real MSFT asset schedule inputs' : 'P5 real MSFT asset schedule inputs']),
    padRow(['Frozen source facts are in USD millions. Estimates and temporary assumptions are visible below.']),
    padRow([]),
    padRow(['Opening balance sheet at 2026-03-31', null, null, 'Source / basis']),
    padRow(['Input', 'Value', 'Units', 'Basis / evidence']),
    padRow(['Cash and cash equivalents', values.openingCash, 'USD millions', source('reported', ['E2'])]),
    padRow(['Short-term investments', values.shortTermInvestments, 'USD millions', source('reported', ['E2'])]),
    padRow(['Accounts receivable', values.accountsReceivable, 'USD millions', source('reported', ['E2'])]),
    padRow(['Inventory', values.inventory, 'USD millions', source('reported', ['E2'])]),
    padRow(['Other current assets', values.otherCurrentAssets, 'USD millions', source('reported', ['E2'])]),
    padRow(['Opening net PP&E', values.openingNetPPE, 'USD millions', source('reported', ['E1', 'E2'])]),
    padRow(['Opening land (nondepreciable)', values.openingLand, 'USD millions', source('reported', ['E1'])]),
    padRow(['Opening depreciable net PP&E', values.openingDepreciableNetPPE, 'USD millions', source('calculated: net PP&E - land', ['E1'])]),
    padRow(['Operating lease ROU asset', values.operatingLeaseRou, 'USD millions', source('reported', ['E2'])]),
    padRow(['Long-term investments', values.longTermInvestments, 'USD millions', source('reported', ['E2'])]),
    padRow(['Goodwill', values.goodwill, 'USD millions', source('reported', ['E2'])]),
    padRow(['Intangible assets', values.intangibles, 'USD millions', source('reported', ['E2'])]),
    padRow(['Other noncurrent assets', values.otherNoncurrentAssets, 'USD millions', source('reported', ['E2'])]),
    padRow(['Total assets', values.totalAssets, 'USD millions', source('reported', ['E2'])]),
    padRow(['Accounts payable', values.accountsPayable, 'USD millions', source('reported', ['E2'])]),
    padRow(['Short-term debt', values.shortTermDebt, 'USD millions', source('reported', ['E2'])]),
    padRow(['Long-term debt', values.longTermDebt, 'USD millions', source('reported', ['E2'])]),
    padRow(['Total liabilities', values.totalLiabilities, 'USD millions', source('reported', ['E2'])]),
    padRow(['Total stockholders equity', values.totalEquity, 'USD millions', source('reported', ['E2'])]),
    padRow(['Opening balance identity', '=B19-(B6+B7+B8+B9+B10+B11+B14+B15+B16+B17+B18)', 'USD millions', 'Must be zero; no plug']),
    padRow([]),
    padRow(['Selected asset method parameters', null, null, 'Analyst selection; system-reviewed provisional']),
    padRow(['Parameter', 'Value', 'Units', 'Basis / evidence']),
    padRow(['Opening remaining-life proxy', values.remainingLife, 'years', source(c.parameters.find((x) => x.name === 'opening_remaining_life_years')?.basis ?? 'estimate', ['E1', 'E6'])]),
    padRow(['New-addition useful life proxy', values.newUsefulLife, 'years', source(c.parameters.find((x) => x.name === 'new_addition_useful_life_years')?.basis ?? 'estimate', ['E6'])]),
    padRow(['New-addition timing fraction', values.timingFraction, 'fraction', source(c.parameters.find((x) => x.name === 'new_addition_timing_fraction')?.basis ?? 'estimate', ['E3', 'E5'])]),
    padRow(['Cash PP&E additions rate', values.cashPpeRate, '% of revenue', source(c.parameters.find((x) => x.name === 'cash_ppe_additions_rate')?.basis ?? 'estimate', ['E3', 'E5'])]),
    padRow(['Noncash PP&E additions ratio', values.noncashRatio, '% of cash additions', source(c.parameters.find((x) => x.name === 'noncash_ppe_additions_ratio')?.basis ?? 'estimate', ['E1', 'E4'])]),
    padRow(['Lease additions modeled', values.leaseAdditions, 'USD millions', source('P8B pending; must remain zero', ['E6', 'E7'])]),
    padRow(['Tax rate', values.taxRate, '%', source(c.parameters.find((x) => x.name === 'tax_rate')?.basis ?? 'estimate', ['E3', 'E5'])]),
    padRow(['Revenue growth', values.revenueGrowth, '%', source(c.parameters.find((x) => x.name === 'revenue_growth')?.basis ?? 'estimate', ['E1', 'E3'])]),
    padRow(['WACC', values.wacc, '%', source(c.parameters.find((x) => x.name === 'wacc')?.basis ?? 'estimate', ['E3'])]),
    padRow(['Terminal growth', values.terminalGrowth, '%', source(c.parameters.find((x) => x.name === 'terminal_growth')?.basis ?? 'estimate', ['E3'])]),
    padRow(['Method ID', c.method_id, '', 'Catalog version p5-asset-methods-v1']),
    padRow(['Method version', c.method_version, '', 'Application-owned method execution']),
    padRow([]),
    padRow(['Historical support and cash/noncash distinction', null, null, 'Source / basis']),
    padRow(['TTM revenue', values.ttmRevenue, 'USD millions', source('derived TTM', ['E3', 'E5'])]),
    padRow(['TTM operating income', values.ttmEbit, 'USD millions', source('derived TTM', ['E3', 'E5'])]),
    padRow(['TTM operating margin', values.ttmEbitMargin, '%', source('calculated', ['E3', 'E5'])]),
    padRow(['TTM depreciation, amortization and other', values.ttmDnaOther, 'USD millions', source('derived TTM; not used as PP&E-only D&A', ['E3', 'E5'])]),
    padRow(['TTM cash PP&E payments', values.ttmCashPpe, 'USD millions', source('derived TTM cash flow', ['E3', 'E5'])]),
    padRow(['TTM cash PP&E additions rate', values.ttmCashPpeRate, '% of revenue', source('calculated', ['E3', 'E5'])]),
    padRow(['FY2025 cash PP&E payments', values.fy25CashPpe, 'USD millions', source('reported cash flow', ['E5'])]),
    padRow(['FY2025 PP&E purchases in AP', values.fy25PpePayables, 'USD millions', source('reported note subset', ['E4'])]),
    padRow(['2026-03-31 PP&E purchases in AP', values.q3PpePayables, 'USD millions', source('reported note subset', ['E1'])]),
    padRow(['FY2025 finance-lease PP&E net already in PP&E', values.financeLeaseNet, 'USD millions', source('reported lease note', ['E7'])]),
    padRow([]),
    padRow(['Required input check', inputGate(model), '', 'Missing, text and invalid inputs block every period and valuation; numeric zero is explicit.']),
    periodRow('Revenue forecast input / driver', PERIODS.map((period, index) => model.operating_forecast ? `=Operating!${periodColumn(index)}11` : index === 0 ? '=B43*0.25' : index === 1 ? '=B55/0.25*(1+$B$36)' : `=${periodColumn(index - 1)}55*(1+$B$36)`), 'USD millions'),
    padRow(['Forecast revenue note', model.operating_forecast ? 'P6 segment revenue total visibly supersedes the P5 revenue placeholder; FY2027 starts from actual FY2026 YTD plus the forecast stub.' : 'Stub is explicitly 0.25 years; later years use visible temporary growth assumption.']),
    padRow(['TTM reported PP&E depreciation', values.ttmPpeDepreciation, 'USD millions', 'Note6: FY2025 + current YTD - prior YTD; reported billion precision. E1/E4; lease/amortization scope remains a limitation.']),
    periodRow('Cash PP&E payment forecast', PERIODS.map((_, index) => `=${periodColumn(index)}55*$B$32`), 'USD millions'),
    padRow(['Operating-cost proxy excluding PP&E depreciation', '=(B43-B44-B57)/B43', '% of revenue', model.operating_forecast ? 'P5 historical placeholder retained for provenance; P6 Operating!row21 supersedes it in linked schedules.' : 'Fixed historical baseline. Other embedded amortization/SBC and lease treatment pending P6–P8; not a pure cash-cost estimate.']),
    padRow(['Noncash investment assumption', 'Forecast noncash PP&E is an explicit estimate of unpaid purchases. Historical payable stocks are not period additions; payment/financing policy is provisional.']),
  ];
  if (model.operating_forecast) {
    const drivers = operatingDriverInputs(model);
    rows.push(
      padRow(['P6 formula drivers (application-owned inputs)', null, null, 'Edit these visible inputs; Mog/Excel formulas compile forecast outputs.']),
      periodRow('P6 forecast period', PERIODS.map((period) => period.id), ''),
      padRow(['Driver convention', 'B = FY2026 stub estimate; C:L = FY2027-FY2036 annual estimates. Growth is bounded [-100%, 100%]; cost ratios [0%, 100%].']),
    );
    for (const segment of OPERATING_SEGMENTS) rows.push(periodRow(`${segment} growth assumption`, [drivers.segmentGrowth[segment].stub, ...drivers.segmentGrowth[segment].annual], 'ratio; B=stub, C:L=annual'));
    rows.push(padRow([]));
    for (const line of ['cost_of_revenue', 'research_and_development', 'sales_and_marketing', 'general_and_administrative']) {
      const label = line.replaceAll('_', ' ').replace(/(^| )\w/g, (value) => value.toUpperCase());
      rows.push(periodRow(`${label} ratio assumption`, [drivers.costRatio[line].stub, ...drivers.costRatio[line].annual], 'ratio; B=stub, C:L=annual'));
    }
    rows.push(
      padRow([]),
      padRow(['P6 historical segment anchors (source observations, not forecast inputs)', null, null, null, 'Frozen P2 source values']),
      padRow(['Anchor', ...OPERATING_SEGMENTS, 'Source / basis']),
      padRow(['Prior FY2025 revenue', ...OPERATING_SEGMENTS.map((segment) => drivers.anchors[segment].priorFy), 'Frozen P2 annual comparable']),
      padRow(['Prior comparable YTD revenue', ...OPERATING_SEGMENTS.map((segment) => drivers.anchors[segment].priorYtd), 'Frozen P2 prior YTD comparable']),
      padRow(['Current comparable YTD revenue', ...OPERATING_SEGMENTS.map((segment) => drivers.anchors[segment].currentYtd), 'Frozen P2 current YTD actual']),
      padRow(['P6 driver input check', p6DriverGate(), '', 'Missing/non-numeric drivers fail; numeric zero and negative growth remain valid within bounds.']),
    );
  }
  if (model.working_capital_forecast) {
    const wc = workingCapitalInputs(model);
    rows.push(
      padRow([]),
       padRow(['P7 working-capital drivers and opening balances', null, null, 'Application-owned inputs; source-locked contract parameters are derived from the packet; USD millions unless stated']),
      padRow(['P7 methods', 'Balance-based DSO/DIO/DPO proxies; aggregate contract billing/recognition bridge; explicit residual hold-flat policy.']),
      padRow(['Current AR DSO proxy', wc.dso, 'days', '60,041 / TTM revenue 318,273 × 365; current AR only']),
      padRow(['Inventory DIO proxy', wc.dio, 'days', '1,219 / TTM cost of revenue 100,863 × 365; cost-of-revenue proxy']),
      padRow(['Operating AP DPO proxy', wc.dpo, 'days', 'Calculated operating AP 14,913 / TTM cost of revenue 100,863 × 365; PP&E payable excluded']),
      padRow(['Accrued compensation multiplier', wc.accruedCompensationMultiplier, 'dimensionless', 'Analyst judgment; base 1.0; bounded 0.8 / 1.2; scales the source baseline and is never a revenue fraction']),
      padRow(['Server receivables first-stub change', wc.serverReceivableShock, 'ratio', 'Base 0.0; bounded -20% / +20% scenario; balance held flat thereafter']),
       padRow(['Contract billings / recognition base (application-locked)', wc.contractBillingsRatio, 'ratio', 'Fixed by selected policy; modeled additions creating scoped liability, not cash receipts']),
      padRow(['Contract billings first-stub multiplier', wc.contractBillingMultiplier, 'ratio', 'Base 1.0; bounded 0.9 / 1.1 sensitivity; later periods revert to 1.0']),
       padRow(['Contract recognition share (application-locked)', wc.contractRecognitionShare, 'ratio', 'Derived from packet disclosed recognition / comparable nine-month consolidated revenue']),
      padRow(['Other OCA residual opening', wc.otherOcaResidual, 'USD millions', 'Calculated OCA 35,797 - server receivables 17,800 = 17,997; held flat, not disclosed operating-only']),
      padRow(['Other OCL residual opening', wc.otherOclResidual, 'USD millions', 'Calculated reported OCL 24,552 - operating lease 5,535 - finance lease 4,063 - dividend payable 6,760 = 8,194; dividend is financing, excluded from operating NWC and held flat; unclassified residual held flat']),
      padRow(['Long-term AR opening', wc.longTermAr, 'USD millions', 'Separately disclosed noncurrent operating receivable; excluded from current DSO']),
      padRow(['Contract liability current opening', wc.contractCurrent, 'USD millions', 'Reported current contract liability at 2026-03-31']),
      padRow(['Contract liability noncurrent opening', wc.contractNoncurrent, 'USD millions', 'Reported noncurrent contract liability at 2026-03-31']),
      padRow(['Server-component receivables opening', wc.serverReceivables, 'USD millions', 'Disclosed current OCA component; modeled separately']),
      padRow(['Operating AP opening', wc.operatingAp, 'USD millions', 'Calculated reported AP 37,513 - PP&E payable subset 22,600']),
      padRow(['Accrued compensation opening', wc.accruedCompensation, 'USD millions', 'Reported EmployeeRelatedLiabilitiesCurrent']),
      periodRow('P7 period days', wc.days, 'calendar days; stub 91, FY periods actual 365/366'),
       padRow(['Current contract presentation share (application-locked)', wc.currentContractShare, 'ratio', 'Derived from packet current / total contract liability; future presentation estimate']),
       padRow(['P7 driver input check', p7DriverGate(), '', 'Missing, text and invalid P7 inputs fail the all-period gate; zero is explicit where supported.']),
       padRow(['Accrued compensation source baseline', `=B${P7_DRIVER_ROWS.accruedCompensation} / B43`, 'ratio', 'Application-derived from reported opening accrued compensation 11,270 / source TTM revenue 318,273; outside analyst proposal']),
       padRow(['Accrued compensation effective ratio', `=B${P7_DRIVER_ROWS.accruedCompensationBaseline}*B${P7_DRIVER_ROWS.accruedCompensationMultiplier}`, 'ratio', 'Application formula: source baseline × dimensionless multiplier']),
    );
  }
  if (model.tax_forecast) {
    const tax = taxForecastInputs(model);
    // Keep the fixed driver addresses stable after the P7 block.  This makes
    // the saved-input comparison and native Excel proof auditable.
    while (rows.length < TAX_DRIVER_ROWS.bookTaxRate - 2) rows.push(padRow([]));
    rows.push(
      padRow(['P8A tax drivers and reported opening balances', null, null, 'Application-owned inputs; USD millions unless stated']),
      padRow(['Book tax rate', tax.bookTaxRate, 'decimal fraction', 'TTM book tax / pretax proxy; independently reviewed policy']),
      padRow(['Operating tax rate', tax.operatingTaxRate, 'decimal fraction', 'Independent normalized tax on positive EBIT for UFCF']),
      periodRow('Deferred tax expense share of book expense', tax.deferredShare, 'dimensionless; bounded [-1,1]'),
      periodRow('Current tax payable closing balance (explicit method only)', tax.currentTaxPayableClosing ?? Array(PERIODS.length).fill(null), 'USD millions; active only for explicit_closing_balance'),
      periodRow('Long-term tax settlement', tax.longTermTaxSettlement, 'USD millions; cash/liability once, no expense'),
      padRow(['Opening current tax payable', tax.openingCurrent, 'USD millions', 'Reported 2026-03-31 current income-tax liability; source locked']),
      padRow(['Opening long-term income-tax liability', tax.openingLongTerm, 'USD millions', 'Reported 2026-03-31 long-term income taxes; source locked']),
      padRow(['Opening deferred tax liability', tax.openingDeferred, 'USD millions', 'Reported 2026-03-31 deferred income taxes; source locked']),
      padRow(['P8A tax input check', taxDriverGate(), '', 'Missing/invalid tax drivers or unsupported tax balances block all periods and valuation.']),
      padRow(['Interest expense assumption', 0, 'USD millions per forecast period', 'P8A financing input; zero in the production base and editable only for bounded oracle/scenario checks']),
      padRow(['Current tax payable timing method', tax.currentTaxPayableMethod, 'method ID', 'Active method; source_anchored_payable_days derives closing payable from actual period days; explicit_closing_balance uses the closing row']),
      padRow(['Selected current tax payable days', tax.currentTaxPayableDays, 'calendar days', 'Active only for source_anchored_payable_days; bounded [0,365] and source-derived baseline is shown in the evidence packet']),
      periodRow('Tax forecast period days', tax.periodDays, 'calendar days; actual FY2026 stub 91 and FY2027-FY2036 spans 365/366'),
    );
  }
  if (model.financing_forecast) {
    const financing = financingForecast(model);
    const f = FINANCING_DRIVER_ROWS;
    while (rows.length < f.debtFace - 2) rows.push(padRow([]));
    rows.push(
      padRow(['P8B financing drivers and opening containment', null, null, 'Application-owned source facts, policy and calibrated timing; USD millions unless stated']),
      padRow(['Debt face value', financing.debtFace, 'USD millions', 'Q3 Note 9-10; source face measure, not carrying value']),
      padRow(['Debt carrying value', financing.debtCarrying, 'USD millions', 'Q3 Note 9-10; face plus signed contra components']),
      padRow(['Debt fair value', financing.debtFairValue, 'USD millions', 'Q3 Note 9; Level 2; P9 claim once, distinct from carrying value']),
      padRow(['Debt coupon proxy', financing.debtCouponRate, 'decimal fraction', 'Explicit provisional annual cash-interest proxy; not a tranche rate']),
      padRow(['Debt refinancing policy', financing.debtRefinancePolicy, 'method ID', 'Known FY2027/FY2029 face maturities repaid and refinanced at par period end']),
      padRow(['Debt tail policy', financing.debtTailPolicy, 'method ID', '34,890 thereafter held through FY2036 in base; separate runoff scenario disclosed']),
      padRow(['Refinancing term', financing.refinanceTermYears, 'years', 'Selected 30-year par refinancing estimate']),
      padRow(['Refinancing fee rate', financing.refinanceFeeRate, 'decimal fraction', 'Selected zero-fee estimate']),
      padRow(['Opening operating lease ROU', financing.openingOperatingRou, 'USD millions', 'Q3 Note 9-12; separate ROU asset']),
      padRow(['Opening operating lease liability', financing.openingOperatingLiability, 'USD millions', 'Q3 Note 9-12; current/noncurrent source rows carved once']),
      padRow(['Opening finance-lease PP&E', financing.openingFinancePpe, 'USD millions', 'Q3 Note 9-12; contained in reported PP&E and carved once']),
      padRow(['Opening finance-lease liability', financing.openingFinanceLiability, 'USD millions', 'Q3 Note 9-12; debt-like P9 claim once']),
      padRow(['Opening operating remaining book cost', financing.openingOperatingBookCost, 'USD millions', 'Opening ROU + opening contractual cash - opening liability; explicit aggregate proxy']),
      padRow(['Opening operating calibrated rate', financing.openingOperatingRate, 'decimal fraction', 'Application PV calibration from dated disclosed payments; not hard-coded']),
      padRow(['Opening finance calibrated rate', financing.openingFinanceRate, 'decimal fraction', 'Application PV calibration from dated disclosed payments; not hard-coded']),
      padRow(['Disclosed operating weighted rate', financing.operatingWeightedRate, 'decimal fraction', 'Portfolio statistic shown separately from calibrated rate']),
      padRow(['Disclosed finance weighted rate', financing.financeWeightedRate, 'decimal fraction', 'Portfolio statistic shown separately from calibrated rate']),
      padRow(['Uncommenced lease commitments', financing.pipelineCommitments, 'USD millions', 'Q3 Note 12; undiscounted signed pipeline, not opening PV']),
      padRow(['Pipeline finance share', financing.pipelineFinanceShare, 'dimensionless', 'Recent Q3 noncash addition mix proxy: 19,486 / (19,486 + 3,686)']),
      padRow(['Pipeline operating service life', financing.pipelineOperatingLifeYears, 'years', 'Selected six-year estimate']),
      padRow(['Pipeline finance service life', financing.pipelineFinanceLifeYears, 'years', 'Selected thirteen-year estimate']),
      padRow(['Pipeline operating rate', financing.pipelineOperatingRate, 'decimal fraction', 'Disclosed current portfolio proxy']),
      padRow(['Pipeline finance rate', financing.pipelineFinanceRate, 'decimal fraction', 'Disclosed current portfolio proxy']),
      padRow(['Embedded operating lease cost proxy', financing.embeddedCostProxy, 'USD millions', 'Annualized Q3 FY2026 nine-month flow; compatible TTM unavailable; variable/short-term remain embedded']),
      padRow(['P8B financing input check', financingDriverGate(), '', 'Missing, invalid, stale-calibration and containment inputs block linked statements; numeric zero remains valid where supported']),
      periodRow('P8B forecast period days', financing.periodDays, 'calendar days'),
      periodRow('Debt original face redemption', financing.debtRedemption, 'USD millions; gross original face repayment'),
      periodRow('Debt new par proceeds', financing.debtProceeds, 'USD millions; gross period-end refinancing proceeds'),
      periodRow('Opening operating lease payment', financing.operatingPayment, 'USD millions; disclosed bucket/tail allocation'),
      periodRow('Opening finance lease payment', financing.financePayment, 'USD millions; disclosed bucket/tail allocation'),
      periodRow('Pipeline operating PV additions', financing.pipelineOperatingAdditions, 'USD millions; noncash end-period additions'),
      periodRow('Pipeline finance PV additions', financing.pipelineFinanceAdditions, 'USD millions; noncash end-period additions'),
      periodRow('Pipeline operating expense', financing.pipelineOperatingExpense, 'USD millions; zero in commencement period'),
      periodRow('Pipeline finance depreciation', financing.pipelineFinanceDepreciation, 'USD millions; zero in commencement period'),
      padRow(['Debt signed contra total', financing.debtContraTotal, 'USD millions; signed source components preserved']),
      padRow(['Opening current debt classification', financing.openingCurrentDebt, 'USD millions; source presentation']),
      padRow(['Opening noncurrent debt classification', financing.openingNoncurrentDebt, 'USD millions; source presentation']),
      padRow(['Opening operating current liability', financing.openingOperatingCurrentLiability, 'USD millions; contained in source OCL']),
      padRow(['Opening operating noncurrent liability', financing.openingOperatingNoncurrentLiability, 'USD millions; source presentation']),
      padRow(['Opening finance current liability', financing.openingFinanceCurrentLiability, 'USD millions; contained in source OCL']),
      padRow(['Opening finance noncurrent liability', financing.openingFinanceNoncurrentLiability, 'USD millions; contained in source other LT liabilities']),
      periodRow('Pipeline operating interest', financing.pipelineOperatingInterest, 'USD millions; financing interest in PBT/CFO, excluded from UFCF'),
      periodRow('Pipeline finance interest', financing.pipelineFinanceInterest, 'USD millions; financing interest in PBT/CFO, excluded from UFCF'),
      periodRow('Pipeline operating principal', financing.pipelineOperatingPrincipal, 'USD millions; CFO operating lease principal'),
      periodRow('Pipeline finance principal', financing.pipelineFinancePrincipal, 'USD millions; CFF finance lease principal'),
      padRow(['Lease accounting bundle', financing.leaseBundle, 'method ID', 'Selected bundle A: operating lease cost/CFO treatment; finance lease debt-like treatment']),
      padRow(['Pipeline commencement timing policy', financing.pipelineTimingPolicy, 'method ID', 'Actual-day-weighted FY2026-FY2031 cohorts; period-end commencement']),
      padRow(['Opening finance service life', financing.openingFinanceLifeYears, 'years', 'Selected 13-year proxy; 10-year and 16-year alternatives are shown on Sensitivity']),
    );
  }
  if (model.equity_forecast) {
    const equity = equityForecast(model);
    const e = P8C_DRIVER_ROWS;
    while (rows.length < e.sbcRatio - 2) rows.push(padRow([]));
    const equityOutputRows = {
      bookSbc: 6, existingServiceCost: 7, newSbc: 8, grossExistingUnits: 9,
      grossNewUnits: 10, withheldUnits: 11, netDeliveredUnits: 12,
      cashIssuance: 13, issuanceUnits: 14, programTarget: 15, programCash: 16,
      programUnits: 17, programApicBasis: 18, dividendDeclaration: 20,
      dividendPayableOpening: 21, dividendPayableClosing: 22,
      dividendCashPaid: 23, pointSharesOpening: 24, pointSharesClosing: 25,
      basicWeightedShares: 26, dilutedIncrement: 27, basicEps: 28,
      dilutedEps: 29, valuationEbit: 30, normalizedTax: 31,
      valuationUfcf: 32, cfoUfcf: 33, withholdingCash: 19, apicClosing: 34,
      retainedEarningsClosing: 35, aociClosing: 36, totalEquity: 37,
      authorizationRemaining: 38,
    };
    const linked = (name, label, units = 'USD millions') => periodRow(label, PERIODS.map((_, index) => `=Equity!${periodColumn(index)}${equityOutputRows[name]}`), units);
    const serviceDayChoices = {
      2: [91, 365, 275, 0, 0, 0, 0, 0, 0, 0, 0],
      3: [91, 365, 366, 274, 0, 0, 0, 0, 0, 0, 0],
      4: [91, 365, 366, 365, 274, 0, 0, 0, 0, 0, 0],
    };
    const serviceDayFormula = (index) => `=IF($B$${e.existingServiceYears}=2,${serviceDayChoices[2][index]},IF($B$${e.existingServiceYears}=3,${serviceDayChoices[3][index]},IF($B$${e.existingServiceYears}=4,${serviceDayChoices[4][index]},NA())))`;
    const totalServiceDaysFormula = `=IF($B$${e.existingServiceYears}=2,731,IF($B$${e.existingServiceYears}=3,1096,IF($B$${e.existingServiceYears}=4,1461,NA())))`;
    rows.push(
      padRow(['P8C equity drivers and source containment', null, null, 'Source/policy inputs are editable; calculated rows link to Mog Equity formulas. Amounts USD millions unless stated']),
      padRow(['SBC / revenue ratio', equity.sbcRatio, 'decimal fraction', 'TTM source 12,356 / 318,273; P6 gross costs already include SBC']),
      padRow(['Existing award units proxy', equity.existingAwardUnits, 'shares millions', 'FY25 stale proxy; not a Q3 disclosure']),
      padRow(['Existing unrecognized cost proxy', equity.existingUnrecognizedCost, 'USD millions', 'FY25 stale proxy; amortized using actual service days']),
      padRow(['Existing service years', equity.existingServiceYears, 'years', 'Selected bounded 2/3/4-year sensitivity']),
      padRow(['Existing award claim price', equity.existingClaimPrice, 'USD/share', 'P9 Mar31 unadjusted close 370.17; claim price distinct from settlement price']),
      padRow(['Future settlement / repurchase price', equity.settlementPrice, 'USD/share', 'Q3 program cash / program units = 493.296296 historical proxy']),
      padRow(['Withholding rate', equity.withholdingRate, 'decimal fraction', 'FY25 5,400 / 16,200 = one-third proxy']),
      padRow(['Cash issuance / revenue ratio', equity.cashIssuanceRatio, 'decimal fraction', 'TTM cash issuance proxy 2,037 / 318,273']),
      padRow(['Program repurchase / revenue ratio', equity.repurchaseRatio, 'decimal fraction', 'Q3 disclosed cash / revenue proxy; capped at authorization']),
      padRow(['Remaining repurchase authorization', equity.repurchaseAuthorization, 'USD millions', 'Disclosed remaining authorization; no renewal in base']),
      padRow(['Dividend per share per quarter', equity.dividendPerShareQuarter, 'USD/share', 'Selected flat quarterly declaration rate']),
      padRow(['Dividend declaration quarters: stub', equity.dividendQuartersStub, 'quarters', 'One stub declaration']),
      padRow(['Dividend declaration quarters: annual', equity.dividendQuartersAnnual, 'quarters', 'Four full-year declarations']),
      padRow(['P8C equity input check', equityDriverGate(), '', 'Required source/policy inputs and formula-owned outputs are checked; zero supported flows remain valid']),
      periodRow('P8C forecast period days', equity.periodDays, 'calendar days'),
      linked('bookSbc', 'Book SBC expense'),
      linked('existingServiceCost', 'Existing-award service cost', 'USD millions; actual day runoff'),
      linked('newSbc', 'Future new compensation', 'USD millions; blocks if negative'),
      linked('grossExistingUnits', 'Existing gross units delivered', 'shares millions'),
      linked('grossNewUnits', 'Future gross units delivered', 'shares millions'),
      linked('withheldUnits', 'Withheld units', 'shares millions; CFF/APIC once'),
      linked('netDeliveredUnits', 'Net delivered units', 'shares millions'),
      linked('cashIssuance', 'Cash issuance'),
      linked('issuanceUnits', 'Cash issuance units', 'shares millions'),
      linked('programTarget', 'Program repurchase target'),
      linked('programCash', 'Program repurchase cash', 'USD millions; capped, unfunded visible upstream'),
      linked('programUnits', 'Program repurchase units', 'shares millions'),
      linked('programApicBasis', 'Program APIC retirement basis'),
      linked('dividendDeclaration', 'Dividend declaration', 'USD millions; retained earnings'),
      linked('dividendPayableOpening', 'Dividend payable opening', 'USD millions; financing liability'),
      linked('dividendPayableClosing', 'Dividend payable closing', 'USD millions; financing liability'),
      linked('dividendCashPaid', 'Dividend cash paid', 'USD millions; CFF'),
      linked('pointSharesOpening', 'Point shares opening', 'shares millions'),
      linked('pointSharesClosing', 'Point shares closing', 'shares millions'),
      linked('basicWeightedShares', 'Basic weighted-average shares', 'shares millions'),
      linked('dilutedIncrement', 'Treasury-stock-style diluted increment', 'shares millions; proxy; loss antidilutive'),
      linked('basicEps', 'Basic EPS', 'USD/share'),
      linked('dilutedEps', 'Diluted EPS', 'USD/share; proxy'),
      linked('valuationEbit', 'Valuation EBIT', 'USD millions; old service restored once'),
      linked('normalizedTax', 'Normalized valuation tax', 'USD millions'),
      linked('valuationUfcf', 'Valuation UFCF', 'USD millions'),
      linked('cfoUfcf', 'CFO-route UFCF', 'USD millions'),
      linked('withholdingCash', 'Withholding cash settlement', 'USD millions; CFF'),
      linked('apicClosing', 'APIC closing'),
      linked('retainedEarningsClosing', 'Retained earnings closing'),
      linked('aociClosing', 'AOCI closing', 'USD millions; no new OCI'),
      linked('totalEquity', 'Total equity'),
      linked('authorizationRemaining', 'Authorization remaining'),
      padRow(['Embedded source SBC ratio', equity.embeddedSbcRatio, 'decimal fraction', 'TTM source component removed once from P6 operating costs']),
      padRow(['Delivery timing fraction', equity.deliveryTiming, 'fraction within period', 'Selected real base midpoint; live what-if']),
      padRow(['Cash issuance timing fraction', equity.issuanceTiming, 'fraction within period', 'Selected real base midpoint; live what-if']),
      padRow(['Repurchase timing fraction', equity.repurchaseTiming, 'fraction within period', 'Selected real base midpoint; live what-if']),
      periodRow('Existing-award service-day overlap', PERIODS.map((_, index) => serviceDayFormula(index)), 'calendar days; live 2/3/4-year calendar table'),
      padRow(['Existing-award total service days', totalServiceDaysFormula, 'calendar days', 'Apr 1 measurement-following date through selected anniversary, inclusive']),
      padRow(['Opening dividend payable', equity.openingDividendPayable, 'USD millions', 'Reported Q3 opening financing liability']),
      padRow(['Opening point shares', equity.openingPointShares, 'shares millions', 'Reported Q3 point shares']),
      padRow(['Opening APIC', equity.openingApic, 'USD millions', 'Reported Q3 common/APIC balance']),
      padRow(['Opening retained earnings', equity.openingRetained, 'USD millions', 'Reported Q3 retained earnings']),
      padRow(['Opening AOCI', equity.openingAoci, 'USD millions', 'Reported Q3 AOCI']),
      padRow(['Opening total equity', equity.openingTotalEquity, 'USD millions', 'Reported Q3 total stockholders equity']),
    );
  }
  if (model.other_balances_forecast) {
    const d = otherBalancesForecastInputs(model);
    const r = P8D_DRIVER_ROWS;
    while (rows.length < r.otherInvestmentMultiplier - 2) rows.push(padRow([]));
    const linked = (outputRow, label, units = 'USD millions', sign = 1) => periodRow(label, PERIODS.map((_, index) => `${sign === 1 ? '=' : '=-'}OtherBalances!${periodColumn(index)}${outputRow}`), units);
    rows.push(
      padRow(['P8D investments, intangibles, goodwill and residual balances', null, null, 'Application-owned source facts and selected estimates; USD millions unless stated']),
      padRow(['Other investment value multiplier', d.otherInvestmentMultiplier, 'x carrying pool', 'Selected carrying-based estimate; not observed FV; 0.5x/1.5x scenarios']),
      padRow(['Opening cash-income yield', d.cashIncomeYield, 'decimal fraction', 'Opening anchor pool 91,218; 9m interest/dividends 2,546 annualized over 274 days; actual prior-period closing cash thereafter; no circularity']),
      padRow(['Intangible tail life', d.intangibleTailLifeYears, 'years', 'Selected 10-year tail; 6/15-year sensitivities']),
      padRow(['Goodwill impairment', d.goodwillImpairment, 'USD millions', 'Base zero; noncash and nondeductible when selected']),
      padRow(['Unfunded commitment value fraction', d.unfundedCommitmentValueFraction, 'fraction', '1.0x rights value at 1,200 funding; downside 0.0x retains one dated claim']),
      padRow(['Incremental legal stress', d.legalStress, 'USD millions', 'Base zero; 400 adverse loss/cash stress without automatic tax shield']),
      padRow(['Incremental NET DTA value', d.incrementalNetDtaValue, 'USD millions', 'Base zero; historical 0-26,273 sensitivity is not a Q3 carrying fact']),
      padRow(['Known unrealized investment gain', d.unrealizedInvestmentGain, 'USD millions', 'Noncash gain; P8A deferred treatment once, excluded from UFCF']),
      padRow(['Opening cash', d.openingCash, 'USD millions', 'Reported parent balance']),
      padRow(['Opening short-term investments', d.openingShortTermInvestments, 'USD millions', 'Reported parent balance; restricted supplier component retained']),
      padRow(['Opening equity / other investments', d.openingEquityOtherInvestments, 'USD millions', 'Reported carrying pool; rounded subcomponents are not separate NAV']),
      padRow(['Opening financing receivables', d.openingFinancingReceivables, 'USD millions', 'One nonoperating value proxy; current/LT split unknown']),
      padRow(['Opening goodwill', d.openingGoodwill, 'USD millions', 'Reported nonamortizing balance']),
      padRow(['Opening finite-lived intangibles', d.openingIntangibles, 'USD millions', 'Reported net carrying amount']),
      padRow(['Opening other-current-assets residual', d.openingOtherCurrentAssetsResidual, 'USD millions', 'P7 parent residual; includes unresolved financing-receivable split']),
      padRow(['Opening other-long-term-assets parent', d.openingOtherLongTermAssets, 'USD millions', 'Reported parent; Q3 DTA detail unknown']),
      padRow(['Opening other-current-liability residual', d.openingOtherCurrentLiabilityResidual, 'USD millions', 'P7 residual; legal amount remains contained']),
      padRow(['Opening other-long-term-liability residual', d.openingOtherLongTermLiabilityResidual, 'USD millions', 'P8B carve-out already removed; composition remains unresolved']),
      padRow(['Opening deferred-tax liability', d.openingDeferredTaxLiability, 'USD millions', 'Q3 reported; NET DTA convention prevents second standalone claim']),
      padRow(['P8D input check', p8dDriverGate(), '', 'Source parents, selected estimates, explicit schedules and coverage must be complete']),
      linked(P8D_OUTPUT_ROWS.investmentClosing, 'Investment carrying value roll-forward'), linked(P8D_OUTPUT_ROWS.investmentAdditions, 'Investment additions / commitment funding', 'USD millions; CFI outflow equals negative addition'), linked(P8D_OUTPUT_ROWS.cashIncome, 'Cash investment income', 'USD millions; opening-balance actual-day convention'), linked(P8D_OUTPUT_ROWS.noncashGain, 'Noncash unrealized investment gain', 'USD millions; excluded from UFCF'), linked(P8D_OUTPUT_ROWS.investmentValue, 'Investment measurement value bridge', 'USD millions; value once, outside operating EV'), linked(P8D_OUTPUT_ROWS.intangibleOpening, 'Finite-lived intangible opening carrying value'), linked(P8D_OUTPUT_ROWS.intangibleAmortization, 'Finite-lived intangible amortization', 'USD millions; explicit schedule once'), linked(P8D_OUTPUT_ROWS.intangibleClosing, 'Finite-lived intangible closing carrying value'), linked(P8D_OUTPUT_ROWS.goodwillClosing, 'Goodwill closing carrying value'), linked(P8D_OUTPUT_ROWS.dtaValue, 'Incremental NET DTA value estimate'), linked(P8D_OUTPUT_ROWS.commitmentFunding, 'Unfunded commitment CFI funding', 'USD millions; positive source preview, workbook CFI is negative', -1),
      padRow(['P8D coverage', '=IF(B253="PASS","PASS","FAIL")', 'status', 'Cash, ST/equity investments, financing receivables, goodwill, intangibles, OCA/OLTA/OCL residuals, DTA, legal stress and commitments are each represented once; unknown splits remain within source parents.']),
      padRow(['Embedded TTM intangible amortization ratio', d.embeddedIntangibleRatio, 'decimal fraction', 'Application-owned calibration / accepted TTM revenue; removed once from P6 gross operating costs and replaced by the explicit P8D schedule.']),
      padRow(['Unidentified D&A and other residual', d.unidentifiedDnaOther, 'USD millions', 'Historical CFS residual only; diagnostic, never forecast as amortization or CFO add-back.']),
      padRow(['Other-investment pool', d.sourceOtherInvestmentPool, 'USD millions', 'P8D source parent; application-owned Other investment pool carried at the selected multiplier.']),
      padRow(['Known market/cash investment value', d.sourceKnownInvestmentValue, 'USD millions', 'P8D source parent; reported cash and investment balances less the Other pool.']),
      padRow(['Unfunded commitment', d.sourceUnfundedCommitment, 'USD millions', 'P8D source parent; remaining dated commitment funding and claim base.']),
      padRow(['Disclosed intangible amortization — FY2026 stub', d.intangibleSchedule.stub, 'USD millions', 'Reported finite-lived schedule; source value is required and retained once.']),
      padRow(['Disclosed intangible amortization — FY2027', d.intangibleSchedule.annualExplicit[0], 'USD millions', 'Reported finite-lived schedule; source value is required and retained once.']),
      padRow(['Disclosed intangible amortization — FY2028', d.intangibleSchedule.annualExplicit[1], 'USD millions', 'Reported finite-lived schedule; source value is required and retained once.']),
      padRow(['Disclosed intangible amortization — FY2029', d.intangibleSchedule.annualExplicit[2], 'USD millions', 'Reported finite-lived schedule; source value is required and retained once.']),
      padRow(['Disclosed intangible amortization — FY2030', d.intangibleSchedule.annualExplicit[3], 'USD millions', 'Reported finite-lived schedule; source value is required and retained once.']),
      padRow(['Disclosed intangible thereafter pool', d.intangibleSchedule.tail, 'USD millions', 'Reported finite-lived schedule; selected tail life allocates this pool after FY2030.']),
      padRow(['Identified long-term debt investments', d.identifiedLongTermDebtInvestments, 'USD millions', 'Selected eligible investment-income pool anchor; source calibration remains visible.']),
      periodRow('P8D forecast period days', d.periodDays, 'calendar days'),
    );
  }
  return rows;
}

// One formula definition for the original pool, each new cohort and sensitivities.
// Fixed straight-line charge; cumulative expense is capped at the cohort's cost.
function cohortCharge(cost, life, placement, index) {
  const end = PERIODS[index].cumulativeYears;
  const start = index === 0 ? 0 : PERIODS[index - 1].cumulativeYears;
  const boundedCost = `(${cost})`;
  const expenseTo = (t) => `MIN(${boundedCost},${boundedCost}/${life}*MAX(0,${t}-(${placement})))`;
  return `MAX(0,${expenseTo(end)}-${expenseTo(start)})`;
}

function placementFor(index, timing = 'Inputs!$B$31') {
  const start = index === 0 ? 0 : PERIODS[index - 1].cumulativeYears;
  return `${start}+${PERIODS[index].yearFraction}*(1-${timing})`;
}

function cohortRow(index, offset) { return 15 + index * 4 + offset; }

function cohortRows(model = {}) {
  const openingDepreciable = model.financing_forecast ? `=Inputs!$B$13-Inputs!$B$${FINANCING_DRIVER_ROWS.openingFinancePpe}` : '=Inputs!$B$13';
  const rows = [padRow(['Original assets and separate forecast addition cohorts']), padRow(['USD millions. Straight-line fixed charge with remaining book-value cap. Land is held constant and never depreciated.']), periodHeader(), periodLabels(), periodFractions(), periodRow('Cumulative years', PERIODS.map((p) => p.cumulativeYears), 'years'), padRow([]), padRow([])];
  const push = (label, fn) => rows.push(periodRow(label, PERIODS.map((_, i) => fn(periodColumn(i), i))));
  push('Original pool cost / remaining carrying value at measurement date', () => openingDepreciable);
  push('Original pool opening book value', (c, i) => i === 0 ? openingDepreciable : `=${periodColumn(i - 1)}12`);
  push('Original pool depreciation', (c, i) => `=${cohortCharge(openingDepreciable.slice(1), 'Inputs!$B$29', '0', i)}`);
  push('Original pool closing book value', (c) => `=MAX(0,${c}10-${c}11)`);
  push('Nondepreciable land', () => '=Inputs!$B$12');
  rows.push(padRow([]));
  PERIODS.forEach((p, j) => {
    const cost = `Schedules!$${periodColumn(j)}$14`;
    push(`${p.id}: recognized depreciable additions`, (c, i) => i < j ? '=0' : `=${cost}`);
    push(`${p.id}: book value available for depreciation`, (c, i) => i < j ? '=0' : i === j ? `=${cost}` : `=${periodColumn(i - 1)}${cohortRow(j, 3)}`);
    push(`${p.id}: depreciation`, (c, i) => i < j ? '=0' : `=${cohortCharge(cost, 'Inputs!$B$30', placementFor(j), i)}`);
    push(`${p.id}: closing book value`, (c) => `=MAX(0,${c}${cohortRow(j, 1)}-${c}${cohortRow(j, 2)})`);
  });
  return rows;
}

function operatingBaseline(model) {
  const candidate = model.operating_forecast?.embedded_ppe_baseline;
  if (candidate && Number.isFinite(Number(candidate.ttm_ppe_depreciation)) && Number.isFinite(Number(candidate.ttm_revenue)) && Number(candidate.ttm_revenue) > 0) {
    return {
      depreciation: Number(candidate.ttm_ppe_depreciation),
      revenue: Number(candidate.ttm_revenue),
      ratio: Number.isFinite(Number(candidate.ratio)) ? Number(candidate.ratio) : Number(candidate.ttm_ppe_depreciation) / Number(candidate.ttm_revenue),
      basis: candidate.basis ?? 'P5 calculated TTM PP&E-only depreciation / TTM revenue',
      scope: candidate.scope ?? 'aggregate consolidated PP&E-only depreciation proxy',
    };
  }
  const calculated = model.packet?.facts?.calculated;
  const ttmRevenue = model.packet?.facts?.ttm?.revenue?.value;
  if (calculated && Number.isFinite(Number(calculated.ttm_ppe_depreciation)) && Number.isFinite(Number(ttmRevenue)) && Number(ttmRevenue) > 0) {
    return {
      depreciation: Number(calculated.ttm_ppe_depreciation),
      revenue: Number(ttmRevenue),
      ratio: Number(calculated.ttm_ppe_depreciation) / Number(ttmRevenue),
      basis: 'P5 calculated TTM PP&E-only depreciation / TTM revenue',
      scope: 'aggregate consolidated PP&E-only depreciation proxy',
    };
  }
  throw new Error('P6 operating forecast requires a sourced TTM PP&E depreciation baseline');
}

function operatingRows(model) {
  const operating = model.operating_forecast;
  if (!operating) throw new Error('P6 operating forecast is missing');
  const baseline = operatingBaseline(model);
  if (baseline.ratio < 0 || baseline.ratio > 1) throw new Error('P6 embedded PP&E baseline ratio is outside [0,1]');
  const drivers = operatingDriverInputs(model);
  const rows = [
    padRow(['P6 operating forecast — reportable business segments and consolidated costs']),
    padRow(['Frozen P2 observations are anchors; editable Inputs!P6 driver rows drive all forecast formulas. Geography/product alternatives remain separate. Costs stay consolidated; aggregate TTM PP&E depreciation is removed once and actual P5 scheduled depreciation is added once.']),
    periodHeader(), periodLabels(), periodFractions(),
  ];
  const push = (label, values, units = 'USD millions') => rows.push(periodRow(label, values, units));
  for (const [segmentIndex, segment] of OPERATING_SEGMENTS.entries()) {
    const row = 6 + segmentIndex;
    const growthRow = P6_DRIVER_ROWS.segmentGrowth[segment];
    const anchorColumn = drivers.anchors[segment].column;
    const priorFy = `Inputs!$${anchorColumn}$${P6_DRIVER_ROWS.anchors.priorFy}`;
    const priorYtd = `Inputs!$${anchorColumn}$${P6_DRIVER_ROWS.anchors.priorYtd}`;
    const currentYtd = `Inputs!$${anchorColumn}$${P6_DRIVER_ROWS.anchors.currentYtd}`;
    const formulas = PERIODS.map((_, index) => {
      const c = periodColumn(index);
      if (index === 0) return `=(${priorFy}-${priorYtd})*(1+Inputs!$B$${growthRow})`;
      if (index === 1) return `=(${currentYtd}+B${row})*(1+Inputs!C$${growthRow})`;
      return `=${periodColumn(index - 1)}${row}*(1+Inputs!${c}$${growthRow})`;
    });
    push(segment, formulas);
  }
  push('Corporate / eliminations', PERIODS.map(() => '=0'));
  push('Segment revenue total', PERIODS.map((_, index) => `=SUM(${periodColumn(index)}6:${periodColumn(index)}8)`));
  push('Consolidated revenue', PERIODS.map((_, index) => `=${periodColumn(index)}10+${periodColumn(index)}9`));
  rows.push(padRow([]));
  for (const line of ['cost_of_revenue', 'research_and_development', 'sales_and_marketing', 'general_and_administrative']) {
    const label = line.replaceAll('_', ' ').replace(/(^| )\w/g, (value) => value.toUpperCase());
    const ratioRow = P6_DRIVER_ROWS.costRatio[line];
    push(label, PERIODS.map((_, index) => {
      const c = periodColumn(index);
      return `=${c}11*Inputs!${c}$${ratioRow}`;
    }));
  }
  push('Gross reported operating costs', PERIODS.map((_, index) => `=SUM(${periodColumn(index)}13:${periodColumn(index)}16)`));
  push('Embedded PP&E depreciation baseline removed', PERIODS.map((_, index) => `=${periodColumn(index)}11*Inputs!$B$57/Inputs!$B$43`));
  push('P5 scheduled PP&E depreciation added', PERIODS.map((_, index) => `=Schedules!${periodColumn(index)}17`));
  push('Total operating expenses after PP&E substitution', PERIODS.map((_, index) => `=${periodColumn(index)}17-${periodColumn(index)}18+${periodColumn(index)}19`));
  push('Operating costs excluding embedded PP&E depreciation', PERIODS.map((_, index) => `=${periodColumn(index)}17-${periodColumn(index)}18`));
  push('Gross operating-cost ratio', PERIODS.map((_, index) => `=IFERROR(${periodColumn(index)}17/${periodColumn(index)}11,0)`), 'ratio');
  push('Operating margin output', PERIODS.map((_, index) => `=IFERROR((${periodColumn(index)}11-${periodColumn(index)}20)/${periodColumn(index)}11,0)`), 'ratio');
  rows.push(padRow([]));
  rows.push(padRow(['P6 method', `${operating.method.id} / ${operating.method.version}`]));
  rows.push(padRow(['P6 decision status', operating.decision.status]));
  rows.push(padRow(['P6 PP&E baseline', `${baseline.depreciation.toFixed(3)} / ${baseline.revenue.toFixed(3)} = ${(baseline.ratio * 100).toFixed(3)}%; ${baseline.basis}; ${baseline.scope}`]));
  rows.push(padRow(['P6 no-double-count basis', 'Gross consolidated costs retain embedded other amortization/SBC; aggregate TTM PP&E depreciation is removed once and actual P5 scheduled PP&E depreciation is added once.']));
  const residuals = operating.historical_residuals ?? {};
  rows.push(padRow(['P6 historical consolidated-minus-segment residuals', Object.entries(residuals).map(([period, value]) => `${period}=${Number(value).toFixed(3)}`).join('; ')]));
  const comparability = operating.segment_comparability ?? {};
  rows.push(padRow(['P6 segment source comparability', `${comparability.status ?? 'MISSING'}; recast=${comparability.recast_comparison?.status ?? 'NOT_PROVIDED'}; FY25/current/prior YTD definitions preserved in packet evidence.`]));
  rows.push(padRow(['P6 forecast identity / corporate choice', 'Forecast segment revenue total ties to consolidated revenue each period; corporate forecast is explicitly 0.000.']));
  rows.push(padRow(['P6 limitations', operating.limitations.join('; ')]));
  return rows;
}

function workingCapitalRows(model) {
  const wc = workingCapitalInputs(model);
  const rows = [
    padRow(['P7 working-capital schedule — balance based operating cash conversion']),
     padRow(['Forecast balances are formula-owned. Current NWC excludes long-term AR and noncurrent contract liabilities; modeled cash-conversion NWC includes both. Unknown residuals stay visible and flat. Application-locked contract parameters and the accrued-compensation source baseline are derived from the packet.']),
    periodHeader(), periodLabels(), periodFractions(),
  ];
  const push = (label, values, units = 'USD millions') => rows.push(periodRow(label, values, units));
  const input = (row) => `Inputs!$B$${row}`;
  push('Revenue', PERIODS.map((_, i) => `=Operating!${periodColumn(i)}11`));
  push('Cost of revenue denominator proxy', PERIODS.map((_, i) => `=Operating!${periodColumn(i)}13`), 'USD millions; functional COGS proxy');
  push('Period days', PERIODS.map((_, i) => `=Inputs!${periodColumn(i)}${P7_DRIVER_ROWS.periodDays}`), 'calendar days');
  push('Current AR opening', PERIODS.map((_, i) => i === 0 ? `=Inputs!$B$8` : `=${periodColumn(i - 1)}10`));
  push('Current AR closing', PERIODS.map((_, i) => `=${periodColumn(i)}6/${periodColumn(i)}8*${input(P7_DRIVER_ROWS.dso)}`));
  push('Current AR change', PERIODS.map((_, i) => `=${periodColumn(i)}10-${periodColumn(i)}9`));
  push('Inventory opening', PERIODS.map((_, i) => i === 0 ? `=Inputs!$B$9` : `=${periodColumn(i - 1)}13`));
  push('Inventory closing', PERIODS.map((_, i) => `=${periodColumn(i)}7/${periodColumn(i)}8*${input(P7_DRIVER_ROWS.dio)}`));
  push('Inventory change', PERIODS.map((_, i) => `=${periodColumn(i)}13-${periodColumn(i)}12`));
  push('Operating AP opening', PERIODS.map((_, i) => i === 0 ? `=${input(P7_DRIVER_ROWS.operatingAp)}` : `=${periodColumn(i - 1)}16`));
  push('Operating AP closing', PERIODS.map((_, i) => `=${periodColumn(i)}7/${periodColumn(i)}8*${input(P7_DRIVER_ROWS.dpo)}`));
  push('Operating AP change', PERIODS.map((_, i) => `=${periodColumn(i)}16-${periodColumn(i)}15`));
  push('Long-term AR opening', PERIODS.map((_, i) => i === 0 ? `=${input(P7_DRIVER_ROWS.longTermAr)}` : `=${periodColumn(i - 1)}19`));
  push('Long-term AR closing', PERIODS.map((_, i) => `=${periodColumn(i)}18`));
  push('Long-term AR change', PERIODS.map((_, i) => `=${periodColumn(i)}19-${periodColumn(i)}18`));
  push('Server receivables opening', PERIODS.map((_, i) => i === 0 ? `=${input(P7_DRIVER_ROWS.serverReceivables)}` : `=${periodColumn(i - 1)}22`));
  push('Server receivables closing', PERIODS.map((_, i) => i === 0 ? `=${periodColumn(i)}21*(1+${input(P7_DRIVER_ROWS.serverReceivableShock)})` : `=${periodColumn(i)}21`));
  push('Server receivables change', PERIODS.map((_, i) => `=${periodColumn(i)}22-${periodColumn(i)}21`));
  push('Other OCA residual opening', PERIODS.map((_, i) => i === 0 ? `=${input(P7_DRIVER_ROWS.otherOcaResidual)}` : `=${periodColumn(i - 1)}25`));
  push('Other OCA residual closing', PERIODS.map((_, i) => `=${periodColumn(i)}24`));
  push('Other OCA residual change', PERIODS.map((_, i) => `=${periodColumn(i)}25-${periodColumn(i)}24`));
  push('Accrued compensation opening', PERIODS.map((_, i) => i === 0 ? `=${input(P7_DRIVER_ROWS.accruedCompensation)}` : `=${periodColumn(i - 1)}28`));
   push('Accrued compensation closing', PERIODS.map((_, i) => `=${periodColumn(i)}6/${periodColumn(i)}8*365*${input(P7_DRIVER_ROWS.accruedCompensationBaseline)}*${input(P7_DRIVER_ROWS.accruedCompensationMultiplier)}`));
  push('Accrued compensation change', PERIODS.map((_, i) => `=${periodColumn(i)}28-${periodColumn(i)}27`));
  push('Contract liability opening total', PERIODS.map((_, i) => i === 0 ? `=${input(P7_DRIVER_ROWS.contractCurrent)}+${input(P7_DRIVER_ROWS.contractNoncurrent)}` : `=${periodColumn(i - 1)}33`));
  push('Deferred revenue recognized in scoped bridge', PERIODS.map((_, i) => `=${periodColumn(i)}6*${input(P7_DRIVER_ROWS.contractRecognitionShare)}`));
  push('Modeled deferred billings/additions', PERIODS.map((_, i) => i === 0 ? `=${periodColumn(i)}31*${input(P7_DRIVER_ROWS.contractBillingsRatio)}*${input(P7_DRIVER_ROWS.contractBillingMultiplier)}` : `=${periodColumn(i)}31*${input(P7_DRIVER_ROWS.contractBillingsRatio)}`));
  push('Contract liability closing total', PERIODS.map((_, i) => `=${periodColumn(i)}30+${periodColumn(i)}32-${periodColumn(i)}31`));
  push('Contract liability change', PERIODS.map((_, i) => `=${periodColumn(i)}33-${periodColumn(i)}30`));
  push('Current contract liability presentation', PERIODS.map((_, i) => `=${periodColumn(i)}33*${input(P7_DRIVER_ROWS.currentContractShare)}`));
  push('Noncurrent contract liability presentation', PERIODS.map((_, i) => `=${periodColumn(i)}33-${periodColumn(i)}35`));
  push('Other OCL residual opening', PERIODS.map((_, i) => i === 0 ? `=${input(P7_DRIVER_ROWS.otherOclResidual)}` : `=${periodColumn(i - 1)}38`));
  push('Other OCL residual closing', PERIODS.map((_, i) => `=${periodColumn(i)}37`));
  push('Other OCL residual change', PERIODS.map((_, i) => `=${periodColumn(i)}38-${periodColumn(i)}37`));
  push('Conventional current operating NWC', PERIODS.map((_, i) => `=${periodColumn(i)}10+${periodColumn(i)}13+${periodColumn(i)}22+${periodColumn(i)}25-${periodColumn(i)}16-${periodColumn(i)}28-${periodColumn(i)}35-${periodColumn(i)}38`));
  push('Modeled cash-conversion NWC', PERIODS.map((_, i) => `=${periodColumn(i)}10+${periodColumn(i)}13+${periodColumn(i)}22+${periodColumn(i)}25+${periodColumn(i)}19-${periodColumn(i)}16-${periodColumn(i)}28-${periodColumn(i)}33-${periodColumn(i)}38`));
  const openingNwc = `Inputs!$B$8+Inputs!$B$9+${input(P7_DRIVER_ROWS.serverReceivables)}+${input(P7_DRIVER_ROWS.otherOcaResidual)}+${input(P7_DRIVER_ROWS.longTermAr)}-${input(P7_DRIVER_ROWS.operatingAp)}-${input(P7_DRIVER_ROWS.accruedCompensation)}-${input(P7_DRIVER_ROWS.contractCurrent)}-${input(P7_DRIVER_ROWS.contractNoncurrent)}-${input(P7_DRIVER_ROWS.otherOclResidual)}`;
  push('Increase in modeled cash-conversion NWC', PERIODS.map((_, i) => i === 0 ? `=${periodColumn(i)}41-(${openingNwc})` : `=${periodColumn(i)}41-${periodColumn(i - 1)}41`));
  push('CFO contribution from working capital', PERIODS.map((_, i) => `=-${periodColumn(i)}42`));
  rows.push(padRow([]), padRow(['Historical balance / reported CFS bridge', null, null, 'Reported movements remain beside unresolved diagnostics; no forecast plug.']));
  const packet = model.working_capital_packet ?? {};
  for (const [name, item] of Object.entries(packet.historical_bridge ?? {})) rows.push(padRow([name, item.balance_change_fy25_to_q3, item.reported_cfs_contribution_9m, item.unexplained_difference, item.source_identity]));
  const oclBridge = packet.ocl_bridge ?? {};
  rows.push(padRow(['OCL classification', 'Reported OCL ' + (oclBridge.reported_other_current_liabilities ?? 'MISSING') + ' less leases ' + ((oclBridge.operating_lease_liability ?? 0) + (oclBridge.finance_lease_liability ?? 0)) + ' less financing dividend ' + (oclBridge.dividend_payable_financing ?? 'MISSING') + ' = unclassified residual ' + (oclBridge.unclassified_operating_residual ?? 'MISSING'), null, null, oclBridge.financing_exclusion ?? 'Q3 Note 14 dividend payable excluded from operating NWC and held flat; P8C owns payment/declaration roll-forward.']));
  rows.push(padRow(['Contract liability identity', '=67265+143442-157030', 53677, '=B' + (rows.length + 1) + '-C' + (rows.length + 1), 'Actual Q3 Note 11; 9-month USD millions; deferrals are not cash receipts']), padRow(['Contract bridge note', 'Aggregate scoped liability bridge assumes no forecast change in separately unidentified contract assets; negative liability blocks the model gate.', null, null, 'Missing source is not zero']));
  rows.push(padRow(['P7 method / policy', `${model.working_capital_forecast.method.id} / ${model.working_capital_forecast.method.version}; LT AR and noncurrent contract included in modeled cash-conversion NWC; conventional current NWC shown separately.`]));
  return rows;
}

function taxRows(model) {
  const tax = taxForecastInputs(model);
  const rows = [
    padRow(['P8A tax schedule — linked book/current/deferred/cash bridge']),
    padRow(['USD millions unless stated. Book/current/deferred tax and cash timing remain separate; operating tax is an independent positive-EBIT UFCF driver.']),
    periodHeader(), periodLabels(), periodFractions(),
  ];
  const push = (label, values, units = 'USD millions') => rows.push(periodRow(label, values, units));
  push('EBIT', PERIODS.map((_, i) => `=Income!${periodColumn(i)}11`));
  push('Interest expense', PERIODS.map((_, i) => `=-Income!${periodColumn(i)}12`));
  push('Pre-tax income', PERIODS.map((_, i) => `=Income!${periodColumn(i)}13`));
  push('Positive pre-tax income', PERIODS.map((_, i) => `=MAX(0,${periodColumn(i)}8${model.other_balances_forecast ? `+OtherBalances!${periodColumn(i)}${P8D_OUTPUT_ROWS.goodwillImpairment}+OtherBalances!${periodColumn(i)}${P8D_OUTPUT_ROWS.legalStress}` : ''})`));
  push('Book tax rate', PERIODS.map(() => `=Inputs!$B$${TAX_DRIVER_ROWS.bookTaxRate}`), 'decimal fraction');
  push('Book tax expense', PERIODS.map((_, i) => `=${periodColumn(i)}9*${periodColumn(i)}10`));
  push('Deferred tax expense share', PERIODS.map((_, i) => `=Inputs!${periodColumn(i)}${TAX_DRIVER_ROWS.deferredShare}`), 'dimensionless');
  push('Deferred tax expense', PERIODS.map((_, i) => `=${periodColumn(i)}11*${periodColumn(i)}12${model.other_balances_forecast ? `+OtherBalances!${periodColumn(i)}${P8D_OUTPUT_ROWS.noncashGain}*Inputs!$B$${TAX_DRIVER_ROWS.bookTaxRate}` : ''}`));
  push('Current tax expense', PERIODS.map((_, i) => `=${periodColumn(i)}11-${periodColumn(i)}13`));
  push('Current tax payable opening', PERIODS.map((_, i) => i === 0 ? `=Inputs!$B$${TAX_DRIVER_ROWS.openingCurrentTaxPayable}` : `=${periodColumn(i - 1)}16`));
  push('Current tax payable closing', PERIODS.map((_, i) => `=IF(Inputs!$B$${TAX_DRIVER_ROWS.currentTaxPayableMethod}="source_anchored_payable_days",IFERROR(${periodColumn(i)}14/Inputs!${periodColumn(i)}${TAX_DRIVER_ROWS.periodDays}*Inputs!$B$${TAX_DRIVER_ROWS.currentTaxPayableDays},NA()),IF(Inputs!$B$${TAX_DRIVER_ROWS.currentTaxPayableMethod}="explicit_closing_balance",Inputs!${periodColumn(i)}${TAX_DRIVER_ROWS.currentTaxPayableClosing},NA()))`));
  push('Current tax payment', PERIODS.map((_, i) => `=${periodColumn(i)}15+${periodColumn(i)}14-${periodColumn(i)}16`));
  push('Long-term tax liability opening', PERIODS.map((_, i) => i === 0 ? `=Inputs!$B$${TAX_DRIVER_ROWS.openingLongTermTaxLiability}` : `=${periodColumn(i - 1)}20`));
  push('Long-term tax settlement', PERIODS.map((_, i) => `=Inputs!${periodColumn(i)}${TAX_DRIVER_ROWS.longTermTaxSettlement}`));
  push('Long-term tax liability closing', PERIODS.map((_, i) => `=${periodColumn(i)}18-${periodColumn(i)}19`));
  push('Deferred tax liability opening', PERIODS.map((_, i) => i === 0 ? `=Inputs!$B$${TAX_DRIVER_ROWS.openingDeferredTaxLiability}` : `=${periodColumn(i - 1)}22`));
  push('Deferred tax liability closing', PERIODS.map((_, i) => `=${periodColumn(i)}21+${periodColumn(i)}13`));
  push('Deferred tax add-back', PERIODS.map((_, i) => `=${periodColumn(i)}13`));
  push('Current tax payable movement / CFO effect', PERIODS.map((_, i) => `=${periodColumn(i)}16-${periodColumn(i)}15`));
  push('Long-term tax settlement / CFO effect', PERIODS.map((_, i) => `=-${periodColumn(i)}19`));
  push('Total tax CFO adjustment', PERIODS.map((_, i) => `=${periodColumn(i)}23+${periodColumn(i)}24+${periodColumn(i)}25`));
  push('Modeled company cash taxes (forecast; includes selected financing effects)', PERIODS.map((_, i) => `=${periodColumn(i)}17+${periodColumn(i)}19`));
  push('Operating tax rate', PERIODS.map(() => `=Inputs!$B$${TAX_DRIVER_ROWS.operatingTaxRate}`), 'decimal fraction');
  push('Normalized operating tax on positive EBIT', PERIODS.map((_, i) => `=MAX(0,${periodColumn(i)}6)*${periodColumn(i)}28`));
  push('Tax period check', PERIODS.map((_, i) => `=IFERROR(IF(AND(${periodColumn(i)}16>=0,${periodColumn(i)}17>=0,${periodColumn(i)}19>=0,${periodColumn(i)}20>=0,${periodColumn(i)}22>=0,${periodColumn(i)}27>=0),"PASS","FAIL"),"FAIL")`), 'status');
  rows.push(padRow(['P8A policy note', 'A loss yields zero book/operating tax in the base. No NOL utilization, DTA recognition, unsupported refund or settlement expense is inferred.']), padRow(['P8A source containment', 'Current tax 3,563, long-term tax 27,941 and deferred tax liability 2,899 are carved from the containing reported liability aggregate exactly once.']));
  return rows;
}

function financingRows(model) {
  const financing = financingForecast(model);
  const f = FINANCING_DRIVER_ROWS;
  const rows = [
    padRow(['P8B financing schedule — debt, operating leases and finance leases']),
    padRow(['Source balances remain separate from estimated timing. Debt interest uses opening face and actual days/365; lease additions occur at period end.']),
    periodHeader(), periodLabels(), periodFractions(),
  ];
  const push = (label, values, units = 'USD millions') => rows.push(periodRow(label, values, units));
  const input = (row, column = 'B') => `Inputs!${column}$${row}`;
  const next = (index, row) => index + 1 < PERIODS.length ? `${periodColumn(index + 1)}${row}` : '0';
  const currentPortion = (totalRow, principalRow, index) => index + 1 < PERIODS.length ? `=MIN(${periodColumn(index)}${totalRow},MAX(0,${periodColumn(index + 1)}${principalRow}))` : '=0';
  push('Original debt face opening', PERIODS.map((_, i) => i === 0 ? `=${input(f.debtFace)}` : `=${periodColumn(i - 1)}8`)); // 6
  push('Original debt face redemption', PERIODS.map((_, i) => `=${input(f.debtRedemption, periodColumn(i))}`)); // 7
  push('Original debt face closing', PERIODS.map((_, i) => `=${periodColumn(i)}6-${periodColumn(i)}7`)); // 8
  push('New par debt opening', PERIODS.map((_, i) => i === 0 ? '=0' : `=${periodColumn(i - 1)}11`)); // 9
  push('New par debt proceeds', PERIODS.map((_, i) => `=${input(f.debtProceeds, periodColumn(i))}`)); // 10
  push('New par debt closing', PERIODS.map((_, i) => `=${periodColumn(i)}9+${periodColumn(i)}10`)); // 11
  push('Total debt face opening', PERIODS.map((_, i) => `=${periodColumn(i)}6+${periodColumn(i)}9`)); // 12
  push('Total debt face closing', PERIODS.map((_, i) => `=${periodColumn(i)}8+${periodColumn(i)}11`)); // 13
  push('Debt cash interest', PERIODS.map((_, i) => `=${periodColumn(i)}12*${input(f.debtCouponRate)}*${input(f.periodDays, periodColumn(i))}/365`)); // 14
  push('Opening signed debt contra', PERIODS.map((_, i) => i === 0 ? `=${input(f.debtContraTotal)}` : `=${periodColumn(i - 1)}17`)); // 15
  push('Debt contra release expense', PERIODS.map((_, i) => `=IFERROR(-${periodColumn(i)}15*${periodColumn(i)}7/${periodColumn(i)}6,0)`)); // 16
  push('Closing signed debt contra', PERIODS.map((_, i) => `=${periodColumn(i)}15+${periodColumn(i)}16`)); // 17
  push('Debt book financing expense', PERIODS.map((_, i) => `=${periodColumn(i)}14+${periodColumn(i)}16`)); // 18
  push('Debt gross repayment', PERIODS.map((_, i) => `=${periodColumn(i)}7`)); // 19
  push('Debt gross refinancing proceeds', PERIODS.map((_, i) => `=${periodColumn(i)}10`)); // 20
  push('Debt net financing cash', PERIODS.map((_, i) => `=${periodColumn(i)}20-${periodColumn(i)}19`)); // 21
  push('Debt face due next 12 months', PERIODS.map((_, i) => i + 1 < PERIODS.length ? `=${periodColumn(i + 1)}7` : '=0')); // 22
  push('Debt contra allocated to current face', PERIODS.map((_, i) => `=IFERROR(${periodColumn(i)}17*${periodColumn(i)}22/${periodColumn(i)}8,0)`)); // 23
  push('Current debt carrying value', PERIODS.map((_, i) => `=${periodColumn(i)}22+${periodColumn(i)}23`)); // 24
  push('Noncurrent debt carrying value', PERIODS.map((_, i) => `=${periodColumn(i)}13+${periodColumn(i)}17-${periodColumn(i)}24`)); // 25
  push('Debt fair value comparator', PERIODS.map(() => `=${input(f.debtFairValue)}`)); // 26
  push('Debt schedule status', PERIODS.map((_, i) => `=IF(AND(${periodColumn(i)}8>=-${TOLERANCE},${periodColumn(i)}11>=-${TOLERANCE},${periodColumn(i)}13+${periodColumn(i)}17>=-${TOLERANCE}),"PASS","FAIL")`), 'status'); // 27
  rows.push(padRow([]));
  push('Opening operating lease liability', PERIODS.map((_, i) => i === 0 ? `=${input(f.openingOperatingLiability)}` : `=${periodColumn(i - 1)}52`)); // 29
  push('Opening operating lease interest', PERIODS.map((_, i) => `=${periodColumn(i)}29*((1+${input(f.openingOperatingRate)})^(${input(f.periodDays, periodColumn(i))}/365)-1)`)); // 30
  push('Opening operating lease payment', PERIODS.map((_, i) => `=${input(f.operatingPayment, periodColumn(i))}`)); // 31
  push('Opening operating lease principal', PERIODS.map((_, i) => `=${periodColumn(i)}31-${periodColumn(i)}30`)); // 32
  push('Opening operating lease liability closing', PERIODS.map((_, i) => `=${periodColumn(i)}29+${periodColumn(i)}30-${periodColumn(i)}31`)); // 33
  push('Opening operating lease ROU asset', PERIODS.map((_, i) => i === 0 ? `=${input(f.openingOperatingRou)}` : `=${periodColumn(i - 1)}54`)); // 34
  push('Opening operating lease expense', PERIODS.map((_, i) => `=IFERROR(${input(f.openingOperatingBookCost)}*${periodColumn(i)}31/SUM(Inputs!$B$${f.operatingPayment}:Inputs!$L$${f.operatingPayment}),NA())`)); // 35
  push('Opening operating lease ROU amortization', PERIODS.map((_, i) => `=${periodColumn(i)}35-${periodColumn(i)}30`)); // 36
  push('Opening operating lease ROU closing', PERIODS.map((_, i) => `=${periodColumn(i)}34-${periodColumn(i)}36`)); // 37
  rows.push(padRow([]));
  push('Opening finance lease liability', PERIODS.map((_, i) => i === 0 ? `=${input(f.openingFinanceLiability)}` : `=${periodColumn(i - 1)}53`)); // 39
  push('Opening finance lease interest', PERIODS.map((_, i) => `=${periodColumn(i)}39*((1+${input(f.openingFinanceRate)})^(${input(f.periodDays, periodColumn(i))}/365)-1)`)); // 40
  push('Opening finance lease payment', PERIODS.map((_, i) => `=${input(f.financePayment, periodColumn(i))}`)); // 41
  push('Opening finance lease principal', PERIODS.map((_, i) => `=${periodColumn(i)}41-${periodColumn(i)}40`)); // 42
  push('Opening finance lease liability closing', PERIODS.map((_, i) => `=${periodColumn(i)}39+${periodColumn(i)}40-${periodColumn(i)}41`)); // 43
  push('Opening finance lease PP&E asset', PERIODS.map((_, i) => i === 0 ? `=${input(f.openingFinancePpe)}` : `=${periodColumn(i - 1)}46`)); // 44
  push('Opening finance lease depreciation', PERIODS.map((_, i) => `=MIN(${periodColumn(i)}44,${input(f.openingFinancePpe)}/${input(f.openingFinanceLifeYears)}*${input(f.periodDays, periodColumn(i))}/365)`)); // 45
  push('Opening finance lease PP&E closing', PERIODS.map((_, i) => `=${periodColumn(i)}44-${periodColumn(i)}45`)); // 46
  rows.push(padRow([]));
  push('Pipeline operating PV additions', PERIODS.map((_, i) => `=${input(f.pipelineOperatingAdditions, periodColumn(i))}`)); // 48
  push('Pipeline finance PV additions', PERIODS.map((_, i) => `=${input(f.pipelineFinanceAdditions, periodColumn(i))}`)); // 49
  push('Pipeline operating expense', PERIODS.map((_, i) => `=${input(f.pipelineOperatingExpense, periodColumn(i))}`)); // 50
  push('Pipeline finance depreciation', PERIODS.map((_, i) => `=${input(f.pipelineFinanceDepreciation, periodColumn(i))}`)); // 51
  push('Total operating lease liability closing', PERIODS.map((_, i) => `=${periodColumn(i)}33+${periodColumn(i)}48+${input(f.pipelineOperatingInterest, periodColumn(i))}-${input(f.pipelineOperatingPrincipal, periodColumn(i))}-${input(f.pipelineOperatingInterest, periodColumn(i))}`)); // 52
  push('Total finance lease liability closing', PERIODS.map((_, i) => `=${periodColumn(i)}43+${periodColumn(i)}49+${input(f.pipelineFinanceInterest, periodColumn(i))}-${input(f.pipelineFinancePrincipal, periodColumn(i))}-${input(f.pipelineFinanceInterest, periodColumn(i))}`)); // 53
  push('Total operating lease ROU closing', PERIODS.map((_, i) => `=${periodColumn(i)}37+${periodColumn(i)}48-${input(f.pipelineOperatingExpense, periodColumn(i))}+${input(f.pipelineOperatingInterest, periodColumn(i))}`)); // 54
  push('Total finance lease PP&E closing', PERIODS.map((_, i) => `=${i === 0 ? `${periodColumn(i)}44` : `${periodColumn(i - 1)}55`}+${periodColumn(i)}49-${periodColumn(i)}45-${input(f.pipelineFinanceDepreciation, periodColumn(i))}`)); // 55
  push('Total operating lease cash payment', PERIODS.map((_, i) => `=${periodColumn(i)}31+${input(f.pipelineOperatingAdditions, periodColumn(i))}*0+${input(f.pipelineOperatingPrincipal, periodColumn(i))}+${input(f.pipelineOperatingInterest, periodColumn(i))}`)); // 56
  push('Total finance lease cash payment', PERIODS.map((_, i) => `=${periodColumn(i)}41+${input(f.pipelineFinancePrincipal, periodColumn(i))}+${input(f.pipelineFinanceInterest, periodColumn(i))}`)); // 57
  push('Total finance lease principal', PERIODS.map((_, i) => `=${periodColumn(i)}42+${input(f.pipelineFinancePrincipal, periodColumn(i))}`)); // 58
  push('Total operating lease principal', PERIODS.map((_, i) => `=${periodColumn(i)}32+${input(f.pipelineOperatingPrincipal, periodColumn(i))}`)); // 59
  push('Total lease noncash additions', PERIODS.map((_, i) => `=${periodColumn(i)}48+${periodColumn(i)}49`)); // 60
  push('Embedded operating lease cost removed', PERIODS.map((_, i) => `=${input(f.embeddedOperatingLeaseCostProxy)}*Schedules!${periodColumn(i)}10/Inputs!$B$43`)); // 61
  push('Total operating lease interest', PERIODS.map((_, i) => `=${periodColumn(i)}30+${input(f.pipelineOperatingInterest, periodColumn(i))}`)); // 62
  push('Total finance lease interest', PERIODS.map((_, i) => `=${periodColumn(i)}40+${input(f.pipelineFinanceInterest, periodColumn(i))}`)); // 63
  push('Total operating lease expense', PERIODS.map((_, i) => `=${periodColumn(i)}35+${periodColumn(i)}50`)); // 64
  push('Total operating lease ROU amortization', PERIODS.map((_, i) => `=${periodColumn(i)}36+${periodColumn(i)}50-${input(f.pipelineOperatingInterest, periodColumn(i))}`)); // 65
  push('Total finance lease depreciation', PERIODS.map((_, i) => `=${periodColumn(i)}45+${periodColumn(i)}51`)); // 66
  push('Total finance lease principal', PERIODS.map((_, i) => `=${periodColumn(i)}58`)); // 67
  push('Total operating lease principal', PERIODS.map((_, i) => `=${periodColumn(i)}59`)); // 68
  push('Current operating lease liability', PERIODS.map((_, i) => currentPortion(52, 59, i))); // 69
  push('Noncurrent operating lease liability', PERIODS.map((_, i) => `=${periodColumn(i)}52-${periodColumn(i)}69`)); // 70
  push('Current finance lease liability', PERIODS.map((_, i) => currentPortion(53, 58, i))); // 71
  push('Noncurrent finance lease liability', PERIODS.map((_, i) => `=${periodColumn(i)}53-${periodColumn(i)}71`)); // 72
  push('Funding status', PERIODS.map((_, i) => `=IF(Schedules!${periodColumn(i)}31<0,"UNFUNDED","OK")`), 'status'); // 73
  push('Opening-pool calibration status', PERIODS.map((_, i) => `=IF(AND(${periodColumn(i)}33>=-${TOLERANCE},${periodColumn(i)}37>=-${TOLERANCE},${periodColumn(i)}43>=-${TOLERANCE},${periodColumn(i)}46>=-${TOLERANCE}),"PASS","FAIL")`), 'status'); // 74
  rows.push(padRow(['P8B schedule note', 'Debt classification is noncash; gross repayment/proceeds remain separate. Operating lease cash stays in CFO/UFCF; finance principal stays in CFF; finance noncash additions enter economic UFCF once.']));
  return rows;
}

// The optional fixture conventions keep the parent oracle's explicit
// accounting convention inside this shared formula builder. Production uses
// the selected opening-balance APIC basis and one-quarter dividend payable;
// the fictional oracle uses cash retirement and a fully settled dividend so
// its movements can be reconciled in one period without inventing a source
// payable. No oracle-only calculation engine is introduced.
export function equityRows(model, options = {}) {
  const equity = equityForecast(model);
  const e = P8C_DRIVER_ROWS;
  const financing = Boolean(model.financing_forecast);
  const tax = Boolean(model.tax_forecast);
  const rows = [
    padRow(['P8C equity schedule — SBC, shares, capital returns and valuation bridge']),
    padRow(['USD millions unless stated. Formulas recalculate from linked P6/P8A/P8B statements; reported opening equity, stale proxies, prices and timing remain visible inputs.']),
    periodHeader(), periodLabels(), periodFractions(),
  ];
  const push = (label, values, units = 'USD millions') => rows.push(periodRow(label, values, units));
  const input = (row) => `Inputs!$B$${row}`;
  const oldUnitsOpening = (index) => index === 0 ? input(e.existingAwardUnits) : `MAX(0,${input(e.existingAwardUnits)}-SUM($B$9:${periodColumn(index - 1)}9))`;
  const oldUnitsClosing = (index) => `MAX(0,${input(e.existingAwardUnits)}-SUM($B$9:${periodColumn(index)}9))`;
  const oldCostOpening = (index) => index === 0 ? input(e.existingUnrecognizedCost) : `MAX(0,${input(e.existingUnrecognizedCost)}-SUM($B$7:${periodColumn(index - 1)}7))`;
  const oldCostClosing = (index) => `MAX(0,${input(e.existingUnrecognizedCost)}-SUM($B$7:${periodColumn(index)}7))`;
  push('Book SBC expense', PERIODS.map((_, i) => `=Schedules!${periodColumn(i)}10*${input(e.sbcRatio)}`));
  push('Existing-award service cost', PERIODS.map((_, i) => `=${input(e.existingUnrecognizedCost)}*Inputs!${periodColumn(i)}${e.serviceDays}/${input(e.totalServiceDays)}`));
  push('Future new compensation', PERIODS.map((_, i) => `=${periodColumn(i)}6-${periodColumn(i)}7`));
  push('Existing gross units delivered', PERIODS.map((_, i) => `=${input(e.existingAwardUnits)}*Inputs!${periodColumn(i)}${e.serviceDays}/${input(e.totalServiceDays)}`), 'shares millions');
  push('Future gross units delivered', PERIODS.map((_, i) => `=${periodColumn(i)}8/${input(e.settlementPrice)}`), 'shares millions');
  push('Withheld units', PERIODS.map((_, i) => `=(${periodColumn(i)}9+${periodColumn(i)}10)*${input(e.withholdingRate)}`), 'shares millions');
  push('Net employee delivery', PERIODS.map((_, i) => `=${periodColumn(i)}9+${periodColumn(i)}10-${periodColumn(i)}11`), 'shares millions');
  push('Cash issuance', PERIODS.map((_, i) => `=Schedules!${periodColumn(i)}10*${input(e.cashIssuanceRatio)}`));
  push('Cash issuance units', PERIODS.map((_, i) => `=${periodColumn(i)}13/${input(e.settlementPrice)}`), 'shares millions');
  push('Program repurchase target', PERIODS.map((_, i) => `=Schedules!${periodColumn(i)}10*${input(e.repurchaseRatio)}`));
  push('Program repurchase cash', PERIODS.map((_, i) => i === 0 ? `=MIN(B15,${input(e.repurchaseAuthorization)})` : `=MIN(${periodColumn(i)}15,${periodColumn(i - 1)}38)`));
  push('Program retired units', PERIODS.map((_, i) => `=${periodColumn(i)}16/${input(e.settlementPrice)}`), 'shares millions');
  push('Program APIC retirement basis', PERIODS.map((_, i) => options.programApicBasisMode === 'cash'
    ? `=${periodColumn(i)}16`
    : `=IFERROR(${(i === 0 ? input(e.openingApic) : `${periodColumn(i - 1)}34`)}/${periodColumn(i)}24*${periodColumn(i)}17,NA())`));
  push('Withholding cash settlement', PERIODS.map((_, i) => `=${periodColumn(i)}11*${input(e.settlementPrice)}`));
  push('Dividend declaration', PERIODS.map((_, i) => `=${periodColumn(i)}24*${input(e.dividendPerShareQuarter)}*IF(${periodColumn(i)}$3="FY2026_STUB",${input(e.dividendQuartersStub)},${input(e.dividendQuartersAnnual)})`));
  push('Dividend payable opening', PERIODS.map((_, i) => i === 0 ? `=${input(e.openingDividendPayable)}` : `=${periodColumn(i - 1)}22`));
  push('Dividend payable closing', PERIODS.map((_, i) => options.dividendPayableMode === 'settled'
    ? '=0'
    : `=${periodColumn(i)}24*${input(e.dividendPerShareQuarter)}`));
  push('Dividend cash paid', PERIODS.map((_, i) => `=${periodColumn(i)}21+${periodColumn(i)}20-${periodColumn(i)}22`));
  push('Point shares opening', PERIODS.map((_, i) => i === 0 ? `=${input(e.openingPointShares)}` : `=${periodColumn(i - 1)}25`), 'shares millions');
  push('Point shares closing', PERIODS.map((_, i) => `=${periodColumn(i)}24+${periodColumn(i)}12+${periodColumn(i)}14-${periodColumn(i)}17`), 'shares millions');
  push('Basic weighted-average shares', PERIODS.map((_, i) => `=${periodColumn(i)}24+${periodColumn(i)}12*${input(e.deliveryTiming)}+${periodColumn(i)}14*${input(e.issuanceTiming)}-${periodColumn(i)}17*${input(e.repurchaseTiming)}`), 'shares millions');
  push('Treasury-stock-style diluted increment', PERIODS.map((_, i) => `=IF(Income!${periodColumn(i)}15>0,MAX(0,((${oldUnitsOpening(i)})+(${oldUnitsClosing(i)}))/2-(((${oldCostOpening(i)})+(${oldCostClosing(i)}))/2)/${input(e.settlementPrice)}),0)`), 'shares millions; proxy');
  push('Basic EPS', PERIODS.map((_, i) => `=Income!${periodColumn(i)}15/${periodColumn(i)}26`), 'USD/share');
  push('Diluted EPS', PERIODS.map((_, i) => `=Income!${periodColumn(i)}15/(${periodColumn(i)}26+${periodColumn(i)}27)`), 'USD/share; proxy');
  push('Valuation EBIT', PERIODS.map((_, i) => `=Income!${periodColumn(i)}11+${periodColumn(i)}7`));
  push('Normalized tax', PERIODS.map((_, i) => tax ? `=MAX(0,${periodColumn(i)}30)*Taxes!${periodColumn(i)}28` : `=MAX(0,${periodColumn(i)}30)*Inputs!$B$35`));
  push('Valuation UFCF', PERIODS.map((_, i) => financing ? `=${periodColumn(i)}30-${periodColumn(i)}31+Schedules!${periodColumn(i)}17+Financing!${periodColumn(i)}64-Financing!${periodColumn(i)}56-Schedules!${periodColumn(i)}14-Financing!${periodColumn(i)}49-Schedules!${periodColumn(i)}26${model.other_balances_forecast ? `+OtherBalances!${periodColumn(i)}${P8D_OUTPUT_ROWS.intangibleAmortization}-OtherBalances!${periodColumn(i)}${P8D_OUTPUT_ROWS.legalStress}` : ''}` : `=${periodColumn(i)}30-${periodColumn(i)}31+Schedules!${periodColumn(i)}17-Schedules!${periodColumn(i)}14-Schedules!${periodColumn(i)}26${model.other_balances_forecast ? `+OtherBalances!${periodColumn(i)}${P8D_OUTPUT_ROWS.intangibleAmortization}-OtherBalances!${periodColumn(i)}${P8D_OUTPUT_ROWS.legalStress}` : ''}`));
  push('CFO route UFCF', PERIODS.map((_, i) => financing ? `=CashFlow!${periodColumn(i)}12+Financing!${periodColumn(i)}18+Financing!${periodColumn(i)}63+Taxes!${periodColumn(i)}27-${periodColumn(i)}31-${periodColumn(i)}8+Financing!${periodColumn(i)}64-Financing!${periodColumn(i)}56-Financing!${periodColumn(i)}65-Financing!${periodColumn(i)}16+Financing!${periodColumn(i)}68-Schedules!${periodColumn(i)}14-Financing!${periodColumn(i)}49${model.other_balances_forecast ? `-OtherBalances!${periodColumn(i)}${P8D_OUTPUT_ROWS.cashIncome}` : ''}` : `=CashFlow!${periodColumn(i)}9-${periodColumn(i)}31-${periodColumn(i)}8-Schedules!${periodColumn(i)}14${model.other_balances_forecast ? `-OtherBalances!${periodColumn(i)}${P8D_OUTPUT_ROWS.cashIncome}` : ''}`));
  push('APIC closing', PERIODS.map((_, i) => i === 0 ? `=${input(e.openingApic)}+${periodColumn(i)}6+${periodColumn(i)}13-${periodColumn(i)}19-${periodColumn(i)}18` : `=${periodColumn(i - 1)}34+${periodColumn(i)}6+${periodColumn(i)}13-${periodColumn(i)}19-${periodColumn(i)}18`));
  push('Retained earnings closing', PERIODS.map((_, i) => {
    const opening = i === 0 ? input(e.openingRetainedEarnings) : `${periodColumn(i - 1)}35`;
    const repurchaseExcess = options.programApicBasisMode === 'cash' ? '0' : `(${periodColumn(i)}16-${periodColumn(i)}18)`;
    return `=${opening}+Income!${periodColumn(i)}15-${periodColumn(i)}20-${repurchaseExcess}`;
  }));
  push('AOCI closing', PERIODS.map(() => `=${input(e.openingAoci)}`));
  push('Total equity', PERIODS.map((_, i) => `=${periodColumn(i)}34+${periodColumn(i)}35+${periodColumn(i)}36`));
  push('Remaining program authorization', PERIODS.map((_, i) => i === 0 ? `=${input(e.repurchaseAuthorization)}-${periodColumn(i)}16` : `=${periodColumn(i - 1)}38-${periodColumn(i)}16`));
  rows.push(padRow(['P8C input check', `=Inputs!B${e.gate}`, '', 'Required source/policy inputs and formula-owned statement/share/equity/UFCF outputs are checked before valuation linkage.']));
  rows.push(padRow(['Existing-award gross claim', `=${input(e.existingAwardUnits)}*${input(e.existingClaimPrice)}`, 'USD millions', 'Stale proxy units × dated P9 claim price; deducted once from equity value and excluded from the current denominator.']));
  rows.push(padRow(['Price policy', `=${input(e.existingClaimPrice)}`, 'USD/share', 'Existing-claim Mar31 quote; future settlement/repurchase proxy remains separate.']));
  return rows;
}

function financingRunoffRows(model) {
  const sourceForecast = model.financing_forecast.forecast ?? model.financing_forecast;
  const operating = sourceForecast.operating_opening_pool;
  const finance = sourceForecast.finance_opening_pool;
  const debtTail = sourceForecast.debt_tail_alternative ?? {};
  const pipelineSensitivities = sourceForecast.pipeline_sensitivities?.scenarios ?? [];
  const rows = [
    ['P8B full opening-pool runoff proof', 'Opening lease payments are carried through their final assigned date; this sheet is a visible proof companion to formula-owned visible schedules.', ''],
    ['Date', ...finance.payment_dates, 'Units'],
  ];
  const append = (label, values) => rows.push([label, ...values, 'USD millions']);
  append('Operating payment', operating.payment);
  append('Operating closing liability (application preview)', operating.full_runoff.map((item) => item.closing));
  append('Finance payment', finance.payment);
  append('Finance closing liability (application preview)', finance.full_runoff.map((item) => item.closing));
  rows.push(['Final closing liability', operating.full_runoff_final_closing, finance.full_runoff_final_closing, 'USD millions; both must be 0 within tolerance']);
  rows.push(['Debt tail alternative', 'FY2031-FY2036 allocates 34,890 evenly without refinancing; base selected policy holds it through FY2036.', '', 'scenario']);
  append('Debt tail alt original-face redemption (no refi)', debtTail.redemption ?? []);
  append('Debt tail alt new-par proceeds (zero on tail)', debtTail.proceeds ?? []);
  append('Debt tail alt closing face', debtTail.closing_face ?? []);
  rows.push(['Opening finance-asset life alternatives', '10-year / 13-year selected / 16-year service-life proxy; base visible schedule uses the selected 13-year input.', '', 'scenario']);
  for (const scenario of sourceForecast.opening_finance_life_sensitivities ?? []) {
    rows.push([`${scenario.name} depreciation`, ...(scenario.depreciation ?? []), 'USD millions']);
    rows.push([`${scenario.name} closing PP&E`, ...(scenario.closing_ppe ?? []), 'USD millions']);
  }
  rows.push(['Pipeline sensitivities', 'Base actual-day weights plus 50%/90% finance-share, front/back timing and +/-100bp new-rate scenarios.', '', 'scenario']);
  for (const scenario of pipelineSensitivities) {
    rows.push([`${scenario.name} finance share`, scenario.finance_share, 'operating rate', scenario.operating_rate, 'finance rate', scenario.finance_rate, 'weights', ...(scenario.weights ?? [])]);
    rows.push([`${scenario.name} operating PV additions`, ...(scenario.operating_additions ?? []), 'USD millions']);
    rows.push([`${scenario.name} finance PV additions`, ...(scenario.finance_additions ?? []), 'USD millions']);
  }
  rows.push(['Pipeline cohort full-runoff summary', 'Each cohort is carried through its final contractual payment date in the offline proof; visible model periods stop at FY2036.', '', '', '', '', '', '', '']);
  rows.push(['Cohort / class', 'Class', 'Commencement', 'Initial PV', 'Final payment date', 'Final closing liability', 'Service life', 'Rate', 'Units']);
  for (const cohort of sourceForecast.pipeline?.cohorts ?? []) {
    for (const kind of ['operating', 'finance']) {
      const lease = cohort[kind];
      const finalFlow = lease?.flows?.[lease.flows.length - 1] ?? {};
      rows.push([
        `${cohort.period} ${kind}`,
        kind,
        cohort.commencement,
        lease?.initial_pv,
        finalFlow.date,
        finalFlow.closing,
        lease?.term_years,
        lease?.rate,
        'USD millions; service life years; decimal rate',
      ]);
    }
  }
  return rows;
}

function schedulesRows(model) {
  const financing = Boolean(model.financing_forecast);
  const f = FINANCING_DRIVER_ROWS;
  const rows = [
    padRow(['Shared real asset schedules; formulas are application-owned']),
    padRow([financing ? 'Opening nonlease depreciable PP&E excludes disclosed land and the separately modeled finance-lease asset; total PP&E remains unchanged.' : 'Opening depreciable PP&E excludes disclosed land. Finance-lease PP&E is already included; new lease additions remain zero pending P8B.']),
    periodHeader(), periodLabels(), periodFractions(),
    periodRow('Cumulative forecast years', PERIODS.map((period) => period.cumulativeYears), 'years'),
    periodRow('Discount factor', PERIODS.map((_, index) => `=1/(1+Inputs!$B$37)^${periodColumn(index)}6`), 'factor'),
    padRow([]),
    padRow(['Asset and cross-statement schedules', null, null, 'USD millions']),
  ];
  const push = (label, generator, units = 'USD millions') => rows.push(periodRow(label, PERIODS.map((_, index) => generator(index)), units));
  push('Revenue', (index) => `=Inputs!${periodColumn(index)}55`);
  push('Operating-cost proxy excluding PP&E depreciation', (index) => {
    const column = periodColumn(index);
    const base = model.operating_forecast
      ? (financing ? `=Operating!${column}21-Financing!${column}61+Financing!${column}64` : `=Operating!${column}21`)
      : (financing ? `=${column}10*Inputs!$B$59-Financing!${column}61+Financing!${column}64` : `=${column}10*Inputs!$B$59`);
    const equityAdjustment = model.equity_forecast ? `-${column}10*Inputs!$B$${P8C_DRIVER_ROWS.embeddedSbcRatio}+Equity!${column}6` : '';
    const p8dAdjustment = model.other_balances_forecast ? `-OtherBalances!${column}${P8D_OUTPUT_ROWS.embeddedAmortizationRemoved}+OtherBalances!${column}${P8D_OUTPUT_ROWS.intangibleAmortization}` : '';
    return `${base}${equityAdjustment}${p8dAdjustment}`;
  });
  push('Cash PP&E additions / payments', (index) => `=Inputs!${periodColumn(index)}58`);
  push('Noncash PP&E additions in AP subset', (index) => `=${periodColumn(index)}12*Inputs!$B$33`);
  push('Recognized PP&E additions', (index) => `=${periodColumn(index)}12+${periodColumn(index)}13+${periodColumn(index)}32`);
  push('Original opening-pool depreciation', (index) => `=AssetCohorts!${periodColumn(index)}11`);
  push('Forecast-cohort depreciation', (index) => `=${PERIODS.map((_, j) => `AssetCohorts!${periodColumn(index)}${cohortRow(j, 2)}`).join('+')}`);
  push('Total depreciation', (index) => financing ? `=${periodColumn(index)}15+${periodColumn(index)}16+Financing!${periodColumn(index)}66` : `=${periodColumn(index)}15+${periodColumn(index)}16`);
  push('Opening depreciable net PP&E', (index) => financing ? (index === 0 ? `=Inputs!$B$13-Inputs!$B$${f.openingFinancePpe}` : `=${periodColumn(index - 1)}19`) : (index === 0 ? '=Inputs!$B$13' : `=${periodColumn(index - 1)}19`));
  push('Closing depreciable net PP&E', (index) => `=AssetCohorts!${periodColumn(index)}12+${PERIODS.map((_, j) => `AssetCohorts!${periodColumn(index)}${cohortRow(j, 3)}`).join('+')}`);
  push('Opening land', (index) => index === 0 ? '=Inputs!$B$12' : `=${periodColumn(index - 1)}21`);
  push('Closing land', (index) => `=${periodColumn(index)}20`);
  push('Opening net PP&E', (index) => financing ? `=${periodColumn(index)}18+${periodColumn(index)}20+${index === 0 ? `Financing!${periodColumn(index)}44` : `Financing!${periodColumn(index - 1)}55`}` : `=${periodColumn(index)}18+${periodColumn(index)}20`);
  push('Closing net PP&E', (index) => financing ? `=${periodColumn(index)}19+${periodColumn(index)}21+Financing!${periodColumn(index)}55` : `=${periodColumn(index)}19+${periodColumn(index)}21`);
  push('Opening PP&E payable subset', (index) => index === 0 ? '=Inputs!$B$51' : `=${periodColumn(index - 1)}25`);
  push('Closing PP&E payable subset', (index) => `=${periodColumn(index)}24+${periodColumn(index)}13`);
  push('Increase in operating NWC', (index) => model.working_capital_forecast ? `=WorkingCapital!${periodColumn(index)}42` : '=0');
  push('Opening equity', (index) => index === 0 ? '=Inputs!$B$24' : `=${periodColumn(index - 1)}28`);
  push('Closing equity', (index) => model.equity_forecast ? `=${periodColumn(index)}27+Income!${periodColumn(index)}15+Equity!${periodColumn(index)}6+Equity!${periodColumn(index)}13-Equity!${periodColumn(index)}19-Equity!${periodColumn(index)}16-Equity!${periodColumn(index)}20` : `=${periodColumn(index)}27+Income!${periodColumn(index)}15`);
  push('Opening cash', (index) => index === 0 ? '=Inputs!$B$6' : `=${periodColumn(index - 1)}31`);
  push('Net change in cash', (index) => `=CashFlow!${periodColumn(index)}${model.tax_forecast ? 16 : 13}`);
  push('Closing cash', (index) => `=CashFlow!${periodColumn(index)}${model.tax_forecast ? 18 : 15}`);
  push('Lease additions modeled', () => '=Inputs!$B$34');
  push('Funding status', (index) => `=IF(OR(Inputs!${periodColumn(index)}$${P8D_DRIVER_ROWS.openingCash}<0,${periodColumn(index)}31<0),"UNFUNDED_CASH","OK")`, 'status');
  push('Tax status', (index) => model.tax_forecast ? `=Taxes!${periodColumn(index)}30` : `=IF(Income!${periodColumn(index)}14>0,"UNEXPLAINED_TAX_BENEFIT","OK")`, 'status');
  rows.push(padRow(['Schedule note', 'Cash PP&E payments, noncash payable additions, and lease additions remain separate. Economic UFCF includes recognized additions; cash FCF is shown separately.']));
  return rows;
}

function otherBalancesRows(model) {
  const d = otherBalancesForecastInputs(model);
  const r = P8D_OUTPUT_ROWS;
  const balanceDifferenceRow = model.financing_forecast ? 32 : model.tax_forecast ? 28 : 25;
  const cashFlowClosingRow = model.tax_forecast ? 18 : 15;
  const input = (row, column = 'B') => `Inputs!${column}$${row}`;
  const actualOpeningCash = (index) => index === 0
    ? input(P8D_DRIVER_ROWS.openingCash)
    : `CashFlow!${periodColumn(index - 1)}${cashFlowClosingRow}`;
  const actualClosingCash = (index) => `CashFlow!${periodColumn(index)}${cashFlowClosingRow}`;
  const rows = [
    padRow(['P8D investments, intangibles, goodwill and remaining balances']),
    padRow(['Source parents remain visible; selected value marks, income, explicit amortization, impairment and commitment funding are linked once.']),
    periodHeader(), periodLabels(), periodFractions(),
  ];
  const push = (label, values, units = 'USD millions') => rows.push(periodRow(label, values, units));
  push('Investment opening carrying value', PERIODS.map((_, i) => i === 0 ? `=${input(P8D_DRIVER_ROWS.openingEquityOtherInvestments)}` : `=${periodColumn(i - 1)}${r.investmentClosing}`));
  push('Investment additions / commitment funding', PERIODS.map((_, i) => i === 0 ? `=${input(P8D_DRIVER_ROWS.unfundedCommitment)}` : '=0'));
  push('Cash investment income', PERIODS.map((_, i) => {
    const eligibleOpeningCash = `MAX(0,${actualOpeningCash(i)})`;
    return `=(${eligibleOpeningCash}+${input(P8D_DRIVER_ROWS.openingShortTermInvestments)}+${input(P8D_DRIVER_ROWS.identifiedLongTermDebtInvestments)}+${input(P8D_DRIVER_ROWS.openingFinancingReceivables)})*${input(P8D_DRIVER_ROWS.cashIncomeYield)}*${input(P8D_DRIVER_ROWS.periodDays, periodColumn(i))}/365`;
  }));
  push('Noncash unrealized investment gain', PERIODS.map((_, i) => i === 0 ? `=${input(P8D_DRIVER_ROWS.unrealizedInvestmentGain)}` : '=0'));
  push('Investment closing carrying value', PERIODS.map((_, i) => `=${periodColumn(i)}${r.investmentOpening}+${periodColumn(i)}${r.investmentAdditions}+${periodColumn(i)}${r.noncashGain}`));
  push('Investment measurement value bridge', PERIODS.map(() => `=${input(P8D_DRIVER_ROWS.knownInvestmentValue)}+${input(P8D_DRIVER_ROWS.otherInvestmentPool)}*${input(P8D_DRIVER_ROWS.otherInvestmentMultiplier)}+${input(P8D_DRIVER_ROWS.openingFinancingReceivables)}+${input(P8D_DRIVER_ROWS.unfundedCommitment)}*(${input(P8D_DRIVER_ROWS.unfundedCommitmentValueFraction)}-1)/(1.043^(91/365))`));
  push('Embedded TTM intangible amortization removed', PERIODS.map((_, i) => `=Schedules!${periodColumn(i)}10*${input(P8D_DRIVER_ROWS.embeddedIntangibleRatio)}`));
  push('Finite-lived intangible opening carrying value', PERIODS.map((_, i) => i === 0 ? `=${input(P8D_DRIVER_ROWS.openingIntangibles)}` : `=${periodColumn(i - 1)}${r.intangibleClosing}`));
  push('Finite-lived intangible amortization', PERIODS.map((_, i) => {
    if (i === 0) return `=${input(P8D_DRIVER_ROWS.intangibleStubAmortization)}`;
    if (i <= 4) return `=${input(P8D_DRIVER_ROWS.intangibleStubAmortization + i)}`;
    return `=IF(${i - 5}<${input(P8D_DRIVER_ROWS.intangibleTailLifeYears)},${input(P8D_DRIVER_ROWS.intangibleTailPool)}/${input(P8D_DRIVER_ROWS.intangibleTailLifeYears)},0)`;
  }));
  push('Finite-lived intangible closing carrying value', PERIODS.map((_, i) => `=${periodColumn(i)}${r.intangibleOpening}-${periodColumn(i)}${r.intangibleAmortization}`));
  push('Goodwill opening carrying value', PERIODS.map((_, i) => i === 0 ? `=${input(P8D_DRIVER_ROWS.openingGoodwill)}` : `=${periodColumn(i - 1)}${r.goodwillClosing}`));
  push('Goodwill impairment', PERIODS.map((_, i) => i === 0 ? `=${input(P8D_DRIVER_ROWS.goodwillImpairment)}` : '=0'));
  push('Goodwill closing carrying value', PERIODS.map((_, i) => `=${periodColumn(i)}${r.goodwillOpening}-${periodColumn(i)}${r.goodwillImpairment}`));
  push('Incremental NET DTA value estimate', PERIODS.map((_, i) => `=${input(P8D_DRIVER_ROWS.incrementalNetDtaValue)}`));
  push('Unfunded commitment CFI funding', PERIODS.map((_, i) => `=-${periodColumn(i)}${r.investmentAdditions}`));
  push('Incremental legal loss / cash stress', PERIODS.map((_, i) => i === 0 ? `=${input(P8D_DRIVER_ROWS.legalStress)}` : '=0'));
  push('P8D coverage', PERIODS.map(() => `=Inputs!$B$${P8D_DRIVER_ROWS.coverage}`), 'status');
  push('Unidentified D&A and other residual', PERIODS.map(() => `=${input(P8D_DRIVER_ROWS.unidentifiedDnaOther)}`));
  push('Commitment rights value', PERIODS.map(() => `=${input(P8D_DRIVER_ROWS.unfundedCommitment)}*${input(P8D_DRIVER_ROWS.unfundedCommitmentValueFraction)}`));
  push('Commitment net measurement adjustment', PERIODS.map(() => `=${input(P8D_DRIVER_ROWS.unfundedCommitment)}*(${input(P8D_DRIVER_ROWS.unfundedCommitmentValueFraction)}-1)/(1.043^(91/365))`));
  push('Funding status', PERIODS.map((_, i) => `=IF(OR(${actualOpeningCash(i)}<0,${actualClosingCash(i)}<0),"UNFUNDED_CASH","OK")`), 'status');
  push('Actual balance-sheet residual difference', PERIODS.map((_, i) => `=BalanceSheet!${periodColumn(i)}${balanceDifferenceRow}`));
  rows.push(padRow(['P8D tail runoff', `=SUM(Inputs!B${P8D_DRIVER_ROWS.intangibleAmortization}:L${P8D_DRIVER_ROWS.intangibleAmortization})`, 'USD millions', 'Visible schedule plus selected tail; full tail runoff is retained in the proposal preview outside FY2036.']));
  rows.push(padRow(['P8D value bridge', `=Inputs!B${P8D_DRIVER_ROWS.investmentValue}`, 'USD millions', 'Nonoperating value is displayed once in the DCF equity bridge; it is excluded from operating UFCF.']));
  return rows;
}

function statementRows(title, subtitle, formulas) {
  return [
    padRow([title]), padRow([subtitle]), periodHeader(), periodLabels(), periodFractions(),
    ...formulas.map(([label, values, units]) => periodRow(label, values, units)),
  ];
}

export function incomeRows(model) {
  return statementRows('Income statement (linked)', 'Expenses display with negative signs; every asset depreciation row flows once through total D&A.', [
    ['Revenue', PERIODS.map((_, index) => `=Schedules!${periodColumn(index)}10`), 'USD millions'],
    ['Operating-cost proxy excluding PP&E depreciation', PERIODS.map((_, index) => `=-Schedules!${periodColumn(index)}11`), 'USD millions; other embedded noncash expenses pending P6–P8'],
    ['Opening-asset depreciation', PERIODS.map((_, index) => `=-Schedules!${periodColumn(index)}15`), 'USD millions'],
    ['New-addition depreciation', PERIODS.map((_, index) => `=-Schedules!${periodColumn(index)}16`), 'USD millions'],
    ['Total depreciation', PERIODS.map((_, index) => `=-Schedules!${periodColumn(index)}17`), 'USD millions'],
    ['EBIT', PERIODS.map((_, index) => `=${periodColumn(index)}6+${periodColumn(index)}7+${periodColumn(index)}10`), 'USD millions'],
    ['Interest expense', PERIODS.map((_, index) => model.financing_forecast ? `=-(Financing!${periodColumn(index)}18+Financing!${periodColumn(index)}63)` : model.tax_forecast ? `=-Inputs!$B$${TAX_DRIVER_ROWS.interestExpense}` : '=0'), 'USD millions; P8B debt/finance lease book interest and contra expense are below EBIT'],
    ['Pre-tax income', PERIODS.map((_, index) => `=${periodColumn(index)}11+${periodColumn(index)}12${model.other_balances_forecast ? `+OtherBalances!${periodColumn(index)}${P8D_OUTPUT_ROWS.cashIncome}+OtherBalances!${periodColumn(index)}${P8D_OUTPUT_ROWS.noncashGain}-OtherBalances!${periodColumn(index)}${P8D_OUTPUT_ROWS.goodwillImpairment}-OtherBalances!${periodColumn(index)}${P8D_OUTPUT_ROWS.legalStress}` : ''}`), 'USD millions'],
    ['Taxes', PERIODS.map((_, index) => model.tax_forecast ? `=-Taxes!${periodColumn(index)}11` : `=-IF(${periodColumn(index)}13>0,${periodColumn(index)}13*Inputs!$B$35,0)`), 'USD millions'],
    ['Net income', PERIODS.map((_, index) => `=${periodColumn(index)}13+${periodColumn(index)}14`), 'USD millions'],
  ]);
}

export function cashFlowRows(model) {
  if (model.tax_forecast) return statementRows('Indirect cash flow statement (linked)', model.financing_forecast ? 'Cash is rolled from CFO, debt/lease financing and PP&E payments; noncash contra expense and operating lease principal are included once.' : 'Cash is rolled from CFO, tax payments and PP&E payments; current/deferred/long-term tax movements are included once.', [
    ['Net income', PERIODS.map((_, index) => `=Income!${periodColumn(index)}15`), 'USD millions'],
    ['Noncash and operating-lease CFO adjustments', PERIODS.map((_, index) => `${model.financing_forecast ? `=Schedules!${periodColumn(index)}17+Financing!${periodColumn(index)}65+Financing!${periodColumn(index)}16-Financing!${periodColumn(index)}68` : `=Schedules!${periodColumn(index)}17`}${model.equity_forecast ? `+Equity!${periodColumn(index)}6` : ''}${model.other_balances_forecast ? `+OtherBalances!${periodColumn(index)}${P8D_OUTPUT_ROWS.intangibleAmortization}+OtherBalances!${periodColumn(index)}${P8D_OUTPUT_ROWS.goodwillImpairment}-OtherBalances!${periodColumn(index)}${P8D_OUTPUT_ROWS.noncashGain}` : ''}`), model.financing_forecast ? 'USD millions; PP&E depreciation + ROU amortization + noncash contra release - operating lease principal; P8D intangible/impairment/gain adjustments and book SBC are shown once' : 'USD millions; PP&E depreciation plus P8D intangible/impairment/gain adjustments and book SBC shown once'],
    ['Deferred tax add-back', PERIODS.map((_, index) => `=Taxes!${periodColumn(index)}23`), 'USD millions'],
    ['Current tax payable movement / CFO effect', PERIODS.map((_, index) => `=Taxes!${periodColumn(index)}24`), 'USD millions'],
    ['Long-term tax settlement / CFO effect', PERIODS.map((_, index) => `=Taxes!${periodColumn(index)}25`), 'USD millions'],
    ['Increase in operating NWC', PERIODS.map((_, index) => `=-Schedules!${periodColumn(index)}26`), 'USD millions'],
    ['Cash from operations', PERIODS.map((_, index) => `=SUM(${periodColumn(index)}6:${periodColumn(index)}11)`), 'USD millions'],
    ['Cash PP&E payments', PERIODS.map((_, index) => `=-Schedules!${periodColumn(index)}12`), 'USD millions'],
    ['Cash flow from investing', PERIODS.map((_, index) => `=${periodColumn(index)}13${model.other_balances_forecast ? `+OtherBalances!${periodColumn(index)}${P8D_OUTPUT_ROWS.commitmentFunding}` : ''}`), 'USD millions'],
    ['Cash flow from financing', PERIODS.map((_, index) => `${model.financing_forecast ? `=Financing!${periodColumn(index)}21-Financing!${periodColumn(index)}67` : '=0'}${model.equity_forecast ? `+Equity!${periodColumn(index)}13-Equity!${periodColumn(index)}16-Equity!${periodColumn(index)}19-Equity!${periodColumn(index)}23` : ''}`), model.financing_forecast ? 'USD millions; debt/lease financing plus explicit P8C issuance, withholding, program repurchases and dividends' : 'USD millions; explicit P8C issuance, withholding, repurchases and dividends when present'],
    ['Net change in cash', PERIODS.map((_, index) => `=${periodColumn(index)}12+${periodColumn(index)}14+${periodColumn(index)}15`), 'USD millions'],
    ['Opening cash', PERIODS.map((_, index) => `=Schedules!${periodColumn(index)}29`), 'USD millions'],
    ['Closing cash', PERIODS.map((_, index) => `=${periodColumn(index)}17+${periodColumn(index)}16`), 'USD millions'],
  ]);
  return statementRows('Indirect cash flow statement (linked)', 'Cash is rolled from CFO and cash PP&E payments; noncash PP&E additions stay in AP and are not cash inflows.', [
    ['Net income', PERIODS.map((_, index) => `=Income!${periodColumn(index)}15`), 'USD millions'],
    ['Depreciation add-back', PERIODS.map((_, index) => `=Schedules!${periodColumn(index)}17${model.other_balances_forecast ? `+OtherBalances!${periodColumn(index)}${P8D_OUTPUT_ROWS.intangibleAmortization}+OtherBalances!${periodColumn(index)}${P8D_OUTPUT_ROWS.goodwillImpairment}-OtherBalances!${periodColumn(index)}${P8D_OUTPUT_ROWS.noncashGain}` : ''}`), 'USD millions'],
    ['Increase in operating NWC', PERIODS.map((_, index) => `=-Schedules!${periodColumn(index)}26`), 'USD millions'],
    ['Cash from operations', PERIODS.map((_, index) => `=${periodColumn(index)}6+${periodColumn(index)}7+${periodColumn(index)}8`), 'USD millions'],
    ['Cash PP&E payments', PERIODS.map((_, index) => `=-Schedules!${periodColumn(index)}12`), 'USD millions'],
    ['Cash flow from investing', PERIODS.map((_, index) => `=${periodColumn(index)}10${model.other_balances_forecast ? `+OtherBalances!${periodColumn(index)}${P8D_OUTPUT_ROWS.commitmentFunding}` : ''}`), 'USD millions'],
    ['Cash flow from financing', PERIODS.map(() => '=0'), 'USD millions; temporary no-new-debt simplification'],
    ['Net change in cash', PERIODS.map((_, index) => `=${periodColumn(index)}9+${periodColumn(index)}11+${periodColumn(index)}12`), 'USD millions'],
    ['Opening cash', PERIODS.map((_, index) => `=Schedules!${periodColumn(index)}29`), 'USD millions'],
    ['Closing cash', PERIODS.map((_, index) => `=${periodColumn(index)}14+${periodColumn(index)}13`), 'USD millions'],
  ]);
}

function balanceSheetRows(model) {
  const p7 = Boolean(model.working_capital_forecast);
  const tax = Boolean(model.tax_forecast);
  const otherLiabilities = tax
    ? PERIODS.map((_, index) => `=Inputs!$B$23-Inputs!$B$20-Inputs!$B$21-Inputs!$B$22-Inputs!$B$${TAX_DRIVER_ROWS.openingCurrentTaxPayable}-Inputs!$B$${TAX_DRIVER_ROWS.openingLongTermTaxLiability}-Inputs!$B$${TAX_DRIVER_ROWS.openingDeferredTaxLiability}+${p7 ? `WorkingCapital!${periodColumn(index)}28-Inputs!$B$${P7_DRIVER_ROWS.accruedCompensation}+WorkingCapital!${periodColumn(index)}33-Inputs!$B$${P7_DRIVER_ROWS.contractCurrent}-Inputs!$B$${P7_DRIVER_ROWS.contractNoncurrent}+WorkingCapital!${periodColumn(index)}38-Inputs!$B$${P7_DRIVER_ROWS.otherOclResidual}` : '0'}${model.equity_forecast ? `+Inputs!${periodColumn(index)}${P8C_DRIVER_ROWS.dividendPayableClosing}-Inputs!$B$${P8C_DRIVER_ROWS.dividendPayableOpening}` : ''}`)
    : PERIODS.map((_, index) => p7 ? `=Inputs!$B$23-Inputs!$B$20-Inputs!$B$21-Inputs!$B$22-Inputs!$B$${P7_DRIVER_ROWS.accruedCompensation}-Inputs!$B$${P7_DRIVER_ROWS.contractCurrent}-Inputs!$B$${P7_DRIVER_ROWS.contractNoncurrent}-Inputs!$B$${P7_DRIVER_ROWS.otherOclResidual}+WorkingCapital!${periodColumn(index)}28+WorkingCapital!${periodColumn(index)}33+WorkingCapital!${periodColumn(index)}38${model.equity_forecast ? `+Inputs!${periodColumn(index)}${P8C_DRIVER_ROWS.dividendPayableClosing}-Inputs!$B$${P8C_DRIVER_ROWS.dividendPayableOpening}` : ''}` : `=Inputs!$B$23-Inputs!$B$20-Inputs!$B$21-Inputs!$B$22${model.equity_forecast ? `+Inputs!${periodColumn(index)}${P8C_DRIVER_ROWS.dividendPayableClosing}-Inputs!$B$${P8C_DRIVER_ROWS.dividendPayableOpening}` : ''}`);
  if (tax && model.financing_forecast) {
    const f = FINANCING_DRIVER_ROWS;
    const financingResidual = PERIODS.map((_, index) => `=Inputs!$B$23-Inputs!$B$20-Inputs!$B$21-Inputs!$B$22-Inputs!$B$${TAX_DRIVER_ROWS.openingCurrentTaxPayable}-Inputs!$B$${TAX_DRIVER_ROWS.openingLongTermTaxLiability}-Inputs!$B$${TAX_DRIVER_ROWS.openingDeferredTaxLiability}-Inputs!$B$${f.openingOperatingCurrentLiability}-Inputs!$B$${f.openingOperatingNoncurrentLiability}-Inputs!$B$${f.openingFinanceCurrentLiability}-Inputs!$B$${f.openingFinanceNoncurrentLiability}+${p7 ? `WorkingCapital!${periodColumn(index)}28-Inputs!$B$${P7_DRIVER_ROWS.accruedCompensation}+WorkingCapital!${periodColumn(index)}33-Inputs!$B$${P7_DRIVER_ROWS.contractCurrent}-Inputs!$B$${P7_DRIVER_ROWS.contractNoncurrent}+WorkingCapital!${periodColumn(index)}38-Inputs!$B$${P7_DRIVER_ROWS.otherOclResidual}` : '0'}${model.equity_forecast ? `+Inputs!${periodColumn(index)}${P8C_DRIVER_ROWS.dividendPayableClosing}-Inputs!$B$${P8C_DRIVER_ROWS.dividendPayableOpening}` : ''}`);
    return statementRows('Balance sheet (linked provisional)', 'Opening debt and lease liabilities are carved from their containing source parents exactly once; current/noncurrent classifications are presentation estimates with no P&L or cash effect.', [
      ['Cash and cash equivalents', PERIODS.map((_, index) => `=CashFlow!${periodColumn(index)}18`), 'USD millions'],
      ['Short-term investments', PERIODS.map(() => '=Inputs!$B$7'), 'USD millions'],
      ['Accounts receivable', PERIODS.map((_, index) => p7 ? `=WorkingCapital!${periodColumn(index)}10` : '=Inputs!$B$8'), 'USD millions'],
      ['Inventory', PERIODS.map((_, index) => p7 ? `=WorkingCapital!${periodColumn(index)}13` : '=Inputs!$B$9'), 'USD millions'],
      ['Other current assets', PERIODS.map((_, index) => p7 ? `=WorkingCapital!${periodColumn(index)}22+WorkingCapital!${periodColumn(index)}25` : '=Inputs!$B$10'), 'USD millions'],
      ['Net PP&E', PERIODS.map((_, index) => `=Schedules!${periodColumn(index)}23`), 'USD millions'],
      ['Operating lease ROU asset', PERIODS.map((_, index) => `=Financing!${periodColumn(index)}54`), 'USD millions'],
      ['Long-term investments', PERIODS.map((_, index) => model.other_balances_forecast ? `=OtherBalances!${periodColumn(index)}${P8D_OUTPUT_ROWS.investmentClosing}` : '=Inputs!$B$15'), 'USD millions'],
      ['Goodwill', PERIODS.map((_, index) => model.other_balances_forecast ? `=OtherBalances!${periodColumn(index)}${P8D_OUTPUT_ROWS.goodwillClosing}` : '=Inputs!$B$16'), 'USD millions'],
      ['Intangible assets', PERIODS.map((_, index) => model.other_balances_forecast ? `=OtherBalances!${periodColumn(index)}${P8D_OUTPUT_ROWS.intangibleClosing}` : '=Inputs!$B$17'), 'USD millions'],
      ['Other noncurrent assets', PERIODS.map(() => model.other_balances_forecast ? `=Inputs!$B$${P8D_DRIVER_ROWS.openingOtherLongTermAssets}` : '=Inputs!$B$18'), 'USD millions'],
      ['Total assets', PERIODS.map((_, index) => `=SUM(${periodColumn(index)}6:${periodColumn(index)}16)`), 'USD millions'],
      ['Accounts payable / PP&E payable subset roll', PERIODS.map((_, index) => p7 ? `=WorkingCapital!${periodColumn(index)}16+Schedules!${periodColumn(index)}25` : `=Inputs!$B$20+SUM(Schedules!$B$13:Schedules!${periodColumn(index)}13)`), 'USD millions'],
      ['Short-term debt', PERIODS.map((_, index) => `=Financing!${periodColumn(index)}24`), 'USD millions; current carrying debt'],
      ['Current income tax payable', PERIODS.map((_, index) => `=Taxes!${periodColumn(index)}16`), 'USD millions'],
      ['Current operating lease liability', PERIODS.map((_, index) => `=Financing!${periodColumn(index)}69`), 'USD millions; presentation estimate'],
      ['Current finance lease liability', PERIODS.map((_, index) => `=Financing!${periodColumn(index)}71`), 'USD millions; presentation estimate'],
      ['Other liabilities residual', financingResidual, 'USD millions; containing aggregate after P7/P8A/P8B carve-outs'],
      ['Long-term debt', PERIODS.map((_, index) => `=Financing!${periodColumn(index)}25`), 'USD millions; noncurrent carrying debt'],
      ['Noncurrent operating lease liability', PERIODS.map((_, index) => `=Financing!${periodColumn(index)}70`), 'USD millions; presentation estimate'],
      ['Noncurrent finance lease liability', PERIODS.map((_, index) => `=Financing!${periodColumn(index)}72`), 'USD millions; presentation estimate'],
      ['Long-term income tax liability', PERIODS.map((_, index) => `=Taxes!${periodColumn(index)}20`), 'USD millions'],
      ['Deferred income tax liability', PERIODS.map((_, index) => `=Taxes!${periodColumn(index)}22`), 'USD millions'],
      ['Total liabilities', PERIODS.map((_, index) => `=SUM(${periodColumn(index)}18:${periodColumn(index)}28)`), 'USD millions'],
      ['Total equity', PERIODS.map((_, index) => `=Schedules!${periodColumn(index)}28`), 'USD millions'],
      ['Liabilities + equity', PERIODS.map((_, index) => `=${periodColumn(index)}29+${periodColumn(index)}30`), 'USD millions'],
      ['Balance difference', PERIODS.map((_, index) => `=${periodColumn(index)}17-${periodColumn(index)}31`), 'USD millions'],
    ]);
  }
  if (tax) return statementRows('Balance sheet (linked provisional)', 'Working-capital balances and separately modeled tax liabilities roll through the balance sheet; source aggregates are carved once.', [
    ['Cash and cash equivalents', PERIODS.map((_, index) => `=CashFlow!${periodColumn(index)}18`), 'USD millions'],
    ['Short-term investments', PERIODS.map(() => '=Inputs!$B$7'), 'USD millions; held flat'],
    ['Accounts receivable', PERIODS.map((_, index) => p7 ? `=WorkingCapital!${periodColumn(index)}10` : '=Inputs!$B$8'), 'USD millions; P7 current AR DSO proxy'],
    ['Inventory', PERIODS.map((_, index) => p7 ? `=WorkingCapital!${periodColumn(index)}13` : '=Inputs!$B$9'), 'USD millions; P7 cost-of-revenue DIO proxy'],
    ['Other current assets', PERIODS.map((_, index) => p7 ? `=WorkingCapital!${periodColumn(index)}22+WorkingCapital!${periodColumn(index)}25` : '=Inputs!$B$10'), 'USD millions; P7 server receivables plus OCA residual'],
    ['Net PP&E', PERIODS.map((_, index) => `=Schedules!${periodColumn(index)}23`), 'USD millions'],
    ['Operating lease ROU asset', PERIODS.map(() => '=Inputs!$B$14'), 'USD millions; held flat pending P8B'],
    ['Long-term investments', PERIODS.map((_, index) => model.other_balances_forecast ? `=OtherBalances!${periodColumn(index)}${P8D_OUTPUT_ROWS.investmentClosing}` : '=Inputs!$B$15'), 'USD millions; P8D investment roll-forward when present'],
    ['Goodwill', PERIODS.map((_, index) => model.other_balances_forecast ? `=OtherBalances!${periodColumn(index)}${P8D_OUTPUT_ROWS.goodwillClosing}` : '=Inputs!$B$16'), 'USD millions; P8D impairment roll-forward when present'],
    ['Intangible assets', PERIODS.map((_, index) => model.other_balances_forecast ? `=OtherBalances!${periodColumn(index)}${P8D_OUTPUT_ROWS.intangibleClosing}` : '=Inputs!$B$17'), 'USD millions; P8D explicit amortization schedule when present'],
    ['Other noncurrent assets', PERIODS.map(() => model.other_balances_forecast ? `=Inputs!$B$${P8D_DRIVER_ROWS.openingOtherLongTermAssets}` : '=Inputs!$B$18'), 'USD millions; held flat'],
    ['Total assets', PERIODS.map((_, index) => `=SUM(${periodColumn(index)}6:${periodColumn(index)}16)`), 'USD millions'],
    ['Accounts payable / PP&E payable subset roll', PERIODS.map((_, index) => p7 ? `=WorkingCapital!${periodColumn(index)}16+Schedules!${periodColumn(index)}25` : `=Inputs!$B$20+SUM(Schedules!$B$13:Schedules!${periodColumn(index)}13)`), 'USD millions; P7 operating AP plus separate PP&E payable subset'],
    ['Short-term debt', PERIODS.map(() => '=Inputs!$B$21'), 'USD millions; held flat'],
    ['Current income tax payable', PERIODS.map((_, index) => `=Taxes!${periodColumn(index)}16`), 'USD millions; P8A separate reported account'],
    ['Other liabilities residual', otherLiabilities, 'USD millions; containing aggregate carved for P7 and P8A accounts'],
    ['Long-term debt', PERIODS.map(() => '=Inputs!$B$22'), 'USD millions; held flat'],
    ['Long-term income tax liability', PERIODS.map((_, index) => `=Taxes!${periodColumn(index)}20`), 'USD millions; P8A separate reported account'],
    ['Deferred income tax liability', PERIODS.map((_, index) => `=Taxes!${periodColumn(index)}22`), 'USD millions; P8A separate reported account'],
    ['Total liabilities', PERIODS.map((_, index) => `=SUM(${periodColumn(index)}18:${periodColumn(index)}24)`), 'USD millions'],
    ['Total equity', PERIODS.map((_, index) => `=Schedules!${periodColumn(index)}28`), 'USD millions'],
    ['Liabilities + equity', PERIODS.map((_, index) => `=${periodColumn(index)}25+${periodColumn(index)}26`), 'USD millions'],
    ['Balance difference', PERIODS.map((_, index) => `=${periodColumn(index)}17-${periodColumn(index)}27`), 'USD millions'],
  ]);
  return statementRows('Balance sheet (linked provisional)', p7 ? 'Working-capital balances roll through the balance sheet; excluded taxes, leases, investments and debt remain separate.' : 'Other observed balances are held flat while cash, PP&E, payable subset and equity roll through the asset schedule.', [
    ['Cash and cash equivalents', PERIODS.map((_, index) => `=CashFlow!${periodColumn(index)}15`), 'USD millions'],
    ['Short-term investments', PERIODS.map(() => '=Inputs!$B$7'), 'USD millions; held flat'],
    ['Accounts receivable', PERIODS.map((_, index) => p7 ? `=WorkingCapital!${periodColumn(index)}10` : '=Inputs!$B$8'), 'USD millions; P7 current AR DSO proxy'],
    ['Inventory', PERIODS.map((_, index) => p7 ? `=WorkingCapital!${periodColumn(index)}13` : '=Inputs!$B$9'), 'USD millions; P7 cost-of-revenue DIO proxy'],
    ['Other current assets', PERIODS.map((_, index) => p7 ? `=WorkingCapital!${periodColumn(index)}22+WorkingCapital!${periodColumn(index)}25` : '=Inputs!$B$10'), 'USD millions; P7 server receivables plus OCA residual'],
    ['Net PP&E', PERIODS.map((_, index) => `=Schedules!${periodColumn(index)}23`), 'USD millions'],
    ['Operating lease ROU asset', PERIODS.map(() => '=Inputs!$B$14'), 'USD millions; held flat pending P8B'],
    ['Long-term investments', PERIODS.map((_, index) => model.other_balances_forecast ? `=OtherBalances!${periodColumn(index)}${P8D_OUTPUT_ROWS.investmentClosing}` : '=Inputs!$B$15'), 'USD millions; P8D investment roll-forward when present'],
    ['Goodwill', PERIODS.map((_, index) => model.other_balances_forecast ? `=OtherBalances!${periodColumn(index)}${P8D_OUTPUT_ROWS.goodwillClosing}` : '=Inputs!$B$16'), 'USD millions; P8D impairment roll-forward when present'],
    ['Intangible assets', PERIODS.map((_, index) => model.other_balances_forecast ? `=OtherBalances!${periodColumn(index)}${P8D_OUTPUT_ROWS.intangibleClosing}` : '=Inputs!$B$17'), 'USD millions; P8D explicit amortization schedule when present'],
    ['Other noncurrent assets', PERIODS.map(() => model.other_balances_forecast ? `=Inputs!$B$${P8D_DRIVER_ROWS.openingOtherLongTermAssets}` : '=Inputs!$B$18'), 'USD millions; held flat'],
    ['Total assets', PERIODS.map((_, index) => `=SUM(${periodColumn(index)}6:${periodColumn(index)}16)`), 'USD millions'],
    ['Accounts payable / PP&E payable subset roll', PERIODS.map((_, index) => p7 ? `=WorkingCapital!${periodColumn(index)}16+Schedules!${periodColumn(index)}25` : `=Inputs!$B$20+SUM(Schedules!$B$13:Schedules!${periodColumn(index)}13)`), 'USD millions; P7 operating AP plus separate PP&E payable subset'],
    ['Short-term debt', PERIODS.map(() => '=Inputs!$B$21'), 'USD millions; held flat'],
    ['Other liabilities held flat', otherLiabilities, 'USD millions; P7 accrued compensation, contract liability and OCL residual roll; excluded tax/lease/debt balances held flat'],
    ['Long-term debt', PERIODS.map(() => '=Inputs!$B$22'), 'USD millions; held flat'],
    ['Total liabilities', PERIODS.map((_, index) => `=SUM(${periodColumn(index)}18:${periodColumn(index)}21)`), 'USD millions'],
    ['Total equity', PERIODS.map((_, index) => `=Schedules!${periodColumn(index)}28`), 'USD millions'],
    ['Liabilities + equity', PERIODS.map((_, index) => `=${periodColumn(index)}22+${periodColumn(index)}23`), 'USD millions'],
    ['Balance difference', PERIODS.map((_, index) => `=${periodColumn(index)}17-${periodColumn(index)}24`), 'USD millions'],
  ]);
}

function dcfRows(model) {
  const financing = Boolean(model.financing_forecast);
  const p9 = Boolean(model.valuation_policy);
  const explicit = PERIODS.map((_, index) => `=${periodColumn(index)}7*${periodColumn(index)}10`);
  const gated = (formula) => model.tax_forecast ? `=IF(AND(Checks!$B$22="PASS",Inputs!$B$${TAX_DRIVER_ROWS.gate}="PASS"${model.equity_forecast ? `,Inputs!$B$${P8C_DRIVER_ROWS.gate}="PASS"` : ''}${model.other_balances_forecast ? `,Inputs!$B$${P8D_DRIVER_ROWS.gate}="PASS"` : ''}),${formula},"BLOCKED")` : `=IF(AND(Checks!$B$22="PASS"${model.equity_forecast ? `,Inputs!$B$${P8C_DRIVER_ROWS.gate}="PASS"` : ''}${model.other_balances_forecast ? `,Inputs!$B$${P8D_DRIVER_ROWS.gate}="PASS"` : ''}),${formula},"BLOCKED")`;
  return [
    padRow(['Provisional DCF bridge']),
    padRow(['Economic UFCF includes recognized cash plus noncash PP&E additions. Cash FCF is shown separately to expose financing treatment.']),
    periodHeader(), periodLabels(), periodFractions(),
    periodRow(p9 ? 'ACT/365 elapsed years' : 'Cumulative forecast years', PERIODS.map((period) => p9 ? `=Valuation!${periodColumn(PERIODS.indexOf(period))}46` : `=Schedules!${periodColumn(PERIODS.indexOf(period))}6`), 'years'),
    periodRow('Economic UFCF', PERIODS.map((_, index) => model.equity_forecast ? `=Equity!${periodColumn(index)}32` : financing ? `=Income!${periodColumn(index)}11-Taxes!${periodColumn(index)}29+Schedules!${periodColumn(index)}17+Financing!${periodColumn(index)}64-Financing!${periodColumn(index)}56-Schedules!${periodColumn(index)}14-Financing!${periodColumn(index)}49-Schedules!${periodColumn(index)}26${model.other_balances_forecast ? `-OtherBalances!${periodColumn(index)}${P8D_OUTPUT_ROWS.legalStress}` : ''}` : model.tax_forecast ? `=Income!${periodColumn(index)}11-Taxes!${periodColumn(index)}29+Schedules!${periodColumn(index)}17-Schedules!${periodColumn(index)}14-Schedules!${periodColumn(index)}26${model.other_balances_forecast ? `-OtherBalances!${periodColumn(index)}${P8D_OUTPUT_ROWS.legalStress}` : ''}` : `=Income!${periodColumn(index)}11-MAX(0,Income!${periodColumn(index)}11)*Inputs!$B$35+Schedules!${periodColumn(index)}17-Schedules!${periodColumn(index)}14-Schedules!${periodColumn(index)}26${model.other_balances_forecast ? `-OtherBalances!${periodColumn(index)}${P8D_OUTPUT_ROWS.legalStress}` : ''}`), 'USD millions'),
    periodRow('Economic reinvestment (recognized PP&E additions)', PERIODS.map((_, index) => financing ? `=Schedules!${periodColumn(index)}14+Financing!${periodColumn(index)}49` : `=Schedules!${periodColumn(index)}14`), 'USD millions'),
    periodRow('Cash FCF (CFO - cash PP&E payments)', PERIODS.map((_, index) => model.tax_forecast ? `=CashFlow!${periodColumn(index)}12+CashFlow!${periodColumn(index)}13` : `=CashFlow!${periodColumn(index)}9+CashFlow!${periodColumn(index)}10`), 'USD millions'),
    periodRow('Discount factor', PERIODS.map((_, index) => p9 ? `=Valuation!${periodColumn(index)}48` : `=Schedules!${periodColumn(index)}7`), 'factor'),
    periodRow('PV of economic UFCF', PERIODS.map((_, index) => p9 ? `=Valuation!${periodColumn(index)}49` : explicit[index]), 'USD millions'),
    padRow([]),
    padRow(['DCF summary', null, null, 'USD millions unless stated']),
    padRow(['Terminal economic UFCF', p9 ? '=Valuation!B76' : gated('L7'), 'USD millions', p9 ? 'Normalized FY2037 terminal UFCF' : 'FY2036 terminal run-rate; full terminal economics pending P9']),
    padRow(['Terminal value', p9 ? '=Valuation!B81' : gated('B14*(1+Inputs!$B$38)/(Inputs!$B$37-Inputs!$B$38)'), 'USD millions', p9 ? 'Finite steady-cohort terminal normalization' : 'g < WACC gate']),
    padRow(['PV of terminal value', p9 ? '=Valuation!B82' : gated('B15*L10'), 'USD millions', p9 ? 'ACT/365 at FY2036 period end' : 'Period-end discounting']),
    padRow(['PV of explicit forecast', p9 ? '=Valuation!B50' : gated('SUM(B11:L11)'), 'USD millions', 'Economic UFCF']),
    padRow(['Enterprise value', p9 ? '=Valuation!B120' : gated('B16+B17'), 'USD millions', p9 ? 'Canonical complete guarded P9 enterprise value' : 'Diagnostic asset-slice valuation; not a complete MSFT valuation']),
    padRow(['Bridge cash', '=Inputs!$B$6', 'USD millions', 'Cash and equivalents only']),
    padRow(['Bridge debt', model.other_balances_forecast ? (financing ? `=-Financing!$B$26` : '=-(Inputs!$B$21+Inputs!$B$22)') : (financing ? `=Financing!$B$26` : '=Inputs!$B$21+Inputs!$B$22'), 'USD millions', model.other_balances_forecast ? 'P8D debt deduction uses the P8B fair-value claim once; carrying/face comparators remain on Financing' : financing ? 'P8B disclosed debt fair value claim once; carrying/face comparators remain on Financing' : 'Short + long debt']),
    padRow([model.other_balances_forecast ? 'P8D non-operating investment value excluding bridge cash' : 'Short-term investments excluded', model.other_balances_forecast ? '=OtherBalances!B11-Inputs!$B$6' : '=Inputs!$B$7', 'USD millions', model.other_balances_forecast ? 'P8D measurement value bridge less cash; cash remains in the dedicated bridge row' : 'P8D bridge policy pending']),
    padRow([p9 ? 'Complete common equity value' : 'Partial cash/debt bridge before existing-award claim', p9 ? '=Valuation!B121' : model.other_balances_forecast ? gated('B18+B19+B20+B21') : gated('B18+B19-B20'), 'USD millions', p9 ? 'Canonical complete guarded P9 equity bridge' : model.other_balances_forecast ? 'Displayed operating EV + cash + debt + P8D non-operating value; P9 remaining valuation conventions remain pending' : 'Cash and debt only; investments, PP&E payables and lease liabilities remain outside this partial diagnostic']),
    padRow(['Terminal condition', p9 ? '=Valuation!B40' : '=IFERROR(IF(AND(ISNUMBER(Inputs!B37),ISNUMBER(Inputs!B38),Inputs!B38<Inputs!B37),"PASS","FAIL"),"FAIL")', 'status', p9 ? 'Canonical P9 input and WACC > g gate' : 'Required DCF gate']),
    padRow(['Valuation status', p9 ? '=Valuation!B3' : model.tax_forecast ? '=IF(AND(Checks!B22="PASS",Inputs!B114="PASS"' + (financing ? `,Inputs!B${FINANCING_DRIVER_ROWS.gate}="PASS"` : '') + (model.equity_forecast ? `,Inputs!B${P8C_DRIVER_ROWS.gate}="PASS"` : '') + (model.other_balances_forecast ? `,Inputs!B${P8D_DRIVER_ROWS.gate}="PASS"` : '') + '),Review!B3,"BLOCKED")' : `=IF(AND(Checks!B22="PASS"${model.equity_forecast ? `,Inputs!$B$${P8C_DRIVER_ROWS.gate}="PASS"` : ''}${model.other_balances_forecast ? `,Inputs!$B$${P8D_DRIVER_ROWS.gate}="PASS"` : ''}),Review!B3,"BLOCKED")`, 'status', 'All-period mechanical gate; offline, actual review and workbook edits remain distinct']),
    padRow([p9 ? 'Supplier-financed PP&E payable claim included once' : 'PP&E payable obligation excluded from partial bridge', p9 ? '=Valuation!B21' : '=Inputs!B51', 'USD millions', p9 ? 'Face-value claim deducted once in Valuation bridge; separately excluded from operating AP/NWC' : 'Explicit unresolved P8 financing/valuation policy; not free investment']),
    padRow(['Existing-award gross claim', model.equity_forecast ? '=Equity!B40' : null, 'USD millions', 'Authoritative Equity!B40 claim; stale proxy units × dated measurement-date price, deducted once below']),
    padRow([p9 ? 'Complete common equity value' : 'Partial equity value after existing-award claim', model.equity_forecast ? (p9 ? '=Valuation!B121' : gated('B22-B26')) : null, 'USD millions', p9 ? 'Canonical complete guarded P9 equity bridge; award claim already deducted once' : 'Partial cash/debt bridge less the existing-award claim; P8D investments, P8B lease claims and P9 terminal conventions remain pending']),
    padRow(['Measurement-date point-share denominator', model.equity_forecast ? (p9 ? '=Valuation!B18' : '=Inputs!$B$227') : null, 'shares millions', '7429m measurement-date point shares; distinct from forecast basic weighted-average and diluted EPS denominators']),
    padRow([p9 ? 'Complete value per measurement-date point share' : 'Partial value per measurement-date point share', model.equity_forecast ? (p9 ? '=Valuation!B122' : gated('B27/B28')) : null, 'USD/share', p9 ? 'Canonical complete guarded P9 per-share value' : 'Partial equity value after one claim deduction divided by current point shares; not a complete investment valuation']),
    padRow(['Existing-award claim bridge check', model.equity_forecast ? (p9 ? '=Valuation!B97' : '=IFERROR(IF(AND(ISNUMBER(B26),ABS(B26-Equity!B40)<=1E-8,ISNUMBER(B27),ABS(B27-(B22-B26))<=1E-8),"PASS","FAIL"),"FAIL")') : null, 'status', p9 ? 'P9 complete once-only claim arithmetic check' : 'Fails when the authoritative claim is missing, duplicated or disconnected from the displayed partial equity bridge']),
    padRow(['Point-share denominator check', model.equity_forecast ? '=IFERROR(IF(AND(ISNUMBER(B28),B28>0,ABS(B28-Inputs!$B$227)<=1E-8,ABS(B28-7429)<=1E-8),"PASS","FAIL"),"FAIL")' : null, 'status', 'Fails when outstanding awards are added to the measurement-date denominator or the denominator is otherwise changed']),
    padRow(['Partial per-share arithmetic check', model.equity_forecast ? '=IFERROR(IF(AND(ISNUMBER(B27),ISNUMBER(B28),ISNUMBER(B29),B28>0,ABS(B29*B28-B27)<=1E-8),"PASS","FAIL"),"FAIL")' : null, 'status', 'Per-share result must tie the displayed post-claim bridge to the fixed point-share denominator']),
  ];
}

function checksRows(model) {
  const financing = Boolean(model.financing_forecast);
  const balanceDifferenceRow = financing ? 32 : model.tax_forecast ? 28 : 25;
  const rows = [padRow(['Financial integrity checks']), padRow(['Checks are diagnostics; no check supplies a balancing plug.']), periodHeader(), periodLabels()];
  const push = (label, generator, units = 'status') => rows.push(periodRow(label, PERIODS.map((_, index) => generator(periodColumn(index))), units));
  push('Balance difference', (c) => `=BalanceSheet!${c}${balanceDifferenceRow}`, 'USD millions');
  push('Balance check', (c) => `=IF(ABS(${c}5)<=${TOLERANCE},"PASS","FAIL")`);
  push('Cash agreement difference', (c) => `=CashFlow!${c}${model.tax_forecast ? 18 : 15}-BalanceSheet!${c}6`, 'USD millions');
  push('Cash agreement check', (c) => `=IF(ABS(${c}7)<=${TOLERANCE},"PASS","FAIL")`);
  push('PP&E movement difference', (c) => financing ? `=Schedules!${c}23-(Schedules!${c}22+Schedules!${c}14+Financing!${c}49-Schedules!${c}17)` : `=Schedules!${c}23-(Schedules!${c}22+Schedules!${c}14-Schedules!${c}17)`, 'USD millions');
  push('PP&E movement check', (c) => `=IF(ABS(${c}9)<=${TOLERANCE},"PASS","FAIL")`);
  push('Noncash payable movement difference', (c) => `=Schedules!${c}25-(Schedules!${c}24+Schedules!${c}13)`, 'USD millions');
  push('Cash/noncash separation check', (c) => `=IF(ABS(${c}11)<=${TOLERANCE},"PASS","FAIL")`);
  push('Depreciation-base check', (c) => `=IFERROR(IF(AND(AssetCohorts!${c}11>=0,AssetCohorts!${c}11<=AssetCohorts!${c}10+${TOLERANCE},${PERIODS.flatMap((_, j) => [`AssetCohorts!${c}${cohortRow(j, 2)}>=0`, `AssetCohorts!${c}${cohortRow(j, 2)}<=AssetCohorts!${c}${cohortRow(j, 1)}+${TOLERANCE}`]).join(',')}),"PASS","FAIL"),"FAIL")`);
  push('Cross-statement cost difference', (c) => `=Income!${c}11-(Income!${c}6+Income!${c}7+Income!${c}10)`, 'USD millions');
  push('Cross-statement cost check', (c) => `=IF(ABS(${c}14)<=${TOLERANCE},"PASS","FAIL")`);
  push('Equity movement difference', (c) => model.equity_forecast ? `=Schedules!${c}28-(Schedules!${c}27+Income!${c}15+Equity!${c}6+Equity!${c}13-Equity!${c}19-Equity!${c}16-Equity!${c}20)` : `=Schedules!${c}28-(Schedules!${c}27+Income!${c}15)`, 'USD millions');
  push('Equity movement check', (c) => `=IF(ABS(${c}16)<=${TOLERANCE},"PASS","FAIL")`);
  push('Lease double-count amount', (c) => `=Schedules!${c}32`, 'USD millions');
  push('Lease double-count check', (c) => `=IF(ABS(${c}18)<=${TOLERANCE},"PASS","FAIL")`);
  push('Overall mechanical check', (c) => model.tax_forecast
     ? `=IFERROR(IF(AND(Inputs!$B$54="PASS",Inputs!$B$${TAX_DRIVER_ROWS.gate}="PASS"${financing ? `,Inputs!$B$${FINANCING_DRIVER_ROWS.gate}="PASS",Financing!${c}74="PASS",${model.equity_forecast ? `Inputs!$B$${P8C_DRIVER_ROWS.gate}="PASS",ABS(DCF!${c}7-Equity!${c}32)<=${TOLERANCE}` : `ABS(DCF!${c}7-(CashFlow!${c}12+Financing!${c}18+Financing!${c}63+Taxes!${c}27-Taxes!${c}29-Financing!${c}16-Schedules!${c}14-Financing!${c}49))<=${TOLERANCE}`}` : model.equity_forecast ? `,Inputs!$B$${P8C_DRIVER_ROWS.gate}="PASS",ABS(DCF!${c}7-Equity!${c}32)<=${TOLERANCE}` : ''}${model.other_balances_forecast ? `,Inputs!$B$${P8D_DRIVER_ROWS.gate}="PASS",OtherBalances!${c}${P8D_OUTPUT_ROWS.coverage}="PASS"` : ''},${c}6="PASS",${c}8="PASS",${c}10="PASS",${c}12="PASS",${c}13="PASS",${c}15="PASS",${c}17="PASS",${c}19="PASS"),"PASS","FAIL"),"FAIL")`
     : `=IFERROR(IF(AND(Inputs!$B$54="PASS"${model.equity_forecast ? `,Inputs!$B$${P8C_DRIVER_ROWS.gate}="PASS",ABS(DCF!${c}7-Equity!${c}32)<=${TOLERANCE}` : ''}${model.other_balances_forecast ? `,Inputs!$B$${P8D_DRIVER_ROWS.gate}="PASS",OtherBalances!${c}${P8D_OUTPUT_ROWS.coverage}="PASS"` : ''},${c}6="PASS",${c}8="PASS",${c}10="PASS",${c}12="PASS",${c}13="PASS",${c}15="PASS",${c}17="PASS",${c}19="PASS"),"PASS","FAIL"),"FAIL")`);
  rows.push(padRow(['Check interpretation', 'PP&E, depreciation, cash/noncash, cross-statement and lease controls are visible for every forecast period.']));
  rows.push(padRow(['All-period mechanical gate', `=IFERROR(IF(AND(${PERIODS.map((_, i) => `${periodColumn(i)}20="PASS"`).join(',')}),"PASS","FAIL"),"FAIL")`]));
  const savedInputCount = requiredInputs(model).length;
  rows.push(padRow(['Saved-input comparison', `=IFERROR(IF(SUM(SavedInputs!C4:C${savedInputCount + 3})=0,"UNCHANGED","EDITED"),"EDITED")`]));
  if (financing) {
    rows.push(padRow(['P8B financing integrity checks', 'Debt face/contra, lease liability/asset movements, current classification, full runoff and funding visibility are checked separately; UNFUNDED is a visible state, not a plug.']));
    push('Debt face movement difference', (c) => `=Financing!${c}13-(Financing!${c}12+Financing!${c}20-Financing!${c}19)`, 'USD millions');
    push('Debt carrying identity difference', (c) => `=Financing!${c}13+Financing!${c}17-(Financing!${c}24+Financing!${c}25)`, 'USD millions');
    push('Operating lease liability movement difference', (c) => `=Financing!${c}52-(Financing!${c}29+Financing!${c}62-Financing!${c}56+Financing!${c}48)`, 'USD millions');
    push('Operating ROU movement difference', (c) => `=Financing!${c}54-(Financing!${c}34+Financing!${c}48-Financing!${c}65)`, 'USD millions');
    push('Finance lease liability movement difference', (c) => `=Financing!${c}53-(Financing!${c}39+Financing!${c}63-Financing!${c}57+Financing!${c}49)`, 'USD millions');
    rows.push(periodRow('Finance PP&E movement difference', PERIODS.map((_, index) => `=Financing!${periodColumn(index)}55-(${index === 0 ? `Financing!${periodColumn(index)}44` : `Financing!${periodColumn(index - 1)}55`}+Financing!${periodColumn(index)}49-Financing!${periodColumn(index)}66)`), 'USD millions'));
    push('Debt cash separation difference', (c) => `=Financing!${c}21-(Financing!${c}20-Financing!${c}19)`, 'USD millions');
    push('Lease cash separation difference', (c) => `=Financing!${c}56-Financing!${c}59-Financing!${c}62`, 'USD millions');
    push('Funding state check', (c) => `=IF(OR(Financing!${c}73="OK",Financing!${c}73="UNFUNDED"),"PASS","FAIL")`);
    push('Opening runoff check', () => '=IF(AND(ABS(0)<=1E-5,Inputs!$B$146="PASS"),"PASS","FAIL")');
    push('UFCF CFO/EBIT bridge difference', (c) => model.equity_forecast
      ? `=DCF!${c}7-Equity!${c}33`
      : model.tax_forecast
      ? `=DCF!${c}7-(CashFlow!${c}12+Financing!${c}18+Financing!${c}63+Taxes!${c}27-Taxes!${c}29-Financing!${c}16-Schedules!${c}14-Financing!${c}49)`
      : `=DCF!${c}7-(CashFlow!${c}9+Financing!${c}18+Financing!${c}63-Financing!${c}16-Schedules!${c}14-Financing!${c}49)`, 'USD millions');
    push('UFCF CFO/EBIT bridge check', (c) => `=IF(ABS(${c}35)<=${TOLERANCE},"PASS","FAIL")`);
    push('P8B overall check', (c) => `=IFERROR(IF(AND(ABS(${c}25)<=${TOLERANCE},ABS(${c}26)<=${TOLERANCE},ABS(${c}27)<=${TOLERANCE},ABS(${c}28)<=${TOLERANCE},ABS(${c}29)<=${TOLERANCE},ABS(${c}30)<=${TOLERANCE},ABS(${c}31)<=${TOLERANCE},ABS(${c}32)<=${TOLERANCE},${c}33="PASS",${c}34="PASS",${c}36="PASS"),"PASS","FAIL"),"FAIL")`);
  }
  if (model.equity_forecast) {
    const e = P8C_DRIVER_ROWS;
    const equityBase = financing ? 39 : 25;
    rows.push(padRow(['P8C equity integrity checks', 'SBC replacement, explicit delivery/withholding, capital returns, dividend payable, share timing and CFO/EBIT UFCF bridge are checked separately.']));
    push('SBC replacement difference', (c) => `=Equity!${c}6-Equity!${c}7-Equity!${c}8`, 'USD millions');
    push('SBC replacement check', (c) => `=IF(ABS(${c}${equityBase})<=${TOLERANCE},"PASS","FAIL")`);
    push('Share roll-forward difference', (c) => `=Equity!${c}25-(Equity!${c}24+Equity!${c}12+Equity!${c}14-Equity!${c}17)`, 'shares millions');
    push('Share roll-forward check', (c) => `=IF(ABS(${c}${equityBase + 2})<=${TOLERANCE},"PASS","FAIL")`);
    push('Equity component difference', (c) => `=Equity!${c}37-(Equity!${c}34+Equity!${c}35+Equity!${c}36)`, 'USD millions');
    push('Equity component check', (c) => `=IF(ABS(${c}${equityBase + 4})<=${TOLERANCE},"PASS","FAIL")`);
    push('UFCF CFO/EBIT bridge difference', (c) => `=Equity!${c}32-Equity!${c}33`, 'USD millions');
    push('UFCF CFO/EBIT bridge check', (c) => `=IF(ABS(${c}${equityBase + 6})<=${TOLERANCE},"PASS","FAIL")`);
    push('P8C equity check', (c) => `=IFERROR(IF(AND(Inputs!$B$${e.gate}="PASS",ABS(Equity!${c}6-Equity!${c}7-Equity!${c}8)<=${TOLERANCE},ABS(Equity!${c}25-Equity!${c}24-Equity!${c}12-Equity!${c}14+Equity!${c}17)<=${TOLERANCE},ABS(Equity!${c}37-Equity!${c}34-Equity!${c}35-Equity!${c}36)<=${TOLERANCE},ABS(Equity!${c}32-Equity!${c}33)<=${TOLERANCE}),"PASS","FAIL"),"FAIL")`);
  }
  if (model.other_balances_forecast) {
    const d = P8D_OUTPUT_ROWS;
    rows.push(padRow(['P8D remaining-balance integrity checks', 'Investment, intangible, goodwill and commitment movements are linked once; value marks remain outside operating UFCF and source parents remain visible.']));
    const investmentDifferenceRow = rows.length + 1;
    push('Investment movement difference', (c) => `=OtherBalances!${c}${d.investmentClosing}-(OtherBalances!${c}${d.investmentOpening}+OtherBalances!${c}${d.investmentAdditions}+OtherBalances!${c}${d.noncashGain})`, 'USD millions');
    push('Investment movement check', (c) => `=IF(ABS(${c}${investmentDifferenceRow})<=${TOLERANCE},"PASS","FAIL")`);
    const intangibleDifferenceRow = rows.length + 1;
    push('Intangible movement difference', (c) => `=OtherBalances!${c}${d.intangibleClosing}-(OtherBalances!${c}${d.intangibleOpening}-OtherBalances!${c}${d.intangibleAmortization})`, 'USD millions');
    push('Intangible movement check', (c) => `=IF(ABS(${c}${intangibleDifferenceRow})<=${TOLERANCE},"PASS","FAIL")`);
    const goodwillDifferenceRow = rows.length + 1;
    push('Goodwill movement difference', (c) => `=OtherBalances!${c}${d.goodwillClosing}-(OtherBalances!${c}${d.goodwillOpening}-OtherBalances!${c}${d.goodwillImpairment})`, 'USD millions');
    push('Goodwill movement check', (c) => `=IF(ABS(${c}${goodwillDifferenceRow})<=${TOLERANCE},"PASS","FAIL")`);
    const commitmentDifferenceRow = rows.length + 1;
    push('Commitment CFI difference', (c) => `=CashFlow!${c}${model.tax_forecast ? 14 : 10}-(-Schedules!${c}12+OtherBalances!${c}${d.commitmentFunding})`, 'USD millions');
    push('P8D remaining-balance check', (c) => `=IFERROR(IF(AND(Inputs!$B$${P8D_DRIVER_ROWS.gate}="PASS",OtherBalances!${c}${d.coverage}="PASS",ABS(${c}${commitmentDifferenceRow})<=${TOLERANCE},ABS(${c}${investmentDifferenceRow})<=${TOLERANCE},ABS(${c}${intangibleDifferenceRow})<=${TOLERANCE},ABS(${c}${goodwillDifferenceRow})<=${TOLERANCE}),"PASS","FAIL"),"FAIL")`);
  }
  return rows;
}

function legacyEvidenceRows(model) {
  const rows = [padRow(['Packet-qualified evidence']), padRow([model.working_capital_packet ? 'P5/P6 source packet plus persisted P7 source-table identities; source/model prose stays literal.' : 'Every item below is copied from the persisted P5 evidence packet; locators and source hashes remain visible.']), padRow(['Evidence ID', 'Packet ID', 'Period', 'Kind', 'Excerpt', 'Source file', 'Locator', 'Source SHA256'])];
  for (const item of model.packet.evidence) rows.push(padRow([item.evidence_id, item.packet_id ?? item.evidence_id, item.period, item.kind, item.excerpt, item.source_file, item.source_locator, item.source_sha256]));
  if (model.working_capital_packet?.source_table) rows.push(padRow(['P7-source-table-R1', 'P7-source-table-R1', 'FY2024-Q3FY2026', 'working_capital_classification', 'Frozen P7 balance/CFS classification table; calculated residuals and unresolved differences remain labeled.', model.working_capital_packet.source_table, model.working_capital_packet.source_table_sha256, model.working_capital_packet.source_table_sha256]));
  if (model.tax_packet?.source_table) rows.push(padRow(['P8A-source-table-R1', 'P8A-source-table-R1', 'FY2023-Q3FY2026', 'tax_classification', 'Frozen P8A tax source table; raw signs, unavailable Q3 detail and unresolved DTA/UTP items remain labeled.', model.tax_packet.source_table, model.tax_packet.source_table_sha256, model.tax_packet.source_table_sha256]));
  if (model.financing_packet?.source_table) rows.push(padRow(['P8B-source-table-R1', 'P8B-source-table-R1', 'FY2025-Q3FY2026', 'financing_classification', 'Frozen P8B debt/lease source table; source signs, containment and unresolved maturity/pipeline timing remain labeled.', model.financing_packet.source_table, model.financing_packet.source_table_sha256, model.financing_packet.source_table_sha256]));
  if (model.equity_packet?.source_table) rows.push(padRow(['P8C-source-table-R1', 'P8C-source-table-R1', 'FY2024-Q3FY2026', 'equity_classification', 'Frozen 75-row P8C SBC/equity/share table; stale award proxies, dated quote and historical timing differences remain labeled.', model.equity_packet.source_table, model.equity_packet.source_table_sha256, model.equity_packet.source_table_sha256]));
  return rows;
}

function evidenceRows(model) {
  const metadata = validatedReviewMetadata(model);
  if (!metadata) return legacyEvidenceRows(model);
  const rows = [
    padRow(['Current P10 whole-model review sources']),
    padRow(['Active source treatment: segment cost of revenue and aggregate operating expense are disclosed; consolidated functional ratios are selected model choices. Historical package narratives below are preserved and superseded where the current review differs.']),
    padRow(['Source ID', 'Period', 'Cutoff', 'Kind', 'Excerpt', 'Source file', 'Locator', 'Source SHA256']),
  ];
  for (const source of metadata.sources) rows.push(padRow([source.source_id, source.period, source.cutoff, source.kind, source.excerpt, source.source_file, source.locator, source.sha256]));
  rows.push(padRow([]), padRow(['Historical package evidence — retained provenance; current P10 records above control the review presentation.']));
  rows.push(...legacyEvidenceRows(model));
  return rows;
}

const BINDING_HASH_FIELDS = Object.freeze(['candidate_hash', 'review_hash', 'context_hash', 'source_packet_hash']);

function hasHash(value) {
  return typeof value === 'string' && value.trim().length > 0;
}

function bindingFieldsPresent(binding) {
  return binding && BINDING_HASH_FIELDS.every((field) => hasHash(binding[field]));
}

function bindingMatches(left, right) {
  return bindingFieldsPresent(left) && bindingFieldsPresent(right) && BINDING_HASH_FIELDS.every((field) => left[field] === right[field]);
}

function canonicalValue(value) {
  if (Array.isArray(value)) return value.map((item) => canonicalValue(item));
  if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map((key) => [key, canonicalValue(value[key])]));
  return value;
}

function sameValue(left, right) {
  return JSON.stringify(canonicalValue(left)) === JSON.stringify(canonicalValue(right));
}

function p5BindingRecords(decision) {
  const selected = String(decision.selected_candidate ?? '').includes('revision') ? 'revision' : 'original';
  const stage = selected === 'revision' ? 'review-revision' : 'review-original';
  const metadata = [...(decision.call_metadata ?? [])].reverse().find((item) => item.stage === stage) ?? {};
  return {
    candidate_hash: decision.candidate_hashes?.[selected],
    review_hash: decision.review_hashes?.[selected],
    context_hash: metadata.stage_context_hash,
    source_packet_hash: metadata.source_packet_hash,
  };
}

function p5DecisionIsBound(decision, model = null) {
  const records = p5BindingRecords(decision);
  if (!decision.binding) return bindingFieldsPresent(records);
  if (!bindingMatches(decision.binding, records)) return false;
  if (model && decision.binding.candidate_snapshot !== undefined && !sameValue(decision.binding.candidate_snapshot, model.candidate)) return false;
  if (model && decision.binding.source_case_snapshot_sha256 !== undefined && decision.binding.source_case_snapshot_sha256 !== model.packet?.frozen_case_snapshot_sha256) return false;
  return true;
}

function p6DecisionIsBound(model, decision) {
  const binding = decision.binding;
  if (!bindingMatches(decision, binding)) return false;
  if (binding.candidate_snapshot !== undefined && !sameValue(binding.candidate_snapshot, model.operating_decision?.proposal)) return false;
  if (binding.review_snapshot !== undefined && !sameValue(binding.review_snapshot, model.operating_decision?.review)) return false;
  if (binding.source_case_snapshot_sha256 !== undefined && binding.source_case_snapshot_sha256 !== model.packet?.frozen_case_snapshot_sha256) return false;
  return true;
}

function p7DecisionIsBound(model, decision) {
  const binding = decision?.binding;
  if (!bindingMatches(decision, binding)) return false;
  const current = model.working_capital_decision ?? {};
  if (binding.candidate_snapshot !== undefined && !sameValue(binding.candidate_snapshot, current.proposal)) return false;
  if (binding.review_snapshot !== undefined && !sameValue(binding.review_snapshot, current.review)) return false;
  if (binding.source_case_snapshot_sha256 !== undefined && binding.source_case_snapshot_sha256 !== model.packet?.frozen_case_snapshot_sha256) return false;
  const driver = binding.accrued_compensation_driver;
  if (driver !== undefined) {
    const inputs = model.working_capital_forecast?.inputs ?? {};
    if (!sameValue(driver.source_baseline, inputs.accrued_compensation_baseline)
      || !sameValue(driver.multiplier, inputs.accrued_compensation_multiplier)
      || !sameValue(driver.effective_ratio, inputs.accrued_compensation_effective_ratio)) return false;
  }
  return true;
}

function p8aDecisionIsBound(model, decision) {
  const binding = decision?.binding;
  if (!bindingMatches(decision, binding)) return false;
  const current = model.tax_decision ?? model.tax_forecast?.tax_decision ?? {};
  if (binding.candidate_snapshot !== undefined && !sameValue(binding.candidate_snapshot, current.proposal)) return false;
  if (binding.review_snapshot !== undefined && !sameValue(binding.review_snapshot, current.review)) return false;
  if (binding.source_case_snapshot_sha256 !== undefined && binding.source_case_snapshot_sha256 !== model.packet?.frozen_case_snapshot_sha256) return false;
  return true;
}

const P8B_PIPELINE_FINANCE_SHARE_REFERENCE = 'source_mix_disclosed_recent_additions';

function resolvedP8bPipelineFinanceShare(model, value) {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (value !== P8B_PIPELINE_FINANCE_SHARE_REFERENCE) return null;
  const pipeline = model.financing_packet?.facts?.pipeline ?? model.financing_forecast?.packet?.facts?.pipeline;
  const financeAdditions = pipeline?.finance_additions_source;
  const operatingAdditions = pipeline?.operating_additions_source;
  const sourceShare = pipeline?.finance_share_source;
  if (![financeAdditions, operatingAdditions, sourceShare].every((item) => typeof item === 'number' && Number.isFinite(item))) return null;
  const denominator = financeAdditions + operatingAdditions;
  if (denominator <= 0) return null;
  const resolved = financeAdditions / denominator;
  if (resolved < 0 || resolved > 1 || Math.abs(sourceShare - resolved) > TOLERANCE) return null;
  return resolved;
}

function p8bPolicyForBinding(model, policy) {
  if (!policy || typeof policy !== 'object' || Array.isArray(policy)) return null;
  const resolvedShare = resolvedP8bPipelineFinanceShare(model, policy.pipeline_finance_share);
  if (resolvedShare === null) return null;
  return { ...policy, pipeline_finance_share: resolvedShare };
}

function p8bDecisionIsBound(model, decision) {
  const binding = decision?.binding;
  if (!bindingMatches(decision, binding)) return false;
  const current = model.financing_decision ?? model.financing_forecast?.decision ?? {};
  if (binding.candidate_snapshot !== undefined) {
    const candidatePolicy = p8bPolicyForBinding(model, binding.candidate_snapshot);
    const currentPolicy = p8bPolicyForBinding(model, current.proposal ?? model.financing_forecast?.forecast?.policy);
    if (!candidatePolicy || !currentPolicy || !sameValue(candidatePolicy, currentPolicy)) return false;
  }
  if (binding.review_snapshot !== undefined && !sameValue(binding.review_snapshot, current.review)) return false;
  if (binding.source_case_snapshot_sha256 !== undefined && binding.source_case_snapshot_sha256 !== model.packet?.frozen_case_snapshot_sha256) return false;
  return true;
}

function p8cDecisionIsBound(model, decision) {
  const binding = decision?.binding;
  if (!bindingMatches(decision, binding)) return false;
  const current = model.equity_decision ?? model.equity_forecast?.decision ?? {};
  if (binding.candidate_snapshot !== undefined && !sameValue(binding.candidate_snapshot, model.equity_forecast?.forecast?.policy ?? current.proposal)) return false;
  if (binding.candidate_snapshot?.existing_claim_price !== undefined && binding.candidate_snapshot.existing_claim_price !== model.equity_packet?.facts?.market_quote?.value) return false;
  if (binding.review_snapshot !== undefined && !sameValue(binding.review_snapshot, current.review)) return false;
  if (binding.source_case_snapshot_sha256 !== undefined && binding.source_case_snapshot_sha256 !== model.packet?.frozen_case_snapshot_sha256) return false;
  return true;
}

function p8dDecisionIsBound(model, decision) {
  if (!model.other_balances_forecast) return true;
  if (!decision || typeof decision !== 'object') return false;
  const current = model.other_balances_forecast;
  const policy = current.policy ?? current.inputs ?? current.candidate ?? current.forecast?.policy;
  if (decision.binding) {
    if (!bindingFieldsPresent(decision.binding)) return false;
    if (decision.binding.candidate_snapshot !== undefined && !sameValue(decision.binding.candidate_snapshot, policy)) return false;
    if (decision.binding.source_packet_hash !== undefined && decision.binding.source_packet_hash !== (model.other_balances_packet?.source_table_sha256 ?? model.other_balances_packet?.source_packet_hash)) return false;
  }
  if (decision.candidate_snapshot !== undefined && !sameValue(decision.candidate_snapshot, policy)) return false;
  return decision.status !== 'STALE';
}

export function combinedDecision(model) {
  const p5 = model.p5_decision ?? model.decision?.p5 ?? model.decision ?? {};
  const p6Candidate = model.p6_decision ?? model.operating_decision ?? null;
  const p6 = p6Candidate?.status
    ? p6Candidate
    : { ...(model.operating_forecast?.decision ?? {}), ...(p6Candidate ?? {}) };
  const p5Status = p5.status ?? model.decision?.p5_status ?? 'MISSING';
  const p6Status = p6?.status ?? 'MISSING';
  const p7 = model.p7_decision ?? model.working_capital_decision ?? null;
  const p7Status = p7?.status ?? 'MISSING';
  const p8a = model.p8a_decision ?? model.tax_decision ?? null;
  const p8aStatus = p8a?.status ?? 'MISSING';
  const p8b = model.p8b_decision ?? model.financing_decision ?? null;
  const p8bStatus = p8b?.status ?? 'MISSING';
  const p8c = model.p8c_decision ?? model.equity_decision ?? null;
  const p8cStatus = p8c?.status ?? 'MISSING';
  const p8d = model.p8d_decision ?? model.other_balances_decision ?? (model.other_balances_forecast?.decision ?? null);
  const p8dStatus = p8d?.status ?? 'MISSING';
  const p5Bound = p5DecisionIsBound(p5, model);
  const p6Bound = p6DecisionIsBound(model, p6);
  const p5Reviewed = p5Status === 'SYSTEM_REVIEWED_PROVISIONAL' && p5.review_verdict === 'accept' && p5Bound;
  const p6Reviewed = p6Status === 'SYSTEM_REVIEWED_PROVISIONAL' && p6.review?.verdict === 'accept' && p6.stale !== true && p6.review_status !== 'STALE' && p6Bound;
  const p7Bound = model.working_capital_forecast ? p7DecisionIsBound(model, p7) : true;
  const p7Reviewed = p7Status === 'SYSTEM_REVIEWED_PROVISIONAL' && p7.review?.verdict === 'accept' && p7.stale !== true && p7Bound;
  const p8aBound = model.tax_forecast ? p8aDecisionIsBound(model, p8a) : true;
  const p8aReviewed = p8aStatus === 'SYSTEM_REVIEWED_PROVISIONAL' && p8a.review?.verdict === 'accept' && p8a.stale !== true && p8aBound;
  const p8bBound = model.financing_forecast ? p8bDecisionIsBound(model, p8b) : true;
  const p8bReviewed = p8bStatus === 'SYSTEM_REVIEWED_PROVISIONAL' && p8b.review?.verdict === 'accept' && p8b.stale !== true && p8bBound;
  const p8cBound = model.equity_forecast ? p8cDecisionIsBound(model, p8c) : true;
  const p8cReviewed = p8cStatus === 'SYSTEM_REVIEWED_PROVISIONAL' && p8c.review?.verdict === 'accept' && p8c.stale !== true && p8cBound;
  const p8dBound = model.other_balances_forecast ? p8dDecisionIsBound(model, p8d) : true;
  const p8dReviewed = p8dStatus === 'SYSTEM_REVIEWED_PROVISIONAL' && (p8d.review?.verdict ?? p8d.review_verdict) === 'accept' && p8d.stale !== true && p8dBound;
  let status = 'UNREVIEWED_PROVISIONAL';
  if (p8dStatus === 'OFFLINE_FIXTURE' || p8cStatus === 'OFFLINE_FIXTURE' || p8bStatus === 'OFFLINE_FIXTURE' || p7Status === 'OFFLINE_FIXTURE' || (!model.working_capital_forecast && p6Status === 'OFFLINE_FIXTURE')) status = 'OFFLINE_FIXTURE';
  else if (model.working_capital_forecast && p7Status !== 'SYSTEM_REVIEWED_PROVISIONAL') status = p7Status === 'MISSING' ? 'UNREVIEWED_PROVISIONAL' : p7Status;
  else if (p6Status !== 'SYSTEM_REVIEWED_PROVISIONAL') status = p6Status === 'MISSING' ? 'UNREVIEWED_PROVISIONAL' : p6Status;
  else if (model.tax_forecast && p8aStatus !== 'SYSTEM_REVIEWED_PROVISIONAL') status = p8aStatus === 'MISSING' ? 'UNREVIEWED_PROVISIONAL' : p8aStatus;
  else if (model.financing_forecast && p8bStatus !== 'SYSTEM_REVIEWED_PROVISIONAL') status = p8bStatus === 'MISSING' ? 'UNREVIEWED_PROVISIONAL' : p8bStatus;
  else if (model.equity_forecast && p8cStatus !== 'SYSTEM_REVIEWED_PROVISIONAL') status = p8cStatus === 'MISSING' ? 'UNREVIEWED_PROVISIONAL' : p8cStatus;
  else if (model.other_balances_forecast && p8dStatus !== 'SYSTEM_REVIEWED_PROVISIONAL') status = p8dStatus === 'MISSING' ? 'UNREVIEWED_PROVISIONAL' : p8dStatus;
  else if (p5Reviewed && p6Reviewed && (!model.working_capital_forecast || p7Reviewed) && (!model.tax_forecast || p8aReviewed) && (!model.financing_forecast || p8bReviewed) && (!model.equity_forecast || p8cReviewed) && (!model.other_balances_forecast || p8dReviewed)) status = 'SYSTEM_REVIEWED_PROVISIONAL';
  return {
    ...model.decision,
    decision_id: model.decision?.decision_id ?? 'P6-MSFT-COMBINED-DECISION-R3',
    status,
    human_approval: false,
    p5_status: p5Status,
    p6_status: p6Status,
    p5_binding_valid: p5Bound,
    p6_binding_valid: p6Bound,
    p7_status: p7Status,
    p7_binding_valid: p7Bound,
    p8a_status: p8aStatus,
    p8a_binding_valid: p8aBound,
    p8b_status: p8bStatus,
    p8b_binding_valid: p8bBound,
    p8c_status: p8cStatus,
    p8c_binding_valid: p8cBound,
    p8d_status: p8dStatus,
    p8d_binding_valid: p8dBound,
    p5_decision_id: p5.decision_id ?? 'P5 decision not attached',
    p6_decision_id: p6?.decision_id ?? 'P6 decision not attached',
    p7_decision_id: p7?.decision_id ?? 'P7 decision not attached',
    p8a_decision_id: p8a?.decision_id ?? 'P8A decision not attached',
    p8b_decision_id: p8b?.decision_id ?? 'P8B decision not attached',
    p8c_decision_id: p8c?.decision_id ?? 'P8C decision not attached',
    p8d_decision_id: p8d?.decision_id ?? 'P8D decision not attached',
    coverage: model.other_balances_forecast ? 'P5 asset + P6 operating + P7 working capital + P8A tax + P8B debt/leases + P8C equity + P8D investments/intangibles/remaining balances; P9-P12 remain incomplete' : model.equity_forecast ? 'P5 asset + P6 operating + P7 working capital + P8A tax + P8B debt/leases + P8C equity; P8D-P12 remain incomplete' : model.financing_forecast ? 'P5 asset + P6 operating + P7 working capital + P8A tax + P8B debt/leases; P8C-P12 remain incomplete' : model.working_capital_forecast ? 'P5 asset + P6 operating + P7 working capital; P8-P12 financial coverage remains incomplete' : 'P5 asset slice + P6 operating slice; P7-P12 financial coverage remains incomplete',
  };
}

function legacyDecisionRows(model) {
  const d = model.p5_decision ?? model.decision;
  const combined = combinedDecision(model);
  const p6Candidate = model.p6_decision ?? model.operating_decision ?? {};
  const p6 = p6Candidate.status ? p6Candidate : { ...(model.operating_forecast?.decision ?? {}), ...p6Candidate };
  const c = model.candidate;
  const candidateHashes = d.candidate_hashes ?? {};
  const reviewHashes = d.review_hashes ?? {};
  const revised = d.selected_candidate === 'candidate-revision-v2.json';
  const reviewEvidence = revised
    ? reviewHashes.revision && candidateHashes.revision
    : reviewHashes.original && (candidateHashes.followup || candidateHashes.initial);
  const p5Bound = p5DecisionIsBound(d, model);
  const p6Bound = p6DecisionIsBound(model, p6);
  const status = d.status === 'SYSTEM_REVIEWED_PROVISIONAL'
    ? d.review_verdict === 'accept' && reviewEvidence && p5Bound ? d.status : 'UNREVIEWED_PROVISIONAL'
    : ['OFFLINE_FIXTURE', 'REVISION_REQUIRED', 'REJECTED_BY_REVIEW', 'HELD_BY_REVIEW'].includes(d.status)
      ? d.status : 'UNREVIEWED_PROVISIONAL';
  const p6StoredStatus = p6.status ?? 'MISSING';
  const p6Status = p6StoredStatus === 'SYSTEM_REVIEWED_PROVISIONAL' && !p6Bound ? 'UNREVIEWED_PROVISIONAL' : p6StoredStatus;
  const p7 = model.p7_decision ?? model.working_capital_decision ?? {};
  const p7Bound = model.working_capital_forecast ? p7DecisionIsBound(model, p7) : true;
  const p7StoredStatus = p7.status ?? 'MISSING';
  const p7Status = p7StoredStatus === 'SYSTEM_REVIEWED_PROVISIONAL' && !p7Bound ? 'UNREVIEWED_PROVISIONAL' : p7StoredStatus;
  const rows = [
    padRow(['P5 stored decision and provenance']),
    padRow(['Decision ID', d.decision_id]),
    padRow(['Decision version', d.decision_version]),
    padRow(['Status', status]),
    padRow(['Human approval', String(d.human_approval)]),
    padRow(['Method', `${c.method_id} / ${c.method_version}`]),
    padRow(['Method catalog version', d.method_catalog_version]),
    padRow(['Targeted revision parameter', d.changed_parameter]),
    padRow(['Targeted revision direction', d.change_direction]),
    padRow(['Review rationale', d.review_rationale]),
    padRow(['Initial candidate hash', candidateHashes.initial ?? 'offline fixture']),
    padRow(['Follow-up candidate hash', candidateHashes.followup ?? 'offline fixture']),
    padRow(['Revision candidate hash', candidateHashes.revision ?? 'offline fixture']),
    padRow(['Original review hash', reviewHashes.original ?? 'offline fixture']),
    padRow(['Revision review hash', reviewHashes.revision ?? 'offline fixture']),
    padRow(['Lease policy limitation', 'Finance-lease PP&E is already in opening PP&E; future lease additions are zero pending P8B policy bundle.']),
    padRow(['UFCF policy limitation', 'Economic UFCF subtracts recognized cash plus noncash PP&E additions; cash FCF remains separately visible.']),
    padRow([]),
    padRow(['P6 stored decision and provenance']),
    padRow(['Decision ID', p6.decision_id ?? 'P6 decision not attached']),
    padRow(['Status', p6Status]),
    padRow(['Human approval', 'false']),
    padRow(['Review verdict', p6.review?.verdict ?? 'MISSING']),
    padRow(['Coverage', 'Operating forecast only; later working-capital, tax, debt, SBC, investments and final integration policies remain incomplete.']),
    padRow([]),
    padRow(['Combined included-decision state']),
    padRow(['Decision ID', combined.decision_id]),
    padRow(['Status', combined.status]),
    padRow(['Human approval', 'false']),
    padRow(['P5 status', combined.p5_status]),
    padRow(['P6 status', combined.p6_status]),
    padRow(['P8B status', combined.p8b_status]),
    padRow(['Coverage', combined.coverage]),
  ];
  if (model.working_capital_forecast) rows.push(
    padRow([]),
    padRow(['P7 stored decision and provenance']),
    padRow(['Decision ID', p7.decision_id ?? 'P7 decision not attached']),
    padRow(['Status', p7Status]),
    padRow(['Human approval', 'false']),
    padRow(['Review verdict', p7.review?.verdict ?? p7.review_snapshot?.verdict ?? 'MISSING']),
    padRow(['Method', `${model.working_capital_forecast.method?.id ?? 'MISSING'} / ${model.working_capital_forecast.method?.version ?? 'MISSING'}`]),
    padRow(['Coverage', 'Balance-based working capital, contract liability bridge and cash-conversion NWC; taxes, debt, leases and investments remain separate pending P8.']),
  );
  if (model.tax_forecast) {
    const p8a = model.p8a_decision ?? model.tax_decision ?? {};
    const p8aBound = p8aDecisionIsBound(model, p8a);
    rows.push(
      padRow([]),
      padRow(['P8A stored decision and provenance']),
      padRow(['Decision ID', p8a.decision_id ?? 'P8A decision not attached']),
      padRow(['Status', p8a.status ?? 'MISSING']),
      padRow(['Human approval', 'false']),
      padRow(['Review verdict', p8a.review?.verdict ?? 'MISSING']),
      padRow(['Binding valid', String(p8aBound)]),
      padRow(['Book tax rate', model.tax_forecast.inputs?.book_tax_rate, 'decimal fraction', 'TTM book-tax / pretax anchor; provisional']),
      padRow(['Operating tax rate', model.tax_forecast.inputs?.operating_tax_rate, 'decimal fraction', 'Independent positive-EBIT UFCF tax driver']),
      padRow(['Coverage', 'Book/current/deferred/cash tax bridge and operating tax; P8B-P12 remain incomplete.']),
    );
  }
  if (model.financing_forecast) {
    const p8b = model.p8b_decision ?? model.financing_decision ?? {};
    const p8bBound = p8bDecisionIsBound(model, p8b);
    rows.push(
      padRow([]),
      padRow(['P8B stored decision and provenance']),
      padRow(['Decision ID', p8b.decision_id ?? 'P8B decision not attached']),
      padRow(['Status', p8b.status ?? 'MISSING']),
      padRow(['Human approval', 'false']),
      padRow(['Review verdict', p8b.review?.verdict ?? 'MISSING']),
      padRow(['Binding valid', String(p8bBound)]),
      padRow(['Method', `${model.financing_forecast.method?.id ?? 'MISSING'} / ${model.financing_forecast.method?.version ?? 'MISSING'}`]),
      padRow(['Debt policy', model.financing_forecast.forecast?.policy?.debt_refinance_policy ?? model.financing_forecast.policy?.debt_refinance_policy ?? 'MISSING']),
      padRow(['Lease bundle', model.financing_forecast.forecast?.policy?.lease_bundle ?? model.financing_forecast.policy?.lease_bundle ?? 'MISSING']),
      padRow(['Coverage', 'Debt face/contra/refinancing, operating ROU/liability, finance PP&E/liability, pipeline and explicit funding state; P8C-P12 remain incomplete.']),
    );
  }
  if (model.equity_forecast) {
    const p8c = model.p8c_decision ?? model.equity_decision ?? {};
    const p8cBound = p8cDecisionIsBound(model, p8c);
    rows.push(
      padRow([]),
      padRow(['P8C stored decision and provenance']),
      padRow(['Decision ID', p8c.decision_id ?? 'P8C decision not attached']),
      padRow(['Status', p8c.status ?? 'MISSING']),
      padRow(['Human approval', 'false']),
      padRow(['Review verdict', p8c.review?.verdict ?? 'MISSING']),
      padRow(['Binding valid', String(p8cBound)]),
      padRow(['Existing claim', '=DCF!B26', 'USD millions', 'Authoritative Equity!B40 claim linked once into the DCF bridge; stale proxy units × dated quote.']),
      padRow(['Partial equity bridge after claim', '=DCF!B27', 'USD millions', 'Displayed partial cash/debt bridge less one existing-award claim; P8D/P9 additions remain pending.']),
      padRow(['Partial point-share denominator', '=DCF!B28', 'shares millions', 'Measurement-date 7429m point shares; EPS weighted-average/diluted shares remain separate.']),
      padRow(['Partial value per point share', '=DCF!B29', 'USD/share', 'Partial diagnostic only; no complete investment valuation or human approval is claimed.']),
      padRow(['Settlement / repurchase price', model.equity_forecast.forecast?.existing_claim_price, 'USD/share', 'Claim quote shown; future settlement proxy remains a separate Equity input.']),
      padRow(['Coverage', 'Book SBC/P8A feed, explicit APIC/CFO/withholding, shares/EPS, program authorization, dividends, equity and CFO/EBIT UFCF bridge plus the connected partial claim/per-share diagnostic.']),
    );
  }
  if (model.other_balances_forecast) {
    const p8d = model.p8d_decision ?? model.other_balances_decision ?? model.other_balances_forecast.decision ?? {};
    const p8dBound = p8dDecisionIsBound(model, p8d);
    rows.push(
      padRow([]),
      padRow(['P8D stored decision and provenance']),
      padRow(['Decision ID', p8d.decision_id ?? 'P8D decision not attached']),
      padRow(['Status', p8d.status ?? 'MISSING']),
      padRow(['Human approval', 'false']),
      padRow(['Review verdict', p8d.review?.verdict ?? p8d.review_verdict ?? 'MISSING']),
      padRow(['Binding valid', String(p8dBound)]),
      padRow(['Method', `${model.other_balances_forecast.method?.id ?? model.other_balances_forecast.candidate?.method_id ?? 'investment_intangible_residual_rollforward'} / ${model.other_balances_forecast.method?.version ?? model.other_balances_forecast.candidate?.method_version ?? 'v1'}`]),
      padRow(['Investment value bridge', '=OtherBalances!B11', 'USD millions', 'One displayed nonoperating bridge; commitment rights and dated net funding adjustment are shown separately; source pools remain contained and the bridge stays outside operating UFCF.']),
      padRow(['FY2036 intangible closing', '=OtherBalances!L15', 'USD millions', 'Selected 10-year tail closes at 3,949.2; six/fifteen-year alternatives remain visible in the candidate sensitivities.']),
      padRow(['Coverage', 'Cash/ST/equity investments, financing receivables, intangibles, goodwill, DTA convention, legal stress, residual parents and commitments are represented once; P9 terminal integration remains pending.']),
    );
  }
  return rows;
}

function decisionRows(model) {
  const metadata = validatedReviewMetadata(model);
  if (!metadata) return legacyDecisionRows(model);
  const r = metadata.review;
  const b = metadata.bindings;
  const rows = [
    padRow(['Current P10 whole-model review and area decisions']),
    padRow(['The current independently reviewed exported-base record controls this section. Historical P5-P8D package records remain below as provenance.']),
    padRow(['Review ID', r.id]),
    padRow(['Review version', r.version]),
    padRow(['Verdict', r.verdict]),
    padRow(['Completed at', r.completed_at ?? 'not supplied']),
    padRow(['Selected financial model SHA256', b.selected_model_sha256]),
    padRow(['Financial snapshot SHA256', b.financial_snapshot_sha256]),
    padRow(['Review request SHA256', b.review_request_sha256]),
    padRow(['Review response SHA256', b.review_response_sha256]),
    padRow(['Source context SHA256', b.source_context_sha256]),
    padRow(['Human approval', 'false']),
    padRow(['Area', 'Outcome', 'Basis', 'Changed dependencies assessed', 'Decision refs', 'Source refs', 'Limitations']),
  ];
  for (const areaName of P11_AREAS) {
    const area = metadata.areas.find((item) => item.area === areaName);
    rows.push(padRow([area.area, area.outcome, area.basis, area.changed_dependencies.join('; '), area.decision_refs.join('; '), area.source_refs.join('; '), area.limitations.join('; ')]));
  }
  rows.push(padRow([]), padRow(['Historical package decisions — retained provenance; package-era coverage prose is superseded by the current 12-area review above.']));
  rows.push(...legacyDecisionRows(model));
  return rows;
}

function legacyReviewRows(model) {
  const candidate = model.candidate;
  const p6 = Boolean(model.operating_forecast);
  const p7 = Boolean(model.working_capital_forecast);
  const p8b = Boolean(model.financing_forecast);
  const p8c = Boolean(model.equity_forecast);
  const p8d = Boolean(model.other_balances_forecast);
  const p9 = Boolean(model.valuation_policy);
  const combined = combinedDecision(model);
  const operatingMethod = model.operating_forecast?.method;
  return [
    padRow([p9 ? 'AI Fund P9 — integrated MSFT statements, terminal DCF and complete equity bridge' : p8d ? 'AI Fund P8D — investments, intangibles, goodwill and remaining balances linked to P5/P6/P7/P8A/P8B/P8C schedules' : p8c ? 'AI Fund P8C — compensation, shares and equity linked to P5/P6/P7/P8A/P8B schedules' : p8b ? 'AI Fund P8B — debt and lease financing linked to P5/P6/P7/P8A schedules' : p7 ? 'AI Fund P7 — real MSFT working capital linked to P5/P6 schedules' : p6 ? 'AI Fund P6 — real MSFT operating forecast linked to P5 assets' : 'AI Fund P5 — real MSFT asset evidence-to-forecast slice']),
    padRow(['Purpose', p9 ? 'Preserve the accepted 11-period statements and add ACT/365 WACC discounting, finite-cohort terminal normalization, complete claims, live sensitivities and historical residual disclosure.' : p8d ? 'Preserve nonoperating investment value separately, replace embedded intangible amortization once, and roll goodwill, commitments and residual coverage through statements and the DCF bridge.' : p8c ? 'Separate embedded SBC once, connect book/P8A taxes, explicit share/equity/capital-return flows and claim/UFCF bridges.' : p8b ? 'Debt face/contra/refinancing and operating/finance lease schedules linked once into statements and UFCF.' : p7 ? 'Balance-based operating working capital and cash conversion linked once into CFO, cash, balance sheet and UFCF.' : p6 ? 'Reportable segment revenue and consolidated operating costs linked through the P5 asset, cash and DCF schedules.' : 'Bounded PP&E, depreciation, cash/noncash investment and provisional DCF sensitivity.']),
    padRow(['Status', p9 ? '=Valuation!B3' : model.tax_forecast ? '=IF(OR(Checks!B22<>"PASS",Inputs!B114<>"PASS"' + (p8b ? `,Inputs!B${FINANCING_DRIVER_ROWS.gate}<>"PASS"` : '') + (p8c ? `,Inputs!B${P8C_DRIVER_ROWS.gate}<>"PASS"` : '') + (p8d ? `,Inputs!B${P8D_DRIVER_ROWS.gate}<>"PASS"` : '') + '),"BLOCKED",IF(Checks!B23="UNCHANGED",Decisions!B28,"EDITED_UNREVIEWED"))' : `=IF(OR(Checks!B22<>"PASS"${p8c ? `,Inputs!B${P8C_DRIVER_ROWS.gate}<>"PASS"` : ''}${p8d ? `,Inputs!B${P8D_DRIVER_ROWS.gate}<>"PASS"` : ''}),"BLOCKED",IF(Checks!B23="UNCHANGED",Decisions!B28,"EDITED_UNREVIEWED"))`]),
    padRow(['Information cutoff', model.information_cutoff]),
    padRow(['Measurement / valuation date', model.measurement_date]),
    padRow(['Currency / units', 'USD millions; partial per-share diagnostic uses measurement-date point shares']),
    padRow(['Forecast shape', 'Apr-Jun FY2026 stub (91 days) + FY2027-FY2036 actual fiscal day counts']),
    padRow(['Calculation engine', `Mog SDK ${ENGINE_VERSION}`]),
    padRow(['Formula authority', 'Application-owned JavaScript; Excel is a review/recalculation target.']),
    padRow(['Decision status', '=Decisions!B28']),
    padRow(['Human approval', 'False. Workbook edits are local what-ifs; stored decisions require the controlled revision path.']),
    padRow(['Method', p6 && operatingMethod ? `${operatingMethod.id} / ${operatingMethod.version}` : `${candidate.method_id} / ${candidate.method_version}`]),
    padRow(['Open Inputs', '=HYPERLINK("#\'Inputs\'!A1","Open Inputs")']),
    ...(p6 ? [padRow(['Open Operating', '=HYPERLINK("#\'Operating\'!A1","Open Operating")'])] : []),
    ...(model.tax_forecast ? [padRow(['Open Taxes', '=HYPERLINK("#\'Taxes\'!A1","Open Taxes")'])] : []),
    ...(p8b ? [padRow(['Open Financing', '=HYPERLINK("#\'Financing\'!A1","Open Financing")'])] : []),
    ...(p8c ? [padRow(['Open Equity', '=HYPERLINK("#\'Equity\'!A1","Open Equity")'])] : []),
    ...(p8d ? [padRow(['Open Other Balances', '=HYPERLINK("#\'OtherBalances\'!A1","Open Other Balances")'])] : []),
    padRow(['Open Schedules', '=HYPERLINK("#\'Schedules\'!A1","Open Schedules")']),
    padRow([p9 ? 'Open canonical valuation' : 'Open DCF', p9 ? '=HYPERLINK("#\'Valuation\'!A1","Open Valuation")' : '=HYPERLINK("#\'DCF\'!A1","Open DCF")']),
    ...(p8c ? [
      padRow(['Existing-award claim in DCF bridge', '=DCF!B26', 'USD millions', 'Equity!B40 linked once; stale proxy claim at the dated measurement-date price']),
      padRow([p9 ? 'Complete common equity value' : 'Partial equity value after existing-award claim', '=DCF!B27', 'USD millions', p9 ? 'Canonical complete guarded P9 equity bridge' : 'Cash/debt bridge less one existing-award claim; P8D/P9 additions remain pending']),
      padRow([p9 ? 'Measurement-date point shares' : 'Measurement-date point shares used for partial diagnostic', '=DCF!B28', 'shares millions', '7429m current point shares; separate from EPS weighted-average/diluted shares']),
      padRow([p9 ? 'Complete value per measurement-date point share' : 'Partial value per measurement-date point share', '=DCF!B29', 'USD/share', p9 ? 'Canonical complete guarded P9 value' : 'Partial diagnostic only; not a complete investment valuation']),
    ] : []),
    padRow(['Open Checks', '=HYPERLINK("#\'Checks\'!A1","Open Checks")']),
    padRow(['Open Evidence', '=HYPERLINK("#\'Evidence\'!A1","Open Evidence")']),
    padRow(['Limitations', `${model.packet.unavailable.join('; ')}; ${p7 ? model.working_capital_forecast.limitations.join('; ') : ''}; ${p8d ? model.other_balances_forecast.limitations?.join('; ') ?? 'P8D selected values remain estimates; P9 terminal integration pending.' : ''}; ${combined.coverage}`]),
  ];
}

function reviewRows(model) {
  const metadata = validatedReviewMetadata(model);
  if (!metadata) {
    return {
      rows: legacyReviewRows(model),
      formulaCells: new Set(['B3', 'B10', ...Array.from({ length: 14 }, (_, index) => `B${index + 13}`)]),
    };
  }
  const rows = [];
  const formulaCells = new Set();
  const add = (row, formulaColumns = []) => {
    rows.push(padRow(row));
    const rowNumber = rows.length;
    for (const column of formulaColumns) formulaCells.add(`${columnName(column)}${rowNumber}`);
    return rowNumber;
  };
  const currentBaseUnchanged = 'AND(Checks!B23="UNCHANGED",Valuation!B41="SYSTEM_REVIEWED_PROVISIONAL")';
  const r = metadata.review;
  const s = metadata.states;
  const b = metadata.bindings;
  const p = metadata.provenance;
  const n = metadata.narrative;
  const caseName = typeof model.case === 'string' ? model.case : model.case?.ticker ?? 'MSFT';

  add(['Microsoft — financial model review']);
  add(['Scope', 'Authoritative exported-base financial model and its independent review, including any reviewed revision. Local Excel edits are what-ifs and invalidate the attached analytical state.']);
  add(['Company / case', caseName]);
  add(['Information cutoff', model.information_cutoff, '', 'Later-informed analysis; not point-in-time.']);
  add(['Measurement / valuation date', model.measurement_date]);
  add(['Forecast shape', 'Apr-Jun FY2026 stub (91 days), then FY2027-FY2036; 11 explicit periods.']);
  add(['Currency / units', 'USD millions except rates and USD/share values']);
  add(['Authoritative version', p.authoritative_version]);
  add(['Review record', `${r.id} / ${r.version}`]);
  add(['Selected financial model SHA256', b.selected_model_sha256, '', 'Hash identifies the unannotated financial input; review metadata is attached afterward.']);
  add([]);
  add(['State', 'Exported base', 'Current workbook', 'Meaning']);
  add(['Execution', s.execution, s.execution, 'P10 workflow execution outcome; historical after export.']);
  add(['Mechanical', s.mechanical, '=IF(AND(Checks!B22="PASS",Valuation!B99="PASS"),"PASS","FAIL")', 'Live formula and input gates.'], [3]);
  const coverageRow = add(['Coverage', s.coverage, '', 'All 12 financial areas; local financial edits make the attached assessment stale.']);
  rows[coverageRow - 1][2] = `=IF(${currentBaseUnchanged},B${coverageRow},"STALE_AFTER_EDIT")`;
  formulaCells.add(`C${coverageRow}`);
  const analyticalRow = add(['Analytical', s.analytical, '', 'Bound independent review of the exported base; human approval remains separate.']);
  rows[analyticalRow - 1][2] = `=IF(${currentBaseUnchanged},B${analyticalRow},"EDITED_UNREVIEWED")`;
  formulaCells.add(`C${analyticalRow}`);
  add(['Budget', s.budget, s.budget, 'Recorded P10 budget outcome; workbook recalculation has no paid reasoning.']);
  add(['Human', 'false', 'false', 'No human financial approval recorded.']);
  add([]);
  add(['Key live results', 'Current workbook', 'Units', 'Definition']);
  add(['Enterprise value', '=Valuation!B120', 'USD millions', 'Canonical guarded complete enterprise value.'], [2]);
  add(['Common equity value', '=Valuation!B121', 'USD millions', 'Complete once-only claims bridge.'], [2]);
  add(['Value per measurement-date point share', '=Valuation!B122', 'USD/share', 'Point-share denominator excludes existing award claim units.'], [2]);
  add(['WACC', '=Valuation!B39', 'decimal', 'Frozen dated market inputs plus selected beta and debt spread.'], [2]);
  add(['Terminal growth', '=Valuation!B27', 'decimal', 'Finite-cohort normalized terminal case.'], [2]);
  add(['Stub economic UFCF', '=DCF!B7', 'USD millions', 'Financing-independent operating cash flow.'], [2]);
  add(['FY2036 economic UFCF', '=DCF!L7', 'USD millions'], [2]);
  add(['Stub cash FCF', '=DCF!B9', 'USD millions', 'Reported-style CFO less cash PP&E payments.'], [2]);
  add(['FY2036 cash FCF', '=DCF!L9', 'USD millions'], [2]);
  add(['Stub closing cash', '=CashFlow!B18', 'USD millions'], [2]);
  add(['FY2036 closing cash', '=CashFlow!L18', 'USD millions'], [2]);
  add(['Stub funding state', '=Financing!B73', 'status', 'Negative cash remains visibly UNFUNDED.'], [2]);
  add(['FY2036 funding state', '=Financing!L73', 'status'], [2]);
  add(['Economic UFCF versus cash FCF', reviewNarrative(n.cash_vs_ufcf, 'narrative.cash_vs_ufcf'), '', 'Exported-base explanation.']);
  add([]);
  add(['Workbook navigation', 'Open']);
  for (const [label, sheet] of [
    ['Inputs', 'Inputs'], ['Income statement', 'Income'], ['Cash flow statement', 'CashFlow'], ['Balance sheet', 'BalanceSheet'],
    ['Financing', 'Financing'], ['Equity', 'Equity'], ['Other balances', 'OtherBalances'], ['Canonical valuation', 'Valuation'],
    ['Live sensitivities', 'P9Sensitivity'], ['Checks', 'Checks'], ['Evidence', 'Evidence'], ['Decisions', 'Decisions'], ['Exported/current inputs', 'SavedInputs'],
  ]) add([label, `=HYPERLINK("#'${sheet}'!A1","Open ${label}")`], [2]);
  add([]);
  add(['Material area', 'Outcome', 'Basis', 'Decision refs', 'Source refs', 'Decision record', 'Evidence record']);
  for (const areaName of P11_AREAS) {
    const area = metadata.areas.find((item) => item.area === areaName);
    const areaIndex = P11_AREAS.indexOf(areaName);
    const sourceIndex = metadata.sources.findIndex((source) => source.source_id === area.source_refs[0]);
    add([
      area.area,
      area.outcome,
      area.basis,
      area.decision_refs.join('; '),
      area.source_refs.join('; '),
      `=HYPERLINK("#'Decisions'!A${P11_DECISION_AREA_START + areaIndex}","Open decision")`,
      `=HYPERLINK("#'Evidence'!A${P11_EVIDENCE_SOURCE_START + sourceIndex}","Open evidence")`,
    ], [6, 7]);
  }
  add([]);
  add(['Exported-base analytical narrative']);
  add(['Summary', reviewNarrative(n.summary, 'narrative.summary')]);
  add(['Key drivers', reviewNarrative(n.key_drivers, 'narrative.key_drivers')]);
  add(['Limitations', reviewNarrative(n.limitations, 'narrative.limitations')]);
  add(['Source treatment', 'Segment cost of revenue and aggregate operating expense are disclosed; consolidated functional ratios are selected model choices.']);
  add(['Narrative status', 'Static exported-base rationale. It is not automatically revalidated after a workbook edit.']);
  return { rows, formulaCells };
}

function sensitivitySheets(model) {
  const calc = [padRow(['Recalculated asset sensitivity schedules']), padRow(['Same cohort-charge formulas as the base model. Every scenario recalculates depreciation, tax, cash/noncash investment and terminal discounting.']), periodHeader()];
  const scenario = (label, { factor = 1, wacc = 'Inputs!$B$37', openingLife = 'Inputs!$B$29', newLife = 'Inputs!$B$30', noncash = 'Inputs!$B$33' } = {}) => {
    const r = calc.length + 1;
    calc.push(padRow([label]));
    const push = (labelText, fn) => calc.push(periodRow(labelText, PERIODS.map((_, i) => fn(periodColumn(i), i))));
    const openingSensitivityCost = model.financing_forecast ? 'Inputs!$B$13-Inputs!$B$132' : 'Inputs!$B$13';
    push('Cash PP&E payment', (c) => `=Inputs!${c}58*${factor}`);
    push('Noncash unpaid PP&E additions', (c) => `=${c}${r + 1}*${noncash}`);
    push('Recognized investment', (c) => `=${c}${r + 1}+${c}${r + 2}`);
    push('Original pool depreciation', (c, i) => `=${cohortCharge(openingSensitivityCost, openingLife, '0', i)}`);
    push('New cohort depreciation', (c, i) => `=${PERIODS.slice(0, i + 1).map((_, j) => cohortCharge(`$${periodColumn(j)}$${r + 3}`, newLife, placementFor(j), i)).join('+')}`);
    push('Total depreciation', (c) => model.financing_forecast ? `=${c}${r + 4}+${c}${r + 5}+Financing!${c}66` : `=${c}${r + 4}+${c}${r + 5}`);
    push('Operating-cost proxy excluding PP&E depreciation', (c) => `=Schedules!${c}11`);
    push('EBIT', (c) => `=Schedules!${c}10-${c}${r + 7}-${c}${r + 6}`);
    push('Operating cash/book taxes', (c) => model.tax_forecast ? `=MAX(0,${c}${r + 8})*Inputs!$B$${TAX_DRIVER_ROWS.operatingTaxRate}` : `=MAX(0,${c}${r + 8})*Inputs!$B$35`);
    push('Economic UFCF', (c) => model.equity_forecast && factor === 1
      ? '=Equity!' + c + '33'
      : model.financing_forecast
      ? `=${c}${r + 8}-${c}${r + 9}+${c}${r + 6}+Financing!${c}64-Financing!${c}56-${c}${r + 3}-Financing!${c}49-Schedules!${c}26${model.other_balances_forecast ? `+OtherBalances!${c}${P8D_OUTPUT_ROWS.intangibleAmortization}` : ''}`
      : `=${c}${r + 8}-${c}${r + 9}+${c}${r + 6}-${c}${r + 3}-Schedules!${c}26${model.other_balances_forecast ? `+OtherBalances!${c}${P8D_OUTPUT_ROWS.intangibleAmortization}` : ''}`);
    push('Discount factor', (c, i) => `=1/(1+${wacc})^${PERIODS[i].cumulativeYears}`);
    push('PV of explicit UFCF', (c) => `=${c}${r + 10}*${c}${r + 11}`);
    calc.push(padRow(['Enterprise value', `=IFERROR(IF(AND(Checks!$B$22="PASS",${wacc}>Inputs!$B$38),SUM(B${r + 12}:L${r + 12})+L${r + 10}*(1+Inputs!$B$38)/(${wacc}-Inputs!$B$38)*L${r + 11},"BLOCKED"),"BLOCKED")`]));
    push('Cash from operations', (c) => `=${c}${r + 8}-${c}${r + 9}+${c}${r + 6}-Schedules!${c}26`);
    push('Closing PP&E', (c) => `=Inputs!$B$11+SUM($B$${r + 3}:${c}${r + 3})-SUM($B$${r + 6}:${c}${r + 6})`);
    calc.push(padRow([]));
    return r;
  };
  const ranges = new Map((model.candidate.sensitivities ?? []).map((s) => [s.parameter, s]));
  const params = asParameters(model.candidate);
  const interval = (name, ref, low, high) => {
    const value = ranges.get(name);
    return value ? [`=${ref}-(${params[name] - value.low})`, `=${ref}`, `=${ref}+(${value.high - params[name]})`] : [low, `=${ref}`, high];
  };
  const p9 = Boolean(model.valuation_policy);
  const rows = [padRow([p9 ? 'Superseded P5 asset-slice sensitivity: cash PP&E payments × legacy WACC' : 'DCF sensitivity: cash PP&E payments × WACC']), padRow([p9 ? 'Legacy ScenarioCalc retained for asset-schedule provenance only; use P9Sensitivity for canonical complete valuation cases.' : 'Cash-payment scenarios scale the entire forecast by80% /100% /120%. Supporting ScenarioCalc rows recalculate asset cohorts, tax and noncash investment.']), padRow(['WACC / implied base cash PP&E rate', '=Inputs!B32*0.8', '=Inputs!B32', '=Inputs!B32*1.2', p9 ? 'superseded USD millions asset-slice EV' : 'USD millions EV'])];
  const matrix = [];
  for (let i = 0; i < 3; i += 1) {
    const starts = [0.8, 1, 1.2].map((factor) => scenario(`Cash payments ×${factor}; WACC case${i + 1}`, { factor, wacc: `Sensitivity!$A$${i + 4}` }));
    matrix.push(starts);
    rows.push(padRow([i === 0 ? '=Inputs!B37-0.01' : i === 1 ? '=Inputs!B37' : '=Inputs!B37+0.01', ...starts.map((r) => `=ScenarioCalc!B${r + 13}`), 'USD millions EV']));
  }
  rows.push(padRow([]));
  const base = matrix[1][1];
  const addLife = (title, name, ref, row, option) => {
    rows.push(padRow([title]));
    const range = interval(name, ref, `=MAX(1,${ref}-2)`, `=MIN(20,${ref}+2)`);
    rows.push(padRow(['Life in years', ...range]));
    const starts = [scenario(`${title}: low`, { [option]: `Sensitivity!B${row}` }), base, scenario(`${title}: high`, { [option]: `Sensitivity!D${row}` })];
    const metric = (label, offset, expression) => rows.push(padRow([label, ...starts.map((r) => expression ? `=${expression(r)}` : `=ScenarioCalc!B${r + offset}`)]));
    metric('Stub total depreciation', 6);
    metric('Stub net income', 0, (r) => `ScenarioCalc!B${r + 8}-ScenarioCalc!B${r + 9}`);
    metric('Stub CFO', 14);
    metric('Stub closing PP&E', 15);
    metric('Enterprise value', 13);
  };
  addLife('Original-pool remaining-life sensitivity', 'opening_remaining_life_years', 'Inputs!B29', 9, 'openingLife');
  rows.push(padRow([]));
  addLife('New-addition useful-life sensitivity', 'new_addition_useful_life_years', 'Inputs!B30', 17, 'newLife');
  rows.push(padRow([]));
  rows.push(padRow(['Unpaid noncash-addition sensitivity']));
  rows.push(padRow(['Noncash additions / cash payments', ...interval('noncash_ppe_additions_ratio', 'Inputs!B33', '=MAX(0,Inputs!B33-0.1)', '=MIN(1,Inputs!B33+0.1)')]));
  const noncash = [scenario('Noncash low', { noncash: 'Sensitivity!B25' }), base, scenario('Noncash high', { noncash: 'Sensitivity!D25' })];
  for (const [label, offset] of [['Stub recognized investment', 3], ['Stub CFO', 14], ['Stub closing PP&E', 15], ['Enterprise value', 13]]) rows.push(padRow([label, ...noncash.map((r) => `=ScenarioCalc!B${r + offset}`)]));
  if (model.financing_forecast) {
    const financingSensitivity = model.financing_forecast.forecast?.pipeline_sensitivities?.scenarios ?? [];
    rows.push(padRow([]));
    rows.push(padRow(['P8B signed-pipeline sensitivity preview']));
    rows.push(padRow(['Application-recomputed alternatives preserve the 196,600 commitment total; base Mog formulas remain above and inputs/terms stay visible.']));
    rows.push(padRow(['Scenario', 'Finance share', 'Operating rate', 'Finance rate', 'FY2026 stub weight', 'FY2027 weight', 'FY2028 weight', 'FY2029 weight', 'FY2030 weight', 'FY2031 weight']));
    for (const item of financingSensitivity) {
      rows.push(padRow([item.name, item.finance_share, item.operating_rate, item.finance_rate, ...(item.weights ?? [])]));
      rows.push(padRow(['Operating PV additions', ...(item.operating_additions ?? []).slice(0, 6), 'USD millions']));
      rows.push(padRow(['Finance PV additions', ...(item.finance_additions ?? []).slice(0, 6), 'USD millions']));
      rows.push(padRow(['Operating expense', ...(item.operating_expense ?? []).slice(0, 6), 'USD millions']));
      rows.push(padRow(['Finance depreciation', ...(item.finance_depreciation ?? []).slice(0, 6), 'USD millions']));
    }
    rows.push(padRow([]));
    rows.push(padRow(['P8B opening finance-asset life sensitivity']));
    rows.push(padRow(['Service life years', ...(model.financing_forecast.forecast?.opening_finance_life_sensitivities ?? []).map((item) => item.service_life_years), 'Selected base is 13 years; 10/16-year alternatives are application previews.']));
    rows.push(padRow(['FY2026 stub depreciation', ...(model.financing_forecast.forecast?.opening_finance_life_sensitivities ?? []).map((item) => item.depreciation?.[0]), 'USD millions']));
    rows.push(padRow(['FY2036 closing finance PP&E', ...(model.financing_forecast.forecast?.opening_finance_life_sensitivities ?? []).map((item) => item.closing_ppe?.[10]), 'USD millions']));
  }
  if (model.other_balances_forecast) {
    rows.push(padRow([]));
    rows.push(padRow(['P8D investment and remaining-balance sensitivities']));
    rows.push(padRow(['Other investment value multiplier', 0.5, 1.0, 1.5, 'x; carrying-based estimate on the selected Other pool']));
    const multipleRow = rows.length;
    rows.push(padRow(['Investment measurement value bridge', `=OtherBalances!B11-Inputs!$B$${P8D_DRIVER_ROWS.otherInvestmentPool}*Inputs!$B$${P8D_DRIVER_ROWS.otherInvestmentMultiplier}+Inputs!$B$${P8D_DRIVER_ROWS.otherInvestmentPool}*B${multipleRow}`, '=OtherBalances!B11', `=OtherBalances!B11-Inputs!$B$${P8D_DRIVER_ROWS.otherInvestmentPool}*Inputs!$B$${P8D_DRIVER_ROWS.otherInvestmentMultiplier}+Inputs!$B$${P8D_DRIVER_ROWS.otherInvestmentPool}*D${multipleRow}`, 'USD millions; known market/cash, financing receivables and commitment adjustment remain unchanged']));
    rows.push(padRow(['Intangible tail life years', 6, 10, 15, 'years; full selected tail remains outside the visible horizon']));
    const tailLifeRow = rows.length + 1;
    rows.push(padRow(['FY2036 intangible closing', `=Inputs!$B$${P8D_DRIVER_ROWS.openingIntangibles}-SUM(Inputs!$B$${P8D_DRIVER_ROWS.intangibleStubAmortization}:Inputs!$B$${P8D_DRIVER_ROWS.intangibleFy30Amortization})-Inputs!$B$${P8D_DRIVER_ROWS.intangibleTailPool}/B${tailLifeRow}*6`, '=OtherBalances!L15', `=Inputs!$B$${P8D_DRIVER_ROWS.openingIntangibles}-SUM(Inputs!$B$${P8D_DRIVER_ROWS.intangibleStubAmortization}:Inputs!$B$${P8D_DRIVER_ROWS.intangibleFy30Amortization})-Inputs!$B$${P8D_DRIVER_ROWS.intangibleTailPool}/D${tailLifeRow}*6`, 'USD millions']));
    rows.push(padRow(['Goodwill impairment stress', 0, 10000, 'USD millions; nondeductible noncash loss, no automatic EV deduction']));
    rows.push(padRow(['Incremental NET DTA value sensitivity', 0, 26273, 'USD millions; historical proxy, not Q3 carrying value']));
  }
  return { rows, calc };
}

export async function writeSheet(wb, name, rows, { formulaCells = new Set() } = {}) {
  const sheet = await wb.getSheet(name);
  const width = Math.max(13, ...rows.map((row) => row.length));
  const normalized = rows.map((row) => padRow(row, width));
  // All source and model text is literal before it can enter the engine.
  // Only explicitly application-owned formula locations are executable.
  const formulaSheets = new Set(['Schedules', 'AssetCohorts', 'ScenarioCalc', 'Sensitivity', 'Income', 'CashFlow', 'BalanceSheet', 'DCF', 'Checks', 'WorkingCapital', 'Taxes', 'SavedInputs', 'Financing', 'FinancingRunoff', 'Equity', 'Claims', 'OtherBalances', 'Valuation', 'TerminalCohorts', 'P9Sensitivity', 'HistoricalBridge']);
  const appFormula = (r, c, value) => typeof value === 'string' && value.startsWith('=') && (
    formulaSheets.has(name)
    || (name === 'Operating' && c >= 2 && c <= 12 && OPERATING_FORMULA_ROWS.includes(r))
    || (name === 'Inputs' && ((c === 2 && [25, 54, 59, 78, P7_DRIVER_ROWS.gate, P7_DRIVER_ROWS.accruedCompensationBaseline, P7_DRIVER_ROWS.accruedCompensationEffectiveRatio, TAX_DRIVER_ROWS.gate, FINANCING_DRIVER_ROWS.gate, P8C_DRIVER_ROWS.gate, P8C_DRIVER_ROWS.totalServiceDays, P8D_DRIVER_ROWS.gate, P8D_DRIVER_ROWS.coverage].includes(r)) || (c >= 2 && c <= 12 && [55, 58, P8C_DRIVER_ROWS.bookSbc, P8C_DRIVER_ROWS.existingServiceCost, P8C_DRIVER_ROWS.newSbc, P8C_DRIVER_ROWS.grossExistingUnits, P8C_DRIVER_ROWS.grossNewUnits, P8C_DRIVER_ROWS.withheldUnits, P8C_DRIVER_ROWS.netDeliveredUnits, P8C_DRIVER_ROWS.cashIssuance, P8C_DRIVER_ROWS.issuanceUnits, P8C_DRIVER_ROWS.programTarget, P8C_DRIVER_ROWS.programCash, P8C_DRIVER_ROWS.programUnits, P8C_DRIVER_ROWS.programApicBasis, P8C_DRIVER_ROWS.dividendDeclaration, P8C_DRIVER_ROWS.dividendPayableOpening, P8C_DRIVER_ROWS.dividendPayableClosing, P8C_DRIVER_ROWS.dividendCashPaid, P8C_DRIVER_ROWS.pointSharesOpening, P8C_DRIVER_ROWS.pointSharesClosing, P8C_DRIVER_ROWS.basicWeightedShares, P8C_DRIVER_ROWS.dilutedIncrement, P8C_DRIVER_ROWS.basicEps, P8C_DRIVER_ROWS.dilutedEps, P8C_DRIVER_ROWS.valuationEbit, P8C_DRIVER_ROWS.normalizedTax, P8C_DRIVER_ROWS.valuationUfcf, P8C_DRIVER_ROWS.cfoUfcf, P8C_DRIVER_ROWS.withholdingCash, P8C_DRIVER_ROWS.apicClosing, P8C_DRIVER_ROWS.retainedEarningsClosing, P8C_DRIVER_ROWS.aociClosing, P8C_DRIVER_ROWS.totalEquity, P8C_DRIVER_ROWS.authorizationRemaining, P8C_DRIVER_ROWS.serviceDays, P8D_DRIVER_ROWS.investmentCarrying, P8D_DRIVER_ROWS.investmentAdditions, P8D_DRIVER_ROWS.cashIncome, P8D_DRIVER_ROWS.noncashGain, P8D_DRIVER_ROWS.investmentValue, P8D_DRIVER_ROWS.intangibleOpening, P8D_DRIVER_ROWS.intangibleAmortization, P8D_DRIVER_ROWS.intangibleClosing, P8D_DRIVER_ROWS.goodwillClosing, P8D_DRIVER_ROWS.dtaValue, P8D_DRIVER_ROWS.commitmentFundingCfi].includes(r))))
    || (name === 'Review' && formulaCells.has(`${columnName(c)}${r}`))
  );
  await sheet.setRange(`A1:${columnName(width)}${normalized.length}`, normalized.map((row, r) => row.map((v, c) => typeof v === 'string' && !appFormula(r + 1, c + 1, v) ? null : v)));
  for (let r = 0; r < normalized.length; r += 1) {
    for (let c = 0; c < normalized[r].length; c += 1) {
      const value = normalized[r][c];
      if (typeof value === 'string' && !appFormula(r + 1, c + 1, value)) await sheet.setCell(`${columnName(c + 1)}${r + 1}`, value, { literal: true });
    }
  }
  return sheet;
}

async function formatWorkbook(wb, model) {
  const sheetNames = ['Review', 'Inputs', ...(model.operating_forecast ? ['Operating'] : []), ...(model.working_capital_forecast ? ['WorkingCapital'] : []), ...(model.tax_forecast ? ['Taxes'] : []), ...(model.financing_forecast ? ['Financing', 'FinancingRunoff'] : []), ...(model.equity_forecast ? ['Equity'] : []), ...(model.other_balances_forecast ? ['OtherBalances'] : []), ...(model.valuation_policy ? ['Valuation', 'TerminalCohorts', 'P9Sensitivity', 'HistoricalBridge'] : []), 'Schedules', 'AssetCohorts', 'ScenarioCalc', 'SavedInputs', 'Income', 'CashFlow', 'BalanceSheet', 'DCF', 'Checks', 'Evidence', 'Decisions', 'Sensitivity'];
  for (const name of sheetNames) {
    const sheet = await wb.getSheet(name);
    await sheet.formats.setRange('A1:M1', { bold: true, backgroundColor: '#D9EAF7' });
    await sheet.formats.setRange('A3:M5', { bold: true, backgroundColor: '#EAF2F8' });
  }
  const inputs = await wb.getSheet('Inputs');
  await inputs.formats.setRange('B6:B50', { numberFormat: AMOUNT_FORMAT });
  await inputs.formats.setRange('B29:B30', { numberFormat: '0.000' });
  await inputs.formats.setRange('B31:B33', { numberFormat: '0.0%' });
  await inputs.formats.setRange('B35:B38', { numberFormat: '0.0%' });
  await inputs.formats.setRange('B55:L55', { numberFormat: AMOUNT_FORMAT });
  await inputs.formats.setRange('B58:L58', { numberFormat: AMOUNT_FORMAT });
  await inputs.formats.setRange('B59', { numberFormat: '0.0%' });
  if (model.operating_forecast) {
    await inputs.formats.setRange('B64:L71', { numberFormat: '0.0%' });
    await inputs.formats.setRange('B75:D77', { numberFormat: AMOUNT_FORMAT });
    const operating = await wb.getSheet('Operating');
    await operating.formats.setRange('B6:L21', { numberFormat: AMOUNT_FORMAT });
    await operating.formats.setRange('B22:L23', { numberFormat: '0.0%' });
  }
  if (model.working_capital_forecast) {
    const workingCapital = await wb.getSheet('WorkingCapital');
    await workingCapital.formats.setRange('B6:L47', { numberFormat: AMOUNT_FORMAT });
    await workingCapital.formats.setRange('B8:L8', { numberFormat: '0' });
    await workingCapital.formats.setRange('B49:D70', { numberFormat: AMOUNT_FORMAT });
    await inputs.formats.setRange(`B${P7_DRIVER_ROWS.dso}:B${P7_DRIVER_ROWS.dpo}`, { numberFormat: '0.000' });
     await inputs.formats.setRange(`B${P7_DRIVER_ROWS.accruedCompensationMultiplier}:B${P7_DRIVER_ROWS.contractRecognitionShare}`, { numberFormat: '0.000000' });
     await inputs.formats.setRange(`B${P7_DRIVER_ROWS.currentContractShare}`, { numberFormat: '0.000000' });
     await inputs.formats.setRange(`B${P7_DRIVER_ROWS.accruedCompensationBaseline}:B${P7_DRIVER_ROWS.accruedCompensationEffectiveRatio}`, { numberFormat: '0.000000' });
    await inputs.formats.setRange(`B${P7_DRIVER_ROWS.periodDays}:L${P7_DRIVER_ROWS.periodDays}`, { numberFormat: '0' });
  }
  if (model.tax_forecast) {
    const taxes = await wb.getSheet('Taxes');
    await taxes.formats.setRange('B6:L29', { numberFormat: AMOUNT_FORMAT });
    await taxes.formats.setRange('B10:L10', { numberFormat: '0.0%' });
    await taxes.formats.setRange('B12:L12', { numberFormat: '0.0%' });
    await taxes.formats.setRange('B28:L28', { numberFormat: '0.0%' });
    await inputs.formats.setRange(`B${TAX_DRIVER_ROWS.bookTaxRate}:B${TAX_DRIVER_ROWS.operatingTaxRate}`, { numberFormat: '0.0%' });
    await inputs.formats.setRange(`B${TAX_DRIVER_ROWS.deferredShare}:L${TAX_DRIVER_ROWS.longTermTaxSettlement}`, { numberFormat: AMOUNT_FORMAT });
    await inputs.formats.setRange(`B${TAX_DRIVER_ROWS.openingCurrentTaxPayable}:B${TAX_DRIVER_ROWS.openingDeferredTaxLiability}`, { numberFormat: AMOUNT_FORMAT });
    await inputs.formats.setRange(`B${TAX_DRIVER_ROWS.currentTaxPayableDays}`, { numberFormat: '0.000000' });
    await inputs.formats.setRange(`B${TAX_DRIVER_ROWS.periodDays}:L${TAX_DRIVER_ROWS.periodDays}`, { numberFormat: '0' });
  }
  if (model.financing_forecast) {
    const financingSheet = await wb.getSheet('Financing');
    await financingSheet.formats.setRange('B6:L74', { numberFormat: AMOUNT_FORMAT });
    await financingSheet.formats.setRange('B27:L27', { numberFormat: '@' });
    await financingSheet.formats.setRange('B73:L74', { numberFormat: '@' });
    await inputs.formats.setRange(`B${FINANCING_DRIVER_ROWS.debtCouponRate}:B${FINANCING_DRIVER_ROWS.debtCouponRate}`, { numberFormat: '0.0%' });
    await inputs.formats.setRange(`B${FINANCING_DRIVER_ROWS.refinanceFeeRate}:B${FINANCING_DRIVER_ROWS.refinanceFeeRate}`, { numberFormat: '0.0%' });
    await inputs.formats.setRange(`B${FINANCING_DRIVER_ROWS.openingOperatingRate}:B${FINANCING_DRIVER_ROWS.financeWeightedRate}`, { numberFormat: '0.0%' });
    await inputs.formats.setRange(`B${FINANCING_DRIVER_ROWS.pipelineFinanceShare}:B${FINANCING_DRIVER_ROWS.pipelineFinanceShare}`, { numberFormat: '0.0%' });
    await inputs.formats.setRange(`B${FINANCING_DRIVER_ROWS.pipelineOperatingRate}:B${FINANCING_DRIVER_ROWS.pipelineFinanceRate}`, { numberFormat: '0.0%' });
    await inputs.formats.setRange(`B${FINANCING_DRIVER_ROWS.openingFinanceLifeYears}:B${FINANCING_DRIVER_ROWS.openingFinanceLifeYears}`, { numberFormat: '0' });
    await inputs.formats.setRange(`B${FINANCING_DRIVER_ROWS.periodDays}:L${FINANCING_DRIVER_ROWS.periodDays}`, { numberFormat: '0' });
    await inputs.formats.setRange(`B${FINANCING_DRIVER_ROWS.debtRedemption}:L${FINANCING_DRIVER_ROWS.pipelineFinancePrincipal}`, { numberFormat: AMOUNT_FORMAT });
    const runoff = await wb.getSheet('FinancingRunoff');
    await runoff.formats.setRange('B1:Q10', { numberFormat: AMOUNT_FORMAT });
  }
  if (model.equity_forecast) {
    const equitySheet = await wb.getSheet('Equity');
    await equitySheet.formats.setRange('B6:L45', { numberFormat: AMOUNT_FORMAT });
    await inputs.formats.setRange(`B${P8C_DRIVER_ROWS.sbcRatio}:B${P8C_DRIVER_ROWS.sbcRatio}`, { numberFormat: '0.000000%' });
    await inputs.formats.setRange(`B${P8C_DRIVER_ROWS.withholdingRate}:B${P8C_DRIVER_ROWS.withholdingRate}`, { numberFormat: '0.0%' });
    await inputs.formats.setRange(`B${P8C_DRIVER_ROWS.cashIssuanceRatio}:B${P8C_DRIVER_ROWS.repurchaseRatio}`, { numberFormat: '0.000000%' });
    await inputs.formats.setRange(`B${P8C_DRIVER_ROWS.dividendPerShareQuarter}:B${P8C_DRIVER_ROWS.dividendPerShareQuarter}`, { numberFormat: '0.00' });
    await inputs.formats.setRange(`B${P8C_DRIVER_ROWS.embeddedSbcRatio}:B${P8C_DRIVER_ROWS.embeddedSbcRatio}`, { numberFormat: '0.000000%' });
    await inputs.formats.setRange(`B${P8C_DRIVER_ROWS.deliveryTiming}:B${P8C_DRIVER_ROWS.repurchaseTiming}`, { numberFormat: '0.0%' });
    await inputs.formats.setRange(`B${P8C_DRIVER_ROWS.periodDays}:L${P8C_DRIVER_ROWS.serviceDays}`, { numberFormat: '0' });
    await inputs.formats.setRange(`B${P8C_DRIVER_ROWS.totalServiceDays}:B${P8C_DRIVER_ROWS.openingTotalEquity}`, { numberFormat: AMOUNT_FORMAT });
  }
  if (model.other_balances_forecast) {
    const otherBalances = await wb.getSheet('OtherBalances');
    await otherBalances.formats.setRange('B6:L25', { numberFormat: AMOUNT_FORMAT });
    await otherBalances.formats.setRange('B22:L22', { numberFormat: '@' });
    await otherBalances.formats.setRange('B26:L26', { numberFormat: '@' });
    await inputs.formats.setRange(`B${P8D_DRIVER_ROWS.cashIncomeYield}`, { numberFormat: '0.000000%' });
    await inputs.formats.setRange(`B${P8D_DRIVER_ROWS.unfundedCommitmentValueFraction}`, { numberFormat: '0.0%' });
    await inputs.formats.setRange(`B${P8D_DRIVER_ROWS.embeddedIntangibleRatio}`, { numberFormat: '0.000000%' });
    await inputs.formats.setRange(`B${P8D_DRIVER_ROWS.intangibleTailLifeYears}`, { numberFormat: '0' });
    await inputs.formats.setRange(`B${P8D_DRIVER_ROWS.investmentCarrying}:L${P8D_DRIVER_ROWS.commitmentFundingCfi}`, { numberFormat: AMOUNT_FORMAT });
    await inputs.formats.setRange(`B${P8D_DRIVER_ROWS.intangibleStubAmortization}:B${P8D_DRIVER_ROWS.identifiedLongTermDebtInvestments}`, { numberFormat: AMOUNT_FORMAT });
    await inputs.formats.setRange(`B${P8D_DRIVER_ROWS.periodDays}:L${P8D_DRIVER_ROWS.periodDays}`, { numberFormat: '0' });
  }
  if (model.valuation_policy) {
    const valuation = await wb.getSheet('Valuation');
    await valuation.formats.setRange('B12:B39', { numberFormat: AMOUNT_FORMAT });
    await valuation.formats.setRange('B12:B16', { numberFormat: '0.000000%' });
    await valuation.formats.setRange('B27:B31', { numberFormat: '0.000000%' });
    await valuation.formats.setRange('B39:B39', { numberFormat: '0.000000%' });
    await valuation.formats.setRange('B46:L49', { numberFormat: AMOUNT_FORMAT });
    await valuation.formats.setRange('B116:B118', { numberFormat: '0.000000%' });
    const p9Sensitivity = await wb.getSheet('P9Sensitivity');
    await p9Sensitivity.formats.setRange('A4:O8', { numberFormat: AMOUNT_FORMAT });
    await p9Sensitivity.formats.setRange('A4:A8', { numberFormat: '0.0%' });
  }
  for (const name of ['Schedules', 'Income', 'CashFlow', 'BalanceSheet', 'DCF', 'Checks', 'Sensitivity']) {
    const sheet = await wb.getSheet(name);
    await sheet.formats.setRange('B5:L40', { numberFormat: AMOUNT_FORMAT });
  }
  const schedules = await wb.getSheet('Schedules');
  await schedules.formats.setRange('B5:L7', { numberFormat: '0.000000' });
  const dcf = await wb.getSheet('DCF');
  await dcf.formats.setRange('B5:L10', { numberFormat: AMOUNT_FORMAT });
}

function validatePeriods() {
  let cumulative = 0;
  PERIODS.forEach((period, index) => {
    cumulative += period.yearFraction;
    if (Math.abs(cumulative - period.cumulativeYears) > TOLERANCE) throw new Error(`Bad cumulative period at ${period.id}`);
    if (index === 0 && period.yearFraction !== 0.25) throw new Error('P5 stub must be 0.25 years');
    if (index > 0 && period.yearFraction !== 1) throw new Error('P5 full-year periods must be one year');
  });
}

export async function buildAssetWorkbook(model) {
  validatePeriods();
  if (model.valuation_policy) validateValuationPolicy(model.valuation_policy);
  const reviewMetadata = validatedReviewMetadata(model);
  const values = inputsFromModel(model);
  const wb = await createWorkbook({ userTimezone: 'UTC' });
  await wb.sheets.rename('Sheet1', 'Review');
  for (const name of ['Inputs', ...(model.operating_forecast ? ['Operating'] : []), ...(model.working_capital_forecast ? ['WorkingCapital'] : []), ...(model.tax_forecast ? ['Taxes'] : []), ...(model.financing_forecast ? ['Financing', 'FinancingRunoff'] : []), ...(model.equity_forecast ? ['Equity'] : []), ...(model.other_balances_forecast ? ['OtherBalances'] : []), ...(model.valuation_policy ? ['Valuation', 'TerminalCohorts', 'P9Sensitivity', 'HistoricalBridge'] : []), 'Schedules', 'AssetCohorts', 'ScenarioCalc', 'SavedInputs', 'Income', 'CashFlow', 'BalanceSheet', 'DCF', 'Checks', 'Evidence', 'Decisions', 'Sensitivity']) await wb.sheets.add(name);
  const review = reviewRows(model);
  await writeSheet(wb, 'Review', review.rows, { formulaCells: review.formulaCells });
  await writeSheet(wb, 'Inputs', sourceRows(values, model));
  if (model.operating_forecast) await writeSheet(wb, 'Operating', operatingRows(model));
  if (model.working_capital_forecast) await writeSheet(wb, 'WorkingCapital', workingCapitalRows(model));
  if (model.tax_forecast) await writeSheet(wb, 'Taxes', taxRows(model));
  if (model.financing_forecast) {
    await writeSheet(wb, 'Financing', financingRows(model));
    await writeSheet(wb, 'FinancingRunoff', financingRunoffRows(model));
  }
  if (model.equity_forecast) await writeSheet(wb, 'Equity', equityRows(model));
  if (model.other_balances_forecast) await writeSheet(wb, 'OtherBalances', otherBalancesRows(model));
  await writeSheet(wb, 'Schedules', schedulesRows(model));
  await writeSheet(wb, 'AssetCohorts', cohortRows(model));
  await writeSheet(wb, 'Income', incomeRows(model));
  await writeSheet(wb, 'CashFlow', cashFlowRows(model));
  await writeSheet(wb, 'BalanceSheet', balanceSheetRows(model));
  await writeSheet(wb, 'DCF', dcfRows(model));
  await writeSheet(wb, 'Checks', checksRows(model));
  if (model.valuation_policy) {
    await writeSheet(wb, 'Valuation', valuationRows(model));
    await writeSheet(wb, 'TerminalCohorts', terminalCohortRows(model));
    await writeSheet(wb, 'P9Sensitivity', p9SensitivityRows(model));
    await writeSheet(wb, 'HistoricalBridge', historicalBridgeRows(model));
  }
  await writeSheet(wb, 'Evidence', evidenceRows(model));
  await writeSheet(wb, 'Decisions', decisionRows(model));
  const sensitivity = sensitivitySheets(model);
  await writeSheet(wb, 'Sensitivity', sensitivity.rows);
  await writeSheet(wb, 'ScenarioCalc', sensitivity.calc);
  const inputs = await wb.getSheet('Inputs');
  const parameters = new Map(model.candidate.parameters.map((p) => [p.name, p]));
  const materialInputs = new Map((reviewMetadata?.material_inputs ?? []).map((item) => [item.address, item]));
  for (const [address, name] of [['B29', 'opening_remaining_life_years'], ['B30', 'new_addition_useful_life_years'], ['B32', 'cash_ppe_additions_rate'], ['B33', 'noncash_ppe_additions_ratio']]) {
    const p = parameters.get(name);
    if (!materialInputs.has(`Inputs!${address}`)) await inputs.comments.addNote(address, { author: 'smrik-fund', text: `${p.basis}; ${(p.evidence_refs ?? []).join(', ')}\n${p.rationale}\nUncertainty: ${p.uncertainty}` });
  }
  await wb.calculate();
  const required = requiredInputs(model);
  const requiredQualified = new Set(required.map((address) => `Inputs!${address}`));
  const savedAddresses = [...required.map((address) => `Inputs!${address}`), ...[...materialInputs.keys()].filter((address) => !requiredQualified.has(address))];
  const savedRows = [
    padRow(['Exported-base and current workbook inputs']),
    padRow(['Workbook changes are local what-ifs. Exported-base rationale stays static and the attached analytical review becomes stale.']),
    padRow(['Input address', 'Exported-base value', 'Changed flag', 'Current workbook value', 'Units / classification', 'Area', 'Decision / evidence refs']),
  ];
  for (const qualifiedAddress of savedAddresses) {
    const [sheetName, address] = qualifiedAddress.split('!');
    const sourceSheet = sheetName === 'Inputs' ? inputs : await wb.getSheet(sheetName);
    const row = savedRows.length + 1;
    const saved = await sourceSheet.getValue(address);
    const material = materialInputs.get(qualifiedAddress);
    if (material) {
      const matches = typeof saved === 'number' && typeof material.exported_value === 'number'
        ? Math.abs(saved - material.exported_value) <= TOLERANCE
        : saved === material.exported_value;
      if (!matches) throw new Error(`P11 exported input does not match workbook: ${qualifiedAddress}`);
      const sourceDetails = material.source_refs.map((sourceId) => {
        const source = reviewMetadata.sources.find((item) => item.source_id === sourceId);
        return `${sourceId}: ${source.source_file} ${source.locator} (${source.period}; ${source.sha256})`;
      }).join('\n');
      await sourceSheet.comments.addNote(address, {
        author: 'smrik-fund exported review',
        text: `Exported base: ${material.exported_value} ${material.units}\nClassification: ${material.classification}\nArea: ${material.area}\nDecision: ${material.decision_refs.join(', ')}\nEvidence:\n${sourceDetails}\nExported-base rationale: ${material.rationale}\nCaveat: ${material.caveat || 'none stated'}\nLocal edits invalidate the attached analytical review; compare SavedInputs.`,
      });
    }
    const comparison = typeof saved === 'number'
      ? `=IFERROR(IF(ABS(${qualifiedAddress}-B${row})<=${TOLERANCE},0,1),1)`
      : `=IFERROR(IF(${qualifiedAddress}=B${row},0,1),1)`;
    savedRows.push(padRow([
      qualifiedAddress,
      saved,
      comparison,
      `=${qualifiedAddress}`,
      material ? `${material.units} / ${material.classification}` : '',
      material?.area ?? '',
      material ? `${material.decision_refs.join(', ')} / ${material.source_refs.join(', ')}` : '',
    ]));
  }
  await writeSheet(wb, 'SavedInputs', savedRows);
  const savedInputs = await wb.getSheet('SavedInputs');
  for (let row = 4; row <= savedRows.length; row += 1) {
    // Register display links after the saved values exist. Mog can otherwise
    // retain their cached values while omitting a forward-reference formula.
    await savedInputs.setCell(`D${row}`, savedRows[row - 1][3]);
  }
  if (model.valuation_policy) {
    // Register this dependency after the saved-input comparison exists. Mog
    // can otherwise omit the formula while retaining a stale calculated value.
    const valuation = await wb.getSheet('Valuation');
    await valuation.setCell(`B${P9_ROWS.reviewStatus}`, valuationRows(model)[P9_ROWS.reviewStatus - 1][1]);
    if (reviewMetadata) {
      await valuation.setCell('A1', 'Microsoft — integrated valuation and terminal economics');
      await valuation.setCell('B3', '=IF(Review!C14="PASS",Review!C16,"BLOCKED")');
      await valuation.setCell('C3', 'Current bound analytical review; local edits invalidate it');
      await valuation.setCell('C4', 'Independent review recorded; human financial approval remains outstanding');
    }
  }
  await formatWorkbook(wb, model);
  await wb.calculate();
  return { wb, values, modelVersion: MODEL_VERSION, engineVersion: ENGINE_VERSION };
}

export async function readPeriodValues(wb, sheetName, row) {
  const sheet = await wb.getSheet(sheetName);
  const values = [];
  for (let index = 0; index < PERIODS.length; index += 1) values.push(await sheet.getValue(periodCell(index, row)));
  return values;
}

export async function readSnapshot(wb) {
  const schedules = await wb.getSheet('Schedules');
  const income = await wb.getSheet('Income');
  const cashFlow = await wb.getSheet('CashFlow');
  const bs = await wb.getSheet('BalanceSheet');
  const inputs = await wb.getSheet('Inputs');
  const dcf = await wb.getSheet('DCF');
  const checks = await wb.getSheet('Checks');
  let operating = null;
  try {
    operating = await wb.getSheet('Operating');
  } catch {
    operating = null;
  }
  let workingCapital = null;
  try {
    workingCapital = await wb.getSheet('WorkingCapital');
  } catch {
    workingCapital = null;
  }
  let taxes = null;
  try {
    taxes = await wb.getSheet('Taxes');
  } catch {
    taxes = null;
  }
  let financing = null;
  try {
    financing = await wb.getSheet('Financing');
  } catch {
    financing = null;
  }
  let equity = null;
  try {
    equity = await wb.getSheet('Equity');
  } catch {
    equity = null;
  }
  let otherBalances = null;
  try {
    otherBalances = await wb.getSheet('OtherBalances');
  } catch {
    otherBalances = null;
  }
  let p9Sensitivity = null;
  try {
    p9Sensitivity = await wb.getSheet('P9Sensitivity');
  } catch {
    p9Sensitivity = null;
  }
  const taxModel = Boolean(taxes);
  const financingModel = Boolean(financing);
  const read = async (sheet, address) => sheet.getValue(address);
  const statementRows = async (sheet, startRow, endRow) => {
    const rows = [];
    for (let row = startRow; row <= endRow; row += 1) {
      const values = [];
      for (let index = 0; index < PERIODS.length; index += 1) values.push(await sheet.getValue(periodCell(index, row)));
      rows.push({ row, label: await sheet.getValue(`A${row}`), values });
    }
    return rows;
  };
  const snapshot = {
    stub: {
      revenue: await read(income, 'B6'),
      openingAssetDepreciation: await read(schedules, 'B15'),
      newAdditionDepreciation: await read(schedules, 'B16'),
      totalDepreciation: await read(schedules, 'B17'),
      cashPpePayments: await read(schedules, 'B12'),
      noncashPpeAdditions: await read(schedules, 'B13'),
      recognizedPpeAdditions: await read(schedules, 'B14'),
      ebit: await read(income, 'B11'),
      netIncome: await read(income, 'B15'),
      cfo: await read(cashFlow, taxModel ? 'B12' : 'B9'),
      cashInvesting: await read(cashFlow, taxModel ? 'B14' : 'B11'),
      cashFinancing: await read(cashFlow, taxModel ? 'B15' : 'B12'),
      cashFcf: await read(dcf, 'B9'),
      economicUfcf: await read(dcf, 'B7'),
      closingCash: await read(cashFlow, taxModel ? 'B18' : 'B15'),
      closingNetPpe: await read(bs, 'B11'),
      totalAssets: await read(bs, 'B17'),
      balanceDifference: await read(bs, financingModel ? 'B32' : taxModel ? 'B28' : 'B25'),
    },
    checks: await readPeriodValues(wb, 'Checks', 20),
    enterpriseValue: await read(dcf, 'B18'),
    equityValueBeforeExistingClaim: await read(dcf, 'B22'),
    existingAwardClaim: await read(dcf, 'B26'),
    equityValue: await read(dcf, 'B27'),
    pointShareDenominator: await read(dcf, 'B28'),
    partialPerShareValue: await read(dcf, 'B29'),
    existingAwardClaimBridgeCheck: await read(dcf, 'B30'),
    pointShareDenominatorCheck: await read(dcf, 'B31'),
    partialPerShareArithmeticCheck: await read(dcf, 'B32'),
    dcfStatus: await read(dcf, 'B24'),
    inputStatus: await read(await wb.getSheet('Inputs'), 'B54'),
    contextStatus: await read(checks, 'B23'),
    allPeriodStatus: await read(checks, 'B22'),
    sensitivityCenter: p9Sensitivity ? await read(p9Sensitivity, 'N6') : await read(await wb.getSheet('Sensitivity'), 'C5'),
    annualRevenue: await read(income, 'C6'),
    originalPoolDepreciation: await readPeriodValues(wb, 'AssetCohorts', 11),
    totalDepreciation: await readPeriodValues(wb, 'Schedules', 17),
    formulas: {
      ppe: await schedules.getFormula('B23'),
      income: await income.getFormula('B11'),
      cash: await cashFlow.getFormula(taxModel ? 'B18' : 'B15'),
      dcf: await dcf.getFormula('B7'),
      cashFcf: await dcf.getFormula('B9'),
      sensitivity: await sensitivityFormula(wb),
    },
  };
  snapshot.statements = {
    income: await statementRows(income, 6, 15),
    cashFlow: await statementRows(cashFlow, 6, taxModel ? 18 : 15),
    balanceSheet: await statementRows(bs, 6, financingModel ? 32 : taxModel ? 28 : 25),
  };
  if (financing) {
    snapshot.financingGateStatus = await read(await wb.getSheet('Inputs'), `B${FINANCING_DRIVER_ROWS.gate}`);
    snapshot.p8bOverallChecks = await readPeriodValues(wb, 'Checks', 37);
    snapshot.p8bUfcfBridgeDifferences = await readPeriodValues(wb, 'Checks', 35);
    snapshot.financing = {
      debtOpeningFace: await readPeriodValues(wb, 'Financing', 12),
      debtClosingFace: await readPeriodValues(wb, 'Financing', 13),
      debtCashInterest: await readPeriodValues(wb, 'Financing', 14),
      debtContraRelease: await readPeriodValues(wb, 'Financing', 16),
      debtClosingContra: await readPeriodValues(wb, 'Financing', 17),
      debtBookExpense: await readPeriodValues(wb, 'Financing', 18),
      debtRepayment: await readPeriodValues(wb, 'Financing', 19),
      debtProceeds: await readPeriodValues(wb, 'Financing', 20),
      debtNetCash: await readPeriodValues(wb, 'Financing', 21),
      debtCurrentCarrying: await readPeriodValues(wb, 'Financing', 24),
      debtNoncurrentCarrying: await readPeriodValues(wb, 'Financing', 25),
      operatingLiabilityClosing: await readPeriodValues(wb, 'Financing', 52),
      operatingRouClosing: await readPeriodValues(wb, 'Financing', 54),
      operatingInterest: await readPeriodValues(wb, 'Financing', 62),
      operatingExpense: await readPeriodValues(wb, 'Financing', 64),
      operatingAmortization: await readPeriodValues(wb, 'Financing', 65),
      operatingPrincipal: await readPeriodValues(wb, 'Financing', 68),
      financeLiabilityClosing: await readPeriodValues(wb, 'Financing', 53),
      financePpeClosing: await readPeriodValues(wb, 'Financing', 55),
      financeInterest: await readPeriodValues(wb, 'Financing', 63),
      financePrincipal: await readPeriodValues(wb, 'Financing', 67),
      financeDepreciation: await readPeriodValues(wb, 'Financing', 66),
      operatingPayment: await readPeriodValues(wb, 'Financing', 56),
      financePayment: await readPeriodValues(wb, 'Financing', 57),
      financeAdditions: await readPeriodValues(wb, 'Financing', 49),
      currentOperatingLiability: await readPeriodValues(wb, 'Financing', 69),
      noncurrentOperatingLiability: await readPeriodValues(wb, 'Financing', 70),
      currentFinanceLiability: await readPeriodValues(wb, 'Financing', 71),
      noncurrentFinanceLiability: await readPeriodValues(wb, 'Financing', 72),
      fundingStatus: await readPeriodValues(wb, 'Financing', 73),
      calibrationStatus: await readPeriodValues(wb, 'Financing', 74),
      formulas: {
        debt: await financing.getFormula('B13'),
        debtInterest: await financing.getFormula('B14'),
        operatingLiability: await financing.getFormula('B52'),
        financeAsset: await financing.getFormula('B55'),
      },
    };
  }
  if (equity) {
    const e = P8C_DRIVER_ROWS;
    snapshot.equityGateStatus = await read(await wb.getSheet('Inputs'), `B${e.gate}`);
    snapshot.equity = {
      bookSbc: await readPeriodValues(wb, 'Inputs', e.bookSbc),
      existingServiceCost: await readPeriodValues(wb, 'Inputs', e.existingServiceCost),
      newSbc: await readPeriodValues(wb, 'Inputs', e.newSbc),
      grossExistingUnits: await readPeriodValues(wb, 'Inputs', e.grossExistingUnits),
      grossNewUnits: await readPeriodValues(wb, 'Inputs', e.grossNewUnits),
      withheldUnits: await readPeriodValues(wb, 'Inputs', e.withheldUnits),
      netDeliveredUnits: await readPeriodValues(wb, 'Inputs', e.netDeliveredUnits),
      cashIssuance: await readPeriodValues(wb, 'Inputs', e.cashIssuance),
      programCash: await readPeriodValues(wb, 'Inputs', e.programCash),
      programUnits: await readPeriodValues(wb, 'Inputs', e.programUnits),
      programApicBasis: await readPeriodValues(wb, 'Inputs', e.programApicBasis),
      dividendDeclaration: await readPeriodValues(wb, 'Inputs', e.dividendDeclaration),
      dividendPayableOpening: await readPeriodValues(wb, 'Inputs', e.dividendPayableOpening),
      dividendPayableClosing: await readPeriodValues(wb, 'Inputs', e.dividendPayableClosing),
      dividendCashPaid: await readPeriodValues(wb, 'Inputs', e.dividendCashPaid),
      pointSharesOpening: await readPeriodValues(wb, 'Inputs', e.pointSharesOpening),
      pointSharesClosing: await readPeriodValues(wb, 'Inputs', e.pointSharesClosing),
      basicWeightedShares: await readPeriodValues(wb, 'Inputs', e.basicWeightedShares),
      dilutedIncrement: await readPeriodValues(wb, 'Inputs', e.dilutedIncrement),
      basicEps: await readPeriodValues(wb, 'Inputs', e.basicEps),
      dilutedEps: await readPeriodValues(wb, 'Inputs', e.dilutedEps),
      valuationEbit: await readPeriodValues(wb, 'Inputs', e.valuationEbit),
      normalizedTax: await readPeriodValues(wb, 'Inputs', e.normalizedTax),
      valuationUfcf: await readPeriodValues(wb, 'Inputs', e.valuationUfcf),
      cfoUfcf: await readPeriodValues(wb, 'Inputs', e.cfoUfcf),
      withholdingCash: await readPeriodValues(wb, 'Inputs', e.withholdingCash),
      apicClosing: await readPeriodValues(wb, 'Inputs', e.apicClosing),
      retainedEarningsClosing: await readPeriodValues(wb, 'Inputs', e.retainedEarningsClosing),
      aociClosing: await readPeriodValues(wb, 'Inputs', e.aociClosing),
      totalEquity: await readPeriodValues(wb, 'Inputs', e.totalEquity),
      authorizationRemaining: await readPeriodValues(wb, 'Inputs', e.authorizationRemaining),
      serviceDays: await readPeriodValues(wb, 'Inputs', e.serviceDays),
      totalServiceDays: await read(await wb.getSheet('Inputs'), `B${e.totalServiceDays}`),
      existingClaim: await read(equity, 'B40'),
      formulas: {
        ufcf: await equity.getFormula('B32'),
        pointShares: await equity.getFormula('B25'),
        equityClaim: await equity.getFormula('B40'),
        dcfClaim: await dcf.getFormula('B26'),
        dcfPartialEquity: await dcf.getFormula('B27'),
        dcfPointShares: await dcf.getFormula('B28'),
        dcfPartialPerShare: await dcf.getFormula('B29'),
      },
    };
    snapshot.p8cOverallChecks = await readPeriodValues(wb, 'Checks', Boolean(financing) ? 47 : 33);
  }
  if (taxes) {
    const taxInputs = await wb.getSheet('Inputs');
    snapshot.taxGateStatus = await read(taxInputs, `B${TAX_DRIVER_ROWS.gate}`);
    snapshot.tax = {
      currentTaxPayableMethod: await read(taxInputs, `B${TAX_DRIVER_ROWS.currentTaxPayableMethod}`),
      currentTaxPayableDays: await read(taxInputs, `B${TAX_DRIVER_ROWS.currentTaxPayableDays}`),
      periodDays: await readPeriodValues(wb, 'Inputs', TAX_DRIVER_ROWS.periodDays),
      ebit: await readPeriodValues(wb, 'Taxes', 6),
      interestExpense: await readPeriodValues(wb, 'Taxes', 7),
      pretaxIncome: await readPeriodValues(wb, 'Taxes', 8),
      bookTaxExpense: await readPeriodValues(wb, 'Taxes', 11),
      deferredTaxExpense: await readPeriodValues(wb, 'Taxes', 13),
      currentTaxExpense: await readPeriodValues(wb, 'Taxes', 14),
      currentTaxPayment: await readPeriodValues(wb, 'Taxes', 17),
      currentTaxPayableOpening: await readPeriodValues(wb, 'Taxes', 15),
      currentTaxPayableClosing: await readPeriodValues(wb, 'Taxes', 16),
      longTermTaxSettlement: await readPeriodValues(wb, 'Taxes', 19),
      longTermTaxLiabilityClosing: await readPeriodValues(wb, 'Taxes', 20),
      deferredTaxLiabilityClosing: await readPeriodValues(wb, 'Taxes', 22),
      taxCfoAdjustment: await readPeriodValues(wb, 'Taxes', 26),
      modeledCompanyCashTaxes: await readPeriodValues(wb, 'Taxes', 27),
      modeledCompanyCashTaxesMeaning: 'Forecast-period company cash payments from current-tax payment plus long-term-tax settlement under selected provisional assumptions; distinct from historical reported cash-tax disclosures and normalized operating taxes.',
      operatingTaxRate: await readPeriodValues(wb, 'Taxes', 28),
      operatingTaxExpense: await readPeriodValues(wb, 'Taxes', 29),
      status: await readPeriodValues(wb, 'Taxes', 30),
      formulas: {
        book: await taxes.getFormula('B11'),
        currentPayableClosing: await taxes.getFormula('B16'),
        currentPayment: await taxes.getFormula('B17'),
        deferredLiability: await taxes.getFormula('B22'),
        operatingTax: await taxes.getFormula('B29'),
      },
    };
  }
  if (operating) {
    snapshot.operatingBridge = {
      segmentRevenue: Object.fromEntries(await Promise.all(OPERATING_SEGMENTS.map(async (segment, index) => [segment, await readPeriodValues(wb, 'Operating', 6 + index)]))),
      costs: Object.fromEntries(await Promise.all(['cost_of_revenue', 'research_and_development', 'sales_and_marketing', 'general_and_administrative'].map(async (line, index) => [line, await readPeriodValues(wb, 'Operating', 13 + index)]))),
      grossCosts: await readPeriodValues(wb, 'Operating', 17),
      embeddedPpeRemoved: await readPeriodValues(wb, 'Operating', 18),
      scheduledPpeAdded: await readPeriodValues(wb, 'Operating', 19),
      totalOperatingExpenses: await readPeriodValues(wb, 'Operating', 20),
      costsExcludingEmbeddedPpe: await readPeriodValues(wb, 'Operating', 21),
      grossCostRatio: await readPeriodValues(wb, 'Operating', 22),
      operatingMargin: await readPeriodValues(wb, 'Operating', 23),
      formulas: {
        segments: Object.fromEntries(await Promise.all(OPERATING_SEGMENTS.map(async (segment, index) => [segment, [await operating.getFormula('B' + (6 + index)), await operating.getFormula('C' + (6 + index))]]))),
        costs: Object.fromEntries(await Promise.all(['cost_of_revenue', 'research_and_development', 'sales_and_marketing', 'general_and_administrative'].map(async (line, index) => [line, await operating.getFormula('B' + (13 + index))]))),
        total: await operating.getFormula('B20'),
        excludingEmbedded: await operating.getFormula('B21'),
        margin: await operating.getFormula('B23'),
      },
    };
    snapshot.p6DriverStatus = await read(await wb.getSheet('Inputs'), 'B78');
    snapshot.combinedDecisionStatus = await read(await wb.getSheet('Decisions'), 'B28');
    snapshot.operatingForecast = {
      segments: snapshot.operatingBridge.segmentRevenue,
      consolidatedRevenue: await readPeriodValues(wb, 'Operating', 11),
      costs: snapshot.operatingBridge.costs,
      grossCosts: snapshot.operatingBridge.grossCosts,
      embeddedPpeRemoved: snapshot.operatingBridge.embeddedPpeRemoved,
      scheduledPpeAdded: snapshot.operatingBridge.scheduledPpeAdded,
      totalOperatingExpenses: snapshot.operatingBridge.totalOperatingExpenses,
    };
  }
  if (workingCapital) {
    const inputSheet = await wb.getSheet('Inputs');
    snapshot.p7DriverStatus = await read(inputSheet, `B${P7_DRIVER_ROWS.gate}`);
    snapshot.accruedCompensationDriver = {
      sourceBaseline: await read(inputSheet, `B${P7_DRIVER_ROWS.accruedCompensationBaseline}`),
      multiplier: await read(inputSheet, `B${P7_DRIVER_ROWS.accruedCompensationMultiplier}`),
      effectiveRatio: await read(inputSheet, `B${P7_DRIVER_ROWS.accruedCompensationEffectiveRatio}`),
      units: {
        sourceBaseline: 'ratio of USD millions accrued compensation to USD millions TTM revenue',
        multiplier: 'dimensionless',
        effectiveRatio: 'ratio of USD millions accrued compensation to USD millions revenue',
      },
    };
    snapshot.workingCapital = {
      revenue: await readPeriodValues(wb, 'WorkingCapital', 6),
      costOfRevenue: await readPeriodValues(wb, 'WorkingCapital', 7),
      periodDays: await readPeriodValues(wb, 'WorkingCapital', 8),
      currentArOpening: await readPeriodValues(wb, 'WorkingCapital', 9),
      currentArClosing: await readPeriodValues(wb, 'WorkingCapital', 10),
      inventoryOpening: await readPeriodValues(wb, 'WorkingCapital', 12),
      inventoryClosing: await readPeriodValues(wb, 'WorkingCapital', 13),
      operatingApOpening: await readPeriodValues(wb, 'WorkingCapital', 15),
      operatingApClosing: await readPeriodValues(wb, 'WorkingCapital', 16),
      longTermArClosing: await readPeriodValues(wb, 'WorkingCapital', 19),
      serverReceivablesClosing: await readPeriodValues(wb, 'WorkingCapital', 22),
      otherOcaClosing: await readPeriodValues(wb, 'WorkingCapital', 25),
      accruedCompensationClosing: await readPeriodValues(wb, 'WorkingCapital', 28),
      contractLiabilityOpening: await readPeriodValues(wb, 'WorkingCapital', 30),
      contractRecognition: await readPeriodValues(wb, 'WorkingCapital', 31),
      contractBillings: await readPeriodValues(wb, 'WorkingCapital', 32),
      contractLiabilityClosing: await readPeriodValues(wb, 'WorkingCapital', 33),
      currentContractPresentation: await readPeriodValues(wb, 'WorkingCapital', 35),
      noncurrentContractPresentation: await readPeriodValues(wb, 'WorkingCapital', 36),
      otherOclClosing: await readPeriodValues(wb, 'WorkingCapital', 38),
      conventionalCurrentNwc: await readPeriodValues(wb, 'WorkingCapital', 40),
      cashConversionNwc: await readPeriodValues(wb, 'WorkingCapital', 41),
      cashConversionNwcChange: await readPeriodValues(wb, 'WorkingCapital', 42),
      cfoContribution: await readPeriodValues(wb, 'WorkingCapital', 43),
      formulas: { currentAr: await (await wb.getSheet('WorkingCapital')).getFormula('B10'), contract: await (await wb.getSheet('WorkingCapital')).getFormula('B33'), nwc: await (await wb.getSheet('WorkingCapital')).getFormula('B42') },
    };
    snapshot.combinedDecisionStatus = await read(await wb.getSheet('Decisions'), 'B28');
  }
  if (otherBalances) {
    const d = P8D_OUTPUT_ROWS;
    snapshot.otherBalancesGateStatus = await read(await wb.getSheet('Inputs'), `B${P8D_DRIVER_ROWS.gate}`);
    snapshot.otherBalances = {
      periodDays: await readPeriodValues(wb, 'Inputs', P8D_DRIVER_ROWS.periodDays),
      eligibleNoncashPool: Number(await read(inputs, `B${P8D_DRIVER_ROWS.openingShortTermInvestments}`))
        + Number(await read(inputs, `B${P8D_DRIVER_ROWS.identifiedLongTermDebtInvestments}`))
        + Number(await read(inputs, `B${P8D_DRIVER_ROWS.openingFinancingReceivables}`)),
      cashIncomeYield: await read(inputs, `B${P8D_DRIVER_ROWS.cashIncomeYield}`),
      actualOpeningCash: [await read(inputs, `B${P8D_DRIVER_ROWS.openingCash}`), ...(await readPeriodValues(wb, 'CashFlow', taxModel ? 18 : 15)).slice(0, -1)],
      actualClosingCash: await readPeriodValues(wb, 'CashFlow', taxModel ? 18 : 15),
      investmentOpening: await readPeriodValues(wb, 'OtherBalances', d.investmentOpening),
      investmentAdditions: await readPeriodValues(wb, 'OtherBalances', d.investmentAdditions),
      cashIncome: await readPeriodValues(wb, 'OtherBalances', d.cashIncome),
      noncashGain: await readPeriodValues(wb, 'OtherBalances', d.noncashGain),
      investmentClosing: await readPeriodValues(wb, 'OtherBalances', d.investmentClosing),
      investmentValue: await readPeriodValues(wb, 'OtherBalances', d.investmentValue),
      embeddedAmortizationRemoved: await readPeriodValues(wb, 'OtherBalances', d.embeddedAmortizationRemoved),
      intangibleOpening: await readPeriodValues(wb, 'OtherBalances', d.intangibleOpening),
      intangibleAmortization: await readPeriodValues(wb, 'OtherBalances', d.intangibleAmortization),
      intangibleClosing: await readPeriodValues(wb, 'OtherBalances', d.intangibleClosing),
      goodwillOpening: await readPeriodValues(wb, 'OtherBalances', d.goodwillOpening),
      goodwillImpairment: await readPeriodValues(wb, 'OtherBalances', d.goodwillImpairment),
      goodwillClosing: await readPeriodValues(wb, 'OtherBalances', d.goodwillClosing),
      dtaValue: await readPeriodValues(wb, 'OtherBalances', d.dtaValue),
      commitmentFunding: await readPeriodValues(wb, 'OtherBalances', d.commitmentFunding),
      commitmentRightsValue: await readPeriodValues(wb, 'OtherBalances', d.commitmentRightsValue),
      commitmentNetMeasurementAdjustment: await readPeriodValues(wb, 'OtherBalances', d.commitmentNetMeasurementAdjustment),
      fundingStatus: await readPeriodValues(wb, 'OtherBalances', d.fundingStatus),
      residualMovementDifference: await readPeriodValues(wb, 'OtherBalances', d.residualMovementDifference),
      coverage: await readPeriodValues(wb, 'OtherBalances', d.coverage),
      formulas: {
        investment: await otherBalances.getFormula('B10'),
        intangible: await otherBalances.getFormula('B15'),
        goodwill: await otherBalances.getFormula('B18'),
        value: await otherBalances.getFormula('B11'),
        cashIncome: await otherBalances.getFormula('B8'),
      },
    };
    snapshot.combinedDecisionStatus = await read(await wb.getSheet('Decisions'), 'B28');
  }
  const finalColumn = periodColumn(PERIODS.length - 1);
  const finalNetPpe = await read(bs, `${finalColumn}11`);
  const finalFinancePpe = financing ? await read(financing, `${finalColumn}55`) : null;
  snapshot.periodEnd = {
    periodId: PERIODS[PERIODS.length - 1].id,
    revenue: await read(income, `${finalColumn}6`),
    ebit: await read(income, `${finalColumn}11`),
    economicUfcf: await read(dcf, `${finalColumn}7`),
    netPpe: finalNetPpe,
    ownedPpe: financing ? Number(finalNetPpe) - Number(finalFinancePpe) : finalNetPpe,
    financePpe: finalFinancePpe,
    cashConversionNwc: workingCapital ? await read(workingCapital, `${finalColumn}41`) : null,
    remainingIntangibles: otherBalances ? await read(otherBalances, `${finalColumn}${P8D_OUTPUT_ROWS.intangibleClosing}`) : null,
    incrementalNetDtaValue: otherBalances ? await read(otherBalances, `${finalColumn}${P8D_OUTPUT_ROWS.dtaValue}`) : null,
    currentTaxPayable: taxes ? await read(taxes, `${finalColumn}16`) : null,
    longTermTaxLiability: taxes ? await read(taxes, `${finalColumn}20`) : null,
    deferredTaxLiability: taxes ? await read(taxes, `${finalColumn}22`) : null,
  };
  if (otherBalances) {
    try {
      snapshot.p9 = await readP9Snapshot(wb);
    } catch {
      snapshot.p9 = null;
    }
  }
  return snapshot;
}

async function sensitivityFormula(wb) {
  try {
    const p9 = await wb.getSheet('P9Sensitivity');
    return p9.getFormula('N6');
  } catch {
    // Earlier packages use the asset-slice sensitivity sheet.
  }
  const sheet = await wb.getSheet('Sensitivity');
  return sheet.getFormula('B4');
}

export async function inspectAssetWorkbook(path, { allowSensitivityCenterDrift = false } = {}) {
  const wb = await createWorkbook(path, { userTimezone: 'UTC' });
  try {
    const snapshot = await readSnapshot(wb);
    const equitySheet = snapshot.equity ? await wb.getSheet('Equity') : null;
    const bs = await wb.getSheet('BalanceSheet');
    if (snapshot.checks.some((value) => value !== 'PASS')) throw new Error(`P5 checks failed: ${JSON.stringify(snapshot.checks)}`);
    if (Math.abs(Number(snapshot.stub.balanceDifference)) > TOLERANCE) throw new Error(`P5 stub balance failed: ${snapshot.stub.balanceDifference}`);
    if (snapshot.allPeriodStatus !== 'PASS') throw new Error('P5 global mechanical/input gate failed');
    if (Math.abs(Number(snapshot.stub.recognizedPpeAdditions) - Number(snapshot.stub.cashPpePayments) - Number(snapshot.stub.noncashPpeAdditions)) > TOLERANCE) throw new Error('P5 recognized additions do not tie cash plus noncash');
    const expectedCashFcf = Number(snapshot.stub.cfo) - Number(snapshot.stub.cashPpePayments);
    if (Math.abs(Number(snapshot.stub.cashFcf) - expectedCashFcf) > TOLERANCE) throw new Error('Cash FCF must equal CFO less cash PP&E payments');
    if (!snapshot.p9 && !allowSensitivityCenterDrift && Math.abs(Number(snapshot.enterpriseValue) - Number(snapshot.sensitivityCenter)) > TOLERANCE) throw new Error('P5 sensitivity center does not tie base EV');
    if (snapshot.operatingBridge) {
      if (snapshot.p6DriverStatus !== 'PASS') throw new Error(`P6 driver input gate failed: ${snapshot.p6DriverStatus}`);
      if (!snapshot.workingCapital && snapshot.combinedDecisionStatus === 'SYSTEM_REVIEWED_PROVISIONAL') throw new Error('P6 combined status incorrectly claims system review');
      for (const [segment, formulas] of Object.entries(snapshot.operatingBridge.formulas.segments)) {
        if (!formulas[0] || !formulas[1]) throw new Error(`P6 segment formula missing for ${segment}`);
      }
      for (const [line, formula] of Object.entries(snapshot.operatingBridge.formulas.costs)) {
        if (!formula) throw new Error(`P6 cost formula missing for ${line}`);
      }
      for (let index = 0; index < PERIODS.length; index += 1) {
        const gross = Number(snapshot.operatingBridge.grossCosts[index]);
        const embedded = Number(snapshot.operatingBridge.embeddedPpeRemoved[index]);
        const scheduled = Number(snapshot.operatingBridge.scheduledPpeAdded[index]);
        const total = Number(snapshot.operatingBridge.totalOperatingExpenses[index]);
        const excluding = Number(snapshot.operatingBridge.costsExcludingEmbeddedPpe[index]);
        if (Math.abs(gross - embedded + scheduled - total) > TOLERANCE) throw new Error(`P6 operating bridge failed in period ${index}`);
        if (Math.abs(gross - embedded - excluding) > TOLERANCE) throw new Error(`P6 embedded-cost removal failed in period ${index}`);
      }
    }
    if (snapshot.workingCapital) {
      if (snapshot.p7DriverStatus !== 'PASS') throw new Error(`P7 driver input gate failed: ${snapshot.p7DriverStatus}`);
      const wc = snapshot.workingCapital;
      if (!wc.formulas.currentAr || !wc.formulas.contract || !wc.formulas.nwc) throw new Error('P7 working-capital formula missing');
      for (let index = 0; index < PERIODS.length; index += 1) {
        if (!Number.isFinite(Number(wc.cashConversionNwc[index])) || !Number.isFinite(Number(wc.cashConversionNwcChange[index]))) throw new Error(`P7 NWC is nonnumeric in period ${index}`);
        if (Math.abs(Number(wc.cfoContribution[index]) + Number(wc.cashConversionNwcChange[index])) > TOLERANCE) throw new Error(`P7 CFO sign bridge failed in period ${index}`);
        if (Number(wc.contractLiabilityClosing[index]) < -TOLERANCE) throw new Error(`P7 negative contract liability in period ${index}`);
        if (Math.abs(Number(wc.currentContractPresentation[index]) + Number(wc.noncurrentContractPresentation[index]) - Number(wc.contractLiabilityClosing[index])) > TOLERANCE) throw new Error(`P7 current/noncurrent contract presentation failed in period ${index}`);
      }
    }
    if (snapshot.tax) {
      if (snapshot.taxGateStatus !== 'PASS') throw new Error(`P8A tax input gate failed: ${snapshot.taxGateStatus}`);
      const tax = snapshot.tax;
      const schedules = await wb.getSheet('Schedules');
      const cashFlow = await wb.getSheet('CashFlow');
      if (!tax.formulas.book || !tax.formulas.currentPayment || !tax.formulas.deferredLiability || !tax.formulas.operatingTax) throw new Error('P8A tax formula missing');
      const financingSheet = snapshot.financing ? await wb.getSheet('Financing') : null;
      for (let index = 0; index < PERIODS.length; index += 1) {
        if (tax.status[index] !== 'PASS') throw new Error(`P8A tax period failed in period ${index}`);
        const expectedCfo = Number(await (await wb.getSheet('Income')).getValue(`${periodColumn(index)}15`))
          + Number(await schedules.getValue(`${periodColumn(index)}17`))
          + (financingSheet ? Number(await financingSheet.getValue(`${periodColumn(index)}65`)) + Number(await financingSheet.getValue(`${periodColumn(index)}16`)) - Number(await financingSheet.getValue(`${periodColumn(index)}68`)) : 0)
          + Number(tax.deferredTaxExpense[index])
          + Number(tax.currentTaxPayableClosing[index]) - Number(tax.currentTaxPayableOpening[index])
          - Number(tax.longTermTaxSettlement[index])
          + (equitySheet ? Number(await equitySheet.getValue(`${periodColumn(index)}6`)) : 0)
          + (snapshot.otherBalances ? Number(snapshot.otherBalances.intangibleAmortization[index]) + Number(snapshot.otherBalances.goodwillImpairment[index]) - Number(snapshot.otherBalances.noncashGain[index]) : 0)
          - Number(await (await wb.getSheet('WorkingCapital')).getValue(`${periodColumn(index)}42`));
        const actualCfo = Number(await cashFlow.getValue(`${periodColumn(index)}12`));
        if (Math.abs(actualCfo - expectedCfo) > TOLERANCE) throw new Error(`P8A CFO tax bridge failed in period ${index}`);
        if (Math.abs(Number(tax.currentTaxPayment[index]) + Number(tax.currentTaxPayableClosing[index]) - Number(tax.currentTaxPayableOpening[index]) - Number(tax.currentTaxExpense[index])) > TOLERANCE) throw new Error(`P8A current tax cash bridge failed in period ${index}`);
      }
    }
    if (snapshot.financing) {
      if (snapshot.financingGateStatus !== 'PASS') throw new Error(`P8B financing input gate failed: ${snapshot.financingGateStatus}`);
      const f = snapshot.financing;
      const financingSheet = await wb.getSheet('Financing');
      if (!f.formulas.debt || !f.formulas.debtInterest || !f.formulas.operatingLiability || !f.formulas.financeAsset) throw new Error('P8B financing formula missing');
      for (let index = 0; index < PERIODS.length; index += 1) {
        const checks = [
          ['debt face', Number(f.debtClosingFace[index]) - Number(f.debtOpeningFace[index]) - Number(f.debtProceeds[index]) + Number(f.debtRepayment[index])],
          ['debt carrying', Number(f.debtClosingFace[index]) + Number(f.debtClosingContra[index]) - Number(f.debtCurrentCarrying[index]) - Number(f.debtNoncurrentCarrying[index])],
          ['operating liability', Number(f.operatingLiabilityClosing[index]) - (Number(await financingSheet.getValue(`${periodColumn(index)}29`)) + Number(f.operatingInterest[index]) - Number(f.operatingPayment[index]) + Number(await financingSheet.getValue(`${periodColumn(index)}48`)))],
          ['finance asset', Number(f.financePpeClosing[index]) - (Number(await financingSheet.getValue(index === 0 ? `${periodColumn(index)}44` : `${periodColumn(index - 1)}55`)) + Number(await financingSheet.getValue(`${periodColumn(index)}49`)) - Number(f.financeDepreciation[index]))],
        ];
        for (const [label, difference] of checks) if (Math.abs(difference) > TOLERANCE) throw new Error(`P8B ${label} bridge failed in period ${index}: ${difference}`);
        if (f.fundingStatus[index] !== 'OK' && f.fundingStatus[index] !== 'UNFUNDED') throw new Error(`P8B funding state invalid in period ${index}`);
        if (f.calibrationStatus[index] !== 'PASS') throw new Error(`P8B opening-pool status failed in period ${index}`);
      }
      if (snapshot.p8bOverallChecks.some((value) => value !== 'PASS')) throw new Error(`P8B overall checks failed: ${JSON.stringify(snapshot.p8bOverallChecks)}`);
      if (snapshot.p8bUfcfBridgeDifferences.some((value) => Math.abs(Number(value)) > TOLERANCE)) throw new Error(`P8B CFO/EBIT UFCF bridge failed: ${JSON.stringify(snapshot.p8bUfcfBridgeDifferences)}`);
    }
    if (snapshot.equity) {
      if (snapshot.equityGateStatus !== 'PASS') throw new Error(`P8C equity input gate failed: ${snapshot.equityGateStatus}`);
      const e = snapshot.equity;
      if (!e.formulas.ufcf || !e.formulas.pointShares) throw new Error('P8C equity formula missing');
      const dcf = await wb.getSheet('DCF');
      const claimFormula = String(await dcf.getFormula('B26'));
      const postClaimFormula = String(await dcf.getFormula('B27'));
      const pointShareFormula = String(await dcf.getFormula('B28'));
      const perShareFormula = String(await dcf.getFormula('B29'));
      if (e.formulas.equityClaim !== '=Inputs!$B$173*Inputs!$B$176') throw new Error(`P8C authoritative Equity!B40 claim formula changed: ${e.formulas.equityClaim}`);
      if (claimFormula !== '=Equity!B40') throw new Error(`P8C existing-award claim is not linked to Equity!B40: ${claimFormula}`);
      if (Math.abs(Number(snapshot.existingAwardClaim) - Number(e.existingClaim)) > TOLERANCE) throw new Error('P8C displayed claim does not tie Equity!B40');
      if (snapshot.p9) {
        if (postClaimFormula !== '=Valuation!B121' || pointShareFormula !== '=Valuation!B18' || perShareFormula !== '=Valuation!B122') throw new Error('P9 canonical DCF front is disconnected');
        if (snapshot.existingAwardClaimBridgeCheck !== 'PASS' || snapshot.pointShareDenominatorCheck !== 'PASS' || snapshot.partialPerShareArithmeticCheck !== 'PASS') throw new Error('P9 canonical DCF front checks failed');
        if (Math.abs(Number(snapshot.equityValue) - Number(snapshot.p9.commonEquityValue)) > TOLERANCE || Math.abs(Number(snapshot.partialPerShareValue) - Number(snapshot.p9.perShareValue)) > TOLERANCE) throw new Error('P9 canonical DCF front values do not tie Valuation');
      } else {
        if ((postClaimFormula.match(/B26/g) ?? []).length !== 1 || !postClaimFormula.includes('B22')) throw new Error(`P8C existing-award claim deduction is missing or duplicated: ${postClaimFormula}`);
        if (pointShareFormula !== '=Inputs!$B$227') throw new Error(`P8C point-share denominator is not the measurement-date input: ${pointShareFormula}`);
        if ((pointShareFormula.match(/B173|B190|B205|B206|B207/g) ?? []).length > 0) throw new Error(`P8C point-share denominator includes forecast award/share rows: ${pointShareFormula}`);
        if ((perShareFormula.match(/B27/g) ?? []).length !== 1 || (perShareFormula.match(/B28/g) ?? []).length !== 1) throw new Error(`P8C partial per-share formula is disconnected: ${perShareFormula}`);
        if (snapshot.existingAwardClaimBridgeCheck !== 'PASS') throw new Error(`P8C existing-award claim bridge check failed: ${snapshot.existingAwardClaimBridgeCheck}`);
        if (snapshot.pointShareDenominatorCheck !== 'PASS') throw new Error(`P8C point-share denominator check failed: ${snapshot.pointShareDenominatorCheck}`);
        if (snapshot.partialPerShareArithmeticCheck !== 'PASS') throw new Error(`P8C partial per-share arithmetic check failed: ${snapshot.partialPerShareArithmeticCheck}`);
        if (Math.abs(Number(snapshot.equityValue) - (Number(snapshot.equityValueBeforeExistingClaim) - Number(snapshot.existingAwardClaim))) > TOLERANCE) throw new Error('P8C displayed partial equity bridge does not deduct the claim exactly once');
        if (Math.abs(Number(snapshot.pointShareDenominator) - 7429) > TOLERANCE) throw new Error('P8C partial point-share denominator is not the 7429m measurement-date balance');
        if (Math.abs(Number(snapshot.partialPerShareValue) * Number(snapshot.pointShareDenominator) - Number(snapshot.equityValue)) > TOLERANCE) throw new Error('P8C partial per-share diagnostic does not tie the displayed bridge');
      }
      for (let index = 0; index < PERIODS.length; index += 1) {
        if (Number(e.newSbc[index]) < -TOLERANCE) throw new Error(`P8C negative new compensation in period ${index}`);
        if (Number(e.pointSharesClosing[index]) < -TOLERANCE || Number(e.basicWeightedShares[index]) <= 0) throw new Error(`P8C share denominator invalid in period ${index}`);
        if (Math.abs(Number(e.bookSbc[index]) - Number(e.existingServiceCost[index]) - Number(e.newSbc[index])) > TOLERANCE) throw new Error(`P8C SBC bridge failed in period ${index}`);
        if (Math.abs(Number(e.valuationUfcf[index]) - Number(e.cfoUfcf[index])) > TOLERANCE) throw new Error(`P8C CFO/EBIT UFCF bridge failed in period ${index}`);
        if (Math.abs(Number(e.totalEquity[index]) - Number(e.apicClosing[index]) - Number(e.retainedEarningsClosing[index]) - Number(e.aociClosing[index])) > TOLERANCE) throw new Error(`P8C equity components failed in period ${index}`);
      }
      if (Math.abs(e.serviceDays.reduce((sum, value) => sum + Number(value), 0) - Number(e.totalServiceDays)) > TOLERANCE) throw new Error('P8C service calendar does not fully run off');
      const inputs = await wb.getSheet('Inputs');
      const totalCost = e.existingServiceCost.reduce((sum, value) => sum + Number(value), 0);
      const totalUnits = e.grossExistingUnits.reduce((sum, value) => sum + Number(value), 0);
      if (Math.abs(totalCost - Number(await inputs.getValue(`B${P8C_DRIVER_ROWS.existingUnrecognizedCost}`))) > TOLERANCE) throw new Error('P8C existing service cost does not fully run off');
      if (Math.abs(totalUnits - Number(await inputs.getValue(`B${P8C_DRIVER_ROWS.existingAwardUnits}`))) > TOLERANCE) throw new Error('P8C existing award units do not fully run off');
      for (let index = 0; index < PERIODS.length; index += 1) {
        if (Number(e.serviceDays[index]) <= TOLERANCE && (Math.abs(Number(e.existingServiceCost[index])) > TOLERANCE || Math.abs(Number(e.grossExistingUnits[index])) > TOLERANCE || Math.abs(Number(e.dilutedIncrement[index])) > TOLERANCE)) throw new Error(`P8C service tail remains in period ${index}`);
      }
      if (snapshot.p8cOverallChecks.some((value) => value !== 'PASS')) throw new Error(`P8C overall checks failed: ${JSON.stringify(snapshot.p8cOverallChecks)}`);
    }
    if (snapshot.otherBalances) {
      if (snapshot.otherBalancesGateStatus !== 'PASS') throw new Error(`P8D input gate failed: ${snapshot.otherBalancesGateStatus}`);
      const d = snapshot.otherBalances;
      if (!d.formulas.investment || !d.formulas.intangible || !d.formulas.goodwill) throw new Error('P8D formula missing');
      for (let index = 0; index < PERIODS.length; index += 1) {
        if (d.coverage[index] !== 'PASS') throw new Error(`P8D coverage failed in period ${index}`);
        if (Math.abs(Number(d.investmentClosing[index]) - Number(d.investmentOpening[index]) - Number(d.investmentAdditions[index]) - Number(d.noncashGain[index])) > TOLERANCE) throw new Error(`P8D investment movement failed in period ${index}`);
        if (Math.abs(Number(d.intangibleClosing[index]) - Number(d.intangibleOpening[index]) + Number(d.intangibleAmortization[index])) > TOLERANCE) throw new Error(`P8D intangible movement failed in period ${index}`);
        if (Math.abs(Number(d.goodwillClosing[index]) - Number(d.goodwillOpening[index]) + Number(d.goodwillImpairment[index])) > TOLERANCE) throw new Error(`P8D goodwill movement failed in period ${index}`);
      }
      const p8dInputs = await wb.getSheet('Inputs');
      const selectedTail = Number(await p8dInputs.getValue(`B${P8D_DRIVER_ROWS.intangibleTailLifeYears}`));
      const tailPool = Number(await p8dInputs.getValue(`B${P8D_DRIVER_ROWS.intangibleTailPool}`));
      const expectedRemaining = tailPool * Math.max(selectedTail - 6, 0) / selectedTail;
      if (Math.abs(Number(d.intangibleClosing[10]) - expectedRemaining) > 1e-6) throw new Error(`P8D FY2036 intangible closing does not tie selected tail: ${d.intangibleClosing[10]}`);
      const unfundedCommitment = Number(await p8dInputs.getValue(`B${P8D_DRIVER_ROWS.unfundedCommitment}`));
      if (Math.abs(Number(d.investmentAdditions[0]) - unfundedCommitment) > TOLERANCE || d.investmentAdditions.slice(1).some((value) => Math.abs(Number(value)) > TOLERANCE)) throw new Error('P8D commitment funding is not a one-time stub addition');
      if (Math.abs(Number(d.commitmentFunding[0]) + unfundedCommitment) > TOLERANCE || d.commitmentFunding.slice(1).some((value) => Math.abs(Number(value)) > TOLERANCE)) throw new Error('P8D commitment CFI is not a one-time negative funding flow');
      const balanceDifferenceRow = snapshot.financing ? 32 : snapshot.tax ? 28 : 25;
      const cashFlow = await wb.getSheet('CashFlow');
      const cashOpeningRow = snapshot.tax ? 17 : 14;
      const cashClosingRow = snapshot.tax ? 18 : 15;
      for (let index = 0; index < PERIODS.length; index += 1) {
        const actualBalanceDifference = Number(await bs.getValue(`${periodColumn(index)}${balanceDifferenceRow}`));
        if (Math.abs(Number(d.residualMovementDifference[index]) - actualBalanceDifference) > TOLERANCE) throw new Error(`P8D residual movement is not sourced from the actual balance sheet in period ${index}`);
        const actualOpeningCash = Number(d.actualOpeningCash[index]);
        const cashFlowOpeningCash = Number(await cashFlow.getValue(`${periodColumn(index)}${cashOpeningRow}`));
        const actualClosingCash = Number(await cashFlow.getValue(`${periodColumn(index)}${cashClosingRow}`));
        if (Math.abs(Number(d.actualClosingCash[index]) - actualClosingCash) > TOLERANCE) throw new Error(`P8D cash snapshot is not sourced from CashFlow in period ${index}`);
        const expectedOpeningCash = index === 0 ? Number(await p8dInputs.getValue(`B${P8D_DRIVER_ROWS.openingCash}`)) : Number(d.actualClosingCash[index - 1]);
        if (Math.abs(actualOpeningCash - expectedOpeningCash) > TOLERANCE) throw new Error(`P8D actual opening cash does not roll from prior CashFlow closing in period ${index}`);
        if (index > 0 && Math.abs(cashFlowOpeningCash - actualOpeningCash) > TOLERANCE) throw new Error(`CashFlow opening cash does not roll from prior closing in period ${index}`);
        const expectedIncome = (Math.max(actualOpeningCash, 0) + Number(d.eligibleNoncashPool)) * Number(d.cashIncomeYield) * Number(d.periodDays[index]) / 365;
        if (Math.abs(Number(d.cashIncome[index]) - expectedIncome) > TOLERANCE) throw new Error(`P8D cash income does not use actual opening cash in period ${index}`);
        const expectedFundingStatus = actualOpeningCash < 0 || actualClosingCash < 0 ? 'UNFUNDED_CASH' : 'OK';
        if (d.fundingStatus[index] !== expectedFundingStatus) throw new Error(`P8D funding status does not use actual cash in period ${index}`);
      }
    }
    if (snapshot.p9) {
      const p9 = snapshot.p9;
      if (p9.inputGate !== 'PASS' || p9.terminalGate !== 'PASS' || p9.valuationGate !== 'PASS') throw new Error(`P9 valuation gate failed: ${p9.inputGate}/${p9.terminalGate}/${p9.valuationGate}`);
      if (!['PROVISIONAL_REVIEW_REQUIRED', 'EDITED_UNREVIEWED'].includes(p9.status)) throw new Error(`P9 status invalid: ${p9.status}`);
      if (p9.claimCheck !== 'PASS') throw new Error('P9 claim-once check failed');
      if (p9.explicitUfcf.length !== PERIODS.length || p9.explicitUfcf.some((value) => typeof value !== 'number')) throw new Error('P9 explicit UFCF snapshot is incomplete');
      if (Math.abs(Number(p9.terminal.netReinvestment) - 0.02 * Number(p9.terminal.openingCapital)) > 1e-4 && Math.abs(Number(await (await wb.getSheet('Valuation')).getValue('B27')) - 0.02) <= TOLERANCE) throw new Error('P9 base terminal reinvestment does not tie opening capital');
      for (const [statement, rows] of Object.entries(snapshot.statements)) {
        if (!rows.length || rows.some((row) => row.values.length !== PERIODS.length || row.values.some((value) => typeof value !== 'number' || !Number.isFinite(value)))) throw new Error(`P9 ${statement} full-period snapshot is incomplete`);
      }
    }
    return snapshot;
  } finally {
    wb.dispose();
  }
}
