import { createWorkbook } from '@mog-sdk/sdk';
import { readFile, writeFile, mkdir, access } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';

const F = (formula) => ({ formula: `=${formula}` });
const col = (i) => String.fromCharCode(66 + i);
const model = JSON.parse(await readFile(process.argv[2], 'utf8'));
for (const path of [process.argv[3],process.argv[4]]) {
  try { await access(path); } catch (error) { if(error.code==='ENOENT') continue; throw error; }
  throw Error(`Refusing to overwrite ${path}`);
}
if (model.schema_version !== 'company-dcf-development-v1' || model.periods.length !== 11) throw Error('Unsupported model');
const aggregate = model.method === 'consolidated-development-v1';
const displayNames = aggregate ? {receivables:'Operating current assets (derived aggregate)', payables:'Operating current liabilities (derived aggregate)', cost_of_sales:'Total operating expenses (revenue minus EBIT)', research:'R&D included in aggregate expenses', sga:'SG&A included in aggregate expenses', products_growth:'Consolidated revenue growth', services_growth:'Unused separate-revenue growth', Products:'Consolidated', Services:'Separate-category'} : {};
const wb = await createWorkbook({ userTimezone: 'UTC' });
await wb.sheets.rename('Sheet1', 'Review');
for (const name of ['Inputs', 'SavedInputs', 'History', 'Schedules', 'Income', 'BalanceSheet', 'CashFlow', 'DCF', 'Checks', 'Evidence', 'Sensitivity']) await wb.sheets.add(name);

async function table(name, rows) {
  const sheet = await wb.getSheet(name);
  const width = Math.max(...rows.map(r => r.length));
  await sheet.setRange(`A1:${String.fromCharCode(64 + width)}${rows.length}`, rows.map(row => Array.from({ length: width }, (_, i) => row[i]?.formula ?? (typeof row[i] === 'string' ? null : row[i] ?? null))));
  for (let r = 0; r < rows.length; r++) for (let c = 0; c < rows[r].length; c++) if (typeof rows[r][c] === 'string') await sheet.setCell(`${String.fromCharCode(65+c)}${r+1}`, rows[r][c], { literal: true });
  await sheet.formats.setRange(`A1:${String.fromCharCode(64+width)}1`, { bold: true, backgroundColor: '#16324F', fontColor: '#FFFFFF' });
  await sheet.formats.setRange(`A3:${String.fromCharCode(64+width)}3`, { bold: true, backgroundColor: '#DCEAF4' });
  if (width > 1 && rows.length > 3) await sheet.formats.setRange(`B4:${String.fromCharCode(64+width)}${rows.length}`, { numberFormat: '#,##0.00;(#,##0.00);–' });
  return sheet;
}
const inputRows = [['Source values and editable development assumptions'], ['USD millions / million shares; ratio inputs decimal. Blue cells editable; edits invalidate review.'], ['Input', 'Value', 'Basis']];
const indices = {};
function input(key, value, basis) { inputRows.push([displayNames[key] ?? (aggregate ? key.replace('Products_', 'Consolidated revenue — ').replace('Services_', 'Separate-category structural zero — ') : key), value, aggregate ? `Consolidated method; see allocations and caveats. ${basis}` : basis]); indices[key] = inputRows.length; }
for (const [key, value] of Object.entries(model.opening)) input(key, value, key==='shares_proxy' ? 'Reported diluted quarterly weighted-average shares; development valuation proxy, not point-in-time shares' : aggregate ? 'Reported value or explicit derived group; structural zeros identify detail grouped elsewhere. See Evidence.' : 'Reported closing balance; see Evidence');
for (const [key, value] of Object.entries(model.history)) input(`ttm_${key}`, value.ttm, 'Derived FY + current YTD − prior YTD; reported signs preserved');
for (const [segment, values] of Object.entries(model.segments)) for (const [period, value] of Object.entries(values)) input(`${segment}_${period}`, value, aggregate ? 'Consolidated reported revenue; separate-category slots are structural zeros. History and Evidence.' : 'Disclosed product/service view; History and Evidence');
if (model.normalized_tax_rate !== undefined) input('normalized_tax_rate', model.normalized_tax_rate, 'Historical effective rate when usable; otherwise explicit 25% development normalization. Reported tax remains in History.');
input('estimated_ttm_ppe_depreciation', model.estimated_ttm_ppe_depreciation, 'ESTIMATE: disclosed annual PP&E / annual combined D&A × TTM combined D&A');
for (const [key, value] of Object.entries(model.controls)) input(key, value, 'AGENT-SELECTED DEVELOPMENT ASSUMPTION; not a sourced market observation');
const I = key => `Inputs!$B$${indices[key]}`;
const inputs = await table('Inputs', inputRows);
await table('SavedInputs', inputRows.map(row => [...row]));
for (const key of Object.keys(model.controls)) {
  await inputs.formats.setRange(`B${indices[key]}:B${indices[key]}`, { fontColor: '#0066CC', backgroundColor: '#FFF2CC' });
  await inputs.comments.addNote(`B${indices[key]}`, { author: 'smrik-fund', text: `${inputRows[indices[key]-1][2]}. ${model.analyst?.rationale ?? 'Provisional default for E2E testing.'}` });
}
const debt = `(${I('commercial_paper')}+${I('current_debt')}+${I('long_debt')})`;
const minority = model.opening.minority_interest_proxy === undefined ? '0' : I('minority_interest_proxy');
const securities = `(${I('short_investments')}+${I('long_investments')})`;
const taxRate = model.normalized_tax_rate !== undefined ? I('normalized_tax_rate') : `(${I('ttm_tax')}/${I('ttm_pretax')})`;
const openingNwc = `(${I('receivables')}+${I('vendor_receivables')}+${I('inventory')}+${I('other_current_assets')}-${I('intangibles_current')}-${I('payables')}-${I('deferred_revenue')})`;
const rows = [[`${model.case} — linked provisional schedules`], ['Development method: declining carrying-balance depreciation; half-period charge on additions; all formulas application-owned.'], ['USD millions', ...model.periods.map(p => p.id)]];
function row(label, fn) { rows.push([label, ...model.periods.map((p, i) => F(fn(col(i), i, p)))]); }
row('Period fraction (364-day fiscal basis)', (c,i,p) => `${p.fraction}`); // 4
row('Elapsed years (ACT/365)', (c,i,p) => `${p.elapsed}`); // 5
for (const name of ['Products','Services']) row(`${displayNames[name] ?? name} revenue`, (c,i) => i===0 ? `(${I(name+'_annual')}-${I(name+'_prior_ytd')})*(1+${I(name.toLowerCase()+'_growth')})` : i===1 ? `(${I(name+'_current_ytd')}+B${name==='Products'?6:7})*(1+${I(name.toLowerCase()+'_growth')})` : `${col(i-1)}${name==='Products'?6:7}*(1+${I(name.toLowerCase()+'_growth')})`);
row('Revenue', c => `SUM(${c}6:${c}7)`); //8
for (const name of ['cost_of_sales','research','sga']) row(displayNames[name] ?? name, c => `${c}8*${I('ttm_'+name)}/${I('ttm_revenue')}`); //9-11
row('Gross operating costs (includes embedded D&A and SBC)', c => `SUM(${c}9:${c}11)`); //12
row('Estimated embedded D&A removed', c => `${c}8*${I('ttm_da')}/${I('ttm_revenue')}`); //13
row('Scheduled PP&E depreciation', c => `${c}20`); //14
row('Scheduled intangible amortization', c => `${c}24`); //15
row('EBIT', c => `${c}8-${c}12+${c}13-${c}14-${c}15`); //16
row('Estimated embedded PP&E component (diagnostic)', c => `${c}8*${I('estimated_ttm_ppe_depreciation')}/${I('ttm_revenue')}`); //17
row('Opening PP&E', (c,i) => i===0 ? I('ppe') : `${col(i-1)}21`); //18
row('Cash PP&E additions', c => `${c}8*(-${I('ttm_capex_cash')})/${I('ttm_revenue')}`); //19
row('PP&E depreciation: declining balance + half-period additions', c => `MIN(${c}18,${c}18/${I('ppe_life')}*${c}4)+MIN(${c}19,${c}19/${I('ppe_life')}*0.5*${c}4)`); //20
row('Closing PP&E', c => `${c}18+${c}19-${c}20`); //21
row('Opening total intangibles', (c,i) => i===0 ? `${I('intangibles_noncurrent')}+${I('intangibles_current')}` : `${col(i-1)}25`); //22
row('Cash intangible additions (estimated)', c => `${c}8*${I('intangible_additions_ratio')}`); //23
row('Intangible amortization: declining balance', c => `MIN(${c}22,${c}22/${I('intangible_life')}*${c}4)+MIN(${c}23,${c}23/${I('intangible_life')}*0.5*${c}4)`); //24
row('Closing total intangibles', c => `${c}22+${c}23-${c}24`); //25
for (const key of ['receivables','vendor_receivables']) row(displayNames[key] ?? key, c => `${I(key)}*${c}8/${c}4/${I('ttm_revenue')}`); //26-27
row('Inventory', c => `${I('inventory')}*${c}9/${c}4/${I('ttm_cost_of_sales')}`); //28
row('Other current operating assets excluding disclosed intangibles', c => `(${I('other_current_assets')}-${I('intangibles_current')})*${c}8/${c}4/${I('ttm_revenue')}`); //29
row(aggregate ? 'Operating current liabilities' : 'Accounts payable', c => `${I('payables')}*${c}9/${c}4/${I('ttm_cost_of_sales')}`); //30
row('Deferred revenue', c => `${I('deferred_revenue')}*${c}8/${c}4/${I('ttm_revenue')}`); //31
row('Other current liabilities (held flat; includes tax/accrual uncertainty)', () => I('other_current_liabilities')); //32
row('Operating NWC', c => `SUM(${c}26:${c}29)-${c}30-${c}31`); //33
row('Change in NWC', (c,i) => `${c}33-(${i===0?openingNwc:col(i-1)+'33'})`); //34
row('Interest expense on constant refinanced debt', c => `${debt}*${I('debt_rate')}*${c}4`); //35
row('Investment income (scenario risk-free yield)', c => `${securities}*${I('risk_free')}*${c}4`); //36
row('Pretax income', c => `${c}16-${c}35+${c}36`); //37
row('Book/cash tax (same timing assumption)', c => `MAX(0,${c}37)*${taxRate}`); //38
row('Net income', c => `${c}37-${c}38`); //39
row('SBC cash-flow addback / equity contribution', c => `${c}8*${I('ttm_sbc')}/${I('ttm_revenue')}`); //40
row('Cash shareholder distributions (dividend-equivalent policy)', c => `MAX(0,${c}39)*${I('payout_ratio')}`); //41
row('CFO', c => `${c}39+${c}20+${c}24+${c}40-${c}34`); //42
row('CFI', c => `-${c}19-${c}23`); //43
row('CFF (zero net debt issuance; refinancing assumption)', c => `-${c}41`); //44
row('Opening cash', (c,i) => i===0?I('cash'):`${col(i-1)}46`); //45
row('Closing cash', c => `${c}45+${c}42+${c}43+${c}44`); //46
row('Opening equity', (c,i) => i===0?I('equity'):`${col(i-1)}48`); //47
row('Closing equity', c => `${c}47+${c}39+${c}40-${c}41`); //48
row('Total assets', c => `${c}46+${securities}+${c}21+${c}25+SUM(${c}26:${c}29)+${I('other_noncurrent_assets')}`); //49
row('Total liabilities', c => `${c}30+${c}31+${c}32+${debt}+${I('other_noncurrent_liabilities')}`); //50
row('Balance difference (no cash/equity plug)', c => `${c}49-${c}50-${c}48`); //51
row('Economic UFCF (SBC remains expensed)', c => `${c}16-MAX(0,${c}16)*${taxRate}+${c}20+${c}24-${c}19-${c}23-${c}34`); //52
row('Cash FCF', c => `${c}42+${c}43`); //53
row('Unlevered NOPAT', c => `${c}16-MAX(0,${c}16)*${taxRate}`); //54
row('Operating capital for normalized terminal reinvestment', c => `${c}21+${c}25+${c}33`); //55
if (new Set(rows.slice(3).map(row => row[0])).size !== 52) throw Error('Duplicate schedule labels would lose snapshot rows');
if (rows.length !== 55) throw Error('Schedule layout drift');
await table('Schedules', rows);
async function statement(name, mapping) {
  return table(name, [[`${model.case} — ${name}`], ['USD millions; calculated forecast, not reported source values'], ['Line', ...model.periods.map(p=>p.id)], ...mapping.map(([label,r])=>[label, ...model.periods.map((p,i)=>F(`Schedules!${col(i)}${r}`))])]);
}
await statement('Income', [['Revenue',8],[aggregate ? 'Total operating expenses (before D&A substitution)' : 'Cost of sales (before D&A substitution)',9],[aggregate ? 'Expense detail grouped above' : 'R&D (before D&A substitution)',10],[aggregate ? 'Expense detail grouped above' : 'SG&A (before D&A substitution)',11],['Embedded D&A removed',13],['PP&E depreciation',14],['Intangible amortization',15],['EBIT',16],['Interest expense',35],['Investment income',36],['Pretax income',37],['Tax',38],['Net income',39]]);
await statement('CashFlow', [['Net income',39],['Depreciation',20],['Amortization',24],['SBC addback',40],['Change in NWC (cash use)',34],['CFO',42],['Cash PP&E additions (cash use)',19],['Cash intangible additions (cash use)',23],['CFI',43],['Shareholder distributions (cash use)',41],['CFF',44],['Opening cash',45],['Closing cash',46],['Cash FCF',53],['Economic UFCF (SBC expensed)',52]]);
await statement('BalanceSheet', [['Cash',46],[aggregate ? 'Operating current assets' : 'Receivables',26],['Vendor receivables',27],['Inventory',28],['Other current operating assets (ex intangibles)',29],['PP&E',21],['Total intangibles (current/noncurrent combined)',25],['Total assets (includes static securities/other noncurrent assets)',49],[aggregate ? 'Operating current liabilities' : 'Accounts payable',30],['Deferred revenue',31],['Other current liabilities',32],['Total liabilities (includes static debt/other noncurrent liabilities)',50],['Equity',48],['Balance difference',51]]);
const numericGate = Object.values(indices).map(r=>`ISNUMBER(Inputs!B${r})`).join(',');
const sourceGate = `${I('ttm_revenue')}>0,${aggregate ? `${taxRate}>=0,${taxRate}<1` : `${I('ttm_pretax')}>0,${I('ttm_tax')}>=0,${I('ttm_tax')}<${I('ttm_pretax')}`},${I('shares_proxy')}>0,${Object.entries(model.control_bounds).flatMap(([k,[lo,hi]])=>[`${I(k)}>=${lo}`,`${I(k)}<=${hi}`]).join(',')}`;
await table('Checks', [['Mechanical and review gates'], ['PASS only covers the explicitly implemented relationships; source/estimate caveats remain.'], ['Check', ...model.periods.map(p=>p.id)],
 ['Balance equation', ...model.periods.map((p,i)=>F(`IF(ABS(Schedules!${col(i)}51)<0.000001,"PASS","FAIL")`))],
 ['Cash funded without plug', ...model.periods.map((p,i)=>F(`IF(Schedules!${col(i)}46>=0,"PASS","FAIL")`))],
 ['Asset carrying values nonnegative', ...model.periods.map((p,i)=>F(`IF(AND(Schedules!${col(i)}21>=0,Schedules!${col(i)}25>=0),"PASS","FAIL")`))],
 ['Required numeric/valid inputs', F(`IFERROR(IF(AND(${numericGate},${sourceGate}),"PASS","FAIL"),"FAIL")`)],
 ['Local inputs unchanged', F(`IFERROR(IF(AND(${Object.values(indices).map(r=>`Inputs!B${r}=SavedInputs!B${r}`).join(',')}),"PASS","EDITED_UNREVIEWED"),"EDITED_UNREVIEWED")`)],
 ['Combined mechanical gate', F('IF(AND(COUNTIF(B4:L6,"PASS")=33,B7="PASS"),"PASS","FAIL")')],
]);
const dcfRows = [[`${model.case} — provisional DCF`], ['Development assumptions; USD millions except value/share. Terminal capital normalization; no future cash double count.'], ['Metric','Value'],
 ['Cost of equity', F(`${I('risk_free')}+${I('beta')}*${I('equity_premium')}`)],
 ['Debt weight', F(`${debt}/(${debt}+${I('share_price_proxy')}*${I('shares_proxy')}+${minority})`)],
 ['WACC', F(`B4*(1-B5)+${I('debt_rate')}*(1-${taxRate})*B5`)],
 ['Terminal growth', F(I('terminal_growth'))],
 ['Valuation gate', F('IFERROR(IF(AND(Checks!B9="PASS",B6>B7),"PASS","BLOCKED"),"BLOCKED")')],
 ['PV of explicit UFCF', F(model.periods.map((p,i)=>`Schedules!${col(i)}52/(1+B6)^Schedules!${col(i)}5`).join('+'))],
 ['Terminal NOPAT', F('Schedules!L54*(1+B7)')],
 ['Terminal net reinvestment incl NWC', F('Schedules!L55*B7')],
 ['Terminal UFCF', F('B10-B11')],
 ['PV terminal value', F('IF(B8="PASS",B12/(B6-B7)/(1+B6)^Schedules!L5,"")')],
 ['Enterprise value', F('IF(B8="PASS",B9+B13,"")')],
 ['Opening cash + marketable securities', F(`${I('cash')}+${securities}`)],
 ['Debt claim at carrying-value proxy', F(debt)],
 ['Equity value', F('IF(B8="PASS",B14+B15-B16-B21,"")')],
 ['Diluted share-count proxy', F(I('shares_proxy'))],
 ['Value per share', F('IF(B8="PASS",B17/B18,"")')],
 ['Attached review status', F(`IF(Checks!B8="PASS","${model.review.status}","EDITED_UNREVIEWED")`)],
 ['Minority interest claim at carrying-value proxy', F(minority)],
];
await table('DCF', dcfRows);
const history = [['Reported / derived history'], ['USD millions. TTM = FY + current YTD − prior YTD. Signed capex/cash-flow values preserved.'], ['Metric','Annual','Current YTD','Prior YTD','Derived TTM']];
for (const [name, values] of Object.entries(model.history)) history.push([displayNames[name] ?? name, values.annual, values.current_ytd, values.prior_ytd, F(`B${history.length+1}+C${history.length+1}-D${history.length+1}`)]);
await table('History',history);
await table('Evidence', [['Frozen source audit trail'], ['CSV values are EdgarTools standard values. Display conversion explicitly divides by 1,000,000.'], ['ID','File','Line / CSV record','Concept','Source period','Display value','Units'], ...model.evidence.map(e=>[e.id,e.file,e.line,e.concept,e.column,e.display_value,e.units]), ...(model.allocations ?? []).map((e,i)=>[`A${i+1}`,e.basis,null,e.group,model.measurement_date,e.value,e.units ?? (e.group==='shares_proxy' ? 'million shares; estimate' : 'USD millions; derived grouping')])]);
await table('Review', [[`${model.company_name} | E2E development model`], [`Measurement ${model.measurement_date}; information cutoff ${model.information_cutoff}. All financial assumptions provisional.`], ['Metric','Value'],
 ['Value per share',F('DCF!B19')],['WACC',F('DCF!B6')],['Mechanical gate',F('Checks!B9')],['Analytical review',F('DCF!B20')],['Human financial approval','FALSE'],
 ['Reviewer rationale',model.review.rationale ?? 'Independent review pending'],['Analyst rationale',model.analyst?.rationale ?? 'Agent defaults authorized for E2E testing'],
 ...model.limitations.map((s,i)=>[`Caveat ${i+1}`,s]),
 ['Local edits','Editable inputs invalidate attached review; arbitrary formula changes are not certified. Rebuild through CLI for a new reviewed version.'],
]);
const sensitivity = [['Beta / terminal-growth sensitivity'], ['USD/share. All cells recalculate from the same schedules.'], ['Beta', 'Growth −0.5pp','Base growth','Growth +0.5pp']];
for (const b of [-0.2,0,0.2]) {
  const beta = `(${I('beta')}+(${b}))`;
  const w = `((${I('risk_free')}+${beta}*${I('equity_premium')})*(1-DCF!B5)+${I('debt_rate')}*(1-${taxRate})*DCF!B5)`;
  sensitivity.push([F(beta), ...[-0.005,0,0.005].map(d=>{
    const g=`(${I('terminal_growth')}+(${d}))`;
    const pv=model.periods.map((p,i)=>`Schedules!${col(i)}52/(1+${w})^Schedules!${col(i)}5`).join('+');
    return F(`IF(AND(Checks!B9="PASS",${w}>${g}),(${pv}+(Schedules!L54*(1+${g})-Schedules!L55*${g})/(${w}-${g})/(1+${w})^Schedules!L5+DCF!B15-DCF!B16-DCF!B21)/DCF!B18,"")`);
  })]);
}
await table('Sensitivity',sensitivity);
await wb.calculate();
async function snapshot() {
  const schedules = await wb.getSheet('Schedules');
  const dcf = await wb.getSheet('DCF');
  const checks = await wb.getSheet('Checks');
  const result = { case: model.case, mechanical: await checks.getValue('B9'), valuation_gate: await dcf.getValue('B8'), review_status: await dcf.getValue('B20'), wacc: await dcf.getValue('B6'), enterprise_value: await dcf.getValue('B14'), equity_value: await dcf.getValue('B17'), per_share_value: await dcf.getValue('B19'), schedules: {} };
  for (let r=4;r<=55;r++) result.schedules[rows[r-1][0]] = await Promise.all(model.periods.map((p,i)=>schedules.getValue(`${col(i)}${r}`)));
  result.formula_examples = Object.fromEntries(rows.slice(3).map(r=>[r[0], [r[1].formula,r[2].formula,r[11].formula]]));
  result.dcf_formulas = Object.fromEntries(dcfRows.slice(3).map(r=>[r[0],r[1].formula]));
  return result;
}
try {
  const base = await snapshot();
  // Mandatory local-edit and missing-input proof, restored before export.
  await inputs.setCell(`B${indices.beta}`,model.controls.beta+0.1); await wb.calculate();
  const edited = await snapshot();
  await inputs.setCell(`B${indices.beta}`,model.controls.beta);
  await inputs.setCell(`B${indices.ppe_life}`,null); await wb.calculate();
  const missing = await snapshot();
  await inputs.setCell(`B${indices.ppe_life}`,model.controls.ppe_life); await wb.calculate();
  const restored = await snapshot();
  if (JSON.stringify(restored)!==JSON.stringify(base)) throw Error('Restored model differs');
  const proof = { beta_edit_changes_value: base.valuation_gate === 'PASS' ? edited.per_share_value!==base.per_share_value : null, edit_invalidates_review: edited.review_status==='EDITED_UNREVIEWED', missing_blocks_value: missing.valuation_gate==='BLOCKED' && (missing.per_share_value==='' || missing.per_share_value===null), restored_identical: true };
  if (Object.values(proof).some(x=>x===false)) throw Error(`Local-edit proof failed: ${JSON.stringify(proof)}`);
  const out = resolve(process.argv[3]); await mkdir(dirname(out),{recursive:true});
  await wb.save(out);
  await writeFile(process.argv[4],JSON.stringify({ ...base, proof, input_rows: indices },null,2),{flag:'wx'});
  process.stdout.write(JSON.stringify({ case:model.case,mechanical:base.mechanical,value:base.per_share_value,proof })+'\n');
} finally { wb.dispose(); }
