import { AlertTriangle, Cpu, Info, Shapes, TrendingDown, TrendingUp, Waves } from "lucide-react";

import { ConfidenceBar, Disclaimer, SignalBadge } from "@/components/common/finance";
import { EmptyState } from "@/components/common/states";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/primitives";
import { ContributionBars } from "@/features/charts/recharts";
import { formatDateTime, formatPct, formatPrice } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Analysis, Risk } from "@/types/api";

export function SignalSummaryCard({ a }: { a: Analysis }) {
  const s = a.signal;
  if (!s) return null;
  return (
    <Card>
      <CardContent className="grid gap-5 p-5 md:grid-cols-[auto_1fr_auto] md:items-center">
        <div className="flex items-center gap-3">
          <SignalBadge action={s.action} className="px-3 py-1.5 text-sm" />
          <div>
            <p className="text-sm font-medium">{a.asset.symbol} · {a.timeframe}</p>
            <p className="text-xs text-muted-foreground">Signal at {formatPrice(s.price_at_signal, true)}</p>
          </div>
        </div>
        <div className="grid gap-2">
          <div className="flex items-center justify-between text-xs">
            <span className="text-muted-foreground">Composite score (buy &gt; +0.20, sell &lt; −0.20)</span>
            <span className={cn("font-semibold tabular", s.score > 0.2 ? "text-gain" : s.score < -0.2 ? "text-loss" : "text-muted-foreground")}>
              {s.score >= 0 ? "+" : ""}
              {s.score.toFixed(2)}
            </span>
          </div>
          <div className="relative h-2 rounded-full bg-gradient-to-r from-loss/60 via-muted to-gain/60">
            <span className="absolute top-1/2 h-3.5 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full bg-foreground" style={{ left: `${((s.score + 1) / 2) * 100}%` }} />
          </div>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span className="w-20">Confidence</span>
            <ConfidenceBar value={s.confidence} className="flex-1" />
          </div>
        </div>
        <div className="text-xs text-muted-foreground md:text-right">
          <p>Data as of {formatDateTime(a.data_as_of)} UTC</p>
          <p>Generated {formatDateTime(a.created_at)}</p>
          <p className="mt-1">{a.data_source.replace(":stale", " (stale)")}</p>
        </div>
      </CardContent>
    </Card>
  );
}

export function ComponentsCard({ a }: { a: Analysis }) {
  const comps = a.signal?.components ?? [];
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Why this signal</CardTitle>
          <CardDescription>Each component scored −1 (bearish) to +1 (bullish), then weighted</CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <ContributionBars data={comps.map((c) => ({ name: c.name, value: c.score }))} height={Math.max(120, comps.length * 34)} />
        <ul className="space-y-3">
          {comps.map((c) => (
            <li key={c.name} className="rounded-lg border border-border p-3">
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium">{c.name}</span>
                <span className="flex items-center gap-2 text-xs tabular">
                  <span className={cn(c.score > 0 ? "text-gain" : c.score < 0 ? "text-loss" : "text-muted-foreground")}>
                    {c.score >= 0 ? "+" : ""}
                    {c.score.toFixed(2)}
                  </span>
                  <Badge variant={c.weight ? "outline" : "warn"}>weight {c.weight.toFixed(2)}</Badge>
                </span>
              </div>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{c.reason}</p>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

export function TrendCard({ a }: { a: Analysis }) {
  const t = a.indicators.trend;
  const lv = a.indicators.levels;
  const Icon = t.direction === "uptrend" ? TrendingUp : t.direction === "downtrend" ? TrendingDown : Waves;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Trend &amp; levels</CardTitle>
        <Badge variant={t.direction === "uptrend" ? "gain" : t.direction === "downtrend" ? "loss" : "secondary"}>
          <Icon /> {t.direction}
        </Badge>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-lg bg-muted/50 p-3">
            <p className="text-[11px] text-muted-foreground">Regression move ({t.lookback_bars} bars)</p>
            <p className="font-semibold tabular">{formatPct(t.regression_move_pct, 1)}</p>
          </div>
          <div className="rounded-lg bg-muted/50 p-3">
            <p className="text-[11px] text-muted-foreground">Fit quality (R²)</p>
            <p className="font-semibold tabular">{t.r_squared.toFixed(2)}</p>
          </div>
        </div>
        <div className="flex flex-wrap gap-2 text-xs">
          <Badge variant={t.above_sma_50 ? "gain" : "loss"}>{t.above_sma_50 ? "Above" : "Below"} SMA50</Badge>
          <Badge variant={t.above_sma_200 ? "gain" : "loss"}>{t.above_sma_200 ? "Above" : "Below"} SMA200</Badge>
        </div>
        <div className="grid grid-cols-2 gap-4 text-xs">
          <div>
            <p className="mb-1.5 font-medium text-loss">Resistance</p>
            {lv.resistances.length ? lv.resistances.map((r) => (
              <p key={r.price} className="flex justify-between tabular"><span>{formatPrice(r.price)}</span><span className="text-muted-foreground">{r.touches}× touched</span></p>
            )) : <p className="text-muted-foreground">None detected</p>}
          </div>
          <div>
            <p className="mb-1.5 font-medium text-gain">Support</p>
            {lv.supports.length ? lv.supports.map((s) => (
              <p key={s.price} className="flex justify-between tabular"><span>{formatPrice(s.price)}</span><span className="text-muted-foreground">{s.touches}× touched</span></p>
            )) : <p className="text-muted-foreground">None detected</p>}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export function PatternsCard({ a }: { a: Analysis }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Detected patterns</CardTitle>
        <Badge variant="outline">{a.patterns.length}</Badge>
      </CardHeader>
      <CardContent>
        {a.patterns.length === 0 ? (
          <EmptyState icon={Shapes} title="No notable patterns" description="No rule-based pattern fired on the latest closed bars." className="py-6" />
        ) : (
          <ul className="space-y-2.5">
            {a.patterns.map((p, i) => (
              <li key={`${p.name}-${i}`} className="flex gap-3">
                <span className={cn("mt-1.5 size-2 shrink-0 rounded-full", p.bias === "bullish" ? "bg-gain" : p.bias === "bearish" ? "bg-loss" : "bg-warn")} />
                <div>
                  <p className="text-sm font-medium">
                    {p.name} <span className="text-xs font-normal text-muted-foreground">· {p.bias}{p.time ? ` · ${formatDateTime(p.time)}` : ""}</span>
                  </p>
                  <p className="text-xs text-muted-foreground">{p.description}</p>
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

export function MlCard({ a }: { a: Analysis }) {
  const ml = a.ml;
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle className="flex items-center gap-1.5">
            <Cpu className="size-4 text-primary" /> ML direction estimate
          </CardTitle>
          <CardDescription>Logistic regression, walk-forward validated</CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {!ml.available ? (
          <p className="text-sm text-muted-foreground">{ml.reason}</p>
        ) : (
          <>
            <div className="grid grid-cols-3 gap-2 text-center">
              <div className="rounded-lg bg-muted/50 p-2.5">
                <p className="text-[11px] text-muted-foreground">P(up, {ml.horizon_bars} bars)</p>
                <p className="text-lg font-semibold tabular">{((ml.prob_up ?? 0) * 100).toFixed(0)}%</p>
              </div>
              <div className="rounded-lg bg-muted/50 p-2.5">
                <p className="text-[11px] text-muted-foreground">Out-of-sample acc.</p>
                <p className="text-lg font-semibold tabular">{((ml.oos_accuracy ?? 0) * 100).toFixed(1)}%</p>
              </div>
              <div className="rounded-lg bg-muted/50 p-2.5">
                <p className="text-[11px] text-muted-foreground">Naive baseline</p>
                <p className="text-lg font-semibold tabular">{((ml.baseline_accuracy ?? 0) * 100).toFixed(1)}%</p>
              </div>
            </div>
            <p className={cn("flex items-start gap-1.5 text-xs", (ml.skill ?? 0) > 0.02 ? "text-gain" : "text-warn")}>
              <Info className="mt-0.5 size-3.5 shrink-0" />
              {(ml.skill ?? 0) > 0.02
                ? `Beat the baseline by ${((ml.skill ?? 0) * 100).toFixed(1)} pts on ${ml.n_test} held-out bars, so it contributes to the score.`
                : "No meaningful edge over the baseline on held-out data — excluded from the signal score."}
            </p>
            {ml.top_features?.length ? (
              <div>
                <p className="mb-1.5 text-xs font-medium">Largest feature contributions (log-odds)</p>
                <ul className="space-y-1 text-xs">
                  {ml.top_features.map((f) => (
                    <li key={f.feature} className="flex justify-between tabular">
                      <span className="text-muted-foreground">{f.feature}</span>
                      <span className={f.contribution >= 0 ? "text-gain" : "text-loss"}>{f.contribution >= 0 ? "+" : ""}{f.contribution.toFixed(3)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </>
        )}
        <p className="text-[11px] text-muted-foreground">{ml.label}</p>
      </CardContent>
    </Card>
  );
}

const RISK_STYLE: Record<Risk["level"], string> = {
  high: "border-loss/30 bg-loss-soft text-loss",
  medium: "border-warn/30 bg-warn-soft text-warn",
  low: "border-border bg-muted/40 text-muted-foreground",
  info: "border-info/25 bg-info-soft text-info",
};

export function RisksCard({ a }: { a: Analysis }) {
  const risks = a.signal?.risks ?? [];
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5">
          <AlertTriangle className="size-4 text-warn" /> Risks behind this analysis
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ul className="space-y-2">
          {risks.map((r) => (
            <li key={r.title} className={cn("rounded-lg border px-3 py-2", RISK_STYLE[r.level])}>
              <p className="text-xs font-semibold">{r.title} <span className="font-normal uppercase opacity-70">· {r.level}</span></p>
              <p className="mt-0.5 text-xs opacity-90">{r.detail}</p>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

export function NarrativeCard({ a }: { a: Analysis }) {
  const isLlm = a.narrative_source.startsWith("openai");
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Market summary</CardTitle>
          <CardDescription>{isLlm ? "Written by an LLM using only the computed data above" : "Deterministic summary of computed indicators"}</CardDescription>
        </div>
        <Badge variant={isLlm ? "default" : "outline"}>{isLlm ? a.narrative_source.replace("openai:", "AI · ") : "Rule-based"}</Badge>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="space-y-3 text-sm leading-relaxed whitespace-pre-line text-foreground/90">{a.narrative}</div>
        <Disclaimer>{a.disclaimer}</Disclaimer>
      </CardContent>
    </Card>
  );
}
