from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


AssetClass = Literal["stock", "future", "crypto", "option", "forex", "other"]
ParticipantRole = Literal["trader", "observer", "risk_controller"]
OrderSide = Literal["buy", "sell"]
OrderType = Literal["market", "limit", "stop"]
OrderStatus = Literal[
    "accepted",
    "partially_filled",
    "filled",
    "canceled",
    "rejected",
]
DirectiveType = Literal[
    "halt_new_orders",
    "resume_new_orders",
    "flatten_requested",
    "risk_warning",
    "market_regime",
]


def normalize_symbol(value: Any) -> str:
    symbol = str(value or "").strip().upper()
    if not symbol:
        raise ValueError("symbol is required")
    return symbol


class InstrumentSpec(BaseModel):
    symbol: str
    asset_class: AssetClass = "stock"
    multiplier: Decimal = Field(default=Decimal("1"), gt=0)
    tick_size: Decimal = Field(default=Decimal("0.01"), gt=0)
    initial_margin: Decimal = Field(default=Decimal("0"), ge=0)
    currency: str = "USD"
    shortable: bool = True
    max_volume_participation_pct: Decimal = Field(default=Decimal("100"), gt=0, le=100)

    _normalize_symbol = field_validator("symbol", mode="before")(normalize_symbol)


class DatasetImportRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    csv_text: str = Field(min_length=1)
    data_kind: Literal["recorded", "synthetic"]
    source_name: str = Field(min_length=1, max_length=160)
    source_url: str | None = None
    retrieved_at: str | None = None
    notes: str = ""
    instruments: list[InstrumentSpec] = Field(default_factory=list)


class DatasetSummary(BaseModel):
    dataset_id: str
    name: str
    data_kind: Literal["recorded", "synthetic"]
    source_name: str
    source_url: str | None = None
    retrieved_at: str | None = None
    notes: str = ""
    checksum_sha256: str
    symbols: list[str]
    bar_count: int
    first_timestamp: str
    last_timestamp: str
    instruments: list[InstrumentSpec]


class CreateRunRequest(BaseModel):
    dataset_id: str
    name: str = Field(default="General API replay", min_length=1, max_length=160)
    speed: float = Field(default=1.0, gt=0, le=10000)
    loop: bool = False


class ReplayRun(BaseModel):
    run_id: str
    dataset_id: str
    name: str
    state: Literal["ready", "running", "stopped", "completed"] = "ready"
    speed: float = 1.0
    loop: bool = False
    index: int = 0
    current_timestamp: str | None = None
    participant_ids: list[str] = Field(default_factory=list)
    latest_sequence: int = 0


class RegisterParticipantRequest(BaseModel):
    participant_id: str | None = Field(default=None, min_length=1, max_length=100)
    bot_id: str = Field(min_length=1, max_length=100)
    display_name: str | None = Field(default=None, max_length=160)
    roles: list[ParticipantRole] = Field(default_factory=lambda: ["trader"])
    subscribed_symbols: list[str] = Field(default_factory=list)
    starting_cash: Decimal = Field(default=Decimal("100000"), gt=0)
    commission_per_order: Decimal = Field(default=Decimal("0"), ge=0)
    slippage_bps: Decimal = Field(default=Decimal("0"), ge=0)

    @field_validator("subscribed_symbols", mode="before")
    @classmethod
    def normalize_symbols(cls, value: Any) -> list[str]:
        return [normalize_symbol(symbol) for symbol in (value or [])]


class Participant(BaseModel):
    participant_id: str
    bot_id: str
    display_name: str
    roles: list[ParticipantRole]
    subscribed_symbols: list[str]
    starting_cash: Decimal
    commission_per_order: Decimal
    slippage_bps: Decimal
    new_orders_halted: bool = False
    acknowledged_directive_ids: list[str] = Field(default_factory=list)


class ParticipantRegistration(BaseModel):
    participant: Participant
    api_token: str
    token_header: str = "X-Archive-Bot-Token"


class SubmitOrderRequest(BaseModel):
    client_order_id: str = Field(min_length=1, max_length=160)
    symbol: str
    side: OrderSide
    quantity: Decimal = Field(gt=0)
    order_type: OrderType = "market"
    limit_price: Decimal | None = Field(default=None, gt=0)
    stop_price: Decimal | None = Field(default=None, gt=0)
    time_in_force: Literal["day", "gtc", "ioc"] = "day"
    reduce_only: bool = False
    oco_group: str | None = Field(default=None, max_length=160)
    strategy_id: str | None = Field(default=None, max_length=160)
    metadata: dict[str, Any] = Field(default_factory=dict)

    _normalize_symbol = field_validator("symbol", mode="before")(normalize_symbol)

    @model_validator(mode="after")
    def validate_prices(self) -> "SubmitOrderRequest":
        if self.order_type == "limit" and self.limit_price is None:
            raise ValueError("limit_price is required for a limit order")
        if self.order_type == "stop" and self.stop_price is None:
            raise ValueError("stop_price is required for a stop order")
        return self

    model_config = ConfigDict(extra="forbid")


class BrokerOrder(BaseModel):
    order_id: str
    run_id: str
    participant_id: str
    bot_id: str
    client_order_id: str
    symbol: str
    side: OrderSide
    quantity: Decimal
    filled_quantity: Decimal = Decimal("0")
    remaining_quantity: Decimal
    order_type: OrderType
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    time_in_force: Literal["day", "gtc", "ioc"] = "day"
    reduce_only: bool = False
    oco_group: str | None = None
    strategy_id: str | None = None
    status: OrderStatus = "accepted"
    submitted_at: str | None = None
    submitted_sequence: int
    updated_at: str | None = None
    rejection_reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    submitted_payload: dict[str, Any] = Field(default_factory=dict)


class BrokerFill(BaseModel):
    fill_id: str
    order_id: str
    run_id: str
    participant_id: str
    bot_id: str
    symbol: str
    side: OrderSide
    quantity: Decimal
    price: Decimal
    commission: Decimal
    multiplier: Decimal
    virtual_timestamp: str
    sequence: int


class BrokerPosition(BaseModel):
    symbol: str
    asset_class: AssetClass
    quantity: Decimal
    average_entry_price: Decimal
    market_price: Decimal
    multiplier: Decimal
    realized_pnl: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")


class AccountSnapshot(BaseModel):
    participant_id: str
    bot_id: str
    starting_cash: Decimal
    cash: Decimal
    equity: Decimal
    buying_power: Decimal
    margin_used: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    total_pnl: Decimal
    return_pct: Decimal
    commission_paid: Decimal
    positions: list[BrokerPosition]
    order_count: int
    fill_count: int
    new_orders_halted: bool


class PublishDirectiveRequest(BaseModel):
    directive_type: DirectiveType
    target_participant_ids: list[str] = Field(default_factory=list)
    target_bot_ids: list[str] = Field(default_factory=list)
    symbol: str | None = None
    reason: str = Field(min_length=1, max_length=1000)
    severity: Literal["info", "warning", "critical"] = "warning"
    expires_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("symbol", mode="before")
    @classmethod
    def normalize_optional_symbol(cls, value: Any) -> str | None:
        return normalize_symbol(value) if value else None


class ControlDirective(BaseModel):
    directive_id: str
    run_id: str
    source_participant_id: str
    source_bot_id: str
    directive_type: DirectiveType
    target_participant_ids: list[str]
    target_bot_ids: list[str]
    symbol: str | None = None
    reason: str
    severity: Literal["info", "warning", "critical"]
    created_at: str | None = None
    expires_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    acknowledged_by: list[str] = Field(default_factory=list)


class BotObservationRequest(BaseModel):
    event_type: str = Field(min_length=1, max_length=160)
    symbol: str | None = None
    decision: str | None = Field(default=None, max_length=160)
    reason: str = Field(default="", max_length=2000)
    confidence: Decimal | None = Field(default=None, ge=0, le=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("symbol", mode="before")
    @classmethod
    def normalize_optional_symbol(cls, value: Any) -> str | None:
        return normalize_symbol(value) if value else None


class GeneralEvent(BaseModel):
    sequence: int
    run_id: str
    event_type: str
    virtual_timestamp: str | None = None
    participant_id: str | None = None
    bot_id: str | None = None
    symbol: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
