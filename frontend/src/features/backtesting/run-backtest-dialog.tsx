"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FlaskConical } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Button, type ButtonProps } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/overlays";
import { Field, Input } from "@/components/ui/primitives";
import { api } from "@/services/api";

import { HistoryHint } from "./history-hint";

export function RunBacktestDialog({ strategyId, strategyName, size = "sm", variant = "default" }: { strategyId: number; strategyName: string; size?: ButtonProps["size"]; variant?: ButtonProps["variant"] }) {
  const [open, setOpen] = useState(false);
  const [bars, setBars] = useState(1000);
  const [capital, setCapital] = useState(10_000);
  const [fee, setFee] = useState(10);
  const [slip, setSlip] = useState(5);
  const router = useRouter();
  const qc = useQueryClient();
  const strategy = useQuery({ queryKey: ["strategy", strategyId], queryFn: () => api.strategies.get(strategyId), enabled: open });
  const cfg = strategy.data?.current_config;

  const run = useMutation({
    mutationFn: () => api.backtests.run({ strategy_id: strategyId, bars, initial_capital: capital, fee_bps: fee, slippage_bps: slip }),
    onSuccess: (bt) => {
      qc.invalidateQueries({ queryKey: ["backtests"] });
      qc.invalidateQueries({ queryKey: ["strategies"] });
      if (bt.status === "failed") {
        toast.error(bt.error ?? "Backtest failed");
      } else {
        toast.success("Backtest complete");
        setOpen(false);
      }
      router.push(`/backtests/${bt.id}`);
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const valid = bars >= 100 && bars <= 20_000 && capital > 0 && fee >= 0 && slip >= 0;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size={size} variant={variant}>
          <FlaskConical /> Backtest
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Run backtest</DialogTitle>
          <DialogDescription>
            Simulate <span className="font-medium text-foreground">{strategyName}</span> on historical candles. Orders fill at the next bar&apos;s open;
            fees and slippage apply to every fill.
          </DialogDescription>
        </DialogHeader>
        <div className="grid grid-cols-2 gap-4">
          <Field label="History (bars)" hint="100 – 20,000 closed candles">
            <Input type="number" min={100} max={20000} value={bars} onChange={(e) => setBars(Number(e.target.value))} />
          </Field>
          <Field label="Initial capital ($)">
            <Input type="number" min={1} value={capital} onChange={(e) => setCapital(Number(e.target.value))} />
          </Field>
          <Field label="Fee (bps per fill)" hint="10 bps = 0.10%">
            <Input type="number" min={0} max={500} value={fee} onChange={(e) => setFee(Number(e.target.value))} />
          </Field>
          <Field label="Slippage (bps per fill)">
            <Input type="number" min={0} max={500} value={slip} onChange={(e) => setSlip(Number(e.target.value))} />
          </Field>
        </div>
        <HistoryHint symbol={cfg?.asset.symbol} timeframe={cfg?.timeframe} bars={bars} />
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button onClick={() => run.mutate()} loading={run.isPending} disabled={!valid}>
            Run backtest
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
