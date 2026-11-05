"use client";

import { useQuery } from "@tanstack/react-query";
import { PieChart } from "lucide-react";
import Link from "next/link";

import { StatCard } from "@/components/common/finance";
import { EmptyState, ErrorState, LoadingRows } from "@/components/common/states";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/primitives";
import { AllocationDonut, DrawdownChart, EquityAreaChart } from "@/features/charts/recharts";
import { formatNumber, formatPct, formatUsd, pnlClass } from "@/lib/format";
import { api } from "@/services/api";

export function PortfolioView() {
  const portfolio = useQuery({ queryKey: ["paper", "portfolio"], queryFn: api.paper.portfolio, refetchInterval: 30_000 });
  const history = useQuery({ queryKey: ["paper", "history"], queryFn: api.paper.history, refetchInterval: 60_000 });
  const analytics = useQuery({ queryKey: ["paper", "analytics"], queryFn: api.paper.analytics });

  if (portfolio.isLoading) return <LoadingRows rows={8} />;
  if (portfolio.error || !portfolio.data) return <Card><ErrorState error={portfolio.error} onRetry={() => portfolio.refetch()} /></Card>;
  const p = portfolio.data;
  const a = analytics.data;

  const curve = (history.data ?? []).map((s) => ({ time: Math.floor(new Date(s.ts).getTime() / 1000), equity: s.equity }));
  if (curve.length < 2) curve.push({ time: Math.floor(Date.now() / 1000), equity: p.equity });
  let peak = 0;
  const dd = curve.map((c) => {
    peak = Math.max(peak, c.equity);
    return { time: c.time, drawdown_pct: peak ? (c.equity / peak - 1) * 100 : 0 };
  });
  const allocation = [
    ...p.positions.map((pos) => ({ name: pos.asset.symbol, value: pos.market_value })),
    { name: "Cash", value: p.cash_balance },
  ].filter((x) => x.value > 0);

  return (
    <>
      <PageHeader
        title="Portfolio Analytics"
        description="Performance and risk of your simulated portfolio."
        actions={<Button size="sm" variant="outline" asChild><Link href="/paper-trading">Trade</Link></Button>}
      />
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
          <StatCard label="Equity" value={formatUsd(p.equity)} sub={<span className={pnlClass(p.total_return_pct)}>{formatPct(p.total_return_pct)}</span>} />
          <StatCard label="24h P&L" value={<span className={pnlClass(p.daily_pnl)}>{formatUsd(p.daily_pnl, { sign: true })}</span>} sub={formatPct(p.daily_pnl_pct)} />
          <StatCard label="Win rate" value={formatPct(a?.win_rate, 1, false)} sub={`${a?.closed_trades ?? 0} closing trades`} hint="Share of sell fills with positive realized P&L." />
          <StatCard label="Profit factor" value={formatNumber(a?.profit_factor)} sub="Gross wins ÷ gross losses" />
          <StatCard label="Max drawdown" value={<span className="text-loss">{formatPct(a?.max_drawdown_pct, 2, false)}</span>} sub="From equity snapshots" />
          <StatCard label="Fees paid" value={formatUsd(p.total_fees)} sub={`${a?.total_trades ?? 0} fills`} />
        </div>
        <div className="grid gap-4 xl:grid-cols-3">
          <Card className="xl:col-span-2">
            <CardHeader>
              <div>
                <CardTitle>Equity history</CardTitle>
                <CardDescription>Snapshots recorded after each fill and every few minutes while positions are open</CardDescription>
              </div>
              <Badge variant="outline">Simulated</Badge>
            </CardHeader>
            <CardContent className="space-y-2">
              <EquityAreaChart data={curve} baseline={p.starting_balance} height={260} />
              <p className="pt-1 text-xs font-medium text-muted-foreground">Drawdown</p>
              <DrawdownChart data={dd} height={120} />
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Allocation</CardTitle></CardHeader>
            <CardContent>
              {allocation.length ? (
                <>
                  <AllocationDonut data={allocation} />
                  <ul className="mt-3 space-y-1.5 text-xs">
                    {allocation.map((x) => (
                      <li key={x.name} className="flex justify-between tabular">
                        <span className="text-muted-foreground">{x.name}</span>
                        <span>{formatUsd(x.value)} <span className="text-muted-foreground">({formatPct((x.value / p.equity) * 100, 1, false)})</span></span>
                      </li>
                    ))}
                  </ul>
                </>
              ) : (
                <EmptyState icon={PieChart} title="Nothing allocated" />
              )}
            </CardContent>
          </Card>
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader><CardTitle>Trade statistics</CardTitle></CardHeader>
            <CardContent>
              <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
                {[
                  ["Average win", formatUsd(a?.avg_win, { sign: true }), pnlClass(a?.avg_win)],
                  ["Average loss", formatUsd(a?.avg_loss, { sign: true }), pnlClass(a?.avg_loss)],
                  ["Best trade", formatUsd(a?.best_trade, { sign: true }), pnlClass(a?.best_trade)],
                  ["Worst trade", formatUsd(a?.worst_trade, { sign: true }), pnlClass(a?.worst_trade)],
                  ["Realized P&L", formatUsd(p.realized_pnl, { sign: true }), pnlClass(p.realized_pnl)],
                  ["Unrealized P&L", formatUsd(p.unrealized_pnl, { sign: true }), pnlClass(p.unrealized_pnl)],
                ].map(([label, value, cls]) => (
                  <div key={label} className="flex justify-between border-b border-border/60 pb-2">
                    <dt className="text-muted-foreground">{label}</dt>
                    <dd className={`font-medium tabular ${cls}`}>{value}</dd>
                  </div>
                ))}
              </dl>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Position performance</CardTitle></CardHeader>
            <CardContent>
              {p.positions.length ? (
                <ul className="space-y-3">
                  {p.positions.map((pos) => {
                    const pct = pos.unrealized_pnl_pct ?? 0;
                    return (
                      <li key={pos.id}>
                        <div className="flex justify-between text-sm">
                          <span className="font-medium">{pos.asset.symbol}</span>
                          <span className={`tabular ${pnlClass(pct)}`}>{formatUsd(pos.unrealized_pnl, { sign: true })} ({formatPct(pct, 1)})</span>
                        </div>
                        <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted">
                          <div className={pct >= 0 ? "h-full bg-gain" : "h-full bg-loss"} style={{ width: `${Math.min(100, Math.abs(pct) * 5)}%` }} />
                        </div>
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <EmptyState title="No open positions" description="Open positions and their P&L will appear here." />
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  );
}
