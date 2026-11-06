"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, BellRing, Trash2 } from "lucide-react";
import Link from "next/link";
import { toast } from "sonner";

import { Disclaimer } from "@/components/common/finance";
import { EmptyState, ErrorState, LoadingRows } from "@/components/common/states";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { DropdownMenu, DropdownMenuContent, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/overlays";
import { Badge, Label, Switch } from "@/components/ui/primitives";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { useMe } from "@/hooks/use-auth";
import { formatDateTime, formatPrice, timeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";
import { api } from "@/services/api";
import type { AlertEvent, AlertSettings, StrategyAlert } from "@/types/api";

const EVENTS_KEY = ["alert-events"] as const;
const ALERTS_KEY = ["alerts"] as const;
const POLL_MS = 60_000; // alerts are checked once a minute on the server

function KindBadge({ kind }: { kind: AlertEvent["kind"] }) {
  return <Badge variant={kind === "entry" ? "gain" : "loss"}>{kind === "entry" ? "Entry" : "Exit"}</Badge>;
}

function useEvents(limit = 50) {
  return useQuery({ queryKey: [...EVENTS_KEY, limit], queryFn: () => api.alerts.events(limit), refetchInterval: POLL_MS });
}

function useMarkRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ids?: number[]) => api.alerts.markRead(ids),
    onSuccess: () => qc.invalidateQueries({ queryKey: EVENTS_KEY }),
  });
}

// ------------------------------------------------------------- header bell
export function AlertsBell() {
  const events = useEvents(8);
  const markRead = useMarkRead();
  const unread = events.data?.unread ?? 0;
  return (
    <DropdownMenu onOpenChange={(open) => !open && unread > 0 && markRead.mutate(undefined)}>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon-sm" className="relative" aria-label={unread ? `Alerts, ${unread} unread` : "Alerts"}>
          {unread ? <BellRing /> : <Bell />}
          {unread > 0 && (
            <span className="absolute -top-0.5 -right-0.5 flex min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] leading-4 font-semibold text-primary-foreground tabular">
              {unread > 9 ? "9+" : unread}
            </span>
          )}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-80">
        <DropdownMenuLabel className="flex items-center justify-between">
          <span className="font-medium text-foreground">Strategy alerts</span>
          <Link href="/alerts" className="text-xs font-normal text-primary hover:underline">View all</Link>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        {!events.data?.events.length ? (
          <p className="px-3 py-6 text-center text-xs text-muted-foreground">
            No alerts yet. Turn them on from a strategy&apos;s page.
          </p>
        ) : (
          <ul className="max-h-96 overflow-y-auto">
            {events.data.events.map((e) => (
              <li key={e.id} className={cn("border-b border-border px-3 py-2 last:border-0", !e.read_at && "bg-primary/5")}>
                <div className="flex items-center gap-2 text-xs">
                  <KindBadge kind={e.kind} />
                  <span className="font-medium">{e.symbol}</span>
                  <span className="text-muted-foreground">{e.timeframe}</span>
                  <span className="ml-auto text-muted-foreground">{timeAgo(e.created_at)}</span>
                </div>
                <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{e.message}</p>
              </li>
            ))}
          </ul>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

// ----------------------------------------------------- strategy page card
export function StrategyAlertCard({ strategyId }: { strategyId: number }) {
  const qc = useQueryClient();
  const me = useMe();
  const alert = useQuery({ queryKey: [...ALERTS_KEY, strategyId], queryFn: () => api.alerts.get(strategyId) });
  const save = useMutation({
    mutationFn: (s: AlertSettings) => api.alerts.upsert(strategyId, s),
    onSuccess: (a) => {
      qc.setQueryData([...ALERTS_KEY, strategyId], a);
      qc.invalidateQueries({ queryKey: ALERTS_KEY, exact: true });
      toast.success(a.enabled ? "Alerts on" : "Alerts paused");
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const a = alert.data;
  const current: AlertSettings = a ?? { enabled: false, on_entry: true, on_exit: true, notify_email: false };
  const set = (patch: Partial<AlertSettings>) => save.mutate({ ...current, ...patch });
  const verified = me.data?.email_verified ?? false;

  return (
    <Card className="mt-4">
      <CardHeader>
        <div>
          <CardTitle className="flex items-center gap-2"><Bell className="size-4" /> Alerts</CardTitle>
          <CardDescription>
            Get notified when this strategy&apos;s rules fire on a newly closed candle (checked every minute). Notifications only; no orders are placed.
          </CardDescription>
        </div>
        {a?.enabled && <Badge variant="gain">Watching</Badge>}
      </CardHeader>
      <CardContent className="space-y-3">
        {alert.isLoading ? (
          <LoadingRows rows={2} />
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Toggle id="alert-enabled" label="Alerts on" checked={current.enabled} disabled={save.isPending} onChange={(v) => set({ enabled: v })} />
              <Toggle id="alert-entry" label="Entry signals" checked={current.on_entry} disabled={save.isPending || !current.enabled} onChange={(v) => set({ on_entry: v })} />
              <Toggle id="alert-exit" label="Exit signals" checked={current.on_exit} disabled={save.isPending || !current.enabled} onChange={(v) => set({ on_exit: v })} />
              <Toggle
                id="alert-email"
                label="Also email me"
                checked={current.notify_email}
                disabled={save.isPending || !current.enabled}
                onChange={(v) => set({ notify_email: v })}
              />
            </div>
            {current.notify_email && !verified && (
              <p className="text-xs text-warn">Emails are sent only to verified addresses. Verify yours from the banner at the top of the page.</p>
            )}
            {a?.enabled && (
              <p className="text-xs text-muted-foreground">
                {a.last_error
                  ? <span className="text-warn">{a.last_error}</span>
                  : a.last_checked_at
                    ? <>Last checked {timeAgo(a.last_checked_at)} · newest closed bar {formatDateTime(a.last_bar_at)}</>
                    : "Waiting for the first check (within a minute)."}
              </p>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

function Toggle({ id, label, checked, disabled, onChange }: { id: string; label: string; checked: boolean; disabled?: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-md border border-border px-3 py-2">
      <Label htmlFor={id} className="text-sm">{label}</Label>
      <Switch id={id} checked={checked} disabled={disabled} onCheckedChange={onChange} />
    </div>
  );
}

// -------------------------------------------------------------- alerts page
export function AlertsView() {
  const qc = useQueryClient();
  const alerts = useQuery({ queryKey: ALERTS_KEY, queryFn: api.alerts.list });
  const events = useEvents(200);
  const markRead = useMarkRead();
  const remove = useMutation({
    mutationFn: (strategyId: number) => api.alerts.remove(strategyId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ALERTS_KEY }),
    onError: (e: Error) => toast.error(e.message),
  });

  return (
    <>
      <PageHeader
        title="Alerts"
        description="Notifications when your strategies' rules fire on live, closed candles."
        actions={
          <Button size="sm" variant="outline" disabled={!events.data?.unread} loading={markRead.isPending} onClick={() => markRead.mutate(undefined)}>
            Mark all read
          </Button>
        }
      />
      <Disclaimer className="mb-4">{events.data?.disclaimer ?? "Simulated research signals. No orders are placed."}</Disclaimer>
      <div className="grid gap-4 xl:grid-cols-[1fr_420px]">
        <Card>
          <CardHeader><CardTitle>Recent alerts</CardTitle></CardHeader>
          <CardContent className="px-2">
            {events.isLoading ? (
              <LoadingRows rows={5} className="p-3" />
            ) : events.error ? (
              <ErrorState error={events.error} onRetry={() => events.refetch()} />
            ) : !events.data?.events.length ? (
              <EmptyState icon={Bell} title="No alerts yet" description="Turn on alerts from a strategy's page; they fire when its rules match on a newly closed candle." />
            ) : (
              <Table>
                <THead>
                  <TR className="hover:bg-transparent"><TH>Signal</TH><TH>Strategy</TH><TH>Bar</TH><TH className="text-right">Close</TH><TH>Details</TH></TR>
                </THead>
                <TBody>
                  {events.data.events.map((e) => (
                    <TR key={e.id} className={cn(!e.read_at && "bg-primary/5")}>
                      <TD><KindBadge kind={e.kind} /></TD>
                      <TD>
                        <Link href={`/strategies/${e.strategy_id}`} className="font-medium hover:text-primary">{e.symbol} {e.timeframe}</Link>
                        <span className="ml-1 text-xs text-muted-foreground">v{e.strategy_version}</span>
                      </TD>
                      <TD className="whitespace-nowrap text-muted-foreground">{formatDateTime(e.bar_at)}</TD>
                      <TD className="text-right tabular">{formatPrice(e.close_price)}</TD>
                      <TD className="max-w-md text-xs text-muted-foreground">{e.message}{e.emailed_at ? " · emailed" : ""}</TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            )}
          </CardContent>
        </Card>
        <Card className="h-fit">
          <CardHeader><CardTitle>Watched strategies</CardTitle></CardHeader>
          <CardContent className="px-2">
            {!alerts.data?.length ? (
              <p className="px-3 py-4 text-sm text-muted-foreground">None yet. Open a strategy and switch on alerts.</p>
            ) : (
              <Table>
                <TBody>
                  {alerts.data.map((a: StrategyAlert) => (
                    <TR key={a.id}>
                      <TD>
                        <Link href={`/strategies/${a.strategy_id}`} className="font-medium hover:text-primary">{a.strategy_name}</Link>
                        <p className="text-xs text-muted-foreground">
                          {a.symbol} {a.timeframe} · {[a.on_entry && "entry", a.on_exit && "exit"].filter(Boolean).join(" + ") || "no signals"}
                          {a.notify_email ? " · email" : ""}
                        </p>
                        {a.last_error && <p className="text-xs text-warn">{a.last_error}</p>}
                      </TD>
                      <TD>{a.enabled ? <Badge variant="gain">On</Badge> : <Badge variant="outline">Paused</Badge>}</TD>
                      <TD className="text-right">
                        <Button size="icon-sm" variant="ghost" aria-label={`Delete alert for ${a.strategy_name}`} onClick={() => remove.mutate(a.strategy_id)}>
                          <Trash2 />
                        </Button>
                      </TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>
    </>
  );
}
