// Apply Excel forecast edits after generating fresh, company-specific formulas.
export function templateEdits(
  patch,
  historyCount,
  inputRows,
  forecastCount = 10,
) {
  if (
    patch &&
    Object.keys(patch.changes).length &&
    forecastCount !== (patch.forecast_columns ?? 10)
  )
    throw Error(
      "Edited template and company have different forecast horizons; initialize a template for this period layout",
    );
  const row = (sheet, r) => {
    const map = patch?.row_maps[sheet];
    if (!map) return Number(r);
    if (map[r] !== undefined) return map[r];
    const last = Math.max(...Object.keys(map).map(Number));
    return Number(r) + (Number(r) > last ? map[last] - last : 0);
  };
  const address = (a) =>
    a.constant === 0
      ? a
      : {
          ...a,
          cell: a.cell.replace(/\d+$/, (r) => row(a.sheet, r)),
        };
  const rendered = {};
  const refPattern =
    /(?<![A-Za-z0-9_])(?:(?:'([^']+)'|([A-Za-z_][A-Za-z0-9_]*))!)?(\$?[A-Z]{1,3})(\$?)([1-9][0-9]*)(?![A-Za-z0-9_(])/g;
  const letter = (n) => {
    let s = "";
    for (; n; n = Math.floor((n - 1) / 26))
      s = String.fromCharCode(65 + ((n - 1) % 26)) + s;
    return s;
  };
  const column = (s) =>
    [...s.replace("$", "")].reduce((n, c) => n * 26 + c.charCodeAt(0) - 64, 0);
  const moveColumn = (sheet, c) => {
    if (c === 1 || sheet === "Inputs" || sheet === "Stub") return c;
    const moved = c + historyCount - patch.history_columns;
    if (moved < 2)
      throw Error(
        `Template references unavailable historical column in ${sheet}`,
      );
    return moved;
  };
  function formula(text, context, custom = false) {
    if (!patch) return text;
    return text
      .split(/("(?:[^"]|"")*")/)
      .map((part, i) => {
        if (i % 2) return part;
        let lastEnd = -1,
          lastSheet = context;
        return part.replace(
          refPattern,
          (full, quoted, plain, c, dollar, r, offset) => {
            const sheet =
              quoted ||
              plain ||
              (part.slice(lastEnd, offset).trim() === ":"
                ? lastSheet
                : context);
            lastEnd = offset + full.length;
            lastSheet = sheet;
            let targetRow = custom ? Number(r) : row(sheet, r);
            let targetColumn = c;
            if (custom) {
              if (sheet === "Inputs") {
                const key = Object.keys(patch.input_rows).find(
                  (k) => patch.input_rows[k] === Number(r),
                );
                if (column(c) !== 2 || !key || !inputRows[key])
                  throw Error(`Template input has no source binding: ${full}`);
                targetRow = inputRows[key];
              } else {
                targetColumn =
                  (c.startsWith("$") ? "$" : "") +
                  letter(moveColumn(sheet, column(c)));
              }
            }
            return (
              (quoted || plain ? `${sheet}!` : "") +
              targetColumn +
              dollar +
              targetRow
            );
          },
        );
      })
      .join("");
  }
  function table(sheet, rows) {
    const result = [];
    for (let r = 0; r < rows.length; r++) {
      result[row(sheet, r + 1) - 1] = rows[r].map((v) =>
        v?.formula ? { formula: formula(v.formula, sheet) } : v,
      );
    }
    for (const [cell, value] of Object.entries(patch?.changes[sheet] ?? {})) {
      const [, c, r] = cell.match(/^([A-Z]+)(\d+)$/);
      const targetColumn = moveColumn(sheet, column(c)) - 1;
      result[Number(r) - 1] ??= [];
      result[Number(r) - 1][targetColumn] = value?.formula
        ? { formula: formula(value.formula, sheet, true) }
        : value;
    }
    for (let r = 0; r < result.length; r++) result[r] ??= [];
    rendered[sheet] = result;
    return result;
  }
  const customCells = (sheet) =>
    Object.entries(patch?.changes[sheet] ?? {}).map(([cell, value]) => {
      const [, c, r] = cell.match(/^([A-Z]+)(\d+)$/);
      return {
        sheet,
        cell: letter(moveColumn(sheet, column(c))) + r,
        value: value?.formula
          ? { formula: formula(value.formula, sheet, true) }
          : value,
        numberFormat: patch.number_formats?.[sheet]?.[cell],
      };
    });
  return { row, address, formula, table, rendered, customCells };
}
