from __future__ import annotations


def test_metric_summary_ranks_liquidation_warning_as_unsafe():
    from sentinel_archive.backtesting.metrics import summarize_trades
    from sentinel_archive.backtesting.models import BacktestTrade

    trade = BacktestTrade(
        symbol="BTCUSDT",
        side="long",
        quantity=1,
        entry_time="2026-07-01T00:00:00Z",
        entry_price=100,
        exit_time="2026-07-01T01:00:00Z",
        exit_price=110,
        pnl=10,
        fees=0,
        mae=-4,
        mfe=12,
        exit_reason="take_profit",
    )

    summary = summarize_trades(
        trades=[trade],
        starting_equity=1000,
        ending_equity=1010,
        equity_curve=[1000, 1010],
        warnings=["liquidation_before_stop"],
    )

    assert summary.win_rate == 1
    assert summary.profit_factor == 0
    assert summary.safety_score < 50
    assert "liquidation_before_stop" in summary.safety_flags
