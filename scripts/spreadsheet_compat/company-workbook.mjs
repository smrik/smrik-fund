import { templateEdits } from "./company-template.mjs";
import { buildStatements } from "./company-statements.mjs";
import { createWorkbook } from "@mog-sdk/sdk";
import { readFile, writeFile, mkdir, access } from "node:fs/promises";
import { dirname, resolve } from "node:path";

const F = (formula) => ({ formula: `=${formula}` });
const col = (i) => String.fromCharCode(66 + i);
const letter = (n) => {
  let s = "";
  for (n++; n; n = Math.floor((n - 1) / 26))
    s = String.fromCharCode(65 + ((n - 1) % 26)) + s;
  return s;
};
const model = JSON.parse(await readFile(process.argv[2], "utf8"));
for (const path of [process.argv[3], process.argv[4]]) {
  try {
    await access(path);
  } catch (error) {
    if (error.code === "ENOENT") continue;
    throw error;
  }
  throw Error(`Refusing to overwrite ${path}`);
}
if (
  model.schema_version !== "company-dcf-development-v1" ||
  model.periods.length !== 11
)
  throw Error("Unsupported model");
const aggregate = model.method === "consolidated-development-v1";
const costComponents = model.operating_costs?.components ?? [];
const displayNames = aggregate
  ? {
      receivables: "Operating current assets (derived aggregate)",
      payables: "Operating current liabilities (derived aggregate)",
      cost_of_sales: "Total operating expenses (revenue minus EBIT)",
      research: "R&D included in aggregate expenses",
      sga: "SG&A included in aggregate expenses",
      products_growth: "Consolidated revenue growth",
      services_growth: "Unused separate-revenue growth",
      Products: "Consolidated",
      Services: "Separate-category",
    }
  : {};
const wb = await createWorkbook({ userTimezone: "UTC" });
await wb.sheets.rename("Sheet1", "Review");
for (const name of [
  "Inputs",
  "SavedInputs",
  "History",
  "Income",
  "BalanceSheet",
  "CashFlow",
  "Assets",
  "WorkingCapital",
  "Stub",
  "DCF",
  "Checks",
  "Evidence",
  "Sensitivity",
])
  await wb.sheets.add(name);

const indices = {};
const edits = templateEdits(
  model.workbook_template,
  model.annual_history?.periods?.length ?? 0,
  indices,
  model.periods.length - (model.periods[0].id.endsWith("_STUB") ? 1 : 0),
);
async function table(name, rows) {
  rows = edits.table(name, rows);
  const sheet = await wb.getSheet(name);
  const width = Math.max(...rows.map((r) => r.length));
  await sheet.setRange(
    `A1:${letter(width - 1)}${rows.length}`,
    rows.map((row) =>
      Array.from(
        { length: width },
        (_, i) =>
          row[i]?.formula ??
          (typeof row[i] === "string" ? null : (row[i] ?? null)),
      ),
    ),
  );
  for (let r = 0; r < rows.length; r++)
    for (let c = 0; c < rows[r].length; c++)
      if (typeof rows[r][c] === "string")
        await sheet.setCell(`${letter(c)}${r + 1}`, rows[r][c], {
          literal: true,
        });
  await sheet.formats.setRange(`A1:${letter(width - 1)}1`, {
    bold: true,
    backgroundColor: "#16324F",
    fontColor: "#FFFFFF",
  });
  await sheet.formats.setRange(`A3:${letter(width - 1)}3`, {
    bold: true,
    backgroundColor: "#DCEAF4",
  });
  if (width > 1 && rows.length > 3)
    await sheet.formats.setRange(`B4:${letter(width - 1)}${rows.length}`, {
      numberFormat: "#,##0.00;(#,##0.00);–",
    });
  for (const edit of edits.customCells(name))
    if (edit.numberFormat)
      await sheet.formats.setRange(`${edit.cell}:${edit.cell}`, {
        numberFormat: edit.numberFormat,
      });
  return sheet;
}
const inputRows = [
  ["Source values and editable development assumptions"],
  [
    "USD millions / million shares; ratio inputs decimal. Blue cells editable; edits invalidate review.",
  ],
  ["Input", "Value", "Basis"],
];
function input(key, value, basis) {
  inputRows.push([
    displayNames[key] ??
      (aggregate
        ? key
            .replace("Products_", "Consolidated revenue — ")
            .replace("Services_", "Separate-category structural zero — ")
        : key),
    value,
    aggregate
      ? `Consolidated method; see allocations and caveats. ${basis}`
      : basis,
  ]);
  indices[key] = inputRows.length;
}
for (const [key, value] of Object.entries(model.opening))
  input(
    key,
    value,
    key === "shares_proxy"
      ? "Reported diluted quarterly weighted-average shares; development valuation proxy, not point-in-time shares"
      : aggregate
        ? "Reported value or explicit derived group; structural zeros identify detail grouped elsewhere. See Evidence."
        : "Reported closing balance; see Evidence",
  );
for (const [key, value] of Object.entries(model.history))
  input(
    `ttm_${key}`,
    value.ttm,
    "Derived FY + current YTD − prior YTD; reported signs preserved",
  );
for (const [segment, values] of Object.entries(model.segments))
  for (const [period, value] of Object.entries(values))
    input(
      `${segment}_${period}`,
      value,
      aggregate
        ? "Consolidated reported revenue; separate-category slots are structural zeros. History and Evidence."
        : "Disclosed product/service view; History and Evidence",
    );
if (model.normalized_tax_rate !== undefined)
  input(
    "normalized_tax_rate",
    model.normalized_tax_rate,
    "Historical effective rate when usable; otherwise explicit 25% development normalization. Reported tax remains in History.",
  );
input(
  "estimated_ttm_ppe_depreciation",
  model.estimated_ttm_ppe_depreciation,
  "ESTIMATE: disclosed annual PP&E / annual combined D&A × TTM combined D&A",
);
for (const [key, value] of Object.entries(model.controls))
  input(
    key,
    value,
    costComponents.some((c) => c.control === key)
      ? "Expense / revenue assumption; default = reconciled TTM expense magnitude / revenue. Includes embedded D&A/SBC."
      : "AGENT-SELECTED DEVELOPMENT ASSUMPTION; not a sourced market observation",
  );
// Forecast-only diagnostic stresses. Reported Inputs/History never change.
const stressKeys = ["opex", "sbc", "capex", "nwc"];
if (model.diagnostic_scenarios)
  for (const key of stressKeys)
    input(
      `stress_${key}`,
      0,
      "Diagnostic forecast ratio delta; restored to zero before export",
    );
const I = (key) => `Inputs!$B$${indices[key]}`;
const stress = (key) => (model.diagnostic_scenarios ? I(`stress_${key}`) : "0");
const inputs = await table("Inputs", inputRows);
await table(
  "SavedInputs",
  inputRows.map((row) => [...row]),
);
for (const key of Object.keys(model.controls)) {
  await inputs.formats.setRange(`B${indices[key]}:B${indices[key]}`, {
    fontColor: "#0066CC",
    backgroundColor: "#FFF2CC",
  });
  await inputs.comments.addNote(`B${indices[key]}`, {
    author: "smrik-fund",
    text: `${inputRows[indices[key] - 1][2]}. ${model.analyst?.rationale ?? "Provisional default for E2E testing."}`,
  });
}
const debt = `(${I("commercial_paper")}+${I("current_debt")}+${I("long_debt")})`;
const minority =
  model.opening.minority_interest_proxy === undefined
    ? "0"
    : I("minority_interest_proxy");
const securities = `(${I("short_investments")}+${I("long_investments")})`;
const taxRate =
  model.controls.forecast_tax_rate !== undefined
    ? I("forecast_tax_rate")
    : model.normalized_tax_rate !== undefined
      ? I("normalized_tax_rate")
      : `(${I("ttm_tax")}/${I("ttm_pretax")})`;
const openingNwc = `(${I("receivables")}+${I("vendor_receivables")}+${I("inventory")}+${I("other_current_assets")}-${I("intangibles_current")}-${I("payables")}-${I("deferred_revenue")})`;
const rows = [
  [`${model.case} — linked provisional schedules`],
  [
    "Development method: declining carrying-balance depreciation; half-period charge on additions; all formulas application-owned.",
  ],
  ["USD millions", ...model.periods.map((p) => p.id)],
];
function row(label, fn) {
  rows.push([label, ...model.periods.map((p, i) => F(fn(col(i), i, p)))]);
}
row("Period fraction (364-day fiscal basis)", (c, i, p) => `${p.fraction}`); // 4
row("Elapsed years (ACT/365)", (c, i, p) => `${p.elapsed}`); // 5
for (const name of ["Products", "Services"])
  row(`${displayNames[name] ?? name} revenue`, (c, i) =>
    i === 0
      ? `(${I(name + "_annual")}-${I(name + "_prior_ytd")})*(1+${I(name.toLowerCase() + "_growth")})`
      : i === 1
        ? `(${I(name + "_current_ytd")}+B${name === "Products" ? 6 : 7})*(1+${I(name.toLowerCase() + "_growth")})`
        : `${col(i - 1)}${name === "Products" ? 6 : 7}*(1+${I(name.toLowerCase() + "_growth")})`,
  );
row("Revenue", (c) => `SUM(${c}6:${c}7)`); //8
for (const name of ["cost_of_sales", "research", "sga"])
  row(displayNames[name] ?? name, (c) =>
    name === "cost_of_sales" && costComponents.length
      ? `${c}8*(${costComponents.map((x) => I(x.control)).join("+")})`
      : `${c}8*${I("ttm_" + name)}/${I("ttm_revenue")}`,
  ); //9-11
row(
  "Gross operating costs (includes embedded D&A and SBC)",
  (c) => `SUM(${c}9:${c}11)+${c}8*(${stress("opex")}+${stress("sbc")})`,
); //12
row(
  "Estimated embedded D&A removed",
  (c) => `${c}8*${I("ttm_da")}/${I("ttm_revenue")}`,
); //13
row("Scheduled PP&E depreciation", (c) => `${c}20`); //14
row("Scheduled intangible amortization", (c) => `${c}24`); //15
row("EBIT", (c) => `${c}8-${c}12+${c}13-${c}14-${c}15`); //16
row(
  "Estimated embedded PP&E component (diagnostic)",
  (c) => `${c}8*${I("estimated_ttm_ppe_depreciation")}/${I("ttm_revenue")}`,
); //17
row("Opening PP&E", (c, i) => (i === 0 ? I("ppe") : `${col(i - 1)}21`)); //18
row(
  "Cash PP&E additions",
  (c) =>
    `${c}8*((-${I("ttm_capex_cash")})/${I("ttm_revenue")}+${stress("capex")})`,
); //19
row(
  "PP&E depreciation: declining balance + half-period additions",
  (c) =>
    `MIN(${c}18,${c}18/${I("ppe_life")}*${c}4)+MIN(${c}19,${c}19/${I("ppe_life")}*0.5*${c}4)`,
); //20
row("Closing PP&E", (c) => `${c}18+${c}19-${c}20`); //21
row("Opening total intangibles", (c, i) =>
  i === 0
    ? `${I("intangibles_noncurrent")}+${I("intangibles_current")}`
    : `${col(i - 1)}25`,
); //22
row(
  "Cash intangible additions (estimated)",
  (c) => `${c}8*${I("intangible_additions_ratio")}`,
); //23
row(
  "Intangible amortization: declining balance",
  (c) =>
    `MIN(${c}22,${c}22/${I("intangible_life")}*${c}4)+MIN(${c}23,${c}23/${I("intangible_life")}*0.5*${c}4)`,
); //24
row("Closing total intangibles", (c) => `${c}22+${c}23-${c}24`); //25
for (const key of ["receivables", "vendor_receivables"])
  row(
    displayNames[key] ?? key,
    (c) =>
      `${I(key)}*${c}8/${c}4/${I("ttm_revenue")}${key === "receivables" ? `+${c}8/${c}4*${stress("nwc")}` : ""}`,
  ); //26-27
row(
  "Inventory",
  (c) => `${I("inventory")}*${c}9/${c}4/${I("ttm_cost_of_sales")}`,
); //28
row(
  "Other current operating assets excluding disclosed intangibles",
  (c) =>
    `(${I("other_current_assets")}-${I("intangibles_current")})*${c}8/${c}4/${I("ttm_revenue")}`,
); //29
row(
  aggregate ? "Operating current liabilities" : "Accounts payable",
  (c) => `${I("payables")}*${c}9/${c}4/${I("ttm_cost_of_sales")}`,
); //30
row(
  "Deferred revenue",
  (c) => `${I("deferred_revenue")}*${c}8/${c}4/${I("ttm_revenue")}`,
); //31
row(
  "Other current liabilities (held flat; includes tax/accrual uncertainty)",
  () => I("other_current_liabilities"),
); //32
row("Operating NWC", (c) => `SUM(${c}26:${c}29)-${c}30-${c}31`); //33
row(
  "Change in NWC",
  (c, i) => `${c}33-(${i === 0 ? openingNwc : col(i - 1) + "33"})`,
); //34
row(
  "Interest expense on constant refinanced debt",
  (c) => `${debt}*${I("debt_rate")}*${c}4`,
); //35
row(
  "Investment income (scenario risk-free yield)",
  (c) => `${securities}*${I("risk_free")}*${c}4`,
); //36
row("Pretax income", (c) => `${c}16-${c}35+${c}36`); //37
row(
  "Book/cash tax (same timing assumption)",
  (c) => `MAX(0,${c}37)*${taxRate}`,
); //38
row("Net income", (c) => `${c}37-${c}38`); //39
row(
  "SBC cash-flow addback / equity contribution",
  (c) => `${c}8*(${I("ttm_sbc")}/${I("ttm_revenue")}+${stress("sbc")})`,
); //40
row(
  "Cash shareholder distributions (dividend-equivalent policy)",
  (c) => `MAX(0,${c}39)*${I("payout_ratio")}`,
); //41
row("CFO", (c) => `${c}39+${c}20+${c}24+${c}40-${c}34`); //42
row("CFI", (c) => `-${c}19-${c}23`); //43
row("CFF (zero net debt issuance; refinancing assumption)", (c) => `-${c}41`); //44
row("Opening cash", (c, i) => (i === 0 ? I("cash") : `${col(i - 1)}46`)); //45
row("Closing cash", (c) => `${c}45+${c}42+${c}43+${c}44`); //46
row("Opening equity", (c, i) => (i === 0 ? I("equity") : `${col(i - 1)}48`)); //47
row("Closing equity", (c) => `${c}47+${c}39+${c}40-${c}41`); //48
row(
  "Total assets",
  (c) =>
    `${c}46+${securities}+${c}21+${c}25+SUM(${c}26:${c}29)+${I("other_noncurrent_assets")}`,
); //49
row(
  "Total liabilities",
  (c) => `${c}30+${c}31+${c}32+${debt}+${I("other_noncurrent_liabilities")}`,
); //50
row("Balance difference (no cash/equity plug)", (c) => `${c}49-${c}50-${c}48`); //51
row(
  "Economic UFCF (SBC remains expensed)",
  (c) => `${c}16-MAX(0,${c}16)*${taxRate}+${c}20+${c}24-${c}19-${c}23-${c}34`,
); //52
row("Cash FCF", (c) => `${c}42+${c}43`); //53
row("Unlevered NOPAT", (c) => `${c}16-MAX(0,${c}16)*${taxRate}`); //54
row(
  "Operating capital for normalized terminal reinvestment",
  (c) => `${c}21+${c}25+${c}33`,
); //55
if (new Set(rows.slice(3).map((row) => row[0])).size !== 52)
  throw Error("Duplicate schedule labels would lose snapshot rows");
if (rows.length !== 55) throw Error("Schedule layout drift");
const view = await buildStatements({ wb, table, model, rows, I });
const R = view.ref;
const numericGate = Object.values(indices)
  .map((r) => `ISNUMBER(Inputs!B${r})`)
  .join(",");
const sourceGate = `${I("ttm_revenue")}>0,${aggregate ? `${taxRate}>=0,${taxRate}<1` : `${I("ttm_pretax")}>0,${I("ttm_tax")}>=0,${I("ttm_tax")}<${I("ttm_pretax")}`},${I("shares_proxy")}>0,${Object.entries(
  model.control_bounds,
)
  .flatMap(([k, [lo, hi]]) => [`${I(k)}>=${lo}`, `${I(k)}<=${hi}`])
  .join(",")}`;
await table("Checks", [
  ["Mechanical and review gates"],
  [
    "PASS only covers the explicitly implemented relationships; source/estimate caveats remain.",
  ],
  ["Check", ...model.periods.map((p) => p.id)],
  [
    "Balance equation",
    ...model.periods.map((p, i) =>
      F(`IF(ABS(${R(i, 51)})<0.000001,"PASS","FAIL")`),
    ),
  ],
  [
    "Cash funded without plug",
    ...model.periods.map((p, i) => F(`IF(${R(i, 46)}>=0,"PASS","FAIL")`)),
  ],
  [
    "Asset carrying values nonnegative",
    ...model.periods.map((p, i) =>
      F(`IF(AND(${R(i, 21)}>=0,${R(i, 25)}>=0),"PASS","FAIL")`),
    ),
  ],
  [
    "Required numeric/valid inputs",
    F(`IFERROR(IF(AND(${numericGate},${sourceGate}),"PASS","FAIL"),"FAIL")`),
  ],
  [
    "Local inputs unchanged",
    F(
      `IFERROR(IF(AND(${Object.values(indices)
        .map((r) => `Inputs!B${r}=SavedInputs!B${r}`)
        .join(",")}),"PASS","EDITED_UNREVIEWED"),"EDITED_UNREVIEWED")`,
    ),
  ],
  [
    "Combined mechanical gate",
    F('IF(AND(COUNTIF(B4:L6,"PASS")=33,B7="PASS"),"PASS","FAIL")'),
  ],
]);
const dcfRows = [
  [`${model.case} — provisional DCF`],
  [
    "Development assumptions; USD millions except value/share. Terminal capital normalization; no future cash double count.",
  ],
  ["Metric", "Value"],
  [
    "Cost of equity",
    F(`${I("risk_free")}+${I("beta")}*${I("equity_premium")}`),
  ],
  [
    "Debt weight",
    F(
      `${debt}/(${debt}+${I("share_price_proxy")}*${I("shares_proxy")}+${minority})`,
    ),
  ],
  ["WACC", F(`B4*(1-B5)+${I("debt_rate")}*(1-${taxRate})*B5`)],
  ["Terminal growth", F(I("terminal_growth"))],
  [
    "Valuation gate",
    F('IFERROR(IF(AND(Checks!B9="PASS",B6>B7),"PASS","BLOCKED"),"BLOCKED")'),
  ],
  [
    "PV of explicit UFCF",
    F(model.periods.map((p, i) => `${R(i, 52)}/(1+B6)^${R(i, 5)}`).join("+")),
  ],
  ["Terminal NOPAT", F(`${R(10, 54)}*(1+B7)`)],
  ["Terminal net reinvestment incl NWC", F(`${R(10, 55)}*B7`)],
  ["Terminal UFCF", F("B10-B11")],
  ["PV terminal value", F(`IF(B8="PASS",B12/(B6-B7)/(1+B6)^${R(10, 5)},"")`)],
  ["Enterprise value", F('IF(B8="PASS",B9+B13,"")')],
  ["Opening cash + marketable securities", F(`${I("cash")}+${securities}`)],
  ["Debt claim at carrying-value proxy", F(debt)],
  ["Equity value", F('IF(B8="PASS",B14+B15-B16-B21,"")')],
  ["Diluted share-count proxy", F(I("shares_proxy"))],
  ["Value per share", F('IF(B8="PASS",B17/B18,"")')],
  [
    "Attached review status",
    F(`IF(Checks!B8="PASS","${model.review.status}","EDITED_UNREVIEWED")`),
  ],
  ["Minority interest claim at carrying-value proxy", F(minority)],
];
// Annual context is separate from discounted future flows. TTM is never discounted.
while (dcfRows.length < 44) dcfRows.push([]);
for (let r = 0; r < view.grids.DCF.length; r++)
  if (view.grids.DCF[r]?.length) dcfRows[r] = view.grids.DCF[r];
dcfRows[22] = [
  "PV of remaining fiscal-year cash flows",
  view.hasStub ? F(`${R(0, 52)}/(1+B6)^${R(0, 5)}`) : 0,
];
dcfRows[23] = [
  "Past periods are context only. Initial remainder is in Stub; annual forecast PV excludes it here.",
];
dcfRows[24] = view.headings;
for (const [r, label, metric] of [
  [26, "Revenue", 8],
  [27, "EBIT", 16],
  [29, "Depreciation / amortization", null],
  [30, "Cash capital investment (cash use)", null],
  [31, "Change in NWC (cash use)", 34],
  [32, "Economic UFCF", 52],
  [35, "Cash FCF", 53],
  [37, "WACC", null],
  [38, "Discount factor", null],
  [39, "PV of annual UFCF", null],
]) {
  dcfRows[r - 1][0] = label;
  for (const p of view.forecast) {
    const c = view.column(p.index),
      j = c.charCodeAt(0) - 65;
    dcfRows[r - 1][j] = F(
      metric
        ? R(p.index, metric)
        : r === 29
          ? `${R(p.index, 20)}+${R(p.index, 24)}`
          : r === 30
            ? `${R(p.index, 19)}+${R(p.index, 23)}`
            : r === 37
              ? "$B$6"
              : r === 38
                ? `1/(1+$B$6)^${R(p.index, 5)}`
                : `${R(p.index, 52)}*${c}38`,
    );
  }
}
for (let j = 1; j <= view.historyColumns + 1; j++) {
  const c = letter(j);
  dcfRows[25][j] = F(`IF(ISNUMBER(Income!${c}8),Income!${c}8,"")`);
  dcfRows[26][j] = F(`IF(ISNUMBER(Income!${c}38),Income!${c}38,"")`);
  dcfRows[28][j] = F(`IF(ISNUMBER(Assets!${c}6),Assets!${c}6,"")`);
  dcfRows[29][j] = F(`IF(ISNUMBER(Assets!${c}11),Assets!${c}11,"")`);
  dcfRows[30][j] = F(
    `IF(ISNUMBER(WorkingCapital!${c}25),WorkingCapital!${c}25,"")`,
  );
  dcfRows[34][j] = F(`IF(ISNUMBER(CashFlow!${c}33),CashFlow!${c}33,"")`);
}
await table("DCF", dcfRows);
// TTM drivers link to the visible reconstruction rather than duplicated literals.
for (const [key, r] of Object.entries(view.bridges))
  await inputs.setCell(`B${indices["ttm_" + key]}`, `=History!E${r}`);
await table("Evidence", [
  ["Frozen source audit trail"],
  [
    "CSV values are EdgarTools standard values. Display conversion explicitly divides by 1,000,000.",
  ],
  [
    "ID",
    "File / calculation basis",
    "Line / CSV record",
    "Concept",
    "Source period",
    "Display value",
    "Units",
    "SEC filing URL",
  ],
  ...model.evidence.map((e) => [
    e.id,
    e.file,
    e.line,
    e.concept,
    e.column,
    e.display_value,
    e.units,
    e.source_url ?? null,
  ]),
  ...(model.allocations ?? []).map((e, i) => [
    `A${i + 1}`,
    e.basis,
    null,
    e.group,
    model.measurement_date,
    e.value,
    e.units ??
      (e.group === "shares_proxy"
        ? "million shares; estimate"
        : "USD millions; derived grouping"),
  ]),
  ...(model.annual_history?.periods ?? []).flatMap((p) =>
    Object.entries(p.groups ?? {}).map(([key, g]) => [
      "Derived",
      g.basis,
      null,
      key,
      p.end,
      g.value,
      "USD millions; derived",
      null,
    ]),
  ),
]);
await table("Review", [
  [`${model.company_name} | E2E development model`],
  [
    `Measurement ${model.measurement_date}; information cutoff ${model.information_cutoff}. All financial assumptions provisional.`,
  ],
  ["Metric", "Value"],
  ["Value per share", F("DCF!B19")],
  ["WACC", F("DCF!B6")],
  ["Calculation integrity", F("Checks!B9")],
  [
    "Decision readiness",
    "Screen-grade: provisional assumptions; financial review pending",
  ],
  ["Human financial approval", "FALSE"],
  [
    "Reviewer rationale",
    model.review.rationale ?? "Independent review pending",
  ],
  [
    "Analyst rationale",
    model.analyst?.rationale ?? "Agent defaults authorized for E2E testing",
  ],
  ...(model.workbook_template
    ? [
        [
          "Excel template",
          `${model.workbook_template.sha256}; ${Object.values(model.workbook_template.changes).reduce((n, cells) => n + Object.keys(cells).length, 0)} edited cells. Frozen template.xlsx and template.json accompany this run.`,
        ],
      ]
    : []),
  ...model.limitations.map((s, i) => [`Caveat ${i + 1}`, s]),
  [
    "Local edits",
    "Editable inputs invalidate attached review; arbitrary formula changes are not certified. Rebuild through CLI for a new reviewed version.",
  ],
]);
const sensitivity = [
  ["Beta / terminal-growth sensitivity"],
  ["USD/share. All cells recalculate from the same schedules."],
  ["Beta", "Growth −0.5pp", "Base growth", "Growth +0.5pp"],
];
for (const b of [-0.2, 0, 0.2]) {
  const beta = `(${I("beta")}+(${b}))`;
  const w = `((${I("risk_free")}+${beta}*${I("equity_premium")})*(1-DCF!B5)+${I("debt_rate")}*(1-${taxRate})*DCF!B5)`;
  sensitivity.push([
    F(beta),
    ...[-0.005, 0, 0.005].map((d) => {
      const g = `(${I("terminal_growth")}+(${d}))`;
      const pv = model.periods
        .map((p, i) => `${R(i, 52)}/(1+${w})^${R(i, 5)}`)
        .join("+");
      return F(
        `IF(AND(Checks!B9="PASS",${w}>${g}),(${pv}+(${R(10, 54)}*(1+${g})-${R(10, 55)}*${g})/(${w}-${g})/(1+${w})^${R(10, 5)}+DCF!B15-DCF!B16-DCF!B21)/DCF!B18,"")`,
      );
    }),
  ]);
}
await table("Sensitivity", sensitivity);
await wb.calculate();
async function snapshot() {
  const dcf = await wb.getSheet("DCF");
  const checks = await wb.getSheet("Checks");
  const result = {
    case: model.case,
    mechanical: await checks.getValue("B9"),
    valuation_gate: await dcf.getValue("B8"),
    review_status: await dcf.getValue("B20"),
    wacc: await dcf.getValue("B6"),
    enterprise_value: await dcf.getValue("B14"),
    equity_value: await dcf.getValue("B17"),
    per_share_value: await dcf.getValue("B19"),
    schedules: {},
    schedule_cells: {},
    historical_checks: view.historyChecks.map(edits.address),
    template: model.workbook_template
      ? {
          sha256: model.workbook_template.sha256,
          edited_cells: Object.values(model.workbook_template.changes).reduce(
            (n, cells) => n + Object.keys(cells).length,
            0,
          ),
        }
      : null,
    presentation: {
      history_columns: view.historyColumns,
      headers: view.headings,
      row_maps: model.workbook_template?.row_maps ?? {},
      drivers: Object.fromEntries(
        Object.entries(view.drivers).map(([sheet, rows]) => [
          sheet,
          Object.fromEntries(
            Object.entries(rows).map(([r, v]) => [edits.row(sheet, r), v]),
          ),
        ]),
      ),
      income_percent_rows: view.incomePercentRows.map((r) =>
        edits.row("Income", r),
      ),
    },
  };
  for (let r = 4; r <= 55; r++) {
    const cells = model.periods.map((p, i) =>
      edits.address(view.address(i, r)),
    );
    result.schedule_cells[rows[r - 1][0]] = cells;
    result.schedules[rows[r - 1][0]] = await Promise.all(
      cells.map(async (a) =>
        a.constant === 0 ? 0 : (await wb.getSheet(a.sheet)).getValue(a.cell),
      ),
    );
  }
  result.formula_examples = Object.fromEntries(
    rows.slice(3).map((r, offset) => [
      r[0],
      [0, 1, 10].map((i) => {
        const a = edits.address(view.address(i, offset + 4));
        if (a.constant === 0) return "=0";
        const row = Number(a.cell.replace(/[A-Z]/g, ""));
        const column = [...a.cell.replace(/\d/g, "")].reduce(
          (n, c) => n * 26 + c.charCodeAt(0) - 64,
          0,
        );
        return (
          edits.rendered[a.sheet]?.[row - 1]?.[column - 1]?.formula ?? null
        );
      }),
    ]),
  );
  result.operating_checks = [];
  for (const p of view.forecast) {
    for (const r of [11, 14, 17, 20, 26, 29, 32, 35, 36, 38]) {
      const cell = `${view.column(p.index)}${edits.row("Income", r)}`;
      const value = await (await wb.getSheet("Income")).getValue(cell);
      if (typeof value === "number")
        result.operating_checks.push({ sheet: "Income", cell, value });
    }
  }
  result.template_cells = [];
  for (const name of Object.keys(model.workbook_template?.changes ?? {})) {
    const sheet = await wb.getSheet(name);
    for (const edit of edits.customCells(name)) {
      const value = await sheet.getValue(edit.cell);
      if (
        typeof value === "string" &&
        /^#(REF!|DIV\/0!|VALUE!|NAME\?|N\/A|NUM!|NULL!|SPILL!|CALC!)/.test(
          value,
        )
      )
        throw Error(`Template formula error: ${name}!${edit.cell}: ${value}`);
      result.template_cells.push({
        sheet: name,
        cell: edit.cell,
        value,
        formula: edit.value?.formula ?? null,
        number_format: edit.numberFormat ?? null,
      });
    }
  }
  result.dcf_formulas = Object.fromEntries(
    dcfRows.slice(3, 21).map((r) => [r[0], edits.formula(r[1].formula, "DCF")]),
  );
  return result;
}
try {
  const base = await snapshot();
  if (base.mechanical !== "PASS" || base.valuation_gate !== "PASS") {
    await mkdir(dirname(resolve(process.argv[4])), { recursive: true });
    await writeFile(
      process.argv[4],
      JSON.stringify({ ...base, input_rows: indices }, null, 2),
      { flag: "wx" },
    );
    throw Error(
      "Calculated company model is blocked; inspect preserved snapshot",
    );
  }
  // Mandatory local-edit and missing-input proof, restored before export.
  await inputs.setCell(`B${indices.beta}`, model.controls.beta + 0.1);
  await wb.calculate();
  const edited = await snapshot();
  await inputs.setCell(`B${indices.beta}`, model.controls.beta);
  await inputs.setCell(`B${indices.ppe_life}`, null);
  await wb.calculate();
  const missing = await snapshot();
  await inputs.setCell(`B${indices.ppe_life}`, model.controls.ppe_life);
  await wb.calculate();
  const restored = await snapshot();
  if (JSON.stringify(restored) !== JSON.stringify(base))
    throw Error("Restored model differs");
  const proof = {
    beta_edit_changes_value:
      base.valuation_gate === "PASS"
        ? edited.per_share_value !== base.per_share_value
        : null,
    edit_invalidates_review: edited.review_status === "EDITED_UNREVIEWED",
    missing_blocks_value:
      missing.valuation_gate === "BLOCKED" &&
      (missing.per_share_value === "" || missing.per_share_value === null),
    restored_identical: true,
  };
  let diagnostics;
  if (model.diagnostic_scenarios) {
    diagnostics = [];
    const allowed = new Set([
      ...Object.keys(model.controls),
      ...stressKeys.map((k) => `stress_${k}`),
    ]);
    const dcf = await wb.getSheet("DCF");
    const checks = await wb.getSheet("Checks");
    for (const scenario of model.diagnostic_scenarios) {
      if (!Object.keys(scenario.inputs).length)
        throw Error("Empty diagnostic stress");
      for (const [key, value] of Object.entries(scenario.inputs)) {
        if (!allowed.has(key) || !Number.isFinite(value))
          throw Error("Invalid diagnostic input");
        await inputs.setCell(`B${indices[key]}`, value);
      }
      await wb.calculate();
      const mechanical = await checks.getValue("B9");
      const valuation = await dcf.getValue("B8");
      const value = await dcf.getValue("B19");
      diagnostics.push({
        id: scenario.id,
        mechanical,
        valuation_gate: valuation,
        per_share_value:
          mechanical === "PASS" &&
          valuation === "PASS" &&
          typeof value === "number" &&
          Number.isFinite(value)
            ? value
            : null,
      });
      for (const key of Object.keys(scenario.inputs))
        await inputs.setCell(
          `B${indices[key]}`,
          key.startsWith("stress_") ? 0 : model.controls[key],
        );
    }
    await wb.calculate();
    if (JSON.stringify(await snapshot()) !== JSON.stringify(base))
      throw Error("Diagnostic restoration changed baseline");
    proof.diagnostic_baseline_restored = true;
  }
  if (costComponents.length) {
    const control = costComponents[0].control;
    await inputs.setCell(
      `B${indices[control]}`,
      model.controls[control] + 0.01,
    );
    await wb.calculate();
    const costEdit = await snapshot();
    const firstAnnual = view.forecast[0].index;
    const revenue = base.schedules.Revenue[firstAnnual];
    proof.cost_edit_changes_ebit =
      Math.abs(
        base.schedules.EBIT[firstAnnual] -
          costEdit.schedules.EBIT[firstAnnual] -
          revenue * 0.01,
      ) < 1e-6;
    proof.cost_edit_changes_value =
      costEdit.per_share_value < base.per_share_value;
    proof.cost_edit_invalidates_review =
      costEdit.review_status === "EDITED_UNREVIEWED";
    await inputs.setCell(`B${indices[control]}`, null);
    await wb.calculate();
    proof.missing_cost_blocks_value =
      (await snapshot()).valuation_gate === "BLOCKED";
    await inputs.setCell(`B${indices[control]}`, model.controls[control]);
    await wb.calculate();
    if (JSON.stringify(await snapshot()) !== JSON.stringify(base))
      throw Error("Expense driver restoration changed model");
  }
  if (Object.values(proof).some((x) => x === false))
    throw Error(`Local-edit proof failed: ${JSON.stringify(proof)}`);
  const out = resolve(process.argv[3]);
  await mkdir(dirname(out), { recursive: true });
  // Write sparse statement rows cell-by-cell before export. The SDK bulk writer
  // calculates these rows but can omit formulas after leading blank actuals.
  for (const [name, grid] of Object.entries(edits.rendered)) {
    if (name === "DCF") continue;
    const sheet = await wb.getSheet(name);
    for (let r = 0; r < grid.length; r++)
      for (let c = 0; c < (grid[r]?.length ?? 0); c++)
        if (grid[r][c]?.formula)
          await sheet.setCell(`${letter(c)}${r + 1}`, grid[r][c].formula);
  }
  await wb.calculate();
  await wb.save(out);
  await writeFile(
    process.argv[4],
    JSON.stringify(
      {
        ...base,
        proof,
        input_rows: indices,
        ...(diagnostics ? { diagnostics } : {}),
      },
      null,
      2,
    ),
    { flag: "wx" },
  );
  process.stdout.write(
    JSON.stringify({
      case: model.case,
      mechanical: base.mechanical,
      value: base.per_share_value,
      proof,
    }) + "\n",
  );
} finally {
  wb.dispose();
}
