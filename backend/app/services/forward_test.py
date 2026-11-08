"""Forward testing: a strategy trades the paper portfolio on live closed candles.

Runs inside the alert check (every minute, leader-elected) and mirrors the backtester's
rules so live results are comparable with the backtest:

  * flat: buy when the entry rules are true on a newly closed bar;
  * holding: sell when the exit rules are true, or on the strategy's stop-loss,
    take-profit, trailing stop (high-water mark of earlier bars) or time limit.

Differences from a backtest, by necessity: orders are paper *market* orders filled at the
live price when the bar is seen (shortly after it closes), so stops behave like stop-market
orders and can fill worse than the stop level; the paper portfolio's risk limits apply.

Each strategy only ever sells what it bought itself (orders carry strategy_id), so manual
positions in the same asset are left alone. Short strategies need short selling enabled
in the paper portfolio's risk limits.
Everything is simulated; nothing here can reach a brokerage.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.market_data.providers.base import Candle, timeframe_seconds
from app.market_data.service import MarketDataService
from app.models.alert import AlertEvent, StrategyAlert
from app.models.enums import OrderSide, OrderStatus, OrderType
from app.models.paper import SimulatedOrder
from app.models.strategy import StrategyConfiguration
from app.paper_trading.service import MIN_NOTIONAL, QTY_EPSILON, PaperTradingService
from app.strategies.definition import StrategyDefinition

logger = get_logger(__name__)

SHORTS_DISABLED = "This is a short strategy: enable short selling in your paper portfolio's risk limits to forward-test it"


@dataclass
class AutoPosition:
    quantity: float  # signed: positive long, negative short
    entry_order: SimulatedOrder | None


async def auto_position(session: AsyncSession, portfolio_id: int, strategy_id: int, asset_id: int) -> AutoPosition:
    """What this strategy holds: its own filled buys minus its own filled sells (negative = short)."""
    orders = (
        await session.scalars(
            select(SimulatedOrder)
            .where(
                SimulatedOrder.portfolio_id == portfolio_id,
                SimulatedOrder.strategy_id == strategy_id,
                SimulatedOrder.asset_id == asset_id,
                SimulatedOrder.status == OrderStatus.FILLED,
            )
            .order_by(SimulatedOrder.filled_at, SimulatedOrder.id)
        )
    ).all()
    qty = 0.0
    entry: SimulatedOrder | None = None
    for o in orders:
        if abs(qty) <= QTY_EPSILON:
            entry = o  # the order that opened the current position
        qty += o.quantity if o.side == OrderSide.BUY else -o.quantity
    if abs(qty) <= QTY_EPSILON:
        return AutoPosition(0.0, None)
    return AutoPosition(qty, entry)


def protective_exit(
    definition: StrategyDefinition, closed: list[Candle], i: int, entry: SimulatedOrder, slip_rate: float, tf: timedelta
) -> str | None:
    """Stop-loss / take-profit / trailing stop / time limit on closed bar i, mirrored for shorts as in the backtester."""
    risk = definition.risk
    short = definition.risk.direction == "short"
    assert entry.filled_price is not None and entry.filled_at is not None
    ref = entry.filled_price / ((1 - slip_rate) if short else (1 + slip_rate))  # pre-slippage reference
    entry_bar = next((j for j, c in enumerate(closed) if c.ts + tf > entry.filled_at), len(closed))
    bar = closed[i]
    if short:
        if risk.stop_loss_pct and bar.high >= ref * (1 + risk.stop_loss_pct / 100):
            return "stop-loss"
        if risk.trailing_stop_pct and entry_bar < i:
            lwm = min([ref, *(c.low for c in closed[entry_bar:i])])
            if bar.high >= lwm * (1 + risk.trailing_stop_pct / 100):
                return "trailing stop"
        if risk.take_profit_pct and bar.low <= ref * (1 - risk.take_profit_pct / 100):
            return "take-profit"
    else:
        if risk.stop_loss_pct and bar.low <= ref * (1 - risk.stop_loss_pct / 100):
            return "stop-loss"
        if risk.trailing_stop_pct and entry_bar < i:
            hwm = max([ref, *(c.high for c in closed[entry_bar:i])])
            if bar.low <= hwm * (1 - risk.trailing_stop_pct / 100):
                return "trailing stop"
        if risk.take_profit_pct and bar.high >= ref * (1 + risk.take_profit_pct / 100):
            return "take-profit"
    if risk.max_bars_in_trade and i - entry_bar + 1 >= risk.max_bars_in_trade:
        return "time limit"
    return None


async def act(
    session: AsyncSession,
    market: MarketDataService,
    alert: StrategyAlert,
    definition: StrategyDefinition,
    cfg: StrategyConfiguration,
    closed: list[Candle],
    pending: list[int],
    signals: dict,
    events: dict[tuple[str, datetime], AlertEvent],
    make_event: Callable[[str, Candle], AlertEvent],
) -> None:
    """Place the simulated orders this check calls for, and note them on the alert events."""
    paper = PaperTradingService(session, market)
    portfolio = await paper.get_or_create_portfolio(alert.user_id, lock=True)
    short = definition.risk.direction == "short"
    if short and not portfolio.allow_short:
        alert.last_error = SHORTS_DISABLED
        return
    sign = -1.0 if short else 1.0
    open_side, close_side = (OrderSide.SELL, OrderSide.BUY) if short else (OrderSide.BUY, OrderSide.SELL)
    tf = timedelta(seconds=timeframe_seconds(cfg.timeframe))

    async def current() -> AutoPosition:
        # Capped by what the portfolio really holds on this side: if the user closed it manually, the strategy is flat.
        pos = await auto_position(session, portfolio.id, alert.strategy_id, cfg.asset_id)
        held = next((p.quantity for p in portfolio.positions if p.asset_id == cfg.asset_id), 0.0)
        size = min(pos.quantity * sign, held * sign)
        return AutoPosition(size, pos.entry_order) if size > QTY_EPSILON else AutoPosition(0.0, None)

    pos = await current()  # quantity here is the unsigned size on the strategy's side
    for i in pending:
        bar = closed[i]
        if pos.quantity > QTY_EPSILON and pos.entry_order is not None:
            reason = protective_exit(definition, closed, i, pos.entry_order, paper.slip_rate, tf) or (
                "exit rules" if signals["exit"][i] else None
            )
            if reason is None:
                continue
            verb = "covered" if short else "sold"
            note = await _order(paper, portfolio, cfg, close_side, pos.quantity, alert.strategy_id, f"{verb} on {reason}")
            _attach(events, make_event, "exit", bar, note)
            pos = await current()
        elif signals["entry"][i]:
            size = await _entry_quantity(paper, portfolio, cfg, definition)
            if size is None:
                note = (None, "Paper order skipped: not enough virtual buying power or position headroom for a minimum-size order.")
            else:
                verb = "shorted" if short else "bought"
                note = await _order(paper, portfolio, cfg, open_side, size, alert.strategy_id, f"{verb} on entry rules")
            _attach(events, make_event, "entry", bar, note)
            pos = await current()


async def _entry_quantity(paper: PaperTradingService, portfolio, cfg: StrategyConfiguration, definition: StrategyDefinition) -> float | None:  # type: ignore[no-untyped-def]
    """Size like the backtester (position_size_pct of equity), capped by the position limit and buying power."""
    summary = await paper.summary(portfolio)
    price = (await paper.market.get_ticker(cfg.asset)).price
    equity = summary["equity"]
    # Headroom under the position limit counts what is already held in this asset (e.g. manually),
    # otherwise the risk check would reject the order outright.
    held_value = next((abs(v.market_value) for v in summary["positions"] if v.position.asset_id == cfg.asset_id), 0.0)
    headroom = equity * portfolio.max_position_pct / 100 - held_value
    budget = min(equity * definition.risk.position_size_pct / 100, headroom * 0.999, summary["available_cash"])
    qty = budget / ((1 + paper.fee_rate) * (1 + paper.slip_rate)) / price
    qty = float(f"{qty:.8f}")  # no false precision
    return qty if qty * price >= MIN_NOTIONAL else None


async def _order(paper: PaperTradingService, portfolio, cfg: StrategyConfiguration, side: OrderSide, qty: float,  # type: ignore[no-untyped-def]
                 strategy_id: int, action: str) -> tuple[SimulatedOrder | None, str]:  # fmt: skip
    order = await paper.place_order(portfolio, cfg.asset, side, OrderType.MARKET, qty, strategy_id=strategy_id)
    base = cfg.asset.base_currency
    if order.status == OrderStatus.FILLED:
        return order, f"Paper order {action}: {order.quantity:g} {base} at {order.filled_price:,.2f} (simulated)."
    return order, f"Paper order rejected: {order.reject_reason} (simulated)."


def _attach(
    events: dict, make_event: Callable[[str, Candle], AlertEvent], kind: str, bar: Candle, note: tuple[SimulatedOrder | None, str]
) -> None:
    order, text = note
    event = events.get((kind, bar.ts))
    if event is None:
        event = make_event(kind, bar)
        events[(kind, bar.ts)] = event
    event.message = f"{event.message} {text}"
    if order is not None:
        event.order_id = order.id


async def forward_test_summary(session: AsyncSession, market: MarketDataService, user_id: int, strategy_id: int) -> dict:
    """The strategy's own paper trades as round trips, plus any open position."""
    paper = PaperTradingService(session, market)
    portfolio = await paper.get_or_create_portfolio(user_id)
    orders = (
        await session.scalars(
            select(SimulatedOrder)
            .where(SimulatedOrder.portfolio_id == portfolio.id, SimulatedOrder.strategy_id == strategy_id)
            .order_by(SimulatedOrder.created_at, SimulatedOrder.id)
        )
    ).all()
    linked = (await session.scalars(select(AlertEvent).where(AlertEvent.order_id.in_([o.id for o in orders])))).all()
    notes = {e.order_id: e.message for e in linked}
    trips: list[dict] = []
    qty = 0.0  # signed
    basis = entry_value = 0.0  # long: cost incl. fees; short: net proceeds after fees
    entry_at: datetime | None = None
    for o in orders:
        if o.status != OrderStatus.FILLED or o.filled_price is None:
            continue
        direction = 1.0 if o.side == OrderSide.BUY else -1.0
        if abs(qty) <= QTY_EPSILON or qty * direction > 0:  # opens or adds to the position
            if abs(qty) <= QTY_EPSILON:
                entry_at, basis, entry_value = o.filled_at, 0.0, 0.0
            qty += direction * o.quantity
            basis += o.quantity * o.filled_price + (o.fee if direction > 0 else -o.fee)
            entry_value += o.quantity * o.filled_price
        else:  # reduces or closes it
            size = abs(qty)
            closed_qty = min(o.quantity, size)
            share = closed_qty / size
            avg_entry = entry_value / size
            if qty > 0:  # long: proceeds of the sale minus the cost basis
                pnl = closed_qty * o.filled_price - o.fee - basis * share
            else:  # short: proceeds of the short sale minus the cost of buying back
                pnl = basis * share - (closed_qty * o.filled_price + o.fee)
            denom = basis * share
            trips.append(
                {
                    "side": "long" if qty > 0 else "short",
                    "entry_at": entry_at,
                    "exit_at": o.filled_at,
                    "quantity": closed_qty,
                    "entry_price": avg_entry,
                    "exit_price": o.filled_price,
                    "pnl": pnl,
                    "return_pct": pnl / denom * 100 if denom else 0.0,
                    "note": notes.get(o.id),
                }
            )
            qty += direction * closed_qty
            basis -= basis * share
            entry_value -= avg_entry * closed_qty
    open_position = None
    if abs(qty) > QTY_EPSILON:
        asset = orders[-1].asset
        price = (await market.get_ticker(asset)).price
        size = abs(qty)
        open_position = {
            "symbol": asset.symbol,
            "side": "long" if qty > 0 else "short",
            "quantity": size,
            "entry_price": entry_value / size,
            "entry_at": entry_at,
            "current_price": price,
            "unrealized_pnl": size * price - basis if qty > 0 else basis - size * price,
        }
    pnls = [t["pnl"] for t in trips]
    return {
        "started_at": orders[0].created_at if orders else None,
        "orders": len(orders),
        "rejected": sum(o.status == OrderStatus.REJECTED for o in orders),
        "round_trips": list(reversed(trips)),
        "open_position": open_position,
        "realized_pnl": sum(pnls),
        "num_trades": len(trips),
        "win_rate": sum(p > 0 for p in pnls) / len(pnls) * 100 if pnls else None,
        "as_of": datetime.now(UTC),
    }
