from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


TradeSide = Literal["long", "short"]
AssetClass = Literal[
    "crypto",
    "crypto_futures",
    "stock",
    "options",
    "futures",
    "darkpool",
    "futures_risk",
]
OptionAction = Literal["buy", "sell", "exit"]
BacktestRunKind = Literal["run", "sweep", "walk_forward", "stress"]


class MarketPriceBar(BaseModel):
    timestamp: str
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    bid: float | None = Field(default=None, gt=0)
    ask: float | None = Field(default=None, gt=0)
    vwap: float | None = Field(default=None, gt=0)
    trade_count: int | None = Field(default=None, ge=0)
    mark_price: float | None = Field(default=None, gt=0)
    index_price: float | None = Field(default=None, gt=0)
    open_interest: float | None = Field(default=None, ge=0)


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
    maker_fee_bps: float | None = None
    taker_fee_bps: float | None = None
    spread_bps: float = Field(default=0.0, ge=0)
    commission_per_contract: float = Field(default=0.0, ge=0)
    exchange_fee_per_contract: float = Field(default=0.0, ge=0)
    liquidation_fee_bps: float = Field(default=0.0, ge=0)


class FuturesContractSpec(BaseModel):
    symbol: str
    venue: str = "SIMULATED"
    instrument_type: Literal["listed_future", "crypto_perpetual", "crypto_delivery"] = "listed_future"
    base_currency: str = "USD"
    quote_currency: str = "USD"
    settlement_currency: str = "USD"
    contract_multiplier: float = Field(default=1.0, gt=0)
    tick_size: float = Field(default=0.01, gt=0)
    quantity_step: float = Field(default=1.0, gt=0)
    minimum_quantity: float = Field(default=1.0, gt=0)
    maximum_quantity: float | None = Field(default=None, gt=0)
    initial_margin_rate: float = Field(default=0.1, gt=0, le=1)
    maintenance_margin_rate: float = Field(default=0.05, gt=0, le=1)
    maximum_leverage: float = Field(default=100.0, ge=1)
    inverse: bool = False


class FundingEvent(BaseModel):
    timestamp: str
    rate: float
    mark_price: float | None = Field(default=None, gt=0)


OrderAction = Literal["open", "close", "cancel", "amend"]
OrderType = Literal["market", "limit", "stop", "stop_limit", "trailing_stop"]
TimeInForce = Literal["GTC", "IOC", "FOK", "DAY"]
SameBarPolicy = Literal["adverse_first", "favorable_first", "open_high_low_close", "open_low_high_close", "reject_ambiguous"]


class BacktestOrderIntent(BaseModel):
    order_id: str
    timestamp: str | None = None
    action: OrderAction = "open"
    side: TradeSide = "long"
    order_type: OrderType = "market"
    quantity: float = Field(default=1.0, gt=0)
    limit_price: float | None = Field(default=None, gt=0)
    stop_price: float | None = Field(default=None, gt=0)
    trailing_percent: float | None = Field(default=None, gt=0)
    reduce_only: bool = False
    oco_group: str | None = None
    time_in_force: TimeInForce = "IOC"
    metadata: dict[str, Any] = Field(default_factory=dict)


class DerivativesExecutionModel(BaseModel):
    same_bar_policy: SameBarPolicy = "adverse_first"
    maximum_volume_participation: float = Field(default=0.1, gt=0, le=1)
    reject_when_volume_missing: bool = False
    allow_partial_fills: bool = True
    market_order_time_in_force: TimeInForce = "IOC"
    latency_bars: int = Field(default=0, ge=0)
    price_reference: Literal["trade", "mark", "index"] = "trade"
    gap_stop_fill: Literal["open", "stop"] = "open"
    deterministic_seed: int = 0


class DerivativesRunRequest(BaseModel):
    bot_id: Literal["iron", "chain", "combination", "reference", "custom"] = "custom"
    symbol: str
    side: TradeSide = "long"
    quantity: float = Field(default=1.0, gt=0)
    starting_equity: float = Field(default=10000.0, gt=0)
    leverage: float = Field(default=1.0, ge=1)
    margin_mode: Literal["isolated", "cross"] = "isolated"
    contract: FuturesContractSpec
    cost_model: BacktestCostModel = Field(default_factory=BacktestCostModel)
    execution_model: DerivativesExecutionModel = Field(default_factory=DerivativesExecutionModel)
    bars: list[MarketPriceBar] = Field(default_factory=list)
    funding_events: list[FundingEvent] = Field(default_factory=list)
    orders: list[BacktestOrderIntent] = Field(default_factory=list)
    stop_loss_pct: float | None = Field(default=None, gt=0)
    take_profit_pct: float | None = Field(default=None, gt=0)
    trailing_stop_pct: float | None = Field(default=None, gt=0)
    close_final_position: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutionEvent(BaseModel):
    sequence: int
    timestamp: str
    event_type: str
    order_id: str | None = None
    side: TradeSide | None = None
    requested_quantity: float = 0.0
    filled_quantity: float = 0.0
    remaining_quantity: float = 0.0
    price: float | None = None
    fee: float = 0.0
    reason: str | None = None
    oco_group: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AccountSnapshot(BaseModel):
    timestamp: str
    cash: float
    equity: float
    used_margin: float
    maintenance_margin: float
    available_margin: float
    position_quantity: float
    mark_price: float
    unrealized_pnl: float
    realized_pnl: float
    funding: float
    fees: float
    debt: float


class DerivativesMetrics(BaseModel):
    starting_equity: float
    ending_equity: float
    net_pnl: float
    realized_pnl: float
    maximum_equity: float
    minimum_equity: float
    maximum_drawdown_pct: float
    total_fees: float
    total_funding: float
    total_slippage: float
    total_commissions: float
    total_exchange_fees: float
    total_liquidation_fees: float
    order_count: int
    fill_count: int
    partial_fill_count: int
    rejection_count: int
    unfilled_count: int
    liquidation_count: int
    margin_call_count: int
    potential_debt: float
    safety_score: float
    safety_flags: list[str] = Field(default_factory=list)


class DerivativesReport(BaseModel):
    run_id: str = ""
    fingerprint: str = ""
    bot_id: str
    symbol: str
    contract: FuturesContractSpec
    metrics: DerivativesMetrics
    executions: list[ExecutionEvent] = Field(default_factory=list)
    account_curve: list[AccountSnapshot] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    assumptions: dict[str, Any] = Field(default_factory=dict)


class AuditLayerRequest(BaseModel):
    layer_id: str
    label: str
    bot_id: Literal["iron", "chain", "combination", "reference", "custom"] = "custom"
    orders: list[BacktestOrderIntent] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DifferentialAuditRequest(BaseModel):
    name: str
    base_request: DerivativesRunRequest
    layers: list[AuditLayerRequest] = Field(min_length=2)
    event_price_tolerance_ticks: float = Field(default=1.0, ge=0)
    pnl_tolerance: float = Field(default=0.01, ge=0)


class AuditDivergence(BaseModel):
    left_layer: str
    right_layer: str
    category: str
    first_sequence: int | None = None
    severity: Literal["info", "warning", "critical"] = "warning"
    detail: str


class DifferentialAuditReport(BaseModel):
    audit_id: str
    fingerprint: str
    name: str
    layers: dict[str, DerivativesReport]
    divergences: list[AuditDivergence] = Field(default_factory=list)
    combined_assessment: dict[str, Any] = Field(default_factory=dict)


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


class BacktestRunRecord(BaseModel):
    run_id: str
    created_at: str
    kind: BacktestRunKind
    asset_class: AssetClass
    symbol: str
    fingerprint: str
    request: dict[str, Any] = Field(default_factory=dict)
    report: BacktestReport
    result: dict[str, Any] = Field(default_factory=dict)


class BacktestSweepRequest(BaseModel):
    base_request: BacktestRunRequest
    stop_loss_pcts: list[float | None] = Field(default_factory=list)
    take_profit_pcts: list[float | None] = Field(default_factory=list)
    leverage_values: list[float] = Field(default_factory=list)


class BacktestSweepResult(BaseModel):
    reports: list[BacktestReport]


class BacktestRange(BaseModel):
    start: str
    end: str


class BacktestWalkForwardRequest(BaseModel):
    base_request: BacktestRunRequest
    train_size: int = Field(gt=0)
    test_size: int = Field(gt=0)
    step_size: int = Field(gt=0)


class BacktestWalkForwardWindow(BaseModel):
    train_range: BacktestRange
    test_range: BacktestRange
    report: BacktestReport


class BacktestWalkForwardResult(BaseModel):
    windows: list[BacktestWalkForwardWindow]


class BacktestStressScenario(BaseModel):
    name: str
    price_shock_pct: float = 0.0
    slippage_bps: float | None = Field(default=None, ge=0)


class BacktestStressRequest(BaseModel):
    base_request: BacktestRunRequest
    scenarios: list[BacktestStressScenario] = Field(default_factory=list)


class BacktestStressResult(BaseModel):
    reports: list[BacktestReport]
