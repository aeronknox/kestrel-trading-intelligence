import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/primitives";
import { formatCompact, formatNumber, formatPrice, isNum } from "@/lib/format";

type Latest = Record<string, number | null>;

function Row({ label, value, tag }: { label: string; value: string; tag?: { text: string; variant: "gain" | "loss" | "secondary" | "warn" } }) {
  return (
    <div className="flex items-center justify-between gap-3 py-2 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="flex items-center gap-2">
        <span className="font-medium tabular">{value}</span>
        {tag && <Badge variant={tag.variant}>{tag.text}</Badge>}
      </span>
    </div>
  );
}

/** Factual readout of the latest indicator values with standard (textbook) interpretations. */
export function IndicatorPanel({ latest }: { latest: Latest }) {
  const close = latest.close;
  const rsi = latest.rsi_14;
  const hist = latest.macd_hist;
  const pb = latest.bb_pct_b;
  const rel = (ma: number | null | undefined) =>
    isNum(close) && isNum(ma) ? { text: close > ma ? "Above" : "Below", variant: close > ma ? ("gain" as const) : ("loss" as const) } : undefined;

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Technical readout</CardTitle>
          <CardDescription>Latest computed values</CardDescription>
        </div>
      </CardHeader>
      <CardContent className="divide-y divide-border pt-0">
        <Row label="SMA 20" value={formatPrice(latest.sma_20)} tag={rel(latest.sma_20)} />
        <Row label="SMA 50" value={formatPrice(latest.sma_50)} tag={rel(latest.sma_50)} />
        <Row label="SMA 200" value={formatPrice(latest.sma_200)} tag={rel(latest.sma_200)} />
        <Row
          label="RSI (14)"
          value={formatNumber(rsi, 1)}
          tag={isNum(rsi) ? (rsi >= 70 ? { text: "Overbought", variant: "loss" } : rsi <= 30 ? { text: "Oversold", variant: "gain" } : { text: "Neutral", variant: "secondary" }) : undefined}
        />
        <Row label="MACD" value={formatNumber(latest.macd, 4)} />
        <Row label="MACD histogram" value={formatNumber(hist, 4)} tag={isNum(hist) ? (hist >= 0 ? { text: "Bullish", variant: "gain" } : { text: "Bearish", variant: "loss" }) : undefined} />
        <Row label="Bollinger upper" value={formatPrice(latest.bb_upper)} />
        <Row label="Bollinger lower" value={formatPrice(latest.bb_lower)} />
        <Row
          label="Bollinger %B"
          value={formatNumber(pb, 2)}
          tag={isNum(pb) ? (pb > 1 ? { text: "Above band", variant: "warn" } : pb < 0 ? { text: "Below band", variant: "warn" } : { text: "In band", variant: "secondary" }) : undefined}
        />
        <Row label="ATR (14)" value={formatPrice(latest.atr_14)} />
        <Row
          label="Volume vs 20-bar avg"
          value={isNum(latest.volume) && isNum(latest.volume_sma_20) ? `${formatCompact(latest.volume)} / ${formatCompact(latest.volume_sma_20)}` : "—"}
          tag={isNum(latest.volume_z) ? (latest.volume_z > 2 ? { text: "Spike", variant: "warn" } : latest.volume_z < -1 ? { text: "Thin", variant: "secondary" } : undefined) : undefined}
        />
      </CardContent>
    </Card>
  );
}
