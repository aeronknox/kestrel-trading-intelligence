"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { Change } from "@/components/common/finance";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Segmented, SegmentedItem } from "@/components/ui/segmented";
import { Badge, Field, Input, Label, Switch } from "@/components/ui/primitives";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useLiveTicker } from "@/hooks/use-market-stream";
import { formatDateTime, formatPct, formatPrice, formatQty, formatUsd, isNum } from "@/lib/format";
import { cn } from "@/lib/utils";
import { api } from "@/services/api";
import type { OrderSide, OrderType, Portfolio } from "@/types/api";

/** Time in force for resting orders: hours until an unfilled order expires ("gtc": until cancelled). */
const TIME_IN_FORCE = [
  ["gtc", "Good till cancelled"],
  ["1", "1 hour"],
  ["24", "1 day"],
  ["168", "1 week"],
] as const;

/** Whether a `side` order on `symbol` would open or add to a position (rather than reduce one). */
function opensRiskFor(side: OrderSide, portfolio: Portfolio, symbol: string): boolean {
  const held = portfolio.positions.find((p) => p.asset.symbol === symbol)?.quantity ?? 0;
  return side === "buy" ? held >= 0 : held <= 0 && Boolean(portfolio.risk_limits.allow_short || held < 0);
}

export function OrderTicket({ portfolio, symbol, onSymbolChange }: { portfolio: Portfolio; symbol: string; onSymbolChange: (s: string) => void }) {
  const qc = useQueryClient();
  const assets = useQuery({ queryKey: ["assets"], queryFn: () => api.market.assets(), staleTime: 300_000 });
  const rest = useQuery({ queryKey: ["ticker", symbol], queryFn: () => api.market.ticker(symbol), refetchInterval: 30_000 });
  const ticker = useLiveTicker(symbol, rest.data);
  const [side, setSide] = useState<OrderSide>("buy");
  const [type, setType] = useState<OrderType>("market");
  const [mode, setMode] = useState<"qty" | "usd">("usd");
  const [amount, setAmount] = useState("");
  const [tif, setTif] = useState("gtc");
  // A limit or stop price only makes sense for the symbol it was typed for.
  const [limitState, setLimitState] = useState({ symbol, value: "" });
  const limit = limitState.symbol === symbol ? limitState.value : "";
  const setLimit = (value: string) => setLimitState({ symbol, value });

  const level = Number(limit);
  // For a trailing stop the field is a percentage; the stop starts that far from the current price.
  const trailStart = ticker && level > 0 ? ticker.price * (1 + ((side === "buy" ? 1 : -1) * level) / 100) : undefined;
  const price = type === "trailing_stop" ? trailStart : type !== "market" && level > 0 ? level : ticker?.price;
  const num = Number(amount);
  const typedQty = !isNum(num) || num <= 0 || !price ? 0 : mode === "qty" ? num : num / price;
  const execPrice = price ? price * (1 + ((side === "buy" ? 1 : -1) * portfolio.slippage_bps) / 10_000) : 0;

  // Optional stop-loss / take-profit riding on an entry, and sizing the entry by what the stop would cost.
  const riskCap = portfolio.risk_limits.max_risk_per_trade_pct ?? null;
  // The trade plan in the risk limits: new positions need a stop-loss (always, when risk per trade is capped).
  const stopRequired = Boolean(portfolio.risk_limits.require_stop_loss || riskCap) && opensRiskFor(side, portfolio, symbol);
  const canBracket = (type === "market" || type === "limit") && opensRiskFor(side, portfolio, symbol);
  const [bracketOn, setBracketOn] = useState(false);
  const [sl, setSl] = useState("");
  const [tp, setTp] = useState("");
  const [riskOn, setRiskOn] = useState(false);
  const [riskPct, setRiskPct] = useState(String(Math.min(1, riskCap ?? 1)));
  const bracket = canBracket && (bracketOn || stopRequired);
  const long = side === "buy";
  const slNum = Number(sl) > 0 ? Number(sl) : null;
  const tpNum = Number(tp) > 0 ? Number(tp) : null;
  const slError = bracket && slNum && price && (long ? slNum >= price : slNum <= price) ? `Must be ${long ? "below" : "above"} the entry price` : null;
  const tpError = bracket && tpNum && price && (long ? tpNum <= price : tpNum >= price) ? `Must be ${long ? "above" : "below"} the entry price` : null;
  // Loss per unit if the stop fills: the distance plus slippage on the exit and fees both ways.
  const feeRate = portfolio.fee_bps / 10_000;
  const slipRate = portfolio.slippage_bps / 10_000;
  const stopFill = slNum ? slNum * (1 + (long ? -1 : 1) * slipRate) : null;
  const lossPerUnit = bracket && stopFill && !slError && execPrice ? Math.abs(execPrice - stopFill) + (execPrice + stopFill) * feeRate : null;
  const riskSized = bracket && riskOn && lossPerUnit && Number(riskPct) > 0 ? (portfolio.equity * Number(riskPct)) / 100 / lossPerUnit : null;
  const qty = riskSized ?? typedQty;
  const riskUsd = lossPerUnit ? qty * lossPerUnit : null;
  const overRiskCap = riskCap !== null && riskUsd !== null && riskUsd > (portfolio.equity * riskCap) / 100 * (1 + 1e-6);
  const missingStop = stopRequired && !(bracket && slNum);
  const rewardRisk = lossPerUnit && tpNum && !tpError && execPrice ? (Math.abs(tpNum - execPrice) - (tpNum + execPrice) * feeRate) / lossPerUnit : null;
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
        trail_pct: type === "trailing_stop" ? Number(limit) : null,
        stop_loss: bracket ? slNum : null,
        take_profit: bracket ? tpNum : null,
        expires_in_hours: type !== "market" && tif !== "gtc" ? Number(tif) : null,
      }),
    onSuccess: (o) => {
      qc.invalidateQueries({ queryKey: ["paper"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      const protectedBy = [o.bracket_stop_loss && `stop-loss ${formatPrice(o.bracket_stop_loss)}`, o.bracket_take_profit && `take-profit ${formatPrice(o.bracket_take_profit)}`].filter(Boolean).join(" and ");
      if (o.status === "filled") toast.success(`Filled: ${o.side} ${formatQty(o.quantity)} ${o.asset.base_currency} @ ${formatPrice(o.filled_price)}${protectedBy ? `, protected by ${protectedBy}` : ""}`);
      else if (o.status === "open" && o.order_type === "trailing_stop")
        toast.info(`Trailing stop placed — ${o.trail_pct}% behind the price, stop now at ${formatPrice(o.stop_price)}`);
      else if (o.status === "open" && o.order_type === "stop") toast.info(`Stop order placed — becomes a market order at ${formatPrice(o.stop_price)}`);
      else if (o.status === "open") toast.info(`Limit order placed — rests until price reaches ${formatPrice(o.limit_price)}${o.expires_at ? `, or expires ${formatDateTime(o.expires_at)}` : ""}`);
      else toast.error(`Order rejected: ${o.reject_reason}`);
      if (o.status !== "rejected") setAmount("");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const invalid =
    qty <= 0 || (type !== "market" && !(level > 0)) || (type === "trailing_stop" && level > 50) || !ticker ||
    (bracket && (!(slNum || tpNum) || Boolean(slError) || Boolean(tpError) || (riskOn && !riskSized))) ||
    missingStop || overRiskCap;

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
            <SegmentedItem value="trailing_stop" className="flex-1">Trailing</SegmentedItem>
          </Segmented>
        {type === "trailing_stop" && (
          <Field
            label="Trail (%)"
            hint={
              trailStart
                ? `Starts at ${formatPrice(trailStart)} and follows the ${side === "sell" ? "highest" : "lowest"} price since you place it, never moving back. Becomes a market order once reached.`
                : "Distance from the best price since placement, 0.1 – 50%."
            }
          >
            <Input type="number" min={0.1} max={50} step="0.1" value={limit} onChange={(e) => setLimit(e.target.value)} placeholder="5" />
          </Field>
        )}
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
        {type !== "market" && (
          <Field
            label="Time in force"
            hint={tif === "gtc" ? "Rests until it fills or you cancel it." : "If it hasn't filled by then, it is cancelled automatically and you are notified."}
          >
            <Select value={tif} onValueChange={setTif}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {TIME_IN_FORCE.map(([v, label]) => <SelectItem key={v} value={v}>{label}</SelectItem>)}
              </SelectContent>
            </Select>
          </Field>
        )}
        <Field label={mode === "usd" ? "Amount (USD)" : `Quantity (${symbol.split("-")[0]})`}>
          <div className="flex gap-2">
            <Input type="number" min={0} step="any" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder={riskSized ? "Sized by risk" : "0.00"} disabled={Boolean(bracket && riskOn)} />
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
        {canBracket && (
          <div className="space-y-3 rounded-lg border border-border p-3">
            <div className="flex items-center justify-between gap-3">
              <Label htmlFor="ticket-bracket" className="text-sm">Stop-loss &amp; take-profit</Label>
              <Switch id="ticket-bracket" checked={bracket} disabled={stopRequired} onCheckedChange={setBracketOn} />
            </div>
            {bracket && (
              <>
                <div className="grid grid-cols-2 gap-2">
                  <Field label="Stop-loss" error={slError}>
                    <Input type="number" min={0} step="any" value={sl} onChange={(e) => setSl(e.target.value)} placeholder={long ? "Below entry" : "Above entry"} />
                  </Field>
                  <Field label="Take-profit" error={tpError}>
                    <Input type="number" min={0} step="any" value={tp} onChange={(e) => setTp(e.target.value)} placeholder="Optional" />
                  </Field>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <Label htmlFor="ticket-risk" className="text-sm">Size by risk</Label>
                  <div className="flex items-center gap-2">
                    {riskOn && (
                      <div className="flex items-center gap-1">
                        <Input aria-label="Risk per trade (% of equity)" type="number" min={0.1} max={riskCap ?? 10} step="0.1" className="h-8 w-16" value={riskPct} onChange={(e) => setRiskPct(e.target.value)} />
                        <span className="text-xs text-muted-foreground">%</span>
                      </div>
                    )}
                    <Switch id="ticket-risk" checked={riskOn} onCheckedChange={setRiskOn} />
                  </div>
                </div>
                <p className="text-[11px] leading-relaxed text-muted-foreground">
                  {riskOn
                    ? slNum ? "The quantity is set so that hitting the stop-loss loses this share of your equity, including slippage and fees." : "Set a stop-loss to size the position by risk."
                    : "Placed together with the entry; one cancels the other, and they follow the position."}
                </p>
              </>
            )}
          </div>
        )}
        {missingStop && (
          <p className="text-xs text-warn" role="status">
            Your risk limits require a stop-loss on new positions{canBracket ? ": set one above." : ". Use a market or limit order to attach one."}
          </p>
        )}
        {overRiskCap && riskUsd !== null && (
          <p className="text-xs text-loss" role="status">
            Hitting the stop-loss would lose {formatPct((riskUsd / portfolio.equity) * 100, 2, false)} of equity, above your {riskCap}% risk-per-trade
            limit. Trade a smaller size or move the stop closer.
          </p>
        )}
        {riskSized !== null && (notional / portfolio.equity) * 100 > portfolio.risk_limits.max_position_pct && (
          <p className="text-xs text-warn" role="status">
            That is {formatPct((notional / portfolio.equity) * 100, 0, false)} of equity, above your {portfolio.risk_limits.max_position_pct}% position
            limit: the stop is very close for this much risk. Lower the risk or widen the stop.
          </p>
        )}
        <dl className="space-y-1.5 text-xs">
          {riskUsd !== null && (
            <div className="flex justify-between font-medium">
              <dt>Risk if stopped out</dt>
              <dd className="tabular text-loss">{formatUsd(riskUsd)} ({formatPct((riskUsd / portfolio.equity) * 100, 2, false)} of equity)</dd>
            </div>
          )}
          {rewardRisk !== null && (
            <div className="flex justify-between">
              <dt className="text-muted-foreground">Reward : risk</dt>
              <dd className={cn("tabular", rewardRisk < 1 && "text-warn")}>{rewardRisk.toFixed(2)} : 1</dd>
            </div>
          )}
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
