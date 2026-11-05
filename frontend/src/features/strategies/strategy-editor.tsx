"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Save } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { ErrorState, LoadingRows } from "@/components/common/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, Input, Separator, Textarea } from "@/components/ui/primitives";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { api } from "@/services/api";
import { type RiskParams, type RuleSet, type Strategy, TIMEFRAMES, type Timeframe } from "@/types/api";

import { RuleSetBuilder } from "./rule-builder";
import { DEFAULT_RISK, describeRisk, describeRuleSet, emptyRuleSet, validateStrategy } from "./rules";

export interface StrategyDraft {
  name: string;
  description: string;
  symbol: string;
  timeframe: Timeframe;
  entry: RuleSet;
  exit: RuleSet;
  risk: RiskParams;
}

export function draftFromStrategy(s: Strategy): StrategyDraft {
  const c = s.current_config!;
  return {
    name: s.name,
    description: s.description,
    symbol: c.asset.symbol,
    timeframe: c.timeframe,
    entry: c.entry_rules,
    exit: c.exit_rules,
    risk: { ...DEFAULT_RISK, ...c.risk },
  };
}

export const blankDraft = (): StrategyDraft => ({
  name: "",
  description: "",
  symbol: "BTC-USD",
  timeframe: "1h",
  entry: emptyRuleSet(),
  exit: emptyRuleSet(),
  risk: { ...DEFAULT_RISK },
});

function NumOrNull({ label, value, onChange, hint, suffix = "%" }: { label: string; value: number | null; onChange: (v: number | null) => void; hint?: string; suffix?: string }) {
  return (
    <Field label={`${label}${suffix ? ` (${suffix})` : ""}`} hint={hint}>
      <Input type="number" min={0} step="any" placeholder="Off" value={value ?? ""} onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))} />
    </Field>
  );
}

export function StrategyEditor({ initial, strategyId }: { initial: StrategyDraft; strategyId?: number }) {
  const [d, setD] = useState<StrategyDraft>(initial);
  const router = useRouter();
  const qc = useQueryClient();
  const indicators = useQuery({ queryKey: ["indicator-catalog"], queryFn: api.strategies.indicators, staleTime: Infinity });
  const assets = useQuery({ queryKey: ["assets"], queryFn: () => api.market.assets(), staleTime: 300_000 });
  const set = <K extends keyof StrategyDraft>(k: K, v: StrategyDraft[K]) => setD((prev) => ({ ...prev, [k]: v }));
  const setRisk = <K extends keyof RiskParams>(k: K, v: RiskParams[K]) => setD((prev) => ({ ...prev, risk: { ...prev.risk, [k]: v } }));

  const validation = !d.name.trim() ? "Give the strategy a name." : validateStrategy(d.entry, d.exit, d.risk);

  const save = useMutation({
    mutationFn: () => {
      const body = { name: d.name.trim(), description: d.description, config: { symbol: d.symbol, timeframe: d.timeframe, entry: d.entry, exit: d.exit, risk: d.risk } };
      return strategyId ? api.strategies.update(strategyId, body) : api.strategies.create(body);
    },
    onSuccess: (s) => {
      qc.invalidateQueries({ queryKey: ["strategies"] });
      qc.setQueryData(["strategy", s.id], s);
      toast.success(strategyId ? `Saved as version ${s.current_version}` : "Strategy created");
      if (!strategyId) router.push(`/strategies/${s.id}`);
    },
    onError: (e: Error) => toast.error(e.message),
  });

  if (indicators.isLoading) return <LoadingRows rows={8} />;
  if (indicators.error) return <ErrorState error={indicators.error} onRetry={() => indicators.refetch()} />;
  const catalog = indicators.data!.indicators;

  return (
    <div className="grid gap-4 xl:grid-cols-[1fr_340px]">
      <div className="min-w-0 space-y-4">
        <Card>
          <CardHeader>
            <CardTitle>General</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <Field label="Name" className="sm:col-span-2">
              <Input value={d.name} maxLength={120} onChange={(e) => set("name", e.target.value)} placeholder="e.g. RSI dip buyer" />
            </Field>
            <Field label="Description" className="sm:col-span-2">
              <Textarea value={d.description} maxLength={2000} onChange={(e) => set("description", e.target.value)} placeholder="What is the hypothesis behind this strategy?" />
            </Field>
            <Field label="Asset">
              <Select value={d.symbol} onValueChange={(v) => set("symbol", v)}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(assets.data ?? [{ symbol: d.symbol }]).map((a) => (
                    <SelectItem key={a.symbol} value={a.symbol}>{a.symbol}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
            <Field label="Timeframe">
              <Select value={d.timeframe} onValueChange={(v) => set("timeframe", v as Timeframe)}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {TIMEFRAMES.map((tf) => (
                    <SelectItem key={tf} value={tf}>{tf}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>Rules</CardTitle>
              <CardDescription>Evaluated on each closed bar; orders execute at the next bar&apos;s open (long-only).</CardDescription>
            </div>
          </CardHeader>
          <CardContent className="space-y-6">
            <RuleSetBuilder title="Entry conditions" description="Open a position when…" rules={d.entry} catalog={catalog} onChange={(r) => set("entry", r)} />
            <Separator />
            <RuleSetBuilder title="Exit conditions" description="Close the position when…" rules={d.exit} catalog={catalog} onChange={(r) => set("exit", r)} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>Risk parameters</CardTitle>
              <CardDescription>Protective exits are checked intrabar; if a bar gaps through a level the fill is at the open.</CardDescription>
            </div>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-3">
            <Field label="Position size (% equity)">
              <Input type="number" min={1} max={100} value={d.risk.position_size_pct} onChange={(e) => setRisk("position_size_pct", Number(e.target.value))} />
            </Field>
            <NumOrNull label="Stop-loss" value={d.risk.stop_loss_pct} onChange={(v) => setRisk("stop_loss_pct", v)} />
            <NumOrNull label="Take-profit" value={d.risk.take_profit_pct} onChange={(v) => setRisk("take_profit_pct", v)} />
            <NumOrNull label="Trailing stop" value={d.risk.trailing_stop_pct} onChange={(v) => setRisk("trailing_stop_pct", v)} />
            <NumOrNull label="Max bars in trade" suffix="" value={d.risk.max_bars_in_trade} onChange={(v) => setRisk("max_bars_in_trade", v === null ? null : Math.round(v))} />
          </CardContent>
        </Card>
      </div>

      <div className="space-y-4 xl:sticky xl:top-20 xl:self-start">
        <Card>
          <CardHeader>
            <CardTitle>Summary</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-xs">
            <div>
              <p className="font-medium text-gain">Enter long when</p>
              <p className="mt-0.5 text-muted-foreground">{describeRuleSet(d.entry)}</p>
            </div>
            <div>
              <p className="font-medium text-loss">Exit when</p>
              <p className="mt-0.5 text-muted-foreground">{describeRuleSet(d.exit)}</p>
            </div>
            <div>
              <p className="font-medium">Risk</p>
              <ul className="mt-0.5 list-inside list-disc text-muted-foreground">
                {describeRisk(d.risk).map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            </div>
            <p className="text-muted-foreground">{d.symbol} · {d.timeframe}</p>
            {validation && <p className="rounded-md bg-warn-soft px-2.5 py-2 text-warn">{validation}</p>}
            <Button className="w-full" onClick={() => save.mutate()} loading={save.isPending} disabled={!!validation}>
              <Save /> {strategyId ? "Save new version" : "Create strategy"}
            </Button>
            {strategyId && <p className="text-[11px] text-muted-foreground">Edits create a new immutable version, so past backtests stay reproducible.</p>}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
