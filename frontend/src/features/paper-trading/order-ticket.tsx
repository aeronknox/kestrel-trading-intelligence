"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Change } from "@/components/common/finance";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/overlays";
import { Badge, Field, Input } from "@/components/ui/primitives";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useLiveTicker } from "@/hooks/use-market-stream";
import { formatPrice, formatQty, formatUsd, isNum } from "@/lib/format";
import { cn } from "@/lib/utils";
import { api } from "@/services/api";
import type { OrderSide, OrderType, Portfolio } from "@/types/api";

export function OrderTicket({ portfolio, symbol, onSymbolChange }: { portfolio: Portfolio; symbol: string; onSymbolChange: (s: string) => void }) {
  const qc = useQueryClient();
  const assets = useQuery({ queryKey: ["assets"], queryFn: () => api.market.assets(), staleTime: 300_000 });
  const rest = useQuery({ queryKey: ["ticker", symbol], queryFn: () => api.market.ticker(symbol), refetchInterval: 30_000 });
  const ticker = useLiveTicker(symbol, rest.data);
  const [side, setSide] = useState<OrderSide>("buy");
  const [type, setType] = useState<OrderType>("market");
  const [mode, setMode] = useState<"qty" | "usd">("usd");
  const [amount, setAmount] = useState("");
  const [limit, setLimit] = useState("");

  useEffect(() => {
    setLimit("");
  }, [symbol]);

  const price = type === "limit" && Number(limit) > 0 ? Number(limit) : ticker?.price;
  const num = Number(amount);
  const qty = !isNum(num) || num <= 0 || !price ? 0 : mode === "qty" ? num : num / price;
  const execPrice = price ? price * (1 + ((side === "buy" ? 1 : -1) * portfolio.slippage_bps) / 10_000) : 0;
  const notional = qty * execPrice;
  const fee = (notional * portfolio.fee_bps) / 10_000;
  const position = portfolio.positions.find((p) => p.asset.symbol === symbol);

  const place = useMutation({
    mutationFn: () => api.paper.placeOrder({ symbol, side, order_type: type, quantity: Number(qty.toPrecision(12)), limit_price: type === "limit" ? Number(limit) : null }),
    onSuccess: (o) => {
      qc.invalidateQueries({ queryKey: ["paper"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      if (o.status === "filled") toast.success(`Filled: ${o.side} ${formatQty(o.quantity)} ${o.asset.base_currency} @ ${formatPrice(o.filled_price)}`);
      else if (o.status === "open") toast.info(`Limit order placed — rests until price reaches ${formatPrice(o.limit_price)}`);
      else toast.error(`Order rejected: ${o.reject_reason}`);
      if (o.status !== "rejected") setAmount("");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const invalid = qty <= 0 || (type === "limit" && !(Number(limit) > 0)) || !ticker;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Order ticket</CardTitle>
        <Badge variant="warn">Simulated</Badge>
      </CardHeader>
      <CardContent className="space-y-4">
        <Field label="Asset">
          <Select value={symbol} onValueChange={onSymbolChange}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              {(assets.data ?? [{ symbol }]).map((a) => <SelectItem key={a.symbol} value={a.symbol}>{a.symbol}</SelectItem>)}
            </SelectContent>
          </Select>
        </Field>
        <div className="flex items-baseline justify-between rounded-lg bg-muted/50 px-3 py-2.5">
          <span className="text-xs text-muted-foreground">Last price</span>
          <span className="flex items-baseline gap-2">
            <span className="text-lg font-semibold tabular">{formatPrice(ticker?.price, true)}</span>
            <Change value={ticker?.change_pct_24h} className="text-xs" />
          </span>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <button onClick={() => setSide("buy")} className={cn("h-9 rounded-md text-sm font-semibold transition-colors", side === "buy" ? "bg-gain text-[oklch(0.18_0.03_155)]" : "bg-muted text-muted-foreground hover:text-foreground")}>Buy</button>
          <button onClick={() => setSide("sell")} className={cn("h-9 rounded-md text-sm font-semibold transition-colors", side === "sell" ? "bg-loss text-white" : "bg-muted text-muted-foreground hover:text-foreground")}>Sell</button>
        </div>
        <Tabs value={type} onValueChange={(v) => setType(v as OrderType)}>
          <TabsList className="w-full">
            <TabsTrigger value="market" className="flex-1">Market</TabsTrigger>
            <TabsTrigger value="limit" className="flex-1">Limit</TabsTrigger>
          </TabsList>
        </Tabs>
        {type === "limit" && (
          <Field label="Limit price (USD)" hint={side === "buy" ? "Fills when the price is at or below this level." : "Fills when the price is at or above this level."}>
            <Input type="number" min={0} step="any" value={limit} onChange={(e) => setLimit(e.target.value)} placeholder={formatPrice(ticker?.price)} />
          </Field>
        )}
        <Field label={mode === "usd" ? "Amount (USD)" : `Quantity (${symbol.split("-")[0]})`}>
          <div className="flex gap-2">
            <Input type="number" min={0} step="any" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="0.00" />
            <Button variant="outline" size="sm" className="h-9 shrink-0" onClick={() => { setMode(mode === "usd" ? "qty" : "usd"); setAmount(""); }}>
              {mode === "usd" ? "USD" : symbol.split("-")[0]}
            </Button>
          </div>
        </Field>
        <div className="flex gap-1.5">
          {[25, 50, 100].map((pct) => (
            <Button
              key={pct}
              variant="secondary"
              size="sm"
              className="flex-1"
              disabled={!price}
              onClick={() => {
                if (!price) return;
                if (side === "buy") {
                  const usd = (portfolio.available_cash * pct) / 100 / (1 + portfolio.fee_bps / 10_000) / (1 + portfolio.slippage_bps / 10_000);
                  setMode("usd");
                  setAmount(String(Math.floor(usd * 100) / 100));
                } else if (position) {
                  setMode("qty");
                  setAmount(String((position.quantity * pct) / 100));
                }
              }}
            >
              {pct}%
            </Button>
          ))}
        </div>
        <dl className="space-y-1.5 text-xs">
          <div className="flex justify-between"><dt className="text-muted-foreground">Quantity</dt><dd className="tabular">{formatQty(qty)}</dd></div>
          <div className="flex justify-between"><dt className="text-muted-foreground">Est. fill price (incl. {portfolio.slippage_bps} bps slippage)</dt><dd className="tabular">{formatPrice(execPrice || null)}</dd></div>
          <div className="flex justify-between"><dt className="text-muted-foreground">Est. fee ({portfolio.fee_bps} bps)</dt><dd className="tabular">{formatUsd(fee)}</dd></div>
          <div className="flex justify-between font-medium"><dt>Est. {side === "buy" ? "cost" : "proceeds"}</dt><dd className="tabular">{formatUsd(side === "buy" ? notional + fee : notional - fee)}</dd></div>
          <div className="flex justify-between"><dt className="text-muted-foreground">{side === "buy" ? "Cash available" : "Position held"}</dt><dd className="tabular">{side === "buy" ? formatUsd(portfolio.available_cash) : `${formatQty(position?.quantity ?? 0)} ${symbol.split("-")[0]}`}</dd></div>
        </dl>
        <Button className="w-full" variant={side === "buy" ? "gain" : "loss"} disabled={invalid} loading={place.isPending} onClick={() => place.mutate()}>
          {side === "buy" ? "Buy" : "Sell"} {symbol.split("-")[0]} (paper)
        </Button>
        <p className="text-[11px] leading-relaxed text-muted-foreground">Orders are simulated against the latest public price. No real orders are sent to any exchange or broker.</p>
      </CardContent>
    </Card>
  );
}
