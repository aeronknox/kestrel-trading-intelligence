"use client";

import { useQuery } from "@tanstack/react-query";
import { Search, Star } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

import { DataSource } from "@/components/common/finance";
import { EmptyState, ErrorState, LoadingRows } from "@/components/common/states";
import { PageHeader } from "@/components/layout/page-header";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Segmented, SegmentedItem } from "@/components/ui/segmented";
import { Input } from "@/components/ui/primitives";
import { api } from "@/services/api";

import { AddAssetDialog } from "./add-asset-dialog";
import { MarketHeatmap } from "./market-heatmap";
import { MarketTable } from "./market-table";
import { useWatchlist } from "./use-watchlist";

type View = "table" | "heatmap";

export function MarketsView() {
  const overview = useQuery({ queryKey: ["market-overview"], queryFn: api.market.overview, refetchInterval: 60_000 });
  const { symbols: watched, toggle } = useWatchlist();
  const [tab, setTab] = useState<"all" | "watchlist">("all");
  const [filter, setFilter] = useState("");
  // The view is in the URL (?view=heatmap), so it survives a reload and can be linked to.
  const params = useSearchParams();
  const router = useRouter();
  const view: View = params.get("view") === "heatmap" ? "heatmap" : "table";
  const setView = (v: View) => router.replace(v === "heatmap" ? "/markets?view=heatmap" : "/markets", { scroll: false });

  const rows = useMemo(() => {
    let r = overview.data?.assets ?? [];
    if (tab === "watchlist") r = r.filter((a) => watched.has(a.asset.symbol));
    const f = filter.trim().toLowerCase();
    if (f) r = r.filter((a) => a.asset.symbol.toLowerCase().includes(f) || a.asset.name.toLowerCase().includes(f));
    return r;
  }, [overview.data, tab, watched, filter]);

  return (
    <>
      <PageHeader title="Markets" description="Live crypto prices and 24h statistics. Stocks and forex providers can be added via the provider interface." actions={<AddAssetDialog />} />
      <Card>
        <CardHeader className="flex-col gap-3 sm:flex-row sm:items-center">
          <Segmented value={tab} onValueChange={(v) => setTab(v as typeof tab)} label="Show">
              <SegmentedItem value="all">All assets</SegmentedItem>
              <SegmentedItem value="watchlist">
                <Star className="size-3" /> Watchlist ({watched.size})
              </SegmentedItem>
            </Segmented>
          <div className="flex w-full gap-2 sm:w-auto">
            <div className="relative flex-1 sm:w-56">
              <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter…" className="h-8 pl-8 text-xs" />
            </div>
            <Segmented value={view} onValueChange={(v) => setView(v as View)} label="View">
                <SegmentedItem value="table">Table</SegmentedItem>
                <SegmentedItem value="heatmap">Heatmap</SegmentedItem>
              </Segmented>
          </div>
        </CardHeader>
        <CardContent className="px-2">
          {overview.isLoading ? (
            <LoadingRows rows={8} className="px-3" />
          ) : overview.error ? (
            <ErrorState error={overview.error} onRetry={() => overview.refetch()} />
          ) : rows.length === 0 ? (
            <EmptyState icon={Star} title={tab === "watchlist" ? "No assets on your watchlist" : "No assets match"} description={tab === "watchlist" ? "Click the star next to any asset to add it." : undefined} />
          ) : (
            view === "heatmap" ? <MarketHeatmap rows={rows} /> : <MarketTable rows={rows} watchlist={watched} onToggleWatch={toggle} />
          )}
          <DataSource meta={overview.data?.meta} className="px-3 pt-3" />
        </CardContent>
      </Card>
    </>
  );
}
