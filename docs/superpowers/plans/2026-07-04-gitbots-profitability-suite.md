# GitBots Profitability Suite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the backend-first Archive profitability suite: modular backtest engines, saved run history, selective bot-suite run plans, APIs, exports, and tests.

**Architecture:** Sentinel Archive owns the canonical backend model. Backtesting engines live under `sentinel_archive/backtesting`, bot-suite planning lives under `sentinel_archive/bot_suite`, and both persist to the existing local SQLite database path. The UI is deferred until the backend contract is stable.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, aiosqlite, pytest, FastAPI TestClient.

---

## File Structure

- Create `sentinel_archive/backtesting/models.py`: Pydantic request, report, trade, metric, sweep, walk-forward, and export models.
- Create `sentinel_archive/backtesting/metrics.py`: equity curve, drawdown, profit factor, and safe-vs-unsafe score helpers.
- Create `sentinel_archive/backtesting/engines/crypto.py`: isolated Chain-style crypto candle backtest with fees, slippage, funding, leverage, MAE/MFE, and liquidation warnings.
- Create `sentinel_archive/backtesting/engines/stocks.py`: stock bar backtest over Archive-style bars with stops, targets, trailing, DCA extension points, and slippage.
- Create `sentinel_archive/backtesting/engines/options.py`: Echo-style options alert replay with explicit fill assumptions and missing quote coverage warnings.
- Create `sentinel_archive/backtesting/service.py`: run, sweep, stress, and walk-forward orchestration.
- Create `sentinel_archive/backtesting/store.py`: SQLite saved backtest run history.
- Create `sentinel_archive/backtesting/exports.py`: JSON and CSV export payload builders.
- Create `sentinel_archive/backtesting/router.py`: `/api/archive/backtest/...` FastAPI router.
- Create `sentinel_archive/bot_suite/models.py`: selective plan, job, run, budget, and artifact models.
- Create `sentinel_archive/bot_suite/planner.py`: expands selected bots and test families into concrete jobs; rejects live execution.
- Create `sentinel_archive/bot_suite/registry.py`: known GitBots repo paths and supported test families.
- Create `sentinel_archive/bot_suite/store.py`: SQLite saved suite plans and suite runs.
- Create `sentinel_archive/bot_suite/router.py`: `/api/archive/bot-suite/...` FastAPI router.
- Modify `sentinel_archive/api.py`: instantiate and initialize new stores and include both routers under `/api`.
- Create `tests/test_archive_backtesting.py`: unit tests for engines, metrics, sweeps, walk-forward, and exports.
- Create `tests/test_archive_backtest_api.py`: API persistence and export tests.
- Create `tests/test_bot_suite_planner.py`: planner, profiles, budget, and no-live-execution tests.
- Create `tests/test_bot_suite_api.py`: suite plan/run API tests.

## Task 1: Backtesting Models and Metrics

**Files:**
- Create: `sentinel_archive/backtesting/__init__.py`
- Create: `sentinel_archive/backtesting/models.py`
- Create: `sentinel_archive/backtesting/metrics.py`
- Test: `tests/test_archive_backtesting.py`

- [ ] **Step 1: Write failing model and metric tests**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_archive_backtesting.py::test_metric_summary_ranks_liquidation_warning_as_unsafe -q`

Expected: FAIL with `ModuleNotFoundError` for `sentinel_archive.backtesting`.

- [ ] **Step 3: Implement models and metrics**

Create Pydantic models for bars, cost model, strategy inputs, trades, metrics, reports, run records, sweep requests, walk-forward requests, and stress requests. Implement `summarize_trades()` to calculate win rate, gross profit/loss, profit factor, return percent, max drawdown, MAE, MFE, fees, and a deterministic safety score.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_archive_backtesting.py::test_metric_summary_ranks_liquidation_warning_as_unsafe -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sentinel_archive/backtesting/__init__.py sentinel_archive/backtesting/models.py sentinel_archive/backtesting/metrics.py tests/test_archive_backtesting.py
git commit -m "feat: add archive backtest models and metrics"
```

## Task 2: Crypto, Stock, and Options Engines

**Files:**
- Create: `sentinel_archive/backtesting/engines/__init__.py`
- Create: `sentinel_archive/backtesting/engines/crypto.py`
- Create: `sentinel_archive/backtesting/engines/stocks.py`
- Create: `sentinel_archive/backtesting/engines/options.py`
- Test: `tests/test_archive_backtesting.py`

- [ ] **Step 1: Write failing crypto engine test**

```python
def test_crypto_backtest_tracks_costs_excursions_and_liquidation_warning():
    from sentinel_archive.backtesting.engines.crypto import run_crypto_backtest
    from sentinel_archive.backtesting.models import BacktestRunRequest, MarketPriceBar, BacktestCostModel

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
            MarketPriceBar(timestamp="2026-07-01T00:00:00Z", symbol="BTCUSDT", open=100, high=112, low=96, close=108),
        ],
    )

    report = run_crypto_backtest(request)

    assert report.metrics.trade_count == 1
    assert report.metrics.total_fees > 0
    assert report.metrics.mfe > 0
    assert report.metrics.mae < 0
    assert "liquidation_before_stop" in report.metrics.safety_flags
```

- [ ] **Step 2: Write failing stock and options tests**

```python
def test_stock_backtest_exits_on_take_profit_with_slippage():
    from sentinel_archive.backtesting.engines.stocks import run_stock_backtest
    from sentinel_archive.backtesting.models import BacktestRunRequest, MarketPriceBar, BacktestCostModel

    request = BacktestRunRequest(
        asset_class="stock",
        symbol="SPY",
        quantity=10,
        starting_equity=10000,
        take_profit_pct=3,
        cost_model=BacktestCostModel(slippage_bps=10),
        bars=[
            MarketPriceBar(timestamp="2026-07-01T13:30:00Z", symbol="SPY", open=100, high=104, low=99, close=103),
        ],
    )

    report = run_stock_backtest(request)

    assert report.trades[0].exit_reason == "take_profit"
    assert report.metrics.trade_count == 1


def test_options_replay_flags_missing_quote_coverage():
    from sentinel_archive.backtesting.engines.options import run_options_replay
    from sentinel_archive.backtesting.models import BacktestRunRequest, OptionAlert

    request = BacktestRunRequest(
        asset_class="options",
        symbol="SPY",
        starting_equity=5000,
        option_alerts=[
            OptionAlert(timestamp="2026-07-01T14:00:00Z", contract_key="SPY-20260717-500-C", action="buy", quantity=1),
        ],
        option_quotes=[],
    )

    report = run_options_replay(request)

    assert report.metrics.trade_count == 0
    assert "missing_quote_coverage" in report.metrics.safety_flags
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_archive_backtesting.py -q`

Expected: FAIL with missing engine modules or functions.

- [ ] **Step 4: Implement minimal engines**

Implement isolated, pure engine functions. Crypto and stock use adverse-first candle checks for stop/target. Options replay sorts alerts and quotes by timestamp, uses explicit fill assumptions, and records warnings when quotes are missing.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_archive_backtesting.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add sentinel_archive/backtesting/engines tests/test_archive_backtesting.py
git commit -m "feat: add archive backtest engines"
```

## Task 3: Backtest Service, Sweeps, Walk-Forward, Stress, Store, and Exports

**Files:**
- Create: `sentinel_archive/backtesting/service.py`
- Create: `sentinel_archive/backtesting/store.py`
- Create: `sentinel_archive/backtesting/exports.py`
- Test: `tests/test_archive_backtesting.py`

- [ ] **Step 1: Write failing orchestration tests**

```python
def test_sweep_sorts_safe_profitable_reports_first():
    from sentinel_archive.backtesting.service import run_sweep
    from sentinel_archive.backtesting.models import BacktestRunRequest, BacktestSweepRequest, MarketPriceBar

    base = BacktestRunRequest(
        asset_class="crypto",
        symbol="BTCUSDT",
        quantity=1,
        starting_equity=1000,
        bars=[
            MarketPriceBar(timestamp="2026-07-01T00:00:00Z", symbol="BTCUSDT", open=100, high=115, low=98, close=112),
        ],
    )
    sweep = BacktestSweepRequest(base_request=base, take_profit_pcts=[5, 20], stop_loss_pcts=[2], leverage_values=[1, 50])

    result = run_sweep(sweep)

    assert result.reports[0].metrics.safety_score >= result.reports[-1].metrics.safety_score


def test_walk_forward_stores_train_and_test_windows():
    from sentinel_archive.backtesting.service import run_walk_forward
    from sentinel_archive.backtesting.models import BacktestRunRequest, BacktestWalkForwardRequest, MarketPriceBar

    bars = [
        MarketPriceBar(timestamp=f"2026-07-01T00:0{i}:00Z", symbol="SPY", open=100 + i, high=101 + i, low=99 + i, close=100 + i)
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
```

- [ ] **Step 2: Write failing store/export tests**

```python
def test_backtest_store_saves_and_lists_runs(tmp_path):
    import asyncio
    from sentinel_archive.backtesting.store import BacktestStore
    from sentinel_archive.backtesting.models import BacktestRunRecord, BacktestReport, BacktestMetrics

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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_archive_backtesting.py -q`

Expected: FAIL with missing service/store/export modules.

- [ ] **Step 4: Implement service, SQLite store, and exports**

Add run dispatch by `asset_class`, sweep variant generation, stress scenario execution, walk-forward windowing, deterministic fingerprints from canonical JSON, saved run records, JSON export, and CSV trade export.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_archive_backtesting.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add sentinel_archive/backtesting/service.py sentinel_archive/backtesting/store.py sentinel_archive/backtesting/exports.py tests/test_archive_backtesting.py
git commit -m "feat: add backtest orchestration and persistence"
```

## Task 4: Backtest API Router

**Files:**
- Create: `sentinel_archive/backtesting/router.py`
- Modify: `sentinel_archive/api.py`
- Test: `tests/test_archive_backtest_api.py`

- [ ] **Step 1: Write failing API tests**

```python
from fastapi.testclient import TestClient

from sentinel_archive.api import create_app


def test_archive_backtest_api_creates_lists_and_exports_run(tmp_path):
    client = TestClient(create_app(recorder_db_path=tmp_path / "archive.sqlite3"))

    response = client.post(
        "/api/archive/backtest/runs",
        json={
            "asset_class": "stock",
            "symbol": "SPY",
            "quantity": 1,
            "bars": [
                {"timestamp": "2026-07-01T13:30:00Z", "symbol": "SPY", "open": 100, "high": 105, "low": 99, "close": 104}
            ],
            "take_profit_pct": 3,
        },
    )

    assert response.status_code == 200
    run_id = response.json()["run_id"]
    assert client.get("/api/archive/backtest/runs").json()["runs"][0]["run_id"] == run_id
    assert client.get(f"/api/archive/backtest/runs/{run_id}/export.json").json()["run_id"] == run_id
    assert "entry_price" in client.get(f"/api/archive/backtest/runs/{run_id}/export.csv").text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_archive_backtest_api.py -q`

Expected: FAIL with 404 for `/api/archive/backtest/runs`.

- [ ] **Step 3: Implement router and include it in `create_app()`**

Create `create_backtest_router(store: BacktestStore)`. Include it in `create_app()` with prefix `/api`. Initialize the store in lifespan and lazily inside store methods for TestClient usage.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_archive_backtest_api.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sentinel_archive/backtesting/router.py sentinel_archive/api.py tests/test_archive_backtest_api.py
git commit -m "feat: expose archive backtest API"
```

## Task 5: Bot-Suite Planner, Registry, Store, and API

**Files:**
- Create: `sentinel_archive/bot_suite/__init__.py`
- Create: `sentinel_archive/bot_suite/models.py`
- Create: `sentinel_archive/bot_suite/registry.py`
- Create: `sentinel_archive/bot_suite/planner.py`
- Create: `sentinel_archive/bot_suite/store.py`
- Create: `sentinel_archive/bot_suite/router.py`
- Modify: `sentinel_archive/api.py`
- Test: `tests/test_bot_suite_planner.py`
- Test: `tests/test_bot_suite_api.py`

- [ ] **Step 1: Write failing planner tests**

```python
def test_plan_expands_only_selected_bots_and_test_families():
    from sentinel_archive.bot_suite.planner import build_suite_plan
    from sentinel_archive.bot_suite.models import SuitePlanRequest

    plan = build_suite_plan(
        SuitePlanRequest(
            name="focused crypto",
            bots=["chain"],
            test_families=["crypto_backtest"],
            assets=["BTCUSDT"],
            compute_budget={"max_jobs": 5},
        )
    )

    assert [job.bot_id for job in plan.jobs] == ["chain"]
    assert [job.test_family for job in plan.jobs] == ["crypto_backtest"]


def test_full_regression_requires_explicit_profile():
    from sentinel_archive.bot_suite.planner import build_suite_plan
    from sentinel_archive.bot_suite.models import SuitePlanRequest

    targeted = build_suite_plan(SuitePlanRequest(name="targeted", bots=["chain"], test_families=["crypto_backtest"]))
    full = build_suite_plan(SuitePlanRequest(name="full", profile="all-bots/full-regression"))

    assert len(targeted.jobs) < len(full.jobs)
    assert {job.bot_id for job in full.jobs} >= {"chain", "edge", "pulse", "echo"}


def test_live_execution_is_rejected():
    import pytest
    from sentinel_archive.bot_suite.planner import build_suite_plan
    from sentinel_archive.bot_suite.models import SuitePlanRequest

    with pytest.raises(ValueError, match="live execution"):
        build_suite_plan(SuitePlanRequest(name="bad", bots=["chain"], test_families=["crypto_backtest"], allow_live_execution=True))
```

- [ ] **Step 2: Write failing API tests**

```python
from fastapi.testclient import TestClient

from sentinel_archive.api import create_app


def test_bot_suite_api_saves_plan_and_runs_selected_jobs(tmp_path):
    client = TestClient(create_app(recorder_db_path=tmp_path / "archive.sqlite3"))

    created = client.post(
        "/api/archive/bot-suite/plans",
        json={"name": "pulse health", "bots": ["pulse"], "test_families": ["replay_health"], "compute_budget": {"max_jobs": 2}},
    )

    assert created.status_code == 200
    plan_id = created.json()["plan_id"]
    run = client.post(f"/api/archive/bot-suite/plans/{plan_id}/run")

    assert run.status_code == 200
    assert run.json()["plan_id"] == plan_id
    assert {job["bot_id"] for job in run.json()["jobs"]} == {"pulse"}
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_bot_suite_planner.py tests/test_bot_suite_api.py -q`

Expected: FAIL with missing `sentinel_archive.bot_suite`.

- [ ] **Step 4: Implement planner, registry, store, router, and API wiring**

Implement known GitBots paths, supported family validation, full-regression profile expansion, compute budget enforcement, skipped reasons for unavailable repos, deterministic fingerprints, saved plans, saved suite runs, and `/api/archive/bot-suite/...` routes.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_bot_suite_planner.py tests/test_bot_suite_api.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add sentinel_archive/bot_suite sentinel_archive/api.py tests/test_bot_suite_planner.py tests/test_bot_suite_api.py
git commit -m "feat: add selective bot suite planner"
```

## Task 6: Regression Verification

**Files:**
- Modify: no production files unless tests reveal a bug.

- [ ] **Step 1: Run focused tests**

Run: `pytest tests/test_archive_backtesting.py tests/test_archive_backtest_api.py tests/test_bot_suite_planner.py tests/test_bot_suite_api.py -q`

Expected: PASS.

- [ ] **Step 2: Run existing Archive test suite**

Run: `pytest -q`

Expected: PASS.

- [ ] **Step 3: Run frontend build only if backend route wiring affected static fallback**

Run: `npm run build`

Expected: PASS.

- [ ] **Step 4: Commit verification fixes if needed**

```bash
git add sentinel_archive tests
git commit -m "fix: stabilize archive profitability suite"
```
