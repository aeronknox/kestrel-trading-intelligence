"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, MoreHorizontal, Pencil, Plus, Trash2, Workflow } from "lucide-react";
import Link from "next/link";
import { toast } from "sonner";

import { EmptyState, ErrorState, LoadingRows } from "@/components/common/states";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/overlays";
import { Badge } from "@/components/ui/primitives";
import { RunBacktestDialog } from "@/features/backtesting/run-backtest-dialog";
import { formatPct, pnlClass, timeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";
import { api } from "@/services/api";
import type { Strategy } from "@/types/api";

import { describeRuleSet } from "./rules";

function StrategyCard({ s }: { s: Strategy }) {
  const qc = useQueryClient();
  const remove = useMutation({
    mutationFn: () => api.strategies.remove(s.id),
    onSuccess: () => {
      toast.success(`Deleted “${s.name}”`);
      qc.invalidateQueries({ queryKey: ["strategies"] });
      qc.invalidateQueries({ queryKey: ["backtests"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const archive = useMutation({
    mutationFn: () => api.strategies.update(s.id, { is_archived: true }),
    onSuccess: () => {
      toast.success(`Archived “${s.name}”`);
      qc.invalidateQueries({ queryKey: ["strategies"] });
    },
  });
  const c = s.current_config;
  const bt = s.latest_backtest;
  return (
    <Card className="flex flex-col">
      <CardHeader>
        <div className="min-w-0">
          <CardTitle className="truncate">
            <Link href={`/strategies/${s.id}`} className="hover:text-primary">{s.name}</Link>
          </CardTitle>
          <CardDescription>
            {c?.asset.symbol} · {c?.timeframe} · v{s.current_version} · updated {timeAgo(s.updated_at)}
          </CardDescription>
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon-sm" aria-label="Strategy actions"><MoreHorizontal /></Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem asChild><Link href={`/strategies/${s.id}`}><Pencil /> Edit</Link></DropdownMenuItem>
            <DropdownMenuItem onSelect={() => archive.mutate()}><Archive /> Archive</DropdownMenuItem>
            <DropdownMenuItem
              className="text-loss"
              onSelect={() => {
                if (window.confirm(`Delete “${s.name}” and all its backtests? This cannot be undone.`)) remove.mutate();
              }}
            >
              <Trash2 /> Delete
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-4">
        {s.description && <p className="line-clamp-2 text-xs text-muted-foreground">{s.description}</p>}
        <div className="space-y-1.5 text-xs">
          <p><span className="font-medium text-gain">Entry:</span> <span className="text-muted-foreground">{c ? describeRuleSet(c.entry_rules) : "—"}</span></p>
          <p><span className="font-medium text-loss">Exit:</span> <span className="text-muted-foreground">{c ? describeRuleSet(c.exit_rules) : "—"}</span></p>
        </div>
        <div className="mt-auto grid grid-cols-3 gap-2 rounded-lg bg-muted/40 p-2.5 text-center">
          {bt && bt.status === "completed" ? (
            <>
              <div><p className="text-[10px] text-muted-foreground">Return</p><p className={cn("text-sm font-semibold tabular", pnlClass(bt.total_return_pct))}>{formatPct(bt.total_return_pct, 1)}</p></div>
              <div><p className="text-[10px] text-muted-foreground">Max DD</p><p className="text-sm font-semibold text-loss tabular">{formatPct(bt.max_drawdown_pct, 1, false)}</p></div>
              <div><p className="text-[10px] text-muted-foreground">Trades</p><p className="text-sm font-semibold tabular">{bt.num_trades}</p></div>
            </>
          ) : (
            <p className="col-span-3 py-1.5 text-xs text-muted-foreground">{bt?.status === "failed" ? "Last backtest failed" : "Not backtested yet"}</p>
          )}
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" className="flex-1" asChild>
            <Link href={`/strategies/${s.id}`}><Pencil /> Edit</Link>
          </Button>
          <div className="flex-1 [&>button]:w-full">
            <RunBacktestDialog strategyId={s.id} strategyName={s.name} />
          </div>
        </div>
        {bt && <Link href={`/backtests/${bt.id}`} className="text-center text-[11px] text-primary hover:underline">Latest result (hypothetical) →</Link>}
      </CardContent>
    </Card>
  );
}

export function StrategiesView() {
  const strategies = useQuery({ queryKey: ["strategies"], queryFn: () => api.strategies.list() });
  const templates = useQuery({ queryKey: ["strategy-templates"], queryFn: api.strategies.templates, staleTime: Infinity });

  return (
    <>
      <PageHeader
        title="Strategy Builder"
        description="Define rule-based strategies from technical indicators and test them against history."
        actions={
          <Button size="sm" asChild>
            <Link href="/strategies/new"><Plus /> New strategy</Link>
          </Button>
        }
      />
      {strategies.isLoading ? (
        <LoadingRows rows={4} />
      ) : strategies.error ? (
        <Card><ErrorState error={strategies.error} onRetry={() => strategies.refetch()} /></Card>
      ) : strategies.data?.length ? (
        <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
          {strategies.data.map((s) => <StrategyCard key={s.id} s={s} />)}
        </div>
      ) : (
        <Card>
          <EmptyState icon={Workflow} title="No strategies yet" description="Start from scratch or pick one of the templates below." action={<Button size="sm" asChild><Link href="/strategies/new"><Plus /> New strategy</Link></Button>} />
        </Card>
      )}

      <h2 className="mt-8 mb-3 text-sm font-semibold">Start from a template</h2>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {(templates.data?.templates ?? []).map((t) => (
          <Link key={t.key} href={`/strategies/new?template=${t.key}`} className="group rounded-xl border border-border bg-card p-4 transition-colors hover:border-primary/40">
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium group-hover:text-primary">{t.name}</p>
              <Badge variant="outline">{t.timeframe}</Badge>
            </div>
            <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">{t.description}</p>
          </Link>
        ))}
      </div>
    </>
  );
}
