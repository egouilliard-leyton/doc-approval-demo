// Render a spreadsheet cell's display text using its Excel `number_format`, so the
// read-only preview matches the exported workbook (the panel's whole point is
// "verify in the preview"). Only NUMERIC values with a usable format are
// reformatted; text, formula strings, and empty/`General`/unparseable formats fall
// through to the raw string unchanged. Purely presentational and defensive — it
// never throws (any parsing surprise returns the original value).

/** Placeholder standing in for a quoted literal while we parse the number token. */
const LITERAL = "";

/** The number token: digit placeholders, optional grouping comma, optional decimals. */
const NUMBER_TOKEN = /[#0][#0,]*(?:\.[#0]+)?/;

export function formatCellValue(
  value: string | null,
  numberFormat: string | null,
): string {
  if (value == null) return "";

  // Only reformat when the value actually parses as a finite number; text and
  // formula strings (e.g. "=SUM(A1:A9)", "Mock Widget") pass through untouched.
  const trimmed = value.trim();
  if (trimmed === "") return value;
  const num = Number(trimmed);
  if (!Number.isFinite(num)) return value;

  const fmt = numberFormat?.trim();
  if (!fmt || fmt.toLowerCase() === "general") return value;

  try {
    // Pull quoted literals out as placeholders so their contents don't confuse
    // token detection; we splice them back around the formatted number after.
    const literals: string[] = [];
    const skeleton = fmt.replace(/"([^"]*)"/g, (_m, lit: string) => {
      literals.push(lit);
      return LITERAL;
    });

    const token = NUMBER_TOKEN.exec(skeleton);
    if (!token) return value;
    const numberToken = token[0];

    const isPercent = skeleton.includes("%");
    const useGrouping = numberToken.includes(",");
    const dot = numberToken.indexOf(".");
    const decimals = dot === -1 ? 0 : numberToken.length - dot - 1;

    const body = new Intl.NumberFormat(undefined, {
      useGrouping,
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    }).format(isPercent ? num * 100 : num);

    // Restore literal segments around the number token (prefix / suffix); strip
    // the raw `%` from the suffix since we append it explicitly.
    let li = 0;
    const restore = (s: string) => s.replace(new RegExp(LITERAL, "g"), () => literals[li++] ?? "");
    const prefix = restore(skeleton.slice(0, token.index));
    const suffix = restore(skeleton.slice(token.index + numberToken.length)).replace(/%/g, "");

    return `${prefix}${body}${isPercent ? "%" : ""}${suffix}`;
  } catch {
    return value;
  }
}
