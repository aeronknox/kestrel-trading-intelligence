"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/overlays";
import { Segmented, SegmentedItem } from "@/components/ui/segmented";
import { formatPrice, formatQty, formatUsd, pnlClass } from "@/lib/format";
import { cn } from "@/lib/utils";
import { api } from "@/services/api";
import type { Position } from "@/types/api";

const SHARES = ["25", "50", "75"] as const;

/** Take part of a position off at market (simulated); protective orders shrink to what is left. */
export function ClosePartDialog({ position, price }: { position: Position; price: number | null | undefined }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [pct, setPct] = useState<(typeof SHARES)[number]>("50");
  const short = position.quantity < 0;
  const base = position.asset.base_currency;
  const qty = Number(((Math.abs(position.quantity) * Number(pct)) / 100).toPrecision(12));
  // Before the exit's slippage and fee; the average cost already includes the opening fees.
  const pnl = price ? (short ? position.avg_entry_price - price : price - position.avg_entry_price) * qty : null;

  const close = useMutation({
    mutationFn: () => api.paper.placeOrder({ symbol: position.asset.symbol, side: short ? "buy" : "sell", order_type: "market", quantity: qty }),
    onSuccess: (o) => {
      qc.invalidateQueries({ queryKey: ["paper"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      if (o.status === "filled") {
        toast.success(`Closed ${pct}% of ${o.asset.symbol}: ${formatQty(o.quantity)} ${base} @ ${formatPrice(o.filled_price)}`);
        setOpen(false);
      } else toast.error(o.reject_reason ?? "Close rejected");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" variant="ghost" aria-label={`Close part of ${position.asset.symbol}`}>Part…</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{short ? "Buy back" : "Close"} part of {position.asset.symbol}</DialogTitle>
          <DialogDescription>
            At market (simulated). Its stop-loss and take-profit orders shrink to cover what is left.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <Segmented value={pct} onValueChange={(v) => setPct(v as typeof pct)} label="Share of the position" className="w-full">
            {SHARES.map((s) => <SegmentedItem key={s} value={s} className="flex-1">{s}%</SegmentedItem>)}
          </Segmented>
          <dl className="space-y-1.5 text-sm">
            <div className="flex justify-between"><dt className="text-muted-foreground">{short ? "Buy back" : "Sell"}</dt><dd className="tabular">{formatQty(qty)} {base}</dd></div>
            <div className="flex justify-between"><dt className="text-muted-foreground">Left</dt><dd className="tabular">{formatQty(Math.abs(position.quantity) - qty)} {base}</dd></div>
            <div className="flex justify-between">
              <dt className="text-muted-foreground">P&amp;L on this part (before exit costs)</dt>
              <dd className={cn("tabular", pnlClass(pnl))}>{formatUsd(pnl, { sign: true })}</dd>
            </div>
          </dl>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
          <Button variant={short ? "gain" : "loss"} loading={close.isPending} disabled={!(qty > 0)} onClick={() => close.mutate()}>
            {short ? "Buy back" : "Close"} {pct}%
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
