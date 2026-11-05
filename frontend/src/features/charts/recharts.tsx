"use client";

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
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

import { formatDate, formatDateTime, formatPct, formatUsd } from "@/lib/format";

const axisProps = {
  stroke: "var(--muted-foreground)",
  fontSize: 11,
  tickLine: false,
  axisLine: false,
} as const;

/** Axis tick formatter that shows times for intraday ranges and dates otherwise. */
function timeTick(data: { time: number }[]) {
  const span = data.length > 1 ? data[data.length - 1]!.time - data[0]!.time : 0;
  return (t: number) =>
    span < 2 * 86400
      ? new Date(t * 1000).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" })
      : formatDate(t);
}

function TooltipBox({ children }: { children: React.ReactNode }) {
  return <div className="rounded-md border border-border bg-popover px-2.5 py-1.5 text-xs shadow-lg tabular">{children}</div>;
}

export function EquityAreaChart({
  data,
  height = 240,
  baseline,
}: {
  data: { time: number; equity: number }[];
  height?: number;
  baseline?: number;
}) {
  const up = data.length < 2 || data[data.length - 1]!.equity >= data[0]!.equity;
  const color = up ? "var(--gain)" : "var(--loss)";
  const id = up ? "eq-up" : "eq-down";
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.28} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
        <XAxis dataKey="time" type="number" domain={["dataMin", "dataMax"]} {...axisProps} tickFormatter={timeTick(data)} minTickGap={48} />
        <YAxis {...axisProps} width={64} domain={["auto", "auto"]} tickFormatter={(v: number) => formatUsd(v, { compact: true })} />
        {baseline !== undefined && <ReferenceLine y={baseline} stroke="var(--muted-foreground)" strokeDasharray="3 3" strokeOpacity={0.5} />}
        <Tooltip
          cursor={{ stroke: "var(--border)" }}
          content={({ active, payload }) =>
            active && payload?.[0] ? (
              <TooltipBox>
                <div className="text-muted-foreground">{formatDateTime(payload[0].payload.time as number)}</div>
                <div className="font-medium">{formatUsd(payload[0].value as number)}</div>
              </TooltipBox>
            ) : null
          }
        />
        <Area type="linear" dataKey="equity" stroke={color} strokeWidth={2} fill={`url(#${id})`} isAnimationActive={false} />
      </AreaChart>
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
