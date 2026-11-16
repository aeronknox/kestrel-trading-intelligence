"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useMemo, useState } from "react";

import { EmptyState } from "@/components/common/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { addMonths, localTimezone, monthGrid } from "@/lib/calendar";
import { formatUsd, pnlClass } from "@/lib/format";
import { cn } from "@/lib/utils";
import { api } from "@/services/api";
import type { PnlDay } from "@/types/api";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function todayIn(tz: string): { year: number; month: number; iso: string } {
  const iso = new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
  const [y, m] = iso.split("-").map(Number);
  return { year: y, month: m - 1, iso };
}

/** Each day's realized P&L from closing paper fills, a month at a time, in your own timezone. */
export function PnlCalendarCard() {
  const [tz] = useState(localTimezone);
  const today = useMemo(() => todayIn(tz), [tz]);
  const cal = useQuery({ queryKey: ["paper", "pnl-calendar", tz], queryFn: () => api.paper.pnlCalendar(tz) });
  const days = cal.data?.days;
  const byDate = useMemo(() => new Map((days ?? []).map((d) => [d.date, d])), [days]);

  // Start on the latest month with a closed trade (or this month); don't page past this month or before the first.
  const [picked, setPicked] = useState<{ year: number; month: number } | null>(null);
  const last = days?.at(-1)?.date;
  const first = days?.[0]?.date;
  const shown = picked ?? (last ? { year: Number(last.slice(0, 4)), month: Number(last.slice(5, 7)) - 1 } : today);
  const key = (ym: { year: number; month: number }) => ym.year * 12 + ym.month;
  const canBack = first ? key(shown) > Number(first.slice(0, 4)) * 12 + Number(first.slice(5, 7)) - 1 : false;
  const canForward = key(shown) < key(today);

  const grid = monthGrid(shown.year, shown.month);
  const inMonth = grid.flat().flatMap((d) => (d && byDate.get(d) ? [byDate.get(d) as PnlDay] : []));
  const total = inMonth.reduce((s, d) => s + d.realized_pnl, 0);
  const scale = Math.max(...inMonth.map((d) => Math.abs(d.realized_pnl)), 0);
  const monthName = new Date(Date.UTC(shown.year, shown.month, 1)).toLocaleString(undefined, { month: "long", year: "numeric", timeZone: "UTC" });

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>P&amp;L calendar</CardTitle>
          <CardDescription>Realized P&amp;L of each day&apos;s closing fills, after fees ({tz}). Open positions aren&apos;t counted until closed.</CardDescription>
        </div>
      </CardHeader>
      <CardContent>
        {!cal.data && cal.isLoading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : !days?.length ? (
          <EmptyState title="No closed trades yet" description="Each day you close a paper position shows up here, green or red." />
        ) : (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-1">
                <Button size="icon-sm" variant="ghost" aria-label="Previous month" disabled={!canBack} onClick={() => setPicked(addMonths(shown, -1))}><ChevronLeft /></Button>
                <h3 className="min-w-36 text-center text-sm font-semibold" aria-live="polite">{monthName}</h3>
                <Button size="icon-sm" variant="ghost" aria-label="Next month" disabled={!canForward} onClick={() => setPicked(addMonths(shown, 1))}><ChevronRight /></Button>
              </div>
              <p className="text-xs text-muted-foreground">
                <span className={cn("font-semibold tabular", pnlClass(total))}>{formatUsd(total, { sign: true })}</span>
                {" · "}{inMonth.filter((d) => d.realized_pnl > 0).length} green, {inMonth.filter((d) => d.realized_pnl < 0).length} red
              </p>
            </div>
            <table className="w-full table-fixed border-separate border-spacing-1 text-center">
              <caption className="sr-only">Realized P&amp;L by day, {monthName}</caption>
              <thead>
                <tr>{WEEKDAYS.map((w) => <th key={w} scope="col" className="text-[10px] font-medium text-muted-foreground">{w}</th>)}</tr>
              </thead>
              <tbody>
                {grid.map((week, i) => (
                  <tr key={i}>
                    {week.map((date, j) => {
                      if (!date) return <td key={j} />;
                      const d = byDate.get(date);
                      const share = d && scale ? Math.abs(d.realized_pnl) / scale : 0;
                      const color = d && d.realized_pnl > 0 ? "var(--color-gain)" : "var(--color-loss)";
                      const label = d
                        ? `${date}: ${formatUsd(d.realized_pnl, { sign: true })} from ${d.trades} closing fill${d.trades === 1 ? "" : "s"} (${d.wins} won, ${d.losses} lost)`
                        : `${date}: no closed trades`;
                      return (
                        <td
                          key={j}
                          title={label}
                          aria-label={label}
                          className={cn("h-12 rounded-md border border-border/60 p-1 align-top", date === today.iso && "ring-1 ring-primary")}
                          style={d && d.realized_pnl ? { backgroundColor: `color-mix(in oklab, ${color} ${Math.round(10 + share * 25)}%, transparent)` } : undefined}
                        >
                          <span className={cn("block text-left text-[10px]", d ? "text-foreground" : "text-muted-foreground")}>{Number(date.slice(8))}</span>
                          {d && <span className="block truncate text-[10px] font-semibold tabular">{formatUsd(d.realized_pnl, { compact: true, sign: true })}</span>}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
            {cal.data && (cal.data.best_day || cal.data.worst_day) && (
              <p className="text-xs text-muted-foreground">
                All time: {cal.data.green_days} green and {cal.data.red_days} red days
                {cal.data.best_day && <>; best {cal.data.best_day.date} (<span className="text-gain">{formatUsd(cal.data.best_day.realized_pnl, { sign: true })}</span>)</>}
                {cal.data.worst_day && <>; worst {cal.data.worst_day.date} (<span className="text-loss">{formatUsd(cal.data.worst_day.realized_pnl, { sign: true })}</span>)</>}
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
