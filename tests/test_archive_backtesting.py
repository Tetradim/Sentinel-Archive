from __future__ import annotations

import asyncio


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


def test_sweep_sorts_safe_profitable_reports_first():
    from sentinel_archive.backtesting.models import BacktestRunRequest, BacktestSweepRequest, MarketPriceBar
    from sentinel_archive.backtesting.service import run_sweep

    base = BacktestRunRequest(
        asset_class="crypto",
        symbol="BTCUSDT",
        quantity=1,
        starting_equity=1000,
        bars=[
            MarketPriceBar(
                timestamp="2026-07-01T00:00:00Z",
                symbol="BTCUSDT",
                open=100,
                high=115,
                low=98,
                close=112,
            ),
        ],
    )
    sweep = BacktestSweepRequest(
        base_request=base,
        take_profit_pcts=[5, 20],
        stop_loss_pcts=[2],
        leverage_values=[1, 50],
    )

    result = run_sweep(sweep)

    assert len(result.reports) == 4
    assert result.reports[0].metrics.safety_score >= result.reports[-1].metrics.safety_score


def test_walk_forward_stores_train_and_test_windows():
    from sentinel_archive.backtesting.models import BacktestRunRequest, BacktestWalkForwardRequest, MarketPriceBar
    from sentinel_archive.backtesting.service import run_walk_forward

    bars = [
        MarketPriceBar(
            timestamp=f"2026-07-01T00:0{i}:00Z",
            symbol="SPY",
            open=100 + i,
            high=101 + i,
            low=99 + i,
            close=100 + i,
        )
        for i in range(6)
    ]
    request = BacktestWalkForwardRequest(
        base_request=BacktestRunRequest(asset_class="stock", symbol="SPY", quantity=1, bars=bars),
        train_size=2,
        test_size=2,
        step_size=2,
    )

    result = run_walk_forward(request)

    assert len(result.windows) == 2
    assert result.windows[0].train_range.start == "2026-07-01T00:00:00Z"
    assert result.windows[0].test_range.start == "2026-07-01T00:02:00Z"


def test_backtest_store_saves_and_lists_runs(tmp_path):
    from sentinel_archive.backtesting.models import BacktestMetrics, BacktestReport, BacktestRunRecord
    from sentinel_archive.backtesting.store import BacktestStore

    async def scenario():
        store = BacktestStore(tmp_path / "archive.sqlite3")
        record = BacktestRunRecord(
            run_id="bt-test",
            created_at="2026-07-04T00:00:00Z",
            kind="run",
            asset_class="stock",
            symbol="SPY",
            fingerprint="abc",
            request={},
            report=BacktestReport(
                run_id="bt-test",
                asset_class="stock",
                symbol="SPY",
                metrics=BacktestMetrics(starting_equity=100, ending_equity=100),
                trades=[],
                warnings=[],
                assumptions={},
            ),
        )

        await store.save_run(record)
        return await store.list_runs()

    rows = asyncio.run(scenario())

    assert rows[0].run_id == "bt-test"


def test_backtest_exports_include_json_and_csv_rows():
    from sentinel_archive.backtesting.engines.stocks import run_stock_backtest
    from sentinel_archive.backtesting.exports import report_to_csv, report_to_json
    from sentinel_archive.backtesting.models import BacktestRunRequest, MarketPriceBar

    report = run_stock_backtest(
        BacktestRunRequest(
            asset_class="stock",
            symbol="SPY",
            quantity=1,
            bars=[
                MarketPriceBar(
                    timestamp="2026-07-01T13:30:00Z",
                    symbol="SPY",
                    open=100,
                    high=103,
                    low=99,
                    close=102,
                )
            ],
        )
    )

    assert report_to_json(report)["symbol"] == "SPY"
    assert "entry_price" in report_to_csv(report)


def test_repeated_backtest_records_keep_history_with_same_fingerprint():
    from sentinel_archive.backtesting.engines.stocks import run_stock_backtest
    from sentinel_archive.backtesting.models import BacktestRunRequest, MarketPriceBar
    from sentinel_archive.backtesting.service import create_run_record

    request = BacktestRunRequest(
        asset_class="stock",
        symbol="SPY",
        quantity=1,
        bars=[
            MarketPriceBar(
                timestamp="2026-07-01T13:30:00Z",
                symbol="SPY",
                open=100,
                high=103,
                low=99,
                close=102,
            )
        ],
    )

    first = create_run_record(request, run_stock_backtest(request))
    second = create_run_record(request, run_stock_backtest(request))

    assert first.fingerprint == second.fingerprint
    assert first.run_id != second.run_id
