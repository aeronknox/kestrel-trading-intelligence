"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, FlaskConical, GitCompare, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Disclaimer, StatCard } from "@/components/common/finance";
import { EmptyState, ErrorState, LoadingRows } from "@/components/common/states";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/primitives";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { DrawdownChart, EquityAreaChart, MultiLineChart } from "@/features/charts/recharts";
import { formatDate, formatDateTime, formatNumber, formatPct, formatPrice, formatQty, formatUsd, isNum, pnlClass, timeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";
import { api } from "@/services/api";
import type { Backtest } from "@/types/api";

const EXIT_LABEL: Record<string, string> = {
  signal: "Exit signal",
  stop_loss: "Stop-loss",
  take_profit: "Take-profit",
  trailing_stop: "Trailing stop",
  time_limit: "Time limit",
  end_of_data: "End of data",
};

// -------------------------------------------------------------------- list
export function BacktestListView() {
  const router = useRouter();
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["backtests"], queryFn: () => api.backtests.list() });
  const strategies = useQuery({ queryKey: ["strategies"], queryFn: () => api.strategies.list(true) });
  const [selected, setSelected] = useState<number[]>([]);
  const names = new Map((strategies.data ?? []).map((s) => [s.id, s.name]));
  const remove = useMutation({
    mutationFn: api.backtests.remove,
    onSuccess: (_, id) => {
      setSelected((s) => s.filter((x) => x !== id));
      qc.invalidateQueries({ queryKey: ["backtests"] });
      qc.invalidateQueries({ queryKey: ["strategies"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const toggle = (id: number) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : s.length >= 6 ? s : [...s, id]));

  return (
    <>
      <PageHeader
        title="Backtests"
        description="Hypothetical results of strategies on historical data."
        actions={
          <Button size="sm" variant="outline" disabled={selected.length < 2} onClick={() => router.push(`/backtests/compare?ids=${selected.join(",")}`)}>
            <GitCompare /> Compare {selected.length ? `(${selected.length})` : ""}
          </Button>
        }
      />
      <Card>
        <CardContent className="px-2 pt-2">
          {list.isLoading ? (
            <LoadingRows rows={6} className="p-3" />
          ) : list.error ? (
            <ErrorState error={list.error} onRetry={() => list.refetch()} />
          ) : !list.data?.length ? (
            <EmptyState icon={FlaskConical} title="No backtests yet" description="Create a strategy and run a backtest to evaluate it on historical data." action={<Button size="sm" asChild><Link href="/strategies">Go to strategies</Link></Button>} />
          ) : (
            <Table>
              <THead>
                <TR className="hover:bg-transparent">
                  <TH className="w-8"><span className="sr-only">Select</span></TH>
                  <TH>Strategy</TH><TH>Status</TH><TH className="text-right">Return</TH><TH className="text-right">Max DD</TH><TH className="text-right">Sharpe</TH><TH className="text-right">Win rate</TH><TH className="text-right">Trades</TH><TH className="text-right">Run</TH><TH />
                </TR>
              </THead>
              <TBody>
                {list.data.map((b) => (
                  <TR key={b.id}>
                    <TD>
                      <input type="checkbox" aria-label={`Select backtest ${b.id}`} className="size-3.5 accent-[var(--primary)]" checked={selected.includes(b.id)} disabled={b.status !== "completed"} onChange={() => toggle(b.id)} />
                    </TD>
                    <TD>
                      <Link href={`/backtests/${b.id}`} className="font-medium hover:text-primary">{names.get(b.strategy_id) ?? `Strategy #${b.strategy_id}`}</Link>
                      <span className="ml-2 text-xs text-muted-foreground">{b.timeframe}</span>
                    </TD>
                    <TD><Badge variant={b.status === "completed" ? "gain" : b.status === "failed" ? "loss" : "info"}>{b.status}</Badge></TD>
                    <TD className={cn("text-right font-medium", pnlClass(b.total_return_pct))}>{formatPct(b.total_return_pct)}</TD>
                    <TD className="text-right text-loss">{formatPct(b.max_drawdown_pct, 2, false)}</TD>
                    <TD className="text-right">{formatNumber(b.sharpe_ratio)}</TD>
                    <TD className="text-right">{formatPct(b.win_rate, 1, false)}</TD>
                    <TD className="text-right">{b.num_trades ?? "—"}</TD>
                    <TD className="text-right text-muted-foreground">{timeAgo(b.created_at)}</TD>
                    <TD className="text-right">
                      <Button variant="ghost" size="icon-sm" aria-label="Delete backtest" onClick={() => window.confirm("Delete this backtest?") && remove.mutate(b.id)}>
                        <Trash2 className="text-muted-foreground" />
                      </Button>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>
      <p className="mt-3 text-xs text-muted-foreground">Select 2–6 completed backtests to compare them side by side.</p>
    </>
  );
}

// ------------------------------------------------------------------ detail
function MetricsGrid({ bt }: { bt: Backtest }) {
  const m = bt.metrics!;
  // Older runs only stored the cost-free buy-and-hold return.
  const bench = m.benchmark;
  const benchReturn = bench?.total_return_pct ?? m.buy_hold_return_pct;
  const beat = m.excess_return_pct ?? m.total_return_pct - benchReturn;
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
      <StatCard label="Total return" value={<span className={pnlClass(m.total_return_pct)}>{formatPct(m.total_return_pct)}</span>} sub={`${formatUsd(m.initial_capital)} → ${formatUsd(m.final_equity)}`} />
      <StatCard label="Buy & hold" value={<span className={pnlClass(benchReturn)}>{formatPct(benchReturn)}</span>} sub={<span className={pnlClass(beat)}>{beat >= 0 ? "Outperformed" : "Underperformed"} by {formatPct(Math.abs(beat), 2, false)}</span>} hint={bench ? "Benchmark: the same capital bought at the first bar's open and sold at the last close, paying the same fees and slippage." : "Passive benchmark: buy at the first bar's open, sell at the last close (no fees)."} />
      <StatCard label="Max drawdown" value={<span className="text-loss">{formatPct(m.max_drawdown_pct, 2, false)}</span>} sub={bench ? `Buy & hold ${formatPct(bench.max_drawdown_pct, 1, false)}` : "Peak-to-trough equity decline"} />
      <StatCard label="Sharpe ratio" value={formatNumber(m.sharpe_ratio)} sub={`Sortino ${formatNumber(m.sortino_ratio)}${bench ? ` · B&H ${formatNumber(bench.sharpe_ratio)}` : ""}`} hint="Annualized from per-bar returns (365-day year, 0% risk-free rate)." />
      <StatCard label="Win rate" value={formatPct(m.win_rate, 1, false)} sub={`${m.num_trades} trades`} />
      <StatCard label="Profit factor" value={isNum(m.profit_factor) ? formatNumber(m.profit_factor) : m.num_trades && !m.gross_loss ? "∞ (no losses)" : "—"} sub="Gross profit ÷ gross loss" />
      <StatCard label="CAGR" value={formatPct(m.cagr_pct, 1)} sub={`${formatNumber(m.period_years * 365, 0)} days tested`} hint="Annualized compound return; unreliable for short test periods." />
      <StatCard label="Exposure" value={formatPct(m.exposure_pct, 1, false)} sub="Share of bars in a position" />
      <StatCard label="Avg trade" value={<span className={pnlClass(m.avg_trade_return_pct)}>{formatPct(m.avg_trade_return_pct)}</span>} sub={`Best ${formatPct(m.best_trade_pct, 1)} · Worst ${formatPct(m.worst_trade_pct, 1)}`} />
      <StatCard label="Avg holding" value={`${formatNumber(m.avg_bars_held, 1)} bars`} sub={bt.timeframe} />
      <StatCard label="Fees paid" value={formatUsd(m.total_fees)} sub={`${bt.fee_bps} bps fee · ${bt.slippage_bps} bps slippage`} />
      <StatCard label="Volatility" value={formatPct(m.volatility_annual_pct, 1, false)} sub={isNum(m.beta) ? `Beta ${formatNumber(m.beta)} vs buy & hold` : "Annualized equity volatility"} hint="Beta: how much the strategy's per-bar returns move with buy-and-hold (1 = fully invested, 0 = no exposure)." />
    </div>
  );
}

export function BacktestDetailView({ id }: { id: number }) {
  const q = useQuery({ queryKey: ["backtest", id], queryFn: () => api.backtests.get(id) });
  if (q.isLoading) return <LoadingRows rows={8} />;
  if (q.error || !q.data) return <Card><ErrorState error={q.error ?? new Error("Not found")} onRetry={() => q.refetch()} /></Card>;
  const bt = q.data;
  const isSample = bt.data_source.includes("sample");

  return (
    <>
      <Button variant="ghost" size="sm" asChild className="mb-2 -ml-2">
        <Link href="/backtests"><ArrowLeft /> Backtests</Link>
      </Button>
      <PageHeader
        title={<>{bt.strategy_name} <span className="text-base font-normal text-muted-foreground">v{bt.strategy_version}</span></>}
        description={`${bt.asset.symbol} · ${bt.timeframe} · ${formatDate(bt.start_at)} – ${formatDate(bt.end_at)} · run ${formatDateTime(bt.created_at)}`}
        actions={
          <Button variant="outline" size="sm" asChild>
            <Link href={`/strategies/${bt.strategy_id}`}>Open strategy</Link>
          </Button>
        }
      />
      <Disclaimer className="mb-4">
        {bt.disclaimer}
        {isSample && <strong> This run used SAMPLE (synthetic) data.</strong>}
        {bt.metrics?.bars_requested !== undefined && bt.metrics.bars < bt.metrics.bars_requested && (
          <> Only {bt.metrics.bars.toLocaleString()} of the {bt.metrics.bars_requested.toLocaleString()} requested bars were available.</>
        )}
      </Disclaimer>

      {bt.status === "failed" ? (
        <Card><EmptyState icon={FlaskConical} title="Backtest failed" description={bt.error ?? "Unknown error"} /></Card>
      ) : bt.metrics && bt.equity_curve ? (
        <div className="space-y-4">
          <MetricsGrid bt={bt} />
          <div className="grid gap-4 xl:grid-cols-3">
            <Card className="xl:col-span-2">
              <CardHeader>
                <div>
                  <CardTitle>Equity curve</CardTitle>
                  <CardDescription>Marked to market at each bar close{bt.equity_curve.some((p) => p.benchmark !== undefined) ? ", against buy & hold" : ""}</CardDescription>
                </div>
              </CardHeader>
              <CardContent className="space-y-2">
                <EquityAreaChart data={bt.equity_curve} baseline={bt.initial_capital} height={280} />
                <p className="pt-2 text-xs font-medium text-muted-foreground">Drawdown</p>
                <DrawdownChart data={bt.equity_curve} />
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle>Simulation assumptions</CardTitle></CardHeader>
              <CardContent className="space-y-3 text-xs text-muted-foreground">
                <p><span className="font-medium text-foreground">Execution:</span> rules evaluated on each bar&apos;s close; orders fill at the next bar&apos;s open (prevents look-ahead bias).</p>
                <p><span className="font-medium text-foreground">Costs:</span> {bt.fee_bps} bps fee and {bt.slippage_bps} bps adverse slippage on every fill.</p>
                <p><span className="font-medium text-foreground">Protective exits:</span> checked against bar high/low; gaps fill at the open; if stop and target touch in one bar the stop is assumed first.</p>
                <p><span className="font-medium text-foreground">Warm-up:</span> ~{bt.metrics.warmup_bars} bars before all indicators are defined (no trades possible).</p>
                <p><span className="font-medium text-foreground">Signals:</span> {bt.metrics.signal_counts.entries} entry / {bt.metrics.signal_counts.exits} exit triggers over {bt.metrics.bars} closed bars.</p>
                <p><span className="font-medium text-foreground">Data:</span> {bt.data_source}. Long-only, no leverage, no funding costs.</p>
              </CardContent>
            </Card>
          </div>
          <Card>
            <CardHeader><CardTitle>Trades ({bt.trades?.length ?? 0})</CardTitle></CardHeader>
            <CardContent className="px-2">
              {bt.trades?.length ? (
                <Table>
                  <THead>
                    <TR className="hover:bg-transparent"><TH>#</TH><TH>Entry</TH><TH className="text-right">Entry price</TH><TH>Exit</TH><TH className="text-right">Exit price</TH><TH className="text-right">Qty</TH><TH className="text-right">P&amp;L</TH><TH className="text-right">Return</TH><TH className="text-right">Bars</TH><TH>Reason</TH></TR>
                  </THead>
                  <TBody>
                    {bt.trades.map((t, i) => (
                      <TR key={i}>
                        <TD className="text-muted-foreground">{i + 1}</TD>
                        <TD>{formatDateTime(t.entry_time)}</TD>
                        <TD className="text-right">{formatPrice(t.entry_price)}</TD>
                        <TD>{formatDateTime(t.exit_time)}</TD>
                        <TD className="text-right">{formatPrice(t.exit_price)}</TD>
                        <TD className="text-right">{formatQty(t.quantity)}</TD>
                        <TD className={cn("text-right font-medium", pnlClass(t.pnl))}>{formatUsd(t.pnl, { sign: true })}</TD>
                        <TD className={cn("text-right", pnlClass(t.return_pct))}>{formatPct(t.return_pct)}</TD>
                        <TD className="text-right">{t.bars_held}</TD>
                        <TD><Badge variant="outline">{EXIT_LABEL[t.exit_reason] ?? t.exit_reason}</Badge></TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              ) : (
                <EmptyState title="No trades" description="Entry conditions never triggered in this period. Try a longer history or looser rules." />
              )}
            </CardContent>
          </Card>
        </div>
      ) : null}
    </>
  );
}

// ----------------------------------------------------------------- compare
const COMPARE_ROWS: { label: string; get: (b: Backtest) => number | null | undefined; fmt: (v: number | null | undefined) => string; better: "high" | "low" }[] = [
  { label: "Total return", get: (b) => b.metrics?.total_return_pct, fmt: (v) => formatPct(v), better: "high" },
  { label: "Buy & hold", get: (b) => b.metrics?.buy_hold_return_pct, fmt: (v) => formatPct(v), better: "high" },
  { label: "Max drawdown", get: (b) => b.metrics?.max_drawdown_pct, fmt: (v) => formatPct(v, 2, false), better: "high" },
  { label: "Sharpe", get: (b) => b.metrics?.sharpe_ratio, fmt: (v) => formatNumber(v), better: "high" },
  { label: "Sortino", get: (b) => b.metrics?.sortino_ratio, fmt: (v) => formatNumber(v), better: "high" },
  { label: "Win rate", get: (b) => b.metrics?.win_rate, fmt: (v) => formatPct(v, 1, false), better: "high" },
  { label: "Profit factor", get: (b) => b.metrics?.profit_factor, fmt: (v) => formatNumber(v), better: "high" },
  { label: "Trades", get: (b) => b.metrics?.num_trades, fmt: (v) => formatNumber(v, 0), better: "high" },
  { label: "Exposure", get: (b) => b.metrics?.exposure_pct, fmt: (v) => formatPct(v, 1, false), better: "low" },
  { label: "Fees", get: (b) => b.metrics?.total_fees, fmt: (v) => formatUsd(v), better: "low" },
];

export function BacktestCompareView() {
  const params = useSearchParams();
  const ids = (params.get("ids") ?? "").split(",").map(Number).filter((n) => Number.isInteger(n) && n > 0);
  const q = useQuery({ queryKey: ["backtest-compare", ids], queryFn: () => api.backtests.compare(ids), enabled: ids.length > 0 });

  return (
    <>
      <Button variant="ghost" size="sm" asChild className="mb-2 -ml-2">
        <Link href="/backtests"><ArrowLeft /> Backtests</Link>
      </Button>
      <PageHeader title="Compare strategies" description="Hypothetical historical performance, side by side." />
      {ids.length < 2 ? (
        <Card><EmptyState icon={GitCompare} title="Select at least two backtests" description="Choose backtests from the list to compare them." /></Card>
      ) : q.isLoading ? (
        <LoadingRows rows={8} />
      ) : q.error ? (
        <Card><ErrorState error={q.error} onRetry={() => q.refetch()} /></Card>
      ) : q.data ? (
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <div>
                <CardTitle>Cumulative return</CardTitle>
                <CardDescription>Equity normalized to each run&apos;s initial capital</CardDescription>
              </div>
            </CardHeader>
            <CardContent>
              <MultiLineChart
                series={q.data.map((b) => ({
                  name: `${b.strategy_name} v${b.strategy_version} (${b.asset.symbol} ${b.timeframe})`,
                  points: (b.equity_curve ?? []).map((p) => ({ time: p.time, value: (p.equity / b.initial_capital - 1) * 100 })),
                }))}
              />
            </CardContent>
          </Card>
          <Card>
            <CardContent className="px-2 pt-2">
              <Table>
                <THead>
                  <TR className="hover:bg-transparent">
                    <TH>Metric</TH>
                    {q.data.map((b) => (
                      <TH key={b.id} className="text-right normal-case">
                        <Link href={`/backtests/${b.id}`} className="hover:text-primary">{b.strategy_name}</Link>
                        <div className="text-[10px] font-normal">{b.asset.symbol} · {b.timeframe} · #{b.id}</div>
                      </TH>
                    ))}
                  </TR>
                </THead>
                <TBody>
                  {COMPARE_ROWS.map((row) => {
                    const vals = q.data.map(row.get);
                    const nums = vals.filter(isNum);
                    const best = nums.length ? (row.better === "high" ? Math.max(...nums) : Math.min(...nums)) : null;
                    return (
                      <TR key={row.label}>
                        <TD className="text-muted-foreground">{row.label}</TD>
                        {vals.map((v, i) => (
                          <TD key={i} className={cn("text-right", v === best && nums.length > 1 && "font-semibold text-primary")}>{row.fmt(v)}</TD>
                        ))}
                      </TR>
                    );
                  })}
                </TBody>
              </Table>
            </CardContent>
          </Card>
          <Disclaimer>Comparisons of hypothetical backtests can overstate differences — runs may cover different assets, timeframes and periods. Past performance does not guarantee future results.</Disclaimer>
        </div>
      ) : null}
    </>
  );
}
