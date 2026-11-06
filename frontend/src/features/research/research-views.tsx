"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Plus, SlidersHorizontal, Trash2, X } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Disclaimer, StatCard } from "@/components/common/finance";
import { EmptyState, ErrorState, LoadingRows } from "@/components/common/states";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/overlays";
import { Badge, Field, Input } from "@/components/ui/primitives";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { HistoryHint } from "@/features/backtesting/history-hint";
import { MultiLineChart } from "@/features/charts/recharts";
import { formatDate, formatDateTime, formatNumber, formatPct, isNum, pnlClass, timeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";
import { api } from "@/services/api";
import type { ResearchObjective, ResearchRun, RunSummaryMetrics, SweepResult, WalkForwardResult } from "@/types/api";

import { defaultRange, gridProblem, objectiveValue, preferredSecond, rangeValues, shortLabel } from "./grid";

const OBJECTIVES: { value: ResearchObjective; label: string; hint: string }[] = [
  { value: "sharpe_ratio", label: "Sharpe ratio", hint: "Risk-adjusted return" },
  { value: "total_return_pct", label: "Total return", hint: "Raw return; ignores risk" },
  { value: "return_over_drawdown", label: "Return ÷ drawdown", hint: "Return per unit of worst decline" },
];

function formatScore(objective: ResearchObjective, v: number | null | undefined): string {
  return objective === "total_return_pct" ? formatPct(v) : formatNumber(v);
}

function formatValue(v: number): string {
  return Number.isInteger(v) ? String(v) : String(Math.round(v * 1000) / 1000);
}

// -------------------------------------------------------------------- list
export function ResearchListView() {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["research"], queryFn: () => api.research.list() });
  const remove = useMutation({
    mutationFn: api.research.remove,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["research"] }),
    onError: (e: Error) => toast.error(e.message),
  });
  return (
    <>
      <PageHeader
        title="Optimization"
        description="Parameter sweeps and walk-forward tests: does a strategy hold up on data it was not tuned on?"
        actions={
          <Button size="sm" asChild>
            <Link href="/research/new"><Plus /> New analysis</Link>
          </Button>
        }
      />
      <Card>
        <CardContent className="px-2 pt-2">
          {list.isLoading ? (
            <LoadingRows rows={5} className="p-3" />
          ) : list.error ? (
            <ErrorState error={list.error} onRetry={() => list.refetch()} />
          ) : !list.data?.length ? (
            <EmptyState
              icon={SlidersHorizontal}
              title="No analyses yet"
              description="Sweep a strategy's settings to see how sensitive it is, or run a walk-forward test to check it on unseen data."
              action={<Button size="sm" asChild><Link href="/research/new">New analysis</Link></Button>}
            />
          ) : (
            <Table>
              <THead>
                <TR className="hover:bg-transparent"><TH>Strategy</TH><TH>Type</TH><TH>Result</TH><TH className="text-right">Run</TH><TH /></TR>
              </THead>
              <TBody>
                {list.data.map((r) => (
                  <TR key={r.id}>
                    <TD>
                      <Link href={`/research/${r.id}`} className="font-medium hover:text-primary">{r.strategy_name}</Link>
                      <span className="ml-2 text-xs text-muted-foreground">v{r.strategy_version} · {r.asset.symbol} · {r.timeframe}</span>
                    </TD>
                    <TD><Badge variant={r.kind === "walk_forward" ? "info" : "default"}>{r.kind === "walk_forward" ? "Walk-forward" : "Sweep"}</Badge></TD>
                    <TD className="max-w-md truncate text-muted-foreground">{r.headline ?? "Parameter grid"}</TD>
                    <TD className="text-right text-muted-foreground">{timeAgo(r.created_at)}</TD>
                    <TD className="text-right">
                      <Button size="icon-sm" variant="ghost" aria-label={`Delete analysis ${r.id}`} onClick={() => remove.mutate(r.id)}>
                        <Trash2 />
                      </Button>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </>
  );
}

// --------------------------------------------------------------------- new
interface GridRow {
  path: string;
  from: number;
  to: number;
  step: number;
}

export function NewResearchView() {
  const router = useRouter();
  const qc = useQueryClient();
  const search = useSearchParams();
  const strategies = useQuery({ queryKey: ["strategies"], queryFn: () => api.strategies.list() });
  const [chosenStrategy, setStrategyId] = useState<number | null>(Number(search.get("strategy")) || null);
  const strategyId = chosenStrategy ?? strategies.data?.[0]?.id ?? null;
  const [mode, setMode] = useState<"walk_forward" | "sweep">("walk_forward");
  const [edited, setEdited] = useState<{ strategyId: number | null; rows: GridRow[] } | null>(null);
  const [objective, setObjective] = useState<ResearchObjective>("sharpe_ratio");
  const [minTrades, setMinTrades] = useState(3);
  const [bars, setBars] = useState(2000);
  const [folds, setFolds] = useState(4);
  const [isRatio, setIsRatio] = useState(3);

  const params = useQuery({
    queryKey: ["research-parameters", strategyId],
    queryFn: () => api.research.parameters(strategyId!),
    enabled: strategyId !== null,
  });
  const selected = strategies.data?.find((s) => s.id === strategyId);
  const byPath = useMemo(() => new Map((params.data ?? []).map((p) => [p.path, p])), [params.data]);

  // Each strategy starts with its first threshold (usually the most interesting setting) until edited.
  const defaultRows = useMemo<GridRow[]>(() => {
    const first = params.data?.find((p) => p.path.endsWith(".value")) ?? params.data?.[0];
    return first ? [{ path: first.path, ...defaultRange(first) }] : [];
  }, [params.data]);
  const rows = edited && edited.strategyId === strategyId ? edited.rows : defaultRows;
  const setRows = (update: (rs: GridRow[]) => GridRow[]) => setEdited({ strategyId, rows: update(rows) });

  const grids = rows.map((r) => {
    const p = byPath.get(r.path);
    return { path: r.path, label: p?.label ?? r.path, min: p?.min ?? null, max: p?.max ?? null, values: rangeValues(r.from, r.to, r.step, p?.integer) };
  });
  const problem = rows.length ? gridProblem(grids) : "Choose a parameter";
  const combos = grids.reduce((n, g) => n * g.values.length, 1);

  const run = useMutation({
    mutationFn: () => {
      const body = {
        strategy_id: strategyId!,
        bars,
        initial_capital: 10_000,
        fee_bps: 10,
        slippage_bps: 5,
        params: grids.map((g) => ({ path: g.path, values: g.values })),
        objective,
        min_trades: minTrades,
      };
      return mode === "sweep" ? api.research.sweep(body) : api.research.walkForward({ ...body, folds, is_ratio: isRatio });
    },
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["research"] });
      toast.success("Analysis complete");
      router.push(`/research/${r.id}`);
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const setRow = (i: number, patch: Partial<GridRow>) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const unused = (params.data ?? []).filter((p) => !rows.some((r) => r.path === p.path));

  return (
    <>
      <Button variant="ghost" size="sm" asChild className="mb-2 -ml-2">
        <Link href="/research"><ArrowLeft /> Optimization</Link>
      </Button>
      <PageHeader title="New analysis" description="Every run is a hypothetical simulation on historical candles with 10 bps fees and 5 bps slippage." />
      <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
        <Card>
          <CardHeader>
            <div>
              <CardTitle>Setup</CardTitle>
              <CardDescription>Pick a strategy and the settings to vary.</CardDescription>
            </div>
          </CardHeader>
          <CardContent className="space-y-5">
            <Tabs value={mode} onValueChange={(v) => setMode(v as typeof mode)}>
              <TabsList>
                <TabsTrigger value="walk_forward">Walk-forward test</TabsTrigger>
                <TabsTrigger value="sweep">Parameter sweep</TabsTrigger>
              </TabsList>
            </Tabs>
            <p className="text-xs text-muted-foreground">
              {mode === "walk_forward"
                ? "Repeatedly picks the best settings on one window and then trades them on the next, unseen window. Only the unseen windows are scored."
                : "Runs every combination on the same data. A good strategy shows a broad region of decent results, not one lucky cell."}
            </p>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Strategy">
                <Select value={strategyId ? String(strategyId) : undefined} onValueChange={(v) => setStrategyId(Number(v))}>
                  <SelectTrigger aria-label="Strategy"><SelectValue placeholder={strategies.isLoading ? "Loading…" : "Choose a strategy"} /></SelectTrigger>
                  <SelectContent>
                    {(strategies.data ?? []).map((s) => (
                      <SelectItem key={s.id} value={String(s.id)}>{s.name} (v{s.current_version})</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field label="History (bars)" hint="200 – 20,000 closed candles">
                <Input type="number" min={200} max={20000} value={bars} onChange={(e) => setBars(Number(e.target.value))} />
              </Field>
            </div>
            <HistoryHint symbol={selected?.current_config?.asset.symbol} timeframe={selected?.current_config?.timeframe} bars={bars} />

            {strategies.data?.length === 0 && (
              <p className="text-sm text-muted-foreground">You have no strategies yet. <Link className="text-primary" href="/strategies/new">Create one first.</Link></p>
            )}
            {params.error && <ErrorState error={params.error} onRetry={() => params.refetch()} />}

            {rows.map((row, i) => {
              const p = byPath.get(row.path);
              const values = grids[i]!.values;
              return (
                <div key={i} className="space-y-3 rounded-lg border border-border p-3">
                  <div className="flex items-end gap-2">
                    <Field label={`Parameter ${i + 1}`} className="min-w-0 flex-1">
                      <Select value={row.path} onValueChange={(v) => { const np = byPath.get(v); if (np) setRow(i, { path: v, ...defaultRange(np) }); }}>
                        <SelectTrigger aria-label={`Parameter ${i + 1}`}><SelectValue /></SelectTrigger>
                        <SelectContent>
                          {[...(p ? [p] : []), ...unused].map((o) => (
                            <SelectItem key={o.path} value={o.path}>{o.label}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </Field>
                    {rows.length > 1 && (
                      <Button size="icon" variant="ghost" aria-label={`Remove parameter ${i + 1}`} onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))}><X /></Button>
                    )}
                  </div>
                  <div className="grid grid-cols-3 gap-3">
                    <Field label="From"><Input type="number" value={row.from} step="any" onChange={(e) => setRow(i, { from: Number(e.target.value) })} /></Field>
                    <Field label="To"><Input type="number" value={row.to} step="any" onChange={(e) => setRow(i, { to: Number(e.target.value) })} /></Field>
                    <Field label="Step"><Input type="number" value={row.step} step="any" min={0} onChange={(e) => setRow(i, { step: Number(e.target.value) })} /></Field>
                  </div>
                  <p className="text-xs text-muted-foreground tabular">
                    Current {isNum(p?.current) ? formatValue(p!.current!) : "off"} · testing {values.length ? values.map(formatValue).join(", ") : "—"}
                  </p>
                </div>
              );
            })}
            {rows.length < 2 && unused.length > 0 && (
              <Button variant="outline" size="sm" onClick={() => { const np = preferredSecond(unused)!; setRows((rs) => [...rs, { path: np.path, ...defaultRange(np) }]); }}>
                <Plus /> Add a second parameter
              </Button>
            )}
          </CardContent>
        </Card>

        <Card className="h-fit">
          <CardHeader><CardTitle>Scoring</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <Field label="Pick the best settings by">
              <Select value={objective} onValueChange={(v) => setObjective(v as ResearchObjective)}>
                <SelectTrigger aria-label="Objective"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {OBJECTIVES.map((o) => <SelectItem key={o.value} value={o.value}>{o.label} — {o.hint}</SelectItem>)}
                </SelectContent>
              </Select>
            </Field>
            <Field label="Minimum trades" hint="Settings with fewer trades can't be picked as best">
              <Input type="number" min={0} max={100} value={minTrades} onChange={(e) => setMinTrades(Number(e.target.value))} />
            </Field>
            {mode === "walk_forward" && (
              <div className="grid grid-cols-2 gap-3">
                <Field label="Folds" hint="2 – 8 test windows">
                  <Input type="number" min={2} max={8} value={folds} onChange={(e) => setFolds(Number(e.target.value))} />
                </Field>
                <Field label="Tuning : test" hint="Tuning window length">
                  <Input type="number" min={1} max={6} step={0.5} value={isRatio} onChange={(e) => setIsRatio(Number(e.target.value))} />
                </Field>
              </div>
            )}
            <div className="rounded-md bg-muted/50 p-3 text-xs text-muted-foreground tabular">
              {combos} combination{combos === 1 ? "" : "s"}
              {mode === "walk_forward" ? ` × ${folds} folds = ${combos * folds} tuning runs` : ""}
            </div>
            {problem && rows.length > 0 && <p className="text-xs text-loss">{problem}</p>}
            <Button className="w-full" loading={run.isPending} disabled={!strategyId || !!problem || bars < 200 || bars > 20_000 || folds < 2 || folds > 8 || isRatio < 1 || isRatio > 6} onClick={() => run.mutate()}>
              Run {mode === "sweep" ? "sweep" : "walk-forward test"}
            </Button>
          </CardContent>
        </Card>
      </div>
    </>
  );
}

// ------------------------------------------------------------------ detail
export function ResearchDetailView({ id }: { id: number }) {
  const q = useQuery({ queryKey: ["research", id], queryFn: () => api.research.get(id) });
  if (q.isLoading) return <LoadingRows rows={8} />;
  if (q.error || !q.data) return <Card><ErrorState error={q.error ?? new Error("Not found")} onRetry={() => q.refetch()} /></Card>;
  const run = q.data;
  return (
    <>
      <Button variant="ghost" size="sm" asChild className="mb-2 -ml-2">
        <Link href="/research"><ArrowLeft /> Optimization</Link>
      </Button>
      <PageHeader
        title={<>{run.kind === "walk_forward" ? "Walk-forward test" : "Parameter sweep"} <span className="text-base font-normal text-muted-foreground">· {run.strategy_name} v{run.strategy_version}</span></>}
        description={`${run.asset.symbol} · ${run.timeframe} · ${formatDate(run.start_at)} – ${formatDate(run.end_at)} · run ${formatDateTime(run.created_at)}`}
        actions={
          <Button variant="outline" size="sm" asChild>
            <Link href={`/research/new?strategy=${run.strategy_id}`}>Run another</Link>
          </Button>
        }
      />
      <Disclaimer className="mb-4">
        {run.disclaimer}
        {run.data_source.includes("sample") && <strong> This run used SAMPLE (synthetic) data.</strong>}
        {run.request.bars_used !== undefined && run.request.bars_used < run.request.bars && (
          <> Only {run.request.bars_used.toLocaleString()} of the {run.request.bars.toLocaleString()} requested bars were available.</>
        )}
      </Disclaimer>
      {run.kind === "sweep" ? <SweepView result={run.result} /> : <WalkForwardView run={run} result={run.result} />}
    </>
  );
}

// ------------------------------------------------------------------- sweep
type ColorBy = "score" | "total_return_pct" | "max_drawdown_pct" | "num_trades";

function SweepView({ result: r }: { result: SweepResult }) {
  const [colorBy, setColorBy] = useState<ColorBy>("score");
  const best = r.best_index !== null ? r.cells[r.best_index]! : null;
  const [rowsP, colsP] = r.params.length === 2 ? [r.params[0]!, r.params[1]!] : [null, r.params[0]!];
  const value = (c: (typeof r.cells)[number]) => (!c.metrics ? null : colorBy === "score" ? objectiveValue(r.objective, c.metrics) : c.metrics[colorBy]);
  const vals = r.cells.map(value).filter(isNum);
  const lo = Math.min(...vals, 0);
  const hi = Math.max(...vals, 0);
  const fmt = (v: number | null) =>
    v === null ? "—" : colorBy === "score" ? formatScore(r.objective, v) : colorBy === "num_trades" ? String(v) : formatPct(v, 1, colorBy !== "max_drawdown_pct");
  const shade = (v: number | null) => {
    if (v === null) return undefined;
    // Drawdowns are negative numbers where closer to zero is better, so the scale works unchanged.
    const t = v >= 0 ? (hi > 0 ? v / hi : 0) : lo < 0 ? v / lo : 0;
    const good = colorBy === "num_trades" ? "var(--info)" : v >= 0 ? "var(--gain)" : "var(--loss)";
    return { backgroundColor: `color-mix(in oklch, ${good} ${Math.round(12 + Math.abs(t) * 58)}%, transparent)` };
  };
  const cellAt = (ri: number, ci: number) => r.cells[ri * colsP.values.length + ci]!;
  const top = r.cells.map((c, i) => ({ c, i })).filter(({ c }) => c.score !== null).sort((a, b) => b.c.score! - a.c.score!).slice(0, 8);
  const objLabel = OBJECTIVES.find((o) => o.value === r.objective)!.label;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard label={`Best ${objLabel.toLowerCase()}`} value={best ? formatScore(r.objective, best.score) : "—"} sub={best ? r.params.map((p, k) => `${shortLabel(p.label)} ${formatValue(best.values[k]!)}`).join(" · ") : `No setting reached ${r.min_trades} trades`} />
        <StatCard label="Current settings" value={<span className={pnlClass(r.baseline.total_return_pct)}>{formatPct(r.baseline.total_return_pct)}</span>} sub={`Sharpe ${formatNumber(r.baseline.sharpe_ratio)} · buy & hold ${formatPct(r.buy_hold_return_pct)}`} />
        <StatCard label="Profitable settings" value={formatPct(r.robustness.profitable_share_pct, 0, false)} sub={`of ${r.robustness.valid_cells} valid combinations`} hint="Share of tested combinations with a positive return. A high share means results don't hinge on exact settings." />
        <StatCard label="Around the best" value={formatScore(r.objective, r.robustness.best_neighbors_mean_score)} sub="Mean score of neighbouring cells" hint="If neighbours score far below the best cell, the best result is probably an isolated lucky spike." />
      </div>
      <Card>
        <CardHeader className="flex-row flex-wrap items-center justify-between gap-2">
          <div>
            <CardTitle>Results grid</CardTitle>
            <CardDescription>
              Each cell is a full backtest. The outlined cell scored best{r.min_trades ? `; faded cells had fewer than ${r.min_trades} trades and could not be picked` : ""}.
            </CardDescription>
          </div>
          <Tabs value={colorBy} onValueChange={(v) => setColorBy(v as ColorBy)}>
            <TabsList>
              <TabsTrigger value="score">{objLabel}</TabsTrigger>
              <TabsTrigger value="total_return_pct">Return</TabsTrigger>
              <TabsTrigger value="max_drawdown_pct">Drawdown</TabsTrigger>
              <TabsTrigger value="num_trades">Trades</TabsTrigger>
            </TabsList>
          </Tabs>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <table className="w-full border-separate border-spacing-1 text-xs tabular">
            <thead>
              <tr>
                <th className="p-1 text-left font-medium text-muted-foreground">{rowsP ? `${shortLabel(rowsP.label)} ↓ / ${shortLabel(colsP.label)} →` : colsP.label}</th>
                {colsP.values.map((v) => <th key={v} className="p-1 font-medium text-muted-foreground">{formatValue(v)}</th>)}
              </tr>
            </thead>
            <tbody>
              {(rowsP ? rowsP.values : [null]).map((rv, ri) => (
                <tr key={ri}>
                  <th className="p-1 text-left font-medium text-muted-foreground">{rv === null ? "" : formatValue(rv)}</th>
                  {colsP.values.map((_, ci) => {
                    const c = cellAt(ri, ci);
                    const v = value(c);
                    const isBest = r.best_index === ri * colsP.values.length + ci;
                    return (
                      <td
                        key={ci}
                        style={shade(v)}
                        title={c.metrics ? `Return ${formatPct(c.metrics.total_return_pct)} · Sharpe ${formatNumber(c.metrics.sharpe_ratio)} · DD ${formatPct(c.metrics.max_drawdown_pct, 1, false)} · ${c.metrics.num_trades} trades` : "Invalid combination"}
                        className={cn("h-10 min-w-16 rounded-md text-center", !c.valid && "text-muted-foreground", c.valid && c.score === null && "opacity-45", isBest && "ring-2 ring-primary")}
                      >
                        {c.valid ? fmt(v) : "n/a"}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Top settings</CardTitle></CardHeader>
        <CardContent className="px-2">
          <MetricsTable
            rows={top.map(({ c, i }) => ({ key: i, label: r.params.map((p, k) => `${shortLabel(p.label)} ${formatValue(c.values[k]!)}`).join(" · "), score: c.score, m: c.metrics! }))}
            objective={r.objective}
          />
          <p className="px-2 pt-3 text-xs text-muted-foreground">
            The best cell of a sweep is tuned to this exact history and will usually do worse on new data. Use a walk-forward test to measure that.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

function MetricsTable({ rows, objective }: { rows: { key: number; label: string; score: number | null; m: RunSummaryMetrics }[]; objective: ResearchObjective }) {
  return (
    <Table>
      <THead>
        <TR className="hover:bg-transparent"><TH>Settings</TH><TH className="text-right">Score</TH><TH className="text-right">Return</TH><TH className="text-right">Sharpe</TH><TH className="text-right">Max DD</TH><TH className="text-right">Trades</TH></TR>
      </THead>
      <TBody>
        {rows.map((r) => (
          <TR key={r.key}>
            <TD>{r.label}</TD>
            <TD className="text-right font-medium">{formatScore(objective, r.score)}</TD>
            <TD className={cn("text-right", pnlClass(r.m.total_return_pct))}>{formatPct(r.m.total_return_pct)}</TD>
            <TD className="text-right">{formatNumber(r.m.sharpe_ratio)}</TD>
            <TD className="text-right text-loss">{formatPct(r.m.max_drawdown_pct, 1, false)}</TD>
            <TD className="text-right">{r.m.num_trades}</TD>
          </TR>
        ))}
      </TBody>
    </Table>
  );
}

// ------------------------------------------------------------ walk-forward
const VERDICT_STYLE: Record<WalkForwardResult["verdict"]["level"], string> = {
  robust: "border-gain/40 bg-gain-soft",
  weak: "border-warn/40 bg-warn-soft",
  overfit: "border-loss/40 bg-loss-soft",
  unprofitable: "border-loss/40 bg-loss-soft",
  inconclusive: "border-border bg-muted/40",
};

function WalkForwardView({ run, result: r }: { run: ResearchRun; result: WalkForwardResult }) {
  const m = r.oos_metrics;
  const capital = run.request.initial_capital;
  const pct = (v: number) => (v / capital - 1) * 100;
  const tuned = r.fold_results.filter((f) => f.chosen).length;
  const short = (path: string) => shortLabel(r.params.find((p) => p.path === path)?.label ?? path);
  return (
    <div className="space-y-4">
      <div className={cn("rounded-lg border p-4", VERDICT_STYLE[r.verdict.level])}>
        <p className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{r.verdict.level}</p>
        <p className="mt-1 font-semibold">{r.verdict.headline}</p>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-muted-foreground">
          {r.verdict.notes.map((n) => <li key={n}>{n}</li>)}
        </ul>
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <StatCard label="Out-of-sample return" value={<span className={pnlClass(m.total_return_pct)}>{formatPct(m.total_return_pct)}</span>} sub={`${m.num_trades} trades on unseen data`} />
        <StatCard label="Buy & hold" value={<span className={pnlClass(m.benchmark?.total_return_pct)}>{formatPct(m.benchmark?.total_return_pct)}</span>} sub="Same test period, same costs" />
        <StatCard label="Untuned strategy" value={<span className={pnlClass(r.baseline_oos_return_pct)}>{formatPct(r.baseline_oos_return_pct)}</span>} sub="Original settings, same windows" />
        <StatCard label="Efficiency" value={isNum(r.efficiency) ? formatPct(r.efficiency * 100, 0, false) : "—"} sub="Test vs tuning return per bar" hint="How much of the in-sample (tuning) performance survived on unseen data. Above 50% is generally considered good; undefined when the tuned settings lost money in-sample." />
        <StatCard label="Sharpe (test)" value={formatNumber(m.sharpe_ratio)} sub={`Max DD ${formatPct(m.max_drawdown_pct, 1, false)}`} />
        <StatCard label="Stability" value={r.distinct_choices} sub={`Distinct best settings in ${tuned} tuned fold${tuned === 1 ? "" : "s"}`} hint="1 means every tuned fold picked the same settings. Many different choices suggest the optimum is noise." />
      </div>
      <Card>
        <CardHeader>
          <div>
            <CardTitle>Out-of-sample equity</CardTitle>
            <CardDescription>Only the unseen test windows, joined end to end, with each fold starting from the previous fold&apos;s ending capital</CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <MultiLineChart
            height={300}
            series={[
              { name: "Walk-forward", points: r.equity_curve.map((p) => ({ time: p.time, value: pct(p.equity) })) },
              { name: "Untuned", points: r.equity_curve.map((p) => ({ time: p.time, value: pct(p.baseline) })) },
              { name: "Buy & hold", points: r.equity_curve.map((p) => ({ time: p.time, value: pct(p.benchmark) })) },
            ]}
          />
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <div>
            <CardTitle>Folds</CardTitle>
            <CardDescription>Tuned on the in-sample window ({r.is_ratio}× the test length), then traded on the next window</CardDescription>
          </div>
        </CardHeader>
        <CardContent className="px-2">
          <Table>
            <THead>
              <TR className="hover:bg-transparent">
                <TH>#</TH><TH>Tuning window</TH><TH>Test window</TH><TH>Chosen settings</TH>
                <TH className="text-right">Tuning return</TH><TH className="text-right">Test return</TH><TH className="text-right">Untuned test</TH><TH className="text-right">Test trades</TH>
              </TR>
            </THead>
            <TBody>
              {r.fold_results.map((f) => (
                <TR key={f.fold}>
                  <TD>{f.fold}</TD>
                  <TD className="text-muted-foreground">{formatDate(f.in_sample.start)} – {formatDate(f.in_sample.end)}</TD>
                  <TD className="text-muted-foreground">{formatDate(f.out_of_sample.start)} – {formatDate(f.out_of_sample.end)}</TD>
                  <TD>{f.chosen ? Object.entries(f.chosen).map(([p, v]) => `${short(p)} ${formatValue(v)}`).join(" · ") : <span className="text-muted-foreground">original (none qualified)</span>}</TD>
                  <TD className={cn("text-right", pnlClass(f.is_metrics.total_return_pct))}>{formatPct(f.is_metrics.total_return_pct)}</TD>
                  <TD className={cn("text-right font-medium", pnlClass(f.oos_metrics.total_return_pct))}>{formatPct(f.oos_metrics.total_return_pct)}</TD>
                  <TD className={cn("text-right", pnlClass(f.baseline_oos_return_pct))}>{formatPct(f.baseline_oos_return_pct)}</TD>
                  <TD className="text-right">{f.oos_metrics.num_trades}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
          <p className="px-2 pt-3 text-xs text-muted-foreground">
            Open positions are closed at the end of each test window, so every fold is scored on its own trades.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
