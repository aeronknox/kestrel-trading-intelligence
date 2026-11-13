"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BellPlus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/overlays";
import { Badge, Field, Input, Label, Switch } from "@/components/ui/primitives";
import { Table, TBody, TD, TR } from "@/components/ui/table";
import { useMe } from "@/hooks/use-auth";
import { WEBHOOK_KEY } from "@/features/settings/webhook-card";
import { formatDateTime, formatPct, formatPrice } from "@/lib/format";
import { api } from "@/services/api";
import type { PriceAlert } from "@/types/api";

export const PRICE_ALERTS_KEY = ["price-alerts"] as const;

function useDelete() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.priceAlerts.remove(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: PRICE_ALERTS_KEY });
      toast.success("Price alert deleted");
    },
    onError: (e: Error) => toast.error(e.message),
  });
}

function AlertRows({ alerts, showSymbol }: { alerts: PriceAlert[]; showSymbol: boolean }) {
  const remove = useDelete();
  return (
    <Table>
      <TBody>
        {alerts.map((a) => {
          const name = `${a.asset.symbol} ${a.condition} ${formatPrice(a.target)}`;
          return (
            <TR key={a.id}>
              <TD>
                <span className="font-medium">
                  {showSymbol && <Link href={`/markets/${a.asset.symbol}`} className="hover:text-primary">{a.asset.symbol}</Link>}{showSymbol && " "}
                  {a.condition === "above" ? "≥" : "≤"} {formatPrice(a.target)}
                </span>
                <p className="text-xs text-muted-foreground">
                  {a.triggered_at
                    ? `Reached ${formatPrice(a.triggered_price)} · ${formatDateTime(a.triggered_at)}`
                    : `Set at ${formatPrice(a.created_price)} · ${formatDateTime(a.created_at)}`}
                  {a.notify_webhook ? " · webhook" : ""}
                </p>
                {a.note && <p className="max-w-64 truncate text-xs text-muted-foreground" title={a.note}>{a.note}</p>}
              </TD>
              <TD>{a.triggered_at ? <Badge variant="secondary">Fired</Badge> : <Badge variant="info">Active</Badge>}</TD>
              <TD className="text-right">
                <Button size="icon-sm" variant="ghost" aria-label={`Delete price alert ${name}`} onClick={() => remove.mutate(a.id)} disabled={remove.isPending}>
                  <Trash2 />
                </Button>
              </TD>
            </TR>
          );
        })}
      </TBody>
    </Table>
  );
}

/** "Price alert" button for an asset page: set a level, see this asset's alerts. */
export function PriceAlertButton({ symbol, price }: { symbol: string; price: number | undefined }) {
  const qc = useQueryClient();
  const me = useMe();
  const [open, setOpen] = useState(false);
  const [target, setTarget] = useState("");
  const [note, setNote] = useState("");
  const [webhook, setWebhook] = useState(false);
  const alerts = useQuery({ queryKey: [...PRICE_ALERTS_KEY, symbol], queryFn: () => api.priceAlerts.list(symbol), enabled: open });
  const hook = useQuery({ queryKey: WEBHOOK_KEY, queryFn: api.users.webhook, enabled: open && me.data ? !me.data.is_demo : false });
  const level = Number(target);
  const distance = price && level > 0 ? ((level - price) / price) * 100 : null;
  const create = useMutation({
    mutationFn: () => api.priceAlerts.create({ symbol, target: level, note, notify_webhook: webhook }),
    onSuccess: (a) => {
      qc.invalidateQueries({ queryKey: PRICE_ALERTS_KEY });
      toast.success(`Price alert set: ${a.asset.symbol} ${a.condition === "above" ? "rises to" : "falls to"} ${formatPrice(a.target)}`);
      setTarget("");
      setNote("");
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const active = alerts.data?.filter((a) => !a.triggered_at) ?? [];

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm"><BellPlus /> Price alert</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Price alert · {symbol}</DialogTitle>
          <DialogDescription>
            Get notified once {symbol} reaches a price (checked every 15 seconds against the market data feed). A notification only: no order is
            placed.
          </DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <Field
            label="Alert me when the price reaches"
            hint={
              distance !== null && distance !== 0
                ? `${distance > 0 ? "Rises" : "Falls"} ${formatPct(Math.abs(distance), 2, false)} from ${formatPrice(price)}.`
                : `Now ${formatPrice(price)}. Above it alerts on a rise, below it on a fall.`
            }
          >
            <Input type="number" min={0} step="any" value={target} onChange={(e) => setTarget(e.target.value)} placeholder={formatPrice(price)} />
          </Field>
          <Field label="Note (optional)" hint="Why this level matters, e.g. resistance, breakout">
            <Input value={note} maxLength={120} onChange={(e) => setNote(e.target.value)} />
          </Field>
          {hook.data?.url ? (
            <div className="flex items-center justify-between gap-3 rounded-md border border-border px-3 py-2">
              <Label htmlFor="price-alert-webhook" className="text-sm">Also post to my webhook</Label>
              <Switch id="price-alert-webhook" checked={webhook} onCheckedChange={setWebhook} />
            </div>
          ) : null}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>Close</Button>
            <Button type="submit" loading={create.isPending} disabled={!(level > 0) || level === price}>Set alert</Button>
          </DialogFooter>
        </form>
        {active.length > 0 && (
          <div className="space-y-1 border-t border-border pt-3">
            <p className="text-sm font-medium">Active alerts on {symbol}</p>
            <AlertRows alerts={active} showSymbol={false} />
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

/** Every price alert, for the Alerts page. */
export function PriceAlertsCard() {
  const alerts = useQuery({ queryKey: PRICE_ALERTS_KEY, queryFn: () => api.priceAlerts.list(), refetchInterval: 30_000 });
  return (
    <Card className="h-fit">
      <CardHeader>
        <div>
          <CardTitle>Price alerts</CardTitle>
          <CardDescription>Set them from an asset&apos;s page in Markets. Each fires once.</CardDescription>
        </div>
      </CardHeader>
      <CardContent className="px-2">
        {!alerts.data?.length ? (
          <p className="px-3 py-4 text-sm text-muted-foreground">None yet. Open an asset in <Link href="/markets" className="underline underline-offset-2">Markets</Link> and choose Price alert.</p>
        ) : (
          <AlertRows alerts={alerts.data} showSymbol />
        )}
      </CardContent>
    </Card>
  );
}
