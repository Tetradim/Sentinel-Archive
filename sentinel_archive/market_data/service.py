from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from datetime import datetime, timezone
from typing import Any, Callable

import httpx

from sentinel_archive.backtesting.models import FundingEvent, MarketPriceBar
from sentinel_archive.market_data.models import MarketDataFetchRequest, MarketDataFetchResult, MarketDataProviderInfo


PROVIDERS: dict[str, MarketDataProviderInfo] = {
    "yfinance": MarketDataProviderInfo(
        provider_id="yfinance",
        name="Yahoo Finance via yfinance",
        free_access=True,
        authentication="none",
        asset_classes=["stock", "options", "crypto", "futures"],
        capabilities=["ohlcv", "corporate_actions", "recent_intraday"],
        limitations=["unofficial research interface", "intraday depth is limited", "not futures execution truth"],
        homepage="https://ranaroussi.github.io/yfinance/",
    ),
    "stooq": MarketDataProviderInfo(
        provider_id="stooq",
        name="Stooq CSV",
        free_access=True,
        authentication="none",
        asset_classes=["stock", "futures"],
        capabilities=["daily_ohlcv", "csv"],
        limitations=["daily bars only in Archive adapter", "symbol mapping required"],
        homepage="https://stooq.com/",
    ),
    "alpaca_iex": MarketDataProviderInfo(
        provider_id="alpaca_iex",
        name="Alpaca IEX",
        free_access=True,
        authentication="free API key",
        asset_classes=["stock"],
        capabilities=["ohlcv", "vwap", "trade_count"],
        limitations=["IEX is one US venue, not consolidated SIP"],
        homepage="https://docs.alpaca.markets/us/docs/historical-stock-data-1",
    ),
    "alpha_vantage": MarketDataProviderInfo(
        provider_id="alpha_vantage",
        name="Alpha Vantage",
        free_access=True,
        authentication="free API key",
        asset_classes=["stock", "crypto"],
        capabilities=["intraday_ohlcv", "daily_ohlcv"],
        limitations=["free-tier rate limits", "not derivatives execution truth"],
        homepage="https://www.alphavantage.co/documentation/",
    ),
    "twelve_data": MarketDataProviderInfo(
        provider_id="twelve_data",
        name="Twelve Data",
        free_access=True,
        authentication="free API key",
        asset_classes=["stock", "crypto"],
        capabilities=["intraday_ohlcv", "daily_ohlcv"],
        limitations=["free-tier credits and symbol coverage apply"],
        homepage="https://twelvedata.com/docs",
    ),
    "binance_futures": MarketDataProviderInfo(
        provider_id="binance_futures",
        name="Binance Futures Public API",
        free_access=True,
        authentication="none",
        asset_classes=["crypto_futures"],
        capabilities=["trade_ohlcv", "mark_ohlcv", "index_ohlcv", "funding"],
        limitations=["Binance venue semantics", "REST request limits"],
        homepage="https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures",
    ),
    "bybit_futures": MarketDataProviderInfo(
        provider_id="bybit_futures",
        name="Bybit Futures Public API",
        free_access=True,
        authentication="none",
        asset_classes=["crypto_futures"],
        capabilities=["trade_ohlcv", "mark_ohlcv", "index_ohlcv", "funding"],
        limitations=["Bybit venue semantics", "REST request limits"],
        homepage="https://bybit-exchange.github.io/docs/v5/market/kline",
    ),
    "bitunix_futures": MarketDataProviderInfo(
        provider_id="bitunix_futures",
        name="BitUnix Futures Public API",
        free_access=True,
        authentication="none for klines",
        asset_classes=["crypto_futures"],
        capabilities=["trade_ohlcv", "mark_ohlcv"],
        limitations=["200 bars per request", "funding history availability is venue-defined"],
        homepage="https://www.bitunix.com/api-docs/futures/market/get_kline.html",
    ),
    "coinbase": MarketDataProviderInfo(
        provider_id="coinbase",
        name="Coinbase Exchange Public Candles",
        free_access=True,
        authentication="none",
        asset_classes=["crypto"],
        capabilities=["spot_ohlcv"],
        limitations=["spot only", "300 candles per request"],
        homepage="https://docs.cdp.coinbase.com/exchange/reference/exchangerestapi_getproductcandles",
    ),
    "csv_upload": MarketDataProviderInfo(
        provider_id="csv_upload",
        name="Local Archive Dataset Import",
        free_access=True,
        authentication="none",
        asset_classes=["stock", "options", "crypto", "crypto_futures", "futures"],
        capabilities=["ohlcv_csv", "direct_dataset_api", "bid_ask", "mark_index", "custom_fields"],
        limitations=["quality depends on supplied file"],
        homepage="local://archive",
    ),
}


class MarketDataService:
    def __init__(self, client_factory: Callable[..., httpx.Client] | None = None):
        self.client_factory = client_factory or httpx.Client

    def providers(self) -> list[MarketDataProviderInfo]:
        return list(PROVIDERS.values())

    def fetch(self, request: MarketDataFetchRequest) -> MarketDataFetchResult:
        provider = request.provider.lower().strip()
        if provider not in PROVIDERS or provider == "csv_upload":
            raise ValueError(f"unsupported fetch provider: {request.provider}")
        fetcher = getattr(self, f"_fetch_{provider}", None)
        if fetcher is None:
            raise ValueError(f"provider is cataloged but has no fetch adapter: {provider}")
        result: MarketDataFetchResult = fetcher(request)
        if not result.bars:
            raise ValueError(f"{provider} returned no bars for {request.symbol}")
        _validate_bars(result.bars)
        payload = {
            "provider": result.provider,
            "symbol": result.symbol,
            "asset_class": result.asset_class,
            "interval": result.interval,
            "bars": [bar.model_dump(mode="json") for bar in result.bars],
            "funding_events": [event.model_dump(mode="json") for event in result.funding_events],
        }
        result.fingerprint = _fingerprint(payload)
        result.metadata = {
            **result.metadata,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "bar_count": len(result.bars),
            "first_timestamp": result.bars[0].timestamp,
            "last_timestamp": result.bars[-1].timestamp,
            "immutable_fingerprint": result.fingerprint,
        }
        return result

    def _client(self) -> httpx.Client:
        return self.client_factory(timeout=30, follow_redirects=True, headers={"User-Agent": "Sentinel-Archive/0.1"})

    def _fetch_yfinance(self, request: MarketDataFetchRequest) -> MarketDataFetchResult:
        import yfinance as yf

        frame = yf.download(
            request.symbol,
            start=request.start,
            end=request.end,
            interval=request.interval,
            auto_adjust=request.adjusted,
            progress=False,
            threads=False,
        )
        if getattr(frame.columns, "nlevels", 1) > 1:
            frame.columns = frame.columns.get_level_values(0)
        bars: list[MarketPriceBar] = []
        for stamp, row in frame.iterrows():
            bars.append(
                MarketPriceBar(
                    timestamp=_iso(stamp),
                    symbol=request.symbol.upper(),
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=float(row.get("Volume", 0) or 0),
                )
            )
        return _result(request, bars, metadata={"adjusted": request.adjusted, "source": "Yahoo Finance"})

    def _fetch_stooq(self, request: MarketDataFetchRequest) -> MarketDataFetchResult:
        symbol = request.symbol.lower()
        if "." not in symbol and request.asset_class == "stock":
            symbol = f"{symbol}.us"
        params = {"s": symbol, "i": "d"}
        if request.start:
            params["d1"] = _date_compact(request.start)
        if request.end:
            params["d2"] = _date_compact(request.end)
        with self._client() as client:
            response = client.get("https://stooq.com/q/d/l/", params=params)
            response.raise_for_status()
        reader = csv.DictReader(io.StringIO(response.text))
        bars = [
            MarketPriceBar(
                timestamp=f"{row['Date']}T00:00:00Z",
                symbol=request.symbol.upper(),
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=float(row.get("Volume") or 0),
            )
            for row in reader
            if row.get("Date") and row.get("Open") not in {None, "N/D"}
        ]
        return _result(request, bars, warnings=["stooq_daily_only"], metadata={"source_symbol": symbol})

    def _fetch_alpaca_iex(self, request: MarketDataFetchRequest) -> MarketDataFetchResult:
        key = request.api_key or os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID")
        secret = request.api_secret or os.getenv("ALPACA_API_SECRET") or os.getenv("APCA_API_SECRET_KEY")
        if not key or not secret:
            raise ValueError("Alpaca IEX requires ALPACA_API_KEY and ALPACA_API_SECRET")
        params: dict[str, Any] = {"timeframe": _alpaca_interval(request.interval), "feed": "iex", "limit": request.limit}
        if request.start:
            params["start"] = request.start
        if request.end:
            params["end"] = request.end
        with self._client() as client:
            response = client.get(
                f"https://data.alpaca.markets/v2/stocks/{request.symbol.upper()}/bars",
                params=params,
                headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
            )
            response.raise_for_status()
            payload = response.json()
        bars = [_alpaca_bar(request.symbol, item) for item in payload.get("bars", [])]
        return _result(request, bars, warnings=["iex_single_venue_volume"], metadata={"feed": "iex"})

    def _fetch_alpha_vantage(self, request: MarketDataFetchRequest) -> MarketDataFetchResult:
        key = request.api_key or os.getenv("ALPHA_VANTAGE_API_KEY")
        if not key:
            raise ValueError("Alpha Vantage requires ALPHA_VANTAGE_API_KEY")
        intraday = request.interval.lower() not in {"1d", "1day", "day", "daily"}
        interval = _alpha_interval(request.interval) if intraday else None
        params = {
            "function": "TIME_SERIES_INTRADAY" if intraday else "TIME_SERIES_DAILY",
            "symbol": request.symbol,
            "apikey": key,
            "outputsize": "full",
            "datatype": "json",
        }
        if intraday:
            params["interval"] = interval
        with self._client() as client:
            response = client.get("https://www.alphavantage.co/query", params=params)
            response.raise_for_status()
            payload = response.json()
        series_key = next((key for key in payload if "Time Series" in key), None)
        if series_key is None:
            raise ValueError(payload.get("Note") or payload.get("Information") or payload.get("Error Message") or "Alpha Vantage returned no time series")
        bars = []
        for stamp, item in payload[series_key].items():
            bars.append(
                MarketPriceBar(
                    timestamp=_iso(stamp),
                    symbol=request.symbol.upper(),
                    open=float(item["1. open"]),
                    high=float(item["2. high"]),
                    low=float(item["3. low"]),
                    close=float(item["4. close"]),
                    volume=float(item.get("5. volume", 0)),
                )
            )
        return _result(request, sorted(bars, key=lambda bar: bar.timestamp), warnings=["free_tier_rate_limits"])

    def _fetch_twelve_data(self, request: MarketDataFetchRequest) -> MarketDataFetchResult:
        key = request.api_key or os.getenv("TWELVE_DATA_API_KEY")
        if not key:
            raise ValueError("Twelve Data requires TWELVE_DATA_API_KEY")
        params: dict[str, Any] = {
            "symbol": request.symbol,
            "interval": _twelve_interval(request.interval),
            "apikey": key,
            "outputsize": min(request.limit, 5000),
            "timezone": "UTC",
            "order": "ASC",
        }
        if request.start:
            params["start_date"] = request.start
        if request.end:
            params["end_date"] = request.end
        with self._client() as client:
            response = client.get("https://api.twelvedata.com/time_series", params=params)
            response.raise_for_status()
            payload = response.json()
        if payload.get("status") == "error":
            raise ValueError(payload.get("message", "Twelve Data request failed"))
        bars = [
            MarketPriceBar(
                timestamp=_iso(item["datetime"]),
                symbol=request.symbol.upper(),
                open=float(item["open"]),
                high=float(item["high"]),
                low=float(item["low"]),
                close=float(item["close"]),
                volume=float(item.get("volume") or 0),
            )
            for item in payload.get("values", [])
        ]
        return _result(request, bars, warnings=["free_tier_credits_apply"])

    def _fetch_binance_futures(self, request: MarketDataFetchRequest) -> MarketDataFetchResult:
        path = {"mark": "markPriceKlines", "index": "indexPriceKlines"}.get(request.price_type, "klines")
        params: dict[str, Any] = {
            ("pair" if path == "indexPriceKlines" else "symbol"): request.symbol.upper(),
            "interval": request.interval,
            "limit": min(request.limit, 1500),
        }
        if request.start:
            params["startTime"] = _epoch_ms(request.start)
        if request.end:
            params["endTime"] = _epoch_ms(request.end)
        with self._client() as client:
            response = client.get(f"https://fapi.binance.com/fapi/v1/{path}", params=params)
            response.raise_for_status()
            payload = response.json()
            funding_payload: list[dict[str, Any]] = []
            if request.include_funding:
                funding_params = {"symbol": request.symbol.upper(), "limit": 1000}
                if request.start:
                    funding_params["startTime"] = _epoch_ms(request.start)
                if request.end:
                    funding_params["endTime"] = _epoch_ms(request.end)
                funding_response = client.get("https://fapi.binance.com/fapi/v1/fundingRate", params=funding_params)
                if funding_response.is_success:
                    funding_payload = funding_response.json()
        bars = [_binance_bar(request, item, path) for item in payload]
        funding = [
            FundingEvent(timestamp=_iso_epoch(item["fundingTime"]), rate=float(item["fundingRate"]), mark_price=_optional_float(item.get("markPrice")))
            for item in funding_payload
        ]
        return _result(request, bars, funding=funding, metadata={"price_type": request.price_type, "venue": "binance"})

    def _fetch_bybit_futures(self, request: MarketDataFetchRequest) -> MarketDataFetchResult:
        endpoint = {"mark": "mark-price-kline", "index": "index-price-kline"}.get(request.price_type, "kline")
        params: dict[str, Any] = {
            "category": request.venue or "linear",
            "symbol": request.symbol.upper(),
            "interval": _bybit_interval(request.interval),
            "limit": min(request.limit, 1000),
        }
        if request.start:
            params["start"] = _epoch_ms(request.start)
        if request.end:
            params["end"] = _epoch_ms(request.end)
        with self._client() as client:
            response = client.get(f"https://api.bybit.com/v5/market/{endpoint}", params=params)
            response.raise_for_status()
            payload = response.json()
            funding_payload: dict[str, Any] = {}
            if request.include_funding:
                funding_response = client.get(
                    "https://api.bybit.com/v5/market/funding/history",
                    params={"category": params["category"], "symbol": request.symbol.upper(), "limit": 200},
                )
                if funding_response.is_success:
                    funding_payload = funding_response.json()
        if payload.get("retCode") not in {None, 0}:
            raise ValueError(payload.get("retMsg", "Bybit request failed"))
        rows = list(reversed(payload.get("result", {}).get("list", [])))
        bars = [_bybit_bar(request, item, endpoint) for item in rows]
        funding = [
            FundingEvent(timestamp=_iso_epoch(item["fundingRateTimestamp"]), rate=float(item["fundingRate"]))
            for item in reversed(funding_payload.get("result", {}).get("list", []))
        ]
        return _result(request, bars, funding=funding, metadata={"price_type": request.price_type, "venue": "bybit"})

    def _fetch_bitunix_futures(self, request: MarketDataFetchRequest) -> MarketDataFetchResult:
        params: dict[str, Any] = {
            "symbol": request.symbol.upper(),
            "interval": request.interval,
            "limit": min(request.limit, 200),
        }
        if request.price_type.lower() != "trade":
            params["type"] = request.price_type.upper()
        if request.start:
            params["startTime"] = _epoch_ms(request.start)
        if request.end:
            params["endTime"] = _epoch_ms(request.end)
        with self._client() as client:
            response = client.get("https://fapi.bitunix.com/api/v1/futures/market/kline", params=params)
            response.raise_for_status()
            payload = response.json()
        rows = payload.get("data", [])
        if not isinstance(rows, list):
            raise ValueError("BitUnix kline response missing data list")
        bars = [
            MarketPriceBar(
                timestamp=_iso_epoch(item.get("time") or item.get("timestamp")),
                symbol=request.symbol.upper(),
                open=float(item.get("open") or item["close"]),
                high=float(item["high"]),
                low=float(item["low"]),
                close=float(item["close"]),
                volume=float(item.get("baseVol") or item.get("volume") or 0),
            )
            for item in rows
        ]
        return _result(request, sorted(bars, key=lambda bar: bar.timestamp), warnings=["bitunix_200_bar_limit"], metadata={"venue": "bitunix"})

    def _fetch_coinbase(self, request: MarketDataFetchRequest) -> MarketDataFetchResult:
        params: dict[str, Any] = {"granularity": _coinbase_granularity(request.interval)}
        if request.start:
            params["start"] = request.start
        if request.end:
            params["end"] = request.end
        with self._client() as client:
            response = client.get(f"https://api.exchange.coinbase.com/products/{request.symbol.upper()}/candles", params=params)
            response.raise_for_status()
            payload = response.json()
        bars = [
            MarketPriceBar(
                timestamp=_iso_epoch(item[0]),
                symbol=request.symbol.upper(),
                low=float(item[1]),
                high=float(item[2]),
                open=float(item[3]),
                close=float(item[4]),
                volume=float(item[5]),
            )
            for item in reversed(payload)
        ]
        return _result(request, bars, warnings=["coinbase_spot_only", "coinbase_300_candle_limit"], metadata={"venue": "coinbase"})


def _result(
    request: MarketDataFetchRequest,
    bars: list[MarketPriceBar],
    *,
    funding: list[FundingEvent] | None = None,
    warnings: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> MarketDataFetchResult:
    return MarketDataFetchResult(
        provider=request.provider.lower(),
        symbol=request.symbol.upper(),
        asset_class=request.asset_class,
        interval=request.interval,
        fingerprint="pending",
        bars=bars,
        funding_events=funding or [],
        warnings=warnings or [],
        metadata={**request.metadata, **(metadata or {})},
    )


def _validate_bars(bars: list[MarketPriceBar]) -> None:
    previous = ""
    for bar in bars:
        if bar.low > min(bar.open, bar.close, bar.high) or bar.high < max(bar.open, bar.close, bar.low):
            raise ValueError(f"invalid OHLC range at {bar.timestamp}")
        if previous and bar.timestamp < previous:
            raise ValueError("provider returned out-of-order bars")
        if bar.bid is not None and bar.ask is not None and bar.bid > bar.ask:
            raise ValueError(f"crossed bid/ask at {bar.timestamp}")
        previous = bar.timestamp


def _alpaca_bar(symbol: str, item: dict[str, Any]) -> MarketPriceBar:
    return MarketPriceBar(
        timestamp=_iso(item["t"]),
        symbol=symbol.upper(),
        open=float(item["o"]),
        high=float(item["h"]),
        low=float(item["l"]),
        close=float(item["c"]),
        volume=float(item.get("v", 0)),
        vwap=_optional_float(item.get("vw")),
        trade_count=item.get("n"),
    )


def _binance_bar(request: MarketDataFetchRequest, item: list[Any], path: str) -> MarketPriceBar:
    extra = {}
    if path == "markPriceKlines":
        extra["mark_price"] = float(item[4])
    if path == "indexPriceKlines":
        extra["index_price"] = float(item[4])
    return MarketPriceBar(
        timestamp=_iso_epoch(item[0]),
        symbol=request.symbol.upper(),
        open=float(item[1]),
        high=float(item[2]),
        low=float(item[3]),
        close=float(item[4]),
        volume=float(item[5] or 0),
        trade_count=int(item[8]) if len(item) > 8 and str(item[8]).isdigit() else None,
        **extra,
    )


def _bybit_bar(request: MarketDataFetchRequest, item: list[Any], endpoint: str) -> MarketPriceBar:
    extra = {}
    if endpoint == "mark-price-kline":
        extra["mark_price"] = float(item[4])
    if endpoint == "index-price-kline":
        extra["index_price"] = float(item[4])
    return MarketPriceBar(
        timestamp=_iso_epoch(item[0]),
        symbol=request.symbol.upper(),
        open=float(item[1]),
        high=float(item[2]),
        low=float(item[3]),
        close=float(item[4]),
        volume=float(item[5]) if len(item) > 5 else 0.0,
        **extra,
    )


def _iso(value: Any) -> str:
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        stamp = value
    else:
        text = str(value).replace("Z", "+00:00")
        try:
            stamp = datetime.fromisoformat(text)
        except ValueError:
            stamp = datetime.fromisoformat(f"{text}+00:00")
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _iso_epoch(value: Any) -> str:
    raw = float(value)
    if raw > 10_000_000_000:
        raw /= 1000
    return datetime.fromtimestamp(raw, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _epoch_ms(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


def _date_compact(value: str) -> str:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%Y%m%d")


def _alpaca_interval(value: str) -> str:
    mapping = {"1m": "1Min", "5m": "5Min", "15m": "15Min", "30m": "30Min", "1h": "1Hour", "1d": "1Day"}
    return mapping.get(value.lower(), value)


def _alpha_interval(value: str) -> str:
    mapping = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min", "1h": "60min"}
    if value.lower() not in mapping:
        raise ValueError(f"Alpha Vantage does not support Archive interval {value}")
    return mapping[value.lower()]


def _twelve_interval(value: str) -> str:
    mapping = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min", "1h": "1h", "1d": "1day"}
    return mapping.get(value.lower(), value)


def _bybit_interval(value: str) -> str:
    mapping = {"1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30", "1h": "60", "2h": "120", "4h": "240", "1d": "D"}
    return mapping.get(value.lower(), value)


def _coinbase_granularity(value: str) -> int:
    mapping = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "6h": 21600, "1d": 86400}
    if value.lower() not in mapping:
        raise ValueError(f"Coinbase does not support Archive interval {value}")
    return mapping[value.lower()]


def _optional_float(value: Any) -> float | None:
    return None if value in {None, ""} else float(value)


def _fingerprint(payload: object) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
