// Small display formatters shared across the UI.

/** 842 -> "842 ms", 1840 -> "1.84 s". */
export function formatMs(ms?: number): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

/** 0.873 -> "87%". null -> "—". */
export function formatPct(v?: number | null): string {
  if (v == null) return "—";
  return `${Math.round(v * 100)}%`;
}

/** ISO timestamp -> "May 31, 2026". Invalid/unparseable input -> "". */
export function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

// Common currency codes -> symbol; anything else falls back to the code prefix.
const CURRENCY_SYMBOL: Record<string, string> = {
  USD: "$",
  EUR: "€",
  GBP: "£",
  JPY: "¥",
  CNY: "¥",
  AUD: "A$",
  CAD: "C$",
  CHF: "CHF ",
  INR: "₹",
};

// Field names that plausibly hold a monetary amount. Currency formatting is
// applied ONLY to these (and only when a currency is known) so non-money numbers
// — quantities, counts, rates in other doc types — are left untouched.
const MONEY_KEYWORDS = [
  "total",
  "subtotal",
  "sub_total",
  "amount",
  "price",
  "unit_price",
  "balance",
  "paid",
  "fee",
  "cost",
  "charge",
  "tax",
  "vat",
  "gst",
];

/** Whether a field key/label looks like a monetary amount (heuristic, opt-in). */
export function isMoneyField(key: string): boolean {
  const k = key.toLowerCase();
  return MONEY_KEYWORDS.some((w) => k.includes(w));
}

/**
 * Format a numeric amount with a currency, e.g. (85, "USD") -> "$85.00".
 * Best-effort and optional: no currency -> the raw number as-is.
 */
export function formatMoney(
  value: number,
  currency?: string | null,
): string {
  const n = value.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  if (!currency) return String(value);
  const code = currency.trim().toUpperCase();
  const sym = CURRENCY_SYMBOL[code];
  return sym ? `${sym}${n}` : `${code} ${n}`;
}

/** Tailwind text color for a 0-1 confidence value. */
export function confidenceTone(v?: number | null): string {
  if (v == null) return "text-muted-foreground";
  if (v >= 0.8) return "text-approve";
  if (v >= 0.5) return "text-review";
  return "text-flag";
}
