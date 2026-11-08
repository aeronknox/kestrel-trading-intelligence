"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, BrainCircuit, Star, Wallet } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { AssetIcon, Change, DataSource } from "@/components/common/finance";
import { ErrorState } from "@/components/common/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Segmented, SegmentedItem } from "@/components/ui/segmented";
import { Skeleton } from "@/components/ui/primitives";
import { type Overlay, PriceChart } from "@/features/charts/price-chart";
import { useMe } from "@/hooks/use-auth";
import { useLiveTicker } from "@/hooks/use-market-stream";
import { formatCompact, formatPrice } from "@/lib/format";
import { cn } from "@/lib/utils";
import { api } from "@/services/api";
import { TIMEFRAMES, type Timeframe } from "@/types/api";

import { IndicatorPanel } from "./indicator-panel";
import { useWatchlist } from "./use-watchlist";

const OVERLAYS: { key: Overlay; label: string }[] = [
  { key: "sma_20", label: "SMA 20" },
  { key: "sma_50", label: "SMA 50" },
  { key: "sma_200", label: "SMA 200" },
  { key: "bb", label: "Bollinger" },
  { key: "volume", label: "Volume" },
  { key: "rsi", label: "RSI" },
  { key: "macd", label: "MACD" },
];

export function AssetDetailView({ symbol }: { symbol: string }) {
  const me = useMe();
  const [timeframe, setTimeframe] = useState<Timeframe>(me.data?.settings?.default_timeframe ?? "1h");
  const [overlays, setOverlays] = useState<Set<Overlay>>(new Set(["sma_50", "sma_200", "volume", "rsi"]));
  const { symbols: watched, toggle } = useWatchlist();

  const ticker = useQuery({ queryKey: ["ticker", symbol], queryFn: () => api.market.ticker(symbol), refetchInterval: 60_000 });
  const candles = useQuery({
    queryKey: ["candles", symbol, timeframe],
    queryFn: () => api.market.candles(symbol, timeframe, 300),
    refetchInterval: timeframe === "1m" ? 30_000 : 60_000,
  });
  const live = useLiveTicker(symbol, ticker.data);
  const isWatched = watched.has(symbol);

  const toggleOverlay = (k: Overlay) =>
    setOverlays((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });

  if (ticker.error && candles.error) {
    return (
      <Card>
        <ErrorState error={candles.error} onRetry={() => candles.refetch()} />
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="icon-sm" asChild>
            <Link href="/markets" aria-label="Back to markets">
              <ArrowLeft />
            </Link>
          </Button>
          <AssetIcon symbol={symbol} className="size-10 text-xs" />
          <div>
            <h1 className="text-xl font-semibold tracking-tight">{symbol}</h1>
            {live ? (
              <div className="flex items-baseline gap-3">
                <span className="text-2xl font-semibold tabular">{formatPrice(live.price, true)}</span>
                <Change value={live.change_pct_24h} className="text-sm" />
              </div>
            ) : (
              <Skeleton className="mt-1 h-7 w-40" />
            )}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-xs">
          <div>
            <p className="text-muted-foreground">24h high</p>
            <p className="font-medium tabular">{formatPrice(live?.high_24h)}</p>
          </div>
          <div>
            <p className="text-muted-foreground">24h low</p>
            <p className="font-medium tabular">{formatPrice(live?.low_24h)}</p>
          </div>
          <div>
            <p className="text-muted-foreground">24h volume</p>
            <p className="font-medium tabular">{formatCompact(live?.volume_24h)}</p>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => toggle(symbol, isWatched)}>
              <Star className={cn(isWatched && "fill-warn text-warn")} /> {isWatched ? "Watching" : "Watch"}
            </Button>
            <Button variant="outline" size="sm" asChild>
              <Link href={`/paper-trading?symbol=${symbol}`}>
                <Wallet /> Paper trade
              </Link>
            </Button>
            <Button size="sm" asChild>
              <Link href={`/analysis?symbol=${symbol}&timeframe=${timeframe}`}>
                <BrainCircuit /> Analyze
              </Link>
            </Button>
          </div>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1fr_320px]">
        <Card className="min-w-0">
          <CardHeader className="flex-col gap-3 sm:flex-row sm:items-center">
            <Segmented value={timeframe} onValueChange={(v) => setTimeframe(v as Timeframe)} label="Timeframe">
                {TIMEFRAMES.map((tf) => (
                  <SegmentedItem key={tf} value={tf} className="px-2.5">
                    {tf}
                  </SegmentedItem>
                ))}
              </Segmented>
            <div className="flex flex-wrap gap-1.5">
              {OVERLAYS.map((o) => (
                <button
                  key={o.key}
                  onClick={() => toggleOverlay(o.key)}
                  className={cn(
                    "rounded-md border px-2 py-1 text-[11px] font-medium transition-colors",
                    overlays.has(o.key) ? "border-primary/40 bg-primary/12 text-foreground" : "border-border text-muted-foreground hover:text-foreground",
                  )}
                  aria-pressed={overlays.has(o.key)}
                >
                  {o.label}
                </button>
              ))}
            </div>
          </CardHeader>
          <CardContent className="px-2 pb-3 sm:px-3">
            {candles.isLoading ? (
              <Skeleton className="h-[520px] w-full" />
            ) : candles.error ? (
              <ErrorState error={candles.error} onRetry={() => candles.refetch()} />
            ) : candles.data ? (
              <>
                <PriceChart
                  candles={candles.data.candles}
                  indicators={candles.data.indicators}
                  overlays={overlays}
                  timeframe={timeframe}
                  livePrice={live?.price}
                  height={overlays.has("rsi") && overlays.has("macd") ? 620 : 520}
                />
                <DataSource meta={candles.data.meta} className="px-2 pt-2" />
              </>
            ) : null}
          </CardContent>
        </Card>
        {candles.data ? <IndicatorPanel latest={candles.data.latest} /> : <Skeleton className="h-[520px] rounded-xl" />}
      </div>
    </div>
  );
}
