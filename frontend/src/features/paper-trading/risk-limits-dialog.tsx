"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Shield } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/overlays";
import { Field, Input, Label, Switch } from "@/components/ui/primitives";
import { api } from "@/services/api";
import type { RiskLimits } from "@/types/api";

export function RiskLimitsDialog({ limits }: { limits: RiskLimits }) {
  const [open, setOpen] = useState(false);
  const [v, setV] = useState(limits);
  const qc = useQueryClient();
  const save = useMutation({
    mutationFn: () => api.paper.updateRiskLimits(v),
    onSuccess: () => {
      toast.success("Risk limits updated");
      qc.invalidateQueries({ queryKey: ["paper"] });
      setOpen(false);
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const cap = v.max_risk_per_trade_pct ?? null;
  const valid =
    v.max_position_pct >= 1 && v.max_position_pct <= 100 && v.max_open_positions >= 1 && v.max_open_positions <= 100 &&
    v.daily_loss_limit_pct >= 0.5 && v.daily_loss_limit_pct <= 100 && (cap === null || (cap >= 0.1 && cap <= 10));
  return (
    <Dialog open={open} onOpenChange={(o) => { setOpen(o); if (o) setV(limits); }}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm"><Shield /> Risk limits</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Risk limits</DialogTitle>
          <DialogDescription>Orders breaching these limits are rejected before they fill.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-4">
          <Field label="Max position size (% of equity)" hint="1 – 100">
            <Input type="number" value={v.max_position_pct} onChange={(e) => setV({ ...v, max_position_pct: Number(e.target.value) })} />
          </Field>
          <Field label="Max open positions" hint="1 – 100">
            <Input type="number" value={v.max_open_positions} onChange={(e) => setV({ ...v, max_open_positions: Number(e.target.value) })} />
          </Field>
          <Field label="Daily loss limit (%)" hint="New positions are blocked once 24h equity falls by this much.">
            <Input type="number" step="0.5" value={v.daily_loss_limit_pct} onChange={(e) => setV({ ...v, daily_loss_limit_pct: Number(e.target.value) })} />
          </Field>
          <Field label="Max risk per trade (% of equity)" hint="0.1 – 10, or empty for no limit. What a new position's stop-loss would lose, including slippage and fees. Many traders risk 1% or less.">
            <Input type="number" step="0.1" placeholder="No limit" value={cap ?? ""}
              onChange={(e) => setV({ ...v, max_risk_per_trade_pct: e.target.value === "" ? null : Number(e.target.value) })} />
          </Field>
          <div className="flex items-start justify-between gap-4 rounded-md border border-border p-3">
            <div>
              <Label htmlFor="require-stop">Require a stop-loss on new positions</Label>
              <p className="mt-0.5 text-[11px] text-muted-foreground">
                {cap !== null
                  ? "Always on while risk per trade is limited: the stop is what the risk is measured against."
                  : "Plan the exit before you enter. Applies to your own orders, not to strategy forward tests."}
              </p>
            </div>
            <Switch id="require-stop" checked={cap !== null || Boolean(v.require_stop_loss)} disabled={cap !== null}
              onCheckedChange={(on) => setV({ ...v, require_stop_loss: on })} />
          </div>
          <div className="flex items-start justify-between gap-4 rounded-md border border-border p-3 sm:col-span-2">
            <div>
              <Label htmlFor="allow-short">Allow short selling</Label>
              <p className="mt-0.5 text-[11px] text-muted-foreground">
                Sell an asset you don&apos;t hold to profit if it falls; buy it back to close. The short&apos;s value is set aside as collateral, and it
                is bought back automatically if the price doubles (margin call). Simulated only.
              </p>
            </div>
            <Switch id="allow-short" checked={Boolean(v.allow_short)} onCheckedChange={(on) => setV({ ...v, allow_short: on })} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
          <Button onClick={() => save.mutate()} loading={save.isPending} disabled={!valid}>Save limits</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
