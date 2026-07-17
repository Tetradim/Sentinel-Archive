from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sentinel_archive.api import create_app
from sentinel_archive.backtesting.models import BacktestOrderIntent
from sentinel_archive.profitability.adapters import StrategyRuntime
from sentinel_archive.profitability.adapters import build_strategy_runtime
from sentinel_archive.profitability.engine import run_profitability_study
from sentinel_archive.profitability.models import (
    ProfitabilityStrategyConfig,
    ProfitabilityStudyRequest,
    RecordedStrategySignal,
    StrategyAdapterEvidence,
)


def _bars(symbol: str = "MES", count: int = 40) -> list[dict]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        {
            "timestamp": (start + timedelta(days=index)).isoformat(),
            "symbol": symbol,
            "open": 5000 + index,
            "high": 5002 + index,
            "low": 4999 + index,
            "close": 5001 + index,
            "volume": 10_000,
        }
        for index in range(count)
    ]


def _base_request(*, bot_id: str = "iron", crypto: bool = False) -> dict:
    symbol = "BTCUSDT" if crypto else "MES"
    return {
        "bot_id": bot_id,
        "symbol": symbol,
        "quantity": 1,
        "starting_equity": 100_000,
        "leverage": 2,
        "contract": {
            "symbol": symbol,
            "venue": "BINANCE" if crypto else "CME",
            "instrument_type": "crypto_perpetual" if crypto else "listed_future",
            "contract_multiplier": 1,
            "tick_size": 0.01 if crypto else 0.25,
            "quantity_step": 0.001 if crypto else 1,
            "minimum_quantity": 0.001 if crypto else 1,
            "initial_margin_rate": 0.5,
            "maintenance_margin_rate": 0.25,
            "maximum_leverage": 10,
        },
        "bars": _bars(symbol),
        "metadata": {
            "source_fingerprint": "recorded-test-bars",
            **({} if crypto else {"contract_series_type": "specific_contract"}),
        },
    }


def _study_payload(*, bot_id: str = "iron", profile: str = "iron_trend", crypto: bool = False) -> dict:
    return {
        "name": f"{bot_id} evidence",
        "base_request": _base_request(bot_id=bot_id, crypto=crypto),
        "strategy": {"profile": profile, "require_native": False, "parameters": {"lookbacks": [2, 3]}},
        "validation": {
            "minimum_train_bars": 10,
            "test_bars_per_fold": 10,
            "folds": 3,
            "minimum_out_of_sample_bars": 30,
            "minimum_closed_trades": 3,
            "bootstrap_samples": 200,
            "minimum_probability_of_profit": 0.9,
            "minimum_sharpe_ratio": -100,
            "require_benchmark_outperformance": False,
        },
        "cost_stresses": [{"name": "base"}, {"name": "adverse", "slippage_multiplier": 2}],
    }


def test_profitable_verdict_requires_and_accepts_all_gates(monkeypatch):
    def fake_runtime(config, base_request, signals):
        runtime = StrategyRuntime(
            config=config,
            base_request=base_request,
            signals=signals,
            evidence=StrategyAdapterEvidence(
                adapter_id="test.no-lookahead.v1",
                strategy_origin="test fixture",
                native=True,
                repository_commit="a" * 40,
                repository_clean=True,
                strategy_sha256="b" * 64,
                reproducible=True,
            ),
        )
        runtime.generate_orders = lambda bars, trade_start, trade_end: [
            BacktestOrderIntent(
                order_id=f"target-{index}",
                timestamp=bars[index].timestamp,
                action="target",
                side="long",
                quantity=1,
            )
            for index in range(trade_start, trade_end)
        ]
        return runtime

    monkeypatch.setattr("sentinel_archive.profitability.engine.build_strategy_runtime", fake_runtime)
    report = run_profitability_study(ProfitabilityStudyRequest(**_study_payload()))

    assert report.verdict == "profitable"
    assert report.metrics is not None
    assert report.metrics.compounded_return_pct > 0
    assert report.metrics.bootstrap_return_lower_pct > 0
    assert report.metrics.probability_of_profit == 1
    assert len(report.folds) == 3


def test_missing_provenance_and_missing_chain_signals_are_refused():
    missing_provenance = _study_payload()
    missing_provenance["base_request"]["metadata"] = {}
    missing_provenance["validation"]["require_data_provenance"] = True
    report = run_profitability_study(ProfitabilityStudyRequest(**missing_provenance))
    assert report.verdict == "insufficient_data"
    assert "provenance" in report.verdict_reasons[0]

    chain = _study_payload(bot_id="chain", profile="chain_signal_replay", crypto=True)
    report = run_profitability_study(ProfitabilityStudyRequest(**chain))
    assert report.verdict == "insufficient_strategy"
    assert "recorded Chain signals" in report.verdict_reasons[0]


def test_combination_cannot_be_certified_as_an_independent_edge():
    payload = _study_payload(bot_id="combination", profile="combination_routed")
    payload["strategy"]["parameters"] = {
        "source_profile": "iron_trend",
        "source_parameters": {"lookbacks": [2, 3]},
    }
    report = run_profitability_study(ProfitabilityStudyRequest(**payload))

    assert report.verdict != "profitable"
    assert report.adapter is not None
    assert report.adapter.independent_strategy is False
    if report.metrics is not None and report.metrics.compounded_return_pct > 0:
        assert any("not an independent edge" in reason for reason in report.verdict_reasons)


def test_profitability_api_persists_a_refusal_report(tmp_path):
    payload = _study_payload(bot_id="chain", profile="chain_signal_replay", crypto=True)
    with TestClient(create_app(recorder_db_path=tmp_path / "archive.sqlite3")) as client:
        response = client.post("/api/archive/profitability/study", json=payload)
        assert response.status_code == 200
        report = response.json()
        assert report["verdict"] == "insufficient_strategy"
        saved = client.get(f"/api/archive/profitability/runs/{report['study_id']}")
        assert saved.status_code == 200
        assert saved.json()["fingerprint"] == report["fingerprint"]
        assert client.get("/api/archive/profitability/adapters").status_code == 200


def test_native_iron_strategy_families_generate_daily_targets():
    if not (Path.cwd().parent / "Sentinel-Iron").is_dir():
        pytest.skip("Sentinel-Iron sibling repository is required for the native integration test")
    base = _base_request()
    snapshots = [
        {
            "timestamp": bar["timestamp"],
            "front_price": bar["close"],
            "deferred_price": bar["close"] + 5,
            "front_expiration": "2026-09-18",
            "deferred_expiration": "2026-12-18",
        }
        for bar in base["bars"]
    ]
    request = ProfitabilityStudyRequest(**{
        **_study_payload(),
        "strategy": {"profile": "iron_composite", "require_native": True, "parameters": {
            "lookbacks": [2, 3],
            "curve_snapshots": snapshots,
            "trend_weight": 0.7,
            "carry_weight": 0.3,
        }},
    })
    runtime = build_strategy_runtime(request.strategy, request.base_request, [])
    orders = runtime.generate_orders(request.base_request.bars, trade_start=10, trade_end=40)

    assert runtime.evidence.native is True
    assert "carry.py" in runtime.evidence.dependencies
    assert "composite.py" in runtime.evidence.dependencies
    assert orders
    assert all(order.metadata["profile"] == "iron_composite" for order in orders)


def test_native_chain_auto_strategy_generates_next_bar_entries_with_atr_brackets():
    if not (Path.cwd().parent / "Sentinel-Chain").is_dir():
        pytest.skip("Sentinel-Chain sibling repository is required for the native integration test")
    import math

    base = _base_request(bot_id="chain", crypto=True)
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    base["bars"] = []
    for index in range(160):
        close = 5000 + math.sin(index / 2.5) * 120
        base["bars"].append({
            "timestamp": (start + timedelta(hours=index)).isoformat(),
            "symbol": "BTCUSDT",
            "open": close - math.cos(index) * 5,
            "high": close + 25,
            "low": close - 25,
            "close": close,
            "volume": 10_000,
        })
    from sentinel_archive.backtesting.models import DerivativesRunRequest

    request = DerivativesRunRequest(**base)
    config = ProfitabilityStrategyConfig(
        profile="chain_auto_structure",
        require_native=True,
        parameters={"fast_ema": 5, "slow_ema": 12, "quantity": 0.01, "max_bars": 12},
    )
    runtime = build_strategy_runtime(config, request, [])
    orders = runtime.generate_orders(request.bars, trade_start=40, trade_end=len(request.bars))
    entries = [order for order in orders if order.quantity > 0]

    assert runtime.evidence.native is True
    assert entries
    assert all(order.attached_stop_price and order.attached_target_price for order in entries)
    assert all(order.metadata["signal_bar"] < order.timestamp for order in entries)


def test_chain_recorded_signal_maps_leverage_staged_targets_trailing_and_time_exit():
    from sentinel_archive.backtesting.models import DerivativesRunRequest

    request = DerivativesRunRequest(**_base_request(bot_id="chain", crypto=True))
    config = ProfitabilityStrategyConfig(
        profile="chain_signal_replay",
        require_native=False,
        parameters={"signal_stream_complete": True},
    )
    signal = RecordedStrategySignal(
        timestamp=request.bars[10].timestamp,
        payload={
            "symbol": "BTCUSDT",
            "side": "buy",
            "base_amount": "0.01",
            "leverage": "3",
            "stop_loss_pct": "2",
            "take_profit_targets": [
                {"pct": "3", "close_pct": "50"},
                {"pct": "6", "close_pct": "50"},
            ],
            "trailing_stop_pct": "1",
            "trailing_activation_pct": "2",
            "max_hold_marks": 5,
        },
    )
    runtime = build_strategy_runtime(config, request, [signal])
    order = runtime.generate_orders(request.bars, trade_start=10, trade_end=40)[0]

    assert order.leverage == 3
    assert order.attached_stop_price is not None
    assert [target.close_fraction for target in order.attached_targets] == [0.5, 0.5]
    assert order.attached_trailing_percent == 1
    assert order.attached_trailing_activation_price is not None
    assert order.max_hold_bars == 5


def test_combination_routes_source_orders_through_native_risk_preflight():
    if not (Path.cwd().parent / "Sentinel-Iron").is_dir() or not (Path.cwd().parent / "Sentinel-Combination").is_dir():
        pytest.skip("Iron and Combination sibling repositories are required for the native integration test")
    from sentinel_archive.backtesting.models import DerivativesRunRequest

    request = DerivativesRunRequest(**_base_request(bot_id="combination"))
    config = ProfitabilityStrategyConfig(
        profile="combination_routed",
        require_native=True,
        parameters={
            "source_profile": "iron_trend",
            "source_parameters": {"lookbacks": [2, 3], "quantity": 1},
            "risk_limits": {
                "maximum_order_notional": 100,
                "maximum_position_notional": 100,
            },
        },
    )
    runtime = build_strategy_runtime(config, request, [])
    orders = runtime.generate_orders(request.bars, trade_start=10, trade_end=40)

    rejected = [order for order in orders if order.preflight_rejection_reason]
    assert runtime.evidence.native is True
    assert rejected
    assert all("order notional exceeds limit" in order.preflight_rejection_reason for order in rejected)
