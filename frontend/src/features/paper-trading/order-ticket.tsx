"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { Change } from "@/components/common/finance";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Segmented, SegmentedItem } from "@/components/ui/segmented";
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
  // A limit or stop price only makes sense for the symbol it was typed for.
  const [limitState, setLimitState] = useState({ symbol, value: "" });
  const limit = limitState.symbol === symbol ? limitState.value : "";
  const setLimit = (value: string) => setLimitState({ symbol, value });

  const price = type !== "market" && Number(limit) > 0 ? Number(limit) : ticker?.price;
  const num = Number(amount);
  const qty = !isNum(num) || num <= 0 || !price ? 0 : mode === "qty" ? num : num / price;
  const execPrice = price ? price * (1 + ((side === "buy" ? 1 : -1) * portfolio.slippage_bps) / 10_000) : 0;
  const notional = qty * execPrice;
  const fee = (notional * portfolio.fee_bps) / 10_000;
  const position = portfolio.positions.find((p) => p.asset.symbol === symbol);
  const held = position?.quantity ?? 0;
  // What this order does depends on the side and the current position.
  const action =
    side === "buy" ? (held < 0 ? "Buy to cover" : "Buy") : held > 0 ? "Sell" : portfolio.risk_limits.allow_short ? "Sell short" : "Sell";
  const opensRisk = action === "Buy" || action === "Sell short";

  const place = useMutation({
    mutationFn: () =>
      api.paper.placeOrder({
        symbol,
        side,
        order_type: type,
        quantity: Number(qty.toPrecision(12)),
        limit_price: type === "limit" ? Number(limit) : null,
        stop_price: type === "stop" ? Number(limit) : null,
      }),
    onSuccess: (o) => {
      qc.invalidateQueries({ queryKey: ["paper"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      if (o.status === "filled") toast.success(`Filled: ${o.side} ${formatQty(o.quantity)} ${o.asset.base_currency} @ ${formatPrice(o.filled_price)}`);
      else if (o.status === "open" && o.order_type === "stop") toast.info(`Stop order placed — becomes a market order at ${formatPrice(o.stop_price)}`);
      else if (o.status === "open") toast.info(`Limit order placed — rests until price reaches ${formatPrice(o.limit_price)}`);
      else toast.error(`Order rejected: ${o.reject_reason}`);
      if (o.status !== "rejected") setAmount("");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const invalid = qty <= 0 || (type !== "market" && !(Number(limit) > 0)) || !ticker;

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
          <button onClick={() => setSide("buy")} className={cn("h-9 rounded-md text-sm font-semibold transition-colors", side === "buy" ? "bg-gain text-gain-foreground" : "bg-muted text-muted-foreground hover:text-foreground")}>Buy</button>
          <button onClick={() => setSide("sell")} className={cn("h-9 rounded-md text-sm font-semibold transition-colors", side === "sell" ? "bg-loss text-white" : "bg-muted text-muted-foreground hover:text-foreground")}>Sell</button>
        </div>
        <Segmented value={type} onValueChange={(v) => setType(v as OrderType)} label="Order type" className="w-full">
            <SegmentedItem value="market" className="flex-1">Market</SegmentedItem>
            <SegmentedItem value="limit" className="flex-1">Limit</SegmentedItem>
            <SegmentedItem value="stop" className="flex-1">Stop</SegmentedItem>
          </Segmented>
        {type === "stop" && (
          <Field
            label="Stop price (USD)"
            hint={side === "buy"
              ? "Becomes a market order once the price rises to this level (e.g. buy a breakout, or cap a short's loss)."
              : "Becomes a market order once the price falls to this level (e.g. a stop-loss). A gap can fill below it."}
          >
            <Input type="number" min={0} step="any" value={limit} onChange={(e) => setLimit(e.target.value)} placeholder={formatPrice(ticker?.price)} />
          </Field>
        )}
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
                if (opensRisk) {
                  const usd = (portfolio.available_cash * pct) / 100 / (1 + portfolio.fee_bps / 10_000) / (1 + portfolio.slippage_bps / 10_000);
                  setMode("usd");
                  setAmount(String(Math.floor(usd * 100) / 100));
                } else if (position) {
                  setMode("qty");
                  setAmount(String((Math.abs(held) * pct) / 100));
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
          <div className="flex justify-between"><dt className="text-muted-foreground">{opensRisk ? "Buying power" : "Position held"}</dt><dd className="tabular">{opensRisk ? formatUsd(portfolio.available_cash) : `${formatQty(held)} ${symbol.split("-")[0]}${held < 0 ? " (short)" : ""}`}</dd></div>
        </dl>
        <Button className="w-full" variant={side === "buy" ? "gain" : "loss"} disabled={invalid} loading={place.isPending} onClick={() => place.mutate()}>
          {action} {symbol.split("-")[0]} (paper)
        </Button>
        <p className="text-[11px] leading-relaxed text-muted-foreground">Orders are simulated against the latest public price. No real orders are sent to any exchange or broker.</p>
      </CardContent>
    </Card>
  );
}
