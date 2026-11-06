"""AI research assistant grounded in platform data.

With an OpenAI key: the model answers via tool-calling — every number it may cite
comes back from a tool that reads real application data (market data provider,
stored analyses, the user's paper portfolio, backtests).

Without a key: a deterministic intent router calls the same tools and formats
the results. Either way, missing data is reported as unavailable, never guessed.
"""

import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.analysis_engine import run_analysis
from app.ai.llm import GROUNDING_RULES, chat_completion, get_client
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.market_data.service import MarketDataService
from app.models.ai import AIAnalysisResult, TradingSignal
from app.models.backtest import BacktestSession
from app.models.market import Asset
from app.models.user import User
from app.paper_trading.service import PaperTradingService

logger = get_logger(__name__)

ANALYSIS_REUSE_WINDOW = timedelta(minutes=15)
MAX_TOOL_ROUNDS = 4

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_market_overview",
            "description": "Live 24h price statistics for all tracked assets.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_asset_analysis",
            "description": "Technical analysis for one asset: trend, indicators, patterns, ML estimate, signal and risks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "e.g. BTC-USD"},
                    "timeframe": {"type": "string", "enum": ["15m", "1h", "6h", "1d"], "default": "1h"},
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_assets",
            "description": "Side-by-side analysis of 2-4 assets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbols": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 4},
                    "timeframe": {"type": "string", "enum": ["15m", "1h", "6h", "1d"], "default": "1h"},
                },
                "required": ["symbols"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_latest_signal",
            "description": "The most recently generated trading signal for an asset, with its scoring components.",
            "parameters": {
                "type": "object",
                "properties": {"symbol": {"type": "string"}},
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_movements",
            "description": "Price movement summary over the last N bars for an asset.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "timeframe": {"type": "string", "enum": ["5m", "15m", "1h", "6h", "1d"], "default": "1h"},
                    "bars": {"type": "integer", "minimum": 2, "maximum": 300, "default": 24},
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_portfolio",
            "description": "The user's simulated (paper) portfolio: cash, positions, P&L.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_backtests",
            "description": "The user's most recent hypothetical backtest results.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


class AssistantTools:
    def __init__(self, session: AsyncSession, user: User) -> None:
        self.session = session
        self.user = user
        self.market = MarketDataService(session)
        self.sources: set[str] = set()

    async def _asset(self, symbol: str) -> Asset:
        s = symbol.upper().strip()
        if "-" not in s:
            s = f"{s}-USD"
        return await self.market.get_asset(s)

    def _note_source(self) -> None:
        self.sources.add(self.market.provider.attribution)

    async def get_market_overview(self) -> dict:
        assets = await self.market.list_assets()
        tickers = await self.market.get_tickers(assets)
        self._note_source()
        return {
            "as_of": datetime.now(UTC).isoformat(),
            "assets": [
                {"symbol": a.symbol, "price": t.price, "change_pct_24h": round(t.change_pct_24h, 2), "volume_24h": t.volume_24h}
                if (t := tickers.get(a.symbol))
                else {"symbol": a.symbol, "price": None, "note": "price unavailable"}
                for a in assets
            ],
        }

    async def _analysis(self, symbol: str, timeframe: str) -> AIAnalysisResult:
        asset = await self._asset(symbol)
        recent = await self.session.scalar(
            select(AIAnalysisResult)
            .where(
                AIAnalysisResult.asset_id == asset.id,
                AIAnalysisResult.timeframe == timeframe,
                AIAnalysisResult.created_at >= datetime.now(UTC) - ANALYSIS_REUSE_WINDOW,
            )
            .order_by(AIAnalysisResult.created_at.desc())
            .limit(1)
        )
        self._note_source()
        # The assistant phrases results itself, so skip the nested LLM narration call.
        return recent or await run_analysis(self.session, asset, timeframe, self.user.id, narrate=False)

    @staticmethod
    def _analysis_facts(a: AIAnalysisResult) -> dict:
        latest = a.indicators.get("latest", {})
        return {
            "symbol": a.asset.symbol,
            "timeframe": a.timeframe,
            "data_as_of": a.data_as_of.isoformat(),
            "trend": a.indicators.get("trend"),
            "indicators": {k: latest.get(k) for k in ("close", "sma_50", "sma_200", "rsi_14", "macd_hist", "bb_pct_b", "atr_14")},
            "levels": a.indicators.get("levels"),
            "patterns": [{"name": p["name"], "bias": p["bias"]} for p in a.patterns],
            "ml_estimate": {k: a.ml.get(k) for k in ("available", "prob_up", "horizon_bars", "oos_accuracy", "baseline_accuracy", "reason")},
            "signal": {
                "action": a.signal.action.value,
                "score": round(a.signal.score, 3),
                "confidence": a.signal.confidence,
                "components": a.signal.components,
            }
            if a.signal
            else None,
            "risks": [r["title"] + ": " + r["detail"] for r in (a.signal.risks if a.signal else [])],
        }

    async def get_asset_analysis(self, symbol: str, timeframe: str = "1h") -> dict:
        return self._analysis_facts(await self._analysis(symbol, timeframe))

    async def compare_assets(self, symbols: list[str], timeframe: str = "1h") -> dict:
        out = []
        for s in symbols[:4]:
            try:
                f = await self.get_asset_analysis(s, timeframe)
                out.append({k: f[k] for k in ("symbol", "trend", "indicators", "signal", "data_as_of")})
            except AppError as exc:
                out.append({"symbol": s, "error": exc.message})
        return {"timeframe": timeframe, "assets": out}

    async def get_latest_signal(self, symbol: str) -> dict:
        asset = await self._asset(symbol)
        sig = await self.session.scalar(
            select(TradingSignal).where(TradingSignal.asset_id == asset.id).order_by(TradingSignal.created_at.desc()).limit(1)
        )
        if sig is None:
            return {"symbol": asset.symbol, "signal": None, "note": "No signal has been generated for this asset yet."}
        return {
            "symbol": asset.symbol,
            "timeframe": sig.timeframe,
            "generated_at": sig.created_at.isoformat(),
            "action": sig.action.value,
            "score": sig.score,
            "confidence": sig.confidence,
            "price_at_signal": sig.price_at_signal,
            "components": sig.components,
            "risks": sig.risks,
        }

    async def get_recent_movements(self, symbol: str, timeframe: str = "1h", bars: int = 24) -> dict:
        asset = await self._asset(symbol)
        bars = max(2, min(int(bars), 300))
        series = await self.market.get_candles(asset, timeframe, limit=bars)
        self._note_source()
        c = series.candles[-bars:]
        first, last = c[0], c[-1]
        return {
            "symbol": asset.symbol,
            "timeframe": timeframe,
            "bars": len(c),
            "from": first.ts.isoformat(),
            "to": last.ts.isoformat(),
            "open": first.open,
            "last": last.close,
            "change_pct": (last.close / first.open - 1) * 100,
            "high": max(x.high for x in c),
            "low": min(x.low for x in c),
            "total_volume": sum(x.volume for x in c),
            "up_bars": sum(1 for x in c if x.close > x.open),
            "down_bars": sum(1 for x in c if x.close < x.open),
            "is_sample": series.is_sample,
        }

    async def get_portfolio(self) -> dict:
        svc = PaperTradingService(self.session, self.market)
        pf = await svc.get_or_create_portfolio(self.user.id)
        s = await svc.summary(pf)
        return {
            "simulated": True,
            "equity": s["equity"],
            "cash": pf.cash_balance,
            "total_pnl": s["total_pnl"],
            "total_return_pct": s["total_return_pct"],
            "daily_pnl": s["daily_pnl"],
            "positions": [
                {
                    "symbol": v.position.asset.symbol,
                    "quantity": v.position.quantity,
                    "avg_entry_price": v.position.avg_entry_price,
                    "price": v.price,
                    "unrealized_pnl": v.unrealized_pnl,
                }
                for v in s["positions"]
            ],
        }

    async def list_backtests(self) -> dict:
        rows = (
            await self.session.scalars(
                select(BacktestSession)
                .where(BacktestSession.user_id == self.user.id)
                .order_by(BacktestSession.created_at.desc())
                .limit(5)
            )
        ).all()
        return {
            "hypothetical": True,
            "backtests": [
                {
                    "strategy": b.strategy.name,
                    "symbol": b.asset.symbol,
                    "timeframe": b.timeframe,
                    "status": b.status.value,
                    "metrics": {
                        k: b.result.metrics.get(k)
                        for k in ("total_return_pct", "buy_hold_return_pct", "max_drawdown_pct", "sharpe_ratio", "win_rate", "num_trades")
                    }
                    if b.result
                    else None,
                }
                for b in rows
            ],
        }

    async def call(self, name: str, args: dict) -> dict:
        fn = getattr(self, name, None)
        if name.startswith("_") or name not in {t["function"]["name"] for t in TOOL_SPECS} or fn is None:
            return {"error": f"Unknown tool {name}"}
        try:
            return await fn(**args)
        except AppError as exc:
            return {"error": exc.message}
        except TypeError as exc:
            return {"error": f"Bad arguments: {exc}"}


SYSTEM_PROMPT = (
    "You are the research assistant of a trading-intelligence platform that supports research and "
    "SIMULATED paper trading only. Answer using the provided tools; call them whenever the question "
    "involves prices, indicators, signals, the user's portfolio or backtests. Be concise and use markdown. "
    "Explicitly label model outputs and signals as estimates, and backtests as hypothetical. "
    + GROUNDING_RULES
)


async def answer_with_llm(tools: AssistantTools, history: list[dict], question: str) -> tuple[str, list[str], str]:
    client = get_client()
    model = get_settings().openai_model
    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}, *history, {"role": "user", "content": question}]
    used: list[str] = []
    for _ in range(MAX_TOOL_ROUNDS):
        resp = await chat_completion(
            client, model=model, messages=messages, tools=TOOL_SPECS, temperature=0.2, max_completion_tokens=1200
        )
        msg = resp.choices[0].message
        if not msg.tool_calls:
            return (msg.content or "").strip(), used, f"openai:{model}"
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ],
        })
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            result = await tools.call(tc.function.name, args)
            used.append(tc.function.name)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result, default=str)[:12000]})
    return "I could not complete this request within the tool-call budget. Please ask a narrower question.", used, f"openai:{model}"


# ---------------------------------------------------------------------------
# Deterministic fallback
# ---------------------------------------------------------------------------


def _fmt(v: float | None, digits: int = 2) -> str:
    if v is None:
        return "unavailable"
    if abs(v) >= 1:
        return f"{v:,.{digits}f}"
    return f"{v:.6g}"


def _pct(v: float | None) -> str:
    return "unavailable" if v is None else f"{v:+.2f}%"


async def _find_symbols(session: AsyncSession, text: str) -> list[str]:
    assets = (await session.scalars(select(Asset).where(Asset.is_active.is_(True)))).all()
    found: list[tuple[int, str]] = []
    upper = text.upper()
    lower = text.lower()
    for a in assets:
        candidates = [
            (m.start(), a.symbol)
            for pat in (re.escape(a.symbol), rf"\b{re.escape(a.base_currency)}\b")
            for m in re.finditer(pat, upper)
        ]
        idx = lower.find(a.name.lower())
        if idx >= 0 and len(a.name) > 3:
            candidates.append((idx, a.symbol))
        if candidates:
            found.append(min(candidates))
    return [s for _, s in sorted(found)]


def _timeframe_from(text: str) -> str:
    t = text.lower()
    if re.search(r"\b(daily|1d|day|week|long[- ]term)\b", t):
        return "1d"
    if re.search(r"\b(6h|swing)\b", t):
        return "6h"
    if re.search(r"\b(15m|intraday|short[- ]term)\b", t):
        return "15m"
    return "1h"


def _render_analysis(f: dict) -> str:
    t, ind, sig = f["trend"] or {}, f["indicators"], f["signal"]
    lines = [
        f"### {f['symbol']} — {f['timeframe']} technical picture",
        f"*Data as of {f['data_as_of'][:16].replace('T', ' ')} UTC.*",
        "",
        f"- **Trend:** {t.get('direction', 'unavailable')} (regression move {_pct(t.get('regression_move_pct'))} over "
        f"{t.get('lookback_bars', '?')} bars, R² {_fmt(t.get('r_squared'))})",
        f"- **Price:** {_fmt(ind.get('close'))} · SMA50 {_fmt(ind.get('sma_50'))} · SMA200 {_fmt(ind.get('sma_200'))}",
        f"- **RSI(14):** {_fmt(ind.get('rsi_14'), 1)} · **MACD hist:** {_fmt(ind.get('macd_hist'), 4)} · **Bollinger %B:** {_fmt(ind.get('bb_pct_b'))}",
    ]
    if f["patterns"]:
        lines.append("- **Patterns:** " + ", ".join(f"{p['name']} ({p['bias']})" for p in f["patterns"]))
    ml = f["ml_estimate"]
    if ml.get("available"):
        lines.append(
            f"- **ML estimate:** P(up over {ml['horizon_bars']} bars) ≈ {ml['prob_up']:.0%} — walk-forward accuracy "
            f"{ml['oos_accuracy']:.1%} vs {ml['baseline_accuracy']:.1%} baseline (estimate, not a forecast)"
        )
    if sig:
        lines += ["", f"**Signal:** {sig['action'].upper()} · score {sig['score']:+.2f} · confidence {sig['confidence']:.0f}/100", ""]
        for c in sorted(sig["components"], key=lambda c: -abs(c["score"] * c["weight"])):
            lines.append(f"- *{c['name']}* ({c['score']:+.2f}, weight {c['weight']:.2f}): {c['reason']}")
    if f["risks"]:
        lines += ["", "**Risks:**"] + [f"- {r}" for r in f["risks"]]
    return "\n".join(lines)


async def answer_rule_based(tools: AssistantTools, question: str) -> tuple[str, list[str]]:
    q = question.lower()
    symbols = await _find_symbols(tools.session, question)
    tf = _timeframe_from(question)
    used: list[str] = []

    async def call(name: str, **kw: Any) -> dict:
        used.append(name)
        return await tools.call(name, kw)

    if re.search(r"\b(portfolio|positions?|holdings|my (pnl|p&l|balance))\b", q):
        p = await call("get_portfolio")
        lines = [
            "### Your simulated portfolio",
            f"- Equity **${_fmt(p['equity'])}** · cash ${_fmt(p['cash'])}",
            f"- Total P&L {_fmt(p['total_pnl'])} ({_pct(p['total_return_pct'])}) · 24h P&L {_fmt(p['daily_pnl'])}",
        ]
        if p["positions"]:
            lines += ["", "| Asset | Qty | Avg cost | Price | Unrealized |", "|---|---:|---:|---:|---:|"]
            lines += [
                f"| {x['symbol']} | {x['quantity']:g} | {_fmt(x['avg_entry_price'])} | {_fmt(x['price'])} | {_fmt(x['unrealized_pnl'])} |"
                for x in p["positions"]
            ]
        else:
            lines.append("- No open positions.")
        return "\n".join(lines), used

    if re.search(r"\bbacktests?\b", q):
        b = await call("list_backtests")
        if not b["backtests"]:
            return "You have not run any backtests yet. Create a strategy and run one from the Backtesting page.", used
        lines = ["### Recent backtests (hypothetical results)", "", "| Strategy | Asset | Return | Buy&Hold | Max DD | Trades |", "|---|---|---:|---:|---:|---:|"]
        for x in b["backtests"]:
            m = x["metrics"] or {}
            lines.append(
                f"| {x['strategy']} | {x['symbol']} {x['timeframe']} | {_pct(m.get('total_return_pct'))} | "
                f"{_pct(m.get('buy_hold_return_pct'))} | {_pct(m.get('max_drawdown_pct'))} | {m.get('num_trades', '–')} |"
            )
        return "\n".join(lines), used

    if len(symbols) >= 2 or (symbols and re.search(r"\b(compare|vs\.?|versus)\b", q)):
        if len(symbols) < 2:
            return "Please name at least two assets to compare (e.g. *compare BTC and ETH*).", used
        r = await call("compare_assets", symbols=symbols[:4], timeframe=tf)
        lines = [f"### Comparison — {tf}", "", "| Asset | Trend | Price | RSI | Signal | Confidence |", "|---|---|---:|---:|---|---:|"]
        for a in r["assets"]:
            if "error" in a:
                lines.append(f"| {a['symbol']} | {a['error']} | | | | |")
                continue
            s = a["signal"] or {}
            lines.append(
                f"| {a['symbol']} | {(a['trend'] or {}).get('direction', '–')} | {_fmt(a['indicators'].get('close'))} | "
                f"{_fmt(a['indicators'].get('rsi_14'), 1)} | {s.get('action', '–').upper()} | {s.get('confidence', '–')} |"
            )
        lines.append("\nSignals are model estimates from technical data, not recommendations.")
        return "\n".join(lines), used

    if symbols and re.search(r"\bwhy\b|\bsignal\b|explain.*(signal|recommend)", q):
        s = await call("get_latest_signal", symbol=symbols[0])
        if not s.get("action"):
            f = await call("get_asset_analysis", symbol=symbols[0], timeframe=tf)
            return _render_analysis(f), used
        lines = [
            f"### Why {s['symbol']} shows **{s['action'].upper()}** ({s['timeframe']})",
            f"*Generated {s['generated_at'][:16].replace('T', ' ')} UTC at price {_fmt(s['price_at_signal'])}.*",
            "",
            f"The composite score is **{s['score']:+.2f}** (buy > +0.20, sell < −0.20) with confidence {s['confidence']:.0f}/100. Contributions:",
        ]
        lines += [f"- *{c['name']}* ({c['score']:+.2f} × {c['weight']:.2f}): {c['reason']}" for c in s["components"]]
        lines += ["", "**Risks:**"] + [f"- {r['title']}: {r['detail']}" for r in s["risks"]]
        return "\n".join(lines), used

    if symbols and re.search(r"summar|move|moved|movement|recent|today|last \d+", q):
        m = await call("get_recent_movements", symbol=symbols[0], timeframe=tf, bars=24)
        if "error" in m:
            return m["error"], used
        return (
            f"### {m['symbol']} — last {m['bars']} × {m['timeframe']} bars\n"
            f"- From {_fmt(m['open'])} to {_fmt(m['last'])} (**{_pct(m['change_pct'])}**)\n"
            f"- Range {_fmt(m['low'])} – {_fmt(m['high'])}\n"
            f"- {m['up_bars']} up bars / {m['down_bars']} down bars"
        ), used

    if symbols:
        f = await call("get_asset_analysis", symbol=symbols[0], timeframe=tf)
        if "error" in f:
            return f["error"], used
        return _render_analysis(f), used

    o = await call("get_market_overview")
    priced = [a for a in o["assets"] if a.get("price") is not None]
    if not priced:
        return "Live market data is currently unavailable, so I can't describe the market right now.", used
    priced.sort(key=lambda a: -a["change_pct_24h"])
    avg = sum(a["change_pct_24h"] for a in priced) / len(priced)
    up = sum(1 for a in priced if a["change_pct_24h"] > 0)
    lines = [
        "### Market overview (24h)",
        f"{up} of {len(priced)} tracked assets are up; average change {_pct(avg)}.",
        "",
        "| Asset | Price | 24h |",
        "|---|---:|---:|",
    ]
    lines += [f"| {a['symbol']} | {_fmt(a['price'])} | {_pct(a['change_pct_24h'])} |" for a in priced]
    lines.append("\nAsk about a specific asset (e.g. *explain the BTC trend*) for a full technical breakdown.")
    return "\n".join(lines), used


async def answer(session: AsyncSession, user: User, question: str, history: list[dict]) -> tuple[str, dict]:
    tools = AssistantTools(session, user)
    engine = "rule_based"
    if get_client() is not None:
        try:
            text, used, engine = await answer_with_llm(tools, history, question)
        except Exception as exc:  # noqa: BLE001
            logger.warning("assistant_llm_failed", error=str(exc))
            text, used = await answer_rule_based(tools, question)
            engine = "rule_based"
    else:
        text, used = await answer_rule_based(tools, question)
    if engine == "rule_based":
        text += (
            "\n\n---\n*Composed by the platform's deterministic engine from live application data "
            "(no language model is configured).*"
        )
    return text, {"engine": engine, "tools": used, "sources": sorted(tools.sources)}
