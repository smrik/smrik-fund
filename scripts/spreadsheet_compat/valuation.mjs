const AGE_LIMIT = 40;
const TOLERANCE = 1e-8;

export const P9_METHOD_ID = 'finite_steady_annual_cohorts';

export const P9_ROWS = Object.freeze({
  status: 3,
  riskFree: 12,
  erp: 13,
  beta: 14,
  debtSpread: 15,
  shield: 16,
  price: 17,
  pointShares: 18,
  debtClaim: 19,
  financeLeaseClaim: 20,
  supplierClaim: 21,
  longTermTaxClaim: 22,
  awardClaim: 23,
  currentTaxClaimSwitch: 24,
  currentTaxFace: 25,
  netDta: 26,
  terminalGrowth: 27,
  ownedLife: 28,
  ownedTiming: 29,
  financeLife: 30,
  financeTiming: 31,
  method: 32,
  marketEquity: 34,
  financingWeight: 35,
  costOfEquity: 36,
  costOfDebt: 37,
  afterTaxDebtCost: 38,
  wacc: 39,
  inputGate: 40,
  reviewStatus: 41,
  explicitUfcf: 47,
  elapsedYears: 46,
  discountFactor: 48,
  pvUfcf: 49,
  explicitPv: 50,
  terminalDiscountFactor: 51,
  openingOwnedPpe: 54,
  openingFinancePpe: 55,
  openingNwc: 56,
  openingCapital: 57,
  lastEbit: 58,
  finiteIntangibleAmortization: 59,
  prePpeProfit: 60,
  normalizedPrePpeProfit: 61,
  ownedCoefficient: 62,
  financeCoefficient: 63,
  ownedGrossAdditions: 64,
  financeGrossAdditions: 65,
  totalGrossAdditions: 66,
  ownedDepreciation: 67,
  financeDepreciation: 68,
  totalDepreciation: 69,
  normalizedEbit: 70,
  operatingTax: 71,
  nopat: 72,
  deltaNwc: 73,
  netReinvestment: 74,
  netReinvestmentCrosscheck: 75,
  terminalUfcf: 76,
  ownedStockDifference: 77,
  financeStockDifference: 78,
  terminalGate: 79,
  terminalValue: 81,
  pvTerminalValue: 82,
  rawEnterpriseValue: 83,
  investmentValue: 85,
  rawCommonEquityValue: 95,
  rawPerShareValue: 96,
  claimCheck: 97,
  valuationGate: 99,
  taxTimingPv: 109,
  taxTimingPerShare: 110,
  supplierClosing: 113,
  openingRoic: 116,
  averageRoic: 117,
  endingRoic: 118,
  enterpriseValue: 120,
  commonEquityValue: 121,
  perShareValue: 122,
});

const pad = (row, width = 15) => [...row, ...Array(Math.max(0, width - row.length)).fill(null)];
const periodColumns = ['B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L'];
const periodLabels = ['Apr-Jun FY2026 (stub)', 'FY2027', 'FY2028', 'FY2029', 'FY2030', 'FY2031', 'FY2032', 'FY2033', 'FY2034', 'FY2035', 'FY2036'];
const elapsedDays = [91, 456, 822, 1187, 1552, 1917, 2283, 2648, 3013, 3378, 3744];

function requireNumber(value, name) {
  if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error(`P9 missing/nonnumeric input: ${name}`);
  return value;
}

export function validateValuationPolicy(policy) {
  if (!policy || policy.method_id !== P9_METHOD_ID || policy.method_version !== 'v1') throw new Error('Unsupported P9 terminal method');
  for (const [name, value] of Object.entries({
    risk_free_rate: policy.risk_free_rate,
    equity_risk_premium: policy.equity_risk_premium,
    beta: policy.beta,
    debt_spread: policy.debt_spread,
    debt_tax_shield_rate: policy.debt_tax_shield_rate,
    price: policy.price,
    debt_fair_value: policy.debt_fair_value,
    finance_lease_claim: policy.finance_lease_claim,
    supplier_claim: policy.supplier_claim,
    long_term_tax_claim: policy.long_term_tax_claim,
    current_tax_claim_switch: policy.current_tax_claim_switch,
    current_tax_face: policy.current_tax_face,
    terminal_growth: policy.terminal_growth,
    owned_life_years: policy.owned_life_years,
    owned_first_year_fraction: policy.owned_first_year_fraction,
    finance_life_years: policy.finance_life_years,
    finance_first_year_fraction: policy.finance_first_year_fraction,
  })) requireNumber(value, name);
  if (policy.owned_life_years <= 0 || policy.finance_life_years <= 0 || policy.owned_life_years > AGE_LIMIT || policy.finance_life_years > AGE_LIMIT) throw new Error(`P9 asset lives must be within (0,${AGE_LIMIT}]`);
  if (policy.owned_first_year_fraction < 0 || policy.owned_first_year_fraction > 1 || policy.finance_first_year_fraction < 0 || policy.finance_first_year_fraction > 1) throw new Error('P9 first-year depreciation fractions must be within [0,1]');
  if (![0, 1].includes(policy.current_tax_claim_switch)) throw new Error('P9 current-tax claim switch must be zero or one');
  if (policy.debt_spread < 0) throw new Error('P9 debt credit spread must be nonnegative');
  return policy;
}

function formulaRow(label, formulas, units = 'USD millions', note = '') {
  return pad([label, ...formulas, units, note]);
}

export function valuationRows(model) {
  const p = validateValuationPolicy(model.valuation_policy);
  const rows = [
    pad(['AI Fund P9 — integrated real-company statements and DCF']),
    pad(['Eleven explicit forecast periods plus one normalized FY2037 terminal memorandum; USD nominal, later-informed analysis.']),
    pad(['Status', '=IFERROR(IF(B99<>"PASS","BLOCKED",IF(B41="SYSTEM_REVIEWED_PROVISIONAL","PROVISIONAL_REVIEW_REQUIRED",IF(B41="EDITED_UNREVIEWED","EDITED_UNREVIEWED","REVIEW_STATE_UNAVAILABLE"))),"REVIEW_STATE_UNAVAILABLE")', 'P9 whole-model analytical review remains pending']),
    pad(['Human approval', 'false', 'P10 analytical review and human decision remain outstanding']),
    pad(['Measurement / valuation date', model.measurement_date]),
    pad(['Information cutoff', model.information_cutoff]),
    pad(['Units', 'USD millions except rates and per-share values']),
    pad(['Formula authority', 'Mog formulas; native Excel is recalculation/review target']),
    pad(['Point-in-time treatment', 'Later-informed, not point-in-time; frozen dated market observations']),
    pad([]),
    pad(['Frozen market, terminal and claim inputs', 'Value', 'Units', 'Basis / treatment']),
    pad(['Risk-free rate', p.risk_free_rate, 'decimal', 'Mar31 2026 US Treasury 10Y par/CMT proxy']),
    pad(['Equity risk premium', p.equity_risk_premium, 'decimal', 'Damodaran forward implied ERP at Mar31 close']),
    pad(['Levered beta', p.beta, 'x', 'Explicit estimate; 0.85/1.15 sensitivity']),
    pad(['Debt spread proxy', p.debt_spread, 'decimal', 'AAA category/time proxy; +/-100bp sensitivity with explicit zero floor']),
    pad(['Debt tax-shield rate', p.debt_tax_shield_rate, 'decimal', 'Independent editable proxy; 0/current/21% sensitivity']),
    pad(['Unadjusted closing price', '=Inputs!$B$176', 'USD/share', 'Mar31 close; shared existing-award market quote; future repurchase proxy remains separate']),
    pad(['Point shares', '=Inputs!$B$227', 'shares millions', 'Measurement-date count; awards are a separate claim']),
    pad(['Debt fair-value claim', p.debt_fair_value, 'USD millions', 'Measurement-date disclosed fair value']),
    pad(['Finance-lease claim', p.finance_lease_claim, 'USD millions', 'Opening liability value approximation']),
    pad(['Supplier-financed PP&E payable claim', p.supplier_claim, 'USD millions', 'Face-value proxy; outside operating AP/NWC']),
    pad(['Long-term tax claim', p.long_term_tax_claim, 'USD millions', 'Face-value proxy once']),
    pad(['Existing-award claim', '=Equity!$B$40', 'USD millions', '82m awards × dated price; deducted once']),
    pad(['Current-tax face-claim switch', p.current_tax_claim_switch, '0/1', 'Base zero; one deducts face claim once']),
    pad(['Current-tax face amount', p.current_tax_face, 'USD millions', 'Source balance; base continuing-float convention']),
    pad(['Incremental NET DTA value', '=OtherBalances!$B$19', 'USD millions', 'Selected NET estimate; no separate DTL deduction']),
    pad(['Terminal growth', p.terminal_growth, 'decimal', 'Mature nominal estimate; 0%–4% sensitivity']),
    pad(['Owned PP&E steady-cohort life', '=Inputs!$B$30', 'years', `Linked to accepted new-owned useful life; bounded at ${AGE_LIMIT}`]),
    pad(['Owned first-year depreciation fraction', '=Inputs!$B$31', 'fraction', 'Linked to accepted midpoint convention']),
    pad(['Finance PP&E steady-cohort life', '=Inputs!$B$142', 'years', `Linked to accepted pipeline-finance life; bounded at ${AGE_LIMIT}`]),
    pad(['Finance first-year depreciation fraction', '=IF(Inputs!$B$168="actual_day_weighted_fy2026_fy2031",0,"")', 'fraction', 'End-period convention bound to accepted pipeline timing method']),
    pad(['Terminal method', p.method_id, 'method ID', 'Finite steady annual cohorts']),
    pad([]),
    pad(['Market equity', '=B17*B18', 'USD millions', 'Price × point shares']),
    pad(['Financing weight', '=B19+B20', 'USD millions', 'Debt fair value + finance-lease claim; operating leases excluded']),
    pad(['Cost of equity', '=B12+B14*B13', 'decimal', 'Rf + beta × ERP']),
    pad(['Pretax cost of debt', '=B12+B15', 'decimal', 'Rf + spread']),
    pad(['After-tax cost of debt', '=B37*(1-B16)', 'decimal', 'No financing tax benefit enters UFCF']),
    pad(['WACC', '=B34/(B34+B35)*B36+B35/(B34+B35)*B38', 'decimal', 'Constant market weights']),
    pad(['P9 input gate', `=IFERROR(IF(AND(COUNT(B12:B31)=20,B13>=0,B15>=0,B16>=0,B16<=1,B17>0,B18>0,B19>=0,B20>=0,B21>=0,B22>=0,B23>=0,OR(B24=0,B24=1),B25>=0,B26>=0,B27>=0,B27<B39,B28>0,B28<=${AGE_LIMIT},B29>=0,B29<=1,B30>0,B30<=${AGE_LIMIT},B31>=0,B31<=1,B32="${P9_METHOD_ID}"),"PASS","FAIL"),"FAIL")`, 'status', 'Missing/out-of-domain inputs block; zero credit spread is valid, negative credit spread is blocked']),
    pad(['Attached-base review status', `=IF(AND(Checks!B23="UNCHANGED",ABS(B12-${p.risk_free_rate})<=${TOLERANCE},ABS(B13-${p.equity_risk_premium})<=${TOLERANCE},ABS(B14-${p.beta})<=${TOLERANCE},ABS(B15-${p.debt_spread})<=${TOLERANCE},ABS(B16-${p.debt_tax_shield_rate})<=${TOLERANCE},ABS(B17-${p.price})<=${TOLERANCE},ABS(B19-${p.debt_fair_value})<=${TOLERANCE},ABS(B20-${p.finance_lease_claim})<=${TOLERANCE},ABS(B21-${p.supplier_claim})<=${TOLERANCE},ABS(B22-${p.long_term_tax_claim})<=${TOLERANCE},ABS(B24-${p.current_tax_claim_switch})<=${TOLERANCE},ABS(B25-${p.current_tax_face})<=${TOLERANCE},ABS(B27-${p.terminal_growth})<=${TOLERANCE},ABS(B28-${p.owned_life_years})<=${TOLERANCE},ABS(B29-${p.owned_first_year_fraction})<=${TOLERANCE},ABS(B30-${p.finance_life_years})<=${TOLERANCE},ABS(B31-${p.finance_first_year_fraction})<=${TOLERANCE},B32="${P9_METHOD_ID}"),"SYSTEM_REVIEWED_PROVISIONAL","EDITED_UNREVIEWED")`, 'status', 'Any accepted upstream or P9 driver edit invalidates attached base review']),
    pad([]),
    pad(['Explicit economic UFCF and ACT/365 discounting']),
    pad(['Line', ...periodLabels, 'Units', 'Treatment']),
    pad(['Period end', '2026-06-30', '2027-06-30', '2028-06-30', '2029-06-30', '2030-06-30', '2031-06-30', '2032-06-30', '2033-06-30', '2034-06-30', '2035-06-30', '2036-06-30', 'date']),
    formulaRow('ACT/365 elapsed years', elapsedDays.map((days) => `=${days}/365`), 'years', 'Period end from 2026-03-31; first period 91/365'),
    formulaRow('Economic UFCF', periodColumns.map((column) => `=Equity!${column}32`), 'USD millions', 'Financing-independent operating UFCF; investment income and its company tax excluded'),
    formulaRow('Discount factor', periodColumns.map((column) => `=1/(1+$B$39)^${column}46`), 'factor', 'Period-end ACT/365'),
    formulaRow('PV of economic UFCF', periodColumns.map((column) => `=${column}47*${column}48`), 'USD millions'),
    pad(['PV of explicit forecast', '=SUM(B49:L49)', 'USD millions']),
    pad(['Final explicit-period discount factor', '=L48', 'factor', 'Terminal value is at 2036-06-30']),
    pad([]),
    pad(['Normalized FY2037 terminal memorandum', 'Value', 'Units', 'Definition']),
    pad(['Opening owned PP&E', '=BalanceSheet!L11-Financing!L55', 'USD millions', 'FY2036 closing PP&E excluding finance PP&E']),
    pad(['Opening finance PP&E', '=Financing!L55', 'USD millions', 'FY2036 closing finance PP&E']),
    pad(['Opening operating cash-conversion NWC', '=WorkingCapital!L41', 'USD millions', 'FY2036 closing operating NWC']),
    pad(['Opening invested operating capital', '=SUM(B54:B56)', 'USD millions', 'No operating-lease ROU capital']),
    pad(['FY2036 EBIT', '=Income!L11', 'USD millions']),
    pad(['Finite acquired-intangible amortization removed', '=OtherBalances!L14', 'USD millions', 'Removed once; no perpetual replacement or tax shield']),
    pad(['FY2036 pre-PP&E-depreciation operating profit', '=B58+Schedules!L17+B59', 'USD millions', 'Retains operating leases, recurring R&D and new SBC as costs']),
    pad(['Normalized FY2037 pre-PP&E-depreciation profit', '=B60*(1+B27)', 'USD millions', 'Revenue/cost productivity base grows once']),
    pad(['Owned capital coefficient', '=TerminalCohorts!E44', 'factor', 'Sum of remaining fractions discounted by cohort growth']),
    pad(['Finance capital coefficient', '=TerminalCohorts!K44', 'factor']),
    pad(['Owned gross additions', '=B54*(1+B27)/B62', 'USD millions']),
    pad(['Finance gross additions', '=B55*(1+B27)/B63', 'USD millions']),
    pad(['Total gross PP&E additions', '=B64+B65', 'USD millions', 'Cash and noncash investment recognized once']),
    pad(['Owned PP&E depreciation', '=TerminalCohorts!D44', 'USD millions']),
    pad(['Finance PP&E depreciation', '=TerminalCohorts!J44', 'USD millions']),
    pad(['Total PP&E depreciation', '=B67+B68', 'USD millions']),
    pad(['Normalized EBIT', '=B61-B69', 'USD millions']),
    pad(['Normalized accrued operating tax', '=MAX(0,B70)*Inputs!$B$107', 'USD millions', 'Financing independent; current-tax float excluded']),
    pad(['Normalized NOPAT', '=B70-B71', 'USD millions']),
    pad(['Operating NWC change', '=B27*B56', 'USD millions']),
    pad(['Net reinvestment', '=B66-B69+B73', 'USD millions']),
    pad(['Net reinvestment cross-check', '=B27*B57', 'USD millions', 'g × opening capital']),
    pad(['Normalized terminal UFCF', '=B72-B74', 'USD millions']),
    pad(['Owned stock-rollforward difference', '=B54+B64-B67-B54*(1+B27)', 'USD millions']),
    pad(['Finance stock-rollforward difference', '=B55+B65-B68-B55*(1+B27)', 'USD millions']),
    pad(['Terminal normalization gate', `=IFERROR(IF(AND(ABS(B77)<=${TOLERANCE},ABS(B78)<=${TOLERANCE},ABS(B74-B75)<=${TOLERANCE},IF(B27=0,AND(ABS(B64-B67)<=${TOLERANCE},ABS(B65-B68)<=${TOLERANCE},ABS(B74)<=${TOLERANCE}),TRUE)),"PASS","FAIL"),"FAIL")`, 'status']),
    pad([]),
    pad(['Terminal value', '=IFERROR(IF(AND(B40="PASS",B79="PASS",B39>B27),B76/(B39-B27),"BLOCKED"),"BLOCKED")', 'USD millions', 'FY2037 normalized UFCF divided by WACC-g']),
    pad(['PV of terminal value', '=IF(ISNUMBER(B81),B81*B51,"BLOCKED")', 'USD millions']),
    pad(['Enterprise value', '=IF(ISNUMBER(B82),B50+B82,"BLOCKED")', 'USD millions', 'Explicit PV plus normalized terminal PV']),
    pad([]),
    pad(['Investment value including cash', '=OtherBalances!B11', 'USD millions', 'Includes known cash and investments 91,436, selected other investments/receivable and commitment adjustment; cash not added again']),
    pad(['Debt fair value deduction', '=B19', 'USD millions']),
    pad(['Finance-lease claim deduction', '=B20', 'USD millions']),
    pad(['Supplier-payable claim deduction', '=B21', 'USD millions']),
    pad(['Long-term tax claim deduction', '=B22', 'USD millions']),
    pad(['Existing-award claim deduction', '=B23', 'USD millions']),
    pad(['Optional current-tax claim deduction', '=B24*B25', 'USD millions', 'Base zero; stress deducts face amount once']),
    pad(['Incremental NET DTA addition', '=B26', 'USD millions', 'No separate DTL deduction']),
    pad(['Operating-lease claim', 'Excluded', '', 'Expense remains in operations; no second financing claim']),
    pad(['Minority-interest treatment', 'Unsupported / absent from accepted source coverage', '', 'No amount invented or added']),
    pad(['Common equity value', '=IF(ISNUMBER(B83),B83+B85-B86-B87-B88-B89-B90-B91+B92,"BLOCKED")', 'USD millions']),
    pad(['Value per point share', '=IF(ISNUMBER(B95),B95/B18,"BLOCKED")', 'USD/share']),
    pad(['Claim-once arithmetic check', `=IFERROR(IF(AND(ISNUMBER(B95),ABS(B95-(B83+B85-B19-B20-B21-B22-B23-B24*B25+B26))<=${TOLERANCE},ABS(B23-Equity!B40)<=${TOLERANCE},ABS(B85-OtherBalances!B11)<=${TOLERANCE}),"PASS","FAIL"),"FAIL")`, 'status']),
    pad([]),
    pad(['P9 valuation gate', '=IFERROR(IF(AND(B40="PASS",B79="PASS",B97="PASS",Checks!B22="PASS",Inputs!B114="PASS",Inputs!B146="PASS",Inputs!B185="PASS",Inputs!B253="PASS"),"PASS","FAIL"),"FAIL")', 'status', 'All accepted upstream mechanical/input gates plus P9 input, terminal and claim checks']),
    pad(['Hypothetical current-tax timing diagnostic', null, null, 'All opening current tax assigned to operating taxes only for this sensitivity; allocation is unsupported. No terminal timing benefit.']),
    pad(['Line', ...periodLabels, 'Units']),
    formulaRow('Economic operating tax expense', periodColumns.map((column) => `=Equity!${column}31`)),
    formulaRow('Hypothetical payable opening', periodColumns.map((column, index) => index === 0 ? '=B25' : `=${periodColumns[index - 1]}104`)),
    formulaRow('Hypothetical payable closing', periodColumns.map((column) => `=${column}102*Inputs!$B$117/Inputs!${column}$118`)),
    formulaRow('Hypothetical tax payment', periodColumns.map((column) => `=${column}102+${column}103-${column}104`)),
    formulaRow('Timing cash benefit vs accrual', periodColumns.map((column) => `=${column}104-${column}103`)),
    formulaRow('Discount factor', periodColumns.map((column) => `=${column}48`), 'factor'),
    formulaRow('PV timing benefit', periodColumns.map((column) => `=${column}106*${column}107`)),
    pad(['Explicit-horizon PV timing benefit', '=SUM(B108:L108)', 'USD millions', 'Assumption diagnostic only; excluded from base value']),
    pad(['Explicit-horizon timing benefit per share', '=B109/B18', 'USD/share']),
    pad(['Separate current-tax face-claim stress per share', '=-B25/B18', 'USD/share']),
    pad(['Supplier-financed PP&E limitation']),
    pad(['FY2036 no-settlement payable', '=Schedules!L25', 'USD millions', 'P5 noncash additions grow without selected settlements']),
    pad(['Reported AP less supplier claim', '=Inputs!B20-B21', 'USD millions', '37,513 - 22,600 = operating AP 14,913']),
    pad(['Treatment', 'Opening face claim deducted once; new supplier/noncash investment enters UFCF once. Supported book CFI settlement must not be deducted again. Maturity/rate unknown; excluded from WACC.']),
    pad(['Implied return on opening capital', '=B72/B57', 'decimal']),
    pad(['Implied return on average capital', '=B72/(B57*(1+B27/2))', 'decimal']),
    pad(['Implied return on ending capital', '=B72/(B57*(1+B27))', 'decimal']),
    pad([]),
    pad(['Canonical guarded enterprise value', '=IF(B99="PASS",B83,"BLOCKED")', 'USD millions']),
    pad(['Canonical guarded common equity value', '=IF(B99="PASS",B95,"BLOCKED")', 'USD millions']),
    pad(['Canonical guarded value per point share', '=IF(B99="PASS",B96,"BLOCKED")', 'USD/share']),
  ];
  if (rows.length !== 122) throw new Error(`P9 valuation row catalog drift: ${rows.length}`);
  return rows;
}

export function terminalCohortRows(model) {
  validateValuationPolicy(model.valuation_policy);
  const rows = [
    pad(['P9 bounded terminal steady-cohort schedule']),
    pad(['Age grid is formula driven and supports fractional lives up to 40 years. Existing cohorts are deflated by g; depreciation is capped at remaining carrying fraction.']),
    pad(['Owned age k', 'Remaining fraction', 'Existing cohort gross', 'FY2037 depreciation', 'Coefficient contribution', null, 'Finance age k', 'Remaining fraction', 'Existing cohort gross', 'FY2037 depreciation', 'Coefficient contribution']),
  ];
  for (let k = 0; k < AGE_LIMIT; k += 1) {
    const row = rows.length + 1;
    rows.push(pad([
      k,
      `=IF(A${row}<Valuation!$B$28,MAX(0,1-(A${row}+Valuation!$B$29)/Valuation!$B$28),0)`,
      `=IF(A${row}<Valuation!$B$28,Valuation!$B$64/(1+Valuation!$B$27)^(A${row}+1),0)`,
      `=MIN(1/Valuation!$B$28,B${row})*C${row}`,
      `=B${row}/(1+Valuation!$B$27)^A${row}`,
      null,
      k,
      `=IF(G${row}<Valuation!$B$30,MAX(0,1-(G${row}+Valuation!$B$31)/Valuation!$B$30),0)`,
      `=IF(G${row}<Valuation!$B$30,Valuation!$B$65/(1+Valuation!$B$27)^(G${row}+1),0)`,
      `=MIN(1/Valuation!$B$30,H${row})*I${row}`,
      `=H${row}/(1+Valuation!$B$27)^G${row}`,
    ]));
  }
  rows.push(pad(['Totals', null, null, `=SUM(D4:D${AGE_LIMIT + 3})+Valuation!$B$64*Valuation!$B$29/Valuation!$B$28`, `=SUM(E4:E${AGE_LIMIT + 3})`, null, 'Totals', null, null, `=SUM(J4:J${AGE_LIMIT + 3})+Valuation!$B$65*Valuation!$B$31/Valuation!$B$30`, `=SUM(K4:K${AGE_LIMIT + 3})`]));
  return rows;
}

function coefficientExpression(life, timing, growth) {
  return `SUM(${Array.from({ length: AGE_LIMIT }, (_, k) => `IF(${k}<${life},MAX(0,1-(${k}+${timing})/${life})/(1+${growth})^${k},0)`).join(',')})`;
}

function depreciationExpression(life, timing, growth, gross) {
  const old = Array.from({ length: AGE_LIMIT }, (_, k) => `IF(${k}<${life},MIN(1/${life},MAX(0,1-(${k}+${timing})/${life}))*${gross}/(1+${growth})^(${k}+1),0)`);
  return `SUM(${old.join(',')})+${gross}*${timing}/${life}`;
}

function equityBridgeFormula(ev) {
  return `(${ev}+Valuation!$B$85-Valuation!$B$19-Valuation!$B$20-Valuation!$B$21-Valuation!$B$22-Valuation!$B$23-Valuation!$B$24*Valuation!$B$25+Valuation!$B$26)/Valuation!$B$18`;
}

export function p9SensitivityRows(model) {
  validateValuationPolicy(model.valuation_policy);
  const rows = [
    pad(['P9 live valuation sensitivities']),
    pad(['Terminal and WACC cases recalculate formulas. Operating driver row is a live link; edit the stated Inputs cell to recalculate the complete workbook.']),
    pad(['Terminal g', 'Owned coefficient', 'Owned gross', 'Owned depreciation', 'Finance coefficient', 'Finance gross', 'Finance depreciation', 'Total gross', 'Total depreciation', 'Delta NWC', 'NOPAT', 'UFCF', 'Terminal value', 'Enterprise value', 'Value/share']),
  ];
  for (const g of [0, 0.01, 0.02, 0.03, 0.04]) {
    const row = rows.length + 1;
    const growth = `$A${row}`;
    const ownedCoefficient = coefficientExpression('Valuation!$B$28', 'Valuation!$B$29', growth);
    const financeCoefficient = coefficientExpression('Valuation!$B$30', 'Valuation!$B$31', growth);
    rows.push(pad([
      g,
      `=${ownedCoefficient}`,
      `=Valuation!$B$54*(1+${growth})/B${row}`,
      `=${depreciationExpression('Valuation!$B$28', 'Valuation!$B$29', growth, `C${row}`)}`,
      `=${financeCoefficient}`,
      `=Valuation!$B$55*(1+${growth})/E${row}`,
      `=${depreciationExpression('Valuation!$B$30', 'Valuation!$B$31', growth, `F${row}`)}`,
      `=C${row}+F${row}`,
      `=D${row}+G${row}`,
      `=${growth}*Valuation!$B$56`,
      `=(Valuation!$B$60*(1+${growth})-I${row})*(1-Inputs!$B$107)`,
      `=K${row}-(H${row}-I${row}+J${row})`,
      `=IF(Valuation!$B$39>${growth},L${row}/(Valuation!$B$39-${growth}),"BLOCKED")`,
      `=IF(AND(Valuation!$B$99="PASS",ISNUMBER(M${row})),Valuation!$B$50+M${row}*Valuation!$B$51,"BLOCKED")`,
      `=IF(AND(Valuation!$B$99="PASS",ISNUMBER(N${row})),${equityBridgeFormula(`N${row}`)},"BLOCKED")`,
    ], 15));
  }
  rows.push(pad([]));
  rows.push(pad(['WACC case', 'Beta', 'Debt spread', 'Shield', 'WACC', 'Explicit PV', 'Terminal PV', 'Enterprise value', 'Value/share']));
  const waccCases = [
    ['Beta low', 0.85, '=Valuation!B15', '=Valuation!B16'],
    ['Base', 1, '=Valuation!B15', '=Valuation!B16'],
    ['Beta high', 1.15, '=Valuation!B15', '=Valuation!B16'],
    ['Debt spread -100bp (floor 0%)', '=Valuation!B14', '=MAX(0,Valuation!B15-0.01)', '=Valuation!B16'],
    ['Debt spread +100bp', '=Valuation!B14', '=Valuation!B15+0.01', '=Valuation!B16'],
    ['No debt shield', '=Valuation!B14', '=Valuation!B15', 0],
    ['21% debt shield', '=Valuation!B14', '=Valuation!B15', 0.21],
  ];
  for (const [label, beta, spread, shield] of waccCases) {
    const row = rows.length + 1;
    const wacc = `(Valuation!$B$34/(Valuation!$B$34+Valuation!$B$35)*(Valuation!$B$12+B${row}*Valuation!$B$13)+Valuation!$B$35/(Valuation!$B$34+Valuation!$B$35)*(Valuation!$B$12+C${row})*(1-D${row}))`;
    const pvTerms = periodColumns.map((column) => `DCF!${column}$7/(1+E${row})^Valuation!${column}$46`).join(',');
    rows.push(pad([label, beta, spread, shield, `=${wacc}`, `=SUM(${pvTerms})`, `=IF(AND(Valuation!$B$99="PASS",E${row}>Valuation!$B$27),Valuation!$B$76/(E${row}-Valuation!$B$27)/(1+E${row})^Valuation!$L$46,"BLOCKED")`, `=IF(AND(Valuation!$B$99="PASS",ISNUMBER(G${row})),F${row}+G${row},"BLOCKED")`, `=IF(AND(Valuation!$B$99="PASS",ISNUMBER(H${row})),${equityBridgeFormula(`H${row}`)},"BLOCKED")`]));
  }
  rows.push(pad([]));
  rows.push(pad(['Live operating driver', 'Current input', 'FY2036 revenue', 'FY2036 EBIT', 'Enterprise value', 'Value/share', 'Review state']));
  rows.push(pad(['Intelligent Cloud stub growth', '=Inputs!B64', '=Income!L6', '=Income!L11', '=Valuation!B120', '=Valuation!B122', '=Valuation!B3']));
  rows.push(pad(['Live source/estimate bridge cases', 'Low', 'Base', 'High', 'Units / treatment']));
  rows.push(pad(['Other investment value multiplier', 0.5, 1, 1.5, 'x; linked P8D value estimate']));
  const multiplierRow = rows.length;
  rows.push(pad(['Value/share', ...['B', 'C', 'D'].map((column) => `=IF(Valuation!$B$99="PASS",(Valuation!$B$95-Inputs!$B$268*Inputs!$B$234+Inputs!$B$268*${column}${multiplierRow})/Valuation!$B$18,"BLOCKED")`), 'USD/share']));
  rows.push(pad(['Current-tax claim switch', 0, '=Valuation!B24', 1, '0/1; claim replaces base continuing-float convention']));
  const taxSwitchRow = rows.length;
  rows.push(pad(['Value/share', ...['B', 'C', 'D'].map((column) => `=IF(Valuation!$B$99="PASS",(Valuation!$B$95+Valuation!$B$24*Valuation!$B$25-${column}${taxSwitchRow}*Valuation!$B$25)/Valuation!$B$18,"BLOCKED")`), 'USD/share']));
  rows.push(pad(['Incremental NET DTA value', 0, '=Valuation!B26', 26273, 'USD millions; high is historical proxy, not Q3 carrying value']));
  const dtaRow = rows.length;
  rows.push(pad(['Value/share', ...['B', 'C', 'D'].map((column) => `=IF(Valuation!$B$99="PASS",(Valuation!$B$95-Valuation!$B$26+${column}${dtaRow})/Valuation!$B$18,"BLOCKED")`), 'USD/share']));
  return rows;
}

export function historicalBridgeRows(model) {
  const h = model.historical_bridge;
  if (!h) return [];
  const f = h.facts;
  return [
    pad(['P9 historical CFO / cash-FCF / operating-value bridge']),
    pad(['TTM source-backed bridge. Visible residuals preserve incomplete historical investment, operating-NWC and financing/supplier-noncash coverage.']),
    pad(['Line', 'Value', 'Units', 'Source / treatment']),
    pad(['TTM cash from operations', f.ttm_cfo, 'USD millions', h.source_label]),
    pad(['TTM cash PP&E payments', f.ttm_cash_ppe_payments, 'USD millions', h.source_label]),
    pad(['TTM cash FCF', '=B4-B5', 'USD millions', 'CFO less cash PP&E payments']),
    pad(['TTM net income', f.ttm_net_income, 'USD millions', h.source_label]),
    pad(['CFO less net income', '=B4-B7', 'USD millions', 'Book cash-conversion bridge; not treated as operating NWC']),
    pad(['TTM tax expense', f.ttm_tax_expense, 'USD millions', h.source_label]),
    pad(['TTM net nonoperating income', f.ttm_net_nonoperating_income, 'USD millions', h.source_label]),
    pad(['TTM EBIT', '=B7+B9-B10', 'USD millions', 'Net income + tax - net nonoperating income']),
    pad(['Normalized accrued operating tax', '=B11*Inputs!$B$107', 'USD millions', 'Financing-independent valuation tax']),
    pad(['TTM NOPAT', '=B11-B12', 'USD millions']),
    pad(['Supported PP&E depreciation', f.supported_ppe_depreciation, 'USD millions', h.source_label]),
    pad(['Supported intangible amortization', f.supported_intangible_amortization, 'USD millions', h.source_label]),
    pad(['Supported subtotal before missing historical investment/NWC', '=B13+B14+B15-B5', 'USD millions', 'NOT UFCF']),
    pad(['Broad D&A and other', f.broad_da_and_other, 'USD millions', h.source_label]),
    pad(['Unallocated broad D&A and other residual', '=B17-B14-B15', 'USD millions', 'Visible; no automatic addback']),
    pad(['Current nine-month finance noncash additions', f.current_nine_month_finance_noncash_additions, 'USD millions', 'Not TTM; not annualized or deducted']),
    pad(['Full historical UFCF', 'NOT_FULLY_ESTIMATED_SOURCE_LIMITATIONS', '', 'Missing historical operating NWC and finance/supplier noncash investment composition']),
    pad(['Historical SBC treatment', 'Retained as operating cost', '', 'Retrospective old/new award split unavailable']),
    pad(['Forecast treatment', 'All 11 forecast UFCF periods fully calculated', '', 'Historical source residual does not enter forecast DCF']),
    pad(['Packet', h.packet_path, '', h.packet_sha256]),
  ];
}

export async function readP9Snapshot(wb) {
  const valuation = await wb.getSheet('Valuation');
  const sensitivity = await wb.getSheet('P9Sensitivity');
  const history = await wb.getSheet('HistoricalBridge');
  const read = (row) => valuation.getValue(`B${row}`);
  const period = async (row) => {
    const values = [];
    for (const column of periodColumns) values.push(await valuation.getValue(`${column}${row}`));
    return values;
  };
  return {
    status: await read(P9_ROWS.status),
    reviewStatus: await read(P9_ROWS.reviewStatus),
    inputGate: await read(P9_ROWS.inputGate),
    terminalGate: await read(P9_ROWS.terminalGate),
    valuationGate: await read(P9_ROWS.valuationGate),
    wacc: await read(P9_ROWS.wacc),
    explicitUfcf: await period(P9_ROWS.explicitUfcf),
    elapsedYears: await period(P9_ROWS.elapsedYears),
    discountFactors: await period(P9_ROWS.discountFactor),
    pvUfcf: await period(P9_ROWS.pvUfcf),
    explicitPv: await read(P9_ROWS.explicitPv),
    terminal: {
      openingOwnedPpe: await read(P9_ROWS.openingOwnedPpe),
      openingFinancePpe: await read(P9_ROWS.openingFinancePpe),
      openingNwc: await read(P9_ROWS.openingNwc),
      openingCapital: await read(P9_ROWS.openingCapital),
      prePpeProfit: await read(P9_ROWS.prePpeProfit),
      normalizedPrePpeProfit: await read(P9_ROWS.normalizedPrePpeProfit),
      grossAdditions: await read(P9_ROWS.totalGrossAdditions),
      depreciation: await read(P9_ROWS.totalDepreciation),
      nopat: await read(P9_ROWS.nopat),
      deltaNwc: await read(P9_ROWS.deltaNwc),
      netReinvestment: await read(P9_ROWS.netReinvestment),
      ufcf: await read(P9_ROWS.terminalUfcf),
      value: await read(P9_ROWS.terminalValue),
      openingRoic: await read(P9_ROWS.openingRoic),
      averageRoic: await read(P9_ROWS.averageRoic),
      endingRoic: await read(P9_ROWS.endingRoic),
    },
    rawEnterpriseValue: await read(P9_ROWS.rawEnterpriseValue),
    enterpriseValue: await read(P9_ROWS.enterpriseValue),
    investmentValue: await read(P9_ROWS.investmentValue),
    rawCommonEquityValue: await read(P9_ROWS.rawCommonEquityValue),
    rawPerShareValue: await read(P9_ROWS.rawPerShareValue),
    commonEquityValue: await read(P9_ROWS.commonEquityValue),
    perShareValue: await read(P9_ROWS.perShareValue),
    claimCheck: await read(P9_ROWS.claimCheck),
    taxTimingPv: await read(P9_ROWS.taxTimingPv),
    taxTimingPerShare: await read(P9_ROWS.taxTimingPerShare),
    supplierClosing: await read(P9_ROWS.supplierClosing),
    terminalGrowthSensitivity: await Promise.all([4, 5, 6, 7, 8].map(async (row) => ({ growth: await sensitivity.getValue(`A${row}`), ufcf: await sensitivity.getValue(`L${row}`), terminalValue: await sensitivity.getValue(`M${row}`), enterpriseValue: await sensitivity.getValue(`N${row}`), perShareValue: await sensitivity.getValue(`O${row}`) }))),
    history: {
      cashFcf: await history.getValue('B6'),
      operatingSubtotalBeforeGaps: await history.getValue('B16'),
      unallocatedDaResidual: await history.getValue('B18'),
      fullHistoricalUfcf: await history.getValue('B20'),
    },
    formulas: {
      reviewStatus: await valuation.getFormula(`B${P9_ROWS.reviewStatus}`),
      wacc: await valuation.getFormula('B39'),
      terminalUfcf: await valuation.getFormula('B76'),
      equityBridge: await valuation.getFormula('B95'),
      taxTiming: await valuation.getFormula('B109'),
    },
  };
}
