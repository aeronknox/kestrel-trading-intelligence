"use client";

import { ArrowDown, ArrowUp, ArrowUpDown, Star } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type ReactNode, useState } from "react";

import { AssetIcon, Change } from "@/components/common/finance";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { useMarketStream } from "@/hooks/use-market-stream";
import { formatCompact, formatPrice, formatUsd } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { AssetWithTicker } from "@/types/api";

import { nextSort, type Sort, type SortKey, sortRows } from "./market-sort";

/** A header that sorts the table (full tables only); announces its state to screen readers. */
function SortHeader({ k, sort, onSort, className, children }: { k: SortKey; sort: Sort; onSort: (k: SortKey) => void; className?: string; children: ReactNode }) {
  const active = sort?.key === k ? sort.dir : null;
  const Icon = active === "asc" ? ArrowUp : active === "desc" ? ArrowDown : ArrowUpDown;
  return (
    <TH className={className} aria-sort={active === "asc" ? "ascending" : active === "desc" ? "descending" : "none"}>
      <button type="button" onClick={() => onSort(k)} className={cn("inline-flex items-center gap-1 hover:text-foreground", active && "text-foreground")}>
        {children}
        <Icon className="size-3" aria-hidden />
      </button>
    </TH>
  );
}

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
  const [sort, setSort] = useState<Sort>(null);
  const onSort = (k: SortKey) => setSort((s) => nextSort(s, k));
  const shown = compact ? rows : sortRows(rows, sort, tickers);
  return (
    <Table>
      <THead>
        <TR className="hover:bg-transparent">
          {onToggleWatch && <TH className="w-8" />}
          {compact ? (
            <>
              <TH>Asset</TH>
              <TH className="text-right">Price</TH>
              <TH className="text-right">24h</TH>
            </>
          ) : (
            <>
              <SortHeader k="name" sort={sort} onSort={onSort}>Asset</SortHeader>
              <SortHeader k="price" sort={sort} onSort={onSort} className="text-right">Price</SortHeader>
              <SortHeader k="change" sort={sort} onSort={onSort} className="text-right">24h</SortHeader>
              <TH className="hidden text-right md:table-cell">24h High</TH>
              <TH className="hidden text-right md:table-cell">24h Low</TH>
              <SortHeader k="volume" sort={sort} onSort={onSort} className="hidden text-right sm:table-cell">Volume (USD)</SortHeader>
            </>
          )}
        </TR>
      </THead>
      <TBody>
        {shown.map(({ asset, ticker: rest }) => {
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
              {!compact && (
                <TD className="hidden text-right text-muted-foreground sm:table-cell" title={t?.volume_24h != null ? `${formatCompact(t.volume_24h)} ${asset.base_currency}` : undefined}>
                  {t?.volume_24h != null ? formatUsd(t.volume_24h * t.price, { compact: true }) : "—"}
                </TD>
              )}
            </TR>
          );
        })}
      </TBody>
    </Table>
  );
}
