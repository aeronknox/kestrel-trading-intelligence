import type { ResearchObjective, RunSummaryMetrics, TunableParameter } from "@/types/api";

export const MAX_VALUES = 12;
export const MAX_COMBINATIONS = 100;

/** Values from `from` to `to` (inclusive) in steps of `step`, rounded to avoid float drift. */
export function rangeValues(from: number, to: number, step: number, integer = false): number[] {
  if (![from, to, step].every(Number.isFinite) || step <= 0 || to < from) return [];
  const out: number[] = [];
  for (let i = 0; out.length <= MAX_VALUES; i++) {
    const v = Math.round((from + i * step) * 1e6) / 1e6;
    if (v > to + 1e-9) break;
    out.push(integer ? Math.round(v) : v);
  }
  return [...new Set(out)];
}

/** A sensible default range centred on the current value, inside the parameter's bounds. */
export function defaultRange(p: TunableParameter): { from: number; to: number; step: number } {
  const cur = p.current ?? (p.min !== null && p.max !== null ? (p.min + p.max) / 2 : 10);
  const step = p.integer ? Math.max(1, Math.round(Math.abs(cur) * 0.2)) : Math.max(0.5, Math.round(Math.abs(cur) * 0.2 * 2) / 2);
  const clamp = (v: number) => Math.min(p.max ?? Infinity, Math.max(p.min ?? -Infinity, v));
  return { from: clamp(cur - 2 * step), to: clamp(cur + 2 * step), step };
}

/** Why a set of grids can't be run, or null if it can. */
export function gridProblem(grids: { label: string; values: number[]; min: number | null; max: number | null }[]): string | null {
  for (const g of grids) {
    if (g.values.length < 2) return `${g.label}: the range must contain at least 2 values`;
    if (g.values.length > MAX_VALUES) return `${g.label}: at most ${MAX_VALUES} values`;
    if (g.values.some((v) => (g.min !== null && v < g.min) || (g.max !== null && v > g.max)))
      return `${g.label}: values must be between ${g.min} and ${g.max}`;
  }
  const total = grids.reduce((n, g) => n * g.values.length, 1);
  return total > MAX_COMBINATIONS ? `${total} combinations; the limit is ${MAX_COMBINATIONS}` : null;
}

/** "Entry #1 (RSI(14) crosses above 30): threshold" -> "Entry #1: threshold". */
export function shortLabel(label: string): string {
  return label.replace(/ \(.*\): /, ": ");
}

/** The objective's raw value for a run, mirroring the backend score without the minimum-trade rule. */
export function objectiveValue(objective: ResearchObjective, m: RunSummaryMetrics): number | null {
  if (objective === "sharpe_ratio") return m.sharpe_ratio;
  if (objective === "total_return_pct") return m.total_return_pct;
  return m.total_return_pct / Math.max(Math.abs(m.max_drawdown_pct), 1);
}

/** Preferred second sweep parameter: an exit setting is usually more informative than position size. */
export function preferredSecond(unused: TunableParameter[]): TunableParameter | undefined {
  for (const path of ["risk.stop_loss_pct", "risk.take_profit_pct", "risk.trailing_stop_pct"]) {
    const p = unused.find((u) => u.path === path);
    if (p) return p;
  }
  return unused.find((u) => u.path.endsWith(".value")) ?? unused[0];
}
