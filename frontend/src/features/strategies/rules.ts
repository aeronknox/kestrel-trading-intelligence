import type { Condition, IndicatorName, IndicatorSpec, Operand, Operator, RiskParams, RuleSet } from "@/types/api";

export const INDICATOR_LABELS: Record<IndicatorName, string> = {
  close: "Close price",
  open: "Open price",
  high: "High",
  low: "Low",
  volume: "Volume",
  sma: "SMA",
  ema: "EMA",
  rsi: "RSI",
  macd: "MACD",
  bollinger: "Bollinger Bands",
  atr: "ATR",
  volume_sma: "Volume SMA",
  roc: "Rate of change %",
};

export const OPERATOR_LABELS: Record<Operator, string> = {
  ">": "is above",
  "<": "is below",
  ">=": "is at or above",
  "<=": "is at or below",
  crosses_above: "crosses above",
  crosses_below: "crosses below",
};

export const DEFAULT_RISK: RiskParams = {
  position_size_pct: 100,
  stop_loss_pct: 5,
  take_profit_pct: null,
  trailing_stop_pct: null,
  max_bars_in_trade: null,
};

/** Build an operand for `name` populated with the catalog's default params. */
export function defaultOperand(name: IndicatorName, catalog: IndicatorSpec[]): Operand {
  const spec = catalog.find((s) => s.name === name);
  const params: Record<string, number> = {};
  for (const [k, v] of Object.entries(spec?.params ?? {})) params[k] = v.default;
  return { indicator: name, params, field: spec?.fields[0] ?? null };
}

export function defaultCondition(catalog: IndicatorSpec[]): Condition {
  return { left: defaultOperand("rsi", catalog), op: "<", right: { value: 30 } };
}

export function emptyRuleSet(): RuleSet {
  return { logic: "all", conditions: [] };
}

function fmtParam(v: number): string {
  return Number.isInteger(v) ? String(v) : String(v);
}

export function describeOperand(o: Operand): string {
  if (o.indicator === undefined || o.indicator === null) return String(o.value ?? "?");
  const name = o.indicator;
  const params = Object.values(o.params ?? {});
  const base = ["close", "open", "high", "low", "volume"].includes(name) ? INDICATOR_LABELS[name] : `${INDICATOR_LABELS[name]}${params.length ? `(${params.map(fmtParam).join(", ")})` : ""}`;
  return o.field ? `${base} ${o.field.replace("_", " ")}` : base;
}

export function describeCondition(c: Condition): string {
  return `${describeOperand(c.left)} ${OPERATOR_LABELS[c.op]} ${describeOperand(c.right)}`;
}

export function describeRuleSet(rs: RuleSet): string {
  if (!rs.conditions.length) return "—";
  const joiner = rs.logic === "all" ? " AND " : " OR ";
  return rs.conditions.map(describeCondition).join(joiner);
}

export function describeRisk(r: Partial<RiskParams>): string[] {
  const out = [`Allocate ${r.position_size_pct ?? 100}% of equity per entry`];
  if (r.stop_loss_pct) out.push(`stop-loss ${r.stop_loss_pct}%`);
  if (r.take_profit_pct) out.push(`take-profit ${r.take_profit_pct}%`);
  if (r.trailing_stop_pct) out.push(`trailing stop ${r.trailing_stop_pct}%`);
  if (r.max_bars_in_trade) out.push(`exit after ${r.max_bars_in_trade} bars`);
  return out;
}

/** Optional exits use null for "off"; treat 0, negatives and NaN the same way. */
export function normalizeRisk(r: RiskParams): RiskParams {
  const opt = (v: number | null) => (v === null || !Number.isFinite(v) || v <= 0 ? null : v);
  return {
    position_size_pct: r.position_size_pct,
    stop_loss_pct: opt(r.stop_loss_pct),
    take_profit_pct: opt(r.take_profit_pct),
    trailing_stop_pct: opt(r.trailing_stop_pct),
    max_bars_in_trade: opt(r.max_bars_in_trade),
  };
}

/** Client-side validation mirroring the backend's rules (the server re-validates). */
export function validateStrategy(entry: RuleSet, exit: RuleSet, risk: Partial<RiskParams>): string | null {
  if (!entry.conditions.length) return "Add at least one entry condition.";
  const hasRiskExit = !!(risk.stop_loss_pct || risk.take_profit_pct || risk.trailing_stop_pct || risk.max_bars_in_trade);
  if (!exit.conditions.length && !hasRiskExit) return "Add an exit condition or a stop-loss / take-profit / time-based exit.";
  for (const c of [...entry.conditions, ...exit.conditions]) {
    if (c.right.indicator == null && (c.right.value === null || c.right.value === undefined || Number.isNaN(c.right.value))) {
      return "Every condition needs a comparison value.";
    }
  }
  const size = risk.position_size_pct ?? 100;
  if (size <= 0 || size > 100) return "Position size must be between 0 and 100%.";
  return null;
}
