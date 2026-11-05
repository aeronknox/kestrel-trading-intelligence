"""Paper trading: a fully simulated order/fill/position ledger.

SIMULATION ONLY. Nothing in this module (or anywhere in the platform) connects
to a brokerage or moves real money. Fills use the provider's latest public price
plus configured slippage and fees.

Accounting:
  * Buy fees are capitalized into the position's average cost.
  * Sell fees reduce realized P&L.
  * Therefore: equity - starting_balance == realized_pnl + unrealized_pnl.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import NotFoundError, RiskLimitError, ValidationFailedError
from app.core.logging import get_logger
from app.market_data.service import MarketDataService
from app.models.enums import OrderSide, OrderStatus, OrderType
from app.models.market import Asset
from app.models.paper import (
    PaperPortfolio,
    PortfolioPosition,
    PortfolioSnapshot,
    SimulatedOrder,
    SimulatedTrade,
)

logger = get_logger(__name__)

QTY_EPSILON = 1e-12
MIN_NOTIONAL = 1.0
SNAPSHOT_MIN_INTERVAL = timedelta(minutes=5)


@dataclass
class PositionView:
    position: PortfolioPosition
    price: float | None

    @property
    def market_value(self) -> float:
        return self.position.quantity * (self.price if self.price is not None else self.position.avg_entry_price)

    @property
    def unrealized_pnl(self) -> float:
        if self.price is None:
            return 0.0
        return (self.price - self.position.avg_entry_price) * self.position.quantity


class PaperTradingService:
    def __init__(self, session: AsyncSession, market: MarketDataService | None = None) -> None:
        self.session = session
        self.market = market or MarketDataService(session)
        settings = get_settings()
        self.fee_rate = settings.paper_fee_bps / 10_000
        self.slip_rate = settings.paper_slippage_bps / 10_000

    # -------------------------------------------------------------- portfolio
    async def get_or_create_portfolio(self, user_id: int, *, lock: bool = False) -> PaperPortfolio:
        stmt = select(PaperPortfolio).where(PaperPortfolio.user_id == user_id, PaperPortfolio.is_active.is_(True))
        if lock:
            stmt = stmt.with_for_update()
        portfolio = await self.session.scalar(stmt.order_by(PaperPortfolio.id).limit(1))
        if portfolio is None:
            balance = get_settings().paper_starting_balance
            portfolio = PaperPortfolio(user_id=user_id, name="Main", starting_balance=balance, cash_balance=balance)
            self.session.add(portfolio)
            await self.session.flush()
            self.session.add(
                PortfolioSnapshot(portfolio_id=portfolio.id, equity=balance, cash=balance, positions_value=0.0)
            )
            await self.session.flush()
            await self.session.refresh(portfolio, attribute_names=["positions"])
        return portfolio

    async def position_views(self, portfolio: PaperPortfolio) -> list[PositionView]:
        positions = [p for p in portfolio.positions if p.quantity > QTY_EPSILON]
        tickers = await self.market.get_tickers([p.asset for p in positions]) if positions else {}
        return [
            PositionView(p, tickers.get(p.asset.symbol).price if tickers.get(p.asset.symbol) else None)
            for p in positions
        ]

    async def summary(self, portfolio: PaperPortfolio) -> dict:
        views = await self.position_views(portfolio)
        positions_value = sum(v.market_value for v in views)
        equity = portfolio.cash_balance + positions_value
        unrealized = sum(v.unrealized_pnl for v in views)
        day_ago = datetime.now(UTC) - timedelta(hours=24)
        ref = await self.session.scalar(
            select(PortfolioSnapshot)
            .where(PortfolioSnapshot.portfolio_id == portfolio.id, PortfolioSnapshot.ts <= day_ago)
            .order_by(PortfolioSnapshot.ts.desc())
            .limit(1)
        )
        if ref is None:  # portfolio younger than 24h: compare against its first snapshot
            ref = await self.session.scalar(
                select(PortfolioSnapshot)
                .where(PortfolioSnapshot.portfolio_id == portfolio.id)
                .order_by(PortfolioSnapshot.ts.asc())
                .limit(1)
            )
        ref_equity = ref.equity if ref else portfolio.starting_balance
        return {
            "portfolio": portfolio,
            "positions": views,
            "positions_value": positions_value,
            "equity": equity,
            "unrealized_pnl": unrealized,
            "total_pnl": equity - portfolio.starting_balance,
            "total_return_pct": (equity / portfolio.starting_balance - 1) * 100,
            "daily_pnl": equity - ref_equity,
            "daily_pnl_pct": (equity / ref_equity - 1) * 100 if ref_equity else 0.0,
            "prices_complete": all(v.price is not None for v in views),
        }

    async def record_snapshot(self, portfolio: PaperPortfolio, *, force: bool = False) -> PortfolioSnapshot | None:
        last = await self.session.scalar(
            select(PortfolioSnapshot)
            .where(PortfolioSnapshot.portfolio_id == portfolio.id)
            .order_by(PortfolioSnapshot.ts.desc())
            .limit(1)
        )
        if not force and last and datetime.now(UTC) - last.ts < SNAPSHOT_MIN_INTERVAL:
            return None
        views = await self.position_views(portfolio)
        if not all(v.price is not None for v in views):
            return None  # never record an equity point from incomplete prices
        pv = sum(v.market_value for v in views)
        snap = PortfolioSnapshot(
            portfolio_id=portfolio.id,
            equity=portfolio.cash_balance + pv,
            cash=portfolio.cash_balance,
            positions_value=pv,
        )
        self.session.add(snap)
        await self.session.flush()
        return snap

    async def reset(self, portfolio: PaperPortfolio) -> PaperPortfolio:
        await self.session.execute(delete(SimulatedTrade).where(SimulatedTrade.portfolio_id == portfolio.id))
        await self.session.execute(delete(SimulatedOrder).where(SimulatedOrder.portfolio_id == portfolio.id))
        await self.session.execute(delete(PortfolioPosition).where(PortfolioPosition.portfolio_id == portfolio.id))
        await self.session.execute(delete(PortfolioSnapshot).where(PortfolioSnapshot.portfolio_id == portfolio.id))
        portfolio.cash_balance = portfolio.starting_balance
        portfolio.realized_pnl = 0.0
        portfolio.total_fees = 0.0
        await self.session.flush()
        self.session.add(
            PortfolioSnapshot(
                portfolio_id=portfolio.id,
                equity=portfolio.starting_balance,
                cash=portfolio.starting_balance,
                positions_value=0.0,
            )
        )
        await self.session.flush()
        await self.session.refresh(portfolio, attribute_names=["positions"])
        return portfolio

    # ------------------------------------------------------------------ orders
    async def place_order(
        self,
        portfolio: PaperPortfolio,
        asset: Asset,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        limit_price: float | None = None,
    ) -> SimulatedOrder:
        if quantity <= 0:
            raise ValidationFailedError("Quantity must be positive")
        if order_type == OrderType.LIMIT and (limit_price is None or limit_price <= 0):
            raise ValidationFailedError("Limit orders require a positive limit price")
        if order_type == OrderType.MARKET:
            limit_price = None

        ticker = await self.market.get_ticker(asset)
        order = SimulatedOrder(
            portfolio_id=portfolio.id,
            asset_id=asset.id,
            side=side,
            order_type=order_type,
            quantity=quantity,
            limit_price=limit_price,
            status=OrderStatus.OPEN,
        )
        order.asset = asset
        self.session.add(order)
        await self.session.flush()

        reference_price = limit_price if order_type == OrderType.LIMIT else ticker.price
        try:
            await self._check_risk(portfolio, asset, side, quantity, reference_price)
        except RiskLimitError as exc:
            order.status = OrderStatus.REJECTED
            order.reject_reason = exc.message
            await self.session.flush()
            return order

        if self._is_marketable(order, ticker.price):
            await self._fill(portfolio, order, ticker.price)
        return order

    @staticmethod
    def _is_marketable(order: SimulatedOrder, price: float) -> bool:
        if order.order_type == OrderType.MARKET:
            return True
        assert order.limit_price is not None
        return price <= order.limit_price if order.side == OrderSide.BUY else price >= order.limit_price

    async def _position(self, portfolio: PaperPortfolio, asset_id: int) -> PortfolioPosition | None:
        return next((p for p in portfolio.positions if p.asset_id == asset_id), None)

    async def _check_risk(
        self, portfolio: PaperPortfolio, asset: Asset, side: OrderSide, quantity: float, price: float
    ) -> None:
        notional = quantity * price
        if notional < MIN_NOTIONAL:
            raise RiskLimitError(f"Order notional must be at least ${MIN_NOTIONAL:.2f}")
        position = await self._position(portfolio, asset.id)
        if side == OrderSide.SELL:
            held = position.quantity if position else 0.0
            if quantity > held + QTY_EPSILON:
                raise RiskLimitError(f"Cannot sell {quantity:g} {asset.base_currency}; position is {held:g} (short selling is disabled)")
            return

        cost = notional * (1 + self.slip_rate) * (1 + self.fee_rate)
        if cost > portfolio.cash_balance + 1e-9:
            raise RiskLimitError(f"Insufficient virtual cash: order needs ${cost:,.2f}, available ${portfolio.cash_balance:,.2f}")
        summary = await self.summary(portfolio)
        equity = summary["equity"]
        current_value = next((v.market_value for v in summary["positions"] if v.position.asset_id == asset.id), 0.0)
        if (current_value + notional) / equity * 100 > portfolio.max_position_pct + 1e-9:
            raise RiskLimitError(
                f"Position would be {(current_value + notional) / equity * 100:.1f}% of equity; "
                f"limit is {portfolio.max_position_pct:.0f}%"
            )
        open_positions = len(summary["positions"])
        if current_value == 0 and open_positions >= portfolio.max_open_positions:
            raise RiskLimitError(f"Maximum of {portfolio.max_open_positions} open positions reached")
        if summary["daily_pnl_pct"] <= -portfolio.daily_loss_limit_pct:
            raise RiskLimitError(
                f"Daily loss limit of {portfolio.daily_loss_limit_pct:.1f}% reached; new buys are blocked for now"
            )

    async def _fill(self, portfolio: PaperPortfolio, order: SimulatedOrder, market_price: float) -> None:
        if order.side == OrderSide.BUY:
            price = market_price * (1 + self.slip_rate)
            if order.limit_price is not None:
                price = min(price, order.limit_price)
        else:
            price = market_price * (1 - self.slip_rate)
            if order.limit_price is not None:
                price = max(price, order.limit_price)
        notional = order.quantity * price
        fee = notional * self.fee_rate
        position = await self._position(portfolio, order.asset_id)
        realized = 0.0

        if order.side == OrderSide.BUY:
            if notional + fee > portfolio.cash_balance + 1e-9:
                order.status = OrderStatus.REJECTED
                order.reject_reason = "Insufficient virtual cash at fill time"
                return
            portfolio.cash_balance -= notional + fee
            if position is None:
                position = PortfolioPosition(
                    portfolio_id=portfolio.id, asset_id=order.asset_id, quantity=0.0, avg_entry_price=0.0
                )
                position.asset = order.asset
                portfolio.positions.append(position)
            total_cost = position.quantity * position.avg_entry_price + notional + fee
            position.quantity += order.quantity
            position.avg_entry_price = total_cost / position.quantity
        else:
            if position is None or order.quantity > position.quantity + QTY_EPSILON:
                order.status = OrderStatus.REJECTED
                order.reject_reason = "Insufficient position at fill time"
                return
            qty = min(order.quantity, position.quantity)
            realized = (price - position.avg_entry_price) * qty - fee
            portfolio.cash_balance += notional - fee
            position.quantity -= qty
            position.realized_pnl += realized
            portfolio.realized_pnl += realized
            if position.quantity <= QTY_EPSILON:
                portfolio.positions.remove(position)
                await self.session.delete(position)

        portfolio.total_fees += fee
        now = datetime.now(UTC)
        order.status = OrderStatus.FILLED
        order.filled_price = price
        order.fee = fee
        order.filled_at = now
        self.session.add(
            SimulatedTrade(
                order_id=order.id,
                portfolio_id=portfolio.id,
                asset_id=order.asset_id,
                side=order.side,
                quantity=order.quantity,
                price=price,
                fee=fee,
                realized_pnl=realized,
                executed_at=now,
            )
        )
        await self.session.flush()
        await self.record_snapshot(portfolio, force=True)

    async def cancel_order(self, portfolio: PaperPortfolio, order_id: int) -> SimulatedOrder:
        order = await self.session.scalar(
            select(SimulatedOrder).where(SimulatedOrder.id == order_id, SimulatedOrder.portfolio_id == portfolio.id)
        )
        if order is None:
            raise NotFoundError("Order not found")
        if order.status != OrderStatus.OPEN:
            raise ValidationFailedError(f"Only open orders can be cancelled (status: {order.status.value})")
        order.status = OrderStatus.CANCELLED
        await self.session.flush()
        return order

    async def process_open_orders(self, portfolio: PaperPortfolio) -> int:
        """Fill any resting limit orders whose price has been reached. Returns fills."""
        orders = (
            await self.session.scalars(
                select(SimulatedOrder)
                .where(SimulatedOrder.portfolio_id == portfolio.id, SimulatedOrder.status == OrderStatus.OPEN)
                .order_by(SimulatedOrder.created_at)
            )
        ).all()
        if not orders:
            return 0
        tickers = await self.market.get_tickers(list({o.asset_id: o.asset for o in orders}.values()))
        fills = 0
        for order in orders:
            t = tickers.get(order.asset.symbol)
            if t is None or not self._is_marketable(order, t.price):
                continue
            await self._fill(portfolio, order, t.price)
            fills += order.status == OrderStatus.FILLED
        return fills

    # --------------------------------------------------------------- history
    async def list_orders(self, portfolio: PaperPortfolio, status: OrderStatus | None, limit: int) -> list[SimulatedOrder]:
        stmt = select(SimulatedOrder).where(SimulatedOrder.portfolio_id == portfolio.id)
        if status:
            stmt = stmt.where(SimulatedOrder.status == status)
        return list((await self.session.scalars(stmt.order_by(SimulatedOrder.created_at.desc()).limit(limit))).all())

    async def list_trades(self, portfolio: PaperPortfolio, limit: int) -> list[SimulatedTrade]:
        stmt = (
            select(SimulatedTrade)
            .where(SimulatedTrade.portfolio_id == portfolio.id)
            .order_by(SimulatedTrade.executed_at.desc())
            .limit(limit)
        )
        return list((await self.session.scalars(stmt)).all())

    async def equity_history(self, portfolio: PaperPortfolio, limit: int = 1000) -> list[PortfolioSnapshot]:
        rows = (
            await self.session.scalars(
                select(PortfolioSnapshot)
                .where(PortfolioSnapshot.portfolio_id == portfolio.id)
                .order_by(PortfolioSnapshot.ts.desc())
                .limit(limit)
            )
        ).all()
        return list(reversed(rows))

    async def analytics(self, portfolio: PaperPortfolio) -> dict:
        sells = (
            await self.session.scalars(
                select(SimulatedTrade).where(
                    SimulatedTrade.portfolio_id == portfolio.id, SimulatedTrade.side == OrderSide.SELL
                )
            )
        ).all()
        n_trades = await self.session.scalar(
            select(func.count()).select_from(SimulatedTrade).where(SimulatedTrade.portfolio_id == portfolio.id)
        )
        pnls = [t.realized_pnl for t in sells]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        history = await self.equity_history(portfolio)
        peak = 0.0
        max_dd = 0.0
        for s in history:
            peak = max(peak, s.equity)
            if peak:
                max_dd = min(max_dd, (s.equity / peak - 1) * 100)
        return {
            "total_trades": int(n_trades or 0),
            "closed_trades": len(pnls),
            "win_rate": len(wins) / len(pnls) * 100 if pnls else None,
            "profit_factor": sum(wins) / -sum(losses) if losses else None,
            "avg_win": sum(wins) / len(wins) if wins else None,
            "avg_loss": sum(losses) / len(losses) if losses else None,
            "best_trade": max(pnls) if pnls else None,
            "worst_trade": min(pnls) if pnls else None,
            "total_fees": portfolio.total_fees,
            "max_drawdown_pct": max_dd,
        }
