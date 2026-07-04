from __future__ import annotations

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
                {
                    "timestamp": "2026-07-01T13:30:00Z",
                    "symbol": "SPY",
                    "open": 100,
                    "high": 105,
                    "low": 99,
                    "close": 104,
                }
            ],
            "take_profit_pct": 3,
        },
    )

    assert response.status_code == 200
    run_id = response.json()["run_id"]
    assert client.get("/api/archive/backtest/runs").json()["runs"][0]["run_id"] == run_id
    assert client.get(f"/api/archive/backtest/runs/{run_id}/export.json").json()["run_id"] == run_id
    assert "entry_price" in client.get(f"/api/archive/backtest/runs/{run_id}/export.csv").text


def test_archive_backtest_api_saves_sweep_and_walk_forward_history(tmp_path):
    client = TestClient(create_app(recorder_db_path=tmp_path / "archive.sqlite3"))
    base_request = {
        "asset_class": "stock",
        "symbol": "SPY",
        "quantity": 1,
        "bars": [
            {"timestamp": "2026-07-01T13:30:00Z", "symbol": "SPY", "open": 100, "high": 101, "low": 99, "close": 100},
            {"timestamp": "2026-07-01T13:31:00Z", "symbol": "SPY", "open": 101, "high": 102, "low": 100, "close": 101},
            {"timestamp": "2026-07-01T13:32:00Z", "symbol": "SPY", "open": 102, "high": 104, "low": 101, "close": 103},
            {"timestamp": "2026-07-01T13:33:00Z", "symbol": "SPY", "open": 103, "high": 105, "low": 102, "close": 104},
        ],
    }

    sweep = client.post(
        "/api/archive/backtest/sweeps",
        json={"base_request": base_request, "take_profit_pcts": [1, 2], "stop_loss_pcts": [1], "leverage_values": [1]},
    )
    walk_forward = client.post(
        "/api/archive/backtest/walk-forward",
        json={"base_request": base_request, "train_size": 1, "test_size": 1, "step_size": 1},
    )

    assert sweep.status_code == 200
    assert walk_forward.status_code == 200
    run_kinds = {run["kind"] for run in client.get("/api/archive/backtest/runs").json()["runs"]}
    assert {"sweep", "walk_forward"} <= run_kinds
