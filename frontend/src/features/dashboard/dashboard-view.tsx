"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, ArrowRight, BrainCircuit, DollarSign, Landmark, LineChart, Sparkles, TrendingUp } from "lucide-react";
import Link from "next/link";
import { toast } from "sonner";

import { Change, DataSource, SignalBadge, StatCard } from "@/components/common/finance";
import { EmptyState, ErrorState } from "@/components/common/states";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge, Skeleton } from "@/components/ui/primitives";
import { EquityAreaChart, hasChartableSpan, YoungHistoryNote } from "@/features/charts/recharts";
import { MarketTable } from "@/features/markets/market-table";
import { useMe } from "@/hooks/use-auth";
import { formatPrice, formatQty, formatUsd, pnlClass, timeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";
import { api } from "@/services/api";

import { SentimentCard } from "./sentiment-card";

function DashboardSkeleton() {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-[104px] rounded-xl" />
        ))}
      </div>
      <div className="grid gap-4 xl:grid-cols-3">
        <Skeleton className="h-80 rounded-xl xl:col-span-2" />
        <Skeleton className="h-80 rounded-xl" />
      </div>
    </div>
  );
}

export function DashboardView() {
  const me = useMe();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["dashboard"], queryFn: api.dashboard, refetchInterval: 30_000 });
  const analyze = useMutation({
    mutationFn: () => api.analysis.run(me.data?.settings?.default_symbol ?? "BTC-USD", me.data?.settings?.default_timeframe ?? "1h"),
    onSuccess: (a) => {
      toast.success(`Analysis complete: ${a.summary}`);
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const firstName = me.data?.full_name.split(" ")[0];

  return (
    <>
      <PageHeader
        title={firstName ? `Good to see you, ${firstName}` : "Dashboard"}
        description="Your simulated portfolio and today's market picture."
        actions={
          <>
            <Button variant="outline" size="sm" asChild>
              <Link href="/paper-trading">
                <DollarSign /> Trade
              </Link>
            </Button>
            <Button size="sm" onClick={() => analyze.mutate()} loading={analyze.isPending}>
              <Sparkles /> Run AI analysis
            </Button>
          </>
        }
      />
      {q.isLoading ? (
        <DashboardSkeleton />
      ) : q.error ? (
        <Card>
          <ErrorState error={q.error} onRetry={() => q.refetch()} />
        </Card>
      ) : q.data ? (
        (() => {
          const d = q.data;
          const p = d.portfolio;
          const history = d.equity_history.map((s) => ({ time: Math.floor(new Date(s.ts).getTime() / 1000), equity: s.equity }));
          if (history.length < 2) history.push({ time: Math.floor(q.dataUpdatedAt / 1000), equity: p.equity });
          const watchSymbols = d.watchlist.map((w) => w.asset.symbol);
          return (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
                <StatCard label="Virtual portfolio value" icon={Landmark} value={formatUsd(p.equity)} sub={<Change value={p.total_return_pct} className="text-xs" />} hint="Simulated equity: cash + marked-to-market positions." />
                <StatCard
                  label="24h simulated P&L"
                  icon={Activity}
                  value={<span className={pnlClass(p.daily_pnl)}>{formatUsd(p.daily_pnl, { sign: true })}</span>}
                  sub={<Change value={p.daily_pnl_pct} className="text-xs" />}
                  hint="Change in equity versus the snapshot closest to 24 hours ago."
                />
                <StatCard label="Total P&L" icon={TrendingUp} value={<span className={pnlClass(p.total_pnl)}>{formatUsd(p.total_pnl, { sign: true })}</span>} sub={`Realized ${formatUsd(p.realized_pnl, { sign: true })} · Unrealized ${formatUsd(p.unrealized_pnl, { sign: true })}`} />
                <StatCard label="Buying power" icon={DollarSign} value={formatUsd(p.available_cash)} sub={`${p.positions.length} open position${p.positions.length === 1 ? "" : "s"}`} />
              </div>

              <div className="grid gap-4 xl:grid-cols-3">
                <Card className="xl:col-span-2">
                  <CardHeader>
                    <div>
                      <CardTitle>Portfolio performance</CardTitle>
                      <CardDescription>Simulated equity over time</CardDescription>
                    </div>
                    <Badge variant="outline">Paper</Badge>
                  </CardHeader>
                  <CardContent>
                    {hasChartableSpan(history) ? (
                      <EquityAreaChart data={history} baseline={p.starting_balance} height={260} />
                    ) : (
                      <YoungHistoryNote since={history[0]?.time} height={260} />
                    )}
                  </CardContent>
                </Card>
                <SentimentCard sentiment={d.sentiment} />
              </div>

              <div className="grid gap-4 xl:grid-cols-3">
                <Card className="xl:col-span-2">
                  <CardHeader>
                    <div>
                      <CardTitle>Market overview</CardTitle>
                      <DataSource meta={d.meta} />
                    </div>
                    <Button variant="ghost" size="sm" asChild>
                      <Link href="/markets">
                        All markets <ArrowRight />
                      </Link>
                    </Button>
                  </CardHeader>
                  <CardContent className="px-2 pb-2">
                    <MarketTable rows={d.market} />
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader>
                    <CardTitle>Watchlist</CardTitle>
                    <Button variant="ghost" size="sm" asChild>
                      <Link href="/markets">Edit</Link>
                    </Button>
                  </CardHeader>
                  <CardContent className="px-2 pb-2">
                    {watchSymbols.length ? (
                      <MarketTable rows={d.watchlist} compact />
                    ) : (
                      <EmptyState title="Your watchlist is empty" description="Star assets on the Markets page to track them here." />
                    )}
                  </CardContent>
                </Card>
              </div>

              <div className="grid gap-4 xl:grid-cols-3">
                <Card>
                  <CardHeader>
                    <div>
                      <CardTitle className="flex items-center gap-1.5">
                        <BrainCircuit className="size-4 text-primary" /> AI market insight
                      </CardTitle>
                      <CardDescription>{d.insight ? `${d.insight.symbol} · ${d.insight.timeframe} · ${timeAgo(d.insight.created_at)}` : "Latest analysis"}</CardDescription>
                    </div>
                  </CardHeader>
                  <CardContent>
                    {d.insight ? (
                      <div className="space-y-3">
                        <p className="text-sm font-medium">{d.insight.summary}</p>
                        <p className="line-clamp-6 text-xs leading-relaxed whitespace-pre-line text-muted-foreground">{d.insight.narrative}</p>
                        <div className="flex items-center justify-between">
                          <Badge variant="outline">{d.insight.narrative_source === "rule_based" ? "Rule-based summary" : d.insight.narrative_source}</Badge>
                          <Link href="/analysis" className="text-xs font-medium text-primary hover:underline">Full analysis →</Link>
                        </div>
                        <p className="text-[10px] text-muted-foreground">Estimate from historical data — not a prediction or advice.</p>
                      </div>
                    ) : (
                      <EmptyState icon={BrainCircuit} title="No analysis yet" description="Run an AI analysis to see an explainable market brief here." action={<Button size="sm" onClick={() => analyze.mutate()} loading={analyze.isPending}>Analyze now</Button>} />
                    )}
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <CardTitle>Recent signals</CardTitle>
                    <Button variant="ghost" size="sm" asChild>
                      <Link href="/analysis">View all</Link>
                    </Button>
                  </CardHeader>
                  <CardContent>
                    {d.signals.length ? (
                      <ul className="divide-y divide-border">
                        {d.signals.map((s) => (
                          <li key={s.id} className="flex items-center gap-3 py-2.5">
                            <SignalBadge action={s.action} />
                            <div className="min-w-0 flex-1">
                              <p className="text-sm font-medium">{s.asset.symbol} <span className="text-xs font-normal text-muted-foreground">{s.timeframe}</span></p>
                              <p className="text-xs text-muted-foreground">@ {formatPrice(s.price_at_signal)} · {timeAgo(s.created_at)}</p>
                            </div>
                            <span className="text-xs text-muted-foreground tabular">{s.confidence.toFixed(0)}/100</span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <EmptyState icon={LineChart} title="No signals yet" description="Signals appear after you run an analysis." />
                    )}
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <CardTitle>Recent trading activity</CardTitle>
                    <Button variant="ghost" size="sm" asChild>
                      <Link href="/paper-trading">Open</Link>
                    </Button>
                  </CardHeader>
                  <CardContent>
                    {d.recent_orders.length ? (
                      <ul className="divide-y divide-border">
                        {d.recent_orders.map((o) => (
                          <li key={o.id} className="flex items-center gap-3 py-2.5 text-sm">
                            <span className={cn("w-9 text-xs font-semibold uppercase", o.side === "buy" ? "text-gain" : "text-loss")}>{o.side}</span>
                            <div className="min-w-0 flex-1">
                              <p className="font-medium">{formatQty(o.quantity)} {o.asset.base_currency}</p>
                              <p className="text-xs text-muted-foreground">
                                {o.filled_price ? `${o.order_type} @ ${formatPrice(o.filled_price)}` : o.limit_price ? `limit @ ${formatPrice(o.limit_price)}` : o.order_type} · {timeAgo(o.created_at)}
                              </p>
                            </div>
                            <Badge variant={o.status === "filled" ? "gain" : o.status === "open" ? "info" : o.status === "rejected" ? "loss" : "secondary"}>{o.status}</Badge>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <EmptyState icon={Activity} title="No simulated trades yet" description="Place a paper order to start building a track record." />
                    )}
                  </CardContent>
                </Card>
              </div>
            </div>
          );
        })()
      ) : null}
    </>
  );
}
