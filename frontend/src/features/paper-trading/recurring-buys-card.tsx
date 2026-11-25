"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pause, Play, Repeat, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge, Field, Input, Label, Switch } from "@/components/ui/primitives";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { formatDateTime, formatPrice, formatQty, formatUsd } from "@/lib/format";
import { api } from "@/services/api";
import type { RecurringBuy } from "@/types/api";

const KEY = ["paper", "recurring-buys"] as const;
const INTERVALS = [["1", "Every day"], ["7", "Every week"], ["14", "Every 2 weeks"], ["30", "Every 30 days"]] as const;
const every = (days: number) => INTERVALS.find(([d]) => Number(d) === days)?.[1].toLowerCase() ?? `every ${days} days`;

/** Dollar-cost averaging in the paper portfolio: buy a fixed amount on a schedule (simulated market buys). */
export function RecurringBuysCard({ symbol }: { symbol: string }) {
  const qc = useQueryClient();
  const plans = useQuery({ queryKey: KEY, queryFn: api.recurringBuys.list, refetchInterval: 60_000 });
  const assets = useQuery({ queryKey: ["assets"], queryFn: () => api.market.assets(), staleTime: 300_000 });
  const [asset, setAsset] = useState(symbol);
  const [amount, setAmount] = useState("100");
  const [interval, setEvery] = useState("7");
  const [startNow, setStartNow] = useState(true);
  const refresh = () => {
    qc.invalidateQueries({ queryKey: KEY });
    qc.invalidateQueries({ queryKey: ["paper", "portfolio"] });
  };
  const fail = (e: Error) => toast.error(e.message);

  const create = useMutation({
    mutationFn: () => api.recurringBuys.create({ symbol: asset, amount_usd: Number(amount), interval_days: Number(interval), start_now: startNow }),
    onSuccess: (p) => {
      refresh();
      toast.success(`Recurring buy set: ${formatUsd(p.amount_usd)} of ${p.asset.symbol} ${every(p.interval_days)}${startNow ? ", first one within a minute" : ""}`);
    },
    onError: fail,
  });
  const toggle = useMutation({
    mutationFn: (p: RecurringBuy) => api.recurringBuys.setActive(p.id, !p.active),
    onSuccess: (p) => {
      refresh();
      toast.success(p.active ? `Resumed: next buy ${formatDateTime(p.next_run_at)}` : "Paused");
    },
    onError: fail,
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.recurringBuys.remove(id),
    onSuccess: () => {
      refresh();
      toast.success("Recurring buy stopped. Buys it already made stay in the portfolio.");
    },
    onError: fail,
  });
  const amountNum = Number(amount);

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle className="flex items-center gap-2"><Repeat className="size-4" /> Recurring buys</CardTitle>
          <CardDescription>
            Dollar-cost averaging, simulated: a market buy of a fixed amount on a schedule, checked against your risk limits like any order.
            Dates missed while the server is down aren&apos;t made up.
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <form
          className="grid grid-cols-2 items-end gap-3 sm:grid-cols-4"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <Field label="Asset">
            <Select value={asset} onValueChange={setAsset}>
              <SelectTrigger aria-label="Asset to buy"><SelectValue /></SelectTrigger>
              <SelectContent>
                {(assets.data ?? [{ symbol: asset }]).map((a) => <SelectItem key={a.symbol} value={a.symbol}>{a.symbol}</SelectItem>)}
              </SelectContent>
            </Select>
          </Field>
          <Field label="Amount per buy (USD)">
            <Input type="number" min={1} step="any" value={amount} onChange={(e) => setAmount(e.target.value)} />
          </Field>
          <Field label="How often">
            <Select value={interval} onValueChange={setEvery}>
              <SelectTrigger aria-label="How often"><SelectValue /></SelectTrigger>
              <SelectContent>
                {INTERVALS.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}
              </SelectContent>
            </Select>
          </Field>
          <Button type="submit" loading={create.isPending} disabled={!(amountNum >= 1)}>Start</Button>
          <div className="col-span-2 flex items-center gap-2 sm:col-span-4">
            <Switch id="recurring-now" checked={startNow} onCheckedChange={setStartNow} />
            <Label htmlFor="recurring-now" className="text-xs">First buy now (otherwise in one interval)</Label>
          </div>
        </form>
        {plans.data?.length ? (
          <ul className="divide-y divide-border rounded-lg border border-border">
            {plans.data.map((p) => (
              <li key={p.id} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 px-3 py-2.5">
                <div className="min-w-0">
                  <p className="text-sm font-medium">
                    {formatUsd(p.amount_usd)} of {p.asset.symbol} {every(p.interval_days)}{" "}
                    {!p.active && <Badge variant="secondary">Paused</Badge>}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {p.active ? `Next ${formatDateTime(p.next_run_at)}` : "Not running"}
                    {p.runs > 0 && ` · ${p.runs} buy${p.runs === 1 ? "" : "s"}: ${formatQty(p.quantity_bought)} ${p.asset.base_currency} for ${formatUsd(p.invested_usd)}, average ${formatPrice(p.average_price)}`}
                  </p>
                  {p.last_status && p.last_status !== "filled" && (
                    <p className="max-w-md truncate text-xs text-warn" title={p.last_message ?? undefined}>Last run {p.last_status}: {p.last_message}</p>
                  )}
                </div>
                <div className="flex gap-1">
                  <Button size="icon-sm" variant="ghost" aria-label={`${p.active ? "Pause" : "Resume"} recurring buy of ${p.asset.symbol}`} onClick={() => toggle.mutate(p)} disabled={toggle.isPending}>
                    {p.active ? <Pause /> : <Play />}
                  </Button>
                  <Button size="icon-sm" variant="ghost" aria-label={`Stop recurring buy of ${p.asset.symbol}`} onClick={() => remove.mutate(p.id)} disabled={remove.isPending}>
                    <Trash2 />
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        ) : null}
      </CardContent>
    </Card>
  );
}
