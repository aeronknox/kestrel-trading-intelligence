"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/services/api";

export function useWatchlist() {
  const qc = useQueryClient();
  const query = useQuery({ queryKey: ["watchlist"], queryFn: api.watchlist.get });
  const toggle = useMutation({
    mutationFn: ({ symbol, watched }: { symbol: string; watched: boolean }) =>
      watched ? api.watchlist.remove(symbol) : api.watchlist.add(symbol),
    onSuccess: (wl, { symbol, watched }) => {
      qc.setQueryData(["watchlist"], wl);
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      toast.success(watched ? `${symbol} removed from watchlist` : `${symbol} added to watchlist`);
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const symbols = new Set(query.data?.items.map((i) => i.asset.symbol) ?? []);
  return { query, symbols, toggle: (symbol: string, watched: boolean) => toggle.mutate({ symbol, watched }) };
}
