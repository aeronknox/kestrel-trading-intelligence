import { ArrowDownRight, ArrowUpRight, Info, Minus, ShieldAlert } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/primitives";
import { Tooltip } from "@/components/ui/overlays";
import { formatPct, isNum, pnlClass } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { DataMeta, SignalAction } from "@/types/api";

export function Change({ value, className, showIcon = true }: { value: number | null | undefined; className?: string; showIcon?: boolean }) {
  const Icon = !isNum(value) || value === 0 ? Minus : value > 0 ? ArrowUpRight : ArrowDownRight;
  return (
    <span className={cn("inline-flex items-center gap-0.5 tabular", pnlClass(value), className)}>
      {showIcon && <Icon className="size-3.5" />}
      {formatPct(value)}
    </span>
  );
}

export function StatCard({
  label,
  value,
  sub,
  icon: Icon,
  hint,
  className,
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  icon?: LucideIcon;
  hint?: string;
  className?: string;
}) {
  return (
    <Card className={cn("relative overflow-hidden p-4", className)}>
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-1 text-xs text-muted-foreground">
          {label}
          {hint && (
            <Tooltip content={hint}>
              <Info className="size-3 cursor-help opacity-60" />
            </Tooltip>
          )}
        </span>
        {Icon && <Icon className="size-4 text-muted-foreground/70" />}
      </div>
      <div className="mt-2 text-xl font-semibold tracking-tight tabular sm:text-2xl">{value}</div>
      {sub && <div className="mt-1 text-xs text-muted-foreground">{sub}</div>}
    </Card>
  );
}

const ACTION_STYLE: Record<SignalAction, { variant: "gain" | "loss" | "secondary"; label: string }> = {
  buy: { variant: "gain", label: "BUY" },
  sell: { variant: "loss", label: "SELL" },
  hold: { variant: "secondary", label: "HOLD" },
};

export function SignalBadge({ action, className }: { action: SignalAction; className?: string }) {
  const s = ACTION_STYLE[action];
  return (
    <Badge variant={s.variant} className={cn("font-semibold tracking-wide", className)}>
      {s.label}
    </Badge>
  );
}

export function ConfidenceBar({ value, className }: { value: number; className?: string }) {
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${Math.max(2, Math.min(100, value))}%` }} />
      </div>
      <span className="w-12 text-right text-xs text-muted-foreground tabular">{value.toFixed(0)}/100</span>
    </div>
  );
}

/** Small provenance line under any data-derived widget. */
export function DataSource({ meta, className }: { meta?: Partial<DataMeta> | null; className?: string }) {
  if (!meta) return null;
  return (
    <p className={cn("text-[11px] text-muted-foreground", className)}>
      {meta.is_sample ? <span className="font-medium text-warn">SAMPLE DATA · </span> : null}
      {meta.attribution}
      {meta.stale ? <span className="text-warn"> · stale (provider unavailable)</span> : null}
    </p>
  );
}

export function Disclaimer({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("flex items-start gap-2 rounded-lg border border-warn/25 bg-warn-soft px-3 py-2 text-xs text-warn", className)}>
      <ShieldAlert className="mt-0.5 size-3.5 shrink-0" />
      <div className="leading-relaxed">{children}</div>
    </div>
  );
}

export function AssetIcon({ symbol, className }: { symbol: string; className?: string }) {
  const base = symbol.split("-")[0] ?? symbol;
  // Deterministic hue per asset so icons are distinguishable without logos.
  let h = 0;
  for (const ch of base) h = (h * 31 + ch.charCodeAt(0)) % 360;
  return (
    <span
      className={cn("asset-icon inline-flex size-7 shrink-0 items-center justify-center rounded-full text-[10px] font-bold", className)}
      style={{ "--hue": h } as React.CSSProperties}
    >
      {base.slice(0, 4)}
    </span>
  );
}
