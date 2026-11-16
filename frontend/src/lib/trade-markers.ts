import type { ChartMarker } from "@/features/charts/price-chart";

interface Fill {
  side: "buy" | "sell";
  quantity: number;
  price: number;
  executed_at: string;
}

/**
 * Chart markers for simulated fills: each on the candle it happened in (the last bar opening at or before
 * it), buys below the bar and sells above. Fills in the same bar and direction are combined. Fills before
 * the first candle are left out; ones after the last candle go on the last (still forming) bar.
 */
export function tradeMarkers(fills: Fill[], candleTimes: number[]): ChartMarker[] {
  if (!candleTimes.length) return [];
  const times = [...candleTimes].sort((a, b) => a - b);
  const barOf = (t: number): number | null => {
    if (t < times[0]) return null;
    let lo = 0;
    let hi = times.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (times[mid] <= t) lo = mid;
      else hi = mid - 1;
    }
    return times[lo];
  };
  const groups = new Map<string, { time: number; side: Fill["side"]; qty: number; notional: number }>();
  for (const f of fills) {
    const bar = barOf(Math.floor(new Date(f.executed_at).getTime() / 1000));
    if (bar === null) continue;
    const key = `${bar}:${f.side}`;
    const g = groups.get(key) ?? { time: bar, side: f.side, qty: 0, notional: 0 };
    g.qty += f.quantity;
    g.notional += f.quantity * f.price;
    groups.set(key, g);
  }
  return [...groups.values()]
    .sort((a, b) => a.time - b.time)
    .map((g) => ({
      time: g.time,
      position: g.side === "buy" ? "belowBar" : "aboveBar",
      shape: g.side === "buy" ? "arrowUp" : "arrowDown",
      color: g.side === "buy" ? "gain" : "loss",
      text: `${g.side === "buy" ? "B" : "S"} @ ${fmt(g.notional / g.qty)}`,
    }));
}

function fmt(v: number): string {
  return v >= 1 ? v.toLocaleString("en-US", { maximumFractionDigits: 2 }) : v.toPrecision(4);
}
