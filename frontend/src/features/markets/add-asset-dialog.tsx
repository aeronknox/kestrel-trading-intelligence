"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Plus, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { AssetIcon } from "@/components/common/finance";
import { ErrorState, LoadingRows } from "@/components/common/states";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/overlays";
import { Input } from "@/components/ui/primitives";
import { api } from "@/services/api";

function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export function AddAssetDialog() {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const term = useDebounced(q.trim());
  const qc = useQueryClient();
  const catalog = useQuery({ queryKey: ["catalog", term], queryFn: () => api.market.catalog(term), enabled: open && term.length >= 2 });
  const track = useMutation({
    mutationFn: api.market.track,
    onSuccess: (asset) => {
      toast.success(`Now tracking ${asset.symbol}`);
      qc.invalidateQueries({ queryKey: ["market-overview"] });
      qc.invalidateQueries({ queryKey: ["assets"] });
      qc.invalidateQueries({ queryKey: ["catalog"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" variant="outline">
          <Plus /> Track asset
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Track a new asset</DialogTitle>
          <DialogDescription>Search the market data provider&apos;s product catalog.</DialogDescription>
        </DialogHeader>
        <div className="relative">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. ATOM, AAVE, UNI…" className="pl-8" />
        </div>
        <div className="max-h-80 min-h-24 overflow-y-auto scrollbar-thin">
          {term.length < 2 ? (
            <p className="py-6 text-center text-xs text-muted-foreground">Type at least two characters.</p>
          ) : catalog.isLoading ? (
            <LoadingRows rows={4} />
          ) : catalog.error ? (
            <ErrorState error={catalog.error} onRetry={() => catalog.refetch()} />
          ) : catalog.data?.length ? (
            <ul className="divide-y divide-border">
              {catalog.data.map((p) => (
                <li key={p.symbol} className="flex items-center gap-3 py-2">
                  <AssetIcon symbol={p.symbol} />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium">{p.symbol}</p>
                    <p className="truncate text-xs text-muted-foreground">{p.name}</p>
                  </div>
                  {p.tracked ? (
                    <span className="flex items-center gap-1 text-xs text-gain">
                      <Check className="size-3.5" /> Tracked
                    </span>
                  ) : (
                    <Button size="sm" variant="secondary" loading={track.isPending && track.variables === p.symbol} onClick={() => track.mutate(p.symbol)}>
                      Track
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p className="py-6 text-center text-xs text-muted-foreground">No products match “{term}”.</p>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
