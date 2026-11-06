from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.enums import BacktestStatus
from app.schemas.common import ORMModel
from app.schemas.market import AssetOut
from app.strategies.definition import RiskParams, RuleSet

Timeframe = Literal["1m", "5m", "15m", "1h", "6h", "1d"]


class StrategyConfigIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    timeframe: Timeframe = "1h"
    entry: RuleSet
    exit: RuleSet
    risk: RiskParams = Field(default_factory=RiskParams)


class StrategyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field("", max_length=2000)
    config: StrategyConfigIn


class StrategyUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    description: str | None = Field(None, max_length=2000)
    config: StrategyConfigIn | None = None
    is_archived: bool | None = None


class StrategyConfigOut(ORMModel):
    id: int
    version: int
    asset: AssetOut
    timeframe: str
    entry_rules: dict
    exit_rules: dict
    risk: dict
    created_at: datetime


class StrategyOut(ORMModel):
    id: int
    name: str
    description: str
    is_archived: bool
    current_version: int
    created_at: datetime
    updated_at: datetime
    current_config: StrategyConfigOut | None
    latest_backtest: "BacktestSummary | None" = None


class BacktestRequest(BaseModel):
    strategy_id: int
    bars: int = Field(1000, ge=100, le=20_000, description="Number of historical candles to test on")
    initial_capital: float = Field(10_000, gt=0, le=1e9)
    fee_bps: float = Field(10, ge=0, le=500)
    slippage_bps: float = Field(5, ge=0, le=500)


class BacktestSummary(ORMModel):
    id: int
    strategy_id: int
    status: BacktestStatus
    timeframe: str
    created_at: datetime
    total_return_pct: float | None = None
    max_drawdown_pct: float | None = None
    sharpe_ratio: float | None = None
    win_rate: float | None = None
    num_trades: int | None = None


class BacktestOut(ORMModel):
    id: int
    strategy_id: int
    strategy_name: str
    strategy_version: int
    asset: AssetOut
    timeframe: str
    start_at: datetime | None
    end_at: datetime | None
    initial_capital: float
    fee_bps: float
    slippage_bps: float
    status: BacktestStatus
    error: str | None
    data_source: str
    created_at: datetime
    completed_at: datetime | None
    metrics: dict | None = None
    equity_curve: list[dict] | None = None
    trades: list[dict] | None = None
    disclaimer: str = (
        "HYPOTHETICAL backtest results computed on historical data. They do not represent actual "
        "trading, and past performance does not guarantee future results."
    )


StrategyOut.model_rebuild()
