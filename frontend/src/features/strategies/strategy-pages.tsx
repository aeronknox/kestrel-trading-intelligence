"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, SlidersHorizontal } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { ErrorState, LoadingRows } from "@/components/common/states";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Badge } from "@/components/ui/primitives";
import { RunBacktestDialog } from "@/features/backtesting/run-backtest-dialog";
import { formatPct, formatNumber, pnlClass, timeAgo } from "@/lib/format";
import { api } from "@/services/api";

import { DEFAULT_RISK } from "./rules";
import { blankDraft, draftFromStrategy, StrategyEditor } from "./strategy-editor";

const Back = () => (
  <Button variant="ghost" size="sm" asChild className="mb-2 -ml-2">
    <Link href="/strategies"><ArrowLeft /> Strategies</Link>
  </Button>
);

export function NewStrategyView() {
  const params = useSearchParams();
  const key = params.get("template");
  const templates = useQuery({ queryKey: ["strategy-templates"], queryFn: api.strategies.templates, staleTime: Infinity, enabled: !!key });
  if (key && templates.isLoading) return <LoadingRows rows={8} />;
  const tpl = templates.data?.templates.find((t) => t.key === key);
  const initial = tpl
    ? { ...blankDraft(), name: tpl.name, description: tpl.description, timeframe: tpl.timeframe, entry: tpl.definition.entry, exit: tpl.definition.exit, risk: { ...DEFAULT_RISK, stop_loss_pct: null, ...tpl.definition.risk } }
    : blankDraft();
  return (
    <>
      <Back />
      <PageHeader title={tpl ? `New strategy from “${tpl.name}”` : "New strategy"} description="Combine indicator conditions with risk rules." />
      <StrategyEditor key={key ?? "blank"} initial={initial} />
    </>
  );
}

export function EditStrategyView({ id }: { id: number }) {
  const strategy = useQuery({ queryKey: ["strategy", id], queryFn: () => api.strategies.get(id) });
  const backtests = useQuery({ queryKey: ["backtests", { strategy: id }], queryFn: () => api.backtests.list(id) });

  if (strategy.isLoading) return <LoadingRows rows={8} />;
  if (strategy.error || !strategy.data) return <Card><ErrorState error={strategy.error ?? new Error("Not found")} onRetry={() => strategy.refetch()} /></Card>;
  const s = strategy.data;

  return (
    <>
      <Back />
      <PageHeader
        title={s.name}
        description={`Version ${s.current_version} · ${s.current_config?.asset.symbol} · ${s.current_config?.timeframe}`}
        actions={
          <>
            <Button size="sm" variant="outline" asChild>
              <Link href={`/research/new?strategy=${s.id}`}><SlidersHorizontal /> Optimize</Link>
            </Button>
            <RunBacktestDialog strategyId={s.id} strategyName={s.name} />
          </>
        }
      />
      <StrategyEditor key={`${s.id}-${s.current_version}`} initial={draftFromStrategy(s)} strategyId={s.id} />
      <Card className="mt-4">
        <CardHeader><CardTitle>Backtest history</CardTitle></CardHeader>
        <CardContent className="px-2">
          {backtests.data?.length ? (
            <Table>
              <THead>
                <TR className="hover:bg-transparent"><TH>Run</TH><TH>Status</TH><TH className="text-right">Return</TH><TH className="text-right">Max DD</TH><TH className="text-right">Sharpe</TH><TH className="text-right">Win rate</TH><TH className="text-right">Trades</TH><TH /></TR>
              </THead>
              <TBody>
                {backtests.data.map((b) => (
                  <TR key={b.id}>
                    <TD className="text-muted-foreground">#{b.id} · {timeAgo(b.created_at)}</TD>
                    <TD><Badge variant={b.status === "completed" ? "gain" : b.status === "failed" ? "loss" : "info"}>{b.status}</Badge></TD>
                    <TD className={`text-right ${pnlClass(b.total_return_pct)}`}>{formatPct(b.total_return_pct)}</TD>
                    <TD className="text-right text-loss">{formatPct(b.max_drawdown_pct, 2, false)}</TD>
                    <TD className="text-right">{formatNumber(b.sharpe_ratio)}</TD>
                    <TD className="text-right">{formatPct(b.win_rate, 1, false)}</TD>
                    <TD className="text-right">{b.num_trades ?? "—"}</TD>
                    <TD className="text-right"><Link className="text-xs text-primary hover:underline" href={`/backtests/${b.id}`}>View</Link></TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          ) : (
            <p className="px-3 py-4 text-sm text-muted-foreground">No backtests yet. Run one to see hypothetical historical performance.</p>
          )}
        </CardContent>
      </Card>
    </>
  );
}
