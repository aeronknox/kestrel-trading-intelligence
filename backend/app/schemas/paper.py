from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.enums import OrderSide, OrderStatus, OrderType
from app.schemas.common import ORMModel
from app.schemas.market import AssetOut


class OrderCreate(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    side: OrderSide
    order_type: OrderType = OrderType.MARKET
    quantity: float = Field(gt=0, le=1e12)
    limit_price: float | None = Field(None, gt=0)


class OrderOut(ORMModel):
    id: int
    asset: AssetOut
    side: OrderSide
    order_type: OrderType
    quantity: float
    limit_price: float | None
    status: OrderStatus
    filled_price: float | None
    fee: float
    reject_reason: str | None
    created_at: datetime
    filled_at: datetime | None
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


class RiskLimits(BaseModel):
    max_position_pct: float = Field(ge=1, le=100)
    max_open_positions: int = Field(ge=1, le=100)
    daily_loss_limit_pct: float = Field(ge=0.5, le=100)
    allow_short: bool = False  # simulated short selling (sell while flat; buy to cover)


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
    fee_bps: float
    slippage_bps: float
    simulated: bool = True


class SnapshotOut(ORMModel):
    ts: datetime
    equity: float
    cash: float
    positions_value: float
