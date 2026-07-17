from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from sentinel_archive.backtesting.models import AssetClass, FundingEvent, MarketPriceBar


class MarketDataProviderInfo(BaseModel):
    provider_id: str
    name: str
    free_access: bool
    authentication: str
    asset_classes: list[str]
    capabilities: list[str]
    limitations: list[str] = Field(default_factory=list)
    homepage: str


class MarketDataFetchRequest(BaseModel):
    provider: str
    symbol: str
    asset_class: AssetClass
    interval: str = "1m"
    start: str | None = None
    end: str | None = None
    limit: int = Field(default=1000, gt=0, le=10000)
    venue: str | None = None
    price_type: str = "trade"
    include_funding: bool = True
    adjusted: bool = False
    dataset_name: str | None = None
    save_dataset: bool = True
    api_key: str | None = Field(default=None, exclude=True)
    api_secret: str | None = Field(default=None, exclude=True)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MarketDataFetchResult(BaseModel):
    provider: str
    symbol: str
    asset_class: AssetClass
    interval: str
    fingerprint: str
    bars: list[MarketPriceBar] = Field(default_factory=list)
    funding_events: list[FundingEvent] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    dataset_id: str | None = None
