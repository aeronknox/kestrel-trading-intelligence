"use client";

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { formatDate, formatDateTime, formatPct, formatUsd, timeAxisFormatter, usdAxisFormatter } from "@/lib/format";

const axisProps = {
  stroke: "var(--muted-foreground)",
  fontSize: 11,
  tickLine: false,
  axisLine: false,
} as const;

/** Axis tick formatter scaled to the series' time span. */
function timeTick(data: { time: number }[]) {
  return timeAxisFormatter(data.length > 1 ? data[data.length - 1]!.time - data[0]!.time : 0);
}

function TooltipBox({ children }: { children: React.ReactNode }) {
  return <div className="rounded-md border border-border bg-popover px-2.5 py-1.5 text-xs shadow-lg tabular">{children}</div>;
}

export function EquityAreaChart({
  data,
  height = 240,
  baseline,
}: {
  data: { time: number; equity: number; benchmark?: number }[];
  height?: number;
  baseline?: number;
}) {
  const up = data.length < 2 || data[data.length - 1]!.equity >= data[0]!.equity;
  const color = up ? "var(--gain)" : "var(--loss)";
  const id = up ? "eq-up" : "eq-down";
  const hasBenchmark = data.some((d) => d.benchmark !== undefined);
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.28} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
        <XAxis dataKey="time" type="number" domain={["dataMin", "dataMax"]} {...axisProps} tickFormatter={timeTick(data)} minTickGap={48} />
        <YAxis {...axisProps} width={64} domain={["auto", "auto"]} tickFormatter={usdAxisFormatter(data.flatMap((d) => (d.benchmark !== undefined ? [d.equity, d.benchmark] : [d.equity])))} />
        {baseline !== undefined && <ReferenceLine y={baseline} stroke="var(--muted-foreground)" strokeDasharray="3 3" strokeOpacity={0.5} />}
        <Tooltip
          cursor={{ stroke: "var(--border)" }}
          content={({ active, payload }) => {
            const point = payload?.[0]?.payload as { time: number; equity: number; benchmark?: number } | undefined;
            return active && point ? (
              <TooltipBox>
                <div className="text-muted-foreground">{formatDateTime(point.time)}</div>
                <div className="font-medium">{hasBenchmark && "Strategy "}{formatUsd(point.equity)}</div>
                {point.benchmark !== undefined && <div className="text-muted-foreground">Buy &amp; hold {formatUsd(point.benchmark)}</div>}
              </TooltipBox>
            ) : null;
          }}
        />
        <Area type="linear" dataKey="equity" name="Strategy" stroke={color} strokeWidth={2} fill={`url(#${id})`} isAnimationActive={false} />
        {hasBenchmark && (
          <Line type="linear" dataKey="benchmark" name="Buy & hold" stroke="var(--muted-foreground)" strokeWidth={1.5} strokeDasharray="4 3" dot={false} isAnimationActive={false} />
        )}
        {hasBenchmark && <Legend verticalAlign="top" height={24} iconSize={10} wrapperStyle={{ fontSize: 11 }} />}
      </ComposedChart>
    </ResponsiveContainer>
  );
}

export function DrawdownChart({ data, height = 140 }: { data: { time: number; drawdown_pct: number }[]; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
        <XAxis dataKey="time" type="number" domain={["dataMin", "dataMax"]} {...axisProps} tickFormatter={timeTick(data)} minTickGap={48} />
        <YAxis {...axisProps} width={64} tickFormatter={(v: number) => `${v.toFixed(0)}%`} />
        <Tooltip
          content={({ active, payload }) =>
            active && payload?.[0] ? (
              <TooltipBox>
                <div className="text-muted-foreground">{formatDateTime(payload[0].payload.time as number)}</div>
                <div className="font-medium text-loss">{formatPct(payload[0].value as number)}</div>
              </TooltipBox>
            ) : null
          }
        />
        <Area type="linear" dataKey="drawdown_pct" stroke="var(--loss)" fill="var(--loss-soft)" strokeWidth={1.5} isAnimationActive={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

const SERIES_COLORS = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)", "var(--chart-5)", "var(--info)"];

export function MultiLineChart({
  series,
  height = 300,
  valueFormatter = (v: number) => formatPct(v, 1),
}: {
  series: { name: string; points: { time: number; value: number }[] }[];
  height?: number;
  valueFormatter?: (v: number) => string;
}) {
  // Merge series onto a shared time axis.
  const rows = new Map<number, Record<string, number>>();
  series.forEach((s, i) => {
    for (const p of s.points) {
      const row = rows.get(p.time) ?? { time: p.time };
      row[`s${i}`] = p.value;
      rows.set(p.time, row);
    }
  });
  const data = [...rows.values()].sort((a, b) => a.time! - b.time!);
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
        <XAxis dataKey="time" type="number" domain={["dataMin", "dataMax"]} {...axisProps} tickFormatter={(t: number) => formatDate(t)} minTickGap={48} />
        <YAxis {...axisProps} width={56} tickFormatter={valueFormatter} />
        <ReferenceLine y={0} stroke="var(--muted-foreground)" strokeOpacity={0.4} />
        <Tooltip
          content={({ active, payload, label }) =>
            active && payload?.length ? (
              <TooltipBox>
                <div className="mb-1 text-muted-foreground">{formatDateTime(label as number)}</div>
                {payload.map((p) => (
                  <div key={String(p.dataKey)} className="flex items-center gap-2">
                    <span className="size-2 rounded-full" style={{ background: p.color }} />
                    <span className="text-muted-foreground">{p.name}</span>
                    <span className="ml-auto font-medium">{valueFormatter(p.value as number)}</span>
                  </div>
                ))}
              </TooltipBox>
            ) : null
          }
        />
        <Legend wrapperStyle={{ fontSize: 11 }} iconType="circle" iconSize={8} />
        {series.map((s, i) => (
          <Line key={s.name} name={s.name} dataKey={`s${i}`} stroke={SERIES_COLORS[i % SERIES_COLORS.length]} dot={false} strokeWidth={2} connectNulls isAnimationActive={false} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

export function AllocationDonut({ data, height = 220 }: { data: { name: string; value: number }[]; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <PieChart>
        <Pie data={data} dataKey="value" nameKey="name" innerRadius="62%" outerRadius="90%" paddingAngle={2} stroke="none" isAnimationActive={false}>
          {data.map((d, i) => (
            <Cell key={d.name} fill={d.name === "Cash" ? "var(--muted)" : SERIES_COLORS[i % SERIES_COLORS.length]} />
          ))}
        </Pie>
        <Tooltip
          content={({ active, payload }) =>
            active && payload?.[0] ? (
              <TooltipBox>
                <span className="text-muted-foreground">{payload[0].name}</span> <span className="font-medium">{formatUsd(payload[0].value as number)}</span>
              </TooltipBox>
            ) : null
          }
        />
      </PieChart>
    </ResponsiveContainer>
  );
}

export function ContributionBars({ data, height = 200 }: { data: { name: string; value: number }[]; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} layout="vertical" margin={{ top: 0, right: 12, bottom: 0, left: 0 }}>
        <XAxis type="number" domain={[-1, 1]} {...axisProps} tickFormatter={(v: number) => v.toFixed(1)} />
        <YAxis type="category" dataKey="name" {...axisProps} width={120} />
        <ReferenceLine x={0} stroke="var(--muted-foreground)" strokeOpacity={0.5} />
        <Tooltip
          cursor={{ fill: "var(--muted)", opacity: 0.4 }}
          content={({ active, payload }) =>
            active && payload?.[0] ? (
              <TooltipBox>
                {payload[0].payload.name}: <span className="font-medium">{(payload[0].value as number).toFixed(2)}</span>
              </TooltipBox>
            ) : null
          }
        />
        <Bar dataKey="value" radius={3} isAnimationActive={false}>
          {data.map((d) => (
            <Cell key={d.name} fill={d.value >= 0 ? "var(--gain)" : "var(--loss)"} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export function Sparkline({ values, height = 32, positive }: { values: number[]; height?: number; positive?: boolean }) {
  const up = positive ?? (values.length > 1 && values[values.length - 1]! >= values[0]!);
  const data = values.map((v, i) => ({ i, v }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 2, right: 0, bottom: 2, left: 0 }}>
        <YAxis hide domain={["dataMin", "dataMax"]} />
        <Line dataKey="v" stroke={up ? "var(--gain)" : "var(--loss)"} dot={false} strokeWidth={1.5} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

const MIN_CHART_SPAN_SECONDS = 600;

/** True once a series covers enough time for a line chart to mean something. */
export function hasChartableSpan(data: { time: number }[], minSeconds = MIN_CHART_SPAN_SECONDS): boolean {
  return data.length > 1 && data[data.length - 1]!.time - data[0]!.time >= minSeconds;
}

/** Shown instead of a chart for a brand-new portfolio whose snapshots are only seconds apart. */
export function YoungHistoryNote({ since, height }: { since: number | undefined; height: number }) {
  return (
    <div className="flex flex-col items-center justify-center gap-1 rounded-md border border-dashed border-border px-6 text-center" style={{ height }}>
      <p className="text-sm font-medium">Tracking started {since ? formatDateTime(since) : "just now"}</p>
      <p className="max-w-sm text-xs text-muted-foreground">
        The chart fills in as equity snapshots are recorded: after every fill, and every few minutes while positions are open.
      </p>
    </div>
  );
}

