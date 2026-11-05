"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Landmark, RotateCcw, Wallet, X } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { AssetIcon, Disclaimer, StatCard } from "@/components/common/finance";
import { EmptyState, ErrorState, LoadingRows } from "@/components/common/states";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/overlays";
import { Badge, Skeleton } from "@/components/ui/primitives";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { useMarketStream } from "@/hooks/use-market-stream";
import { formatDateTime, formatPct, formatPrice, formatQty, formatUsd, pnlClass } from "@/lib/format";
import { cn } from "@/lib/utils";
import { api } from "@/services/api";
import type { Order, Portfolio } from "@/types/api";

import { OrderTicket } from "./order-ticket";
import { RiskLimitsDialog } from "./risk-limits-dialog";

const STATUS_VARIANT = { filled: "gain", open: "info", rejected: "loss", cancelled: "secondary" } as const;

function PositionsTable({ portfolio }: { portfolio: Portfolio }) {
  const { tickers } = useMarketStream();
  const qc = useQueryClient();
  const close = useMutation({
    mutationFn: (p: { symbol: string; quantity: number }) => api.paper.placeOrder({ symbol: p.symbol, side: "sell", order_type: "market", quantity: p.quantity }),
    onSuccess: (o) => {
      qc.invalidateQueries({ queryKey: ["paper"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      if (o.status === "filled") toast.success(`Closed ${o.asset.symbol} @ ${formatPrice(o.filled_price)}`);
      else toast.error(o.reject_reason ?? "Close rejected");
    },
    onError: (e: Error) => toast.error(e.message),
  });
  if (!portfolio.positions.length) {
    return <EmptyState icon={Wallet} title="No open positions" description="Use the order ticket to open a simulated position." />;
  }
  return (
    <Table>
      <THead>
        <TR className="hover:bg-transparent">
          <TH>Asset</TH><TH className="text-right">Quantity</TH><TH className="hidden text-right 2xl:table-cell">Avg cost</TH><TH className="text-right">Price</TH><TH className="text-right">Value</TH><TH className="text-right">Unrealized P&amp;L</TH><TH className="hidden text-right 2xl:table-cell">Alloc.</TH><TH />
        </TR>
      </THead>
      <TBody>
        {portfolio.positions.map((p) => {
          const price = tickers[p.asset.symbol]?.price ?? p.current_price;
          const value = price ? p.quantity * price : p.market_value;
          const upnl = price ? (price - p.avg_entry_price) * p.quantity : p.unrealized_pnl;
          const upct = price ? (price / p.avg_entry_price - 1) * 100 : p.unrealized_pnl_pct;
          return (
            <TR key={p.id}>
              <TD>
                <Link href={`/markets/${p.asset.symbol}`} className="flex items-center gap-2">
                  <AssetIcon symbol={p.asset.symbol} className="size-6" />
                  <span className="font-medium">{p.asset.symbol}</span>
                </Link>
              </TD>
              <TD className="text-right">{formatQty(p.quantity)}</TD>
              <TD className="hidden text-right 2xl:table-cell">{formatPrice(p.avg_entry_price)}</TD>
              <TD className="text-right">{price ? formatPrice(price) : <span className="text-warn">unavailable</span>}</TD>
              <TD className="text-right font-medium">{formatUsd(value)}</TD>
              <TD className={cn("text-right", pnlClass(upnl))}>
                {formatUsd(upnl, { sign: true })} <span className="text-xs">({formatPct(upct, 1)})</span>
              </TD>
              <TD className="hidden text-right text-muted-foreground 2xl:table-cell">{formatPct(p.allocation_pct, 1, false)}</TD>
              <TD className="text-right">
                <Button
                  size="sm"
                  variant="outline"
                  loading={close.isPending && close.variables?.symbol === p.asset.symbol}
                  onClick={() => window.confirm(`Close the full ${p.asset.symbol} position at market (simulated)?`) && close.mutate({ symbol: p.asset.symbol, quantity: p.quantity })}
                >
                  Close
                </Button>
              </TD>
            </TR>
          );
        })}
      </TBody>
    </Table>
  );
}

function OrdersTable({ orders, cancellable }: { orders: Order[]; cancellable?: boolean }) {
  const qc = useQueryClient();
  const cancel = useMutation({
    mutationFn: api.paper.cancelOrder,
    onSuccess: () => {
      toast.success("Order cancelled");
      qc.invalidateQueries({ queryKey: ["paper"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });
  if (!orders.length) return <EmptyState title={cancellable ? "No open orders" : "No orders yet"} className="py-8" />;
  return (
    <Table>
      <THead>
        <TR className="hover:bg-transparent">
          <TH>Time</TH><TH>Asset</TH><TH>Side</TH><TH>Type</TH><TH className="text-right">Qty</TH><TH className="text-right">Limit</TH><TH className="text-right">Fill price</TH><TH className="text-right">Fee</TH><TH>Status</TH>{cancellable && <TH />}
        </TR>
      </THead>
      <TBody>
        {orders.map((o) => (
          <TR key={o.id}>
            <TD className="text-muted-foreground">{formatDateTime(o.created_at)}</TD>
            <TD className="font-medium">{o.asset.symbol}</TD>
            <TD className={cn("font-semibold uppercase", o.side === "buy" ? "text-gain" : "text-loss")}>{o.side}</TD>
            <TD className="capitalize">{o.order_type}</TD>
            <TD className="text-right">{formatQty(o.quantity)}</TD>
            <TD className="text-right">{formatPrice(o.limit_price)}</TD>
            <TD className="text-right">{formatPrice(o.filled_price)}</TD>
            <TD className="text-right text-muted-foreground">{o.fee ? formatUsd(o.fee) : "—"}</TD>
            <TD>
              <Badge variant={STATUS_VARIANT[o.status]} title={o.reject_reason ?? undefined}>{o.status}</Badge>
              {o.reject_reason && <p className="mt-0.5 max-w-56 truncate text-[11px] text-muted-foreground" title={o.reject_reason}>{o.reject_reason}</p>}
            </TD>
            {cancellable && (
              <TD className="text-right">
                <Button size="icon-sm" variant="ghost" aria-label="Cancel order" onClick={() => cancel.mutate(o.id)} disabled={cancel.isPending}><X /></Button>
              </TD>
            )}
          </TR>
        ))}
      </TBody>
    </Table>
  );
}

function TradesTable() {
  const trades = useQuery({ queryKey: ["paper", "trades"], queryFn: api.paper.trades });
  if (trades.isLoading) return <LoadingRows rows={4} className="p-3" />;
  if (trades.error) return <ErrorState error={trades.error} onRetry={() => trades.refetch()} />;
  if (!trades.data?.length) return <EmptyState title="No executed trades yet" className="py-8" />;
  return (
    <Table>
      <THead>
        <TR className="hover:bg-transparent"><TH>Executed</TH><TH>Asset</TH><TH>Side</TH><TH className="text-right">Qty</TH><TH className="text-right">Price</TH><TH className="text-right">Notional</TH><TH className="text-right">Fee</TH><TH className="text-right">Realized P&amp;L</TH></TR>
      </THead>
      <TBody>
        {trades.data.map((t) => (
          <TR key={t.id}>
            <TD className="text-muted-foreground">{formatDateTime(t.executed_at)}</TD>
            <TD className="font-medium">{t.asset.symbol}</TD>
            <TD className={cn("font-semibold uppercase", t.side === "buy" ? "text-gain" : "text-loss")}>{t.side}</TD>
            <TD className="text-right">{formatQty(t.quantity)}</TD>
            <TD className="text-right">{formatPrice(t.price)}</TD>
            <TD className="text-right">{formatUsd(t.quantity * t.price)}</TD>
            <TD className="text-right text-muted-foreground">{formatUsd(t.fee)}</TD>
            <TD className={cn("text-right", t.side === "sell" ? pnlClass(t.realized_pnl) : "text-muted-foreground")}>{t.side === "sell" ? formatUsd(t.realized_pnl, { sign: true }) : "—"}</TD>
          </TR>
        ))}
      </TBody>
    </Table>
  );
}

export function PaperTradingView() {
  const params = useSearchParams();
  const [symbol, setSymbol] = useState(params.get("symbol") ?? "BTC-USD");
  const qc = useQueryClient();
  const portfolio = useQuery({ queryKey: ["paper", "portfolio"], queryFn: api.paper.portfolio, refetchInterval: 20_000 });
  const orders = useQuery({ queryKey: ["paper", "orders"], queryFn: () => api.paper.orders(), refetchInterval: 20_000 });
  const reset = useMutation({
    mutationFn: api.paper.reset,
    onSuccess: () => {
      toast.success("Portfolio reset to starting balance");
      qc.invalidateQueries({ queryKey: ["paper"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const p = portfolio.data;
  const openOrders = orders.data?.filter((o) => o.status === "open") ?? [];

  return (
    <>
      <PageHeader
        title="Paper Trading"
        description="Practice execution with a virtual balance. Fills use live public prices plus simulated fees and slippage."
        actions={
          p && (
            <>
              <RiskLimitsDialog limits={p.risk_limits} />
              <Button variant="outline" size="sm" loading={reset.isPending} onClick={() => window.confirm("Reset the paper portfolio? All simulated positions, orders and trade history will be deleted.") && reset.mutate()}>
                <RotateCcw /> Reset
              </Button>
            </>
          )
        }
      />
      <Disclaimer className="mb-4">Simulation only — this module never connects to a brokerage and no real money is involved.</Disclaimer>
      {portfolio.isLoading ? (
        <div className="grid gap-4 lg:grid-cols-[1fr_360px]"><Skeleton className="h-96 rounded-xl" /><Skeleton className="h-96 rounded-xl" /></div>
      ) : portfolio.error || !p ? (
        <Card><ErrorState error={portfolio.error} onRetry={() => portfolio.refetch()} /></Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[1fr_360px]">
          <div className="min-w-0 space-y-4">
            <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
              <StatCard label="Equity" icon={Landmark} value={formatUsd(p.equity)} sub={<span className={pnlClass(p.total_return_pct)}>{formatPct(p.total_return_pct)} all-time</span>} />
              <StatCard label="Cash" value={formatUsd(p.cash_balance)} sub={`Started with ${formatUsd(p.starting_balance)}`} />
              <StatCard label="Unrealized P&L" value={<span className={pnlClass(p.unrealized_pnl)}>{formatUsd(p.unrealized_pnl, { sign: true })}</span>} sub={`Positions ${formatUsd(p.positions_value)}`} />
              <StatCard label="Realized P&L" value={<span className={pnlClass(p.realized_pnl)}>{formatUsd(p.realized_pnl, { sign: true })}</span>} sub={`Fees paid ${formatUsd(p.total_fees)}`} />
            </div>
            <Card>
              <CardHeader>
                <CardTitle>Positions</CardTitle>
                <span className="text-xs text-muted-foreground">Max {p.risk_limits.max_position_pct}% per position · {p.risk_limits.max_open_positions} positions · {p.risk_limits.daily_loss_limit_pct}% daily loss limit</span>
              </CardHeader>
              <CardContent className="px-2">
                <PositionsTable portfolio={p} />
              </CardContent>
            </Card>
            <Card>
              <Tabs defaultValue="open">
                <CardHeader>
                  <TabsList>
                    <TabsTrigger value="open">Open orders ({openOrders.length})</TabsTrigger>
                    <TabsTrigger value="orders">Order history</TabsTrigger>
                    <TabsTrigger value="trades">Trade history</TabsTrigger>
                  </TabsList>
                </CardHeader>
                <CardContent className="px-2">
                  {orders.isLoading ? (
                    <LoadingRows rows={3} className="p-3" />
                  ) : orders.error ? (
                    <ErrorState error={orders.error} onRetry={() => orders.refetch()} />
                  ) : (
                    <>
                      <TabsContent value="open"><OrdersTable orders={openOrders} cancellable /></TabsContent>
                      <TabsContent value="orders"><OrdersTable orders={orders.data ?? []} /></TabsContent>
                    </>
                  )}
                  <TabsContent value="trades"><TradesTable /></TabsContent>
                </CardContent>
              </Tabs>
            </Card>
          </div>
          <div className="lg:sticky lg:top-20 lg:self-start">
            <OrderTicket portfolio={p} symbol={symbol} onSymbolChange={setSymbol} />
          </div>
        </div>
      )}
    </>
  );
}
