"""Rebalance the paper portfolio to target weights (simulated market orders).

Targets are % of equity for the assets you list; anything else (other positions, the rest of the cash) is
left alone. Sells come first so their proceeds pay for the buys. Differences under the drift band
(MIN_TRADE_USD or DRIFT_PCT of equity, whichever is larger) are skipped, so a portfolio already close to
its targets isn't churned by its own trading costs. Shorts aren't rebalanced.
"""

from dataclasses import dataclass

from app.core.exceptions import ValidationFailedError
from app.models.enums import OrderSide, OrderStatus, OrderType
from app.models.market import Asset
from app.models.paper import PaperPortfolio, SimulatedOrder
from app.paper_trading.service import PaperTradingService

MIN_TRADE_USD = 10.0
DRIFT_PCT = 0.1  # % of equity
NOTE = "Rebalance"


@dataclass
class Leg:
    asset: Asset
    side: OrderSide
    quantity: float
    price: float  # the market price the leg was planned at
    current_value: float
    target_value: float
    current_pct: float
    target_pct: float

    @property
    def value(self) -> float:
        return self.quantity * self.price


@dataclass
class Plan:
    equity: float
    legs: list[Leg]
    unchanged: list[str]  # listed assets already within MIN_TRADE_USD of their target
    cash_after_pct: float  # cash as % of equity once the plan is done (before fees)


async def plan_rebalance(paper: PaperTradingService, portfolio: PaperPortfolio, assets: list[Asset], targets: list[float]) -> Plan:
    if sum(targets) > 100 + 1e-9:
        raise ValidationFailedError(f"The targets add up to {sum(targets):g}%; they can be at most 100% (the rest stays in cash)")
    limit = portfolio.max_position_pct
    over = [f"{a.symbol} {t:g}%" for a, t in zip(assets, targets, strict=True) if t > limit + 1e-9]
    if over:
        raise ValidationFailedError(f"Above your {limit:g}% position-size limit: {', '.join(over)}. Lower the target or raise the limit")
    summary = await paper.summary(portfolio)
    equity = summary["equity"]
    views = {v.position.asset_id: v for v in summary["positions"]}
    if any(views[a.id].is_short for a in assets if a.id in views):
        raise ValidationFailedError("Buy back your short first: rebalancing only adjusts long positions")
    tickers = await paper.market.get_tickers(assets)
    legs: list[Leg] = []
    unchanged: list[str] = []
    band = max(MIN_TRADE_USD, equity * DRIFT_PCT / 100)
    for asset, target in zip(assets, targets, strict=True):
        t = tickers.get(asset.symbol)
        if t is None:
            raise ValidationFailedError(f"No current price for {asset.symbol}; try again in a moment")
        current = views[asset.id].position.quantity * t.price if asset.id in views else 0.0
        goal = equity * target / 100
        diff = goal - current
        if abs(diff) < band:
            unchanged.append(asset.symbol)
            continue
        if diff > 0:  # buy what is worth the difference at the market price (slippage and fee come out of cash)
            qty = diff / t.price
            side = OrderSide.BUY
        else:  # sell; all of it when the target is 0
            held = views[asset.id].position.quantity
            qty = held if target == 0 else min(held, -diff / t.price)
            side = OrderSide.SELL
        legs.append(Leg(asset, side, qty, t.price, current, goal, current / equity * 100, target))
    legs.sort(key=lambda leg: leg.side != OrderSide.SELL)  # sells first
    invested_after = sum(v.market_value for v in summary["positions"] if not v.is_short) + sum(
        (leg.value if leg.side == OrderSide.BUY else -leg.value) for leg in legs
    )
    return Plan(equity, legs, unchanged, max(0.0, (equity - invested_after) / equity * 100) if equity else 0.0)


async def execute(paper: PaperTradingService, portfolio: PaperPortfolio, plan: Plan) -> list[SimulatedOrder]:
    """Place the legs in order; a rejected leg doesn't stop the others (each is reported)."""
    orders = []
    for leg in plan.legs:
        orders.append(await paper.place_order(portfolio, leg.asset, leg.side, OrderType.MARKET, leg.quantity, note=NOTE))
    return orders


def filled(orders: list[SimulatedOrder]) -> int:
    return sum(o.status == OrderStatus.FILLED for o in orders)
