"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Scale, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/overlays";
import { Input } from "@/components/ui/primitives";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { formatPct, formatQty, formatUsd } from "@/lib/format";
import { cn } from "@/lib/utils";
import { api } from "@/services/api";
import type { Portfolio, RebalancePlan } from "@/types/api";

type Row = { symbol: string; pct: string };

/** Current long positions as starting targets, rounded to 0.5%. */
function initialRows(p: Portfolio): Row[] {
  const rows = p.positions
    .filter((pos) => pos.quantity > 0)
    .map((pos) => ({ symbol: pos.asset.symbol, pct: String(Math.round(((pos.market_value / p.equity) * 100) * 2) / 2) }));
  return rows.length ? rows : [{ symbol: "BTC-USD", pct: "10" }];
}

/** Bring chosen assets to target weights with simulated market orders: preview first, then place. */
export function RebalanceDialog({ portfolio }: { portfolio: Portfolio }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [rows, setRows] = useState<Row[]>(() => initialRows(portfolio));
  const [plan, setPlan] = useState<RebalancePlan | null>(null);
  const assets = useQuery({ queryKey: ["assets"], queryFn: () => api.market.assets(), staleTime: 300_000, enabled: open });
  const targets = rows.map((r) => ({ symbol: r.symbol, pct: Number(r.pct) }));
  const total = targets.reduce((s, t) => s + (Number.isFinite(t.pct) ? t.pct : 0), 0);
  const invalid = !rows.length || targets.some((t) => !(t.pct >= 0 && t.pct <= 100)) || total > 100 || new Set(rows.map((r) => r.symbol)).size !== rows.length;
  const edit = (i: number, patch: Partial<Row>) => {
    setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
    setPlan(null); // a preview is only good for the targets it was made for
  };

  const preview = useMutation({ mutationFn: () => api.paper.rebalancePreview(targets), onSuccess: setPlan, onError: (e: Error) => toast.error(e.message) });
  const run = useMutation({
    mutationFn: () => api.paper.rebalance(targets),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["paper"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      if (r.orders.every((o) => o.status === "filled")) toast.success(r.message);
      else toast.warning(r.message);
      setOpen(false);
      setPlan(null);
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const held = new Set(portfolio.positions.map((p) => p.asset.symbol));
  const choices = [...new Set([...(assets.data ?? []).map((a) => a.symbol), ...held, ...rows.map((r) => r.symbol)])].sort();

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        if (o) {
          setRows(initialRows(portfolio));
          setPlan(null);
        }
      }}
    >
      <DialogTrigger asChild>
        <Button variant="outline" size="sm"><Scale /> Rebalance</Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Rebalance to target weights</DialogTitle>
          <DialogDescription>
            Set a target % of equity for each asset (0 sells it all). Assets you don&apos;t list are left alone, and the rest stays in cash. Simulated
            market orders, sells first; your risk limits apply.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          {rows.map((r, i) => (
            <div key={i} className="flex items-center gap-2">
              <Select value={r.symbol} onValueChange={(v) => edit(i, { symbol: v })}>
                <SelectTrigger aria-label={`Asset ${i + 1}`} className="h-8 w-36"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {choices.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}
                </SelectContent>
              </Select>
              <Input aria-label={`Target % for ${r.symbol}`} type="number" min={0} max={100} step="0.5" className="h-8 w-24" value={r.pct} onChange={(e) => edit(i, { pct: e.target.value })} />
              <span className="text-xs text-muted-foreground">% of equity</span>
              <Button size="icon-sm" variant="ghost" aria-label={`Remove ${r.symbol}`} className="ml-auto" onClick={() => { setRows(rows.filter((_, j) => j !== i)); setPlan(null); }}>
                <X />
              </Button>
            </div>
          ))}
          <div className="flex items-center justify-between">
            <Button
              size="sm"
              variant="ghost"
              disabled={rows.length >= 20}
              onClick={() => {
                setRows([...rows, { symbol: choices.find((s) => !rows.some((r) => r.symbol === s)) ?? "BTC-USD", pct: "0" }]);
                setPlan(null);
              }}
            >
              <Plus /> Add asset
            </Button>
            <p className={cn("text-xs", total > 100 ? "text-loss" : "text-muted-foreground")}>
              Listed assets {formatPct(total, 1, false)} of equity · cash and unlisted positions {formatPct(Math.max(0, 100 - total), 1, false)}
            </p>
          </div>
        </div>
        {plan && (
          plan.legs.length ? (
            <div className="space-y-2">
              <Table>
                <THead>
                  <TR className="hover:bg-transparent">
                    <TH>Asset</TH><TH className="text-right">Now → target</TH><TH>Order</TH><TH className="text-right">Value</TH>
                  </TR>
                </THead>
                <TBody>
                  {plan.legs.map((l) => (
                    <TR key={l.symbol}>
                      <TD className="font-medium">{l.symbol}</TD>
                      <TD className="text-right tabular">{formatPct(l.current_pct, 1, false)} → {formatPct(l.target_pct, 1, false)}</TD>
                      <TD className={cn("font-medium uppercase", l.side === "buy" ? "text-gain" : "text-loss")}>{l.side} {formatQty(l.quantity)}</TD>
                      <TD className="text-right tabular">{formatUsd(l.value)}</TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
              <p className="text-xs text-muted-foreground">
                At current prices, before slippage and fees. Afterwards about {formatPct(plan.cash_after_pct, 1, false)} of equity is cash.
                {plan.unchanged.length > 0 && ` Already on target (within ${formatUsd(plan.drift_band_usd)}): ${plan.unchanged.join(", ")}.`}
              </p>
            </div>
          ) : (
            <p className="text-sm" role="status">Already on target: every difference is under {formatUsd(plan.drift_band_usd)}, so there is nothing to trade.</p>
          )
        )}
        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
          <Button variant="outline" disabled={invalid} loading={preview.isPending} onClick={() => preview.mutate()}>Preview orders</Button>
          <Button disabled={invalid || !plan?.legs.length} loading={run.isPending} onClick={() => run.mutate()}>Rebalance now</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
