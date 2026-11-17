"use client";

import Link from "next/link";

import { useMarketStream } from "@/hooks/use-market-stream";
import { formatPct, formatPrice, isNum } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { AssetWithTicker } from "@/types/api";

/** Moves this big or bigger get the strongest tint. */
const FULL_TINT_PCT = 10;

/** Every asset as a tile tinted by its live 24h change: green up, red down, stronger for bigger moves. */
export function MarketHeatmap({ rows }: { rows: AssetWithTicker[] }) {
  const { tickers } = useMarketStream();
  const tiles = rows
    .map(({ asset, ticker }) => ({ asset, t: tickers[asset.symbol] ?? ticker }))
    .sort((a, b) => (b.t?.change_pct_24h ?? -Infinity) - (a.t?.change_pct_24h ?? -Infinity));
  return (
    <ul className="grid grid-cols-2 gap-2 px-1 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-6" aria-label="24h change by asset, biggest gain first">
      {tiles.map(({ asset, t }) => {
        const chg = t?.change_pct_24h;
        const share = isNum(chg) ? Math.min(Math.abs(chg) / FULL_TINT_PCT, 1) : 0;
        const color = isNum(chg) && chg < 0 ? "var(--color-loss)" : "var(--color-gain)";
        return (
          <li key={asset.id}>
            <Link
              href={`/markets/${asset.symbol}`}
              className={cn("block rounded-lg border border-border/60 p-3 transition-colors hover:border-primary/50", !isNum(chg) && "bg-muted/40")}
              style={isNum(chg) && chg !== 0 ? { backgroundColor: `color-mix(in oklab, ${color} ${Math.round(8 + share * 27)}%, transparent)` } : undefined}
            >
              <span className="block text-sm font-semibold">{asset.base_currency}</span>
              <span className="block text-lg font-semibold tabular">
                {isNum(chg) ? formatPct(chg) : "—"}
                <span className="sr-only"> 24h change,</span>
              </span>
              <span className="block truncate text-xs tabular">{t ? formatPrice(t.price, true) : "unavailable"}</span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
