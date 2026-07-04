from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


TradeSide = Literal["long", "short"]
AssetClass = Literal["crypto", "stock", "options", "darkpool", "futures_risk"]
OptionAction = Literal["buy", "sell", "exit"]


class MarketPriceBar(BaseModel):
    timestamp: str
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


class OptionAlert(BaseModel):
    timestamp: str
    contract_key: str
    action: OptionAction
    quantity: float = Field(default=1.0, gt=0)
    alert_price: float | None = Field(default=None, ge=0)
    fill_price: float | None = Field(default=None, ge=0)


class OptionQuote(BaseModel):
    timestamp: str
    contract_key: str
    bid: float | None = Field(default=None, ge=0)
    ask: float | None = Field(default=None, ge=0)
    mid: float | None = Field(default=None, ge=0)
    last: float | None = Field(default=None, ge=0)


class BacktestCostModel(BaseModel):
    fee_bps: float = Field(default=0.0, ge=0)
    slippage_bps: float = Field(default=0.0, ge=0)
    funding_bps_per_step: float = 0.0
    commission_per_trade: float = Field(default=0.0, ge=0)
    option_fill_price: Literal["mid", "last", "bid", "ask"] = "mid"
    option_multiplier: float = Field(default=100.0, gt=0)


class BacktestRunRequest(BaseModel):
    asset_class: AssetClass
    symbol: str
    side: TradeSide = "long"
    quantity: float = Field(default=1.0, gt=0)
    starting_equity: float = Field(default=10000.0, gt=0)
    leverage: float = Field(default=1.0, gt=0)
    stop_loss_pct: float | None = Field(default=None, gt=0)
    take_profit_pct: float | None = Field(default=None, gt=0)
    trailing_stop_pct: float | None = Field(default=None, gt=0)
    close_final_position: bool = True
    cost_model: BacktestCostModel = Field(default_factory=BacktestCostModel)
    bars: list[MarketPriceBar] = Field(default_factory=list)
    option_alerts: list[OptionAlert] = Field(default_factory=list)
    option_quotes: list[OptionQuote] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BacktestTrade(BaseModel):
    symbol: str
    side: TradeSide = "long"
    quantity: float = Field(default=0, ge=0)
    entry_time: str
    entry_price: float
    exit_time: str
    exit_price: float
    pnl: float = 0.0
    fees: float = 0.0
    mae: float = 0.0
    mfe: float = 0.0
    exit_reason: str = "final_close"


class BacktestMetrics(BaseModel):
    starting_equity: float = 0.0
    ending_equity: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    total_pnl: float = 0.0
    total_return_pct: float = 0.0
    win_rate: float = 0.0
    trade_count: int = 0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    profit_factor: float = 0.0
    max_drawdown_pct: float = 0.0
    mae: float = 0.0
    mfe: float = 0.0
    average_win: float = 0.0
    average_loss: float = 0.0
    total_fees: float = 0.0
    slippage: float = 0.0
    funding: float = 0.0
    safety_score: float = 100.0
    safety_flags: list[str] = Field(default_factory=list)


class BacktestReport(BaseModel):
    run_id: str = ""
    asset_class: AssetClass
    symbol: str
    metrics: BacktestMetrics
    trades: list[BacktestTrade] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    assumptions: dict[str, Any] = Field(default_factory=dict)
