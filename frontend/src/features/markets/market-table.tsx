"use client";

import { Star } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { AssetIcon, Change } from "@/components/common/finance";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { useMarketStream } from "@/hooks/use-market-stream";
import { formatCompact, formatPrice } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { AssetWithTicker } from "@/types/api";

/** Market table whose prices update live from the WebSocket stream. */
export function MarketTable({
  rows,
  compact = false,
  watchlist,
  onToggleWatch,
}: {
  rows: AssetWithTicker[];
  compact?: boolean;
  watchlist?: Set<string>;
  onToggleWatch?: (symbol: string, watched: boolean) => void;
}) {
  const { tickers } = useMarketStream();
  const router = useRouter();
  return (
    <Table>
      <THead>
        <TR className="hover:bg-transparent">
          {onToggleWatch && <TH className="w-8" />}
          <TH>Asset</TH>
          <TH className="text-right">Price</TH>
          <TH className="text-right">24h</TH>
          {!compact && <TH className="hidden text-right md:table-cell">24h High</TH>}
          {!compact && <TH className="hidden text-right md:table-cell">24h Low</TH>}
          {!compact && <TH className="hidden text-right sm:table-cell">Volume (base)</TH>}
        </TR>
      </THead>
      <TBody>
        {rows.map(({ asset, ticker: rest }) => {
          const t = tickers[asset.symbol] ?? rest;
          const watched = watchlist?.has(asset.symbol) ?? false;
          return (
            <TR key={asset.id} className="cursor-pointer" onClick={() => router.push(`/markets/${asset.symbol}`)}>
              {onToggleWatch && (
                <TD className="pr-0">
                  <button
                    aria-label={watched ? `Remove ${asset.symbol} from watchlist` : `Add ${asset.symbol} to watchlist`}
                    onClick={(e) => {
                      e.stopPropagation();
                      onToggleWatch(asset.symbol, watched);
                    }}
                    className="rounded p-1 text-muted-foreground hover:text-warn"
                  >
                    <Star className={cn("size-3.5", watched && "fill-warn text-warn")} />
                  </button>
                </TD>
              )}
              <TD>
                <Link href={`/markets/${asset.symbol}`} className="flex items-center gap-2.5" onClick={(e) => e.stopPropagation()}>
                  <AssetIcon symbol={asset.symbol} />
                  <span className="min-w-0">
                    <span className="block font-medium">{asset.base_currency}</span>
                    <span className="block truncate text-xs text-muted-foreground">{asset.name}</span>
                  </span>
                </Link>
              </TD>
              <TD className="text-right font-medium">{t ? formatPrice(t.price, true) : <span className="text-muted-foreground">unavailable</span>}</TD>
              <TD className="text-right">
                <Change value={t?.change_pct_24h} />
              </TD>
              {!compact && <TD className="hidden text-right text-muted-foreground md:table-cell">{formatPrice(t?.high_24h)}</TD>}
              {!compact && <TD className="hidden text-right text-muted-foreground md:table-cell">{formatPrice(t?.low_24h)}</TD>}
              {!compact && <TD className="hidden text-right text-muted-foreground sm:table-cell">{formatCompact(t?.volume_24h)}</TD>}
            </TR>
          );
        })}
      </TBody>
    </Table>
  );
}
