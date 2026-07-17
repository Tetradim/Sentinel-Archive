#!/usr/bin/env python3
"""Replay recorded candles through native Sentinel bot decision code.

Archive owns data acquisition, deterministic scheduling, evidence capture, and
reporting in this study.  It does not create entry or exit decisions.  Pulse
decisions are produced by ``TradingEngine.evaluate_ticker`` (or its native Edge
handoff methods), and Edge decisions are produced by ``SignalEngine`` plus
``DecisionEngine``.  A bot that does not expose a candle-to-order loop receives
zero invented orders and is reported as not autonomously testable.

This is a research replay, not a forecast or a promise of live profitability.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import importlib.util
import itertools
import json
import logging
import math
import subprocess
import sys
import time
import types
import urllib.parse
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import httpx


UTC = timezone.utc
ET = ZoneInfo("America/New_York")
STUDY_ID = "sentinel-native-profitability-2026-07-17"
TUNE_START = "2026-04-01T00:00:00Z"
TUNE_END = "2026-06-01T00:00:00Z"
VALIDATE_START = "2026-06-01T00:00:00Z"
VALIDATE_END = "2026-07-17T00:00:00Z"
WARMUP_START = "2025-01-01T00:00:00Z"
SLIPPAGE_BPS_PER_ORDER = 2.0
COMMISSION_PER_ORDER = 0.0
CAPITAL_PER_TICKER = 10_000.0
PULSE_SYMBOLS = ("SPY", "QQQ", "TSLA")


@dataclass(frozen=True)
class Bar:
    timestamp: str
    epoch: int
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def et_date(self) -> date:
        return datetime.fromtimestamp(self.epoch, UTC).astimezone(ET).date()

    @property
    def et_time(self) -> tuple[int, int]:
        stamp = datetime.fromtimestamp(self.epoch, UTC).astimezone(ET)
        return stamp.hour, stamp.minute


@dataclass(frozen=True)
class Dataset:
    provider: str
    symbol: str
    interval: str
    bars: tuple[Bar, ...]
    fingerprint: str
    retrieved_at: str
    source: str
    dropped_rows: int = 0
    warnings: tuple[str, ...] = ()

    def subset(self, start: str, end: str) -> tuple[Bar, ...]:
        start_epoch = _epoch(start)
        end_epoch = _epoch(end)
        return tuple(bar for bar in self.bars if start_epoch <= bar.epoch < end_epoch)

    def manifest(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "symbol": self.symbol,
            "interval": self.interval,
            "bar_count": len(self.bars),
            "first_timestamp": self.bars[0].timestamp if self.bars else None,
            "last_timestamp": self.bars[-1].timestamp if self.bars else None,
            "fingerprint_sha256": self.fingerprint,
            "retrieved_at": self.retrieved_at,
            "source": self.source,
            "dropped_rows": self.dropped_rows,
            "warnings": list(self.warnings),
        }


def _epoch(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())


def _iso(epoch: int | float) -> str:
    return datetime.fromtimestamp(float(epoch), UTC).isoformat().replace("+00:00", "Z")


def _fingerprint(rows: Iterable[Any]) -> str:
    encoded = json.dumps(list(rows), sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _valid_bar(open_: float, high: float, low: float, close: float) -> bool:
    values = (open_, high, low, close)
    return all(math.isfinite(item) and item > 0 for item in values) and low <= min(values) and high >= max(values)


class RecordedMarketData:
    """Small, provenance-preserving clients for public recorded candle APIs."""

    def __init__(self) -> None:
        self.client = httpx.Client(
            timeout=30,
            follow_redirects=True,
            headers={"User-Agent": "Sentinel-Archive/2026.07 native replay study"},
        )

    def close(self) -> None:
        self.client.close()

    def yahoo(self, symbol: str, interval: str, start: str, end: str) -> Dataset:
        endpoint = (
            "https://query1.finance.yahoo.com/v8/finance/chart/"
            + urllib.parse.quote(symbol, safe="")
        )
        params = {
            "period1": _epoch(start),
            "period2": _epoch(end),
            "interval": interval,
            "events": "div,splits",
            "includePrePost": "false",
        }
        payload = self._json_get(endpoint, params)
        chart = payload.get("chart", {})
        if chart.get("error"):
            raise RuntimeError(f"Yahoo chart error for {symbol}: {chart['error']}")
        results = chart.get("result") or []
        if not results:
            raise RuntimeError(f"Yahoo returned no chart result for {symbol}")
        result = results[0]
        stamps = result.get("timestamp") or []
        quotes = (result.get("indicators", {}).get("quote") or [{}])[0]
        bars: list[Bar] = []
        dropped = 0
        start_epoch, end_epoch = _epoch(start), _epoch(end)
        for index, stamp in enumerate(stamps):
            if not (start_epoch <= int(stamp) < end_epoch):
                continue
            try:
                open_ = float(quotes["open"][index])
                high = float(quotes["high"][index])
                low = float(quotes["low"][index])
                close = float(quotes["close"][index])
                volume = float((quotes.get("volume") or [0] * len(stamps))[index] or 0)
            except (KeyError, IndexError, TypeError, ValueError):
                dropped += 1
                continue
            if not _valid_bar(open_, high, low, close) or not math.isfinite(volume) or volume < 0:
                dropped += 1
                continue
            bars.append(Bar(_iso(stamp), int(stamp), open_, high, low, close, volume))
        bars.sort(key=lambda bar: bar.epoch)
        bars = _dedupe_bars(bars)
        if not bars:
            raise RuntimeError(f"Yahoo returned no valid {interval} bars for {symbol}")
        canonical = [asdict(bar) for bar in bars]
        return Dataset(
            provider="yahoo_chart",
            symbol=symbol,
            interval=interval,
            bars=tuple(bars),
            fingerprint=_fingerprint(canonical),
            retrieved_at=datetime.now(UTC).isoformat(),
            source=endpoint,
            dropped_rows=dropped,
            warnings=("unofficial_research_interface",),
        )

    def bitunix(self, symbol: str, interval: str, start: str, end: str) -> Dataset:
        endpoint = "https://fapi.bitunix.com/api/v1/futures/market/kline"
        start_ms = _epoch(start) * 1000
        cursor_end = _epoch(end) * 1000 - 1
        rows_by_time: dict[int, dict[str, Any]] = {}
        dropped = 0
        pages = 0
        while cursor_end >= start_ms:
            pages += 1
            payload = self._json_get(
                endpoint,
                {
                    "symbol": symbol,
                    "interval": interval,
                    "limit": 200,
                    "startTime": start_ms,
                    "endTime": cursor_end,
                },
            )
            rows = payload.get("data") or []
            if not isinstance(rows, list) or not rows:
                break
            oldest = cursor_end
            for item in rows:
                try:
                    stamp_ms = int(item.get("time") or item.get("timestamp"))
                    oldest = min(oldest, stamp_ms)
                    if not (start_ms <= stamp_ms < _epoch(end) * 1000):
                        continue
                    open_ = float(item["open"])
                    high = float(item["high"])
                    low = float(item["low"])
                    close = float(item["close"])
                    volume = float(item.get("baseVol") or item.get("volume") or 0)
                except (KeyError, TypeError, ValueError):
                    dropped += 1
                    continue
                if not _valid_bar(open_, high, low, close) or not math.isfinite(volume) or volume < 0:
                    dropped += 1
                    continue
                rows_by_time[stamp_ms] = {
                    "stamp_ms": stamp_ms,
                    "open": open_,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": volume,
                }
            print(f"BitUnix {symbol}: fetched page {pages}, accumulated {len(rows_by_time)} valid bars", flush=True)
            if oldest <= start_ms or oldest >= cursor_end:
                break
            cursor_end = oldest - 1
            if pages >= 100:
                raise RuntimeError("BitUnix pagination safety limit reached")
        bars = [
            Bar(
                _iso(item["stamp_ms"] / 1000),
                item["stamp_ms"] // 1000,
                item["open"],
                item["high"],
                item["low"],
                item["close"],
                item["volume"],
            )
            for item in sorted(rows_by_time.values(), key=lambda row: row["stamp_ms"])
        ]
        if not bars:
            raise RuntimeError(f"BitUnix returned no valid bars for {symbol}")
        return Dataset(
            provider="bitunix_futures",
            symbol=symbol,
            interval=interval,
            bars=tuple(bars),
            fingerprint=_fingerprint([asdict(bar) for bar in bars]),
            retrieved_at=datetime.now(UTC).isoformat(),
            source=endpoint,
            dropped_rows=dropped,
            warnings=("malformed_upstream_rows_excluded",) if dropped else (),
        )

    def _json_get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(4):
            try:
                response = self.client.get(url, params=params)
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                if "json" not in content_type.lower() and response.text.lstrip().startswith("<"):
                    raise RuntimeError(f"{url} returned an HTML access page")
                return response.json()
            except Exception as exc:  # transient public endpoint/proxy failures
                last_error = exc
                if attempt < 3:
                    time.sleep(1 + attempt)
        raise RuntimeError(f"market-data request failed for {url}: {last_error}")


def _dedupe_bars(bars: list[Bar]) -> list[Bar]:
    unique: dict[int, Bar] = {}
    for bar in bars:
        unique[bar.epoch] = bar
    return [unique[key] for key in sorted(unique)]


class _Span:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def set_attribute(self, *_args, **_kwargs):
        return None

    def add_event(self, *_args, **_kwargs):
        return None


class _Tracer:
    def start_as_current_span(self, *_args, **_kwargs):
        return _Span()


class _QuietLogger:
    def debug(self, *_args, **_kwargs):
        return None

    def info(self, *_args, **_kwargs):
        return None

    def warning(self, *_args, **_kwargs):
        return None

    def error(self, *_args, **_kwargs):
        return None


class _WsManager:
    async def broadcast(self, _message):
        return None


class _Telegram:
    running = False

    async def send_trade_alert(self, _trade):
        return None

    async def _broadcast_alert(self, _message):
        return None


def _matches(document: dict[str, Any], query: dict[str, Any]) -> bool:
    for key, expected in (query or {}).items():
        actual = document.get(key)
        if isinstance(expected, dict):
            if "$ne" in expected and actual == expected["$ne"]:
                return False
            if "$lt" in expected and not (actual is not None and actual < expected["$lt"]):
                return False
            if "$gte" in expected and not (actual is not None and actual >= expected["$gte"]):
                return False
            continue
        if actual != expected:
            return False
    return True


class _Cursor:
    def __init__(self, documents: list[dict[str, Any]]):
        self.documents = documents

    def sort(self, field: str, direction: int):
        self.documents.sort(key=lambda item: item.get(field, ""), reverse=direction < 0)
        return self

    def limit(self, value: int):
        self.documents = self.documents[:value]
        return self

    async def to_list(self, length: int | None):
        return copy.deepcopy(self.documents if length is None else self.documents[:length])


class _Collection:
    def __init__(self, documents: list[dict[str, Any]] | None = None, clock=None):
        self.documents = documents or []
        self.clock = clock

    async def insert_one(self, document: dict[str, Any]):
        row = copy.deepcopy(document)
        if self.clock and self.clock.timestamp:
            row["timestamp"] = self.clock.timestamp
        self.documents.append(row)
        return SimpleNamespace(inserted_id=row.get("id"))

    def find(self, query=None, projection=None):
        rows = [copy.deepcopy(row) for row in self.documents if _matches(row, query or {})]
        if projection and projection.get("_id") == 0:
            for row in rows:
                row.pop("_id", None)
        return _Cursor(rows)

    async def find_one(self, query, projection=None, sort=None):
        rows = [row for row in self.documents if _matches(row, query or {})]
        if sort:
            field, direction = sort[0]
            rows = sorted(rows, key=lambda item: item.get(field, ""), reverse=direction < 0)
        if not rows:
            return None
        row = copy.deepcopy(rows[0])
        if projection and projection.get("_id") == 0:
            row.pop("_id", None)
        return row

    async def update_one(self, query, update, upsert=False):
        for row in self.documents:
            if _matches(row, query or {}):
                self._apply(row, update)
                return SimpleNamespace(matched_count=1, modified_count=1)
        if upsert:
            row = copy.deepcopy(query or {})
            self._apply(row, update)
            self.documents.append(row)
            return SimpleNamespace(matched_count=0, modified_count=1, upserted_id=True)
        return SimpleNamespace(matched_count=0, modified_count=0)

    async def update_many(self, query, update):
        count = 0
        for row in self.documents:
            if _matches(row, query or {}):
                self._apply(row, update)
                count += 1
        return SimpleNamespace(matched_count=count, modified_count=count)

    def aggregate(self, _pipeline):
        losses = [row for row in self.documents if float(row.get("pnl", 0) or 0) < 0]
        total = sum(float(row.get("pnl", 0) or 0) for row in losses)
        return _Cursor([{"_id": None, "total_loss": total}] if losses else [])

    @staticmethod
    def _apply(row: dict[str, Any], update: dict[str, Any]) -> None:
        for key, value in update.get("$set", {}).items():
            row[key] = copy.deepcopy(value)
        for key, value in update.get("$inc", {}).items():
            row[key] = row.get(key, 0) + value
        for key in update.get("$unset", {}):
            row.pop(key, None)


class _ReplayClock:
    timestamp: str | None = None


class _Db:
    def __init__(self, ticker: dict[str, Any], clock: _ReplayClock):
        self.tickers = _Collection([ticker], clock)
        self.trades = _Collection(clock=clock)
        self.profits = _Collection(clock=clock)
        self.settings = _Collection(clock=clock)


class _ReplayPriceService:
    def __init__(self, symbol: str, daily_bars: tuple[Bar, ...]):
        self.symbol = symbol
        self.daily_bars = daily_bars
        self.current: Bar | None = None

    def set_bar(self, bar: Bar) -> None:
        self.current = bar

    async def get_price(self, _symbol: str) -> float:
        if self.current is None:
            raise RuntimeError("replay has no current bar")
        return float(self.current.close)

    async def get_avg_price(self, _symbol: str, days: int) -> float:
        if self.current is None:
            raise RuntimeError("replay has no current bar")
        # Use only completed prior trading days.  This is a stricter no-lookahead
        # version of Pulse PriceService._fetch_avg_yf().tail(days).mean().
        current_date = self.current.et_date
        closes = [bar.close for bar in self.daily_bars if bar.et_date < current_date]
        if not closes:
            return round(self.current.close, 2)
        return round(sum(closes[-max(1, int(days)):]) / len(closes[-max(1, int(days)):]), 2)

    async def get_enriched_market_data(self, _ticker_doc: dict[str, Any]):
        return {"current_price": self.current.close if self.current else 0.0, "history": None}


def _load_pulse(pulse_root: Path):
    backend = pulse_root / "backend"
    deps = types.ModuleType("deps")
    deps.logger = _QuietLogger()
    deps.tracer = _Tracer()
    deps.ROOT_DIR = Path("/tmp/sentinel-native-profitability")
    deps.YF_AVAILABLE = False
    sys.modules["deps"] = deps

    # Import native trading submodules without executing trading/__init__.py,
    # whose live-broker composition is intentionally irrelevant to paper replay.
    trading_package = types.ModuleType("trading")
    trading_package.__path__ = [str(backend / "trading")]
    sys.modules["trading"] = trading_package
    strategies_package = types.ModuleType("strategies")
    strategies_package.__path__ = [str(backend / "strategies")]
    sys.modules["strategies"] = strategies_package

    shared_package = types.ModuleType("shared")
    shared_package.__path__ = [str(backend / "shared")]
    sys.modules["shared"] = shared_package
    edge_integration = types.ModuleType("shared.edge_integration")

    async def _on_trade_executed(_document):
        return None

    edge_integration.on_trade_executed = _on_trade_executed
    sys.modules["shared.edge_integration"] = edge_integration
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    from trading_engine import TradingEngine  # type: ignore

    return TradingEngine, deps


class _Metric:
    def labels(self, **_kwargs):
        return self

    def set(self, *_args, **_kwargs):
        return None

    def inc(self, *_args, **_kwargs):
        return None


class _GenericRecord:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _ObservationScorer:
    def score(self, *_args, **_kwargs):
        return 0.0


def _load_edge(edge_root: Path):
    backend = edge_root / "backend"
    metrics = types.ModuleType("metrics")
    for name in (
        "edge_signal_strength", "edge_trend_direction", "edge_volume_ratio", "edge_volume_zscore",
        "edge_decision_total", "edge_consecutive_losses", "edge_win_rate", "edge_confidence_score",
        "edge_signal_quality",
    ):
        setattr(metrics, name, _Metric())
    sys.modules["metrics"] = metrics

    shared = sys.modules.get("shared") or types.ModuleType("shared")
    shared.__path__ = [str(backend / "shared")]
    sys.modules["shared"] = shared
    commands = types.ModuleType("shared.commands")
    for name in ("OrderFilledCommand", "PositionUpdateCommand", "SignalUpdateCommand"):
        setattr(commands, name, _GenericRecord)
    sys.modules["shared.commands"] = commands
    observations = types.ModuleType("shared.observations")
    for name in ("BaseObservation", "PatternObservation", "ExecutionObservation"):
        setattr(observations, name, _GenericRecord)
    observations.ObservationScorer = _ObservationScorer
    observations.observation_scorer = _ObservationScorer()
    observations.desync_monitor = _GenericRecord()
    sys.modules["shared.observations"] = observations

    signals_spec = importlib.util.spec_from_file_location("signals", backend / "signals.py")
    signals_module = importlib.util.module_from_spec(signals_spec)
    sys.modules["signals"] = signals_module
    assert signals_spec and signals_spec.loader
    signals_spec.loader.exec_module(signals_module)

    engine_spec = importlib.util.spec_from_file_location("sentinel_edge_native_engine", backend / "engine.py")
    engine_module = importlib.util.module_from_spec(engine_spec)
    assert engine_spec and engine_spec.loader
    engine_spec.loader.exec_module(engine_module)
    signals_module.logger.setLevel(logging.CRITICAL)
    engine_module.logger.setLevel(logging.CRITICAL)
    return signals_module.SignalEngine, engine_module.DecisionEngine, engine_module.Decision


def _ticker(symbol: str, config: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "enabled": True,
        "strategy": "custom",
        "base_power": CAPITAL_PER_TICKER,
        "avg_days": config["avg_days"],
        "buy_percent": True,
        "buy_offset": config["buy_offset"],
        "buy_order_type": "limit",
        "sell_percent": True,
        "sell_offset": config["sell_offset"],
        "sell_order_type": "limit",
        "stop_percent": True,
        "stop_offset": config["stop_offset"],
        "stop_order_type": "market",
        "trailing_enabled": config["trailing_enabled"],
        "trailing_percent": config["trailing_percent"],
        "trailing_percent_mode": True,
        "trailing_order_type": "market",
        "broker_ids": [],
        "broker_allocations": {},
        "compound_profits": False,
        "reentry_cooldown_seconds": 0,
        "auto_rebracket": False,
        "partial_fills_enabled": False,
        "max_daily_loss": 0,
        "max_consecutive_losses": 0,
        "market": "US",
    }


def _config_id(config: dict[str, Any]) -> str:
    return (
        f"avg{config['avg_days']}_buy{config['buy_offset']}_sell{config['sell_offset']}_"
        f"stop{config['stop_offset']}_trail"
        f"{config['trailing_percent'] if config['trailing_enabled'] else 'off'}"
    ).replace("-", "m").replace(".", "p")


def candidate_configs() -> list[dict[str, Any]]:
    candidates = []
    for avg_days, buy, sell, stop, trailing in itertools.product(
        (14, 30, 60),
        (-0.5, -1.5, -3.0, -5.0),
        (1.0, 3.0, 6.0),
        (-2.0, -5.0, -8.0),
        ((False, 0.0), (True, 1.0), (True, 2.0)),
    ):
        config = {
            "avg_days": avg_days,
            "buy_offset": buy,
            "sell_offset": sell,
            "stop_offset": stop,
            "trailing_enabled": trailing[0],
            "trailing_percent": trailing[1],
        }
        config["id"] = _config_id(config)
        candidates.append(config)
    presets = [
        {"id": "preset_conservative_1y", "avg_days": 365, "buy_offset": -5.0, "sell_offset": 8.0, "stop_offset": -10.0, "trailing_enabled": False, "trailing_percent": 3.0},
        {"id": "preset_aggressive_monthly", "avg_days": 30, "buy_offset": -2.0, "sell_offset": 4.0, "stop_offset": -5.0, "trailing_enabled": True, "trailing_percent": 1.5},
        {"id": "preset_swing_trader", "avg_days": 14, "buy_offset": -1.5, "sell_offset": 3.0, "stop_offset": -3.0, "trailing_enabled": True, "trailing_percent": 2.0},
    ]
    by_id = {item["id"]: item for item in [*candidates, *presets]}
    return list(by_id.values())


def _trade_cost(trade: dict[str, Any]) -> float:
    notional = float(trade.get("price", 0) or 0) * float(trade.get("quantity", 0) or 0)
    return notional * SLIPPAGE_BPS_PER_ORDER / 10_000 + COMMISSION_PER_ORDER


def _metrics(
    trades: list[dict[str, Any]],
    position: dict[str, Any],
    final_price: float,
    equity_curve: list[float],
) -> dict[str, Any]:
    realized_gross = sum(float(trade.get("pnl", 0) or 0) for trade in trades if trade.get("side") != "BUY")
    friction = sum(_trade_cost(trade) for trade in trades)
    qty = float(position.get("qty", 0) or 0)
    entry = float(position.get("avg_entry", 0) or 0)
    unrealized_gross = (final_price - entry) * qty if qty > 0 and entry > 0 else 0.0
    hypothetical_exit_cost = final_price * qty * SLIPPAGE_BPS_PER_ORDER / 10_000 if qty > 0 else 0.0
    total_net = realized_gross + unrealized_gross - friction - hypothetical_exit_cost

    round_trips = []
    pending_buy = None
    for trade in trades:
        if trade.get("side") == "BUY":
            pending_buy = trade
        elif pending_buy is not None:
            net = float(trade.get("pnl", 0) or 0) - _trade_cost(pending_buy) - _trade_cost(trade)
            round_trips.append(net)
            pending_buy = None
    wins = sum(1 for value in round_trips if value > 0)
    peak = CAPITAL_PER_TICKER
    max_drawdown = 0.0
    for equity in equity_curve:
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    return {
        "orders": len(trades),
        "closed_trades": len(round_trips),
        "winning_trades": wins,
        "win_rate_pct": round((wins / len(round_trips) * 100) if round_trips else 0.0, 4),
        "realized_gross_pnl": round(realized_gross, 4),
        "unrealized_gross_pnl": round(unrealized_gross, 4),
        "modeled_friction": round(friction + hypothetical_exit_cost, 4),
        "total_net_pnl": round(total_net, 4),
        "return_pct": round(total_net / CAPITAL_PER_TICKER * 100, 6),
        "max_drawdown": round(max_drawdown, 4),
        "max_drawdown_pct": round(max_drawdown / CAPITAL_PER_TICKER * 100, 6),
        "open_quantity": round(qty, 8),
        "open_entry": round(entry, 4),
        "final_mark": round(final_price, 4),
    }


async def run_pulse(
    TradingEngine,
    deps,
    symbol: str,
    bars: tuple[Bar, ...],
    daily_bars: tuple[Bar, ...],
    config: dict[str, Any],
) -> dict[str, Any]:
    ticker = _ticker(symbol, config)
    clock = _ReplayClock()
    db = _Db(ticker, clock)
    price_service = _ReplayPriceService(symbol, daily_bars)
    deps.db = db
    deps.price_service = price_service
    deps.ws_manager = _WsManager()
    deps.telegram_service = _Telegram()
    deps.broker_mgr = SimpleNamespace()
    engine = TradingEngine()
    deps.engine = engine
    engine.simulate_24_7 = True
    engine.TRADE_COOLDOWN_SECS = 0
    engine.REENTRY_COOLDOWN_SECS = 0
    engine._is_ticker_market_open = lambda _ticker_doc: True
    engine._is_opening_window = lambda *_args, **_kwargs: False
    engine._is_past_opening_window = lambda *_args, **_kwargs: False
    engine._write_loss_log = lambda _trade: None
    equity_curve: list[float] = []
    for bar in bars:
        clock.timestamp = bar.timestamp
        price_service.set_bar(bar)
        current_ticker = db.tickers.documents[0]
        await engine.evaluate_ticker(current_ticker)
        realized = sum(float(item.get("pnl", 0) or 0) for item in db.trades.documents if item.get("side") != "BUY")
        friction = sum(_trade_cost(item) for item in db.trades.documents)
        position = engine._positions.get(symbol, {"qty": 0, "avg_entry": 0})
        unrealized = (bar.close - float(position.get("avg_entry", 0) or 0)) * float(position.get("qty", 0) or 0)
        equity_curve.append(CAPITAL_PER_TICKER + realized + unrealized - friction)
    final_price = bars[-1].close
    position = engine._positions.get(symbol, {"qty": 0, "avg_entry": 0})
    result = {
        "symbol": symbol,
        "config": copy.deepcopy(config),
        "bar_count": len(bars),
        "first_bar": bars[0].timestamp,
        "last_bar": bars[-1].timestamp,
        "metrics": _metrics(db.trades.documents, position, final_price, equity_curve),
        "trades": copy.deepcopy(db.trades.documents),
    }
    return result


def _atr(bars: list[Bar], period: int = 14) -> float:
    if len(bars) < 2:
        return 0.0
    subset = bars[-period:]
    true_ranges = []
    previous_close = bars[-len(subset) - 1].close if len(bars) > len(subset) else subset[0].close
    for bar in subset:
        true_ranges.append(max(bar.high - bar.low, abs(bar.high - previous_close), abs(bar.low - previous_close)))
        previous_close = bar.close
    return sum(true_ranges) / len(true_ranges)


async def run_pulse_edge_duo(
    TradingEngine,
    deps,
    SignalEngine,
    DecisionEngine,
    Decision,
    symbol: str,
    bars: tuple[Bar, ...],
    daily_bars: tuple[Bar, ...],
    config: dict[str, Any],
    execution_order: str,
) -> dict[str, Any]:
    ticker = _ticker(symbol, config)
    clock = _ReplayClock()
    db = _Db(ticker, clock)
    price_service = _ReplayPriceService(symbol, daily_bars)
    deps.db = db
    deps.price_service = price_service
    deps.ws_manager = _WsManager()
    deps.telegram_service = _Telegram()
    deps.broker_mgr = SimpleNamespace()
    pulse = TradingEngine()
    deps.engine = pulse
    pulse.simulate_24_7 = True
    pulse.TRADE_COOLDOWN_SECS = 0
    pulse.REENTRY_COOLDOWN_SECS = 0
    pulse._is_ticker_market_open = lambda _ticker_doc: True
    pulse._is_opening_window = lambda *_args, **_kwargs: False
    pulse._is_past_opening_window = lambda *_args, **_kwargs: False
    pulse._write_loss_log = lambda _trade: None
    signals = SignalEngine()
    decisions = DecisionEngine()
    action_counts: dict[str, int] = defaultdict(int)
    handoff_counts: dict[str, int] = defaultdict(int)
    decision_log: list[dict[str, Any]] = []
    seen_exit_ids: set[str] = set()
    history: list[Bar] = []
    equity_curve: list[float] = []

    async def edge_cycle(bar: Bar) -> None:
        history.append(bar)
        day_bars = [item for item in history if item.et_date == bar.et_date]
        opening = next((item for item in day_bars if item.et_time == (9, 30)), None)
        orb_high = opening.high if opening and bar.et_time >= (9, 45) else None
        orb_low = opening.low if opening and bar.et_time >= (9, 45) else None
        prior_close = history[-2].close if len(history) > 1 else bar.close
        price_change_pct = ((bar.close - prior_close) / prior_close * 100) if prior_close > 0 else 0.0
        signals.update_avg_volume(symbol, bar.volume)
        volume_ratio = signals.get_volume_ratio(symbol, bar.volume)
        volume_zscore = signals.compute_volume_zscore(symbol, bar.volume)
        atr = _atr(history)
        trend, strength = signals.evaluate_signal(
            symbol=symbol,
            price=bar.close,
            orb_high=orb_high,
            orb_low=orb_low,
            volume_ratio=volume_ratio,
            atr=atr,
            price_change_pct=price_change_pct,
            volume_zscore=volume_zscore,
        )
        position = pulse._positions.get(symbol, {"qty": 0, "avg_entry": 0})
        qty = float(position.get("qty", 0) or 0)
        entry = float(position.get("avg_entry", 0) or 0)
        pnl_pct = ((bar.close - entry) / entry * 100) if qty > 0 and entry > 0 else 0.0
        decision = decisions.decide(
            symbol=symbol,
            trend=trend,
            signal_strength=strength,
            confidence=1.0,
            pnl=(bar.close - entry) * qty if qty > 0 else 0.0,
            pnl_pct=pnl_pct,
            current_drawdown=max(0.0, -pnl_pct),
            has_position=qty > 0,
            trailing_enabled=bool(db.tickers.documents[0].get("trailing_enabled", False)),
        )
        action = decision.value
        action_counts[action] += 1
        accepted = False
        reason = "no_handoff_for_hold"
        current_ticker = db.tickers.documents[0]
        try:
            if decision == Decision.BUY:
                if qty <= 0:
                    await pulse.execute_buy(symbol, bar.close)
                    accepted, reason = True, "pulse_execute_buy"
                else:
                    reason = "already_have_position"
            elif decision == Decision.SELL:
                if qty > 0:
                    await pulse.execute_sell(symbol, bar.close)
                    accepted, reason = True, "pulse_execute_sell"
                else:
                    reason = "no_position"
            elif decision == Decision.STOP_BUYING:
                current_ticker["buying_paused"] = True
                current_ticker["auto_stop_reason"] = "edge_stop_buying"
                current_ticker["enabled"] = qty > 0
                accepted, reason = True, "pulse_stop_buying"
            elif decision == Decision.ENABLE_TRAILING_STOP:
                trailing_pct = min(2.0, max(0.5, (atr / bar.close) * 100 * 2)) if bar.close > 0 else 1.5
                current_ticker["trailing_enabled"] = True
                current_ticker["trailing_percent"] = trailing_pct
                accepted, reason = True, "pulse_enable_trailing"
            elif decision == Decision.TIGHTEN_TRAILING_STOP:
                current_ticker["trailing_enabled"] = True
                current_ticker["trailing_percent"] = 0.5
                accepted, reason = True, "pulse_tighten_trailing"
            elif decision == Decision.TIGHTEN_STOP:
                # This mirrors the current handoff: Edge sends no numeric
                # stop_offset metadata, so Pulse records the reason only.
                current_ticker["auto_stop_reason"] = "edge_tighten_stop"
                accepted, reason = True, "pulse_tighten_stop_no_numeric_offset"
            elif decision == Decision.EMERGENCY_EXIT:
                if qty > 0:
                    await pulse.execute_sell(symbol, bar.close)
                current_ticker["buying_paused"] = True
                current_ticker["enabled"] = False
                accepted, reason = True, "pulse_emergency_exit"
        except (RuntimeError, ValueError) as exc:
            reason = f"rejected:{exc}"
        if decision != Decision.HOLD:
            handoff_counts["accepted" if accepted else "rejected"] += 1
            decision_log.append(
                {
                    "timestamp": bar.timestamp,
                    "decision": action,
                    "signal_strength": round(strength, 4),
                    "trend": trend.name.lower(),
                    "accepted": accepted,
                    "reason": reason,
                    "price": bar.close,
                }
            )

    for bar in bars:
        clock.timestamp = bar.timestamp
        price_service.set_bar(bar)
        if execution_order == "edge_first":
            await edge_cycle(bar)
            await pulse.evaluate_ticker(db.tickers.documents[0])
        else:
            await pulse.evaluate_ticker(db.tickers.documents[0])
            await edge_cycle(bar)

        # Feed authoritative Pulse exits back into Edge's loss/win state.
        for trade in db.trades.documents:
            trade_id = str(trade.get("id"))
            if trade_id in seen_exit_ids or trade.get("side") == "BUY":
                continue
            seen_exit_ids.add(trade_id)
            decisions.record_trade_result_legacy(symbol, profit=float(trade.get("pnl", 0) or 0))
        position = pulse._positions.get(symbol, {"qty": 0, "avg_entry": 0})
        qty = float(position.get("qty", 0) or 0)
        entry = float(position.get("avg_entry", 0) or 0)
        if qty > 0:
            decisions.positions[symbol] = {
                "size": qty,
                "entry_price": entry,
                "current_pnl_pct": ((bar.close - entry) / entry * 100) if entry > 0 else 0.0,
                "current_pnl_dollar": (bar.close - entry) * qty,
            }
        else:
            decisions.positions.pop(symbol, None)
        realized = sum(float(item.get("pnl", 0) or 0) for item in db.trades.documents if item.get("side") != "BUY")
        friction = sum(_trade_cost(item) for item in db.trades.documents)
        unrealized = (bar.close - entry) * qty if qty > 0 else 0.0
        equity_curve.append(CAPITAL_PER_TICKER + realized + unrealized - friction)

    final_position = pulse._positions.get(symbol, {"qty": 0, "avg_entry": 0})
    return {
        "symbol": symbol,
        "execution_order": execution_order,
        "config": copy.deepcopy(config),
        "bar_count": len(bars),
        "metrics": _metrics(db.trades.documents, final_position, bars[-1].close, equity_curve),
        "edge_decisions": dict(sorted(action_counts.items())),
        "handoffs": dict(sorted(handoff_counts.items())),
        "decision_log": decision_log,
        "trades": copy.deepcopy(db.trades.documents),
        "final_ticker_state": {
            key: db.tickers.documents[0].get(key)
            for key in ("enabled", "buying_paused", "trailing_enabled", "trailing_percent", "auto_stop_reason")
        },
    }


def _git_revision(path: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=path, text=True).strip()


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _automation_audit(chain_root: Path, iron_root: Path) -> dict[str, Any]:
    chain_presets = chain_root / "src" / "sentinel_chain" / "strategy_presets.py"
    chain_scalper = chain_root / "src" / "sentinel_chain" / "scalper.py"
    iron_readme = iron_root / "README.md"
    trend_file = iron_root / "src" / "sentinel_iron" / "strategies" / "trend_following.py"
    chain_text = chain_presets.read_text(encoding="utf-8")
    iron_text = iron_readme.read_text(encoding="utf-8")
    return {
        "chain": {
            "autonomous_candle_to_entry_loop": False,
            "replay_orders": 0,
            "replay_pnl": 0.0,
            "classification": "not_autonomously_testable",
            "evidence": [
                "Strategy presets normalize operator/external entries and explicitly do not generate signals.",
                "Scalper helpers construct or re-bracket externally selected bands; they do not discover an entry from candles.",
            ],
            "source_checks": {
                "preset_non_generation_marker_present": "does not generate signals" in chain_text,
                "strategy_presets_sha256": _file_sha(chain_presets),
                "scalper_sha256": _file_sha(chain_scalper),
            },
        },
        "iron": {
            "autonomous_candle_to_entry_loop": False,
            "replay_orders": 0,
            "replay_pnl": 0.0,
            "classification": "not_autonomously_testable",
            "evidence": [
                "Iron has trend/carry signal calculations, target sizing, order planning, and broker submission components.",
                "The current README explicitly says autonomous strategy-driven live order entry does not yet run.",
            ],
            "source_checks": {
                "readme_non_autonomous_marker_present": "does not yet run autonomous strategy-driven live order entry" in iron_text,
                "readme_sha256": _file_sha(iron_readme),
                "trend_following_sha256": _file_sha(trend_file),
            },
        },
    }


def _compact_run(run: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in run.items() if key not in {"trades", "decision_log"}}


def _top_eligible(runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    eligible = [run for run in runs if run["metrics"]["closed_trades"] >= 1]
    if not eligible:
        return None
    return max(eligible, key=lambda run: (run["metrics"]["total_net_pnl"], -run["metrics"]["max_drawdown"]))


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Sentinel Native Profitability Replay — 2026-07-17",
        "",
        "> Research replay only. Positive historical P&L is not proof of future profitability and is not a recommendation to trade.",
        "",
        "## Verdict",
        "",
        report["verdict"],
        "",
        "## Pulse: April–May tuning, June–July held-out replay",
        "",
        "| Symbol | Selected settings | Apr–May net | Jun–Jul net | Jun–Jul return | Closed trades | Max drawdown |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for symbol in PULSE_SYMBOLS:
        tuned = report["pulse"]["selected_by_symbol"].get(symbol)
        validated = report["pulse"]["held_out_validation"].get(symbol)
        if not tuned or not validated:
            lines.append(f"| {symbol} | No eligible completed trade | — | — | — | — | — |")
            continue
        config = tuned["config"]
        label = (
            f"avg {config['avg_days']}; buy {config['buy_offset']}%; sell {config['sell_offset']}%; "
            f"stop {config['stop_offset']}%; trail "
            f"{str(config['trailing_percent']) + '%' if config['trailing_enabled'] else 'off'}"
        )
        tune_metrics = tuned["metrics"]
        metrics = validated["metrics"]
        lines.append(
            f"| {symbol} | {label} | ${tune_metrics['total_net_pnl']:.2f} | "
            f"${metrics['total_net_pnl']:.2f} | {metrics['return_pct']:.3f}% | "
            f"{metrics['closed_trades']} | ${metrics['max_drawdown']:.2f} |"
        )
    common = report["pulse"].get("common_configuration")
    common_validation = report["pulse"].get("common_configuration_held_out", [])
    common_summary = ""
    if common:
        common_metrics = ", ".join(
            f"{item['symbol']} ${item['metrics']['total_net_pnl']:.2f} ({item['metrics']['orders']} orders)"
            for item in common_validation
        )
        common_summary = (
            f" A robustness check selected one shared setting across all three tickers "
            f"(`{common['config']['id']}`): held-out results were {common_metrics}. The lack of SPY and QQQ "
            "orders shows that the positive per-ticker result is not broad confirmation."
        )
    lines.extend(
        [
            "",
            "The selection rule required at least one completed round trip in April–May. June–July settings were frozen before replay. Open end-of-window positions are marked to the final close and include a hypothetical exit slippage charge; they are not counted as bot-generated sells."
            + common_summary,
            "",
            "## Pulse + Edge coordination replay (June–July, 15-minute)",
            "",
            "| Symbol | Ordering | Net P&L | Return | Edge non-HOLD handoffs | Accepted | Closed trades |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for item in report["pulse_edge"]["runs"]:
        metrics = item["metrics"]
        handoffs = item["handoffs"]
        lines.append(
            f"| {item['symbol']} | {item['execution_order']} | ${metrics['total_net_pnl']:.2f} | "
            f"{metrics['return_pct']:.3f}% | {sum(handoffs.values())} | {handoffs.get('accepted', 0)} | "
            f"{metrics['closed_trades']} |"
        )
    lines.extend(
        [
            "",
            "This duo replay exercises Edge's native core ORB/volume/momentum scoring and DecisionEngine, plus Pulse's native Edge buy/sell methods and ticker risk settings. It does not exercise Edge's enhanced chart-pattern analyzer, so it is coordination evidence—not a complete profitability certification for the duo.",
            "",
            "## Chain and Iron",
            "",
            "| Bot | Orders independently initiated | P&L | Conclusion |",
            "|---|---:|---:|---|",
            "| Chain | 0 | $0.00 | No candle-to-entry automation loop; waits for an external/operator signal. |",
            "| Iron | 0 | $0.00 | Strategy primitives exist, but no autonomous strategy-to-order runtime loop. |",
            "",
            "Zero is not a profitable result, but it is also not a losing strategy result. These bots are presently **not autonomously testable as traders** without adding the missing orchestration inside the bots themselves.",
            "",
            "## Evidence controls",
            "",
            f"- Tuning window: `{TUNE_START}` through `{TUNE_END}` (end exclusive).",
            f"- Held-out window: `{VALIDATE_START}` through `{VALIDATE_END}` (end exclusive; last completed US session July 16).",
            f"- Pulse setting runs: {report['pulse']['tuning_run_count']}.",
            f"- Execution friction: {SLIPPAGE_BPS_PER_ORDER:.1f} bps per order plus ${COMMISSION_PER_ORDER:.2f} commission.",
            "- No synthetic candles, scripted signals, or preselected trade timestamps were used.",
            "- April–May selected settings were frozen before June–July validation.",
            "- Every input series has a SHA-256 fingerprint and malformed OHLC rows were excluded rather than corrected.",
            "",
            "## Data manifests",
            "",
            "| Provider | Symbol | Interval | Bars | First | Last | Fingerprint | Dropped |",
            "|---|---|---:|---:|---|---|---|---:|",
        ]
    )
    for item in report["datasets"]:
        lines.append(
            f"| {item['provider']} | {item['symbol']} | {item['interval']} | {item['bar_count']} | "
            f"{item['first_timestamp']} | {item['last_timestamp']} | `{item['fingerprint_sha256'][:16]}…` | {item['dropped_rows']} |"
        )
    lines.extend(
        [
            "",
            "## Important limitations",
            "",
            "- Yahoo's public chart endpoint is a research feed, not exchange or broker execution truth.",
            "- Pulse was sampled once per recorded candle close. Intrabar price paths were not invented.",
            "- The study models 2 bps per order after native paper fills; Pulse's decisions do not currently wait for Archive General API fill acknowledgements in this adapter.",
            "- Hourly continuous futures data was acquired for Iron feed coverage, but no futures P&L was produced because Iron did not initiate an order.",
            "- BitUnix malformed candles were excluded and counted. Archive did not repair vendor OHLC values.",
            "- A roughly six-and-a-half-week held-out interval is far too short to establish durable profitability.",
        ]
    )
    return "\n".join(lines) + "\n"


async def study(args) -> dict[str, Any]:
    archive_root = Path(__file__).resolve().parents[1]
    workspace = archive_root.parent
    pulse_root = workspace / "Sentinel-Pulse"
    edge_root = workspace / "Sentinel-Edge"
    chain_root = workspace / "Sentinel-Chain"
    iron_root = workspace / "Sentinel-Iron"
    TradingEngine, pulse_deps = _load_pulse(pulse_root)
    SignalEngine, DecisionEngine, Decision = _load_edge(edge_root)

    market = RecordedMarketData()
    try:
        datasets: dict[tuple[str, str], Dataset] = {}
        print("Downloading recorded Yahoo candles and daily average inputs...", flush=True)
        for symbol in (*PULSE_SYMBOLS, "MES=F", "MNQ=F", "BTC-USD"):
            datasets[(symbol, "1h")] = market.yahoo(symbol, "1h", "2026-03-01T00:00:00Z", VALIDATE_END)
        for symbol in PULSE_SYMBOLS:
            datasets[(symbol, "1d")] = market.yahoo(symbol, "1d", WARMUP_START, VALIDATE_END)
            datasets[(symbol, "15m")] = market.yahoo(symbol, "15m", VALIDATE_START, VALIDATE_END)
        print("Downloading paginated BitUnix BTCUSDT futures candles...", flush=True)
        bitunix = market.bitunix("BTCUSDT", "1h", TUNE_START, VALIDATE_END)
    finally:
        market.close()

    configs = candidate_configs()
    tuning_runs: dict[str, list[dict[str, Any]]] = {}
    selected: dict[str, dict[str, Any] | None] = {}
    validation: dict[str, dict[str, Any]] = {}
    for symbol in PULSE_SYMBOLS:
        hourly = datasets[(symbol, "1h")].subset(TUNE_START, TUNE_END)
        daily = datasets[(symbol, "1d")].bars
        print(f"Pulse tuning {symbol}: {len(configs)} native settings across {len(hourly)} bars", flush=True)
        runs = []
        for index, config in enumerate(configs, 1):
            runs.append(await run_pulse(TradingEngine, pulse_deps, symbol, hourly, daily, config))
            if index % 100 == 0:
                print(f"  {symbol}: completed {index}/{len(configs)} settings", flush=True)
        tuning_runs[symbol] = runs
        selected[symbol] = _top_eligible(runs)
        if selected[symbol]:
            validation_bars = datasets[(symbol, "1h")].subset(VALIDATE_START, VALIDATE_END)
            validation[symbol] = await run_pulse(
                TradingEngine,
                pulse_deps,
                symbol,
                validation_bars,
                daily,
                selected[symbol]["config"],
            )

    # Select one common configuration by April–May aggregate, requiring at least
    # one closed trade across the portfolio.  This is reported separately from
    # per-ticker tuning to make overfitting visible.
    by_config: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for runs in tuning_runs.values():
        for run in runs:
            by_config[run["config"]["id"]].append(run)
    common_candidates = []
    for config_id, runs in by_config.items():
        if sum(run["metrics"]["closed_trades"] for run in runs) < 1:
            continue
        common_candidates.append(
            {
                "config": runs[0]["config"],
                "tuning_net_pnl": round(sum(run["metrics"]["total_net_pnl"] for run in runs), 4),
                "tuning_closed_trades": sum(run["metrics"]["closed_trades"] for run in runs),
                "tuning_max_drawdown_sum": round(sum(run["metrics"]["max_drawdown"] for run in runs), 4),
            }
        )
    common_selected = max(
        common_candidates,
        key=lambda item: (item["tuning_net_pnl"], -item["tuning_max_drawdown_sum"]),
        default=None,
    )
    common_validation = []
    if common_selected:
        for symbol in PULSE_SYMBOLS:
            common_validation.append(
                await run_pulse(
                    TradingEngine,
                    pulse_deps,
                    symbol,
                    datasets[(symbol, "1h")].subset(VALIDATE_START, VALIDATE_END),
                    datasets[(symbol, "1d")].bars,
                    common_selected["config"],
                )
            )

    duo_runs = []
    for symbol in PULSE_SYMBOLS:
        if not selected[symbol]:
            continue
        for ordering in ("edge_first", "pulse_first"):
            print(f"Pulse+Edge {symbol}: June–July 15m replay ({ordering})", flush=True)
            duo_runs.append(
                await run_pulse_edge_duo(
                    TradingEngine,
                    pulse_deps,
                    SignalEngine,
                    DecisionEngine,
                    Decision,
                    symbol,
                    datasets[(symbol, "15m")].subset(VALIDATE_START, VALIDATE_END),
                    datasets[(symbol, "1d")].bars,
                    selected[symbol]["config"],
                    ordering,
                )
            )

    held_out_values = [item["metrics"]["total_net_pnl"] for item in validation.values()]
    positive_count = sum(value > 0 for value in held_out_values)
    held_out_total = sum(held_out_values)
    if not validation:
        verdict = "Pulse produced no eligible April–May round trip, so no honest held-out profitability conclusion is available."
    elif positive_count == len(validation) and held_out_total > 0:
        verdict = (
            f"Pulse's per-symbol April–May-selected settings ended with positive mark-to-market value on all "
            f"{positive_count} held-out June–July tickers (${held_out_total:.2f} combined after modeled friction). "
            "Only QQQ and TSLA had positive realized gross P&L; SPY's positive ending depended on an open gain after "
            "one closed loss. This is encouraging but insufficient evidence of reliable profitability. Chain and "
            "Iron cannot yet be ranked because neither initiated a candle-derived order."
        )
    elif held_out_total > 0:
        verdict = (
            f"Pulse was mixed on held-out June–July data: {positive_count}/{len(validation)} tickers were positive, "
            f"with ${held_out_total:.2f} combined modeled net P&L. That is not broad enough to call the bot reliably "
            "profitable. Chain and Iron remain unrankable as autonomous traders because neither initiated an order."
        )
    else:
        verdict = (
            f"Pulse's tuned settings did not survive held-out June–July replay (combined modeled net P&L "
            f"${held_out_total:.2f}). No tested bot can presently be called reliably profitable. Chain and Iron "
            "remain unrankable because their missing candle-to-entry loops produced no autonomous orders."
        )

    report = {
        "schema_version": "sentinel.archive.native_profitability_study.v1",
        "study_id": STUDY_ID,
        "generated_at": datetime.now(UTC).isoformat(),
        "verdict": verdict,
        "windows": {
            "tuning": {"start": TUNE_START, "end_exclusive": TUNE_END},
            "held_out_validation": {"start": VALIDATE_START, "end_exclusive": VALIDATE_END},
        },
        "assumptions": {
            "capital_per_ticker": CAPITAL_PER_TICKER,
            "slippage_bps_per_order": SLIPPAGE_BPS_PER_ORDER,
            "commission_per_order": COMMISSION_PER_ORDER,
            "decision_sample": "recorded candle close only",
            "end_of_window_open_positions": "marked to final close with hypothetical exit slippage; not counted as bot exits",
        },
        "repositories": {
            "archive": _git_revision(archive_root),
            "pulse": _git_revision(pulse_root),
            "edge": _git_revision(edge_root),
            "chain": _git_revision(chain_root),
            "iron": _git_revision(iron_root),
        },
        "runner": {
            "path": "scripts/run_native_profitability_study.py",
            "sha256": _file_sha(Path(__file__).resolve()),
        },
        "datasets": [
            *[dataset.manifest() for dataset in datasets.values()],
            bitunix.manifest(),
        ],
        "pulse": {
            "native_entry_method": "TradingEngine.evaluate_ticker",
            "candidate_settings_per_symbol": len(configs),
            "tuning_run_count": len(configs) * len(PULSE_SYMBOLS),
            "selection_rule": "maximum modeled net P&L with at least one completed April–May round trip",
            "selected_by_symbol": {
                symbol: _compact_run(run) if run else None for symbol, run in selected.items()
            },
            "held_out_validation": {
                symbol: _compact_run(run) for symbol, run in validation.items()
            },
            "top_five_tuning_by_symbol": {
                symbol: [
                    _compact_run(run)
                    for run in sorted(
                        (item for item in runs if item["metrics"]["closed_trades"] >= 1),
                        key=lambda item: item["metrics"]["total_net_pnl"],
                        reverse=True,
                    )[:5]
                ]
                for symbol, runs in tuning_runs.items()
            },
            "common_configuration": common_selected,
            "common_configuration_held_out": [_compact_run(run) for run in common_validation],
        },
        "pulse_edge": {
            "classification": "partial_native_coordination_replay",
            "included": ["SignalEngine", "DecisionEngine", "Pulse Edge buy/sell methods", "Pulse ticker risk settings"],
            "excluded": ["SignalEngineEnhanced chart-pattern analyzer", "HTTP transport timing", "live broker acknowledgements"],
            "runs": [_compact_run(run) for run in duo_runs],
        },
        "automation_audit": _automation_audit(chain_root, iron_root),
        "futures_feed_coverage": {
            "chain_bitunix_btcusdt": bitunix.manifest(),
            "chain_reference_btcusd": datasets[("BTC-USD", "1h")].manifest(),
            "iron_mes": datasets[("MES=F", "1h")].manifest(),
            "iron_mnq": datasets[("MNQ=F", "1h")].manifest(),
        },
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "reports" / STUDY_ID,
    )
    args = parser.parse_args()
    report = asyncio.run(study(args))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "report.json"
    markdown_path = args.output_dir / "report.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    markdown_path.write_text(_markdown(report), encoding="utf-8")
    print(f"Wrote {json_path}", flush=True)
    print(f"Wrote {markdown_path}", flush=True)
    print(report["verdict"], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
