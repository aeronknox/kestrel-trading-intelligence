import type { Timeframe } from "@/types/api";

export const BENCHMARK = "BTC-USD";
export const TF_SECONDS: Record<Timeframe, number> = { "1m": 60, "5m": 300, "15m": 900, "1h": 3600, "6h": 21_600, "1d": 86_400 };
const CHOICES: Timeframe[] = ["5m", "15m", "1h", "6h", "1d"];
export const MAX_BARS = 1500;

/** The finest candle timeframe that covers `spanSeconds` in at most MAX_BARS bars. */
export function benchmarkTimeframe(spanSeconds: number): Timeframe {
  return CHOICES.find((tf) => spanSeconds / TF_SECONDS[tf] <= MAX_BARS) ?? "1d";
}

/**
 * What the starting equity would be worth at each point had it all been put in one asset at the first
 * point and held: equity₀ × close(t) / close(t₀), using the bar open at each time (to the nearest bar).
 * Returns null when the candles don't reach back to the first point: nothing is filled in or guessed.
 */
export function buyAndHold<T extends { time: number; equity: number }>(
  curve: T[],
  candles: { time: number; close: number }[],
): (T & { benchmark: number })[] | null {
  if (curve.length < 2 || !candles.length) return null;
  const bars = [...candles].sort((a, b) => a.time - b.time);
  let i = 0;
  const closeAt = (t: number): number | null => {
    while (i + 1 < bars.length && bars[i + 1].time <= t) i++;
    return bars[i].time <= t ? bars[i].close : null;
  };
  const points = [...curve].sort((a, b) => a.time - b.time);
  const start = closeAt(points[0].time);
  if (!start) return null;
  const units = points[0].equity / start;
  return points.map((p) => ({ ...p, benchmark: units * (closeAt(p.time) as number) }));
}
