"use client";

import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  CrosshairMode,
  HistogramSeries,
  type IChartApi,
  type ISeriesApi,
  LineSeries,
  LineStyle,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef } from "react";

import { useTheme } from "@/hooks/use-theme";
import type { Candle, Point, Timeframe } from "@/types/api";

import { chartPalette } from "./colors";

export type Overlay = "sma_20" | "sma_50" | "sma_200" | "bb" | "volume" | "rsi" | "macd";

export interface PriceLevel {
  price: number;
  label: string;
  kind: "support" | "resistance";
}

export interface ChartMarker {
  time: number;
  position: "aboveBar" | "belowBar";
  shape: "arrowUp" | "arrowDown" | "circle";
  color: "gain" | "loss" | "neutral";
  text: string;
}

const TF_SECONDS: Record<Timeframe, number> = { "1m": 60, "5m": 300, "15m": 900, "1h": 3600, "6h": 21600, "1d": 86400 };

const toPoints = (pts: Point[] | undefined) => (pts ?? []).map((p) => ({ time: p.time as UTCTimestamp, value: p.value }));

export function PriceChart({
  candles,
  indicators,
  overlays,
  timeframe,
  livePrice,
  levels = [],
  markers = [],
  height = 460,
}: {
  candles: Candle[];
  indicators: Record<string, Point[]>;
  overlays: Set<Overlay>;
  timeframe: Timeframe;
  livePrice?: number | null;
  levels?: PriceLevel[];
  markers?: ChartMarker[];
  height?: number;
}) {
  const container = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const lastBar = useRef<Candle | null>(null);
  const { theme } = useTheme();

  useEffect(() => {
    if (!container.current || candles.length === 0) return;
    const c = chartPalette();
    const chart = createChart(container.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: c.background },
        textColor: c.text,
        fontFamily: "var(--font-inter), ui-sans-serif, system-ui",
        fontSize: 11,
        attributionLogo: true,
        panes: { separatorColor: c.border, separatorHoverColor: c.grid, enableResize: true },
      },
      grid: { vertLines: { color: c.grid }, horzLines: { color: c.grid } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: c.border },
      timeScale: { borderColor: c.border, timeVisible: TF_SECONDS[timeframe] < 86400, secondsVisible: false },
    });
    chartRef.current = chart;

    const series = chart.addSeries(CandlestickSeries, {
      upColor: c.gain,
      downColor: c.loss,
      borderVisible: false,
      wickUpColor: c.gain,
      wickDownColor: c.loss,
      priceLineVisible: true,
    });
    series.setData(candles.map((k) => ({ time: k.time as UTCTimestamp, open: k.open, high: k.high, low: k.low, close: k.close })));
    candleRef.current = series;
    lastBar.current = candles[candles.length - 1] ?? null;

    for (const lv of levels) {
      series.createPriceLine({
        price: lv.price,
        color: lv.kind === "support" ? c.gainSoft : c.lossSoft,
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: lv.label,
      });
    }
    if (markers.length) {
      const colorOf = { gain: c.gain, loss: c.loss, neutral: c.c3 };
      const m: SeriesMarker<Time>[] = markers
        .slice()
        .sort((a, b) => a.time - b.time)
        .map((mk) => ({ time: mk.time as UTCTimestamp, position: mk.position, shape: mk.shape, color: colorOf[mk.color], text: mk.text }));
      createSeriesMarkers(series, m);
    }

    const line = (key: string, color: string, width: 1 | 2 = 1, pane = 0, style: LineStyle = LineStyle.Solid) => {
      const s = chart.addSeries(LineSeries, { color, lineWidth: width, lineStyle: style, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false }, pane);
      s.setData(toPoints(indicators[key]));
      return s;
    };

    if (overlays.has("sma_20")) line("sma_20", c.c3);
    if (overlays.has("sma_50")) line("sma_50", c.c1, 2);
    if (overlays.has("sma_200")) line("sma_200", c.c4, 2);
    if (overlays.has("bb")) {
      line("bb_upper", c.band, 1, 0, LineStyle.Dotted);
      line("bb_middle", c.muted, 1, 0, LineStyle.Dotted);
      line("bb_lower", c.band, 1, 0, LineStyle.Dotted);
    }
    if (overlays.has("volume")) {
      const vol = chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "vol", lastValueVisible: false, priceLineVisible: false });
      vol.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
      vol.setData(candles.map((k) => ({ time: k.time as UTCTimestamp, value: k.volume, color: k.close >= k.open ? c.gainSoft : c.lossSoft })));
    }

    let pane = 1;
    if (overlays.has("rsi")) {
      const rsi = line("rsi_14", c.c2, 1, pane);
      rsi.createPriceLine({ price: 70, color: c.lossSoft, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false, title: "" });
      rsi.createPriceLine({ price: 30, color: c.gainSoft, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false, title: "" });
      pane++;
    }
    if (overlays.has("macd")) {
      const hist = chart.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false }, pane);
      hist.setData((indicators.macd_hist ?? []).map((p) => ({ time: p.time as UTCTimestamp, value: p.value, color: p.value >= 0 ? c.gainSoft : c.lossSoft })));
      line("macd", c.c1, 1, pane);
      line("macd_signal", c.c3, 1, pane);
      pane++;
    }
    const panes = chart.panes();
    for (let i = 1; i < panes.length; i++) panes[i]?.setHeight(110);

    chart.timeScale().fitContent();
    return () => {
      chart.remove();
      chartRef.current = null;
      candleRef.current = null;
    };
  }, [candles, indicators, overlays, timeframe, theme, levels, markers]);

  // Stream the live price into the forming bar without rebuilding the chart.
  useEffect(() => {
    const bar = lastBar.current;
    if (!livePrice || !bar || !candleRef.current) return;
    const nowSec = Date.now() / 1000;
    if (nowSec >= bar.time + TF_SECONDS[timeframe]) return; // bar closed; next refetch adds a new one
    const updated = { ...bar, high: Math.max(bar.high, livePrice), low: Math.min(bar.low, livePrice), close: livePrice };
    lastBar.current = updated;
    candleRef.current.update({ time: bar.time as UTCTimestamp, open: updated.open, high: updated.high, low: updated.low, close: updated.close });
  }, [livePrice, timeframe]);

  return <div ref={container} style={{ height }} className="w-full" />;
}
