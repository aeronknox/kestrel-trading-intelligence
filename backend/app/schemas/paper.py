from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.enums import OrderSide, OrderStatus, OrderType
from app.schemas.common import ORMModel
from app.schemas.market import AssetOut

MAX_EXPIRY_HOURS = 90 * 24


class OrderCreate(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    side: OrderSide
    order_type: OrderType = OrderType.MARKET
    quantity: float = Field(gt=0, le=1e12)
    limit_price: float | None = Field(None, gt=0)
    stop_price: float | None = Field(None, gt=0, description="Trigger price for stop orders")
    trail_pct: float | None = Field(None, gt=0, le=50, description="Trailing stops: distance from the best price, in %")
    reduce_only: bool = Field(False, description="Only ever shrink a position; cancelled once it is closed")
    stop_loss: float | None = Field(None, gt=0, description="Attach a stop-loss once this entry fills")
    take_profit: float | None = Field(None, gt=0, description="Attach a take-profit once this entry fills")
    expires_in_hours: float | None = Field(
        None, gt=0, le=MAX_EXPIRY_HOURS, description="Resting orders: expire if not filled within this many hours (default: until cancelled)"
    )


class ProtectPosition(BaseModel):
    """A one-cancels-other stop-loss and take-profit for an open position (replaces earlier ones)."""

    stop_loss: float | None = Field(None, gt=0)
    trailing_stop_pct: float | None = Field(None, gt=0, le=50, description="Instead of a fixed stop-loss")
    take_profit: float | None = Field(None, gt=0)
    partial_take_profit: float | None = Field(None, gt=0, description="Scale out: a first target that closes part of the position")
    partial_pct: float = Field(50, ge=1, le=99, description="% of the position the partial take-profit closes")


class OrderOut(ORMModel):
    id: int
    asset: AssetOut
    side: OrderSide
    order_type: OrderType
    quantity: float
    limit_price: float | None
    stop_price: float | None = None
    trail_pct: float | None = None
    trail_anchor: float | None = None
    bracket_stop_loss: float | None = None
    bracket_take_profit: float | None = None
    reduce_only: bool = False
    oco_group: str | None = None
    status: OrderStatus
    filled_price: float | None
    fee: float
    reject_reason: str | None
    created_at: datetime
    filled_at: datetime | None
    expires_at: datetime | None = None
    strategy_id: int | None = None  # set when a strategy's forward test placed the order
    note: str | None = None  # e.g. "Margin call: ..." for orders the system placed


class TradeOut(ORMModel):
    id: int
    order_id: int
    asset: AssetOut
    side: OrderSide
    quantity: float
    price: float
    fee: float
    realized_pnl: float
    executed_at: datetime


class PositionOut(BaseModel):
    id: int
    asset: AssetOut
    side: Literal["long", "short"] = "long"
    quantity: float  # signed: negative for shorts
    avg_entry_price: float
    current_price: float | None
    market_value: float
    unrealized_pnl: float
    unrealized_pnl_pct: float | None
    realized_pnl: float
    allocation_pct: float
    opened_at: datetime
    # Open risk: what resting stops would lose from the current price if they filled.
    stop_price: float | None = None
    risk_to_stop: float | None = None
    unprotected_qty: float = 0.0


class RiskLimits(BaseModel):
    max_position_pct: float = Field(ge=1, le=100)
    max_open_positions: int = Field(ge=1, le=100)
    daily_loss_limit_pct: float = Field(ge=0.5, le=100)
    allow_short: bool = False  # simulated short selling (sell while flat; buy to cover)
    require_stop_loss: bool = False  # your new positions must carry a stop-loss
    max_risk_per_trade_pct: float | None = Field(
        None, ge=0.1, le=10, description="Cap on what a new position's stop-loss would lose, as % of equity (needs a stop)"
    )


class PortfolioOut(BaseModel):
    id: int
    name: str
    starting_balance: float
    cash_balance: float
    reserved_cash: float = 0.0
    short_liability: float = 0.0  # cost to buy back all shorts now
    available_cash: float
    positions_value: float
    equity: float
    realized_pnl: float
    unrealized_pnl: float
    total_pnl: float
    total_return_pct: float
    daily_pnl: float
    daily_pnl_pct: float
    total_fees: float
    risk_limits: RiskLimits
    positions: list[PositionOut]
    prices_complete: bool
    open_risk: float = 0.0  # summed over positions with a stop; unprotected quantity is not included
    open_risk_pct: float = 0.0
    unprotected_positions: int = 0  # positions with quantity no stop covers
    fee_bps: float
    slippage_bps: float
    simulated: bool = True


class SnapshotOut(ORMModel):
    ts: datetime
    equity: float
    cash: float
    positions_value: float
