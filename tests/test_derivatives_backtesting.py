from __future__ import annotations

import pytest

from sentinel_archive.backtesting.derivatives import run_derivatives_backtest
from sentinel_archive.backtesting.differential import run_differential_audit
from sentinel_archive.backtesting.models import DerivativesRunRequest, DifferentialAuditRequest


def _bar(minute: int, *, open_: float, high: float, low: float, close: float, volume: float = 1000) -> dict:
    return {
        "timestamp": f"2026-07-01T13:{minute:02d}:00Z",
        "symbol": "MES",
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


def _request(**updates) -> DerivativesRunRequest:
    payload = {
        "bot_id": "iron",
        "symbol": "MES",
        "quantity": 1,
        "starting_equity": 5000,
        "leverage": 10,
        "contract": {
            "symbol": "MES",
            "venue": "CME",
            "instrument_type": "listed_future",
            "contract_multiplier": 5,
            "tick_size": 0.25,
            "quantity_step": 1,
            "minimum_quantity": 1,
            "initial_margin_rate": 0.1,
            "maintenance_margin_rate": 0.08,
            "maximum_leverage": 20,
        },
        "bars": [
            _bar(30, open_=5000, high=5002, low=4998, close=5001),
            _bar(31, open_=5001, high=5005, low=4999, close=5004),
        ],
    }
    payload.update(updates)
    return DerivativesRunRequest(**payload)


def test_multiplier_tick_fees_and_commissions_are_applied():
    report = run_derivatives_backtest(
        _request(
            cost_model={
                "taker_fee_bps": 1,
                "commission_per_contract": 0.5,
                "exchange_fee_per_contract": 0.25,
            }
        )
    )

    assert report.executions[0].price % 0.25 == 0
    assert report.metrics.total_commissions == pytest.approx(1.0)
    assert report.metrics.total_exchange_fees == pytest.approx(0.5)
    assert report.metrics.ending_equity < 5020


def test_insufficient_margin_rejects_order_without_position():
    report = run_derivatives_backtest(_request(starting_equity=100, quantity=10))

    assert report.metrics.rejection_count == 1
    assert report.executions[0].reason == "insufficient_initial_margin"
    assert all(point.position_quantity == 0 for point in report.account_curve)


def test_volume_limit_creates_partial_fill_and_ioc_remainder():
    report = run_derivatives_backtest(
        _request(
            quantity=10,
            starting_equity=100_000,
            bars=[_bar(30, open_=5000, high=5002, low=4998, close=5001, volume=20)],
            execution_model={"maximum_volume_participation": 0.1},
        )
    )

    assert report.metrics.partial_fill_count == 1
    assert report.executions[0].filled_quantity == 2
    assert any(event.event_type == "unfilled" and event.remaining_quantity == 8 for event in report.executions)


def test_gap_liquidation_records_debt_and_liquidation_fee():
    report = run_derivatives_backtest(
        _request(
            starting_equity=3000,
            bars=[
                _bar(30, open_=5000, high=5001, low=4999, close=5000),
                _bar(31, open_=3000, high=3100, low=2500, close=2800),
            ],
            cost_model={"liquidation_fee_bps": 50},
        )
    )

    assert report.metrics.liquidation_count == 1
    assert report.metrics.potential_debt > 0
    assert report.metrics.total_liquidation_fees > 0
    assert {"liquidated", "potential_debt"} <= set(report.metrics.safety_flags)


def test_positive_funding_debits_long_and_credits_short():
    funding = [{"timestamp": "2026-07-01T13:31:00Z", "rate": 0.001, "mark_price": 5000}]
    long_report = run_derivatives_backtest(_request(funding_events=funding))
    short_report = run_derivatives_backtest(_request(side="short", funding_events=funding))

    assert long_report.metrics.total_funding > 0
    assert short_report.metrics.total_funding < 0
    assert long_report.metrics.ending_equity < short_report.metrics.ending_equity


def test_funding_before_position_entry_is_not_charged():
    report = run_derivatives_backtest(
        _request(funding_events=[{"timestamp": "2026-07-01T13:29:00Z", "rate": 0.5, "mark_price": 5000}])
    )

    assert report.metrics.total_funding == 0


def test_same_bar_policy_can_defer_ambiguous_stop_and_target():
    report = run_derivatives_backtest(
        _request(
            bars=[
                _bar(30, open_=5000, high=5000, low=5000, close=5000),
                _bar(31, open_=5000, high=5100, low=4900, close=5000),
                _bar(32, open_=5000, high=5002, low=4998, close=5000),
            ],
            stop_loss_pct=1,
            take_profit_pct=1,
            execution_model={"same_bar_policy": "reject_ambiguous"},
        )
    )

    assert "same_bar_ambiguity" in report.metrics.safety_flags
    assert "ambiguous_execution_deferred" in report.metrics.safety_flags
    assert any(event.reason == "final_close" for event in report.executions)


def test_replay_fingerprint_and_run_id_are_deterministic():
    first = run_derivatives_backtest(_request())
    second = run_derivatives_backtest(_request())

    assert first.fingerprint == second.fingerprint
    assert first.run_id == second.run_id
    assert first.executions == second.executions
    assert first.account_curve == second.account_curve


def test_gtc_limit_waits_for_a_later_bar_and_missing_price_is_rejected():
    waiting = run_derivatives_backtest(
        _request(
            orders=[
                {
                    "order_id": "wait-for-4990",
                    "timestamp": "2026-07-01T13:30:00Z",
                    "side": "long",
                    "order_type": "limit",
                    "limit_price": 4990,
                    "quantity": 1,
                    "time_in_force": "GTC",
                }
            ],
            bars=[
                _bar(30, open_=5000, high=5002, low=4998, close=5001),
                _bar(31, open_=4995, high=4996, low=4988, close=4990),
            ],
        )
    )
    assert waiting.executions[0].event_type == "filled"
    assert waiting.executions[0].timestamp == "2026-07-01T13:31:00Z"

    rejected = run_derivatives_backtest(
        _request(orders=[{"order_id": "bad-limit", "side": "long", "order_type": "limit", "quantity": 1}])
    )
    assert rejected.executions[0].reason == "missing_limit_price"


def test_target_orders_rebalance_flatten_and_reenter_after_a_stop():
    report = run_derivatives_backtest(
        _request(
            bars=[
                _bar(30, open_=5000, high=5001, low=5000, close=5001),
                _bar(31, open_=5001, high=5002, low=4940, close=4950),
                _bar(32, open_=4950, high=4960, low=4945, close=4955),
                _bar(33, open_=4955, high=4970, low=4950, close=4968),
            ],
            stop_loss_pct=1,
            orders=[
                {"order_id": "long-1", "timestamp": "2026-07-01T13:30:00Z", "action": "target", "side": "long", "quantity": 1},
                {"order_id": "long-2", "timestamp": "2026-07-01T13:31:00Z", "action": "target", "side": "long", "quantity": 1},
                {"order_id": "long-3", "timestamp": "2026-07-01T13:32:00Z", "action": "target", "side": "long", "quantity": 1},
                {"order_id": "flat", "timestamp": "2026-07-01T13:33:00Z", "action": "target", "side": "long", "quantity": 0},
            ],
        )
    )

    reasons = [event.reason for event in report.executions if event.event_type == "position_closed"]
    assert "stop_loss" in reasons
    assert "strategy_target_flat" in reasons
    assert sum(1 for event in report.executions if event.event_type == "filled") == 2
    assert any(event.event_type == "target_unchanged" for event in report.executions)


def test_target_reversal_closes_then_opens_the_opposite_side():
    report = run_derivatives_backtest(
        _request(
            orders=[
                {"order_id": "long", "timestamp": "2026-07-01T13:30:00Z", "action": "target", "side": "long", "quantity": 1},
                {"order_id": "short", "timestamp": "2026-07-01T13:31:00Z", "action": "target", "side": "short", "quantity": 1},
            ]
        )
    )

    assert any(event.reason == "strategy_target_rebalance" for event in report.executions)
    fills = [event for event in report.executions if event.event_type == "filled"]
    assert [event.side for event in fills] == ["long", "short"]
    assert "target_rebalances_use_full_close_and_reopen" in report.warnings


def test_target_order_attached_bracket_overrides_global_bracket():
    report = run_derivatives_backtest(
        _request(
            take_profit_pct=50,
            orders=[
                {
                    "order_id": "native-bracket",
                    "timestamp": "2026-07-01T13:30:00Z",
                    "action": "target",
                    "side": "long",
                    "quantity": 1,
                    "attached_stop_price": 4990,
                    "attached_target_price": 5004,
                }
            ],
        )
    )

    close = next(event for event in report.executions if event.event_type == "position_closed")
    assert close.reason == "take_profit"
    assert close.price == 5004
    fill = next(event for event in report.executions if event.event_type == "filled")
    assert fill.metadata["attached_target_price"] == 5004


def test_attached_multi_target_bracket_reduces_position_in_slices():
    report = run_derivatives_backtest(
        _request(
            quantity=4,
            starting_equity=100_000,
            bars=[
                _bar(30, open_=5000, high=5001, low=4999, close=5000),
                _bar(31, open_=5000, high=5012, low=4998, close=5010),
                _bar(32, open_=5010, high=5011, low=5008, close=5010),
            ],
            orders=[
                {
                    "order_id": "multi-target",
                    "timestamp": "2026-07-01T13:30:00Z",
                    "action": "target",
                    "side": "long",
                    "quantity": 4,
                    "attached_stop_price": 4950,
                    "attached_targets": [
                        {"price": 5005, "close_fraction": 0.25},
                        {"price": 5010, "close_fraction": 0.5},
                    ],
                }
            ],
        )
    )

    reductions = [event for event in report.executions if event.event_type == "position_reduced"]
    assert [event.filled_quantity for event in reductions] == [1, 2]
    final = next(event for event in report.executions if event.reason == "final_close")
    assert final.filled_quantity == 1


def test_attached_time_exit_and_trailing_activation_are_respected():
    timed = run_derivatives_backtest(
        _request(
            bars=[
                _bar(30, open_=5000, high=5005, low=4995, close=5001),
                _bar(31, open_=5002, high=5100, low=4900, close=5000),
            ],
            orders=[{
                "order_id": "timed",
                "timestamp": "2026-07-01T13:30:00Z",
                "action": "target",
                "side": "long",
                "quantity": 1,
                "max_hold_bars": 1,
            }],
        )
    )
    assert any(event.reason == "time_exit" and event.price == 5002 for event in timed.executions)

    activation = run_derivatives_backtest(
        _request(
            bars=[
                _bar(30, open_=5000, high=5005, low=4995, close=5001),
                _bar(31, open_=5001, high=5050, low=4900, close=5000),
            ],
            orders=[{
                "order_id": "activation",
                "timestamp": "2026-07-01T13:30:00Z",
                "action": "target",
                "side": "long",
                "quantity": 1,
                "attached_trailing_percent": 1,
                "attached_trailing_activation_price": 5100,
            }],
        )
    )
    assert not any(event.reason == "trailing_stop" for event in activation.executions)
    assert any(event.reason == "final_close" for event in activation.executions)


def test_differential_audit_reports_parity_and_divergence():
    base = _request(orders=[])
    same_order = {
        "order_id": "entry",
        "timestamp": "2026-07-01T13:30:00Z",
        "side": "long",
        "quantity": 1,
        "order_type": "market",
    }
    audit = run_differential_audit(
        DifferentialAuditRequest(
            name="Iron Chain Combination",
            base_request=base,
            layers=[
                {"layer_id": "iron", "label": "Iron", "bot_id": "iron", "orders": [same_order]},
                {"layer_id": "combination", "label": "Combination", "bot_id": "combination", "orders": [same_order]},
            ],
        )
    )
    assert audit.combined_assessment["verdict"] == "parity_observed"

    divergent = run_differential_audit(
        DifferentialAuditRequest(
            name="Divergent",
            base_request=base,
            layers=[
                {"layer_id": "iron", "label": "Iron", "bot_id": "iron", "orders": [same_order]},
                {
                    "layer_id": "chain",
                    "label": "Chain",
                    "bot_id": "chain",
                    "orders": [{**same_order, "side": "short"}],
                },
            ],
        )
    )
    assert divergent.combined_assessment["verdict"] == "investigate_divergence"
    assert any(item.severity == "critical" for item in divergent.divergences)
