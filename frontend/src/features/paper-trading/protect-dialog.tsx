"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/overlays";
import { Field, Input } from "@/components/ui/primitives";
import { Segmented, SegmentedItem } from "@/components/ui/segmented";
import { formatPct, formatPrice } from "@/lib/format";
import { api } from "@/services/api";
import type { Order, Position } from "@/types/api";

/** The open stop-loss / take-profit orders protecting a position, if any. */
export function protection(position: Position, openOrders: Order[]) {
  const mine = openOrders.filter((o) => o.reduce_only && o.oco_group && o.asset.symbol === position.asset.symbol);
  const stop = mine.find((o) => o.order_type === "stop" || o.order_type === "trailing_stop");
  return {
    stopLoss: stop?.stop_price ?? null,
    trailPct: stop?.trail_pct ?? null,
    takeProfit: mine.find((o) => o.order_type === "limit")?.limit_price ?? null,
  };
}

const num = (v: string) => (v.trim() === "" ? null : Number(v));

/** Attach a one-cancels-other stop-loss and take-profit to a position (simulated orders). */
export function ProtectDialog({ position, price, openOrders }: { position: Position; price: number | null; openOrders: Order[] }) {
  const qc = useQueryClient();
  const current = protection(position, openOrders);
  const [open, setOpen] = useState(false);
  const [sl, setSl] = useState("");
  const [mode, setMode] = useState<"fixed" | "trailing">("fixed");
  const [trail, setTrail] = useState("");
  const [tp, setTp] = useState("");
  const long = position.quantity > 0;
  const stopLoss = mode === "fixed" ? num(sl) : null;
  const trailPct = mode === "trailing" ? num(trail) : null;
  const trailError = trailPct !== null && !(trailPct > 0 && trailPct <= 50) ? "Between 0.1 and 50%" : null;
  const trailStart = trailPct && price && !trailError ? price * (1 + ((long ? -1 : 1) * trailPct) / 100) : null;
  const takeProfit = num(tp);
  const pct = (level: number | null) => (level && price ? formatPct((level / price - 1) * 100, 1) : null);
  // Mirrors the server's checks, so mistakes show before submitting.
  const slError = stopLoss !== null && price !== null && (long ? stopLoss >= price : stopLoss <= price) ? `Must be ${long ? "below" : "above"} the current price` : null;
  const tpError = takeProfit !== null && price !== null && (long ? takeProfit <= price : takeProfit >= price) ? `Must be ${long ? "above" : "below"} the current price` : null;
  const valid =
    (stopLoss !== null || trailPct !== null || takeProfit !== null) && !slError && !tpError && !trailError && [stopLoss, takeProfit].every((v) => v === null || v > 0);

  const save = useMutation({
    mutationFn: () => api.paper.protect(position.asset.symbol, { stop_loss: stopLoss, trailing_stop_pct: trailPct, take_profit: takeProfit }),
    onSuccess: (orders) => {
      qc.invalidateQueries({ queryKey: ["paper"] });
      const rejected = orders.find((o) => o.status === "rejected");
      if (rejected) toast.error(`Protection rejected: ${rejected.reject_reason}`);
      else toast.success(`${position.asset.symbol} protected: ${orders.map((o) => `${o.note} ${formatPrice(o.stop_price ?? o.limit_price)}`).join(", ")}`);
      setOpen(false);
    },
    onError: (e: Error) => toast.error(e.message),
  });

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        if (o) {
          setMode(current.trailPct ? "trailing" : "fixed");
          setTrail(current.trailPct ? String(current.trailPct) : "");
          setSl(current.stopLoss && !current.trailPct ? String(current.stopLoss) : "");
          setTp(current.takeProfit ? String(current.takeProfit) : "");
        }
      }}
    >
      <DialogTrigger asChild>
        <Button size="sm" variant="ghost" aria-label={`Protect ${position.asset.symbol}`}>
          <ShieldCheck aria-hidden />
          <span className="hidden 2xl:inline">Protect</span>
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Protect {position.asset.symbol} {long ? "long" : "short"}</DialogTitle>
          <DialogDescription>
            Simulated orders that close the whole position: a stop-loss (a stop order, filled at the market price once reached, so a gap can
            fill worse) and a take-profit (a limit order). When one fills, the other is cancelled. They follow the position: selling part of it
            shrinks them, closing it cancels them. Current price {formatPrice(price)}.
          </DialogDescription>
        </DialogHeader>
        <Segmented value={mode} onValueChange={(v) => setMode(v as "fixed" | "trailing")} label="Stop-loss kind" className="w-full">
          <SegmentedItem value="fixed" className="flex-1">Fixed stop-loss</SegmentedItem>
          <SegmentedItem value="trailing" className="flex-1">Trailing stop</SegmentedItem>
        </Segmented>
        <div className="grid gap-4 sm:grid-cols-2">
          {mode === "fixed" ? (
            <Field label="Stop-loss price (USD)" error={slError} hint={!slError && stopLoss ? `${pct(stopLoss)} from the current price` : long ? "Below the current price" : "Above the current price"}>
              <Input type="number" min={0} step="any" value={sl} onChange={(e) => setSl(e.target.value)} placeholder="Optional" />
            </Field>
          ) : (
            <Field
              label="Trail (%)"
              error={trailError}
              hint={trailStart ? `Starts at ${formatPrice(trailStart)} and follows the ${long ? "highest" : "lowest"} price, never moving back` : "Follows the best price by this much"}
            >
              <Input type="number" min={0.1} max={50} step="0.1" value={trail} onChange={(e) => setTrail(e.target.value)} placeholder="Optional" />
            </Field>
          )}
          <Field label="Take-profit price (USD)" error={tpError} hint={!tpError && takeProfit ? `${pct(takeProfit)} from the current price` : long ? "Above the current price" : "Below the current price"}>
            <Input type="number" min={0} step="any" value={tp} onChange={(e) => setTp(e.target.value)} placeholder="Optional" />
          </Field>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
          <Button onClick={() => save.mutate()} loading={save.isPending} disabled={!valid}>
            {current.stopLoss || current.takeProfit ? "Replace protection" : "Protect position"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
