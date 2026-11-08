import { Gauge } from "lucide-react";

import { EmptyState } from "@/components/common/states";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/primitives";
import { formatNumber, formatPct, isNum } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Sentiment } from "@/types/api";

function labelVariant(label: string): "gain" | "loss" | "secondary" | "warn" {
  if (label.includes("Risk-on") || label.includes("bullish")) return "gain";
  if (label.includes("Risk-off") || label.includes("bearish")) return "loss";
  if (label === "Unavailable") return "warn";
  return "secondary";
}

function Meter({ value, label, sub }: { value: number | null; label: string; sub?: string }) {
  const v = isNum(value) ? Math.max(0, Math.min(100, value)) : null;
  return (
    <div>
      <div className="flex items-baseline justify-between text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-medium tabular">{v === null ? "—" : formatNumber(v, 0)}{sub}</span>
      </div>
      <div className="relative mt-1.5 h-1.5 rounded-full bg-gradient-to-r from-loss via-warn to-gain opacity-80">
        {v !== null && (
          <span className="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-card bg-foreground shadow" style={{ left: `${v}%` }} />
        )}
      </div>
    </div>
  );
}

export function SentimentCard({ sentiment }: { sentiment: Sentiment | null }) {
  return (
    <Card className="h-full">
      <CardHeader>
        <div>
          <CardTitle>Market sentiment</CardTitle>
          <CardDescription>Computed from tracked assets&apos; daily data</CardDescription>
        </div>
        {sentiment && <Badge variant={labelVariant(sentiment.label)}>{sentiment.label}</Badge>}
      </CardHeader>
      <CardContent>
        {!sentiment ? (
          <EmptyState icon={Gauge} title="Sentiment unavailable" description="Market data could not be loaded." />
        ) : (
          <div className="space-y-4">
            <Meter
              value={sentiment.fear_greed?.value ?? null}
              label={`Fear & Greed${sentiment.fear_greed ? ` · ${sentiment.fear_greed.classification}` : ""}`}
            />
            <Meter value={sentiment.breadth_above_sma50_pct} label="Breadth (above daily SMA50)" sub="%" />
            <Meter value={sentiment.avg_rsi} label="Average daily RSI(14)" />
            <div className="grid grid-cols-3 gap-2 pt-1 text-center">
              <div className="rounded-md bg-gain-soft py-2">
                <div className="text-base font-semibold text-gain tabular">{sentiment.advancers}</div>
                <div className="text-[10px] text-muted-foreground">Advancing</div>
              </div>
              <div className="rounded-md bg-loss-soft py-2">
                <div className="text-base font-semibold text-loss tabular">{sentiment.decliners}</div>
                <div className="text-[10px] text-muted-foreground">Declining</div>
              </div>
              <div className="rounded-md bg-muted py-2">
                <div className={cn("text-base font-semibold tabular", (sentiment.avg_change_pct_24h ?? 0) >= 0 ? "text-gain" : "text-loss")}>
                  {formatPct(sentiment.avg_change_pct_24h, 1)}
                </div>
                <div className="text-[10px] text-muted-foreground">Avg 24h</div>
              </div>
            </div>
            <p className="text-[10px] text-muted-foreground">
              {sentiment.fear_greed ? `Fear & Greed: ${sentiment.fear_greed.source}. ` : "Fear & Greed index unavailable. "}
              Breadth/RSI derived from provider candles.
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
