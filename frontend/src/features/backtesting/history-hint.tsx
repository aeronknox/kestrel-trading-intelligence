"use client";

import { useQuery } from "@tanstack/react-query";

import { barsSpan, formatDate } from "@/lib/format";
import { api } from "@/services/api";
import type { Timeframe } from "@/types/api";

/** What history exists for a backtest/research run of `bars` candles, and whether more must be downloaded first. */
export function HistoryHint({ symbol, timeframe, bars }: { symbol?: string; timeframe?: Timeframe; bars: number }) {
  const q = useQuery({
    queryKey: ["history", symbol, timeframe],
    queryFn: () => api.market.history(symbol!, timeframe!),
    enabled: Boolean(symbol && timeframe),
    staleTime: 30_000,
  });
  if (!symbol || !timeframe) return null;
  const span = barsSpan(bars, timeframe);
  if (!q.data) return <p className="text-xs text-muted-foreground">{span} of {timeframe} candles</p>;
  const h = q.data;
  if (h.is_sample) return <p className="text-xs text-muted-foreground">{span} of synthetic sample candles</p>;
  const stored = h.stored_bars ?? 0;
  const missing = Math.max(0, bars - stored);
  return (
    <p className="text-xs text-muted-foreground">
      {span} · {stored.toLocaleString()} {symbol} {timeframe} bars stored
      {stored > 0 && h.first ? ` since ${formatDate(h.first)}` : ""}.
      {missing > 0 && (
        <span className="text-warn"> Up to {missing.toLocaleString()} older bars will be downloaded first, which can take a minute; the asset&apos;s listing date may limit what exists.</span>
      )}
    </p>
  );
}
