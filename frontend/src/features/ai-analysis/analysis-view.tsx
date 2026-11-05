"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BrainCircuit, History, Sparkles } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { SignalBadge } from "@/components/common/finance";
import { EmptyState, ErrorState, LoadingRows } from "@/components/common/states";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/primitives";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { type ChartMarker, type Overlay, PriceChart, type PriceLevel } from "@/features/charts/price-chart";
import { formatPrice, timeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";
import { api } from "@/services/api";
import { type Analysis, TIMEFRAMES, type Timeframe } from "@/types/api";

import { ComponentsCard, MlCard, NarrativeCard, PatternsCard, RisksCard, SignalSummaryCard, TrendCard } from "./analysis-panels";

const OVERLAYS = new Set<Overlay>(["sma_50", "sma_200", "bb"]);

function AnalysisChart({ a }: { a: Analysis }) {
  const candles = useQuery({ queryKey: ["candles", a.asset.symbol, a.timeframe], queryFn: () => api.market.candles(a.asset.symbol, a.timeframe, 300) });
  const levels = useMemo<PriceLevel[]>(
    () => [
      ...a.indicators.levels.supports.map((s) => ({ price: s.price, label: "S", kind: "support" as const })),
      ...a.indicators.levels.resistances.map((r) => ({ price: r.price, label: "R", kind: "resistance" as const })),
    ],
    [a],
  );
  const markers = useMemo<ChartMarker[]>(() => {
    const first = candles.data?.candles[0]?.time ?? 0;
    return a.patterns
      .filter((p) => p.time && p.time >= first && p.bias !== "neutral")
      .map((p) => ({
        time: p.time!,
        position: p.bias === "bullish" ? "belowBar" : "aboveBar",
        shape: p.bias === "bullish" ? "arrowUp" : "arrowDown",
        color: p.bias === "bullish" ? "gain" : "loss",
        text: p.name,
      }));
  }, [a, candles.data]);
  if (candles.isLoading) return <Skeleton className="h-[420px] w-full" />;
  if (candles.error) return <ErrorState error={candles.error} onRetry={() => candles.refetch()} />;
  if (!candles.data) return null;
  return (
    <PriceChart
      candles={candles.data.candles}
      indicators={candles.data.indicators}
      overlays={OVERLAYS}
      timeframe={a.timeframe}
      levels={levels}
      markers={markers}
      height={420}
    />
  );
}

export function AnalysisView() {
  const params = useSearchParams();
  const router = useRouter();
  const qc = useQueryClient();
  const [symbol, setSymbol] = useState(params.get("symbol") ?? "BTC-USD");
  const [timeframe, setTimeframe] = useState<Timeframe>((params.get("timeframe") as Timeframe) ?? "1h");
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const assets = useQuery({ queryKey: ["assets"], queryFn: () => api.market.assets(), staleTime: 300_000 });
  const history = useQuery({ queryKey: ["analyses"], queryFn: () => api.analysis.list(undefined, 30) });

  const current: Analysis | undefined = useMemo(() => {
    const list = history.data ?? [];
    if (selectedId) return list.find((a) => a.id === selectedId);
    return list.find((a) => a.asset.symbol === symbol && a.timeframe === timeframe);
  }, [history.data, selectedId, symbol, timeframe]);

  const run = useMutation({
    mutationFn: () => api.analysis.run(symbol, timeframe),
    onSuccess: (a) => {
      qc.setQueryData<Analysis[]>(["analyses"], (old) => [a, ...(old ?? [])]);
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      setSelectedId(a.id);
      toast.success(a.summary);
    },
    onError: (e: Error) => toast.error(e.message),
  });

  useEffect(() => {
    router.replace(`/analysis?symbol=${symbol}&timeframe=${timeframe}`, { scroll: false });
  }, [symbol, timeframe, router]);

  return (
    <>
      <PageHeader
        title="AI Trading Intelligence"
        description="Explainable signals from technical indicators, chart patterns and a walk-forward-validated ML model."
        actions={
          <>
            <Select value={symbol} onValueChange={(v) => { setSymbol(v); setSelectedId(null); }}>
              <SelectTrigger className="h-8 w-36 text-xs" aria-label="Asset">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(assets.data ?? [{ symbol }]).map((a) => (
                  <SelectItem key={a.symbol} value={a.symbol}>{a.symbol}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={timeframe} onValueChange={(v) => { setTimeframe(v as Timeframe); setSelectedId(null); }}>
              <SelectTrigger className="h-8 w-20 text-xs" aria-label="Timeframe">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {TIMEFRAMES.map((tf) => (
                  <SelectItem key={tf} value={tf}>{tf}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button size="sm" onClick={() => run.mutate()} loading={run.isPending}>
              <Sparkles /> {current ? "Re-run analysis" : "Run analysis"}
            </Button>
          </>
        }
      />

      {history.isLoading ? (
        <LoadingRows rows={6} />
      ) : history.error ? (
        <Card><ErrorState error={history.error} onRetry={() => history.refetch()} /></Card>
      ) : !current ? (
        <Card>
          <EmptyState
            icon={BrainCircuit}
            title={`No analysis for ${symbol} · ${timeframe} yet`}
            description="Run an analysis to compute indicators, detect patterns, evaluate the ML model and generate an explainable signal from live market data."
            action={<Button onClick={() => run.mutate()} loading={run.isPending}><Sparkles /> Run analysis</Button>}
            className="py-16"
          />
        </Card>
      ) : (
        <div className="space-y-4">
          <SignalSummaryCard a={current} />
          <div className="grid gap-4 xl:grid-cols-[1fr_380px]">
            <div className="min-w-0 space-y-4">
              <Card>
                <CardHeader>
                  <CardTitle>{current.asset.symbol} · {current.timeframe} with detected levels &amp; patterns</CardTitle>
                </CardHeader>
                <CardContent className="px-2 sm:px-3">
                  <AnalysisChart a={current} />
                </CardContent>
              </Card>
              <NarrativeCard a={current} />
              <div className="grid gap-4 lg:grid-cols-2">
                <TrendCard a={current} />
                <PatternsCard a={current} />
              </div>
            </div>
            <div className="space-y-4">
              <ComponentsCard a={current} />
              <MlCard a={current} />
              <RisksCard a={current} />
            </div>
          </div>
        </div>
      )}

      {history.data && history.data.length > 0 && (
        <Card className="mt-4">
          <CardHeader>
            <CardTitle className="flex items-center gap-1.5"><History className="size-4" /> Signal history</CardTitle>
          </CardHeader>
          <CardContent className="px-2">
            <Table>
              <THead>
                <TR className="hover:bg-transparent">
                  <TH>Asset</TH><TH>Signal</TH><TH className="text-right">Score</TH><TH className="text-right">Confidence</TH><TH className="text-right">Price</TH><TH>Trend</TH><TH className="text-right">When</TH>
                </TR>
              </THead>
              <TBody>
                {history.data.map((a) => (
                  <TR key={a.id} className={cn("cursor-pointer", current?.id === a.id && "bg-primary/8")} onClick={() => { setSymbol(a.asset.symbol); setTimeframe(a.timeframe); setSelectedId(a.id); window.scrollTo({ top: 0, behavior: "smooth" }); }}>
                    <TD className="font-medium">{a.asset.symbol} <span className="text-xs text-muted-foreground">{a.timeframe}</span></TD>
                    <TD>{a.signal && <SignalBadge action={a.signal.action} />}</TD>
                    <TD className="text-right">{a.signal ? `${a.signal.score >= 0 ? "+" : ""}${a.signal.score.toFixed(2)}` : "—"}</TD>
                    <TD className="text-right">{a.signal ? `${a.signal.confidence.toFixed(0)}/100` : "—"}</TD>
                    <TD className="text-right">{formatPrice(a.signal?.price_at_signal)}</TD>
                    <TD className="capitalize text-muted-foreground">{a.trend}</TD>
                    <TD className="text-right text-muted-foreground">{timeAgo(a.created_at)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </>
  );
}
