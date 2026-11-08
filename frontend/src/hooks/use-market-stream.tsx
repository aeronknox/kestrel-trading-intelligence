"use client";

import { createContext, useContext, useEffect, useRef, useState } from "react";

import type { DataMeta, Ticker } from "@/types/api";

type Status = "connecting" | "live" | "offline";

interface StreamState {
  tickers: Record<string, Ticker>;
  status: Status;
  /** `streaming` is true when prices come from the exchange's live feed, false when polled. */
  meta: (Pick<DataMeta, "source" | "is_sample" | "attribution"> & { streaming?: boolean }) | null;
  lastUpdate: number | null;
}

const MarketStreamContext = createContext<StreamState>({ tickers: {}, status: "connecting", meta: null, lastUpdate: null });

function wsUrl(): string {
  const configured = process.env.NEXT_PUBLIC_WS_URL;
  if (configured) return configured;
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.hostname}:8000/api/v1/ws/market`;
}

/** One shared WebSocket for live tickers, with exponential-backoff reconnect. */
export function MarketStreamProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<StreamState>({ tickers: {}, status: "connecting", meta: null, lastUpdate: null });
  const retry = useRef(0);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let closed = false;

    const connect = () => {
      setState((s) => ({ ...s, status: "connecting" }));
      try {
        ws = new WebSocket(wsUrl());
      } catch {
        schedule();
        return;
      }
      ws.onopen = () => {
        retry.current = 0;
        setState((s) => ({ ...s, status: "live" }));
      };
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data as string) as { type: string; data?: Ticker[]; meta?: StreamState["meta"] };
          if (msg.type !== "tickers" || !msg.data) return;
          setState((s) => {
            const tickers = { ...s.tickers };
            for (const t of msg.data!) tickers[t.symbol] = t;
            return { tickers, status: "live", meta: msg.meta ?? s.meta, lastUpdate: Date.now() };
          });
        } catch {
          /* ignore malformed frames */
        }
      };
      ws.onclose = () => {
        if (!closed) schedule();
      };
      ws.onerror = () => ws?.close();
    };

    const schedule = () => {
      setState((s) => ({ ...s, status: "offline" }));
      const delay = Math.min(30_000, 1000 * 2 ** retry.current++);
      timer = setTimeout(connect, delay);
    };

    connect();
    return () => {
      closed = true;
      if (timer) clearTimeout(timer);
      ws?.close();
    };
  }, []);

  return <MarketStreamContext.Provider value={state}>{children}</MarketStreamContext.Provider>;
}

export function useMarketStream() {
  return useContext(MarketStreamContext);
}

/** Live ticker for a symbol, falling back to a REST-fetched one. */
export function useLiveTicker(symbol: string, fallback?: Ticker | null): Ticker | null {
  const { tickers } = useMarketStream();
  return tickers[symbol] ?? fallback ?? null;
}
