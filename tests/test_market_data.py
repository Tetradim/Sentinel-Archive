from __future__ import annotations

from sentinel_archive.market_data.models import MarketDataFetchRequest
from sentinel_archive.market_data.service import MarketDataService


class _Response:
    def __init__(self, payload):
        self._payload = payload
        self.is_success = True

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


class _Client:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def get(self, url, params=None, headers=None):
        self.calls.append((url, params, headers))
        for suffix, payload in self.routes.items():
            if url.endswith(suffix):
                return _Response(payload)
        raise AssertionError(f"unexpected URL {url}")


def test_provider_catalog_contains_free_stock_and_futures_sources():
    providers = {item.provider_id: item for item in MarketDataService().providers()}

    assert {"yfinance", "stooq", "alpaca_iex", "alpha_vantage", "twelve_data"} <= providers.keys()
    assert {"binance_futures", "bybit_futures", "bitunix_futures", "coinbase", "csv_upload"} <= providers.keys()
    assert all(item.free_access for item in providers.values())


def test_binance_trade_bars_and_funding_are_normalized_and_fingerprinted():
    client = _Client(
        {
            "/klines": [[1656678600000, "100", "102", "99", "101", "50", 0, 0, 12]],
            "/fundingRate": [{"fundingTime": 1656678600000, "fundingRate": "0.0001", "markPrice": "101"}],
        }
    )
    service = MarketDataService(client_factory=lambda **_: client)
    result = service.fetch(
        MarketDataFetchRequest(
            provider="binance_futures",
            symbol="BTCUSDT",
            asset_class="crypto_futures",
            interval="1m",
        )
    )

    assert result.bars[0].close == 101
    assert result.bars[0].trade_count == 12
    assert result.funding_events[0].rate == 0.0001
    assert len(result.fingerprint) == 64


def test_bitunix_trade_request_omits_invalid_type_parameter():
    client = _Client(
        {
            "/kline": {
                "data": [
                    {"time": 1656678600000, "open": "100", "high": "102", "low": "99", "close": "101", "baseVol": "50"}
                ]
            }
        }
    )
    service = MarketDataService(client_factory=lambda **_: client)
    result = service.fetch(
        MarketDataFetchRequest(
            provider="bitunix_futures",
            symbol="BTCUSDT",
            asset_class="crypto_futures",
        )
    )

    assert result.bars[0].volume == 50
    assert "type" not in client.calls[0][1]
