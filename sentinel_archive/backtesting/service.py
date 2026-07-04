from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from itertools import product
from uuid import uuid4

from sentinel_archive.backtesting.engines.crypto import run_crypto_backtest
from sentinel_archive.backtesting.engines.options import run_options_replay
from sentinel_archive.backtesting.engines.stocks import run_stock_backtest
from sentinel_archive.backtesting.models import (
    BacktestReport,
    BacktestRunKind,
    BacktestRunRecord,
    BacktestRunRequest,
    BacktestStressRequest,
    BacktestStressResult,
    BacktestSweepRequest,
    BacktestSweepResult,
    BacktestWalkForwardRequest,
    BacktestWalkForwardResult,
    BacktestWalkForwardWindow,
    BacktestRange,
    MarketPriceBar,
)


def run_backtest(request: BacktestRunRequest) -> BacktestReport:
    if request.asset_class == "crypto":
        return run_crypto_backtest(request)
    if request.asset_class == "stock":
        return run_stock_backtest(request)
    if request.asset_class == "options":
        return run_options_replay(request)
    raise ValueError(f"unsupported asset class: {request.asset_class}")


def run_sweep(request: BacktestSweepRequest) -> BacktestSweepResult:
    stop_values = request.stop_loss_pcts or [request.base_request.stop_loss_pct]
    target_values = request.take_profit_pcts or [request.base_request.take_profit_pct]
    leverage_values = request.leverage_values or [request.base_request.leverage]
    reports: list[BacktestReport] = []

    for stop_loss_pct, take_profit_pct, leverage in product(stop_values, target_values, leverage_values):
        candidate = request.base_request.model_copy(
            update={
                "stop_loss_pct": stop_loss_pct,
                "take_profit_pct": take_profit_pct,
                "leverage": leverage,
            }
        )
        report = run_backtest(candidate)
        report.assumptions = {
            **report.assumptions,
            "sweep": {
                "stop_loss_pct": stop_loss_pct,
                "take_profit_pct": take_profit_pct,
                "leverage": leverage,
            },
        }
        reports.append(report)

    reports.sort(key=lambda item: (item.metrics.safety_score, item.metrics.total_pnl), reverse=True)
    return BacktestSweepResult(reports=reports)


def run_walk_forward(request: BacktestWalkForwardRequest) -> BacktestWalkForwardResult:
    bars = request.base_request.bars
    windows: list[BacktestWalkForwardWindow] = []
    start = 0
    while start + request.train_size + request.test_size <= len(bars):
        train_bars = bars[start : start + request.train_size]
        test_bars = bars[start + request.train_size : start + request.train_size + request.test_size]
        test_request = request.base_request.model_copy(update={"bars": test_bars})
        report = run_backtest(test_request)
        windows.append(
            BacktestWalkForwardWindow(
                train_range=_bar_range(train_bars),
                test_range=_bar_range(test_bars),
                report=report,
            )
        )
        start += request.step_size
    return BacktestWalkForwardResult(windows=windows)


def run_stress(request: BacktestStressRequest) -> BacktestStressResult:
    reports: list[BacktestReport] = []
    scenarios = request.scenarios or []
    for scenario in scenarios:
        shocked_bars = [_shock_bar(bar, scenario.price_shock_pct) for bar in request.base_request.bars]
        cost_model = request.base_request.cost_model
        if scenario.slippage_bps is not None:
            cost_model = cost_model.model_copy(update={"slippage_bps": scenario.slippage_bps})
        candidate = request.base_request.model_copy(update={"bars": shocked_bars, "cost_model": cost_model})
        report = run_backtest(candidate)
        report.assumptions = {**report.assumptions, "stress": scenario.model_dump(mode="json")}
        reports.append(report)
    reports.sort(key=lambda item: (item.metrics.safety_score, item.metrics.total_pnl), reverse=True)
    return BacktestStressResult(reports=reports)


def create_run_record(request: BacktestRunRequest, report: BacktestReport, *, kind: str = "run") -> BacktestRunRecord:
    return create_result_record(
        kind=kind,  # type: ignore[arg-type]
        asset_class=request.asset_class,
        symbol=request.symbol,
        request_payload=request.model_dump(mode="json"),
        report=report,
        result_payload=report.model_dump(mode="json"),
    )


def create_result_record(
    *,
    kind: BacktestRunKind,
    asset_class: str,
    symbol: str,
    request_payload: dict,
    report: BacktestReport,
    result_payload: dict,
) -> BacktestRunRecord:
    created_at = datetime.now(timezone.utc).isoformat()
    fingerprint = fingerprint_payload({"kind": kind, "request": request_payload})
    run_id = f"bt-{fingerprint[:8]}-{uuid4().hex[:8]}"
    report.run_id = run_id
    return BacktestRunRecord(
        run_id=run_id,
        created_at=created_at,
        kind=kind,
        asset_class=asset_class,  # type: ignore[arg-type]
        symbol=symbol.upper(),
        fingerprint=fingerprint,
        request=request_payload,
        report=report,
        result=result_payload,
    )


def fingerprint_payload(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _bar_range(bars: list[MarketPriceBar]) -> BacktestRange:
    return BacktestRange(start=bars[0].timestamp, end=bars[-1].timestamp)


def _shock_bar(bar: MarketPriceBar, price_shock_pct: float) -> MarketPriceBar:
    multiplier = 1 + price_shock_pct / 100
    return bar.model_copy(
        update={
            "open": bar.open * multiplier,
            "high": bar.high * multiplier,
            "low": bar.low * multiplier,
            "close": bar.close * multiplier,
        }
    )
