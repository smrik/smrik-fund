/** Period-aligned statements. Forecast formulas live on their owning statement;
 * the only separate calculations are asset roll-forwards, working capital and
 * the short initial DCF remainder. Raw annual observations remain in History. */
export async function buildStatements({ wb, table, model, rows, I }) {
  const F = (x) => ({ formula: `=${x}` });
  const letter = (n) => {
    let s = "";
    for (n++; n; n = Math.floor((n - 1) / 26))
      s = String.fromCharCode(65 + ((n - 1) % 26)) + s;
    return s;
  };
  const aggregate = model.method === "consolidated-development-v1";
  const annuals = model.annual_history?.periods ?? [];
  const n = annuals.length,
    ttm = letter(n + 1),
    firstForecast = n + 2;
  const hasStub = model.periods[0].id.endsWith("_STUB");
  const forecast = model.periods
    .map((p, i) => ({ ...p, index: i }))
    .filter((p) => !hasStub || p.index > 0);
  const column = (i) => letter(firstForecast + i - (hasStub ? 1 : 0));
  // Metric IDs correspond to the explicit forecast equations in company-workbook.
  const locations = {
    4: ["Income", 5],
    5: ["DCF", 44],
    6: ["Income", 62],
    7: ["Income", 64],
    8: ["Income", 8],
    9: ["Income", 11],
    10: ["Income", 20],
    11: ["Income", 17],
    12: ["Income", 26],
    13: ["Income", 29],
    14: ["Income", 35],
    15: ["Income", 36],
    16: ["Income", 38],
    17: ["Assets", 8],
    18: ["Assets", 10],
    19: ["Assets", 11],
    20: ["Assets", 13],
    21: ["Assets", 14],
    22: ["Assets", 18],
    23: ["Assets", 19],
    24: ["Assets", 21],
    25: ["Assets", 22],
    26: ["WorkingCapital", 8],
    27: ["WorkingCapital", 10],
    28: ["WorkingCapital", 12],
    29: ["WorkingCapital", 14],
    30: ["WorkingCapital", 18],
    31: ["WorkingCapital", 20],
    32: ["BalanceSheet", 21],
    33: ["WorkingCapital", 23],
    34: ["WorkingCapital", 25],
    35: ["Income", 41],
    36: ["Income", 44],
    37: ["Income", 47],
    38: ["Income", 48],
    39: ["Income", 51],
    40: ["CashFlow", 11],
    41: ["CashFlow", 24],
    42: ["CashFlow", 14],
    43: ["CashFlow", 20],
    44: ["CashFlow", 25],
    45: ["CashFlow", 28],
    46: ["CashFlow", 30],
    47: ["BalanceSheet", 26],
    48: ["BalanceSheet", 29],
    49: ["BalanceSheet", 15],
    50: ["BalanceSheet", 24],
    51: ["BalanceSheet", 32],
    52: ["CashFlow", 35],
    53: ["CashFlow", 33],
    54: ["DCF", 34],
    55: ["DCF", 42],
  };
  if (aggregate) {
    locations[6] = ["Income", 8];
    locations[9] = ["Income", 26];
  }
  const constant = (r) => aggregate && [7, 10, 11].includes(r);
  const address = (i, r) =>
    hasStub && i === 0
      ? { sheet: "Stub", cell: `B${r}` }
      : constant(r)
        ? { constant: 0 }
        : { sheet: locations[r][0], cell: `${column(i)}${locations[r][1]}` };
  const ref = (i, r) => {
    const a = address(i, r);
    return a.constant === 0 ? "0" : `${a.sheet}!${a.cell}`;
  };
  // Relocate existing tested equations; expand SUM ranges because adjacent metric
  // IDs are deliberately separated by visible driver rows in the new layout.
  function relocate(formula, targetSheet) {
    const source = formula
      .replace(/^=/, "")
      .replace(/([B-L])(\d+):\1(\d+)/g, (_, c, a, b) =>
        Array.from(
          { length: Number(b) - Number(a) + 1 },
          (_, i) => `${c}${Number(a) + i}`,
        ).join(","),
      );
    return source.replace(
      /(?:(\w+)!)?(\$?[A-Z]+)(\$?\d+)/g,
      (whole, sheet, c, r) => {
        if (sheet && sheet !== "Schedules") return whole;
        const i = c.replaceAll("$", "").charCodeAt(0) - 66,
          metric = Number(r.replaceAll("$", ""));
        if (i < 0 || i > 10 || !locations[metric]) return whole;
        const a = address(i, metric);
        if (a.constant === 0) return "0";
        return a.sheet === targetSheet ? a.cell : `${a.sheet}!${a.cell}`;
      },
    );
  }
  const headings = [
    "Line",
    ...annuals.map((p) => `${p.label}A\n${p.end}`),
    `TTM\n${model.measurement_date}`,
    ...forecast.map((p) => `${p.id}E\n${p.end}`),
  ];
  const grids = {};
  for (const name of [
    "Income",
    "BalanceSheet",
    "CashFlow",
    "Assets",
    "WorkingCapital",
  ]) {
    grids[name] = [
      [
        `${model.case} — ${name === "Assets" ? "PP&E and finite intangibles" : name === "WorkingCapital" ? "Working capital" : name}`,
      ],
      [
        "USD millions. Actuals | TTM / latest balances | annual forecasts. Blank = unavailable or not comparable.",
      ],
      [...headings],
    ];
  }
  grids.BalanceSheet[2][n + 1] = `Latest balance\n${model.measurement_date}`;
  const historyKeys = [
    ...new Set(annuals.flatMap((p) => Object.keys(p.values))),
  ];
  for (const k of Object.keys(model.history))
    if (!historyKeys.includes(k)) historyKeys.push(k);
  for (const k of ["operating_expenses", "equity", "cash_fcf"])
    if (!historyKeys.includes(k)) historyKeys.push(k);
  const historyRows = [
    ["Historical observations and explicit derived groups"],
    [
      model.annual_history?.policy ??
        "Existing frozen FY / YTD inputs; capture a new case for annual history.",
    ],
    ["Metric", ...headings.slice(1, n + 2)],
  ];
  const hrow = {};
  for (const key of historyKeys) {
    hrow[key] = historyRows.length + 1;
    historyRows.push([
      key,
      ...annuals.map((p) => p.values[key] ?? null),
      model.history[key]?.ttm ?? null,
    ]);
  }
  const H = (key, c) => (hrow[key] ? `History!${c}${hrow[key]}` : null);
  const both = (a, b, op) => F(`IF(COUNT(${a},${b})=2,${a}${op}${b},"")`);
  for (let j = 0; j < n; j++) {
    const c = letter(j + 1),
      v = annuals[j].values;
    historyRows[hrow.operating_expenses - 1][j + 1] = both(
      H("revenue", c),
      H("ebit", c),
      "-",
    );
    historyRows[hrow.cash_fcf - 1][j + 1] = both(H("cfo", c), H("cfi", c), "+");
    historyRows[hrow.equity - 1][j + 1] =
      v.equity_total != null
        ? F(H("equity_total", c))
        : v.equity_parent != null
          ? F(H("equity_parent", c))
          : null;
    if (
      v.liabilities == null &&
      v.liabilities_equity != null &&
      (v.equity_total != null || v.equity_parent != null)
    )
      historyRows[hrow.liabilities - 1][j + 1] = both(
        H("liabilities_equity", c),
        H("equity", c),
        "-",
      );
  }
  historyRows[hrow.operating_expenses - 1][n + 1] = both(
    H("revenue", ttm),
    H("ebit", ttm),
    "-",
  );
  historyRows[hrow.cash_fcf - 1][n + 1] = both(
    H("cfo", ttm),
    H("cfi", ttm),
    "+",
  );
  // Preserve the actual TTM reconstruction as a separate, dated bridge.
  historyRows.push(
    [],
    ["TTM reconstruction — flows only"],
    [
      "Metric",
      `FY ended ${model.history_windows?.annual?.end_date ?? "latest annual"}`,
      `Current YTD ${model.history_windows?.current_ytd?.end_date ?? "not applicable"}`,
      `Prior YTD ${model.history_windows?.prior_ytd?.end_date ?? "not applicable"}`,
      "Derived TTM",
    ],
  );
  const bridges = {};
  for (const [key, v] of Object.entries(model.history)) {
    const r = historyRows.length + 1;
    bridges[key] = r;
    historyRows.push([
      key,
      v.annual,
      v.current_ytd,
      v.prior_ytd,
      F(`B${r}+C${r}-D${r}`),
    ]);
    historyRows[hrow[key] - 1][n + 1] = F(`E${r}`);
  }
  historyRows.push(
    [],
    ["Historical comparability"],
    ...(model.annual_history?.issues ?? []).map((x) => [x]),
    ["Fiscal period length", ...annuals.map((p) => p.days)],
  );
  await table("History", historyRows);
  const historicalChecks = [];
  for (let j = 0; j < n; j++)
    for (const [key, v] of Object.entries(annuals[j].values))
      if (v != null)
        historicalChecks.push({
          sheet: "History",
          cell: `${letter(j + 1)}${hrow[key]}`,
          value: v,
        });
  function put(sheet, r, label, j, value) {
    const g = grids[sheet] ?? (grids[sheet] = []);
    while (g.length < r) g.push([]);
    g[r - 1][0] = label;
    g[r - 1][j] = value;
  }
  function actual(sheet, r, label, key, kind = "flow") {
    for (let j = 0; j <= n; j++) {
      let v = null;
      if (j < n && H(key, letter(j + 1)))
        v = F(
          `IF(ISNUMBER(${H(key, letter(j + 1))}),${H(key, letter(j + 1))},"")`,
        );
      if (j === n && kind === "flow" && H(key, ttm))
        v = F(`IF(ISNUMBER(${H(key, ttm)}),${H(key, ttm)},"")`);
      if (j === n && kind === "balance" && model.opening[key] != null)
        v = F(I(key));
      put(sheet, r, label, j + 1, v);
    }
  }
  const actualMap = {
    8: ["revenue"],
    12: ["operating_expenses"],
    16: ["ebit"],
    21: ["ppe", "balance"],
    25: ["intangibles_noncurrent", "balance"],
    26: ["receivables", "balance"],
    27: ["vendor_receivables", "balance"],
    28: ["inventory", "balance"],
    29: ["other_current_assets", "balance"],
    30: ["payables", "balance"],
    31: ["deferred_revenue", "balance"],
    32: ["other_current_liabilities", "balance"],
    35: ["interest_reported"],
    37: ["pretax"],
    38: ["tax_reported"],
    39: ["net_income"],
    40: ["sbc"],
    42: ["cfo"],
    43: ["cfi"],
    44: ["cff"],
    46: ["cash", "balance"],
    48: ["equity", "balance"],
    49: ["assets", "balance"],
    50: ["liabilities", "balance"],
    53: ["cash_fcf"],
  };
  for (const [metric, [sheet, r]] of Object.entries(locations)) {
    if (constant(Number(metric))) continue;
    if (aggregate && [6, 9].includes(Number(metric))) continue;
    for (let j = 0; j <= n; j++)
      put(sheet, r, rows[Number(metric) - 1][0], j + 1, null);
    const a = actualMap[metric];
    if (a) actual(sheet, r, rows[Number(metric) - 1][0], ...a);
  }
  actual("Income", 48, "Tax expense (checked earnings bridge)", "tax_expense");
  put(
    "Income",
    48,
    "Tax expense (checked earnings bridge)",
    n + 1,
    F(I("ttm_tax")),
  );
  put(
    "Income",
    41,
    "Interest expense (actuals retain reported sign)",
    0,
    "Interest expense (actuals retain reported sign)",
  );
  // Historical broad categories stay blank when source detail cannot support the
  // forecast grouping. Explicit reported detail below remains available.
  if (hrow.intangibles)
    for (let j = 0; j < n; j++)
      put(
        "Assets",
        22,
        "Closing finite intangibles",
        j + 1,
        F(
          `IF(ISNUMBER(${H("intangibles", letter(j + 1))}),${H("intangibles", letter(j + 1))},"")`,
        ),
      );
  const drivers = {
    Income: {
      9: ["Revenue growth", I("products_growth")],
      27: [
        "Operating expenses / revenue",
        `${I("ttm_cost_of_sales")}/${I("ttm_revenue")}`,
      ],
      30: [
        "Embedded reported D&A / revenue",
        `${I("ttm_da")}/${I("ttm_revenue")}`,
      ],
      42: ["Debt interest rate", I("debt_rate")],
      45: ["Investment yield", I("risk_free")],
      49: [
        "Tax rate",
        model.normalized_tax_rate !== undefined
          ? I("normalized_tax_rate")
          : `${I("ttm_tax")}/${I("ttm_pretax")}`,
      ],
    },
    Assets: {
      12: [
        "Cash PP&E additions / revenue",
        `-${I("ttm_capex_cash")}/${I("ttm_revenue")}`,
      ],
      16: ["PP&E depreciation life (years)", I("ppe_life")],
      20: ["Intangible additions / revenue", I("intangible_additions_ratio")],
      24: ["Intangible amortization life (years)", I("intangible_life")],
    },
    WorkingCapital: {
      9: [
        "Operating current assets / annualized revenue",
        `${I("receivables")}/${I("ttm_revenue")}`,
      ],
      13: [
        "Inventory / operating expenses",
        `${I("inventory")}/${I("ttm_cost_of_sales")}`,
      ],
      19: [
        "Operating current liabilities / operating expenses",
        `${I("payables")}/${I("ttm_cost_of_sales")}`,
      ],
    },
    CashFlow: {
      12: ["SBC / revenue", `${I("ttm_sbc")}/${I("ttm_revenue")}`],
      23: ["Distribution payout ratio", I("payout_ratio")],
    },
  };
  const driverReferences = {
    6: [[I("products_growth"), "Income", 9]],
    9: [[`${I("ttm_cost_of_sales")}/${I("ttm_revenue")}`, "Income", 27]],
    12: [[`${I("ttm_cost_of_sales")}/${I("ttm_revenue")}`, "Income", 27]],
    13: [[`${I("ttm_da")}/${I("ttm_revenue")}`, "Income", 30]],
    19: [[`(-${I("ttm_capex_cash")})/${I("ttm_revenue")}`, "Assets", 12]],
    20: [[I("ppe_life"), "Assets", 16]],
    23: [[I("intangible_additions_ratio"), "Assets", 20]],
    24: [[I("intangible_life"), "Assets", 24]],
    35: [[I("debt_rate"), "Income", 42]],
    36: [[I("risk_free"), "Income", 45]],
    38: [
      [
        model.normalized_tax_rate !== undefined
          ? I("normalized_tax_rate")
          : `(${I("ttm_tax")}/${I("ttm_pretax")})`,
        "Income",
        49,
      ],
    ],
    40: [[`${I("ttm_sbc")}/${I("ttm_revenue")}`, "CashFlow", 12]],
    41: [[I("payout_ratio"), "CashFlow", 23]],
  };
  for (const p of forecast)
    for (let metric = 4; metric <= 55; metric++) {
      if (constant(metric) || (aggregate && [8, 12].includes(metric))) continue;
      const a = address(p.index, metric),
        r = Number(a.cell.replace(/[A-Z]/g, "")),
        j = firstForecast + p.index - (hasStub ? 1 : 0);
      let formula = relocate(rows[metric - 1][p.index + 1].formula, a.sheet);
      for (const [source, sheet, row] of driverReferences[metric] ?? [])
        formula = formula.replaceAll(
          source,
          `${sheet === a.sheet ? "" : sheet + "!"}${column(p.index)}${row}`,
        );
      put(
        a.sheet,
        r,
        aggregate && metric === 6
          ? "Revenue"
          : aggregate && metric === 9
            ? "Operating expenses before D&A substitution"
            : rows[metric - 1][0],
        j,
        F(formula),
      );
    }
  if (hasStub)
    await table(
      "Stub",
      rows.map((r, i) => [
        i === 0
          ? `${model.case} — remaining fiscal-year cash flows`
          : i === 1
            ? "Future remainder only; not TTM. Main statements compare full annual periods."
            : r[0],
        r[1],
      ]),
    );
  else
    await table("Stub", [
      ["No initial remainder"],
      [
        "The measurement date is the fiscal year end. All forecast periods are full years.",
      ],
    ]);
  for (const [sheet, items] of Object.entries(drivers))
    for (const [r, [label, basis]] of Object.entries(items))
      for (const p of forecast)
        put(
          sheet,
          Number(r),
          label,
          firstForecast + p.index - (hasStub ? 1 : 0),
          F(basis),
        );
  const ratio = (sheet, r, label, num, den) => {
    for (let j = 1; j < headings.length; j++) {
      const c = letter(j);
      put(
        sheet,
        r,
        label,
        j,
        F(
          `IF(AND(COUNT(${c}${num},${c}${den})=2,${c}${den}<>0),${c}${num}/${c}${den},"")`,
        ),
      );
    }
  };
  ratio("Income", 39, "EBIT margin", 38, 8);
  ratio("Income", 52, "Net income margin", 51, 8);
  for (let j = 1; j < n; j++) {
    const c = letter(j + 1),
      prior = letter(j);
    put(
      "Income",
      9,
      "Revenue growth",
      j + 1,
      F(`IF(AND(COUNT(${c}8,${prior}8)=2,${prior}8<>0),${c}8/${prior}8-1,"")`),
    );
  }
  for (let j = 1; j <= n + 1; j++) {
    const c = letter(j);
    for (const [r, a, b] of [
      [27, 26, 8],
      [49, 48, 47],
    ])
      put(
        "Income",
        r,
        drivers.Income[r][0],
        j,
        F(
          `IF(AND(COUNT(${c}${a},${c}${b})=2,${c}${b}<>0),${c}${a}/${c}${b},"")`,
        ),
      );
  }
  // Annual balance movements are context, not an asserted CFO reconciliation.
  for (let j = 1; j <= n; j++) {
    const c = letter(j),
      previous = letter(j - 1);
    for (const [r, label, key] of [
      [8, "Operating current assets", "operating_current_assets"],
      [18, "Operating current liabilities", "operating_current_liabilities"],
    ])
      if (H(key, c))
        put(
          "WorkingCapital",
          r,
          label,
          j,
          F(`IF(ISNUMBER(${H(key, c)}),${H(key, c)},"")`),
        );
    put(
      "WorkingCapital",
      23,
      "Operating NWC",
      j,
      F(`IF(COUNT(${c}8,${c}18)=2,${c}8-${c}18,"")`),
    );
    if (j > 1) {
      put(
        "WorkingCapital",
        25,
        "Change in NWC (historical balance movement)",
        j,
        F(`IF(COUNT(${c}23,${previous}23)=2,${c}23-${previous}23,"")`),
      );
      for (const [sheet, opening, closing, label] of [
        ["Assets", 10, 14, "Opening PP&E"],
        ["Assets", 18, 22, "Opening finite intangibles"],
        ["CashFlow", 28, 30, "Opening cash"],
        ["BalanceSheet", 26, 29, "Opening equity"],
      ])
        put(
          sheet,
          opening,
          label,
          j,
          F(`IF(ISNUMBER(${previous}${closing}),${previous}${closing},"")`),
        );
    }
    if (H("capex_cash", c))
      put(
        "Assets",
        11,
        "Cash PP&E additions (cash use)",
        j,
        F(`IF(ISNUMBER(${H("capex_cash", c)}),-${H("capex_cash", c)},"")`),
      );
  }
  for (let j = 1; j <= n + 1; j++) {
    const c = letter(j);
    if (j === n + 1) {
      put(
        "WorkingCapital",
        23,
        "Operating NWC",
        j,
        F(
          `${I("receivables")}+${I("vendor_receivables")}+${I("inventory")}+${I("other_current_assets")}-${I("intangibles_current")}-${I("payables")}-${I("deferred_revenue")}`,
        ),
      );
      put(
        "Assets",
        11,
        "Cash PP&E additions (cash use)",
        j,
        F(`-${I("ttm_capex_cash")}`),
      );
    }
    put(
      "Assets",
      12,
      "Cash PP&E additions / revenue",
      j,
      F(`IF(AND(ISNUMBER(${c}11),Income!${c}8<>0),${c}11/Income!${c}8,"")`),
    );
  }
  actual(
    "Income",
    54,
    "Reported discontinued-operations income",
    "discontinued_income",
  );
  actual(
    "Income",
    55,
    "Reported continuing-operations income",
    "continuing_income",
  );
  actual("Assets", 6, "Reported depreciation / amortization aggregate", "da");
  for (const p of forecast)
    put(
      "Assets",
      6,
      "Depreciation / amortization aggregate",
      firstForecast + p.index - (hasStub ? 1 : 0),
      F(`${ref(p.index, 20)}+${ref(p.index, 24)}`),
    );
  // Statement links appear in their financial order, with the actual calculation
  // remaining on the owning asset, working-capital or cash-flow build.
  const links = {
    BalanceSheet: [
      [8, "Operating current assets", 26],
      [10, "PP&E", 21],
      [11, "Finite intangibles", 25],
      [18, "Operating current liabilities", 30],
    ],
    CashFlow: [
      [8, "Net income", 39],
      [9, "PP&E depreciation", 20],
      [10, "Intangible amortization", 24],
      [13, "Change in operating NWC (cash use)", 34],
      [17, "Cash PP&E additions (cash use)", 19],
      [18, "Cash intangible additions (cash use)", 23],
    ],
  };
  for (const [sheet, items] of Object.entries(links))
    for (const [r, label, metric] of items) {
      for (const p of forecast)
        put(
          sheet,
          r,
          label,
          firstForecast + p.index - (hasStub ? 1 : 0),
          F(ref(p.index, metric)),
        );
      const a = actualMap[metric];
      if (a) actual(sheet, r, label, ...a);
    }
  for (const [r, label, key] of [
    [6, "Cash", "cash"],
    [
      36,
      "Reported accounts receivable (included above)",
      "receivables_reported",
    ],
    [37, "Reported inventory (included above)", "inventory_reported"],
    [38, "Reported accounts payable (included above)", "payables_reported"],
  ])
    actual("BalanceSheet", r, label, key, "balance");
  const balanceGroups = [
    [7, "Marketable securities", ["short_investments", "long_investments"]],
    [
      9,
      "Other modeled current assets",
      ["vendor_receivables", "inventory", "other_current_assets"],
    ],
    [14, "Other noncurrent assets", ["other_noncurrent_assets"]],
    [20, "Debt", ["commercial_paper", "current_debt", "long_debt"]],
    [22, "Other noncurrent liabilities", ["other_noncurrent_liabilities"]],
    [23, "Deferred revenue", ["deferred_revenue"]],
  ];
  for (const [r, label, keys] of balanceGroups) {
    put("BalanceSheet", r, label, n + 1, F(keys.map(I).join("+")));
    for (const p of forecast) {
      const basis =
        r === 9
          ? [27, 28, 29].map((m) => ref(p.index, m)).join("+")
          : r === 23
            ? ref(p.index, 31)
            : keys.map(I).join("+");
      put(
        "BalanceSheet",
        r,
        label,
        firstForecast + p.index - (hasStub ? 1 : 0),
        F(basis),
      );
    }
  }
  for (const p of forecast) {
    const j = firstForecast + p.index - (hasStub ? 1 : 0),
      c = column(p.index);
    put(
      "BalanceSheet",
      27,
      "Net income + SBC equity contribution",
      j,
      F(`${ref(p.index, 39)}+${ref(p.index, 40)}`),
    );
    put(
      "BalanceSheet",
      28,
      "Shareholder distributions (equity deduction)",
      j,
      F(ref(p.index, 41)),
    );
    put("BalanceSheet", 29, "Closing equity", j, F(`${c}26+${c}27-${c}28`));
    put("BalanceSheet", 15, "Total assets", j, F(`SUM(${c}6:${c}11)+${c}14`));
    put(
      "BalanceSheet",
      24,
      "Total liabilities",
      j,
      F(`${c}18+SUM(${c}20:${c}23)`),
    );
  }
  for (let j = 1; j <= n; j++) {
    const c = letter(j);
    for (const [r, w] of [
      [8, 8],
      [18, 18],
    ])
      put(
        "BalanceSheet",
        r,
        r === 8 ? "Operating current assets" : "Operating current liabilities",
        j,
        F(`IF(ISNUMBER(WorkingCapital!${c}${w}),WorkingCapital!${c}${w},"")`),
      );
  }
  for (const p of forecast)
    put(
      "BalanceSheet",
      6,
      "Cash",
      firstForecast + p.index - (hasStub ? 1 : 0),
      F(ref(p.index, 46)),
    );
  for (let j = 1; j <= n + 1; j++) {
    const c = letter(j);
    put(
      "BalanceSheet",
      32,
      "Balance check",
      j,
      F(`IF(COUNT(${c}15,${c}24,${c}29)=3,${c}15-${c}24-${c}29,"")`),
    );
  }
  for (let j = 1; j <= n + 1; j++) {
    const c = letter(j);
    put(
      "CashFlow",
      17,
      "Cash PP&E additions (cash use)",
      j,
      F(`IF(ISNUMBER(Assets!${c}11),Assets!${c}11,"")`),
    );
  }
  grids.Income[40][0] = "Interest expense (actuals: reported sign)";
  const costRows = { cogs: 11, sga: 17, research: 20 };
  const components = model.operating_costs?.components ?? [];
  for (const [key, r] of Object.entries(costRows)) {
    const component = components.find((x) => x.key === key);
    const label =
      key === "cogs" ? "Cost of revenue" : key === "sga" ? "SG&A" : "R&D";
    actual("Income", r, label, `cost_${key}`);
    ratio("Income", r + 1, `${label} / revenue`, r, 8);
    // No component means no separately supported forecast, not a reported zero.
    if (component) {
      drivers.Income[r + 1] = [`${label} / revenue`, I(component.control)];
      for (const p of forecast) {
        const c = column(p.index),
          j = firstForecast + p.index - (hasStub ? 1 : 0);
        put("Income", r + 1, `${label} / revenue`, j, F(I(component.control)));
        put("Income", r, label, j, F(`${c}8*${c}${r + 1}`));
      }
    }
  }
  for (let j = 1; j < headings.length; j++) {
    const c = letter(j);
    put(
      "Income",
      14,
      "Gross profit before D&A replacement",
      j,
      F(`IF(COUNT(${c}8,${c}11)=2,${c}8-${c}11,"")`),
    );
    put(
      "Income",
      32,
      "EBITDA proxy (EBIT + total D&A)",
      j,
      j <= n + 1
        ? F(`IF(COUNT(${c}38,Assets!${c}6)=2,${c}38+Assets!${c}6,"")`)
        : F(`${c}8-${c}26+${c}29`),
    );
  }
  for (const p of forecast) {
    const c = column(p.index),
      j = firstForecast + p.index - (hasStub ? 1 : 0);
    if (components.length) {
      put(
        "Income",
        26,
        "Total costs before D&A replacement",
        j,
        F(components.map((x) => `${c}${costRows[x.key]}`).join("+")),
      );
      put("Income", 27, "Total costs / revenue", j, F(`${c}26/${c}8`));
    } else if (aggregate) {
      put(
        "Income",
        23,
        "Aggregate costs (separate drivers unavailable)",
        j,
        F(`${c}8*${c}24`),
      );
      put(
        "Income",
        24,
        "Aggregate costs / revenue",
        j,
        F(`${I("ttm_cost_of_sales")}/${I("ttm_revenue")}`),
      );
      put("Income", 26, "Total costs before D&A replacement", j, F(`${c}23`));
    }
    put("Income", 38, "EBIT", j, F(`${c}32-${c}35-${c}36`));
  }
  ratio("Income", 15, "Gross margin before D&A replacement", 14, 8);
  ratio("Income", 33, "EBITDA margin", 32, 8);
  const incomePercentRows = [
    9, 12, 15, 18, 21, 24, 27, 30, 33, 39, 42, 45, 49, 52,
  ];
  grids.CashFlow[32][0] = "Cash FCF (CFO + CFI)";
  actual("CashFlow", 9, "Depreciation and amortization", "da");
  for (let j = 1; j < headings.length; j++) put("CashFlow", 10, "", j, null);
  for (const p of forecast)
    put(
      "CashFlow",
      9,
      "Depreciation and amortization",
      firstForecast + p.index - (hasStub ? 1 : 0),
      F(`${ref(p.index, 20)}+${ref(p.index, 24)}`),
    );
  grids.Income.push(
    [],
    [
      "Revenue grows from the preceding fiscal year; first full year uses YTD + Stub. Gross profit retains embedded D&A ratios; total D&A is replaced once below EBITDA. SBC remains expensed. EBITDA uses the disclosed D&A aggregate as a proxy; no issuer-adjusted EBITDA is claimed. " +
        (model.operating_costs?.reason ?? "Legacy expense method."),
    ],
  );
  for (const [name, g] of Object.entries(grids))
    if (name !== "DCF") await table(name, g);
  return {
    ref,
    address,
    relocate,
    historyChecks: historicalChecks,
    bridges,
    headings,
    grids,
    forecast,
    column,
    ttm,
    locations,
    drivers,
    incomePercentRows,
    hasStub,
    historyColumns: n,
  };
}
