"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Pencil } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/overlays";
import { Field, Input } from "@/components/ui/primitives";
import { formatPrice, formatQty } from "@/lib/format";
import { api, type OrderAmend } from "@/services/api";
import type { Order } from "@/types/api";

const KIND: Record<Order["order_type"], string> = {
  market: "market", limit: "limit", stop: "stop", trailing_stop: "trailing stop", stop_limit: "stop-limit",
};

/** Change a resting order's size, limit, stop or trail in place: it keeps its place, its pair and its journal stop. */
export function AmendOrderDialog({ order }: { order: Order }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const initial = () => ({
    quantity: String(order.quantity),
    limit: order.limit_price != null ? String(order.limit_price) : "",
    stop: order.stop_price != null ? String(order.stop_price) : "",
    trail: order.trail_pct != null ? String(order.trail_pct) : "",
  });
  const [v, setV] = useState(initial);
  const t = order.order_type;
  const hasLimit = t === "limit" || t === "stop_limit";
  const hasStop = t === "stop" || (t === "stop_limit" && !order.triggered_at);
  const hasTrail = t === "trailing_stop";

  // Only what changed is sent.
  const body: OrderAmend = {};
  const num = (s: string) => (s.trim() === "" ? NaN : Number(s));
  if (num(v.quantity) !== order.quantity) body.quantity = num(v.quantity);
  if (hasLimit && num(v.limit) !== order.limit_price) body.limit_price = num(v.limit);
  if (hasStop && num(v.stop) !== order.stop_price) body.stop_price = num(v.stop);
  if (hasTrail && num(v.trail) !== order.trail_pct) body.trail_pct = num(v.trail);
  const values = Object.values(body);
  const invalid = !values.length || values.some((x) => !(x > 0)) || (body.trail_pct !== undefined && body.trail_pct > 50);

  const save = useMutation({
    mutationFn: () => api.paper.amendOrder(order.id, body),
    onSuccess: (o) => {
      qc.invalidateQueries({ queryKey: ["paper"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      toast.success(o.status === "filled" ? `Order changed and filled at ${formatPrice(o.filled_price)}` : "Order changed");
      setOpen(false);
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const label = `${order.side} ${KIND[t]} ${order.asset.symbol}`;

  return (
    <Dialog open={open} onOpenChange={(o) => { setOpen(o); if (o) setV(initial()); }}>
      <DialogTrigger asChild>
        <Button size="icon-sm" variant="ghost" aria-label={`Change ${label} order`}><Pencil /></Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="capitalize">Change {label}</DialogTitle>
          <DialogDescription>
            Same checks as a new order; if one fails, the order stays as it is. A protective stop you move keeps its pair, and the
            journal still measures R from where the stop started.
          </DialogDescription>
        </DialogHeader>
        <form className="grid gap-4" onSubmit={(e) => { e.preventDefault(); if (!invalid) save.mutate(); }}>
          <Field label={`Quantity (${order.asset.base_currency})`} hint={`Now ${formatQty(order.quantity)}`}>
            <Input type="number" min={0} step="any" value={v.quantity} onChange={(e) => setV({ ...v, quantity: e.target.value })} />
          </Field>
          {hasStop && (
            <Field label="Stop price (USD)" hint={`Now ${formatPrice(order.stop_price)}`}>
              <Input type="number" min={0} step="any" value={v.stop} onChange={(e) => setV({ ...v, stop: e.target.value })} />
            </Field>
          )}
          {hasLimit && (
            <Field
              label="Limit price (USD)"
              hint={order.triggered_at ? "Triggered: it waits at this limit. Accept a worse price to get filled sooner." : `Now ${formatPrice(order.limit_price)}`}
            >
              <Input type="number" min={0} step="any" value={v.limit} onChange={(e) => setV({ ...v, limit: e.target.value })} />
            </Field>
          )}
          {hasTrail && (
            <Field label="Trail (%)" hint={`Now ${order.trail_pct}% behind the best price (${formatPrice(order.trail_anchor)}); the stop moves with it.`}>
              <Input type="number" min={0.1} max={50} step="0.1" value={v.trail} onChange={(e) => setV({ ...v, trail: e.target.value })} />
            </Field>
          )}
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => setOpen(false)}>Keep as is</Button>
            <Button type="submit" disabled={invalid} loading={save.isPending}>Save changes</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
