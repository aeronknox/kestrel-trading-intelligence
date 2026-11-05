from datetime import datetime

from pydantic import BaseModel

from app.models.enums import SignalAction
from app.schemas.common import ORMModel
from app.schemas.market import AssetOut


class AnalyzeRequest(BaseModel):
    symbol: str
    timeframe: str = "1h"


class SignalOut(ORMModel):
    id: int
    asset: AssetOut
    timeframe: str
    action: SignalAction
    score: float
    confidence: float
    price_at_signal: float
    components: list[dict]
    risks: list[dict]
    created_at: datetime


class AnalysisOut(ORMModel):
    id: int
    asset: AssetOut
    timeframe: str
    trend: str
    summary: str
    narrative: str
    narrative_source: str
    indicators: dict
    patterns: list[dict]
    ml: dict
    data_source: str
    data_as_of: datetime
    created_at: datetime
    signal: SignalOut | None
    disclaimer: str = (
        "AI-generated analysis is an estimate based on historical data, not a guarantee of future "
        "results and not financial advice."
    )
