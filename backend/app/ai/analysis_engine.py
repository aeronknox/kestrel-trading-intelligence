"""Orchestrates a full analysis run: data → indicators → patterns → ML → signal → narrative."""

from datetime import UTC, datetime

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.llm import narrate_analysis, rule_based_narrative
from app.ai.ml_model import predict_direction
from app.ai.patterns import classify_trend, detect_patterns, support_resistance
from app.ai.signals import assess_risks, combine, score_components
from app.core.exceptions import ValidationFailedError
from app.indicators.technical import add_standard_indicators, candles_to_frame, latest_snapshot
from app.market_data.service import MarketDataService
from app.models.ai import AIAnalysisResult, TradingSignal
from app.models.enums import SignalAction
from app.models.market import Asset

MIN_BARS = 60
ANALYSIS_BARS = 600


def compute_analysis(df: pd.DataFrame, *, is_sample: bool = False, stale: bool = False) -> dict:
    """Pure computation over a closed-candle frame (no I/O). Used by the API and tests."""
    if len(df) < MIN_BARS:
        raise ValidationFailedError(f"Need at least {MIN_BARS} closed candles for analysis, got {len(df)}")
    enriched = add_standard_indicators(df)
    ind = latest_snapshot(enriched)
    trend = classify_trend(enriched)
    levels = support_resistance(enriched)
    patterns = detect_patterns(enriched)
    ml = predict_direction(enriched)
    components = score_components(ind, trend, patterns, ml)
    action, score, confidence = combine(components)
    risks = assess_risks(ind, components, patterns, ml, levels, is_sample=is_sample, stale=stale)
    return {
        "indicators": ind,
        "trend": trend,
        "levels": levels,
        "patterns": [p.to_dict() for p in patterns],
        "ml": ml,
        "signal": {
            "action": action,
            "score": score,
            "confidence": confidence,
            "components": [c.to_dict() for c in components],
        },
        "risks": risks,
        "data_as_of": pd.Timestamp(enriched["ts"].iloc[-1]).to_pydatetime(),
        "bars_analyzed": len(enriched),
    }


def build_summary(symbol: str, timeframe: str, result: dict) -> str:
    sig = result["signal"]
    return (
        f"{symbol} {timeframe}: {result['trend']['direction']}, signal {sig['action'].upper()} "
        f"(score {sig['score']:+.2f}, confidence {sig['confidence']:.0f}/100)."
    )


async def run_analysis(
    session: AsyncSession, asset: Asset, timeframe: str, user_id: int | None = None, *, narrate: bool = True
) -> AIAnalysisResult:
    """Run and persist an analysis. `narrate=False` skips the (optional, paid) LLM call,
    e.g. when the assistant already phrases the result itself."""
    market = MarketDataService(session)
    series = await market.get_candles(asset, timeframe, limit=ANALYSIS_BARS)
    closed = series.closed()
    df = candles_to_frame(closed)
    result = compute_analysis(df, is_sample=series.is_sample, stale=series.stale)

    facts = {
        "symbol": asset.symbol,
        "timeframe": timeframe,
        "data_source": series.attribution,
        "data_as_of": result["data_as_of"].isoformat(),
        "indicators": result["indicators"],
        "trend": result["trend"],
        "levels": result["levels"],
        "patterns": result["patterns"],
        "ml": {k: v for k, v in result["ml"].items() if k != "top_features"},
        "signal": result["signal"],
        "risks": result["risks"],
    }
    if narrate:
        narrative, narrative_source = await narrate_analysis(facts)
    else:
        narrative, narrative_source = rule_based_narrative(facts), "rule_based"

    analysis = AIAnalysisResult(
        user_id=user_id,
        asset_id=asset.id,
        timeframe=timeframe,
        trend=result["trend"]["direction"],
        summary=build_summary(asset.symbol, timeframe, result),
        narrative=narrative,
        narrative_source=narrative_source,
        indicators={"latest": result["indicators"], "trend": result["trend"], "levels": result["levels"]},
        patterns=result["patterns"],
        ml=result["ml"],
        data_source=series.source + (":stale" if series.stale else ""),
        data_as_of=result["data_as_of"],
        created_at=datetime.now(UTC),
    )
    session.add(analysis)
    await session.flush()
    signal = TradingSignal(
        analysis_id=analysis.id,
        asset_id=asset.id,
        timeframe=timeframe,
        action=SignalAction(result["signal"]["action"]),
        score=result["signal"]["score"],
        confidence=result["signal"]["confidence"],
        price_at_signal=result["indicators"]["close"],
        components=result["signal"]["components"],
        risks=result["risks"],
    )
    session.add(signal)
    await session.flush()
    await session.refresh(analysis, attribute_names=["signal", "asset"])
    return analysis


async def latest_analysis(session: AsyncSession, asset_id: int, timeframe: str | None = None) -> AIAnalysisResult | None:
    stmt = select(AIAnalysisResult).where(AIAnalysisResult.asset_id == asset_id)
    if timeframe:
        stmt = stmt.where(AIAnalysisResult.timeframe == timeframe)
    return await session.scalar(stmt.order_by(AIAnalysisResult.created_at.desc()).limit(1))
