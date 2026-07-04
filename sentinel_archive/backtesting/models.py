from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


TradeSide = Literal["long", "short"]


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

