"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { NotebookPen } from "lucide-react";
import Link from "next/link";
import { type ReactNode, useState } from "react";
import { toast } from "sonner";

import { DownloadButton } from "@/components/common/download-button";
import { EmptyState, ErrorState, LoadingRows } from "@/components/common/states";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/overlays";
import { Badge, Field, Input, Textarea } from "@/components/ui/primitives";
import { Segmented, SegmentedItem } from "@/components/ui/segmented";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { RCurveChart } from "@/features/charts/recharts";
import { formatDateTime, formatPct, formatPrice, formatQty, formatUsd, pnlClass } from "@/lib/format";
import { cn } from "@/lib/utils";
import { api } from "@/services/api";
import type { JournalGroup, JournalTrip, RCurve } from "@/types/api";

const JOURNAL_KEY = ["paper", "journal"] as const;
const EMOTION_LABEL: Record<string, string> = {
  calm: "Calm", confident: "Confident", anxious: "Anxious", fearful: "Fearful", greedy: "Greedy",
  impatient: "Impatient", fomo: "FOMO", revenge: "Revenge", bored: "Bored",
};
const NO_EMOTION = "none";

function held(seconds: number | null): string {
  if (seconds === null) return "—";
  const m = seconds / 60;
  if (m < 1) return "<1m";
  if (m < 60) return `${Math.round(m)}m`;
  if (m < 60 * 48) return `${Math.round(m / 60)}h`;
  return `${Math.round(m / 1440)}d`;
}

function formatR(r: number | null | undefined): string {
  return r === null || r === undefined ? "—" : `${r >= 0 ? "+" : "−"}${Math.abs(r).toFixed(2)}R`;
}

const R_HINT = "Result in units of the initial risk: what hitting the first stop would have lost.";

function Summary({ overall }: { overall: JournalGroup }) {
  const tiles: [string, ReactNode, string?][] = [
    ["Closed trades", overall.trades],
    ["Win rate", formatPct(overall.win_rate, 0, false)],
    ["Expectancy", <span key="e" className={pnlClass(overall.avg_pnl)}>{formatUsd(overall.avg_pnl, { sign: true })}</span>, "Average P&L per trade"],
    ["Avg R", <span key="r" className={pnlClass(overall.avg_r)}>{formatR(overall.avg_r)}</span>,
      overall.r_trades < overall.trades ? `Over the ${overall.r_trades} of ${overall.trades} trades with a stop` : R_HINT],
    ["Total P&L", <span key="t" className={pnlClass(overall.total_pnl)}>{formatUsd(overall.total_pnl, { sign: true })}</span>],
  ];
  return (
    <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
      {tiles.map(([label, value, hint]) => (
        <div key={label} className="rounded-lg border border-border bg-card px-4 py-3">
          <dt className="text-xs text-muted-foreground">{label}</dt>
          <dd className="tabular mt-1 text-lg font-semibold">{value}</dd>
          {hint && <dd className="mt-0.5 text-[11px] leading-snug text-muted-foreground">{hint}</dd>}
        </div>
      ))}
    </dl>
  );
}

function RCurveCard({ curve, closed }: { curve: RCurve | null; closed: number }) {
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>R curve</CardTitle>
          <CardDescription>
            Each closed trade&apos;s result in R (bars) and the running total (line), in the order they closed. A curve that climbs over many
            trades suggests an edge; a few trades prove little.
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent>
        {!curve ? (
          <p className="text-sm text-muted-foreground">
            {closed
              ? "None of your closed trades has a stop yet. Add a stop-loss to new entries, or record a planned stop when you review a trade."
              : "Close a trade that has a stop-loss to start the curve."}
          </p>
        ) : (
          <div className="space-y-3">
            <dl className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
              <div><dt className="inline text-muted-foreground">Total </dt><dd className={cn("inline font-semibold tabular", pnlClass(curve.total_r))}>{formatR(curve.total_r)}</dd></div>
              <div><dt className="inline text-muted-foreground">Worst drawdown </dt><dd className="inline font-semibold tabular">{curve.max_drawdown_r ? formatR(-curve.max_drawdown_r) : "none"}</dd></div>
              <div><dt className="inline text-muted-foreground">Longest losing streak </dt><dd className="inline font-semibold tabular">{curve.longest_losing_streak} {curve.longest_losing_streak === 1 ? "trade" : "trades"}</dd></div>
              <div><dt className="inline text-muted-foreground">Trades </dt><dd className="inline font-semibold tabular">{curve.points.length}{curve.points.length < closed ? ` of ${closed}` : ""}</dd></div>
            </dl>
            <RCurveChart points={curve.points} />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Stars({ rating }: { rating: number | null | undefined }) {
  if (!rating) return <span className="text-muted-foreground">—</span>;
  return (
    <span title={`Followed the plan: ${rating} of 5`}>
      <span aria-hidden className="text-warn">{"★".repeat(rating)}</span>
      <span aria-hidden className="text-muted-foreground/50">{"★".repeat(5 - rating)}</span>
      <span className="sr-only">{rating} of 5</span>
    </span>
  );
}

function StatsTable({ title, description, groups, empty, label }: {
  title: string;
  description: string;
  groups: JournalGroup[];
  empty: string;
  label: (name: string | null) => string;
}) {
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>{title}</CardTitle>
          <CardDescription>{description}</CardDescription>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        {!groups.length ? (
          <p className="px-5 pb-5 text-sm text-muted-foreground">{empty}</p>
        ) : (
          <Table>
            <THead>
              <TR className="hover:bg-transparent">
                <TH>{title.replace("By ", "")}</TH><TH className="text-right">Trades</TH><TH className="text-right">Win rate</TH>
                <TH className="text-right" title="Average P&L per trade (expectancy)">Avg P&amp;L</TH><TH className="text-right">Total</TH>
                <TH className="hidden text-right sm:table-cell" title={R_HINT}>Avg R</TH>
                <TH className="hidden text-right sm:table-cell">Discipline</TH>
              </TR>
            </THead>
            <TBody>
              {groups.map((g) => (
                <TR key={g.name ?? "-"}>
                  <TD className={cn("font-medium", g.name === null && "text-muted-foreground italic")}>{label(g.name)}</TD>
                  <TD className="text-right">{g.trades}</TD>
                  <TD className="text-right">{formatPct(g.win_rate, 0, false)}</TD>
                  <TD className={cn("text-right", pnlClass(g.avg_pnl))}>{formatUsd(g.avg_pnl, { sign: true })}</TD>
                  <TD className={cn("text-right", pnlClass(g.total_pnl))}>{formatUsd(g.total_pnl, { sign: true })}</TD>
                  <TD className={cn("hidden text-right sm:table-cell", pnlClass(g.avg_r))}
                    title={g.avg_r !== null && g.r_trades < g.trades ? `${g.r_trades} of ${g.trades} trades had a stop` : undefined}>
                    {formatR(g.avg_r)}
                  </TD>
                  <TD className="hidden text-right sm:table-cell">{g.avg_rating ? g.avg_rating.toFixed(1) : "—"}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

function EntryDialog({ trip, setups, emotions, onClose }: { trip: JournalTrip; setups: string[]; emotions: string[]; onClose: () => void }) {
  const qc = useQueryClient();
  const e = trip.entry;
  const [setup, setSetup] = useState(e?.setup ?? "");
  const [emotion, setEmotion] = useState(e?.emotion ?? NO_EMOTION);
  const [rating, setRating] = useState(e?.rating ? String(e.rating) : "");
  const [notes, setNotes] = useState(e?.notes ?? "");
  const [lesson, setLesson] = useState(e?.lesson ?? "");
  const [stop, setStop] = useState(e?.planned_stop ? String(e.planned_stop) : "");
  const long = trip.side === "long";
  const stopNum = Number(stop) > 0 ? Number(stop) : null;
  const stopError = stopNum && (long ? stopNum >= trip.entry_price : stopNum <= trip.entry_price)
    ? `Must be ${long ? "below" : "above"} the entry price (${formatPrice(trip.entry_price)})` : null;
  const previewRisk = stopNum && !stopError ? Math.abs(trip.entry_price - stopNum) * trip.quantity : null;
  const previewR = previewRisk && trip.pnl !== null ? trip.pnl / previewRisk : null;
  const found = trip.stop_source && trip.stop_source !== "journal" ? trip.initial_stop : null;
  const done = (message: string) => {
    qc.invalidateQueries({ queryKey: JOURNAL_KEY });
    toast.success(message);
    onClose();
  };
  const save = useMutation({
    mutationFn: () =>
      api.journal.save(trip.trade_id, {
        setup: setup.trim() || null,
        emotion: emotion === NO_EMOTION ? null : emotion,
        rating: rating ? Number(rating) : null,
        notes,
        lesson,
        planned_stop: stopNum,
      }),
    onSuccess: () => done("Journal saved"),
    onError: (err: Error) => toast.error(err.message),
  });
  const remove = useMutation({
    mutationFn: () => api.journal.remove(trip.trade_id),
    onSuccess: () => done("Journal entry deleted"),
    onError: (err: Error) => toast.error(err.message),
  });

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>
            Review {trip.side} {trip.symbol}
          </DialogTitle>
          <DialogDescription>
            Opened {formatDateTime(trip.opened_at)} at {formatPrice(trip.entry_price)}
            {trip.closed_at && trip.pnl !== null && (
              <> · closed at {formatPrice(trip.exit_price)} for <span className={pnlClass(trip.pnl)}>{formatUsd(trip.pnl, { sign: true })}</span></>
            )}
            . Be honest: the journal is only useful if it records what actually happened.
          </DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-4"
          onSubmit={(ev) => {
            ev.preventDefault();
            save.mutate();
          }}
        >
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Setup" hint="The pattern or reason you traded, e.g. Breakout">
              <Input value={setup} maxLength={40} list="journal-setups" onChange={(ev) => setSetup(ev.target.value)} placeholder="Breakout" />
            </Field>
            <datalist id="journal-setups">
              {setups.map((s) => <option key={s} value={s} />)}
            </datalist>
            <Field label="State of mind when you entered">
              <Select value={emotion} onValueChange={setEmotion}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value={NO_EMOTION}>Not recorded</SelectItem>
                  {emotions.map((m) => <SelectItem key={m} value={m}>{EMOTION_LABEL[m] ?? m}</SelectItem>)}
                </SelectContent>
              </Select>
            </Field>
          </div>
          <div className="space-y-1.5">
            <p className="text-sm font-medium" aria-hidden>How well did you follow your plan?</p>
            <Segmented value={rating} onValueChange={setRating} label="How well did you follow your plan? 1 to 5" className="w-full">
              {["1", "2", "3", "4", "5"].map((r) => <SegmentedItem key={r} value={r} className="flex-1">{r}</SegmentedItem>)}
            </Segmented>
            <p className="text-[11px] text-muted-foreground">1: ignored it · 5: followed it exactly, whatever the result.</p>
          </div>
          <Field
            label="Planned stop"
            error={stopError}
            hint={
              previewRisk
                ? `Risked ${formatUsd(previewRisk)}${previewR !== null ? `, so this trade made ${formatR(previewR)}` : ""}.`
                : found
                  ? `Found on your orders: ${formatPrice(found)}. Enter a price to use another.`
                  : "Where you planned to get out at a loss. Measures the result in R (multiples of what you risked)."
            }
          >
            <Input type="number" min={0} step="any" value={stop} onChange={(ev) => setStop(ev.target.value)}
              placeholder={found ? formatPrice(found) : long ? "Below entry" : "Above entry"} />
          </Field>
          <Field label="Notes" hint="Entry reason, where the stop and target were, what happened">
            <Textarea rows={3} maxLength={4000} value={notes} onChange={(ev) => setNotes(ev.target.value)} />
          </Field>
          <Field label="Lesson" hint="One thing to repeat or avoid next time">
            <Textarea rows={2} maxLength={2000} value={lesson} onChange={(ev) => setLesson(ev.target.value)} />
          </Field>
          <DialogFooter className="gap-2 sm:justify-between">
            {e ? (
              <Button type="button" variant="ghost" onClick={() => window.confirm("Delete this journal entry?") && remove.mutate()} loading={remove.isPending}>
                Delete entry
              </Button>
            ) : <span />}
            <div className="flex gap-2">
              <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
              <Button type="submit" loading={save.isPending} disabled={Boolean(stopError)}>Save</Button>
            </div>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function JournalView() {
  const journal = useQuery({ queryKey: JOURNAL_KEY, queryFn: api.journal.get });
  const [filter, setFilter] = useState<"all" | "review" | "open">("all");
  const [editing, setEditing] = useState<JournalTrip | null>(null);
  const data = journal.data;
  const trips = (data?.trips ?? []).filter((t) =>
    filter === "review" ? t.closed_at && !t.entry : filter === "open" ? !t.closed_at : true,
  );

  return (
    <>
      <PageHeader
        title="Trading journal"
        description="Review each simulated trade: why you took it, how you felt, and what it taught you. The stats show which setups and states of mind actually pay."
        actions={data?.trips.length ? <DownloadButton href="/paper/journal.csv" label="Download the journal as CSV">Journal CSV</DownloadButton> : null}
      />
      {journal.isLoading ? (
        <LoadingRows rows={6} />
      ) : journal.isError ? (
        <ErrorState error={journal.error} onRetry={() => journal.refetch()} />
      ) : !data?.trips.length ? (
        <EmptyState
          icon={NotebookPen}
          title="No trades to review yet"
          description="Each paper trade, from opening a position to closing it, becomes a journal entry here."
          action={<Button asChild size="sm"><Link href="/paper-trading">Go to paper trading</Link></Button>}
        />
      ) : (
        <div className="grid grid-cols-[minmax(0,1fr)] gap-4">
          {data.overall && <Summary overall={data.overall} />}
          {data.overall && <RCurveCard curve={data.r_curve} closed={data.overall.trades} />}
          {data.needs_review > 0 && (
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-primary/30 bg-primary/5 px-4 py-3 text-sm">
              <span>
                <strong>{data.needs_review}</strong> closed {data.needs_review === 1 ? "trade needs" : "trades need"} a review.
              </span>
              <Button size="sm" variant="outline" onClick={() => setFilter("review")}>Show them</Button>
            </div>
          )}
          <div className="grid grid-cols-[minmax(0,1fr)] gap-4 xl:grid-cols-2">
            <StatsTable
              title="By setup"
              description="Closed trades grouped by the setup you recorded."
              groups={data.by_setup}
              empty="Record a setup on a closed trade to compare setups."
              label={(n) => n ?? "Not reviewed"}
            />
            <StatsTable
              title="By state of mind"
              description="Does trading while impatient or chasing (FOMO) cost you?"
              groups={data.by_emotion}
              empty="Record how you felt to see its effect."
              label={(n) => (n ? EMOTION_LABEL[n] ?? n : "Not recorded")}
            />
          </div>
          <Card>
            <CardHeader>
              <CardTitle>Trades</CardTitle>
              <Segmented value={filter} onValueChange={(v) => setFilter(v as typeof filter)} label="Show trades">
                <SegmentedItem value="all">All</SegmentedItem>
                <SegmentedItem value="review">Needs review</SegmentedItem>
                <SegmentedItem value="open">Open</SegmentedItem>
              </Segmented>
            </CardHeader>
            <CardContent className="p-0">
              {!trips.length ? (
                <EmptyState title={filter === "review" ? "Every closed trade is reviewed" : "No open trades"} className="py-8" />
              ) : (
                <Table>
                  <THead>
                    <TR className="hover:bg-transparent">
                      <TH>Opened</TH><TH>Trade</TH><TH className="hidden text-right lg:table-cell">Size</TH>
                      <TH className="hidden text-right md:table-cell">Entry → exit</TH><TH className="text-right">P&amp;L</TH>
                      <TH className="hidden text-right sm:table-cell" title={R_HINT}>R</TH><TH className="hidden text-right lg:table-cell">Held</TH><TH>Setup</TH><TH className="hidden md:table-cell">Mind</TH>
                      <TH className="hidden lg:table-cell">Plan</TH><TH />
                    </TR>
                  </THead>
                  <TBody>
                    {trips.map((t) => (
                      <TR key={t.trade_id}>
                        <TD className="whitespace-nowrap text-muted-foreground">{formatDateTime(t.opened_at)}</TD>
                        <TD className="whitespace-nowrap">
                          <span className="font-medium">{t.symbol}</span>{" "}
                          <Badge variant={t.side === "short" ? "loss" : "secondary"}>{t.side}</Badge>
                        </TD>
                        <TD className="hidden text-right lg:table-cell">{formatQty(t.quantity)}</TD>
                        <TD className="hidden whitespace-nowrap text-right md:table-cell">
                          {formatPrice(t.entry_price)} → {t.exit_price !== null ? formatPrice(t.exit_price) : "open"}
                        </TD>
                        <TD className={cn("whitespace-nowrap text-right", pnlClass(t.pnl))}>
                          {t.pnl === null ? <Badge variant="info">Open</Badge> : (
                            <>{formatUsd(t.pnl, { sign: true })} <span className="text-xs">({formatPct(t.pnl_pct, 1)})</span></>
                          )}
                        </TD>
                        <TD className={cn("hidden whitespace-nowrap text-right sm:table-cell", pnlClass(t.r_multiple))}
                          title={t.initial_stop !== null ? `Initial stop ${formatPrice(t.initial_stop)} (${t.stop_source}), risking ${formatUsd(t.risk)}` : "No stop: record one when you review the trade"}>
                          {t.pnl === null ? (t.initial_stop !== null ? <span className="text-muted-foreground">stop {formatPrice(t.initial_stop)}</span> : "—") : formatR(t.r_multiple)}
                        </TD>
                        <TD className="hidden text-right lg:table-cell">{held(t.holding_seconds)}</TD>
                        <TD>{t.entry?.setup ?? <span className="text-muted-foreground">—</span>}</TD>
                        <TD className="hidden md:table-cell">{t.entry?.emotion ? EMOTION_LABEL[t.entry.emotion] ?? t.entry.emotion : "—"}</TD>
                        <TD className="hidden lg:table-cell"><Stars rating={t.entry?.rating} /></TD>
                        <TD className="text-right">
                          <Button size="sm" variant={t.entry || !t.closed_at ? "ghost" : "outline"} onClick={() => setEditing(t)}
                            aria-label={`${t.entry ? "Edit" : "Review"} ${t.symbol} trade opened ${formatDateTime(t.opened_at)}`}>
                            {t.entry ? "Edit" : "Review"}
                          </Button>
                        </TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              )}
            </CardContent>
          </Card>
          <p className="text-xs text-muted-foreground">{data.disclaimer}</p>
        </div>
      )}
      {editing && data && <EntryDialog trip={editing} setups={data.setups} emotions={data.emotions} onClose={() => setEditing(null)} />}
    </>
  );
}
