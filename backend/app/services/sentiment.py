"""Market sentiment computed from real market data (plus the public Fear & Greed index)."""

import asyncio

from app.core.exceptions import AppError
from app.indicators.technical import add_standard_indicators, candles_to_frame
from app.market_data.service import MarketDataService


def _label(score: float | None) -> str:
    if score is None:
        return "Unavailable"
    if score >= 65:
        return "Risk-on"
    if score >= 55:
        return "Mildly bullish"
    if score > 45:
        return "Neutral"
    if score > 35:
        return "Mildly bearish"
    return "Risk-off"


async def compute_sentiment(market: MarketDataService) -> dict:
    cached = await market.cache.get_json(f"sentiment:breadth:{market.provider.name}")
    assets = await market.list_assets()
    if cached is None:
        async def one(asset):  # type: ignore[no-untyped-def]
            try:
                series = await market.get_candles(asset, "1d", limit=80)
            except AppError:
                return None
            df = add_standard_indicators(candles_to_frame(series.closed()))
            last = df.iloc[-1]
            return {
                "above_sma50": bool(last["close"] > last["sma_50"]) if last["sma_50"] == last["sma_50"] else None,
                "rsi": float(last["rsi_14"]) if last["rsi_14"] == last["rsi_14"] else None,
            }

        rows = [r for r in await asyncio.gather(*(one(a) for a in assets)) if r]
        flags = [r["above_sma50"] for r in rows if r["above_sma50"] is not None]
        rsis = [r["rsi"] for r in rows if r["rsi"] is not None]
        cached = {
            "breadth": sum(flags) / len(flags) * 100 if flags else None,
            "avg_rsi": sum(rsis) / len(rsis) if rsis else None,
        }
        await market.cache.set_json(f"sentiment:breadth:{market.provider.name}", cached, ttl=600)

    tickers = await market.get_tickers(assets)
    changes = [t.change_pct_24h for t in tickers.values() if t]
    fng = await market.get_fear_greed()
    parts = [p for p in (cached["breadth"], cached["avg_rsi"], fng["value"] if fng else None) if p is not None]
    composite = sum(parts) / len(parts) if parts else None
    return {
        "fear_greed": fng,
        "breadth_above_sma50_pct": cached["breadth"],
        "avg_rsi": cached["avg_rsi"],
        "advancers": sum(1 for c in changes if c > 0),
        "decliners": sum(1 for c in changes if c < 0),
        "avg_change_pct_24h": sum(changes) / len(changes) if changes else None,
        "label": _label(composite),
    }
