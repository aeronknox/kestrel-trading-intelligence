from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.backtesting.optimization import MAX_PARAMS, MAX_VALUES_PER_PARAM
from app.schemas.common import ORMModel
from app.schemas.market import AssetOut

DISCLAIMER = (
    "HYPOTHETICAL research results computed on historical data. They do not represent actual "
    "trading, and past performance does not guarantee future results."
)


class ParamGridIn(BaseModel):
    path: str = Field(max_length=120, examples=["entry.conditions.0.right.value"])
    values: list[float] = Field(min_length=2, max_length=MAX_VALUES_PER_PARAM)


class ResearchRequest(BaseModel):
    strategy_id: int
    bars: int = Field(2000, ge=200, le=20_000, description="Number of historical candles to use")
    initial_capital: float = Field(10_000, gt=0, le=1e9)
    fee_bps: float = Field(10, ge=0, le=500)
    slippage_bps: float = Field(5, ge=0, le=500)
    params: list[ParamGridIn] = Field(min_length=1, max_length=MAX_PARAMS)
    objective: Literal["sharpe_ratio", "total_return_pct", "return_over_drawdown"] = "sharpe_ratio"
    min_trades: int = Field(3, ge=0, le=100, description="Runs with fewer trades are not eligible to be 'best'")


class WalkForwardRequest(ResearchRequest):
    folds: int = Field(4, ge=2, le=8)
    is_ratio: float = Field(3.0, ge=1.0, le=6.0, description="In-sample window length as a multiple of the test window")


class TunableParameter(BaseModel):
    path: str
    label: str
    current: float | None
    min: float | None
    max: float | None
    integer: bool


class ResearchSummary(ORMModel):
    id: int
    kind: Literal["sweep", "walk_forward"]
    strategy_id: int
    strategy_name: str
    strategy_version: int
    asset: AssetOut
    timeframe: str
    start_at: datetime | None
    end_at: datetime | None
    data_source: str
    created_at: datetime
    headline: str | None = None


class ResearchOut(ResearchSummary):
    request: dict
    result: dict
    disclaimer: str = DISCLAIMER
