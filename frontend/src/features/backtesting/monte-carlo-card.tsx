"use client";

import { useMutation } from "@tanstack/react-query";
import { Dices } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { formatPct, pnlClass } from "@/lib/format";
import { cn } from "@/lib/utils";
import { api } from "@/services/api";
import type { MonteCarlo } from "@/types/api";

const COLUMNS = [["5", "Unlucky (5th pct.)"], ["50", "Median"], ["95", "Lucky (95th pct.)"]] as const;

/** Reshuffle the backtest's own trades: how much did their order (luck) shape the result? Run on request. */
export function MonteCarloCard({ backtestId, closedTrades }: { backtestId: number; closedTrades: number }) {
  const run = useMutation({ mutationFn: () => api.backtests.monteCarlo(backtestId) });
  const mc: MonteCarlo | undefined = run.data;
  const enough = closedTrades >= 5;

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Luck check (Monte Carlo)</CardTitle>
          <CardDescription>
            Redraws this backtest&apos;s own {closedTrades} closed trades at random (a trade can come up more than once), 1,000 times, to show how
            much luck (which wins and losses came, and in what order) shaped the return and drawdown.
          </CardDescription>
        </div>
        {!mc && (
          <Button size="sm" variant="outline" disabled={!enough} loading={run.isPending} onClick={() => run.mutate()}>
            <Dices /> Run
          </Button>
        )}
      </CardHeader>
      <CardContent className="space-y-3">
        {!enough && <p className="text-sm text-muted-foreground">Needs at least 5 closed trades.</p>}
        {run.error && <p className="text-sm text-loss" role="alert">{run.error.message}</p>}
        {mc && (
          <>
            <div className="overflow-x-auto">
              <Table>
                <THead>
                  <TR className="hover:bg-transparent">
                    <TH />
                    <TH className="text-right">This backtest</TH>
                    {COLUMNS.map(([, label]) => <TH key={label} className="text-right">{label}</TH>)}
                  </TR>
                </THead>
                <TBody>
                  <TR>
                    <TD className="font-medium">Return</TD>
                    <TD className={cn("text-right tabular", pnlClass(mc.actual_return_pct))}>{formatPct(mc.actual_return_pct)}</TD>
                    {COLUMNS.map(([p]) => <TD key={p} className={cn("text-right tabular", pnlClass(mc.return_pct[p]))}>{formatPct(mc.return_pct[p])}</TD>)}
                  </TR>
                  <TR>
                    <TD className="font-medium">Max drawdown</TD>
                    <TD className="text-right tabular">{formatPct(-mc.actual_max_drawdown_pct)}</TD>
                    {/* Bad luck is a deep drawdown: the 95th percentile of drawdowns goes under "Unlucky". */}
                    {COLUMNS.map(([p]) => (
                      <TD key={p} className="text-right tabular">{formatPct(-mc.max_drawdown_pct[p === "5" ? "95" : p === "95" ? "5" : p])}</TD>
                    ))}
                  </TR>
                </TBody>
              </Table>
            </div>
            <p className="text-sm">
              <span className={cn("font-semibold", mc.loss_probability_pct >= 25 ? "text-loss" : mc.loss_probability_pct >= 10 ? "text-warn" : "text-gain")}>
                {mc.loss_probability_pct.toFixed(0)}%
              </span>{" "}
              of the {mc.runs.toLocaleString()} reshuffles ended below the starting capital, and{" "}
              <span className="font-semibold">{mc.drawdown_worse_than_actual_pct.toFixed(0)}%</span> had a deeper drawdown than this backtest did.
            </p>
            <p className="text-xs text-muted-foreground">{mc.method}</p>
          </>
        )}
      </CardContent>
    </Card>
  );
}
