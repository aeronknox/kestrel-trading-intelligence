/** Number/date formatting helpers. All return "—" for missing values. */

const DASH = "—";

export function isNum(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

/** Price with precision adapted to magnitude (crypto ranges from 1e-6 to 1e5). */
export function formatPrice(v: number | null | undefined, currency = false): string {
  if (!isNum(v)) return DASH;
  const abs = Math.abs(v);
  const digits = abs >= 1000 ? 2 : abs >= 1 ? 2 : abs >= 0.01 ? 4 : 6;
  const s = v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return currency ? `$${s}` : s;
}

export function formatUsd(v: number | null | undefined, opts: { compact?: boolean; sign?: boolean } = {}): string {
  if (!isNum(v)) return DASH;
  const sign = opts.sign && v > 0 ? "+" : v < 0 ? "-" : "";
  const abs = Math.abs(v);
  const body = opts.compact
    ? abs.toLocaleString("en-US", { notation: "compact", maximumFractionDigits: 2 })
    : abs.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${sign}$${body}`;
}

export function formatPct(v: number | null | undefined, digits = 2, sign = true): string {
  if (!isNum(v)) return DASH;
  const prefix = sign && v > 0 ? "+" : "";
  return `${prefix}${v.toFixed(digits)}%`;
}

export function formatNumber(v: number | null | undefined, digits = 2): string {
  if (!isNum(v)) return DASH;
  return v.toLocaleString("en-US", { maximumFractionDigits: digits });
}

export function formatCompact(v: number | null | undefined): string {
  if (!isNum(v)) return DASH;
  return v.toLocaleString("en-US", { notation: "compact", maximumFractionDigits: 2 });
}

export function formatQty(v: number | null | undefined): string {
  if (!isNum(v)) return DASH;
  return v.toLocaleString("en-US", { maximumFractionDigits: 8 });
}

export function formatDateTime(v: string | number | Date | null | undefined): string {
  if (v === null || v === undefined) return DASH;
  const d = typeof v === "number" ? new Date(v * 1000) : new Date(v);
  if (Number.isNaN(d.getTime())) return DASH;
  return d.toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function formatDate(v: string | number | Date | null | undefined): string {
  if (v === null || v === undefined) return DASH;
  const d = typeof v === "number" ? new Date(v * 1000) : new Date(v);
  if (Number.isNaN(d.getTime())) return DASH;
  return d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

export function timeAgo(v: string | Date | null | undefined, now: Date = new Date()): string {
  if (!v) return DASH;
  const d = new Date(v);
  const s = Math.round((now.getTime() - d.getTime()) / 1000);
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

/** Tailwind text color class for a signed value. */
export function pnlClass(v: number | null | undefined): string {
  if (!isNum(v) || v === 0) return "text-muted-foreground";
  return v > 0 ? "text-gain" : "text-loss";
}
