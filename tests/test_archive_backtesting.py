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


def test_crypto_backtest_tracks_costs_excursions_and_liquidation_warning():
    from sentinel_archive.backtesting.engines.crypto import run_crypto_backtest
    from sentinel_archive.backtesting.models import BacktestCostModel, BacktestRunRequest, MarketPriceBar

    request = BacktestRunRequest(
        asset_class="crypto",
        symbol="BTCUSDT",
        side="long",
        quantity=1,
        starting_equity=1000,
        leverage=25,
        stop_loss_pct=5,
        take_profit_pct=10,
        close_final_position=True,
        cost_model=BacktestCostModel(fee_bps=10, slippage_bps=5, funding_bps_per_step=1),
        bars=[
            MarketPriceBar(
                timestamp="2026-07-01T00:00:00Z",
                symbol="BTCUSDT",
                open=100,
                high=112,
                low=96,
                close=108,
            ),
        ],
    )

    report = run_crypto_backtest(request)

    assert report.metrics.trade_count == 1
    assert report.metrics.total_fees > 0
    assert report.metrics.funding > 0
    assert report.metrics.mfe > 0
    assert report.metrics.mae < 0
    assert "liquidation_before_stop" in report.metrics.safety_flags


def test_stock_backtest_exits_on_take_profit_with_slippage():
    from sentinel_archive.backtesting.engines.stocks import run_stock_backtest
    from sentinel_archive.backtesting.models import BacktestCostModel, BacktestRunRequest, MarketPriceBar

    request = BacktestRunRequest(
        asset_class="stock",
        symbol="SPY",
        quantity=10,
        starting_equity=10000,
        take_profit_pct=3,
        cost_model=BacktestCostModel(slippage_bps=10),
        bars=[
            MarketPriceBar(
                timestamp="2026-07-01T13:30:00Z",
                symbol="SPY",
                open=100,
                high=104,
                low=99,
                close=103,
            ),
        ],
    )

    report = run_stock_backtest(request)

    assert report.trades[0].exit_reason == "take_profit"
    assert report.metrics.trade_count == 1
    assert report.metrics.slippage > 0


def test_options_replay_flags_missing_quote_coverage():
    from sentinel_archive.backtesting.engines.options import run_options_replay
    from sentinel_archive.backtesting.models import BacktestRunRequest, OptionAlert

    request = BacktestRunRequest(
        asset_class="options",
        symbol="SPY",
        starting_equity=5000,
        option_alerts=[
            OptionAlert(
                timestamp="2026-07-01T14:00:00Z",
                contract_key="SPY-20260717-500-C",
                action="buy",
                quantity=1,
            ),
        ],
        option_quotes=[],
    )

    report = run_options_replay(request)

    assert report.metrics.trade_count == 0
    assert "missing_quote_coverage" in report.metrics.safety_flags
