"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Shield } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/overlays";
import { Field, Input } from "@/components/ui/primitives";
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
  const valid = v.max_position_pct >= 1 && v.max_position_pct <= 100 && v.max_open_positions >= 1 && v.max_open_positions <= 100 && v.daily_loss_limit_pct >= 0.5 && v.daily_loss_limit_pct <= 100;
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
          <Field label="Daily loss limit (%)" hint="New buys are blocked once 24h equity falls by this much.">
            <Input type="number" step="0.5" value={v.daily_loss_limit_pct} onChange={(e) => setV({ ...v, daily_loss_limit_pct: Number(e.target.value) })} />
          </Field>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
          <Button onClick={() => save.mutate()} loading={save.isPending} disabled={!valid}>Save limits</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
