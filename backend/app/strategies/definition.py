"""Strategy rule DSL (validated with Pydantic).

Example entry rule set:
    {"logic": "all", "conditions": [
        {"left": {"indicator": "rsi", "params": {"period": 14}}, "op": "crosses_above", "right": {"value": 30}},
        {"left": {"indicator": "close"}, "op": ">", "right": {"indicator": "sma", "params": {"period": 200}}}
    ]}
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

IndicatorName = Literal[
    "close", "open", "high", "low", "volume", "sma", "ema", "rsi", "macd", "bollinger", "atr", "volume_sma", "roc"
]  # fmt: skip
Operator = Literal[">", "<", ">=", "<=", "crosses_above", "crosses_below"]

# Allowed params, defaults, and (min, max) bounds per indicator.
INDICATOR_PARAMS: dict[str, dict[str, tuple[float, float, float]]] = {
    "close": {}, "open": {}, "high": {}, "low": {}, "volume": {},
    "sma": {"period": (20, 2, 400)},
    "ema": {"period": (20, 2, 400)},
    "rsi": {"period": (14, 2, 100)},
    "macd": {"fast": (12, 2, 100), "slow": (26, 3, 200), "signal": (9, 2, 100)},
    "bollinger": {"period": (20, 2, 200), "std": (2.0, 0.5, 5.0)},
    "atr": {"period": (14, 2, 100)},
    "volume_sma": {"period": (20, 2, 400)},
    "roc": {"period": (10, 1, 200)},
}  # fmt: skip
INDICATOR_FIELDS: dict[str, tuple[str, ...]] = {
    "macd": ("macd", "signal", "hist"),
    "bollinger": ("upper", "middle", "lower", "pct_b", "width"),
}


class Operand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    indicator: IndicatorName | None = None
    params: dict[str, float] = Field(default_factory=dict)
    field: str | None = None
    value: float | None = None

    @model_validator(mode="after")
    def _check(self) -> "Operand":
        if (self.indicator is None) == (self.value is None):
            raise ValueError("Operand must specify exactly one of 'indicator' or 'value'")
        if self.indicator is None:
            return self
        spec = INDICATOR_PARAMS[self.indicator]
        unknown = set(self.params) - set(spec)
        if unknown:
            raise ValueError(f"Unknown params for {self.indicator}: {sorted(unknown)}")
        resolved = {}
        for name, (default, lo, hi) in spec.items():
            v = float(self.params.get(name, default))
            if not lo <= v <= hi:
                raise ValueError(f"{self.indicator}.{name} must be between {lo} and {hi}")
            resolved[name] = v
        self.params = resolved
        fields = INDICATOR_FIELDS.get(self.indicator)
        if fields:
            self.field = self.field or fields[0]
            if self.field not in fields:
                raise ValueError(f"{self.indicator} field must be one of {fields}")
        elif self.field is not None:
            raise ValueError(f"{self.indicator} does not take a field")
        if self.indicator == "macd" and self.params["fast"] >= self.params["slow"]:
            raise ValueError("macd.fast must be smaller than macd.slow")
        return self

    def label(self) -> str:
        if self.indicator is None:
            return f"{self.value:g}"
        args = ",".join(f"{int(v) if float(v).is_integer() else v}" for v in self.params.values())
        base = self.indicator.upper() + (f"({args})" if args else "")
        return f"{base}.{self.field}" if self.field else base


class Condition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    left: Operand
    op: Operator
    right: Operand

    @model_validator(mode="after")
    def _check(self) -> "Condition":
        if self.left.indicator is None:
            raise ValueError("The left side of a condition must be an indicator")
        return self

    def label(self) -> str:
        return f"{self.left.label()} {self.op.replace('_', ' ')} {self.right.label()}"


class RuleSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    logic: Literal["all", "any"] = "all"
    conditions: list[Condition] = Field(default_factory=list, max_length=10)


class RiskParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position_size_pct: float = Field(100.0, gt=0, le=100, description="% of equity allocated per entry")
    stop_loss_pct: float | None = Field(None, gt=0, le=90)
    take_profit_pct: float | None = Field(None, gt=0, le=1000)
    trailing_stop_pct: float | None = Field(None, gt=0, le=90)
    max_bars_in_trade: int | None = Field(None, ge=1, le=10000)


class StrategyDefinition(BaseModel):
    entry: RuleSet
    exit: RuleSet
    risk: RiskParams = Field(default_factory=RiskParams)

    @model_validator(mode="after")
    def _check(self) -> "StrategyDefinition":
        if not self.entry.conditions:
            raise ValueError("A strategy needs at least one entry condition")
        r = self.risk
        if not self.exit.conditions and not any(
            [r.stop_loss_pct, r.take_profit_pct, r.trailing_stop_pct, r.max_bars_in_trade]
        ):
            raise ValueError("A strategy needs exit conditions or at least one risk-based exit")
        return self


def _op(indicator: str, **params: float) -> dict:
    return {"indicator": indicator, "params": params}


TEMPLATES: list[dict] = [
    {
        "key": "rsi_mean_reversion",
        "name": "RSI mean reversion",
        "description": "Buy when RSI recovers from oversold while price is above the long-term average; exit when RSI is overbought.",
        "timeframe": "1h",
        "definition": {
            "entry": {"logic": "all", "conditions": [
                {"left": _op("rsi", period=14), "op": "crosses_above", "right": {"value": 30}},
                {"left": _op("close"), "op": ">", "right": _op("sma", period=200)},
            ]},
            "exit": {"logic": "any", "conditions": [
                {"left": _op("rsi", period=14), "op": ">", "right": {"value": 70}},
            ]},
            "risk": {"position_size_pct": 100, "stop_loss_pct": 5, "take_profit_pct": 10},
        },
    },
    {
        "key": "ma_crossover",
        "name": "Moving-average crossover",
        "description": "Classic trend-following: enter when EMA(20) crosses above EMA(50), exit on the reverse cross.",
        "timeframe": "6h",
        "definition": {
            "entry": {"logic": "all", "conditions": [
                {"left": _op("ema", period=20), "op": "crosses_above", "right": _op("ema", period=50)},
            ]},
            "exit": {"logic": "any", "conditions": [
                {"left": _op("ema", period=20), "op": "crosses_below", "right": _op("ema", period=50)},
            ]},
            "risk": {"position_size_pct": 100, "trailing_stop_pct": 8},
        },
    },
    {
        "key": "macd_momentum",
        "name": "MACD momentum",
        "description": "Enter on a bullish MACD crossover above the zero line; exit on a bearish crossover.",
        "timeframe": "1h",
        "definition": {
            "entry": {"logic": "all", "conditions": [
                {"left": {**_op("macd"), "field": "macd"}, "op": "crosses_above", "right": {**_op("macd"), "field": "signal"}},
                {"left": {**_op("macd"), "field": "macd"}, "op": ">", "right": {"value": 0}},
            ]},
            "exit": {"logic": "any", "conditions": [
                {"left": {**_op("macd"), "field": "macd"}, "op": "crosses_below", "right": {**_op("macd"), "field": "signal"}},
            ]},
            "risk": {"position_size_pct": 100, "stop_loss_pct": 4},
        },
    },
    {
        "key": "bollinger_breakout",
        "name": "Bollinger breakout",
        "description": "Enter when price closes above the upper band with above-average volume; exit at the middle band.",
        "timeframe": "1h",
        "definition": {
            "entry": {"logic": "all", "conditions": [
                {"left": _op("close"), "op": "crosses_above", "right": {**_op("bollinger"), "field": "upper"}},
                {"left": _op("volume"), "op": ">", "right": _op("volume_sma", period=20)},
            ]},
            "exit": {"logic": "any", "conditions": [
                {"left": _op("close"), "op": "crosses_below", "right": {**_op("bollinger"), "field": "middle"}},
            ]},
            "risk": {"position_size_pct": 100, "stop_loss_pct": 3, "max_bars_in_trade": 48},
        },
    },
]
