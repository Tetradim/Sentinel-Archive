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
